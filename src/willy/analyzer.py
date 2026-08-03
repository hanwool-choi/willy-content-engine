"""룩 이미지 -> 구조화 분석. 기온 배정과 이미지 재생성에 모두 쓰인다."""
from __future__ import annotations

import base64
import json
import re
import time

import httpx
from anthropic import Anthropic

from willy.images import sniff
from willy.models import Gender, LookAnalysis, RawLook

MODEL = "claude-sonnet-5"
GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"

REQUIRED_KEYS = (
    "gender",
    "sleeve",
    "layers",
    "fabric_weight",
    "coverage",
    "temp_range",
    "rain_ok",
)

ANALYSIS_PROMPT = """이 사진의 착장을 분석해 JSON만 출력해. 설명 문장은 쓰지 마.

{
  "gender": "men" 또는 "women",
  "sleeve": "sleeveless" | "short" | "long",
  "outer": 아우터 종류 문자열 또는 null,
  "layers": 상체에 겹쳐 입은 옷의 개수 (정수),
  "fabric_weight": "light" | "mid" | "heavy",
  "coverage": "low" | "mid" | "high",
  "temp_range": [최저, 최고],
  "rain_ok": true 또는 false,
  "style_tags": 한국어 스타일 키워드 2~4개,
  "palette": 주요 색상 영문 2~4개
}

temp_range 판단 기준:
- 반팔 단독, 얇은 소재 -> 24~32
- 얇은 긴팔 또는 반팔+얇은 겉옷 -> 17~24
- 두꺼운 긴팔, 자켓 -> 10~18
- 코트, 패딩 -> 10도 미만
반드시 최저 < 최고 순서로 쓸 것.

rain_ok 판단 기준: 우천에 입을 수 있으면 true.
아우터가 없거나, 스웨이드·린넨처럼 물에 약한 소재이거나,
하의가 바닥에 끌리는 기장이면 false."""


def derive_season(temp_median: float, collected_month: int) -> str:
    """계절은 모델 판단이 아니라 기온에서 규칙으로 파생한다.

    아카이브 폴백 조회가 일관되려면 결정론적이어야 한다.
    """
    if temp_median >= 23:
        return "summer"
    if temp_median >= 17:
        return "spring" if collected_month in (3, 4, 5) else "fall"
    return "winter"


def _extract_json(text: str) -> dict:
    """마크다운 펜스나 앞뒤 잡음이 섞여도 JSON 본문을 건져낸다."""
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    candidate = fenced.group(1) if fenced else None
    if candidate is None:
        braced = re.search(r"\{.*\}", text, re.S)
        candidate = braced.group(0) if braced else None
    if candidate is None:
        raise ValueError(f"분석 결과를 파싱할 수 없습니다: {text[:120]}")
    try:
        return json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise ValueError(f"분석 결과를 파싱할 수 없습니다: {exc}") from exc


def build_analysis(raw_look: RawLook, data: dict) -> LookAnalysis:
    """모델 응답 dict를 검증해 LookAnalysis로 만든다. 공급자와 무관하다."""
    missing = [key for key in REQUIRED_KEYS if key not in data]
    if missing:
        raise ValueError(f"분석 결과를 파싱할 수 없습니다: 필수 키 누락 {missing}")

    raw_range = data["temp_range"]
    try:
        lo, hi = (int(value) for value in raw_range)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"분석 결과를 파싱할 수 없습니다: temp_range={raw_range!r}"
        ) from exc

    # 정수 절삭 뒤에 검사해야 한다. [24.1, 24.9]는 절삭하면 (24, 24)로 붕괴한다.
    if lo >= hi:
        raise ValueError(f"temp_range 순서가 잘못되었습니다: {raw_range}")

    try:
        gender = Gender(data["gender"])
    except ValueError as exc:
        raise ValueError(
            f"분석 결과를 파싱할 수 없습니다: gender={data['gender']!r}"
        ) from exc

    median = (lo + hi) / 2
    return LookAnalysis(
        look_id=raw_look.look_id,
        source=raw_look.source,
        gender=gender,
        sleeve=data["sleeve"],
        outer=data.get("outer"),
        layers=int(data["layers"]),
        fabric_weight=data["fabric_weight"],
        coverage=data["coverage"],
        temp_range=(lo, hi),
        rain_ok=bool(data["rain_ok"]),
        season=derive_season(median, raw_look.collected_at.month),
        style_tags=list(data.get("style_tags", [])),
        palette=list(data.get("palette", [])),
        image_path=raw_look.image_path,
    )


