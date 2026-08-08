from willy.pulluk.course import build_course, candidates, in_region, route_cost
from willy.pulluk.models import Place, SlotSpec
from willy.pulluk.regions import INDOOR_DRIVE_SLOTS, REGIONS, Region
from willy.pulluk.render import render_briefing, render_reply_addresses, render_worksheet

PAJU = REGIONS["paju"]

# 파주 중심(37.7130, 126.6980) 기준 동서로 벌려 놓은 좌표.
# 경도 0.01도 ≈ 880m.


def place(name, folder, cat, lon_offset=0.0, lat_offset=0.0, addr="경기 파주시 탄현면", sid=None):
    return Place(
        name=name,
        folder=folder,
        category=cat,
        address=addr,
        lat=PAJU.center[0] + lat_offset,
        lon=PAJU.center[1] + lon_offset,
        place_id=sid or name,
    )


def test_region_matches_by_address_keyword_without_coords():
    p = Place(name="어딘가", folder="카페", category="카페", address="경기 파주시 문발동")
    assert in_region(p, PAJU) is True


def test_region_matches_by_radius_when_address_differs():
    # 주소에 '파주'가 없어도 중심 반경 안이면 후보다 (행정구역 경계 걸침).
    p = place("경계카페", "카페", "카페", lon_offset=0.02, addr="경기 고양시 덕양구")
    assert in_region(p, PAJU) is True


def test_region_excludes_far_places():
    p = Place(
        name="성수카페", folder="카페", category="카페",
        address="서울 성동구", lat=37.5447, lon=127.0557,
    )
    assert in_region(p, PAJU) is False


def test_outdoor_places_are_excluded_from_indoor_slots():
    anchor = next(s for s in INDOOR_DRIVE_SLOTS if s.key == "anchor")
    by_folder = {
        "스팟": [
            place("○○미술관", "스팟", "미술관"),
            place("△△공원", "스팟", "공원"),
            place("□□수목원", "스팟", "수목원"),
        ]
    }

    names = [p.name for p in candidates(anchor, by_folder, PAJU)]

    assert names == ["○○미술관"]


def test_include_keywords_split_spot_folder_between_slots():
    anchor = next(s for s in INDOOR_DRIVE_SLOTS if s.key == "anchor")
    shopping = next(s for s in INDOOR_DRIVE_SLOTS if s.key == "shopping")
    by_folder = {"스팟": [place("A미술관", "스팟", "미술관"), place("B아울렛", "스팟", "아울렛")]}

    assert [p.name for p in candidates(anchor, by_folder, PAJU)] == ["A미술관"]
    assert [p.name for p in candidates(shopping, by_folder, PAJU)] == ["B아울렛"]


def test_duplicate_places_across_folders_appear_once():
    slot = SlotSpec(key="x", role="X", action="x", folders=("카페", "스팟"), stay_min=10)
    same = place("겹치는곳", "카페", "카페", sid="dup")
    by_folder = {"카페": [same], "스팟": [place("겹치는곳", "스팟", "카페", sid="dup")]}

    assert len(candidates(slot, by_folder, PAJU)) == 1


def test_route_cost_penalizes_backtracking():
    west = place("서", "카페", "카페", lon_offset=-0.02)
    mid = place("중", "카페", "카페", lon_offset=0.0)
    east = place("동", "카페", "카페", lon_offset=0.02)

    forward = route_cost([west, mid, east], PAJU)
    zigzag = route_cost([west, east, mid], PAJU)

    assert forward < zigzag


