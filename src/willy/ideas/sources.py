"""수집 소스 정의. 소스를 늘리거나 빼는 일은 이 파일에서 끝나야 한다.

robots.txt는 urllib.robotparser로 판정했고, 실제 제목을 뽑아 주제에
맞는지 확인한 뒤 골랐다. 무신사 매거진·에펨코리아·딜바다는 robots가
차단하므로 넣지 않는다 (에이블리·크림을 제외한 것과 같은 기준).
"""
from __future__ import annotations

from dataclasses import dataclass

# 필터 칩에 그대로 쓰인다.
SOURCE_GROUPS = {
    "deal": "할인",
    "drop": "드랍·신상",
    "magazine": "매거진",
}


@dataclass(frozen=True)
class IdeaSource:
    name: str          # 소스 id
    label: str         # 화면 배지
    url: str           # 목록 주소
    kind: str          # 파서 종류
    group: str         # SOURCE_GROUPS 키
    needs_browser: bool = False


IDEA_SOURCES: dict[str, IdeaSource] = {
    "eomisae_os": IdeaSource(
        name="eomisae_os",
        label="어미새",
        url="https://eomisae.co.kr/os",
        kind="eomisae",
        group="deal",
    ),
    # 서버 HTML에 글이 없다(완전 클라이언트 렌더링). 초기 데이터에도 없고
    # 내부 API 경로가 공개돼 있지 않아 브라우저로 읽는다.
    "eyesmag": IdeaSource(
        name="eyesmag",
        label="아이즈",
        url="https://www.eyesmag.com/category/fashion/all",
        kind="eyesmag",
        group="drop",
        needs_browser=True,
    ),
    "hypebeast": IdeaSource(
        name="hypebeast",
        label="하입비스트",
        url="https://hypebeast.kr/feed",
        kind="rss",
        group="drop",
    ),
    "esquire": IdeaSource(
        name="esquire",
        label="에스콰이어",
        url="https://www.esquirekorea.co.kr/fashion",
        kind="hearst",
        group="magazine",
    ),
    "elle": IdeaSource(
        name="elle",
        label="엘르",
        url="https://www.elle.co.kr/fashion",
        kind="hearst",
        group="magazine",
    ),
    "gq": IdeaSource(
        name="gq",
        label="GQ",
        url="https://www.gqkorea.co.kr/category/style/",
        kind="condenast",
        group="magazine",
    ),
    "vogue": IdeaSource(
        name="vogue",
        label="보그",
        url="https://www.vogue.co.kr/category/fashion",
        kind="condenast",
        group="magazine",
    ),
}
