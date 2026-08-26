# -*- coding: utf-8 -*-
"""오늘의 브리핑 주제를 고르는 순수 로직.

네트워크·파일 I/O를 두지 않는다. 로테이션 규칙을 바꿔도 전송이나
발행 코드를 건드릴 일이 없고, 테스트가 빨라진다.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import date, datetime

# 요일별 기본 골격 (0=월). 설계 문서 §4.1
ROTATION = {0: "족보", 1: "코스", 2: "족보", 3: "코스", 4: "족보", 5: "드라이브", 6: "변주"}

# 월별 가중 키워드. 세부업종에 부분 문자열로 걸리면 가산점을 준다.
SEASON_KEYWORDS = {
    1: ("칼국수", "곰탕"), 2: ("곰탕", "만두"), 3: ("막국수", "칼국수"),
    4: ("막국수", "냉면"), 5: ("냉면", "막국수"), 6: ("냉면", "콩국수"),
    7: ("냉면", "콩국수", "막국수"), 8: ("냉면", "콩국수", "막국수"),
    9: ("칼국수", "순대"), 10: ("칼국수", "곰탕"), 11: ("곰탕", "순대"), 12: ("곰탕", "만두"),
}

# 비 오는 날 코스에서 뺄 장소. 이름·업종에 이 단어가 있으면 야외로 본다.
OUTDOOR_HINTS = ("공원", "숲", "해변", "호수", "산책", "강변", "천변", "피크닉")

# 일요일 변주 편 주제. (테마, 이름·업종 매칭 힌트)
VARIETY_THEMES = (
    ("해장", ("해장", "국밥", "순대", "곰탕", "감자탕")),
    ("혼밥", ("국밥", "순대", "칼국수", "덮밥", "라면", "라멘")),
    ("심야", ()),           # 영업시간 힌트로 거른다
    ("주차 되는 집", ()),    # d.pk == 1 로 거른다
)

# 족보로 쓰기엔 너무 넓은 업종. 이걸로 묶으면 주제가 안 선다.
BROAD_CATEGORIES = ("한식", "육류,고기요리", "양식", "일식당", "중식당")

TOPIC_DAYS = 60   # 같은 주제 재사용 금지 기간
PLACE_DAYS = 30   # 같은 가게 재등장 금지 기간
MIN_ROSTER = 5
MAX_ROSTER = 6
MIN_COURSE_STOPS = 3


@dataclass
class TopicPlan:
    kind: str                       # 족보 | 코스 | 드라이브 | 변주
    topic: str                      # "칼국수" / "성수·서울숲"
    title: str                      # 카톡·페이지 제목
    places: list[dict] = field(default_factory=list)
    deep: dict | None = None
    rainy: bool = False
    note: str = ""                  # 소재 부족 등 사람에게 알릴 말


def dong_of(addr: str) -> str:
    """주소에서 동네 토큰을 뽑는다. "서울 성동구 성수동1가 668-79" → "성수동"."""
    parts = (addr or "").split()
    token = parts[2] if len(parts) > 2 else (parts[1] if len(parts) > 1 else "")
    return re.sub(r"\d.*$", "", token)


def category_of(place: dict) -> str:
    return ((place.get("d") or {}).get("c") or "").strip()


def review_of(place: dict) -> int:
    return int((place.get("d") or {}).get("r") or 0)


def is_outdoor(place: dict) -> bool:
    if place.get("cat") != "스팟":
        return False
    blob = place.get("name", "") + " " + category_of(place)
    return any(hint in blob for hint in OUTDOOR_HINTS)


def _within(entry_date: str, today: date, days: int) -> bool:
    try:
        parsed = datetime.strptime(entry_date, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return False
    # 아카이브는 발행 이력이라 미래 날짜가 있을 수 없다. 과거 방향으로만 센다.
    return 0 <= (today - parsed).days <= days


def recent_topics(archive: list[dict], today: date, days: int = TOPIC_DAYS) -> set[str]:
    return {e["topic"] for e in archive
            if e.get("topic") and _within(e.get("date", ""), today, days)}


def recent_places(archive: list[dict], today: date, days: int = PLACE_DAYS) -> set[str]:
    names: set[str] = set()
    for entry in archive:
        if not _within(entry.get("date", ""), today, days):
            continue
        names.update(entry.get("places") or [])
        if entry.get("deep"):
            names.add(entry["deep"])
    return names


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    rad = math.pi / 180
    a = (math.sin((lat2 - lat1) * rad / 2) ** 2
         + math.cos(lat1 * rad) * math.cos(lat2 * rad) * math.sin((lon2 - lon1) * rad / 2) ** 2)
    return 2 * 6371.0 * math.asin(math.sqrt(a))


def pick_roster(data: dict, archive: list[dict], today: date, rainy: bool) -> TopicPlan | None:
    """카테고리 족보. 최근 안 쓴 업종 중 리뷰 총량이 두꺼운 쪽을 고른다."""
    used_topics = recent_topics(archive, today)
    used_places = recent_places(archive, today)
    season = SEASON_KEYWORDS.get(today.month, ())

    buckets: dict[str, list[dict]] = {}
    for place in data.get("places", []):
        if place.get("cat") not in ("식당", "바"):
            continue
        cat = category_of(place)
        if not cat or cat in BROAD_CATEGORIES:
            continue
        buckets.setdefault(cat, []).append(place)

    scored: list[tuple[float, str, list[dict]]] = []
    for cat, places in buckets.items():
        if cat in used_topics:
            continue
        fresh = [p for p in places if p.get("name") not in used_places]
        if len(fresh) < MIN_ROSTER:
            continue
        fresh.sort(key=review_of, reverse=True)
        top = fresh[:MAX_ROSTER]
        score = sum(review_of(p) for p in top) / 1000.0
        if any(keyword in cat for keyword in season):
            score += 50.0
        scored.append((score, cat, top))

    if not scored:
        return None
    scored.sort(key=lambda item: -item[0])
    _, cat, top = scored[0]
    return TopicPlan(kind="족보", topic=cat,
                     title=f"수도권 {cat.split(',')[0]} 탑티어 족보",
                     places=top, rainy=rainy)


def pick_course(data: dict, archive: list[dict], today: date, rainy: bool,
                drive: bool) -> TopicPlan | None:
    """지역 코스. 식당→스팟→카페→식당 순서로 가까운 곳을 이어 붙인다."""
    used_topics = recent_topics(archive, today)
    used_places = recent_places(archive, today)

    regions = [r for r in data.get("regions", []) if r.get("name") not in used_topics]
    regions = [r for r in regions if (r.get("sido") != "서울") == drive]
    regions.sort(key=lambda r: -r.get("count", 0))

    for region in regions:
        pool: dict[str, list[dict]] = {}
        for place in data.get("places", []):
            if haversine_km(region["lat"], region["lon"],
                            place["lat"], place["lon"]) > region.get("radius", 1.4):
                continue
            if place.get("name") in used_places:
                continue
            if rainy and is_outdoor(place):
                continue
            pool.setdefault(place.get("cat", ""), []).append(place)

        stops: list[dict] = []
        cur: dict | None = None
        for slot in ("식당", "스팟", "카페", "식당"):
            cands = [p for p in pool.get(slot, []) if p not in stops]
            if not cands:
                continue
            if cur is None:
                cands.sort(key=review_of, reverse=True)
            else:
                cands.sort(key=lambda p: haversine_km(cur["lat"], cur["lon"], p["lat"], p["lon"]))
            stops.append(cands[0])
            cur = cands[0]

        if len(stops) >= MIN_COURSE_STOPS:
            kind = "드라이브" if drive else "코스"
            suffix = "근교 드라이브 코스" if drive else "하루 코스"
            return TopicPlan(kind=kind, topic=region["name"],
                             title=f"{region['name']} {suffix}", places=stops, rainy=rainy,
                             note="비 예보라 실내 위주로 짰다" if rainy else "")
    return None


def pick_variety(data: dict, archive: list[dict], today: date, rainy: bool) -> TopicPlan | None:
    """일요일 변주 편. 상황형 테마로 5~6곳을 모은다."""
    used_topics = recent_topics(archive, today)
    used_places = recent_places(archive, today)

    for theme, hints in VARIETY_THEMES:
        if theme in used_topics:
            continue
        picked: list[dict] = []
        for place in data.get("places", []):
            if place.get("cat") not in ("식당", "바") or place.get("name") in used_places:
                continue
            detail = place.get("d") or {}
            if theme == "심야":
                matched = any(t in (detail.get("h") or "") for t in ("23:", "24:", "다음 날"))
            elif theme == "주차 되는 집":
                matched = detail.get("pk") == 1
            else:
                blob = place.get("name", "") + " " + category_of(place)
                matched = any(hint in blob for hint in hints)
            if matched:
                picked.append(place)
        if len(picked) >= MIN_ROSTER:
            picked.sort(key=review_of, reverse=True)
            return TopicPlan(kind="변주", topic=theme, title=f"{theme} 탑티어 족보",
                             places=picked[:MAX_ROSTER], rainy=rainy)
    return None


def pick_deep(plan: TopicPlan, archive: list[dict], today: date) -> dict | None:
    """집중분석 1곳. 최근 다룬 곳은 빼고 정보가 가장 촘촘한 집을 고른다."""
    used = recent_places(archive, today)
    cands = [p for p in plan.places if p.get("name") not in used] or list(plan.places)
    if not cands:
        return None

    def richness(place: dict) -> tuple[int, int]:
        detail = place.get("d") or {}
        filled = sum(1 for key in ("c", "r", "s", "h", "pk") if detail.get(key) is not None)
        return (filled, review_of(place))

    return max(cands, key=richness)


def plan_for(data: dict, archive: list[dict], today: date, rainy: bool) -> TopicPlan:
    """요일 로테이션대로 시도하고, 소재가 없으면 다른 유형으로 넘어간다."""
    wanted = ROTATION[today.weekday()]
    order = [wanted] + [k for k in ("족보", "코스", "변주", "드라이브") if k != wanted]

    for kind in order:
        if kind == "족보":
            plan = pick_roster(data, archive, today, rainy)
        elif kind == "코스":
            plan = pick_course(data, archive, today, rainy, drive=False)
        elif kind == "드라이브":
            plan = pick_course(data, archive, today, rainy, drive=True)
        else:
            plan = pick_variety(data, archive, today, rainy)
        if plan is not None:
            if kind != wanted:
                extra = f"{wanted} 소재가 부족해 {kind}으로 대체함"
                plan.note = f"{plan.note} / {extra}" if plan.note else extra
            plan.deep = pick_deep(plan, archive, today)
            return plan

    return TopicPlan(kind=wanted, topic="소재 부족", title="오늘은 소재가 부족합니다",
                     places=[], rainy=rainy,
                     note="즐겨찾기를 더 넣거나 중복 금지 기간을 줄여야 한다")
