"""RSS 2.0 / Atom 읽기, 날짜 읽기, 내려받기. 인터넷 없이 시험할 수 있게 내려받기는 따로 둔다."""

from __future__ import annotations

import http.client
import re
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

KST = timezone(timedelta(hours=9))
USER_AGENT = "Mozilla/5.0 (compatible; news-digest/1.0)"


@dataclass
class Article:
    source: str
    title: str
    link: str
    description: str = ""
    published: datetime | None = None
    raw_date: str = ""  # 날짜 칸 원문(읽지 못했을 때 점검용)
    topic: str = ""
    measured: bool = False          # 기사 페이지를 열어 봤는지
    body_chars: int | None = None   # 본문 글자 수(공백 제외). None: 못 읽음
    page_desc: str = ""             # 기사 페이지의 소개문(og:description)
    points: int = 0                 # 최종 점수
    reasons: list[str] = field(default_factory=list)  # 점수 이유(예: "4곳 보도")
    summary: str = ""
    also: list[str] = field(default_factory=list)  # 같은 소식을 다룬 다른 언론사


def fetch(url: str, timeout: float = 20.0, retries: int = 2, wait: float = 5.0, sleep=time.sleep) -> bytes:
    """RSS 받기. 연결이 끊기거나 시간이 넘으면 잠시 쉬었다가 다시 시도한다(5초, 10초)."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*"})
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            if exc.code < 500 or attempt == retries:  # 404 같은 것은 다시 해도 같다
                raise
        except (OSError, http.client.HTTPException):
            if attempt == retries:
                raise
        sleep(wait * (attempt + 1))
    raise AssertionError("unreachable")


def fetch_page(url: str, timeout: float = 15.0) -> str:
    """기사 페이지를 받아 글자로 바꾼다(인코딩은 응답 머리글 → meta → UTF-8 → CP949 순)."""
    from .article import decode_html  # 순환 import 피하기

    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return decode_html(resp.read(2_000_000), resp.headers.get_content_charset())


def _local(tag: str) -> str:
    """'{namespace}name' → 'name'"""
    return tag.rsplit("}", 1)[-1].lower()


def _child_text(elem: ET.Element, *names: str) -> str:
    for child in elem:
        if _local(child.tag) in names:
            text = "".join(child.itertext()).strip()
            if text:
                return text
    return ""


def _atom_link(entry: ET.Element) -> str:
    fallback = ""
    for child in entry:
        if _local(child.tag) != "link":
            continue
        href = (child.get("href") or "").strip()
        if not href:
            continue
        if child.get("rel", "alternate") == "alternate":
            return href
        fallback = fallback or href
    return fallback


# XML에서 허용되지 않는 맨 '&'(예: "A&B")를 &amp;로 바꾼다. 이미 표기인 &amp; &#123; 등은 그대로.
_BARE_AMP = re.compile(rb"&(?!(?:[A-Za-z][A-Za-z0-9]*|#[0-9]+|#x[0-9A-Fa-f]+);)")
_BAD_CTRL = re.compile(rb"[\x00-\x08\x0b\x0c\x0e-\x1f]")


_DECL_ENCODING = re.compile(rb"^\s*<\?xml[^>]*?encoding\s*=\s*[\"']([A-Za-z0-9._-]+)[\"']", re.I)
_EXPAT_OK = {"utf-8", "utf8", "us-ascii", "ascii", "iso-8859-1", "latin-1", "latin1", "utf-16"}


def _to_utf8(data: bytes) -> bytes:
    """expat이 못 읽는 EUC-KR 같은 인코딩은 UTF-8로 바꾸고 선언도 고친다."""
    m = _DECL_ENCODING.match(data)
    if not m:
        return data
    enc = m.group(1).decode("ascii").lower()
    if enc in _EXPAT_OK:
        return data
    codec = "cp949" if enc in ("euc-kr", "euckr", "ks_c_5601-1987", "ksc5601") else enc
    text = data.decode(codec, errors="replace")
    text = re.sub(r"encoding\s*=\s*[\"'][^\"']+[\"']", 'encoding="utf-8"', text, count=1)
    return text.encode("utf-8")


def _parse_xml(data: bytes) -> ET.Element:
    data = _to_utf8(data)
    try:
        return ET.fromstring(data)
    except ET.ParseError:
        fixed = _BAD_CTRL.sub(b"", _BARE_AMP.sub(b"&amp;", data))
        return ET.fromstring(fixed)


def parse_feed(data: bytes, source: str) -> list[Article]:
    """RSS 2.0, RSS 1.0(RDF), Atom을 읽어 기사 목록으로 바꾼다."""
    root = _parse_xml(data)
    articles: list[Article] = []
    for elem in root.iter():
        kind = _local(elem.tag)
        if kind == "item":
            link = _child_text(elem, "link") or _child_text(elem, "guid")
            desc = _child_text(elem, "description", "encoded")
            date = _child_text(elem, "pubdate", "date", "published", "updated")
        elif kind == "entry":
            link = _atom_link(elem)
            desc = _child_text(elem, "summary", "content")
            date = _child_text(elem, "published", "updated")
        else:
            continue
        title = _child_text(elem, "title")
        if not title or not link:
            continue
        articles.append(Article(source=source, title=title, link=link.strip(),
                                description=desc, published=parse_date(date), raw_date=date))
    return articles


_NAIVE_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y.%m.%d %H:%M:%S", "%Y.%m.%d %H:%M", "%Y/%m/%d %H:%M:%S",
                  "%Y-%m-%d", "%Y.%m.%d", "%Y/%m/%d")  # 날짜만 있으면 그날 0시(한국)


def parse_date(text: str) -> datetime | None:
    """RFC 822(RSS), ISO 8601(Atom), 국내 피드에 흔한 'YYYY-MM-DD HH:MM:SS'를 읽는다.
    시간대가 없으면 한국 시각으로 본다. 못 읽으면 None."""
    text = (text or "").strip()
    if not text:
        return None
    dt = None
    try:
        dt = parsedate_to_datetime(text)
    except (TypeError, ValueError, IndexError):
        pass
    if dt is None:
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            pass
    if dt is None:
        for fmt in _NAIVE_FORMATS:
            try:
                dt = datetime.strptime(text, fmt)
                break
            except ValueError:
                continue
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=KST)
    return dt


@dataclass
class FeedResult:
    topic: str
    source: str
    url: str
    articles: list[Article]
    error: str | None = None


def collect(config: dict, fetcher=fetch) -> list[FeedResult]:
    """주제별로 설정된 RSS를 읽는다. 한 곳이 실패해도 멈추지 않는다."""
    results: list[FeedResult] = []
    for topic in config["topics"]:
        for feed in topic["feeds"]:
            try:
                arts = parse_feed(fetcher(feed["url"]), feed["source"])
                for a in arts:
                    a.topic = topic["name"]
                results.append(FeedResult(topic["name"], feed["source"], feed["url"], arts))
            except Exception as exc:  # noqa: BLE001 — 어떤 실패든 기록하고 다음 주소로
                results.append(FeedResult(topic["name"], feed["source"], feed["url"], [], f"{type(exc).__name__}: {exc}"))
    return results
