"""내일 날씨·픽 정보로 Threads 텍스트 콘텐츠를 3가지 톤으로 쓴다.

이미지·영상 생성은 사용자가 별도 엔진에서 수동으로 하므로, 이 모듈의
산출물이 발행 직전의 마지막 자동화 단계다. AI(Gemini)가 죽어도 초안
하나는 나오도록 템플릿 폴백을 둔다.
"""
from __future__ import annotations

import json
import re
import time

import httpx

from willy.analyzer import gemini_generate
from willy.ideas.models import IdeaItem
from willy.models import DayWeather, Gender, LookAnalysis

# 채널의 말투 기준. 사용자가 실제로 올린 글이다.
STYLE_EXAMPLE = """* 내일 34도 ‼️‼️‼️
8/2 (일)서울 기준 34도 + 바람도 거의 안 부는 찜통 더위.
덥지만 센스있게 입는게 제일 어려움.
1. 시어서커 반팔 셔츠 or 면 반팔
2. 슬랙스 반바지 or 면 반바지
3. 흰 양말에 로퍼
4. 팔찌/모자 액세서리 포인트
앞으로 날씨 기준 다음날 코디 자주 올릴 예정.
팔로우 해두면 입을 옷 고민 덜 함니다."""

TONES = (
    ("기본 정보형", "예시와 같은 반말 정보형. 숫자 목록으로 코디 요소를 짚는다"),
    ("담백 미니멀", "이모지·과장 없이 짧고 담백하게. 문장 수를 줄인다"),
    ("위트", "가볍게 웃긴 한 줄을 섞되 정보는 유지한다"),
)


def _looks_brief(looks: list[LookAnalysis]) -> str:
    lines = []
    for look in looks:
        gender = {"men": "남", "women": "여"}.get(look.gender.value, "공용")
        tags = ", ".join(look.style_tags) or "태그 없음"
        lines.append(f"- [{gender}] {tags}")
    return "\n".join(lines) or "- (픽 없음 — 날씨 중심으로 쓴다)"


def build_prompt(day: DayWeather, looks: list[LookAnalysis]) -> str:
    tone_lines = "\n".join(
        f"{i + 1}. {name}: {guide}" for i, (name, guide) in enumerate(TONES)
    )
    return f"""너는 Threads 패션 채널 '옷장연구소'의 작가다. 아래 예시 글의 말투와
구조를 기준으로, 내일 코디 추천 글을 서로 다른 3가지 톤으로 써라.

[말투 예시]
{STYLE_EXAMPLE}

[내일 날씨 — 서울]
{day.date.month}/{day.date.day} ({day.weekday_ko}) {day.sky},
최고 {day.temp_max}도 / 최저 {day.temp_min}도, 강수확률 {day.precip_prob}%

[내일의 픽]
{_looks_brief(looks)}

[톤 3종]
{tone_lines}

규칙:
- 각 글은 Threads 한 게시물 분량(500자 이내), 한국어
- 날씨 숫자를 첫 줄에 쓰고, 픽의 스타일 태그를 코디 요소로 녹인다
- 강수확률이 60% 이상이면 우산·방수 관련 한 줄을 넣는다
- 마지막 줄은 예시처럼 팔로우 유도로 끝낸다
- JSON 배열만 출력: [{{"tone": "톤 이름", "text": "본문"}}, ...] 정확히 3개"""


def _extract_json_array(text: str) -> list:
    fenced = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", text, re.S)
    candidate = fenced.group(1) if fenced else None
    if candidate is None:
        bracketed = re.search(r"\[.*\]", text, re.S)
        candidate = bracketed.group(0) if bracketed else None
    if candidate is None:
        raise ValueError(f"텍스트 결과를 파싱할 수 없습니다: {text[:120]}")
    try:
        return json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise ValueError(f"텍스트 결과를 파싱할 수 없습니다: {exc}") from exc


def template_texts(day: DayWeather, looks: list[LookAnalysis]) -> list[dict]:
    """AI 없이 예시 구조를 그대로 채운 초안. 폴백용이라 1종만 만든다."""
    tags: list[str] = []
    for look in looks:
        for tag in look.style_tags:
            if tag not in tags:
                tags.append(tag)
    items = "\n".join(f"{i + 1}. {tag}" for i, tag in enumerate(tags[:4]))
    rain = "\n비 소식 있음. 우산 챙기고 젖어도 되는 신발 추천." if day.is_rainy else ""

    body = (
        f"* 내일 {day.temp_max}도 ‼️\n"
        f"{day.date.month}/{day.date.day} ({day.weekday_ko}) 서울 기준 "
        f"{day.temp_max}도, {day.sky}.{rain}\n"
        f"내일의 픽 키워드:\n{items or '1. (수집된 태그 없음)'}\n"
        f"앞으로 날씨 기준 다음날 코디 자주 올릴 예정.\n"
        f"팔로우 해두면 입을 옷 고민 덜 함니다."
    )
    return [{"tone": "기본 정보형 (템플릿)", "text": body}]


