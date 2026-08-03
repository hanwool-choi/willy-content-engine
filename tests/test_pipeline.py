from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from willy.models import WarningCode, DayWeather, Gender, LookAnalysis, RawLook
from willy.pipeline import Pipeline


class FakeWeather:
    def __init__(self, precip_prob: int = 10):
        self.precip_prob = precip_prob

    def get_week_forecast(self, base_date: date, days: int = 7) -> list[DayWeather]:
        out = []
        for i in range(days):
            d = base_date + timedelta(days=i)
            out.append(
                DayWeather(
                    date=d, weekday_ko="월화수목금토일"[d.weekday()], temp_max=29,
                    temp_min=24, precip_prob=self.precip_prob, sky="맑음",
                    resolution="detailed",
                )
            )
        return out


class FakeCollector:
    def __init__(self, workspace: Path, count: int = 14):
        self.workspace = workspace
        workspace.mkdir(parents=True, exist_ok=True)
        self.count = count
        self.last_quotas = None

    def collect(self, sources, limit_per_source=20, quotas=None):
        self.last_quotas = quotas
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
    def __init__(self, rain_ok: bool = True, ai_ids: set[str] | None = None):
        self.rain_ok = rain_ok
        self.ai_ids = ai_ids or set()
        self.last_day = None
        self.calls = 0

    def analyze_batch(
        self, raw_looks: list[RawLook], day: DayWeather
    ) -> list[LookAnalysis]:
        self.calls += 1
        self.last_day = day
        out = []
        for raw in raw_looks:
            index = int(raw.look_id[1:])
            out.append(
                LookAnalysis(
                    look_id=raw.look_id,
                    source=raw.source,
                    gender=Gender.MEN if index % 2 == 0 else Gender.WOMEN,
                    temp_range=(24, 30),
                    rain_ok=self.rain_ok,
                    season="summer",
                    style_tags=["미니멀"],
                    image_path=raw.image_path,
                    is_ai=raw.look_id in self.ai_ids,
                )
            )
        return out


class FakeGenerator:
    def __init__(self, out: Path):
        self.out = out
        out.mkdir(parents=True, exist_ok=True)
        self.calls = 0

    def generate(self, source_image, analysis, preset, strength, day=None):
        self.calls += 1
        path = self.out / f"{analysis.look_id}.png"
        path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"gen")  # 완전한 PNG 매직바이트
        return path


def make_pipeline(tmp_path: Path, **overrides) -> Pipeline:
    from willy.archive import Archive
    from willy.generator.preset import load_preset

    preset = load_preset(Path(__file__).parents[1] / "presets" / "concept_v1.yaml")
    kwargs = dict(
        weather_client=FakeWeather(),
        collector=FakeCollector(tmp_path / "ws"),
        analyzer=FakeAnalyzer(),
        generator=FakeGenerator(tmp_path / "gen"),
        archive=Archive(tmp_path / "a.db"),
        preset=preset,
        output_root=tmp_path / "outputs",
    )
    kwargs.update(overrides)
    return Pipeline(**kwargs)


@pytest.fixture
def pipeline(tmp_path: Path) -> Pipeline:
    return make_pipeline(tmp_path)


def test_gather_produces_week_and_assignment(pipeline: Pipeline):
    state = pipeline.gather(base_date=date(2026, 8, 3))

    # 기본 설정은 내일 하루, 성별당 2픽 = 4칸이다.
    assert len(state.week) == 1
    assert state.week[0].date == date(2026, 8, 4)  # base_date(8/3)의 다음날
    assert len(state.assignment) == 4


def test_gather_analyzes_in_a_single_batch_with_weather(pipeline: Pipeline):
    """분석은 배치 1회 호출이고, 내일 날씨가 함께 전달된다."""
    state = pipeline.gather(base_date=date(2026, 8, 3))

    assert pipeline.analyzer.calls == 1
    assert pipeline.analyzer.last_day == state.week[0]


