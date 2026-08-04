from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from willy.ideas.models import IdeaItem
from willy.web.app import create_app


def idea(**kwargs) -> IdeaItem:
    base = dict(
        source="eyesmag", title="버켄스탁 x 아더에러 협업", url="https://x.test/1"
    )
    base.update(kwargs)
    return IdeaItem(**base)


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

    return TestClient(
        create_app(
            factory,
            ideas_collector=lambda: ([idea(is_hot=True, category="슈즈")], ["vogue"]),
            detail_fetcher=lambda url: f"본문 발췌 {url}",
            ideas_writer=lambda pairs: [
                {"tone": f"톤{i}", "text": f"본문 {i}"} for i in range(3)
            ],
        )
    )


def test_ideas_endpoint_returns_items_and_failures(client: TestClient):
    body = client.post("/api/ideas").json()

    assert body["items"][0]["title"] == "버켄스탁 x 아더에러 협업"
    assert body["items"][0]["is_hot"] is True
    assert body["items"][0]["source_label"] == "아이즈"
    assert body["failed"] == ["vogue"], "실패한 소스를 화면에 알려야 한다"
    assert body["groups"] == {"deal": "할인", "drop": "드랍·신상", "magazine": "매거진"}


def test_idea_items_carry_group_for_filter_chips(client: TestClient):
    body = client.post("/api/ideas").json()

    assert body["items"][0]["group"] == "drop"


def test_texts_endpoint_requires_urls(client: TestClient):
    assert client.post("/api/ideas/texts", json={"urls": []}).status_code == 400


def test_texts_endpoint_needs_ideas_first(client: TestClient):
    response = client.post("/api/ideas/texts", json={"urls": ["https://x.test/1"]})

    assert response.status_code == 409


def test_texts_endpoint_rejects_unknown_urls(client: TestClient):
    """목록에 없는 주소로 상세를 긁게 하면 안 된다."""
    client.post("/api/ideas")

    response = client.post("/api/ideas/texts", json={"urls": ["https://evil.test/x"]})

    assert response.status_code == 400


def test_texts_endpoint_generates_three_tones(client: TestClient):
    client.post("/api/ideas")

    body = client.post("/api/ideas/texts", json={"urls": ["https://x.test/1"]}).json()

    assert len(body["texts"]) == 3
