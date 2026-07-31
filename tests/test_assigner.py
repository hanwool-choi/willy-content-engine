from datetime import date, timedelta
from pathlib import Path

import pytest

from willy.assigner import assign, assignment_cost
from willy.models import DayWeather, Gender, LookAnalysis, WarningCode


def look(look_id: str, temp_range, rain_ok=True, gender=Gender.MEN) -> LookAnalysis:
    return LookAnalysis(
        look_id=look_id, gender=gender, sleeve="short", outer=None, layers=1,
        fabric_weight="light", coverage="mid", temp_range=temp_range,
        rain_ok=rain_ok, season="summer", style_tags=[], palette=[],
        image_path=Path(f"/tmp/{look_id}.jpg"),
    )


def day(offset: int, tmax=28, tmin=22, pop=10, sky="맑음") -> DayWeather:
    d = date(2026, 8, 3) + timedelta(days=offset)
    return DayWeather(
        date=d, weekday_ko="월화수목금토일"[d.weekday()], temp_max=tmax,
        temp_min=tmin, precip_prob=pop, sky=sky, resolution="detailed",
    )


def full_week() -> list[DayWeather]:
    return [day(i) for i in range(7)]


def test_cost_is_temperature_distance_when_in_range():
    # 대표기온 28*0.6 + 22*0.4 = 25.6, 룩 중앙값 25 -> 0.6
    assert assignment_cost(look("a", (20, 30)), day(0)) == pytest.approx(0.6)


def test_cost_adds_penalty_when_temperature_out_of_range():
    # 대표기온 25.6이 (5,10) 밖 -> 거리 18.1 + 5
    assert assignment_cost(look("a", (5, 10)), day(0)) == pytest.approx(23.1)


def test_cost_blocks_non_rain_look_on_rainy_day():
    cost = assignment_cost(look("a", (20, 30), rain_ok=False), day(0, pop=60))
    assert cost >= 999


def test_cost_allows_rain_ok_look_on_rainy_day():
    cost = assignment_cost(look("a", (20, 30), rain_ok=True), day(0, pop=60))
    assert cost < 999


def test_assign_fills_all_fourteen_slots():
    looks = [look(f"m{i}", (20, 30)) for i in range(7)]
    looks += [look(f"w{i}", (20, 30), gender=Gender.WOMEN) for i in range(7)]

    assignment, warnings = assign(looks, full_week())

    assert len(assignment) == 14
    assert all(v is not None for v in assignment.values())
    assert warnings == []


def test_assign_never_reuses_the_same_look():
    looks = [look(f"m{i}", (20, 30)) for i in range(7)]
    looks += [look(f"w{i}", (20, 30), gender=Gender.WOMEN) for i in range(7)]

    assignment, _ = assign(looks, full_week())
    used = [v.look_id for v in assignment.values() if v]

    assert len(used) == len(set(used))


def test_assign_warns_when_pool_too_small():
    assignment, warnings = assign([look("only", (20, 30))], full_week())

    codes = [w.code for w in warnings]
    assert WarningCode.POOL_TOO_SMALL in codes


def test_assign_leaves_empty_slot_rather_than_forcing_bad_match():
    """한파 주간에 여름룩만 있으면 억지로 배정하지 않는다."""
    winter_week = [day(i, tmax=-2, tmin=-10) for i in range(7)]
    looks = [look(f"m{i}", (24, 30)) for i in range(7)]

    assignment, warnings = assign(looks, winter_week)

    assert any(v is None for v in assignment.values())
    assert WarningCode.EMPTY_SLOT in [w.code for w in warnings]


def test_assign_prefers_globally_optimal_over_greedy():
    """앞 요일이 좋은 룩을 선점해 뒤 요일이 무너지지 않아야 한다."""
    week = [day(0, tmax=30, tmin=30), day(1, tmax=20, tmin=20)]
    # cool은 양쪽에 쓸 수 있지만 hot은 더운 날에만 맞다.
    looks = [look("cool", (18, 30)), look("hot", (29, 31))]

    assignment, _ = assign(looks, week)

    assert assignment[(week[0].date, Gender.MEN)].look_id == "hot"
    assert assignment[(week[1].date, Gender.MEN)].look_id == "cool"


def test_assign_uses_archive_substitute_on_rainy_day(tmp_path: Path):
    from willy.archive import Archive

    archive = Archive(tmp_path / "a.db")
    archive.save(look("rain_backup", (22, 28), rain_ok=True))

    week = [day(0, pop=80, sky="비")]
    looks = [look("dry_only", (22, 28), rain_ok=False)]

    assignment, warnings = assign(looks, week, archive=archive)

    assert assignment[(week[0].date, Gender.MEN)].look_id == "rain_backup"
    # 우천 대체는 RAIN_SUBSTITUTE 하나만 남긴다. 한 사건에 경고 하나.
    codes = [w.code for w in warnings]
    assert WarningCode.RAIN_SUBSTITUTE in codes
    assert codes.count(WarningCode.RAIN_SUBSTITUTE) == 1


def test_assign_uses_archive_fallback_on_dry_day(tmp_path: Path):
    """비가 안 오는 날 폴백은 ARCHIVE_FALLBACK으로 구분한다."""
    from willy.archive import Archive

    archive = Archive(tmp_path / "a.db")
    archive.save(look("backup", (24, 30), rain_ok=False))

    week = [day(0, tmax=28, tmin=22)]
    looks = [look("way_off", (-10, -5))]  # 배정 불가 수준

    assignment, warnings = assign(looks, week, archive=archive)

    assert assignment[(week[0].date, Gender.MEN)].look_id == "backup"
    assert WarningCode.ARCHIVE_FALLBACK in [w.code for w in warnings]
