"""API 키 없이 UI를 클릭해보는 데모 서버.

외부 의존 중 '분석'과 '이미지 생성'만 가짜로 대체한다. 날씨는 실제
Open-Meteo를 호출하고, 룩 사진도 첫 실행 때 실제 수집기로 세 소스에서
받아와 `.demo_cache/`에 캐싱한다. 배정 알고리즘·경고·2단계 컨펌·폴더
산출은 전부 실제 코드 그대로다.

    python demo.py

수집이 실패하면(오프라인, 사이트 구조 변경 등) 단색 자리표시자로 대체해
데모 자체는 계속 뜬다.

주의: 캐시에 담기는 사진은 제3자 저작물이다. `.demo_cache/`는 gitignore
되어 있고 저장소에 올리지 않는다.
"""
from __future__ import annotations

import logging
import struct
import zlib
from datetime import date, datetime
from pathlib import Path

# 사내망처럼 TLS 검사 프록시가 끼어드는 환경에서는 certifi 번들만 믿는
# httpx가 모든 외부 호출에 실패한다. OS 인증서 저장소를 신뢰하도록
# 어떤 HTTP 클라이언트보다 먼저 주입해야 한다.
import truststore

truststore.inject_into_ssl()

import uvicorn

import sys
from pathlib import Path

# 편집 설치(pip install -e .) 없이도 바로 실행되게 한다. pyproject의
# pythonpath 설정은 pytest 전용이라 여기까지 오지 않는다.
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from willy.archive import Archive
from willy.collector.browser import browser_page
from willy.collector.collector import Collector
from willy.collector.sources import SOURCE_SPECS
from willy.config import PROJECT_ROOT, Settings
from willy.generator.noop import NoopGenerator
from willy.generator.preset import load_preset
from willy.models import Gender, LookAnalysis, RawLook
from willy.pipeline import Pipeline
from willy.weather.openmeteo import OpenMeteoClient
from willy.web.app import create_app

log = logging.getLogger("demo")

CACHE = PROJECT_ROOT / ".demo_cache"
LOOKS_DIR = CACHE / "looks"
PORT = 8770

# 분석기가 매길 속성. 실제로는 Claude 비전이 사진을 보고 판정한다.
PROFILES = [
    ((26, 33), False, ["미니멀", "클린핏"]),
    ((25, 31), False, ["아메카지"]),
    ((24, 30), True, ["워크웨어", "실용"]),
    ((27, 34), False, ["시티보이"]),
    ((23, 29), True, ["꾸안꾸"]),
    ((26, 32), False, ["러프", "빈티지"]),
    ((25, 30), False, ["모노톤"]),
    ((28, 34), False, ["리조트"]),
    ((26, 33), False, ["페미닌"]),
    ((24, 30), True, ["시티", "레인"]),
    ((25, 31), False, ["원마일웨어"]),
    ((27, 33), False, ["로맨틱"]),
]

PALETTE = [
    (203, 213, 225), (148, 163, 184), (100, 116, 139), (71, 85, 105),
    (251, 191, 36), (245, 158, 11), (217, 119, 6), (180, 83, 9),
    (167, 139, 250), (139, 92, 246), (52, 211, 153), (16, 185, 129),
]


def solid_png(width: int, height: int, rgb: tuple[int, int, int]) -> bytes:
    """단색 PNG. 수집이 실패했을 때 쓰는 자리표시자."""

    def chunk(tag: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + tag
            + payload
            + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF)
        )

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    row = b"\x00" + bytes(rgb) * width
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(row * height))
        + chunk(b"IEND", b"")
    )


