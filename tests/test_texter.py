import json
from datetime import date
from pathlib import Path

import pytest

from willy.models import DayWeather, Gender, LookAnalysis
from willy.texter import TextWriter, template_texts


def day(pop: int = 0) -> DayWeather:
    return DayWeather(
        date=date(2026, 8, 4), weekday_ko="화", temp_max=34, temp_min=27,
        precip_prob=pop, sky="맑음", resolution="detailed",
    )


def look(look_id: str, gender=Gender.MEN, tags=None) -> LookAnalysis:
    return LookAnalysis(
        look_id=look_id, source="musinsa_snap", gender=gender,
        temp_range=(24, 32), rain_ok=False, season="summer",
        style_tags=tags or ["미니멀", "시티보이"],
        image_path=Path(f"/tmp/{look_id}.jpg"),
    )


def valid_texts(count: int = 3) -> str:
    return json.dumps(
        [{"tone": f"톤{i}", "text": f"내일 34도. 본문 {i}"} for i in range(count)],
        ensure_ascii=False,
    )


def gemini_body(text: str) -> dict:
    return {"candidates": [{"content": {"parts": [{"text": text}]}}]}


class FakeResponse:
    def __init__(self, body: dict, status_code: int = 200):
        self._body = body
        self.status_code = status_code

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeHttp:
    def __init__(self, response):
        self._response = response
        self.calls = 0
        self.last_kwargs = None

    def post(self, url, **kwargs):
        self.calls += 1
        self.last_kwargs = kwargs
        if isinstance(self._response, Exception):
            raise self._response
        return self._response


def test_write_returns_three_tones():
    writer = TextWriter(api_key="g", http=FakeHttp(FakeResponse(gemini_body(valid_texts()))))

    texts = writer.write(day(), [look("L1"), look("L2", gender=Gender.WOMEN)])

    assert len(texts) == 3
    assert all(set(t) == {"tone", "text"} for t in texts)


def test_prompt_carries_weather_looks_and_style_example():
    http = FakeHttp(FakeResponse(gemini_body(valid_texts())))
    TextWriter(api_key="g", http=http).write(day(pop=70), [look("L1")])

    prompt = http.last_kwargs["json"]["contents"][0]["parts"][0]["text"]
    assert "34" in prompt and "27" in prompt and "70" in prompt  # 날씨
    assert "미니멀" in prompt                                     # 룩 태그
    assert "팔로우" in prompt                                     # 말투 예시 포함


def test_write_rejects_wrong_count():
    writer = TextWriter(api_key="g", http=FakeHttp(FakeResponse(gemini_body(valid_texts(1)))))

    with pytest.raises(ValueError, match="3개"):
        writer.write(day(), [look("L1")])


def test_write_surfaces_http_error():
    writer = TextWriter(api_key="g", http=FakeHttp(FakeResponse({}, status_code=429)))

    with pytest.raises(RuntimeError, match="HTTP 429"):
        writer.write(day(), [look("L1")])


def test_template_fallback_builds_from_weather_and_tags():
    """AI가 죽어도 예시 구조 기반 초안 하나는 나온다."""
    texts = template_texts(day(pop=70), [look("L1", tags=["시어서커", "리넨"])])

    assert len(texts) >= 1
    body = texts[0]["text"]
    assert "34" in body           # 최고기온
    assert "8/4" in body          # 날짜
    assert "시어서커" in body      # 룩 태그
    assert "팔로우" in body        # CTA 유지
