# 최펄럭 데일리 브리핑 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 매일 09:00 KST에 GitHub Actions가 즐겨찾기 데이터로 그날의 스레드 콘텐츠 초안을 기획해 카카오톡 나와의 채팅으로 보내고, 전문을 gh-pages 브리핑 페이지에 발행한다.

**Architecture:** 순수 로직(주제 선정·초안 작성)과 I/O(카카오 전송·페이지 발행·데이터 적재)를 파일 단위로 분리한다. 주제 선정은 요일 로테이션 + 날씨·시즌 보정 + 아카이브 중복 제거로 결정론적으로 돌아가고, 초안은 Gemini가 쓰되 실패하면 템플릿으로 폴백한다. 카카오 200자 제한 때문에 메시지는 요약 카드 1통 + 전문 분할 2통으로 나눈다.

**Tech Stack:** Python 3.11+, httpx, truststore, GitHub Actions, 카카오 나에게 보내기 REST API, Gemini(기존 `willy.analyzer.gemini_generate` 재사용), pytest

## Global Constraints

- 설계 문서: `docs/superpowers/specs/2026-08-26-pulluk-daily-brief-design.md` — 충돌 시 설계 문서가 우선
- 주석·문자열은 한국어. 기존 저장소 톤(무엇이 아니라 왜를 적는 주석)을 따른다
- 네트워크를 쓰는 진입점은 httpx import 전에 `truststore.inject_into_ssl()`을 호출한다 (사내망 TLS 프록시)
- 토큰·API 키는 절대 커밋하지 않는다. 환경변수로만 읽는다
- 날짜·시간은 KST(`timezone(timedelta(hours=9))`) 기준
- 팝업 데이터는 브리핑에서 사용하지 않는다 (`data["popups"]`를 읽지 않는다)
- AI는 경험담을 지어내지 않는다. 데이터로 확인된 사실만 단정하고 한줄평에는 `※확인`을 붙인다
- 중복 규칙: 같은 주제 60일, 같은 가게 30일
- 신규 모듈은 `tools/` 아래. 테스트는 `from tools.x import y`로 import한다 (`pyproject.toml`의 `pythonpath = ["src", "."]` 덕에 동작한다). 진입점 스크립트는 맨 위에서 저장소 루트와 `src`를 `sys.path`에 넣는다
- 테스트 실행: `C:\venvs\willy\Scripts\python.exe -m pytest`

## File Structure

| 파일 | 책임 |
|---|---|
| `tools/pulluk_brief_core.py` | 주제 선정 (로테이션·시즌·날씨·중복). 네트워크 없음 |
| `tools/pulluk_brief_text.py` | 초안 문장 생성 (템플릿 + Gemini), 확인 목록 |
| `tools/pulluk_kakao.py` | 토큰 갱신, 200자 분할, 나에게 보내기 전송 |
| `tools/pulluk_brief_page.py` | 브리핑 HTML·인덱스 렌더링 |
| `tools/pulluk_brief.py` | 진입점. 데이터 적재 → 기획 → 발행 → 전송 → 아카이브 |
| `tools/kakao_token_setup.py` | 사용자 1회 실행용 토큰 발급 |
| `assets/pulluk/style_examples.json` | 채널 실게시물 말투 예시 |
| `.github/workflows/pulluk-brief.yml` | 09:00 KST 크론 |

---

### Task 1: 주제 선정 엔진

**Files:**
- Create: `tools/pulluk_brief_core.py`
- Test: `tests/test_pulluk_brief_core.py`

**Interfaces:**
- Consumes: `assets/pulluk/data.js` 구조 — `{"places": [{"name","cat","lat","lon","addr","sid","d":{"c","r","s","h","pk","pkt"}}], "regions": [{"name","sido","lat","lon","radius","count"}]}`
- Produces:
  - `TopicPlan(kind: str, topic: str, title: str, places: list[dict], deep: dict | None, rainy: bool, note: str)`
  - `plan_for(data: dict, archive: list[dict], today: date, rainy: bool) -> TopicPlan`
  - `pick_deep(plan: TopicPlan, archive: list[dict], today: date) -> dict | None`
  - `dong_of(addr: str) -> str`, `category_of(place: dict) -> str`, `review_of(place: dict) -> int`, `is_outdoor(place: dict) -> bool`, `recent_topics(archive, today, days=60) -> set[str]`, `recent_places(archive, today, days=30) -> set[str]`
  - 상수 `ROTATION`, `SEASON_KEYWORDS`, `TOPIC_DAYS = 60`, `PLACE_DAYS = 30`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

```python
# tests/test_pulluk_brief_core.py
from datetime import date

from tools.pulluk_brief_core import (
    TopicPlan,
    dong_of,
    is_outdoor,
    pick_deep,
    plan_for,
    recent_topics,
)


def _place(name, cat="식당", c="칼국수", r=1000, lat=37.5, lon=127.0,
           addr="서울 종로구 청진동 1", **extra):
    return {"name": name, "cat": cat, "lat": lat, "lon": lon, "addr": addr,
            "sid": name, "d": {"c": c, "r": r, **extra}}


def _data():
    places = [_place(f"칼국수{i}", r=2000 - i * 10) for i in range(8)]
    places += [_place(f"곰탕{i}", c="곰탕,설렁탕", r=1500 - i * 10) for i in range(8)]
    places += [
        _place("성수식당", c="한식", lat=37.5435, lon=127.048, addr="서울 성동구 성수동1가 1"),
        _place("성수카페", cat="카페", c="카페", lat=37.5440, lon=127.049, addr="서울 성동구 성수동1가 2"),
        _place("서울숲공원", cat="스팟", c="공원", lat=37.5445, lon=127.047, addr="서울 성동구 성수동1가 3"),
        _place("성수편집숍", cat="스팟", c="쇼핑", lat=37.5450, lon=127.050, addr="서울 성동구 성수동1가 4"),
    ]
    regions = [{"name": "성수·서울숲", "sido": "서울", "lat": 37.5435, "lon": 127.048,
                "radius": 1.4, "count": 4}]
    return {"places": places, "regions": regions}


def test_dong_of_strips_numbers():
    assert dong_of("서울 성동구 성수동1가 668-79") == "성수동"


def test_is_outdoor_detects_park_only():
    assert is_outdoor(_place("서울숲공원", cat="스팟")) is True
    assert is_outdoor(_place("성수편집숍", cat="스팟")) is False


def test_recent_topics_excludes_old_entries():
    archive = [{"date": "2026-08-25", "topic": "칼국수", "places": []},
               {"date": "2026-01-01", "topic": "곰탕,설렁탕", "places": []}]
    topics = recent_topics(archive, date(2026, 8, 26))
    assert "칼국수" in topics
    assert "곰탕,설렁탕" not in topics


def test_roster_skips_recently_used_topic():
    archive = [{"date": "2026-08-25", "topic": "칼국수", "places": []}]
    plan = plan_for(_data(), archive, date(2026, 8, 24), rainy=False)  # 월요일 → 족보
    assert plan.kind == "족보"
    assert plan.topic != "칼국수"


def test_course_drops_outdoor_places_when_rainy():
    plan = plan_for(_data(), [], date(2026, 8, 25), rainy=True)  # 화요일 → 코스
    assert plan.kind == "코스"
    assert plan.rainy is True
    assert all(not is_outdoor(p) for p in plan.places)


def test_deep_dive_avoids_recent_place():
    plan = TopicPlan(kind="족보", topic="칼국수", title="t",
                     places=[_place("칼국수0"), _place("칼국수1")])
    archive = [{"date": "2026-08-25", "topic": "x", "places": [], "deep": "칼국수0"}]
    deep = pick_deep(plan, archive, date(2026, 8, 26))
    assert deep is not None and deep["name"] == "칼국수1"


def test_plan_always_returns_something():
    plan = plan_for({"places": [], "regions": []}, [], date(2026, 8, 24), rainy=False)
    assert plan.places == []
    assert plan.note
```

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

Run: `C:\venvs\willy\Scripts\python.exe -m pytest tests/test_pulluk_brief_core.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tools.pulluk_brief_core'`

- [ ] **Step 3: 구현한다**

