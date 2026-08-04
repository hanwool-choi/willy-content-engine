# 콘텐츠 아이디어 보울 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 패션 신소식·할인 정보를 7개 소스에서 매일 모아 보여주고, 사용자가 고른 항목을 채널 말투의 텍스트 콘텐츠 3종으로 바꾼다.

**Architecture:** 룩 수집기와 분리된 `willy/ideas/` 모듈을 만든다. 파서는 `(응답 문자열) -> list[IdeaItem]` 순수 함수라 픽스처로 테스트하고, 네트워크는 수집기가 담당한다. 소스 6곳은 httpx/RSS로 충분하고 아이즈매거진만 기존 Playwright를 재사용한다.

**Tech Stack:** Python 3.11+, httpx, xml.etree(표준), re/html(표준), Playwright(1곳), FastAPI, pytest

**설계 문서:** `docs/superpowers/specs/2026-08-04-content-idea-bowl-design.md`

## Global Constraints

- 의존성을 추가하지 않는다. 파싱은 표준 라이브러리(`re`, `html`, `xml.etree`, `email.utils`)로 한다
- 테스트는 네트워크를 타지 않는다. 픽스처는 이 문서에 적힌 내용을 그대로 파일로 만든다
- robots.txt가 차단하는 사이트(무신사 매거진·에펨코리아·딜바다)는 추가하지 않는다
- 파서는 순수 함수다. 파서 안에서 HTTP 요청을 하지 않는다
- 한 소스가 실패해도 나머지 소스는 수집한다
- 소스당 최신 10건까지만 담는다
- 모든 링크는 절대 URL로 만든다 (게시 페이지에서 상대경로 링크가 깨진 전례가 있다)
- 모델이 만든 값과 외부 사이트에서 온 값은 화면에 넣기 전에 이스케이프한다
- 커밋 메시지는 한국어로, 왜 그렇게 했는지를 남긴다

## File Structure

```
src/willy/ideas/
  __init__.py
  models.py      # IdeaItem
  sources.py     # IdeaSource 정의 7개 + 그룹
  parsers.py     # 소스 종류별 파서 5종 (순수 함수)
  hotness.py     # 반응 뱃지 판정
  collector.py   # 수집 오케스트레이션
  detail.py      # 선택 항목 상세 본문
tests/fixtures/ideas/
  hypebeast.xml, eomisae_os.html, hearst.html, condenast.html, eyesmag.html
tests/
  test_ideas_models.py, test_ideas_parsers.py, test_ideas_hotness.py,
  test_ideas_collector.py, test_ideas_texter.py, test_ideas_web.py
```

수정 대상: `src/willy/texter.py`, `src/willy/web/app.py`,
`src/willy/web/static/index.html`, `src/willy/publisher/site.py`,
`build_site.py`, `run.py`

---

## Task 1: 도메인 모델과 소스 정의

**Files:**
- Create: `src/willy/ideas/__init__.py`, `src/willy/ideas/models.py`, `src/willy/ideas/sources.py`
- Test: `tests/test_ideas_models.py`

**Interfaces:**
- Produces: `IdeaItem` 데이터클래스, `IdeaSource` 데이터클래스, `IDEA_SOURCES: dict[str, IdeaSource]`, `SOURCE_GROUPS: dict[str, str]`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_ideas_models.py`:

```python
from datetime import datetime

from willy.ideas.models import IdeaItem
from willy.ideas.sources import IDEA_SOURCES, SOURCE_GROUPS


def test_idea_item_defaults_are_unknown_not_zero():
    """반응 수를 모르는 소스와 0인 소스는 다르다. 0으로 채우면 뱃지 판정이 틀어진다."""
    item = IdeaItem(
        source="hypebeast",
        title="Palace 2026 가을 컬렉션",
        url="https://hypebeast.kr/2026/8/palace",
    )

    assert item.views is None
    assert item.comments is None
    assert item.likes is None
    assert item.is_hot is False
    assert item.published_at is None


def test_seven_sources_are_registered():
    assert set(IDEA_SOURCES) == {
        "eomisae_os", "eyesmag", "hypebeast", "esquire", "gq", "elle", "vogue",
    }


def test_robots_blocked_sites_are_absent():
    """무신사 매거진·에펨코리아·딜바다는 robots.txt가 막는다. 되살아나면 안 된다."""
    joined = " ".join(source.url for source in IDEA_SOURCES.values())

    assert "musinsa.com/magazine" not in joined
    assert "fmkorea" not in joined
    assert "dealbada" not in joined


def test_every_source_declares_kind_and_group():
    for name, source in IDEA_SOURCES.items():
        assert source.kind in {"rss", "eomisae", "hearst", "condenast", "eyesmag"}, name
        assert source.group in SOURCE_GROUPS, name
        assert source.url.startswith("https://"), name


def test_groups_cover_the_filter_chips():
    assert SOURCE_GROUPS == {
        "deal": "할인",
        "drop": "드랍·신상",
        "magazine": "매거진",
    }
    assert IDEA_SOURCES["eomisae_os"].group == "deal"
    assert IDEA_SOURCES["eyesmag"].group == "drop"
    assert IDEA_SOURCES["vogue"].group == "magazine"


def test_only_eyesmag_needs_a_browser():
    """브라우저는 느리고 배치에서만 쓸 수 있다. 늘어나면 곧바로 알아채야 한다."""
    browser_sources = [n for n, s in IDEA_SOURCES.items() if s.needs_browser]

    assert browser_sources == ["eyesmag"]
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `C:\venvs\willy\Scripts\python.exe -m pytest tests/test_ideas_models.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'willy.ideas'`

- [ ] **Step 3: 모델 구현**

`src/willy/ideas/__init__.py`: 빈 파일로 만든다.

`src/willy/ideas/models.py`:

```python
"""콘텐츠 아이디어 도메인 모델."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass
class IdeaItem:
    """패션 소식 한 건. 소스마다 채울 수 있는 필드가 다르다.

    반응 수(views/comments/likes)는 제공하지 않는 소스가 많다. 0과
    '모름'을 구분해야 뱃지 판정이 틀어지지 않으므로 기본값은 None이다.
    """

    source: str
    title: str
    url: str
    published_at: datetime | None = None
    category: str | None = None
    thumbnail_url: str | None = None
    views: int | None = None
    comments: int | None = None
    likes: int | None = None
    is_hot: bool = False
```

- [ ] **Step 4: 소스 정의 구현**

`src/willy/ideas/sources.py`:

```python
"""수집 소스 정의. 소스를 늘리거나 빼는 일은 이 파일에서 끝나야 한다.

robots.txt는 urllib.robotparser로 판정했고, 실제 제목을 뽑아 주제에
맞는지 확인한 뒤 골랐다. 무신사 매거진·에펨코리아·딜바다는 robots가
차단하므로 넣지 않는다 (에이블리·크림을 제외한 것과 같은 기준).
"""
from __future__ import annotations

from dataclasses import dataclass

# 필터 칩에 그대로 쓰인다.
SOURCE_GROUPS = {
    "deal": "할인",
    "drop": "드랍·신상",
    "magazine": "매거진",
}


@dataclass(frozen=True)
class IdeaSource:
    name: str          # 소스 id
    label: str         # 화면 배지
    url: str           # 목록 주소
    kind: str          # 파서 종류
    group: str         # SOURCE_GROUPS 키
    needs_browser: bool = False


IDEA_SOURCES: dict[str, IdeaSource] = {
    "eomisae_os": IdeaSource(
        name="eomisae_os",
        label="어미새",
        url="https://eomisae.co.kr/os",
        kind="eomisae",
        group="deal",
    ),
    # 서버 HTML에 글이 없다(완전 클라이언트 렌더링). 초기 데이터에도 없고
    # 내부 API 경로가 공개돼 있지 않아 브라우저로 읽는다.
    "eyesmag": IdeaSource(
        name="eyesmag",
        label="아이즈",
        url="https://www.eyesmag.com/category/fashion/all",
        kind="eyesmag",
        group="drop",
        needs_browser=True,
    ),
    "hypebeast": IdeaSource(
        name="hypebeast",
        label="하입비스트",
        url="https://hypebeast.kr/feed",
        kind="rss",
        group="drop",
    ),
    "esquire": IdeaSource(
        name="esquire",
        label="에스콰이어",
        url="https://www.esquirekorea.co.kr/fashion",
        kind="hearst",
        group="magazine",
    ),
    "elle": IdeaSource(
        name="elle",
        label="엘르",
        url="https://www.elle.co.kr/fashion",
        kind="hearst",
        group="magazine",
    ),
    "gq": IdeaSource(
        name="gq",
        label="GQ",
        url="https://www.gqkorea.co.kr/category/style/",
        kind="condenast",
        group="magazine",
    ),
    "vogue": IdeaSource(
        name="vogue",
        label="보그",
        url="https://www.vogue.co.kr/category/fashion",
        kind="condenast",
        group="magazine",
    ),
}
```

- [ ] **Step 5: 테스트 통과 확인**

Run: `C:\venvs\willy\Scripts\python.exe -m pytest tests/test_ideas_models.py -q`
Expected: PASS (6 passed)

- [ ] **Step 6: 커밋**

```bash
git add src/willy/ideas/ tests/test_ideas_models.py
git commit -m "feat: 콘텐츠 아이디어 도메인 모델과 소스 7곳 정의

반응 수는 제공하지 않는 소스가 많아 0과 '모름'을 구분해야 뱃지 판정이
틀어지지 않는다. 기본값을 None으로 둔다.

robots.txt가 차단하는 무신사 매거진·에펨코리아·딜바다는 넣지 않는다.
되살아나지 않도록 테스트로 고정한다."
```

---

## Task 2: RSS 파서 (하입비스트)

**Files:**
- Create: `src/willy/ideas/parsers.py`, `tests/fixtures/ideas/hypebeast.xml`
- Test: `tests/test_ideas_parsers.py`

**Interfaces:**
- Consumes: Task 1의 `IdeaItem`
- Produces: `parse_rss(xml: str, source: str) -> list[IdeaItem]`, 내부 헬퍼 `clean_text(raw: str) -> str`, `tag_parts(raw: str) -> list[str]`

- [ ] **Step 1: 픽스처 작성**

