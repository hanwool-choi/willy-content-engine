# -*- coding: utf-8 -*-
"""데일리 브리핑 진입점.

    python tools/pulluk_brief.py --out out_brief          # 생성 + 카톡 전송
    python tools/pulluk_brief.py --out out_brief --dry-run  # 생성만

데이터는 gh-pages에 올라간 최신본을 먼저 보고(펄럭 워크플로가 06:20에
갱신한다), 실패하면 저장소 커밋본으로 떨어진다. 카카오 키가 없으면
전송을 건너뛰므로 로컬에서도 그냥 돌아간다.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import truststore

truststore.inject_into_ssl()

import httpx  # noqa: E402  truststore 주입 뒤에 import해야 한다

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from tools.pulluk_brief_core import plan_for  # noqa: E402
from tools.pulluk_brief_page import render_brief, render_index  # noqa: E402
from tools.pulluk_brief_text import checklist, compose  # noqa: E402
from tools.pulluk_kakao import KakaoError, refresh_access_token, send_brief  # noqa: E402

KST = timezone(timedelta(hours=9))
GH_PAGES = "https://raw.githubusercontent.com/hanwool-choi/willy-content-engine/gh-pages"
DATA_URL = f"{GH_PAGES}/pulluk/data.js"
ARCHIVE_URL = f"{GH_PAGES}/brief/archive.json"
LOCAL_DATA = PROJECT_ROOT / "assets" / "pulluk" / "data.js"
BRIEF_BASE_URL = "https://hanwool-choi.github.io/willy-content-engine/brief"
SUMMARY_URL = "https://map.naver.com/p/api/place/summary/{sid}"


def _parse_data_js(text: str) -> dict:
    return json.loads(text[text.index("=") + 1:].rstrip().rstrip(";"))


def load_data() -> dict:
    """gh-pages 최신본 → 커밋본 순으로 시도한다."""
    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.get(DATA_URL)
        if response.status_code == 200:
            return _parse_data_js(response.text)
    except Exception:
        pass
    return _parse_data_js(LOCAL_DATA.read_text(encoding="utf-8"))


def load_archive() -> list[dict]:
    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.get(ARCHIVE_URL)
        if response.status_code == 200:
            return list(response.json())
    except Exception:
        pass
    return []


def today_rainy(day: date) -> bool:
    """KMA 단기예보. 실패하면 비가 안 온다고 보고 로테이션을 그대로 간다."""
    key = os.getenv("KMA_SERVICE_KEY", "")
    if not key:
        return False
    try:
        from willy.weather.client import WeatherClient

        forecast = WeatherClient(key).get_week_forecast(day, days=1)
        return bool(forecast and forecast[0].is_rainy)
    except Exception:
        return False


def run(data: dict, archive: list[dict], day: date, rainy: bool,
        api_key: str | None, out_dir: Path) -> dict:
    """기획 → 초안 → 페이지 → 아카이브. 네트워크 전송은 하지 않는다."""
    plan = plan_for(data, archive, day, rainy)
    draft, source = compose(plan, api_key)
    checks = checklist(plan)

    out_dir.mkdir(parents=True, exist_ok=True)
    html = render_brief(plan, draft, checks, day, source)
    (out_dir / f"{day.isoformat()}.html").write_text(html, encoding="utf-8")
    (out_dir / "latest.html").write_text(html, encoding="utf-8")

    record = {
        "date": day.isoformat(),
        "kind": plan.kind,
        "topic": plan.topic,
        "title": plan.title,
        "places": [p.get("name") for p in plan.places],
        "deep": (plan.deep or {}).get("name"),
        "source": source,
    }
    merged = [record] + [e for e in archive if e.get("date") != record["date"]]
    merged.sort(key=lambda e: e.get("date", ""), reverse=True)
    (out_dir / "archive.json").write_text(
        json.dumps(merged, ensure_ascii=False, indent=1), encoding="utf-8")
    (out_dir / "index.html").write_text(render_index(merged), encoding="utf-8")

    head = [line for line in draft.split("\n") if line.strip()][:2]
    return {"plan": plan, "draft": draft, "source": source, "record": record,
            "summary": " ".join(head)[:150]}


def place_image_url(place: dict, http: httpx.Client) -> str | None:
    """플레이스 요약 API의 대표 사진. 없거나 실패하면 None(이미지 없이 보낸다)."""
    sid = place.get("sid")
    if not sid:
        return None
    try:
        response = http.get(SUMMARY_URL.format(sid=sid),
                            headers={"Referer": "https://map.naver.com/"})
        if response.status_code != 200:
            return None
        detail = (response.json().get("data") or {}).get("placeDetail") or {}
        images = (detail.get("images") or {}).get("images") or []
        return images[0].get("origin") if images else None
    except Exception:
        return None


def _send_kakao(result: dict, day: date) -> None:
    rest_key = os.getenv("KAKAO_REST_API_KEY", "")
    refresh = os.getenv("KAKAO_REFRESH_TOKEN", "")
    if not (rest_key and refresh):
        print("카카오 키가 없어 전송을 건너뛴다", file=sys.stderr)
        return

    plan = result["plan"]
    link = f"{BRIEF_BASE_URL}/{day.isoformat()}.html"

    with httpx.Client(timeout=30.0) as client:
        # 집중분석 대상 사진을 우선 쓰고, 없으면 코스 첫 장소로 넘어간다.
        image_url = None
        for candidate in [plan.deep] + list(plan.places):
            if not candidate:
                continue
            image_url = place_image_url(candidate, client)
            if image_url:
                break

        access, rotated = refresh_access_token(rest_key, refresh, client)
        sent = send_brief(client, access,
                          title=f"🚩 {day.isoformat()} {plan.title}",
                          summary=result["summary"], body=result["draft"],
                          link_url=link, image_url=image_url)
    print(f"카톡 {sent}통 전송 완료")
    if rotated:
        Path("new_refresh_token.txt").write_text(rotated, encoding="utf-8")
        print("리프레시 토큰이 갱신됐다 — 시크릿을 업데이트해야 한다")


def main() -> None:
    parser = argparse.ArgumentParser(description="최펄럭 데일리 브리핑")
    parser.add_argument("--out", default="out_brief", help="출력 디렉터리")
    parser.add_argument("--dry-run", action="store_true", help="카톡 전송 없이 생성만")
    parser.add_argument("--date", help="기준일 (YYYY-MM-DD, 기본: 오늘 KST)")
    args = parser.parse_args()

    day = (datetime.strptime(args.date, "%Y-%m-%d").date() if args.date
           else datetime.now(KST).date())
    data = load_data()
    archive = load_archive()
    rainy = today_rainy(day)

    result = run(data, archive, day, rainy, os.getenv("GEMINI_API_KEY"), Path(args.out))
    print(f"기획: [{result['record']['kind']}] {result['record']['title']} "
          f"({result['source']}, 장소 {len(result['record']['places'])}곳, 비={rainy})")

    if args.dry_run:
        print("--dry-run이라 전송하지 않는다")
        return
    try:
        _send_kakao(result, day)
    except KakaoError as exc:
        print(f"카톡 전송 실패: {exc}", file=sys.stderr)
        raise


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
