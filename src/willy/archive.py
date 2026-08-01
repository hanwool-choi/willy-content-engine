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
    image_path    TEXT,
    source        TEXT NOT NULL DEFAULT ''
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
        # FastAPI가 동기 엔드포인트를 스레드풀에서 돌리기 때문에 요청마다
        # 스레드가 달라진다. 단일 사용자 로컬 도구라 동시 쓰기가 없으므로
        # 연결을 스레드 간에 공유해도 안전하다.
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)
        self._migrate_add_source_column()
        self._conn.commit()

    def _migrate_add_source_column(self) -> None:
        """이전 실행의 archive/looks.db에는 source 컬럼이 없을 수 있다.

        CREATE TABLE IF NOT EXISTS는 이미 존재하는 테이블을 건드리지 않으므로,
        기존 DB를 여는 두 번째 주차부터 여기서 직접 보강해야 한다.
        """
        columns = {row["name"] for row in self._conn.execute("PRAGMA table_info(looks)")}
        if "source" not in columns:
            self._conn.execute(
                "ALTER TABLE looks ADD COLUMN source TEXT NOT NULL DEFAULT ''"
            )

    def save(self, look: LookAnalysis) -> None:
        self._conn.execute(
            """INSERT OR REPLACE INTO looks
               (look_id, gender, sleeve, outer, layers, fabric_weight, coverage,
                temp_min, temp_max, rain_ok, season, style_tags, palette, image_path,
                source)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
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
                look.source,
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

    def close(self) -> None:
        """열린 연결을 닫는다. 서버가 계속 떠 있으므로 GC에 맡기지 않는다."""
        self._conn.close()

    def find_substitute(
        self,
        temp: float,
        rain_ok: bool | None,
        season: str,
        gender: Gender,
        exclude_recent_weeks: int = 4,
        exclude_ids: set[str] | None = None,
        as_of: date | None = None,
    ) -> LookAnalysis | None:
        """조건에 맞는 룩 중 기온이 가장 가까운 것 하나.

        rain_ok=None이면 우천 가능 여부를 따지지 않는다. 맑은 날에 비에도
        입을 수 있는 룩을 굳이 뺄 이유가 없다.

        exclude_ids는 이번 배정에서 이미 쓴 룩이다. usages 테이블은 finalize
        시점에야 갱신되므로, 한 번의 배정 안에서는 이 인자로 중복을 막는다.

        as_of는 4주 컷오프를 계산하는 기준일이다. 생략하면 오늘 날짜를 쓴다.
        테스트가 실제 시계에 의존하지 않도록 주입할 수 있게 열어둔다.
        """
        cutoff = (
            (as_of or date.today()) - timedelta(weeks=exclude_recent_weeks)
        ).isoformat()

        clauses = ["gender = ?", "season = ?"]
        params: list = [gender.value, season]

        if rain_ok is not None:
            clauses.append("rain_ok = ?")
            params.append(int(rain_ok))

        clauses.append("ABS((temp_min + temp_max) / 2.0 - ?) <= ?")
        params.extend([temp, TEMP_WINDOW])

        clauses.append(
            "look_id NOT IN (SELECT look_id FROM usages WHERE used_on >= ?)"
        )
        params.append(cutoff)

        if exclude_ids:
            placeholders = ",".join("?" for _ in exclude_ids)
            clauses.append(f"look_id NOT IN ({placeholders})")
            params.extend(sorted(exclude_ids))

        params.append(temp)  # ORDER BY

        row = self._conn.execute(
            f"""SELECT * FROM looks
                WHERE {" AND ".join(clauses)}
                ORDER BY ABS((temp_min + temp_max) / 2.0 - ?) ASC, look_id ASC
                LIMIT 1""",
            params,
        ).fetchone()

        return self._to_look(row) if row else None

    @staticmethod
    def _to_look(row: sqlite3.Row) -> LookAnalysis:
        return LookAnalysis(
            look_id=row["look_id"],
            source=row["source"],
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
