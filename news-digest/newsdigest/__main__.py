"""실행: python -m newsdigest [--config 설정.json] [--out 결과폴더] [--check-feeds]"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

from .feeds import KST, collect, fetch
from .dump import read_dump, write_dump
from .render import render_text, write_site
from .selection import select

HERE = Path(__file__).resolve().parent.parent  # news-digest/


def load_config(path: Path) -> dict:
    config = json.loads(path.read_text(encoding="utf-8"))
    for key in ("topic", "keywords", "sources"):
        if not config.get(key):
            raise SystemExit(f"설정 파일에 '{key}'가 비어 있습니다: {path}")
    for src in config["sources"]:
        if not src.get("name") or not src.get("feeds"):
            raise SystemExit(f"언론사 항목에는 name과 feeds가 있어야 합니다: {src}")
    return config


def check_feeds(config: dict, now: datetime, fetcher=fetch) -> int:
    """각 RSS 주소가 열리는지, 기사·날짜가 읽히는지 보고한다."""
    window = now - timedelta(hours=config.get("window_hours", 24))
    lines = ["| 결과 | 언론사 | 기사 | 최근 | 날짜 없음 | 주소 |", "| --- | --- | --- | --- | --- | --- |"]
    bad = 0
    for r in collect(config["sources"], fetcher=fetcher):
        if r.error:
            bad += 1
            lines.append(f"| 실패 | {r.source} | - | - | - | {r.url} ({r.error[:120]}) |")
            continue
        recent = sum(1 for a in r.articles if a.published and a.published >= window)
        undated = sum(1 for a in r.articles if a.published is None)
        status = "확인" if r.articles and recent else "주의"
        lines.append(f"| {status} | {r.source} | {len(r.articles)} | {recent} | {undated} | {r.url} |")
    report = "\n".join(lines)
    print(report)
    if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write("## RSS 주소 점검\n\n" + report + "\n")
    return 1 if bad else 0


def run(config: dict, out_dir: Path, now: datetime, fetcher=fetch, *, from_dump: Path | None = None,
        dump: Path | None = None, print_text: bool = False) -> int:
    results = read_dump(from_dump) if from_dump else collect(config["sources"], fetcher=fetcher)
    for r in results:
        print(f"{'실패' if r.error else '확인'} {r.source} {len(r.articles)}건 {r.url}" + (f" — {r.error}" if r.error else ""))
    if dump:
        write_dump(dump, results, config)
    if all(r.error for r in results):
        print("모든 RSS 주소를 가져오지 못해 페이지를 만들지 않았습니다.", file=sys.stderr)
        return 1
    articles = [a for r in results for a in r.articles]
    chosen, stats = select(articles, config, now)
    day, index = write_site(out_dir, config=config, articles=chosen, stats=stats, results=results, now=now)
    print(f"{stats.selected}건 선택 → {day}, {index}")
    if print_text:
        print()
        print(render_text(config=config, articles=chosen, stats=stats, results=results, now=now))
    return 0


def main(argv: list[str] | None = None, fetcher=fetch) -> int:
    parser = argparse.ArgumentParser(prog="newsdigest", description="주제별 아침 뉴스 요약 페이지 만들기")
    parser.add_argument("--config", type=Path, default=HERE / "config.json")
    parser.add_argument("--out", type=Path, default=HERE.parent / "news")
    parser.add_argument("--now", help="기준 시각(ISO 8601, 시험용). 기본은 지금")
    parser.add_argument("--dump", type=Path, help="수집 결과(주제 기사)를 JSON으로 저장")
    parser.add_argument("--from-dump", type=Path, help="RSS에 접속하지 않고 저장해 둔 JSON으로 만들기")
    parser.add_argument("--print", dest="print_text", action="store_true", help="요약을 글로도 출력")
    parser.add_argument("--check-feeds", action="store_true", help="RSS 주소만 점검하고 페이지는 만들지 않음")
    args = parser.parse_args(argv)

    config = load_config(args.config)
    now = datetime.fromisoformat(args.now) if args.now else datetime.now(KST)
    if now.tzinfo is None:
        now = now.replace(tzinfo=KST)
    if args.check_feeds:
        return check_feeds(config, now, fetcher=fetcher)
    return run(config, args.out, now, fetcher=fetcher, from_dump=args.from_dump, dump=args.dump,
               print_text=args.print_text)


if __name__ == "__main__":
    sys.exit(main())
