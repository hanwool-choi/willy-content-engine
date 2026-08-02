"""고정 URL 3곳 + 수동 투입에서 룩 이미지를 확보한다.

사용자가 버튼을 눌렀을 때만 실행된다. 스케줄러 자동 순회는 하지 않는다.
"""
from __future__ import annotations

import hashlib
import logging
import shutil
from contextlib import AbstractContextManager
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
        page_factory: Callable[[], AbstractContextManager],
        downloader: Callable[[str, Path], None] | None = None,
    ):
        """
        page_factory: 페이지를 내주는 컨텍스트매니저를 반환하는 콜러블.
            (페이지 자체가 아니라 `with page_factory() as page:` 로 여는 대상이다.)
            `collect`가 이 컨텍스트매니저의 수명을 소유하고 항상 닫는다 —
            호출자가 `__exit__`을 잊어 브라우저가 계속 떠 있는 사고를 막기 위해서다.
        """
        self._workspace = workspace
        self._workspace.mkdir(parents=True, exist_ok=True)
        self._page_factory = page_factory
        self._download = downloader or _default_downloader

    def collect(
        self, sources: list[SourceSpec], limit_per_source: int = 20
    ) -> list[RawLook]:
        looks: list[RawLook] = []

        # 같은 사진이 한 목록에 두 번 실리거나 소스끼리 겹치는 일이 실제로
        # 있다. 그대로 두면 같은 룩을 두 번 분석해 비용을 버리고, 배정
        # 후보에도 중복으로 올라간다. 내용 해시로 한 번만 남긴다.
        seen: set[str] = set()

        # 페이지 수명을 여기서 소유한다. 호출자가 __exit__을 잊으면
        # 브라우저가 그대로 남기 때문이다.
        with self._page_factory() as page:
            for spec in sources:
                try:
                    looks.extend(
                        self._collect_one(page, spec, limit_per_source, seen)
                    )
                except Exception:
                    # 한 소스 실패가 전체를 무너뜨리지 않는다.
                    log.exception("소스 수집 실패: %s", spec.name)

        return looks

    def _collect_one(
        self, page, spec: SourceSpec, limit: int, seen: set[str]
    ) -> list[RawLook]:
        # networkidle을 쓰면 안 된다. 세 소스 모두 애널리틱스·소켓 연결이
        # 계속 살아 있어 네트워크가 조용해지는 순간이 오지 않고, goto가
        # 타임아웃으로 끝난다. 실측으로 확인했다.
        page.goto(spec.url, wait_until="domcontentloaded")
        page.wait_for_timeout(3000)

        # 지연 로딩 대응
        for _ in range(spec.scroll_rounds):
            page.mouse.wheel(0, 4000)
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

            digest = hashlib.sha256(dest.read_bytes()).hexdigest()
            if digest in seen:
                log.info("중복 사진을 건너뜁니다: %s", dest.name)
                dest.unlink(missing_ok=True)
                continue
            seen.add(digest)

            source_url = None
            if spec.link_selector:
                link_el = card.query_selector(spec.link_selector)
                if link_el is not None:
                    source_url = link_el.get_attribute("href")
            if source_url is None:
                # 카드 자체가 링크인 경우가 있다 (유니클로 스타일링북).
                source_url = card.get_attribute("href")

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
