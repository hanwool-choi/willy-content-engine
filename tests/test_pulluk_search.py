from willy.pulluk.models import Place
from willy.pulluk.search import expand_terms, group_by_area, matches, search_places


def place(name, folder="식당", cat="한식", addr="서울 성동구 성수동", sid=None):
    return Place(
        name=name, folder=folder, category=cat, address=addr, place_id=sid or name
    )


def test_sundae_search_catches_sait_siot_spelling():
    # '순댓국'에는 '순대'가 부분문자열로 없다(순/댓/국). 별칭이 없으면 통째로 놓친다.
    assert "순대" not in "순댓국"
    assert matches(place("우리순댓국"), expand_terms(["순대국"]))


def test_sundae_search_catches_plain_spelling():
    assert matches(place("농민백암순대"), expand_terms(["순대국"]))
    assert matches(place("순대국밥집"), expand_terms(["순대국"]))


def test_matches_category_when_name_has_no_menu():
    # 상호에 메뉴가 없고 분류에만 있는 집 — 상호만 보면 놓친다.
    assert matches(place("역전회관", cat="순댓국"), expand_terms(["순대국"]))


def test_unrelated_place_is_not_matched():
    assert not matches(place("동네칼국수", cat="칼국수"), expand_terms(["순대국"]))


def test_expand_terms_keeps_unknown_terms_as_is():
    assert expand_terms(["돈까스"]) == ("돈까스",)


def test_expand_terms_dedupes_across_aliases():
    out = expand_terms(["순대국", "순댓국"])
    assert out == ("순대", "순댓")


def test_expand_terms_ignores_blank_input():
    assert expand_terms(["  ", ""]) == ()


def test_search_returns_empty_for_blank_terms():
    assert search_places({"식당": [place("아무집")]}, [""]) == []


def sample():
    return {
        "식당": [
            place("농민백암순대", addr="서울 강남구 역삼동", sid="1"),
            place("우리순댓국", addr="경기 파주시 문발동", sid="2"),
            place("역전회관", cat="순댓국", addr="서울 강남구 논현동", sid="3"),
            place("동네칼국수", cat="칼국수", addr="서울 강남구", sid="4"),
        ],
        "카페": [place("순대카페", folder="카페", cat="카페", addr="서울 마포구", sid="5")],
    }


def test_search_across_folders():
    found = [p.name for p in search_places(sample(), ["순대국"])]
    assert set(found) == {"농민백암순대", "우리순댓국", "역전회관", "순대카페"}


def test_folder_filter_narrows_to_restaurants():
    found = [p.name for p in search_places(sample(), ["순대국"], folders=["식당"])]
    assert "순대카페" not in found
    assert len(found) == 3


def test_duplicate_registration_appears_once():
    same = place("겹치는순대", sid="dup")
    data = {"식당": [same], "카페": [place("겹치는순대", folder="카페", sid="dup")]}
    assert len(search_places(data, ["순대국"])) == 1


def test_results_are_sorted_by_address():
    found = search_places(sample(), ["순대국"], folders=["식당"])
    assert [p.address for p in found] == sorted(p.address for p in found)


def test_group_by_area_buckets_and_orders_by_count():
    grouped = group_by_area(search_places(sample(), ["순대국"], folders=["식당"]))
    assert list(grouped) == ["서울 강남구", "경기 파주시"]
    assert len(grouped["서울 강남구"]) == 2


def test_group_by_area_handles_missing_address():
    grouped = group_by_area([place("주소없는집", addr="")])
    assert "주소 없음" in grouped
