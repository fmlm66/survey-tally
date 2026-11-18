import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from newsdigest.__main__ import run
from newsdigest.dump import read_dump
from tests.test_render_main import CONFIG, NOW, fake_fetch, fake_page


def no_network(url):
    raise AssertionError("저장 파일을 쓸 때는 접속하면 안 됨")


class DumpTest(unittest.TestCase):
    def test_from_dump_gives_same_page_as_live(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            with redirect_stdout(io.StringIO()):
                run(CONFIG, d / "live", NOW, fetcher=fake_fetch, page_fetcher=fake_page, dump=d / "raw.json")
                run(CONFIG, d / "again", NOW, fetcher=no_network, page_fetcher=no_network, from_dump=d / "raw.json")
            name = "2026-11-18.html"
            self.assertEqual((d / "live" / name).read_text(encoding="utf-8"), (d / "again" / name).read_text(encoding="utf-8"))

    def test_only_measured_articles_keep_text(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "raw.json"
            with redirect_stdout(io.StringIO()):
                run(CONFIG, Path(d), NOW, fetcher=fake_fetch, page_fetcher=fake_page, dump=p)
            data = json.loads(p.read_text(encoding="utf-8"))
            self.assertEqual(data["version"], 2)
            items = data["feeds"][0]["articles"]
            self.assertEqual((items[0]["t"], items[0]["b"]), ("정부, AI 반도체에 1조 투자", 1800))
            self.assertIsNone(items[2]["b"])  # 페이지를 못 연 기사
            self.assertEqual(set(data["feeds"][1]["articles"][0]), {"t", "l", "d", "p", "b", "pd"})
            self.assertEqual(data["feeds"][2]["error"], "OSError: connection refused")
            back, headlines = read_dump(p)
            self.assertEqual(back[0].articles[0].body_chars, 1800)
            self.assertEqual(headlines, frozenset())

    def test_unmeasured_articles_keep_only_time(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "raw.json"
            with redirect_stdout(io.StringIO()):
                run(dict(CONFIG, max_fetch_per_topic=1), Path(d), NOW, fetcher=fake_fetch, page_fetcher=fake_page, dump=p)
            items = json.loads(p.read_text(encoding="utf-8"))["feeds"][0]["articles"]
            self.assertEqual([set(i) == {"p"} for i in items].count(True), 2)

    def test_from_dump_keeps_counts_of_unmeasured_articles(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            cfg = dict(CONFIG, max_fetch_per_topic=1)
            live, again = io.StringIO(), io.StringIO()
            with redirect_stdout(live):
                run(cfg, d / "live", NOW, fetcher=fake_fetch, page_fetcher=fake_page, dump=d / "raw.json")
            with redirect_stdout(again):
                run(cfg, d / "again", NOW, from_dump=d / "raw.json")
            pick = lambda out: [l for l in out.getvalue().splitlines() if ": 기사" in l]
            self.assertEqual(pick(live), pick(again))
            self.assertIn("산업경제: 기사 3 → 기간 안 3 → 본문 1/1 → 1건", pick(live))
            name = "2026-11-18.html"
            self.assertEqual((d / "live" / name).read_text(encoding="utf-8"), (d / "again" / name).read_text(encoding="utf-8"))

    def test_from_dump_ignores_removed_feeds(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            with redirect_stdout(io.StringIO()):
                run(CONFIG, d, NOW, fetcher=fake_fetch, page_fetcher=fake_page, dump=d / "raw.json")
                cfg = dict(CONFIG, topics=CONFIG["topics"][:1])
                run(cfg, d / "x", NOW, from_dump=d / "raw.json")
            html = (d / "x" / "2026-11-18.html").read_text(encoding="utf-8")
            self.assertNotIn("예시방송", html)
            self.assertNotIn("고장난곳", html)

    def test_old_version_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "old.json"
            p.write_text('{"version":1,"feeds":[]}', encoding="utf-8")
            with self.assertRaises(ValueError):
                read_dump(p)


if __name__ == "__main__":
    unittest.main()
