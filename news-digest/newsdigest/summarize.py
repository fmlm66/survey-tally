"""RSS 요약문을 사람이 읽을 짧은 요약으로 다듬는다(외부 API 없음)."""

from __future__ import annotations

import html
import re

_TAG = re.compile(r"<[^>]+>")
_SPACE = re.compile(r"\s+")
_LEADS = [
    re.compile(r"^\s*\[[^\]]{1,30}\]\s*"),             # [사진] [앵커] [속보]
    re.compile(r"^\s*【[^】]{1,30}】\s*"),
    re.compile(r"^\s*◀[^▶]{0,20}▶\s*"),                # ◀ 앵커 ▶
    re.compile(r"^\s*\([^()]{1,30}=[^()]{1,30}\)\s*"),  # (서울=연합뉴스)
    re.compile(r"^[^=.!?]{0,30}?(?:기자|특파원|통신원|PD)\s*=\s*"),  # 홍길동 기자 =
]
_SENTENCE_END = re.compile(r"(?<=[.?!])\s+")


def clean_text(raw: str) -> str:
    """HTML 태그와 특수문자 표기(&amp; 등, 두 번 감싼 것 포함)를 지우고 공백을 하나로."""
    text = html.unescape(html.unescape(raw or ""))
    text = _TAG.sub(" ", text)
    return _SPACE.sub(" ", text).strip()


def strip_lead(text: str) -> str:
    """앞머리의 머리표·기자 표기를 걷어 낸다."""
    changed = True
    while changed:
        changed = False
        for pat in _LEADS:
            new = pat.sub("", text, count=1)
            if new != text:
                text, changed = new, True
    return text.strip()


def summarize(description: str, title: str = "", sentences: int = 2, max_chars: int = 200) -> str:
    text = strip_lead(clean_text(description))
    if not text or text == clean_text(title):
        return ""
    parts = [p for p in _SENTENCE_END.split(text) if p]
    out = " ".join(parts[:sentences])
    if len(out) > max_chars:
        out = out[: max_chars - 1].rstrip() + "…"
    return out
