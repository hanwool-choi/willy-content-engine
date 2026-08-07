# -*- coding: utf-8 -*-
"""김펄럭(최펄럭) 채널용 네이버 지도 즐겨찾기 수집·지역 필터 도구.

고정 공유 폴더 3개(카페/식당/스팟)를 로그인 없이 수집해서
지역 키워드 또는 좌표 반경으로 필터링한 목록을 출력한다.
코스 콘텐츠는 이 출력 목록에 있는 장소만으로 구성하는 것이 원칙.

사용 예:
    python tools/pulluk_favorites.py --addr 성수
    python tools/pulluk_favorites.py --center 37.49794,127.02761 --radius 1.3
    python tools/pulluk_favorites.py --dump all.json          # 전체 원본 저장

주의:
- 사내망 TLS 프록시 때문에 truststore 주입 필수 (curl 불가, httpx 사용)
- 응답 JSON의 목록 키는 `bookmarkList` (bookmarks 아님)
- 공유가 해제되면 수집이 실패한다 → 재공유 후 새 링크로 FOLDERS 갱신
"""
import argparse
import json
import math
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")
import truststore

truststore.inject_into_ssl()
import httpx

# 고정 즐겨찾기 공유 링크 (2026-08-07 등록)
FOLDERS = {
    "카페": "https://naver.me/x7efW1Yh",
    "식당": "https://naver.me/xbK62x9h",
    "스팟": "https://naver.me/GsBXIKaC",
}

UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36",
    "Accept": "application/json",
}
API = "https://pages.map.naver.com/save-pages/api/maps-bookmark/v3/shares/{token}/bookmarks"


def fetch_folder(client: httpx.Client, short_url: str):
    r = client.get(short_url, follow_redirects=True)
    m = re.search(r"folder/([A-Za-z0-9]+)", str(r.url))
    if not m:
        raise RuntimeError(f"공유 링크에서 폴더 토큰을 찾지 못함: {short_url} -> {r.url}")
    token = m.group(1)
    headers = {"Referer": f"https://map.naver.com/p/favorite/sharedPlace/folder/{token}"}
    items, start, folder_name = [], 0, None
    while True:
        rr = client.get(API.format(token=token), params={"start": start, "limit": 200}, headers=headers)
        rr.raise_for_status()
        data = rr.json()
        if folder_name is None:
            folder_name = (data.get("folder") or {}).get("name")
        page = data.get("bookmarkList") or data.get("bookmarks") or []
        if not page:
            break
        items.extend(page)
        start += len(page)
        if len(page) < 200:
            break
    return token, folder_name, items


def haversine_km(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(a))


def norm_addr(addr: str) -> str:
    return (addr or "").replace("서울특별시", "서울").replace("경기도", "경기").replace("부산광역시", "부산")


def main():
    ap = argparse.ArgumentParser(description="네이버 즐겨찾기 수집·지역 필터")
    ap.add_argument("--addr", help="주소 포함 키워드 (예: 성수, 용산구)")
    ap.add_argument("--center", help="중심 좌표 lat,lon (예: 37.49794,127.02761)")
    ap.add_argument("--radius", type=float, default=1.3, help="반경 km (기본 1.3)")
    ap.add_argument("--dump", help="전체 원본을 JSON 파일로 저장")
    args = ap.parse_args()

    center = None
    if args.center:
        lat, lon = (float(x) for x in args.center.split(","))
        center = (lat, lon)

    all_data = {}
    with httpx.Client(headers=UA, timeout=25) as c:
        for label, url in FOLDERS.items():
            token, fname, items = fetch_folder(c, url)
            all_data[label] = items
            print(f"[{label}] 폴더명='{fname}' {len(items)}개 수집", file=sys.stderr)

    if args.dump:
        json.dump(all_data, open(args.dump, "w", encoding="utf-8"), ensure_ascii=False)
        print(f"저장: {args.dump}", file=sys.stderr)

    for label, items in all_data.items():
        rows = []
        for b in items:
            addr = norm_addr(b.get("address"))
            if args.addr and args.addr not in addr and args.addr not in (b.get("name") or ""):
                continue
            d = None
            if center:
                py, px = b.get("py"), b.get("px")
                if not (py and px):
                    continue
                d = haversine_km(center[0], center[1], py, px)
                if d > args.radius:
                    continue
            rows.append((d if d is not None else 0.0, b, addr))
        rows.sort(key=lambda x: x[0])
        print(f"\n[{label}] {len(rows)}곳")
        for d, b, addr in rows:
            dist = f"{d * 1000:4.0f}m  " if center else ""
            print(f"  {dist}{b['name']} | {b.get('mcidName')} | {addr}")


if __name__ == "__main__":
    main()
