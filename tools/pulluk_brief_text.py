# -*- coding: utf-8 -*-
"""브리핑 초안 문장을 만든다.

Gemini가 채널 말투로 쓰고, 죽으면 템플릿이 대신 쓴다. 어느 쪽이든
'경험담은 지어내지 않는다'는 원칙을 지키려고 한줄평 자리에는 데이터로
확인된 사실만 넣고 ※확인 표시를 붙인다.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import httpx

from tools.pulluk_brief_core import TopicPlan, category_of, dong_of, review_of

PROJECT_ROOT = Path(__file__).resolve().parents[1]
STYLE_PATH = PROJECT_ROOT / "assets" / "pulluk" / "style_examples.json"

CLOSING_ROSTER = "나만 아는 {topic} 성지 있으면 풀어주세요\n(+) 팔로우 해두면 맛집/카페/볼거리 매일 올라옴"
CLOSING_COURSE = "앞으로 짜줄 코스 한 보따리 쌓여있다.\n(+) 팔로우 해두면 이제 주말에 뭐할지 고민할일 없음."


def load_styles(path: Path | None = None) -> list[str]:
    try:
        raw = json.loads((path or STYLE_PATH).read_text(encoding="utf-8"))
        return list(raw.get("examples") or [])
    except (OSError, ValueError):
        return []


def one_liner(place: dict) -> str:
    """데이터로 확인된 사실만 담은 한줄평 초안."""
    detail = place.get("d") or {}
    bits: list[str] = []
    cat = category_of(place)
    if cat:
        bits.append(cat.split(",")[0])
    if detail.get("r"):
        bits.append(f"리뷰 {int(detail['r']):,}")
    if detail.get("s"):
        bits.append(f"★{detail['s']}")
    if detail.get("h"):
        bits.append(str(detail["h"]))
    if detail.get("pk") == 1:
        bits.append("주차 가능")
    body = " · ".join(bits) if bits else "정보 보강 필요"
    return f"{body} ※확인"


def deep_dive_block(place: dict) -> str:
    """집중분석 1곳 블록."""
    if not place:
        return ""
    detail = place.get("d") or {}
    label = place.get("label") or dong_of(place.get("addr", ""))
    lines = [f"■ 오늘의 집중분석 — {place.get('name', '')}({label})"]
    lines.append(f"  주소: {place.get('addr', '')}")
    if category_of(place):
        lines.append(f"  업종: {category_of(place)}")
    if detail.get("r"):
        score = f" · ★{detail['s']}" if detail.get("s") else ""
        lines.append(f"  방문자 리뷰 {int(detail['r']):,}{score}")
    if detail.get("h"):
        lines.append(f"  영업 힌트: {detail['h']}")
    if detail.get("pk") == 1:
        lines.append(f"  주차: {detail.get('pkt') or '가능'}")
    if place.get("sid"):
        lines.append(f"  지도: https://map.naver.com/p/entry/place/{place['sid']}")
    return "\n".join(lines)


def template_draft(plan: TopicPlan) -> str:
    """AI 없이도 나오는 초안. 채널 고정 포맷을 그대로 따른다."""
    if not plan.places:
        return f"{plan.title}\n\n{plan.note}"

    if plan.kind in ("코스", "드라이브"):
        head = ("목적지 정해지면 코스부터 짜는 파워J가\n"
                f"{plan.topic} 코스 딱 짜드림.\n(광고 협찬 절대 아님)")
        body = "\n".join(
            f"{i}. 🚩{p['name']}({p.get('label') or dong_of(p.get('addr', ''))})\n{one_liner(p)}"
            for i, p in enumerate(plan.places, 1)
        )
        return f"{head}\n\n{body}\n\n{CLOSING_COURSE}"

    label = plan.topic.split(",")[0]
    head = f"내 기준 수도권 {label} 탑티어 족보 정리해봄.\n*광고/협찬 아님"
    body = "\n".join(
        f"{i}. {p['name']}({p.get('label') or dong_of(p.get('addr', ''))}) : {one_liner(p)}"
        for i, p in enumerate(plan.places, 1)
    )
    return f"{head}\n\n{body}\n\n{CLOSING_ROSTER.format(topic=label)}"


def build_prompt(plan: TopicPlan, styles: list[str]) -> str:
    facts = "\n".join(
        f"- {p['name']} / {p.get('label') or dong_of(p.get('addr', ''))}"
        f" / {category_of(p) or '업종 미상'}"
        f" / 리뷰 {review_of(p):,} / {(p.get('d') or {}).get('h') or '영업정보 없음'}"
        for p in plan.places
    )
    examples = "\n\n---\n\n".join(styles)
    return (
        "너는 아래 예시 글을 쓴 사람의 말투를 그대로 흉내내 스레드 게시글 초안을 쓴다.\n\n"
        f"[말투 예시]\n{examples}\n\n"
        f"[오늘 주제]\n{plan.title} ({plan.kind})\n"
        f"{'비 예보라 실내 위주다.' if plan.rainy else ''}\n\n"
        f"[쓸 수 있는 사실 — 이 목록 밖의 정보를 지어내지 마라]\n{facts}\n\n"
        "[규칙]\n"
        "1. 예시와 같은 오프닝·번호 목록·클로징 구조를 유지한다.\n"
        "2. 맛·분위기 같은 개인 경험은 절대 지어내지 말고, 위 사실만 근거로 쓴다.\n"
        "3. 각 항목의 한줄평 끝에 ' ※확인'을 붙인다.\n"
        "4. 400자 이내. 해설 없이 게시글 본문만 출력한다.\n"
    )


def gemini_draft(plan: TopicPlan, api_key: str | None, generate=None,
                 http=None, sleep=time.sleep) -> str | None:
    """Gemini 1콜. 어떤 이유로든 실패하면 None을 돌려주고 호출자가 폴백한다."""
    if not api_key or not plan.places:
        return None
    if generate is None:
        try:
            from willy.analyzer import gemini_generate
        except ImportError as exc:
            # CI에 의존성이 빠지면 매일 조용히 템플릿으로 떨어진다. 이유를 남긴다.
            print(f"Gemini 초안 실패({type(exc).__name__}) — 템플릿으로 대체", file=sys.stderr)
            return None
        generate = gemini_generate

    prompt = build_prompt(plan, load_styles())
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    client = http or httpx.Client(timeout=60.0)
    try:
        text = generate(client, api_key, payload, sleep)
    except Exception as exc:
        print(f"Gemini 초안 실패({type(exc).__name__}) — 템플릿으로 대체", file=sys.stderr)
        return None
    finally:
        if http is None:
            client.close()
    text = (text or "").strip()
    return text or None


def compose(plan: TopicPlan, api_key: str | None, generate=None) -> tuple[str, str]:
    draft = gemini_draft(plan, api_key, generate=generate)
    if draft:
        return draft, "ai"
    return template_draft(plan), "template"


def checklist(plan: TopicPlan) -> list[str]:
    checks = [
        "한줄평의 ※확인 표시는 직접 가본 경험으로 바꾸고 지울 것",
        "가격·영업시간·휴무는 게시 직전 최신인지 대조할 것",
    ]
    if any((p.get("d") or {}).get("pk") == 1 for p in plan.places):
        checks.append("주차 안내문은 매장 등록 정보라 실제와 다를 수 있음")
    if plan.rainy:
        checks.append("비 예보 기준으로 실내 위주로 짰다 — 날씨가 바뀌면 야외 슬롯 추가 가능")
    if plan.note:
        checks.append(f"기획 메모: {plan.note}")
    return checks
