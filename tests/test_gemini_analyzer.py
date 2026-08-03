import base64
import json
from datetime import date, datetime
from pathlib import Path

import httpx
import pytest

from willy.analyzer import GEMINI_MODEL, GeminiAnalyzer
from willy.models import DayWeather, Gender, RawLook


def valid_batch(count: int = 2) -> str:
    entries = []
    for i in range(count):
        entries.append(
            {
                "gender": "women" if i % 2 == 0 else "men",
                "temp_range": [24 + i, 30 + i],
                "rain_ok": i % 2 == 1,
                "style_tags": ["캐주얼", f"태그{i}"],
            }
        )
    return json.dumps(entries, ensure_ascii=False)


def gemini_body(text: str) -> dict:
    return {"candidates": [{"content": {"parts": [{"text": text}]}}]}


class FakeResponse:
    def __init__(self, body: dict, status_code: int = 200):
        self._body = body
        self.status_code = status_code

    def json(self) -> dict:
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeHttp:
    def __init__(self, response, *more):
        self._responses = [response, *more]
        self.calls = 0
        self.last_url = None
        self.last_kwargs = None

    def post(self, url, **kwargs):
        self.calls += 1
        self.last_url = url
        self.last_kwargs = kwargs
        result = self._responses[min(self.calls, len(self._responses)) - 1]
        if isinstance(result, Exception):
            raise result
        return result


@pytest.fixture
def day() -> DayWeather:
    return DayWeather(
        date=date(2026, 8, 4),
        weekday_ko="화",
        temp_min=27,
        temp_max=35,
        precip_prob=78,
        sky="대체로맑음",
        resolution="detailed",
    )


@pytest.fixture
def images(tmp_path: Path) -> list[Path]:
    jpg = tmp_path / "look0.jpg"
    jpg.write_bytes(b"\xff\xd8\xff\xe0fake-jpeg")
    png = tmp_path / "look1.jpg"  # 확장자는 jpg지만 내용은 png
    png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"body")
    return [jpg, png]


def raws(images: list[Path]) -> list[RawLook]:
    return [
        RawLook(
            look_id=f"L{i}",
            source="musinsa_snap" if i == 0 else "uniqlo_men",
            image_path=path,
            capture_method="original_url",
            collected_at=datetime(2026, 8, 3),
        )
        for i, path in enumerate(images)
    ]


def make(response, *more, sleep=None):
    return GeminiAnalyzer(
        api_key="g", http=FakeHttp(response, *more), sleep=sleep or (lambda s: None)
    )


def test_batch_maps_fields_in_order(images, day):
    analyzer = make(FakeResponse(gemini_body(valid_batch())))

    results = analyzer.analyze_batch(raws(images), day)

    assert [r.look_id for r in results] == ["L0", "L1"]
    assert [r.source for r in results] == ["musinsa_snap", "uniqlo_men"]
    assert results[0].gender is Gender.WOMEN
    assert results[1].gender is Gender.MEN
    assert results[0].temp_range == (24, 30)
    assert results[1].rain_ok is True
    # temp_range [24, 30] -> 중앙값 27, 8월 -> summer. 계절은 규칙으로 파생.
    assert results[0].season == "summer"
    assert results[0].image_path == images[0]


def test_batch_is_a_single_call(images, day):
    http = FakeHttp(FakeResponse(gemini_body(valid_batch())))
    GeminiAnalyzer(api_key="g", http=http).analyze_batch(raws(images), day)

    assert http.calls == 1


def test_batch_sends_all_images_in_order_with_sniffed_types(images, day):
    http = FakeHttp(FakeResponse(gemini_body(valid_batch())))
    GeminiAnalyzer(api_key="g-key", http=http).analyze_batch(raws(images), day)

    assert GEMINI_MODEL in http.last_url
    assert http.last_kwargs["headers"]["x-goog-api-key"] == "g-key"

    parts = http.last_kwargs["json"]["contents"][0]["parts"]
    inlines = [p["inline_data"] for p in parts if "inline_data" in p]
    assert len(inlines) == 2
    assert inlines[0]["mime_type"] == "image/jpeg"
    assert inlines[1]["mime_type"] == "image/png"  # 확장자가 아니라 내용 기준
    assert inlines[0]["data"] == base64.standard_b64encode(
        images[0].read_bytes()
    ).decode()


def test_batch_prompt_includes_weather_and_count(images, day):
    http = FakeHttp(FakeResponse(gemini_body(valid_batch())))
    GeminiAnalyzer(api_key="g", http=http).analyze_batch(raws(images), day)

    parts = http.last_kwargs["json"]["contents"][0]["parts"]
    prompt = next(p["text"] for p in parts if "text" in p)
    assert "2장" in prompt
    assert "35" in prompt and "27" in prompt  # 기온
    assert "78" in prompt  # 강수확률


