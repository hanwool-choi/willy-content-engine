"""최펄럭 채널 — 네이버 즐겨찾기 기반 코스 브리핑 생성.

수집(favorites) → 지역·슬롯 배정(course) → 게시물 초안(render) 순으로 쓴다.
"""
from willy.pulluk.course import build_course, candidates
from willy.pulluk.favorites import fetch_favorites, load_favorites
from willy.pulluk.models import Course, Place, SlotPick, SlotSpec
from willy.pulluk.regions import COURSE_SPECS, INDOOR_DRIVE_SLOTS, REGIONS, Region
from willy.pulluk.render import render_all, render_briefing, render_worksheet
from willy.pulluk.search import expand_terms, group_by_area, search_places

__all__ = [
    "COURSE_SPECS",
    "Course",
    "INDOOR_DRIVE_SLOTS",
    "Place",
    "REGIONS",
    "Region",
    "SlotPick",
    "SlotSpec",
    "build_course",
    "candidates",
    "expand_terms",
    "fetch_favorites",
    "group_by_area",
    "load_favorites",
    "render_all",
    "render_briefing",
    "render_worksheet",
    "search_places",
]
