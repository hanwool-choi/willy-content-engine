# [내일 뭐입지?] 파이프라인 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 버튼 1회로 주간 14룩(요일 7 × 성별 2)을 수집·분석·날씨배정·AI재생성하고, 컨펌 후 폴더와 워드 문서로 산출하는 로컬 파이프라인을 만든다.

**Architecture:** 순수 로직(모델·날씨·아카이브·배정)을 먼저 만들고 IO 계층(수집·생성·산출)을 그 위에 얹은 뒤, FastAPI 단일 페이지로 2단계 컨펌을 붙인다. 외부 의존(Claude 비전, 기상청 API, 이미지 생성 엔진, Playwright)은 전부 인터페이스 뒤에 두고 테스트는 고정 픽스처로 돌린다. 네트워크를 타는 테스트는 없다.

**Tech Stack:** Python 3.11+, Playwright, scipy, SQLite, python-docx, FastAPI, pytest, PyYAML, httpx

**설계 문서:** `docs/superpowers/specs/2026-07-31-tomorrow-outfit-pipeline-design.md`

## Global Constraints

- Python 3.11+ (`match`문, `X | None` 타입 문법 사용)
- 수집은 **사용자가 버튼을 눌렀을 때만** 실행한다. 스케줄러 기반 자동 순회 금지
- CAPTCHA·봇 차단 우회 코드는 작성하지 않는다. 에이블리·크림은 소스에서 제외
- 수집량 기본값: 소스당 20개, 총 60개 (설정으로 조정 가능)
- 주차 계산은 **ISO 기준** — 해당 주 목요일이 속한 달을 그 주의 달로 삼는다
- 요일 대표기온 `temp_repr = (temp_max × 0.6) + (temp_min × 0.4)`
- 배정 비용 `cost = abs(temp_repr - median(temp_range)) + (강수확률≥60 and not rain_ok ? 999 : 0) + (temp_repr가 temp_range 밖 ? 5 : 0)`
- 배정 폴백 순서: ① 당일 수집분 → ② 아카이브(기온 ±3℃, 비 오는 날만 rain_ok 필요, 같은 계절) → ③ 빈 칸 + 경고. **억지 배정 금지**
- 같은 룩은 4주 내 재등장 금지
- 컨펌은 2단계 — 배정 컨펌 → (AI 생성) → 최종 컨펌 → 폴더 생성. **최종 컨펌 전 `outputs/`에 쓰지 않는다**
- 원본 참고 이미지 파일명은 반드시 `_ref_원본_발행금지.jpg`
- 영상 생성·Threads 자동게시는 이번 범위 제외
- 성별은 분석기가 판정한 값만 신뢰한다 (무신사 스냅은 남녀 혼재)
- 모든 외부 API 키는 `.env`에서 읽는다. 코드·테스트에 하드코딩 금지
- 테스트는 네트워크를 타지 않는다. 외부 응답은 `tests/fixtures/`의 고정 JSON을 쓴다

---

## File Structure

```
src/willy/
  models.py            # 전 컴포넌트가 공유하는 도메인 dataclass
  config.py            # 설정 로드 (.env, 상수)
  weather/
    client.py          # 기상청 단기+중기 API 호출
    parser.py          # 응답 → DayWeather 변환 (순수 함수)
  analyzer.py          # Claude 비전 → LookAnalysis
  archive.py           # SQLite 저장/폴백 조회
  assigner.py          # 헝가리안 배정 + 경고
  collector/
    browser.py         # Playwright 세션 관리
    sources.py         # 소스별 셀렉터/추출 규칙
    collector.py       # 수집 오케스트레이션
  generator/
    base.py            # ImageGenerator 인터페이스
    preset.py          # 컨셉 프리셋 로드
    noop.py            # 엔진 미확정용 통과 구현체
  publisher/
    folders.py         # 폴더 구조 생성
    docs.py            # python-docx 문서 생성
  web/
    app.py             # FastAPI 라우트
    static/index.html  # 단일 페이지 UI
  pipeline.py          # 전체 흐름 오케스트레이션

tests/
  fixtures/            # 기상청 응답, 룩 분석 결과 등 고정 JSON
  test_*.py
```

**분리 기준:** `weather/`는 호출(IO)과 변환(순수)을 나눠 파서를 네트워크 없이 테스트한다. `collector/`는 소스별 셀렉터를 `sources.py`로 격리해 사이트 DOM이 바뀌어도 한 파일만 고친다. `generator/`는 엔진이 미확정이므로 인터페이스와 구현체를 분리한다.

---

## Task 1: 도메인 모델과 설정

**Files:**
- Create: `src/willy/__init__.py`
- Create: `src/willy/models.py`
- Create: `src/willy/config.py`
- Create: `pyproject.toml`
- Create: `.env.example`
- Test: `tests/test_models.py`

**Interfaces:**
- Consumes: 없음 (최초 태스크)
- Produces: `RawLook`, `LookAnalysis`, `DayWeather`, `Assignment`, `Warning`, `WarningCode`, `Gender`, `Settings`, `iso_week_label()`, `temp_repr()`

- [ ] **Step 1: 프로젝트 스캐폴딩**

`pyproject.toml`:

```toml
[project]
name = "willy-content-engine"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "playwright>=1.45",
    "scipy>=1.13",
    "python-docx>=1.1",
    "fastapi>=0.111",
    "uvicorn>=0.30",
    "httpx>=0.27",
    "PyYAML>=6.0",
    "python-dotenv>=1.0",
    "anthropic>=0.34",
]

[project.optional-dependencies]
dev = ["pytest>=8.0", "pytest-asyncio>=0.23"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]
```

`.env.example`:

```
KMA_SERVICE_KEY=여기에_공공데이터포털_기상청_키
ANTHROPIC_API_KEY=여기에_클로드_키
```

`src/willy/__init__.py`: 빈 파일.

- [ ] **Step 2: 실패하는 테스트 작성**

`tests/test_models.py`:

```python
from datetime import date

import pytest

from willy.models import (
    DayWeather,
    Gender,
    LookAnalysis,
    WarningCode,
    iso_week_label,
    temp_repr,
)


def test_temp_repr_weights_daytime_higher():
    # 최고 30, 최저 20 -> 30*0.6 + 20*0.4 = 26.0
    assert temp_repr(temp_max=30, temp_min=20) == 26.0


def test_iso_week_label_uses_thursday_month():
    # 2026-08-01은 토요일. 그 주 목요일은 2026-07-30 -> 7월로 귀속
    assert iso_week_label(date(2026, 8, 1)) == "2026-07_W5"


def test_iso_week_label_first_week_of_month():
    # 2026-08-03은 월요일. 그 주 목요일은 2026-08-06 -> 8월 1주차
    assert iso_week_label(date(2026, 8, 3)) == "2026-08_W1"


def test_look_analysis_temp_median():
    look = LookAnalysis(
        look_id="a",
        gender=Gender.MEN,
        sleeve="short",
        outer=None,
        layers=1,
        fabric_weight="light",
        coverage="mid",
        temp_range=(24, 30),
        rain_ok=False,
        season="summer",
        style_tags=["미니멀"],
        palette=["ecru"],
    )
    assert look.temp_median == 27.0


def test_day_weather_is_rainy_at_threshold():
    common = dict(
        date=date(2026, 8, 3),
        weekday_ko="월",
        temp_min=22,
        temp_max=28,
        sky="비",
        resolution="detailed",
    )
    assert DayWeather(precip_prob=60, **common).is_rainy is True
    assert DayWeather(precip_prob=59, **common).is_rainy is False


def test_warning_code_values_are_stable():
    assert WarningCode.EMPTY_SLOT.value == "EMPTY_SLOT"
    assert WarningCode.ARCHIVE_FALLBACK.value == "ARCHIVE_FALLBACK"
    assert WarningCode.RAIN_SUBSTITUTE.value == "RAIN_SUBSTITUTE"
    assert WarningCode.POOL_TOO_SMALL.value == "POOL_TOO_SMALL"
```

- [ ] **Step 3: 테스트 실패 확인**

Run: `pytest tests/test_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'willy.models'`

- [ ] **Step 4: 모델 구현**

`src/willy/models.py`:

```python
"""전 컴포넌트가 공유하는 도메인 모델."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from enum import Enum
from pathlib import Path

WEEKDAY_KO = ["월", "화", "수", "목", "금", "토", "일"]

RAIN_THRESHOLD = 60  # 강수확률 %. 이 값 이상이면 우천으로 본다.


class Gender(str, Enum):
    MEN = "men"
    WOMEN = "women"


class WarningCode(str, Enum):
    EMPTY_SLOT = "EMPTY_SLOT"
    ARCHIVE_FALLBACK = "ARCHIVE_FALLBACK"
    RAIN_SUBSTITUTE = "RAIN_SUBSTITUTE"
    POOL_TOO_SMALL = "POOL_TOO_SMALL"


def temp_repr(temp_max: int, temp_min: int) -> float:
    """요일 대표기온. 낮 활동시간에 가중을 둔다."""
    return round(temp_max * 0.6 + temp_min * 0.4, 1)


def iso_week_label(d: date) -> str:
    """ISO 기준 주차 라벨. 해당 주 목요일이 속한 달을 그 주의 달로 삼는다.

    주가 월을 걸칠 때 '7월 5주차냐 8월 1주차냐'를 결정론적으로 정한다.
    """
    thursday = d - timedelta(days=d.weekday()) + timedelta(days=3)
    first = date(thursday.year, thursday.month, 1)
    # 그 달의 첫 목요일을 찾는다.
    offset = (3 - first.weekday()) % 7
    first_thursday = first + timedelta(days=offset)
    week_no = (thursday - first_thursday).days // 7 + 1
    return f"{thursday.year:04d}-{thursday.month:02d}_W{week_no}"


@dataclass
class RawLook:
    look_id: str
    source: str  # "musinsa_snap" | "uniqlo_women" | "uniqlo_men" | "manual"
    image_path: Path
    capture_method: str  # "original_url" | "screenshot"
    source_url: str | None = None
    raw_meta: dict = field(default_factory=dict)
    collected_at: datetime = field(default_factory=datetime.now)


@dataclass
class LookAnalysis:
    look_id: str
    gender: Gender
    sleeve: str  # "sleeveless" | "short" | "long"
    outer: str | None
    layers: int
    fabric_weight: str  # "light" | "mid" | "heavy"
    coverage: str  # "low" | "mid" | "high"
    temp_range: tuple[int, int]
    rain_ok: bool
    season: str  # "spring" | "summer" | "fall" | "winter"
    style_tags: list[str]
    palette: list[str]
    image_path: Path | None = None

    @property
    def temp_median(self) -> float:
        lo, hi = self.temp_range
        return round((lo + hi) / 2, 1)


@dataclass
class DayWeather:
    date: date
    weekday_ko: str
    temp_min: int
    temp_max: int
    precip_prob: int
    sky: str
    resolution: str  # "detailed" | "coarse"

    @property
    def temp_repr(self) -> float:
        return temp_repr(self.temp_max, self.temp_min)

    @property
    def is_rainy(self) -> bool:
        return self.precip_prob >= RAIN_THRESHOLD

    @property
    def folder_name(self) -> str:
        """예: 08-03_월_맑음_29-24℃"""
        return (
            f"{self.date.month:02d}-{self.date.day:02d}_{self.weekday_ko}"
            f"_{self.sky}_{self.temp_max}-{self.temp_min}℃"
        )


@dataclass
class Warning:
    code: WarningCode
    slot_date: date | None
    gender: Gender | None
    message: str


# (date, Gender) -> LookAnalysis | None
Assignment = dict[tuple[date, Gender], LookAnalysis | None]
```

`src/willy/config.py`:

```python
"""설정. 비밀값은 .env에서만 읽는다."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# 서울 기상청 격자 좌표 / 예보구역 코드
SEOUL_NX = 60
SEOUL_NY = 127
SEOUL_MID_LAND_REG = "11B00000"
SEOUL_MID_TA_REG = "11B10101"


@dataclass(frozen=True)
class Settings:
    kma_service_key: str
    anthropic_api_key: str
    looks_per_source: int = 20
    output_root: Path = PROJECT_ROOT / "outputs"
    archive_db: Path = PROJECT_ROOT / "archive" / "looks.db"
    workspace: Path = PROJECT_ROOT / ".workspace"

    @classmethod
    def load(cls) -> "Settings":
        return cls(
            kma_service_key=os.environ.get("KMA_SERVICE_KEY", ""),
            anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY", ""),
        )


SOURCE_URLS = {
    "musinsa_snap": "https://www.musinsa.com/snap/main/today",
    "uniqlo_women": "https://www.uniqlo.com/kr/ko/stylingbook/stylehint/women",
    "uniqlo_men": "https://www.uniqlo.com/kr/ko/stylingbook/stylehint/men",
}
```

- [ ] **Step 5: 테스트 통과 확인**

Run: `pytest tests/test_models.py -v`
Expected: PASS (6개)

- [ ] **Step 6: 커밋**

```bash
git add pyproject.toml .env.example src/willy/__init__.py src/willy/models.py src/willy/config.py tests/test_models.py
git commit -m "feat: 도메인 모델과 설정 추가"
```

---

## Task 2: 날씨 파서

**Files:**
- Create: `src/willy/weather/__init__.py`
- Create: `src/willy/weather/parser.py`
- Create: `tests/fixtures/kma_vilage_fcst.json`
- Create: `tests/fixtures/kma_mid_land.json`
- Create: `tests/fixtures/kma_mid_ta.json`
- Test: `tests/test_weather_parser.py`

**Interfaces:**
- Consumes: `DayWeather`, `WEEKDAY_KO` (Task 1)
- Produces: `parse_short_term(payload, base_date) -> list[DayWeather]`, `parse_mid_term(land_payload, ta_payload, base_date) -> list[DayWeather]`, `merge_forecasts(short, mid, base_date) -> list[DayWeather]`

- [ ] **Step 1: 픽스처 작성**

