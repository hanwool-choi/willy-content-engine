from datetime import date

import pytest

from willy.models import (
    DayWeather,
    Gender,
    LookAnalysis,
    WarningCode,
    iso_week_label,
    temp_repr,
)


def test_temp_repr_weights_daytime_higher():
    # 최고 30, 최저 20 -> 30*0.6 + 20*0.4 = 26.0
    assert temp_repr(temp_max=30, temp_min=20) == 26.0


def test_iso_week_label_uses_thursday_month():
    # 2026-08-01은 토요일. 그 주 목요일은 2026-07-30 -> 7월로 귀속
    assert iso_week_label(date(2026, 8, 1)) == "2026-07_W5"


def test_iso_week_label_first_week_of_month():
    # 2026-08-03은 월요일. 그 주 목요일은 2026-08-06 -> 8월 1주차
    assert iso_week_label(date(2026, 8, 3)) == "2026-08_W1"


def test_look_analysis_temp_median():
    look = LookAnalysis(
        look_id="a",
        source="musinsa_snap",
        gender=Gender.MEN,
        sleeve="short",
        outer=None,
        layers=1,
        fabric_weight="light",
        coverage="mid",
        temp_range=(23, 30),
        rain_ok=False,
        season="summer",
        style_tags=["미니멀"],
        palette=["ecru"],
    )
    assert look.temp_median == 26.5


def test_day_weather_is_rainy_at_threshold():
    common = dict(
        date=date(2026, 8, 3),
        weekday_ko="월",
        temp_min=22,
        temp_max=28,
        sky="비",
        resolution="detailed",
    )
    assert DayWeather(precip_prob=60, **common).is_rainy is True
    assert DayWeather(precip_prob=59, **common).is_rainy is False


def test_day_weather_folder_name_format():
    day = DayWeather(
        date=date(2026, 8, 3),
        weekday_ko="월",
        temp_min=24,
        temp_max=29,
        precip_prob=10,
        sky="맑음",
        resolution="detailed",
    )
    # Task 9가 이 문자열로 실제 폴더를 만든다. 포맷이 곧 계약이다.
    assert day.folder_name == "08-03_월_맑음_29-24℃"
    assert "℃" in day.folder_name  # U+2103. °C(U+00B0 + C)로 바뀌면 실패한다.


def test_warning_code_values_are_stable():
    assert WarningCode.EMPTY_SLOT.value == "EMPTY_SLOT"
    assert WarningCode.ARCHIVE_FALLBACK.value == "ARCHIVE_FALLBACK"
    assert WarningCode.RAIN_SUBSTITUTE.value == "RAIN_SUBSTITUTE"
    assert WarningCode.POOL_TOO_SMALL.value == "POOL_TOO_SMALL"
