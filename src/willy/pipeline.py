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

from willy.analyzer import derive_season
from willy.archive import Archive
from willy.assigner import assign
from willy.collector.sources import SOURCE_SPECS
from willy.models import (
    Assignment,
    DayWeather,
    Gender,
    LookAnalysis,
    Warning,
    WarningCode,
)
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
        min_pool_per_gender: int = 4,
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
        self.min_pool_per_gender = min_pool_per_gender

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

        looks, topup_warnings = self._top_up_from_archive(looks, week[0])

        assignment, warnings = assign(
            looks, week, archive=self.archive, picks_per_gender=self.picks_per_gender
        )
        return PipelineState(
            week=week,
            looks=looks,
            assignment=assignment,
            warnings=topup_warnings + warnings,
        )

    def _top_up_from_archive(
        self, looks: list[LookAnalysis], day: DayWeather
    ) -> tuple[list[LookAnalysis], list[Warning]]:
        """수집 풀이 얇으면 아카이브에서 비슷한 계절·기온의 룩으로 채운다.

        외부 사이트를 다시 두드리지 않고 비전 분석도 새로 하지 않는다.
        이미 분석해 저장해둔 것을 꺼내 쓰는 것이라 추가 비용이 없다.
        """
        warnings: list[Warning] = []
        have = {look.look_id for look in looks}

        for gender in (Gender.MEN, Gender.WOMEN):
            current = [look for look in looks if look.gender == gender]
            shortfall = self.min_pool_per_gender - len(current)
            if shortfall <= 0:
                continue

            # 그 성별 수집분이 아예 없으면 계절을 날씨에서 파생한다.
            season = current[0].season if current else derive_season(
                day.temp_repr, day.date.month
            )

            extra = self.archive.find_similar(
                temp=day.temp_repr,
                rain_ok=True if day.is_rainy else None,
                season=season,
                gender=gender,
                limit=shortfall,
                exclude_ids=have,
            )
            if not extra:
                continue

            looks.extend(extra)
            have.update(look.look_id for look in extra)
            warnings.append(
                Warning(
                    code=WarningCode.ARCHIVE_FALLBACK,
                    slot_date=day.date,
                    gender=gender,
                    message=(
                        f"{gender.value} 수집분이 {len(current)}장뿐이라 "
                        f"아카이브에서 {len(extra)}장을 보충했습니다."
                    ),
                )
            )

        return looks, warnings

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
