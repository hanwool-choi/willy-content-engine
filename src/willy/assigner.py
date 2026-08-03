"""요일 × 성별 × 픽 칸에 룩을 배정한다.

하루 몇 칸 규모라 최적화 알고리즘 없이 비용 오름차순 정렬 픽으로
충분하다. 적합 룩이 모자라면 순서대로 ① 아카이브의 진짜 적합한 룩,
② 차선 룩 조건부 추천(사유 표시), ③ 빈 칸 + 경고로 내려간다.
조건부 추천을 쓸지 뺄지는 컨펌 단계에서 사용자가 결정한다.
"""
from __future__ import annotations

from willy.archive import Archive
from willy.models import (
    Assignment,
    Caveats,
    DayWeather,
    Gender,
    LookAnalysis,
    Warning,
    WarningCode,
)

BLOCKED = 999.0        # 우천 부적합 룩에 부과하는 사실상 금지 비용
OUT_OF_RANGE = 5.0     # 적정 기온 구간을 벗어났을 때 가산
MAX_ACCEPTABLE = 12.0  # 이 비용을 넘으면 '적합'으로 배정하지 않는다


def assignment_cost(look: LookAnalysis, day: DayWeather) -> float:
    """룩을 그 요일에 배정했을 때의 부적합도. 낮을수록 좋다."""
    cost = abs(day.temp_repr - look.temp_median)
    if day.is_rainy and not look.rain_ok:
        cost += BLOCKED
    lo, hi = look.temp_range
    if not (lo <= day.temp_repr <= hi):
        cost += OUT_OF_RANGE
    return round(cost, 2)


def caveat_for(look: LookAnalysis, day: DayWeather) -> str:
    """조건부 추천 사유. 무엇이 안 맞고 무엇은 괜찮은지를 같이 말한다."""
    problems = []
    if day.is_rainy and not look.rain_ok:
        problems.append("우천 부적합")
    lo, hi = look.temp_range
    temp_fits = lo <= day.temp_repr <= hi
    if not temp_fits:
        problems.append(f"적정 기온({lo}~{hi}℃) 범위 밖")
    reason = " · ".join(problems)
    if temp_fits:
        reason += " — 기온은 적합"
    return reason


def _assign_one_gender(
    looks: list[LookAnalysis],
    week: list[DayWeather],
    gender: Gender,
    archive: Archive | None,
    assignment: Assignment,
    warnings: list[Warning],
    caveats: Caveats,
    used_ids: set[str],
    picks_per_gender: int,
) -> None:
    pool = [look for look in looks if look.gender == gender]

    for day in week:
        # 동점은 look_id 사전순으로 갈라 결정론을 지킨다.
        ranked = sorted(
            (look for look in pool if look.look_id not in used_ids),
            key=lambda look: (assignment_cost(look, day), look.look_id),
        )

        for pick in range(picks_per_gender):
            slot = (day.date, gender, pick)
            ranked = [look for look in ranked if look.look_id not in used_ids]

            # ① 적합한 수집 룩
            if ranked and assignment_cost(ranked[0], day) <= MAX_ACCEPTABLE:
                chosen = ranked.pop(0)
                assignment[slot] = chosen
                used_ids.add(chosen.look_id)
                continue

            # ② 아카이브의 진짜 적합한 룩
            substitute = None
            if archive is not None:
                substitute = archive.find_substitute(
                    temp=day.temp_repr,
                    rain_ok=True if day.is_rainy else None,
                    season=pool[0].season if pool else None,
                    gender=gender,
                    exclude_ids=used_ids,
                )
            if substitute is not None:
                assignment[slot] = substitute
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
                            f"{day.weekday_ko}요일 {gender.value} 픽{pick + 1}: "
                            f"아카이브에서 '{substitute.look_id}'로 대체했습니다."
                        ),
                    )
                )
                continue

            # ③ 차선 룩 조건부 추천 — 빈손보다는 사유 달린 후보가 낫다.
            #    쓸지 뺄지는 컨펌에서 사용자가 결정한다.
            if ranked:
                chosen = ranked.pop(0)
                assignment[slot] = chosen
                used_ids.add(chosen.look_id)
                caveats[slot] = caveat_for(chosen, day)
                warnings.append(
                    Warning(
                        code=WarningCode.CONDITIONAL_PICK,
                        slot_date=day.date,
                        gender=gender,
                        message=(
                            f"{day.weekday_ko}요일 {gender.value} 픽{pick + 1}: "
                            f"조건부 추천 '{chosen.look_id}' ({caveats[slot]})."
                        ),
                    )
                )
                continue

            # ④ 빈 칸
            assignment[slot] = None
            warnings.append(
                Warning(
                    code=WarningCode.EMPTY_SLOT,
                    slot_date=day.date,
                    gender=gender,
                    message=(
                        f"{day.weekday_ko}요일 {gender.value} 픽{pick + 1}: "
                        f"맞는 룩이 없어 비워둡니다. 직접 추가해 주세요."
                    ),
                )
            )


def assign(
    looks: list[LookAnalysis],
    week: list[DayWeather],
    archive: Archive | None = None,
    picks_per_gender: int = 2,
) -> tuple[Assignment, list[Warning], Caveats]:
    """비용순 정렬 픽 배정. 적합 룩이 없으면 아카이브 → 조건부 추천 → 빈 칸."""
    assignment: Assignment = {}
    warnings: list[Warning] = []
    caveats: Caveats = {}
    used_ids: set[str] = set()

    required = len(week) * 2 * picks_per_gender
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
        _assign_one_gender(
            looks, week, gender, archive, assignment, warnings, caveats,
            used_ids, picks_per_gender,
        )

    return assignment, warnings, caveats
