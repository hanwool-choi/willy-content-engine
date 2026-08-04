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


def test_renders_warnings_so_degraded_runs_are_visible():
    """폴백은 워크플로를 성공으로 끝내므로, 페이지가 알려주지 않으면
    분석이 빠진 날을 아무도 눈치채지 못한다."""
    from willy.models import Warning, WarningCode

    st = state_with()
    st.warnings = [
        Warning(
            code=WarningCode.ANALYSIS_SKIPPED, slot_date=day().date, gender=None,
            message="비전 분석에 실패해 분석 생략 모드로 진행합니다.",
        )
    ]

    html = render_site(st, TEXTS, STAMP)

    assert "분석 생략 모드" in html
    assert "class=\"notice" in html


def test_no_notice_block_when_there_are_no_warnings():
    html = render_site(state_with(), TEXTS, STAMP)

    assert "class=\"notice" not in html


def test_warning_messages_are_escaped():
    from willy.models import Warning, WarningCode

    st = state_with()
    st.warnings = [
        Warning(code=WarningCode.EMPTY_SLOT, slot_date=None, gender=None,
                message="<script>alert(9)</script>")
    ]

    html = render_site(st, TEXTS, STAMP)

    assert "<script>alert(9)</script>" not in html


# ── 원본 링크 절대화 ──────────────────────────────────────

def test_relative_source_links_become_absolute():
    """유니클로·WEAR는 상대경로 href를 준다. 그대로 두면 게시 도메인
    (github.io)으로 붙어 깨진다."""
    uniqlo = LookAnalysis(
        look_id="U1", source="uniqlo_men", gender=Gender.MEN, temp_range=(24, 32),
        rain_ok=False, season="summer", style_tags=[],
        source_url="/kr/ko/stylingbook/stylehint/15043829",
        image_url="https://cdn.test/u.jpg",
    )
    wear = LookAnalysis(
        look_id="W1", source="wear_men", gender=Gender.MEN, temp_range=(24, 32),
        rain_ok=False, season="summer", style_tags=[],
        source_url="/rei718/27136486/", image_url="https://cdn.test/w.jpg",
    )

    html = render_site(state_with(looks=[uniqlo, wear], assignment={}), TEXTS, STAMP)

    assert "https://www.uniqlo.com/kr/ko/stylingbook/stylehint/15043829" in html
    assert "https://wear.jp/rei718/27136486/" in html
    assert 'href="/kr/ko' not in html
    assert 'href="/rei718' not in html


def test_absolute_source_link_is_left_alone():
    html = render_site(state_with(), TEXTS, STAMP)

    assert "https://www.musinsa.com/snap/1" in html
    assert "https://www.musinsa.comhttps://" not in html


def test_non_http_source_link_is_dropped():
    """스킴이 http(s)가 아니면 링크를 걸지 않는다."""
    evil = look(source_url="javascript:alert(1)")

    html = render_site(state_with(looks=[evil], assignment={}), TEXTS, STAMP)

    assert "javascript:alert" not in html


# ── 확대 보기와 이미지 저장 ────────────────────────────────

def test_thumbnails_carry_lightbox_data():
    html = render_site(state_with(), TEXTS, STAMP)

    assert 'data-full="https://cdn.test/a.jpg"' in html
    assert 'data-link="https://www.musinsa.com/snap/1"' in html


def test_page_has_lightbox_with_save_and_source_actions():
    html = render_site(state_with(), TEXTS, STAMP)

    assert 'id="lightbox"' in html
    assert "이미지 저장" in html
    assert "원본 페이지" in html
    assert "Escape" in html, "Esc로 닫는 처리가 없다"


def test_save_falls_back_to_new_tab_when_cors_blocks_fetch():
    """무신사·WEAR CDN은 CORS를 허용하지 않아 blob 저장이 실패한다.
    그때는 새 탭으로 열어 사용자가 직접 저장할 수 있어야 한다."""
    html = render_site(state_with(), TEXTS, STAMP)

    assert "window.open" in html
    assert "createObjectURL" in html


# ── 공유 미리보기(오픈그래프) ──────────────────────────────

def test_page_title_is_the_platform_name():
    html = render_site(state_with(), TEXTS, STAMP)

    assert "<title>최윌리 옷장연구소 콘텐츠 플랫폼</title>" in html


def test_open_graph_tags_for_link_previews():
    html = render_site(state_with(), TEXTS, STAMP, og_image="og.png")

    assert 'property="og:title" content="최윌리 옷장연구소 콘텐츠 플랫폼"' in html
    assert 'property="og:type"' in html
    assert 'property="og:description"' in html
    assert 'name="twitter:card" content="summary_large_image"' in html


def test_og_image_url_is_absolute():
    """상대경로 og:image는 카카오톡·슬랙 등에서 무시된다."""
    html = render_site(state_with(), TEXTS, STAMP, og_image="og.png")

    assert (
        'property="og:image" '
        'content="https://hanwool-choi.github.io/willy-content-engine/og.png"' in html
    )
    assert 'property="og:url" content="https://hanwool-choi.github.io/' in html


def test_absolute_og_image_is_left_alone():
    html = render_site(
        state_with(), TEXTS, STAMP, og_image="https://cdn.test/custom-og.png"
    )

    assert 'content="https://cdn.test/custom-og.png"' in html


def test_no_og_image_tag_when_file_is_missing():
    """이미지가 없는데 태그만 남기면 미리보기가 깨진 채로 뜬다."""
    html = render_site(state_with(), TEXTS, STAMP, og_image=None)

    assert "og:image" not in html
    assert 'property="og:title"' in html, "이미지가 없어도 제목·설명은 남는다"


# ── 콘텐츠 아이디어 보울 (읽기 전용) ────────────────────────

def _idea(**kwargs):
    from willy.ideas.models import IdeaItem

    base = dict(
        source="eyesmag", title="버켄스탁 x 아더에러 협업", url="https://x.test/1"
    )
    base.update(kwargs)
    return IdeaItem(**base)


def test_site_renders_idea_section():
    ideas = [_idea(category="패션 > 슈즈", views=9000, is_hot=True)]

    html = render_site(state_with(), TEXTS, STAMP, ideas=ideas)

    assert "콘텐츠 아이디어 보울" in html
    assert "버켄스탁 x 아더에러 협업" in html
    assert "https://x.test/1" in html
    assert "🔥" in html
    assert "아이즈" in html, "소스 배지가 보여야 어디서 온 소식인지 안다"


def test_site_without_ideas_omits_the_section():
    html = render_site(state_with(), TEXTS, STAMP, ideas=[])

    assert "콘텐츠 아이디어 보울" not in html


def test_published_idea_section_has_no_selection_controls():
    """정적 페이지라 선택·생성이 불가능하다. 되는 척하면 안 된다."""
    html = render_site(state_with(), TEXTS, STAMP, ideas=[_idea()])

    assert "읽기 전용" in html
    assert 'type="checkbox"' not in html


def test_idea_titles_are_escaped_on_the_published_page():
    ideas = [_idea(source="vogue", title="<script>alert(1)</script>")]

    html = render_site(state_with(), TEXTS, STAMP, ideas=ideas)

    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html
