import unittest
from datetime import datetime, timedelta

from newsdigest.feeds import KST, Article
from newsdigest.selection import group_similar, normalize_link, plan_fetch, select, similarity
from newsdigest.summarize import clean_text, strip_lead, summarize

NOW = datetime(2026, 11, 18, 6, 40, tzinfo=KST)
_n = iter(range(10**6))


def art(title, source="A", topic="정치", hours_ago=1, body=None, desc="", link=None):
    a = Article(source=source, title=title, link=link or f"https://{source}.kr/{next(_n)}", description=desc,
                published=None if hours_ago is None else NOW - timedelta(hours=hours_ago), topic=topic)
    a._body = body  # 가짜 측정에서 쓸 본문 길이
    return a


def fake_measure(arts):
    for a in arts:
        a.measured = True
        a.body_chars = a._body


CONFIG = {"topics": [{"name": "정치", "feeds": []}, {"name": "경제", "feeds": []}],
          "window_hours": 24, "per_topic": 2, "max_fetch_per_topic": 10}


class HelpersTest(unittest.TestCase):
    def test_normalize_link(self):
        self.assertEqual(normalize_link("https://www.A.kr/news/1/"), normalize_link("http://a.kr/news/1"))
        self.assertNotEqual(normalize_link("https://a.kr/v?id=1"), normalize_link("https://a.kr/v?id=2"))

    def test_similarity(self):
        same = [("정부, AI 반도체에 1조 투자", "정부 AI반도체 1조 투자한다"),
                ('KPMG, AI로 영국 기업 첫 감사…"회계사보다 깊이 파고들어"', 'KPMG, AI로 英상장사 첫 감사…"회계사보다 더 깊이있는 질문해"'),
                ("AI앱 ‘피클’, 인공지능 부정행위 우려에 “수능 시간 동안 이미지 입력 제한”", "피클, 수능시간에 이미지 입력 제한한다…AI 수능 악용 차단")]
        different = [("정부, AI 반도체에 1조 투자", "챗GPT 새 버전 공개"),
                     ("‘AI 커닝’ 2년전부터 국가시험서 적발…스마트안경은 올해 첫 사례", "경찰, ‘AI 커닝’ 세무사 수석 합격자 압수수색"),
                     ("삼성 스마트싱스도 챗GPT 연동…AI로 가전 제어 확산", "【独自】「AI眼鏡で試験合格、両親も知らず」相次ぐカンニング自白"),
                     ("AI", "AI 반도체 수출")]
        for a, b in same:
            self.assertGreaterEqual(similarity(a, b), 0.45, (a, b))
        for a, b in different:
            self.assertLess(similarity(a, b), 0.45, (a, b))

    def test_plan_fetch_round_robin_newest_first(self):
        arts = [art("a1", "A", hours_ago=5), art("a2", "A", hours_ago=1), art("a3", "A", hours_ago=3),
                art("b1", "B", hours_ago=2), art("c1", "C", hours_ago=None)]
        self.assertEqual([a.title for a in plan_fetch(arts, 4)], ["a2", "b1", "c1", "a3"])

    def test_group_similar(self):
        g = group_similar([art("정부, AI 반도체에 1조 투자"), art("챗GPT 새 버전 공개"), art("정부 AI반도체 1조 투자한다")])
        self.assertEqual([len(x) for x in g], [2, 1])


