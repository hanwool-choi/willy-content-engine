"""반응 뱃지 판정.

소스마다 지표 스케일이 달라(어미새 좋아요 3~10, 아이즈 조회 4천~1.7만)
공통 임계값은 뜻이 없다. 소스별로 두고, 임계값이 없는 소스는 늘 False다.
"""
from __future__ import annotations

from dataclasses import replace

from willy.ideas.models import IdeaItem

HOT_THRESHOLDS: dict[str, dict[str, int]] = {
    "eomisae_os": {"likes": 5, "comments": 10},
    "eyesmag": {"views": 5000},
}


def _is_hot(item: IdeaItem) -> bool:
    thresholds = HOT_THRESHOLDS.get(item.source)
    if not thresholds:
        return False
    for metric, minimum in thresholds.items():
        value = getattr(item, metric)
        # None은 '모름'이다. 0으로 보면 판정이 틀어진다.
        if value is not None and value >= minimum:
            return True
    return False


def mark_hot(items: list[IdeaItem]) -> list[IdeaItem]:
    """뱃지를 매긴 새 목록을 돌려준다. 입력은 건드리지 않는다."""
    return [replace(item, is_hot=_is_hot(item)) for item in items]