```python
# tools/pulluk_brief_core.py
# -*- coding: utf-8 -*-
"""오늘의 브리핑 주제를 고르는 순수 로직.

네트워크·파일 I/O를 두지 않는다. 로테이션 규칙을 바꿔도 전송이나
발행 코드를 건드릴 일이 없고, 테스트가 빨라진다.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import date, datetime

# 요일별 기본 골격 (0=월). 설계 문서 §4.1
ROTATION = {0: "족보", 1: "코스", 2: "족보", 3: "코스", 4: "족보", 5: "드라이브", 6: "변주"}

# 월별 가중 키워드. 세부업종에 부분 문자열로 걸리면 가산점을 준다.
SEASON_KEYWORDS = {
    1: ("칼국수", "곰탕"), 2: ("곰탕", "만두"), 3: ("막국수", "칼국수"),
    4: ("막국수", "냉면"), 5: ("냉면", "막국수"), 6: ("냉면", "콩국수"),
    7: ("냉면", "콩국수", "막국수"), 8: ("냉면", "콩국수", "막국수"),
    9: ("칼국수", "순대"), 10: ("칼국수", "곰탕"), 11: ("곰탕", "순대"), 12: ("곰탕", "만두"),
}

# 비 오는 날 코스에서 뺄 장소. 이름·업종에 이 단어가 있으면 야외로 본다.
OUTDOOR_HINTS = ("공원", "숲", "해변", "호수", "산책", "강변", "천변", "피크닉")

# 일요일 변주 편 주제. (테마, 이름·업종 매칭 힌트)
VARIETY_THEMES = (
    ("해장", ("해장", "국밥", "순대", "곰탕", "감자탕")),
    ("혼밥", ("국밥", "순대", "칼국수", "덮밥", "라면", "라멘")),
    ("심야", ()),           # 영업시간 힌트로 거른다
    ("주차 되는 집", ()),    # d.pk == 1 로 거른다
)

# 족보로 쓰기엔 너무 넓은 업종. 이걸로 묶으면 주제가 안 선다.
BROAD_CATEGORIES = ("한식", "육류,고기요리", "양식", "일식당", "중식당")

TOPIC_DAYS = 60   # 같은 주제 재사용 금지 기간
PLACE_DAYS = 30   # 같은 가게 재등장 금지 기간
MIN_ROSTER = 5
MAX_ROSTER = 6
MIN_COURSE_STOPS = 3


@dataclass
class TopicPlan:
    kind: str                       # 족보 | 코스 | 드라이브 | 변주
    topic: str                      # "칼국수" / "성수·서울숲"
    title: str                      # 카톡·페이지 제목
    places: list[dict] = field(default_factory=list)
    deep: dict | None = None
    rainy: bool = False
    note: str = ""                  # 소재 부족 등 사람에게 알릴 말


def dong_of(addr: str) -> str:
    """주소에서 동네 토큰을 뽑는다. "서울 성동구 성수동1가 668-79" → "성수동"."""
    parts = (addr or "").split()
    token = parts[2] if len(parts) > 2 else (parts[1] if len(parts) > 1 else "")
    return re.sub(r"\d.*$", "", token)


def category_of(place: dict) -> str:
    return ((place.get("d") or {}).get("c") or "").strip()


def review_of(place: dict) -> int:
    return int((place.get("d") or {}).get("r") or 0)


def is_outdoor(place: dict) -> bool:
    if place.get("cat") != "스팟":
        return False
    blob = place.get("name", "") + " " + category_of(place)
    return any(hint in blob for hint in OUTDOOR_HINTS)


def _within(entry_date: str, today: date, days: int) -> bool:
    try:
        parsed = datetime.strptime(entry_date, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return False
    return 0 <= (today - parsed).days <= days


def recent_topics(archive: list[dict], today: date, days: int = TOPIC_DAYS) -> set[str]:
    return {e["topic"] for e in archive
            if e.get("topic") and _within(e.get("date", ""), today, days)}


def recent_places(archive: list[dict], today: date, days: int = PLACE_DAYS) -> set[str]:
    names: set[str] = set()
    for entry in archive:
        if not _within(entry.get("date", ""), today, days):
            continue
        names.update(entry.get("places") or [])
        if entry.get("deep"):
            names.add(entry["deep"])
    return names


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    rad = math.pi / 180
    a = (math.sin((lat2 - lat1) * rad / 2) ** 2
         + math.cos(lat1 * rad) * math.cos(lat2 * rad) * math.sin((lon2 - lon1) * rad / 2) ** 2)
    return 2 * 6371.0 * math.asin(math.sqrt(a))


def pick_roster(data: dict, archive: list[dict], today: date, rainy: bool) -> TopicPlan | None:
    """카테고리 족보. 최근 안 쓴 업종 중 리뷰 총량이 두꺼운 쪽을 고른다."""
    used_topics = recent_topics(archive, today)
    used_places = recent_places(archive, today)
    season = SEASON_KEYWORDS.get(today.month, ())

    buckets: dict[str, list[dict]] = {}
    for place in data.get("places", []):
        if place.get("cat") not in ("식당", "바"):
            continue
        cat = category_of(place)
        if not cat or cat in BROAD_CATEGORIES:
            continue
        buckets.setdefault(cat, []).append(place)

    scored: list[tuple[float, str, list[dict]]] = []
    for cat, places in buckets.items():
        if cat in used_topics:
            continue
        fresh = [p for p in places if p.get("name") not in used_places]
        if len(fresh) < MIN_ROSTER:
            continue
        fresh.sort(key=review_of, reverse=True)
        top = fresh[:MAX_ROSTER]
        score = sum(review_of(p) for p in top) / 1000.0
        if any(keyword in cat for keyword in season):
            score += 50.0
        scored.append((score, cat, top))

    if not scored:
        return None
    scored.sort(key=lambda item: -item[0])
    _, cat, top = scored[0]
    return TopicPlan(kind="족보", topic=cat,
                     title=f"수도권 {cat.split(',')[0]} 탑티어 족보",
                     places=top, rainy=rainy)


def pick_course(data: dict, archive: list[dict], today: date, rainy: bool,
                drive: bool) -> TopicPlan | None:
    """지역 코스. 식당→스팟→카페→식당 순서로 가까운 곳을 이어 붙인다."""
    used_topics = recent_topics(archive, today)
    used_places = recent_places(archive, today)

    regions = [r for r in data.get("regions", []) if r.get("name") not in used_topics]
    regions = [r for r in regions if (r.get("sido") != "서울") == drive]
    regions.sort(key=lambda r: -r.get("count", 0))

    for region in regions:
        pool: dict[str, list[dict]] = {}
        for place in data.get("places", []):
            if haversine_km(region["lat"], region["lon"],
                            place["lat"], place["lon"]) > region.get("radius", 1.4):
                continue
            if place.get("name") in used_places:
                continue
            if rainy and is_outdoor(place):
                continue
            pool.setdefault(place.get("cat", ""), []).append(place)

        stops: list[dict] = []
        cur: dict | None = None
        for slot in ("식당", "스팟", "카페", "식당"):
            cands = [p for p in pool.get(slot, []) if p not in stops]
            if not cands:
                continue
            if cur is None:
                cands.sort(key=review_of, reverse=True)
            else:
                cands.sort(key=lambda p: haversine_km(cur["lat"], cur["lon"], p["lat"], p["lon"]))
            stops.append(cands[0])
            cur = cands[0]

        if len(stops) >= MIN_COURSE_STOPS:
            kind = "드라이브" if drive else "코스"
            suffix = "근교 드라이브 코스" if drive else "하루 코스"
            return TopicPlan(kind=kind, topic=region["name"],
                             title=f"{region['name']} {suffix}", places=stops, rainy=rainy,
                             note="비 예보라 실내 위주로 짰다" if rainy else "")
    return None


def pick_variety(data: dict, archive: list[dict], today: date, rainy: bool) -> TopicPlan | None:
    """일요일 변주 편. 상황형 테마로 5~6곳을 모은다."""
    used_topics = recent_topics(archive, today)
    used_places = recent_places(archive, today)

    for theme, hints in VARIETY_THEMES:
        if theme in used_topics:
            continue
        picked: list[dict] = []
        for place in data.get("places", []):
            if place.get("cat") not in ("식당", "바") or place.get("name") in used_places:
                continue
            detail = place.get("d") or {}
            if theme == "심야":
                matched = any(t in (detail.get("h") or "") for t in ("23:", "24:", "다음 날"))
            elif theme == "주차 되는 집":
                matched = detail.get("pk") == 1
            else:
                blob = place.get("name", "") + " " + category_of(place)
                matched = any(hint in blob for hint in hints)
            if matched:
                picked.append(place)
        if len(picked) >= MIN_ROSTER:
            picked.sort(key=review_of, reverse=True)
            return TopicPlan(kind="변주", topic=theme, title=f"{theme} 탑티어 족보",
                             places=picked[:MAX_ROSTER], rainy=rainy)
    return None


def pick_deep(plan: TopicPlan, archive: list[dict], today: date) -> dict | None:
    """집중분석 1곳. 최근 다룬 곳은 빼고 정보가 가장 촘촘한 집을 고른다."""
    used = recent_places(archive, today)
    cands = [p for p in plan.places if p.get("name") not in used] or list(plan.places)
    if not cands:
        return None

    def richness(place: dict) -> tuple[int, int]:
        detail = place.get("d") or {}
        filled = sum(1 for key in ("c", "r", "s", "h", "pk") if detail.get(key) is not None)
        return (filled, review_of(place))

    return max(cands, key=richness)


def plan_for(data: dict, archive: list[dict], today: date, rainy: bool) -> TopicPlan:
    """요일 로테이션대로 시도하고, 소재가 없으면 다른 유형으로 넘어간다."""
    wanted = ROTATION[today.weekday()]
    order = [wanted] + [k for k in ("족보", "코스", "변주", "드라이브") if k != wanted]

    for kind in order:
        if kind == "족보":
            plan = pick_roster(data, archive, today, rainy)
        elif kind == "코스":
            plan = pick_course(data, archive, today, rainy, drive=False)
        elif kind == "드라이브":
            plan = pick_course(data, archive, today, rainy, drive=True)
        else:
            plan = pick_variety(data, archive, today, rainy)
        if plan is not None:
            if kind != wanted:
                extra = f"{wanted} 소재가 부족해 {kind}으로 대체함"
                plan.note = f"{plan.note} / {extra}" if plan.note else extra
            plan.deep = pick_deep(plan, archive, today)
            return plan

    return TopicPlan(kind=wanted, topic="소재 부족", title="오늘은 소재가 부족합니다",
                     places=[], rainy=rainy,
                     note="즐겨찾기를 더 넣거나 중복 금지 기간을 줄여야 한다")
```