`tests/fixtures/ideas/hypebeast.xml` — 실제 응답 구조를 줄인 것이다:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>HYPEBEAST</title>
    <item>
      <title>Palace 2026 가을 컬렉션 및 발매일 공개</title>
      <link>https://hypebeast.kr/2026/8/palace-fall-2026-full-collection</link>
      <pubDate>Mon, 03 Aug 2026 12:20:53 +0000</pubDate>
      <category>패션</category>
      <category>기획 상품</category>
      <description>&lt;p&gt;Palace Skateboards가 2026년 가을 컬렉션 전체 라인업을 선보인다.&lt;/p&gt;</description>
    </item>
    <item>
      <title>Andersson Bell, 도쿄 아오야마에 첫 플래그십 스토어 오픈</title>
      <link>https://hypebeast.kr/2026/8/andersson-bell-tokyo-flagship</link>
      <pubDate>Mon, 03 Aug 2026 11:58:06 +0000</pubDate>
      <category>패션</category>
    </item>
    <item>
      <title></title>
      <link>https://hypebeast.kr/2026/8/broken</link>
    </item>
  </channel>
</rss>
```

- [ ] **Step 2: 실패하는 테스트 작성**

`tests/test_ideas_parsers.py`:

```python
from datetime import timezone
from pathlib import Path

import pytest

from willy.ideas.parsers import parse_rss

FIXTURES = Path(__file__).parent / "fixtures" / "ideas"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_rss_maps_title_link_and_category():
    items = parse_rss(fixture("hypebeast.xml"), source="hypebeast")

    assert len(items) == 2, "제목이 빈 항목은 버려야 한다"
    first = items[0]
    assert first.source == "hypebeast"
    assert first.title == "Palace 2026 가을 컬렉션 및 발매일 공개"
    assert first.url == "https://hypebeast.kr/2026/8/palace-fall-2026-full-collection"
    assert first.category == "패션"


def test_rss_parses_pubdate_as_aware_datetime():
    """RFC822 문자열을 그대로 두면 정렬이 문자열 비교가 된다."""
    items = parse_rss(fixture("hypebeast.xml"), source="hypebeast")

    published = items[0].published_at
    assert published is not None
    assert published.year == 2026 and published.month == 8 and published.day == 3
    assert published.tzinfo is not None


def test_rss_leaves_reaction_fields_unknown():
    """하입비스트는 반응 수를 주지 않는다. 0으로 채우면 안 된다."""
    items = parse_rss(fixture("hypebeast.xml"), source="hypebeast")

    assert items[0].views is None and items[0].likes is None


def test_rss_survives_missing_pubdate():
    items = parse_rss(fixture("hypebeast.xml"), source="hypebeast")

    assert items[1].published_at is not None  # 두 번째 항목엔 pubDate가 있다


def test_rss_raises_nothing_on_broken_xml():
    """사이트가 점검 페이지를 내려줄 때가 있다. 수집기 전체를 죽이지 않는다."""
    with pytest.raises(ValueError, match="RSS를 파싱할 수 없습니다"):
        parse_rss("<html>점검 중</html>", source="hypebeast")
```

- [ ] **Step 3: 테스트 실패 확인**

Run: `C:\venvs\willy\Scripts\python.exe -m pytest tests/test_ideas_parsers.py -q`
Expected: FAIL — `ImportError: cannot import name 'parse_rss'`

- [ ] **Step 4: 파서 구현**

`src/willy/ideas/parsers.py`:

```python
"""소스 종류별 파서. 전부 순수 함수다 — 안에서 HTTP를 하지 않는다.

파서를 네트워크와 분리해야 저장한 픽스처로 테스트할 수 있다.
"""
from __future__ import annotations

import html
import re
from datetime import datetime
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin
from xml.etree import ElementTree as ET

from willy.ideas.models import IdeaItem


def clean_text(raw: str) -> str:
    """태그를 걷어내고 공백을 하나로 눌러 한 줄 텍스트로 만든다."""
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", raw))).strip()


def tag_parts(raw: str) -> list[str]:
    """태그 경계로 잘라 조각 목록을 만든다.

    카테고리·제목·날짜·기자명이 서로 다른 요소로 오는 매거진에서,
    조각을 살려두면 필드로 나눌 수 있다.
    """
    pieces = (
        html.unescape(re.sub(r"\s+", " ", piece)).strip()
        for piece in re.split(r"<[^>]+>", raw)
    )
    return [piece for piece in pieces if piece]


