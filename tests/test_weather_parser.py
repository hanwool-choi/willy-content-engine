import json
from datetime import date
from pathlib import Path

import pytest

from willy.weather.parser import merge_forecasts, parse_mid_term, parse_short_term

FIXTURES = Path(__file__).parent / "fixtures"


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_parse_short_term_extracts_daily_values():
    days = parse_short_term(load("kma_vilage_fcst.json"), base_date=date(2026, 8, 3))

    assert len(days) == 2
    monday = days[0]
    assert monday.date == date(2026, 8, 3)
    assert monday.weekday_ko == "월"
    assert monday.temp_max == 29
    assert monday.temp_min == 24
    assert monday.sky == "맑음"
    assert monday.resolution == "detailed"


def test_parse_short_term_takes_max_precip_of_day():
    days = parse_short_term(load("kma_vilage_fcst.json"), base_date=date(2026, 8, 3))
    # 20%와 30% 중 큰 값을 그날 강수확률로 삼는다.
    assert days[0].precip_prob == 30


def test_parse_short_term_marks_rainy_day():
    days = parse_short_term(load("kma_vilage_fcst.json"), base_date=date(2026, 8, 3))
    tuesday = days[1]
    assert tuesday.precip_prob == 80
    assert tuesday.is_rainy is True
    assert tuesday.sky == "흐림"


def test_parse_mid_term_builds_coarse_days():
    days = parse_mid_term(
        load("kma_mid_land.json"), load("kma_mid_ta.json"), base_date=date(2026, 8, 3)
    )

    assert [d.date for d in days] == [
        date(2026, 8, 8),
        date(2026, 8, 9),
        date(2026, 8, 10),
    ]
    assert all(d.resolution == "coarse" for d in days)


def test_parse_mid_term_takes_max_of_am_pm_precip():
    days = parse_mid_term(
        load("kma_mid_land.json"), load("kma_mid_ta.json"), base_date=date(2026, 8, 3)
    )
    # 6일차: 오전 60, 오후 70 -> 70
    assert days[1].precip_prob == 70
    assert days[1].temp_max == 25
    assert days[1].temp_min == 20


def test_merge_forecasts_returns_exactly_seven_days_without_gaps():
    week = merge_forecasts(
        short=parse_short_term(load("kma_vilage_fcst.json"), base_date=date(2026, 8, 3)),
        mid=parse_mid_term(
            load("kma_mid_land.json"), load("kma_mid_ta.json"), base_date=date(2026, 8, 3)
        ),
        base_date=date(2026, 8, 3),
    )

    assert len(week) == 7
    assert [d.date.day for d in week] == [3, 4, 5, 6, 7, 8, 9]


def test_merge_forecasts_prefers_short_term_when_overlapping():
    short = parse_short_term(load("kma_vilage_fcst.json"), base_date=date(2026, 8, 3))
    mid = parse_mid_term(
        load("kma_mid_land.json"), load("kma_mid_ta.json"), base_date=date(2026, 8, 3)
    )
    week = merge_forecasts(short=short, mid=mid, base_date=date(2026, 8, 3))

    # 8/3은 단기예보에 있으므로 detailed 여야 한다.
    assert week[0].resolution == "detailed"


def test_merge_forecasts_fills_missing_days_with_placeholder():
    """단기·중기 어느 쪽에도 없는 날은 빠뜨리지 않고 자리를 채운다."""
    week = merge_forecasts(short=[], mid=[], base_date=date(2026, 8, 3))

    assert len(week) == 7
    assert all(d.resolution == "missing" for d in week)
    assert week[0].sky == "정보없음"