- [ ] **Step 4: 테스트가 통과하는지 확인한다**

Run: `C:\venvs\willy\Scripts\python.exe -m pytest tests/test_pulluk_brief_core.py -v`
Expected: PASS (7 passed)

- [ ] **Step 5: 커밋한다**

```bash
git add tools/pulluk_brief_core.py tests/test_pulluk_brief_core.py
git commit -m "feat: 브리핑 주제 선정 엔진 (요일 로테이션·시즌·날씨·중복 방지)"
```

---

### Task 2: 초안 생성기

**Files:**
- Create: `tools/pulluk_brief_text.py`, `assets/pulluk/style_examples.json`
- Test: `tests/test_pulluk_brief_text.py`

**Interfaces:**
- Consumes: Task 1의 `TopicPlan`, `dong_of`, `category_of`, `review_of`
- Produces:
  - `one_liner(place: dict) -> str` — 항상 `※확인`으로 끝난다
  - `template_draft(plan: TopicPlan) -> str`
  - `deep_dive_block(place: dict) -> str`
  - `build_prompt(plan: TopicPlan, styles: list[str]) -> str`
  - `gemini_draft(plan, api_key: str | None, generate=None, http=None, sleep=time.sleep) -> str | None`
  - `compose(plan, api_key: str | None, generate=None) -> tuple[str, str]` — 두 번째 값은 `"ai"` 또는 `"template"`
  - `checklist(plan: TopicPlan) -> list[str]`
  - `load_styles(path: Path | None = None) -> list[str]`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

```python
# tests/test_pulluk_brief_text.py
from tools.pulluk_brief_core import TopicPlan
from tools.pulluk_brief_text import checklist, compose, one_liner, template_draft


def _place(name, **detail):
    return {"name": name, "cat": "식당", "lat": 37.5, "lon": 127.0,
            "addr": "서울 서초구 서초동 1", "sid": name,
            "d": {"c": "칼국수", "r": 3150, "s": 4.5, **detail}}


def _roster_plan():
    places = [_place(f"집{i}") for i in range(5)]
    return TopicPlan(kind="족보", topic="칼국수", title="수도권 칼국수 탑티어 족보",
                     places=places, deep=places[0])


def _course_plan():
    places = [_place("밥집"), _place("구경거리"), _place("커피집")]
    return TopicPlan(kind="코스", topic="성수·서울숲", title="성수·서울숲 하루 코스",
                     places=places, deep=places[0])


def test_one_liner_marks_unverified():
    assert one_liner(_place("집")).endswith("※확인")
    assert "리뷰 3,150" in one_liner(_place("집"))


def test_roster_draft_has_channel_markers():
    draft = template_draft(_roster_plan())
    assert "탑티어 족보 정리해봄" in draft
    assert "*광고/협찬 아님" in draft
    assert "1. 집0(서초동)" in draft
    assert "(+) 팔로우 해두면 맛집/카페/볼거리 매일 올라옴" in draft


def test_course_draft_uses_course_opening():
    draft = template_draft(_course_plan())
    assert "목적지 정해지면 코스부터 짜는 파워J가" in draft
    assert "🚩밥집" in draft


def test_compose_falls_back_to_template_without_key():
    draft, source = compose(_roster_plan(), api_key=None)
    assert source == "template"
    assert "탑티어 족보 정리해봄" in draft


def test_compose_uses_generator_when_available():
    def fake_generate(http, api_key, payload, sleep):
        return "AI가 쓴 초안"

    draft, source = compose(_roster_plan(), api_key="key", generate=fake_generate)
    assert source == "ai"
    assert draft == "AI가 쓴 초안"


def test_compose_falls_back_when_generator_raises():
    def broken(http, api_key, payload, sleep):
        raise RuntimeError("429")

    draft, source = compose(_roster_plan(), api_key="key", generate=broken)
    assert source == "template"


def test_checklist_mentions_verification():
    checks = checklist(_roster_plan())
    assert any("※확인" in c or "한줄평" in c for c in checks)
    assert any("가격" in c or "영업" in c for c in checks)
```

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

Run: `C:\venvs\willy\Scripts\python.exe -m pytest tests/test_pulluk_brief_text.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tools.pulluk_brief_text'`

- [ ] **Step 3: 말투 예시 파일을 만든다**

```json
{
  "_설명": "채널 실게시물. Gemini 프롬프트에 말투 기준으로 들어간다. 새 글이 터지면 여기에 추가하면 된다.",
  "examples": [
    "내 기준 서울 콩국수 탑티어 족보 정리해봄.\n*광고/협찬 아님\n\n1. 진주회관(시청) : 뭐니뭐니해도 클래식.\n2. 진주집(여의도) : 여의도의 터줏대감. 만두도 굿\n3. 임병주산동칼국수(양재) : 쫄깃한 면과 꾸덕한 국물의 조화. 만두, 칼국수도 맛있음\n4. 해밝음순두부(강서) : 숨겨진 강자\n5. 서민준밀밭(영등포) : 검은 콩국수가 명물\n\n나만 아는 콩국수 성지 있으면 풀어주세요\n(+) 팔로우 해두면 맛집/카페/볼거리 매일 올라옴",
    "내 기준 수도권 순대국 탑티어 족보 정리해봄.\n*광고/협찬 아님\n\n1. 농민백암순대(강남) : 너무 유명해서 뭐..\n2. 인하순대국(서초/교대) : 깔끔한데 진함\n3. 막줘군대국(고양 행신) : 숨겨진 강자\n4. 약수순대국(약수) : 맑은 스타일 강자\n5. 양재순대(양재) : 양재 직장인 성지\n6. 80년 전통 원조순대국(강서) : 막창순대국\n\n나만 아는 순대국 성지 있으면 풀어주세요\n(+) 팔로우 해두면 맛집/카페/볼거리 매일 올라옴",
    "내 기준 수도권 만두 탑티어 족보 정리해봄.\n만두 블로그도 했었으니 믿고 저장해도 됨\n*광고/협찬 아님\n\n1. 은마왕만두(대치역) : 대치동 토박이들이 숨겨두고 가는 맛집. 매장이 스시집처럼 깔끔하고 무료주차까지!\n2. 버들만두(염창역) : 여긴 아마 많이들 모를텐데 내기준 김치 왕만두 원탑. 몇 팩씩 사서 냉동해둬야함\n3. 가메골손왕만두(남대문) : 서울역 근무할때 혼자 왕만두 두판씩 먹던 집\n4. 해안칼국수(인천역) : 흐물흐물 부드러운 접시만두. 마성의 매력이 있음\n\n나만 아는 만두 성지 있으면 풀어주세요\n(+) 팔로우 해두면 맛집/카페/볼거리 매일 올라옴",
    "목적지 정해지면 코스부터 짜는 파워J가\n주말 더위+시간 둘다 녹일 하남 코스 딱 짜드림.\n(광고 협찬 절대 아님)\n\n1. 🚩드로게리아 : 뇨끼+피자로 브런치 + 사장님이 큐레이션해둔 식료품 구경\n2. 🚩미사장 : 숲멍 or 투썸 팔당점에서 물멍 (투썸은 창가자리 굉장히 치열함)\n3. 🚩스타필드 하남 : 팝업 보고 세일기간 쇼핑\n4. 🚩시가올 비빔국수 : 시원한 살얼음 비빔국수 때리고 귀가\n\n앞으로 짜줄 코스가 무궁무진 너무 많다.\n(+) 팔로우 해두면 이제 주말에 뭐할지 고민할일 없음."
  ]
}
```

