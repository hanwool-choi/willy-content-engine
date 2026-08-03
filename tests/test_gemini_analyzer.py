import base64
import json
from datetime import datetime
from pathlib import Path

import pytest

from willy.analyzer import GEMINI_MODEL, GeminiAnalyzer
from willy.models import Gender, RawLook


VALID_ANALYSIS = """{
  "gender": "women", "sleeve": "short", "outer": null, "layers": 1,
  "fabric_weight": "light", "coverage": "mid", "temp_range": [24, 30],
  "rain_ok": false, "style_tags": ["시티보이"], "palette": ["ivory", "navy"]
}"""


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
    def __init__(self, response: FakeResponse, *more: FakeResponse):
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
def image(tmp_path: Path) -> Path:
    path = tmp_path / "look.jpg"
    path.write_bytes(b"\xff\xd8\xff\xe0fake-jpeg")
    return path


def raw(image: Path) -> RawLook:
    return RawLook(
        look_id="L7",
        source="uniqlo_women",
        image_path=image,
        capture_method="original_url",
        collected_at=datetime(2026, 8, 3),
    )


def test_analyze_maps_fields(image: Path):
    analyzer = GeminiAnalyzer(
        api_key="g", http=FakeHttp(FakeResponse(gemini_body(VALID_ANALYSIS)))
    )

    result = analyzer.analyze(raw(image))

    assert result.look_id == "L7"
    assert result.source == "uniqlo_women"
    assert result.gender is Gender.WOMEN
    assert result.temp_range == (24, 30)
    assert result.rain_ok is False
    # temp_range [24, 30] -> 중앙값 27 -> summer. 계절 파생 규칙을 공유한다.
    assert result.season == "summer"
    assert result.image_path == image


def test_analyze_sends_inline_image_key_and_model(image: Path):
    http = FakeHttp(FakeResponse(gemini_body(VALID_ANALYSIS)))
    GeminiAnalyzer(api_key="g-key", http=http).analyze(raw(image))

    assert GEMINI_MODEL in http.last_url
    assert http.last_kwargs["headers"]["x-goog-api-key"] == "g-key"

    parts = http.last_kwargs["json"]["contents"][0]["parts"]
    inline = next(p["inline_data"] for p in parts if "inline_data" in p)
    assert inline["mime_type"] == "image/jpeg"
    assert inline["data"] == base64.standard_b64encode(image.read_bytes()).decode()


def test_analyze_key_never_in_url(image: Path):
    """키가 URL 쿼리로 나가면 서버·프록시 로그에 남는다. 헤더로만 보낸다."""
    http = FakeHttp(FakeResponse(gemini_body(VALID_ANALYSIS)))
    GeminiAnalyzer(api_key="g-secret", http=http).analyze(raw(image))

    assert "g-secret" not in http.last_url
    assert "params" not in (http.last_kwargs or {})


def test_analyze_declares_media_type_from_bytes(tmp_path: Path):
    """확장자가 jpg여도 내용이 PNG면 image/png로 선언해야 한다."""
    png = tmp_path / "look.jpg"
    png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"body")

    http = FakeHttp(FakeResponse(gemini_body(VALID_ANALYSIS)))
    GeminiAnalyzer(api_key="g", http=http).analyze(
        RawLook(
            look_id="L7",
            source="manual",
            image_path=png,
            capture_method="original_url",
            collected_at=datetime(2026, 8, 3),
        )
    )

    parts = http.last_kwargs["json"]["contents"][0]["parts"]
    inline = next(p["inline_data"] for p in parts if "inline_data" in p)
    assert inline["mime_type"] == "image/png"


def test_analyze_strips_markdown_fence(image: Path):
    noisy = "결과입니다.\n```json\n" + VALID_ANALYSIS + "\n```"
    analyzer = GeminiAnalyzer(
        api_key="g", http=FakeHttp(FakeResponse(gemini_body(noisy)))
    )

    assert analyzer.analyze(raw(image)).gender is Gender.WOMEN


def test_analyze_rejects_malformed_text(image: Path):
    analyzer = GeminiAnalyzer(
        api_key="g", http=FakeHttp(FakeResponse(gemini_body("설명을 드리자면...")))
    )

    with pytest.raises(ValueError, match="분석 결과를 파싱"):
        analyzer.analyze(raw(image))


def test_analyze_rejects_response_without_candidates(image: Path):
    """차단(safety) 등으로 candidates가 비면 KeyError가 아니라 ValueError."""
    analyzer = GeminiAnalyzer(
        api_key="g", http=FakeHttp(FakeResponse({"candidates": []}))
    )

    with pytest.raises(ValueError, match="분석 결과를 파싱"):
        analyzer.analyze(raw(image))


def test_analyze_rejects_candidate_without_text_part(image: Path):
    analyzer = GeminiAnalyzer(
        api_key="g",
        http=FakeHttp(FakeResponse({"candidates": [{"content": {"parts": []}}]})),
    )

    with pytest.raises(ValueError, match="분석 결과를 파싱"):
        analyzer.analyze(raw(image))


