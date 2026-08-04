"""로컬 컨펌 UI. 2단계 컨펌을 서버가 강제한다."""
from __future__ import annotations

import hashlib
import logging
import threading
from datetime import date
from pathlib import Path
from typing import Callable

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel

from willy.ideas.collector import collect_ideas
from willy.ideas.detail import fetch_detail
from willy.ideas.models import IdeaItem
from willy.ideas.sources import IDEA_SOURCES, SOURCE_GROUPS
from willy.images import UnsupportedImageError, sniff
from willy.models import Gender
from willy.pipeline import Pipeline, PipelineState

log = logging.getLogger(__name__)

STATIC = Path(__file__).parent / "static"


class GatherRequest(BaseModel):
    base_date: date


class IdeaTextsRequest(BaseModel):
    urls: list[str]


def _serialize_idea(item: IdeaItem) -> dict:
    source = IDEA_SOURCES.get(item.source)
    return {
        "source": item.source,
        "source_label": source.label if source else item.source,
        "group": source.group if source else "magazine",
        "title": item.title,
        "url": item.url,
        "category": item.category,
        "thumbnail_url": item.thumbnail_url,
        "published_at": item.published_at.isoformat() if item.published_at else None,
        "views": item.views,
        "comments": item.comments,
        "likes": item.likes,
        "is_hot": item.is_hot,
    }


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
                "is_ai": look.is_ai,
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
                "is_ai": look.is_ai if look else False,
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


def create_app(
    pipeline_factory: Callable[[], Pipeline],
    ideas_collector: Callable[[], tuple[list, list[str]]] | None = None,
    detail_fetcher: Callable[[str], str] | None = None,
    ideas_writer: Callable[[list], list[dict]] | None = None,
) -> FastAPI:
    app = FastAPI(title="최윌리 옷장연구소 콘텐츠 플랫폼")
    ctx: dict = {"pipeline": None, "state": None, "generated": False, "ideas": []}

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

    def _run_gather(base_date: date, exclude_hashes: set[str] | None) -> dict:
        if not gather_lock.acquire(blocking=False):
            raise HTTPException(
                409, "수집이 이미 진행 중입니다. 끝날 때까지 기다려 주세요."
            )
        try:
            previous = ctx["pipeline"]
            if previous is not None:
                previous.archive.close()

            pipeline = pipeline_factory()
            state = pipeline.gather(
                base_date=base_date, exclude_hashes=exclude_hashes
            )
            ctx.update(
                pipeline=pipeline, state=state, generated=False,
                base_date=base_date,
            )
            return _serialize(state)
        finally:
            gather_lock.release()

    @app.post("/api/gather")
    def gather(request: GatherRequest) -> dict:
        return _run_gather(request.base_date, None)

    @app.post("/api/regather")
    def regather() -> dict:
        """같은 날짜로 다시 수집하되, 이미 가진 이미지는 건너뛴다."""
        state = ctx["state"]
        if state is None or ctx.get("base_date") is None:
            raise HTTPException(409, "먼저 수집을 실행해 주세요.")

        exclude = {
            hashlib.sha256(look.image_path.read_bytes()).hexdigest()
            for look in state.looks
            if look.image_path and look.image_path.exists()
        }
        return _run_gather(ctx["base_date"], exclude)

    @app.post("/api/texts")
    def texts() -> dict:
        if ctx["state"] is None:
            raise HTTPException(409, "먼저 수집을 실행해 주세요.")
        return {"texts": ctx["pipeline"].write_texts(ctx["state"])}

    # 아이디어 수집도 여러 탭에서 겹쳐 돌 수 있다. 룩 수집과 같은 이유로 잠근다.
    ideas_lock = threading.Lock()

    @app.post("/api/ideas")
    def ideas() -> dict:
        if not ideas_lock.acquire(blocking=False):
            raise HTTPException(
                409, "아이디어를 이미 모으는 중입니다. 끝날 때까지 기다려 주세요."
            )
        try:
            collector = ideas_collector or (lambda: collect_ideas())
            items, failed = collector()
            ctx["ideas"] = items
            return {
                "items": [_serialize_idea(item) for item in items],
                "failed": failed,
                "groups": SOURCE_GROUPS,
            }
        finally:
            ideas_lock.release()

    @app.post("/api/ideas/texts")
    def idea_texts(request: IdeaTextsRequest) -> dict:
        if not request.urls:
            raise HTTPException(400, "소식을 하나 이상 선택해 주세요.")
        if not ctx["ideas"]:
            raise HTTPException(409, "먼저 아이디어를 불러와 주세요.")

        # 목록에 있는 주소만 연다. 임의 주소를 받으면 서버가 남의 사이트를
        # 긁는 통로가 된다.
        by_url = {item.url: item for item in ctx["ideas"]}
        if any(url not in by_url for url in request.urls):
            raise HTTPException(400, "목록에 없는 소식입니다.")

        fetcher = detail_fetcher or fetch_detail
        pairs = []
        for url in request.urls:
            try:
                detail = fetcher(url)
            except Exception:
                log.exception("상세 수집 실패: %s", url)
                detail = ""
            pairs.append((by_url[url], detail))

        from willy.texter import template_idea_texts

        # 두 탭은 독립이다. 아이디어 텍스트를 쓰려고 룩 수집을 먼저
        # 돌려야 한다면 흐름이 어긋난다. 주입된 작성자를 우선 쓰고,
        # 없을 때만 파이프라인 것을 빌린다.
        writer_fn = ideas_writer
        if writer_fn is None and ctx["pipeline"] is not None:
            texter = ctx["pipeline"].texter
            writer_fn = texter.write_from_ideas if texter else None

        if writer_fn is not None:
            try:
                return {"texts": writer_fn(pairs)}
            except Exception:
                log.exception("소식 텍스트 생성 실패 — 템플릿 폴백")
        return {"texts": template_idea_texts(pairs)}

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