- [ ] **Step 4: 초안 생성기를 구현한다**

```python
# tools/pulluk_brief_text.py
# -*- coding: utf-8 -*-
"""브리핑 초안 문장을 만든다.

Gemini가 채널 말투로 쓰고, 죽으면 템플릿이 대신 쓴다. 어느 쪽이든
'경험담은 지어내지 않는다'는 원칙을 지키려고 한줄평 자리에는 데이터로
확인된 사실만 넣고 ※확인 표시를 붙인다.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import httpx

from tools.pulluk_brief_core import TopicPlan, category_of, dong_of, review_of

PROJECT_ROOT = Path(__file__).resolve().parents[1]
STYLE_PATH = PROJECT_ROOT / "assets" / "pulluk" / "style_examples.json"

CLOSING_ROSTER = "나만 아는 {topic} 성지 있으면 풀어주세요\n(+) 팔로우 해두면 맛집/카페/볼거리 매일 올라옴"
CLOSING_COURSE = "앞으로 짜줄 코스 한 보따리 쌓여있다.\n(+) 팔로우 해두면 이제 주말에 뭐할지 고민할일 없음."


def load_styles(path: Path | None = None) -> list[str]:
    try:
        raw = json.loads((path or STYLE_PATH).read_text(encoding="utf-8"))
        return list(raw.get("examples") or [])
    except (OSError, ValueError):
        return []


def one_liner(place: dict) -> str:
    """데이터로 확인된 사실만 담은 한줄평 초안."""
    detail = place.get("d") or {}
    bits: list[str] = []
    cat = category_of(place)
    if cat:
        bits.append(cat.split(",")[0])
    if detail.get("r"):
        bits.append(f"리뷰 {int(detail['r']):,}")
    if detail.get("s"):
        bits.append(f"★{detail['s']}")
    if detail.get("h"):
        bits.append(str(detail["h"]))
    if detail.get("pk") == 1:
        bits.append("주차 가능")
    body = " · ".join(bits) if bits else "정보 보강 필요"
    return f"{body} ※확인"


def deep_dive_block(place: dict) -> str:
    """집중분석 1곳 블록."""
    if not place:
        return ""
    detail = place.get("d") or {}
    lines = [f"■ 오늘의 집중분석 — {place.get('name', '')}({dong_of(place.get('addr', ''))})"]
    lines.append(f"  주소: {place.get('addr', '')}")
    if category_of(place):
        lines.append(f"  업종: {category_of(place)}")
    if detail.get("r"):
        score = f" · ★{detail['s']}" if detail.get("s") else ""
        lines.append(f"  방문자 리뷰 {int(detail['r']):,}{score}")
    if detail.get("h"):
        lines.append(f"  영업 힌트: {detail['h']}")
    if detail.get("pk") == 1:
        lines.append(f"  주차: {detail.get('pkt') or '가능'}")
    if place.get("sid"):
        lines.append(f"  지도: https://map.naver.com/p/entry/place/{place['sid']}")
    return "\n".join(lines)


def template_draft(plan: TopicPlan) -> str:
    """AI 없이도 나오는 초안. 채널 고정 포맷을 그대로 따른다."""
    if not plan.places:
        return f"{plan.title}\n\n{plan.note}"

    if plan.kind in ("코스", "드라이브"):
        head = ("목적지 정해지면 코스부터 짜는 파워J가\n"
                f"{plan.topic} 코스 딱 짜드림.\n(광고 협찬 절대 아님)")
        body = "\n".join(
            f"{i}. 🚩{p['name']}({dong_of(p.get('addr', ''))})\n{one_liner(p)}"
            for i, p in enumerate(plan.places, 1)
        )
        return f"{head}\n\n{body}\n\n{CLOSING_COURSE}"

    label = plan.topic.split(",")[0]
    head = f"내 기준 수도권 {label} 탑티어 족보 정리해봄.\n*광고/협찬 아님"
    body = "\n".join(
        f"{i}. {p['name']}({dong_of(p.get('addr', ''))}) : {one_liner(p)}"
        for i, p in enumerate(plan.places, 1)
    )
    return f"{head}\n\n{body}\n\n{CLOSING_ROSTER.format(topic=label)}"


def build_prompt(plan: TopicPlan, styles: list[str]) -> str:
    facts = "\n".join(
        f"- {p['name']} / {dong_of(p.get('addr', ''))} / {category_of(p) or '업종 미상'}"
        f" / 리뷰 {review_of(p):,} / {(p.get('d') or {}).get('h') or '영업정보 없음'}"
        for p in plan.places
    )
    examples = "\n\n---\n\n".join(styles)
    return (
        "너는 아래 예시 글을 쓴 사람의 말투를 그대로 흉내내 스레드 게시글 초안을 쓴다.\n\n"
        f"[말투 예시]\n{examples}\n\n"
        f"[오늘 주제]\n{plan.title} ({plan.kind})\n"
        f"{'비 예보라 실내 위주다.' if plan.rainy else ''}\n\n"
        f"[쓸 수 있는 사실 — 이 목록 밖의 정보를 지어내지 마라]\n{facts}\n\n"
        "[규칙]\n"
        "1. 예시와 같은 오프닝·번호 목록·클로징 구조를 유지한다.\n"
        "2. 맛·분위기 같은 개인 경험은 절대 지어내지 말고, 위 사실만 근거로 쓴다.\n"
        "3. 각 항목의 한줄평 끝에 ' ※확인'을 붙인다.\n"
        "4. 400자 이내. 해설 없이 게시글 본문만 출력한다.\n"
    )


def gemini_draft(plan: TopicPlan, api_key: str | None, generate=None,
                 http=None, sleep=time.sleep) -> str | None:
    """Gemini 1콜. 어떤 이유로든 실패하면 None을 돌려주고 호출자가 폴백한다."""
    if not api_key or not plan.places:
        return None
    if generate is None:
        try:
            from willy.analyzer import gemini_generate
        except ImportError:
            return None
        generate = gemini_generate

    prompt = build_prompt(plan, load_styles())
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    client = http or httpx.Client(timeout=60.0)
    try:
        text = generate(client, api_key, payload, sleep)
    except Exception:
        return None
    finally:
        if http is None:
            client.close()
    text = (text or "").strip()
    return text or None


def compose(plan: TopicPlan, api_key: str | None, generate=None) -> tuple[str, str]:
    draft = gemini_draft(plan, api_key, generate=generate)
    if draft:
        return draft, "ai"
    return template_draft(plan), "template"


def checklist(plan: TopicPlan) -> list[str]:
    checks = [
        "한줄평의 ※확인 표시는 직접 가본 경험으로 바꾸고 지울 것",
        "가격·영업시간·휴무는 게시 직전 최신인지 대조할 것",
    ]
    if any((p.get("d") or {}).get("pk") == 1 for p in plan.places):
        checks.append("주차 안내문은 매장 등록 정보라 실제와 다를 수 있음")
    if plan.rainy:
        checks.append("비 예보 기준으로 실내 위주로 짬 — 날씨가 바뀌면 야외 슬롯 추가 가능")
    if plan.note:
        checks.append(f"기획 메모: {plan.note}")
    return checks
```

- [ ] **Step 5: 테스트가 통과하는지 확인한다**

Run: `C:\venvs\willy\Scripts\python.exe -m pytest tests/test_pulluk_brief_text.py -v`
Expected: PASS (7 passed)

- [ ] **Step 6: 커밋한다**

```bash
git add tools/pulluk_brief_text.py tests/test_pulluk_brief_text.py assets/pulluk/style_examples.json
git commit -m "feat: 브리핑 초안 생성기 (채널 말투 학습 + 템플릿 폴백)"
```

---

### Task 3: 카카오 전송 모듈

**Files:**
- Create: `tools/pulluk_kakao.py`
- Test: `tests/test_pulluk_kakao.py`

**Interfaces:**
- Consumes: 없음 (독립 모듈)
- Produces:
  - `KakaoError(RuntimeError)`
  - `refresh_access_token(rest_key: str, refresh_token: str, http: httpx.Client) -> tuple[str, str | None]` — (access_token, 새 refresh_token 또는 None)
  - `split_text(text: str, limit: int = 200) -> list[str]`
  - `send_text(http, access_token: str, text: str, link_url: str | None = None) -> None`
  - `send_feed(http, access_token: str, title: str, description: str, image_url: str | None, link_url: str) -> None`
  - `send_brief(http, access_token: str, title: str, summary: str, body: str, link_url: str, image_url: str | None = None) -> int` — 보낸 통 수

- [ ] **Step 1: 실패하는 테스트를 쓴다**

