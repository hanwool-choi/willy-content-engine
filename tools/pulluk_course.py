# -*- coding: utf-8 -*-
"""즐겨찾기에서 코스 브리핑 초안을 뽑는다.

사용 예:
    python tools/pulluk_course.py --region paju
    python tools/pulluk_course.py --region ganghwa --refresh
    python tools/pulluk_course.py --region paju --radius 12 --out drafts/paju.md
    python tools/pulluk_course.py --list

첫 실행은 네이버 즐겨찾기를 수집해 `.cache/pulluk_favorites.json`에 남긴다.
두 번째부터는 캐시로 도니까 네트워크가 막힌 자리에서도 초안이 나온다
(--refresh로 강제 재수집).
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import truststore  # noqa: E402  사내망 TLS 프록시 — httpx보다 먼저 주입해야 한다

truststore.inject_into_ssl()

from willy.pulluk.course import build_course  # noqa: E402
from willy.pulluk.favorites import DEFAULT_CACHE, load_favorites  # noqa: E402
from willy.pulluk.regions import COURSE_SPECS, REGIONS  # noqa: E402
from willy.pulluk.render import render_all  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="즐겨찾기 기반 코스 브리핑 초안 생성")
    ap.add_argument("--region", help=f"지역 키 ({'/'.join(REGIONS)})")
    ap.add_argument("--course", default="indoor_drive", choices=sorted(COURSE_SPECS))
    ap.add_argument("--radius", type=float, help="지역 반경 km 재정의")
    ap.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    ap.add_argument("--refresh", action="store_true", help="캐시 무시하고 재수집")
    ap.add_argument("--out", type=Path, help="초안을 파일로 저장")
    ap.add_argument("--list", action="store_true", help="지역 목록만 출력")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stderr)

    if args.list:
        for key, region in REGIONS.items():
            print(f"{key:12} {region.label}  중심={region.center} 반경={region.radius_km}km")
        return 0

    if not args.region:
        ap.error("--region 이 필요하다 (--list 로 목록 확인)")
    if args.region not in REGIONS:
        ap.error(f"모르는 지역: {args.region} (가능: {', '.join(REGIONS)})")

    region = REGIONS[args.region]
    by_folder, failed = load_favorites(cache_path=args.cache, refresh=args.refresh)
    if failed:
        print(f"[경고] 수집 실패한 폴더: {', '.join(failed)}", file=sys.stderr)
    if not by_folder:
        print(
            "즐겨찾기를 하나도 못 읽었다. 공유가 풀렸거나 네트워크가 막혔다.\n"
            "  - 공유 해제라면 재공유 후 favorites.py의 FOLDERS 링크를 갱신할 것\n"
            "  - 네트워크라면 캐시(.cache/pulluk_favorites.json)를 옮겨와서 다시 실행할 것",
            file=sys.stderr,
        )
        return 1

    total = sum(len(v) for v in by_folder.values())
    counts = " / ".join(f"{k} {len(v)}" for k, v in by_folder.items())
    print(f"[즐겨찾기] 총 {total}곳 — {counts}", file=sys.stderr)

    course = build_course(
        by_folder,
        region,
        slots=COURSE_SPECS[args.course],
        radius_km=args.radius,
    )
    text = render_all(course, region)

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
        print(f"저장: {args.out}", file=sys.stderr)
    else:
        print(text)

    for w in course.warnings:
        print(f"[경고] {w}", file=sys.stderr)
    return 0 if course.is_complete else 2


if __name__ == "__main__":
    raise SystemExit(main())
