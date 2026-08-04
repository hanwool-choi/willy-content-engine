"""콘텐츠 아이디어 도메인 모델."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass
class IdeaItem:
    """패션 소식 한 건. 소스마다 채울 수 있는 필드가 다르다.

    반응 수(views/comments/likes)는 제공하지 않는 소스가 많다. 0과
    '모름'을 구분해야 뱃지 판정이 틀어지지 않으므로 기본값은 None이다.
    """

    source: str
    title: str
    url: str
    published_at: datetime | None = None
    category: str | None = None
    thumbnail_url: str | None = None
    views: int | None = None
    comments: int | None = None
    likes: int | None = None
    is_hot: bool = False