```python
# tests/test_pulluk_kakao.py
import json

import httpx
import pytest

from tools.pulluk_kakao import (
    KakaoError,
    refresh_access_token,
    send_brief,
    send_text,
    split_text,
)


def test_split_text_keeps_lines_within_limit():
    text = "\n".join(f"{i}번째 줄입니다" * 2 for i in range(20))
    chunks = split_text(text, limit=200)
    assert all(len(c) <= 200 for c in chunks)
    assert "".join(c.replace("\n", "") for c in chunks) == text.replace("\n", "")


def test_split_text_single_long_line_is_hard_split():
    chunks = split_text("가" * 450, limit=200)
    assert [len(c) for c in chunks] == [200, 200, 50]


def test_refresh_access_token_returns_rotated_token():
    def handler(request):
        assert b"grant_type=refresh_token" in request.content
        return httpx.Response(200, json={"access_token": "AT", "refresh_token": "NEW"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    access, rotated = refresh_access_token("KEY", "OLD", client)
    assert access == "AT"
    assert rotated == "NEW"


def test_refresh_access_token_raises_on_error():
    client = httpx.Client(transport=httpx.MockTransport(
        lambda request: httpx.Response(400, json={"error": "invalid_grant"})))
    with pytest.raises(KakaoError):
        refresh_access_token("KEY", "OLD", client)


def test_send_text_posts_template_object():
    seen = {}

    def handler(request):
        seen["body"] = request.content.decode()
        seen["auth"] = request.headers["Authorization"]
        return httpx.Response(200, json={"result_code": 0})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    send_text(client, "AT", "안녕", link_url="https://example.com")
    assert seen["auth"] == "Bearer AT"
    assert "template_object" in seen["body"]


def test_send_brief_sends_card_plus_chunks():
    calls = []

    def handler(request):
        calls.append(request.content.decode())
        return httpx.Response(200, json={"result_code": 0})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    sent = send_brief(client, "AT", title="제목", summary="요약",
                      body="본문\n" * 120, link_url="https://example.com")
    assert sent == len(calls) >= 2
    assert "feed" in calls[0]
```

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

Run: `C:\venvs\willy\Scripts\python.exe -m pytest tests/test_pulluk_kakao.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tools.pulluk_kakao'`

- [ ] **Step 3: 구현한다**

```python
# tools/pulluk_kakao.py
# -*- coding: utf-8 -*-
"""카카오톡 '나에게 보내기' 전송.

PlayMCP는 PC 전용이라 무인 실행이 안 된다. 나챗방 MCP가 감싸고 있는
공식 API를 직접 호출해 GitHub Actions에서도 같은 곳으로 보낸다.
텍스트 템플릿이 200자까지라 본문은 잘라서 여러 통으로 나눈다.
"""
from __future__ import annotations

import json

import httpx

TOKEN_URL = "https://kauth.kakao.com/oauth/token"
SEND_URL = "https://kapi.kakao.com/v2/api/talk/memo/default/send"
TEXT_LIMIT = 200


class KakaoError(RuntimeError):
    """토큰 갱신이나 전송이 실패했을 때. 메시지에 토큰을 담지 않는다."""


def refresh_access_token(rest_key: str, refresh_token: str,
                         http: httpx.Client) -> tuple[str, str | None]:
    """리프레시 토큰으로 액세스 토큰을 받는다.

    카카오는 리프레시 토큰 잔여 기간이 1개월 미만일 때만 새 것을 함께 준다.
    새로 왔으면 호출자가 저장소 시크릿을 갱신해야 한다.
    """
    response = http.post(TOKEN_URL, data={
        "grant_type": "refresh_token",
        "client_id": rest_key,
        "refresh_token": refresh_token,
    })
    if response.status_code != 200:
        raise KakaoError(f"토큰 갱신 실패: HTTP {response.status_code} {response.text[:200]}")
    body = response.json()
    if not body.get("access_token"):
        raise KakaoError("토큰 갱신 응답에 access_token이 없다")
    return body["access_token"], body.get("refresh_token")


def split_text(text: str, limit: int = TEXT_LIMIT) -> list[str]:
    """줄 경계를 지키며 limit 이하 조각으로 나눈다."""
    chunks: list[str] = []
    current = ""
    for line in text.split("\n"):
        candidate = line if not current else f"{current}\n{line}"
        if len(candidate) <= limit:
            current = candidate
            continue
        if current:
            chunks.append(current)
            current = ""
        while len(line) > limit:
            chunks.append(line[:limit])
            line = line[limit:]
        current = line
    if current:
        chunks.append(current)
    return chunks


def _send(http: httpx.Client, access_token: str, template_object: dict) -> None:
    response = http.post(
        SEND_URL,
        headers={"Authorization": f"Bearer {access_token}"},
        data={"template_object": json.dumps(template_object, ensure_ascii=False)},
    )
    if response.status_code != 200:
        raise KakaoError(f"전송 실패: HTTP {response.status_code} {response.text[:200]}")


def send_text(http: httpx.Client, access_token: str, text: str,
              link_url: str | None = None) -> None:
    link = {"web_url": link_url, "mobile_web_url": link_url} if link_url else {}
    _send(http, access_token, {"object_type": "text", "text": text[:TEXT_LIMIT], "link": link})


def send_feed(http: httpx.Client, access_token: str, title: str, description: str,
              image_url: str | None, link_url: str) -> None:
    content = {
        "title": title,
        "description": description,
        "link": {"web_url": link_url, "mobile_web_url": link_url},
    }
    if image_url:
        content["image_url"] = image_url
    _send(http, access_token, {
        "object_type": "feed",
        "content": content,
        "buttons": [{"title": "전문 보기",
                     "link": {"web_url": link_url, "mobile_web_url": link_url}}],
    })


def send_brief(http: httpx.Client, access_token: str, title: str, summary: str,
               body: str, link_url: str, image_url: str | None = None) -> int:
    """요약 카드 1통 + 본문 조각 n통. 보낸 통 수를 돌려준다."""
    send_feed(http, access_token, title, summary, image_url, link_url)
    sent = 1
    for chunk in split_text(body):
        send_text(http, access_token, chunk, link_url)
        sent += 1
    return sent
```

- [ ] **Step 4: 테스트가 통과하는지 확인한다**

Run: `C:\venvs\willy\Scripts\python.exe -m pytest tests/test_pulluk_kakao.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: 커밋한다**

```bash
git add tools/pulluk_kakao.py tests/test_pulluk_kakao.py
git commit -m "feat: 카카오 나에게 보내기 전송 모듈 (토큰 갱신·200자 분할)"
```

---

### Task 4: 브리핑 페이지

**Files:**
- Create: `tools/pulluk_brief_page.py`
- Test: `tests/test_pulluk_brief_page.py`

**Interfaces:**
- Consumes: Task 1의 `TopicPlan`, `dong_of`; Task 2의 `deep_dive_block`
- Produces:
  - `render_brief(plan: TopicPlan, draft: str, checks: list[str], day: date, source: str) -> str`
  - `render_index(archive: list[dict]) -> str`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

```python
# tests/test_pulluk_brief_page.py
from datetime import date

from tools.pulluk_brief_core import TopicPlan
from tools.pulluk_brief_page import render_brief, render_index


def _plan():
    place = {"name": "칼국수집", "cat": "식당", "lat": 37.5, "lon": 127.0,
             "addr": "서울 서초구 서초동 1", "sid": "123", "d": {"c": "칼국수", "r": 100}}
    return TopicPlan(kind="족보", topic="칼국수", title="수도권 칼국수 탑티어 족보",
                     places=[place], deep=place)


def test_render_brief_contains_draft_and_copy_button():
    html = render_brief(_plan(), "초안 본문", ["확인1"], date(2026, 8, 26), "template")
    assert "초안 본문" in html
    assert "복사" in html
    assert "수도권 칼국수 탑티어 족보" in html
    assert "확인1" in html
    assert "map.naver.com/p/entry/place/123" in html


def test_render_brief_escapes_html_in_draft():
    html = render_brief(_plan(), "<script>alert(1)</script>", [], date(2026, 8, 26), "ai")
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_render_index_lists_dates_newest_first():
    archive = [{"date": "2026-08-25", "title": "어제 것", "kind": "코스"},
               {"date": "2026-08-26", "title": "오늘 것", "kind": "족보"}]
    html = render_index(archive)
    assert html.index("2026-08-26") < html.index("2026-08-25")
```

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

Run: `C:\venvs\willy\Scripts\python.exe -m pytest tests/test_pulluk_brief_page.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tools.pulluk_brief_page'`

- [ ] **Step 3: 구현한다**

