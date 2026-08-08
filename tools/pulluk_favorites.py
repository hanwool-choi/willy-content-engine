# -*- coding: utf-8 -*-
"""최펄럭 채널용 네이버 지도 즐겨찾기 수집·지역 필터 도구.

고정 공유 폴더 3개(카페/식당/스팟)를 로그인 없이 수집해서
지역 키워드 또는 좌표 반경으로 필터링한 목록을 출력한다.
코스 콘텐츠는 이 출력 목록에 있는 장소만으로 구성하는 것이 원칙.

수집 로직은 `willy.pulluk.favorites`에 있다. 이 파일은 그 진입점이다.
코스 초안까지 한 번에 뽑으려면 `tools/pulluk_course.py`를 쓴다.

사용 예:
    python tools/pulluk_favorites.py --addr 성수
    python tools/pulluk_favorites.py --center 37.49794,127.02761 --radius 1.3
    python tools/pulluk_favorites.py --dump all.json          # 전체 목록을 파일로

주의:
- 사내망 TLS 프록시 때문에 truststore 주입 필수 (curl 불가, httpx 사용)
- 공유가 해제되면 수집이 실패한다 → 재공유 후 favorites.py의 FOLDERS 갱신
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import truststore  # noqa: E402  httpx보다 먼저 주입해야 한다

truststore.inject_into_ssl()

from willy.pulluk.favorites import (  # noqa: E402
    DEFAULT_CACHE,
    load_favorites,
    save_cache,
)
from willy.pulluk.models import haversine_km  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="네이버 즐겨찾기 수집·지역 필터")
    ap.add_argument("--addr", help="주소 포함 키워드 (예: 성수, 용산구)")
    ap.add_argument("--center", help="중심 좌표 lat,lon (예: 37.49794,127.02761)")
    ap.add_argument("--radius", type=float, default=1.3, help="반경 km (기본 1.3)")
    ap.add_argument("--dump", help="전체 목록을 JSON 파일로 저장 (캐시와 같은 형식)")
    ap.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    ap.add_argument("--refresh", action="store_true", help="캐시 무시하고 재수집")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stderr)

    center = None
    if args.center:
        lat, lon = (float(x) for x in args.center.split(","))
        center = (lat, lon)

    by_folder, failed = load_favorites(cache_path=args.cache, refresh=args.refresh)
    if failed:
        print(f"[경고] 수집 실패한 폴더: {', '.join(failed)}", file=sys.stderr)
    if not by_folder:
        print("즐겨찾기를 하나도 못 읽었다 (공유 해제 또는 네트워크 차단).", file=sys.stderr)
        return 1

    for label, places in by_folder.items():
        print(f"[{label}] {len(places)}개 수집", file=sys.stderr)

    if args.dump:
        save_cache(by_folder, Path(args.dump))
        print(f"저장: {args.dump}", file=sys.stderr)

    for label, places in by_folder.items():
        rows = []
        for p in places:
            if args.addr and args.addr not in p.address and args.addr not in p.name:
                continue
            d = None
            if center:
                if not p.has_coord:
                    continue
                d = haversine_km(center[0], center[1], p.lat, p.lon)
                if d > args.radius:
                    continue
            rows.append((d if d is not None else 0.0, p))
        rows.sort(key=lambda x: x[0])
        print(f"\n[{label}] {len(rows)}곳")
        for d, p in rows:
            dist = f"{d * 1000:4.0f}m  " if center else ""
            print(f"  {dist}{p.name} | {p.category} | {p.address}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
