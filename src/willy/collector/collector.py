"""고정 URL 3곳 + 수동 투입에서 룩 이미지를 확보한다.

사용자가 버튼을 눌렀을 때만 실행된다. 스케줄러 자동 순회는 하지 않는다.
"""
from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Callable

import httpx

from willy.collector.sources import SourceSpec, build_look_id
from willy.images import retag
from willy.models import RawLook

log = logging.getLogger(__name__)


def _default_downloader(url: str, dest: Path) -> None:
    with httpx.Client(timeout=20.0, follow_redirects=True) as client:
        response = client.get(url)
        response.raise_for_status()
        dest.write_bytes(response.content)


class Collector:
    def __init__(
        self,
        workspace: Path,
        page_factory: Callable[[], object],
        downloader: Callable[[str, Path], None] | None = None,
    ):
        self._workspace = workspace
        self._workspace.mkdir(parents=True, exist_ok=True)
        self._page_factory = page_factory
        self._download = downloader or _default_downloader

    def collect(
        self, sources: list[SourceSpec], limit_per_source: int = 20
    ) -> list[RawLook]:
        page = self._page_factory()
        looks: list[RawLook] = []

        for spec in sources:
            try:
                looks.extend(self._collect_one(page, spec, limit_per_source))
            except Exception:
                # 한 소스 실패가 전체를 무너뜨리지 않는다.
                log.exception("소스 수집 실패: %s", spec.name)

        return looks

    def _collect_one(
        self, page, spec: SourceSpec, limit: int
    ) -> list[RawLook]:
        page.goto(spec.url, wait_until="networkidle")
        page.wait_for_timeout(2000)

        # 지연 로딩 대응
        for _ in range(spec.scroll_rounds):
            page.mouse_wheel(0, 4000)
            page.wait_for_timeout(1200)

        cards = page.query_selector_all(spec.card_selector)[:limit]
        looks: list[RawLook] = []

        for index, card in enumerate(cards):
            look_id = build_look_id(spec.name, index)
            dest = self._workspace / f"{look_id}.jpg"

            image_url = None
            image_el = card.query_selector(spec.image_selector)
            if image_el is not None:
                image_url = image_el.get_attribute("src")

            method = "screenshot"
            if image_url:
                try:
                    self._download(image_url, dest)
                    dest = retag(dest)
                    method = "original_url"
                except Exception:
                    log.warning("원본 다운로드 실패, 캡처로 대체: %s", image_url)

            if method == "screenshot":
                card.screenshot(path=str(dest))

            source_url = None
            if spec.link_selector:
                link_el = card.query_selector(spec.link_selector)
                if link_el is not None:
                    source_url = link_el.get_attribute("href")

            looks.append(
                RawLook(
                    look_id=look_id,
                    source=spec.name,
                    image_path=dest,
                    capture_method=method,
                    source_url=source_url,
                )
            )

        return looks

    def add_manual(self, path_or_url: str) -> RawLook:
        """사용자 직접 투입. 로컬 파일 경로 또는 이미지 URL."""
        look_id = build_look_id("manual", 0)
        dest = self._workspace / f"{look_id}.jpg"

        if path_or_url.startswith(("http://", "https://")):
            self._download(path_or_url, dest)
            source_url = path_or_url
        else:
            shutil.copyfile(path_or_url, dest)
            source_url = None

        dest = retag(dest)

        return RawLook(
            look_id=look_id,
            source="manual",
            image_path=dest,
            capture_method="original_url",
            source_url=source_url,
        )
