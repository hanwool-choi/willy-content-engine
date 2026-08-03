"""매일 아침 배치가 게시하는 정적 보드 페이지.

로컬 앱과 달리 서버가 없다. 사진은 저장소에 올리지 않고 수집 시점의
CDN 주소로 바로 띄운다(핫링크) — 제3자 저작물을 재배포하지 않기 위해서다.
CDN 주소가 없는 룩(캡처 대체분)은 출처 링크만 남긴다.
"""
from __future__ import annotations

from datetime import datetime
from html import escape

from willy.models import DayWeather, Gender, LookAnalysis
from willy.pipeline import PipelineState

SOURCE_LABELS = {
    "musinsa_snap": "무신사",
    "wear_men": "WEAR M",
    "wear_women": "WEAR W",
    "uniqlo_men": "유니클로M",
    "uniqlo_women": "유니클로W",
    "manual": "직접",
}

GENDER_LABELS = {"men": "MEN", "women": "WOMEN"}


def _accent(day: DayWeather) -> str:
    """내일 날씨가 페이지의 액센트 색을 정한다. 로컬 앱과 같은 규칙."""
    if day.is_rainy:
        return "#2b4a8b"
    if day.temp_repr >= 30:
        return "#b0491f"
    if day.temp_repr <= 8:
        return "#4a5568"
    if day.temp_repr >= 17:
        return "#4f6d48"
    return "#3d5a80"


def _source_label(source: str) -> str:
    return SOURCE_LABELS.get(source, source)


def _photo(look: LookAnalysis, alt: str) -> str:
    """CDN 원본을 그대로 띄운다. 주소가 없으면 자리표시자를 둔다."""
    if not look.image_url:
        return '<div class="noimg">이미지 없음<br /><small>출처 링크로 확인</small></div>'
    return (
        f'<img src="{escape(look.image_url)}" alt="{escape(alt)}" '
        f'loading="lazy" referrerpolicy="no-referrer" />'
    )


def _source_link(look: LookAnalysis) -> str:
    if not look.source_url:
        return ""
    return (
        f'<a class="src-link" href="{escape(look.source_url)}" '
        f'target="_blank" rel="noopener noreferrer">원본 페이지 ↗</a>'
    )


def _slot_card(gender: Gender, pick: int, look: LookAnalysis, caveat: str | None) -> str:
    who = GENDER_LABELS.get(gender.value, "성별 미상")
    tags = " · ".join(escape(tag) for tag in look.style_tags)
    temp = (
        f'<span class="range">{look.temp_range[0]}~{look.temp_range[1]}℃ 적합</span>'
        if look.temp_range
        else ""
    )
    badges = ""
    if caveat:
        badges += '<span class="badge warn">조건부 추천</span>'
    if look.is_ai:
        badges += '<span class="badge ai">AI 생성 소스</span>'

    return f"""
      <div class="card{' is-warn' if caveat else ''}">
        <header><b>{who}</b><span>픽{pick + 1} · {escape(_source_label(look.source))}</span></header>
        {_photo(look, look.look_id)}
        {badges}
        {temp}
        <span class="tags">{tags}</span>
        {f'<span class="caveat">{escape(caveat)}</span>' if caveat else ''}
        {_source_link(look)}
      </div>"""


def _pool_card(look: LookAnalysis) -> str:
    who = GENDER_LABELS.get(look.gender.value, "성별 미상")
    tags = " · ".join(escape(tag) for tag in look.style_tags)
    temp = (
        f"{look.temp_range[0]}~{look.temp_range[1]}℃"
        if look.temp_range
        else "기온 미판정"
    )
    return f"""
      <div class="look">
        <span class="src">{escape(_source_label(look.source))}</span>
        {'<span class="badge ai">AI</span>' if look.is_ai else ''}
        {_photo(look, look.look_id)}
        <div class="meta"><b>{who}</b> · {temp}<br />{tags}</div>
        {_source_link(look)}
      </div>"""


