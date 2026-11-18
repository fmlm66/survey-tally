"""결과 HTML 만들기. 스크립트 없이 CSS만으로 주제 탭을 만들고, 모든 글자는 이스케이프한다."""

from __future__ import annotations

import re
from datetime import datetime
from html import escape
from pathlib import Path

from .feeds import KST, Article, FeedResult
from .selection import TopicStats
from .summarize import clean_text

WEEKDAYS = "월화수목금토일"
SAFE_LINK = re.compile(r"^https?://", re.I)
DATE_FILE = re.compile(r"^(\d{4}-\d{2}-\d{2})\.html$")

STYLE = """
:root { color-scheme: light dark; --bg:#f7f7f5; --panel:#fff; --text:#1d1d1b; --muted:#6b6b66; --line:#deded8; --accent:#2f5fd0; --accent-bg:#e8eefc; }
@media (prefers-color-scheme: dark) { :root { --bg:#161615; --panel:#1f1f1d; --text:#ececea; --muted:#a2a29c; --line:#3a3a36; --accent:#8aa8ff; --accent-bg:#26304a; } }
* { box-sizing: border-box; }
body { margin:0; background:var(--bg); color:var(--text); font:16px/1.6 system-ui,-apple-system,"Segoe UI","Apple SD Gothic Neo","Malgun Gothic",sans-serif; }
main { max-width:760px; margin:0 auto; padding:24px 16px 48px; }
h1 { font-size:1.45rem; margin:0 0 4px; }
.sub { margin:0 0 16px; color:var(--muted); }
.tab-input { position:absolute; opacity:0; pointer-events:none; }
.tab-bar { position:sticky; top:0; z-index:1; display:flex; gap:6px; overflow-x:auto; padding:8px 0; margin:0 0 12px;
  background:var(--bg); border-bottom:1px solid var(--line); scrollbar-width:thin; }
.tab-bar label { flex:none; padding:6px 12px; border:1px solid var(--line); border-radius:999px; background:var(--panel);
  cursor:pointer; white-space:nowrap; font-size:.95rem; }
.tab-bar label span { color:var(--muted); font-size:.8rem; margin-left:4px; }
.panel { display:none; }
.panel h2.topic { font-size:1.1rem; margin:4px 0 10px; }
ol.news { list-style:none; padding:0; margin:0; display:grid; gap:12px; }
ol.news li { background:var(--panel); border:1px solid var(--line); border-radius:10px; padding:14px 16px; }
ol.news h3 { font-size:1.05rem; margin:0 0 4px; line-height:1.45; }
a { color:var(--accent); }
ol.news h3 a { color:var(--text); text-decoration:none; }
ol.news h3 a:hover { text-decoration:underline; }
.meta { font-size:.85rem; color:var(--muted); margin:0 0 6px; }
.summary { margin:0; overflow-wrap:anywhere; }
.empty { padding:24px 16px; background:var(--panel); border:1px solid var(--line); border-radius:10px; margin:0; }
footer { margin-top:28px; font-size:.85rem; color:var(--muted); }
footer ul { padding-left:1.2em; }
footer h2 { font-size:1rem; }
.archive { display:flex; flex-wrap:wrap; gap:6px 14px; padding:0; list-style:none; }
"""


def _tab_css(n: int) -> str:
    """i번째 라디오가 선택되면 i번째 패널을 보이고 i번째 탭을 강조한다."""
    show = ", ".join(f"#tab{i}:checked ~ .panels #panel{i}" for i in range(n))
    active = ", ".join(f"#tab{i}:checked ~ .tab-bar label[for=tab{i}]" for i in range(n))
    focus = ", ".join(f"#tab{i}:focus-visible ~ .tab-bar label[for=tab{i}]" for i in range(n))
    return (f"{show} {{ display:block; }}\n"
            f"{active} {{ background:var(--accent-bg); border-color:var(--accent); color:var(--accent); font-weight:600; }}\n"
            f"{focus} {{ outline:2px solid var(--accent); outline-offset:2px; }}\n")


def format_date(d: datetime) -> str:
    d = d.astimezone(KST)
    return f"{d:%Y-%m-%d} ({WEEKDAYS[d.weekday()]})"


def format_time(published: datetime | None, now: datetime) -> str:
    if published is None:
        return "시각 미표기"
    p, n = published.astimezone(KST), now.astimezone(KST)
    return f"{p:%H:%M}" if p.date() == n.date() else f"{p.month}/{p.day} {p:%H:%M}"


def _meta(a: Article, now: datetime) -> str:
    parts = [a.source, format_time(a.published, now)]
    if a.body_chars:
        parts.append(f"본문 {a.body_chars:,}자")
    if a.also:
        parts.append("같은 소식: " + ", ".join(a.also))
    return " · ".join(parts)


