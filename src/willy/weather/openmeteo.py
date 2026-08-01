"""Open-Meteo API 호출. 기상청 키가 없을 때 쓰는 대체 공급자.

키 등록 없이 7일 예보를 한 번의 호출로 받는다. WeatherClient와 동일한
인터페이스(get_week_forecast)를 구현해 Pipeline이 어느 쪽이든 그대로 받게 한다.
"""
from __future__ import annotations

import logging
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal

import httpx

from willy.config import SEOUL_LAT, SEOUL_LON
from willy.models import WEEKDAY_KO, DayWeather
from willy.weather.parser import merge_forecasts

log = logging.getLogger(__name__)

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

# WMO 날씨코드 -> 한글 하늘상태. sky는 폴더명에 그대로 쓰이므로 짧고
# 파일시스템 안전 문자로 유지한다. 매핑에 없는 코드는 "흐림"으로 떨어진다.
WMO_SKY = {
    0: "맑음",
    1: "대체로맑음",
    2: "구름조금",
    3: "흐림",
    45: "안개",
    48: "안개",
    51: "이슬비",
    53: "이슬비",
    55: "이슬비",
    56: "언이슬비",
    57: "언이슬비",
    61: "비",
    63: "비",
    65: "비",
    66: "얼어붙는비",
    67: "얼어붙는비",
    71: "눈",
    73: "눈",
    75: "눈",
    77: "싸락눈",
    80: "소나기",
    81: "소나기",
    82: "소나기",
    85: "소낙눈",
    86: "소낙눈",
    95: "뇌우",
    96: "우박뇌우",
    99: "우박뇌우",
}


def _round(value: float) -> int:
    """반올림(사사오입). 내림이 아니라 반올림 — 33.6은 34가 되어야 한다.

    Python 내장 round()는 은행가 반올림(.5를 짝수로)을 쓰므로 36.5가 36이
    되는 등 사람이 기대하는 반올림과 어긋난다. Decimal로 절반올림을 강제한다.
    """
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _weekday(d: date) -> str:
    return WEEKDAY_KO[d.weekday()]


def _sky(code: int) -> str:
    return WMO_SKY.get(code, "흐림")


class OpenMeteoClient:
    def __init__(self, http_client: httpx.Client | None = None):
        self._http = http_client or httpx.Client(timeout=20.0)

    def _parse(self, payload: dict, base_date: date) -> list[DayWeather]:
        daily = payload.get("daily", {})
        times = daily.get("time", [])
        tmax = daily.get("temperature_2m_max", [])
        tmin = daily.get("temperature_2m_min", [])
        pops = daily.get("precipitation_probability_max", [])
        codes = daily.get("weather_code", [])

        days: list[DayWeather] = []
        for i, t in enumerate(times):
            d = datetime.strptime(t, "%Y-%m-%d").date()
            pop = pops[i] if i < len(pops) else None
            code = codes[i] if i < len(codes) else None
            days.append(
                DayWeather(
                    date=d,
                    weekday_ko=_weekday(d),
                    temp_max=_round(tmax[i]),
                    temp_min=_round(tmin[i]),
                    precip_prob=int(pop) if pop is not None else 0,
                    sky=_sky(code) if code is not None else "흐림",
                    # 처음 3일은 detailed, 나머지는 coarse. Open-Meteo는 7일
                    # 내내 균일한 일별 데이터를 주지만, 예보 신뢰도는 실제로
                    # 날짜가 멀수록 떨어진다. 이 구분은 데이터 해상도가 아니라
                    # "얼마나 믿을 만한가"를 UI에 신호로 주기 위한 것이다.
                    resolution="detailed" if i < 3 else "coarse",
                )
            )
        return days

    def get_week_forecast(self, base_date: date) -> list[DayWeather]:
        """서울 7일 예보. 실패해도 절대 예외를 전파하지 않고 7일을 채워 돌려준다."""
        parsed: list[DayWeather] = []
        try:
            response = self._http.get(
                FORECAST_URL,
                params={
                    "latitude": SEOUL_LAT,
                    "longitude": SEOUL_LON,
                    "daily": "temperature_2m_max,temperature_2m_min,"
                    "precipitation_probability_max,weather_code",
                    "timezone": "Asia/Seoul",
                    "forecast_days": 7,
                },
            )
            response.raise_for_status()
            parsed = self._parse(response.json(), base_date)
        except Exception:
            log.exception("Open-Meteo 조회 실패")

        # API가 반환한 첫 날짜가 base_date와 다를 수 있다(타임존 경계 등).
        # merge_forecasts로 base_date 기준 7칸을 강제하고 빈 자리는
        # placeholder로 채운다. 직접 채움 로직을 새로 만들지 않고 재사용한다.
        return merge_forecasts(short=parsed, mid=[], base_date=base_date)
