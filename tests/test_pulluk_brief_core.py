# -*- coding: utf-8 -*-
from datetime import date

from tools.pulluk_brief_core import (
    TopicPlan,
    dong_of,
    is_outdoor,
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
