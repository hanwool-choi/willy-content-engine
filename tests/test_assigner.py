from datetime import date, timedelta
from pathlib import Path

import pytest

from willy.assigner import assign, assignment_cost
from willy.models import DayWeather, Gender, LookAnalysis, WarningCode


def look(look_id: str, temp_range, rain_ok=True, gender=Gender.MEN) -> LookAnalysis:
    return LookAnalysis(
        look_id=look_id,
        source="musinsa_snap",
        gender=gender,
        temp_range=temp_range,
        rain_ok=rain_ok,
        season="summer",
        style_tags=[],
        image_path=Path(f"/tmp/{look_id}.jpg"),
    )


def day(offset: int = 0, tmax=28, tmin=22, pop=10, sky="맑음") -> DayWeather:
    d = date(2026, 8, 4) + timedelta(days=offset)
    return DayWeather(
        date=d, weekday_ko="월화수목금토일"[d.weekday()], temp_max=tmax,
        temp_min=tmin, precip_prob=pop, sky=sky, resolution="detailed",
    )


class FakeArchive:
    def __init__(self, substitutes: list[LookAnalysis] | None = None):
        self._substitutes = list(substitutes or [])
        self.calls: list[dict] = []

    def find_substitute(self, **kwargs):
        self.calls.append(kwargs)
        for candidate in self._substitutes:
            if candidate.gender == kwargs["gender"] and candidate.look_id not in (
                kwargs.get("exclude_ids") or set()
            ):
                return candidate
        return None


# ── 비용 함수 ──────────────────────────────────────────────


def test_cost_is_temperature_distance_when_in_range():
    # 대표기온 28*0.6 + 22*0.4 = 25.6, 룩 중앙값 25 -> 0.6
    assert assignment_cost(look("a", (20, 30)), day()) == pytest.approx(0.6)


def test_cost_adds_penalty_when_temperature_out_of_range():
    # 대표기온 25.6이 (5,10) 밖 -> 거리 18.1 + 5
    assert assignment_cost(look("a", (5, 10)), day()) == pytest.approx(23.1)


def test_cost_blocks_non_rain_look_on_rainy_day():
    assert assignment_cost(look("a", (20, 30), rain_ok=False), day(pop=60)) >= 999


def test_cost_allows_rain_ok_look_on_rainy_day():
    assert assignment_cost(look("a", (20, 30), rain_ok=True), day(pop=60)) < 999


# ── 정렬 픽 배정 ──────────────────────────────────────────


def two_per_gender():
    return [
        look("m1", (20, 30)),
        look("m2", (22, 30)),
        look("w1", (20, 30), gender=Gender.WOMEN),
        look("w2", (22, 30), gender=Gender.WOMEN),
    ]


def test_assign_fills_all_slots_when_pool_fits():
    assignment, warnings, caveats = assign(two_per_gender(), [day()])

    assert len(assignment) == 4
    assert all(v is not None for v in assignment.values())
    assert warnings == []
    assert caveats == {}


def test_assign_prefers_lower_cost_look_for_first_pick():
    # 대표기온 25.6. m-far 중앙값 21 (거리 4.6), m-near 중앙값 26 (거리 0.4)
    looks = [look("m-far", (16, 26)), look("m-near", (22, 30))]

    assignment, _, _ = assign(looks, [day()], picks_per_gender=2)

    assert assignment[(day().date, Gender.MEN, 0)].look_id == "m-near"
    assert assignment[(day().date, Gender.MEN, 1)].look_id == "m-far"


def test_assign_breaks_cost_ties_by_look_id():
    looks = [look("b", (20, 30)), look("a", (20, 30))]

    assignment, _, _ = assign(looks, [day()], picks_per_gender=2)

    assert assignment[(day().date, Gender.MEN, 0)].look_id == "a"


def test_assign_never_reuses_the_same_look():
    assignment, _, _ = assign(two_per_gender(), [day()])

    used = [v.look_id for v in assignment.values() if v]
    assert len(used) == len(set(used))


