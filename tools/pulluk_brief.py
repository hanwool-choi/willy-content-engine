# -*- coding: utf-8 -*-
"""데일리 브리핑 진입점.

    python tools/pulluk_brief.py --out out_brief             # 생성 + 카톡 전송
    python tools/pulluk_brief.py --out out_brief --no-send   # 생성만 (페이로드 파일 남김)
    python tools/pulluk_brief.py --send send_payload.json    # 전송만

CI는 생성 → 게시 → 전송 순으로 돈다. 전송이 실패해도 페이지는 이미 올라가 있어야
하고, 카톡의 "전문 보기" 버튼이 눌리는 시점엔 링크가 살아 있어야 하기 때문이다.
그래서 생성 단계가 전송에 필요한 것만 send_payload.json에 적어두고 빠진다.

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
from tools.pulluk_brief_text import checklist, compose, deep_dive_block  # noqa: E402
from tools.pulluk_kakao import KakaoError, refresh_access_token, send_brief  # noqa: E402

KST = timezone(timedelta(hours=9))
GH_PAGES = "https://raw.githubusercontent.com/hanwool-choi/willy-content-engine/gh-pages"
DATA_URL = f"{GH_PAGES}/pulluk/data.js"
ARCHIVE_URL = f"{GH_PAGES}/brief/archive.json"
LOCAL_DATA = PROJECT_ROOT / "assets" / "pulluk" / "data.js"
BRIEF_BASE_URL = "https://hanwool-choi.github.io/willy-content-engine/brief"
SUMMARY_URL = "https://map.naver.com/p/api/place/summary/{sid}"
# 게시 디렉터리 밖에 둔다. 여기 들어가면 gh-pages로 같이 올라가 버린다.
SEND_PAYLOAD = "send_payload.json"


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


def load_archive(http: httpx.Client | None = None) -> list[dict]:
    """지난 발행 이력. 못 읽으면 올린다 — 삼키면 그날 발행이 이력을 통째로 덮어쓴다.

    404는 첫 실행이라 정상이지만, 그 밖의 실패에 빈 리스트를 돌려주면
    일시적 네트워크 오류 한 번에 archive.json이 1건짜리로 리셋된다.
    """
    client = http or httpx.Client(timeout=30.0)
    try:
        response = client.get(ARCHIVE_URL)
    except httpx.HTTPError as exc:
        raise RuntimeError(f"아카이브를 읽지 못했다 ({type(exc).__name__}): {ARCHIVE_URL}") from exc
    finally:
        if http is None:
            client.close()
    if response.status_code == 404:
        return []
    if response.status_code != 200:
        raise RuntimeError(
            f"아카이브를 읽지 못했다 (HTTP {response.status_code}): {ARCHIVE_URL}")
    return list(response.json())


def today_rainy(day: date) -> bool:
    """KMA 단기예보. 실패하면 비가 안 온다고 보고 로테이션을 그대로 간다."""
    key = os.getenv("KMA_SERVICE_KEY", "")
    if not key:
        return False
    try:
        from willy.weather.client import WeatherClient

        forecast = WeatherClient(key).get_week_forecast(day, days=1)
        return bool(forecast and forecast[0].is_rainy)
    except Exception as exc:
        print(f"날씨 조회 실패({type(exc).__name__}) — 로테이션 그대로 진행", file=sys.stderr)
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


def build_payload(result: dict, day: date) -> dict:
    """전송 단계가 알아야 할 것만 추린다. 여기서 계획 객체와의 연이 끊긴다."""
    plan = result["plan"]
    # 카톡 본문에는 페이지에 있는 집중분석을 덧붙인다(설계 §6). 페이지 초안
    # 영역에는 넣지 않는다 — 사용자가 그대로 복사해 올리는 글이라서다.
    body = result["draft"]
    if plan.deep:
        body = f"{body}\n\n{deep_dive_block(plan.deep)}"
    # 이미지 후보 순서: 집중분석 → 코스 장소. 집중분석은 보통 코스 안의 한 곳이라
    # 순서를 지키며 중복만 걷어낸다(같은 sid를 두 번 조회할 이유가 없다).
    candidates = ([plan.deep] if plan.deep else []) + list(plan.places)
    sids: list[str] = []
    for place in candidates:
        sid = str(place.get("sid") or "") if place else ""
        if sid and sid not in sids:
            sids.append(sid)
    return {
        "title": f"🚩 {day.isoformat()} {plan.title}",
        "summary": result["summary"],
        "body": body,
        "link": f"{BRIEF_BASE_URL}/{day.isoformat()}.html",
        "sids": sids,
    }


def _send_kakao(payload: dict, http: httpx.Client | None = None) -> None:
    rest_key = os.getenv("KAKAO_REST_API_KEY", "")
    refresh = os.getenv("KAKAO_REFRESH_TOKEN", "")
    if not (rest_key and refresh):
        print("카카오 키가 없어 전송을 건너뛴다", file=sys.stderr)
        return

    client = http or httpx.Client(timeout=30.0)
    try:
        # 집중분석 대상 사진을 우선 쓰고, 없으면 코스 장소 순으로 넘어간다.
        image_url = None
        for sid in payload.get("sids") or []:
            image_url = place_image_url({"sid": sid}, client)
            if image_url:
                break

        try:
            access, rotated = refresh_access_token(rest_key, refresh, client)
            # 카카오는 새 토큰을 내주는 순간 구 토큰을 무효화한다. 전송보다 먼저
            # 적어두지 않으면 전송 실패 한 번에 다음 날부터 영구 실패한다.
            if rotated:
                Path("new_refresh_token.txt").write_text(rotated, encoding="utf-8")
                print("리프레시 토큰이 갱신됐다 — 시크릿을 업데이트해야 한다")
            sent = send_brief(client, access,
                              title=payload["title"], summary=payload["summary"],
                              body=payload["body"], link_url=payload["link"],
                              image_url=image_url)
        except httpx.HTTPError as exc:
            # 네트워크 예외까지 스택트레이스로 터뜨릴 이유가 없다. 토큰은 담지 않는다.
            raise KakaoError(f"카카오 요청 실패({type(exc).__name__})") from exc
    finally:
        if http is None:
            client.close()
    print(f"카톡 {sent}통 전송 완료")


def _send_from_file(path: Path) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    try:
        _send_kakao(payload)
    except KakaoError as exc:
        print(f"카톡 전송 실패: {exc}", file=sys.stderr)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description="최펄럭 데일리 브리핑")
    parser.add_argument("--out", default="out_brief", help="출력 디렉터리")
    parser.add_argument("--no-send", action="store_true", help="카톡 전송 없이 생성만")
    parser.add_argument("--dry-run", action="store_true", help="--no-send와 같다(옛 이름)")
    parser.add_argument("--send", metavar="PATH",
                        help="이미 만들어 둔 페이로드 파일로 전송만 한다")
    parser.add_argument("--date", help="기준일 (YYYY-MM-DD, 기본: 오늘 KST)")
    args = parser.parse_args()

    if args.send:
        _send_from_file(Path(args.send))
        return

    day = (datetime.strptime(args.date, "%Y-%m-%d").date() if args.date
           else datetime.now(KST).date())
    data = load_data()
    archive = load_archive()
    rainy = today_rainy(day)

    result = run(data, archive, day, rainy, os.getenv("GEMINI_API_KEY"), Path(args.out))
    print(f"기획: [{result['record']['kind']}] {result['record']['title']} "
          f"({result['source']}, 장소 {len(result['record']['places'])}곳, 비={rainy})")

    payload = build_payload(result, day)
    payload_path = Path(SEND_PAYLOAD)
    payload_path.write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                            encoding="utf-8")
    print(f"전송 페이로드: {payload_path}")

    if args.no_send or args.dry_run:
        print("전송하지 않는다 — 페이로드 파일로 나중에 보내면 된다")
        return
    try:
        _send_kakao(payload)
    except KakaoError as exc:
        print(f"카톡 전송 실패: {exc}", file=sys.stderr)
        raise


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