```python
# tools/pulluk_brief_page.py
# -*- coding: utf-8 -*-
"""브리핑 페이지 HTML.

카톡은 200자씩 끊겨 오니 복사·확인은 이 페이지에서 하는 게 편하다.
코스 스튜디오와 같은 색·서체를 써서 같은 채널의 도구로 보이게 한다.
"""
from __future__ import annotations

from datetime import date
from html import escape

from tools.pulluk_brief_core import TopicPlan, dong_of

WEEKDAYS = ("월", "화", "수", "목", "금", "토", "일")

STYLE = """
:root { --flag:#2447D6; --flag-deep:#1B36A8; --yellow:#F6BE2C; --paper:#FFF9EC;
        --ink:#221D16; --signal:#E8442E; --card:#fff; --muted:#7A6F60; }
* { margin:0; padding:0; box-sizing:border-box; }
body { font-family:'Pretendard Variable',Pretendard,-apple-system,sans-serif;
       background:var(--paper); color:var(--ink); line-height:1.6; }
header { background:var(--yellow); border-bottom:3px solid var(--ink); padding:22px clamp(16px,4vw,40px); }
header .eyebrow { font-size:13px; letter-spacing:.12em; color:var(--flag-deep); font-weight:700; }
header h1 { font-size:clamp(22px,4vw,32px); line-height:1.2; margin-top:2px; }
main { max-width:820px; margin:0 auto; padding:24px clamp(16px,4vw,40px) 72px; }
section { background:var(--card); border:2px solid var(--ink); border-radius:12px;
          padding:18px; margin-bottom:18px; box-shadow:4px 4px 0 rgba(34,29,22,.12); }
h2 { font-size:18px; margin-bottom:10px; }
textarea { width:100%; min-height:320px; padding:14px; font:inherit; line-height:1.7;
           border:2px solid var(--ink); border-radius:10px; background:var(--paper); resize:vertical; }
button.copy { margin-top:10px; padding:11px 22px; font:inherit; font-weight:700; cursor:pointer;
              background:var(--yellow); border:2px solid var(--ink); border-radius:9px;
              box-shadow:3px 3px 0 var(--ink); }
ul { list-style:none; } li { padding:5px 0; border-bottom:1px dashed #e3d9c4; font-size:14px; }
li:last-child { border-bottom:0; }
a { color:var(--flag-deep); }
.check li { color:var(--signal); }
.meta { font-size:13px; color:var(--muted); margin-top:4px; }
pre { white-space:pre-wrap; font:inherit; font-size:14px; }
"""


def _head(title: str) -> str:
    return (
        "<!DOCTYPE html><html lang=\"ko\"><head><meta charset=\"UTF-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\">"
        f"<title>{escape(title)}</title>"
        "<link rel=\"icon\" href=\"data:image/svg+xml,"
        "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'>"
        "<text y='.9em' font-size='90'>🚩</text></svg>\">"
        "<link rel=\"stylesheet\" as=\"style\" crossorigin "
        "href=\"https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/"
        "pretendardvariable-dynamic-subset.min.css\">"
        f"<style>{STYLE}</style></head><body>"
    )


def render_brief(plan: TopicPlan, draft: str, checks: list[str], day: date, source: str) -> str:
    label = f"{day.isoformat()}({WEEKDAYS[day.weekday()]})"
    written = "AI 초안" if source == "ai" else "템플릿 초안"

    places_html = "".join(
        f"<li><a href=\"https://map.naver.com/p/entry/place/{escape(str(p.get('sid', '')))}\""
        " target=\"_blank\" rel=\"noopener\">"
        f"{escape(p.get('name', ''))}</a> · {escape(dong_of(p.get('addr', '')))}"
        f" · {escape(str((p.get('d') or {}).get('c') or ''))}</li>"
        for p in plan.places
    ) or "<li>선정된 장소가 없습니다</li>"

    deep = plan.deep or {}
    deep_detail = deep.get("d") or {}
    deep_rows = []
    if deep:
        deep_rows.append(f"<li>주소 · {escape(deep.get('addr', ''))}</li>")
        if deep_detail.get("r"):
            score = f" · ★{deep_detail['s']}" if deep_detail.get("s") else ""
            deep_rows.append(f"<li>방문자 리뷰 {int(deep_detail['r']):,}{escape(score)}</li>")
        if deep_detail.get("h"):
            deep_rows.append(f"<li>영업 힌트 · {escape(str(deep_detail['h']))}</li>")
        if deep_detail.get("pk") == 1:
            deep_rows.append(f"<li>주차 · {escape(str(deep_detail.get('pkt') or '가능'))}</li>")
    deep_html = "".join(deep_rows) or "<li>집중분석 대상이 없습니다</li>"

    checks_html = "".join(f"<li>{escape(c)}</li>" for c in checks) or "<li>확인할 항목 없음</li>"

    return (
        _head(f"{label} 최펄럭 브리핑")
        + "<header><div class=\"eyebrow\">최펄럭 데일리 브리핑</div>"
        + f"<h1>🚩 {escape(plan.title)}</h1>"
        + f"<div class=\"meta\">{escape(label)} · {escape(plan.kind)} · {escape(written)}</div></header>"
        + "<main>"
        + "<section><h2>게시 초안</h2>"
        + f"<textarea id=\"draft\" spellcheck=\"false\">{escape(draft)}</textarea>"
        + "<button class=\"copy\" id=\"copyBtn\">초안 복사</button></section>"
        + f"<section><h2>오늘의 장소</h2><ul>{places_html}</ul></section>"
        + f"<section><h2>집중분석 — {escape(deep.get('name', '없음'))}</h2><ul>{deep_html}</ul></section>"
        + f"<section><h2>게시 전 확인</h2><ul class=\"check\">{checks_html}</ul></section>"
        + "<p class=\"meta\"><a href=\"index.html\">지난 브리핑 보기</a></p>"
        + "</main>"
        + "<script>document.getElementById('copyBtn').addEventListener('click',function(){"
          "var t=document.getElementById('draft');"
          "navigator.clipboard.writeText(t.value).then(function(){"
          "var b=document.getElementById('copyBtn');b.textContent='복사됨 🚩';"
          "setTimeout(function(){b.textContent='초안 복사';},1400);});});</script>"
        + "</body></html>"
    )


def render_index(archive: list[dict]) -> str:
    rows = sorted(archive, key=lambda e: e.get("date", ""), reverse=True)
    items = "".join(
        f"<li><a href=\"{escape(e.get('date', ''))}.html\">{escape(e.get('date', ''))}</a>"
        f" · {escape(e.get('kind', ''))} · {escape(e.get('title', ''))}</li>"
        for e in rows
    ) or "<li>아직 브리핑이 없습니다</li>"
    return (
        _head("최펄럭 브리핑 아카이브")
        + "<header><div class=\"eyebrow\">최펄럭 데일리 브리핑</div><h1>지난 브리핑</h1></header>"
        + f"<main><section><ul>{items}</ul></section></main></body></html>"
    )
```

- [ ] **Step 4: 테스트가 통과하는지 확인한다**

Run: `C:\venvs\willy\Scripts\python.exe -m pytest tests/test_pulluk_brief_page.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: 커밋한다**

```bash
git add tools/pulluk_brief_page.py tests/test_pulluk_brief_page.py
git commit -m "feat: 브리핑 페이지 렌더러 (초안 복사·집중분석·확인 목록)"
```

---

### Task 5: 진입점 오케스트레이션

**Files:**
- Create: `tools/pulluk_brief.py`
- Test: `tests/test_pulluk_brief.py`

**Interfaces:**
- Consumes: Task 1~4의 `plan_for`, `compose`, `checklist`, `render_brief`, `render_index`, `refresh_access_token`, `send_brief`
- Produces:
  - `run(data: dict, archive: list[dict], day: date, rainy: bool, api_key: str | None, out_dir: Path) -> dict` — `{"plan","draft","source","record","summary"}`
  - `load_data() -> dict`, `load_archive() -> list[dict]`, `today_rainy(day: date) -> bool`
  - `place_image_url(place: dict, http: httpx.Client) -> str | None` — 네이버 플레이스 대표 사진
  - `main() -> None` — `--out`, `--dry-run`, `--date` 인자

- [ ] **Step 1: 실패하는 테스트를 쓴다**

```python
# tests/test_pulluk_brief.py
import json
from datetime import date

from tools.pulluk_brief import run


def _data():
    places = [{"name": f"칼국수{i}", "cat": "식당", "lat": 37.5, "lon": 127.0,
               "addr": "서울 서초구 서초동 1", "sid": str(i),
               "d": {"c": "칼국수", "r": 2000 - i}} for i in range(6)]
    return {"places": places, "regions": []}


def test_run_writes_pages_and_archive(tmp_path):
    result = run(_data(), [], date(2026, 8, 24), rainy=False, api_key=None, out_dir=tmp_path)

    assert (tmp_path / "2026-08-24.html").exists()
    assert (tmp_path / "latest.html").exists()
    assert (tmp_path / "index.html").exists()

    archive = json.loads((tmp_path / "archive.json").read_text(encoding="utf-8"))
    assert archive[0]["date"] == "2026-08-24"
    assert archive[0]["places"]
    assert result["source"] == "template"
    assert result["summary"]


