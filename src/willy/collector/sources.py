"""소스별 셀렉터. 사이트 DOM이 바뀌면 이 파일만 고친다."""
from __future__ import annotations

import uuid
from dataclasses import dataclass

from willy.config import SOURCE_URLS


@dataclass(frozen=True)
class SourceSpec:
    name: str
    url: str
    card_selector: str      # 룩 카드 하나를 가리키는 셀렉터
    image_selector: str     # 카드 안의 이미지
    link_selector: str | None = None
    meta_selector: str | None = None  # 제품명 등 (옵션)
    scroll_rounds: int = 3            # 지연 로딩을 위한 스크롤 횟수


SOURCE_SPECS: dict[str, SourceSpec] = {
    "musinsa_snap": SourceSpec(
        name="musinsa_snap",
        url=SOURCE_URLS["musinsa_snap"],
        card_selector="[class*='SnapItem'], [data-snap-id], article",
        image_selector="img",
        link_selector="a",
    ),
    "uniqlo_women": SourceSpec(
        name="uniqlo_women",
        url=SOURCE_URLS["uniqlo_women"],
        card_selector="[class*='styling'] li, [class*='Card'], article",
        image_selector="img",
        link_selector="a",
    ),
    "uniqlo_men": SourceSpec(
        name="uniqlo_men",
        url=SOURCE_URLS["uniqlo_men"],
        card_selector="[class*='styling'] li, [class*='Card'], article",
        image_selector="img",
        link_selector="a",
    ),
}


def build_look_id(source: str, index: int) -> str:
    return f"{source}-{index}-{uuid.uuid4().hex[:8]}"
