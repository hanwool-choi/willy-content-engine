from tools.pulluk_brief_core import TopicPlan
from tools.pulluk_brief_text import checklist, compose, one_liner, template_draft


def _place(name, **detail):
    return {"name": name, "cat": "식당", "lat": 37.5, "lon": 127.0,
            "addr": "서울 서초구 서초동 1", "sid": name,
            "d": {"c": "칼국수", "r": 3150, "s": 4.5, **detail}}


def _roster_plan():
    places = [_place(f"집{i}") for i in range(5)]
    return TopicPlan(kind="족보", topic="칼국수", title="수도권 칼국수 탑티어 족보",
                     places=places, deep=places[0])


def _course_plan():
    places = [_place("밥집"), _place("구경거리"), _place("커피집")]
    return TopicPlan(kind="코스", topic="성수·서울숲", title="성수·서울숲 하루 코스",
                     places=places, deep=places[0])


def test_one_liner_marks_unverified():
    assert one_liner(_place("집")).endswith("※확인")
    assert "리뷰 3,150" in one_liner(_place("집"))


def test_roster_draft_has_channel_markers():
    draft = template_draft(_roster_plan())
    assert "탑티어 족보 정리해봄" in draft
    assert "*광고/협찬 아님" in draft
    assert "1. 집0(서초동)" in draft
    assert "(+) 팔로우 해두면 맛집/카페/볼거리 매일 올라옴" in draft


def test_course_draft_uses_course_opening():
    draft = template_draft(_course_plan())
    assert "목적지 정해지면 코스부터 짜는 파워J가" in draft
    assert "🚩밥집" in draft


def test_compose_falls_back_to_template_without_key():
    draft, source = compose(_roster_plan(), api_key=None)
    assert source == "template"
    assert "탑티어 족보 정리해봄" in draft


def test_compose_uses_generator_when_available():
    def fake_generate(http, api_key, payload, sleep):
        return "AI가 쓴 초안"

    draft, source = compose(_roster_plan(), api_key="key", generate=fake_generate)
    assert source == "ai"
    assert draft == "AI가 쓴 초안"


def test_compose_falls_back_when_generator_raises():
    def broken(http, api_key, payload, sleep):
        raise RuntimeError("429")

    draft, source = compose(_roster_plan(), api_key="key", generate=broken)
    assert source == "template"


def test_checklist_mentions_verification():
    checks = checklist(_roster_plan())
    assert any("※확인" in c or "한줄평" in c for c in checks)
    assert any("가격" in c or "영업" in c for c in checks)
