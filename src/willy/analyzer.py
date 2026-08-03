"""룩 이미지 -> 구조화 분석. 기온 배정과 아카이브 폴백에 쓰인다.

전 수집분을 요청 1번에 넣어 일괄 분석한다. 사진 N장을 N번 부르던
구조는 무료 티어 분당 한도에 걸려 5~10분씩 걸렸다.
"""
from __future__ import annotations

import base64
import json
import re
import time

import httpx
from anthropic import Anthropic

from willy.images import sniff
from willy.models import DayWeather, Gender, LookAnalysis, RawLook

MODEL = "claude-sonnet-5"
# 고정 버전은 신규 사용자에게 제공 종료될 수 있다 (2.5-flash가 실제로 그랬다).
# 별칭은 항상 최신 Flash를 가리키므로 그 반복을 피한다.
GEMINI_MODEL = "gemini-flash-latest"
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"

REQUIRED_KEYS = ("gender", "temp_range", "rain_ok")


def batch_prompt(count: int, day: DayWeather) -> str:
    return f"""사진 {count}장의 착장을 각각 분석해 JSON 배열만 출력해. 설명 문장은 쓰지 마.
배열 길이는 정확히 {count}이어야 하고, 순서는 입력 사진 순서와 같아야 한다.

각 원소:
{{
  "gender": "men" 또는 "women",
  "temp_range": [최저, 최고],
  "rain_ok": true 또는 false,
  "style_tags": 한국어 스타일 키워드 2~4개,
  "is_ai": true 또는 false
}}

is_ai 판단 기준: 실제 인물 스냅이 아니라 AI로 생성·합성된 이미지면 true.
좌하단 "AI로 생성" 워터마크, 균일한 무지 스튜디오 배경 위 "MUSINSA" 로고,
비현실적으로 매끈한 피부·손가락이 단서다. 일반 사용자가 찍은 일상
사진(거울샷, 야외, 실내 스냅)은 false.

temp_range 판단 기준 (이 착장이 적합한 기온 구간, 정수 ℃):
- 반팔 단독, 얇은 소재 -> 24~32
- 얇은 긴팔 또는 반팔+얇은 겉옷 -> 17~24
- 두꺼운 긴팔, 자켓 -> 10~18
- 코트, 패딩 -> 10도 미만
반드시 최저 < 최고 순서로 쓸 것.

rain_ok 판단 기준: 우천에 입을 수 있으면 true.
아우터가 없거나, 스웨이드·린넨처럼 물에 약한 소재이거나,
하의가 바닥에 끌리는 기장이면 false.

참고로 이 룩들이 입혀질 내일 서울 날씨는 {day.sky}, 최고 {day.temp_max}℃ /
최저 {day.temp_min}℃, 강수확률 {day.precip_prob}%다. 판정 자체는 사진의
착장 기준으로 하되, 애매한 경계 판단은 이 날씨를 참고해라."""


def derive_season(temp_median: float, collected_month: int) -> str:
    """계절은 모델 판단이 아니라 기온에서 규칙으로 파생한다.

    아카이브 폴백 조회가 일관되려면 결정론적이어야 한다.
    """
    if temp_median >= 23:
        return "summer"
    if temp_median >= 17:
        return "spring" if collected_month in (3, 4, 5) else "fall"
    return "winter"


def _extract_json_array(text: str) -> list:
    """마크다운 펜스나 앞뒤 잡음이 섞여도 JSON 배열 본문을 건져낸다."""
    fenced = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", text, re.S)
    candidate = fenced.group(1) if fenced else None
    if candidate is None:
        bracketed = re.search(r"\[.*\]", text, re.S)
        candidate = bracketed.group(0) if bracketed else None
    if candidate is None:
        raise ValueError(f"분석 결과를 파싱할 수 없습니다: {text[:120]}")
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise ValueError(f"분석 결과를 파싱할 수 없습니다: {exc}") from exc
    if not isinstance(parsed, list):
        raise ValueError("분석 결과를 파싱할 수 없습니다: 배열이 아닙니다")
    return parsed


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
        temp_range=(lo, hi),
        rain_ok=bool(data["rain_ok"]),
        season=derive_season(median, raw_look.collected_at.month),
        style_tags=list(data.get("style_tags", [])),
        image_path=raw_look.image_path,
        is_ai=bool(data.get("is_ai", False)),
        source_url=raw_look.source_url,
        image_url=raw_look.image_url,
    )


