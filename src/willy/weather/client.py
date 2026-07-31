"""기상청 API 호출. 파싱은 parser.py에 위임한다."""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

import httpx

from willy.config import SEOUL_MID_LAND_REG, SEOUL_MID_TA_REG, SEOUL_NX, SEOUL_NY
from willy.models import DayWeather
from willy.weather.parser import merge_forecasts, parse_mid_term, parse_short_term

log = logging.getLogger(__name__)

SHORT_TERM_URL = (
    "https://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/getVilageFcst"
)
MID_LAND_URL = "https://apis.data.go.kr/1360000/MidFcstInfoService/getMidLandFcst"
MID_TA_URL = "https://apis.data.go.kr/1360000/MidFcstInfoService/getMidTa"

# 단기예보 발표시각 (시)
BASE_HOURS = [2, 5, 8, 11, 14, 17, 20, 23]


def latest_base_time(now: datetime) -> tuple[str, str]:
    """현재 시각 기준 가장 최근 발표분의 (base_date, base_time)."""
    for hour in reversed(BASE_HOURS):
        if now.hour >= hour:
            return now.strftime("%Y%m%d"), f"{hour:02d}00"
    prev = now - timedelta(days=1)
    return prev.strftime("%Y%m%d"), "2300"


class WeatherClient:
    def __init__(self, service_key: str, http_client: httpx.Client | None = None):
        self._key = service_key
        self._http = http_client or httpx.Client(timeout=20.0)

    def _get(self, url: str, params: dict) -> dict:
        params = {**params, "serviceKey": self._key, "dataType": "JSON"}
        response = self._http.get(url, params=params)
        response.raise_for_status()
        return response.json()

    def get_week_forecast(self, base_date: date) -> list[DayWeather]:
        """서울 7일 예보. 단기(0~3일) + 중기(3~10일)를 병합한다.

        한쪽이 실패해도 다른 쪽으로 최대한 채운다. 예보는 콘텐츠 신뢰도에
        직결되므로 부분 실패를 전체 실패로 만들지 않는다.
        """
        short: list[DayWeather] = []
        mid: list[DayWeather] = []

        b_date, b_time = latest_base_time(datetime.now())
        try:
            payload = self._get(
                SHORT_TERM_URL,
                {
                    "numOfRows": 1000,
                    "pageNo": 1,
                    "base_date": b_date,
                    "base_time": b_time,
                    "nx": SEOUL_NX,
                    "ny": SEOUL_NY,
                },
            )
            short = parse_short_term(payload, base_date)
        except Exception:
            log.exception("단기예보 조회 실패")

        try:
            tmfc = f"{base_date.strftime('%Y%m%d')}0600"
            land = self._get(MID_LAND_URL, {"regId": SEOUL_MID_LAND_REG, "tmFc": tmfc})
            ta = self._get(MID_TA_URL, {"regId": SEOUL_MID_TA_REG, "tmFc": tmfc})
            mid = parse_mid_term(land, ta, base_date)
        except Exception:
            log.exception("중기예보 조회 실패")

        return merge_forecasts(short=short, mid=mid, base_date=base_date)
