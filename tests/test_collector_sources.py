import pytest

from willy.collector.sources import SOURCE_SPECS, build_look_id


def test_all_three_fixed_sources_are_registered():
    assert set(SOURCE_SPECS) == {"musinsa_snap", "uniqlo_women", "uniqlo_men"}


def test_blocked_platforms_are_absent():
    """에이블리·크림은 CAPTCHA/미제공으로 제외했다. 되살아나면 안 된다."""
    joined = " ".join(spec.url for spec in SOURCE_SPECS.values())
    assert "a-bly" not in joined
    assert "kream" not in joined


def test_each_spec_has_selectors():
    for name, spec in SOURCE_SPECS.items():
        assert spec.card_selector, f"{name}: card_selector 누락"
        assert spec.image_selector, f"{name}: image_selector 누락"


def test_build_look_id_is_unique_per_source_and_index():
    a = build_look_id("musinsa_snap", 0)
    b = build_look_id("musinsa_snap", 1)
    c = build_look_id("uniqlo_men", 0)

    assert a != b != c
    assert a.startswith("musinsa_snap-")