def test_analyze_surfaces_http_error(image: Path):
    """4xx/5xx는 조용히 넘기지 않고 raise_for_status로 드러낸다."""
    analyzer = GeminiAnalyzer(
        api_key="g", http=FakeHttp(FakeResponse({}, status_code=429))
    )

    with pytest.raises(RuntimeError, match="HTTP 429"):
        analyzer.analyze(raw(image))


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


def test_analyze_retries_rate_limit_after_server_delay(image: Path):
    """무료 티어 분당 한도에 걸리면 서버가 알려준 시간만큼 쉬고 재시도한다."""
    http = FakeHttp(rate_limited("7s"), FakeResponse(gemini_body(VALID_ANALYSIS)))
    naps = []
    analyzer = GeminiAnalyzer(api_key="g", http=http, sleep=naps.append)

    result = analyzer.analyze(raw(image))

    assert result.gender is Gender.WOMEN
    assert http.calls == 2
    assert naps == [7.0]


def test_analyze_gives_up_after_repeated_rate_limits(image: Path):
    http = FakeHttp(rate_limited())
    naps = []
    analyzer = GeminiAnalyzer(api_key="g", http=http, sleep=naps.append)

    with pytest.raises(RuntimeError, match="HTTP 429"):
        analyzer.analyze(raw(image))

    assert http.calls == 4  # 최초 1회 + 재시도 3회
    assert len(naps) == 3


def test_analyze_retries_server_error(image: Path):
    """503 같은 5xx는 일시적 과부하다. 짧게 쉬고 재시도한다."""
    http = FakeHttp(
        FakeResponse({}, status_code=503),
        FakeResponse(gemini_body(VALID_ANALYSIS)),
    )
    naps = []
    analyzer = GeminiAnalyzer(api_key="g", http=http, sleep=naps.append)

    result = analyzer.analyze(raw(image))

    assert result.gender is Gender.WOMEN
    assert http.calls == 2
    assert len(naps) == 1


def test_analyze_retries_read_timeout(image: Path):
    import httpx

    http = FakeHttp(
        httpx.ReadTimeout("timed out"),
        FakeResponse(gemini_body(VALID_ANALYSIS)),
    )
    naps = []
    analyzer = GeminiAnalyzer(api_key="g", http=http, sleep=naps.append)

    result = analyzer.analyze(raw(image))

    assert result.gender is Gender.WOMEN
    assert http.calls == 2
    assert len(naps) == 1


def test_analyze_gives_up_after_repeated_timeouts(image: Path):
    import httpx

    http = FakeHttp(httpx.ReadTimeout("timed out"))
    naps = []
    analyzer = GeminiAnalyzer(api_key="g", http=http, sleep=naps.append)

    with pytest.raises(httpx.ReadTimeout):
        analyzer.analyze(raw(image))

    assert http.calls == 4  # 최초 1회 + 재시도 3회


def test_analyze_does_not_retry_4xx_other_than_429(image: Path):
    """400·404 같은 명백한 요청 오류는 재시도해도 결과가 같다."""
    http = FakeHttp(FakeResponse({}, status_code=404))
    naps = []
    analyzer = GeminiAnalyzer(api_key="g", http=http, sleep=naps.append)

    with pytest.raises(RuntimeError, match="HTTP 404"):
        analyzer.analyze(raw(image))

    assert http.calls == 1
    assert naps == []


def test_analyze_does_not_retry_429_without_retry_info(image: Path):
    """크레딧 소진처럼 기다려도 소용없는 429는 재시도 없이 즉시 드러낸다."""
    depleted = FakeResponse(
        {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED"}}, status_code=429
    )
    http = FakeHttp(depleted)
    naps = []
    analyzer = GeminiAnalyzer(api_key="g", http=http, sleep=naps.append)

    with pytest.raises(RuntimeError, match="HTTP 429"):
        analyzer.analyze(raw(image))

    assert http.calls == 1
    assert naps == []


def test_analyze_rejects_unknown_gender(image: Path):
    bad = VALID_ANALYSIS.replace('"gender": "women"', '"gender": "female"')
    assert bad != VALID_ANALYSIS
    analyzer = GeminiAnalyzer(api_key="g", http=FakeHttp(FakeResponse(gemini_body(bad))))

    with pytest.raises(ValueError, match="분석 결과를 파싱"):
        analyzer.analyze(raw(image))


def test_analyze_rejects_inverted_temp_range(image: Path):
    bad = VALID_ANALYSIS.replace('"temp_range": [24, 30]', '"temp_range": [30, 24]')
    assert bad != VALID_ANALYSIS
    analyzer = GeminiAnalyzer(api_key="g", http=FakeHttp(FakeResponse(gemini_body(bad))))

    with pytest.raises(ValueError, match="temp_range"):
        analyzer.analyze(raw(image))
