# -*- coding: utf-8 -*-
"""최펄럭 코스 스튜디오용 데이터 생성.

즐겨찾기 3개 폴더를 수집해 지역 클러스터를 자동 산출하고,
큐레이션된 AI 추천 후보(assets/pulluk/ai_picks.json)를 합쳐
assets/pulluk/data.js 를 만든다.

    python tools/pulluk_site_data.py            # assets/pulluk/data.js 갱신
    python tools/pulluk_site_data.py --print    # 클러스터 미리보기만

빌드(build_site.py)에서도 같은 함수를 호출해 배포 시 데이터를 새로 받는다.
실패하면 커밋된 data.js 를 그대로 쓰면 되므로 예외는 위로 던진다.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pulluk_favorites import FOLDERS, UA, fetch_folder, haversine_km, norm_addr  # noqa: E402

import httpx  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUT_JS = PROJECT_ROOT / "assets" / "pulluk" / "data.js"
AI_PICKS = PROJECT_ROOT / "assets" / "pulluk" / "ai_picks.json"

KST = timezone(timedelta(hours=9))

# 자동 클러스터에 붙일 통용 지명. (위도, 경도) 반경 1.5km 안에 클러스터
# 중심이 들어오면 이 이름을 쓴다.
NICKNAMES = [
    ("강남역·서초", 37.49794, 127.02761),
    ("성수·서울숲", 37.54350, 127.04800),
    ("연남·홍대", 37.56230, 126.92500),
    ("을지로·종로", 37.56630, 126.99100),
    ("한남·이태원", 37.53400, 126.99480),
    ("여의도", 37.52150, 126.92430),
    ("문래·영등포", 37.51770, 126.89480),
    ("압구정·도산", 37.52480, 127.03850),
    ("서촌·경복궁", 37.57900, 126.97100),
    ("북촌·삼청", 37.58200, 126.98500),
    ("송리단길·잠실", 37.50800, 127.10500),
    ("부산 전포·서면", 35.15500, 129.06300),
    ("부산 광안·수영", 35.15300, 129.11300),
    ("부산 해운대", 35.16000, 129.16000),
    ("제주시", 33.49900, 126.53100),
    ("의정부", 37.74100, 127.04700),
    ("속초", 38.20400, 128.59100),
    ("공주", 36.45500, 127.12500),
    ("남영·후암", 37.54986, 126.97599),
    ("삼각지·용리단길", 37.53200, 126.96875),
    ("망원·합정", 37.55574, 126.90667),
    ("동묘·창신", 37.56973, 127.01518),
    ("경주 황리단길", 35.83760, 129.21135),
    ("양재·매봉", 37.48454, 127.03516),
    ("당산", 37.53536, 126.90167),
    ("전주 객리단길", 35.81763, 127.14383),
    ("강릉", 37.75837, 128.89284),
    ("대구 동성로", 35.86862, 128.59495),
    ("인천 신포·개항장", 37.47298, 126.62207),
    ("군산 원도심", 35.98710, 126.70967),
]

RADIUS_KM = 1.4  # 지역 필터 반경 (도보권+α)


def build_places() -> list[dict]:
    places = []
    with httpx.Client(headers=UA, timeout=25) as c:
        for label, url in FOLDERS.items():
            _, _, items = fetch_folder(c, url)
            for b in items:
                if not (b.get("py") and b.get("px")):
                    continue
                mcid = b.get("mcidName") or ""
                # 폴더가 1차 분류, BAR/카페는 세부 분류로 승격
                cat = {"카페": "카페", "식당": "식당", "스팟": "스팟"}[label]
                if label == "식당" and mcid == "BAR":
                    cat = "바"
                elif label == "식당" and mcid == "카페":
                    cat = "카페"
                places.append(
                    {
                        "name": b["name"],
                        "cat": cat,
                        "lat": round(b["py"], 6),
                        "lon": round(b["px"], 6),
                        "addr": norm_addr(b.get("address")),
                        "sid": b.get("sid"),
                    }
                )
    # 폴더 간 중복(같은 sid) 제거 — 먼저 들어온 항목 우선
    seen, out = set(), []
    for p in places:
        key = p.get("sid") or (p["name"], p["addr"])
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out


def cluster_regions(places: list[dict]) -> list[dict]:
    """0.01도 격자 밀도 → 그리디 억제(2km) → 지명 붙이기."""
    grid = Counter()
    for p in places:
        grid[(round(p["lat"], 2), round(p["lon"], 2))] += 1

    centers: list[tuple[float, float, int]] = []
    for (glat, glon), n in grid.most_common():
        if n < 5:
            break
        if any(haversine_km(glat, glon, c[0], c[1]) < 2.0 for c in centers):
            continue
        centers.append((glat, glon, n))

    regions = []
    for glat, glon, _ in centers:
        members = [p for p in places if haversine_km(glat, glon, p["lat"], p["lon"]) <= RADIUS_KM]
        if len(members) < 6:
            continue
        clat = sum(p["lat"] for p in members) / len(members)
        clon = sum(p["lon"] for p in members) / len(members)
        name = None
        for nick, nlat, nlon in NICKNAMES:
            if haversine_km(clat, clon, nlat, nlon) <= 1.5:
                name = nick
                break
        if name is None:
            toks = Counter()
            for p in members:
                parts = p["addr"].split()
                if len(parts) >= 2:
                    toks[" ".join(parts[:2])] += 1
            name = toks.most_common(1)[0][0] if toks else "미분류"
        cats = Counter(p["cat"] for p in members)
        regions.append(
            {
                "name": name,
                "lat": round(clat, 5),
                "lon": round(clon, 5),
                "radius": RADIUS_KM,
                "count": len(members),
                "cats": dict(cats),
            }
        )
    # 같은 이름이 두 번 나오면 큰 쪽만 남긴다
    best: dict[str, dict] = {}
    for r in regions:
        if r["name"] not in best or r["count"] > best[r["name"]]["count"]:
            best[r["name"]] = r
    return sorted(best.values(), key=lambda r: -r["count"])


# ── 장소 설명 보강 (네이버 플레이스 요약 API) ──────────────────────
# sid당 1.2KB짜리 요약에서 세부 업종·리뷰 수·평점·영업 힌트를 얻는다.
# 이미 보강된 sid는 gh-pages/로컬 data.js에서 재사용하므로 매일 신규
# 즐겨찾기 몇 건만 추가 요청된다.
SUMMARY_URL = "https://map.naver.com/p/api/place/summary/{sid}"


def load_prev_descs() -> dict:
    descs: dict[str, dict] = {}
    # 로컬 커밋본 → gh-pages 게시본 순으로 읽는다 (게시본이 최신일 수 있음)
    for src in ("local", "remote"):
        try:
            if src == "local":
                txt = OUT_JS.read_text(encoding="utf-8")
            else:
                import pulluk_popups

                with httpx.Client(headers=UA, timeout=30) as c:
                    txt = c.get(pulluk_popups.PREV_URL).text
            data = json.loads(txt[txt.index("=") + 1 :].rstrip().rstrip(";"))
            for p in data.get("places", []):
                if p.get("sid") and p.get("d"):
                    descs.setdefault(str(p["sid"]), p["d"])
        except Exception:
            pass
    return descs


def fetch_desc(client: httpx.Client, sid) -> dict | None:
    r = client.get(SUMMARY_URL.format(sid=sid), headers={"Referer": "https://map.naver.com/"})
    if r.status_code != 200:
        return None
    detail = (r.json().get("data") or {}).get("placeDetail") or {}
    out: dict = {}
    cat = ((detail.get("category") or {}).get("category") or "").strip()
    if cat:
        out["c"] = cat
    vr = detail.get("visitorReviews") or {}
    m = re.search(r"([\d,]+)", vr.get("displayText") or "")
    if m:
        out["r"] = int(m.group(1).replace(",", ""))
    if vr.get("score"):
        out["s"] = vr["score"]
    hours = (detail.get("businessHours") or {}).get("description")
    if hours:
        out["h"] = hours
    return out or None


def enrich_places(places: list[dict], limit: int = 150, delay: float = 0.25) -> None:
    descs = load_prev_descs()
    todo = [p for p in places if p.get("sid") and str(p["sid"]) not in descs]
    if todo:
        with httpx.Client(headers=UA, timeout=15) as c:
            for p in todo[:limit]:
                try:
                    d = fetch_desc(c, p["sid"])
                    if d:
                        descs[str(p["sid"])] = d
                except Exception:
                    pass
                time.sleep(delay)
    for p in places:
        d = descs.get(str(p.get("sid")))
        if d:
            p["d"] = d


# ── 주차 정보 보강 (모바일 플레이스 페이지) ─────────────────────────
# conveniences(주차/발렛)와 InformationParking.description으로 판정한다.
# 페이지가 커서(300~550KB) 하루 상한을 낮게 잡고 클러스터 안 장소부터 채운다.
MPLACE_URL = "https://m.place.naver.com/place/{sid}/home"
MOBILE_UA = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148 Safari/604.1"
}
_NEG = re.compile(r"불가|없습니|없음|미지원|어렵")


def fetch_parking(client: httpx.Client, sid) -> dict | None:
    """{'pk': 0|1, 'pkt': 안내문?} — 판정 불가(차단 등)면 None."""
    r = client.get(MPLACE_URL.format(sid=sid))
    if r.status_code != 200:
        return None
    t = r.text
    out: dict = {}
    m = re.search(r'"InformationParking","description":"([^"]{2,120})', t)
    pkt = m.group(1) if m else None
    # 주의: '"parking":"주차"' 같은 문자열은 모든 페이지에 있는 i18n 라벨이라
    # 판정 근거로 쓰면 안 된다 (2026-08-10 오탐 사고). conveniences 배열과
    # InformationParking 안내문만 근거로 삼는다.
    conv_park = bool(re.search(r'"conveniences":\[[^\]]*(?:주차|발렛)', t))
    if conv_park or (pkt and not _NEG.search(pkt)):
        out["pk"] = 1
    else:
        out["pk"] = 0
    if pkt:
        out["pkt"] = pkt[:60]
    return out


def enrich_parking(places: list[dict], regions: list[dict], limit: int = 100, delay: float = 1.0) -> None:
    def in_cluster(p):
        return any(haversine_km(r["lat"], r["lon"], p["lat"], p["lon"]) <= r["radius"] for r in regions)

    todo = [p for p in places if p.get("sid") and "pk" not in (p.get("d") or {})]
    todo.sort(key=lambda p: 0 if in_cluster(p) else 1)
    if not todo:
        return
    with httpx.Client(headers=MOBILE_UA, timeout=25, follow_redirects=True) as c:
        for p in todo[:limit]:
            try:
                info = fetch_parking(c, p["sid"])
                if info:
                    d = p.get("d") or {}
                    d.update(info)
                    p["d"] = d
            except Exception:
                pass
            time.sleep(delay)


def generate(out_path: Path = OUT_JS, enrich_limit: int = 150, parking_limit: int = 100) -> dict:
    places = build_places()
    regions = cluster_regions(places)
    try:
        enrich_places(places, limit=enrich_limit)
    except Exception:
        pass
    try:
        enrich_parking(places, regions, limit=parking_limit)
    except Exception:
        pass
    ai_picks = {}
    if AI_PICKS.exists():
        ai_picks = json.loads(AI_PICKS.read_text(encoding="utf-8"))
    try:
        import pulluk_popups

        popups = pulluk_popups.collect()
    except Exception:
        popups = []
    data = {
        "generatedAt": datetime.now(KST).strftime("%Y-%m-%d %H:%M KST"),
        "places": places,
        "regions": regions,
        "aiPicks": ai_picks,
        "popups": popups,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        "window.PULLUK = " + json.dumps(data, ensure_ascii=False) + ";\n",
        encoding="utf-8",
    )
    return data


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--print", action="store_true", help="클러스터 미리보기만")
    ap.add_argument("--enrich-limit", type=int, default=150, help="이번 실행에서 새로 보강할 장소 수")
    ap.add_argument("--parking-limit", type=int, default=100, help="이번 실행에서 주차 확인할 장소 수")
    args = ap.parse_args()
    if args.print:
        places = build_places()
        print(f"장소 {len(places)}곳")
        for r in cluster_regions(places):
            print(f"  {r['count']:3d}곳  {r['name']}  {r['cats']}")
        return
    data = generate(enrich_limit=args.enrich_limit, parking_limit=args.parking_limit)
    enriched = sum(1 for p in data["places"] if p.get("d"))
    parked = sum(1 for p in data["places"] if "pk" in (p.get("d") or {}))
    print(f"data.js 생성: 장소 {len(data['places'])} / 지역 {len(data['regions'])} / 설명 {enriched} / 주차확인 {parked} / 팝업 {len(data.get('popups') or [])}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