def _article(a: Article, now: datetime) -> str:
    summary = f'<p class="summary">{escape(a.summary)}</p>' if a.summary else ""
    title = escape(clean_text(a.title))
    if SAFE_LINK.match(a.link):  # javascript: 같은 주소는 링크로 만들지 않는다
        title = f'<a href="{escape(a.link, quote=True)}" rel="noopener noreferrer">{title}</a>'
    return f'<li><h3>{title}</h3><p class="meta">{escape(_meta(a, now))}</p>{summary}</li>'


def render_page(*, config: dict, chosen: dict[str, list[Article]], stats: dict[str, TopicStats],
                results: list[FeedResult], now: datetime, archive: list[str] | None = None) -> str:
    title = escape(config.get("title", "아침 뉴스"))
    date = format_date(now)
    topics = [t["name"] for t in config["topics"]]
    hours = config.get("window_hours", 24)
    total = sum(len(v) for v in chosen.values())

    inputs = "".join(
        f'<input class="tab-input" type="radio" name="topic" id="tab{i}"{" checked" if i == 0 else ""}>'
        for i in range(len(topics)))
    labels = "".join(
        f'<label for="tab{i}">{escape(t)}<span>{len(chosen.get(t, []))}</span></label>' for i, t in enumerate(topics))
    panels = []
    for i, t in enumerate(topics):
        arts = chosen.get(t, [])
        if arts:
            body = '<ol class="news">' + "".join(_article(a, now) for a in arts) + "</ol>"
        else:
            body = f'<p class="empty">최근 {hours}시간 동안 본문을 확인한 &lsquo;{escape(t)}&rsquo; 기사가 없습니다.</p>'
        panels.append(f'<section class="panel" id="panel{i}" aria-label="{escape(t, quote=True)}">'
                      f'<h2 class="topic">{escape(t)} · 본문이 긴 기사 {len(arts)}건</h2>{body}</section>')

    rows = "".join(
        f"<li>{escape(t)}: 기사 {s.total}건 → 최근 {hours}시간 {s.in_window}건 → 본문 확인 {s.with_body}/{s.measured}건 → {s.selected}건</li>"
        for t, s in stats.items())
    foot = [
        f"<p>주제마다 최근 {hours}시간 기사 가운데 기사 본문(공백 제외 글자 수)이 가장 긴 {config.get('per_topic', 5)}건을 골랐습니다. "
        "같은 소식은 하나로 묶고 본문이 가장 긴 기사를 보입니다. 요약은 언론사가 RSS나 기사 페이지에 실은 소개문의 앞부분이며, "
        "전체 기사는 제목을 눌러 언론사 사이트에서 보세요.</p>",
        f"<ul>{rows}</ul>",
        f"<p>만든 시각: {now.astimezone(KST):%Y-%m-%d %H:%M} (한국 시각)</p>",
    ]
    failed = [r for r in results if r.error]
    if failed:
        items = "".join(f"<li>{escape(r.topic)} · {escape(r.source)}: {escape(r.url)}</li>" for r in failed)
        foot.append(f"<p>가져오지 못한 RSS</p><ul>{items}</ul>")
    if archive is not None:
        links = "".join(f'<li><a href="{d}.html">{d}</a></li>' for d in archive)
        foot.append(f'<h2>지난 요약</h2><ul class="archive">{links}</ul>')
    else:
        foot.append('<p><a href="index.html">최신 요약과 지난 요약 목록</a></p>')

    return f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'">
<meta name="referrer" content="no-referrer">
<title>{title} · {date}</title>
<style>{STYLE}{_tab_css(len(topics))}</style>
</head>
<body>
<main>
<h1>{title}</h1>
<p class="sub">{date} · {len(topics)}개 주제 · {total}건</p>
<div class="tabs">
{inputs}
<nav class="tab-bar" aria-label="주제">{labels}</nav>
<div class="panels">
{"".join(panels)}
</div>
</div>
<footer>
{"".join(foot)}
</footer>
</main>
</body>
</html>
"""


def render_text(*, config: dict, chosen: dict[str, list[Article]], stats: dict[str, TopicStats],
                results: list[FeedResult], now: datetime) -> str:
    """같은 내용을 마크다운 글로(로그·메신저용)."""
    lines = [f"# {config.get('title', '아침 뉴스')} · {format_date(now)}"]
    for t in (x["name"] for x in config["topics"]):
        arts = chosen.get(t, [])
        lines += ["", f"## {t} ({len(arts)}건)"]
        if not arts:
            lines.append("본문을 확인한 기사가 없습니다.")
        for i, a in enumerate(arts, 1):
            lines.append(f"{i}. **{clean_text(a.title)}** ({_meta(a, now)})")
            if a.summary:
                lines.append(f"   {a.summary}")
            lines.append(f"   {a.link}")
    failed = [f"{r.topic}·{r.source}" for r in results if r.error]
    if failed:
        lines += ["", "가져오지 못한 RSS: " + ", ".join(failed)]
    return "\n".join(lines)


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
