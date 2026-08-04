"""게시 페이지 아이디어 패널의 묶음·정렬·표시량.

정렬을 HTML 문자열로 확인하면 무엇이 왜 앞에 왔는지 알 수 없다. 묶음
함수를 따로 두고 여기서 직접 본다.
"""
from datetime import datetime

from willy.ideas.models import IdeaItem
from willy.publisher.ideas_section import group_ideas, render_idea_panel


def idea(source="vogue", title="제목", **kwargs) -> IdeaItem:
    return IdeaItem(source=source, title=title, url="https://x.test/1", **kwargs)


# ── 묶음 ──────────────────────────────────────────────────


def test_groups_come_in_declared_order():
    """할인 → 드랍·신상 → 매거진. sources.py 선언 순서가 표시 순서다."""
    items = [idea(source="vogue"), idea(source="eomisae_os"), idea(source="eyesmag")]

    groups = group_ideas(items)

    assert [key for key, _, _ in groups] == ["deal", "drop", "magazine"]
    assert [label for _, label, _ in groups] == ["할인", "드랍·신상", "매거진"]


def test_empty_groups_are_dropped():
    groups = group_ideas([idea(source="eomisae_os")])

    assert [key for key, _, _ in groups] == ["deal"]


def test_no_ideas_gives_no_groups():
    assert group_ideas([]) == []


# ── 묶음 안 정렬 ──────────────────────────────────────────


def test_hot_items_come_first():
    items = [
        idea(source="eomisae_os", title="보통", likes=1),
        idea(source="eomisae_os", title="반응 좋음", likes=9, is_hot=True),
    ]

    _, _, sorted_items = group_ideas(items)[0]

    assert [i.title for i in sorted_items] == ["반응 좋음", "보통"]


def test_items_with_metrics_outrank_items_without():
    """지표가 없는 항목은 '모름'이다. 0으로 보고 맨 뒤로 보내면 안 된다는 게
    아니라, 수치가 있는 것부터 보여줘야 훑는 의미가 있다."""
    items = [
        idea(source="hypebeast", title="지표 없음"),
        idea(source="eyesmag", title="조회 있음", views=3000),
    ]

    _, _, sorted_items = group_ideas(items)[0]

    assert [i.title for i in sorted_items] == ["조회 있음", "지표 없음"]


def test_metric_items_sort_descending():
    items = [
        idea(source="eomisae_os", title="낮음", likes=2),
        idea(source="eomisae_os", title="높음", likes=8),
        idea(source="eomisae_os", title="중간", likes=5),
    ]

    _, _, sorted_items = group_ideas(items)[0]

    assert [i.title for i in sorted_items] == ["높음", "중간", "낮음"]


def test_representative_metric_prefers_likes_over_views():
    """항목마다 다른 지표를 섞어 비교하면 순서가 뒤집힌다. likes를 가진
    항목은 views가 아무리 커도 likes로 비교한다."""
    items = [
        idea(source="eomisae_os", title="좋아요 9", likes=9, views=10),
        idea(source="eomisae_os", title="좋아요 3", likes=3, views=99999),
    ]

    _, _, sorted_items = group_ideas(items)[0]

    assert [i.title for i in sorted_items] == ["좋아요 9", "좋아요 3"]


def test_representative_metric_falls_back_to_comments():
    items = [
        idea(source="eomisae_os", title="댓글 2", comments=2),
        idea(source="eomisae_os", title="댓글 7", comments=7),
    ]

    _, _, sorted_items = group_ideas(items)[0]

    assert [i.title for i in sorted_items] == ["댓글 7", "댓글 2"]


def test_items_without_metrics_sort_by_newest():
    items = [
        idea(source="vogue", title="오래됨", published_at=datetime(2026, 8, 1)),
        idea(source="gq", title="최신", published_at=datetime(2026, 8, 4)),
    ]

    _, _, sorted_items = group_ideas(items)[0]

    assert [i.title for i in sorted_items] == ["최신", "오래됨"]


