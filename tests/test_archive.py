from datetime import date, timedelta
from pathlib import Path

import pytest

from willy.archive import Archive
from willy.models import Gender, LookAnalysis


def make_look(look_id: str, temp_range=(20, 26), rain_ok=True,
              season="summer", gender=Gender.MEN) -> LookAnalysis:
    return LookAnalysis(
        look_id=look_id,
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
