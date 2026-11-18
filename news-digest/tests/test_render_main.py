import io
import json
import re
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta
from pathlib import Path

from newsdigest.__main__ import HERE, check_feeds, load_config, main, run
from newsdigest.feeds import KST, Article, FeedResult
from newsdigest.render import render_page, render_text, write_site
from newsdigest.selection import TopicStats

NOW = datetime(2026, 11, 18, 6, 40, tzinfo=KST)
FIX = Path(__file__).parent / "fixtures"
CONFIG = {"title": "아침 뉴스", "window_hours": 24, "per_topic": 5, "max_fetch_per_topic": 60, "topics": [
    {"name": "산업경제", "feeds": [{"source": "예시신문", "url": "https://news.example.kr/rss"}]},
    {"name": "과학기술", "feeds": [{"source": "예시방송", "url": "https://tv.example.kr/atom"},
                                {"source": "고장난곳", "url": "https://broken.example.kr/rss"}]},
]}
BODIES = {"https://news.example.kr/a/1": 1800, "https://news.example.kr/a/2": 600, "https://tv.example.kr/news/10": 2400}


def fake_fetch(url):
    if "broken" in url:
        raise OSError("connection refused")
    return (FIX / ("atom.xml" if "atom" in url else "rss2.xml")).read_bytes()


def fake_page(url):
    n = BODIES.get(url)
    if n is None:
        raise OSError("404")
    return f'<html><head><meta property="og:description" content="페이지 소개"></head><body><div>{"가" * n}</div></body></html>'


def quiet(fn, *a, **kw):
    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        return fn(*a, **kw)


def page(chosen, results=None, archive=None):
    results = results or [FeedResult("산업경제", "A", "https://a/rss", [])]
    stats = {t["name"]: TopicStats(total=3, in_window=2, measured=2, with_body=1, selected=len(chosen.get(t["name"], [])))
             for t in CONFIG["topics"]}
    return render_page(config=CONFIG, chosen=chosen, stats=stats, results=results, now=NOW, archive=archive)


class RenderTest(unittest.TestCase):
    def test_tabs_one_per_topic_first_checked(self):
        html = page({"산업경제": [Article("A", "환율", "https://a.kr/1", published=NOW, body_chars=1234)]})
        self.assertEqual(re.findall(r'<input class="tab-input" type="radio" name="topic" id="(tab\d)"( checked)?>', html),
                         [("tab0", " checked"), ("tab1", "")])
        self.assertIn('<label for="tab0">산업경제<span>1</span></label><label for="tab1">과학기술<span>0</span></label>', html)
        self.assertIn('id="panel1" aria-label="과학기술"', html)
        self.assertIn("#tab1:checked ~ .panels #panel1", html)
        self.assertIn("본문을 확인한 &lsquo;과학기술&rsquo; 기사가 없습니다", html)
        self.assertIn("A · 06:40 · 본문 1,234자", html)

    def test_escapes_and_links(self):
        a = Article("A<b>", "AI <script>alert(1)</script> &amp; 소식", 'https://a.kr/1?x=1&y="2"',
                    published=NOW - timedelta(hours=1), summary="<img src=x onerror=alert(1)>", also=["B&C"], body_chars=500)
        html = page({"산업경제": [a]})
        self.assertNotIn("<script>", html)
        self.assertNotIn("<img", html)
        self.assertIn('href="https://a.kr/1?x=1&amp;y=&quot;2&quot;"', html)
        self.assertIn(">AI alert(1) &amp; 소식</a>", html)
        self.assertIn("A&lt;b&gt; · 05:40 · 본문 500자 · 같은 소식: B&amp;C", html)

    def test_reasons_shown_but_not_penalties(self):
        a = Article("A", "x", "https://a.kr/1", published=NOW, body_chars=900, reasons=["4곳 보도", "심층·단독", "홍보성"])
        html = page({"산업경제": [a]})
        meta = re.search(r'<p class="meta">([^<]*)</p>', html).group(1)
        self.assertEqual(meta, "A · 06:40 · 본문 900자 · 4곳 보도 · 심층·단독")  # 감점 이유(홍보성)는 안 보임

    def test_unsafe_link_not_linked(self):
        self.assertNotIn("javascript:", page({"산업경제": [Article("A", "AI", "javascript:alert(1)", published=NOW)]}))

    def test_time_formats(self):
        html = page({"산업경제": [Article("A", "x", "https://a.kr/1", published=datetime(2026, 11, 17, 23, 10, tzinfo=KST)),
                                Article("B", "y", "https://b.kr/1")]})
        self.assertIn("A · 11/17 23:10", html)
        self.assertIn("B · 시각 미표기", html)

    def test_failures_and_archive(self):
        html = page({}, results=[FeedResult("과학기술", "B", "https://b/rss", [], "OSError")],
                    archive=["2026-11-18", "2026-11-17"])
        self.assertIn("<li>과학기술 · B: https://b/rss</li>", html)
        self.assertIn('<a href="2026-11-17.html">2026-11-17</a>', html)
        self.assertIn("<title>아침 뉴스 · 2026-11-18 (수)</title>", html)

    def test_no_scripts_or_external_loads(self):
        html = page({"산업경제": [Article("A", "AI", "https://a.kr/1", published=NOW)]})
        self.assertIn("default-src 'none'", html)
        self.assertNotIn("script-src", html)
        self.assertNotRegex(html, r"<(script|link|img|iframe)\b")
        self.assertNotRegex(html, r"\ssrc=")
        self.assertEqual(re.findall(r'href="([^"]+)"', html), ["https://a.kr/1", "index.html"])