def test_gather_passes_source_quotas_to_collector(tmp_path: Path):
    quotas = {"musinsa_snap": 6, "uniqlo_men": 2, "uniqlo_women": 2}
    pipeline = make_pipeline(tmp_path, source_quotas=quotas)

    pipeline.gather(base_date=date(2026, 8, 3))

    assert pipeline.collector.last_quotas == quotas


def test_gather_fails_loudly_when_batch_analysis_fails(pipeline: Pipeline):
    """배치 분석 실패는 부분 성공이 없다. 조용히 넘어가지 않는다."""

    class BrokenAnalyzer:
        def analyze_batch(self, raw_looks, day):
            raise ValueError("분석 결과를 파싱할 수 없습니다")

    pipeline.analyzer = BrokenAnalyzer()

    with pytest.raises(ValueError, match="분석 결과를 파싱"):
        pipeline.gather(base_date=date(2026, 8, 3))


def test_gather_excludes_ai_generated_looks(tmp_path: Path):
    """AI 생성으로 판정된 이미지는 발행 후보·아카이브에서 모두 뺀다.

    무신사가 자체 AI 코디를 스냅 피드에 섞어 내보내는데, 남의 AI 이미지를
    재생성 원본으로 쓰면 채널 정체성도 저작권도 애매해진다.
    """
    pipeline = make_pipeline(
        tmp_path, analyzer=FakeAnalyzer(ai_ids={"L0", "L2"})
    )

    state = pipeline.gather(base_date=date(2026, 8, 3))

    ids = {look.look_id for look in state.looks}
    assert "L0" not in ids and "L2" not in ids
    assert pipeline.archive.count() == 12  # 14 - AI 2장
    assert WarningCode.AI_FILTERED in [w.code for w in state.warnings]


def test_gather_does_not_write_to_outputs(pipeline: Pipeline, tmp_path: Path):
    """1차 컨펌 전에는 outputs/에 아무것도 쓰지 않는다."""
    pipeline.gather(base_date=date(2026, 8, 3))

    assert not (tmp_path / "outputs").exists()


def test_gather_saves_looks_to_archive(pipeline: Pipeline):
    state = pipeline.gather(base_date=date(2026, 8, 3))

    assert pipeline.archive.count() == 14
    assert state.assignment is not None


def test_rainy_day_fills_slots_conditionally_with_caveats(tmp_path: Path):
    """전원 우천 부적합이어도 빈손이 아니라 조건부 추천 + 사유가 나온다."""
    pipeline = make_pipeline(
        tmp_path,
        weather_client=FakeWeather(precip_prob=78),
        analyzer=FakeAnalyzer(rain_ok=False),
    )

    state = pipeline.gather(base_date=date(2026, 8, 3))

    filled = [v for v in state.assignment.values() if v is not None]
    assert filled, "조건부 추천으로도 채워지지 않았다"
    assert state.caveats, "조건부 추천 사유가 비어 있다"
    assert any("우천" in reason for reason in state.caveats.values())


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
    assert (root / "_요약.docx").exists()

    # 발행용 이미지가 실제로 복사되었는지. 픽스처 바이트가 깨져 있으면
    # publish가 조용히 건너뛰므로 여기서 잡는다.
    published = list(root.glob("*/*/발행용*.*"))  # 픽이 여럿이면 발행용_1, 발행용_2
    assert published, "발행용 이미지가 하나도 만들어지지 않았다"

    # 사용 이력이 남아야 4주 내 재등장이 막힌다. 하루치만 배정하므로 수집분
    # 대부분은 미사용으로 남는 게 정상이고, '배정된 것'만 후보에서 빠져야 한다.
    assigned_ids = {
        look.look_id for look in state.assignment.values() if look is not None
    }
    assert assigned_ids, "배정된 룩이 하나도 없다"

    unassigned_ids = {look.look_id for look in state.looks} - assigned_ids
    leftover = pipeline.archive.find_substitute(
        temp=26.0,
        rain_ok=True,
        season="summer",
        gender=Gender.MEN,
        as_of=date(2026, 8, 10),  # 배정일 직후 기준으로 고정한다
        exclude_ids=unassigned_ids,  # 미배정분을 빼면 사용 처리된 것만 남는다
    )
    assert leftover is None, f"사용 처리된 룩이 다시 후보로 나왔다: {leftover}"


