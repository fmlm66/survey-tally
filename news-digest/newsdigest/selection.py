"""주제별로 기사 고르기: 기간 → 중복 → 본문 길이 재기 → 같은 소식 묶기 → 본문 긴 순."""

from __future__ import annotations

import re
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable
from urllib.parse import urlsplit

from .article import parse_article
from .feeds import Article, fetch_page
from .scoring import final_score, is_opinion, pre_score, settings
from .summarize import clean_text, summarize

SIMILAR = 0.45
MIN_BIGRAMS = 4  # 이보다 짧은 제목은 비교하지 않는다
_NON_WORD = re.compile(r"[^0-9A-Za-z가-힣぀-ヿ一-鿿]")  # 한글·영숫자·일본어·한자


def normalize_link(link: str) -> str:
    parts = urlsplit(link.strip())
    host = parts.netloc.lower().removeprefix("www.")
    path = parts.path.rstrip("/")
    return f"{host}{path}?{parts.query}" if parts.query else f"{host}{path}"


def bigrams(title: str) -> set[str]:
    s = _NON_WORD.sub("", clean_text(title).lower())
    return {s[i:i + 2] for i in range(len(s) - 1)} if len(s) > 1 else {s}


_TOKEN = re.compile(r"[가-힣A-Za-z0-9]+")
_PARTICLES = ("에서", "에게", "으로", "까지", "부터", "에는", "에도", "이다", "에", "은", "는", "이", "가", "을", "를",
              "의", "도", "로", "와", "과", "만")
_STOP = {"종합", "속보", "단독", "영상", "포토", "정부", "오늘", "내일", "이유", "관련", "위해", "대한", "통해", "이번",
         "올해", "내년", "기자", "뉴스", "사진", "1보", "2보", "3보"}
MIN_SHARED_WORDS = 3     # 이만큼 핵심 낱말이 겹치면 같은 소식
SHARED_WORDS_RATIO = 0.3  # (짧은 제목 낱말 수 대비)


def keywords(title: str) -> set[str]:
    """제목의 핵심 낱말(두 글자 이상, 흔한 조사·낱말 제외)."""
    out = set()
    for tok in _TOKEN.findall(clean_text(title)):
        if re.fullmatch(r"[가-힣]+", tok) and len(tok) >= 3:
            for p in _PARTICLES:
                if tok.endswith(p) and len(tok) - len(p) >= 2:
                    tok = tok[: -len(p)]
                    break
        tok = tok.lower()
        if len(tok) >= 2 and tok not in _STOP:
            out.add(tok)
    return out


def _same_story(x: tuple[set[str], set[str]], y: tuple[set[str], set[str]]) -> bool:
    """글자 2개 묶음이 많이 겹치거나(표현이 비슷), 핵심 낱말이 3개 이상 겹치면(표현이 달라도) 같은 소식."""
    (bx, kx), (by, ky) = x, y
    if min(len(bx), len(by)) >= MIN_BIGRAMS and len(bx & by) / min(len(bx), len(by)) >= SIMILAR:
        return True
    if min(len(bx), len(by)) < MIN_BIGRAMS and bx == by and bx:
        return True
    shared = len(kx & ky)
    return shared >= MIN_SHARED_WORDS and shared / max(min(len(kx), len(ky)), 1) >= SHARED_WORDS_RATIO


def similarity(a: str, b: str) -> float:
    """겹치는 글자 2개 묶음 ÷ 짧은 제목의 묶음 수. 언론사마다 제목 길이가 달라도 같은 소식을 잡는다."""
    x, y = bigrams(a), bigrams(b)
    if min(len(x), len(y)) < MIN_BIGRAMS:
        return 1.0 if x == y and x else 0.0
    return len(x & y) / min(len(x), len(y))


@dataclass
class TopicStats:
    total: int = 0       # RSS에서 읽은 기사
    in_window: int = 0   # 기간 안(중복 제외)
    measured: int = 0    # 기사 페이지를 연 수
    with_body: int = 0   # 본문 글자 수를 읽은 수
    selected: int = 0


def measure_pages(articles: list[Article], fetcher: Callable[[str], str] = fetch_page, workers: int = 8,
                  per_host: int = 2) -> None:
    """기사 페이지를 동시에 열어 본문 글자 수·소개문·발행 시각을 채운다. 이미 잰 기사는 건너뛴다."""
    todo = [a for a in articles if not a.measured]
    hosts: dict[str, threading.Semaphore] = {}
    for a in todo:
        hosts.setdefault(urlsplit(a.link).netloc.lower(), threading.Semaphore(per_host))

    def one(a: Article) -> None:
        try:
            with hosts[urlsplit(a.link).netloc.lower()]:  # 한 사이트에 동시에 per_host건까지만
                html = fetcher(a.link)
            info = parse_article(html)
        except Exception:  # noqa: BLE001 — 열지 못한 기사는 본문 없음으로
            a.measured = True
            return
        a.measured = True
        a.body_chars = info.body_chars
        a.page_desc = info.description
        if a.published is None and info.published is not None:
            a.published = info.published

    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(one, todo))


