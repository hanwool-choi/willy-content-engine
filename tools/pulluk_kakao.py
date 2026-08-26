# -*- coding: utf-8 -*-
"""카카오톡 '나에게 보내기' 전송.

PlayMCP는 PC 전용이라 무인 실행이 안 된다. 나챗방 MCP가 감싸고 있는
공식 API를 직접 호출해 GitHub Actions에서도 같은 곳으로 보낸다.
텍스트 템플릿이 200자까지라 본문은 잘라서 여러 통으로 나눈다.
"""
from __future__ import annotations

import json

import httpx

TOKEN_URL = "https://kauth.kakao.com/oauth/token"
SEND_URL = "https://kapi.kakao.com/v2/api/talk/memo/default/send"
TEXT_LIMIT = 200


class KakaoError(RuntimeError):
    """토큰 갱신이나 전송이 실패했을 때. 메시지에 토큰을 담지 않는다."""


def refresh_access_token(rest_key: str, refresh_token: str,
                         http: httpx.Client) -> tuple[str, str | None]:
    """리프레시 토큰으로 액세스 토큰을 받는다.

    카카오는 리프레시 토큰 잔여 기간이 1개월 미만일 때만 새 것을 함께 준다.
    새로 왔으면 호출자가 저장소 시크릿을 갱신해야 한다.
    """
    response = http.post(TOKEN_URL, data={
        "grant_type": "refresh_token",
        "client_id": rest_key,
        "refresh_token": refresh_token,
    })
    if response.status_code != 200:
        raise KakaoError(f"토큰 갱신 실패: HTTP {response.status_code} {response.text[:200]}")
    body = response.json()
    if not body.get("access_token"):
        raise KakaoError("토큰 갱신 응답에 access_token이 없다")
    return body["access_token"], body.get("refresh_token")


def split_text(text: str, limit: int = TEXT_LIMIT) -> list[str]:
    """줄 경계를 지키며 limit 이하 조각으로 나눈다."""
    chunks: list[str] = []
    current = ""
    for line in text.split("\n"):
        candidate = line if not current else f"{current}\n{line}"
        if len(candidate) <= limit:
            current = candidate
            continue
        if current:
            chunks.append(current)
            current = ""
        while len(line) > limit:
            chunks.append(line[:limit])
            line = line[limit:]
        current = line
    if current:
        chunks.append(current)
    return chunks


def _send(http: httpx.Client, access_token: str, template_object: dict) -> None:
    response = http.post(
        SEND_URL,
        headers={"Authorization": f"Bearer {access_token}"},
        data={"template_object": json.dumps(template_object, ensure_ascii=False)},
    )
    if response.status_code != 200:
        raise KakaoError(f"전송 실패: HTTP {response.status_code} {response.text[:200]}")


def send_text(http: httpx.Client, access_token: str, text: str,
              link_url: str | None = None) -> None:
    link = {"web_url": link_url, "mobile_web_url": link_url} if link_url else {}
    _send(http, access_token, {"object_type": "text", "text": text[:TEXT_LIMIT], "link": link})


def send_feed(http: httpx.Client, access_token: str, title: str, description: str,
              image_url: str | None, link_url: str) -> None:
    content = {
        "title": title,
        "description": description,
        "link": {"web_url": link_url, "mobile_web_url": link_url},
    }
    if image_url:
        content["image_url"] = image_url
    _send(http, access_token, {
        "object_type": "feed",
        "content": content,
        "buttons": [{"title": "전문 보기",
                     "link": {"web_url": link_url, "mobile_web_url": link_url}}],
    })


def send_brief(http: httpx.Client, access_token: str, title: str, summary: str,
               body: str, link_url: str, image_url: str | None = None) -> int:
    """요약 카드 1통 + 본문 조각 n통. 보낸 통 수를 돌려준다."""
    send_feed(http, access_token, title, summary, image_url, link_url)
    sent = 1
    for chunk in split_text(body):
        send_text(http, access_token, chunk, link_url)
        sent += 1
    return sent
