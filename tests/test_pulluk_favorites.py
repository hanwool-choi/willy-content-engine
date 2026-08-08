import json

from willy.pulluk.favorites import (
    fetch_favorites,
    load_cache,
    load_favorites,
    normalize_address,
    save_cache,
)
from willy.pulluk.models import Place

SHARE = "https://naver.me/AAA"
FOLDER_URL = "https://map.naver.com/p/favorite/sharedPlace/folder/tok123"


def bookmark(name, addr, cat="카페", py=37.71, px=126.70, sid="111"):
    return {"name": name, "address": addr, "mcidName": cat, "py": py, "px": px, "sid": sid}


class FakeResponse:
    def __init__(self, payload=None, url=""):
        self._payload = payload
        self.url = url

    def json(self):
        return self._payload

    def raise_for_status(self):
        pass


class FakeHttp:
    """공유 링크는 폴더 주소로 리다이렉트되고, API는 페이지 단위로 답한다."""

    def __init__(self, pages, fail=False):
        self._pages = pages          # list[list[dict]] — 호출 순서대로
        self._fail = fail
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs.get("params")))
        if self._fail:
            raise RuntimeError("연결 실패")
        if url.startswith("https://naver.me"):
            return FakeResponse(url=FOLDER_URL)
        page = self._pages.pop(0) if self._pages else []
        return FakeResponse({"folder": {"name": "테스트폴더"}, "bookmarkList": page})


def test_maps_bookmark_fields_to_place():
    http = FakeHttp([[bookmark("갤러리카페", "경기 파주시 탄현면 1")]])
    by_folder, failed = fetch_favorites({"카페": SHARE}, http=http)

    assert failed == []
    place = by_folder["카페"][0]
    assert place.name == "갤러리카페"
    assert place.folder == "카페"
    assert place.category == "카페"
    assert (place.lat, place.lon) == (37.71, 126.70)
    assert place.map_url == "https://map.naver.com/p/entry/place/111"


def test_paginates_until_short_page():
    full = [bookmark(f"곳{i}", "경기 파주시") for i in range(200)]
    http = FakeHttp([full, [bookmark("마지막", "경기 파주시")]])

    by_folder, _ = fetch_favorites({"카페": SHARE}, http=http)

    assert len(by_folder["카페"]) == 201
    # 두 번째 요청은 start=200부터여야 한다.
    api_calls = [c for c in http.calls if c[1]]
    assert api_calls[1][1]["start"] == 200


def test_missing_coordinates_stay_none():
    http = FakeHttp([[bookmark("좌표없는곳", "경기 파주시", py=None, px=None)]])
    by_folder, _ = fetch_favorites({"카페": SHARE}, http=http)

    place = by_folder["카페"][0]
    assert place.lat is None and place.lon is None
    assert place.has_coord is False


def test_one_folder_failure_is_reported_not_swallowed():
    http = FakeHttp([], fail=True)
    by_folder, failed = fetch_favorites({"카페": SHARE}, http=http)

    assert by_folder == {}
    assert failed == ["카페"]


def test_normalize_address_shortens_province_names():
    assert normalize_address("서울특별시 성동구") == "서울 성동구"
    assert normalize_address("인천광역시 강화군") == "인천 강화군"
    assert normalize_address(None) == ""


def test_cache_round_trip(tmp_path):
    places = {"카페": [Place(name="A", folder="카페", category="카페", address="경기 파주시")]}
    path = save_cache(places, tmp_path / "fav.json")

    loaded, stamp = load_cache(path)

    assert loaded["카페"][0].name == "A"
    assert stamp is not None
    assert json.loads(path.read_text(encoding="utf-8"))["folders"]["카페"][0]["name"] == "A"


def test_load_favorites_prefers_cache(tmp_path):
    path = tmp_path / "fav.json"
    save_cache({"카페": [Place(name="캐시된곳", folder="카페", category="카페", address="")]}, path)
    http = FakeHttp([], fail=True)

    by_folder, failed = load_favorites(cache_path=path, http=http)

    assert by_folder["카페"][0].name == "캐시된곳"
    assert http.calls == []  # 캐시가 있으면 네트워크를 아예 안 건드린다


def test_load_favorites_falls_back_to_cache_when_fetch_fails(tmp_path):
    path = tmp_path / "fav.json"
    save_cache({"카페": [Place(name="캐시된곳", folder="카페", category="카페", address="")]}, path)
    http = FakeHttp([], fail=True)

    by_folder, failed = load_favorites(cache_path=path, refresh=True, http=http)

    assert by_folder["카페"][0].name == "캐시된곳"
    assert failed  # 실패 자체는 숨기지 않는다
