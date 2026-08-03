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
        # 스냅 탭의 각 룩은 SnapFeedCard__Link <a>가 감싼다. 카드 자체가
        # 링크라 link_selector 없이 수집기가 카드 href를 폴백으로 읽는다.
        card_selector="[class*='SnapFeedCard__Link']",
        image_selector="img",
        link_selector=None,
    ),
    "uniqlo_women": SourceSpec(
        name="uniqlo_women",
        url=SOURCE_URLS["uniqlo_women"],
        # 각 룩은 상세로 가는 <a>가 감싸고 그 안에 fr-ec-tile 버튼과 이미지가 있다.
        # 카드 자체가 링크라 link_selector로는 잡히지 않고, 수집기가 카드의
        # href를 폴백으로 읽는다.
        # :has(...)로 실제 룩 카드만 남긴다. 이게 없으면 /stylingbook/stylehint/women
        # 같은 네비게이션 링크까지 카드로 잡혀 로고 아이콘이 수집된다.
        card_selector="a[href*='/stylingbook/stylehint/']:has(img.fr-ec-image__img)",
        image_selector="img.fr-ec-image__img, img",
        link_selector=None,
    ),
    "uniqlo_men": SourceSpec(
        name="uniqlo_men",
        url=SOURCE_URLS["uniqlo_men"],
        # 각 룩은 상세로 가는 <a>가 감싸고 그 안에 fr-ec-tile 버튼과 이미지가 있다.
        # 카드 자체가 링크라 link_selector로는 잡히지 않고, 수집기가 카드의
        # href를 폴백으로 읽는다.
        # :has(...)로 실제 룩 카드만 남긴다. 이게 없으면 /stylingbook/stylehint/women
        # 같은 네비게이션 링크까지 카드로 잡혀 로고 아이콘이 수집된다.
        card_selector="a[href*='/stylingbook/stylehint/']:has(img.fr-ec-image__img)",
        image_selector="img.fr-ec-image__img, img",
        link_selector=None,
    ),
    # WEAR 코디 카드는 <a class="relative block">가 코디 이미지를 감싼다.
    # 카드 안에 착용 상품 썸네일(c.imgz.jp)이 함께 있어서, 이미지 셀렉터를
    # /coordinate/ 경로로 못박아 옷 더미 사진이 룩으로 섞이는 걸 막는다.
    # 2장만 걷는 소스라 첫 화면이면 충분하다 — 스크롤을 줄여 시간을 아낀다.
    "wear_men": SourceSpec(
        name="wear_men",
        url=SOURCE_URLS["wear_men"],
        card_selector="a:has(img[src*='/coordinate/'])",
        image_selector="img[src*='/coordinate/']",
        link_selector=None,
        scroll_rounds=1,
    ),
    "wear_women": SourceSpec(
        name="wear_women",
        url=SOURCE_URLS["wear_women"],
        card_selector="a:has(img[src*='/coordinate/'])",
        image_selector="img[src*='/coordinate/']",
        link_selector=None,
        scroll_rounds=1,
    ),
}


def build_look_id(source: str, index: int) -> str:
    return f"{source}-{index}-{uuid.uuid4().hex[:8]}"