def _text_card(index: int, entry: dict) -> str:
    return f"""
      <div class="text-card">
        <span class="tone">{escape(str(entry.get("tone", "")))}</span>
        <pre id="t{index}">{escape(str(entry.get("text", "")))}</pre>
        <button type="button" data-copy="{index}">복사</button>
      </div>"""


def render_site(
    state: PipelineState, texts: list[dict], generated_at: datetime
) -> str:
    day = state.week[0]
    accent = _accent(day)

    slots = "".join(
        _slot_card(gender, pick, look, state.caveats.get((slot_date, gender, pick)))
        for (slot_date, gender, pick), look in sorted(
            state.assignment.items(), key=lambda kv: (kv[0][0], kv[0][1].value, kv[0][2])
        )
        if look is not None
    )
    pool = "".join(_pool_card(look) for look in state.looks)
    text_cards = "".join(_text_card(i, entry) for i, entry in enumerate(texts))

    # 폴백이 동작하면 배치는 성공으로 끝난다. 페이지가 알려주지 않으면
    # 분석·텍스트가 빠진 날을 아무도 눈치채지 못한다.
    notice = (
        '<div class="notice">'
        + "<br />".join(escape(w.message) for w in state.warnings)
        + "</div>"
        if state.warnings
        else ""
    )

    return f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<meta name="robots" content="noindex" />
