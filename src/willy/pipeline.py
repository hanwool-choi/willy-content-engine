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
from willy.config import SOURCE_QUOTAS
from willy.models import (
    Assignment,
    Caveats,
    DayWeather,
    Gender,
    LookAnalysis,
    Warning,
    WarningCode,
)
from willy.publisher.folders import publish

log = logging.getLogger(__name__)

# URL 자체가 성별을 보장하는 소스. 분석 생략 모드의 성별 폴백에 쓴다.
GENDER_BY_SOURCE = {
    "wear_men": Gender.MEN,
    "wear_women": Gender.WOMEN,
    "uniqlo_men": Gender.MEN,
    "uniqlo_women": Gender.WOMEN,
}


@dataclass
class PipelineState:
    week: list[DayWeather]
    looks: list[LookAnalysis]
    assignment: Assignment
    warnings: list[Warning]
    caveats: Caveats = field(default_factory=dict)
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
        source_quotas: dict[str, int] | None = None,
        horizon_days: int = 1,
        picks_per_gender: int = 2,
        min_pool_per_gender: int = 4,
        texter=None,
    ):
        self.weather_client = weather_client
        self.collector = collector
        self.analyzer = analyzer
        self.generator = generator
        self.archive = archive
        self.preset = preset
        self.output_root = output_root
        self.texter = texter
        self.source_quotas = source_quotas or dict(SOURCE_QUOTAS)
        self.horizon_days = horizon_days
        self.picks_per_gender = picks_per_gender
        self.min_pool_per_gender = min_pool_per_gender

    def gather(
        self, base_date: date, exclude_hashes: set[str] | None = None
    ) -> PipelineState:
        """수집 -> 배치 분석 -> 배정. 1차 컨펌 대상.

        계획 대상은 base_date 당일이 아니라 '내일', 즉 base_date + 1일부터다.
        exclude_hashes는 재수집용 — 이미 가진 이미지를 건너뛰고 새 룩을 걷는다.
        """
        plan_start = base_date + timedelta(days=1)
        week = self.weather_client.get_week_forecast(
            plan_start, days=self.horizon_days
        )

        raw_looks = self.collector.collect(
            list(SOURCE_SPECS.values()),
            quotas=self.source_quotas,
            exclude_hashes=exclude_hashes,
        )

        try:
            analyses = self.analyzer.analyze_batch(raw_looks, week[0])
        except Exception:
            # 분석이 죽어도(무료 한도 429 등) 하루 발행이 막히면 안 된다.
            # 자동화 수준을 낮춰 사람 컨펌으로 넘기는 모드로 완주한다.
            log.exception("배치 분석 실패 — 분석 생략 모드로 진행합니다")
            return self._gather_without_analysis(raw_looks, week)

        # AI 생성 판정 이미지도 참고 소재로 쓸 수 있다 — 다만 풀이 AI로
        # 쏠리지 않게 성별당 1장까지만 남기고 초과분을 뺀다.
        looks: list[LookAnalysis] = []
        ai_kept: dict[Gender, int] = {}
        for analysis in analyses:
            if analysis.is_ai:
                if ai_kept.get(analysis.gender, 0) >= 1:
                    continue
                ai_kept[analysis.gender] = ai_kept.get(analysis.gender, 0) + 1
            looks.append(analysis)

        ai_dropped = len(analyses) - len(looks)
        topup_warnings: list[Warning] = []
        if ai_dropped:
            topup_warnings.append(
                Warning(
                    code=WarningCode.AI_FILTERED,
                    slot_date=None,
                    gender=None,
                    message=(
                        f"AI 생성 판정 이미지는 성별당 1장만 남기고 "
                        f"{ai_dropped}장을 제외했습니다."
                    ),
                )
            )

        for analysis in looks:
            self.archive.save(analysis)

        looks, more_warnings = self._top_up_from_archive(looks, week[0])
        topup_warnings += more_warnings

        assignment, warnings, caveats = assign(
            looks, week, archive=self.archive, picks_per_gender=self.picks_per_gender
        )
        return PipelineState(
            week=week,
            looks=looks,
            assignment=assignment,
            warnings=topup_warnings + warnings,
            caveats=caveats,
        )

    def _gather_without_analysis(
        self, raw_looks: list, week: list[DayWeather]
    ) -> PipelineState:
        """분석 생략 모드. 성별은 소스 URL에서만 얻고, 날씨 적합은 판단하지
        않은 채 전 슬롯을 '직접 확인' 조건부로 채워 사람 컨펌에 맡긴다.

        메타데이터가 빈 룩은 아카이브에 저장하지 않는다 — 폴백·재등장
        금지 조회를 오염시킨다. 무신사처럼 성별 미상인 룩은 배정하지 않고
        풀에만 남긴다 (자체 AI 코디가 섞여 있어 자동 배정이 위험하다).
        """
        day = week[0]
        season = derive_season(day.temp_repr, day.date.month)
        looks = [
            LookAnalysis(
                look_id=raw.look_id,
                source=raw.source,
                gender=GENDER_BY_SOURCE.get(raw.source, Gender.UNKNOWN),
                temp_range=None,
                rain_ok=False,
                season=season,
                style_tags=[],
                image_path=raw.image_path,
                source_url=raw.source_url,
            )
            for raw in raw_looks
        ]

        assignment: Assignment = {}
        caveats = {}
        warnings = [
            Warning(
                code=WarningCode.ANALYSIS_SKIPPED,
                slot_date=day.date,
                gender=None,
                message=(
                    "비전 분석에 실패해 분석 생략 모드로 진행합니다. "
                    "날씨 적합과 AI 생성 여부를 직접 확인해 주세요."
                ),
            )
        ]

        for gender in (Gender.MEN, Gender.WOMEN):
            candidates = [look for look in looks if look.gender == gender]
            for pick in range(self.picks_per_gender):
                slot = (day.date, gender, pick)
                if candidates:
                    chosen = candidates.pop(0)
                    assignment[slot] = chosen
                    caveats[slot] = "분석 생략 — 날씨 적합 미확인, 직접 확인해 주세요"
                else:
                    assignment[slot] = None
                    warnings.append(
                        Warning(
                            code=WarningCode.EMPTY_SLOT,
                            slot_date=day.date,
                            gender=gender,
                            message=(
                                f"{day.weekday_ko}요일 {gender.value} 픽{pick + 1}: "
                                f"성별이 보장된 수집분이 없어 비워둡니다."
                            ),
                        )
                    )

        return PipelineState(
            week=week,
            looks=looks,
            assignment=assignment,
            warnings=warnings,
            caveats=caveats,
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

    def write_texts(self, state: PipelineState) -> list[dict]:
        """내일 날씨 + 배정된 픽으로 Threads 텍스트 3종을 쓴다.

        AI가 죽으면 예시 구조 기반 템플릿 초안으로 폴백한다 — 텍스트가
        없어서 발행을 못 하는 날은 없어야 한다.
        """
        from willy.texter import template_texts

        picks = [look for look in state.assignment.values() if look is not None]
        if self.texter is not None:
            try:
                return self.texter.write(state.week[0], picks)
            except Exception:
                log.exception("텍스트 생성 실패 — 템플릿 폴백으로 대체합니다")
        return template_texts(state.week[0], picks)

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
                    analysis.image_path, analysis, self.preset, self.preset.strength,
                    day=state.week[0],
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
