from willy.ideas.models import IdeaItem
from willy.ideas.sources import IDEA_SOURCES, SOURCE_GROUPS


def test_idea_item_defaults_are_unknown_not_zero():
    """반응 수를 모르는 소스와 0인 소스는 다르다. 0으로 채우면 뱃지 판정이 틀어진다."""
    item = IdeaItem(
        source="hypebeast",
        title="Palace 2026 가을 컬렉션",
        url="https://hypebeast.kr/2026/8/palace",
    )

    assert item.views is None
    assert item.comments is None
    assert item.likes is None
    assert item.is_hot is False
    assert item.published_at is None


def test_seven_sources_are_registered():
    assert set(IDEA_SOURCES) == {
        "eomisae_os", "eyesmag", "hypebeast", "esquire", "gq", "elle", "vogue",
    }


def test_robots_blocked_sites_are_absent():
    """무신사 매거진·에펨코리아·딜바다는 robots.txt가 막는다. 되살아나면 안 된다."""
    joined = " ".join(source.url for source in IDEA_SOURCES.values())

    assert "musinsa.com/magazine" not in joined
    assert "fmkorea" not in joined
    assert "dealbada" not in joined


def test_every_source_declares_kind_and_group():
    for name, source in IDEA_SOURCES.items():
        assert source.kind in {"rss", "eomisae", "hearst", "condenast", "eyesmag"}, name
        assert source.group in SOURCE_GROUPS, name
        assert source.url.startswith("https://"), name


def test_groups_cover_the_filter_chips():
    assert SOURCE_GROUPS == {
        "deal": "할인",
        "drop": "드랍·신상",
        "magazine": "매거진",
    }
    assert IDEA_SOURCES["eomisae_os"].group == "deal"
    assert IDEA_SOURCES["eyesmag"].group == "drop"
    assert IDEA_SOURCES["vogue"].group == "magazine"


def test_only_eyesmag_needs_a_browser():
    """브라우저는 느리고 배치에서만 쓸 수 있다. 늘어나면 곧바로 알아채야 한다."""
    browser_sources = [n for n, s in IDEA_SOURCES.items() if s.needs_browser]

    assert browser_sources == ["eyesmag"]
