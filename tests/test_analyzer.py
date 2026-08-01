import base64
from datetime import datetime
from pathlib import Path

import pytest

from willy.analyzer import LookAnalyzer, derive_season
from willy.models import Gender, RawLook


@pytest.mark.parametrize(
    "temp,month,expected",
    [
        (27.0, 8, "summer"),
        (23.0, 8, "summer"),
        (20.0, 4, "spring"),
        (20.0, 10, "fall"),
        (17.0, 3, "spring"),
        (10.0, 12, "winter"),
        (16.9, 5, "winter"),
    ],
)
def test_derive_season_is_deterministic(temp, month, expected):
    assert derive_season(temp, month) == expected


class FakeMessages:
    def __init__(self, payload: str):
        self._payload = payload
        self.last_kwargs = None

    def create(self, **kwargs):
        self.last_kwargs = kwargs

        class Block:
            text = self._payload

        class Response:
            content = [Block()]

        return Response()


class FakeClient:
    def __init__(self, payload: str):
        self.messages = FakeMessages(payload)


@pytest.fixture
def image(tmp_path: Path) -> Path:
    path = tmp_path / "look.jpg"
    path.write_bytes(b"\xff\xd8\xff\xe0fake-jpeg")
    return path


def raw(image: Path) -> RawLook:
    return RawLook(
        look_id="L1",
        source="musinsa_snap",
        image_path=image,
        capture_method="original_url",
        collected_at=datetime(2026, 8, 3),
    )


VALID = """{
  "gender": "men", "sleeve": "short", "outer": null, "layers": 1,
  "fabric_weight": "light", "coverage": "mid", "temp_range": [24, 30],
  "rain_ok": false, "style_tags": ["미니멀"], "palette": ["ecru", "charcoal"]
}"""


def test_analyze_maps_fields(image: Path):
    analyzer = LookAnalyzer(api_key="k", client=FakeClient(VALID))
    result = analyzer.analyze(raw(image))

    assert result.look_id == "L1"
    assert result.gender is Gender.MEN
    assert result.temp_range == (24, 30)
    assert result.rain_ok is False
    assert result.palette == ["ecru", "charcoal"]
    assert result.image_path == image


def test_analyze_derives_season_not_from_model(image: Path):
    """계절은 모델이 말한 값이 아니라 기온에서 규칙으로 파생한다."""
    analyzer = LookAnalyzer(api_key="k", client=FakeClient(VALID))
    result = analyzer.analyze(raw(image))

    assert result.season == "summer"  # 중앙값 27 -> summer


def test_analyze_strips_markdown_fence(image: Path):
    fenced = "```json\n" + VALID + "\n```"
    analyzer = LookAnalyzer(api_key="k", client=FakeClient(fenced))

    assert analyzer.analyze(raw(image)).gender is Gender.MEN


def test_analyze_sends_base64_image(image: Path):
    client = FakeClient(VALID)
    LookAnalyzer(api_key="k", client=client).analyze(raw(image))

    content = client.messages.last_kwargs["messages"][0]["content"]
    image_block = next(b for b in content if b["type"] == "image")
    assert image_block["source"]["data"] == base64.standard_b64encode(
        image.read_bytes()
    ).decode()


def test_analyze_raises_on_malformed_response(image: Path):
    analyzer = LookAnalyzer(api_key="k", client=FakeClient("설명을 드리자면..."))

    with pytest.raises(ValueError, match="분석 결과를 파싱"):
        analyzer.analyze(raw(image))


def test_analyze_rejects_inverted_temp_range(image: Path):
    bad = VALID.replace('"temp_range": [24, 30]', '"temp_range": [30, 24]')
    analyzer = LookAnalyzer(api_key="k", client=FakeClient(bad))

    with pytest.raises(ValueError, match="temp_range"):
        analyzer.analyze(raw(image))
