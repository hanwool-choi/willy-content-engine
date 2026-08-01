import base64
import json
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
    """모델이 계절을 말해줘도 무시하고 기온에서 파생한다.

    아카이브 폴백이 season으로 필터하므로, 모델이 들쭉날쭉 답하면
    룩 재사용이 조용히 깨진다.
    """
    lying = VALID.replace('"rain_ok": false', '"season": "winter", "rain_ok": false')
    assert lying != VALID  # replace가 실제로 적용됐는지 확인
    analyzer = LookAnalyzer(api_key="k", client=FakeClient(lying))

    result = analyzer.analyze(raw(image))

    # temp_range [24, 30] -> 중앙값 27 -> summer. 모델이 말한 winter는 버린다.
    assert result.season == "summer"


def test_analyze_strips_markdown_fence(image: Path):
    """앞에 중괄호가 섞인 설명이 붙어도 펜스 안의 JSON만 정확히 집어낸다.

    펜스 분기가 없으면 탐욕적인 fallback 정규식이 설명 속 중괄호부터
    JSON 끝까지를 통째로 잡아 파싱에 실패한다.
    """
    noisy = (
        "설명드리자면 {이건 JSON이 아닙니다} 아래가 결과입니다.\n"
        "```json\n" + VALID + "\n```"
    )
    analyzer = LookAnalyzer(api_key="k", client=FakeClient(noisy))

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


def test_analyze_rejects_temp_range_that_collapses_after_truncation(image: Path):
    """[24.1, 24.9]는 정수 변환 후 (24, 24)가 된다. lo < hi가 깨지므로 거부한다."""
    collapsing = VALID.replace('"temp_range": [24, 30]', '"temp_range": [24.1, 24.9]')
    assert collapsing != VALID
    analyzer = LookAnalyzer(api_key="k", client=FakeClient(collapsing))

    with pytest.raises(ValueError, match="temp_range"):
        analyzer.analyze(raw(image))


def test_analyze_rejects_response_missing_required_key(image: Path):
    """필수 키가 빠지면 KeyError가 아니라 ValueError여야 한다."""
    data = json.loads(VALID)
    del data["sleeve"]
    analyzer = LookAnalyzer(api_key="k", client=FakeClient(json.dumps(data)))

    with pytest.raises(ValueError, match="분석 결과를 파싱"):
        analyzer.analyze(raw(image))


def test_analyze_rejects_unknown_gender(image: Path):
    bad = VALID.replace('"gender": "men"', '"gender": "male"')
    assert bad != VALID
    analyzer = LookAnalyzer(api_key="k", client=FakeClient(bad))

    with pytest.raises(ValueError, match="분석 결과를 파싱"):
        analyzer.analyze(raw(image))


def test_analyze_declares_media_type_from_bytes(tmp_path: Path):
    """PNG를 image/jpeg라고 선언하면 비전 API가 거부한다."""
    png = tmp_path / "look.jpg"  # 확장자는 jpg지만 내용은 png
    png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"body")

    client = FakeClient(VALID)
    LookAnalyzer(api_key="k", client=client).analyze(
        RawLook(
            look_id="L1",
            source="manual",
            image_path=png,
            capture_method="original_url",
            collected_at=datetime(2026, 8, 3),
        )
    )

    content = client.messages.last_kwargs["messages"][0]["content"]
    image_block = next(b for b in content if b["type"] == "image")
    assert image_block["source"]["media_type"] == "image/png"
