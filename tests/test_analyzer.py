import base64
import json
from datetime import date, datetime
from pathlib import Path

import pytest

from willy.analyzer import LookAnalyzer, derive_season
from willy.models import DayWeather, Gender, RawLook


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
    def __init__(self, payloads: list[str]):
        self._payloads = payloads
        self.calls = 0
        self.last_kwargs = None

    def create(self, **kwargs):
        self.calls += 1
        self.last_kwargs = kwargs
        payload = self._payloads[min(self.calls, len(self._payloads)) - 1]

        class Block:
            text = payload

        class Response:
            content = [Block()]

        return Response()


class FakeClient:
    def __init__(self, *payloads: str):
        self.messages = FakeMessages(list(payloads))


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
            source="musinsa_snap",
            image_path=path,
            capture_method="original_url",
            collected_at=datetime(2026, 8, 3),
        )
        for i, path in enumerate(images)
    ]


def valid_batch(count: int = 2) -> str:
    return json.dumps(
        [
            {
                "gender": "men",
                "temp_range": [24, 30],
                "rain_ok": False,
                "style_tags": ["미니멀"],
            }
            for _ in range(count)
        ],
        ensure_ascii=False,
    )


def test_batch_maps_fields(images, day):
    analyzer = LookAnalyzer(api_key="k", client=FakeClient(valid_batch()))

    results = analyzer.analyze_batch(raws(images), day)

    assert [r.look_id for r in results] == ["L0", "L1"]
    assert results[0].gender is Gender.MEN
    assert results[0].temp_range == (24, 30)
    assert results[0].season == "summer"
    assert results[0].source == "musinsa_snap"


def test_batch_sends_images_as_ordered_blocks(images, day):
    client = FakeClient(valid_batch())
    LookAnalyzer(api_key="k", client=client).analyze_batch(raws(images), day)

    assert client.messages.calls == 1
    content = client.messages.last_kwargs["messages"][0]["content"]
    image_blocks = [b for b in content if b["type"] == "image"]
    assert len(image_blocks) == 2
    assert image_blocks[0]["source"]["media_type"] == "image/jpeg"
    assert image_blocks[1]["source"]["media_type"] == "image/png"
    assert image_blocks[0]["source"]["data"] == base64.standard_b64encode(
        images[0].read_bytes()
    ).decode()


def test_batch_prompt_includes_weather(images, day):
    client = FakeClient(valid_batch())
    LookAnalyzer(api_key="k", client=client).analyze_batch(raws(images), day)

    content = client.messages.last_kwargs["messages"][0]["content"]
    prompt = next(b["text"] for b in content if b["type"] == "text")
    assert "35" in prompt and "78" in prompt


def test_batch_retries_length_mismatch_once(images, day):
    client = FakeClient(valid_batch(1), valid_batch(2))
    analyzer = LookAnalyzer(api_key="k", client=client)

    assert len(analyzer.analyze_batch(raws(images), day)) == 2
    assert client.messages.calls == 2


def test_batch_fails_after_repeated_length_mismatch(images, day):
    client = FakeClient(valid_batch(1))
    analyzer = LookAnalyzer(api_key="k", client=client)

    with pytest.raises(ValueError, match="분석 결과를 파싱"):
        analyzer.analyze_batch(raws(images), day)

    assert client.messages.calls == 2


def test_batch_strips_markdown_fence(images, day):
    noisy = "설명입니다.\n```json\n" + valid_batch() + "\n```"
    analyzer = LookAnalyzer(api_key="k", client=FakeClient(noisy))

    assert len(analyzer.analyze_batch(raws(images), day)) == 2


def test_batch_empty_input_makes_no_call(day):
    client = FakeClient(valid_batch())
    analyzer = LookAnalyzer(api_key="k", client=client)

    assert analyzer.analyze_batch([], day) == []
    assert client.messages.calls == 0


def test_batch_rejects_missing_required_key(images, day):
    data = json.loads(valid_batch())
    del data[0]["rain_ok"]
    analyzer = LookAnalyzer(api_key="k", client=FakeClient(json.dumps(data)))

    with pytest.raises(ValueError, match="분석 결과를 파싱"):
        analyzer.analyze_batch(raws(images), day)


def test_batch_rejects_temp_range_that_collapses_after_truncation(images, day):
    """[24.1, 24.9]는 정수 절삭 후 (24, 24)로 붕괴한다. 거부한다."""
    bad = valid_batch().replace("[24, 30]", "[24.1, 24.9]")
    assert "[24.1, 24.9]" in bad
    analyzer = LookAnalyzer(api_key="k", client=FakeClient(bad))

    with pytest.raises(ValueError, match="temp_range"):
        analyzer.analyze_batch(raws(images), day)
