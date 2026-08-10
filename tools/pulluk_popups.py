# -*- coding: utf-8 -*-
"""popga.co.kr 팝업스토어 수집 → 코스 스튜디오 AI 추천용.

팝가 목록 페이지는 최신 등록 12건만 프리렌더된다(robots 허용 확인,
2026-08-10). 그래서 매일 12건을 수집하고, gh-pages에 이미 게시된
data.js의 popups와 병합해 누적한다 — 종료일이 지난 팝업은 자동 탈락.
아카이브 저장소가 곧 gh-pages라 러너가 상태를 따로 들고 있을 필요가 없다.

단독 실행하면 수집 결과를 미리 볼 수 있다:
    python tools/pulluk_popups.py
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timedelta, timezone

import truststore

truststore.inject_into_ssl()
import httpx

KST = timezone(timedelta(hours=9))
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36"}

LIST_URL = (
    "https://popga.co.kr/list/popup"
    "?periodTypes%5B0%5D=IN_PROGRESS&periodTypes%5B1%5D=READY"
    "&size=12&sorts%5B0%5D.order=activated_at"
)
# gh-pages에 게시된 직전 data.js — 팝업 누적 아카이브 역할
PREV_URL = "https://raw.githubusercontent.com/hanwool-choi/willy-content-engine/gh-pages/pulluk/data.js"


def _flatten(html: str) -> str:
    """Next.js flight 페이로드의 이스케이프(\\")를 풀어 JSON처럼 만든다."""
    return html.replace('\\"', '"')


def _extract_store_objects(text: str) -> list[dict]:
    """{"id":N,"type":"STORE"...} 객체를 중괄호 균형으로 잘라 파싱한다."""
    out = []
    for m in re.finditer(r'\{"id":\d+,"type":"STORE"', text):
        s = m.start()
        depth, instr, esc = 0, False, False
        for j in range(s, min(len(text), s + 20000)):
            ch = text[j]
            if instr:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    instr = False
            else:
                if ch == '"':
                    instr = True
                elif ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        try:
                            out.append(json.loads(text[s : j + 1]))
                        except Exception:
                            pass
                        break
    return out


def _normalize(o: dict) -> dict | None:
    area = o.get("area") or {}
    lat = area.get("latitude") or o.get("latitude")
    lon = area.get("longitude") or o.get("longitude")
    if not (o.get("title") and o.get("closeDate") and lat and lon):
        return None
    return {
        "id": o["id"],
        "title": o["title"],
        "status": o.get("periodType"),  # IN_PROGRESS | READY
        "open": o.get("openDate"),
        "close": o["closeDate"],
        "lat": round(float(lat), 6),
        "lon": round(float(lon), 6),
        "area": area.get("region2Depth") or (o.get("address") or "").split(" ")[:2][-1],
        "addr": o.get("address") or "",
        "detail": o.get("addressDetail") or "",
        "url": f"https://popga.co.kr/popup/{o['id']}",
        "source": "popga",
    }


def fetch_today(client: httpx.Client) -> list[dict]:
    html = client.get(LIST_URL).text
    items = [_normalize(o) for o in _extract_store_objects(_flatten(html))]
    return [x for x in items if x]


def fetch_detail(client: httpx.Client, pid: int) -> dict | None:
    """상세 페이지에서 팝업 1건을 파싱한다 (백필용)."""
    r = client.get(f"https://popga.co.kr/popup/{pid}")
    if r.status_code != 200:
        return None
    u = _flatten(r.text)

    def grab(key, pat=r'"([^"]*)"'):
        m = re.search(rf'"{key}":{pat}', u)
        return m.group(1) if m else None

    def grabnum(key):
        m = re.search(rf'"{key}":([\d.]+)', u)
        return float(m.group(1)) if m else None

    title = grab("title") or ""
    tm = re.search(r"<title>([^<|]+)", r.text)
    if tm and not title:
        title = tm.group(1).strip()
    o = {
        "id": pid,
        "title": title,
        "periodType": grab("periodType"),
        "openDate": grab("openDate"),
        "closeDate": grab("closeDate"),
        "latitude": grabnum("latitude"),
        "longitude": grabnum("longitude"),
        "address": grab("address"),
        "addressDetail": grab("addressDetail"),
    }
    return _normalize(o)


def fetch_prev(client: httpx.Client) -> list[dict]:
    try:
        r = client.get(PREV_URL)
        if r.status_code != 200:
            return []
        txt = r.text
        data = json.loads(txt[txt.index("=") + 1 :].rstrip().rstrip(";"))
        return data.get("popups") or []
    except Exception:
        return []


def collect() -> list[dict]:
    """오늘 수집분 + gh-pages 누적분 병합, 종료된 팝업 제거."""
    today = datetime.now(KST).strftime("%Y-%m-%d")
    merged: dict[int, dict] = {}
    with httpx.Client(headers=UA, timeout=30, follow_redirects=True) as c:
        for p in fetch_prev(c):
            merged[p["id"]] = p
        try:
            for p in fetch_today(c):
                merged[p["id"]] = p  # 오늘 수집분이 상태를 갱신한다
        except Exception:
            pass  # 수집 실패 시 누적분만으로 진행
    alive = [p for p in merged.values() if (p.get("close") or "") >= today]
    alive.sort(key=lambda p: (p.get("close") or "", p.get("open") or ""))
    return alive


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    popups = collect()
    print(f"팝업 {len(popups)}건")
    for p in popups:
        print(f"  [{p['status']}] {p['open']}~{p['close']}  {p['title']} | {p['area']} | {p['addr'][:30]}")
