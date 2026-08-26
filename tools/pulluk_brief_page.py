# -*- coding: utf-8 -*-
"""브리핑 페이지 HTML.

카톡은 200자씩 끊겨 오니 복사·확인은 이 페이지에서 하는 게 편하다.
코스 스튜디오와 같은 색·서체를 써서 같은 채널의 도구로 보이게 한다.
"""
from __future__ import annotations

from datetime import date
from html import escape

from tools.pulluk_brief_core import TopicPlan, dong_of

WEEKDAYS = ("월", "화", "수", "목", "금", "토", "일")

STYLE = """
:root { --flag:#2447D6; --flag-deep:#1B36A8; --yellow:#F6BE2C; --paper:#FFF9EC;
        --ink:#221D16; --signal:#E8442E; --card:#fff; --muted:#7A6F60; }
* { margin:0; padding:0; box-sizing:border-box; }
body { font-family:'Pretendard Variable',Pretendard,-apple-system,sans-serif;
       background:var(--paper); color:var(--ink); line-height:1.6; }
header { background:var(--yellow); border-bottom:3px solid var(--ink); padding:22px clamp(16px,4vw,40px); }
header .eyebrow { font-size:13px; letter-spacing:.12em; color:var(--flag-deep); font-weight:700; }
header h1 { font-size:clamp(22px,4vw,32px); line-height:1.2; margin-top:2px; }
main { max-width:820px; margin:0 auto; padding:24px clamp(16px,4vw,40px) 72px; }
section { background:var(--card); border:2px solid var(--ink); border-radius:12px;
          padding:18px; margin-bottom:18px; box-shadow:4px 4px 0 rgba(34,29,22,.12); }
h2 { font-size:18px; margin-bottom:10px; }
textarea { width:100%; min-height:320px; padding:14px; font:inherit; line-height:1.7;
           border:2px solid var(--ink); border-radius:10px; background:var(--paper); resize:vertical; }
button.copy { margin-top:10px; padding:11px 22px; font:inherit; font-weight:700; cursor:pointer;
              background:var(--yellow); border:2px solid var(--ink); border-radius:9px;
              box-shadow:3px 3px 0 var(--ink); }
ul { list-style:none; } li { padding:5px 0; border-bottom:1px dashed #e3d9c4; font-size:14px; }
li:last-child { border-bottom:0; }
a { color:var(--flag-deep); }
.check li { color:var(--signal); }
.meta { font-size:13px; color:var(--muted); margin-top:4px; }
pre { white-space:pre-wrap; font:inherit; font-size:14px; }
"""


def _head(title: str) -> str:
    return (
        "<!DOCTYPE html><html lang=\"ko\"><head><meta charset=\"UTF-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\">"
        f"<title>{escape(title)}</title>"
        "<link rel=\"icon\" href=\"data:image/svg+xml,"
        "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'>"
        "<text y='.9em' font-size='90'>🚩</text></svg>\">"
        "<link rel=\"stylesheet\" as=\"style\" crossorigin "
        "href=\"https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/"
        "pretendardvariable-dynamic-subset.min.css\">"
        f"<style>{STYLE}</style></head><body>"
    )


def render_brief(plan: TopicPlan, draft: str, checks: list[str], day: date, source: str) -> str:
    label = f"{day.isoformat()}({WEEKDAYS[day.weekday()]})"
    written = "AI 초안" if source == "ai" else "템플릿 초안"

    places_html = "".join(
        f"<li><a href=\"https://map.naver.com/p/entry/place/{escape(str(p.get('sid', '')))}\""
        " target=\"_blank\" rel=\"noopener\">"
        f"{escape(p.get('name', ''))}</a>"
        f" · {escape(p.get('label') or dong_of(p.get('addr', '')))}"
        f" · {escape(str((p.get('d') or {}).get('c') or ''))}</li>"
        for p in plan.places
    ) or "<li>선정된 장소가 없습니다</li>"

    deep = plan.deep or {}
    deep_detail = deep.get("d") or {}
    deep_rows = []
    if deep:
        deep_rows.append(f"<li>주소 · {escape(deep.get('addr', ''))}</li>")
        if deep_detail.get("r"):
            score = f" · ★{deep_detail['s']}" if deep_detail.get("s") else ""
            deep_rows.append(f"<li>방문자 리뷰 {int(deep_detail['r']):,}{escape(score)}</li>")
        if deep_detail.get("h"):
            deep_rows.append(f"<li>영업 힌트 · {escape(str(deep_detail['h']))}</li>")
        if deep_detail.get("pk") == 1:
            deep_rows.append(f"<li>주차 · {escape(str(deep_detail.get('pkt') or '가능'))}</li>")
    deep_html = "".join(deep_rows) or "<li>집중분석 대상이 없습니다</li>"

    checks_html = "".join(f"<li>{escape(c)}</li>" for c in checks) or "<li>확인할 항목 없음</li>"

    return (
        _head(f"{label} 최펄럭 브리핑")
        + "<header><div class=\"eyebrow\">최펄럭 데일리 브리핑</div>"
        + f"<h1>🚩 {escape(plan.title)}</h1>"
        + f"<div class=\"meta\">{escape(label)} · {escape(plan.kind)} · {escape(written)}</div></header>"
        + "<main>"
        + "<section><h2>게시 초안</h2>"
        + f"<textarea id=\"draft\" spellcheck=\"false\">{escape(draft)}</textarea>"
        + "<button class=\"copy\" id=\"copyBtn\">초안 복사</button></section>"
        + f"<section><h2>오늘의 장소</h2><ul>{places_html}</ul></section>"
        + f"<section><h2>집중분석 — {escape(deep.get('name', '없음'))}</h2><ul>{deep_html}</ul></section>"
        + f"<section><h2>게시 전 확인</h2><ul class=\"check\">{checks_html}</ul></section>"
        + "<p class=\"meta\"><a href=\"index.html\">지난 브리핑 보기</a></p>"
        + "</main>"
        + "<script>document.getElementById('copyBtn').addEventListener('click',function(){"
          "var t=document.getElementById('draft');"
          "navigator.clipboard.writeText(t.value).then(function(){"
          "var b=document.getElementById('copyBtn');b.textContent='복사됨 🚩';"
          "setTimeout(function(){b.textContent='초안 복사';},1400);});});</script>"
        + "</body></html>"
    )


def render_index(archive: list[dict]) -> str:
    rows = sorted(archive, key=lambda e: e.get("date", ""), reverse=True)
    items = "".join(
        f"<li><a href=\"{escape(e.get('date', ''))}.html\">{escape(e.get('date', ''))}</a>"
        f" · {escape(e.get('kind', ''))} · {escape(e.get('title', ''))}</li>"
        for e in rows
    ) or "<li>아직 브리핑이 없습니다</li>"
    return (
        _head("최펄럭 브리핑 아카이브")
        + "<header><div class=\"eyebrow\">최펄럭 데일리 브리핑</div><h1>지난 브리핑</h1></header>"
        + f"<main><section><ul>{items}</ul></section></main></body></html>"
    )
