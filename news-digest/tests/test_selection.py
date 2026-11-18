import unittest
from datetime import datetime, timedelta

from newsdigest.feeds import KST, Article
from newsdigest.selection import keyword_pattern, normalize_link, score, select, similarity
from newsdigest.summarize import clean_text, strip_lead, summarize

NOW = datetime(2026, 11, 18, 6, 40, tzinfo=KST)


def art(title, source="A", desc="", hours_ago=1, link=None):
    return Article(source=source, title=title, link=link or f"https://{source}.kr/{abs(hash(title))}",
                   description=desc, published=None if hours_ago is None else NOW - timedelta(hours=hours_ago))


CONFIG = {"keywords": ["AI", "인공지능", "챗GPT"], "window_hours": 24, "max_articles": 15, "per_source_max": 5}


class KeywordTest(unittest.TestCase):
    def test_ascii_keyword_not_inside_english_words(self):
        p = keyword_pattern("AI")
        for text in ["AI 반도체", "생성형AI", "AI·로봇", "(AI)", "ai 시대", "AI2 모델"]:
            self.assertTrue(p.search(text), text)
        for text in ["MAIN 사업", "Thailand 여행", "OpenAI 발표", "SAID"]:
            self.assertFalse(p.search(text), text)

    def test_korean_keyword_substring(self):
        self.assertTrue(keyword_pattern("인공지능").search("인공지능법"))
        self.assertTrue(keyword_pattern("챗GPT").search("오픈AI 챗GPT 새 버전"))

    def test_score_title_beats_body(self):
        kws = [keyword_pattern(k) for k in CONFIG["keywords"]]
        self.assertEqual(score(art("AI 인공지능 소식"), kws), 6)
        self.assertEqual(score(art("경제 소식", desc="인공지능 언급"), kws), 1)
        self.assertEqual(score(art("AI 소식", desc="AI 또"), kws), 3)  # 한 키워드는 한 번만
        self.assertEqual(score(art("날씨"), kws), 0)


class HelpersTest(unittest.TestCase):
    def test_normalize_link(self):
        self.assertEqual(normalize_link("https://www.A.kr/news/1/"), normalize_link("http://a.kr/news/1"))
        self.assertNotEqual(normalize_link("https://a.kr/v?id=1"), normalize_link("https://a.kr/v?id=2"))

    def test_similarity(self):
        self.assertGreaterEqual(similarity("정부, AI 반도체에 1조 투자", "정부 AI반도체 1조 투자한다"), 0.5)
        self.assertLess(similarity("정부, AI 반도체에 1조 투자", "챗GPT 새 버전 공개"), 0.5)


class SummarizeTest(unittest.TestCase):
    def test_clean_text(self):
        self.assertEqual(clean_text("<p>A&amp;amp;B</p>\n<br>  C"), "A&B C")

    def test_strip_lead(self):
        self.assertEqual(strip_lead("(서울=연합뉴스) 홍길동 기자 = 정부가 발표했다."), "정부가 발표했다.")
        self.assertEqual(strip_lead("[앵커] [리포트] 오늘 소식입니다."), "오늘 소식입니다.")
        self.assertEqual(strip_lead("◀ 앵커 ▶ 오늘 소식입니다."), "오늘 소식입니다.")
        self.assertEqual(strip_lead("(워싱턴=연합뉴스) 김철수 특파원 = 미국이"), "미국이")
        self.assertEqual(strip_lead("세율 = 10% 로 정했다."), "세율 = 10% 로 정했다.")  # 기자 표기 아님

    def test_two_sentences(self):
        s = summarize("<p>(서울=연합뉴스) 홍길동 기자 = 첫 문장이다. 둘째 문장이다. 셋째 문장이다.</p>")
        self.assertEqual(s, "첫 문장이다. 둘째 문장이다.")

    def test_sentence_without_space(self):
        self.assertEqual(summarize("성적을 믿기 어렵다고 답했다.특히 감독을 강화해야 한다. 셋째다."),
                         "성적을 믿기 어렵다고 답했다. 특히 감독을 강화해야 한다.")
        self.assertEqual(summarize("금리는 1.5%다. 둘째다. 셋째다."), "금리는 1.5%다. 둘째다.")

    def test_truncate_and_empty(self):
        s = summarize("가" * 500)
        self.assertEqual(len(s), 200)
        self.assertTrue(s.endswith("…"))
        self.assertEqual(summarize(""), "")
        self.assertEqual(summarize("<b>제목과 같음</b>", "제목과 같음"), "")


