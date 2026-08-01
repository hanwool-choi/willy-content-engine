"""컨펌된 배정을 폴더와 문서로 물리화한다."""
from __future__ import annotations

import json
import shutil
from dataclasses import asdict
from pathlib import Path

from willy.images import sniff
from willy.models import Assignment, DayWeather, Gender, iso_week_label
from willy.publisher.docs import write_item_doc, write_week_summary

# 원본은 로컬 참고용이다. 파일명에 표식을 박아 오발행을 막는다.
REF_STEM = "_ref_원본_발행금지"
PUBLISH_STEM = "발행용"


def _write_analysis(path: Path, analysis) -> None:
    data = asdict(analysis)
    data["gender"] = analysis.gender.value
    data["temp_range"] = list(analysis.temp_range)
    data["image_path"] = str(analysis.image_path) if analysis.image_path else None
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def publish(
    assignment: Assignment,
    week: list[DayWeather],
    generated: dict[tuple, Path],
    output_root: Path,
) -> Path:
    """최종 컨펌 이후에만 호출된다. 이 함수가 유일하게 outputs/에 쓴다."""
    root = output_root / iso_week_label(week[0].date)
    root.mkdir(parents=True, exist_ok=True)

    for day in week:
        day_dir = root / day.folder_name
        day_dir.mkdir(parents=True, exist_ok=True)

        entries: dict[Gender, list[dict]] = {}

        for gender in (Gender.MEN, Gender.WOMEN):
            analysis = assignment.get((day.date, gender))
            if analysis is None:
                continue  # 빈 칸은 폴더를 만들지 않는다.

            gender_dir = day_dir / gender.value
            gender_dir.mkdir(parents=True, exist_ok=True)

            if analysis.image_path and analysis.image_path.exists():
                _media, suffix = sniff(analysis.image_path)
                shutil.copyfile(analysis.image_path, gender_dir / f"{REF_STEM}{suffix}")

            gen_path = generated.get((day.date, gender))
            if gen_path and gen_path.exists():
                _media, suffix = sniff(gen_path)
                shutil.copyfile(gen_path, gender_dir / f"{PUBLISH_STEM}{suffix}")

            _write_analysis(gender_dir / "analysis.json", analysis)
            entries[gender] = []

        write_item_doc(day_dir / "아이템정보.docx", day, entries)

    write_week_summary(root / "_주간요약.docx", week, assignment)
    return root
