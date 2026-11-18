import unittest
from datetime import datetime
from pathlib import Path

from newsdigest.article import count_chars, decode_html, parse_article
from newsdigest.feeds import KST

PAGES = Path(__file__).parent / "fixtures" / "pages"
SENTENCE = "정부가 오늘 새 정책을 발표했다. "
BODY = count_chars(SENTENCE * 20)  # 문단 하나의 글자 수(공백 제외)


def page(name):
    return decode_html((PAGES / name).read_bytes())


class ArticleTest(unittest.TestCase):
    def test_paragraphs_ignore_menus_links_captions_ads(self):
        info = parse_article(page("paragraphs.html"))
        # 본문 문단 둘 + "관련 기사:"(링크 글자는 빼고)
        self.assertEqual(info.body_chars, 2 * BODY + count_chars("관련 기사:"))
        self.assertEqual(info.description, "정부가 새 정책을 발표했다.")
        self.assertEqual(info.published, datetime(2026, 11, 18, 9, 30, tzinfo=KST))

    def test_paragraphs_in_divs(self):
        self.assertEqual(parse_article(page("div_paragraphs.html")).body_chars, 3 * BODY)

    def test_ld_json_article_body(self):
        info = parse_article(page("ldjson.html"))
        self.assertEqual(info.body_chars, 1234)
        self.assertEqual(info.description, "구조화 소개문")
        self.assertEqual(info.published, datetime(2026, 11, 18, 7, 0, tzinfo=KST))

    def test_euckr_table_layout_and_unclosed_tags(self):
        html = page("table_layout.html")
        self.assertIn("정부가", html)
        # 바깥 블록이 메뉴 칸 등 작은 글자를 조금 더 모을 수 있다(순위에는 영향 미미)
        self.assertTrue(2 * BODY <= parse_article(html).body_chars <= 2 * BODY + 40)

    def test_arc_page_data(self):
        # 본문이 화면이 아니라 스크립트 데이터에 있는 페이지(조선일보 등): text 항목만 센다
        self.assertEqual(parse_article(page("arc.html")).body_chars, 2 * BODY)

    def test_data_table_is_not_body(self):
        # 숫자 표(300줄)만 긴 페이지: 표 칸 글자는 세지 않아 옆 상자(120자) 정도만 남는다
        self.assertLess(parse_article(page("datatable.html")).body_chars or 0, 200)

    def test_no_body(self):
        info = parse_article(page("nobody.html"))
        self.assertIsNone(info.body_chars)
        self.assertIsNone(info.published)

    def test_garbage_does_not_raise(self):
        self.assertIsNone(parse_article("<div><<<>>></p></span>").body_chars)
        self.assertIsNone(parse_article("").body_chars)

    def test_decode(self):
        self.assertEqual(decode_html("한글".encode("cp949")), "한글")
        self.assertEqual(decode_html("한글".encode("utf-8"), "utf-8"), "한글")
        self.assertEqual(decode_html("한글".encode("utf-8"), "bogus-charset"), "한글")


if __name__ == "__main__":
    unittest.main()
