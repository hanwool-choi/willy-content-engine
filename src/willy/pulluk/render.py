"""코스를 스레드 게시물 초안으로 옮긴다.

말투는 §11.3의 확정 템플릿(반말 직설체)을 따른다. 즐겨찾기가 주는 것은
장소·주소·좌표뿐이라 [한 줄 코멘트]는 채울 수 없다 — 지어내지 않고
`___`로 비워 두고, 무엇을 채워야 하는지는 작업표에 적는다.
"""
from __future__ import annotations

from willy.pulluk.models import Course
from willy.pulluk.regions import Region

BLANK = "___"

OPENING = "목적지 정해지면 코스부터 짜는 파워J가"
DISCLAIMER = "(광고 협찬 절대 아님)"
CLOSING = (
    "앞으로 짜줄 코스가 무궁무진 너무 많다.\n"
    "(+) 팔로우 해두면 이제 주말에 뭐할지 고민할일 없음."
)


def render_briefing(course: Course, region: Region) -> str:
    """본문 초안. 그대로 복사해서 코멘트만 채우면 올릴 수 있는 상태로 낸다."""
    lines = [OPENING, f"{region.hook} {region.label} 코스 딱 짜드림.", DISCLAIMER, ""]

    n = 0
    for pick in course.picks:
        n += 1
        if pick.place is None:
            lines.append(f"{n}. ({pick.spec.role} — 즐겨찾기 후보 없음, 답사 후 채울 것)")
            continue
        lines.append(f"{n}. '{pick.place.name}' 가서 {pick.spec.action}. {BLANK}")

    lines.append("")
    if region.outro:
        lines.append(region.outro)
    lines.append(CLOSING)
    return "\n".join(lines)


def render_reply_addresses(course: Course) -> str:
    """답글1 — 주소·지도링크·이동거리. 저장 유도가 목적이라 링크가 본체다."""
    lines = ["📍 주소 정리"]
    for pick in course.filled:
        place = pick.place
        link = place.map_url or "(지도링크 확인 필요)"
        lines.append(f"· {place.name} — {place.address}")
        lines.append(f"  {link}")
    if course.travel_km:
        lines.append("")
        lines.append(
            f"지역 내 직선 이동 {course.travel_km}km "
            f"(실주행·주차 시간은 답사 때 실측할 것)"
        )
    return "\n".join(lines)


def render_reply_intake(region: Region) -> str:
    """답글2 — 투어지 접수. 다음 편 소재가 여기서 나온다."""
    return (
        "차 있는데 갈 데 없는 지역 있으면 댓글로. 다음 실내 코스 거기로 짬.\n"
        f"({region.label} 말고 어디 필요하세요?)"
    )


def render_worksheet(course: Course, region: Region) -> str:
    """답사·확정용 작업표. 게시물에는 안 들어간다."""
    lines = [f"# {region.label} 실내 드라이브 코스 — 작업표", ""]

    total_stay = sum(p.spec.stay_min for p in course.filled)
    lines.append(
        f"슬롯 {len(course.filled)}/{len(course.picks)}칸 · "
        f"체류 합계 {total_stay}분 · 지역 내 직선 이동 {course.travel_km}km"
    )
    lines.append("")

    for i, pick in enumerate(course.picks, 1):
        if pick.place is None:
            lines.append(f"## {i}. {pick.spec.role} — 후보 없음")
            lines.append(f"- 확인: {pick.spec.note}")
            lines.append("")
            continue
        place = pick.place
        lines.append(f"## {i}. {pick.spec.role} — {place.name}")
        lines.append(f"- 분류: {place.category or '미상'} / 폴더: {place.folder}")
        lines.append(f"- 주소: {place.address}")
        if place.map_url:
            lines.append(f"- 지도: {place.map_url}")
        lines.append(f"- 체류 {pick.spec.stay_min}분")
        lines.append(f"- 답사 확인: {pick.spec.note}")
        if pick.alternates:
            alts = ", ".join(p.name for p in pick.alternates)
            lines.append(f"- 대안: {alts}")
        lines.append("")

    lines.append("## 사전답사 공통 (§5 + 실내 4항목)")
    for item in (
        "네이버지도+인스타 교차 확인 (최근 3개월 내 후기)",
        "폐업·휴업 아님",
        "영업시간·브레이크타임·라스트오더 (요일별)",
        "웨이팅 정보 (캐치테이블/테이블링, 피크 시간)",
        "이동 동선 실측 (도보/차량 시간)",
        "주차 or 대중교통 접근",
        "가격대",
        "팝업·한철 장사 제외",
        "[실내] 냉난방·실내 규모",
        "[실내] 체류시간 제한",
        "[실내] 주차장→입구 노출 거리",
        "[실내] 실내 비중",
    ):
        lines.append(f"- [ ] {item}")

    if course.warnings:
        lines.append("")
        lines.append("## 경고")
        for w in course.warnings:
            lines.append(f"- {w}")

    lines.append("")
    lines.append(f"`{BLANK}` 자리는 직접 채울 것: 한 줄 코멘트, 실전 팁(웨이팅·자리·예약), "
                 "밖에 서 있는 시간 실측값")
    return "\n".join(lines)


def render_all(course: Course, region: Region) -> str:
    return "\n".join(
        [
            "=" * 60,
            "[본문]",
            "=" * 60,
            render_briefing(course, region),
            "",
            "=" * 60,
            "[답글1]",
            "=" * 60,
            render_reply_addresses(course),
            "",
            "=" * 60,
            "[답글2]",
            "=" * 60,
            render_reply_intake(region),
            "",
            "=" * 60,
            render_worksheet(course, region),
        ]
    )