class SelectTest(unittest.TestCase):
    def test_window_and_undated(self):
        arts = [art("AI 새 소식", hours_ago=2), art("AI 옛 소식", hours_ago=30), art("AI 날짜 없음", hours_ago=None),
                art("AI 미래 시각", hours_ago=-3), art("AI 5분 뒤", hours_ago=-1/12)]
        chosen, stats = select(arts, CONFIG, NOW)
        self.assertEqual([a.title for a in chosen], ["AI 새 소식"])
        self.assertEqual((stats.total, stats.undated, stats.in_window, stats.matched, stats.selected), (5, 1, 1, 1, 1))

    def test_undated_recent_source_included(self):
        cfg = dict(CONFIG, sources=[{"name": "H", "feeds": ["x"], "undated": "recent"}, {"name": "A", "feeds": ["y"]}])
        arts = [art("AI 날짜 없음 H", source="H", hours_ago=None), art("AI 날짜 없음 A", source="A", hours_ago=None),
                art("인공지능 새 정책 발표", source="A", hours_ago=3)]
        chosen, stats = select(arts, cfg, NOW)
        self.assertEqual(sorted(a.title for a in chosen), ["AI 날짜 없음 H", "인공지능 새 정책 발표"])
        self.assertEqual(stats.undated, 2)

    def test_off_topic_and_excluded(self):
        cfg = dict(CONFIG, exclude_keywords=["광고"])
        arts = [art("날씨 소식"), art("AI 광고 안내"), art("인공지능 정책")]
        chosen, _ = select(arts, cfg, NOW)
        self.assertEqual([a.title for a in chosen], ["인공지능 정책"])

    def test_same_link_counted_once(self):
        arts = [art("AI 정책", link="https://www.a.kr/1"), art("AI 정책(종합)", link="http://a.kr/1/")]
        chosen, stats = select(arts, CONFIG, NOW)
        self.assertEqual(len(chosen), 1)
        self.assertEqual(stats.matched, 1)

    def test_similar_titles_grouped_and_ranked_first(self):
        arts = [
            art("챗GPT 새 버전 공개", source="A", hours_ago=1),
            art("정부, AI 반도체에 1조 투자", source="A", hours_ago=5, desc="인공지능 반도체"),
            art("정부 AI반도체 1조 투자한다", source="B", hours_ago=4),
            art("정부, AI 반도체 1조 투자 발표", source="C", hours_ago=3),
            art("정부, AI 반도체에 1조 투자", source="A", hours_ago=2, link="https://A.kr/dup-other-link"),
        ]
        chosen, _ = select(arts, CONFIG, NOW)
        self.assertEqual(len(chosen), 2)
        top = chosen[0]
        self.assertEqual(top.title, "정부, AI 반도체에 1조 투자")
        self.assertEqual(top.description, "인공지능 반도체")  # 점수 높은 것이 대표
        self.assertEqual(sorted(top.also), ["B", "C"])  # 같은 언론사는 다시 적지 않음
        self.assertEqual(chosen[1].title, "챗GPT 새 버전 공개")

    def test_limits(self):
        arts = [art(f"AI 소식 {chr(0xAC00 + i * 50)}{chr(0xAC00 + i * 97)}", source="A" if i < 8 else "B", hours_ago=i % 20 + 1)
                for i in range(12)]
        chosen, _ = select(arts, dict(CONFIG, per_source_max=3, max_articles=5), NOW)
        self.assertEqual([a.source for a in chosen].count("A"), 3)
        self.assertEqual(len(chosen), 5)

    def test_summary_filled(self):
        chosen, _ = select([art("AI 소식", desc="(서울=연합뉴스) 홍길동 기자 = 하나다. 둘이다. 셋이다.")], CONFIG, NOW)
        self.assertEqual(chosen[0].summary, "하나다. 둘이다.")


if __name__ == "__main__":
    unittest.main()
