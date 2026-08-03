"""로컬 컨펌 UI. 2단계 컨펌을 서버가 강제한다."""
from __future__ import annotations

import threading
from datetime import date
from pathlib import Path
from typing import Callable

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel

from willy.images import UnsupportedImageError, sniff
from willy.models import Gender
from willy.pipeline import Pipeline, PipelineState

STATIC = Path(__file__).parent / "static"


class GatherRequest(BaseModel):
    base_date: date


def _serialize(state: PipelineState) -> dict:
    assigned_ids = {
        look.look_id for look in state.assignment.values() if look is not None
    }

    return {
        "pool": [
            {
                "look_id": look.look_id,
                "source": look.source,
                "gender": look.gender.value,
                "temp_range": list(look.temp_range) if look.temp_range else None,
                "rain_ok": look.rain_ok,
                "style_tags": look.style_tags,
                "image_url": f"/api/image/{look.look_id}",
                "source_url": look.source_url,
                "assigned": look.look_id in assigned_ids,
            }
            for look in state.looks
        ],
        "week": [
            {
                "date": d.date.isoformat(),
                "weekday": d.weekday_ko,
                "sky": d.sky,
                "temp_max": d.temp_max,
                "temp_min": d.temp_min,
                "temp_repr": d.temp_repr,
                "precip_prob": d.precip_prob,
                "is_rainy": d.is_rainy,
                "resolution": d.resolution,
            }
            for d in state.week
        ],
        "slots": [
            {
                "date": slot_date.isoformat(),
                "gender": gender.value,
                "pick": pick,
                "look_id": look.look_id if look else None,
                "source": look.source if look else None,
                "temp_range": (
                    list(look.temp_range) if look and look.temp_range else None
                ),
                "style_tags": look.style_tags if look else [],
                "empty": look is None,
                "caveat": state.caveats.get((slot_date, gender, pick)),
                "image_url": f"/api/image/{look.look_id}" if look else None,
                "source_url": look.source_url if look else None,
                "generated_url": (
                    f"/api/generated/{slot_date.isoformat()}/{gender.value}/{pick}"
                    if (slot_date, gender, pick) in state.generated
                    else None
                ),
            }
            for (slot_date, gender, pick), look in sorted(
                state.assignment.items(),
                key=lambda kv: (kv[0][0], kv[0][1].value, kv[0][2]),
            )
        ],
        "warnings": [
            {"code": w.code.value, "message": w.message} for w in state.warnings
        ],
        "generated_count": len(state.generated),
    }


def create_app(pipeline_factory: Callable[[], Pipeline]) -> FastAPI:
    app = FastAPI(title="내일 뭐입지? 콘텐츠 엔진")
    ctx: dict = {"pipeline": None, "state": None, "generated": False}

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return (STATIC / "index.html").read_text(encoding="utf-8")

    def _serve(path) -> FileResponse:
        """파이프라인이 만든 파일만 내보낸다."""
        if path is None or not path.exists():
            raise HTTPException(404, "이미지를 찾을 수 없습니다.")
        try:
            media_type, _suffix = sniff(path)
        except UnsupportedImageError:
            raise HTTPException(404, "이미지 형식을 알 수 없습니다.")
        return FileResponse(path, media_type=media_type)

    @app.get("/api/image/{look_id}")
    def look_image(look_id: str) -> FileResponse:
        # URL 조각을 경로에 이어붙이지 않는다. 현재 상태에서 id로 조회해
        # 파이프라인이 만든 경로만 내보낸다.
        state = ctx["state"]
        if state is None:
            raise HTTPException(404, "수집된 룩이 없습니다.")

        match = next((x for x in state.looks if x.look_id == look_id), None)
        if match is None:
            raise HTTPException(404, "이미지를 찾을 수 없습니다.")
        return _serve(match.image_path)

    @app.get("/api/generated/{slot_date}/{gender}/{pick}")
    def generated_image(slot_date: date, gender: Gender, pick: int) -> FileResponse:
        state = ctx["state"]
        if state is None:
            raise HTTPException(404, "생성된 이미지가 없습니다.")
        return _serve(state.generated.get((slot_date, gender, pick)))

    # 수집 한 번에 비전 호출이 12번 붙는다. 여러 탭·중복 클릭으로 수집이
    # 겹쳐 돌면 API 한도만 태우므로 서버에서 한 번에 하나만 허용한다.
    gather_lock = threading.Lock()

    @app.post("/api/gather")
    def gather(request: GatherRequest) -> dict:
        if not gather_lock.acquire(blocking=False):
            raise HTTPException(
                409, "수집이 이미 진행 중입니다. 끝날 때까지 기다려 주세요."
            )
        try:
            previous = ctx["pipeline"]
            if previous is not None:
                previous.archive.close()

            pipeline = pipeline_factory()
            state = pipeline.gather(base_date=request.base_date)
            ctx.update(pipeline=pipeline, state=state, generated=False)
            return _serialize(state)
        finally:
            gather_lock.release()

    @app.post("/api/generate")
    def generate() -> dict:
        if ctx["state"] is None:
            raise HTTPException(409, "먼저 수집을 실행해 주세요.")
        state = ctx["pipeline"].generate_images(ctx["state"])
        ctx.update(state=state, generated=True)
        return _serialize(state)

    @app.post("/api/finalize")
    def finalize() -> dict:
        if ctx["state"] is None:
            raise HTTPException(409, "먼저 수집을 실행해 주세요.")
        if not ctx["generated"]:
            raise HTTPException(409, "이미지 생성 후 최종 컨펌이 가능합니다.")
        root = ctx["pipeline"].finalize(ctx["state"])
        return {"output_path": str(root)}

    return app
