"""아이디어 수집 오케스트레이션.

한 소스가 실패해도 나머지는 모은다. 브라우저가 필요한 소스는
page_factory가 있을 때만 수집한다 — 로컬 앱은 브라우저를 띄우지 않고
배치만 띄우기 때문이다.
"""
from __future__ import annotations

import logging
from typing import Callable

import httpx

from willy.ideas.hotness import mark_hot
from willy.ideas.models import IdeaItem
from willy.ideas.parsers import (
    parse_condenast,
    parse_eomisae,
    parse_eyesmag,
    parse_hearst,
    parse_rss,
)
from willy.ideas.sources import IDEA_SOURCES, IdeaSource

log = logging.getLogger(__name__)

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

PARSERS: dict[str, Callable[..., list[IdeaItem]]] = {
    "rss": parse_rss,
    "eomisae": parse_eomisae,
    "hearst": parse_hearst,
    "condenast": parse_condenast,
    "eyesmag": parse_eyesmag,
}


def _parse(source: IdeaSource, text: str) -> list[IdeaItem]:
    parser = PARSERS[source.kind]
    if source.kind == "rss":
        return parser(text, source=source.name)
    return parser(text, source=source.name, base_url=source.url)


def _fetch_with_browser(source: IdeaSource, page_factory) -> list[IdeaItem]:
    with page_factory() as page:
        page.goto(source.url, wait_until="domcontentloaded")
        page.wait_for_timeout(4000)
        return _parse(source, page.content())


def collect_ideas(
    sources: list[IdeaSource] | None = None,
    limit_per_source: int = 10,
    http=None,
    page_factory=None,
) -> tuple[list[IdeaItem], list[str]]:
    """소스별 최신 limit_per_source건까지 모은다.

    돌려주는 값은 (아이디어 목록, 실패한 소스 이름 목록)이다. 실패를
    조용히 삼키면 어느 날 목록이 반쪽이 돼도 알 수 없다.
    """
    sources = sources if sources is not None else list(IDEA_SOURCES.values())
    client = http or httpx.Client(timeout=25, follow_redirects=True, headers=HEADERS)

    collected: list[IdeaItem] = []
    failed: list[str] = []

    for source in sources:
        if source.needs_browser and page_factory is None:
            log.info("브라우저가 없어 건너뜁니다: %s", source.name)
            continue
        try:
            if source.needs_browser:
                items = _fetch_with_browser(source, page_factory)
            else:
                response = client.get(source.url)
                response.raise_for_status()
                items = _parse(source, response.text)
        except Exception:
            log.exception("아이디어 수집 실패: %s", source.name)
            failed.append(source.name)
            continue
        collected.extend(items[:limit_per_source])

    return mark_hot(collected), failed
