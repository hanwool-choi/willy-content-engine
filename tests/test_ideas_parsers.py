from pathlib import Path

import pytest

from willy.ideas.parsers import (
    parse_condenast,
    parse_eomisae,
    parse_eyesmag,
    parse_hearst,
    parse_rss,
)

FIXTURES = Path(__file__).parent / "fixtures" / "ideas"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


# ── RSS (하입비스트) ──────────────────────────────────────


def test_rss_maps_title_link_and_category():
    items = parse_rss(fixture("hypebeast.xml"), source="hypebeast")

    assert len(items) == 2, "제목이 빈 항목은 버려야 한다"
    first = items[0]
    assert first.source == "hypebeast"
    assert first.title == "Palace 2026 가을 컬렉션 및 발매일 공개"
    assert first.url == "https://hypebeast.kr/2026/8/palace-fall-2026-full-collection"
    assert first.category == "패션"


def test_rss_parses_pubdate_as_aware_datetime():
    """RFC822 문자열을 그대로 두면 정렬이 문자열 비교가 된다."""
    items = parse_rss(fixture("hypebeast.xml"), source="hypebeast")

    published = items[0].published_at
    assert published is not None
    assert published.year == 2026 and published.month == 8 and published.day == 3
    assert published.tzinfo is not None


def test_rss_leaves_reaction_fields_unknown():
    """하입비스트는 반응 수를 주지 않는다. 0으로 채우면 안 된다."""
    items = parse_rss(fixture("hypebeast.xml"), source="hypebeast")

    assert items[0].views is None and items[0].likes is None


def test_rss_survives_missing_pubdate():
    items = parse_rss(fixture("hypebeast.xml"), source="hypebeast")

    assert items[1].published_at is not None


def test_rss_raises_on_broken_xml():
    """사이트가 점검 페이지를 내려줄 때가 있다. 수집기 전체를 죽이지 않는다."""
    with pytest.raises(ValueError, match="RSS를 파싱할 수 없습니다"):
        parse_rss("<html>점검 중", source="hypebeast")


# ── 어미새 ────────────────────────────────────────────────


def eomisae_items():
    return parse_eomisae(
        fixture("eomisae_os.html"),
        source="eomisae_os",
        base_url="https://eomisae.co.kr/os",
    )


def test_eomisae_extracts_title_link_and_reactions():
    first = eomisae_items()[0]

    assert first.title == "스탠 스미스 디콘(decon) 4종 9.9만 아래"
    assert first.url == "https://eomisae.co.kr/os/196764338"
    assert first.views == 1317
    assert first.comments == 5
    assert first.likes == 3
    assert first.category == "패션"


def test_eomisae_makes_thumbnail_absolute():
    """//로 시작하는 프로토콜 상대 주소는 정적 페이지에서 깨진다."""
    assert eomisae_items()[0].thumbnail_url == (
        "https://img.eomisae.co.kr/files/thumbnails/338/764/196/190x190.crop.jpg?t=1785802954"
    )


def test_eomisae_keeps_zero_reactions_as_zero():
    """0회와 '모름'은 다르다. 댓글 0은 0으로 남아야 한다."""
    second = eomisae_items()[1]

    assert second.comments == 0
    assert second.likes == 1


def test_eomisae_skips_ad_slots():
    """목록 사이에 광고 슬롯이 카드 모양으로 끼어 있다."""
    assert "list_ad_link" not in [item.title for item in eomisae_items()]


def test_eomisae_skips_level_locked_posts():
    """레벨 제한 글은 제목 자리에 안내문만 있어 소재가 되지 않는다."""
    titles = [item.title for item in eomisae_items()]

    assert not any("전체 공개로 전환됩니다" in title for title in titles)


def test_eomisae_returns_only_real_posts():
    assert len(eomisae_items()) == 2


# ── 매거진 (Hearst / Condé Nast) ─────────────────────────


def test_hearst_extracts_titles_and_absolute_urls():
    items = parse_hearst(
        fixture("hearst.html"),
        source="esquire",
        base_url="https://www.esquirekorea.co.kr/fashion",
    )

    assert len(items) == 2, "기사 링크가 아닌 것과 너무 짧은 제목은 버린다"
    assert items[0].title == (
        "차덕후 주목! '아디다스 오리지널스 x 피치스' 두 번째 협업 출시"
    )
    assert items[0].url == "https://www.esquirekorea.co.kr/article/1907093"
    assert items[1].title == "흰 티에 청바지 '국롤' 조합 이렇게 해보세요"


def test_condenast_splits_category_title_and_date():
    """링크 안에 카테고리·제목·날짜·기자명이 함께 온다. 제목만 남겨야 한다."""
    first = parse_condenast(
        fixture("condenast.html"),
        source="gq",
        base_url="https://www.gqkorea.co.kr/category/style/",
    )[0]

    assert first.category == "sneakers"
    assert first.title == "왈라비 한 켤레도 없는 남자 없지? 지금이 최적의 구매 기회다"
    assert first.published_at is not None
    assert (first.published_at.year, first.published_at.month, first.published_at.day) == (
        2026, 8, 3,
    )
    assert "by 조서형" not in first.title
    assert "2026.08.03" not in first.title


def test_condenast_handles_reordered_parts():
    """두 번째 글은 날짜가 제목보다 먼저 온다. 위치로 고르면 깨진다."""
    items = parse_condenast(
        fixture("condenast.html"),
        source="vogue",
        base_url="https://www.vogue.co.kr/category/fashion",
    )

    assert items[1].category == "패션 아이템"
    assert items[1].title == "반바지에는 운동화도, 샌들도, 플립플롭도 아닙니다"


def test_condenast_skips_outbound_links():
    """목록 안에 브랜드 광고 링크가 섞여 있다."""
    items = parse_condenast(
        fixture("condenast.html"),
        source="vogue",
        base_url="https://www.vogue.co.kr/category/fashion",
    )

    assert len(items) == 2
    assert all("prada.com" not in item.url for item in items)


# ── 아이즈매거진 ──────────────────────────────────────────


def eyesmag_items():
    return parse_eyesmag(
        fixture("eyesmag.html"),
        source="eyesmag",
        base_url="https://www.eyesmag.com/category/fashion/all",
    )


def test_eyesmag_extracts_title_category_and_views():
    first = eyesmag_items()[0]

    assert first.title == "버켄스탁 x 아더에러, 두 번째 협업 컬렉션"
    assert first.url == (
        "https://www.eyesmag.com/posts/165004/birkenstock-ader-error-collab"
    )
    assert first.category == "패션 > 슈즈"
    assert first.views == 4172


def test_eyesmag_parses_thousands_separator_in_views():
    """조회수가 만 단위를 넘으면 쉼표가 붙는다."""
    assert eyesmag_items()[1].views == 12345


def test_eyesmag_keeps_posts_without_meta():
    """카테고리·조회수가 없는 글도 제목이 있으면 소재가 된다."""
    third = eyesmag_items()[2]

    assert third.title == "반항의 상징이 된 슬리브리스, 헤인즈"
    assert third.views is None
    assert third.category is None


def test_eyesmag_skips_navigation_links():
    items = eyesmag_items()

    assert len(items) == 3
    assert all("/posts/" in item.url for item in items)


def test_eyesmag_title_has_no_meta_noise():
    """조회수·상대시간이 제목에 섞여 들어가면 텍스트 생성이 오염된다."""
    for item in eyesmag_items():
        assert "읽음" not in item.title
        assert "시간 전" not in item.title