def ensure_cache() -> list[Path]:
    """캐시가 비어 있으면 실제 수집기로 한 번 받아온다."""
    LOOKS_DIR.mkdir(parents=True, exist_ok=True)
    cached = sorted(LOOKS_DIR.glob("*.jpg")) + sorted(LOOKS_DIR.glob("*.png"))
    if cached:
        log.info("캐시된 룩 %d장을 재사용합니다: %s", len(cached), LOOKS_DIR)
        return cached

    log.info("캐시가 비어 실제 수집을 한 번 실행합니다 (브라우저가 뜹니다)")
    try:
        collector = Collector(
            workspace=LOOKS_DIR,
            page_factory=lambda: browser_page(headless=True),
        )
        collector.collect(list(SOURCE_SPECS.values()), limit_per_source=4)
    except Exception:
        log.exception("수집 실패 — 자리표시자로 대체합니다")

    cached = sorted(LOOKS_DIR.glob("*.jpg")) + sorted(LOOKS_DIR.glob("*.png"))
    if cached:
        return cached

    log.warning("수집된 사진이 없어 단색 자리표시자를 만듭니다")
    for index, rgb in enumerate(PALETTE):
        (LOOKS_DIR / f"placeholder-{index:02d}.png").write_bytes(
            solid_png(120, 160, rgb)
        )
    return sorted(LOOKS_DIR.glob("*.png"))


class DemoCollector:
    """수집기 자리. 캐시된 사진을 그대로 돌려준다."""

    def __init__(self, files: list[Path]):
        self._files = files

    def collect(self, sources, limit_per_source: int = 20, quotas=None, exclude_hashes=None) -> list[RawLook]:
        return [
            RawLook(
                look_id=f"look{index:02d}",
                source=self._source_of(path),
                image_path=path,
                capture_method="original_url",
                collected_at=datetime.now(),
            )
            for index, path in enumerate(self._files)
        ]

    @staticmethod
    def _source_of(path: Path) -> str:
        name = path.name
        for key in SOURCE_SPECS:
            if name.startswith(key):
                return key
        return "manual"


class DemoAnalyzer:
    """분석기 자리. 실제로는 비전 모델이 배치 1콜로 착장을 읽는다.

    성별은 소스 URL에서 유추한다. 무신사 스냅은 남녀가 섞여 있어 번갈아
    배정하는데, 사진과 라벨이 어긋날 수 있다 — 데모에만 있는 한계다.
    """

    def __init__(self):
        self._musinsa_turn = 0

    def analyze_batch(self, raw_looks, day) -> list[LookAnalysis]:
        return [self._analyze_one(raw) for raw in raw_looks]

    def _analyze_one(self, raw_look: RawLook) -> LookAnalysis:
        index = int(raw_look.look_id.removeprefix("look"))
        temp_range, rain_ok, tags = PROFILES[index % len(PROFILES)]

        if raw_look.source == "uniqlo_men":
            gender = Gender.MEN
        elif raw_look.source == "uniqlo_women":
            gender = Gender.WOMEN
        else:
            gender = Gender.MEN if self._musinsa_turn % 2 == 0 else Gender.WOMEN
            self._musinsa_turn += 1

        return LookAnalysis(
            look_id=raw_look.look_id,
            gender=gender,
            temp_range=temp_range,
            rain_ok=rain_ok,
            season="summer",
            style_tags=tags,
            image_path=raw_look.image_path,
            source=raw_look.source,
        )


def build_pipeline(files: list[Path]):
    settings = Settings.load()

    def factory() -> Pipeline:
        return Pipeline(
            weather_client=OpenMeteoClient(),  # 실제 호출
            collector=DemoCollector(files),
            analyzer=DemoAnalyzer(),
            generator=NoopGenerator(CACHE / "generated"),
            archive=Archive(CACHE / "archive.db"),
            preset=load_preset(PROJECT_ROOT / "presets" / "concept_v1.yaml"),
            output_root=CACHE / "outputs",
            horizon_days=settings.horizon_days,
            picks_per_gender=settings.picks_per_gender,
        )

    return factory


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    files = ensure_cache()
    log.info("데모 룩 %d장 준비됨", len(files))
    log.info("산출물 위치: %s", CACHE / "outputs")
    uvicorn.run(create_app(build_pipeline(files)), host="127.0.0.1", port=PORT)


if __name__ == "__main__":
    main()