def _encode_image(raw_look: RawLook) -> tuple[str, str]:
    media_type, _suffix = sniff(raw_look.image_path)
    encoded = base64.standard_b64encode(raw_look.image_path.read_bytes()).decode()
    return media_type, encoded


class LookAnalyzer:
    def __init__(self, api_key: str, client=None):
        self._client = client or Anthropic(api_key=api_key)

    def analyze(self, raw_look: RawLook) -> LookAnalysis:
        media_type, encoded = _encode_image(raw_look)

        response = self._client.messages.create(
            model=MODEL,
            max_tokens=1024,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": encoded,
                            },
                        },
                        {"type": "text", "text": ANALYSIS_PROMPT},
                    ],
                }
            ],
        )

        return build_analysis(raw_look, _extract_json(response.content[0].text))


def _retry_delay_seconds(response) -> float | None:
    """429 응답에서 서버가 알려준 재시도 대기 시간을 꺼낸다.

    분당 한도 초과에는 RetryInfo가 실려 온다. 크레딧 소진처럼 기다려도
    소용없는 429에는 없으므로 None을 돌려 재시도를 막는다.
    """
    try:
        details = response.json()["error"]["details"]
    except (ValueError, KeyError, TypeError):
        return None
    for detail in details:
        if detail.get("@type", "").endswith("RetryInfo"):
            raw = detail.get("retryDelay", "")
            try:
                return float(str(raw).rstrip("s"))
            except ValueError:
                return None
    return None


class GeminiAnalyzer:
    """Gemini API 룩 분석기. 무료 티어로도 하루치(비전 12회)는 넉넉하다.

    별도 SDK 없이 REST를 직접 부른다. 키는 로그·프록시에 남는 URL 쿼리가
    아니라 헤더로만 보낸다.
    """

    MAX_RATE_LIMIT_RETRIES = 3

    def __init__(self, api_key: str, http=None, sleep=None):
        self._api_key = api_key
        self._http = http or httpx.Client(timeout=60)
        self._sleep = sleep or time.sleep

    def analyze(self, raw_look: RawLook) -> LookAnalysis:
        media_type, encoded = _encode_image(raw_look)

        payload = {
            "contents": [
                {
                    "parts": [
                        {
                            "inline_data": {
                                "mime_type": media_type,
                                "data": encoded,
                            }
                        },
                        {"text": ANALYSIS_PROMPT},
                    ]
                }
            ]
        }

        for _attempt in range(self.MAX_RATE_LIMIT_RETRIES + 1):
            response = self._http.post(
                f"{GEMINI_BASE_URL}/models/{GEMINI_MODEL}:generateContent",
                headers={"x-goog-api-key": self._api_key},
                json=payload,
            )
            if response.status_code != 429:
                break
            delay = _retry_delay_seconds(response)
            if delay is None or _attempt == self.MAX_RATE_LIMIT_RETRIES:
                break
            self._sleep(delay)
        response.raise_for_status()

        body = response.json()
        try:
            parts = body["candidates"][0]["content"]["parts"]
            text = next(part["text"] for part in parts if "text" in part)
        except (KeyError, IndexError, StopIteration) as exc:
            raise ValueError(
                "분석 결과를 파싱할 수 없습니다: 응답에 텍스트가 없습니다"
            ) from exc

        return build_analysis(raw_look, _extract_json(text))
