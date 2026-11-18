"""기사 점수: 중요도 + 읽을 가치 − 감점. 외부 API 없이 제목·요약문·본문 길이·보도 언론사 수로 계산한다.

설정(config.json의 "scoring")에서 점수와 단어 목록을 바꿀 수 있다. 빠진 항목은 DEFAULTS를 쓴다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .feeds import Article
from .summarize import clean_text

DEFAULTS: dict = {
    "coverage_per_outlet": 3,   # 같은 소식을 보도한 다른 언론사 1곳마다
    "coverage_max": 12,
    "headline": 3,              # 언론사 주요뉴스 RSS에 실림
    "follow_up": {"pattern": r"\((종합|\d+보)\)", "points": 1},
    "depth": {"pattern": r"\[(단독|심층|기획|분석|탐사|팩트체크|인터뷰|르포)", "points": 3, "label": "심층·단독"},
    "length_buckets": [[600, 1], [1500, 2]],   # 본문 글자 수 이상이면 점수(가장 높은 구간 하나)
    "min_body": 300,                            # 이보다 짧으면 단신으로 보고 뺀다
    "facts": {"pattern": r"\d|[“”\"]", "points": 1},   # 요약문에 수치·인용
    "penalties": [
        {"label": "홍보성", "points": -4,
         "pattern": r"맞손|MOU|업무협약|협약 체결|출시|론칭|선정|수상|개최|오픈|체험단|이벤트|Start-up NEST|스타트업 탐방|\[신제품"},
        {"label": "연예·연재", "points": -4,
         "pattern": r"열애|결혼|이혼|생일|근황|화보|직캠|컴백|데뷔|\[\d+화\]|연재소설"},
    ],
    "opinion": {"pattern": r"^\s*\[(사설|칼럼|기고|시론|오피니언|기자수첩|기자24시|데스크|시평|만물상|횡설수설|논단)|\[[가-힣]{2,4}의 [^\]]{1,15}\]",
                "max_per_topic": 1},
    "per_source_max": 2,
}


def settings(config: dict) -> dict:
    s = dict(DEFAULTS)
    s.update(config.get("scoring", {}))
    return s


@dataclass
class Score:
    points: int = 0
    reasons: list[str] = field(default_factory=list)


def _rx(pattern: str) -> re.Pattern:
    return re.compile(pattern, re.I)


def pre_score(a: Article, coverage: int, in_headline: bool, s: dict) -> Score:
    """기사 페이지를 열기 전: 보도 언론사 수, 주요뉴스, 후속 보도, 심층 표시, 감점."""
    title = clean_text(a.title)
    sc = Score()
    others = max(coverage - 1, 0)
    if others:
        sc.points += min(others * s["coverage_per_outlet"], s["coverage_max"])
        sc.reasons.append(f"{coverage}곳 보도")
    if in_headline:
        sc.points += s["headline"]
        sc.reasons.append("주요뉴스")
    if _rx(s["follow_up"]["pattern"]).search(title):
        sc.points += s["follow_up"]["points"]
        sc.reasons.append("후속 보도")
    if _rx(s["depth"]["pattern"]).search(title):
        sc.points += s["depth"]["points"]
        sc.reasons.append(s["depth"].get("label", "심층"))
    text = title + " " + clean_text(a.description)
    for p in s["penalties"]:
        if _rx(p["pattern"]).search(text):
            sc.points += p["points"]
            sc.reasons.append(p["label"])
    return sc


def body_points(body_chars: int | None, s: dict) -> int:
    pts = 0
    for minimum, points in s["length_buckets"]:
        if body_chars and body_chars >= minimum:
            pts = points
    return pts


def final_score(a: Article, pre: Score, s: dict) -> Score:
    sc = Score(pre.points, list(pre.reasons))
    sc.points += body_points(a.body_chars, s)
    if _rx(s["facts"]["pattern"]).search(clean_text(a.description or a.page_desc)):
        sc.points += s["facts"]["points"]
    return sc


def is_opinion(a: Article, s: dict) -> bool:
    return bool(_rx(s["opinion"]["pattern"]).search(clean_text(a.title)))
