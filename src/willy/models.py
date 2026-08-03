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
    # 분석 생략 모드에서 소스로 성별을 알 수 없는 룩(무신사 등).
    # 배정 후보에서는 빠지고 풀에만 남는다.
    UNKNOWN = "unknown"


class WarningCode(str, Enum):
    EMPTY_SLOT = "EMPTY_SLOT"
    ARCHIVE_FALLBACK = "ARCHIVE_FALLBACK"
    RAIN_SUBSTITUTE = "RAIN_SUBSTITUTE"
    POOL_TOO_SMALL = "POOL_TOO_SMALL"
    CONDITIONAL_PICK = "CONDITIONAL_PICK"
    AI_FILTERED = "AI_FILTERED"
    ANALYSIS_SKIPPED = "ANALYSIS_SKIPPED"


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
    # CDN 원본 주소. 정적 페이지가 사진을 재업로드하지 않고 이 주소로
    # 바로 띄운다. 캡처로 만든 사진은 없다(None).
    image_url: str | None = None
    raw_meta: dict = field(default_factory=dict)
    collected_at: datetime = field(default_factory=datetime.now)


@dataclass
class LookAnalysis:
    """비전 분석 결과. 배정(temp_range·rain_ok)과 아카이브 폴백에 필요한
    최소 필드만 담는다. 착장 세부 묘사는 원본 사진이 대신한다."""

    look_id: str
    source: str  # "musinsa_snap" | "wear_men" | "uniqlo_women" | ... | "manual"
    gender: Gender
    # 분석 생략 모드에서는 None — 날씨 적합을 판단하지 못했다는 뜻이다.
    temp_range: tuple[int, int] | None
    rain_ok: bool
    season: str  # "spring" | "summer" | "fall" | "winter"
    style_tags: list[str]
    image_path: Path | None = None
    # 무신사가 피드에 섞어 내보내는 자체 AI 코디 판정. 발행 후보에서 뺀다.
    is_ai: bool = False
    # 수집 시점의 원본 페이지 링크. UI 확대 보기에서 출처로 이동할 때 쓴다.
    source_url: str | None = None
    # CDN 원본 주소. 정적 페이지가 핫링크로 띄운다.
    image_url: str | None = None

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
    resolution: str  # "detailed" | "coarse" | "missing"

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


# (date, Gender, pick index 0..picks_per_gender-1)
SlotKey = tuple[date, Gender, int]
Assignment = dict[SlotKey, LookAnalysis | None]
# 조건부 추천 슬롯의 사유. 예: "우천 부적합 — 기온은 적합"
Caveats = dict[SlotKey, str]
