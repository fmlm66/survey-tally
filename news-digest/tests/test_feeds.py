import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from newsdigest.feeds import KST, collect, parse_date, parse_feed

FIX = Path(__file__).parent / "fixtures"


def read(name):
    return (FIX / name).read_bytes()


class ParseFeedTest(unittest.TestCase):
    def test_rss2(self):
        arts = parse_feed(read("rss2.xml"), "예시신문")
        self.assertEqual([a.title for a in arts], ["정부, AI 반도체에 1조 투자", "날씨: 내일 전국 비", "guid만 있는 항목"])
        first = arts[0]
        self.assertEqual(first.source, "예시신문")
        self.assertEqual(first.link, "https://news.example.kr/a/1")
        self.assertIn("1조 원을 투자한다", first.description)
        self.assertEqual(first.published, datetime(2026, 11, 17, 23, 10, tzinfo=KST))
        self.assertEqual(arts[1].published, datetime(2026, 11, 17, 21, 0, tzinfo=KST))  # dc:date
        self.assertEqual(arts[2].link, "https://news.example.kr/a/3")  # guid로 대신
        self.assertEqual(arts[2].published, datetime(2026, 11, 17, 20, 0, tzinfo=KST))  # 시간대 없음 → KST

    def test_atom_prefers_alternate_link(self):
        (a,) = parse_feed(read("atom.xml"), "예시방송")
        self.assertEqual(a.title, "생성형 AI 규제 법안 국회 통과")
        self.assertEqual(a.link, "https://tv.example.kr/news/10")
        self.assertEqual(a.published, datetime(2026, 11, 17, 14, 0, tzinfo=timezone.utc))
        self.assertIn("인공지능 기본법", a.description)

    def test_euckr_and_bare_ampersand(self):
        (a,) = parse_feed(read("euckr_amp.xml"), "옛신문")
        self.assertEqual(a.title, "인공지능 R&D 예산 증액")
        self.assertEqual(a.link, "https://old.example.kr/view?id=1&sec=2")

    def test_garbage_raises(self):
        with self.assertRaises(Exception):
            parse_feed(b"<html><body>not a feed", "x")


class ParseDateTest(unittest.TestCase):
    def test_formats(self):
        utc = timezone.utc
        self.assertEqual(parse_date("Tue, 17 Nov 2026 10:00:00 GMT"), datetime(2026, 11, 17, 10, tzinfo=utc))
        self.assertEqual(parse_date("2026-11-17T10:00:00Z"), datetime(2026, 11, 17, 10, tzinfo=utc))
        self.assertEqual(parse_date("2026-11-17T19:00:00+09:00"), datetime(2026, 11, 17, 10, tzinfo=utc))
        self.assertEqual(parse_date("2026.11.17 19:00"), datetime(2026, 11, 17, 19, tzinfo=KST))
        self.assertEqual(parse_date(" 2026-11-17 19:00:00 ").utcoffset(), timedelta(hours=9))

    def test_date_only(self):
        self.assertEqual(parse_date("2024.10.29"), datetime(2024, 10, 29, tzinfo=KST))
        self.assertEqual(parse_date("2026-11-18"), datetime(2026, 11, 18, tzinfo=KST))

    def test_unreadable(self):
        for text in ("", None, "어제", "17/11/2026"):
            self.assertIsNone(parse_date(text), text)


class CollectTest(unittest.TestCase):
    def test_topics_and_one_failure_does_not_stop_others(self):
        def fetcher(url):
            if "bad" in url:
                raise OSError("timed out")
            return read("rss2.xml")

        config = {"topics": [
            {"name": "정치", "feeds": [{"source": "A", "url": "https://a/rss"}, {"source": "A", "url": "https://a/bad"}]},
            {"name": "경제", "feeds": [{"source": "B", "url": "https://b/rss"}]},
        ]}
        results = collect(config, fetcher=fetcher)
        self.assertEqual([(r.topic, r.source, r.error is None, len(r.articles)) for r in results],
                         [("정치", "A", True, 3), ("정치", "A", False, 0), ("경제", "B", True, 3)])
        self.assertIn("timed out", results[1].error)
        self.assertEqual({a.topic for a in results[2].articles}, {"경제"})

if __name__ == "__main__":
    unittest.main()