def two_option_folders():
    """슬롯마다 동/서 후보를 하나씩 둔다. 한 방향으로 꿰는 조합만 싸야 한다."""
    return {
        "식당": [
            place("서쪽식당", "식당", "한식", lon_offset=-0.03),
            place("동쪽식당", "식당", "한식", lon_offset=0.03),
            place("최동단식당", "식당", "한식", lon_offset=0.05),
        ],
        "스팟": [
            place("서쪽미술관", "스팟", "미술관", lon_offset=-0.015),
            place("동쪽미술관", "스팟", "미술관", lon_offset=0.04),
            place("서쪽아울렛", "스팟", "아울렛", lon_offset=-0.01),
            place("동쪽아울렛", "스팟", "아울렛", lon_offset=0.04),
        ],
        "카페": [
            place("서쪽카페", "카페", "카페", lon_offset=-0.005),
            place("동쪽카페", "카페", "카페", lon_offset=0.02),
        ],
    }


def test_build_course_fills_every_slot_in_order():
    course = build_course(two_option_folders(), PAJU)

    assert course.is_complete
    assert [p.spec.key for p in course.picks] == [s.key for s in INDOOR_DRIVE_SLOTS]
    assert course.travel_km > 0


def test_build_course_picks_one_directional_route():
    course = build_course(two_option_folders(), PAJU)
    lons = [p.place.lon for p in course.filled]

    # 단조 증가(서→동) 또는 단조 감소(동→서) 중 하나여야 한다.
    increasing = all(a <= b for a, b in zip(lons, lons[1:]))
    decreasing = all(a >= b for a, b in zip(lons, lons[1:]))
    assert increasing or decreasing


def test_no_place_fills_two_slots():
    # 점심·저녁 후보가 한 곳뿐이면 둘 중 하나는 비어야 한다 — 같은 데서 두 번 안 먹는다.
    folders = two_option_folders()
    folders["식당"] = [place("유일식당", "식당", "한식")]

    course = build_course(folders, PAJU)
    names = [p.place.name for p in course.filled]

    assert len(names) == len(set(names))


def test_empty_slot_is_reported_not_hidden():
    folders = two_option_folders()
    folders["카페"] = []

    course = build_course(folders, PAJU)
    cafe = next(p for p in course.picks if p.spec.key == "cafe")

    assert cafe.place is None
    assert not course.is_complete
    assert any("대형 카페" in w for w in course.warnings)


def test_thin_region_warns_to_scout_first():
    thin = Region(
        key="thin", label="빈지역", addr_keywords=("빈지역",),
        center=PAJU.center, radius_km=5.0, hook="테스트",
    )
    folders = {"식당": [place("한곳", "식당", "한식", addr="경기 빈지역시")]}

    course = build_course(folders, thin)

    assert any("답사해서 즐겨찾기를 먼저 채우" in w for w in course.warnings)


def test_alternates_exclude_the_chosen_place():
    course = build_course(two_option_folders(), PAJU)
    for pick in course.filled:
        assert pick.place not in pick.alternates


def test_briefing_uses_confirmed_template_and_real_names():
    course = build_course(two_option_folders(), PAJU)
    text = render_briefing(course, PAJU)

    assert text.startswith("목적지 정해지면 코스부터 짜는 파워J가")
    assert "(광고 협찬 절대 아님)" in text
    assert "팔로우 해두면 이제 주말에 뭐할지 고민할일 없음." in text
    assert PAJU.outro in text
    for pick in course.filled:
        assert f"'{pick.place.name}'" in text
    # 코멘트는 지어내지 않고 빈칸으로 남긴다.
    assert text.count("___") == len(course.filled)


def test_empty_slot_shows_as_blank_line_in_briefing():
    folders = two_option_folders()
    folders["카페"] = []

    text = render_briefing(build_course(folders, PAJU), PAJU)

    assert "즐겨찾기 후보 없음" in text


def test_reply_carries_addresses_and_map_links():
    course = build_course(two_option_folders(), PAJU)
    text = render_reply_addresses(course)

    for pick in course.filled:
        assert pick.place.address in text
        assert pick.place.map_url in text


def test_worksheet_lists_indoor_checklist_items():
    course = build_course(two_option_folders(), PAJU)
    text = render_worksheet(course, PAJU)

    assert "[실내] 체류시간 제한" in text
    assert "[실내] 주차장→입구 노출 거리" in text
    assert "체류 합계" in text
