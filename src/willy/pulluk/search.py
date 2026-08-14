"""즐겨찾기 메뉴·키워드 검색.

코스(course.py)가 슬롯을 채우는 쪽이라면, 이쪽은 "순대국집만 모아줘" 같은
단일 메뉴 리스트를 뽑는 쪽이다. 채널 포맷으로 치면 코스 브리핑이 아니라
저장형 리스트에 해당한다.

한글 검색은 부분문자열만으로는 샌다. 사이시옷 표기가 대표적이다 —
'순댓국'에는 '순대'가 들어 있지 않다(순/댓/국). 그래서 표기 변형을
별칭으로 펼친 뒤에 찾는다.
"""
from __future__ import annotations

from collections.abc import Iterable

from willy.pulluk.models import Place

# 한 메뉴가 실제 상호·분류에 쓰이는 표기들. 하나를 넣으면 나머지도 같이 찾는다.
# 사이시옷(순댓/북엇/황탯), 붙임/띄움, 방언 표기가 주로 갈린다.
TERM_ALIASES: dict[str, tuple[str, ...]] = {
    "순대": ("순대", "순댓"),
    "순대국": ("순대", "순댓"),
    "순댓국": ("순대", "순댓"),
    "순대국밥": ("순대", "순댓"),
    "국밥": ("국밥", "국반"),
    "감자탕": ("감자탕", "뼈해장", "뼈다귀"),
    "해장국": ("해장국", "해장"),
    "칼국수": ("칼국수", "칼국시"),
    "냉면": ("냉면", "랭면"),
    "곰탕": ("곰탕", "설렁탕"),
    "북어국": ("북어", "북엇"),
}


def expand_terms(terms: Iterable[str]) -> tuple[str, ...]:
    """검색어를 표기 변형까지 펼친다. 별칭이 없으면 입력 그대로."""
    out: list[str] = []
    for term in terms:
        cleaned = term.strip()
        if not cleaned:
            continue
        for variant in TERM_ALIASES.get(cleaned, (cleaned,)):
            if variant not in out:
                out.append(variant)
    return tuple(out)


def matches(place: Place, terms: Iterable[str]) -> bool:
    """상호와 네이버 분류 둘 다 본다.

    분류만 '순대,순댓국'이고 상호에는 메뉴가 안 들어간 집이 흔하다
    (예: '역전회관'). 상호만 보면 그런 집을 통째로 놓친다.
    """
    haystack = f"{place.name} {place.category or ''}"
    return any(t in haystack for t in terms)


def search_places(
    by_folder: dict[str, list[Place]],
    terms: Iterable[str],
    folders: Iterable[str] | None = None,
) -> list[Place]:
    """키워드로 즐겨찾기를 훑는다. 폴더를 지정하면 그 폴더만 본다.

    같은 곳이 여러 폴더에 등록돼 있어도 한 번만 돌려준다.
    """
    expanded = expand_terms(terms)
    if not expanded:
        return []

    wanted = set(folders) if folders else None
    found: list[Place] = []
    seen: set[str] = set()
    for folder, places in by_folder.items():
        if wanted is not None and folder not in wanted:
            continue
        for place in places:
            if not matches(place, expanded):
                continue
            key = place.place_id or place.name
            if key in seen:
                continue
            seen.add(key)
            found.append(place)

    found.sort(key=lambda p: (p.address, p.name))
    return found


def group_by_area(places: Iterable[Place], depth: int = 2) -> dict[str, list[Place]]:
    """주소 앞 depth 토막으로 묶는다. 예: '서울 성동구'.

    지역별로 몇 곳인지 보여야 "어디 편부터 쓸지"를 정할 수 있다.
    """
    grouped: dict[str, list[Place]] = {}
    for place in places:
        parts = (place.address or "").split()
        area = " ".join(parts[:depth]) if parts else "주소 없음"
        grouped.setdefault(area, []).append(place)
    return dict(sorted(grouped.items(), key=lambda kv: (-len(kv[1]), kv[0])))
