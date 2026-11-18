"""실행: python -m newsdigest [--config 설정.json] [--out 결과폴더] [--now 기준시각] [--check-feeds]
                            [--dump 저장.json] [--from-dump 저장.json] [--print]"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

from .article import parse_article
from .dump import read_dump, write_dump
from .feeds import KST, collect, fetch, fetch_page
from .render import render_text, write_site
from .selection import measure_pages, normalize_link, select

HERE = Path(__file__).resolve().parent.parent  # news-digest/


def load_config(path: Path) -> dict:
    config = json.loads(path.read_text(encoding="utf-8"))
    if not config.get("topics"):
        raise SystemExit(f"설정 파일에 'topics'가 비어 있습니다: {path}")
    names = [t.get("name") for t in config["topics"]]
    if not all(names) or len(set(names)) != len(names):
        raise SystemExit(f"주제 이름은 비어 있거나 겹치면 안 됩니다: {names}")
    for t in config["topics"]:
        if not t.get("feeds") or not all(f.get("source") and f.get("url") for f in t["feeds"]):
            raise SystemExit(f"주제 '{t['name']}'의 feeds에는 source와 url이 있어야 합니다")
    return config


def collect_headlines(config: dict, fetcher=fetch) -> frozenset[str]:
    """언론사 주요뉴스 RSS(headline_feeds)에 실린 기사 주소. 실패한 곳은 건너뛴다."""
    feeds = config.get("headline_feeds", [])
    if not feeds:
        return frozenset()
    results = collect({"topics": [{"name": "주요뉴스", "feeds": feeds}]}, fetcher=fetcher)
    for r in results:
        if r.error:
            print(f"주요뉴스 RSS 실패 {r.source} {r.url} — {r.error}")
    return frozenset(normalize_link(a.link) for r in results for a in r.articles)


def check_feeds(config: dict, now: datetime, fetcher=fetch, page_fetcher=fetch_page) -> int:
    """주제·언론사별로 RSS가 열리는지, 최근 기사 수, 첫 기사 페이지의 본문 글자 수를 보고한다."""
    window = now - timedelta(hours=config.get("window_hours", 24))
    lines = ["| 결과 | 주제 | 언론사 | 기사 | 최근 | 날짜 없음 | 첫 기사 본문 | 주소 |",
             "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    bad = 0
    checked = dict(config, topics=config["topics"] + ([{"name": "(주요뉴스)", "feeds": config["headline_feeds"]}]
                                                    if config.get("headline_feeds") else []))
    for r in collect(checked, fetcher=fetcher):
        if r.error:
            bad += 1
            lines.append(f"| 실패 | {r.topic} | {r.source} | - | - | - | - | {r.url} ({r.error[:100]}) |")
            continue
        recent = [a for a in r.articles if a.published and a.published >= window]
        undated = [a for a in r.articles if a.published is None]
        sample = (recent or undated or [None])[0]
        body = "-"
        if sample is not None:
            try:
                info = parse_article(page_fetcher(sample.link))
                body = f"{info.body_chars:,}자" if info.body_chars else "못 찾음"
            except Exception as exc:  # noqa: BLE001
                body = f"열기 실패({type(exc).__name__})"
        status = "확인" if (recent or undated) and body.endswith("자") else "주의"
        note = f" (날짜 칸 예: {undated[0].raw_date[:40]!r})" if undated else ""
        lines.append(f"| {status} | {r.topic} | {r.source} | {len(r.articles)} | {len(recent)} | {len(undated)} | {body} | {r.url}{note} |")
    report = "\n".join(lines)
    print(report)
    if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write("## RSS·본문 점검\n\n" + report + "\n")
    return 1 if bad else 0


def run(config: dict, out_dir: Path, now: datetime, fetcher=fetch, page_fetcher=fetch_page, *,
        from_dump: Path | None = None, dump: Path | None = None, print_text: bool = False) -> int:
    if from_dump:
        wanted = {(t["name"], f["url"]) for t in config["topics"] for f in t["feeds"]}
        results, headlines = read_dump(from_dump)
        results = [r for r in results if (r.topic, r.url) in wanted]  # 설정에서 뺀 RSS는 무시
    else:
        results = collect(config, fetcher=fetcher)
        headlines = collect_headlines(config, fetcher=fetcher)
    for r in results:
        print(f"{'실패' if r.error else '확인'} {r.topic} {r.source} {len(r.articles)}건 {r.url}"
              + (f" — {r.error}" if r.error else ""))
    if not results or all(r.error for r in results):
        print("모든 RSS 주소를 가져오지 못해 페이지를 만들지 않았습니다.", file=sys.stderr)
        return 1
    articles = [a for r in results for a in r.articles]
    chosen, stats = select(articles, config, now, measure=lambda arts: measure_pages(arts, fetcher=page_fetcher),
                           headlines=headlines)
    if dump:
        write_dump(dump, results, headlines)
    day, index = write_site(out_dir, config=config, chosen=chosen, stats=stats, results=results, now=now)
    for t, s in stats.items():
        print(f"{t}: 기사 {s.total} → 기간 안 {s.in_window} → 본문 {s.with_body}/{s.measured} → {s.selected}건")
    print(f"→ {day}, {index}")
    if print_text:
        print()
        print(render_text(config=config, chosen=chosen, stats=stats, results=results, now=now))
    return 0


def main(argv: list[str] | None = None, fetcher=fetch, page_fetcher=fetch_page) -> int:
    parser = argparse.ArgumentParser(prog="newsdigest", description="주제별 뉴스 요약 페이지 만들기")
    parser.add_argument("--config", type=Path, default=HERE / "config.json")
    parser.add_argument("--out", type=Path, default=HERE.parent / "news")
    parser.add_argument("--now", help="기준 시각(ISO 8601). 기본은 지금")
    parser.add_argument("--dump", type=Path, help="수집·측정 결과를 JSON으로 저장")
    parser.add_argument("--from-dump", type=Path, help="접속하지 않고 저장해 둔 JSON으로 만들기")
    parser.add_argument("--print", dest="print_text", action="store_true", help="요약을 글로도 출력")
    parser.add_argument("--check-feeds", action="store_true", help="RSS·본문 읽기만 점검하고 페이지는 만들지 않음")
    args = parser.parse_args(argv)

    config = load_config(args.config)
    now = datetime.fromisoformat(args.now) if args.now else datetime.now(KST)
    if now.tzinfo is None:
        now = now.replace(tzinfo=KST)
    if args.check_feeds:
        return check_feeds(config, now, fetcher=fetcher, page_fetcher=page_fetcher)
    return run(config, args.out, now, fetcher=fetcher, page_fetcher=page_fetcher,
               from_dump=args.from_dump, dump=args.dump, print_text=args.print_text)


if __name__ == "__main__":
    sys.exit(main())
