"""수집된 룩의 누적 저장소. 배정 폴백 소스로 쓰인다."""
from __future__ import annotations

import json
import sqlite3
from datetime import date, timedelta
from pathlib import Path

from willy.models import Gender, LookAnalysis

TEMP_WINDOW = 3.0  # 폴백 조회 시 허용 기온 차 (℃)

SCHEMA = """
CREATE TABLE IF NOT EXISTS looks (
    look_id       TEXT PRIMARY KEY,
    gender        TEXT NOT NULL,
    sleeve        TEXT NOT NULL,
    outer         TEXT,
    layers        INTEGER NOT NULL,
    fabric_weight TEXT NOT NULL,
    coverage      TEXT NOT NULL,
    temp_min      INTEGER NOT NULL,
    temp_max      INTEGER NOT NULL,
    rain_ok       INTEGER NOT NULL,
    season        TEXT NOT NULL,
    style_tags    TEXT NOT NULL,
    palette       TEXT NOT NULL,
    image_path    TEXT
);

CREATE TABLE IF NOT EXISTS usages (
    look_id TEXT NOT NULL,
    used_on TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_lookup ON looks (gender, season, rain_ok);
"""


class Archive:
    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def save(self, look: LookAnalysis) -> None:
        self._conn.execute(
            """INSERT OR REPLACE INTO looks
               (look_id, gender, sleeve, outer, layers, fabric_weight, coverage,
                temp_min, temp_max, rain_ok, season, style_tags, palette, image_path)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                look.look_id,
                look.gender.value,
                look.sleeve,
                look.outer,
                look.layers,
                look.fabric_weight,
                look.coverage,
                look.temp_range[0],
                look.temp_range[1],
                int(look.rain_ok),
                look.season,
                json.dumps(look.style_tags, ensure_ascii=False),
                json.dumps(look.palette, ensure_ascii=False),
                str(look.image_path) if look.image_path else None,
            ),
        )
        self._conn.commit()

    def mark_used(self, look_id: str, used_on: date) -> None:
        self._conn.execute(
            "INSERT INTO usages (look_id, used_on) VALUES (?, ?)",
            (look_id, used_on.isoformat()),
        )
        self._conn.commit()

    def count(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM looks").fetchone()[0]

    def find_substitute(
        self,
        temp: float,
        rain_ok: bool,
        season: str,
        gender: Gender,
        exclude_recent_weeks: int = 4,
    ) -> LookAnalysis | None:
        """조건에 맞는 룩 중 기온이 가장 가까운 것 하나."""
        cutoff = (date.today() - timedelta(weeks=exclude_recent_weeks)).isoformat()

        row = self._conn.execute(
            """SELECT * FROM looks
               WHERE gender = ? AND season = ? AND rain_ok = ?
                 AND ABS((temp_min + temp_max) / 2.0 - ?) <= ?
                 AND look_id NOT IN (
                     SELECT look_id FROM usages WHERE used_on >= ?
                 )
               ORDER BY ABS((temp_min + temp_max) / 2.0 - ?) ASC
               LIMIT 1""",
            (gender.value, season, int(rain_ok), temp, TEMP_WINDOW, cutoff, temp),
        ).fetchone()

        return self._to_look(row) if row else None

    @staticmethod
    def _to_look(row: sqlite3.Row) -> LookAnalysis:
        return LookAnalysis(
            look_id=row["look_id"],
            gender=Gender(row["gender"]),
            sleeve=row["sleeve"],
            outer=row["outer"],
            layers=row["layers"],
            fabric_weight=row["fabric_weight"],
            coverage=row["coverage"],
            temp_range=(row["temp_min"], row["temp_max"]),
            rain_ok=bool(row["rain_ok"]),
            season=row["season"],
            style_tags=json.loads(row["style_tags"]),
            palette=json.loads(row["palette"]),
            image_path=Path(row["image_path"]) if row["image_path"] else None,
        )
