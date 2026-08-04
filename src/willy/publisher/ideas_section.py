"""게시 페이지의 아이디어 패널.

묶음과 정렬을 빌드 타임에 끝낸다. 브라우저가 할 일은 탭 전환과 더보기
토글뿐이라, JS가 죽어도 68건이 HTML에 남아 검색과 공유가 살아 있다.

site.py에서 떼어낸 이유는 정렬을 HTML 문자열 없이 시험하기 위해서다.
"""
from __future__ import annotations

from html import escape

from willy.ideas.models import IdeaItem
from willy.ideas.sources import IDEA_SOURCES, SOURCE_GROUPS

# 묶음마다 처음에 펼쳐두는 건수. 나머지는 '더 보기'로 연다.
MAX_VISIBLE = 10

# 정렬용 대표 지표. 항목마다 다른 지표를 섞어 비교하면 순서가 뒤집히므로
# 하나만 고른다.
_METRICS = ("likes", "views", "comments")


def _group_of(item: IdeaItem) -> str:
    source = IDEA_SOURCES.get(item.source)
    return source.group if source else "magazine"


def _label_of(item: IdeaItem) -> str:
    source = IDEA_SOURCES.get(item.source)
    return source.label if source else item.source


def _metric(item: IdeaItem) -> int | None:
    """대표 지표. None은 '모름'이며 0으로 취급하지 않는다."""
    for name in _METRICS:
        value = getattr(item, name)
        if value is not None:
            return value
    return None


def _sort_key(index: int, item: IdeaItem) -> tuple:
    metric = _metric(item)
    published = item.published_at
    return (
        not item.is_hot,
        metric is None,
        -(metric or 0),
        -(published.timestamp() if published else 0),
        index,
    )


def group_ideas(items: list[IdeaItem]) -> list[tuple[str, str, list[IdeaItem]]]:
    """(묶음 키, 라벨, 정렬된 항목) 목록. 빈 묶음은 내보내지 않는다.

    표시 순서는 SOURCE_GROUPS 선언 순서를 따른다.
    """
    buckets: dict[str, list[tuple[int, IdeaItem]]] = {key: [] for key in SOURCE_GROUPS}
    for index, item in enumerate(items):
        buckets[_group_of(item)].append((index, item))

    grouped = []
    for key, label in SOURCE_GROUPS.items():
        pairs = buckets[key]
        if not pairs:
            continue
        pairs.sort(key=lambda pair: _sort_key(*pair))
        grouped.append((key, label, [item for _, item in pairs]))
    return grouped


def _meta(item: IdeaItem) -> str:
    parts = [
        _label_of(item),
        "🔥" if item.is_hot else None,
        f"♥ {item.likes}" if item.likes is not None else None,
        f"조회 {item.views}" if item.views is not None else None,
        item.category,
    ]
    return " · ".join(escape(str(part)) for part in parts if part)


def _row(item: IdeaItem, extra: bool) -> str:
    classes = "idea-row is-extra" if extra else "idea-row"
    return f"""
        <a class="{classes}" href="{escape(item.url)}"
           target="_blank" rel="noopener noreferrer">
          <span class="idea-title">{escape(item.title)}</span>
          <span class="idea-meta">{_meta(item)}</span>
        </a>"""


def _group_block(label: str, items: list[IdeaItem]) -> str:
    rows = "".join(
        _row(item, extra=index >= MAX_VISIBLE) for index, item in enumerate(items)
    )
    hidden = len(items) - MAX_VISIBLE
    more = (
        f'\n      <button class="more" type="button">더 보기 ({hidden}건)</button>'
        if hidden > 0
        else ""
    )
    # 접힘 표시는 넘치는 묶음에만 붙인다. CSS가 이걸 보고 접는다.
    list_classes = "idea-list is-collapsed" if hidden > 0 else "idea-list"
    return f"""
      <h3 class="idea-group">{escape(label)} <span class="muted">{len(items)}건</span></h3>
      <div class="{list_classes}">{rows}
      </div>{more}"""


def render_idea_panel(items: list[IdeaItem]) -> str:
    """아이디어 패널 안쪽 마크업. 항목이 없으면 빈 문자열."""
    return "".join(
        _group_block(label, group_items) for _, label, group_items in group_ideas(items)
    )