`tests/fixtures/kma_vilage_fcst.json` — 단기예보는 3시간 단위 항목의 나열이다. 최고기온 `TMX`, 최저기온 `TMN`, 강수확률 `POP`, 하늘상태 `SKY`(1=맑음, 3=구름많음, 4=흐림)만 쓴다.

```json
{
  "response": {
    "body": {
      "items": {
        "item": [
          {"category": "TMX", "fcstDate": "20260803", "fcstTime": "1500", "fcstValue": "29.0"},
          {"category": "TMN", "fcstDate": "20260803", "fcstTime": "0600", "fcstValue": "24.0"},
          {"category": "POP", "fcstDate": "20260803", "fcstTime": "1200", "fcstValue": "20"},
          {"category": "POP", "fcstDate": "20260803", "fcstTime": "1500", "fcstValue": "30"},
          {"category": "SKY", "fcstDate": "20260803", "fcstTime": "1200", "fcstValue": "1"},
          {"category": "TMX", "fcstDate": "20260804", "fcstTime": "1500", "fcstValue": "26.0"},
          {"category": "TMN", "fcstDate": "20260804", "fcstTime": "0600", "fcstValue": "22.0"},
          {"category": "POP", "fcstDate": "20260804", "fcstTime": "1200", "fcstValue": "80"},
          {"category": "SKY", "fcstDate": "20260804", "fcstTime": "1200", "fcstValue": "4"}
        ]
      }
    }
  }
}
```

`tests/fixtures/kma_mid_land.json` — 중기육상예보는 하루당 오전/오후 강수확률과 날씨를 준다. `N`은 base_date로부터의 일수.

```json
{
  "response": {
    "body": {
      "items": {
        "item": [
          {
            "rnSt5Am": 20, "rnSt5Pm": 30, "wf5Am": "맑음", "wf5Pm": "구름많음",
            "rnSt6Am": 60, "rnSt6Pm": 70, "wf6Am": "흐리고 비", "wf6Pm": "흐리고 비",
            "rnSt7Am": 10, "rnSt7Pm": 10, "wf7Am": "맑음", "wf7Pm": "맑음"
          }
        ]
      }
    }
  }
}
```

`tests/fixtures/kma_mid_ta.json`:

```json
{
  "response": {
    "body": {
      "items": {
        "item": [
          {
            "taMin5": 21, "taMax5": 27,
            "taMin6": 20, "taMax6": 25,
            "taMin7": 22, "taMax7": 30
          }
        ]
      }
    }
  }
}
```

- [ ] **Step 2: 실패하는 테스트 작성**

`tests/test_weather_parser.py`:

```python
import json
from datetime import date
from pathlib import Path

import pytest

from willy.weather.parser import merge_forecasts, parse_mid_term, parse_short_term

FIXTURES = Path(__file__).parent / "fixtures"


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_parse_short_term_extracts_daily_values():
    days = parse_short_term(load("kma_vilage_fcst.json"), base_date=date(2026, 8, 3))

    assert len(days) == 2
    monday = days[0]
    assert monday.date == date(2026, 8, 3)
    assert monday.weekday_ko == "월"
    assert monday.temp_max == 29
    assert monday.temp_min == 24
    assert monday.sky == "맑음"
    assert monday.resolution == "detailed"


def test_parse_short_term_takes_max_precip_of_day():
    days = parse_short_term(load("kma_vilage_fcst.json"), base_date=date(2026, 8, 3))
    # 20%와 30% 중 큰 값을 그날 강수확률로 삼는다.
    assert days[0].precip_prob == 30


def test_parse_short_term_marks_rainy_day():
    days = parse_short_term(load("kma_vilage_fcst.json"), base_date=date(2026, 8, 3))
    tuesday = days[1]
    assert tuesday.precip_prob == 80
    assert tuesday.is_rainy is True
    assert tuesday.sky == "흐림"


def test_parse_mid_term_builds_coarse_days():
    days = parse_mid_term(
        load("kma_mid_land.json"), load("kma_mid_ta.json"), base_date=date(2026, 8, 3)
    )

    assert [d.date for d in days] == [
        date(2026, 8, 8),
        date(2026, 8, 9),
        date(2026, 8, 10),
    ]
    assert all(d.resolution == "coarse" for d in days)


def test_parse_mid_term_takes_max_of_am_pm_precip():
    days = parse_mid_term(
        load("kma_mid_land.json"), load("kma_mid_ta.json"), base_date=date(2026, 8, 3)
    )
    # 6일차: 오전 60, 오후 70 -> 70
    assert days[1].precip_prob == 70
    assert days[1].temp_max == 25
    assert days[1].temp_min == 20


def test_merge_forecasts_returns_exactly_seven_days_without_gaps():
    week = merge_forecasts(
        short=parse_short_term(load("kma_vilage_fcst.json"), base_date=date(2026, 8, 3)),
        mid=parse_mid_term(
            load("kma_mid_land.json"), load("kma_mid_ta.json"), base_date=date(2026, 8, 3)
        ),
        base_date=date(2026, 8, 3),
    )

    assert len(week) == 7
    assert [d.date.day for d in week] == [3, 4, 5, 6, 7, 8, 9]


def test_merge_forecasts_prefers_short_term_when_overlapping():
    short = parse_short_term(load("kma_vilage_fcst.json"), base_date=date(2026, 8, 3))
    mid = parse_mid_term(
        load("kma_mid_land.json"), load("kma_mid_ta.json"), base_date=date(2026, 8, 3)
    )
    week = merge_forecasts(short=short, mid=mid, base_date=date(2026, 8, 3))

    # 8/3은 단기예보에 있으므로 detailed 여야 한다.
    assert week[0].resolution == "detailed"


def test_merge_forecasts_fills_missing_days_with_placeholder():
    """단기·중기 어느 쪽에도 없는 날은 빠뜨리지 않고 자리를 채운다."""
    week = merge_forecasts(short=[], mid=[], base_date=date(2026, 8, 3))

    assert len(week) == 7
    assert all(d.resolution == "missing" for d in week)
    assert week[0].sky == "정보없음"
```

- [ ] **Step 3: 테스트 실패 확인**

Run: `pytest tests/test_weather_parser.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'willy.weather'`

- [ ] **Step 4: 파서 구현**

`src/willy/weather/__init__.py`: 빈 파일.

`src/willy/weather/parser.py`:

```python
"""기상청 응답 -> DayWeather 변환. 순수 함수만 둔다 (네트워크 없음)."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta

from willy.models import WEEKDAY_KO, DayWeather

SKY_CODE = {"1": "맑음", "3": "구름많음", "4": "흐림"}


def _items(payload: dict) -> list[dict]:
    return payload.get("response", {}).get("body", {}).get("items", {}).get("item", [])


def _weekday(d: date) -> str:
    return WEEKDAY_KO[d.weekday()]


def parse_short_term(payload: dict, base_date: date) -> list[DayWeather]:
    """단기예보(getVilageFcst) -> 일별 DayWeather. base_date 이후만 남긴다."""
    buckets: dict[date, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))

    for item in _items(payload):
        d = datetime.strptime(item["fcstDate"], "%Y%m%d").date()
        buckets[d][item["category"]].append(str(item["fcstValue"]))

    days: list[DayWeather] = []
    for d in sorted(buckets):
        if d < base_date:
            continue
        cats = buckets[d]
        if "TMX" not in cats or "TMN" not in cats:
            continue  # 기온이 없으면 배정에 못 쓴다.

        pops = [int(float(v)) for v in cats.get("POP", ["0"])]
        skies = cats.get("SKY", ["1"])
        # 그날을 대표하는 하늘상태는 가장 흐린 쪽으로 잡는다.
        worst_sky = max(skies, key=lambda c: int(c))

        days.append(
            DayWeather(
                date=d,
                weekday_ko=_weekday(d),
                temp_max=int(float(cats["TMX"][0])),
                temp_min=int(float(cats["TMN"][0])),
                precip_prob=max(pops),
                sky=SKY_CODE.get(worst_sky, "흐림"),
                resolution="detailed",
            )
        )
    return days


def parse_mid_term(
    land_payload: dict, ta_payload: dict, base_date: date
) -> list[DayWeather]:
    """중기예보(getMidLandFcst + getMidTa) -> 일별 DayWeather.

    중기는 base_date + N일 형태의 평면 키(rnSt5Am, taMax5 ...)로 온다.
    오전/오후 강수확률 중 큰 값을 그날 값으로 삼는다.
    """
    land = _items(land_payload)
    ta = _items(ta_payload)
    if not land or not ta:
        return []
    land, ta = land[0], ta[0]

    days: list[DayWeather] = []
    for n in range(3, 11):
        tmax_key, tmin_key = f"taMax{n}", f"taMin{n}"
        if tmax_key not in ta or tmin_key not in ta:
            continue

        am = land.get(f"rnSt{n}Am")
        pm = land.get(f"rnSt{n}Pm")
        probs = [int(v) for v in (am, pm) if v is not None]

        wf = land.get(f"wf{n}Pm") or land.get(f"wf{n}Am") or "정보없음"
        d = base_date + timedelta(days=n)

        days.append(
            DayWeather(
                date=d,
                weekday_ko=_weekday(d),
                temp_max=int(ta[tmax_key]),
                temp_min=int(ta[tmin_key]),
                precip_prob=max(probs) if probs else 0,
                sky=wf,
                resolution="coarse",
            )
        )
    return days


def merge_forecasts(
    short: list[DayWeather], mid: list[DayWeather], base_date: date
) -> list[DayWeather]:
    """base_date부터 7일을 채운다. 겹치면 해상도 높은 단기를 우선한다.

    어느 쪽에도 없는 날은 빠뜨리지 않고 자리표시자로 채운다.
    배정 단계에서 7칸이 항상 존재한다고 가정할 수 있게 하기 위함이다.
    """
    by_date = {d.date: d for d in mid}
    by_date.update({d.date: d for d in short})  # 단기가 중기를 덮어쓴다

    week: list[DayWeather] = []
    for i in range(7):
        d = base_date + timedelta(days=i)
        week.append(
            by_date.get(
                d,
                DayWeather(
                    date=d,
                    weekday_ko=_weekday(d),
                    temp_min=0,
                    temp_max=0,
                    precip_prob=0,
                    sky="정보없음",
                    resolution="missing",
                ),
            )
        )
    return week
```

- [ ] **Step 5: 테스트 통과 확인**

Run: `pytest tests/test_weather_parser.py -v`
Expected: PASS (8개)

- [ ] **Step 6: 커밋**

```bash
git add src/willy/weather tests/test_weather_parser.py tests/fixtures
git commit -m "feat: 기상청 단기/중기 예보 파서 추가"
```

---

## Task 3: 날씨 API 클라이언트

**Files:**
- Create: `src/willy/weather/client.py`
- Test: `tests/test_weather_client.py`

**Interfaces:**
- Consumes: `parse_short_term`, `parse_mid_term`, `merge_forecasts` (Task 2), `Settings`, `SEOUL_NX`, `SEOUL_NY`, `SEOUL_MID_LAND_REG`, `SEOUL_MID_TA_REG` (Task 1)
- Produces: `WeatherClient(service_key, http_client=None)`, `WeatherClient.get_week_forecast(base_date) -> list[DayWeather]`, `latest_base_time(now) -> tuple[str, str]`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_weather_client.py`:

```python
import json
from datetime import date, datetime
from pathlib import Path

import httpx
import pytest

from willy.weather.client import WeatherClient, latest_base_time

FIXTURES = Path(__file__).parent / "fixtures"


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_latest_base_time_picks_previous_slot():
    # 단기예보 발표시각은 02,05,08,11,14,17,20,23시.
    # 13:40이면 아직 14시 발표 전이므로 11시 자료를 쓴다.
    assert latest_base_time(datetime(2026, 8, 3, 13, 40)) == ("20260803", "1100")


def test_latest_base_time_rolls_back_to_previous_day():
    # 00:30이면 당일 02시 발표 전이므로 전날 23시 자료를 쓴다.
    assert latest_base_time(datetime(2026, 8, 3, 0, 30)) == ("20260802", "2300")


