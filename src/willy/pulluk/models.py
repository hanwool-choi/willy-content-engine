"""최펄럭 채널 코스 도메인 모델.

즐겨찾기 한 건(Place)과, 그것이 채워 들어가는 코스 슬롯을 정의한다.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Place:
    """네이버 지도 즐겨찾기 한 곳.

    좌표(lat/lon)가 없는 항목이 섞여 들어온다. 동선 계산에서 빠져야
    하므로 0.0으로 채우지 않고 None으로 남긴다.
    """

    name: str
    folder: str                 # "카페" | "식당" | "스팟" — 어느 즐겨찾기 폴더에서 왔는지
    category: str | None        # 네이버 분류(mcidName). 예: "카페", "한식", "미술관"
    address: str
    lat: float | None = None
    lon: float | None = None
    place_id: str | None = None  # 네이버 플레이스 id(sid). 지도 링크·영업시간 조회의 열쇠

    @property
    def has_coord(self) -> bool:
        return self.lat is not None and self.lon is not None

    @property
    def map_url(self) -> str | None:
        if not self.place_id:
            return None
        return f"https://map.naver.com/p/entry/place/{self.place_id}"

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "folder": self.folder,
            "category": self.category,
            "address": self.address,
            "lat": self.lat,
            "lon": self.lon,
            "place_id": self.place_id,
        }

    @classmethod
    def from_dict(cls, d: dict) -> Place:
        return cls(
            name=d["name"],
            folder=d["folder"],
            category=d.get("category"),
            address=d.get("address") or "",
            lat=d.get("lat"),
            lon=d.get("lon"),
            place_id=d.get("place_id"),
        )


@dataclass(frozen=True)
class SlotSpec:
    """코스 한 칸의 조건. 어떤 폴더에서 어떤 분류를 뽑아 몇 분 머무는지.

    include가 비어 있으면 폴더 전체가 후보다. exclude는 include보다 세다.
    """

    key: str
    role: str                          # 본문에 쓰는 역할 이름. 예: "점심"
    action: str                        # 템플릿의 [구체 메뉴/행동] 기본값. 예: "점심"
    folders: tuple[str, ...]
    stay_min: int
    include: tuple[str, ...] = ()
    exclude: tuple[str, ...] = ()
    note: str = ""                     # 답사 때 확인할 것


@dataclass
class SlotPick:
    spec: SlotSpec
    place: Place | None                # 후보가 없으면 None — 빈 칸으로 남긴다
    alternates: list[Place] = field(default_factory=list)


@dataclass
class Course:
    region_label: str
    picks: list[SlotPick]
    warnings: list[str] = field(default_factory=list)

    @property
    def filled(self) -> list[SlotPick]:
        return [p for p in self.picks if p.place is not None]

    @property
    def is_complete(self) -> bool:
        return len(self.filled) == len(self.picks)

    @property
    def travel_km(self) -> float:
        """지역 내 이동 거리 합계(직선). 실제 주행거리는 이보다 길다."""
        pts = [p.place for p in self.filled if p.place and p.place.has_coord]
        return round(sum(distance_km(a, b) for a, b in zip(pts, pts[1:])), 1)


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(a))


def distance_km(a: Place, b: Place) -> float:
    if not (a.has_coord and b.has_coord):
        return 0.0
    return haversine_km(a.lat, a.lon, b.lat, b.lon)
