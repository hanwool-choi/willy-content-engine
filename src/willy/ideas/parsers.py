"""소스 종류별 파서. 전부 순수 함수다 — 안에서 HTTP를 하지 않는다.

파서를 네트워크와 분리해야 저장한 픽스처로 테스트할 수 있다.
"""
from __future__ import annotations

import html
import re
from datetime import datetime
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin
from xml.etree import ElementTree as ET

from willy.ideas.models import IdeaItem

_ANCHOR_RE = re.compile(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', re.S)
_DATE_RE = re.compile(r"^(\d{4})\.(\d{1,2})\.(\d{1,2})$")


def clean_text(raw: str) -> str:
    """태그를 걷어내고 공백을 하나로 눌러 한 줄 텍스트로 만든다."""
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", raw))).strip()


def tag_parts(raw: str) -> list[str]:
    """태그 경계로 잘라 조각 목록을 만든다.

    카테고리·제목·날짜·기자명이 서로 다른 요소로 오는 매거진에서,
    조각을 살려두면 필드로 나눌 수 있다.
    """
    pieces = (
        html.unescape(re.sub(r"\s+", " ", piece)).strip()
        for piece in re.split(r"<[^>]+>", raw)
    )
    return [piece for piece in pieces if piece]


def _anchors(html_text: str, href_pattern: str):
    """href가 패턴에 맞는 <a>만 (href, 안쪽 HTML)로 돌려준다."""
    for match in _ANCHOR_RE.finditer(html_text):
        if re.search(href_pattern, match.group(1)):
            yield match.group(1), match.group(2)


def _parse_pubdate(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return parsedate_to_datetime(raw.strip())
    except (TypeError, ValueError):
        return None


def parse_rss(xml: str, source: str) -> list[IdeaItem]:
    """하입비스트. 공식 RSS라 구조가 안정적이다."""
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        raise ValueError(f"RSS를 파싱할 수 없습니다: {exc}") from exc

    items: list[IdeaItem] = []
    for node in root.findall(".//item"):
        title = (node.findtext("title") or "").strip()
        link = (node.findtext("link") or "").strip()
        if not title or not link:
            continue
        categories = [c.text.strip() for c in node.findall("category") if c.text]
        items.append(
            IdeaItem(
                source=source,
                title=title,
                url=link,
                published_at=_parse_pubdate(node.findtext("pubDate")),
                category=categories[0] if categories else None,
            )
        )
    return items


# 목록 사이에 광고 슬롯과 레벨 제한 글이 카드 모양으로 끼어 있다.
# 둘 다 제목이 소재가 되지 않으므로 버린다.
_EOMISAE_SKIP = ("list_ad_link", "전체 공개로 전환됩니다")


def _reaction(card: str, icon: str) -> int | None:
    match = re.search(rf'{icon}"></i>\s*([\d,]+)', card)
    return int(match.group(1).replace(",", "")) if match else None


def parse_eomisae(html_text: str, source: str, base_url: str) -> list[IdeaItem]:
    """어미새 패션할인 게시판. 목록 카드에 반응 수와 썸네일이 함께 온다."""
    items: list[IdeaItem] = []

    for card in re.split(r'<div class="card_el', html_text)[1:]:
        link = re.search(
            r'<h3[^>]*>\s*<a[^>]+href="(/os/\d+)"[^>]*>(.*?)</a>', card, re.S
        )
        if link is None:
            continue
        title = clean_text(link.group(2))
        if not title or any(skip in title for skip in _EOMISAE_SKIP):
            continue

        thumbnail = None
        thumb_match = re.search(r'<img class="tmb" src="([^"]+)"', card)
        if thumb_match:
            raw = thumb_match.group(1)
            thumbnail = f"https:{raw}" if raw.startswith("//") else raw

        category = None
        cate_match = re.search(r'<span class="cate">([^<]*)</span>', card)
        if cate_match:
            category = cate_match.group(1).strip().rstrip(",") or None

        items.append(
            IdeaItem(
                source=source,
                title=title,
                url=urljoin(base_url, link.group(1)),
                category=category,
                thumbnail_url=thumbnail,
                views=_reaction(card, "ion-ios-eye"),
                comments=_reaction(card, "ion-ios-chatbubble"),
                likes=_reaction(card, "ion-ios-heart"),
            )
        )
    return items


def parse_hearst(html_text: str, source: str, base_url: str) -> list[IdeaItem]:
    """에스콰이어·엘르. 링크가 /article/{숫자}이고 안에 제목만 있다."""
    items: list[IdeaItem] = []
    seen: set[str] = set()

    for href, inner in _anchors(html_text, r"/article/\d+"):
        title = clean_text(inner)
        if len(title) < 8:
            continue
        url = urljoin(base_url, href)
        if url in seen:
            continue
        seen.add(url)
        items.append(IdeaItem(source=source, title=title, url=url))
    return items


def parse_condenast(html_text: str, source: str, base_url: str) -> list[IdeaItem]:
    """보그·GQ. 링크 안에 카테고리·제목·날짜·기자명이 조각으로 들어 있다.

    조각 순서가 글마다 다르므로 위치가 아니라 성격으로 고른다.
    """
    items: list[IdeaItem] = []
    seen: set[str] = set()

    for href, inner in _anchors(html_text, r"/\d{4}/\d{1,2}/\d{1,2}/"):
        parts = tag_parts(inner)
        if not parts:
            continue

        published = None
        remaining: list[str] = []
        for part in parts:
            date_match = _DATE_RE.match(part)
            if date_match and published is None:
                year, month, day = (int(value) for value in date_match.groups())
                published = datetime(year, month, day)
                continue
            if part.startswith("by "):
                continue
            remaining.append(part)

        if len(remaining) < 2:
            continue
        category = remaining[0]
        # 카테고리를 뺀 나머지 중 가장 긴 조각이 제목이다.
        title = max(remaining[1:], key=len)
        if len(title) < 8:
            continue

        url = urljoin(base_url, href)
        if url in seen:
            continue
        seen.add(url)
        items.append(
            IdeaItem(
                source=source,
                title=title,
                url=url,
                category=category,
                published_at=published,
            )
        )
    return items


_EYESMAG_VIEWS_RE = re.compile(r"읽음\s*([\d,]+)")


def parse_eyesmag(html_text: str, source: str, base_url: str) -> list[IdeaItem]:
    """아이즈매거진. 브라우저가 렌더링한 DOM 문자열을 받는다.

    링크 안에 카테고리·조회수·상대시간·제목이 조각으로 들어온다.
    조회수와 시간 조각은 제목에서 빼야 텍스트 생성이 오염되지 않는다.
    """
    items: list[IdeaItem] = []
    seen: set[str] = set()

    for href, inner in _anchors(html_text, r"/posts/\d+/"):
        category = None
        views = None
        titles: list[str] = []

        for part in tag_parts(inner):
            views_match = _EYESMAG_VIEWS_RE.search(part)
            if views_match:
                views = int(views_match.group(1).replace(",", ""))
                continue
            if part.startswith("패션") and ">" in part:
                category = part
                continue
            titles.append(part)

        if not titles:
            continue
        title = max(titles, key=len)
        if len(title) < 8:
            continue

        url = urljoin(base_url, href)
        if url in seen:
            continue
        seen.add(url)
        items.append(
            IdeaItem(
                source=source,
                title=title,
                url=url,
                category=category,
                views=views,
            )
        )
    return items
