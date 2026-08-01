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
        path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"gen")  # 완전한 PNG 매직바이트
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

    # 발행용 이미지가 실제로 복사되었는지. 픽스처 바이트가 깨져 있으면
    # publish가 조용히 건너뛰므로 여기서 잡는다.
    published = list(root.glob("*/*/발행용.*"))
    assert published, "발행용 이미지가 하나도 만들어지지 않았다"

    # 사용 이력이 남아야 4주 내 재등장이 막힌다.
    used = pipeline.archive.find_substitute(
        temp=26.0,
        rain_ok=True,
        season="summer",
        gender=Gender.MEN,
        as_of=date(2026, 8, 10),  # 배정 주간 직후 기준으로 고정한다
    )
    assert used is None


def test_gather_skips_look_whose_analysis_fails(pipeline: Pipeline):
    """룩 한 장의 분석 실패가 주 전체를 막지 않는다."""
    working = pipeline.analyzer

    class FlakyAnalyzer:
        def analyze(self, raw_look):
            if raw_look.look_id == "L3":
                raise ValueError("분석 결과를 파싱할 수 없습니다")
            return working.analyze(raw_look)

    pipeline.analyzer = FlakyAnalyzer()

    state = pipeline.gather(base_date=date(2026, 8, 3))

    assert len(state.looks) == 13  # 수집 14개 중 1개만 탈락
    assert all(look.look_id != "L3" for look in state.looks)


def test_generate_images_skips_slot_whose_generation_fails(pipeline: Pipeline):
    """이미지 한 장의 생성 실패가 나머지 슬롯을 막지 않는다."""
    working = pipeline.generator

    class FlakyGenerator:
        def __init__(self):
            self.calls = 0

        def generate(self, source_image, analysis, preset, strength):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("이미지 엔진 오류")
            return working.generate(source_image, analysis, preset, strength)

    pipeline.generator = FlakyGenerator()

    state = pipeline.gather(base_date=date(2026, 8, 3))
    state = pipeline.generate_images(state)

    filled = sum(1 for value in state.assignment.values() if value is not None)
    assert filled > 1
    assert len(state.generated) == filled - 1  # 실패한 한 장만 빠진다


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