class WriteSiteTest(unittest.TestCase):
    def args(self, now=NOW):
        return dict(config=CONFIG, chosen={}, stats={}, results=[], now=now)

    def test_daily_file_index_and_archive(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "news"
            out.mkdir()
            (out / "2026-11-16.html").write_text("old", encoding="utf-8")
            (out / "notes.html").write_text("x", encoding="utf-8")
            day, index = write_site(out, **self.args())
            self.assertEqual(day.name, "2026-11-18.html")
            text = index.read_text(encoding="utf-8")
            self.assertLess(text.index("2026-11-18.html"), text.index("2026-11-16.html"))
            self.assertNotIn("notes.html", text)
            write_site(out, **self.args())
            self.assertEqual(sorted(p.name for p in out.iterdir()), ["2026-11-16.html", "2026-11-18.html", "index.html", "notes.html"])

    def test_kst_date_used_for_filename(self):
        with tempfile.TemporaryDirectory() as d:
            day, _ = write_site(Path(d), **self.args(datetime.fromisoformat("2026-11-17T21:40:00+00:00")))
            self.assertEqual(day.name, "2026-11-18.html")


class RunTest(unittest.TestCase):
    def test_end_to_end_with_fake_network(self):
        with tempfile.TemporaryDirectory() as d:
            out = io.StringIO()
            with redirect_stdout(out), redirect_stderr(io.StringIO()):
                code = run(CONFIG, Path(d), NOW, fetcher=fake_fetch, page_fetcher=fake_page, print_text=True)
            self.assertEqual(code, 0)
            html = (Path(d) / "2026-11-18.html").read_text(encoding="utf-8")
            econ = html[html.index('id="panel0"'):html.index('id="panel1"')]
            # 산업경제: 본문 1,800자 > 600자 순. 페이지를 열지 못한 기사(a/3)는 빠짐
            self.assertLess(econ.index("정부, AI 반도체에 1조 투자"), econ.index("날씨: 내일 전국 비"))
            self.assertIn("본문 1,800자", econ)
            self.assertNotIn("guid만 있는 항목", html)
            self.assertIn("정부가 인공지능 반도체 개발에 1조 원을 투자한다. 과기정통부는 18일 이같이 밝혔다.", econ)
            self.assertIn("과학기술 · 고장난곳: https://broken.example.kr/rss", html)
            text = out.getvalue()
            self.assertIn("## 과학기술 (1건)", text)
            self.assertIn("**생성형 AI 규제 법안 국회 통과** (예시방송 · 11/17 23:00 · 본문 2,400자)", text)

    def test_all_feeds_failing_is_an_error(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = dict(CONFIG, topics=[{"name": "x", "feeds": [{"source": "고장난곳", "url": "https://broken.example.kr/rss"}]}])
            self.assertEqual(quiet(run, cfg, Path(d), NOW, fetcher=fake_fetch, page_fetcher=fake_page), 1)
            self.assertEqual(list(Path(d).iterdir()), [])

    def test_check_feeds_report(self):
        out = io.StringIO()
        with redirect_stdout(out):
            code = check_feeds(CONFIG, NOW, fetcher=fake_fetch, page_fetcher=fake_page)
        self.assertEqual(code, 1)
        report = out.getvalue()
        self.assertIn("| 확인 | 산업경제 | 예시신문 | 3 | 3 | 0 | 1,800자 |", report)
        self.assertIn("| 실패 | 과학기술 | 고장난곳 |", report)


class ConfigTest(unittest.TestCase):
    def test_shipped_config(self):
        config = load_config(HERE / "config.json")
        self.assertEqual([t["name"] for t in config["topics"]],
                         ["국내정치", "세계정치", "산업경제", "금융증권", "사회", "문화", "과학기술"])
        self.assertEqual(config["per_topic"], 5)
        urls = [f["url"] for t in config["topics"] for f in t["feeds"]]
        self.assertTrue(all(u.startswith("https://") for u in urls))
        self.assertEqual(len(urls), len(set(urls)))

    def test_invalid_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "c.json"
            for bad in ({"topics": []}, {"topics": [{"name": "a", "feeds": []}]},
                        {"topics": [{"name": "a", "feeds": [{"source": "x", "url": "u"}]}, {"name": "a", "feeds": [{"source": "x", "url": "v"}]}]}):
                p.write_text(json.dumps(bad), encoding="utf-8")
                with self.assertRaises(SystemExit):
                    load_config(p)

    def test_cli(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = Path(d) / "c.json"
            cfg.write_text(json.dumps(CONFIG), encoding="utf-8")
            code = quiet(main, ["--config", str(cfg), "--out", d, "--now", "2026-11-18T06:40:00"],
                         fetcher=fake_fetch, page_fetcher=fake_page)
            self.assertEqual(code, 0)
            self.assertTrue((Path(d) / "2026-11-18.html").exists())


if __name__ == "__main__":
    unittest.main()
