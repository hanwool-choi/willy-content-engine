"""선택 항목의 상세 본문 발췌.

제목만으로는 가격·발매일·브랜드가 빠져 텍스트가 빈약해진다. 선택은
보통 1~3건이라 그때 한 번씩 가져와도 부담이 없다.
"""
from __future__ import annotations

import html
import re

import httpx

MAX_CHARS = 1200
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

_STRIP_BLOCKS = re.compile(r"<(script|style|nav|footer)[^>]*>.*?</\1>", re.S | re.I)


def fetch_detail(url: str, http=None) -> str:
    """상세 페이지 본문을 한 덩어리 텍스트로 줄여 돌려준다."""
    client = http or httpx.Client(timeout=20, follow_redirects=True, headers=HEADERS)
    response = client.get(url)
    response.raise_for_status()

    body = _STRIP_BLOCKS.sub(" ", response.text)
    text = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", body))).strip()
    return text[:MAX_CHARS]
