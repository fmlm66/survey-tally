"""결과 HTML 만들기. 외부 스크립트·글꼴 없이, 모든 글자는 이스케이프한다."""

from __future__ import annotations

import re
from datetime import datetime
from html import escape
from pathlib import Path

from .feeds import KST, Article, FeedResult
from .selection import Stats
from .summarize import clean_text

WEEKDAYS = "월화수목금토일"
SAFE_LINK = re.compile(r"^https?://", re.I)
DATE_FILE = re.compile(r"^(\d{4}-\d{2}-\d{2})\.html$")

STYLE = """
:root { color-scheme: light dark; --bg:#f7f7f5; --panel:#fff; --text:#1d1d1b; --muted:#6b6b66; --line:#deded8; --accent:#2f5fd0; }
@media (prefers-color-scheme: dark) { :root { --bg:#161615; --panel:#1f1f1d; --text:#ececea; --muted:#a2a29c; --line:#3a3a36; --accent:#8aa8ff; } }
* { box-sizing: border-box; }
body { margin:0; background:var(--bg); color:var(--text); font:16px/1.6 system-ui,-apple-system,"Segoe UI","Apple SD Gothic Neo","Malgun Gothic",sans-serif; }
main { max-width:760px; margin:0 auto; padding:24px 16px 48px; }
h1 { font-size:1.45rem; margin:0 0 4px; }
.sub { margin:0 0 20px; color:var(--muted); }
ol.news { list-style:none; padding:0; margin:0; display:grid; gap:12px; }
ol.news li { background:var(--panel); border:1px solid var(--line); border-radius:10px; padding:14px 16px; }
ol.news h2 { font-size:1.05rem; margin:0 0 4px; line-height:1.45; }
a { color:var(--accent); }
ol.news h2 a { color:var(--text); text-decoration:none; }
ol.news h2 a:hover { text-decoration:underline; }
.meta { font-size:.85rem; color:var(--muted); margin:0 0 6px; }
.summary { margin:0; overflow-wrap:anywhere; }
.empty { padding:24px 16px; background:var(--panel); border:1px solid var(--line); border-radius:10px; }
footer { margin-top:28px; font-size:.85rem; color:var(--muted); }
footer ul { padding-left:1.2em; }
footer h2.small { font-size:1rem; }
.archive { display:flex; flex-wrap:wrap; gap:6px 14px; padding:0; list-style:none; }
"""


def format_date(d: datetime) -> str:
    d = d.astimezone(KST)
    return f"{d:%Y-%m-%d} ({WEEKDAYS[d.weekday()]})"


def format_time(published: datetime, now: datetime) -> str:
    p, n = published.astimezone(KST), now.astimezone(KST)
    return f"{p:%H:%M}" if p.date() == n.date() else f"{p.month}/{p.day} {p:%H:%M}"


def _article(a: Article, now: datetime) -> str:
    meta = f"{escape(a.source)} · {format_time(a.published, now)}"
    if a.also:
        meta += f" · 같은 소식: {escape(', '.join(a.also))}"
    summary = f'<p class="summary">{escape(a.summary)}</p>' if a.summary else ""
    title = escape(clean_text(a.title))
    if SAFE_LINK.match(a.link):  # javascript: 같은 주소는 링크로 만들지 않는다
        title = f'<a href="{escape(a.link, quote=True)}" rel="noopener noreferrer">{title}</a>'
    return (f'<li><h2>{title}</h2>'
            f'<p class="meta">{meta}</p>{summary}</li>')


def render_page(*, config: dict, articles: list[Article], stats: Stats, results: list[FeedResult],
                now: datetime, archive: list[str] | None = None) -> str:
    topic = escape(config["topic"])
    date = format_date(now)
    sources = sorted({r.source for r in results if not r.error})
    failed = [r for r in results if r.error]

    if articles:
        body = '<ol class="news">' + "".join(_article(a, now) for a in articles) + "</ol>"
    else:
        body = f'<p class="empty">최근 {config.get("window_hours", 24)}시간 동안 &lsquo;{topic}&rsquo; 주제의 새 기사가 없습니다.</p>'

    foot = [
        f"<p>언론사 {len(sources)}곳({escape(', '.join(sources))})의 기사 {stats.total}건 중 최근 "
        f"{config.get('window_hours', 24)}시간 {stats.in_window}건, 주제 관련 {stats.matched}건에서 {stats.selected}건을 골랐습니다. "
        f"요약은 각 언론사 RSS에 실린 요약문의 앞부분이며, 전체 기사는 제목을 눌러 언론사 사이트에서 보세요.</p>",
        f"<p>만든 시각: {now.astimezone(KST):%Y-%m-%d %H:%M} (한국 시각)</p>",
    ]
    if failed:
        items = "".join(f"<li>{escape(r.source)}: {escape(r.url)}</li>" for r in failed)
        foot.append(f"<p>가져오지 못한 곳</p><ul>{items}</ul>")
    if archive is not None:
        links = "".join(f'<li><a href="{d}.html">{d}</a></li>' for d in archive)
        foot.append(f"<h2 class=\"small\">지난 요약</h2><ul class=\"archive\">{links}</ul>")
    else:
        foot.append('<p><a href="index.html">최신 요약과 지난 요약 목록</a></p>')

    return f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'">
<meta name="referrer" content="no-referrer">
<title>{topic} 아침 뉴스 · {date}</title>
<style>{STYLE}</style>
</head>
<body>
<main>
<h1>{topic} 아침 뉴스</h1>
<p class="sub">{date} · {len(articles)}건</p>
{body}
<footer>
{"".join(foot)}
</footer>
</main>
</body>
</html>
"""


def write_site(out_dir: Path, **page_args) -> tuple[Path, Path]:
    """news/YYYY-MM-DD.html(그날)과 news/index.html(최신 + 지난 목록)을 쓴다. 같은 날 다시 돌리면 덮어쓴다."""
    out_dir.mkdir(parents=True, exist_ok=True)
    day = page_args["now"].astimezone(KST).strftime("%Y-%m-%d")
    day_path = out_dir / f"{day}.html"
    day_path.write_text(render_page(**page_args), encoding="utf-8")
    dates = sorted((m.group(1) for p in out_dir.iterdir() if (m := DATE_FILE.match(p.name))), reverse=True)
    index_path = out_dir / "index.html"
    index_path.write_text(render_page(**page_args, archive=dates), encoding="utf-8")
    return day_path, index_path
