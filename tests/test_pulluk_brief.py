import json
from datetime import date

from tools.pulluk_brief import run


def _data():
    places = [{"name": f"칼국수{i}", "cat": "식당", "lat": 37.5, "lon": 127.0,
               "addr": "서울 서초구 서초동 1", "sid": str(i),
               "d": {"c": "칼국수", "r": 2000 - i}} for i in range(6)]
    return {"places": places, "regions": []}


def test_run_writes_pages_and_archive(tmp_path):
    result = run(_data(), [], date(2026, 8, 24), rainy=False, api_key=None, out_dir=tmp_path)

    assert (tmp_path / "2026-08-24.html").exists()
    assert (tmp_path / "latest.html").exists()
    assert (tmp_path / "index.html").exists()

    archive = json.loads((tmp_path / "archive.json").read_text(encoding="utf-8"))
    assert archive[0]["date"] == "2026-08-24"
    assert archive[0]["places"]
    assert result["source"] == "template"
    assert result["summary"]


def test_run_replaces_same_day_entry(tmp_path):
    old = [{"date": "2026-08-24", "topic": "옛날", "title": "옛날", "kind": "족보", "places": []}]
    run(_data(), old, date(2026, 8, 24), rainy=False, api_key=None, out_dir=tmp_path)
    archive = json.loads((tmp_path / "archive.json").read_text(encoding="utf-8"))
    same_day = [e for e in archive if e["date"] == "2026-08-24"]
    assert len(same_day) == 1
    assert same_day[0]["topic"] != "옛날"


def test_place_image_url_reads_summary_api():
    import httpx

    from tools.pulluk_brief import place_image_url

    def handler(request):
        assert "1234" in str(request.url)
        return httpx.Response(200, json={"data": {"placeDetail": {
            "images": {"images": [{"origin": "https://ldb-phinf.pstatic.net/a.jpg"}]}}}})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    assert place_image_url({"sid": "1234"}, client) == "https://ldb-phinf.pstatic.net/a.jpg"


def test_place_image_url_returns_none_on_failure():
    import httpx

    from tools.pulluk_brief import place_image_url

    client = httpx.Client(transport=httpx.MockTransport(
        lambda request: httpx.Response(500)))
    assert place_image_url({"sid": "1234"}, client) is None
    assert place_image_url({}, client) is None
