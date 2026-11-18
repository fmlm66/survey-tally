"""기사 페이지에서 본문 글자 수, 소개문(og:description), 발행 시각을 읽는다.

본문 찾기:
1. 구조화 데이터(JSON-LD)의 articleBody가 있으면 그 길이.
   없으면 스크립트에 실린 기사 데이터(content_elements의 text 항목, 조선일보 등)의 길이.
2. 없으면 스크립트·메뉴·머리말·꼬리말·그림 설명·링크 글자를 뺀 뒤,
   글자가 가장 많이 모인 블록(div·article·section·main·td)의 글자 수.
   블록 점수 = 블록에 직접 있는 글자 + 바로 아래 블록들에 직접 있는 글자
   (문단마다 <div>로 감싼 사이트도 본문 전체를 잡도록). 짧은 표 칸(시세표 등)은 세지 않는다.
글자 수는 공백을 뺀 글자 개수다. 본문 글 자체는 저장하지 않는다.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from html.parser import HTMLParser

from .feeds import parse_date

SKIP = {"script", "style", "noscript", "nav", "footer", "header", "aside", "form", "button", "figure",
        "figcaption", "iframe", "svg", "select", "template", "textarea", "a"}
BLOCKS = {"div", "article", "section", "main", "td", "body"}
VOID = {"br", "img", "hr", "input", "meta", "link", "source", "wbr", "area", "base", "col", "embed", "param", "track"}
_WS = re.compile(r"\s+")
DATA_CELL = 40  # 표 칸 글자가 이보다 적으면 자료 칸으로 본다


@dataclass
class PageInfo:
    body_chars: int | None          # None: 본문을 찾지 못함
    description: str = ""
    published: datetime | None = None


def count_chars(text: str) -> int:
    return len(_WS.sub("", text))


class _Extractor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack: list[str] = []
        self.skip_depth = 0
        self.blocks: list[list[int]] = []  # 열린 블록마다 [직접 글자, 바로 아래 블록들의 직접 글자]
        self.scores: list[int] = []
        self.meta: dict[str, str] = {}
        self.in_ld = False
        self.ld_chunks: list[str] = []
        self.ld_texts: list[str] = []
        self.ld_is_json = False
        self.data_texts: list[str] = []  # 기사 본문을 데이터로 싣는 페이지(조선일보 등 Arc 기반)

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        attrs = {k.lower(): (v or "") for k, v in attrs}
        if tag == "meta":
            key = (attrs.get("property") or attrs.get("name") or attrs.get("itemprop") or "").lower()
            if key and "content" in attrs:
                self.meta.setdefault(key, attrs["content"])
            return
        if tag in VOID:
            return
        if tag == "script":
            self.in_ld = True  # 스크립트 글은 모아 두고, 닫힐 때 쓸 만한 것(JSON-LD·기사 데이터)만 남긴다
            self.ld_chunks = []
            self.ld_is_json = "ld+json" in attrs.get("type", "").lower()
        self.stack.append(tag)
        if tag in SKIP:
            self.skip_depth += 1
        elif tag in BLOCKS:
            self.blocks.append([0, 0])

    def _close(self, tag):
        if tag in SKIP:
            self.skip_depth -= 1
        elif tag in BLOCKS and self.blocks:
            own, children = self.blocks.pop()
            if tag == "td" and own < DATA_CELL:
                own = 0  # 숫자·짧은 글이 든 표 칸은 본문이 아니다(시세표·실적표)
            self.scores.append(own + children)
            if self.blocks:
                self.blocks[-1][1] += own
        if tag == "script" and self.in_ld:
            self.in_ld = False
            text = "".join(self.ld_chunks)
            if self.ld_is_json:
                self.ld_texts.append(text)
            elif '"content_elements"' in text:
                self.data_texts.append(text)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in VOID or tag not in self.stack:
            return  # 짝이 없는 닫는 태그는 무시
        while self.stack:
            open_tag = self.stack.pop()
            self._close(open_tag)
            if open_tag == tag:
                break

    def handle_data(self, data):
        if self.in_ld:
            self.ld_chunks.append(data)
            return
        if self.skip_depth or not self.blocks:
            return
        self.blocks[-1][0] += count_chars(data)

    def finish(self):
        while self.stack:  # 닫히지 않은 태그 정리
            self._close(self.stack.pop())


_TAGS = re.compile(r"<[^>]+>")


def _content_elements_chars(script: str) -> int:
    """스크립트 속 기사 데이터({"content_elements":[{"type":"text","content":"..."}]})에서 본문 글자 수."""
    best = 0
    decoder = json.JSONDecoder()
    for m in re.finditer(r"=\s*\{", script):
        try:
            obj, _ = decoder.raw_decode(script, m.end() - 1)
        except ValueError:
            continue
        stack = [obj]
        while stack:
            node = stack.pop()
            if isinstance(node, dict):
                elems = node.get("content_elements")
                if isinstance(elems, list):
                    n = sum(count_chars(_TAGS.sub("", e.get("content", ""))) for e in elems
                            if isinstance(e, dict) and e.get("type") == "text" and isinstance(e.get("content"), str))
                    best = max(best, n)
                stack.extend(node.values())
            elif isinstance(node, list):
                stack.extend(node)
    return best


def _walk_ld(node, found: dict):
    if isinstance(node, dict):
        for key in ("articleBody", "datePublished", "description"):
            val = node.get(key)
            if isinstance(val, str) and val.strip() and key not in found:
                found[key] = val
        for val in node.values():
            _walk_ld(val, found)
    elif isinstance(node, list):
        for val in node:
            _walk_ld(val, found)


_META_CHARSET = re.compile(rb"<meta[^>]+charset\s*=\s*[\"']?\s*([A-Za-z0-9_-]+)", re.I)


def decode_html(data: bytes, header_charset: str | None = None) -> str:
    candidates = []
    if header_charset:
        candidates.append(header_charset)
    m = _META_CHARSET.search(data[:4096])
    if m:
        candidates.append(m.group(1).decode("ascii"))
    candidates += ["utf-8", "cp949"]
    for enc in candidates:
        enc = enc.lower()
        enc = "cp949" if enc in ("euc-kr", "euckr", "ks_c_5601-1987") else enc
        try:
            return data.decode(enc)
        except (LookupError, UnicodeDecodeError):
            continue
    return data.decode("utf-8", errors="replace")


MIN_BODY = 100  # 이보다 짧으면 본문을 못 찾은 것으로 본다


def parse_article(html: str) -> PageInfo:
    ex = _Extractor()
    try:
        ex.feed(html)
        ex.close()
    except Exception:  # noqa: BLE001 — 깨진 HTML도 읽은 데까지는 쓴다
        pass
    ex.finish()
    ld: dict = {}
    for text in ex.ld_texts:
        try:
            _walk_ld(json.loads(text), ld)
        except (ValueError, RecursionError):
            continue
    data_body = max((_content_elements_chars(t) for t in ex.data_texts), default=0)
    if "articleBody" in ld and count_chars(ld["articleBody"]) >= MIN_BODY:
        body = count_chars(ld["articleBody"])
    elif data_body >= MIN_BODY:
        body = data_body
    else:
        best = max(ex.scores, default=0)
        body = best if best >= MIN_BODY else None
    desc = ex.meta.get("og:description") or ex.meta.get("description") or ld.get("description", "")
    published = parse_date(ex.meta.get("article:published_time") or ld.get("datePublished") or "")
    return PageInfo(body_chars=body, description=desc.strip(), published=published)
