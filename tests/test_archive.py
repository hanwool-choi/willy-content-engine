import sqlite3
from datetime import date, timedelta
from pathlib import Path

import pytest

from willy.archive import Archive
from willy.models import Gender, LookAnalysis


def make_look(look_id: str, temp_range=(20, 26), rain_ok=True,
              season="summer", gender=Gender.MEN,
              source="musinsa_snap") -> LookAnalysis:
    return LookAnalysis(
        look_id=look_id,
        source=source,
        gender=gender,
        sleeve="short",
        outer=None,
        layers=1,
        fabric_weight="light",
        coverage="mid",
        temp_range=temp_range,
        rain_ok=rain_ok,
        season=season,
        style_tags=["미니멀"],
        palette=["ecru"],
        image_path=Path(f"/tmp/{look_id}.jpg"),
    )


@pytest.fixture
def archive(tmp_path: Path) -> Archive:
    return Archive(tmp_path / "looks.db")


def test_save_then_find_returns_look(archive: Archive):
    archive.save(make_look("a"))

    found = archive.find_substitute(
        temp=23.0, rain_ok=True, season="summer", gender=Gender.MEN
    )
    assert found is not None
    assert found.look_id == "a"
    assert found.temp_range == (20, 26)


def test_find_respects_temp_window_of_three_degrees(archive: Archive):
    archive.save(make_look("far", temp_range=(0, 5)))  # 중앙값 2.5

    # 23도와는 20도 넘게 차이나므로 후보가 아니다.
    assert archive.find_substitute(
        temp=23.0, rain_ok=True, season="summer", gender=Gender.MEN
    ) is None


def test_find_requires_rain_ok_match(archive: Archive):
    archive.save(make_look("dry", rain_ok=False))

    assert archive.find_substitute(
        temp=23.0, rain_ok=True, season="summer", gender=Gender.MEN
    ) is None


def test_find_requires_same_season_and_gender(archive: Archive):
    archive.save(make_look("winter_look", season="winter"))
    archive.save(make_look("women_look", gender=Gender.WOMEN))

    assert archive.find_substitute(
        temp=23.0, rain_ok=True, season="summer", gender=Gender.MEN
    ) is None


def test_find_excludes_look_used_within_four_weeks(archive: Archive):
    archive.save(make_look("recent"))
    archive.mark_used("recent", used_on=date.today() - timedelta(days=10))

    assert archive.find_substitute(
        temp=23.0, rain_ok=True, season="summer", gender=Gender.MEN
    ) is None


def test_find_allows_look_used_long_ago(archive: Archive):
    archive.save(make_look("old"))
    archive.mark_used("old", used_on=date.today() - timedelta(days=40))

    found = archive.find_substitute(
        temp=23.0, rain_ok=True, season="summer", gender=Gender.MEN
    )
    assert found is not None
    assert found.look_id == "old"


def test_find_prefers_closest_temperature(archive: Archive):
    archive.save(make_look("near", temp_range=(22, 24)))   # 중앙값 23
    archive.save(make_look("further", temp_range=(24, 26)))  # 중앙값 25

    found = archive.find_substitute(
        temp=23.0, rain_ok=True, season="summer", gender=Gender.MEN
    )
    assert found.look_id == "near"


def test_save_is_idempotent(archive: Archive):
    archive.save(make_look("dup"))
    archive.save(make_look("dup"))

    assert archive.count() == 1


def test_find_includes_candidate_at_exact_window_edge(archive: Archive):
    """정확히 3.0℃ 차이는 포함이다. <= 를 < 로 바꾸면 실패해야 한다."""
    archive.save(make_look("edge", temp_range=(23, 29)))  # 중앙값 26.0

    found = archive.find_substitute(
        temp=23.0, rain_ok=True, season="summer", gender=Gender.MEN
    )

    assert found is not None
    assert found.look_id == "edge"


def test_find_excludes_candidate_just_outside_window(archive: Archive):
    archive.save(make_look("outside", temp_range=(23, 30)))  # 중앙값 26.5, 거리 3.5

    assert archive.find_substitute(
        temp=23.0, rain_ok=True, season="summer", gender=Gender.MEN
    ) is None


def test_find_excludes_look_used_exactly_four_weeks_ago(archive: Archive):
    """정확히 28일 전 사용도 제외다. >= 를 > 로 바꾸면 실패해야 한다."""
    archive.save(make_look("boundary"))
    archive.mark_used("boundary", used_on=date.today() - timedelta(days=28))

    assert archive.find_substitute(
        temp=23.0, rain_ok=True, season="summer", gender=Gender.MEN
    ) is None


