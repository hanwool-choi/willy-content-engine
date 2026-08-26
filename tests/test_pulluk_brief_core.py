# -*- coding: utf-8 -*-
from datetime import date

from tools.pulluk_brief_core import (
    TopicPlan,
    dong_of,
    is_outdoor,
    label_of,
    pick_course,
    pick_deep,
    plan_for,
    recent_topics,
)


def _place(name, cat="식당", c="칼국수", r=1000, lat=37.5, lon=127.0,
           addr="서울 종로구 청진동 1", **extra):
    return {"name": name, "cat": cat, "lat": lat, "lon": lon, "addr": addr,
            "sid": name, "d": {"c": c, "r": r, **extra}}


def _data():
    places = [_place(f"칼국수{i}", r=2000 - i * 10) for i in range(8)]
    places += [_place(f"곰탕{i}", c="곰탕,설렁탕", r=1500 - i * 10) for i in range(8)]
    places += [
        _place("성수식당", c="한식", lat=37.5435, lon=127.048, addr="서울 성동구 성수동1가 1"),
        _place("성수카페", cat="카페", c="카페", lat=37.5440, lon=127.049, addr="서울 성동구 성수동1가 2"),
        _place("서울숲공원", cat="스팟", c="공원", lat=37.5445, lon=127.047, addr="서울 성동구 성수동1가 3"),
        _place("성수편집숍", cat="스팟", c="쇼핑", lat=37.5450, lon=127.050, addr="서울 성동구 성수동1가 4"),
    ]
    regions = [{"name": "성수·서울숲", "sido": "서울", "lat": 37.5435, "lon": 127.048,
                "radius": 1.4, "count": 4}]
    return {"places": places, "regions": regions}


def test_dong_of_strips_numbers():
    assert dong_of("서울 성동구 성수동1가 668-79") == "성수동"


def test_dong_of_falls_back_to_city_for_road_address():
    # 도로명이 나오면 채널 말투와 안 맞으니 시·군 이름으로 물러선다
    assert dong_of("강원 속초시 원문로 123") == "속초"
    assert dong_of("서울 서초구 효령로67길 71-13") == "서초"
    assert dong_of("인천 강화군 대포항희망길 5") == "강화"


def test_is_outdoor_detects_park_only():
    assert is_outdoor(_place("서울숲공원", cat="스팟")) is True
    assert is_outdoor(_place("성수편집숍", cat="스팟")) is False


def test_recent_topics_excludes_old_entries():
    archive = [{"date": "2026-08-25", "topic": "칼국수", "places": []},
               {"date": "2026-01-01", "topic": "곰탕,설렁탕", "places": []}]
    topics = recent_topics(archive, date(2026, 8, 26))
    assert "칼국수" in topics
    assert "곰탕,설렁탕" not in topics


def test_roster_skips_recently_used_topic():
    archive = [{"date": "2026-08-20", "topic": "칼국수", "places": []}]
    plan = plan_for(_data(), archive, date(2026, 8, 24), rainy=False)  # 월요일 → 족보
    assert plan.kind == "족보"
    assert plan.topic != "칼국수"


def test_course_drops_outdoor_places_when_rainy():
    plan = plan_for(_data(), [], date(2026, 8, 25), rainy=True)  # 화요일 → 코스
    assert plan.kind == "코스"
    assert plan.rainy is True
    assert all(not is_outdoor(p) for p in plan.places)


def test_deep_dive_avoids_recent_place():
    plan = TopicPlan(kind="족보", topic="칼국수", title="t",
                     places=[_place("칼국수0"), _place("칼국수1")])
    archive = [{"date": "2026-08-25", "topic": "x", "places": [], "deep": "칼국수0"}]
    deep = pick_deep(plan, archive, date(2026, 8, 26))
    assert deep is not None and deep["name"] == "칼국수1"


def test_plan_always_returns_something():
    plan = plan_for({"places": [], "regions": []}, [], date(2026, 8, 24), rainy=False)
    assert plan.places == []
    assert plan.note


def _drive_data():
    """부산(원거리)과 수원(근교) 두 후보를 같이 담은 데이터."""
    busan, suwon = (35.1796, 129.0756), (37.2636, 127.0286)
    places = []
    for tag, (lat, lon) in (("부산", busan), ("수원", suwon)):
        places += [
            _place(f"{tag}밥집", lat=lat, lon=lon, addr=f"{tag} 어딘가 어딘동 1"),
            _place(f"{tag}카페", cat="카페", c="카페", lat=lat + 0.002, lon=lon,
                   addr=f"{tag} 어딘가 어딘동 2"),
            _place(f"{tag}스팟", cat="스팟", c="쇼핑", lat=lat, lon=lon + 0.002,
                   addr=f"{tag} 어딘가 어딘동 3"),
        ]
    regions = [
        {"name": "해운대·부산", "sido": "부산", "lat": busan[0], "lon": busan[1],
         "radius": 1.4, "count": 99},
        {"name": "행궁동·수원", "sido": "경기", "lat": suwon[0], "lon": suwon[1],
         "radius": 1.4, "count": 3},
    ]
    return {"places": places, "regions": regions}


def test_drive_course_skips_regions_beyond_day_trip_range():
    # 후보 수는 부산이 훨씬 많지만 당일 왕복권이 아니라 빠져야 한다.
    plan = pick_course(_drive_data(), [], date(2026, 8, 29), rainy=False, drive=True)
    assert plan is not None
    assert plan.topic == "행궁동·수원"
    assert all("부산" not in p["name"] for p in plan.places)


def test_label_of_uses_region_name_when_inside():
    regions = [{"name": "성수·서울숲", "lat": 37.5435, "lon": 127.048, "radius": 1.4}]
    inside = _place("성수식당", lat=37.5440, lon=127.049, addr="서울 성동구 성수동1가 1")
    assert label_of(inside, regions) == "성수"


def test_label_of_falls_back_to_dong_outside_regions():
    regions = [{"name": "성수·서울숲", "lat": 37.5435, "lon": 127.048, "radius": 1.4}]
    outside = _place("서초카페", lat=37.4848, lon=127.0237,
                     addr="서울 서초구 효령로70길 36-27")
    # regions 밖이라 주소 토큰(도로명)으로 떨어진다 — 폴백이 살아 있는지만 본다.
    assert label_of(outside, regions) == dong_of("서울 서초구 효령로70길 36-27")


def test_plan_for_fills_label_on_places_and_deep():
    plan = plan_for(_data(), [], date(2026, 8, 25), rainy=False)  # 화요일 → 코스
    assert plan.places and all(p.get("label") for p in plan.places)
    assert plan.deep is not None and plan.deep.get("label") == "성수"


def test_fallback_note_uses_correct_particle():
    # 토요일(드라이브)인데 서울 region뿐이라 족보로 대체된다.
    plan = plan_for(_data(), [], date(2026, 8, 29), rainy=False)
    assert "드라이브 소재가 부족해 족보 유형으로 대체함" in plan.note