class SummarizeTest(unittest.TestCase):
    def test_clean_text(self):
        self.assertEqual(clean_text("<p>A&amp;amp;B</p>\n<br>  C"), "A&B C")

    def test_strip_lead(self):
        self.assertEqual(strip_lead("(서울=연합뉴스) 홍길동 기자 = 정부가 발표했다."), "정부가 발표했다.")
        self.assertEqual(strip_lead("[앵커] [리포트] 오늘 소식입니다."), "오늘 소식입니다.")
        self.assertEqual(strip_lead("◀ 앵커 ▶ 오늘 소식입니다."), "오늘 소식입니다.")
        self.assertEqual(strip_lead("(워싱턴=연합뉴스) 김철수 특파원 = 미국이"), "미국이")
        self.assertEqual(strip_lead("세율 = 10% 로 정했다."), "세율 = 10% 로 정했다.")

    def test_two_sentences(self):
        self.assertEqual(summarize("<p>(서울=연합뉴스) 홍길동 기자 = 첫 문장이다. 둘째 문장이다. 셋째 문장이다.</p>"),
                         "첫 문장이다. 둘째 문장이다.")

    def test_sentence_without_space(self):
        self.assertEqual(summarize("성적을 믿기 어렵다고 답했다.특히 감독을 강화해야 한다. 셋째다."),
                         "성적을 믿기 어렵다고 답했다. 특히 감독을 강화해야 한다.")
        self.assertEqual(summarize("금리는 1.5%다. 둘째다. 셋째다."), "금리는 1.5%다. 둘째다.")

    def test_description_repeating_title_and_byline(self):
        # 한국경제 소개문 꼴: "제목, 부제, 기자, 섹션"
        title = "800조 반도체가 바꿀 대한민국 지도…'첨단산업 새 심장'이 뛴다"
        self.assertEqual(summarize(f"{title}, 삼성·SK하이닉스 팹 4기 이상 조성", title), "삼성·SK하이닉스 팹 4기 이상 조성")
        self.assertEqual(summarize(f"{title}, 최수진 기자, 사회", title), "")
        self.assertEqual(summarize("법원이 기각했다. 수험생은 항고했다., 최수진 기자, 사회", "다른 제목"),
                         "법원이 기각했다. 수험생은 항고했다.")

    def test_truncate_and_empty(self):
        s = summarize("가" * 500)
        self.assertEqual(len(s), 200)
        self.assertTrue(s.endswith("…"))
        self.assertEqual(summarize(""), "")
        self.assertEqual(summarize("<b>제목과 같음</b>", "제목과 같음"), "")


class MeasureTest(unittest.TestCase):
    def test_per_host_limit_and_failures(self):
        import threading
        import time
        from newsdigest.selection import measure_pages

        active, peak, lock = {}, {}, threading.Lock()

        def fetcher(url):
            host = url.split("/")[2]
            with lock:
                active[host] = active.get(host, 0) + 1
                peak[host] = max(peak.get(host, 0), active[host])
            time.sleep(0.02)
            with lock:
                active[host] -= 1
            if url.endswith("/bad"):
                raise OSError("404")
            return "<div>" + "가" * 300 + "</div>"

        arts = [art(f"기사 {i}", source="A", link=f"https://a.kr/{i}") for i in range(10)]
        arts += [art(f"기사 b{i}", source="B", link=f"https://b.kr/{i}") for i in range(5)]
        arts.append(art("못 여는 기사", source="B", link="https://b.kr/bad"))
        measure_pages(arts, fetcher=fetcher, workers=8, per_host=2)
        self.assertLessEqual(max(peak.values()), 2)
        self.assertTrue(all(a.measured for a in arts))
        self.assertEqual([a.body_chars for a in arts[:15]], [300] * 15)
        self.assertIsNone(arts[-1].body_chars)


