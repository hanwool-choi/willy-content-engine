"""요일 7 × 성별 2 = 14칸에 룩을 최적 배정한다."""
from __future__ import annotations

import numpy as np
from scipy.optimize import linear_sum_assignment

from willy.archive import Archive
from willy.models import (
    Assignment,
    DayWeather,
    Gender,
    LookAnalysis,
    Warning,
    WarningCode,
)

BLOCKED = 999.0        # 우천 부적합 룩에 부과하는 사실상 금지 비용
OUT_OF_RANGE = 5.0     # 적정 기온 구간을 벗어났을 때 가산
MAX_ACCEPTABLE = 12.0  # 이 비용을 넘으면 배정하지 않고 빈 칸으로 둔다


def assignment_cost(look: LookAnalysis, day: DayWeather) -> float:
    """룩을 그 요일에 배정했을 때의 부적합도. 낮을수록 좋다."""
    cost = abs(day.temp_repr - look.temp_median)
    if day.is_rainy and not look.rain_ok:
        cost += BLOCKED
    lo, hi = look.temp_range
    if not (lo <= day.temp_repr <= hi):
        cost += OUT_OF_RANGE
    return round(cost, 2)


def _assign_one_gender(
    looks: list[LookAnalysis],
    week: list[DayWeather],
    gender: Gender,
    archive: Archive | None,
    assignment: Assignment,
    warnings: list[Warning],
    used_ids: set[str],
) -> None:
    pool = [look for look in looks if look.gender == gender]

    if not pool:
        for day in week:
            assignment[(day.date, gender)] = None
            warnings.append(
                Warning(
                    code=WarningCode.EMPTY_SLOT,
                    slot_date=day.date,
                    gender=gender,
                    message=f"{day.weekday_ko}요일 {gender.value}: 후보 룩이 없습니다.",
                )
            )
        return

    # 행=요일, 열=룩. 헝가리안은 정사각이 아니어도 동작한다.
    matrix = np.array(
        [[assignment_cost(look, day) for look in pool] for day in week], dtype=float
    )
    rows, cols = linear_sum_assignment(matrix)
    chosen = {int(r): int(c) for r, c in zip(rows, cols)}

    for i, day in enumerate(week):
        col = chosen.get(i)
        picked = pool[col] if col is not None else None

        if picked is not None and matrix[i][col] <= MAX_ACCEPTABLE:
            assignment[(day.date, gender)] = picked
            used_ids.add(picked.look_id)
            continue

        # 배정 실패 -> 아카이브 폴백
        substitute = None
        if archive is not None:
            substitute = archive.find_substitute(
                temp=day.temp_repr,
                rain_ok=True if day.is_rainy else None,
                season=pool[0].season,
                gender=gender,
                exclude_ids=used_ids,
            )

        if substitute is not None:
            assignment[(day.date, gender)] = substitute
            used_ids.add(substitute.look_id)
            code = (
                WarningCode.RAIN_SUBSTITUTE if day.is_rainy
                else WarningCode.ARCHIVE_FALLBACK
            )
            warnings.append(
                Warning(
                    code=code,
                    slot_date=day.date,
                    gender=gender,
                    message=(
                        f"{day.weekday_ko}요일 {gender.value}: "
                        f"아카이브에서 '{substitute.look_id}'로 대체했습니다."
                    ),
                )
            )
        else:
            assignment[(day.date, gender)] = None
            warnings.append(
                Warning(
                    code=WarningCode.EMPTY_SLOT,
                    slot_date=day.date,
                    gender=gender,
                    message=(
                        f"{day.weekday_ko}요일 {gender.value}: "
                        f"맞는 룩이 없어 비워둡니다. 직접 추가해 주세요."
                    ),
                )
            )


def assign(
    looks: list[LookAnalysis],
    week: list[DayWeather],
    archive: Archive | None = None,
) -> tuple[Assignment, list[Warning]]:
    """전역 최적 배정. 맞는 룩이 없으면 억지로 채우지 않고 비워둔다."""
    assignment: Assignment = {}
    warnings: list[Warning] = []
    used_ids: set[str] = set()

    required = len(week) * 2
    if len(looks) < required:
        warnings.append(
            Warning(
                code=WarningCode.POOL_TOO_SMALL,
                slot_date=None,
                gender=None,
                message=f"룩이 {len(looks)}개뿐입니다. {required}개가 필요합니다.",
            )
        )

    for gender in (Gender.MEN, Gender.WOMEN):
        _assign_one_gender(looks, week, gender, archive, assignment, warnings, used_ids)

    return assignment, warnings
