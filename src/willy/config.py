"""설정. 비밀값은 .env에서만 읽는다."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# cwd 기준 탐색은 저장소 밖에서 실행하면 .env를 놓친다. 위치를 못박는다.
load_dotenv(PROJECT_ROOT / ".env")

# 서울 기상청 격자 좌표 / 예보구역 코드
SEOUL_NX = 60
SEOUL_NY = 127
SEOUL_MID_LAND_REG = "11B00000"
SEOUL_MID_TA_REG = "11B10101"

# 서울 위경도 (Open-Meteo용, 키 불필요)
SEOUL_LAT = 37.5665
SEOUL_LON = 126.978

# 소스별 수집량. 무신사가 주력이고(스트릿 톤 다양성), WEAR·유니클로는
# 성별이 URL로 보장되는 안전핀이다.
# 무신사 스냅 피드에는 자체 AI 코디가 섞여 있어(분석에서 걸러냄),
# 걸러진 뒤에도 6장쯤 남도록 여유를 두고 8장을 걷는다.
SOURCE_QUOTAS = {
    "musinsa_snap": 8,
    "wear_men": 2,
    "wear_women": 2,
    "uniqlo_men": 2,
    "uniqlo_women": 2,
}


@dataclass(frozen=True)
class Settings:
    kma_service_key: str
    anthropic_api_key: str
    gemini_api_key: str = ""
    horizon_days: int = 1
    picks_per_gender: int = 2
    # 성별당 이 수에 못 미치면 아카이브에서 유사 룩으로 채운다.
    min_pool_per_gender: int = 4
    output_root: Path = PROJECT_ROOT / "outputs"
    archive_db: Path = PROJECT_ROOT / "archive" / "looks.db"
    workspace: Path = PROJECT_ROOT / ".workspace"

    @classmethod
    def load(cls) -> "Settings":
        return cls(
            kma_service_key=os.environ.get("KMA_SERVICE_KEY", ""),
            anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY", ""),
            gemini_api_key=os.environ.get("GEMINI_API_KEY", ""),
        )


SOURCE_URLS = {
    # /snap/main/today는 무신사 자체 AI 코디로 도배된 랜딩이다(2026-08 확인).
    # 유저 스냅이 모이는 '스냅' 탭을 쓴다. 여기도 AI 코디가 섞여 있어
    # 분석 단계의 is_ai 판정으로 걸러낸다.
    "musinsa_snap": "https://www.musinsa.com/snap/main/snap",
    "uniqlo_women": "https://www.uniqlo.com/kr/ko/stylingbook/stylehint/women",
    "uniqlo_men": "https://www.uniqlo.com/kr/ko/stylingbook/stylehint/men",
    # WEARISTA(user_type=2)의 인기 코디만 걷는다. robots.txt가 코디
    # 목록을 허용하고, 성별이 URL로 갈린다.
    "wear_men": "https://wear.jp/men-coordinate/?type_id=2&user_type=2",
    "wear_women": "https://wear.jp/women-coordinate/?type_id=2&user_type=2",
}