<title>내일 뭐입지? · {day.date.month:02d}/{day.date.day:02d}</title>
<style>
  :root {{
    --paper:#f1f2ef; --card:#fbfbf9; --ink:#1a1b1e; --ink-soft:#5c5f66;
    --line:#d8dad3; --accent:{accent};
    --serif:"RIDIBatang",Batang,"Noto Serif KR",serif;
    --sans:"Malgun Gothic","Apple SD Gothic Neo",sans-serif;
  }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--paper); color:var(--ink);
    font-family:var(--sans); font-size:14px; line-height:1.55; }}
  main {{ max-width:1060px; margin:0 auto; padding:28px 20px 80px; }}
  .lab {{ font-size:11px; letter-spacing:.35em; color:var(--ink-soft); }}
  h1 {{ font-family:var(--serif); font-size:clamp(28px,5vw,40px); font-weight:600;
    margin:2px 0 0; }}
  h1 .q {{ color:var(--accent); }}
  h2 {{ font-family:var(--serif); font-weight:600; font-size:19px; margin:34px 0 4px;
    display:flex; align-items:baseline; gap:10px; }}
  h2 .muted {{ font-family:var(--sans); font-size:12px; color:var(--ink-soft); }}
  .rule {{ height:1px; background:var(--line); margin-bottom:14px; }}
  .ticket {{ display:flex; align-items:center; gap:22px; flex-wrap:wrap;
    margin:18px 0 0; padding:16px 22px; background:var(--card);
    border:1px solid var(--line); border-left:6px solid var(--accent);
    border-radius:8px; }}
  .ticket .date {{ font-family:var(--serif); font-size:22px; }}
  .ticket .temp {{ font-family:var(--serif); font-size:30px; }}
  .ticket .temp small {{ font-size:15px; color:var(--ink-soft); }}
  .ticket .cell {{ display:flex; flex-direction:column; }}
  .ticket .label {{ font-size:10px; letter-spacing:.22em; color:var(--ink-soft); }}
  .grid {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(230px,1fr)); gap:14px; }}
  .pool {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(150px,1fr)); gap:10px; }}
  .card,.look,.text-card {{ background:var(--card); border:1px solid var(--line);
    border-radius:8px; padding:12px; display:flex; flex-direction:column; gap:8px; }}
  .card.is-warn {{ border-color:#9a6b15; }}
  .card header {{ display:flex; gap:8px; font-size:12px; align-items:baseline; }}
  .card header span {{ color:var(--ink-soft); }}
  .look {{ padding:7px; font-size:11px; position:relative; }}
  .look .src {{ position:absolute; top:11px; left:11px; z-index:1; font-size:10px;
    background:#ffffffd9; padding:2px 6px; border-radius:3px; }}
  img {{ width:100%; aspect-ratio:3/4; object-fit:cover; border-radius:4px;
    background:var(--paper); display:block; }}
  .noimg {{ width:100%; aspect-ratio:3/4; border-radius:4px; background:var(--paper);
    display:flex; flex-direction:column; align-items:center; justify-content:center;
    color:var(--ink-soft); font-size:12px; text-align:center; }}
  .badge {{ align-self:flex-start; font-size:11px; font-weight:700; padding:3px 8px;
    border-radius:4px; }}
  .badge.warn {{ color:#9a6b15; background:#f6edd9; }}
  .badge.ai {{ color:#6b21a8; background:#f3e8ff; }}
  .range {{ color:var(--accent); font-weight:600; font-size:12px; }}
  .tags,.meta {{ color:var(--ink-soft); font-size:12px; }}
  .meta b {{ color:var(--ink); }}
  .caveat {{ font-size:12px; color:#9a6b15; }}
  .src-link {{ font-size:11px; color:var(--accent); text-decoration:none; }}
  .src-link:hover {{ text-decoration:underline; }}
  .texts {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(280px,1fr)); gap:14px; }}
  .text-card .tone {{ font-weight:700; font-size:12px; letter-spacing:.08em; color:var(--accent); }}
  .text-card pre {{ margin:0; white-space:pre-wrap; word-break:break-word;
    font-family:var(--sans); font-size:13px; line-height:1.6; background:var(--paper);
    border-radius:6px; padding:12px; flex:1; }}
  .text-card button {{ align-self:flex-start; font:inherit; font-size:12px; cursor:pointer;
    background:var(--card); border:1px solid var(--line); border-radius:6px; padding:6px 12px; }}
  .text-card button:hover {{ border-color:var(--accent); }}
  .empty {{ color:var(--ink-soft); padding:20px 0; }}
  .notice {{ margin-top:14px; padding:10px 14px; border-radius:8px; font-size:13px;
    background:#f6edd9; color:#9a6b15; }}
  footer {{ margin-top:56px; padding-top:14px; border-top:1px solid var(--line);
    font-size:11px; color:var(--ink-soft); line-height:1.8; }}
</style>
</head>
<body>
<main>
  <span class="lab">CHOI WILLY LAB · 옷장연구소</span>
  <h1>내일 뭐입지<span class="q">?</span></h1>

  <section class="ticket">
    <span class="date">{day.date.month:02d}.{day.date.day:02d} ({day.weekday_ko})</span>
    <span class="temp">{day.temp_max}℃<small> / {day.temp_min}℃</small></span>
    <span class="cell"><span class="label">하늘</span><b>{escape(day.sky)}</b></span>
    <span class="cell"><span class="label">강수확률</span><b>{day.precip_prob}%</b></span>
  </section>

  {notice}

  <h2>내일의 보드</h2>
  <div class="rule"></div>
  <div class="grid">{slots or '<p class="empty">배정된 픽이 없습니다.</p>'}</div>

  <h2>텍스트 콘텐츠 <span class="muted">복사해서 바로 올릴 수 있는 3가지 톤</span></h2>
  <div class="rule"></div>
  <div class="texts">{text_cards or '<p class="empty">생성된 텍스트가 없습니다.</p>'}</div>

  <h2>수집된 룩 <span class="muted">{len(state.looks)}장</span></h2>
  <div class="rule"></div>
  <div class="pool">{pool or '<p class="empty">수집된 룩이 없습니다.</p>'}</div>

  <footer>
    {generated_at:%Y-%m-%d %H:%M} KST 자동 생성 · 매일 아침 8시 갱신<br />
    사진은 각 출처의 원본 주소를 그대로 표시합니다(재배포 아님). 발행에 쓰려면
    출처 링크에서 직접 확인하세요. 이미지·영상 생성과 업로드는 수동 진행합니다.
  </footer>
</main>
<script>
  document.addEventListener("click", async (event) => {{
    const button = event.target.closest("button[data-copy]");
    if (!button) return;
    await navigator.clipboard.writeText(
      document.getElementById("t" + button.dataset.copy).textContent
    );
    button.textContent = "복사됨 ✓";
    setTimeout(() => (button.textContent = "복사"), 1500);
  }});
</script>
</body>
</html>
"""
