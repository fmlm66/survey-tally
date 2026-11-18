"""주제에 맞는 기사 고르기: 기간 → 키워드 점수 → 중복 묶기 → 순위."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from urllib.parse import urlsplit

from .feeds import Article
from .summarize import clean_text, summarize

TITLE_WEIGHT = 3
BODY_WEIGHT = 1
SIMILAR = 0.45


def keyword_pattern(keyword: str) -> re.Pattern:
    """영문·숫자 키워드는 영문 단어 안에 묻힌 경우를 세지 않는다(AI ≠ MAIN). 한글은 그대로 포함 검사."""
    kw = keyword.strip()
    escaped = re.escape(kw)
    if re.fullmatch(r"[A-Za-z0-9 .+#-]+", kw):
        return re.compile(rf"(?<![A-Za-z]){escaped}(?![A-Za-z])", re.I)
    return re.compile(escaped, re.I)


def score(article: Article, keywords: list[re.Pattern]) -> int:
    title = clean_text(article.title)
    body = clean_text(article.description)
    total = 0
    for pat in keywords:
        if pat.search(title):
            total += TITLE_WEIGHT
        elif pat.search(body):
            total += BODY_WEIGHT
    return total


def normalize_link(link: str) -> str:
    parts = urlsplit(link.strip())
    host = parts.netloc.lower().removeprefix("www.")
    path = parts.path.rstrip("/")
    return f"{host}{path}?{parts.query}" if parts.query else f"{host}{path}"


_NON_WORD = re.compile(r"[^0-9A-Za-z가-힣]")


def bigrams(title: str) -> set[str]:
    s = _NON_WORD.sub("", clean_text(title).lower())
    return {s[i:i + 2] for i in range(len(s) - 1)} if len(s) > 1 else {s}


def similarity(a: str, b: str) -> float:
    """겹치는 글자 2개 묶음 ÷ 짧은 제목의 묶음 수. 언론사마다 제목 길이가 달라도 같은 소식을 잡는다."""
    x, y = bigrams(a), bigrams(b)
    return len(x & y) / min(len(x), len(y)) if x and y else 0.0


@dataclass
class Stats:
    total: int = 0
    undated: int = 0
    in_window: int = 0
    matched: int = 0
    selected: int = 0


def select(articles: list[Article], config: dict, now: datetime) -> tuple[list[Article], Stats]:
    keywords = [keyword_pattern(k) for k in config["keywords"] if k.strip()]
    excludes = [keyword_pattern(k) for k in config.get("exclude_keywords", []) if k.strip()]
    hours = config.get("window_hours", 24)
    max_articles = config.get("max_articles", 15)
    per_source = config.get("per_source_max", 5)
    start, end = now - timedelta(hours=hours), now  # 기준 시각 뒤 기사는 다음 실행에서 잡힌다

    # 날짜를 싣지 않는 RSS(최신 몇십 건만 싣는 곳)는 설정에서 "undated": "recent"로 두면 최근 기사로 본다.
    undated_ok = {s["name"] for s in config.get("sources", []) if s.get("undated") == "recent"}
    stats = Stats(total=len(articles))
    seen_links: set[str] = set()
    candidates: list[Article] = []
    for a in articles:
        if a.published is None:
            stats.undated += 1
            if a.source not in undated_ok:
                continue
        elif not (start <= a.published <= end):
            continue
        stats.in_window += 1
        key = normalize_link(a.link)
        if key in seen_links:
            continue
        seen_links.add(key)
        text = clean_text(a.title) + " " + clean_text(a.description)
        if any(p.search(text) for p in excludes):
            continue
        a.score = score(a, keywords)
        if a.score > 0:
            candidates.append(a)
    stats.matched = len(candidates)

    # 점수 높은 것부터 대표로 삼고, 제목이 비슷한 기사는 그 대표에 묶는다.
    def when(a: Article) -> datetime:
        return a.published or now

    candidates.sort(key=lambda a: (a.score, when(a)), reverse=True)
    clusters: list[tuple[Article, set[str]]] = []
    for a in candidates:
        for rep, sources in clusters:
            if similarity(rep.title, a.title) >= SIMILAR:
                if a.source not in sources:
                    sources.add(a.source)
                    rep.also.append(a.source)
                break
        else:
            clusters.append((a, {a.source}))

    clusters.sort(key=lambda c: (len(c[1]), c[0].score, when(c[0])), reverse=True)
    chosen: list[Article] = []
    per_count: dict[str, int] = {}
    for rep, _ in clusters:
        if len(chosen) >= max_articles:
            break
        if per_count.get(rep.source, 0) >= per_source:
            continue
        per_count[rep.source] = per_count.get(rep.source, 0) + 1
        rep.summary = summarize(rep.description, rep.title)
        chosen.append(rep)
    stats.selected = len(chosen)
    return chosen, stats