def test_generate_images_skips_slot_whose_generation_fails(pipeline: Pipeline):
    """이미지 한 장의 생성 실패가 나머지 슬롯을 막지 않는다."""
    working = pipeline.generator

    class FlakyGenerator:
        def __init__(self):
            self.calls = 0

        def generate(self, source_image, analysis, preset, strength, day=None):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("이미지 엔진 오류")
            return working.generate(source_image, analysis, preset, strength, day)

    pipeline.generator = FlakyGenerator()

    state = pipeline.gather(base_date=date(2026, 8, 3))
    state = pipeline.generate_images(state)

    filled = sum(1 for value in state.assignment.values() if value is not None)
    assert filled > 1
    assert len(state.generated) == filled - 1  # 실패한 한 장만 빠진다


def test_full_flow_with_insufficient_looks_still_completes(tmp_path: Path):
    """룩이 모자라도 흐름은 끝까지 간다. 빈 칸 + 경고로 처리."""
    pipeline = make_pipeline(
        tmp_path, collector=FakeCollector(tmp_path / "ws", count=2)
    )

    state = pipeline.gather(base_date=date(2026, 8, 3))
    assert state.warnings  # POOL_TOO_SMALL 등

    state = pipeline.generate_images(state)
    root = pipeline.finalize(state)
    assert root.exists()


def _stub_looks(pipeline: Pipeline, count: int) -> None:
    """수집분을 count장으로 줄인다. 풀이 얇은 상황을 만든다."""
    pipeline.collector.count = count


def test_gather_tops_up_a_thin_pool_from_the_archive(pipeline: Pipeline):
    """수집이 적게 되면 아카이브의 비슷한 룩으로 채운다.

    외부를 다시 두드리지도, 비전 분석을 새로 하지도 않는다.
    """
    # 먼저 한 번 돌려 아카이브를 채운다.
    pipeline.gather(base_date=date(2026, 8, 3))

    # 이번엔 수집이 2장뿐인 상황
    _stub_looks(pipeline, 2)
    state = pipeline.gather(base_date=date(2026, 8, 3))

    assert len(state.looks) > 2, "아카이브에서 보충되지 않았다"
    codes = [w.code for w in state.warnings]
    assert WarningCode.ARCHIVE_FALLBACK in codes


def test_top_up_respects_the_minimum_per_gender(pipeline: Pipeline):
    """성별당 min_pool_per_gender까지만 채운다. 무한정 끌어오지 않는다."""
    pipeline.gather(base_date=date(2026, 8, 3))

    _stub_looks(pipeline, 0)
    state = pipeline.gather(base_date=date(2026, 8, 3))

    for gender in (Gender.MEN, Gender.WOMEN):
        count = sum(1 for look in state.looks if look.gender == gender)
        assert count <= pipeline.min_pool_per_gender


def test_top_up_does_not_duplicate_looks(pipeline: Pipeline):
    """보충한 룩이 이미 수집분에 있는 것과 겹치면 안 된다."""
    pipeline.gather(base_date=date(2026, 8, 3))

    _stub_looks(pipeline, 3)
    state = pipeline.gather(base_date=date(2026, 8, 3))

    ids = [look.look_id for look in state.looks]
    assert len(ids) == len(set(ids)), f"중복: {ids}"


def test_no_top_up_when_the_pool_is_already_full(pipeline: Pipeline):
    """풀이 충분하면 아카이브를 건드리지 않는다."""
    state = pipeline.gather(base_date=date(2026, 8, 3))

    codes = [w.code for w in state.warnings]
    assert WarningCode.ARCHIVE_FALLBACK not in codes