def test_run_replaces_same_day_entry(tmp_path):
    old = [{"date": "2026-08-24", "topic": "옛날", "title": "옛날", "kind": "족보", "places": []}]
    run(_data(), old, date(2026, 8, 24), rainy=False, api_key=None, out_dir=tmp_path)
    archive = json.loads((tmp_path / "archive.json").read_text(encoding="utf-8"))
    same_day = [e for e in archive if e["date"] == "2026-08-24"]
    assert len(same_day) == 1
    assert same_day[0]["topic"] != "옛날"


def test_place_image_url_reads_summary_api():
    import httpx

    from tools.pulluk_brief import place_image_url

    def handler(request):
        assert "1234" in str(request.url)
        return httpx.Response(200, json={"data": {"placeDetail": {
            "images": {"images": [{"origin": "https://ldb-phinf.pstatic.net/a.jpg"}]}}}})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    assert place_image_url({"sid": "1234"}, client) == "https://ldb-phinf.pstatic.net/a.jpg"


def test_place_image_url_returns_none_on_failure():
    import httpx

    from tools.pulluk_brief import place_image_url

    client = httpx.Client(transport=httpx.MockTransport(
        lambda request: httpx.Response(500)))
    assert place_image_url({"sid": "1234"}, client) is None
    assert place_image_url({}, client) is None
```

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

Run: `C:\venvs\willy\Scripts\python.exe -m pytest tests/test_pulluk_brief.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tools.pulluk_brief'`

- [ ] **Step 3: 구현한다**

```python
# tools/pulluk_brief.py
# -*- coding: utf-8 -*-
"""데일리 브리핑 진입점.

    python tools/pulluk_brief.py --out out_brief          # 생성 + 카톡 전송
    python tools/pulluk_brief.py --out out_brief --dry-run  # 생성만

데이터는 gh-pages에 올라간 최신본을 먼저 보고(펄럭 워크플로가 06:20에
갱신한다), 실패하면 저장소 커밋본으로 떨어진다. 카카오 키가 없으면
전송을 건너뛰므로 로컬에서도 그냥 돌아간다.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import truststore

truststore.inject_into_ssl()

import httpx  # noqa: E402  truststore 주입 뒤에 import해야 한다

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from tools.pulluk_brief_core import plan_for  # noqa: E402
from tools.pulluk_brief_page import render_brief, render_index  # noqa: E402
from tools.pulluk_brief_text import checklist, compose  # noqa: E402
from tools.pulluk_kakao import KakaoError, refresh_access_token, send_brief  # noqa: E402

KST = timezone(timedelta(hours=9))
GH_PAGES = "https://raw.githubusercontent.com/hanwool-choi/willy-content-engine/gh-pages"
DATA_URL = f"{GH_PAGES}/pulluk/data.js"
ARCHIVE_URL = f"{GH_PAGES}/brief/archive.json"
LOCAL_DATA = PROJECT_ROOT / "assets" / "pulluk" / "data.js"
BRIEF_BASE_URL = "https://hanwool-choi.github.io/willy-content-engine/brief"
SUMMARY_URL = "https://map.naver.com/p/api/place/summary/{sid}"


def _parse_data_js(text: str) -> dict:
    return json.loads(text[text.index("=") + 1:].rstrip().rstrip(";"))


def load_data() -> dict:
    """gh-pages 최신본 → 커밋본 순으로 시도한다."""
    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.get(DATA_URL)
        if response.status_code == 200:
            return _parse_data_js(response.text)
    except Exception:
        pass
    return _parse_data_js(LOCAL_DATA.read_text(encoding="utf-8"))


def load_archive() -> list[dict]:
    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.get(ARCHIVE_URL)
        if response.status_code == 200:
            return list(response.json())
    except Exception:
        pass
    return []


def today_rainy(day: date) -> bool:
    """KMA 단기예보. 실패하면 비가 안 온다고 보고 로테이션을 그대로 간다."""
    key = os.getenv("KMA_SERVICE_KEY", "")
    if not key:
        return False
    try:
        from willy.weather.client import WeatherClient

        forecast = WeatherClient(key).get_week_forecast(day, days=1)
        return bool(forecast and forecast[0].is_rainy)
    except Exception:
        return False


def run(data: dict, archive: list[dict], day: date, rainy: bool,
        api_key: str | None, out_dir: Path) -> dict:
    """기획 → 초안 → 페이지 → 아카이브. 네트워크 전송은 하지 않는다."""
    plan = plan_for(data, archive, day, rainy)
    draft, source = compose(plan, api_key)
    checks = checklist(plan)

    out_dir.mkdir(parents=True, exist_ok=True)
    html = render_brief(plan, draft, checks, day, source)
    (out_dir / f"{day.isoformat()}.html").write_text(html, encoding="utf-8")
    (out_dir / "latest.html").write_text(html, encoding="utf-8")

    record = {
        "date": day.isoformat(),
        "kind": plan.kind,
        "topic": plan.topic,
        "title": plan.title,
        "places": [p.get("name") for p in plan.places],
        "deep": (plan.deep or {}).get("name"),
        "source": source,
    }
    merged = [record] + [e for e in archive if e.get("date") != record["date"]]
    merged.sort(key=lambda e: e.get("date", ""), reverse=True)
    (out_dir / "archive.json").write_text(
        json.dumps(merged, ensure_ascii=False, indent=1), encoding="utf-8")
    (out_dir / "index.html").write_text(render_index(merged), encoding="utf-8")

    head = [line for line in draft.split("\n") if line.strip()][:2]
    return {"plan": plan, "draft": draft, "source": source, "record": record,
            "summary": " ".join(head)[:150]}


def place_image_url(place: dict, http: httpx.Client) -> str | None:
    """플레이스 요약 API의 대표 사진. 없거나 실패하면 None(이미지 없이 보낸다)."""
    sid = place.get("sid")
    if not sid:
        return None
    try:
        response = http.get(SUMMARY_URL.format(sid=sid),
                            headers={"Referer": "https://map.naver.com/"})
        if response.status_code != 200:
            return None
        detail = (response.json().get("data") or {}).get("placeDetail") or {}
        images = (detail.get("images") or {}).get("images") or []
        return images[0].get("origin") if images else None
    except Exception:
        return None


def _send_kakao(result: dict, day: date) -> None:
    rest_key = os.getenv("KAKAO_REST_API_KEY", "")
    refresh = os.getenv("KAKAO_REFRESH_TOKEN", "")
    if not (rest_key and refresh):
        print("카카오 키가 없어 전송을 건너뛴다", file=sys.stderr)
        return

    plan = result["plan"]
    link = f"{BRIEF_BASE_URL}/{day.isoformat()}.html"

    with httpx.Client(timeout=30.0) as client:
        # 집중분석 대상 사진을 우선 쓰고, 없으면 코스 첫 장소로 넘어간다.
        image_url = None
        for candidate in [plan.deep] + list(plan.places):
            if not candidate:
                continue
            image_url = place_image_url(candidate, client)
            if image_url:
                break

        access, rotated = refresh_access_token(rest_key, refresh, client)
        sent = send_brief(client, access,
                          title=f"🚩 {day.isoformat()} {plan.title}",
                          summary=result["summary"], body=result["draft"],
                          link_url=link, image_url=image_url)
    print(f"카톡 {sent}통 전송 완료")
    if rotated:
        Path("new_refresh_token.txt").write_text(rotated, encoding="utf-8")
        print("리프레시 토큰이 갱신됐다 — 시크릿을 업데이트해야 한다")


def main() -> None:
    parser = argparse.ArgumentParser(description="최펄럭 데일리 브리핑")
    parser.add_argument("--out", default="out_brief", help="출력 디렉터리")
    parser.add_argument("--dry-run", action="store_true", help="카톡 전송 없이 생성만")
    parser.add_argument("--date", help="기준일 (YYYY-MM-DD, 기본: 오늘 KST)")
    args = parser.parse_args()

    day = (datetime.strptime(args.date, "%Y-%m-%d").date() if args.date
           else datetime.now(KST).date())
    data = load_data()
    archive = load_archive()
    rainy = today_rainy(day)

    result = run(data, archive, day, rainy, os.getenv("GEMINI_API_KEY"), Path(args.out))
    print(f"기획: [{result['record']['kind']}] {result['record']['title']} "
          f"({result['source']}, 장소 {len(result['record']['places'])}곳, 비={rainy})")

    if args.dry_run:
        print("--dry-run이라 전송하지 않는다")
        return
    try:
        _send_kakao(result, day)
    except KakaoError as exc:
        print(f"카톡 전송 실패: {exc}", file=sys.stderr)
        raise


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
```

- [ ] **Step 4: 테스트가 통과하는지 확인한다**

