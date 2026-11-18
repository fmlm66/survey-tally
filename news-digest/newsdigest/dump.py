"""수집 결과를 작은 JSON으로 저장/복원한다.

다른 시각을 기준으로 다시 고르거나, 언론사에 직접 접속할 수 없는 곳에서 요약을 만들 때 쓴다.
주제 키워드에 맞는 기사만 제목·주소·요약문을 남기고, 나머지는 통계용 발행 시각만 남긴다.
"""

from __future__ import annotations

import json
from pathlib import Path

from .feeds import Article, FeedResult, parse_date
from .selection import keyword_pattern, score


def dump_results(results: list[FeedResult], config: dict) -> dict:
    keywords = [keyword_pattern(k) for k in config["keywords"] if k.strip()]
    feeds = []
    for r in results:
        items = []
        for a in r.articles:
            p = a.published.isoformat() if a.published else None
            if score(a, keywords) > 0:
                items.append({"t": a.title, "l": a.link, "d": a.description, "p": p})
            else:
                items.append({"p": p})
        feeds.append({"source": r.source, "url": r.url, "error": r.error, "articles": items})
    return {"version": 1, "feeds": feeds}


def load_results(data: dict) -> list[FeedResult]:
    results = []
    for f in data["feeds"]:
        arts = [Article(source=f["source"], title=i.get("t", ""), link=i.get("l", ""),
                        description=i.get("d", ""), published=parse_date(i.get("p") or ""))
                for i in f["articles"]]
        results.append(FeedResult(f["source"], f["url"], arts, f.get("error")))
    return results


def write_dump(path: Path, results: list[FeedResult], config: dict) -> None:
    path.write_text(json.dumps(dump_results(results, config), ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def read_dump(path: Path) -> list[FeedResult]:
    return load_results(json.loads(path.read_text(encoding="utf-8")))