def parse_batch(text: str, raw_looks: list[RawLook]) -> list[LookAnalysis]:
    """배열 응답을 룩 순서대로 검증·매핑한다. 길이가 어긋나면 거부한다."""
    entries = _extract_json_array(text)
    if len(entries) != len(raw_looks):
        raise ValueError(
            f"분석 결과를 파싱할 수 없습니다: "
            f"사진 {len(raw_looks)}장에 응답 {len(entries)}개"
        )
    return [build_analysis(raw, entry) for raw, entry in zip(raw_looks, entries)]


def _encode_image(raw_look: RawLook) -> tuple[str, str]:
    media_type, _suffix = sniff(raw_look.image_path)
    encoded = base64.standard_b64encode(raw_look.image_path.read_bytes()).decode()
    return media_type, encoded


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


MAX_RATE_LIMIT_RETRIES = 3
TRANSIENT_RETRY_SECONDS = 5.0


def gemini_generate(http, api_key: str, payload: dict, sleep) -> str:
    """generateContent 1회 호출 + 재시도. 응답의 첫 텍스트 파트를 돌려준다.

    429는 서버가 알려준 RetryInfo만큼(없으면 즉시 실패), 5xx·타임아웃은
    5초 쉬고 최대 3회 재시도한다. 분석기와 텍스트 생성기가 공유한다.
    """
    for _attempt in range(MAX_RATE_LIMIT_RETRIES + 1):
        last_try = _attempt == MAX_RATE_LIMIT_RETRIES
        try:
            response = http.post(
                f"{GEMINI_BASE_URL}/models/{GEMINI_MODEL}:generateContent",
                headers={"x-goog-api-key": api_key},
                json=payload,
            )
        except httpx.TimeoutException:
            if last_try:
                raise
            sleep(TRANSIENT_RETRY_SECONDS)
            continue

        if response.status_code == 429:
            delay = _retry_delay_seconds(response)
            if delay is None or last_try:
                break
            sleep(delay)
        elif response.status_code >= 500:
            if last_try:
                break
            sleep(TRANSIENT_RETRY_SECONDS)
        else:
            break
    response.raise_for_status()

    body = response.json()
    try:
        parts = body["candidates"][0]["content"]["parts"]
        return next(part["text"] for part in parts if "text" in part)
    except (KeyError, IndexError, StopIteration) as exc:
        raise ValueError(
            "분석 결과를 파싱할 수 없습니다: 응답에 텍스트가 없습니다"
        ) from exc


class LookAnalyzer:
    """Claude 비전 배치 분석기."""

    def __init__(self, api_key: str, client=None):
        self._client = client or Anthropic(api_key=api_key)

    def analyze_batch(
        self, raw_looks: list[RawLook], day: DayWeather
    ) -> list[LookAnalysis]:
        if not raw_looks:
            return []

        content = []
        for raw in raw_looks:
            media_type, encoded = _encode_image(raw)
            content.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": media_type,
                        "data": encoded,
                    },
                }
            )
        content.append({"type": "text", "text": batch_prompt(len(raw_looks), day)})

        last_error: ValueError | None = None
        for _attempt in range(2):  # 길이 불일치·파싱 오류는 1회만 다시 물어본다
            response = self._client.messages.create(
                model=MODEL,
                max_tokens=4096,
                messages=[{"role": "user", "content": content}],
            )
            try:
                return parse_batch(response.content[0].text, raw_looks)
            except ValueError as exc:
                last_error = exc
        raise last_error


class GeminiAnalyzer:
    """Gemini API 배치 분석기. 무료 티어로도 하루치(요청 1회)는 넉넉하다.

    별도 SDK 없이 REST를 직접 부른다. 키는 로그·프록시에 남는 URL 쿼리가
    아니라 헤더로만 보낸다.
    """

    def __init__(self, api_key: str, http=None, sleep=None):
        self._api_key = api_key
        self._http = http or httpx.Client(timeout=120)
        self._sleep = sleep or time.sleep

    def analyze_batch(
        self, raw_looks: list[RawLook], day: DayWeather
    ) -> list[LookAnalysis]:
        if not raw_looks:
            return []

        parts = []
        for raw in raw_looks:
            media_type, encoded = _encode_image(raw)
            parts.append({"inline_data": {"mime_type": media_type, "data": encoded}})
        parts.append({"text": batch_prompt(len(raw_looks), day)})
        payload = {"contents": [{"parts": parts}]}

        last_error: ValueError | None = None
        for _attempt in range(2):  # 길이 불일치·파싱 오류는 1회만 다시 물어본다
            text = self._request(payload)
            try:
                return parse_batch(text, raw_looks)
            except ValueError as exc:
                last_error = exc
        raise last_error

    def _request(self, payload: dict) -> str:
        return gemini_generate(self._http, self._api_key, payload, self._sleep)