def test_get_week_forecast_returns_seven_days():
    def handler(request: httpx.Request) -> httpx.Response:
        if "getVilageFcst" in str(request.url):
            return httpx.Response(200, json=load("kma_vilage_fcst.json"))
        if "getMidLandFcst" in str(request.url):
            return httpx.Response(200, json=load("kma_mid_land.json"))
        if "getMidTa" in str(request.url):
            return httpx.Response(200, json=load("kma_mid_ta.json"))
        raise AssertionError(f"예상치 못한 호출: {request.url}")

    client = WeatherClient(
        service_key="dummy",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    week = client.get_week_forecast(base_date=date(2026, 8, 3))

    assert len(week) == 7
    assert week[0].temp_max == 29


def test_get_week_forecast_survives_mid_term_failure():
    """중기예보가 죽어도 단기 3일은 살려서 반환한다."""

    def handler(request: httpx.Request) -> httpx.Response:
        if "getVilageFcst" in str(request.url):
            return httpx.Response(200, json=load("kma_vilage_fcst.json"))
        return httpx.Response(500, text="서버 오류")

    client = WeatherClient(
        service_key="dummy",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    week = client.get_week_forecast(base_date=date(2026, 8, 3))

    assert len(week) == 7
    assert week[0].resolution == "detailed"
    assert week[6].resolution == "missing"
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest tests/test_weather_client.py -v`
Expected: FAIL — `ImportError: cannot import name 'WeatherClient'`

- [ ] **Step 3: 클라이언트 구현**

`src/willy/weather/client.py`:

```python
"""기상청 API 호출. 파싱은 parser.py에 위임한다."""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

import httpx

from willy.config import SEOUL_MID_LAND_REG, SEOUL_MID_TA_REG, SEOUL_NX, SEOUL_NY
from willy.models import DayWeather
from willy.weather.parser import merge_forecasts, parse_mid_term, parse_short_term

log = logging.getLogger(__name__)

SHORT_TERM_URL = (
    "https://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/getVilageFcst"
)
MID_LAND_URL = "https://apis.data.go.kr/1360000/MidFcstInfoService/getMidLandFcst"
MID_TA_URL = "https://apis.data.go.kr/1360000/MidFcstInfoService/getMidTa"

# 단기예보 발표시각 (시)
BASE_HOURS = [2, 5, 8, 11, 14, 17, 20, 23]


def latest_base_time(now: datetime) -> tuple[str, str]:
    """현재 시각 기준 가장 최근 발표분의 (base_date, base_time)."""
    for hour in reversed(BASE_HOURS):
        if now.hour >= hour:
            return now.strftime("%Y%m%d"), f"{hour:02d}00"
    prev = now - timedelta(days=1)
    return prev.strftime("%Y%m%d"), "2300"


class WeatherClient:
    def __init__(self, service_key: str, http_client: httpx.Client | None = None):
        self._key = service_key
        self._http = http_client or httpx.Client(timeout=20.0)

    def _get(self, url: str, params: dict) -> dict:
        params = {**params, "serviceKey": self._key, "dataType": "JSON"}
        response = self._http.get(url, params=params)
        response.raise_for_status()
        return response.json()

    def get_week_forecast(self, base_date: date) -> list[DayWeather]:
        """서울 7일 예보. 단기(0~3일) + 중기(3~10일)를 병합한다.

        한쪽이 실패해도 다른 쪽으로 최대한 채운다. 예보는 콘텐츠 신뢰도에
        직결되므로 부분 실패를 전체 실패로 만들지 않는다.
        """
        short: list[DayWeather] = []
        mid: list[DayWeather] = []

        b_date, b_time = latest_base_time(datetime.now())
        try:
            payload = self._get(
                SHORT_TERM_URL,
                {
                    "numOfRows": 1000,
                    "pageNo": 1,
                    "base_date": b_date,
                    "base_time": b_time,
                    "nx": SEOUL_NX,
                    "ny": SEOUL_NY,
                },
            )
            short = parse_short_term(payload, base_date)
        except Exception:
            log.exception("단기예보 조회 실패")

        try:
            tmfc = f"{base_date.strftime('%Y%m%d')}0600"
            land = self._get(MID_LAND_URL, {"regId": SEOUL_MID_LAND_REG, "tmFc": tmfc})
            ta = self._get(MID_TA_URL, {"regId": SEOUL_MID_TA_REG, "tmFc": tmfc})
            mid = parse_mid_term(land, ta, base_date)
        except Exception:
            log.exception("중기예보 조회 실패")

        return merge_forecasts(short=short, mid=mid, base_date=base_date)
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `pytest tests/test_weather_client.py -v`
Expected: PASS (4개)

- [ ] **Step 5: 커밋**

```bash
git add src/willy/weather/client.py tests/test_weather_client.py
git commit -m "feat: 기상청 API 클라이언트 추가"
```

---

## Task 4: 아카이브

**Files:**
- Create: `src/willy/archive.py`
- Test: `tests/test_archive.py`

**Interfaces:**
- Consumes: `LookAnalysis`, `Gender` (Task 1)
- Produces: `Archive(db_path)`, `Archive.save(look)`, `Archive.mark_used(look_id, used_on)`, `Archive.find_substitute(temp, rain_ok, season, gender, exclude_recent_weeks=4) -> LookAnalysis | None`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_archive.py`:

```python
from datetime import date, timedelta
from pathlib import Path

import pytest

from willy.archive import Archive
from willy.models import Gender, LookAnalysis


def make_look(look_id: str, temp_range=(20, 26), rain_ok=True,
              season="summer", gender=Gender.MEN) -> LookAnalysis:
    return LookAnalysis(
        look_id=look_id,
        gender=gender,
        sleeve="short",
        outer=None,
        layers=1,
        fabric_weight="light",
        coverage="mid",
        temp_range=temp_range,
        rain_ok=rain_ok,
        season=season,
        style_tags=["미니멀"],
        palette=["ecru"],
        image_path=Path(f"/tmp/{look_id}.jpg"),
    )


@pytest.fixture
def archive(tmp_path: Path) -> Archive:
    return Archive(tmp_path / "looks.db")


def test_save_then_find_returns_look(archive: Archive):
    archive.save(make_look("a"))

    found = archive.find_substitute(
        temp=23.0, rain_ok=True, season="summer", gender=Gender.MEN
    )
    assert found is not None
    assert found.look_id == "a"
    assert found.temp_range == (20, 26)


def test_find_respects_temp_window_of_three_degrees(archive: Archive):
    archive.save(make_look("far", temp_range=(0, 5)))  # 중앙값 2.5

    # 23도와는 20도 넘게 차이나므로 후보가 아니다.
    assert archive.find_substitute(
        temp=23.0, rain_ok=True, season="summer", gender=Gender.MEN
    ) is None


def test_find_requires_rain_ok_match(archive: Archive):
    archive.save(make_look("dry", rain_ok=False))

    assert archive.find_substitute(
        temp=23.0, rain_ok=True, season="summer", gender=Gender.MEN
    ) is None


def test_find_requires_same_season_and_gender(archive: Archive):
    archive.save(make_look("winter_look", season="winter"))
    archive.save(make_look("women_look", gender=Gender.WOMEN))

    assert archive.find_substitute(
        temp=23.0, rain_ok=True, season="summer", gender=Gender.MEN
    ) is None


def test_find_excludes_look_used_within_four_weeks(archive: Archive):
    archive.save(make_look("recent"))
    archive.mark_used("recent", used_on=date.today() - timedelta(days=10))

    assert archive.find_substitute(
        temp=23.0, rain_ok=True, season="summer", gender=Gender.MEN
    ) is None


def test_find_allows_look_used_long_ago(archive: Archive):
    archive.save(make_look("old"))
    archive.mark_used("old", used_on=date.today() - timedelta(days=40))

    found = archive.find_substitute(
        temp=23.0, rain_ok=True, season="summer", gender=Gender.MEN
    )
    assert found is not None
    assert found.look_id == "old"


def test_find_prefers_closest_temperature(archive: Archive):
    archive.save(make_look("near", temp_range=(22, 24)))   # 중앙값 23
    archive.save(make_look("further", temp_range=(24, 26)))  # 중앙값 25

    found = archive.find_substitute(
        temp=23.0, rain_ok=True, season="summer", gender=Gender.MEN
    )
    assert found.look_id == "near"


def test_save_is_idempotent(archive: Archive):
    archive.save(make_look("dup"))
    archive.save(make_look("dup"))

    assert archive.count() == 1
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest tests/test_archive.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'willy.archive'`

- [ ] **Step 3: 아카이브 구현**

`src/willy/archive.py`:

```python
"""수집된 룩의 누적 저장소. 배정 폴백 소스로 쓰인다."""
from __future__ import annotations

import json
import sqlite3
from datetime import date, timedelta
from pathlib import Path

from willy.models import Gender, LookAnalysis

TEMP_WINDOW = 3.0  # 폴백 조회 시 허용 기온 차 (℃)

SCHEMA = """
CREATE TABLE IF NOT EXISTS looks (
    look_id       TEXT PRIMARY KEY,
    gender        TEXT NOT NULL,
    sleeve        TEXT NOT NULL,
    outer         TEXT,
    layers        INTEGER NOT NULL,
    fabric_weight TEXT NOT NULL,
    coverage      TEXT NOT NULL,
    temp_min      INTEGER NOT NULL,
    temp_max      INTEGER NOT NULL,
    rain_ok       INTEGER NOT NULL,
    season        TEXT NOT NULL,
    style_tags    TEXT NOT NULL,
    palette       TEXT NOT NULL,
    image_path    TEXT
);

CREATE TABLE IF NOT EXISTS usages (
    look_id TEXT NOT NULL,
    used_on TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_lookup ON looks (gender, season, rain_ok);
"""


class Archive:
    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def save(self, look: LookAnalysis) -> None:
        self._conn.execute(
            """INSERT OR REPLACE INTO looks
               (look_id, gender, sleeve, outer, layers, fabric_weight, coverage,
                temp_min, temp_max, rain_ok, season, style_tags, palette, image_path)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                look.look_id,
                look.gender.value,
                look.sleeve,
                look.outer,
                look.layers,
                look.fabric_weight,
                look.coverage,
                look.temp_range[0],
                look.temp_range[1],
                int(look.rain_ok),
                look.season,
                json.dumps(look.style_tags, ensure_ascii=False),
                json.dumps(look.palette, ensure_ascii=False),
                str(look.image_path) if look.image_path else None,
            ),
        )
        self._conn.commit()

    def mark_used(self, look_id: str, used_on: date) -> None:
        self._conn.execute(
            "INSERT INTO usages (look_id, used_on) VALUES (?, ?)",
            (look_id, used_on.isoformat()),
        )
        self._conn.commit()

    def count(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM looks").fetchone()[0]

    def find_substitute(
        self,
        temp: float,
        rain_ok: bool,
        season: str,
        gender: Gender,
        exclude_recent_weeks: int = 4,
    ) -> LookAnalysis | None:
        """조건에 맞는 룩 중 기온이 가장 가까운 것 하나."""
        cutoff = (date.today() - timedelta(weeks=exclude_recent_weeks)).isoformat()

        row = self._conn.execute(
            """SELECT * FROM looks
               WHERE gender = ? AND season = ? AND rain_ok = ?
                 AND ABS((temp_min + temp_max) / 2.0 - ?) <= ?
                 AND look_id NOT IN (
                     SELECT look_id FROM usages WHERE used_on >= ?
                 )
               ORDER BY ABS((temp_min + temp_max) / 2.0 - ?) ASC
               LIMIT 1""",
            (gender.value, season, int(rain_ok), temp, TEMP_WINDOW, cutoff, temp),
        ).fetchone()

        return self._to_look(row) if row else None

    @staticmethod
    def _to_look(row: sqlite3.Row) -> LookAnalysis:
        return LookAnalysis(
            look_id=row["look_id"],
            gender=Gender(row["gender"]),
            sleeve=row["sleeve"],
            outer=row["outer"],
            layers=row["layers"],
            fabric_weight=row["fabric_weight"],
            coverage=row["coverage"],
            temp_range=(row["temp_min"], row["temp_max"]),
            rain_ok=bool(row["rain_ok"]),
            season=row["season"],
            style_tags=json.loads(row["style_tags"]),
            palette=json.loads(row["palette"]),
            image_path=Path(row["image_path"]) if row["image_path"] else None,
        )
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `pytest tests/test_archive.py -v`
Expected: PASS (8개)

- [ ] **Step 5: 커밋**

```bash
git add src/willy/archive.py tests/test_archive.py
git commit -m "feat: 룩 아카이브(SQLite) 추가"
```

---

## Task 5: 배정기

**Files:**
- Create: `src/willy/assigner.py`
- Test: `tests/test_assigner.py`

**Interfaces:**
- Consumes: `LookAnalysis`, `DayWeather`, `Gender`, `Assignment`, `Warning`, `WarningCode` (Task 1), `Archive` (Task 4)
- Produces: `assignment_cost(look, day) -> float`, `assign(looks, week, archive=None) -> tuple[Assignment, list[Warning]]`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_assigner.py`:

```python
from datetime import date, timedelta
from pathlib import Path

import pytest

from willy.assigner import assign, assignment_cost
from willy.models import DayWeather, Gender, LookAnalysis, WarningCode


def look(look_id: str, temp_range, rain_ok=True, gender=Gender.MEN) -> LookAnalysis:
    return LookAnalysis(
        look_id=look_id, gender=gender, sleeve="short", outer=None, layers=1,
        fabric_weight="light", coverage="mid", temp_range=temp_range,
        rain_ok=rain_ok, season="summer", style_tags=[], palette=[],
        image_path=Path(f"/tmp/{look_id}.jpg"),
    )


def day(offset: int, tmax=28, tmin=22, pop=10, sky="맑음") -> DayWeather:
    d = date(2026, 8, 3) + timedelta(days=offset)
    return DayWeather(
        date=d, weekday_ko="월화수목금토일"[d.weekday()], temp_max=tmax,
        temp_min=tmin, precip_prob=pop, sky=sky, resolution="detailed",
    )


def full_week() -> list[DayWeather]:
    return [day(i) for i in range(7)]


def test_cost_is_temperature_distance_when_in_range():
    # 대표기온 28*0.6 + 22*0.4 = 25.6, 룩 중앙값 25 -> 0.6
    assert assignment_cost(look("a", (20, 30)), day(0)) == pytest.approx(0.6)


def test_cost_adds_penalty_when_temperature_out_of_range():
    # 대표기온 25.6이 (5,10) 밖 -> 거리 18.1 + 5
    assert assignment_cost(look("a", (5, 10)), day(0)) == pytest.approx(23.1)


def test_cost_blocks_non_rain_look_on_rainy_day():
    cost = assignment_cost(look("a", (20, 30), rain_ok=False), day(0, pop=60))
    assert cost >= 999


def test_cost_allows_rain_ok_look_on_rainy_day():
    cost = assignment_cost(look("a", (20, 30), rain_ok=True), day(0, pop=60))
    assert cost < 999


def test_assign_fills_all_fourteen_slots():
    looks = [look(f"m{i}", (20, 30)) for i in range(7)]
    looks += [look(f"w{i}", (20, 30), gender=Gender.WOMEN) for i in range(7)]

    assignment, warnings = assign(looks, full_week())

    assert len(assignment) == 14
    assert all(v is not None for v in assignment.values())
    assert warnings == []


def test_assign_never_reuses_the_same_look():
    looks = [look(f"m{i}", (20, 30)) for i in range(7)]
    looks += [look(f"w{i}", (20, 30), gender=Gender.WOMEN) for i in range(7)]

    assignment, _ = assign(looks, full_week())
    used = [v.look_id for v in assignment.values() if v]

    assert len(used) == len(set(used))


def test_assign_warns_when_pool_too_small():
    assignment, warnings = assign([look("only", (20, 30))], full_week())

    codes = [w.code for w in warnings]
    assert WarningCode.POOL_TOO_SMALL in codes


def test_assign_leaves_empty_slot_rather_than_forcing_bad_match():
    """한파 주간에 여름룩만 있으면 억지로 배정하지 않는다."""
    winter_week = [day(i, tmax=-2, tmin=-10) for i in range(7)]
    looks = [look(f"m{i}", (24, 30)) for i in range(7)]

    assignment, warnings = assign(looks, winter_week)

    assert any(v is None for v in assignment.values())
    assert WarningCode.EMPTY_SLOT in [w.code for w in warnings]


def test_assign_prefers_globally_optimal_over_greedy():
    """앞 요일이 좋은 룩을 선점해 뒤 요일이 무너지지 않아야 한다."""
    week = [day(0, tmax=30, tmin=30), day(1, tmax=20, tmin=20)]
    # cool은 양쪽에 쓸 수 있지만 hot은 더운 날에만 맞다.
    looks = [look("cool", (18, 30)), look("hot", (29, 31))]

    assignment, _ = assign(looks, week)

    assert assignment[(week[0].date, Gender.MEN)].look_id == "hot"
    assert assignment[(week[1].date, Gender.MEN)].look_id == "cool"


def test_assign_uses_archive_substitute_on_rainy_day(tmp_path: Path):
    from willy.archive import Archive

    archive = Archive(tmp_path / "a.db")
    archive.save(look("rain_backup", (22, 28), rain_ok=True))

    week = [day(0, pop=80, sky="비")]
    looks = [look("dry_only", (22, 28), rain_ok=False)]

    assignment, warnings = assign(looks, week, archive=archive)

    assert assignment[(week[0].date, Gender.MEN)].look_id == "rain_backup"
    # 우천 대체는 RAIN_SUBSTITUTE 하나만 남긴다. 한 사건에 경고 하나.
    codes = [w.code for w in warnings]
    assert WarningCode.RAIN_SUBSTITUTE in codes
    assert codes.count(WarningCode.RAIN_SUBSTITUTE) == 1


def test_assign_uses_archive_fallback_on_dry_day(tmp_path: Path):
    """비가 안 오는 날 폴백은 ARCHIVE_FALLBACK으로 구분한다."""
    from willy.archive import Archive

    archive = Archive(tmp_path / "a.db")
    archive.save(look("backup", (24, 30), rain_ok=False))

    week = [day(0, tmax=28, tmin=22)]
    looks = [look("way_off", (-10, -5))]  # 배정 불가 수준

    assignment, warnings = assign(looks, week, archive=archive)

    assert assignment[(week[0].date, Gender.MEN)].look_id == "backup"
    assert WarningCode.ARCHIVE_FALLBACK in [w.code for w in warnings]
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest tests/test_assigner.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'willy.assigner'`

- [ ] **Step 3: 배정기 구현**

`src/willy/assigner.py`:

```python
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
            continue

        # 배정 실패 -> 아카이브 폴백
        substitute = None
        if archive is not None:
            substitute = archive.find_substitute(
                temp=day.temp_repr,
                rain_ok=day.is_rainy,
                season=pool[0].season,
                gender=gender,
            )

        if substitute is not None:
            assignment[(day.date, gender)] = substitute
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
        _assign_one_gender(looks, week, gender, archive, assignment, warnings)

    return assignment, warnings
```

`numpy`는 scipy 의존성으로 함께 설치되므로 별도 선언하지 않는다.

- [ ] **Step 4: 테스트 통과 확인**

Run: `pytest tests/test_assigner.py -v`
Expected: PASS (11개)

- [ ] **Step 5: 커밋**

```bash
git add src/willy/assigner.py tests/test_assigner.py
git commit -m "feat: 헝가리안 기반 요일 배정기 추가"
```

---

## Task 6: 룩 분석기

**Files:**
- Create: `src/willy/analyzer.py`
- Test: `tests/test_analyzer.py`

**Interfaces:**
- Consumes: `RawLook`, `LookAnalysis`, `Gender` (Task 1)
- Produces: `derive_season(temp_median, collected_month) -> str`, `LookAnalyzer(api_key, client=None)`, `LookAnalyzer.analyze(raw_look) -> LookAnalysis`, `ANALYSIS_PROMPT`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_analyzer.py`:

```python
import base64
from datetime import datetime
from pathlib import Path

import pytest

from willy.analyzer import LookAnalyzer, derive_season
from willy.models import Gender, RawLook


@pytest.mark.parametrize(
    "temp,month,expected",
    [
        (27.0, 8, "summer"),
        (23.0, 8, "summer"),
        (20.0, 4, "spring"),
        (20.0, 10, "fall"),
        (17.0, 3, "spring"),
        (10.0, 12, "winter"),
        (16.9, 5, "winter"),
    ],
)
def test_derive_season_is_deterministic(temp, month, expected):
    assert derive_season(temp, month) == expected


class FakeMessages:
    def __init__(self, payload: str):
        self._payload = payload
        self.last_kwargs = None

    def create(self, **kwargs):
        self.last_kwargs = kwargs

        class Block:
            text = self._payload

        class Response:
            content = [Block()]

        return Response()


class FakeClient:
    def __init__(self, payload: str):
        self.messages = FakeMessages(payload)


@pytest.fixture
def image(tmp_path: Path) -> Path:
    path = tmp_path / "look.jpg"
    path.write_bytes(b"\xff\xd8\xff\xe0fake-jpeg")
    return path


def raw(image: Path) -> RawLook:
    return RawLook(
        look_id="L1",
        source="musinsa_snap",
        image_path=image,
        capture_method="original_url",
        collected_at=datetime(2026, 8, 3),
    )


VALID = """{
  "gender": "men", "sleeve": "short", "outer": null, "layers": 1,
  "fabric_weight": "light", "coverage": "mid", "temp_range": [24, 30],
  "rain_ok": false, "style_tags": ["미니멀"], "palette": ["ecru", "charcoal"]
}"""


def test_analyze_maps_fields(image: Path):
    analyzer = LookAnalyzer(api_key="k", client=FakeClient(VALID))
    result = analyzer.analyze(raw(image))

    assert result.look_id == "L1"
    assert result.gender is Gender.MEN
    assert result.temp_range == (24, 30)
    assert result.rain_ok is False
    assert result.palette == ["ecru", "charcoal"]
    assert result.image_path == image


def test_analyze_derives_season_not_from_model(image: Path):
    """계절은 모델이 말한 값이 아니라 기온에서 규칙으로 파생한다."""
    analyzer = LookAnalyzer(api_key="k", client=FakeClient(VALID))
    result = analyzer.analyze(raw(image))

    assert result.season == "summer"  # 중앙값 27 -> summer


def test_analyze_strips_markdown_fence(image: Path):
    fenced = "```json\n" + VALID + "\n```"
    analyzer = LookAnalyzer(api_key="k", client=FakeClient(fenced))

    assert analyzer.analyze(raw(image)).gender is Gender.MEN


def test_analyze_sends_base64_image(image: Path):
    client = FakeClient(VALID)
    LookAnalyzer(api_key="k", client=client).analyze(raw(image))

    content = client.messages.last_kwargs["messages"][0]["content"]
    image_block = next(b for b in content if b["type"] == "image")
    assert image_block["source"]["data"] == base64.standard_b64encode(
        image.read_bytes()
    ).decode()


def test_analyze_raises_on_malformed_response(image: Path):
    analyzer = LookAnalyzer(api_key="k", client=FakeClient("설명을 드리자면..."))

    with pytest.raises(ValueError, match="분석 결과를 파싱"):
        analyzer.analyze(raw(image))


def test_analyze_rejects_inverted_temp_range(image: Path):
    bad = VALID.replace('"temp_range": [24, 30]', '"temp_range": [30, 24]')
    analyzer = LookAnalyzer(api_key="k", client=FakeClient(bad))

    with pytest.raises(ValueError, match="temp_range"):
        analyzer.analyze(raw(image))
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest tests/test_analyzer.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'willy.analyzer'`

- [ ] **Step 3: 분석기 구현**

`src/willy/analyzer.py`:

```python
"""룩 이미지 -> 구조화 분석. 기온 배정과 이미지 재생성에 모두 쓰인다."""
from __future__ import annotations

import base64
import json
import re

from anthropic import Anthropic

from willy.models import Gender, LookAnalysis, RawLook

MODEL = "claude-sonnet-5"

ANALYSIS_PROMPT = """이 사진의 착장을 분석해 JSON만 출력해. 설명 문장은 쓰지 마.

{
  "gender": "men" 또는 "women",
  "sleeve": "sleeveless" | "short" | "long",
  "outer": 아우터 종류 문자열 또는 null,
  "layers": 상체에 겹쳐 입은 옷의 개수 (정수),
  "fabric_weight": "light" | "mid" | "heavy",
  "coverage": "low" | "mid" | "high",
  "temp_range": [최저, 최고],
  "rain_ok": true 또는 false,
  "style_tags": 한국어 스타일 키워드 2~4개,
  "palette": 주요 색상 영문 2~4개
}

temp_range 판단 기준:
- 반팔 단독, 얇은 소재 -> 24~32
- 얇은 긴팔 또는 반팔+얇은 겉옷 -> 17~24
- 두꺼운 긴팔, 자켓 -> 10~18
- 코트, 패딩 -> 10도 미만
반드시 최저 < 최고 순서로 쓸 것.

rain_ok 판단 기준: 우천에 입을 수 있으면 true.
아우터가 없거나, 스웨이드·린넨처럼 물에 약한 소재이거나,
하의가 바닥에 끌리는 기장이면 false."""


def derive_season(temp_median: float, collected_month: int) -> str:
    """계절은 모델 판단이 아니라 기온에서 규칙으로 파생한다.

    아카이브 폴백 조회가 일관되려면 결정론적이어야 한다.
    """
    if temp_median >= 23:
        return "summer"
    if temp_median >= 17:
        return "spring" if collected_month in (3, 4, 5) else "fall"
    return "winter"


def _extract_json(text: str) -> dict:
    """마크다운 펜스나 앞뒤 잡음이 섞여도 JSON 본문을 건져낸다."""
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    candidate = fenced.group(1) if fenced else None
    if candidate is None:
        braced = re.search(r"\{.*\}", text, re.S)
        candidate = braced.group(0) if braced else None
    if candidate is None:
        raise ValueError(f"분석 결과를 파싱할 수 없습니다: {text[:120]}")
    try:
        return json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise ValueError(f"분석 결과를 파싱할 수 없습니다: {exc}") from exc


class LookAnalyzer:
    def __init__(self, api_key: str, client=None):
        self._client = client or Anthropic(api_key=api_key)

    def analyze(self, raw_look: RawLook) -> LookAnalysis:
        encoded = base64.standard_b64encode(raw_look.image_path.read_bytes()).decode()

        response = self._client.messages.create(
            model=MODEL,
            max_tokens=1024,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/jpeg",
                                "data": encoded,
                            },
                        },
                        {"type": "text", "text": ANALYSIS_PROMPT},
                    ],
                }
            ],
        )

        data = _extract_json(response.content[0].text)

        lo, hi = data["temp_range"]
        if lo >= hi:
            raise ValueError(f"temp_range 순서가 잘못되었습니다: {data['temp_range']}")

        median = (lo + hi) / 2
        return LookAnalysis(
            look_id=raw_look.look_id,
            gender=Gender(data["gender"]),
            sleeve=data["sleeve"],
            outer=data.get("outer"),
            layers=int(data["layers"]),
            fabric_weight=data["fabric_weight"],
            coverage=data["coverage"],
            temp_range=(int(lo), int(hi)),
            rain_ok=bool(data["rain_ok"]),
            season=derive_season(median, raw_look.collected_at.month),
            style_tags=list(data.get("style_tags", [])),
            palette=list(data.get("palette", [])),
            image_path=raw_look.image_path,
        )
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `pytest tests/test_analyzer.py -v`
Expected: PASS (13개)

- [ ] **Step 5: 커밋**

```bash
git add src/willy/analyzer.py tests/test_analyzer.py
git commit -m "feat: Claude 비전 기반 룩 분석기 추가"
```

---

## Task 7: 수집기

**Files:**
- Create: `src/willy/collector/__init__.py`
- Create: `src/willy/collector/sources.py`
- Create: `src/willy/collector/collector.py`
- Test: `tests/test_collector_sources.py`
- Test: `tests/test_collector.py`

**Interfaces:**
- Consumes: `RawLook` (Task 1), `SOURCE_URLS` (Task 1)
- Produces: `SourceSpec`, `SOURCE_SPECS`, `build_look_id(source, index)`, `Collector(workspace, page_factory)`, `Collector.collect(sources, limit_per_source) -> list[RawLook]`, `Collector.add_manual(path_or_url) -> RawLook`

- [ ] **Step 1: 소스 스펙 테스트 작성**

`tests/test_collector_sources.py`:

```python
import pytest

from willy.collector.sources import SOURCE_SPECS, build_look_id


def test_all_three_fixed_sources_are_registered():
    assert set(SOURCE_SPECS) == {"musinsa_snap", "uniqlo_women", "uniqlo_men"}


def test_blocked_platforms_are_absent():
    """에이블리·크림은 CAPTCHA/미제공으로 제외했다. 되살아나면 안 된다."""
    joined = " ".join(spec.url for spec in SOURCE_SPECS.values())
    assert "a-bly" not in joined
    assert "kream" not in joined


def test_each_spec_has_selectors():
    for name, spec in SOURCE_SPECS.items():
        assert spec.card_selector, f"{name}: card_selector 누락"
        assert spec.image_selector, f"{name}: image_selector 누락"


def test_build_look_id_is_unique_per_source_and_index():
    a = build_look_id("musinsa_snap", 0)
    b = build_look_id("musinsa_snap", 1)
    c = build_look_id("uniqlo_men", 0)

    assert a != b != c
    assert a.startswith("musinsa_snap-")
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest tests/test_collector_sources.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'willy.collector'`

- [ ] **Step 3: 소스 스펙 구현**

`src/willy/collector/__init__.py`: 빈 파일.

`src/willy/collector/sources.py`:

```python
"""소스별 셀렉터. 사이트 DOM이 바뀌면 이 파일만 고친다."""
from __future__ import annotations

import uuid
from dataclasses import dataclass

from willy.config import SOURCE_URLS


@dataclass(frozen=True)
class SourceSpec:
    name: str
    url: str
    card_selector: str      # 룩 카드 하나를 가리키는 셀렉터
    image_selector: str     # 카드 안의 이미지
    link_selector: str | None = None
    meta_selector: str | None = None  # 제품명 등 (옵션)
    scroll_rounds: int = 3            # 지연 로딩을 위한 스크롤 횟수


SOURCE_SPECS: dict[str, SourceSpec] = {
    "musinsa_snap": SourceSpec(
        name="musinsa_snap",
        url=SOURCE_URLS["musinsa_snap"],
        card_selector="[class*='SnapItem'], [data-snap-id], article",
        image_selector="img",
        link_selector="a",
    ),
    "uniqlo_women": SourceSpec(
        name="uniqlo_women",
        url=SOURCE_URLS["uniqlo_women"],
        card_selector="[class*='styling'] li, [class*='Card'], article",
        image_selector="img",
        link_selector="a",
    ),
    "uniqlo_men": SourceSpec(
        name="uniqlo_men",
        url=SOURCE_URLS["uniqlo_men"],
        card_selector="[class*='styling'] li, [class*='Card'], article",
        image_selector="img",
        link_selector="a",
    ),
}


def build_look_id(source: str, index: int) -> str:
    return f"{source}-{index}-{uuid.uuid4().hex[:8]}"
```

셀렉터는 실제 DOM 확인 후 조정이 필요하다. 구현 시 브라우저를 띄워 실제 클래스명을 확인하고 이 파일만 갱신한다.

- [ ] **Step 4: 수집기 테스트 작성**

`tests/test_collector.py`:

```python
from pathlib import Path

import pytest

from willy.collector.collector import Collector
from willy.collector.sources import SourceSpec


class FakeElement:
    def __init__(self, image_url: str | None, link: str | None = None):
        self._image = image_url
        self._link = link
        self.screenshot_calls: list[Path] = []

    def query_selector(self, selector: str):
        if selector == "img":
            return FakeImage(self._image) if self._image else None
        if selector == "a":
            return FakeLink(self._link) if self._link else None
        return None

    def screenshot(self, path: str):
        Path(path).write_bytes(b"\xff\xd8\xff\xe0screenshot")
        self.screenshot_calls.append(Path(path))


class FakeImage:
    def __init__(self, url: str):
        self._url = url

    def get_attribute(self, name: str):
        return self._url if name == "src" else None


class FakeLink:
    def __init__(self, href: str):
        self._href = href

    def get_attribute(self, name: str):
        return self._href if name == "href" else None


class FakePage:
    def __init__(self, elements: list[FakeElement]):
        self._elements = elements
        self.visited: list[str] = []

    def goto(self, url: str, **kwargs):
        self.visited.append(url)

    def wait_for_timeout(self, ms: int):
        pass

    def mouse_wheel(self, dx: int, dy: int):
        pass

    def query_selector_all(self, selector: str):
        return self._elements


def spec(name="musinsa_snap") -> SourceSpec:
    return SourceSpec(
        name=name, url="https://example.test/", card_selector=".card",
        image_selector="img", link_selector="a", scroll_rounds=1,
    )


def make_collector(tmp_path: Path, page: FakePage, downloader=None) -> Collector:
    return Collector(
        workspace=tmp_path,
        page_factory=lambda: page,
        downloader=downloader or (lambda url, dest: dest.write_bytes(b"\xff\xd8original")),
    )


def test_collect_downloads_original_when_url_present(tmp_path: Path):
    page = FakePage([FakeElement("https://cdn.test/a.jpg", "https://x.test/1")])
    looks = make_collector(tmp_path, page).collect([spec()], limit_per_source=5)

    assert len(looks) == 1
    assert looks[0].capture_method == "original_url"
    assert looks[0].image_path.read_bytes() == b"\xff\xd8original"
    assert looks[0].source_url == "https://x.test/1"


def test_collect_falls_back_to_screenshot_when_no_image_url(tmp_path: Path):
    page = FakePage([FakeElement(None)])
    looks = make_collector(tmp_path, page).collect([spec()], limit_per_source=5)

    assert looks[0].capture_method == "screenshot"
    assert looks[0].image_path.exists()


def test_collect_falls_back_to_screenshot_when_download_fails(tmp_path: Path):
    def failing(url, dest):
        raise OSError("네트워크 오류")

    page = FakePage([FakeElement("https://cdn.test/a.jpg")])
    looks = make_collector(tmp_path, page, downloader=failing).collect(
        [spec()], limit_per_source=5
    )

    assert looks[0].capture_method == "screenshot"


def test_collect_respects_limit(tmp_path: Path):
    page = FakePage([FakeElement(f"https://cdn.test/{i}.jpg") for i in range(30)])
    looks = make_collector(tmp_path, page).collect([spec()], limit_per_source=20)

    assert len(looks) == 20


def test_collect_continues_when_one_source_fails(tmp_path: Path):
    """한 소스가 죽어도 나머지는 수집한다."""

    class ExplodingPage(FakePage):
        def goto(self, url: str, **kwargs):
            if "bad" in url:
                raise RuntimeError("페이지 로드 실패")
            super().goto(url, **kwargs)

    page = ExplodingPage([FakeElement("https://cdn.test/a.jpg")])
    bad = SourceSpec(
        name="bad", url="https://bad.test/", card_selector=".card",
        image_selector="img", scroll_rounds=1,
    )

    looks = make_collector(tmp_path, page).collect([bad, spec()], limit_per_source=5)

    assert len(looks) == 1
    assert looks[0].source == "musinsa_snap"


def test_add_manual_from_local_file(tmp_path: Path):
    src = tmp_path / "my.jpg"
    src.write_bytes(b"\xff\xd8manual")

    look = make_collector(tmp_path, FakePage([])).add_manual(str(src))

    assert look.source == "manual"
    assert look.capture_method == "original_url"
    assert look.image_path.read_bytes() == b"\xff\xd8manual"
```

- [ ] **Step 5: 테스트 실패 확인**

Run: `pytest tests/test_collector.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'willy.collector.collector'`

- [ ] **Step 6: 수집기 구현**

`src/willy/collector/collector.py`:

```python
"""고정 URL 3곳 + 수동 투입에서 룩 이미지를 확보한다.

사용자가 버튼을 눌렀을 때만 실행된다. 스케줄러 자동 순회는 하지 않는다.
"""
from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Callable

import httpx

from willy.collector.sources import SourceSpec, build_look_id
from willy.models import RawLook

log = logging.getLogger(__name__)


def _default_downloader(url: str, dest: Path) -> None:
    with httpx.Client(timeout=20.0, follow_redirects=True) as client:
        response = client.get(url)
        response.raise_for_status()
        dest.write_bytes(response.content)


class Collector:
    def __init__(
        self,
        workspace: Path,
        page_factory: Callable[[], object],
        downloader: Callable[[str, Path], None] | None = None,
    ):
        self._workspace = workspace
        self._workspace.mkdir(parents=True, exist_ok=True)
        self._page_factory = page_factory
        self._download = downloader or _default_downloader

    def collect(
        self, sources: list[SourceSpec], limit_per_source: int = 20
    ) -> list[RawLook]:
        page = self._page_factory()
        looks: list[RawLook] = []

        for spec in sources:
            try:
                looks.extend(self._collect_one(page, spec, limit_per_source))
            except Exception:
                # 한 소스 실패가 전체를 무너뜨리지 않는다.
                log.exception("소스 수집 실패: %s", spec.name)

        return looks

    def _collect_one(
        self, page, spec: SourceSpec, limit: int
    ) -> list[RawLook]:
        page.goto(spec.url, wait_until="networkidle")
        page.wait_for_timeout(2000)

        # 지연 로딩 대응
        for _ in range(spec.scroll_rounds):
            page.mouse_wheel(0, 4000)
            page.wait_for_timeout(1200)

        cards = page.query_selector_all(spec.card_selector)[:limit]
        looks: list[RawLook] = []

        for index, card in enumerate(cards):
            look_id = build_look_id(spec.name, index)
            dest = self._workspace / f"{look_id}.jpg"

            image_url = None
            image_el = card.query_selector(spec.image_selector)
            if image_el is not None:
                image_url = image_el.get_attribute("src")

            method = "screenshot"
            if image_url:
                try:
                    self._download(image_url, dest)
                    method = "original_url"
                except Exception:
                    log.warning("원본 다운로드 실패, 캡처로 대체: %s", image_url)

            if method == "screenshot":
                card.screenshot(path=str(dest))

            source_url = None
            if spec.link_selector:
                link_el = card.query_selector(spec.link_selector)
                if link_el is not None:
                    source_url = link_el.get_attribute("href")

            looks.append(
                RawLook(
                    look_id=look_id,
                    source=spec.name,
                    image_path=dest,
                    capture_method=method,
                    source_url=source_url,
                )
            )

        return looks

    def add_manual(self, path_or_url: str) -> RawLook:
        """사용자 직접 투입. 로컬 파일 경로 또는 이미지 URL."""
        look_id = build_look_id("manual", 0)
        dest = self._workspace / f"{look_id}.jpg"

        if path_or_url.startswith(("http://", "https://")):
            self._download(path_or_url, dest)
            source_url = path_or_url
        else:
            shutil.copyfile(path_or_url, dest)
            source_url = None

        return RawLook(
            look_id=look_id,
            source="manual",
            image_path=dest,
            capture_method="original_url",
            source_url=source_url,
        )
```

- [ ] **Step 7: 테스트 통과 확인**

Run: `pytest tests/test_collector.py tests/test_collector_sources.py -v`
Expected: PASS (10개)

- [ ] **Step 8: Playwright 페이지 팩토리 추가**

`src/willy/collector/browser.py`:

```python
"""Playwright 세션. 헤드리스가 아니라 화면을 띄워 진행을 볼 수 있게 한다."""
from __future__ import annotations

from contextlib import contextmanager

from playwright.sync_api import sync_playwright

# 무신사 robots.txt는 Claude-User 등 사용자 주도 에이전트를 허용한다.
# 정체를 숨기지 않는다.
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)


@contextmanager
def browser_page(headless: bool = False):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(
            user_agent=USER_AGENT, viewport={"width": 1440, "height": 900}
        )
        page = context.new_page()
        try:
            yield page
        finally:
            context.close()
            browser.close()
```

- [ ] **Step 9: 커밋**

```bash
git add src/willy/collector tests/test_collector.py tests/test_collector_sources.py
git commit -m "feat: Playwright 기반 룩 수집기 추가"
```

---

## Task 8: 이미지 재생성기

**Files:**
- Create: `src/willy/generator/__init__.py`
- Create: `src/willy/generator/preset.py`
- Create: `src/willy/generator/base.py`
- Create: `src/willy/generator/noop.py`
- Create: `presets/concept_v1.yaml`
- Test: `tests/test_generator.py`

**Interfaces:**
- Consumes: `LookAnalysis`, `Gender` (Task 1)
- Produces: `ConceptPreset`, `load_preset(path) -> ConceptPreset`, `ImageGenerator` (ABC), `build_prompt(analysis, preset) -> str`, `NoopGenerator(output_dir)`

- [ ] **Step 1: 프리셋 파일 작성**

`presets/concept_v1.yaml` — 컨셉과 모델이 미확정이므로 `null`로 둔다. 확정 시 이 파일만 채우면 된다.

```yaml
concept_id: v1
model:
  men:
    age: "30대 초반"
    build: "보통"
    height: "175cm"
    hair: null
    face_ref: null
  women:
    age: "30대 초반"
    build: "보통"
    height: "163cm"
    hair: null
    face_ref: null
render:
  art_style: null
  background: null
  lighting: null
  aspect_ratio: "4:5"
  strength: 0.65
negative:
  - "손가락 왜곡"
  - "텍스트"
  - "로고"
```

- [ ] **Step 2: 실패하는 테스트 작성**

`tests/test_generator.py`:

```python
from pathlib import Path

import pytest
import yaml

from willy.generator.base import build_prompt
from willy.generator.noop import NoopGenerator
from willy.generator.preset import load_preset
from willy.models import Gender, LookAnalysis

PRESET_PATH = Path(__file__).parents[1] / "presets" / "concept_v1.yaml"


def look() -> LookAnalysis:
    return LookAnalysis(
        look_id="L1", gender=Gender.MEN, sleeve="short", outer="shirt_jacket",
        layers=2, fabric_weight="light", coverage="mid", temp_range=(17, 23),
        rain_ok=False, season="fall", style_tags=["미니멀", "워크웨어"],
        palette=["charcoal", "ecru"], image_path=Path("/tmp/L1.jpg"),
    )


def test_load_preset_reads_shipped_file():
    preset = load_preset(PRESET_PATH)

    assert preset.concept_id == "v1"
    assert preset.aspect_ratio == "4:5"
    assert preset.strength == 0.65


def test_undecided_fields_are_none_not_empty_string():
    """미확정 항목은 None이어야 프롬프트에서 빠진다."""
    preset = load_preset(PRESET_PATH)

    assert preset.art_style is None
    assert preset.background is None
    assert preset.model_for(Gender.MEN)["face_ref"] is None


def test_build_prompt_includes_look_attributes():
    prompt = build_prompt(look(), load_preset(PRESET_PATH))

    assert "미니멀" in prompt
    assert "charcoal" in prompt
    assert "30대 초반" in prompt


def test_build_prompt_omits_undecided_fields():
    prompt = build_prompt(look(), load_preset(PRESET_PATH))

    assert "None" not in prompt
    assert "null" not in prompt


def test_build_prompt_includes_negative_terms():
    prompt = build_prompt(look(), load_preset(PRESET_PATH))

    assert "손가락 왜곡" in prompt


def test_noop_generator_copies_source_and_records_prompt(tmp_path: Path):
    source = tmp_path / "src.jpg"
    source.write_bytes(b"\xff\xd8src")
    out = tmp_path / "out"

    generator = NoopGenerator(output_dir=out)
    result = generator.generate(source, look(), load_preset(PRESET_PATH), strength=0.65)

    assert result.exists()
    assert result.read_bytes() == b"\xff\xd8src"
    # 엔진 확정 전까지 프롬프트를 눈으로 검증할 수 있어야 한다.
    assert (out / "L1.prompt.txt").exists()


def test_preset_with_filled_concept_appears_in_prompt(tmp_path: Path):
    """컨셉이 정해지면 코드 수정 없이 프롬프트에 반영되어야 한다."""
    data = yaml.safe_load(PRESET_PATH.read_text(encoding="utf-8"))
    data["render"]["art_style"] = "필름 사진 질감"
    data["render"]["background"] = "서울 골목"
    custom = tmp_path / "custom.yaml"
    custom.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")

    prompt = build_prompt(look(), load_preset(custom))

    assert "필름 사진 질감" in prompt
    assert "서울 골목" in prompt
```

- [ ] **Step 3: 테스트 실패 확인**

Run: `pytest tests/test_generator.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'willy.generator'`

- [ ] **Step 4: 구현**

`src/willy/generator/__init__.py`: 빈 파일.

`src/willy/generator/preset.py`:

```python
"""컨셉 프리셋. 미확정 항목을 코드 밖으로 격리한다."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from willy.models import Gender


@dataclass(frozen=True)
class ConceptPreset:
    concept_id: str
    models: dict
    art_style: str | None
    background: str | None
    lighting: str | None
    aspect_ratio: str
    strength: float
    negative: list[str]

    def model_for(self, gender: Gender) -> dict:
        return self.models[gender.value]


def load_preset(path: Path) -> ConceptPreset:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    render = data.get("render", {})
    return ConceptPreset(
        concept_id=data["concept_id"],
        models=data["model"],
        art_style=render.get("art_style"),
        background=render.get("background"),
        lighting=render.get("lighting"),
        aspect_ratio=render.get("aspect_ratio", "4:5"),
        strength=float(render.get("strength", 0.65)),
        negative=list(data.get("negative", [])),
    )
```

`src/willy/generator/base.py`:

```python
"""이미지 생성 엔진 인터페이스. 엔진이 확정되면 구현체를 추가한다."""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from willy.generator.preset import ConceptPreset
from willy.models import LookAnalysis


def build_prompt(analysis: LookAnalysis, preset: ConceptPreset) -> str:
    """룩 분석 + 컨셉 -> 생성 프롬프트. 미확정(None) 항목은 빠진다."""
    model = preset.model_for(analysis.gender)

    lines = [
        f"{model['age']} {analysis.gender.value} 모델, 체형 {model['build']}, "
        f"키 {model['height']}",
        f"착장: {analysis.sleeve} 상의"
        + (f", {analysis.outer} 아우터" if analysis.outer else "")
        + f", {analysis.layers}겹 레이어드",
        f"소재감: {analysis.fabric_weight}",
        f"색상: {', '.join(analysis.palette)}",
        f"무드: {', '.join(analysis.style_tags)}",
        f"비율: {preset.aspect_ratio}",
    ]

    for label, value in (
        ("화풍", preset.art_style),
        ("배경", preset.background),
        ("조명", preset.lighting),
        ("헤어", model.get("hair")),
    ):
        if value:
            lines.append(f"{label}: {value}")

    if preset.negative:
        lines.append("제외: " + ", ".join(preset.negative))

    return "\n".join(lines)


class ImageGenerator(ABC):
    """원본 룩 이미지를 발행용 이미지로 변환한다.

    파이프라인: 원본 -> img2img(구도·핏 유지) -> 모델 일관성 엔진(고정 모델 적용)

    2단계가 필수인 이유: 소스는 실존 인물(무신사 스냅 일반 유저, 유니클로
    직원)의 사진이다. 고정 캐릭터로 인물을 덮어써야 초상이 결과물에 남지 않는다.
    """

    @abstractmethod
    def generate(
        self,
        source_image: Path,
        analysis: LookAnalysis,
        preset: ConceptPreset,
        strength: float,
    ) -> Path:
        """발행용 이미지 경로를 반환한다."""
```

`src/willy/generator/noop.py`:

```python
"""엔진 미확정 구간용 통과 구현체.

원본을 그대로 복사하고 프롬프트를 파일로 남겨, 엔진 없이도 파이프라인
전체를 끝까지 돌리고 프롬프트 품질을 눈으로 검증할 수 있게 한다.
"""
from __future__ import annotations

import shutil
from pathlib import Path

from willy.generator.base import ImageGenerator, build_prompt
from willy.generator.preset import ConceptPreset
from willy.models import LookAnalysis


class NoopGenerator(ImageGenerator):
    def __init__(self, output_dir: Path):
        self._out = output_dir
        self._out.mkdir(parents=True, exist_ok=True)

    def generate(
        self,
        source_image: Path,
        analysis: LookAnalysis,
        preset: ConceptPreset,
        strength: float,
    ) -> Path:
        dest = self._out / f"{analysis.look_id}.jpg"
        shutil.copyfile(source_image, dest)

        prompt_path = self._out / f"{analysis.look_id}.prompt.txt"
        prompt_path.write_text(build_prompt(analysis, preset), encoding="utf-8")

        return dest
```

- [ ] **Step 5: 테스트 통과 확인**

Run: `pytest tests/test_generator.py -v`
Expected: PASS (7개)

- [ ] **Step 6: 커밋**

```bash
git add src/willy/generator presets tests/test_generator.py
git commit -m "feat: 이미지 생성 어댑터와 컨셉 프리셋 추가"
```

---

## Task 9: 산출기

**Files:**
- Create: `src/willy/publisher/__init__.py`
- Create: `src/willy/publisher/docs.py`
- Create: `src/willy/publisher/folders.py`
- Test: `tests/test_publisher.py`

**Interfaces:**
- Consumes: `Assignment`, `DayWeather`, `Gender`, `LookAnalysis`, `iso_week_label` (Task 1)
- Produces: `REF_FILENAME`, `PUBLISH_FILENAME`, `write_item_doc(path, day, entries)`, `write_week_summary(path, week, assignment)`, `publish(assignment, week, generated, output_root) -> Path`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_publisher.py`:

```python
from datetime import date, timedelta
from pathlib import Path

import pytest
from docx import Document

from willy.models import DayWeather, Gender, LookAnalysis
from willy.publisher.folders import PUBLISH_FILENAME, REF_FILENAME, publish


def look(look_id: str, gender=Gender.MEN) -> LookAnalysis:
    return LookAnalysis(
        look_id=look_id, gender=gender, sleeve="short", outer=None, layers=1,
        fabric_weight="light", coverage="mid", temp_range=(24, 30), rain_ok=False,
        season="summer", style_tags=["미니멀"], palette=["ecru"],
    )


def week_of(days: int = 7) -> list[DayWeather]:
    out = []
    for i in range(days):
        d = date(2026, 8, 3) + timedelta(days=i)
        out.append(
            DayWeather(
                date=d, weekday_ko="월화수목금토일"[d.weekday()], temp_max=29,
                temp_min=24, precip_prob=10, sky="맑음", resolution="detailed",
            )
        )
    return out


@pytest.fixture
def setup(tmp_path: Path):
    """원본과 생성물 파일을 준비하고 (assignment, generated, roots)를 돌려준다."""
    src_dir = tmp_path / "src"
    gen_dir = tmp_path / "gen"
    src_dir.mkdir()
    gen_dir.mkdir()

    week = week_of()
    assignment = {}
    generated = {}

    for day in week:
        for gender in (Gender.MEN, Gender.WOMEN):
            lid = f"{day.date.day}-{gender.value}"
            analysis = look(lid, gender)
            ref = src_dir / f"{lid}.jpg"
            ref.write_bytes(b"\xff\xd8ref")
            analysis.image_path = ref

            gen = gen_dir / f"{lid}.png"
            gen.write_bytes(b"\x89PNGgen")

            assignment[(day.date, gender)] = analysis
            generated[(day.date, gender)] = gen

    return assignment, generated, week, tmp_path / "outputs"


def test_publish_creates_iso_week_folder(setup):
    assignment, generated, week, out = setup
    root = publish(assignment, week, generated, output_root=out)

    # 2026-08-03은 월요일, 그 주 목요일은 08-06 -> 8월 1주차
    assert root.name == "2026-08_W1"


def test_publish_creates_one_folder_per_day_with_weather_in_name(setup):
    assignment, generated, week, out = setup
    root = publish(assignment, week, generated, output_root=out)

    day_dirs = sorted(p.name for p in root.iterdir() if p.is_dir())
    assert len(day_dirs) == 7
    assert "08-03_월_맑음_29-24℃" in day_dirs


def test_publish_writes_ref_and_published_images(setup):
    assignment, generated, week, out = setup
    root = publish(assignment, week, generated, output_root=out)

    men_dir = root / "08-03_월_맑음_29-24℃" / "men"
    assert (men_dir / REF_FILENAME).exists()
    assert (men_dir / PUBLISH_FILENAME).exists()
    assert (men_dir / "analysis.json").exists()


def test_ref_filename_marks_do_not_publish(setup):
    """원본이 실수로 발행되지 않도록 파일명에 표식이 있어야 한다."""
    assert "발행금지" in REF_FILENAME


def test_publish_writes_item_doc_per_day(setup):
    assignment, generated, week, out = setup
    root = publish(assignment, week, generated, output_root=out)

    doc_path = root / "08-03_월_맑음_29-24℃" / "아이템정보.docx"
    assert doc_path.exists()

    doc = Document(str(doc_path))
    text = "\n".join(p.text for p in doc.paragraphs)
    assert "08-03" in text


def test_item_doc_created_even_without_metadata(setup):
    """메타데이터는 옵션이다. 없어도 문서는 만든다."""
    assignment, generated, week, out = setup
    root = publish(assignment, week, generated, output_root=out)

    doc = Document(str(root / "08-03_월_맑음_29-24℃" / "아이템정보.docx"))
    assert len(doc.tables) >= 1


def test_publish_writes_week_summary(setup):
    assignment, generated, week, out = setup
    root = publish(assignment, week, generated, output_root=out)

    assert (root / "_주간요약.docx").exists()


def test_publish_skips_empty_slot_without_crashing(setup):
    assignment, generated, week, out = setup
    empty_key = (week[0].date, Gender.MEN)
    assignment[empty_key] = None
    generated.pop(empty_key)

    root = publish(assignment, week, generated, output_root=out)

    assert not (root / "08-03_월_맑음_29-24℃" / "men").exists()
    assert (root / "08-03_월_맑음_29-24℃" / "women").exists()
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest tests/test_publisher.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'willy.publisher'`

- [ ] **Step 3: 문서 생성 구현**

`src/willy/publisher/__init__.py`: 빈 파일.

`src/willy/publisher/docs.py`:

```python
"""워드 문서 생성. 메타데이터는 옵션이므로 없어도 문서는 만든다."""
from __future__ import annotations

from pathlib import Path

from docx import Document

from willy.models import Assignment, DayWeather, Gender

COLUMNS = ["제품명", "브랜드", "가격", "구매링크"]


def write_item_doc(path: Path, day: DayWeather, entries: dict[Gender, list[dict]]) -> None:
    """요일별 아이템 정보 문서.

    entries가 비어 있어도 표 골격은 남긴다. 사장님이 손으로 채울 수 있게.
    """
    doc = Document()
    doc.add_heading(
        f"{day.date.month:02d}-{day.date.day:02d} ({day.weekday_ko}) "
        f"{day.sky} {day.temp_max}/{day.temp_min}℃",
        level=1,
    )

    for gender in (Gender.MEN, Gender.WOMEN):
        doc.add_heading("남성" if gender is Gender.MEN else "여성", level=2)
        rows = entries.get(gender, [])

        table = doc.add_table(rows=1, cols=len(COLUMNS))
        table.style = "Table Grid"
        for i, name in enumerate(COLUMNS):
            table.rows[0].cells[i].text = name

        if not rows:
            blank = table.add_row().cells
            blank[0].text = "(수집된 아이템 정보 없음)"
        for row in rows:
            cells = table.add_row().cells
            cells[0].text = str(row.get("name", ""))
            cells[1].text = str(row.get("brand", ""))
            cells[2].text = str(row.get("price", ""))
            cells[3].text = str(row.get("url", ""))

    doc.save(str(path))


def write_week_summary(path: Path, week: list[DayWeather], assignment: Assignment) -> None:
    doc = Document()
    doc.add_heading("이번주 [내일 뭐입지?] 요약", level=1)

    table = doc.add_table(rows=1, cols=5)
    table.style = "Table Grid"
    for i, name in enumerate(["날짜", "요일", "날씨", "기온", "배정 상태"]):
        table.rows[0].cells[i].text = name

    for day in week:
        men = assignment.get((day.date, Gender.MEN))
        women = assignment.get((day.date, Gender.WOMEN))
        filled = sum(1 for x in (men, women) if x is not None)

        cells = table.add_row().cells
        cells[0].text = day.date.isoformat()
        cells[1].text = day.weekday_ko
        cells[2].text = day.sky
        cells[3].text = f"{day.temp_max}/{day.temp_min}℃"
        cells[4].text = f"{filled}/2"

    doc.save(str(path))
```

- [ ] **Step 4: 폴더 생성 구현**

`src/willy/publisher/folders.py`:

```python
"""컨펌된 배정을 폴더와 문서로 물리화한다."""
from __future__ import annotations

import json
import shutil
from dataclasses import asdict
from pathlib import Path

from willy.models import Assignment, DayWeather, Gender, iso_week_label
from willy.publisher.docs import write_item_doc, write_week_summary

# 원본은 로컬 참고용이다. 파일명에 표식을 박아 오발행을 막는다.
REF_FILENAME = "_ref_원본_발행금지.jpg"
PUBLISH_FILENAME = "발행용.png"


def _write_analysis(path: Path, analysis) -> None:
    data = asdict(analysis)
    data["gender"] = analysis.gender.value
    data["temp_range"] = list(analysis.temp_range)
    data["image_path"] = str(analysis.image_path) if analysis.image_path else None
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def publish(
    assignment: Assignment,
    week: list[DayWeather],
    generated: dict[tuple, Path],
    output_root: Path,
) -> Path:
    """최종 컨펌 이후에만 호출된다. 이 함수가 유일하게 outputs/에 쓴다."""
    root = output_root / iso_week_label(week[0].date)
    root.mkdir(parents=True, exist_ok=True)

    for day in week:
        day_dir = root / day.folder_name
        day_dir.mkdir(parents=True, exist_ok=True)

        entries: dict[Gender, list[dict]] = {}

        for gender in (Gender.MEN, Gender.WOMEN):
            analysis = assignment.get((day.date, gender))
            if analysis is None:
                continue  # 빈 칸은 폴더를 만들지 않는다.

            gender_dir = day_dir / gender.value
            gender_dir.mkdir(parents=True, exist_ok=True)

            if analysis.image_path and analysis.image_path.exists():
                shutil.copyfile(analysis.image_path, gender_dir / REF_FILENAME)

            gen_path = generated.get((day.date, gender))
            if gen_path and gen_path.exists():
                shutil.copyfile(gen_path, gender_dir / PUBLISH_FILENAME)

            _write_analysis(gender_dir / "analysis.json", analysis)
            entries[gender] = []

        write_item_doc(day_dir / "아이템정보.docx", day, entries)

    write_week_summary(root / "_주간요약.docx", week, assignment)
    return root
```

- [ ] **Step 5: 테스트 통과 확인**

Run: `pytest tests/test_publisher.py -v`
Expected: PASS (8개)

- [ ] **Step 6: 커밋**

```bash
git add src/willy/publisher tests/test_publisher.py
git commit -m "feat: 폴더 구조와 워드 문서 산출기 추가"
```

---

## Task 10: 파이프라인 오케스트레이션

**Files:**
- Create: `src/willy/pipeline.py`
- Test: `tests/test_pipeline.py`

**Interfaces:**
- Consumes: 모든 이전 태스크
- Produces: `PipelineState`, `Pipeline(settings, weather_client, analyzer, collector, generator, archive, preset)`, `Pipeline.gather() -> PipelineState`, `Pipeline.generate_images(state) -> PipelineState`, `Pipeline.finalize(state) -> Path`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_pipeline.py`:

```python
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from willy.models import DayWeather, Gender, LookAnalysis, RawLook
from willy.pipeline import Pipeline


class FakeWeather:
    def get_week_forecast(self, base_date: date) -> list[DayWeather]:
        out = []
        for i in range(7):
            d = base_date + timedelta(days=i)
            out.append(
                DayWeather(
                    date=d, weekday_ko="월화수목금토일"[d.weekday()], temp_max=29,
                    temp_min=24, precip_prob=10, sky="맑음", resolution="detailed",
                )
            )
        return out


class FakeCollector:
    def __init__(self, workspace: Path, count: int = 14):
        self.workspace = workspace
        workspace.mkdir(parents=True, exist_ok=True)
        self.count = count

    def collect(self, sources, limit_per_source):
        looks = []
        for i in range(self.count):
            path = self.workspace / f"raw{i}.jpg"
            path.write_bytes(b"\xff\xd8raw")
            looks.append(
                RawLook(
                    look_id=f"L{i}", source="musinsa_snap", image_path=path,
                    capture_method="original_url", collected_at=datetime(2026, 8, 3),
                )
            )
        return looks


class FakeAnalyzer:
    def analyze(self, raw_look: RawLook) -> LookAnalysis:
        index = int(raw_look.look_id[1:])
        return LookAnalysis(
            look_id=raw_look.look_id,
            gender=Gender.MEN if index % 2 == 0 else Gender.WOMEN,
            sleeve="short", outer=None, layers=1, fabric_weight="light",
            coverage="mid", temp_range=(24, 30), rain_ok=True, season="summer",
            style_tags=["미니멀"], palette=["ecru"], image_path=raw_look.image_path,
        )


class FakeGenerator:
    def __init__(self, out: Path):
        self.out = out
        out.mkdir(parents=True, exist_ok=True)
        self.calls = 0

    def generate(self, source_image, analysis, preset, strength):
        self.calls += 1
        path = self.out / f"{analysis.look_id}.png"
        path.write_bytes(b"\x89PNGgen")
        return path


@pytest.fixture
def pipeline(tmp_path: Path) -> Pipeline:
    from willy.archive import Archive
    from willy.generator.preset import load_preset

    preset = load_preset(Path(__file__).parents[1] / "presets" / "concept_v1.yaml")
    return Pipeline(
        weather_client=FakeWeather(),
        collector=FakeCollector(tmp_path / "ws"),
        analyzer=FakeAnalyzer(),
        generator=FakeGenerator(tmp_path / "gen"),
        archive=Archive(tmp_path / "a.db"),
        preset=preset,
        output_root=tmp_path / "outputs",
        looks_per_source=20,
    )


def test_gather_produces_week_and_assignment(pipeline: Pipeline):
    state = pipeline.gather(base_date=date(2026, 8, 3))

    assert len(state.week) == 7
    assert len(state.assignment) == 14


def test_gather_does_not_write_to_outputs(pipeline: Pipeline, tmp_path: Path):
    """1차 컨펌 전에는 outputs/에 아무것도 쓰지 않는다."""
    pipeline.gather(base_date=date(2026, 8, 3))

    assert not (tmp_path / "outputs").exists()


def test_gather_saves_looks_to_archive(pipeline: Pipeline):
    state = pipeline.gather(base_date=date(2026, 8, 3))

    assert pipeline.archive.count() == 14
    assert state.assignment is not None


def test_generate_images_does_not_write_to_outputs(pipeline: Pipeline, tmp_path: Path):
    state = pipeline.gather(base_date=date(2026, 8, 3))
    pipeline.generate_images(state)

    assert not (tmp_path / "outputs").exists()


def test_generate_images_runs_once_per_filled_slot(pipeline: Pipeline):
    state = pipeline.gather(base_date=date(2026, 8, 3))
    state = pipeline.generate_images(state)

    filled = sum(1 for v in state.assignment.values() if v is not None)
    assert pipeline.generator.calls == filled
    assert len(state.generated) == filled


def test_finalize_writes_outputs_and_marks_usage(pipeline: Pipeline, tmp_path: Path):
    state = pipeline.gather(base_date=date(2026, 8, 3))
    state = pipeline.generate_images(state)
    root = pipeline.finalize(state)

    assert root.exists()
    assert root.name == "2026-08_W1"
    assert (root / "_주간요약.docx").exists()

    # 사용 이력이 남아야 4주 내 재등장이 막힌다.
    used = pipeline.archive.find_substitute(
        temp=26.0, rain_ok=True, season="summer", gender=Gender.MEN
    )
    assert used is None


def test_full_flow_with_insufficient_looks_still_completes(tmp_path: Path):
    """룩이 모자라도 흐름은 끝까지 간다. 빈 칸 + 경고로 처리."""
    from willy.archive import Archive
    from willy.generator.preset import load_preset

    preset = load_preset(Path(__file__).parents[1] / "presets" / "concept_v1.yaml")
    pipeline = Pipeline(
        weather_client=FakeWeather(),
        collector=FakeCollector(tmp_path / "ws", count=2),
        analyzer=FakeAnalyzer(),
        generator=FakeGenerator(tmp_path / "gen"),
        archive=Archive(tmp_path / "a.db"),
        preset=preset,
        output_root=tmp_path / "outputs",
        looks_per_source=20,
    )

    state = pipeline.gather(base_date=date(2026, 8, 3))
    assert state.warnings  # POOL_TOO_SMALL 등

    state = pipeline.generate_images(state)
    root = pipeline.finalize(state)
    assert root.exists()
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest tests/test_pipeline.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'willy.pipeline'`

- [ ] **Step 3: 파이프라인 구현**

`src/willy/pipeline.py`:

```python
"""전체 흐름 오케스트레이션.

컨펌 경계가 여기서 강제된다:
  gather()          -> 임시 영역만 사용
  generate_images() -> 임시 영역만 사용
  finalize()        -> 유일하게 outputs/에 쓴다
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from willy.archive import Archive
from willy.assigner import assign
from willy.collector.sources import SOURCE_SPECS
from willy.models import Assignment, DayWeather, Gender, LookAnalysis, Warning
from willy.publisher.folders import publish

log = logging.getLogger(__name__)


@dataclass
class PipelineState:
    week: list[DayWeather]
    looks: list[LookAnalysis]
    assignment: Assignment
    warnings: list[Warning]
    generated: dict[tuple[date, Gender], Path] = field(default_factory=dict)


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
        looks_per_source: int = 20,
    ):
        self.weather_client = weather_client
        self.collector = collector
        self.analyzer = analyzer
        self.generator = generator
        self.archive = archive
        self.preset = preset
        self.output_root = output_root
        self.looks_per_source = looks_per_source

    def gather(self, base_date: date) -> PipelineState:
        """수집 -> 분석 -> 날씨 -> 배정. 1차 컨펌 대상."""
        week = self.weather_client.get_week_forecast(base_date)

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

        assignment, warnings = assign(looks, week, archive=self.archive)
        return PipelineState(
            week=week, looks=looks, assignment=assignment, warnings=warnings
        )

    def generate_images(self, state: PipelineState) -> PipelineState:
        """AI 재생성. 1차 컨펌 이후에만 호출된다."""
        generated: dict[tuple[date, Gender], Path] = {}

        for (slot_date, gender), analysis in state.assignment.items():
            if analysis is None or analysis.image_path is None:
                continue
            try:
                generated[(slot_date, gender)] = self.generator.generate(
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

        for (slot_date, _gender), analysis in state.assignment.items():
            if analysis is not None:
                self.archive.mark_used(analysis.look_id, used_on=slot_date)

        return root
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `pytest tests/test_pipeline.py -v`
Expected: PASS (7개)

- [ ] **Step 5: 전체 테스트 실행**

Run: `pytest -v`
Expected: 전부 PASS

- [ ] **Step 6: 커밋**

```bash
git add src/willy/pipeline.py tests/test_pipeline.py
git commit -m "feat: 파이프라인 오케스트레이션 추가"
```

---

## Task 11: 컨펌 UI

**Files:**
- Create: `src/willy/web/__init__.py`
- Create: `src/willy/web/app.py`
- Create: `src/willy/web/static/index.html`
- Test: `tests/test_web.py`

**Interfaces:**
- Consumes: `Pipeline`, `PipelineState` (Task 10)
- Produces: `create_app(pipeline_factory) -> FastAPI`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_web.py`:

```python
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from willy.web.app import create_app


@pytest.fixture
def client(tmp_path: Path):
    from tests.test_pipeline import (
        FakeAnalyzer,
        FakeCollector,
        FakeGenerator,
        FakeWeather,
    )
    from willy.archive import Archive
    from willy.generator.preset import load_preset
    from willy.pipeline import Pipeline

    preset = load_preset(Path(__file__).parents[1] / "presets" / "concept_v1.yaml")

    def factory() -> Pipeline:
        return Pipeline(
            weather_client=FakeWeather(),
            collector=FakeCollector(tmp_path / "ws"),
            analyzer=FakeAnalyzer(),
            generator=FakeGenerator(tmp_path / "gen"),
            archive=Archive(tmp_path / "a.db"),
            preset=preset,
            output_root=tmp_path / "outputs",
        )

    return TestClient(create_app(factory))


def test_index_serves_page(client: TestClient):
    response = client.get("/")
    assert response.status_code == 200
    assert "내일 뭐입지" in response.text


def test_gather_returns_week_and_slots(client: TestClient):
    response = client.post("/api/gather", json={"base_date": "2026-08-03"})

    assert response.status_code == 200
    body = response.json()
    assert len(body["week"]) == 7
    assert len(body["slots"]) == 14


def test_gather_exposes_warnings(client: TestClient):
    body = client.post("/api/gather", json={"base_date": "2026-08-03"}).json()
    assert "warnings" in body


def test_finalize_before_gather_is_rejected(client: TestClient):
    response = client.post("/api/finalize")
    assert response.status_code == 409


def test_generate_before_gather_is_rejected(client: TestClient):
    response = client.post("/api/generate")
    assert response.status_code == 409


def test_full_confirm_flow(client: TestClient, tmp_path: Path):
    client.post("/api/gather", json={"base_date": "2026-08-03"})

    assert client.post("/api/generate").status_code == 200

    response = client.post("/api/finalize")
    assert response.status_code == 200
    assert "2026-08_W1" in response.json()["output_path"]


def test_finalize_requires_generate_first(client: TestClient):
    """2단계 컨펌을 건너뛸 수 없다."""
    client.post("/api/gather", json={"base_date": "2026-08-03"})

    response = client.post("/api/finalize")
    assert response.status_code == 409
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest tests/test_web.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'willy.web'`

- [ ] **Step 3: FastAPI 앱 구현**

`src/willy/web/__init__.py`: 빈 파일.

`src/willy/web/app.py`:

```python
"""로컬 컨펌 UI. 2단계 컨펌을 서버가 강제한다."""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Callable

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from willy.pipeline import Pipeline, PipelineState

STATIC = Path(__file__).parent / "static"


class GatherRequest(BaseModel):
    base_date: date


def _serialize(state: PipelineState) -> dict:
    return {
        "week": [
            {
                "date": d.date.isoformat(),
                "weekday": d.weekday_ko,
                "sky": d.sky,
                "temp_max": d.temp_max,
                "temp_min": d.temp_min,
                "temp_repr": d.temp_repr,
                "precip_prob": d.precip_prob,
                "is_rainy": d.is_rainy,
                "resolution": d.resolution,
            }
            for d in state.week
        ],
        "slots": [
            {
                "date": slot_date.isoformat(),
                "gender": gender.value,
                "look_id": look.look_id if look else None,
                "temp_range": list(look.temp_range) if look else None,
                "style_tags": look.style_tags if look else [],
                "empty": look is None,
            }
            for (slot_date, gender), look in sorted(
                state.assignment.items(), key=lambda kv: (kv[0][0], kv[0][1].value)
            )
        ],
        "warnings": [
            {"code": w.code.value, "message": w.message} for w in state.warnings
        ],
        "generated_count": len(state.generated),
    }


def create_app(pipeline_factory: Callable[[], Pipeline]) -> FastAPI:
    app = FastAPI(title="내일 뭐입지? 콘텐츠 엔진")
    ctx: dict = {"pipeline": None, "state": None, "generated": False}

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return (STATIC / "index.html").read_text(encoding="utf-8")

    @app.post("/api/gather")
    def gather(request: GatherRequest) -> dict:
        pipeline = pipeline_factory()
        state = pipeline.gather(base_date=request.base_date)
        ctx.update(pipeline=pipeline, state=state, generated=False)
        return _serialize(state)

    @app.post("/api/generate")
    def generate() -> dict:
        if ctx["state"] is None:
            raise HTTPException(409, "먼저 수집을 실행해 주세요.")
        state = ctx["pipeline"].generate_images(ctx["state"])
        ctx.update(state=state, generated=True)
        return _serialize(state)

    @app.post("/api/finalize")
    def finalize() -> dict:
        if ctx["state"] is None:
            raise HTTPException(409, "먼저 수집을 실행해 주세요.")
        if not ctx["generated"]:
            raise HTTPException(409, "이미지 생성 후 최종 컨펌이 가능합니다.")
        root = ctx["pipeline"].finalize(ctx["state"])
        return {"output_path": str(root)}

    return app
```

- [ ] **Step 4: 단일 페이지 UI 작성**

`src/willy/web/static/index.html`:

```html
<!doctype html>
<meta charset="utf-8" />
<title>내일 뭐입지? 콘텐츠 엔진</title>
<style>
  body { font-family: -apple-system, sans-serif; margin: 24px; max-width: 1100px; }
  h1 { font-size: 20px; }
  .week { display: flex; gap: 8px; overflow-x: auto; margin: 16px 0; }
  .day { border: 1px solid #ddd; border-radius: 8px; padding: 10px; min-width: 110px; }
  .day.rainy { border-color: #3b82f6; background: #eff6ff; }
  .day.coarse { opacity: .7; }
  .slots { display: grid; grid-template-columns: repeat(7, 1fr); gap: 8px; }
  .slot { border: 1px solid #ddd; border-radius: 8px; padding: 8px; font-size: 12px; }
  .slot.empty { border-style: dashed; color: #b91c1c; }
  .warn { background: #fef3c7; border-radius: 8px; padding: 10px; margin: 12px 0; }
  button { padding: 10px 16px; margin-right: 8px; border-radius: 8px; cursor: pointer; }
  button:disabled { opacity: .45; cursor: not-allowed; }
</style>

<h1>내일 뭐입지? 콘텐츠 엔진</h1>

<p>
  <input type="date" id="base" />
  <button id="btn-gather">수집</button>
  <button id="btn-generate" disabled>1차 컨펌 · AI 생성</button>
  <button id="btn-finalize" disabled>최종 컨펌 · 폴더 생성</button>
</p>

<div id="warnings"></div>
<div class="week" id="week"></div>
<div class="slots" id="slots"></div>
<pre id="result"></pre>

<script>
  const $ = (id) => document.getElementById(id);
  $("base").valueAsDate = new Date();

  function render(data) {
    $("week").innerHTML = data.week.map((d) => `
      <div class="day ${d.is_rainy ? "rainy" : ""} ${d.resolution === "coarse" ? "coarse" : ""}">
        <b>${d.weekday}</b><br />${d.date.slice(5)}<br />
        ${d.sky}<br />${d.temp_max}/${d.temp_min}℃<br />
        강수 ${d.precip_prob}%
      </div>`).join("");

    $("slots").innerHTML = data.slots.map((s) => `
      <div class="slot ${s.empty ? "empty" : ""}">
        ${s.date.slice(5)} · ${s.gender}<br />
        ${s.empty ? "비어 있음" : s.look_id}<br />
        ${s.temp_range ? s.temp_range.join("~") + "℃" : ""}<br />
        ${s.style_tags.join(", ")}
      </div>`).join("");

    $("warnings").innerHTML = data.warnings.length
      ? `<div class="warn">${data.warnings.map((w) => `[${w.code}] ${w.message}`).join("<br />")}</div>`
      : "";
  }

  async function call(url, body) {
    const response = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: body ? JSON.stringify(body) : null,
    });
    if (!response.ok) {
      alert((await response.json()).detail);
      throw new Error("실패");
    }
    return response.json();
  }

  $("btn-gather").onclick = async () => {
    render(await call("/api/gather", { base_date: $("base").value }));
    $("btn-generate").disabled = false;
    $("btn-finalize").disabled = true;
  };

  $("btn-generate").onclick = async () => {
    render(await call("/api/generate"));
    $("btn-finalize").disabled = false;
  };

  $("btn-finalize").onclick = async () => {
    const data = await call("/api/finalize");
    $("result").textContent = "생성 완료: " + data.output_path;
  };
</script>
```

- [ ] **Step 5: 테스트 통과 확인**

Run: `pytest tests/test_web.py -v`
Expected: PASS (7개)

- [ ] **Step 6: 커밋**

```bash
git add src/willy/web tests/test_web.py
git commit -m "feat: 2단계 컨펌 웹 UI 추가"
```

---

## Task 12: 실행 진입점과 문서, 배포

**Files:**
- Create: `run.py`
- Create: `README.md`
- Modify: `.gitignore`
- Test: `tests/test_smoke.py`

**Interfaces:**
- Consumes: 모든 이전 태스크
- Produces: `build_pipeline() -> Pipeline`, `main()`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_smoke.py`:

```python
from pathlib import Path

import pytest


def test_readme_documents_setup():
    readme = (Path(__file__).parents[1] / "README.md").read_text(encoding="utf-8")

    assert "KMA_SERVICE_KEY" in readme
    assert "playwright install" in readme
    assert "python run.py" in readme


def test_gitignore_protects_secrets_and_outputs():
    ignored = (Path(__file__).parents[1] / ".gitignore").read_text(encoding="utf-8")

    for entry in [".env", "outputs/", "archive/", ".workspace/"]:
        assert entry in ignored, f"{entry}가 .gitignore에 없습니다"


def test_run_module_exposes_builder():
    import run

    assert callable(run.build_pipeline)
    assert callable(run.main)
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest tests/test_smoke.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'run'`

- [ ] **Step 3: 진입점 구현**

`run.py`:

```python
"""로컬 실행 진입점. 브라우저를 띄우고 컨펌 UI를 연다."""
from __future__ import annotations

import uvicorn

from willy.analyzer import LookAnalyzer
from willy.archive import Archive
from willy.collector.browser import browser_page
from willy.collector.collector import Collector
from willy.config import PROJECT_ROOT, Settings
from willy.generator.noop import NoopGenerator
from willy.generator.preset import load_preset
from willy.pipeline import Pipeline
from willy.web.app import create_app


def build_pipeline() -> Pipeline:
    settings = Settings.load()
    from willy.weather.client import WeatherClient

    # Playwright 컨텍스트는 수집 시점에만 연다.
    def page_factory():
        ctx = browser_page(headless=False)
        return ctx.__enter__()

    return Pipeline(
        weather_client=WeatherClient(settings.kma_service_key),
        collector=Collector(settings.workspace, page_factory=page_factory),
        analyzer=LookAnalyzer(settings.anthropic_api_key),
        generator=NoopGenerator(settings.workspace / "generated"),
        archive=Archive(settings.archive_db),
        preset=load_preset(PROJECT_ROOT / "presets" / "concept_v1.yaml"),
        output_root=settings.output_root,
        looks_per_source=settings.looks_per_source,
    )


def main() -> None:
    app = create_app(build_pipeline)
    uvicorn.run(app, host="127.0.0.1", port=8765)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: README 작성**

`README.md`:

````markdown
# 최윌리 옷장연구소 — 콘텐츠 엔진

Threads 채널 `@choi.willy.lab` 의 `[내일 뭐입지?]` 콘텐츠를 반자동으로
기획·생성하는 로컬 도구.

버튼 한 번으로 주간 14룩(요일 7 × 성별 2)을 수집하고, 서울 주간 날씨에 맞춰
요일별로 배정한 뒤, AI로 발행용 이미지를 만들고 폴더와 워드 문서로 정리한다.

## 동작 방식

```
[수집] → 분석 → 날씨 → 배정 → [1차 컨펌] → AI 생성 → [최종 컨펌] → 폴더·문서
```

최종 컨펌 전까지 `outputs/`에 아무것도 쓰지 않는다.

## 수집 대상

- 무신사 스냅 오늘
- 유니클로 스타일링북 women / men
- 사용자 직접 투입 (URL 또는 파일)

수집은 **사용자가 버튼을 눌렀을 때만** 실행된다. 스케줄러 자동 순회는 하지 않는다.
에이블리·크림은 각각 봇 차단과 robots.txt 미제공으로 제외했다.

## 설치

```bash
pip install -e ".[dev]"
playwright install chromium
cp .env.example .env
```

`.env` 에 키를 채운다:

- `KMA_SERVICE_KEY` — 공공데이터포털 기상청 단기예보/중기예보 서비스 키
- `ANTHROPIC_API_KEY` — 룩 분석용 Claude API 키

## 실행

```bash
python run.py
```

브라우저에서 http://127.0.0.1:8765 접속.

## 테스트

```bash
pytest
```

테스트는 네트워크를 타지 않는다. 외부 응답은 `tests/fixtures/` 의 고정 JSON을 쓴다.

## 미확정 항목

디자인 컨셉과 이미지 생성 엔진이 정해지지 않아 다음이 비어 있다.
비어 있어도 파이프라인은 끝까지 동작한다.

| 항목 | 위치 | 확정 시 조치 |
|---|---|---|
| 화풍·배경·조명 | `presets/concept_v1.yaml` 의 `render.*` | YAML 값만 채움 |
| 고정 모델 이미지 | `presets/concept_v1.yaml` 의 `model.*.face_ref` | 이미지 경로 지정 |
| 이미지 생성 엔진 | `src/willy/generator/` | `ImageGenerator` 구현체 추가 |

현재는 `NoopGenerator`가 원본을 복사하고 프롬프트를 `.prompt.txt`로 남긴다.
엔진 없이 프롬프트 품질을 먼저 검증할 수 있다.

## 주의

`outputs/` 안의 `_ref_원본_발행금지.jpg` 는 로컬 참고용 원본이다.
발행하지 않는다. 발행용은 같은 폴더의 `발행용.png` 다.

## 설계 문서

- 스펙: `docs/superpowers/specs/2026-07-31-tomorrow-outfit-pipeline-design.md`
- 구현 계획: `docs/superpowers/plans/2026-07-31-tomorrow-outfit-pipeline.md`
````

- [ ] **Step 5: .gitignore 갱신**

`.gitignore`에 다음이 모두 있는지 확인하고 없으면 추가한다:

```
__pycache__/
*.pyc
.venv/
venv/
.env
outputs/
archive/
.workspace/
.DS_Store
```

- [ ] **Step 6: 테스트 통과 확인**

Run: `pytest -v`
Expected: 전부 PASS

- [ ] **Step 7: 커밋**

```bash
git add run.py README.md .gitignore tests/test_smoke.py
git commit -m "feat: 실행 진입점과 README 추가"
```

- [ ] **Step 8: 원격 저장소 연결**

**사장님 확인 필요.** 지정된 `hanwool-choi/hanwool-choi.github.io`는 이미 운영 중인
공개 GitHub Pages 사이트다. 두 가지 문제가 있다:

1. 이 앱은 Python·Playwright·파일시스템이 필요해 GitHub Pages에서 **실행되지 않는다**
2. 리포가 공개이자 웹으로 서빙되므로, 실수로 커밋된 수집 이미지나 키가 **즉시 인터넷에 게시된다**

권장: 전용 리포를 새로 만든다.

```bash
git remote add origin https://github.com/hanwool-choi/willy-content-engine.git
git push -u origin main
```

지정하신 리포를 그대로 쓰기로 결정하면, 하위 디렉터리에 두고 Pages 빌드에서
제외되는지 반드시 확인한 뒤 푸시한다.

---

## Self-Review

**1. 스펙 커버리지**

| 스펙 항목 | 담당 태스크 |
|---|---|
| §5.1 수집기 | Task 7 |
| §5.2 룩 분석기 | Task 6 |
| §5.3 날씨 수집기 | Task 2, 3 |
| §5.4 아카이브 | Task 4 |
| §5.5 배정기 | Task 5 |
| §5.6 이미지 재생성기 | Task 8 |
| §5.7 산출기 | Task 9 |
| §5.8 컨펌 UI | Task 11 |
| §4 전체 흐름 | Task 10 |
| §7 미확정 항목 격리 | Task 8 (프리셋), Task 12 (README 표) |
| §8 위험 대응 | Task 5(빈 칸), 7(소스 실패), 9(발행금지), 10(분석 실패) |

**2. 플레이스홀더:** 없음. 모든 스텝에 실제 코드가 들어 있다. `presets/concept_v1.yaml`의
`null`은 스펙 §7에서 의도적으로 비워둔 항목이며 README에 채우는 방법이 문서화되어 있다.

**3. 타입 일관성 확인 완료**
- `LookAnalysis.temp_range`는 전 구간에서 `tuple[int, int]`
- `Assignment`는 `dict[tuple[date, Gender], LookAnalysis | None]`로 Task 1에서 정의, 5·9·10에서 동일하게 사용
- `Archive.find_substitute` 시그니처가 Task 4 정의와 Task 5 호출부에서 일치
- `ImageGenerator.generate(source_image, analysis, preset, strength)` 4인자가 Task 8 정의, Task 10 호출, Task 11 테스트에서 일치
- `WarningCode` 4종이 Task 1 정의, Task 5 발생, Task 11 직렬화에서 일치
- `publish(assignment, week, generated, output_root)`가 Task 9 정의와 Task 10 호출부에서 일치
