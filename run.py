"""로컬 실행 진입점. 브라우저를 띄우고 컨펌 UI를 연다."""
from __future__ import annotations

import logging

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

from willy.analyzer import LookAnalyzer
from willy.archive import Archive
from willy.collector.browser import browser_page
from willy.collector.collector import Collector
from willy.config import PROJECT_ROOT, Settings
from willy.generator.noop import NoopGenerator
from willy.generator.preset import load_preset
from willy.pipeline import Pipeline
from willy.weather.client import WeatherClient
from willy.weather.openmeteo import OpenMeteoClient
from willy.web.app import create_app

log = logging.getLogger(__name__)


def build_pipeline() -> Pipeline:
    settings = Settings.load()

    def page_factory():
        # browser_page는 컨텍스트매니저다. 그대로 넘기면 collect가 닫아준다.
        return browser_page(headless=False)

    weather = (
        WeatherClient(settings.kma_service_key)
        if settings.kma_service_key
        else OpenMeteoClient()
    )
    log.info(
        "날씨 공급자: %s",
        "기상청(KMA)" if settings.kma_service_key else "Open-Meteo (키 없음)",
    )

    return Pipeline(
        weather_client=weather,
        collector=Collector(settings.workspace, page_factory=page_factory),
        analyzer=LookAnalyzer(settings.anthropic_api_key),
        generator=NoopGenerator(settings.workspace / "generated"),
        archive=Archive(settings.archive_db),
        preset=load_preset(PROJECT_ROOT / "presets" / "concept_v1.yaml"),
        output_root=settings.output_root,
        looks_per_source=settings.looks_per_source,
        horizon_days=settings.horizon_days,
        picks_per_gender=settings.picks_per_gender,
        min_pool_per_gender=settings.min_pool_per_gender,
    )


def main() -> None:
    app = create_app(build_pipeline)
    uvicorn.run(app, host="127.0.0.1", port=8765)


if __name__ == "__main__":
    main()
