"""지역 정의와 코스 슬롯 스펙.

지역을 늘리는 일은 REGIONS에 한 줄 추가하는 것으로 끝나야 한다.
슬롯 스펙은 「주말 드라이브 실내 코스」 기획서의 동선 설계표를 그대로 옮긴 것
(docs/superpowers/specs/2026-08-08-pulluk-indoor-drive-course-plan.md §2-1, §3-1).
"""
from __future__ import annotations

from dataclasses import dataclass

from willy.pulluk.models import SlotSpec


@dataclass(frozen=True)
class Region:
    """코스를 짤 지역 하나.

    주소 키워드와 좌표 반경을 함께 둔다. 근교는 주소 표기가 제각각이라
    (`파주시` / `파주읍`) 키워드만으로는 새고, 좌표만으로는 행정구역을 넘는다.
    둘 중 하나라도 걸리면 후보로 본다.
    """

    key: str
    label: str                     # 본문에 쓰는 지역명
    addr_keywords: tuple[str, ...]
    center: tuple[float, float]    # (위도, 경도)
    radius_km: float
    hook: str                      # 본문 첫 줄 [상황 후킹]
    outro: str = ""                # 코스 끝에 붙는 한 줄. 없으면 생략


# 서울 기준 편도 50~90분, 대중교통 대비 차가 확실히 유리한 곳만 넣는다.
REGIONS: dict[str, Region] = {
    "paju": Region(
        key="paju",
        label="파주",
        addr_keywords=("파주",),
        center=(37.7130, 126.6980),   # 헤이리·출판도시 축 중간
        radius_km=8.0,
        hook="밖에 1분도 서 있기 싫은 8월 주말,",
        outro="하루 종일 밖에 서 있는 시간 총 10분.",
    ),
    "ganghwa": Region(
        key="ganghwa",
        label="강화",
        addr_keywords=("강화",),
        center=(37.7470, 126.4880),   # 강화읍
        radius_km=12.0,
        hook="차 있으면 한 시간, 근데 하루 종일 실내인",
        outro="섬 하루 코스인데 밖에 서 있는 시간 15분.",
    ),
    # 파주·강화의 즐겨찾기 밀도가 안 나올 때의 대안 2순위 (기획서 §1)
    "yongin": Region(
        key="yongin",
        label="용인",
        addr_keywords=("용인",),
        center=(37.2410, 127.1780),
        radius_km=12.0,
        hook="에어컨 밑에서만 도는",
    ),
    "yangpyeong": Region(
        key="yangpyeong",
        label="양평",
        addr_keywords=("양평",),
        center=(37.4910, 127.4870),
        radius_km=12.0,
        hook="비 와도 상관없는",
    ),
}


# 실내 코스에 넣으면 안 되는 분류. 컨셉이 '실내'인데 야외 장소가 섞이면
# "밖에 서 있는 시간 N분"이라는 킬러 문장 자체가 거짓이 된다.
OUTDOOR_KEYWORDS: tuple[str, ...] = (
    "공원", "해수욕장", "해변", "유원지", "계곡", "캠핑", "야영", "등산",
    "산책", "둘레길", "수목원", "정원", "루지", "글램핑", "낚시", "해안",
)

INDOOR_DRIVE_SLOTS: tuple[SlotSpec, ...] = (
    SlotSpec(
        key="lunch",
        role="점심",
        action="점심",
        folders=("식당",),
        stay_min=70,
        note="12시 전 도착 기준 웨이팅, 주차 대수",
    ),
    SlotSpec(
        key="anchor",
        role="실내 문화 앵커",
        action="실내 관람",
        folders=("스팟",),
        include=("미술관", "박물관", "전시", "갤러리", "문화", "서점", "도서", "체험", "영화"),
        exclude=OUTDOOR_KEYWORDS,
        stay_min=90,
        note="냉난방, 관람 소요시간, 실내 비중(야외 유적 중심이면 제외)",
    ),
    SlotSpec(
        key="cafe",
        role="대형 카페",
        action="커피",
        folders=("카페",),
        stay_min=60,
        note="이용시간 제한(90분 슬롯과 충돌 여부), 층고·좌석 간격, 유리 온실형이면 8월엔 제외",
    ),
    SlotSpec(
        key="shopping",
        role="실내 쇼핑",
        action="쇼핑",
        folders=("스팟",),
        include=("쇼핑", "아울렛", "백화점", "몰", "편집", "의류", "소품", "잡화", "서점"),
        exclude=OUTDOOR_KEYWORDS,
        stay_min=90,
        note="주차장에서 입구까지 노출 거리(우천 대응)",
    ),
    SlotSpec(
        key="dinner",
        role="저녁",
        action="저녁",
        folders=("식당",),
        stay_min=80,
        note="라스트오더, 브레이크타임, 귀가 시간대 정체",
    ),
)

COURSE_SPECS: dict[str, tuple[SlotSpec, ...]] = {
    "indoor_drive": INDOOR_DRIVE_SLOTS,
}
