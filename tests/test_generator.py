from pathlib import Path

import pytest
import yaml

from willy.generator.base import build_prompt
from willy.generator.noop import NoopGenerator
from willy.generator.preset import load_preset
from willy.models import Gender, LookAnalysis

PRESET_PATH = Path(__file__).parents[1] / "presets" / "concept_v1.yaml"


def look() -> LookAnalysis:
    return LookAnalysis(
        look_id="L1", gender=Gender.MEN, sleeve="short", outer="shirt_jacket",
        layers=2, fabric_weight="light", coverage="mid", temp_range=(17, 23),
        rain_ok=False, season="fall", style_tags=["미니멀", "워크웨어"],
        palette=["charcoal", "ecru"], image_path=Path("/tmp/L1.jpg"),
    )


def test_load_preset_reads_shipped_file():
    preset = load_preset(PRESET_PATH)

    assert preset.concept_id == "v1"
    assert preset.aspect_ratio == "4:5"
    assert preset.strength == 0.65


def test_undecided_fields_are_none_not_empty_string():
    """미확정 항목은 None이어야 프롬프트에서 빠진다."""
    preset = load_preset(PRESET_PATH)

    assert preset.art_style is None
    assert preset.background is None
    assert preset.model_for(Gender.MEN)["face_ref"] is None


def test_build_prompt_includes_look_attributes():
    prompt = build_prompt(look(), load_preset(PRESET_PATH))

    assert "미니멀" in prompt
    assert "charcoal" in prompt
    assert "30대 초반" in prompt


def test_build_prompt_omits_undecided_fields():
    prompt = build_prompt(look(), load_preset(PRESET_PATH))

    assert "None" not in prompt
    assert "null" not in prompt


def test_build_prompt_includes_negative_terms():
    prompt = build_prompt(look(), load_preset(PRESET_PATH))

    assert "손가락 왜곡" in prompt


def test_noop_generator_copies_source_and_records_prompt(tmp_path: Path):
    source = tmp_path / "src.jpg"
    source.write_bytes(b"\xff\xd8src")
    out = tmp_path / "out"

    generator = NoopGenerator(output_dir=out)
    result = generator.generate(source, look(), load_preset(PRESET_PATH), strength=0.65)

    assert result.exists()
    assert result.read_bytes() == b"\xff\xd8src"
    # 엔진 확정 전까지 프롬프트를 눈으로 검증할 수 있어야 한다.
    assert (out / "L1.prompt.txt").exists()


def test_preset_with_filled_concept_appears_in_prompt(tmp_path: Path):
    """컨셉이 정해지면 코드 수정 없이 프롬프트에 반영되어야 한다."""
    data = yaml.safe_load(PRESET_PATH.read_text(encoding="utf-8"))
    data["render"]["art_style"] = "필름 사진 질감"
    data["render"]["background"] = "서울 골목"
    custom = tmp_path / "custom.yaml"
    custom.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")

    prompt = build_prompt(look(), load_preset(custom))

    assert "필름 사진 질감" in prompt
    assert "서울 골목" in prompt
