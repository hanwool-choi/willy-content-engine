"""이미지 생성 엔진 인터페이스. 엔진이 확정되면 구현체를 추가한다."""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from willy.generator.preset import ConceptPreset
from willy.models import LookAnalysis


def build_prompt(analysis: LookAnalysis, preset: ConceptPreset) -> str:
    """룩 분석 + 컨셉 -> 생성 프롬프트. 미확정(None) 항목은 빠진다."""
    model = preset.model_for(analysis.gender)

    lines = [
        f"{model['age']} {analysis.gender.value} 모델, 체형 {model['build']}, "
        f"키 {model['height']}",
        f"착장: {analysis.sleeve} 상의"
        + (f", {analysis.outer} 아우터" if analysis.outer else "")
        + f", {analysis.layers}겹 레이어드",
        f"소재감: {analysis.fabric_weight}",
        f"색상: {', '.join(analysis.palette)}",
        f"무드: {', '.join(analysis.style_tags)}",
        f"비율: {preset.aspect_ratio}",
    ]

    for label, value in (
        ("화풍", preset.art_style),
        ("배경", preset.background),
        ("조명", preset.lighting),
        ("헤어", model.get("hair")),
    ):
        if value:
            lines.append(f"{label}: {value}")

    if preset.negative:
        lines.append("제외: " + ", ".join(preset.negative))

    return "\n".join(lines)


class ImageGenerator(ABC):
    """원본 룩 이미지를 발행용 이미지로 변환한다.

    파이프라인: 원본 -> img2img(구도·핏 유지) -> 모델 일관성 엔진(고정 모델 적용)

    2단계가 필수인 이유: 소스는 실존 인물(무신사 스냅 일반 유저, 유니클로
    직원)의 사진이다. 고정 캐릭터로 인물을 덮어써야 초상이 결과물에 남지 않는다.
    """

    @abstractmethod
    def generate(
        self,
        source_image: Path,
        analysis: LookAnalysis,
        preset: ConceptPreset,
        strength: float,
    ) -> Path:
        """발행용 이미지 경로를 반환한다."""
