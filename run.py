"""로컬 실행 진입점. 브라우저를 띄우고 컨펌 UI를 연다."""
from __future__ import annotations

import logging

import uvicorn

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
    )


def main() -> None:
    app = create_app(build_pipeline)
    uvicorn.run(app, host="127.0.0.1", port=8765)


if __name__ == "__main__":
    main()
