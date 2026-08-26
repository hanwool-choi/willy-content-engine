import json

import httpx
import pytest

from tools.pulluk_kakao import (
    KakaoError,
    refresh_access_token,
    send_brief,
    send_text,
    split_text,
)


def test_split_text_keeps_lines_within_limit():
    text = "\n".join(f"{i}번째 줄입니다" * 2 for i in range(20))
    chunks = split_text(text, limit=200)
    assert all(len(c) <= 200 for c in chunks)
    assert "".join(c.replace("\n", "") for c in chunks) == text.replace("\n", "")


def test_split_text_single_long_line_is_hard_split():
    chunks = split_text("가" * 450, limit=200)
    assert [len(c) for c in chunks] == [200, 200, 50]


def test_refresh_access_token_returns_rotated_token():
    def handler(request):
        assert b"grant_type=refresh_token" in request.content
        return httpx.Response(200, json={"access_token": "AT", "refresh_token": "NEW"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    access, rotated = refresh_access_token("KEY", "OLD", client)
    assert access == "AT"
    assert rotated == "NEW"


def test_refresh_access_token_raises_on_error():
    client = httpx.Client(transport=httpx.MockTransport(
        lambda request: httpx.Response(400, json={"error": "invalid_grant"})))
    with pytest.raises(KakaoError):
        refresh_access_token("KEY", "OLD", client)


def test_send_text_posts_template_object():
    seen = {}

    def handler(request):
        seen["body"] = request.content.decode()
        seen["auth"] = request.headers["Authorization"]
        return httpx.Response(200, json={"result_code": 0})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    send_text(client, "AT", "안녕", link_url="https://example.com")
    assert seen["auth"] == "Bearer AT"
    assert "template_object" in seen["body"]


def test_send_brief_sends_card_plus_chunks():
    calls = []

    def handler(request):
        calls.append(request.content.decode())
        return httpx.Response(200, json={"result_code": 0})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    sent = send_brief(client, "AT", title="제목", summary="요약",
                      body="본문\n" * 120, link_url="https://example.com")
    assert sent == len(calls) >= 2
    assert "feed" in calls[0]
