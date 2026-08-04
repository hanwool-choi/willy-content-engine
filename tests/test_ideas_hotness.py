from willy.ideas.hotness import HOT_THRESHOLDS, mark_hot
from willy.ideas.models import IdeaItem


def item(source="eomisae_os", **kwargs) -> IdeaItem:
    return IdeaItem(source=source, title="제목", url="https://x.test/1", **kwargs)


def test_marks_hot_when_any_metric_passes_threshold():
    """어미새는 좋아요 5 또는 댓글 10이 기준이다."""
    marked = mark_hot([item(likes=5, comments=0), item(likes=0, comments=10)])

    assert [i.is_hot for i in marked] == [True, True]


def test_below_threshold_is_not_hot():
    marked = mark_hot([item(likes=4, comments=9)])

    assert marked[0].is_hot is False


def test_unknown_metric_does_not_count_as_zero():
    """지표를 주지 않는 소스를 0으로 보면 판정이 틀어진다."""
    marked = mark_hot([item(likes=None, comments=None)])

    assert marked[0].is_hot is False


def test_source_without_thresholds_is_never_hot():
    """하입비스트·매거진은 반응 데이터가 없다. 뱃지 대신 카테고리를 쓴다."""
    marked = mark_hot([item(source="vogue", views=999999)])

    assert marked[0].is_hot is False


def test_eyesmag_uses_view_threshold():
    marked = mark_hot(
        [item(source="eyesmag", views=5000), item(source="eyesmag", views=4999)]
    )

    assert [i.is_hot for i in marked] == [True, False]


def test_thresholds_only_cover_sources_that_report_reactions():
    assert set(HOT_THRESHOLDS) == {"eomisae_os", "eyesmag"}


def test_mark_hot_does_not_mutate_input():
    """원본을 바꾸면 같은 목록을 두 번 판정할 때 결과가 달라진다."""
    original = item(likes=5)

    mark_hot([original])

    assert original.is_hot is False