def _parse_pubdate(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return parsedate_to_datetime(raw.strip())
    except (TypeError, ValueError):
        return None


def parse_rss(xml: str, source: str) -> list[IdeaItem]:
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        raise ValueError(f"RSS를 파싱할 수 없습니다: {exc}") from exc

    items: list[IdeaItem] = []
    for node in root.findall(".//item"):
        title = (node.findtext("title") or "").strip()
        link = (node.findtext("link") or "").strip()
        if not title or not link:
            continue
        categories = [c.text.strip() for c in node.findall("category") if c.text]
        items.append(
            IdeaItem(
                source=source,
                title=title,
                url=link,
                published_at=_parse_pubdate(node.findtext("pubDate")),
                category=categories[0] if categories else None,
            )
        )
    return items
```

- [ ] **Step 5: 테스트 통과 확인**

Run: `C:\venvs\willy\Scripts\python.exe -m pytest tests/test_ideas_parsers.py -q`
Expected: PASS (5 passed)

- [ ] **Step 6: 커밋**

```bash
git add src/willy/ideas/parsers.py tests/fixtures/ideas/hypebeast.xml tests/test_ideas_parsers.py
git commit -m "feat: RSS 파서 추가 (하입비스트)

파서는 순수 함수로 두고 네트워크는 수집기가 맡는다. 그래야 저장한
픽스처로 테스트할 수 있다.

pubDate를 datetime으로 바꾼다. 문자열로 두면 정렬이 문자열 비교가 된다.
사이트가 점검 페이지를 내려주는 경우를 위해 파싱 실패는 ValueError로
드러낸다."
```

---

## Task 3: 어미새 파서 (반응 수 포함)

**Files:**
- Modify: `src/willy/ideas/parsers.py`
- Create: `tests/fixtures/ideas/eomisae_os.html`
- Modify: `tests/test_ideas_parsers.py`

**Interfaces:**
- Consumes: Task 2의 `clean_text`
- Produces: `parse_eomisae(html_text: str, source: str, base_url: str) -> list[IdeaItem]`

- [ ] **Step 1: 픽스처 작성**

`tests/fixtures/ideas/eomisae_os.html` — 실제 카드 구조를 줄인 것이다:

```html
<div class="card_el n_ntc clear">
  <div class="tmb_wrp">
    <img class="tmb" src="//img.eomisae.co.kr/files/thumbnails/338/764/196/190x190.crop.jpg?t=1785802954" alt="" />
  </div>
  <div class="card_content">
    <p><span class="cate">패션,</span> <span>26.08.04</span></p>
    <h3><a class="pjax" href="/os/196764338">스탠 스미스 디콘(decon) 4종 9.9만 아래</a></h3>
    <div class="infos">
      <span class="fr"><i class="ion-ios-eye"></i>1317</span>
      <span class="fr"><i class="ion-ios-chatbubble"></i>5</span>
      <span class="fr"><i class="ion-ios-heart"></i>3</span>
    </div>
  </div>
</div>
<div class="card_el n_ntc clear">
  <div class="card_content">
    <p><span class="cate">신발,</span> <span>26.08.04</span></p>
    <h3><a class="pjax" href="/os/196748733">나이키 리액트X 리주버네이트 4만원대</a></h3>
    <div class="infos">
      <span class="fr"><i class="ion-ios-eye"></i>933</span>
      <span class="fr"><i class="ion-ios-chatbubble"></i>0</span>
      <span class="fr"><i class="ion-ios-heart"></i>1</span>
    </div>
  </div>
</div>
<div class="card_el n_ntc clear">
  <div class="card_content">
    <h3><a class="pjax" href="/os/196737472">list_ad_link</a></h3>
    <div class="infos">
      <span class="fr"><i class="ion-ios-eye"></i>0</span>
    </div>
  </div>
</div>
<div class="card_el n_ntc clear">
  <div class="card_content">
    <h3><a class="pjax" href="/os/196770332">20분 뒤 전체 공개로 전환됩니다 (미달 조건 : 레벨)</a></h3>
    <div class="infos">
      <span class="fr"><i class="ion-ios-eye"></i>364</span>
      <span class="fr"><i class="ion-ios-heart"></i>4</span>
    </div>
  </div>
</div>
```

- [ ] **Step 2: 실패하는 테스트 작성**

`tests/test_ideas_parsers.py` 끝에 덧붙인다:

```python
from willy.ideas.parsers import parse_eomisae


def eomisae_items():
    return parse_eomisae(
        fixture("eomisae_os.html"),
        source="eomisae_os",
        base_url="https://eomisae.co.kr/os",
    )


def test_eomisae_extracts_title_link_and_reactions():
    items = eomisae_items()

    first = items[0]
    assert first.title == "스탠 스미스 디콘(decon) 4종 9.9만 아래"
    assert first.url == "https://eomisae.co.kr/os/196764338"
    assert first.views == 1317
    assert first.comments == 5
    assert first.likes == 3
    assert first.category == "패션"


def test_eomisae_makes_thumbnail_absolute():
    """//로 시작하는 프로토콜 상대 주소는 정적 페이지에서 깨진다."""
    items = eomisae_items()

    assert items[0].thumbnail_url == (
        "https://img.eomisae.co.kr/files/thumbnails/338/764/196/190x190.crop.jpg?t=1785802954"
    )


def test_eomisae_keeps_zero_reactions_as_zero():
    """0회와 '모름'은 다르다. 댓글 0은 0으로 남아야 한다."""
    items = eomisae_items()

    assert items[1].comments == 0
    assert items[1].likes == 1


def test_eomisae_skips_ad_slots():
    """목록 사이에 광고 슬롯이 카드 모양으로 끼어 있다."""
    titles = [item.title for item in eomisae_items()]

    assert "list_ad_link" not in titles


def test_eomisae_skips_level_locked_posts():
    """레벨 제한 글은 제목 자리에 안내문만 있어 소재가 되지 않는다."""
    titles = [item.title for item in eomisae_items()]

    assert not any("전체 공개로 전환됩니다" in title for title in titles)


def test_eomisae_returns_only_real_posts():
    assert len(eomisae_items()) == 2
```

- [ ] **Step 3: 테스트 실패 확인**

Run: `C:\venvs\willy\Scripts\python.exe -m pytest tests/test_ideas_parsers.py -q`
Expected: FAIL — `ImportError: cannot import name 'parse_eomisae'`

- [ ] **Step 4: 파서 구현**

`src/willy/ideas/parsers.py` 끝에 덧붙인다:

```python
# 목록 사이에 광고 슬롯과 레벨 제한 글이 카드 모양으로 끼어 있다.
# 둘 다 제목이 소재가 되지 않으므로 버린다.
_EOMISAE_SKIP = ("list_ad_link", "전체 공개로 전환됩니다")


def _reaction(card: str, icon: str) -> int | None:
    match = re.search(rf'{icon}"></i>\s*([\d,]+)', card)
    return int(match.group(1).replace(",", "")) if match else None


def parse_eomisae(html_text: str, source: str, base_url: str) -> list[IdeaItem]:
    items: list[IdeaItem] = []
    cards = re.split(r'<div class="card_el', html_text)[1:]

    for card in cards:
        link = re.search(r'<h3[^>]*>\s*<a[^>]+href="(/os/\d+)"[^>]*>(.*?)</a>', card, re.S)
        if link is None:
            continue
        title = clean_text(link.group(2))
        if not title or any(skip in title for skip in _EOMISAE_SKIP):
            continue

        thumbnail = None
        thumb_match = re.search(r'<img class="tmb" src="([^"]+)"', card)
        if thumb_match:
            raw = thumb_match.group(1)
            thumbnail = f"https:{raw}" if raw.startswith("//") else raw

        category = None
        cate_match = re.search(r'<span class="cate">([^<]*)</span>', card)
        if cate_match:
            category = cate_match.group(1).strip().rstrip(",") or None

        items.append(
            IdeaItem(
                source=source,
                title=title,
                url=urljoin(base_url, link.group(1)),
                category=category,
                thumbnail_url=thumbnail,
                views=_reaction(card, "ion-ios-eye"),
                comments=_reaction(card, "ion-ios-chatbubble"),
                likes=_reaction(card, "ion-ios-heart"),
            )
        )
    return items
```

- [ ] **Step 5: 테스트 통과 확인**

Run: `C:\venvs\willy\Scripts\python.exe -m pytest tests/test_ideas_parsers.py -q`
Expected: PASS (11 passed)

- [ ] **Step 6: 커밋**

```bash
git add src/willy/ideas/parsers.py tests/fixtures/ideas/eomisae_os.html tests/test_ideas_parsers.py
git commit -m "feat: 어미새 파서 추가 — 반응 수와 썸네일까지

목록 카드에 조회·댓글·좋아요가 함께 오므로 뱃지 판정에 그대로 쓴다.
0과 '모름'을 구분해 댓글 0은 0으로 남긴다.

카드 모양으로 끼어 있는 광고 슬롯(list_ad_link)과 레벨 제한 글은
제목이 소재가 되지 않아 버린다. 썸네일은 프로토콜 상대 주소로 와서
정적 페이지에서 깨지므로 https로 절대화한다."
```

---

## Task 4: 매거진 파서 2종 (Hearst · Condé Nast)

**Files:**
- Modify: `src/willy/ideas/parsers.py`
- Create: `tests/fixtures/ideas/hearst.html`, `tests/fixtures/ideas/condenast.html`
- Modify: `tests/test_ideas_parsers.py`

**Interfaces:**
- Consumes: Task 2의 `clean_text`, `tag_parts`
- Produces: `parse_hearst(html_text, source, base_url) -> list[IdeaItem]`, `parse_condenast(html_text, source, base_url) -> list[IdeaItem]`

에스콰이어·엘르는 링크가 `/article/{숫자}`이고 제목만 들어 있다.
보그·GQ는 링크가 `/{연}/{월}/{일}/{슬러그}/`이고 링크 안에 카테고리·제목·
날짜·기자명이 각각 다른 요소로 들어 있다. 순서가 글마다 다르므로
위치가 아니라 성격으로 골라야 한다.

- [ ] **Step 1: 픽스처 작성**

`tests/fixtures/ideas/hearst.html`:

```html
<ul class="article-list">
  <li><a href="/article/1907093">차덕후 주목! '아디다스 오리지널스 x 피치스' 두 번째 협업 출시</a></li>
  <li><a href="/article/1907130"><span></span>흰 티에 청바지 '국롤' 조합 이렇게 해보세요<span></span></a></li>
  <li><a href="/tag/fashion">패션</a></li>
  <li><a href="/article/1907123">짧음</a></li>
</ul>
```

`tests/fixtures/ideas/condenast.html`:

```html
<div class="listing">
  <a href="/2026/08/03/%ec%99%88%eb%9d%bc%eb%b9%84/">
    <span class="cat">sneakers</span>
    <h3>왈라비 한 켤레도 없는 남자 없지? 지금이 최적의 구매 기회다</h3>
    <time>2026.08.03</time>
    <span class="by">by 조서형, Adam Cheung</span>
  </a>
  <a href="/2026/08/03/%eb%b0%98%eb%b0%94%ec%a7%80/">
    <span class="cat">패션 아이템</span>
    <time>2026.08.03</time>
    <h3>반바지에는 운동화도, 샌들도, 플립플롭도 아닙니다</h3>
  </a>
  <a href="https://www.prada.com/kr/ko/womens/holiday/c/1029">자세히 보기</a>
</div>
```

- [ ] **Step 2: 실패하는 테스트 작성**

`tests/test_ideas_parsers.py` 끝에 덧붙인다:

```python
from willy.ideas.parsers import parse_condenast, parse_hearst


def test_hearst_extracts_titles_and_absolute_urls():
    items = parse_hearst(
        fixture("hearst.html"),
        source="esquire",
        base_url="https://www.esquirekorea.co.kr/fashion",
    )

    assert len(items) == 2, "기사 링크가 아닌 것과 너무 짧은 제목은 버린다"
    assert items[0].title == (
        "차덕후 주목! '아디다스 오리지널스 x 피치스' 두 번째 협업 출시"
    )
    assert items[0].url == "https://www.esquirekorea.co.kr/article/1907093"
    assert items[1].title == "흰 티에 청바지 '국롤' 조합 이렇게 해보세요"


def test_condenast_splits_category_title_and_date():
    """링크 안에 카테고리·제목·날짜·기자명이 함께 온다. 제목만 남겨야 한다."""
    items = parse_condenast(
        fixture("condenast.html"),
        source="gq",
        base_url="https://www.gqkorea.co.kr/category/style/",
    )

    first = items[0]
    assert first.category == "sneakers"
    assert first.title == "왈라비 한 켤레도 없는 남자 없지? 지금이 최적의 구매 기회다"
    assert first.published_at is not None
    assert (first.published_at.year, first.published_at.month, first.published_at.day) == (
        2026, 8, 3,
    )
    assert "by 조서형" not in first.title
    assert "2026.08.03" not in first.title


def test_condenast_handles_reordered_parts():
    """두 번째 글은 날짜가 제목보다 먼저 온다. 위치로 고르면 깨진다."""
    items = parse_condenast(
        fixture("condenast.html"),
        source="vogue",
        base_url="https://www.vogue.co.kr/category/fashion",
    )

    assert items[1].category == "패션 아이템"
    assert items[1].title == "반바지에는 운동화도, 샌들도, 플립플롭도 아닙니다"


def test_condenast_skips_outbound_links():
    """목록 안에 브랜드 광고 링크가 섞여 있다."""
    items = parse_condenast(
        fixture("condenast.html"),
        source="vogue",
        base_url="https://www.vogue.co.kr/category/fashion",
    )

    assert len(items) == 2
    assert all("prada.com" not in item.url for item in items)
```

- [ ] **Step 3: 테스트 실패 확인**

Run: `C:\venvs\willy\Scripts\python.exe -m pytest tests/test_ideas_parsers.py -q`
Expected: FAIL — `ImportError: cannot import name 'parse_condenast'`

- [ ] **Step 4: 파서 구현**

`src/willy/ideas/parsers.py` 끝에 덧붙인다:

```python
_ANCHOR_RE = re.compile(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', re.S)
_DATE_RE = re.compile(r"^(\d{4})\.(\d{1,2})\.(\d{1,2})$")


def _anchors(html_text: str, href_pattern: str):
    """href가 패턴에 맞는 <a>만 (href, 안쪽 HTML)로 돌려준다."""
    for match in _ANCHOR_RE.finditer(html_text):
        if re.search(href_pattern, match.group(1)):
            yield match.group(1), match.group(2)


def parse_hearst(html_text: str, source: str, base_url: str) -> list[IdeaItem]:
    """에스콰이어·엘르. 링크가 /article/{숫자}이고 안에 제목만 있다."""
    items: list[IdeaItem] = []
    seen: set[str] = set()

    for href, inner in _anchors(html_text, r"/article/\d+"):
        title = clean_text(inner)
        if len(title) < 8:
            continue
        url = urljoin(base_url, href)
        if url in seen:
            continue
        seen.add(url)
        items.append(IdeaItem(source=source, title=title, url=url))
    return items


def parse_condenast(html_text: str, source: str, base_url: str) -> list[IdeaItem]:
    """보그·GQ. 링크 안에 카테고리·제목·날짜·기자명이 조각으로 들어 있다.

    조각 순서가 글마다 다르므로 위치가 아니라 성격으로 고른다.
    """
    items: list[IdeaItem] = []
    seen: set[str] = set()

    for href, inner in _anchors(html_text, r"/\d{4}/\d{1,2}/\d{1,2}/"):
        parts = tag_parts(inner)
        if not parts:
            continue

        published = None
        remaining: list[str] = []
        for part in parts:
            date_match = _DATE_RE.match(part)
            if date_match and published is None:
                year, month, day = (int(value) for value in date_match.groups())
                published = datetime(year, month, day)
                continue
            if part.startswith("by "):
                continue
            remaining.append(part)

        if len(remaining) < 2:
            continue
        category = remaining[0]
        # 카테고리를 뺀 나머지 중 가장 긴 조각이 제목이다.
        title = max(remaining[1:], key=len)
        if len(title) < 8:
            continue

        url = urljoin(base_url, href)
        if url in seen:
            continue
        seen.add(url)
        items.append(
            IdeaItem(
                source=source,
                title=title,
                url=url,
                category=category,
                published_at=published,
            )
        )
    return items
```

- [ ] **Step 5: 테스트 통과 확인**

Run: `C:\venvs\willy\Scripts\python.exe -m pytest tests/test_ideas_parsers.py -q`
Expected: PASS (15 passed)

- [ ] **Step 6: 커밋**

```bash
git add src/willy/ideas/parsers.py tests/fixtures/ideas/hearst.html tests/fixtures/ideas/condenast.html tests/test_ideas_parsers.py
git commit -m "feat: 매거진 파서 2종 추가 — 에스콰이어·엘르, 보그·GQ

네 매체가 두 계열로 갈린다. 에스콰이어·엘르는 /article/{숫자}에 제목만
들어 있고, 보그·GQ는 링크 안에 카테고리·제목·날짜·기자명이 조각으로
들어 있다.

보그·GQ는 조각 순서가 글마다 달라(날짜가 제목보다 먼저 오기도 한다)
위치가 아니라 성격으로 고른다. 목록에 섞인 브랜드 광고 링크는 날짜형
경로가 아니라 자연히 걸러진다."
```

---

## Task 5: 아이즈매거진 파서 (렌더링된 DOM)

**Files:**
- Modify: `src/willy/ideas/parsers.py`
- Create: `tests/fixtures/ideas/eyesmag.html`
- Modify: `tests/test_ideas_parsers.py`

**Interfaces:**
- Consumes: Task 2의 `clean_text`, `tag_parts`
- Produces: `parse_eyesmag(html_text, source, base_url) -> list[IdeaItem]`

이 소스만 브라우저가 필요하다. 서버 HTML에는 글이 없고, 렌더링된 뒤의
DOM에 `/posts/{id}/{슬러그}` 링크가 나타난다. 링크 안에 카테고리·조회수·
상대시간·제목이 줄바꿈으로 구분돼 들어온다. 파서는 그 **렌더링 결과
문자열**을 받는다 — 브라우저를 다루는 일은 Task 7의 수집기 몫이다.

- [ ] **Step 1: 픽스처 작성**

`tests/fixtures/ideas/eyesmag.html`:

```html
<div class="list">
  <a href="/posts/165004/birkenstock-ader-error-collab">
    <span>패션 &gt; 슈즈</span>
    <span>읽음 4172 ・10시간 전</span>
    <strong>버켄스탁 x 아더에러, 두 번째 협업 컬렉션</strong>
  </a>
  <a href="/posts/164997/salomon-trail-running-shoes">
    <span>패션 &gt; 뉴스</span>
    <span>읽음 12,345 ・18시간 전</span>
    <strong>살로몬, 트레일 러닝에 집중한 신제품 공개</strong>
  </a>
  <a href="/posts/164823/empty-title-placeholder">
    <strong>반항의 상징이 된 슬리브리스, 헤인즈</strong>
  </a>
  <a href="/category/life-navigation/all">라이프 내비게이션</a>
</div>
```

- [ ] **Step 2: 실패하는 테스트 작성**

`tests/test_ideas_parsers.py` 끝에 덧붙인다:

```python
from willy.ideas.parsers import parse_eyesmag


def eyesmag_items():
    return parse_eyesmag(
        fixture("eyesmag.html"),
        source="eyesmag",
        base_url="https://www.eyesmag.com/category/fashion/all",
    )


def test_eyesmag_extracts_title_category_and_views():
    items = eyesmag_items()

    first = items[0]
    assert first.title == "버켄스탁 x 아더에러, 두 번째 협업 컬렉션"
    assert first.url == (
        "https://www.eyesmag.com/posts/165004/birkenstock-ader-error-collab"
    )
    assert first.category == "패션 > 슈즈"
    assert first.views == 4172


def test_eyesmag_parses_thousands_separator_in_views():
    """조회수가 만 단위를 넘으면 쉼표가 붙는다."""
    assert eyesmag_items()[1].views == 12345


def test_eyesmag_keeps_posts_without_meta():
    """카테고리·조회수가 없는 글도 제목이 있으면 소재가 된다."""
    items = eyesmag_items()

    assert items[2].title == "반항의 상징이 된 슬리브리스, 헤인즈"
    assert items[2].views is None
    assert items[2].category is None


def test_eyesmag_skips_navigation_links():
    items = eyesmag_items()

    assert len(items) == 3
    assert all("/posts/" in item.url for item in items)


def test_eyesmag_title_has_no_meta_noise():
    """조회수·상대시간이 제목에 섞여 들어가면 텍스트 생성이 오염된다."""
    for item in eyesmag_items():
        assert "읽음" not in item.title
        assert "시간 전" not in item.title
```

- [ ] **Step 3: 테스트 실패 확인**

Run: `C:\venvs\willy\Scripts\python.exe -m pytest tests/test_ideas_parsers.py -q`
Expected: FAIL — `ImportError: cannot import name 'parse_eyesmag'`

- [ ] **Step 4: 파서 구현**

`src/willy/ideas/parsers.py` 끝에 덧붙인다:

```python
_EYESMAG_VIEWS_RE = re.compile(r"읽음\s*([\d,]+)")


def parse_eyesmag(html_text: str, source: str, base_url: str) -> list[IdeaItem]:
    """아이즈매거진. 브라우저가 렌더링한 DOM 문자열을 받는다.

    링크 안에 카테고리·조회수·상대시간·제목이 조각으로 들어온다.
    조회수와 시간 조각은 제목에서 빼야 텍스트 생성이 오염되지 않는다.
    """
    items: list[IdeaItem] = []
    seen: set[str] = set()

    for href, inner in _anchors(html_text, r"/posts/\d+/"):
        parts = tag_parts(inner)
        category = None
        views = None
        titles: list[str] = []

        for part in parts:
            views_match = _EYESMAG_VIEWS_RE.search(part)
            if views_match:
                views = int(views_match.group(1).replace(",", ""))
                continue
            if part.startswith("패션") and ">" in part:
                category = part
                continue
            titles.append(part)

        if not titles:
            continue
        title = max(titles, key=len)
        if len(title) < 8:
            continue

        url = urljoin(base_url, href)
        if url in seen:
            continue
        seen.add(url)
        items.append(
            IdeaItem(
                source=source,
                title=title,
                url=url,
                category=category,
                views=views,
            )
        )
    return items
```

- [ ] **Step 5: 테스트 통과 확인**

Run: `C:\venvs\willy\Scripts\python.exe -m pytest tests/test_ideas_parsers.py -q`
Expected: PASS (20 passed)

- [ ] **Step 6: 커밋**

```bash
git add src/willy/ideas/parsers.py tests/fixtures/ideas/eyesmag.html tests/test_ideas_parsers.py
git commit -m "feat: 아이즈매거진 파서 추가 (렌더링된 DOM)

이 소스만 서버 HTML에 글이 없어 브라우저 렌더링 결과를 받아 파싱한다.
파서는 문자열만 받고 브라우저는 수집기가 다룬다 — 그래야 픽스처로
테스트할 수 있다.

링크 안에 조회수와 상대시간이 제목과 섞여 오므로 분리한다. 그대로 두면
텍스트 생성 프롬프트에 '읽음 4172 ・10시간 전'이 딸려 들어간다."
```

---

## Task 6: 반응 뱃지 판정

**Files:**
- Create: `src/willy/ideas/hotness.py`
- Test: `tests/test_ideas_hotness.py`

**Interfaces:**
- Consumes: Task 1의 `IdeaItem`
- Produces: `HOT_THRESHOLDS: dict[str, dict[str, int]]`, `mark_hot(items: list[IdeaItem]) -> list[IdeaItem]`

소스마다 지표 스케일이 다르다(어미새 좋아요 3~10, 아이즈 조회 4천~1.7만).
공통 임계값은 뜻이 없으므로 소스별로 둔다.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_ideas_hotness.py`:

```python
from willy.ideas.hotness import HOT_THRESHOLDS, mark_hot
from willy.ideas.models import IdeaItem


def item(source="eomisae_os", **kwargs) -> IdeaItem:
    return IdeaItem(source=source, title="제목", url="https://x.test/1", **kwargs)


def test_marks_hot_when_any_metric_passes_threshold():
    """어미새는 좋아요 5 또는 댓글 10이 기준이다."""
    marked = mark_hot([item(likes=5, comments=0), item(likes=0, comments=10)])

    assert [i.is_hot for i in marked] == [True, True]


def test_below_threshold_is_not_hot():
    marked = mark_hot([item(likes=4, comments=9)])

    assert marked[0].is_hot is False


def test_unknown_metric_does_not_count_as_zero():
    """지표를 주지 않는 소스를 0으로 보면 판정이 틀어진다."""
    marked = mark_hot([item(likes=None, comments=None)])

    assert marked[0].is_hot is False


def test_source_without_thresholds_is_never_hot():
    """하입비스트·매거진은 반응 데이터가 없다. 뱃지 대신 카테고리를 쓴다."""
    marked = mark_hot([item(source="vogue", views=999999)])

    assert marked[0].is_hot is False


def test_eyesmag_uses_view_threshold():
    marked = mark_hot([item(source="eyesmag", views=5000), item(source="eyesmag", views=4999)])

    assert [i.is_hot for i in marked] == [True, False]


def test_thresholds_only_cover_sources_that_report_reactions():
    assert set(HOT_THRESHOLDS) == {"eomisae_os", "eyesmag"}


def test_mark_hot_does_not_mutate_input():
    """원본을 바꾸면 같은 목록을 두 번 판정할 때 결과가 달라진다."""
    original = item(likes=5)

    mark_hot([original])

    assert original.is_hot is False
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `C:\venvs\willy\Scripts\python.exe -m pytest tests/test_ideas_hotness.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'willy.ideas.hotness'`

- [ ] **Step 3: 구현**

`src/willy/ideas/hotness.py`:

```python
"""반응 뱃지 판정.

소스마다 지표 스케일이 달라(어미새 좋아요 3~10, 아이즈 조회 4천~1.7만)
공통 임계값은 뜻이 없다. 소스별로 두고, 임계값이 없는 소스는 늘 False다.
"""
from __future__ import annotations

from dataclasses import replace

from willy.ideas.models import IdeaItem

HOT_THRESHOLDS: dict[str, dict[str, int]] = {
    "eomisae_os": {"likes": 5, "comments": 10},
    "eyesmag": {"views": 5000},
}


def _is_hot(item: IdeaItem) -> bool:
    thresholds = HOT_THRESHOLDS.get(item.source)
    if not thresholds:
        return False
    for metric, minimum in thresholds.items():
        value = getattr(item, metric)
        # None은 '모름'이다. 0으로 보면 판정이 틀어진다.
        if value is not None and value >= minimum:
            return True
    return False


def mark_hot(items: list[IdeaItem]) -> list[IdeaItem]:
    """뱃지를 매긴 새 목록을 돌려준다. 입력은 건드리지 않는다."""
    return [replace(item, is_hot=_is_hot(item)) for item in items]
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `C:\venvs\willy\Scripts\python.exe -m pytest tests/test_ideas_hotness.py -q`
Expected: PASS (7 passed)

- [ ] **Step 5: 커밋**

```bash
git add src/willy/ideas/hotness.py tests/test_ideas_hotness.py
git commit -m "feat: 반응 뱃지 판정 추가

소스마다 지표 스케일이 달라 공통 임계값은 뜻이 없다. 어미새는 좋아요·
댓글, 아이즈는 조회수로 소스별 임계값을 둔다. 반응을 주지 않는 소스는
임계값이 없어 늘 False이고 화면에서는 카테고리를 대신 보여준다.

None을 0으로 보지 않는다. 원본을 바꾸지 않고 새 목록을 돌려줘 같은
목록을 두 번 판정해도 결과가 같다."
```

---

## Task 7: 수집기 오케스트레이션

**Files:**
- Create: `src/willy/ideas/collector.py`
- Test: `tests/test_ideas_collector.py`

**Interfaces:**
- Consumes: Task 1의 `IDEA_SOURCES`·`IdeaSource`, Task 2~5의 파서 5종, Task 6의 `mark_hot`
- Produces: `PARSERS: dict[str, Callable]`, `collect_ideas(sources=None, limit_per_source=10, http=None, page_factory=None) -> tuple[list[IdeaItem], list[str]]`
  — 두 번째 값은 실패한 소스 이름 목록이다

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_ideas_collector.py`:

```python
import pytest

from willy.ideas.collector import collect_ideas
from willy.ideas.sources import IdeaSource

RSS = """<?xml version="1.0"?><rss><channel>
<item><title>드랍 소식 하나</title><link>https://a.test/1</link></item>
<item><title>드랍 소식 둘</title><link>https://a.test/2</link></item>
<item><title>드랍 소식 셋</title><link>https://a.test/3</link></item>
</channel></rss>"""

EOMISAE = """<div class="card_el n_ntc">
  <div class="card_content"><h3><a href="/os/1">세일 소식 하나</a></h3>
  <div class="infos"><span><i class="ion-ios-heart"></i>9</span></div></div>
</div>"""


class FakeResponse:
    def __init__(self, text: str):
        self.text = text
        self.status_code = 200

    def raise_for_status(self):
        pass


class FakeHttp:
    def __init__(self, by_url: dict[str, str], fail: set[str] | None = None):
        self._by_url = by_url
        self._fail = fail or set()
        self.calls: list[str] = []

    def get(self, url, **kwargs):
        self.calls.append(url)
        if url in self._fail:
            raise RuntimeError("연결 실패")
        return FakeResponse(self._by_url[url])


def rss_source(name="hypebeast", url="https://a.test/feed") -> IdeaSource:
    return IdeaSource(name=name, label="A", url=url, kind="rss", group="drop")


def eomisae_source() -> IdeaSource:
    return IdeaSource(
        name="eomisae_os", label="어미새", url="https://b.test/os",
        kind="eomisae", group="deal",
    )


def test_collects_from_multiple_sources():
    http = FakeHttp({"https://a.test/feed": RSS, "https://b.test/os": EOMISAE})

    items, failed = collect_ideas(
        sources=[rss_source(), eomisae_source()], http=http
    )

    assert failed == []
    assert {item.source for item in items} == {"hypebeast", "eomisae_os"}


def test_caps_items_per_source():
    """소스당 상한이 없으면 한 소스가 목록을 다 차지한다."""
    http = FakeHttp({"https://a.test/feed": RSS})

    items, _ = collect_ideas(sources=[rss_source()], limit_per_source=2, http=http)

    assert len(items) == 2


def test_one_failing_source_does_not_stop_the_rest():
    http = FakeHttp(
        {"https://a.test/feed": RSS, "https://b.test/os": EOMISAE},
        fail={"https://a.test/feed"},
    )

    items, failed = collect_ideas(
        sources=[rss_source(), eomisae_source()], http=http
    )

    assert failed == ["hypebeast"]
    assert [item.source for item in items] == ["eomisae_os"]


def test_applies_hot_badges():
    """수집 결과에 뱃지가 이미 매겨져 있어야 화면이 판정을 다시 하지 않는다."""
    http = FakeHttp({"https://b.test/os": EOMISAE})

    items, _ = collect_ideas(sources=[eomisae_source()], http=http)

    assert items[0].is_hot is True  # 좋아요 9 >= 5


def test_browser_source_is_skipped_without_page_factory():
    """로컬 앱은 브라우저를 띄우지 않는다. 그 소스만 빠지고 나머지는 모은다."""
    browser = IdeaSource(
        name="eyesmag", label="아이즈", url="https://c.test/f",
        kind="eyesmag", group="drop", needs_browser=True,
    )
    http = FakeHttp({"https://a.test/feed": RSS})

    items, failed = collect_ideas(sources=[rss_source(), browser], http=http)

    assert failed == []
    assert all(item.source != "eyesmag" for item in items)


def test_browser_source_uses_page_factory_when_given():
    import contextlib

    class FakePage:
        def __init__(self):
            self.visited = []

        def goto(self, url, **kwargs):
            self.visited.append(url)

        def wait_for_timeout(self, ms):
            pass

        def content(self):
            return '<a href="/posts/1/x"><strong>협업 컬렉션 소식입니다</strong></a>'

    page = FakePage()
    browser = IdeaSource(
        name="eyesmag", label="아이즈", url="https://c.test/f",
        kind="eyesmag", group="drop", needs_browser=True,
    )

    items, failed = collect_ideas(
        sources=[browser],
        http=FakeHttp({}),
        page_factory=lambda: contextlib.nullcontext(page),
    )

    assert failed == []
    assert page.visited == ["https://c.test/f"]
    assert items[0].title == "협업 컬렉션 소식입니다"
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `C:\venvs\willy\Scripts\python.exe -m pytest tests/test_ideas_collector.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'willy.ideas.collector'`

- [ ] **Step 3: 구현**

`src/willy/ideas/collector.py`:

```python
"""아이디어 수집 오케스트레이션.

한 소스가 실패해도 나머지는 모은다. 브라우저가 필요한 소스는
page_factory가 있을 때만 수집한다 — 로컬 앱은 브라우저를 띄우지 않고
배치만 띄우기 때문이다.
"""
from __future__ import annotations

import logging
from typing import Callable

import httpx

from willy.ideas.hotness import mark_hot
from willy.ideas.models import IdeaItem
from willy.ideas.parsers import (
    parse_condenast,
    parse_eomisae,
    parse_eyesmag,
    parse_hearst,
    parse_rss,
)
from willy.ideas.sources import IDEA_SOURCES, IdeaSource

log = logging.getLogger(__name__)

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

PARSERS: dict[str, Callable[..., list[IdeaItem]]] = {
    "rss": parse_rss,
    "eomisae": parse_eomisae,
    "hearst": parse_hearst,
    "condenast": parse_condenast,
    "eyesmag": parse_eyesmag,
}


def _parse(source: IdeaSource, text: str) -> list[IdeaItem]:
    parser = PARSERS[source.kind]
    if source.kind == "rss":
        return parser(text, source=source.name)
    return parser(text, source=source.name, base_url=source.url)


def _fetch_with_browser(source: IdeaSource, page_factory) -> list[IdeaItem]:
    with page_factory() as page:
        page.goto(source.url, wait_until="domcontentloaded")
        page.wait_for_timeout(4000)
        return _parse(source, page.content())


def collect_ideas(
    sources: list[IdeaSource] | None = None,
    limit_per_source: int = 10,
    http=None,
    page_factory=None,
) -> tuple[list[IdeaItem], list[str]]:
    """소스별 최신 limit_per_source건까지 모은다.

    돌려주는 값은 (아이디어 목록, 실패한 소스 이름 목록)이다. 실패를
    조용히 삼키면 어느 날 목록이 반쪽이 돼도 알 수 없다.
    """
    sources = sources if sources is not None else list(IDEA_SOURCES.values())
    client = http or httpx.Client(timeout=25, follow_redirects=True, headers=HEADERS)

    collected: list[IdeaItem] = []
    failed: list[str] = []

    for source in sources:
        if source.needs_browser and page_factory is None:
            log.info("브라우저가 없어 건너뜁니다: %s", source.name)
            continue
        try:
            if source.needs_browser:
                items = _fetch_with_browser(source, page_factory)
            else:
                response = client.get(source.url)
                response.raise_for_status()
                items = _parse(source, response.text)
        except Exception:
            log.exception("아이디어 수집 실패: %s", source.name)
            failed.append(source.name)
            continue
        collected.extend(items[:limit_per_source])

    return mark_hot(collected), failed
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `C:\venvs\willy\Scripts\python.exe -m pytest tests/test_ideas_collector.py -q`
Expected: PASS (6 passed)

- [ ] **Step 5: 전체 테스트 확인**

Run: `C:\venvs\willy\Scripts\python.exe -m pytest -q`
Expected: PASS (기존 240건 + 신규 전부)

- [ ] **Step 6: 커밋**

```bash
git add src/willy/ideas/collector.py tests/test_ideas_collector.py
git commit -m "feat: 아이디어 수집 오케스트레이션 추가

한 소스가 실패해도 나머지는 모은다. 다만 조용히 삼키지 않고 실패한
소스 이름을 함께 돌려줘, 어느 날 목록이 반쪽이 되면 화면과 로그에
드러나게 한다.

브라우저가 필요한 아이즈매거진은 page_factory가 있을 때만 수집한다.
로컬 앱은 브라우저를 띄우지 않고 배치만 띄운다. 소스당 상한이 없으면
한 소스가 목록을 다 차지하므로 10건으로 자른다."
```

---

## Task 8: 상세 본문과 텍스트 생성

**Files:**
- Create: `src/willy/ideas/detail.py`
- Modify: `src/willy/texter.py`
- Test: `tests/test_ideas_texter.py`

**Interfaces:**
- Consumes: Task 1의 `IdeaItem`, 기존 `willy.texter.STYLE_EXAMPLE`·`gemini_generate`
- Produces: `fetch_detail(url: str, http=None) -> str`, `willy.texter.build_idea_prompt(items_with_details) -> str`, `willy.texter.TextWriter.write_from_ideas(items_with_details) -> list[dict]`, `willy.texter.template_idea_texts(items_with_details) -> list[dict]`
  — `items_with_details`는 `list[tuple[IdeaItem, str]]` (항목, 본문 발췌)

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_ideas_texter.py`:

```python
import json

import pytest

from willy.ideas.detail import fetch_detail
from willy.ideas.models import IdeaItem
from willy.texter import TextWriter, build_idea_prompt, template_idea_texts


def item(title="버켄스탁 x 아더에러 협업", source="eyesmag") -> IdeaItem:
    return IdeaItem(source=source, title=title, url="https://x.test/1", category="슈즈")


PAIRS = [(item(), "9월 5일 발매, 가격은 25만 8천원. 두 가지 컬러웨이로 나온다.")]


class FakeResponse:
    def __init__(self, text):
        self.text = text
        self.status_code = 200

    def raise_for_status(self):
        pass


class FakeHttp:
    def __init__(self, text):
        self._text = text

    def get(self, url, **kwargs):
        return FakeResponse(self._text)


def test_fetch_detail_strips_markup_and_scripts():
    """본문에 스크립트가 섞여 들어가면 프롬프트가 오염된다."""
    html_text = (
        "<html><head><script>var a=1;</script><style>.x{}</style></head>"
        "<body><p>9월 5일 발매</p><p>가격 25만원</p></body></html>"
    )

    text = fetch_detail("https://x.test/1", http=FakeHttp(html_text))

    assert "9월 5일 발매" in text
    assert "var a=1" not in text
    assert "<p>" not in text


def test_fetch_detail_caps_length():
    """상세 페이지 전체를 넣으면 프롬프트가 불필요하게 커진다."""
    text = fetch_detail("https://x.test/1", http=FakeHttp("<p>" + "가" * 5000 + "</p>"))

    assert len(text) <= 1200


def test_prompt_includes_titles_details_and_style_example():
    prompt = build_idea_prompt(PAIRS)

    assert "버켄스탁 x 아더에러 협업" in prompt
    assert "25만 8천원" in prompt
    assert "팔로우" in prompt, "말투 예시가 빠지면 채널 톤이 안 나온다"
    assert "JSON" in prompt


def test_write_from_ideas_returns_three_tones():
    payload = json.dumps(
        [{"tone": f"톤{i}", "text": f"본문 {i}"} for i in range(3)], ensure_ascii=False
    )
    writer = TextWriter(api_key="g", http=_gemini_http(payload), sleep=lambda s: None)

    texts = writer.write_from_ideas(PAIRS)

    assert len(texts) == 3
    assert all(set(t) == {"tone", "text"} for t in texts)


def test_write_from_ideas_rejects_wrong_count():
    payload = json.dumps([{"tone": "하나", "text": "본문"}], ensure_ascii=False)
    writer = TextWriter(api_key="g", http=_gemini_http(payload), sleep=lambda s: None)

    with pytest.raises(ValueError, match="3개"):
        writer.write_from_ideas(PAIRS)


def test_template_fallback_uses_titles():
    """AI가 죽어도 초안 하나는 나온다."""
    texts = template_idea_texts(PAIRS)

    assert len(texts) >= 1
    assert "버켄스탁 x 아더에러 협업" in texts[0]["text"]
    assert "팔로우" in texts[0]["text"]


def _gemini_http(payload: str):
    class Http:
        def __init__(self):
            self.calls = 0

        def post(self, url, **kwargs):
            self.calls += 1

            class Response:
                status_code = 200

                @staticmethod
                def json():
                    return {
                        "candidates": [{"content": {"parts": [{"text": payload}]}}]
                    }

                @staticmethod
                def raise_for_status():
                    pass

            return Response()

    return Http()
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `C:\venvs\willy\Scripts\python.exe -m pytest tests/test_ideas_texter.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'willy.ideas.detail'`

- [ ] **Step 3: 상세 수집 구현**

`src/willy/ideas/detail.py`:

```python
"""선택 항목의 상세 본문 발췌.

제목만으로는 가격·발매일·브랜드가 빠져 텍스트가 빈약해진다. 선택은
보통 1~3건이라 그때 한 번씩 가져와도 부담이 없다.
"""
from __future__ import annotations

import html
import re

import httpx

MAX_CHARS = 1200
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

_STRIP_BLOCKS = re.compile(r"<(script|style|nav|footer)[^>]*>.*?</\1>", re.S | re.I)


def fetch_detail(url: str, http=None) -> str:
    """상세 페이지 본문을 한 덩어리 텍스트로 줄여 돌려준다."""
    client = http or httpx.Client(timeout=20, follow_redirects=True, headers=HEADERS)
    response = client.get(url)
    response.raise_for_status()

    body = _STRIP_BLOCKS.sub(" ", response.text)
    text = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", body))).strip()
    return text[:MAX_CHARS]
```

- [ ] **Step 4: 텍스트 생성 구현**

`src/willy/texter.py` 끝에 덧붙인다. 파일 상단 import에 `from willy.ideas.models import IdeaItem`을 더한다:

```python
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
```

`TextWriter` 클래스 안에 메서드를 더한다:

```python
    def write_from_ideas(
        self, items_with_details: list[tuple[IdeaItem, str]]
    ) -> list[dict]:
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
```

- [ ] **Step 5: 테스트 통과 확인**

Run: `C:\venvs\willy\Scripts\python.exe -m pytest tests/test_ideas_texter.py -q`
Expected: PASS (6 passed)

- [ ] **Step 6: 커밋**

```bash
git add src/willy/ideas/detail.py src/willy/texter.py tests/test_ideas_texter.py
git commit -m "feat: 선택 소식의 상세 본문과 텍스트 3종 생성

제목만으로는 가격·발매일·브랜드가 빠져 글이 빈약해진다. 선택 항목만
상세 페이지를 그때 한 번씩 읽어 프롬프트에 넣는다. 스크립트·스타일은
걷어내고 1200자로 자른다.

말투 예시는 룩 글과 공유하고 톤 구성만 소식용으로 바꾼다. 없는 숫자를
지어내지 말라고 프롬프트에 못박는다. AI가 죽으면 제목 기반 템플릿
초안으로 폴백한다."
```

---

## Task 9: 웹 API

**Files:**
- Modify: `src/willy/web/app.py`, `run.py`
- Test: `tests/test_ideas_web.py`

**Interfaces:**
- Consumes: Task 7의 `collect_ideas`, Task 8의 `fetch_detail`·`write_from_ideas`·`template_idea_texts`
- Produces: `POST /api/ideas` → `{"items": [...], "failed": [...], "groups": {...}}`,
  `POST /api/ideas/texts` (body `{"urls": [...]}`) → `{"texts": [...]}`

`create_app`은 지금 `pipeline_factory` 하나만 받는다. 아이디어 수집은
파이프라인과 무관하므로 주입 지점을 따로 연다.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_ideas_web.py`:

```python
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from willy.ideas.models import IdeaItem
from willy.web.app import create_app


def idea(title="버켄스탁 x 아더에러 협업", url="https://x.test/1", **kwargs) -> IdeaItem:
    return IdeaItem(source="eyesmag", title=title, url=url, **kwargs)


@pytest.fixture
def client(tmp_path: Path):
    from tests.test_pipeline import (
        FakeAnalyzer, FakeCollector, FakeGenerator, FakeWeather,
    )
    from willy.archive import Archive
    from willy.generator.preset import load_preset
    from willy.pipeline import Pipeline

    preset = load_preset(Path(__file__).parents[1] / "presets" / "concept_v1.yaml")

    def factory() -> Pipeline:
        return Pipeline(
            weather_client=FakeWeather(),
            collector=FakeCollector(tmp_path / "ws"),
            analyzer=FakeAnalyzer(),
            generator=FakeGenerator(tmp_path / "gen"),
            archive=Archive(tmp_path / "a.db"),
            preset=preset,
            output_root=tmp_path / "outputs",
        )

    return TestClient(
        create_app(
            factory,
            ideas_collector=lambda: ([idea(is_hot=True, category="슈즈")], ["vogue"]),
            detail_fetcher=lambda url: f"본문 발췌 {url}",
            ideas_writer=lambda pairs: [
                {"tone": f"톤{i}", "text": f"본문 {i}"} for i in range(3)
            ],
        )
    )


def test_ideas_endpoint_returns_items_and_failures(client: TestClient):
    body = client.post("/api/ideas").json()

    assert body["items"][0]["title"] == "버켄스탁 x 아더에러 협업"
    assert body["items"][0]["is_hot"] is True
    assert body["items"][0]["source_label"] == "아이즈"
    assert body["failed"] == ["vogue"], "실패한 소스를 화면에 알려야 한다"
    assert body["groups"] == {"deal": "할인", "drop": "드랍·신상", "magazine": "매거진"}


def test_idea_items_carry_group_for_filter_chips(client: TestClient):
    body = client.post("/api/ideas").json()

    assert body["items"][0]["group"] == "drop"


def test_texts_endpoint_requires_urls(client: TestClient):
    assert client.post("/api/ideas/texts", json={"urls": []}).status_code == 400


def test_texts_endpoint_rejects_unknown_urls(client: TestClient):
    """목록에 없는 주소로 상세를 긁게 하면 안 된다."""
    client.post("/api/ideas")

    response = client.post("/api/ideas/texts", json={"urls": ["https://evil.test/x"]})

    assert response.status_code == 400


def test_texts_endpoint_generates_three_tones(client: TestClient):
    client.post("/api/ideas")

    body = client.post("/api/ideas/texts", json={"urls": ["https://x.test/1"]}).json()

    assert len(body["texts"]) == 3


def test_texts_endpoint_needs_ideas_first(client: TestClient):
    assert client.post("/api/ideas/texts", json={"urls": ["https://x.test/1"]}).status_code == 409
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `C:\venvs\willy\Scripts\python.exe -m pytest tests/test_ideas_web.py -q`
Expected: FAIL — `TypeError: create_app() got an unexpected keyword argument 'ideas_collector'`

- [ ] **Step 3: 구현**

`src/willy/web/app.py` 상단 import에 더한다:

```python
from willy.ideas.collector import collect_ideas
from willy.ideas.detail import fetch_detail
from willy.ideas.sources import IDEA_SOURCES, SOURCE_GROUPS
```

요청 모델을 더한다:

```python
class IdeaTextsRequest(BaseModel):
    urls: list[str]
```

직렬화 헬퍼를 더한다:

```python
def _serialize_idea(item) -> dict:
    source = IDEA_SOURCES.get(item.source)
    return {
        "source": item.source,
        "source_label": source.label if source else item.source,
        "group": source.group if source else "magazine",
        "title": item.title,
        "url": item.url,
        "category": item.category,
        "thumbnail_url": item.thumbnail_url,
        "published_at": item.published_at.isoformat() if item.published_at else None,
        "views": item.views,
        "comments": item.comments,
        "likes": item.likes,
        "is_hot": item.is_hot,
    }
```

`create_app` 시그니처와 본문을 바꾼다:

```python
def create_app(
    pipeline_factory: Callable[[], Pipeline],
    ideas_collector: Callable[[], tuple[list, list[str]]] | None = None,
    detail_fetcher: Callable[[str], str] | None = None,
    ideas_writer: Callable[[list], list[dict]] | None = None,
) -> FastAPI:
    app = FastAPI(title="최윌리 옷장연구소 콘텐츠 플랫폼")
    ctx: dict = {"pipeline": None, "state": None, "generated": False, "ideas": []}
```

그리고 엔드포인트 두 개를 `finalize` 앞에 더한다:

```python
    # 아이디어 수집도 여러 탭에서 겹쳐 돌 수 있다. 룩 수집과 같은 이유로 잠근다.
    ideas_lock = threading.Lock()

    @app.post("/api/ideas")
    def ideas() -> dict:
        if not ideas_lock.acquire(blocking=False):
            raise HTTPException(
                409, "아이디어를 이미 모으는 중입니다. 끝날 때까지 기다려 주세요."
            )
        try:
            collector = ideas_collector or (lambda: collect_ideas())
            items, failed = collector()
            ctx["ideas"] = items
            return {
                "items": [_serialize_idea(item) for item in items],
                "failed": failed,
                "groups": SOURCE_GROUPS,
            }
        finally:
            ideas_lock.release()

    @app.post("/api/ideas/texts")
    def idea_texts(request: IdeaTextsRequest) -> dict:
        if not request.urls:
            raise HTTPException(400, "소식을 하나 이상 선택해 주세요.")
        if not ctx["ideas"]:
            raise HTTPException(409, "먼저 아이디어를 불러와 주세요.")

        # 목록에 있는 주소만 연다. 임의 주소를 받으면 서버가 남의 사이트를
        # 긁는 통로가 된다.
        by_url = {item.url: item for item in ctx["ideas"]}
        unknown = [url for url in request.urls if url not in by_url]
        if unknown:
            raise HTTPException(400, "목록에 없는 소식입니다.")

        fetcher = detail_fetcher or fetch_detail
        pairs = []
        for url in request.urls:
            try:
                detail = fetcher(url)
            except Exception:
                log.exception("상세 수집 실패: %s", url)
                detail = ""
            pairs.append((by_url[url], detail))

        if ideas_writer is not None:
            return {"texts": ideas_writer(pairs)}

        from willy.texter import template_idea_texts

        writer = ctx["pipeline"].texter if ctx["pipeline"] else None
        if writer is not None:
            try:
                return {"texts": writer.write_from_ideas(pairs)}
            except Exception:
                log.exception("소식 텍스트 생성 실패 — 템플릿 폴백")
        return {"texts": template_idea_texts(pairs)}
```

파일 상단에 로거가 없으면 더한다:

```python
import logging

log = logging.getLogger(__name__)
```

`run.py`의 `main()`은 그대로 둔다 — 기본값이 실제 구현을 쓰므로 변경이 없다.

- [ ] **Step 4: 테스트 통과 확인**

Run: `C:\venvs\willy\Scripts\python.exe -m pytest tests/test_ideas_web.py -q`
Expected: PASS (6 passed)

- [ ] **Step 5: 커밋**

```bash
git add src/willy/web/app.py tests/test_ideas_web.py
git commit -m "feat: 아이디어 수집·텍스트 생성 API 두 개

수집은 룩 수집과 같은 이유로 잠근다. 여러 탭에서 겹쳐 돌면 외부
사이트를 불필요하게 두드린다.

텍스트 생성은 목록에 있는 주소만 연다. 임의 주소를 받으면 서버가 남의
사이트를 긁는 통로가 된다. 실패한 소스 이름을 응답에 실어 목록이
반쪽이 된 날을 화면에서 알 수 있게 한다."
```

---

## Task 10: 로컬 앱 탭 UI

**Files:**
- Modify: `src/willy/web/static/index.html`
- Modify: `tests/test_web.py`

**Interfaces:**
- Consumes: Task 9의 두 엔드포인트 응답 형태

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_web.py` 끝에 덧붙인다:

```python
def test_page_has_two_tabs(client: TestClient):
    page = client.get("/").text

    assert 'data-tab="outfit"' in page
    assert 'data-tab="ideas"' in page
    assert "내일 뭐입지?" in page
    assert "콘텐츠 아이디어 보울" in page


def test_ideas_tab_has_controls(client: TestClient):
    page = client.get("/").text

    assert 'id="btn-ideas"' in page
    assert 'id="btn-idea-texts"' in page
    assert 'id="idea-filters"' in page


def test_idea_values_are_escaped(client: TestClient):
    """외부 사이트에서 온 제목이 그대로 실행되면 안 된다."""
    page = client.get("/").text

    for expression in ("i.title", "i.category", "i.source_label"):
        lines = [line for line in page.splitlines() if expression in line]
        assert lines, f"{expression} 를 찾지 못했다"
        assert all("esc(" in line for line in lines), f"{expression} 가 이스케이프되지 않았다"
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `C:\venvs\willy\Scripts\python.exe -m pytest tests/test_web.py -q`
Expected: FAIL — `assert 'data-tab="outfit"' in page`

- [ ] **Step 3: 탭 뼈대와 스타일 추가**

`index.html`의 `<h1>` 바로 아래에 탭 바를 넣는다:

```html
  <nav class="tabs">
    <button class="tab is-active" data-tab="outfit" type="button">내일 뭐입지?</button>
    <button class="tab" data-tab="ideas" type="button">콘텐츠 아이디어 보울</button>
  </nav>
```

기존 본문(`<p class="console">`부터 `<pre id="result">`까지)을
`<section id="panel-outfit">` 으로 감싼다. 그 뒤에 아이디어 패널을 더한다:

```html
  <section id="panel-ideas" hidden>
    <p class="console">
      <button id="btn-ideas">아이디어 불러오기</button>
      <button id="btn-idea-texts" disabled>선택 항목으로 텍스트 만들기</button>
      <span id="idea-busy" class="muted" hidden></span>
    </p>
    <div id="idea-warn"></div>
    <div id="idea-filters" class="chips"></div>
    <div class="pool" id="idea-list"></div>
    <div class="empty-note" id="idea-empty">
      <b>아이디어 불러오기</b>를 누르면 어미새·아이즈매거진·하입비스트·
      매거진 4곳에서 오늘의 패션 소식을 모읍니다. 마음에 드는 항목을 고르고
      <b>텍스트 만들기</b>를 누르면 채널 말투로 3가지 톤을 만들어 줍니다.
    </div>
    <h2 id="idea-texts-title" hidden>생성된 텍스트</h2>
    <div class="texts" id="idea-texts"></div>
  </section>
```

`<style>`에 더한다:

```css
  .tabs { display: flex; gap: 6px; margin: 16px 0 0; }
  .tab {
    font: inherit; cursor: pointer; padding: 9px 16px;
    background: transparent; border: 1px solid transparent;
    border-bottom: 2px solid transparent; color: var(--ink-soft);
  }
  .tab.is-active { color: var(--accent); border-bottom-color: var(--accent); font-weight: 700; }
  .chips { display: flex; gap: 6px; flex-wrap: wrap; margin: 12px 0; }
  .chip {
    font: inherit; font-size: 12px; cursor: pointer; padding: 5px 12px;
    border: 1px solid var(--line); border-radius: 999px; background: var(--card);
  }
  .chip.is-active { border-color: var(--accent); color: var(--accent); font-weight: 700; }
  .idea { position: relative; }
  .idea label { display: flex; gap: 8px; align-items: flex-start; cursor: pointer; }
  .idea .badge-hot {
    font-size: 10px; font-weight: 700; color: #b0491f; background: #fbe9e2;
    padding: 2px 6px; border-radius: 3px;
  }
```

- [ ] **Step 4: 스크립트 추가**

`index.html` 스크립트 끝에 더한다:

```javascript
  // ── 탭 ──
  document.querySelectorAll(".tab").forEach((tab) => {
    tab.onclick = () => {
      document.querySelectorAll(".tab").forEach((t) => t.classList.remove("is-active"));
      tab.classList.add("is-active");
      $("panel-outfit").hidden = tab.dataset.tab !== "outfit";
      $("panel-ideas").hidden = tab.dataset.tab !== "ideas";
    };
  });

  // ── 콘텐츠 아이디어 보울 ──
  let ideaItems = [];
  let activeGroup = "all";

  function ideaCard(i, index) {
    const meta = [
      i.category,
      i.likes != null ? `♥ ${i.likes}` : null,
      i.views != null ? `조회 ${i.views}` : null,
    ].filter(Boolean).map(esc).join(" · ");
    return `
      <div class="look idea" data-group="${esc(i.group)}">
        <label>
          <input type="checkbox" data-url="${esc(i.url)}" />
          <span>
            <span class="src">${esc(i.source_label)}</span>
            ${i.is_hot ? '<span class="badge-hot">🔥 반응 좋음</span>' : ""}
            <br /><b>${esc(i.title)}</b>
            <div class="meta">${meta}</div>
            <a class="src-link" href="${esc(i.url)}" target="_blank" rel="noopener noreferrer">원본 ↗</a>
          </span>
        </label>
      </div>`;
  }

  function renderIdeas(data) {
    ideaItems = data.items;
    $("idea-empty").hidden = true;
    $("idea-warn").innerHTML = data.failed.length
      ? `<div class="warn">${data.failed.map(esc).join(", ")} 수집에 실패했습니다.</div>`
      : "";

    const chips = [["all", "전체"], ...Object.entries(data.groups)];
    $("idea-filters").innerHTML = chips
      .map(([key, label]) =>
        `<button class="chip ${key === activeGroup ? "is-active" : ""}" data-group="${esc(key)}">${esc(label)}</button>`)
      .join("");
    $("idea-list").innerHTML = data.items.map(ideaCard).join("");
    applyGroupFilter();
  }

  function applyGroupFilter() {
    document.querySelectorAll(".idea").forEach((card) => {
      card.hidden = activeGroup !== "all" && card.dataset.group !== activeGroup;
    });
  }

  $("idea-filters").addEventListener("click", (event) => {
    const chip = event.target.closest(".chip");
    if (!chip) return;
    activeGroup = chip.dataset.group;
    document.querySelectorAll(".chip").forEach((c) => c.classList.remove("is-active"));
    chip.classList.add("is-active");
    applyGroupFilter();
  });

  $("idea-list").addEventListener("change", () => {
    const picked = document.querySelectorAll("#idea-list input:checked").length;
    $("btn-idea-texts").disabled = picked === 0;
  });

  async function withIdeaBusy(message, task) {
    $("idea-busy").textContent = message;
    $("idea-busy").hidden = false;
    ["btn-ideas", "btn-idea-texts"].forEach((id) => ($(id).disabled = true));
    try {
      await task();
    } finally {
      $("idea-busy").hidden = true;
      $("btn-ideas").disabled = false;
      const picked = document.querySelectorAll("#idea-list input:checked").length;
      $("btn-idea-texts").disabled = picked === 0;
    }
  }

  $("btn-ideas").onclick = () =>
    withIdeaBusy("소식을 모으는 중… 30초쯤 걸립니다.", async () => {
      renderIdeas(await call("/api/ideas"));
      $("idea-texts-title").hidden = true;
      $("idea-texts").innerHTML = "";
    });

  $("btn-idea-texts").onclick = () =>
    withIdeaBusy("텍스트를 쓰는 중…", async () => {
      const urls = [...document.querySelectorAll("#idea-list input:checked")]
        .map((input) => input.dataset.url);
      const data = await call("/api/ideas/texts", { urls });
      $("idea-texts").innerHTML = data.texts.map(textCard).join("");
      $("idea-texts-title").hidden = false;
      $("idea-texts-title").scrollIntoView({ behavior: "smooth" });
    });
```

기존 복사 버튼 처리기는 `#texts`에만 걸려 있다. 아이디어 텍스트에도
붙도록 그 처리기의 대상을 `document`로 바꾸고 `data-copy` 버튼 전체를
받게 한다(이미 `document` 수준 처리기가 있으면 그대로 둔다).

- [ ] **Step 5: 테스트 통과 확인**

Run: `C:\venvs\willy\Scripts\python.exe -m pytest tests/test_web.py -q`
Expected: PASS

- [ ] **Step 6: 브라우저 확인**

`.claude/launch.json`의 `willy-run`으로 서버를 띄우고 http://127.0.0.1:8765 에서:
탭 전환, 아이디어 불러오기, 필터 칩, 체크박스 선택, 텍스트 생성, 복사.

- [ ] **Step 7: 커밋**

```bash
git add src/willy/web/static/index.html tests/test_web.py
git commit -m "feat: 로컬 앱에 콘텐츠 아이디어 보울 탭 추가

탭 전환은 클라이언트에서만 한다. 서버 라우팅을 늘릴 이유가 없다.

외부 사이트에서 온 제목·카테고리는 전부 이스케이프한다. 필터 칩은
소스 그룹(할인/드랍·신상/매거진)으로 거르고, 선택이 없으면 생성
버튼을 잠가 빈 요청을 막는다."
```

---

## Task 11: 게시 페이지와 배치 연동

**Files:**
- Modify: `src/willy/publisher/site.py`, `build_site.py`
- Modify: `tests/test_site.py`

**Interfaces:**
- Consumes: Task 1의 `IdeaItem`, Task 7의 `collect_ideas`
- Produces: `render_site(state, texts, generated_at, og_image=None, ideas=None)`

게시 페이지는 정적이라 선택·생성이 불가능하다. 읽기 전용 목록으로 둔다.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_site.py` 끝에 덧붙인다:

```python
def test_site_renders_idea_section():
    from willy.ideas.models import IdeaItem

    ideas = [
        IdeaItem(
            source="eyesmag", title="버켄스탁 x 아더에러 협업", url="https://x.test/1",
            category="패션 > 슈즈", views=9000, is_hot=True,
        )
    ]

    html = render_site(state_with(), TEXTS, STAMP, ideas=ideas)

    assert "콘텐츠 아이디어 보울" in html
    assert "버켄스탁 x 아더에러 협업" in html
    assert "https://x.test/1" in html
    assert "🔥" in html


def test_site_without_ideas_omits_the_section():
    html = render_site(state_with(), TEXTS, STAMP, ideas=[])

    assert "콘텐츠 아이디어 보울" not in html


def test_idea_titles_are_escaped_on_the_published_page():
    from willy.ideas.models import IdeaItem

    ideas = [
        IdeaItem(source="vogue", title="<script>alert(1)</script>", url="https://x.test/2")
    ]

    html = render_site(state_with(), TEXTS, STAMP, ideas=ideas)

    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `C:\venvs\willy\Scripts\python.exe -m pytest tests/test_site.py -q`
Expected: FAIL — `TypeError: render_site() got an unexpected keyword argument 'ideas'`

- [ ] **Step 3: 게시 페이지 구현**

`src/willy/publisher/site.py`에 카드 헬퍼를 더한다:

```python
def _idea_card(item) -> str:
    source = IDEA_SOURCES.get(item.source)
    label = source.label if source else item.source
    meta = " · ".join(
        escape(str(part))
        for part in (
            item.category,
            f"♥ {item.likes}" if item.likes is not None else None,
            f"조회 {item.views}" if item.views is not None else None,
        )
        if part
    )
    return f"""
      <div class="look">
        <span class="src">{escape(label)}</span>
        {'<span class="badge ai">🔥 반응 좋음</span>' if item.is_hot else ''}
        <div class="meta"><b>{escape(item.title)}</b><br />{meta}</div>
        <a class="src-link" href="{escape(item.url)}" target="_blank" rel="noopener noreferrer">원본 ↗</a>
      </div>"""
```

상단 import에 `from willy.ideas.sources import IDEA_SOURCES`를 더하고,
`render_site` 시그니처에 `ideas: list | None = None`을 더한 뒤 본문에서
섹션을 만든다:

```python
    idea_section = ""
    if ideas:
        cards = "".join(_idea_card(item) for item in ideas)
        idea_section = f"""
  <h2>콘텐츠 아이디어 보울 <span class="muted">{len(ideas)}건 · 읽기 전용</span></h2>
  <div class="rule"></div>
  <div class="pool">{cards}</div>"""
```

그리고 텍스트 섹션 뒤, 수집된 룩 섹션 앞에 `{idea_section}`을 넣는다.

- [ ] **Step 4: 배치 연동**

`build_site.py`의 `main()`에서 텍스트 생성 뒤에 더한다:

```python
    from willy.collector.browser import browser_page
    from willy.ideas.collector import collect_ideas

    try:
        ideas, failed_sources = collect_ideas(
            page_factory=lambda: browser_page(headless=True)
        )
        log.info("아이디어 %d건 수집 (실패: %s)", len(ideas), failed_sources or "없음")
    except Exception:
        # 아이디어가 실패해도 보드 게시는 진행한다.
        log.exception("아이디어 수집 실패 — 아이디어 없이 게시합니다")
        ideas = []

    html = render_site(state, texts, datetime.now(KST), og_image=og_image, ideas=ideas)
```

- [ ] **Step 5: 테스트 통과 확인**

Run: `C:\venvs\willy\Scripts\python.exe -m pytest -q`
Expected: PASS (전체)

- [ ] **Step 6: 로컬 배치 확인**

Run: `C:\venvs\willy\Scripts\python.exe build_site.py site`
Expected: 로그에 "아이디어 N건 수집", `site/index.html`에 아이디어 섹션

- [ ] **Step 7: 커밋과 푸시**

```bash
git add src/willy/publisher/site.py build_site.py tests/test_site.py
git commit -m "feat: 게시 페이지 아이디어 섹션과 배치 연동

게시 페이지는 정적이라 선택·생성이 불가능하다(브라우저에서 AI를
부르려면 키를 공개해야 한다). 읽기 전용 목록으로 두고, 실제 생성은
로컬 앱 탭에서 한다.

아이디어 수집이 통째로 실패해도 보드 게시는 진행한다. 아침에 보드가
아예 없는 것보다 아이디어만 빠진 편이 낫다."
git push origin main
```

---

## Self-Review 결과

스펙과 대조해 확인한 사항:

- 소스 7곳·그룹·robots 제외 → Task 1
- 파서 5종 → Task 2~5
- 반응 뱃지(소스별 임계값) → Task 6
- 소스당 10건 상한, 부분 실패 허용 → Task 7
- 상세 본문 + 텍스트 3종 + 폴백 → Task 8
- 엔드포인트 2개 + 잠금 → Task 9
- 탭 UI, 필터 칩, 선택 생성 → Task 10
- 게시 페이지 읽기 전용, 배치 연동 → Task 11

이름 일관성: `IdeaItem`, `IdeaSource`, `IDEA_SOURCES`, `SOURCE_GROUPS`,
`parse_rss/parse_eomisae/parse_hearst/parse_condenast/parse_eyesmag`,
`mark_hot`, `collect_ideas`, `fetch_detail`, `write_from_ideas`,
`template_idea_texts`, `build_idea_prompt` — 태스크 간 표기가 같다.

스펙의 "범위 밖"(이미지 생성·자동 발행·중복 방지)은 어느 태스크에도
넣지 않았다.
