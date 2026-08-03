from pathlib import Path

import pytest


def test_readme_documents_setup():
    readme = (Path(__file__).parents[1] / "README.md").read_text(encoding="utf-8")

    assert "KMA_SERVICE_KEY" in readme
    assert "playwright install" in readme
    assert "python run.py" in readme


def test_gitignore_protects_secrets_and_outputs():
    """공개 저장소로 갈 수 있으므로 키 파일은 반드시 추적에서 빠져야 한다."""
    ignored = (Path(__file__).parents[1] / ".gitignore").read_text(encoding="utf-8")

    for entry in [".env", "outputs/", "archive/", ".workspace/"]:
        assert entry in ignored, f"{entry}가 .gitignore에 없습니다"


def test_env_file_is_not_tracked_by_git():
    """.gitignore에 있어도 이미 추적 중이면 계속 올라간다. 실제 추적 상태를 본다."""
    import subprocess

    repo = Path(__file__).parents[1]
    tracked = subprocess.run(
        ["git", "ls-files", ".env"],
        cwd=repo, capture_output=True, text=True,
    ).stdout.strip()

    assert tracked == "", f".env가 아직 git에 추적되고 있습니다: {tracked}"


def test_run_module_exposes_builder():
    import run

    assert callable(run.build_pipeline)
    assert callable(run.main)