Run: `C:\venvs\willy\Scripts\python.exe -m pytest tests/test_pulluk_brief.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: 실제 데이터로 한 번 돌려본다**

Run: `C:\venvs\willy\Scripts\python.exe tools/pulluk_brief.py --out C:\Temp\claude\brief_test --dry-run`
Expected: `기획: [...] ... (template 또는 ai, 장소 N곳, 비=False)` 출력, `C:\Temp\claude\brief_test\latest.html` 생성

- [ ] **Step 6: 전체 테스트가 깨지지 않았는지 확인한다**

Run: `C:\venvs\willy\Scripts\python.exe -m pytest -q`
Expected: 기존 테스트 포함 전부 PASS

- [ ] **Step 7: 커밋한다**

```bash
git add tools/pulluk_brief.py tests/test_pulluk_brief.py
git commit -m "feat: 데일리 브리핑 진입점 (데이터 적재·발행·전송 오케스트레이션)"
```

---

### Task 6: 토큰 발급 스크립트 · 워크플로 · 사용 문서

**Files:**
- Create: `tools/kakao_token_setup.py`, `.github/workflows/pulluk-brief.yml`
- Modify: `docs/superpowers/specs/2026-08-26-pulluk-daily-brief-design.md` (§10에 실제 실행 명령 추가)

**Interfaces:**
- Consumes: Task 3의 `TOKEN_URL`
- Produces: 사용자가 실행하는 CLI (`python tools/kakao_token_setup.py`), 09:00 KST 크론 워크플로

- [ ] **Step 1: 토큰 발급 스크립트를 만든다**

```python
# tools/kakao_token_setup.py
# -*- coding: utf-8 -*-
"""카카오 리프레시 토큰 1회 발급 (사용자가 직접 실행).

    python tools/kakao_token_setup.py --rest-key <REST_API_KEY>

카카오 로그인은 브라우저에서 본인이 해야 한다. 이 스크립트는 인가 코드를
받아 토큰으로 바꿔주기만 하고, 토큰을 저장소에 쓰지 않는다.
"""
from __future__ import annotations

import argparse
import sys
import urllib.parse

import truststore

truststore.inject_into_ssl()

import httpx  # noqa: E402

REDIRECT_URI = "https://localhost:3000/oauth"
AUTH_URL = "https://kauth.kakao.com/oauth/authorize"
TOKEN_URL = "https://kauth.kakao.com/oauth/token"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rest-key", required=True, help="카카오 앱의 REST API 키")
    parser.add_argument("--redirect-uri", default=REDIRECT_URI,
                        help="카카오 앱에 등록한 Redirect URI")
    args = parser.parse_args()

    query = urllib.parse.urlencode({
        "client_id": args.rest_key,
        "redirect_uri": args.redirect_uri,
        "response_type": "code",
        "scope": "talk_message",
    })
    print("\n1) 아래 주소를 브라우저에 붙여넣고 카카오 로그인·동의를 진행하세요.\n")
    print(f"   {AUTH_URL}?{query}\n")
    print("2) 이동한 주소창의 code= 뒤 값을 복사해 붙여넣으세요.")
    print("   (페이지가 안 열려도 주소창에 code= 값은 들어 있습니다)\n")
    code = input("code: ").strip()

    with httpx.Client(timeout=30.0) as client:
        response = client.post(TOKEN_URL, data={
            "grant_type": "authorization_code",
            "client_id": args.rest_key,
            "redirect_uri": args.redirect_uri,
            "code": code,
        })
    if response.status_code != 200:
        print(f"\n실패: HTTP {response.status_code} {response.text[:300]}", file=sys.stderr)
        raise SystemExit(1)

    body = response.json()
    print("\n발급 완료. 아래 값을 GitHub Secrets에 넣으세요.\n")
    print(f"  KAKAO_REST_API_KEY = {args.rest_key}")
    print(f"  KAKAO_REFRESH_TOKEN = {body.get('refresh_token')}\n")
    print("이 값은 화면에만 출력되며 저장소에 저장되지 않습니다.")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
```

- [ ] **Step 2: 스크립트가 인자 없이도 안전하게 죽는지 본다**

Run: `C:\venvs\willy\Scripts\python.exe tools/kakao_token_setup.py`
Expected: `error: the following arguments are required: --rest-key` (exit code 2)

- [ ] **Step 3: 워크플로를 만든다**

```yaml
# .github/workflows/pulluk-brief.yml
name: 펄럭 데일리 브리핑

# 매일 09:00 KST. 즐겨찾기 갱신(06:20)이 끝난 뒤라 최신 데이터를 쓴다.
on:
  schedule:
    - cron: "0 0 * * *"
  workflow_dispatch:

permissions:
  contents: write
  issues: write

# 데일리 보드·스튜디오와 gh-pages 푸시가 겹치지 않게 한다.
concurrency:
  group: pages
  cancel-in-progress: false

jobs:
  brief:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: 의존성 설치
        run: pip install httpx truststore

      - name: 브리핑 생성 및 카톡 전송
        env:
          KAKAO_REST_API_KEY: ${{ secrets.KAKAO_REST_API_KEY }}
          KAKAO_REFRESH_TOKEN: ${{ secrets.KAKAO_REFRESH_TOKEN }}
          GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}
          KMA_SERVICE_KEY: ${{ secrets.KMA_SERVICE_KEY }}
        run: python tools/pulluk_brief.py --out out_brief

      # 카카오는 리프레시 토큰 잔여 1개월 미만일 때만 새 토큰을 준다.
      # 그때 시크릿을 갱신하지 않으면 2개월 뒤 전송이 끊긴다.
      - name: 리프레시 토큰 회전
        if: ${{ hashFiles('new_refresh_token.txt') != '' }}
        env:
          GH_TOKEN: ${{ secrets.GH_PAT_SECRETS }}
        run: gh secret set KAKAO_REFRESH_TOKEN < new_refresh_token.txt

      - name: gh-pages /brief 게시
        uses: peaceiris/actions-gh-pages@v4
        with:
          github_token: ${{ secrets.GITHUB_TOKEN }}
          publish_dir: out_brief
          destination_dir: brief
          publish_branch: gh-pages
          keep_files: true
          commit_message: "publish: 데일리 브리핑"

      - name: 실패 알림 이슈
        if: failure()
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: |
          gh issue create \
            --title "데일리 브리핑 실패 ($(date -u +%Y-%m-%d))" \
            --body "워크플로 실행이 실패했습니다. 카카오 토큰 만료(KOE322)일 수 있으니 tools/kakao_token_setup.py로 재발급 후 KAKAO_REFRESH_TOKEN 시크릿을 갱신하세요. 로그: ${{ github.server_url }}/${{ github.repository }}/actions/runs/${{ github.run_id }}"
```

- [ ] **Step 4: 워크플로 YAML이 유효한지 확인한다**

Run: `C:\venvs\willy\Scripts\python.exe -c "import yaml,sys; yaml.safe_load(open('.github/workflows/pulluk-brief.yml',encoding='utf-8')); print('ok')"`
Expected: `ok`

- [ ] **Step 5: 설계 문서 §10에 실제 명령을 채운다**

`docs/superpowers/specs/2026-08-26-pulluk-daily-brief-design.md`의 §10 3번 항목을 아래로 교체한다.

```markdown
3. `C:\venvs\willy\Scripts\python.exe tools/kakao_token_setup.py --rest-key <REST_API_KEY>` 실행
   → 출력된 주소로 로그인·동의 → 주소창의 `code=` 값 붙여넣기 → refresh token 출력
4. GitHub Secrets 등록: `KAKAO_REST_API_KEY`, `KAKAO_REFRESH_TOKEN`,
   그리고 토큰 자동 회전용 `GH_PAT_SECRETS` (fine-grained PAT, 이 저장소의 Secrets 쓰기 권한)
```

- [ ] **Step 6: 커밋한다**

```bash
git add tools/kakao_token_setup.py .github/workflows/pulluk-brief.yml docs/superpowers/specs/2026-08-26-pulluk-daily-brief-design.md
git commit -m "feat: 브리핑 워크플로와 카카오 토큰 발급 스크립트"
```

- [ ] **Step 7: 푸시한다**

```bash
git push origin HEAD:refs/heads/main
```

---

## 완료 후 사용자 확인 사항

1. 카카오 개발자 앱 생성 → `talk_message` 동의항목 활성화 → 토큰 발급 (Task 6 스크립트)
2. GitHub Secrets 3종 등록 (`KAKAO_REST_API_KEY`, `KAKAO_REFRESH_TOKEN`, `GH_PAT_SECRETS`)
3. Actions 탭에서 "펄럭 데일리 브리핑" 수동 실행 → 카톡 3통 도착 확인
4. 다음 날 09:00 KST 자동 실행 확인
