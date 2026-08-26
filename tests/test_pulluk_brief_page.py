from datetime import date

from tools.pulluk_brief_core import TopicPlan
from tools.pulluk_brief_page import render_brief, render_index


def _plan():
    place = {"name": "칼국수집", "cat": "식당", "lat": 37.5, "lon": 127.0,
             "addr": "서울 서초구 서초동 1", "sid": "123", "d": {"c": "칼국수", "r": 100}}
    return TopicPlan(kind="족보", topic="칼국수", title="수도권 칼국수 탑티어 족보",
                     places=[place], deep=place)


def test_render_brief_contains_draft_and_copy_button():
    html = render_brief(_plan(), "초안 본문", ["확인1"], date(2026, 8, 26), "template")
    assert "초안 본문" in html
    assert "복사" in html
    assert "수도권 칼국수 탑티어 족보" in html
    assert "확인1" in html
    assert "map.naver.com/p/entry/place/123" in html


def test_render_brief_escapes_html_in_draft():
    html = render_brief(_plan(), "<script>alert(1)</script>", [], date(2026, 8, 26), "ai")
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_render_index_lists_dates_newest_first():
    archive = [{"date": "2026-08-25", "title": "어제 것", "kind": "코스"},
               {"date": "2026-08-26", "title": "오늘 것", "kind": "족보"}]
    html = render_index(archive)
    assert html.index("2026-08-26") < html.index("2026-08-25")


def test_render_brief_uses_label_when_present():
    plan = _plan()
    plan.places[0]["label"] = "강남"
    html = render_brief(plan, "초안", [], date(2026, 8, 26), "template")
    # 목록의 동네 자리가 label로 바뀌었는지만 본다(집중분석 주소에는 원문이 남는다).
    assert "칼국수집</a> · 강남" in html
    assert "· 서초동 ·" not in html
