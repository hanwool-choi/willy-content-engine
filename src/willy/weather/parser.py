"""기상청 응답 -> DayWeather 변환. 순수 함수만 둔다 (네트워크 없음)."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta

from willy.models import WEEKDAY_KO, DayWeather

SKY_CODE = {"1": "맑음", "3": "구름많음", "4": "흐림"}


def _items(payload: dict) -> list[dict]:
    return payload.get("response", {}).get("body", {}).get("items", {}).get("item", [])


def _weekday(d: date) -> str:
    return WEEKDAY_KO[d.weekday()]


def parse_short_term(payload: dict, base_date: date) -> list[DayWeather]:
    """단기예보(getVilageFcst) -> 일별 DayWeather. base_date 이후만 남긴다."""
    buckets: dict[date, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))

    for item in _items(payload):
        d = datetime.strptime(item["fcstDate"], "%Y%m%d").date()
        buckets[d][item["category"]].append(str(item["fcstValue"]))

    days: list[DayWeather] = []
    for d in sorted(buckets):
        if d < base_date:
            continue
        cats = buckets[d]
        if "TMX" not in cats or "TMN" not in cats:
            continue  # 기온이 없으면 배정에 못 쓴다.

        pops = [int(float(v)) for v in cats.get("POP", ["0"])]
        skies = cats.get("SKY", ["1"])
        # 그날을 대표하는 하늘상태는 가장 흐린 쪽으로 잡는다.
        worst_sky = max(skies, key=lambda c: int(c))

        days.append(
            DayWeather(
                date=d,
                weekday_ko=_weekday(d),
                temp_max=int(float(cats["TMX"][0])),
                temp_min=int(float(cats["TMN"][0])),
                precip_prob=max(pops),
                sky=SKY_CODE.get(worst_sky, "흐림"),
                resolution="detailed",
            )
        )
    return days


def parse_mid_term(
    land_payload: dict, ta_payload: dict, base_date: date
) -> list[DayWeather]:
    """중기예보(getMidLandFcst + getMidTa) -> 일별 DayWeather.

    중기는 base_date + N일 형태의 평면 키(rnSt5Am, taMax5 ...)로 온다.
    오전/오후 강수확률 중 큰 값을 그날 값으로 삼는다.
    """
    land = _items(land_payload)
    ta = _items(ta_payload)
    if not land or not ta:
        return []
    land, ta = land[0], ta[0]

    days: list[DayWeather] = []
    for n in range(3, 11):
        tmax_key, tmin_key = f"taMax{n}", f"taMin{n}"
        if tmax_key not in ta or tmin_key not in ta:
            continue

        am = land.get(f"rnSt{n}Am")
        pm = land.get(f"rnSt{n}Pm")
        probs = [int(v) for v in (am, pm) if v is not None]

        wf = land.get(f"wf{n}Pm") or land.get(f"wf{n}Am") or "정보없음"
        d = base_date + timedelta(days=n)

        days.append(
            DayWeather(
                date=d,
                weekday_ko=_weekday(d),
                temp_max=int(ta[tmax_key]),
                temp_min=int(ta[tmin_key]),
                precip_prob=max(probs) if probs else 0,
                sky=wf,
                resolution="coarse",
            )
        )
    return days


def merge_forecasts(
    short: list[DayWeather], mid: list[DayWeather], base_date: date
) -> list[DayWeather]:
    """base_date부터 7일을 채운다. 겹치면 해상도 높은 단기를 우선한다.

    어느 쪽에도 없는 날은 빠뜨리지 않고 자리표시자로 채운다.
    배정 단계에서 7칸이 항상 존재한다고 가정할 수 있게 하기 위함이다.
    """
    by_date = {d.date: d for d in mid}
    by_date.update({d.date: d for d in short})  # 단기가 중기를 덮어쓴다

    week: list[DayWeather] = []
    for i in range(7):
        d = base_date + timedelta(days=i)
        week.append(
            by_date.get(
                d,
                DayWeather(
                    date=d,
                    weekday_ko=_weekday(d),
                    temp_min=0,
                    temp_max=0,
                    precip_prob=0,
                    sky="정보없음",
                    resolution="missing",
                ),
            )
        )
    return week
