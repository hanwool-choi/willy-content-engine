"""전체 흐름 오케스트레이션.

컨펌 경계가 여기서 강제된다:
  gather()          -> 임시 영역만 사용
  generate_images() -> 임시 영역만 사용
  finalize()        -> 유일하게 outputs/에 쓴다
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from willy.archive import Archive
from willy.assigner import assign
from willy.collector.sources import SOURCE_SPECS
from willy.models import Assignment, DayWeather, Gender, LookAnalysis, Warning
from willy.publisher.folders import publish

log = logging.getLogger(__name__)


@dataclass
class PipelineState:
    week: list[DayWeather]
    looks: list[LookAnalysis]
    assignment: Assignment
    warnings: list[Warning]
    generated: dict[tuple[date, Gender, int], Path] = field(default_factory=dict)


class Pipeline:
    def __init__(
        self,
        weather_client,
        collector,
        analyzer,
        generator,
        archive: Archive,
        preset,
        output_root: Path,
        looks_per_source: int = 4,
        horizon_days: int = 1,
        picks_per_gender: int = 2,
    ):
        self.weather_client = weather_client
        self.collector = collector
        self.analyzer = analyzer
        self.generator = generator
        self.archive = archive
        self.preset = preset
        self.output_root = output_root
        self.looks_per_source = looks_per_source
        self.horizon_days = horizon_days
        self.picks_per_gender = picks_per_gender

    def gather(self, base_date: date) -> PipelineState:
        """수집 -> 분석 -> 날씨 -> 배정. 1차 컨펌 대상.

        계획 대상은 base_date 당일이 아니라 '내일', 즉 base_date + 1일부터다.
        """
        plan_start = base_date + timedelta(days=1)
        week = self.weather_client.get_week_forecast(
            plan_start, days=self.horizon_days
        )

        raw_looks = self.collector.collect(
            list(SOURCE_SPECS.values()), limit_per_source=self.looks_per_source
        )

        looks: list[LookAnalysis] = []
        for raw in raw_looks:
            try:
                analysis = self.analyzer.analyze(raw)
            except Exception:
                # 한 장의 분석 실패가 전체를 막지 않는다.
                log.exception("룩 분석 실패: %s", raw.look_id)
                continue
            looks.append(analysis)
            self.archive.save(analysis)

        assignment, warnings = assign(
            looks, week, archive=self.archive, picks_per_gender=self.picks_per_gender
        )
        return PipelineState(
            week=week, looks=looks, assignment=assignment, warnings=warnings
        )

    def generate_images(self, state: PipelineState) -> PipelineState:
        """AI 재생성. 1차 컨펌 이후에만 호출된다."""
        generated: dict[tuple[date, Gender, int], Path] = {}

        for (slot_date, gender, pick), analysis in state.assignment.items():
            if analysis is None or analysis.image_path is None:
                continue
            if not analysis.image_path.exists():
                log.warning(
                    "원본 이미지가 없어 생성을 건너뜁니다: %s (%s)",
                    analysis.image_path,
                    analysis.look_id,
                )
                continue
            try:
                generated[(slot_date, gender, pick)] = self.generator.generate(
                    analysis.image_path, analysis, self.preset, self.preset.strength
                )
            except Exception:
                log.exception("이미지 생성 실패: %s", analysis.look_id)

        state.generated = generated
        return state

    def finalize(self, state: PipelineState) -> Path:
        """최종 컨펌 이후. 폴더·문서를 만들고 사용 이력을 남긴다."""
        root = publish(
            state.assignment, state.week, state.generated, self.output_root
        )

        for (slot_date, _gender, _pick), analysis in state.assignment.items():
            if analysis is not None:
                self.archive.mark_used(analysis.look_id, used_on=slot_date)

        return root
