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

    # 남성 후보는 7개 다 있지만 전부 기온이 안 맞는다. WOMEN 풀이 비어서가 아니라
    # MAX_ACCEPTABLE 가드 때문에 비어야 한다.
    men_slots = [v for (_d, g), v in assignment.items() if g is Gender.MEN]
    assert len(men_slots) == 7
    assert all(v is None for v in men_slots)
    assert WarningCode.EMPTY_SLOT in [w.code for w in warnings]


def test_assign_prefers_globally_optimal_over_greedy():
    """앞 요일이 비에도 쓸 수 있는 룩을 선점하면, 비 오는 뒤 요일이 빈다.

    그리디는 월요일에 rainproof(비용 0)를 가져가고 화요일에 fairweather만
    남는데 비용 1001이라 배정 불가 -> 빈칸. 헝가리안은 전체를 보고
    월요일에 fairweather(2), 화요일에 rainproof(0)를 놓아 둘 다 채운다.
    """
    week = [day(0, tmax=25, tmin=25), day(1, tmax=25, tmin=25, pop=80, sky="비")]
    looks = [
        look("rainproof", (20, 30), rain_ok=True),      # 중앙값 25
        look("fairweather", (18, 28), rain_ok=False),   # 중앙값 23
    ]

    assignment, _ = assign(looks, week)

    assert assignment[(week[0].date, Gender.MEN)].look_id == "fairweather"
    assert assignment[(week[1].date, Gender.MEN)].look_id == "rainproof"


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


def test_assign_never_reuses_the_same_archive_look_twice(tmp_path: Path):
    """두 날이 모두 폴백으로 떨어져도 같은 룩이 두 번 나오면 안 된다."""
    from willy.archive import Archive

    archive = Archive(tmp_path / "a.db")
    archive.save(look("backup1", (24, 30)))
    archive.save(look("backup2", (24, 30)))

    week = [day(0), day(1)]
    looks = [look("way_off1", (-10, -5)), look("way_off2", (-10, -5))]

    assignment, _ = assign(looks, week, archive=archive)

    picked = [assignment[(d.date, Gender.MEN)].look_id for d in week]
    assert len(set(picked)) == 2, f"같은 룩이 두 번 배정됨: {picked}"


def test_assign_dry_day_fallback_accepts_rain_capable_look(tmp_path: Path):
    """맑은 날 폴백은 우천 가능 룩도 받는다."""
    from willy.archive import Archive

    archive = Archive(tmp_path / "a.db")
    archive.save(look("rain_capable", (24, 30), rain_ok=True))

    week = [day(0)]
    looks = [look("way_off", (-10, -5))]

    assignment, warnings = assign(looks, week, archive=archive)

    assert assignment[(week[0].date, Gender.MEN)].look_id == "rain_capable"
    assert WarningCode.ARCHIVE_FALLBACK in [w.code for w in warnings]
