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


def plan_fetch(articles: list[Article], limit: int) -> list[Article]:
    """언론사마다 번갈아 가며 최신 기사부터 limit건(본문 길이를 잴 대상)."""
    by_source: dict[str, list[Article]] = {}
    for a in articles:
        by_source.setdefault(a.source, []).append(a)
    queues = [sorted(v, key=lambda a: a.published.timestamp() if a.published else float("inf"), reverse=True)
              for v in by_source.values()]
    chosen: list[Article] = []
    while len(chosen) < limit and any(queues):
        for q in queues:
            if q and len(chosen) < limit:
                chosen.append(q.pop(0))
    return chosen


def group_similar(articles: list[Article]) -> list[list[Article]]:
    groups: list[list[Article]] = []
    for a in articles:
        for g in groups:
            if any(similarity(a.title, b.title) >= SIMILAR for b in g):
                g.append(a)
                break
        else:
            groups.append([a])
    return groups


def select(articles: list[Article], config: dict, now: datetime,
           measure: Callable[[list[Article]], None] = measure_pages) -> tuple[dict[str, list[Article]], dict[str, TopicStats]]:
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

    # 저장 파일로 다시 만들 때 재지 않았던 기사(dump:// 자리)는 잴 대상이 아니다(통계에만 센다)
    plans = {t: plan_fetch([a for a in pools[t] if not a.link.startswith("dump://")], max_fetch) for t in topics}
    measure([a for t in topics for a in plans[t]])

    chosen: dict[str, list[Article]] = {}
    for topic in topics:
        st = stats[topic]
        st.measured = len(plans[topic])
        # 기사 페이지의 발행 시각으로 기간을 다시 확인한다(날짜 없던 RSS 대비)
        ok = [a for a in plans[topic] if a.body_chars and in_window(a)]
        st.with_body = len(ok)
        reps = []
        for g in group_similar(ok):
            g.sort(key=lambda a: a.body_chars, reverse=True)
            rep = g[0]
            rep.also = []
            for other in g[1:]:
                if other.source != rep.source and other.source not in rep.also:
                    rep.also.append(other.source)
            reps.append(rep)
        reps.sort(key=lambda a: a.body_chars, reverse=True)
        picked = reps[:per_topic]
        for a in picked:
            a.summary = summarize(a.description or a.page_desc, a.title)
        st.selected = len(picked)
        chosen[topic] = picked
    return chosen, stats