def test_batch_key_never_in_url(images, day):
    http = FakeHttp(FakeResponse(gemini_body(valid_batch())))
    GeminiAnalyzer(api_key="g-secret", http=http).analyze_batch(raws(images), day)

    assert "g-secret" not in http.last_url
    assert "params" not in (http.last_kwargs or {})


def test_batch_strips_markdown_fence(images, day):
    noisy = "결과입니다.\n```json\n" + valid_batch() + "\n```"
    analyzer = make(FakeResponse(gemini_body(noisy)))

    assert len(analyzer.analyze_batch(raws(images), day)) == 2


def test_batch_empty_input_makes_no_call(day):
    http = FakeHttp(FakeResponse(gemini_body(valid_batch())))
    analyzer = GeminiAnalyzer(api_key="g", http=http)

    assert analyzer.analyze_batch([], day) == []
    assert http.calls == 0


def test_batch_retries_length_mismatch_once(images, day):
    """응답 배열이 사진 수와 다르면 한 번 다시 물어본다."""
    analyzer = make(
        FakeResponse(gemini_body(valid_batch(1))),
        FakeResponse(gemini_body(valid_batch(2))),
    )

    results = analyzer.analyze_batch(raws(images), day)

    assert len(results) == 2
    assert analyzer._http.calls == 2


def test_batch_fails_after_repeated_length_mismatch(images, day):
    analyzer = make(FakeResponse(gemini_body(valid_batch(3))))

    with pytest.raises(ValueError, match="분석 결과를 파싱"):
        analyzer.analyze_batch(raws(images), day)

    assert analyzer._http.calls == 2  # 최초 + 재시도 1회


def test_batch_rejects_bad_gender(images, day):
    bad = valid_batch().replace('"women"', '"female"')
    assert '"female"' in bad
    analyzer = make(FakeResponse(gemini_body(bad)))

    with pytest.raises(ValueError, match="분석 결과를 파싱"):
        analyzer.analyze_batch(raws(images), day)


def test_batch_rejects_inverted_temp_range(images, day):
    bad = valid_batch().replace("[24, 30]", "[30, 24]")
    assert "[30, 24]" in bad
    analyzer = make(FakeResponse(gemini_body(bad)))

    with pytest.raises(ValueError, match="temp_range"):
        analyzer.analyze_batch(raws(images), day)


def rate_limited(delay: str = "3s") -> FakeResponse:
    return FakeResponse(
        {
            "error": {
                "code": 429,
                "status": "RESOURCE_EXHAUSTED",
                "details": [
                    {
                        "@type": "type.googleapis.com/google.rpc.RetryInfo",
                        "retryDelay": delay,
                    }
                ],
            }
        },
        status_code=429,
    )


def test_batch_retries_rate_limit_after_server_delay(images, day):
    naps = []
    analyzer = GeminiAnalyzer(
        api_key="g",
        http=FakeHttp(rate_limited("7s"), FakeResponse(gemini_body(valid_batch()))),
        sleep=naps.append,
    )

    results = analyzer.analyze_batch(raws(images), day)

    assert len(results) == 2
    assert naps == [7.0]


def test_batch_does_not_retry_429_without_retry_info(images, day):
    """크레딧 소진처럼 기다려도 소용없는 429는 즉시 드러낸다."""
    depleted = FakeResponse(
        {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED"}}, status_code=429
    )
    naps = []
    analyzer = GeminiAnalyzer(api_key="g", http=FakeHttp(depleted), sleep=naps.append)

    with pytest.raises(RuntimeError, match="HTTP 429"):
        analyzer.analyze_batch(raws(images), day)

    assert analyzer._http.calls == 1
    assert naps == []


def test_batch_retries_server_error_and_timeout(images, day):
    naps = []
    analyzer = GeminiAnalyzer(
        api_key="g",
        http=FakeHttp(
            FakeResponse({}, status_code=503),
            httpx.ReadTimeout("timed out"),
            FakeResponse(gemini_body(valid_batch())),
        ),
        sleep=naps.append,
    )

    results = analyzer.analyze_batch(raws(images), day)

    assert len(results) == 2
    assert analyzer._http.calls == 3
    assert len(naps) == 2


def test_batch_does_not_retry_plain_4xx(images, day):
    analyzer = make(FakeResponse({}, status_code=404))

    with pytest.raises(RuntimeError, match="HTTP 404"):
        analyzer.analyze_batch(raws(images), day)

    assert analyzer._http.calls == 1