def test_items_without_metrics_or_dates_keep_input_order():
    items = [
        idea(source="vogue", title="첫째"),
        idea(source="elle", title="둘째"),
        idea(source="gq", title="셋째"),
    ]

    _, _, sorted_items = group_ideas(items)[0]

    assert [i.title for i in sorted_items] == ["첫째", "둘째", "셋째"]


# ── 표시량 ────────────────────────────────────────────────


def test_rows_beyond_ten_are_marked_extra():
    items = [idea(source="vogue", title=f"기사 {n}") for n in range(12)]

    html = render_idea_panel(items)

    assert html.count("is-extra") == 2, "11번째부터 접힘 표시가 붙어야 한다"


def test_more_button_shows_remaining_count():
    items = [idea(source="vogue", title=f"기사 {n}") for n in range(12)]

    html = render_idea_panel(items)

    assert "더 보기 (2건)" in html


def test_ten_or_fewer_has_no_more_button():
    items = [idea(source="vogue", title=f"기사 {n}") for n in range(10)]

    html = render_idea_panel(items)

    assert "더 보기" not in html
    assert "is-extra" not in html


def test_more_button_counts_each_group_separately():
    items = [idea(source="vogue", title=f"기사 {n}") for n in range(12)] + [
        idea(source="eomisae_os", title=f"딜 {n}") for n in range(13)
    ]

    html = render_idea_panel(items)

    assert "더 보기 (3건)" in html, "할인 13건 중 10건 표시 → 3건 남음"
    assert "더 보기 (2건)" in html, "매거진 12건 중 10건 표시 → 2건 남음"


# ── 마크업 ────────────────────────────────────────────────


def test_group_heading_shows_count():
    items = [idea(source="eomisae_os", title=f"딜 {n}") for n in range(3)]

    html = render_idea_panel(items)

    assert "할인" in html
    assert "3건" in html


def test_row_is_a_link_to_the_source():
    """행 전체가 링크여야 폰에서 제목만 겨냥하지 않아도 된다."""
    html = render_idea_panel([idea(source="vogue", title="가을 코트")])

    assert 'class="idea-row"' in html
    assert 'href="https://x.test/1"' in html
    assert 'target="_blank"' in html
    assert 'rel="noopener noreferrer"' in html


def test_meta_line_joins_only_present_values():
    items = [idea(source="eomisae_os", title="딜", likes=3, is_hot=True)]

    html = render_idea_panel(items)

    assert "어미새" in html
    assert "🔥" in html
    assert "♥ 3" in html
    assert "조회" not in html, "views가 없으면 조회 표기가 나오면 안 된다"


def test_titles_are_escaped():
    html = render_idea_panel([idea(title="<script>alert(1)</script>")])

    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_urls_are_escaped():
    item = IdeaItem(
        source="vogue", title="제목", url='https://x.test/"><script>alert(1)</script>'
    )

    html = render_idea_panel([item])

    assert "<script>alert(1)</script>" not in html


def test_photo_grid_classes_are_not_reused():
    """사진용 격자(.pool/.look)를 다시 쓰면 소스 라벨이 제목을 덮는다."""
    html = render_idea_panel([idea()])

    assert 'class="pool"' not in html
    assert 'class="look"' not in html


def test_list_with_extras_is_marked_collapsed():
    """CSS가 접을 대상을 알아야 한다. 접힘 표시는 넘치는 묶음에만 붙는다."""
    items = [idea(source="vogue", title=f"기사 {n}") for n in range(12)]

    html = render_idea_panel(items)

    assert 'class="idea-list is-collapsed"' in html


def test_list_without_extras_is_not_marked_collapsed():
    items = [idea(source="vogue", title=f"기사 {n}") for n in range(10)]

    html = render_idea_panel(items)

    assert "is-collapsed" not in html
