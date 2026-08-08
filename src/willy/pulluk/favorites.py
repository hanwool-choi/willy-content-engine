"""네이버 지도 즐겨찾기 공유 폴더 수집.

고정 공유 폴더 3개(카페/식당/스팟)를 로그인 없이 읽어 Place 목록으로 바꾼다.
코스에는 이 목록에 있는 장소만 넣는 것이 채널 원칙이다
(docs/superpowers/specs/2026-08-07-pulluk-channel-design.md §11.2).

수집은 네트워크에 의존하므로 결과를 캐시에 남긴다. 코스를 짜는 쪽
(course.py)은 캐시만 있으면 오프라인에서도 돈다.

주의:
- 응답 JSON의 목록 키는 `bookmarkList` (bookmarks 아님)
- 공유가 해제되면 수집이 실패한다 → 재공유 후 새 링크로 FOLDERS 갱신
- 사내망/프록시 환경에서는 truststore 주입이 필요하다 (tools/ 진입점에서 처리)
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path

import httpx

from willy.pulluk.models import Place

log = logging.getLogger(__name__)

# 고정 즐겨찾기 공유 링크 (2026-08-07 등록)
FOLDERS: dict[str, str] = {
    "카페": "https://naver.me/x7efW1Yh",
    "식당": "https://naver.me/xbK62x9h",
    "스팟": "https://naver.me/GsBXIKaC",
}

API = "https://pages.map.naver.com/save-pages/api/maps-bookmark/v3/shares/{token}/bookmarks"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "Chrome/126.0 Safari/537.36"
    ),
    "Accept": "application/json",
}
PAGE_SIZE = 200

DEFAULT_CACHE = Path(".cache/pulluk_favorites.json")


def _to_place(raw: dict, folder: str) -> Place:
    """즐겨찾기 원본 한 건을 Place로. 좌표 키는 py(위도)/px(경도)다."""
    lat, lon = raw.get("py"), raw.get("px")
    sid = raw.get("sid")
    return Place(
        name=raw.get("name") or "",
        folder=folder,
        category=raw.get("mcidName"),
        address=normalize_address(raw.get("address")),
        lat=float(lat) if lat else None,
        lon=float(lon) if lon else None,
        place_id=str(sid) if sid else None,
    )


def normalize_address(addr: str | None) -> str:
    """지역 키워드 매칭이 표기 차이로 어긋나지 않게 광역시도명을 줄인다."""
    out = addr or ""
    for long, short in (
        ("서울특별시", "서울"),
        ("인천광역시", "인천"),
        ("부산광역시", "부산"),
        ("대구광역시", "대구"),
        ("대전광역시", "대전"),
        ("광주광역시", "광주"),
        ("울산광역시", "울산"),
        ("세종특별자치시", "세종"),
        ("경기도", "경기"),
        ("강원특별자치도", "강원"),
        ("강원도", "강원"),
        ("제주특별자치도", "제주"),
    ):
        out = out.replace(long, short)
    return out


def fetch_folder(client, short_url: str) -> tuple[str, str | None, list[dict]]:
    """공유 단축링크 하나를 끝까지 페이지네이션해 원본 목록을 가져온다."""
    r = client.get(short_url, follow_redirects=True)
    m = re.search(r"folder/([A-Za-z0-9]+)", str(r.url))
    if not m:
        raise RuntimeError(f"공유 링크에서 폴더 토큰을 찾지 못함: {short_url} -> {r.url}")
    token = m.group(1)
    headers = {"Referer": f"https://map.naver.com/p/favorite/sharedPlace/folder/{token}"}

    items: list[dict] = []
    start = 0
    folder_name: str | None = None
    while True:
        rr = client.get(
            API.format(token=token),
            params={"start": start, "limit": PAGE_SIZE},
            headers=headers,
        )
        rr.raise_for_status()
        data = rr.json()
        if folder_name is None:
            folder_name = (data.get("folder") or {}).get("name")
        page = data.get("bookmarkList") or data.get("bookmarks") or []
        if not page:
            break
        items.extend(page)
        start += len(page)
        if len(page) < PAGE_SIZE:
            break
    return token, folder_name, items


def fetch_favorites(
    folders: dict[str, str] | None = None,
    http=None,
) -> tuple[dict[str, list[Place]], list[str]]:
    """폴더별 Place 목록을 모은다.

    돌려주는 값은 (폴더별 목록, 실패한 폴더 라벨)이다. 한 폴더가 실패해도
    나머지는 모으되, 어느 폴더가 비었는지는 반드시 드러낸다 — 조용히 반쪽이
    되면 코스에 장소가 모자란 이유를 알 수 없다.
    """
    folders = folders if folders is not None else FOLDERS
    client = http or httpx.Client(timeout=25, headers=HEADERS, follow_redirects=True)

    by_folder: dict[str, list[Place]] = {}
    failed: list[str] = []
    for label, url in folders.items():
        try:
            _, folder_name, raw = fetch_folder(client, url)
        except Exception:
            log.exception("즐겨찾기 폴더 수집 실패: %s", label)
            failed.append(label)
            continue
        by_folder[label] = [_to_place(b, label) for b in raw]
        log.info("[%s] 폴더명='%s' %d개 수집", label, folder_name, len(by_folder[label]))
    return by_folder, failed


def save_cache(by_folder: dict[str, list[Place]], path: Path = DEFAULT_CACHE) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "collected_at": datetime.now().isoformat(timespec="seconds"),
        "folders": {k: [p.as_dict() for p in v] for k, v in by_folder.items()},
    }
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def load_cache(path: Path = DEFAULT_CACHE) -> tuple[dict[str, list[Place]], datetime | None]:
    """캐시를 읽는다. 없으면 (빈 dict, None)."""
    if not path.exists():
        return {}, None
    payload = json.loads(path.read_text(encoding="utf-8"))
    by_folder = {
        k: [Place.from_dict(d) for d in v] for k, v in (payload.get("folders") or {}).items()
    }
    stamp = payload.get("collected_at")
    return by_folder, datetime.fromisoformat(stamp) if stamp else None


def load_favorites(
    cache_path: Path = DEFAULT_CACHE,
    refresh: bool = False,
    http=None,
) -> tuple[dict[str, list[Place]], list[str]]:
    """캐시 우선으로 즐겨찾기를 얻는다. 없거나 refresh면 새로 수집한다.

    수집이 통째로 실패했는데 캐시가 남아 있으면 캐시로 되돌아간다 —
    네트워크가 막힌 자리에서도 코스 초안은 뽑을 수 있어야 한다.
    """
    if not refresh:
        cached, stamp = load_cache(cache_path)
        if cached:
            log.info("캐시 사용: %s (수집 시각 %s)", cache_path, stamp)
            return cached, []

    by_folder, failed = fetch_favorites(http=http)
    if by_folder:
        save_cache(by_folder, cache_path)
        return by_folder, failed

    cached, stamp = load_cache(cache_path)
    if cached:
        log.warning("수집 전부 실패 — 캐시로 대체합니다 (수집 시각 %s)", stamp)
        return cached, failed
    return {}, failed