class TextWriter:
    def __init__(self, api_key: str, http=None, sleep=None):
        self._api_key = api_key
        self._http = http or httpx.Client(timeout=60)
        self._sleep = sleep or time.sleep

    def write(self, day: DayWeather, looks: list[LookAnalysis]) -> list[dict]:
        payload = {
            "contents": [{"parts": [{"text": build_prompt(day, looks)}]}]
        }
        text = gemini_generate(self._http, self._api_key, payload, self._sleep)
        entries = _extract_json_array(text)

        cleaned = [
            {"tone": str(e.get("tone", "")), "text": str(e.get("text", ""))}
            for e in entries
            if isinstance(e, dict) and e.get("text")
        ]
        if len(cleaned) != 3:
            raise ValueError(f"텍스트 결과가 3개가 아닙니다: {len(cleaned)}개")
        return cleaned

    def write_from_ideas(
        self, items_with_details: list[tuple["IdeaItem", str]]
    ) -> list[dict]:
        """고른 패션 소식으로 3가지 톤을 쓴다. 말투 기준은 룩 글과 같다."""
        payload = {
            "contents": [{"parts": [{"text": build_idea_prompt(items_with_details)}]}]
        }
        text = gemini_generate(self._http, self._api_key, payload, self._sleep)
        entries = _extract_json_array(text)

        cleaned = [
            {"tone": str(e.get("tone", "")), "text": str(e.get("text", ""))}
            for e in entries
            if isinstance(e, dict) and e.get("text")
        ]
        if len(cleaned) != 3:
            raise ValueError(f"텍스트 결과가 3개가 아닙니다: {len(cleaned)}개")
        return cleaned


# ── 패션 소식(콘텐츠 아이디어 보울) ─────────────────────────

IDEA_TONES = (
    ("소식 전달형", "무슨 브랜드가 무엇을 언제 내는지 사실부터 짚는다"),
    ("의견 곁들임", "왜 살 만한지 한 줄 의견을 붙인다"),
    ("위트", "가볍게 웃긴 한 줄을 섞되 정보는 유지한다"),
)


def build_idea_prompt(items_with_details: list[tuple[IdeaItem, str]]) -> str:
    """패션 소식 -> Threads 텍스트 프롬프트. 말투 예시는 룩 글과 공유한다."""
    blocks = []
    for index, (item, detail) in enumerate(items_with_details, start=1):
        blocks.append(
            f"{index}. 제목: {item.title}\n"
            f"   출처: {item.source} / 분류: {item.category or '없음'}\n"
            f"   본문 발췌: {detail[:600]}"
        )
    tone_lines = "\n".join(
        f"{i + 1}. {name}: {guide}" for i, (name, guide) in enumerate(IDEA_TONES)
    )

    return f"""너는 Threads 패션 채널 '옷장연구소'의 작가다. 아래 예시 글의 말투를
기준으로, 주어진 패션 소식을 소개하는 글을 서로 다른 3가지 톤으로 써라.

[말투 예시]
{STYLE_EXAMPLE}

[소개할 소식]
{chr(10).join(blocks)}

[톤 3종]
{tone_lines}

규칙:
- 각 글은 Threads 한 게시물 분량(500자 이내), 한국어
- 본문 발췌에 있는 사실(브랜드·가격·발매일)만 쓴다. 없는 숫자를 지어내지 마라
- 소식이 여러 건이면 한 글에 묶어 소개한다
- 마지막 줄은 예시처럼 팔로우 유도로 끝낸다
- JSON 배열만 출력: [{{"tone": "톤 이름", "text": "본문"}}, ...] 정확히 3개"""


def template_idea_texts(items_with_details: list[tuple[IdeaItem, str]]) -> list[dict]:
    """AI 없이 제목만으로 만든 초안. 폴백용이라 1종만 만든다."""
    lines = "\n".join(
        f"{i}. {item.title}" for i, (item, _) in enumerate(items_with_details, start=1)
    )
    body = (
        "오늘의 패션 소식 ‼️\n"
        f"{lines or '1. (선택된 소식 없음)'}\n"
        "자세한 건 각 브랜드 채널에서 확인.\n"
        "팔로우 해두면 새 소식 놓칠 일 없습니다."
    )
    return [{"tone": "소식 전달형 (템플릿)", "text": body}]
