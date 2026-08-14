# -*- coding: utf-8 -*-
"""즐겨찾기에서 메뉴·키워드로 장소를 모은다.

사용 예:
    python tools/pulluk_search.py 순대국
    python tools/pulluk_search.py 순대국 --folder 식당
    python tools/pulluk_search.py 냉면 칼국수 --area          # 지역별로 묶어서
    python tools/pulluk_search.py 순대국 --out drafts/sundae.md

'순댓국'처럼 사이시옷이 들어간 표기는 '순대'로 검색해도 안 걸린다.
표기 변형은 `willy.pulluk.search.TERM_ALIASES`가 펼쳐 준다.
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

from willy.pulluk.favorites import DEFAULT_CACHE, load_favorites  # noqa: E402
from willy.pulluk.search import expand_terms, group_by_area, search_places  # noqa: E402


def render(places, terms, grouped: bool) -> str:
    lines = [f"# 즐겨찾기 검색: {' / '.join(terms)} — {len(places)}곳", ""]
    if not places:
        lines.append("즐겨찾기에 걸리는 곳이 없다.")
        return "\n".join(lines)

    if grouped:
        for area, group in group_by_area(places).items():
            lines.append(f"## {area} ({len(group)})")
            for p in group:
                link = f" — {p.map_url}" if p.map_url else ""
                lines.append(f"- {p.name} | {p.category or '분류없음'} | {p.address}{link}")
            lines.append("")
    else:
        for p in places:
            link = f" — {p.map_url}" if p.map_url else ""
            lines.append(f"- {p.name} | {p.category or '분류없음'} | {p.address}{link}")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="즐겨찾기 메뉴·키워드 검색")
    ap.add_argument("terms", nargs="+", help="검색어 (예: 순대국)")
    ap.add_argument("--folder", action="append", help="볼 폴더 (카페/식당/스팟). 반복 지정 가능")
    ap.add_argument("--area", action="store_true", help="지역별로 묶어서 출력")
    ap.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    ap.add_argument("--refresh", action="store_true", help="캐시 무시하고 재수집")
    ap.add_argument("--out", type=Path, help="결과를 파일로 저장")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stderr)

    by_folder, failed = load_favorites(cache_path=args.cache, refresh=args.refresh)
    if failed:
        print(f"[경고] 수집 실패한 폴더: {', '.join(failed)}", file=sys.stderr)
    if not by_folder:
        print(
            "즐겨찾기를 하나도 못 읽었다 (공유 해제 또는 네트워크 차단).\n"
            "  - 공유 해제라면 재공유 후 favorites.py의 FOLDERS 링크를 갱신할 것",
            file=sys.stderr,
        )
        return 1

    expanded = expand_terms(args.terms)
    print(f"[검색어] {' / '.join(expanded)}", file=sys.stderr)

    places = search_places(by_folder, args.terms, folders=args.folder)
    text = render(places, args.terms, grouped=args.area)

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
        print(f"저장: {args.out}", file=sys.stderr)
    else:
        print(text)
    return 0 if places else 2


if __name__ == "__main__":
    raise SystemExit(main())
