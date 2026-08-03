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
    assert len(body["week"]) == 1   # 내일 하루
    assert len(body["slots"]) == 4  # 성별당 2픽


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


def test_gather_returns_pool_with_image_urls(client: TestClient):
    """수집 결과를 이미지로 확인할 수 있어야 한다. 텍스트만으로는 룩을 못 고른다."""
    body = client.post("/api/gather", json={"base_date": "2026-08-03"}).json()

    assert body["pool"], "수집된 룩 목록이 비어 있다"
    first = body["pool"][0]
    assert first["image_url"] == f"/api/image/{first['look_id']}"
    assert any(entry["assigned"] for entry in body["pool"])


def test_slots_carry_image_urls(client: TestClient):
    body = client.post("/api/gather", json={"base_date": "2026-08-03"}).json()

    filled = [s for s in body["slots"] if not s["empty"]]
    assert filled
    assert all(s["image_url"] for s in filled)
    assert all(s["generated_url"] is None for s in filled)  # 아직 생성 전


def test_generated_urls_appear_after_first_confirmation(client: TestClient):
    client.post("/api/gather", json={"base_date": "2026-08-03"})
    body = client.post("/api/generate").json()

    filled = [s for s in body["slots"] if not s["empty"]]
    assert any(s["generated_url"] for s in filled)


def test_image_endpoint_serves_a_collected_look(client: TestClient):
    body = client.post("/api/gather", json={"base_date": "2026-08-03"}).json()
    look_id = body["pool"][0]["look_id"]

    response = client.get(f"/api/image/{look_id}")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/")


def test_generated_endpoint_serves_the_generated_image(client: TestClient):
    client.post("/api/gather", json={"base_date": "2026-08-03"})
    body = client.post("/api/generate").json()
    slot = next(s for s in body["slots"] if s["generated_url"])

    response = client.get(slot["generated_url"])

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/")


def test_image_endpoint_rejects_unknown_id(client: TestClient):
    client.post("/api/gather", json={"base_date": "2026-08-03"})

    assert client.get("/api/image/nope").status_code == 404


def test_image_endpoint_does_not_serve_arbitrary_paths(client: TestClient):
    """URL 조각이 파일 경로로 해석되면 안 된다."""
    client.post("/api/gather", json={"base_date": "2026-08-03"})

    for probe in ("..%2F..%2Fetc%2Fpasswd", "....//....//etc/passwd", "%2Fetc%2Fpasswd"):
        assert client.get(f"/api/image/{probe}").status_code in (404, 422)


def test_image_endpoint_before_gather_is_404(client: TestClient):
    assert client.get("/api/image/L0").status_code == 404


def test_style_tags_are_escaped_in_the_page(client: TestClient):
    """비전 모델이 만든 값이 그대로 실행되면 2단계 컨펌이 무의미해진다.

    index.html이 esc()로 감싸는지 소스에서 확인한다. 값 자체는 API가
    그대로 실어 나르는 게 맞고, 위험은 렌더링 시점에 있다.
    """
    page = client.get("/").text

    assert "const esc =" in page, "이스케이프 헬퍼가 없다"
    for expression in (
        "p.style_tags.map",
        "s.style_tags.map",
        "w.message",
        "sourceLabel(p.source)",
    ):
        occurrences = [
            line for line in page.splitlines() if expression in line
        ]
        assert occurrences, f"{expression} 를 찾지 못했다"
        assert all(
            "esc(" in line or "map(esc)" in line for line in occurrences
        ), f"{expression} 가 이스케이프되지 않았다: {occurrences}"
    # 조건부 추천 사유도 모델 산출값이다.
    assert "esc(s.caveat)" in page, "caveat이 이스케이프되지 않았다"


def test_pool_source_badges_and_breakdown_render(client: TestClient):
    """카드 배지와 소스별 집계 요약이 실제 화면 데이터로 채워지는지 확인한다."""
    page = client.get("/").text

    assert "sourceLabel" in page
    assert "무신사" in page and "유니클로W" in page and "유니클로M" in page
    assert 'id="pool-sources"' in page


def test_pool_entries_carry_source(client: TestClient):
    """출처 배지와 소스별 집계는 payload의 source 필드에서 나온다."""
    body = client.post("/api/gather", json={"base_date": "2026-08-03"}).json()

    assert body["pool"], "수집된 룩 목록이 비어 있다"
    assert all(entry["source"] for entry in body["pool"])
    # FakeCollector는 모든 룩을 musinsa_snap으로 수집한다.
    assert {entry["source"] for entry in body["pool"]} == {"musinsa_snap"}


def test_filled_slots_carry_source(client: TestClient):
    body = client.post("/api/gather", json={"base_date": "2026-08-03"}).json()

    filled = [s for s in body["slots"] if not s["empty"]]
    assert filled
    assert all(s["source"] for s in filled)


def test_regather_closes_the_previous_archive(client: TestClient):
    """새로 수집할 때 이전 실행의 연결을 닫고 새 파이프라인으로 간다."""
    first = client.post("/api/gather", json={"base_date": "2026-08-03"})
    second = client.post("/api/gather", json={"base_date": "2026-08-10"})

    assert first.status_code == 200
    assert second.status_code == 200
    assert client.post("/api/generate").status_code == 200


def test_gather_rejects_concurrent_run(tmp_path: Path):
    """수집이 도는 동안 또 수집을 요청하면 409로 거부한다.

    수집 한 번에 비전 API 호출이 12번 붙는다. 진행 표시를 못 본
    사용자가 버튼이나 새 탭에서 거듭 누르면 호출 한도만 태운다.
    """
    import threading

    from tests.test_pipeline import (
        FakeAnalyzer,
        FakeCollector,
        FakeGenerator,
        FakeWeather,
    )
    from willy.archive import Archive
    from willy.generator.preset import load_preset
    from willy.pipeline import Pipeline

    entered = threading.Event()
    release = threading.Event()

    class SlowCollector(FakeCollector):
        def collect(self, *args, **kwargs):
            entered.set()
            assert release.wait(timeout=5), "테스트가 release를 놓쳤습니다"
            return super().collect(*args, **kwargs)

    preset = load_preset(Path(__file__).parents[1] / "presets" / "concept_v1.yaml")

    def factory() -> Pipeline:
        return Pipeline(
            weather_client=FakeWeather(),
            collector=SlowCollector(tmp_path / "ws"),
            analyzer=FakeAnalyzer(),
            generator=FakeGenerator(tmp_path / "gen"),
            archive=Archive(tmp_path / "a.db"),
            preset=preset,
            output_root=tmp_path / "outputs",
        )

    client = TestClient(create_app(factory))
    results = {}

    def first_gather():
        results["first"] = client.post(
            "/api/gather", json={"base_date": "2026-08-03"}
        ).status_code

    worker = threading.Thread(target=first_gather)
    worker.start()
    try:
        assert entered.wait(timeout=5), "첫 수집이 시작되지 않았습니다"

        second = client.post("/api/gather", json={"base_date": "2026-08-03"})
        assert second.status_code == 409
    finally:
        release.set()
        worker.join(timeout=10)

    assert results["first"] == 200
    # 첫 수집이 끝났으니 다시 수집할 수 있어야 한다.
    release.set()
    entered.clear()
    assert (
        client.post("/api/gather", json={"base_date": "2026-08-03"}).status_code == 200
    )
