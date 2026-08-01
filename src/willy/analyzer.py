"""룩 이미지 -> 구조화 분석. 기온 배정과 이미지 재생성에 모두 쓰인다."""
from __future__ import annotations

import base64
import json
import re

from anthropic import Anthropic

from willy.models import Gender, LookAnalysis, RawLook

MODEL = "claude-sonnet-5"

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


class LookAnalyzer:
    def __init__(self, api_key: str, client=None):
        self._client = client or Anthropic(api_key=api_key)

    def analyze(self, raw_look: RawLook) -> LookAnalysis:
        encoded = base64.standard_b64encode(raw_look.image_path.read_bytes()).decode()

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
                                "media_type": "image/jpeg",
                                "data": encoded,
                            },
                        },
                        {"type": "text", "text": ANALYSIS_PROMPT},
                    ],
                }
            ],
        )

        data = _extract_json(response.content[0].text)

        lo, hi = data["temp_range"]
        if lo >= hi:
            raise ValueError(f"temp_range 순서가 잘못되었습니다: {data['temp_range']}")

        median = (lo + hi) / 2
        return LookAnalysis(
            look_id=raw_look.look_id,
            gender=Gender(data["gender"]),
            sleeve=data["sleeve"],
            outer=data.get("outer"),
            layers=int(data["layers"]),
            fabric_weight=data["fabric_weight"],
            coverage=data["coverage"],
            temp_range=(int(lo), int(hi)),
            rain_ok=bool(data["rain_ok"]),
            season=derive_season(median, raw_look.collected_at.month),
            style_tags=list(data.get("style_tags", [])),
            palette=list(data.get("palette", [])),
            image_path=raw_look.image_path,
        )