class SelectTest(unittest.TestCase):
    def run_select(self, arts, **cfg):
        return select(arts, dict(CONFIG, **cfg), NOW, measure=fake_measure)

    def test_longest_bodies_per_topic(self):
        arts = [art("국회 예산안 처리 합의", body=800), art("대통령 순방 출국", body=2500, source="B"),
                art("여야 대표 회동 무산", body=1500), art("선거구 획정 논의 착수", body=None),
                art("환율 급등 수출 비상", topic="경제", body=3000), art("반도체 수출 증가", topic="경제", body=100)]
        chosen, stats = self.run_select(arts)
        self.assertEqual([a.title for a in chosen["정치"]], ["대통령 순방 출국", "여야 대표 회동 무산"])
        self.assertEqual([a.title for a in chosen["경제"]], ["환율 급등 수출 비상", "반도체 수출 증가"])
        st = stats["정치"]
        self.assertEqual((st.total, st.in_window, st.measured, st.with_body, st.selected), (4, 4, 4, 3, 2))

    def test_window_and_future(self):
        arts = [art("최근 기사 하나", body=500), art("어제보다 전 기사", hours_ago=30, body=9000),
                art("기준 시각 뒤 기사", hours_ago=-0.1, body=9000), art("날짜 없는 기사", hours_ago=None, body=9000)]
        chosen, _ = self.run_select(arts)
        self.assertEqual([a.title for a in chosen["정치"]], ["최근 기사 하나"])

    def test_undated_recent_source_and_page_date(self):
        arts = [art("날짜 없는 한겨레 기사", source="H", hours_ago=None, body=900),
                art("페이지 날짜가 오래된 기사", source="H", hours_ago=None, body=5000)]

        def measure(items):
            fake_measure(items)
            items[1].published = NOW - timedelta(days=3)  # 기사 페이지에서 읽은 발행 시각

        chosen, _ = select(arts, dict(CONFIG, sources={"H": {"undated": "recent"}}), NOW, measure=measure)
        self.assertEqual([a.title for a in chosen["정치"]], ["날짜 없는 한겨레 기사"])

    def test_same_story_keeps_longest_and_lists_others(self):
        arts = [art("정부, AI 반도체에 1조 투자", source="A", body=900),
                art("정부 AI반도체 1조 투자한다", source="B", body=2000),
                art("정부, AI 반도체 1조 투자 발표", source="C", body=1200),
                art("정부, AI 반도체에 1조 투자(종합)", source="B", body=1000),
                art("챗GPT 새 버전 공개", source="A", body=1500)]
        chosen, _ = self.run_select(arts)
        top = chosen["정치"][0]
        self.assertEqual((top.source, top.body_chars), ("B", 2000))
        self.assertEqual(sorted(top.also), ["A", "C"])
        self.assertEqual(chosen["정치"][1].title, "챗GPT 새 버전 공개")

    def test_same_link_in_two_topics_goes_to_first(self):
        arts = [art("환율 급등", topic="경제", link="https://a.kr/1", body=900),
                art("환율 급등", topic="정치", link="https://www.a.kr/1/", body=900)]
        chosen, stats = self.run_select(arts)
        self.assertEqual(len(chosen["정치"]), 1)
        self.assertEqual(chosen["경제"], [])
        self.assertEqual(stats["경제"].in_window, 0)

    def test_exclude_titles(self):
        arts = [art("[표] 코스피 시세표", body=9000), art("[인사] 기획재정부", body=9000), art("국회 예산안 처리", body=500)]
        chosen, stats = self.run_select(arts, exclude_titles=[r"^\[(표|인사)\]"])
        self.assertEqual([a.title for a in chosen["정치"]], ["국회 예산안 처리"])
        self.assertEqual(stats["정치"].in_window, 1)

    def test_fetch_limit(self):
        titles = ["국회 예산 처리", "대통령 해외 순방", "여야 대표 회동", "선거구 획정 착수", "지방선거 공천 갈등",
                  "개헌 논의 재점화", "국정감사 일정 확정", "총리 인사청문회", "정당 지지율 조사", "외교부 장관 발언"]
        arts = [art(t, hours_ago=i + 1, body=100 * (i + 1)) for i, t in enumerate(titles)]
        chosen, stats = self.run_select(arts, max_fetch_per_topic=3)
        self.assertEqual(stats["정치"].measured, 3)
        self.assertEqual([a.body_chars for a in chosen["정치"]], [300, 200])  # 최신 3건 중에서

    def test_summary_from_rss_or_page(self):
        a = art("환율 급등에 수출 비상", desc="(서울=연합뉴스) 홍길동 기자 = 하나다. 둘이다. 셋이다.", body=900)
        b = art("국회 예산안 법정시한 넘겨", body=800)
        b.page_desc = "페이지 소개문이다."

        def measure(items):
            fake_measure(items)
            b.page_desc = "페이지 소개문이다."

        chosen, _ = select([a, b], CONFIG, NOW, measure=measure)
        self.assertEqual([x.summary for x in chosen["정치"]], ["하나다. 둘이다.", "페이지 소개문이다."])


if __name__ == "__main__":
    unittest.main()
