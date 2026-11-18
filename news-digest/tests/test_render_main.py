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
from newsdigest.render import render_page, write_site
from newsdigest.selection import Stats

NOW = datetime(2026, 11, 18, 6, 40, tzinfo=KST)
FIX = Path(__file__).parent / "fixtures"
CONFIG = {"topic": "AI(인공지능)", "keywords": ["AI", "인공지능", "생성형"], "window_hours": 24,
          "sources": [{"name": "예시신문", "feeds": ["https://news.example.kr/rss"]},
                      {"name": "예시방송", "feeds": ["https://tv.example.kr/atom"]},
                      {"name": "고장난곳", "feeds": ["https://broken.example.kr/rss"]}]}


def fake_fetch(url):
    if "broken" in url:
        raise OSError("connection refused")
    return (FIX / ("atom.xml" if "atom" in url else "rss2.xml")).read_bytes()


def quiet(fn, *a, **kw):
    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        return fn(*a, **kw)


class RenderTest(unittest.TestCase):
    def page(self, articles, results=None, archive=None):
        results = results or [FeedResult("A", "https://a/rss", [])]
        return render_page(config=CONFIG, articles=articles, stats=Stats(total=3, in_window=2, matched=1, selected=len(articles)),
                           results=results, now=NOW, archive=archive)

    def test_escapes_and_links(self):
        a = Article("A<b>", "AI <script>alert(1)</script> &amp; 소식", 'https://a.kr/1?x=1&y="2"',
                    published=NOW - timedelta(hours=1), summary="<img src=x onerror=alert(1)>", also=["B&C"])
        html = self.page([a])
        self.assertNotIn("<script>", html)
        self.assertNotIn("<img", html)
        self.assertIn('href="https://a.kr/1?x=1&amp;y=&quot;2&quot;"', html)
        self.assertIn(">AI alert(1) &amp; 소식</a>", html)  # 태그는 지우고 &amp;는 풀어서 다시 이스케이프
        self.assertIn("A&lt;b&gt; · 05:40 · 같은 소식: B&amp;C", html)

    def test_unsafe_link_not_linked(self):
        a = Article("A", "AI 소식", "javascript:alert(1)", published=NOW)
        self.assertNotIn("javascript:", self.page([a]))

    def test_undated_article(self):
        self.assertIn("A · 시각 미표기", self.page([Article("A", "AI 소식", "https://a.kr/1")]))

    def test_time_from_previous_day(self):
        a = Article("A", "AI 소식", "https://a.kr/1", published=datetime(2026, 11, 17, 23, 10, tzinfo=KST))
        self.assertIn("A · 11/17 23:10", self.page([a]))

    def test_empty_and_failures_and_archive(self):
        html = self.page([], results=[FeedResult("A", "https://a/rss", []), FeedResult("B", "https://b/rss", [], "OSError")],
                         archive=["2026-11-18", "2026-11-17"])
        self.assertIn("새 기사가 없습니다", html)
        self.assertIn("가져오지 못한 곳</p><ul><li>B: https://b/rss</li>", html)
        self.assertIn('<a href="2026-11-17.html">2026-11-17</a>', html)
        self.assertIn("<title>AI(인공지능) 아침 뉴스 · 2026-11-18 (수)</title>", html)

    def test_page_loads_nothing_external(self):
        html = self.page([Article("A", "AI", "https://a.kr/1", published=NOW)])
        self.assertIn("default-src 'none'", html)
        self.assertNotRegex(html, r"<(script|link|img|iframe)\b")
        self.assertNotRegex(html, r"\ssrc=")
        self.assertEqual(re.findall(r'href="([^"]+)"', html), ["https://a.kr/1", "index.html"])


