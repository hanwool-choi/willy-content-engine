"""즐겨찾기 → 코스 슬롯 배정.

지역으로 즐겨찾기를 거르고, 슬롯 조건에 맞는 후보를 뽑고, 그중
'되돌아가지 않는 한 방향 동선'이 되는 조합을 고른다. 한 방향 동선은
채널 설계의 원칙이라 정렬이 아니라 비용 함수로 강제한다
(docs/superpowers/specs/2026-08-07-pulluk-channel-design.md §11.3).
"""
from __future__ import annotations

import itertools
import math

from willy.pulluk.models import (
    Course,
    Place,
    SlotPick,
    SlotSpec,
    distance_km,
    haversine_km,
)
from willy.pulluk.regions import INDOOR_DRIVE_SLOTS, Region

# 되돌아가는 구간에 매기는 벌점 배수. 1.0이면 그냥 최단거리와 같아지고,
# 너무 크면 일직선만 찾다가 좋은 장소를 버린다. 3배면 "웬만하면 안 되돌아감"
# 정도로 붙는다.
BACKTRACK_WEIGHT = 3.0

# 슬롯당 후보 상한. 조합 전수 탐색이라 이 값이 곧 비용이다(상한^슬롯수).
MAX_CANDIDATES = 8
MAX_COMBOS = 200_000

# 이 개수 미만으로 채워지면 코스로 내보내지 않는 게 맞다 (기획서 §0-1).
MIN_FILLED_SLOTS = 3


def in_region(place: Place, region: Region, radius_km: float | None = None) -> bool:
    """주소 키워드 또는 중심 반경 중 하나라도 걸리면 그 지역으로 본다."""
    if any(k in place.address or k in place.name for k in region.addr_keywords):
        return True
    if place.has_coord:
        radius = region.radius_km if radius_km is None else radius_km
        lat0, lon0 = region.center
        return haversine_km(lat0, lon0, place.lat, place.lon) <= radius
    return False


def _matches(place: Place, slot: SlotSpec) -> bool:
    haystack = f"{place.category or ''} {place.name}"
    if any(x in haystack for x in slot.exclude):
        return False
    if not slot.include:
        return True
    return any(x in haystack for x in slot.include)


def candidates(
    slot: SlotSpec,
    by_folder: dict[str, list[Place]],
    region: Region,
    radius_km: float | None = None,
) -> list[Place]:
    """슬롯 조건 + 지역을 통과한 후보를 중심에서 가까운 순으로."""
    lat0, lon0 = region.center
    found: list[Place] = []
    for folder in slot.folders:
        for place in by_folder.get(folder, []):
            if not in_region(place, region, radius_km):
                continue
            if not _matches(place, slot):
                continue
            found.append(place)

    def sort_key(p: Place) -> tuple[int, float]:
        if not p.has_coord:
            return (1, 0.0)  # 좌표 없는 곳은 뒤로 — 동선 계산에 못 낀다
        return (0, haversine_km(lat0, lon0, p.lat, p.lon))

    found.sort(key=sort_key)
    # 같은 장소가 여러 폴더에 중복 등록된 경우가 있다.
    seen: set[str] = set()
    unique: list[Place] = []
    for p in found:
        key = p.place_id or p.name
        if key in seen:
            continue
        seen.add(key)
        unique.append(p)
    return unique


def _planar(place: Place, region: Region) -> tuple[float, float]:
    """지역 중심 기준 등거리 근사 평면 좌표(km). 한 지역 안에서만 쓴다."""
    lat0, lon0 = region.center
    x = (place.lon - lon0) * math.cos(math.radians(lat0)) * 111.32
    y = (place.lat - lat0) * 110.57
    return x, y


def route_cost(places: list[Place], region: Region) -> float:
    """이동 거리 + 되돌아간 만큼의 벌점.

    첫 곳→끝 곳 방향을 코스의 진행축으로 삼고, 그 축의 반대로 간 성분에만
    벌점을 매긴다. 축과 직각으로 움직이는 건 되돌아간 게 아니므로 봐준다.
    """
    routed = [p for p in places if p.has_coord]
    if len(routed) < 2:
        return 0.0

    total = sum(distance_km(a, b) for a, b in zip(routed, routed[1:]))

    x0, y0 = _planar(routed[0], region)
    xn, yn = _planar(routed[-1], region)
    ax, ay = xn - x0, yn - y0
    axis_len = math.hypot(ax, ay)
    if axis_len < 0.1:  # 시작과 끝이 같은 자리면 방향을 정할 수 없다
        return total
    ux, uy = ax / axis_len, ay / axis_len

    penalty = 0.0
    for a, b in zip(routed, routed[1:]):
        xa, ya = _planar(a, region)
        xb, yb = _planar(b, region)
        proj = (xb - xa) * ux + (yb - ya) * uy
        if proj < 0:
            penalty += -proj * BACKTRACK_WEIGHT
    return total + penalty


def _cap(counts: list[int], limit: int) -> int:
    """조합 수가 MAX_COMBOS를 넘지 않는 슬롯당 후보 상한을 찾는다."""
    while limit > 1:
        total = 1
        for c in counts:
            total *= min(c, limit)
        if total <= MAX_COMBOS:
            return limit
        limit -= 1
    return 1


def build_course(
    by_folder: dict[str, list[Place]],
    region: Region,
    slots: tuple[SlotSpec, ...] = INDOOR_DRIVE_SLOTS,
    radius_km: float | None = None,
    max_candidates: int = MAX_CANDIDATES,
) -> Course:
    """슬롯 순서는 고정한 채, 총 이동과 되돌아감이 가장 적은 조합을 고른다."""
    warnings: list[str] = []
    pools: dict[str, list[Place]] = {}
    for slot in slots:
        pool = candidates(slot, by_folder, region, radius_km)
        if not pool:
            warnings.append(
                f"[{slot.role}] 즐겨찾기에 후보가 없다. "
                f"폴더={'/'.join(slot.folders)} 조건={'|'.join(slot.include) or '전체'}"
            )
        pools[slot.key] = pool

    active = [s for s in slots if pools[s.key]]
    if not active:
        return Course(
            region_label=region.label,
            picks=[SlotPick(spec=s, place=None) for s in slots],
            warnings=warnings + [f"{region.label}: 즐겨찾기에서 한 곳도 못 찾았다."],
        )

    limit = _cap([len(pools[s.key]) for s in active], max_candidates)
    best: tuple[float, tuple[Place, ...]] | None = None
    for combo in itertools.product(*[pools[s.key][:limit] for s in active]):
        keys = [p.place_id or p.name for p in combo]
        if len(set(keys)) != len(keys):  # 한 장소가 두 슬롯을 채우면 코스가 아니다
            continue
        cost = route_cost(list(combo), region)
        if best is None or cost < best[0]:
            best = (cost, combo)

    chosen: dict[str, Place] = {}
    if best:
        chosen = {s.key: p for s, p in zip(active, best[1])}

    picks: list[SlotPick] = []
    for slot in slots:
        place = chosen.get(slot.key)
        alts = [p for p in pools[slot.key] if p is not place][:3]
        picks.append(SlotPick(spec=slot, place=place, alternates=alts))

    course = Course(region_label=region.label, picks=picks, warnings=warnings)
    if len(course.filled) < MIN_FILLED_SLOTS:
        course.warnings.append(
            f"{region.label}: 채워진 슬롯이 {len(course.filled)}칸뿐이다. "
            "답사해서 즐겨찾기를 먼저 채우거나 다른 지역으로 바꾸는 게 맞다 (기획서 §0-1)."
        )
    return course
