"""컨셉 프리셋. 미확정 항목을 코드 밖으로 격리한다."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from willy.models import Gender


@dataclass(frozen=True)
class ConceptPreset:
    concept_id: str
    models: dict
    art_style: str | None
    background: str | None
    lighting: str | None
    aspect_ratio: str
    strength: float
    negative: list[str]

    def model_for(self, gender: Gender) -> dict:
        return self.models[gender.value]


def load_preset(path: Path) -> ConceptPreset:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    render = data.get("render", {})
    return ConceptPreset(
        concept_id=data["concept_id"],
        models=data["model"],
        art_style=render.get("art_style"),
        background=render.get("background"),
        lighting=render.get("lighting"),
        aspect_ratio=render.get("aspect_ratio", "4:5"),
        strength=float(render.get("strength", 0.65)),
        negative=list(data.get("negative", [])),
    )
