import json
import logging
from datetime import date, datetime
from pathlib import Path

import httpx

from willy.weather.client import WeatherClient, latest_base_time

FIXTURES = Path(__file__).parent / "fixtures"


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_latest_base_time_picks_previous_slot():
    # 단기예보 발표시각은 02,05,08,11,14,17,20,23시.
    # 13:40이면 아직 14시 발표 전이므로 11시 자료를 쓴다.
    assert latest_base_time(datetime(2026, 8, 3, 13, 40)) == ("20260803", "1100")


def test_latest_base_time_rolls_back_to_previous_day():
    # 00:30이면 당일 02시 발표 전이므로 전날 23시 자료를 쓴다.
    assert latest_base_time(datetime(2026, 8, 3, 0, 30)) == ("20260802", "2300")


def test_get_week_forecast_returns_seven_days():
    def handler(request: httpx.Request) -> httpx.Response:
        if "getVilageFcst" in str(request.url):
            return httpx.Response(200, json=load("kma_vilage_fcst.json"))
        if "getMidLandFcst" in str(request.url):
            return httpx.Response(200, json=load("kma_mid_land.json"))
        if "getMidTa" in str(request.url):
            return httpx.Response(200, json=load("kma_mid_ta.json"))
        raise AssertionError(f"예상치 못한 호출: {request.url}")

    client = WeatherClient(
        service_key="dummy",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    week = client.get_week_forecast(base_date=date(2026, 8, 3))

    assert len(week) == 7
    assert week[0].temp_max == 29


def test_get_week_forecast_survives_mid_term_failure():
    """중기예보가 죽어도 단기 3일은 살려서 반환한다."""

    def handler(request: httpx.Request) -> httpx.Response:
        if "getVilageFcst" in str(request.url):
            return httpx.Response(200, json=load("kma_vilage_fcst.json"))
        return httpx.Response(500, text="서버 오류")

    client = WeatherClient(
        service_key="dummy",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    week = client.get_week_forecast(base_date=date(2026, 8, 3))

    assert len(week) == 7
    assert week[0].resolution == "detailed"
    assert week[6].resolution == "missing"


def test_get_week_forecast_survives_short_term_failure():
    def handler(request: httpx.Request) -> httpx.Response:
        if "getVilageFcst" in str(request.url):
            return httpx.Response(500, text="서버 오류")
        if "getMidLandFcst" in str(request.url):
            return httpx.Response(200, json=load("kma_mid_land.json"))
        if "getMidTa" in str(request.url):
            return httpx.Response(200, json=load("kma_mid_ta.json"))
        raise AssertionError(f"예상치 못한 호출: {request.url}")

    client = WeatherClient(
        service_key="dummy",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    week = client.get_week_forecast(base_date=date(2026, 8, 3))

    assert len(week) == 7
    assert week[0].resolution == "missing"  # 8/3, 단기 실패로 자리표시자
    assert week[5].resolution == "coarse"   # 8/8, 중기가 살아 있다


def test_service_key_never_reaches_logs(caplog):
    """기상청 오류 응답이 와도 서비스 키가 로그에 남으면 안 된다."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="서버 오류")

    client = WeatherClient(
        service_key="SUPER_SECRET_KEY",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    with caplog.at_level(logging.DEBUG):
        week = client.get_week_forecast(base_date=date(2026, 8, 3))

    assert len(week) == 7  # 실패해도 7일은 나온다
    assert "SUPER_SECRET_KEY" not in caplog.text
    assert "serviceKey=***" in caplog.text  # 로그 자체는 남되 값만 가려진다
