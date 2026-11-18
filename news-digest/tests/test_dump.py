import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from newsdigest.__main__ import run
from newsdigest.dump import dump_results, read_dump, write_dump
from newsdigest.feeds import collect
from tests.test_render_main import CONFIG, NOW, fake_fetch


class DumpTest(unittest.TestCase):
    def test_only_topic_articles_keep_text(self):
        results = collect(CONFIG["sources"], fetcher=fake_fetch)
        data = dump_results(results, CONFIG)
        items = data["feeds"][0]["articles"]
        self.assertEqual(items[0]["t"], "정부, AI 반도체에 1조 투자")
        self.assertEqual(set(items[1]), {"p"})  # 날씨 기사는 시각만
        self.assertEqual(data["feeds"][2]["error"], "OSError: connection refused")

    def test_from_dump_gives_same_page_as_live(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            with redirect_stdout(io.StringIO()):
                run(CONFIG, d / "live", NOW, fetcher=fake_fetch, dump=d / "raw.json")

                def no_network(url):
                    raise AssertionError("dump 사용 시 접속하면 안 됨")

                run(CONFIG, d / "again", NOW, fetcher=no_network, from_dump=d / "raw.json")
            name = "2026-11-18.html"
            self.assertEqual((d / "live" / name).read_text(encoding="utf-8"), (d / "again" / name).read_text(encoding="utf-8"))

    def test_roundtrip_dates(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "raw.json"
            results = collect(CONFIG["sources"], fetcher=fake_fetch)
            write_dump(p, results, CONFIG)
            back = read_dump(p)
            self.assertEqual([a.published for a in back[0].articles], [a.published for a in results[0].articles])

    def test_print_text(self):
        with tempfile.TemporaryDirectory() as d:
            out = io.StringIO()
            with redirect_stdout(out):
                run(CONFIG, Path(d), NOW, fetcher=fake_fetch, print_text=True)
            text = out.getvalue()
            self.assertIn("# AI(인공지능) 아침 뉴스 · 2026-11-18 (수) · 2건", text)
            self.assertIn("**정부, AI 반도체에 1조 투자** (예시신문 · 11/17 23:10)", text)
            self.assertIn("   https://news.example.kr/a/1", text)
            self.assertIn("가져오지 못한 곳: 고장난곳", text)


if __name__ == "__main__":
    unittest.main()
