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


def test_gather_resets_generated_flag(client: TestClient):
    """다시 수집하면 이전 실행의 생성 컨펌이 남아 있으면 안 된다.

    남아 있으면 사장님이 새 주차의 이미지를 보지도 않고 최종 컨펌이 통과한다.
    """
    client.post("/api/gather", json={"base_date": "2026-08-03"})
    client.post("/api/generate")

    # 새 주차를 수집하면 생성 단계를 다시 거쳐야 한다
    client.post("/api/gather", json={"base_date": "2026-08-10"})

    assert client.post("/api/finalize").status_code == 409
