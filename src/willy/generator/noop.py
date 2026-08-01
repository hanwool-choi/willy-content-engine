"""엔진 미확정 구간용 통과 구현체.

원본을 그대로 복사하고 프롬프트를 파일로 남겨, 엔진 없이도 파이프라인
전체를 끝까지 돌리고 프롬프트 품질을 눈으로 검증할 수 있게 한다.
"""
from __future__ import annotations

import shutil
from pathlib import Path

from willy.generator.base import ImageGenerator, build_prompt
from willy.generator.preset import ConceptPreset
from willy.models import LookAnalysis


class NoopGenerator(ImageGenerator):
    def __init__(self, output_dir: Path):
        self._out = output_dir
        self._out.mkdir(parents=True, exist_ok=True)

    def generate(
        self,
        source_image: Path,
        analysis: LookAnalysis,
        preset: ConceptPreset,
        strength: float,
    ) -> Path:
        dest = self._out / f"{analysis.look_id}.jpg"
        shutil.copyfile(source_image, dest)

        prompt_path = self._out / f"{analysis.look_id}.prompt.txt"
        prompt_path.write_text(build_prompt(analysis, preset), encoding="utf-8")

        return dest
