import json
from datetime import date
from pathlib import Path

import httpx

from willy.weather.openmeteo import OpenMeteoClient

FIXTURES = Path(__file__).parent / "fixtures"


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def client_with(payload: dict | None, status: int = 200) -> OpenMeteoClient:
    def handler(request: httpx.Request) -> httpx.Response:
        if status != 200:
            return httpx.Response(status, text="서버 오류")
        return httpx.Response(200, json=payload)

    return OpenMeteoClient(
        http_client=httpx.Client(transport=httpx.MockTransport(handler))
    )


def test_get_week_forecast_returns_seven_days_from_base_date():
    client = client_with(load("open_meteo_seoul.json"))
    week = client.get_week_forecast(base_date=date(2026, 8, 2))

    assert len(week) == 7
    assert [d.date for d in week] == [
        date(2026, 8, 2),
        date(2026, 8, 3),
        date(2026, 8, 4),
        date(2026, 8, 5),
        date(2026, 8, 6),
        date(2026, 8, 7),
        date(2026, 8, 8),
    ]


def test_temperatures_are_rounded_not_truncated():
    client = client_with(load("open_meteo_seoul.json"))
    week = client.get_week_forecast(base_date=date(2026, 8, 2))

    # fixture: 33.2 -> 33, 34.8 -> 35, 36.5 -> 37 (round-half-up, NOT Python's
    # banker's rounding which would give 36 for 36.5).
    assert week[0].temp_max == 33
    assert week[1].temp_max == 35
    assert week[2].temp_max == 37
    assert week[0].temp_min == 26  # 25.5 rounds up to 26 (round-half-up)
    assert week[3].temp_min == 28  # 28.2 rounds to 28


def test_precip_prob_mapped_and_null_becomes_zero():
    payload = {
        "daily": {
            "time": ["2026-08-02", "2026-08-03", "2026-08-04", "2026-08-05",
                      "2026-08-06", "2026-08-07", "2026-08-08"],
            "temperature_2m_max": [20.0] * 7,
            "temperature_2m_min": [10.0] * 7,
            "precipitation_probability_max": [None, 37, 53, 37, 10, 25, 40],
            "weather_code": [0, 0, 0, 0, 0, 0, 0],
        }
    }
    client = client_with(payload)
    week = client.get_week_forecast(base_date=date(2026, 8, 2))

    assert week[0].precip_prob == 0
    assert week[1].precip_prob == 37


def test_wmo_code_mapping():
    payload = {
        "daily": {
            "time": ["2026-08-02", "2026-08-03", "2026-08-04", "2026-08-05",
                      "2026-08-06", "2026-08-07", "2026-08-08"],
            "temperature_2m_max": [20.0] * 7,
            "temperature_2m_min": [10.0] * 7,
            "precipitation_probability_max": [0] * 7,
            "weather_code": [0, 3, 51, 4, 0, 0, 0],
        }
    }
    client = client_with(payload)
    week = client.get_week_forecast(base_date=date(2026, 8, 2))

    assert week[0].sky == "맑음"
    assert week[1].sky == "흐림"
    assert week[2].sky == "이슬비"
    assert week[3].sky == "흐림"  # 4 is unmapped -> fallback


def test_first_three_days_detailed_rest_coarse():
    client = client_with(load("open_meteo_seoul.json"))
    week = client.get_week_forecast(base_date=date(2026, 8, 2))

    assert [d.resolution for d in week[:3]] == ["detailed", "detailed", "detailed"]
    assert [d.resolution for d in week[3:]] == ["coarse"] * 4


def test_high_precip_prob_marks_rainy():
    payload = {
        "daily": {
            "time": ["2026-08-02", "2026-08-03", "2026-08-04", "2026-08-05",
                      "2026-08-06", "2026-08-07", "2026-08-08"],
            "temperature_2m_max": [20.0] * 7,
            "temperature_2m_min": [10.0] * 7,
            "precipitation_probability_max": [80, 0, 0, 0, 0, 0, 0],
            "weather_code": [61, 0, 0, 0, 0, 0, 0],
        }
    }
    client = client_with(payload)
    week = client.get_week_forecast(base_date=date(2026, 8, 2))

    assert week[0].is_rainy is True
    assert week[1].is_rainy is False


def test_http_failure_still_returns_seven_placeholder_days():
    client = client_with(None, status=500)
    week = client.get_week_forecast(base_date=date(2026, 8, 2))

    assert len(week) == 7
    assert all(d.resolution == "missing" for d in week)
    assert all(d.sky == "정보없음" for d in week)


def test_missing_leading_days_are_filled_as_placeholders():
    # API's first returned day is not base_date -> earlier days get filled in.
    payload = {
        "daily": {
            "time": ["2026-08-04", "2026-08-05", "2026-08-06", "2026-08-07",
                      "2026-08-08", "2026-08-09", "2026-08-10"],
            "temperature_2m_max": [20.0] * 7,
            "temperature_2m_min": [10.0] * 7,
            "precipitation_probability_max": [0] * 7,
            "weather_code": [0] * 7,
        }
    }
    client = client_with(payload)
    week = client.get_week_forecast(base_date=date(2026, 8, 2))

    assert len(week) == 7
    assert week[0].date == date(2026, 8, 2)
    assert week[0].resolution == "missing"
    assert week[1].resolution == "missing"
    assert week[2].date == date(2026, 8, 4)