def group_similar(articles: list[Article]) -> list[list[Article]]:
    """같은 소식끼리 묶는다(묶음 안 어느 기사와든 같은 소식이면 같은 묶음)."""
    keys = {id(a): (bigrams(a.title), keywords(a.title)) for a in articles}
    groups: list[list[Article]] = []
    for a in articles:
        ka = keys[id(a)]
        for g in groups:
            if any(_same_story(ka, keys[id(b)]) for b in g):
                g.append(a)
                break
        else:
            groups.append([a])
    return groups


def select(articles: list[Article], config: dict, now: datetime,
           measure: Callable[[list[Article]], None] = measure_pages,
           headlines: frozenset[str] = frozenset()) -> tuple[dict[str, list[Article]], dict[str, TopicStats]]:
    """headlines: 언론사 주요뉴스 RSS에 실린 기사 주소(normalize_link)."""
    sc = settings(config)
    topics = [t["name"] for t in config["topics"]]
    hours = config.get("window_hours", 24)
    per_topic = config.get("per_topic", 5)
    max_fetch = config.get("max_fetch_per_topic", 60)
    undated_ok = {name for name, opt in config.get("sources", {}).items() if opt.get("undated") == "recent"}
    start = now - timedelta(hours=hours)
    skip_titles = [re.compile(p) for p in config.get("exclude_titles", [])]

    def in_window(a: Article) -> bool:
        if a.published is None:
            return a.source in undated_ok
        return start <= a.published <= now  # 기준 시각 뒤 기사는 다음 실행에서 잡힌다

    stats = {t: TopicStats() for t in topics}
    pools: dict[str, list[Article]] = {t: [] for t in topics}
    seen: set[str] = set()
    for topic in topics:  # 설정 순서대로: 여러 주제에 실린 기사는 앞 주제에
        for a in (x for x in articles if x.topic == topic):
            stats[topic].total += 1
            key = normalize_link(a.link)
            if key in seen or not in_window(a) or any(p.search(clean_text(a.title)) for p in skip_titles):
                continue
            seen.add(key)
            pools[topic].append(a)
        stats[topic].in_window = len(pools[topic])

    # 저장 파일로 다시 만들 때 재지 않았던 기사(dump:// 자리)는 제목이 없어 통계에만 센다
    real = {t: [a for a in pools[t] if not a.link.startswith("dump://")] for t in topics}

    # 1) 모든 주제를 통틀어 같은 소식을 묶고, 묶음마다 보도한 언론사를 센다
    # 한 소식은 기사가 가장 많이 실린 주제 하나에만 싣는다(같으면 설정에서 앞선 주제)
    story_sources: dict[int, list[str]] = {}
    story_of: dict[int, int] = {}
    home: dict[int, str] = {}
    for gi, g in enumerate(group_similar([a for t in topics for a in real[t]])):
        sources = list(dict.fromkeys(a.source for a in g))
        counts = {t: sum(1 for a in g if a.topic == t) for t in topics}
        home[gi] = max(topics, key=lambda t: (counts[t], -topics.index(t)))
        for a in g:
            story_sources[id(a)] = sources
            story_of[id(a)] = gi

    # 2) 1차 점수(제목·요약문)로 잴 기사를 고른다
    pre = {id(a): pre_score(a, len(story_sources[id(a)]), normalize_link(a.link) in headlines, sc)
           for t in topics for a in real[t]}

    def recency(a: Article) -> float:
        return (a.published or now).timestamp()

    plans = {t: sorted(real[t], key=lambda a: (pre[id(a)].points, recency(a)), reverse=True)[:max_fetch] for t in topics}
    measure([a for t in topics for a in plans[t]])

    # 3) 최종 점수와 고르기
    measured_ok: list[Article] = []
    for topic in topics:
        ok = [a for a in plans[topic] if a.body_chars and a.body_chars >= sc["min_body"] and in_window(a)]
        stats[topic].measured = len(plans[topic])
        stats[topic].with_body = len(ok)
        for a in ok:
            fin = final_score(a, pre[id(a)], sc)
            a.points, a.reasons = fin.points, fin.reasons
        measured_ok += ok

    chosen: dict[str, list[Article]] = {}
    for topic in topics:
        st = stats[topic]
        by_story: dict[int, list[Article]] = {}
        for a in measured_ok:
            if home[story_of[id(a)]] == topic:
                by_story.setdefault(story_of[id(a)], []).append(a)
        reps = []
        for g in by_story.values():
            rep = max(g, key=lambda a: (a.points, a.body_chars))
            rep.also = [s for s in story_sources[id(rep)] if s != rep.source]
            reps.append(rep)
        reps.sort(key=lambda a: (a.points, recency(a)), reverse=True)
        picked: list[Article] = []
        per_source: dict[str, int] = {}
        opinions = 0
        for a in reps:
            if len(picked) >= per_topic:
                break
            if per_source.get(a.source, 0) >= sc["per_source_max"]:
                continue
            if is_opinion(a, sc):
                if opinions >= sc["opinion"]["max_per_topic"]:
                    continue
                opinions += 1
            per_source[a.source] = per_source.get(a.source, 0) + 1
            a.summary = summarize(a.description or a.page_desc, a.title)
            picked.append(a)
        st.selected = len(picked)
        chosen[topic] = picked
    return chosen, stats
