"""수집·측정 결과를 JSON으로 저장/복원한다.

언론사에 직접 접속할 수 없는 곳에서 요약을 다시 만들거나, 다른 기준 시각으로 다시 고를 때 쓴다.
본문 길이를 잰 기사는 제목·주소·요약문·글자 수를 남기고, 나머지는 통계용 발행 시각만 남긴다.
"""

from __future__ import annotations

import json
from pathlib import Path

from .feeds import Article, FeedResult, parse_date


def dump_results(results: list[FeedResult]) -> dict:
    feeds = []
    for r in results:
        items = []
        for a in r.articles:
            p = a.published.isoformat() if a.published else None
            if a.measured:
                items.append({"t": a.title, "l": a.link, "d": a.description, "p": p,
                              "b": a.body_chars, "pd": a.page_desc})
            else:
                items.append({"p": p})
        feeds.append({"topic": r.topic, "source": r.source, "url": r.url, "error": r.error, "articles": items})
    return {"version": 2, "feeds": feeds}


def load_results(data: dict) -> list[FeedResult]:
    if data.get("version") != 2:
        raise ValueError("이 형식의 저장 파일은 읽을 수 없습니다(version 2 필요)")
    results = []
    for fi, f in enumerate(data["feeds"]):
        arts = []
        for i, item in enumerate(f["articles"]):
            measured = "b" in item
            arts.append(Article(source=f["source"], title=item.get("t", ""),
                                link=item.get("l") or f"dump://feed{fi}/item{i}",  # 재지 않은 기사: 통계용 자리(서로 다른 주소)
                                description=item.get("d", ""), published=parse_date(item.get("p") or ""),
                                topic=f["topic"], measured=True, body_chars=item.get("b") if measured else None,
                                page_desc=item.get("pd", "")))
        results.append(FeedResult(f["topic"], f["source"], f["url"], arts, f.get("error")))
    return results


def write_dump(path: Path, results: list[FeedResult]) -> None:
    path.write_text(json.dumps(dump_results(results), ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def read_dump(path: Path) -> list[FeedResult]:
    return load_results(json.loads(path.read_text(encoding="utf-8")))
