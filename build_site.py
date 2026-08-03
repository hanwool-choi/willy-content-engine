"""매일 아침 배치 진입점. 수집·분석·텍스트 생성 후 정적 보드를 만든다.

    python build_site.py [출력디렉터리]

GitHub Actions가 이걸 돌리고 결과를 Pages로 게시한다. 서버를 띄우지
않으므로 브라우저 조작 없이 한 번에 끝난다.
"""
from __future__ import annotations

import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# 사내망처럼 TLS 검사 프록시가 끼어드는 환경 대응. 어떤 HTTP 클라이언트보다
# 먼저 주입해야 한다.
import truststore

truststore.inject_into_ssl()

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from willy.analyzer import GeminiAnalyzer, LookAnalyzer
from willy.archive import Archive
from willy.collector.browser import browser_page
from willy.collector.collector import Collector
from willy.config import PROJECT_ROOT, Settings
from willy.generator.noop import NoopGenerator
from willy.generator.preset import load_preset
from willy.pipeline import Pipeline
from willy.publisher.site import render_site
from willy.texter import TextWriter
from willy.weather.client import WeatherClient
from willy.weather.openmeteo import OpenMeteoClient

log = logging.getLogger("build_site")

KST = timezone(timedelta(hours=9))


def build_pipeline(settings: Settings) -> Pipeline:
    weather = (
        WeatherClient(settings.kma_service_key)
        if settings.kma_service_key
        else OpenMeteoClient()
    )
    log.info(
        "날씨 공급자: %s",
        "기상청(KMA)" if settings.kma_service_key else "Open-Meteo (키 없음)",
    )

    if settings.anthropic_api_key:
        analyzer = LookAnalyzer(settings.anthropic_api_key)
        log.info("분석 공급자: Claude")
    elif settings.gemini_api_key:
        analyzer = GeminiAnalyzer(settings.gemini_api_key)
        log.info("분석 공급자: Gemini")
    else:
        analyzer = LookAnalyzer("")
        log.warning("분석 키가 없습니다. 분석 생략 모드로 떨어집니다")

    return Pipeline(
        weather_client=weather,
        collector=Collector(
            settings.workspace, page_factory=lambda: browser_page(headless=True)
        ),
        analyzer=analyzer,
        texter=TextWriter(settings.gemini_api_key) if settings.gemini_api_key else None,
        generator=NoopGenerator(settings.workspace / "generated"),
        archive=Archive(settings.archive_db),
        preset=load_preset(PROJECT_ROOT / "presets" / "concept_v1.yaml"),
        output_root=settings.output_root,
        horizon_days=settings.horizon_days,
        picks_per_gender=settings.picks_per_gender,
        min_pool_per_gender=settings.min_pool_per_gender,
    )


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s %(name)s: %(message)s"
    )
    out_dir = Path(sys.argv[1] if len(sys.argv) > 1 else "site")
    out_dir.mkdir(parents=True, exist_ok=True)

    settings = Settings.load()
    pipeline = build_pipeline(settings)

    # 배치는 한국 시간 아침에 돈다. 러너는 UTC라 기준일을 명시해야
    # '내일'이 하루 밀리지 않는다.
    today_kst = datetime.now(KST).date()
    log.info("기준일(KST): %s — 계획 대상은 다음날", today_kst)

    state = pipeline.gather(base_date=today_kst)
    log.info(
        "수집 %d장 / 배정 %d칸",
        len(state.looks),
        sum(1 for v in state.assignment.values() if v is not None),
    )

    texts = pipeline.write_texts(state)
    log.info("텍스트 %d종 생성", len(texts))

    html = render_site(state, texts, datetime.now(KST))
    (out_dir / "index.html").write_text(html, encoding="utf-8")
    # Pages가 _로 시작하는 경로를 Jekyll로 처리하지 않게 한다.
    (out_dir / ".nojekyll").write_text("", encoding="utf-8")

    log.info("정적 보드 생성 완료: %s", out_dir / "index.html")
    pipeline.archive.close()


if __name__ == "__main__":
    main()
