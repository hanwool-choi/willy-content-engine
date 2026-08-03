from pathlib import Path

import pytest


def test_readme_documents_setup():
    readme = (Path(__file__).parents[1] / "README.md").read_text(encoding="utf-8")

    assert "KMA_SERVICE_KEY" in readme
    assert "playwright install" in readme
    assert "python run.py" in readme


def test_gitignore_protects_outputs():
    """.env는 사용자 결정으로 저장소에 포함한다 (비공개 저장소 + 무료 키).

    산출물·아카이브·작업 폴더는 여전히 올리지 않는다.
    """
    ignored = (Path(__file__).parents[1] / ".gitignore").read_text(encoding="utf-8")

    for entry in ["outputs/", "archive/", ".workspace/"]:
        assert entry in ignored, f"{entry}가 .gitignore에 없습니다"


def test_run_module_exposes_builder():
    import run

    assert callable(run.build_pipeline)
    assert callable(run.main)
