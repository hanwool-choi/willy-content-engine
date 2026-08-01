"""로컬 컨펌 UI. 2단계 컨펌을 서버가 강제한다."""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Callable

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from willy.pipeline import Pipeline, PipelineState

STATIC = Path(__file__).parent / "static"


class GatherRequest(BaseModel):
    base_date: date


def _serialize(state: PipelineState) -> dict:
    return {
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
                "look_id": look.look_id if look else None,
                "temp_range": list(look.temp_range) if look else None,
                "style_tags": look.style_tags if look else [],
                "empty": look is None,
            }
            for (slot_date, gender), look in sorted(
                state.assignment.items(), key=lambda kv: (kv[0][0], kv[0][1].value)
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

    @app.post("/api/gather")
    def gather(request: GatherRequest) -> dict:
        pipeline = pipeline_factory()
        state = pipeline.gather(base_date=request.base_date)
        ctx.update(pipeline=pipeline, state=state, generated=False)
        return _serialize(state)

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
