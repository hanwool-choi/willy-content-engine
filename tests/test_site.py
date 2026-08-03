from datetime import date, datetime
from pathlib import Path

import pytest

from willy.models import DayWeather, Gender, LookAnalysis
from willy.pipeline import PipelineState
from willy.publisher.site import render_site


def day(pop: int = 0) -> DayWeather:
    return DayWeather(
        date=date(2026, 8, 4), weekday_ko="화", temp_max=34, temp_min=27,
        precip_prob=pop, sky="맑음", resolution="detailed",
    )


def look(look_id="L1", gender=Gender.MEN, tags=None, image_url="https://cdn.test/a.jpg",
         source_url="https://www.musinsa.com/snap/1", is_ai=False) -> LookAnalysis:
    return LookAnalysis(
        look_id=look_id, source="musinsa_snap", gender=gender,
        temp_range=(24, 32), rain_ok=False, season="summer",
        style_tags=tags or ["미니멀"], image_path=Path(f"/tmp/{look_id}.jpg"),
        is_ai=is_ai, source_url=source_url, image_url=image_url,
    )


def state_with(looks=None, assignment=None, caveats=None, pop=0) -> PipelineState:
    looks = looks if looks is not None else [look()]
    if assignment is None:
        assignment = {(day().date, Gender.MEN, 0): looks[0]}
    return PipelineState(
        week=[day(pop)], looks=looks, assignment=assignment,
        warnings=[], caveats=caveats or {},
    )


TEXTS = [
    {"tone": "기본 정보형", "text": "내일 34도. 본문"},
    {"tone": "담백 미니멀", "text": "34도. 짧게"},
    {"tone": "위트", "text": "34도 웃김"},
]

STAMP = datetime(2026, 8, 3, 8, 0)


def test_renders_weather():
    html = render_site(state_with(), TEXTS, STAMP)

    assert "34" in html and "27" in html
    assert "맑음" in html
    assert "08.04" in html or "8/4" in html


def test_hotlinks_cdn_images_instead_of_local_paths():
    """사진을 재업로드하지 않는다. 원본 CDN 주소로 바로 띄운다."""
    html = render_site(state_with(), TEXTS, STAMP)

    assert "https://cdn.test/a.jpg" in html
    assert "/api/image/" not in html, "로컬 서버 경로가 정적 페이지에 남았다"
    assert "/tmp/L1.jpg" not in html, "로컬 파일 경로가 새어 나갔다"


def test_links_to_source_page():
    html = render_site(state_with(), TEXTS, STAMP)

    assert "https://www.musinsa.com/snap/1" in html


def test_look_without_cdn_url_is_link_only_without_broken_image():
    """캡처로 만든 룩은 CDN 주소가 없다. 깨진 이미지를 넣지 않는다."""
    bare = look(image_url=None)
    html = render_site(state_with(looks=[bare]), TEXTS, STAMP)

    assert "src=\"\"" not in html
    assert "src=\"None\"" not in html
    assert "이미지 없음" in html


def test_renders_all_three_texts_with_tones():
    html = render_site(state_with(), TEXTS, STAMP)

    for entry in TEXTS:
        assert entry["tone"] in html
        assert entry["text"] in html


def test_escapes_model_derived_values():
    """공개 페이지다. 모델이 만든 값이 그대로 실행되면 안 된다."""
    evil_look = look(tags=["<script>alert(1)</script>"])
    evil_texts = [
        {"tone": "<img src=x onerror=alert(2)>", "text": "<script>alert(3)</script>"},
        *TEXTS[1:],
    ]

    html = render_site(state_with(looks=[evil_look]), evil_texts, STAMP)

    # 꺾쇠가 살아 있으면 태그로 실행된다. 이스케이프된 텍스트로만 남아야 한다.
    assert "<script>alert(1)</script>" not in html
    assert "<script>alert(3)</script>" not in html
    assert "<img src=x onerror" not in html
    assert "&lt;script&gt;" in html


def test_shows_generated_timestamp():
    html = render_site(state_with(), TEXTS, STAMP)

    assert "2026-08-03" in html and "08:00" in html


def test_marks_conditional_and_ai_looks():
    ai_look = look(look_id="L9", is_ai=True)
    slot = (day().date, Gender.MEN, 0)
    html = render_site(
        state_with(looks=[ai_look], assignment={slot: ai_look},
                   caveats={slot: "우천 부적합 — 기온은 적합"}),
        TEXTS, STAMP,
    )

    assert "AI" in html
    assert "우천 부적합" in html


def test_is_self_contained_without_external_assets():
    """오프라인 CSS·JS 의존이 없어야 정적 호스팅에서 그대로 뜬다."""
    html = render_site(state_with(), TEXTS, STAMP)

    assert "<link" not in html.lower() or "stylesheet" not in html.lower()
    assert "<!doctype html>" in html.lower()


def test_survives_empty_board_and_texts():
    empty = PipelineState(
        week=[day()], looks=[], assignment={}, warnings=[], caveats={},
    )

    html = render_site(empty, [], STAMP)

    assert "<!doctype html>" in html.lower()
    assert "수집된 룩이 없습니다" in html
