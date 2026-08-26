# tools/kakao_token_setup.py
# -*- coding: utf-8 -*-
"""카카오 리프레시 토큰 1회 발급 (사용자가 직접 실행).

    python tools/kakao_token_setup.py --rest-key <REST_API_KEY>

카카오 로그인은 브라우저에서 본인이 해야 한다. 이 스크립트는 인가 코드를
받아 토큰으로 바꿔주기만 하고, 토큰을 저장소에 쓰지 않는다.
"""
from __future__ import annotations

import argparse
import sys
import urllib.parse

import truststore

truststore.inject_into_ssl()

import httpx  # noqa: E402

REDIRECT_URI = "https://localhost:3000/oauth"
AUTH_URL = "https://kauth.kakao.com/oauth/authorize"
TOKEN_URL = "https://kauth.kakao.com/oauth/token"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rest-key", required=True, help="카카오 앱의 REST API 키")
    parser.add_argument("--redirect-uri", default=REDIRECT_URI,
                        help="카카오 앱에 등록한 Redirect URI")
    args = parser.parse_args()

    query = urllib.parse.urlencode({
        "client_id": args.rest_key,
        "redirect_uri": args.redirect_uri,
        "response_type": "code",
        "scope": "talk_message",
    })
    print("\n1) 아래 주소를 브라우저에 붙여넣고 카카오 로그인·동의를 진행하세요.\n")
    print(f"   {AUTH_URL}?{query}\n")
    print("2) 이동한 주소창의 code= 뒤 값을 복사해 붙여넣으세요.")
    print("   (페이지가 안 열려도 주소창에 code= 값은 들어 있습니다)\n")
    code = input("code: ").strip()

    with httpx.Client(timeout=30.0) as client:
        response = client.post(TOKEN_URL, data={
            "grant_type": "authorization_code",
            "client_id": args.rest_key,
            "redirect_uri": args.redirect_uri,
            "code": code,
        })
    if response.status_code != 200:
        print(f"\n실패: HTTP {response.status_code} {response.text[:300]}", file=sys.stderr)
        raise SystemExit(1)

    body = response.json()
    print("\n발급 완료. 아래 값을 GitHub Secrets에 넣으세요.\n")
    print(f"  KAKAO_REST_API_KEY = {args.rest_key}")
    print(f"  KAKAO_REFRESH_TOKEN = {body.get('refresh_token')}\n")
    print("이 값은 화면에만 출력되며 저장소에 저장되지 않습니다.")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
