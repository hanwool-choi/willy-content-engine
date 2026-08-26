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


def test_load_archive_returns_empty_on_404():
    import httpx

    from tools.pulluk_brief import load_archive

    client = httpx.Client(transport=httpx.MockTransport(
        lambda request: httpx.Response(404, text="Not Found")))
    assert load_archive(client) == []


def test_load_archive_raises_on_server_error():
    import httpx
    import pytest

    from tools.pulluk_brief import load_archive

    client = httpx.Client(transport=httpx.MockTransport(
        lambda request: httpx.Response(500)))
    with pytest.raises(RuntimeError):
        load_archive(client)


def test_load_archive_raises_on_network_error():
    import httpx
    import pytest

    from tools.pulluk_brief import load_archive

    def boom(request):
        raise httpx.ConnectError("끊김", request=request)

    client = httpx.Client(transport=httpx.MockTransport(boom))
    with pytest.raises(RuntimeError):
        load_archive(client)


def test_payload_carries_deep_dive_but_page_draft_does_not(tmp_path):
    from tools.pulluk_brief import build_payload

    result = run(_data(), [], date(2026, 8, 24), rainy=False, api_key=None, out_dir=tmp_path)
    payload = build_payload(result, date(2026, 8, 24))

    assert "■ 오늘의 집중분석" in payload["body"]
    assert payload["body"].startswith(result["draft"])
    assert "■ 오늘의 집중분석" not in result["draft"]

    html = (tmp_path / "2026-08-24.html").read_text(encoding="utf-8")
    assert "■ 오늘의 집중분석" not in html
    assert payload["sids"] and payload["link"].endswith("2026-08-24.html")


def test_send_payload_writes_rotated_token_before_sending(tmp_path, monkeypatch):
    import httpx
    import pytest

    from tools.pulluk_brief import _send_kakao
    from tools.pulluk_kakao import KakaoError

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("KAKAO_REST_API_KEY", "KEY")
    monkeypatch.setenv("KAKAO_REFRESH_TOKEN", "OLD")

    def handler(request):
        if "kauth" in str(request.url):
            return httpx.Response(200, json={"access_token": "AT", "refresh_token": "NEW"})
        return httpx.Response(500, text="전송 실패")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    payload = {"title": "t", "summary": "s", "body": "b", "link": "https://x", "sids": []}
    with pytest.raises(KakaoError):
        _send_kakao(payload, client)
    # 전송이 죽어도 회전된 토큰은 남아야 다음 날이 살아난다.
    assert (tmp_path / "new_refresh_token.txt").read_text(encoding="utf-8") == "NEW"


def test_send_wraps_network_error_in_kakao_error(tmp_path, monkeypatch):
    import httpx
    import pytest

    from tools.pulluk_brief import _send_kakao
    from tools.pulluk_kakao import KakaoError

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("KAKAO_REST_API_KEY", "KEY")
    monkeypatch.setenv("KAKAO_REFRESH_TOKEN", "OLD-SECRET")

    def boom(request):
        raise httpx.ConnectError("끊김", request=request)

    client = httpx.Client(transport=httpx.MockTransport(boom))
    payload = {"title": "t", "summary": "s", "body": "b", "link": "https://x", "sids": ["1"]}
    with pytest.raises(KakaoError) as caught:
        _send_kakao(payload, client)
    assert "ConnectError" in str(caught.value)
    assert "OLD-SECRET" not in str(caught.value)


def test_main_no_send_writes_payload_and_skips_sending(tmp_path, monkeypatch):
    import sys

    import tools.pulluk_brief as brief

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(brief, "load_data", lambda: _data())
    monkeypatch.setattr(brief, "load_archive", lambda: [])
    monkeypatch.setattr(brief, "today_rainy", lambda day: False)

    def refuse(*args, **kwargs):
        raise AssertionError("--no-send인데 전송이 일어났다")

    monkeypatch.setattr(brief, "_send_kakao", refuse)
    monkeypatch.setattr(sys, "argv", [
        "pulluk_brief.py", "--out", str(tmp_path / "out"),
        "--no-send", "--date", "2026-08-24"])
    brief.main()

    payload = json.loads((tmp_path / "send_payload.json").read_text(encoding="utf-8"))
    assert set(payload) == {"title", "summary", "body", "link", "sids"}
    assert (tmp_path / "out" / "2026-08-24.html").exists()
    # 페이로드는 게시 디렉터리 밖에 있어야 gh-pages로 새어나가지 않는다.
    assert not (tmp_path / "out" / "send_payload.json").exists()


def test_main_send_only_uses_existing_payload(tmp_path, monkeypatch):
    import sys

    import tools.pulluk_brief as brief

    payload = {"title": "제목", "summary": "요약", "body": "본문",
               "link": "https://x/2026-08-24.html", "sids": ["1", "2"]}
    path = tmp_path / "send_payload.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    seen = {}
    monkeypatch.setattr(brief, "_send_kakao", lambda p: seen.update(p))
    monkeypatch.setattr(brief, "load_data", lambda: (_ for _ in ()).throw(
        AssertionError("--send인데 생성이 돌았다")))
    monkeypatch.setattr(sys, "argv", ["pulluk_brief.py", "--send", str(path)])
    brief.main()

    assert seen == payload


def test_payload_sids_are_ordered_and_deduped(tmp_path):
    from tools.pulluk_brief import build_payload

    result = run(_data(), [], date(2026, 8, 24), rainy=False, api_key=None, out_dir=tmp_path)
    payload = build_payload(result, date(2026, 8, 24))
    plan = result["plan"]

    assert len(payload["sids"]) == len(set(payload["sids"]))
    assert payload["sids"][0] == str(plan.deep["sid"])   # 집중분석이 첫 후보