def test_assign_warns_when_pool_too_small():
    _, warnings, _ = assign([look("only", (20, 30))], [day()])

    assert WarningCode.POOL_TOO_SMALL in [w.code for w in warnings]


# ── 조건부 추천 ────────────────────────────────────────────


def test_rainy_day_conditional_pick_carries_caveat():
    """우천 부적합만 있는 날, 빈 칸 대신 차선 룩을 사유와 함께 채운다."""
    rainy = day(pop=78)
    looks = [look("m1", (20, 30), rain_ok=False), look("m2", (22, 30), rain_ok=False)]

    assignment, warnings, caveats = assign(looks, [rainy], picks_per_gender=2)

    slot0 = (rainy.date, Gender.MEN, 0)
    assert assignment[slot0] is not None
    assert "우천 부적합" in caveats[slot0]
    assert "기온은 적합" in caveats[slot0]
    assert WarningCode.CONDITIONAL_PICK in [w.code for w in warnings]


def test_conditional_pick_prefers_lowest_cost_among_unfit():
    rainy = day(pop=78)
    # 둘 다 우천 부적합. m-near가 기온 거리가 더 가깝다.
    looks = [look("m-far", (10, 16), rain_ok=False), look("m-near", (22, 30), rain_ok=False)]

    assignment, _, caveats = assign(looks, [rainy], picks_per_gender=2)

    assert assignment[(rainy.date, Gender.MEN, 0)].look_id == "m-near"
    # 기온 범위 밖 룩의 사유에는 기온 문제가 담긴다.
    assert "기온" in caveats[(rainy.date, Gender.MEN, 1)]


def test_archive_substitute_beats_conditional_pick():
    """진짜 적합한 아카이브 룩이 있으면 조건부 추천보다 우선한다."""
    rainy = day(pop=78)
    substitute = look("arch-rain", (22, 30), rain_ok=True)
    archive = FakeArchive([substitute])
    looks = [look("m1", (22, 30), rain_ok=False)]

    assignment, warnings, caveats = assign(
        looks, [rainy], archive=archive, picks_per_gender=1
    )

    slot = (rainy.date, Gender.MEN, 0)
    assert assignment[slot].look_id == "arch-rain"
    assert slot not in caveats
    assert WarningCode.RAIN_SUBSTITUTE in [w.code for w in warnings]


def test_conditional_pick_used_when_archive_has_nothing():
    rainy = day(pop=78)
    archive = FakeArchive([])
    looks = [look("m1", (22, 30), rain_ok=False)]

    assignment, _, caveats = assign(
        looks, [rainy], archive=archive, picks_per_gender=1
    )

    slot = (rainy.date, Gender.MEN, 0)
    assert assignment[slot].look_id == "m1"
    assert slot in caveats


def test_empty_slot_when_no_pool_at_all():
    assignment, warnings, caveats = assign([], [day()], picks_per_gender=1)

    assert all(v is None for v in assignment.values())
    assert WarningCode.EMPTY_SLOT in [w.code for w in warnings]
    assert caveats == {}


def test_conditional_pick_is_not_duplicated_across_slots():
    rainy = day(pop=78)
    looks = [look("m1", (22, 30), rain_ok=False)]

    assignment, _, _ = assign(looks, [rainy], picks_per_gender=2)

    slot0 = assignment[(rainy.date, Gender.MEN, 0)]
    slot1 = assignment[(rainy.date, Gender.MEN, 1)]
    assert slot0 is not None and slot0.look_id == "m1"
    assert slot1 is None  # 같은 룩을 두 칸에 넣지 않는다


def test_out_of_range_fit_uses_conditional_with_temp_caveat():
    """맑은 날이지만 기온 범위 밖뿐인 경우도 조건부 추천으로 채운다."""
    hot = day(tmax=36, tmin=28)  # 대표기온 32.8
    looks = [look("m1", (17, 24))]  # 거리 12.3 + 5 = 17.3 > MAX_ACCEPTABLE

    assignment, _, caveats = assign(looks, [hot], picks_per_gender=1)

    slot = (hot.date, Gender.MEN, 0)
    assert assignment[slot].look_id == "m1"
    assert "기온" in caveats[slot]