class WriteSiteTest(unittest.TestCase):
    def test_daily_file_index_and_archive(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "news"
            out.mkdir()
            (out / "2026-11-16.html").write_text("old", encoding="utf-8")
            (out / "notes.html").write_text("x", encoding="utf-8")
            args = dict(config=CONFIG, articles=[], stats=Stats(), results=[FeedResult("A", "u", [])], now=NOW)
            day, index = write_site(out, **args)
            self.assertEqual(day.name, "2026-11-18.html")
            text = index.read_text(encoding="utf-8")
            self.assertLess(text.index("2026-11-18.html"), text.index("2026-11-16.html"))
            self.assertNotIn("notes.html", text)
            self.assertIn('href="index.html"', day.read_text(encoding="utf-8"))
            write_site(out, **args)  # 같은 날 다시 돌려도 파일이 늘지 않는다
            self.assertEqual(sorted(p.name for p in out.iterdir()), ["2026-11-16.html", "2026-11-18.html", "index.html", "notes.html"])

    def test_kst_date_used_for_filename(self):
        with tempfile.TemporaryDirectory() as d:
            utc_evening = datetime.fromisoformat("2026-11-17T21:40:00+00:00")  # 한국은 11/18 06:40
            day, _ = write_site(Path(d), config=CONFIG, articles=[], stats=Stats(), results=[], now=utc_evening)
            self.assertEqual(day.name, "2026-11-18.html")


class RunTest(unittest.TestCase):
    def test_end_to_end_with_fake_feeds(self):
        with tempfile.TemporaryDirectory() as d:
            code = quiet(run, CONFIG, Path(d), NOW, fetcher=fake_fetch)
            self.assertEqual(code, 0)
            html = (Path(d) / "2026-11-18.html").read_text(encoding="utf-8")
            self.assertIn("정부, AI 반도체에 1조 투자", html)
            self.assertIn("정부가 인공지능 반도체 개발에 1조 원을 투자한다. 과기정통부는 18일 이같이 밝혔다.", html)
            self.assertNotIn("세부 계획은", html)  # 셋째 문장은 빠짐
            self.assertNotIn("홍길동 기자", html)
            self.assertIn("생성형 AI 규제 법안 국회 통과", html)
            self.assertNotIn("날씨", html.split("<footer>")[0])  # 주제 밖
            self.assertIn("고장난곳: https://broken.example.kr/rss", html)

    def test_all_feeds_failing_is_an_error(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = dict(CONFIG, sources=[CONFIG["sources"][2]])
            self.assertEqual(quiet(run, cfg, Path(d), NOW, fetcher=fake_fetch), 1)
            self.assertEqual(list(Path(d).iterdir()), [])

    def test_check_feeds_report(self):
        out = io.StringIO()
        with redirect_stdout(out):
            code = check_feeds(CONFIG, NOW, fetcher=fake_fetch)
        self.assertEqual(code, 1)
        report = out.getvalue()
        self.assertIn("| 확인 | 예시신문 | 3 | 3 | 0 |", report)
        self.assertIn("| 실패 | 고장난곳 |", report)


class ConfigTest(unittest.TestCase):
    def test_shipped_config_is_valid(self):
        config = load_config(HERE / "config.json")
        self.assertTrue(all(url.startswith("https://") or url.startswith("http://")
                            for s in config["sources"] for url in s["feeds"]))
        self.assertEqual(len({s["name"] for s in config["sources"]}), len(config["sources"]))

    def test_missing_fields_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "c.json"
            p.write_text(json.dumps({"topic": "x", "keywords": [], "sources": []}), encoding="utf-8")
            with self.assertRaises(SystemExit):
                load_config(p)

    def test_cli_now_option(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = Path(d) / "c.json"
            cfg.write_text(json.dumps(dict(CONFIG, sources=[CONFIG["sources"][2]])), encoding="utf-8")
            self.assertEqual(quiet(main, ["--config", str(cfg), "--out", d, "--now", "2026-11-18T06:40:00"],
                                   fetcher=fake_fetch), 1)
            ok = Path(d) / "ok.json"
            ok.write_text(json.dumps(CONFIG), encoding="utf-8")
            self.assertEqual(quiet(main, ["--config", str(ok), "--out", d, "--now", "2026-11-18T06:40:00"],
                                   fetcher=fake_fetch), 0)
            self.assertTrue((Path(d) / "2026-11-18.html").exists())


if __name__ == "__main__":
    unittest.main()