def test_find_with_rain_ok_none_ignores_rain_constraint(archive: Archive):
    """rain_ok=None이면 우천 가능 룩도 후보다. 맑은 날 폴백이 이 경로를 쓴다."""
    archive.save(make_look("rain_capable", rain_ok=True))

    assert archive.find_substitute(
        temp=23.0, rain_ok=None, season="summer", gender=Gender.MEN
    ) is not None
    # rain_ok=False를 명시하면 같은 룩이 걸러진다
    assert archive.find_substitute(
        temp=23.0, rain_ok=False, season="summer", gender=Gender.MEN
    ) is None


def test_find_honours_exclude_ids(archive: Archive):
    archive.save(make_look("first"))
    archive.save(make_look("second"))

    first = archive.find_substitute(
        temp=23.0, rain_ok=True, season="summer", gender=Gender.MEN
    )
    second = archive.find_substitute(
        temp=23.0, rain_ok=True, season="summer", gender=Gender.MEN,
        exclude_ids={first.look_id},
    )

    assert second is not None
    assert second.look_id != first.look_id


def test_find_substitute_honours_injected_clock(archive: Archive):
    """as_of가 없으면 오늘 기준. 있으면 그 시점 기준으로 4주를 센다."""
    archive.save(make_look("old"))
    archive.mark_used("old", used_on=date(2026, 8, 3))

    # 사용 직후 시점에서는 제외된다
    assert archive.find_substitute(
        temp=23.0, rain_ok=True, season="summer", gender=Gender.MEN,
        as_of=date(2026, 8, 10),
    ) is None
    # 4주가 지난 시점에서는 다시 후보가 된다
    assert archive.find_substitute(
        temp=23.0, rain_ok=True, season="summer", gender=Gender.MEN,
        as_of=date(2026, 9, 30),
    ) is not None


def test_find_breaks_ties_deterministically(archive: Archive):
    """거리가 같으면 look_id 순으로 고정한다. 파이프라인 재현성에 필요하다."""
    archive.save(make_look("bbb", temp_range=(20, 26)))  # 중앙값 23, 거리 0
    archive.save(make_look("aaa", temp_range=(20, 26)))  # 동일 거리

    picks = {
        archive.find_substitute(
            temp=23.0, rain_ok=True, season="summer", gender=Gender.MEN
        ).look_id
        for _ in range(5)
    }

    assert picks == {"aaa"}


def test_close_releases_the_connection(tmp_path: Path):
    archive = Archive(tmp_path / "a.db")
    archive.save(make_look("x"))

    archive.close()

    with pytest.raises(sqlite3.ProgrammingError):
        archive.count()


def test_source_round_trips_through_save_and_find(archive: Archive):
    archive.save(make_look("src_look", source="uniqlo_women"))

    found = archive.find_substitute(
        temp=23.0, rain_ok=True, season="summer", gender=Gender.MEN
    )

    assert found is not None
    assert found.source == "uniqlo_women"


def test_archive_migrates_db_missing_source_column(tmp_path: Path):
    """이전 실행이 만든 archive/looks.db에는 source 컬럼이 없다.

    CREATE TABLE IF NOT EXISTS는 기존 테이블을 건드리지 않으므로, __init__이
    스스로 ALTER TABLE로 보강해야 한다. 이걸 빼먹으면 사장님의 둘째 주에
    바로 터진다.
    """
    db_path = tmp_path / "looks.db"

    # 먼저 정상적으로 만든 뒤, 마치 구버전 스키마인 것처럼 컬럼을 제거한다.
    bootstrap = Archive(db_path)
    bootstrap.save(make_look("pre_existing"))
    bootstrap._conn.execute("ALTER TABLE looks DROP COLUMN source")
    bootstrap._conn.commit()
    bootstrap.close()

    # 컬럼 없는 상태에서 새로 여는 것이 마이그레이션 가드가 검증할 지점이다.
    migrated = Archive(db_path)

    # 새 컬럼이 생기고, 기존 행도 기본값으로 채워져 조회가 계속 동작해야 한다.
    columns = {row[1] for row in migrated._conn.execute("PRAGMA table_info(looks)")}
    assert "source" in columns

    migrated.save(make_look("post_migration", source="uniqlo_men"))
    found = migrated.find_substitute(
        temp=23.0, rain_ok=True, season="summer", gender=Gender.MEN,
        exclude_ids={"pre_existing"},
    )
    assert found is not None
    assert found.look_id == "post_migration"
    assert found.source == "uniqlo_men"
