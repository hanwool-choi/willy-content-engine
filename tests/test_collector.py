import contextlib
from pathlib import Path

import pytest

from willy.collector.collector import Collector
from willy.collector.sources import SourceSpec


class FakeElement:
    def __init__(
        self,
        image_url: str | None,
        link: str | None = None,
        own_href: str | None = None,
    ):
        self._image = image_url
        self._link = link
        self._own_href = own_href
        self.screenshot_calls: list[Path] = []

    def query_selector(self, selector: str):
        if selector == "img":
            return FakeImage(self._image) if self._image else None
        if selector == "a":
            return FakeLink(self._link) if self._link else None
        return None

    def get_attribute(self, name: str):
        """카드 자체가 링크인 경우(유니클로 스타일링북)를 위한 것."""
        return self._own_href if name == "href" else None

    def screenshot(self, path: str):
        Path(path).write_bytes(b"\xff\xd8\xff\xe0screenshot")
        self.screenshot_calls.append(Path(path))


class FakeImage:
    def __init__(self, url: str):
        self._url = url

    def get_attribute(self, name: str):
        return self._url if name == "src" else None


class FakeLink:
    def __init__(self, href: str):
        self._href = href

    def get_attribute(self, name: str):
        return self._href if name == "href" else None


class FakeMouse:
    """Playwright의 page.mouse. 실물은 page.mouse.wheel()이지 page.mouse_wheel()이 아니다."""

    def __init__(self):
        self.wheels: list[tuple[int, int]] = []

    def wheel(self, dx: int, dy: int):
        self.wheels.append((dx, dy))


class FakePage:
    def __init__(self, elements: list[FakeElement]):
        self._elements = elements
        self.visited: list[str] = []
        self.mouse = FakeMouse()

    def goto(self, url: str, **kwargs):
        self.visited.append(url)

    def wait_for_timeout(self, ms: int):
        pass

    def query_selector_all(self, selector: str):
        return self._elements


def spec(name="musinsa_snap") -> SourceSpec:
    return SourceSpec(
        name=name, url="https://example.test/", card_selector=".card",
        image_selector="img", link_selector="a", scroll_rounds=1,
    )


def make_collector(tmp_path: Path, page: FakePage, downloader=None) -> Collector:
    return Collector(
        workspace=tmp_path,
        page_factory=lambda: contextlib.nullcontext(page),
        downloader=downloader
        or (lambda url, dest: dest.write_bytes(b"\xff\xd8" + url.encode())),
    )


def test_collect_downloads_original_when_url_present(tmp_path: Path):
    page = FakePage([FakeElement("https://cdn.test/a.jpg", "https://x.test/1")])
    looks = make_collector(tmp_path, page).collect([spec()], limit_per_source=5)

    assert len(looks) == 1
    assert looks[0].capture_method == "original_url"
    assert looks[0].image_path.read_bytes() == b"\xff\xd8https://cdn.test/a.jpg"
    assert looks[0].source_url == "https://x.test/1"


def test_collect_falls_back_to_screenshot_when_no_image_url(tmp_path: Path):
    page = FakePage([FakeElement(None)])
    looks = make_collector(tmp_path, page).collect([spec()], limit_per_source=5)

    assert looks[0].capture_method == "screenshot"
    assert looks[0].image_path.exists()


def test_collect_falls_back_to_screenshot_when_download_fails(tmp_path: Path):
    def failing(url, dest):
        raise OSError("네트워크 오류")

    page = FakePage([FakeElement("https://cdn.test/a.jpg")])
    looks = make_collector(tmp_path, page, downloader=failing).collect(
        [spec()], limit_per_source=5
    )

    assert looks[0].capture_method == "screenshot"


def test_collect_respects_limit(tmp_path: Path):
    page = FakePage([FakeElement(f"https://cdn.test/{i}.jpg") for i in range(30)])
    looks = make_collector(tmp_path, page).collect([spec()], limit_per_source=20)

    assert len(looks) == 20


def test_collect_continues_when_one_source_fails(tmp_path: Path):
    """한 소스가 죽어도 나머지는 수집한다."""

    class ExplodingPage(FakePage):
        def goto(self, url: str, **kwargs):
            if "bad" in url:
                raise RuntimeError("페이지 로드 실패")
            super().goto(url, **kwargs)

    page = ExplodingPage([FakeElement("https://cdn.test/a.jpg")])
    bad = SourceSpec(
        name="bad", url="https://bad.test/", card_selector=".card",
        image_selector="img", scroll_rounds=1,
    )

    looks = make_collector(tmp_path, page).collect([bad, spec()], limit_per_source=5)

    assert len(looks) == 1
    assert looks[0].source == "musinsa_snap"


def test_add_manual_from_local_file(tmp_path: Path):
    src = tmp_path / "my.jpg"
    src.write_bytes(b"\xff\xd8manual")

    look = make_collector(tmp_path, FakePage([])).add_manual(str(src))

    assert look.source == "manual"
    assert look.capture_method == "original_url"
    assert look.image_path.read_bytes() == b"\xff\xd8manual"


def test_add_manual_preserves_png_format(tmp_path: Path):
    """스크린샷은 대개 PNG다. .jpg로 이름만 바꿔 저장하면 안 된다."""
    src = tmp_path / "shot.png"
    src.write_bytes(b"\x89PNG\r\n\x1a\n" + b"body")

    look = make_collector(tmp_path, FakePage([])).add_manual(str(src))

    assert look.image_path.suffix == ".png"
    assert src.exists()  # 원본은 그대로 남는다


def test_add_manual_from_url(tmp_path: Path):
    def downloader(url, dest):
        dest.write_bytes(b"\xff\xd8\xff\xe0downloaded")

    look = make_collector(tmp_path, FakePage([]), downloader=downloader).add_manual(
        "https://cdn.test/a.jpg"
    )

    assert look.source == "manual"
    assert look.source_url == "https://cdn.test/a.jpg"
    assert look.image_path.read_bytes().startswith(b"\xff\xd8")


def test_collect_falls_back_to_screenshot_when_download_returns_non_image(tmp_path: Path):
    """다운로드가 HTML을 받아와도 이미지인 척하지 않는다."""
    def downloader(url, dest):
        dest.write_bytes(b"<!DOCTYPE html><html>404</html>")

    page = FakePage([FakeElement("https://cdn.test/a.jpg")])
    looks = make_collector(tmp_path, page, downloader=downloader).collect(
        [spec()], limit_per_source=5
    )

    assert looks[0].capture_method == "screenshot"


def test_collect_closes_the_page_context(tmp_path: Path):
    """수집이 끝나면 브라우저가 닫혀야 한다. 서버가 계속 떠 있으므로
    닫지 않으면 버튼을 누를 때마다 Chromium이 쌓인다."""
    closed = []

    @contextlib.contextmanager
    def factory():
        page = FakePage([FakeElement("https://cdn.test/a.jpg")])
        try:
            yield page
        finally:
            closed.append(True)

    collector = Collector(
        workspace=tmp_path,
        page_factory=factory,
        downloader=lambda url, dest: dest.write_bytes(b"\xff\xd8" + url.encode()),
    )
    collector.collect([spec()], limit_per_source=5)

    assert closed == [True]


def test_collect_closes_the_page_even_when_a_source_explodes(tmp_path: Path):
    closed = []

    @contextlib.contextmanager
    def factory():
        class ExplodingPage(FakePage):
            def goto(self, url: str, **kwargs):
                raise RuntimeError("페이지 로드 실패")

        try:
            yield ExplodingPage([])
        finally:
            closed.append(True)

    collector = Collector(workspace=tmp_path, page_factory=factory)
    collector.collect([spec()], limit_per_source=5)

    assert closed == [True]


def test_fake_page_matches_the_real_playwright_api():
    """가짜가 실제 API와 다르면 테스트는 아무것도 검증하지 못한다.

    page.mouse_wheel()은 Playwright에 없다. 실물은 page.mouse.wheel()이다.
    이 테스트가 없던 동안 수집기는 존재하지 않는 메서드를 부르고 있었고
    10개 테스트가 전부 통과했다.
    """
    from playwright.sync_api import Mouse, Page

    assert not hasattr(Page, "mouse_wheel"), "Playwright에 없는 메서드다"
    assert hasattr(Mouse, "wheel")
    assert hasattr(Page, "goto")
    assert hasattr(Page, "query_selector_all")
    assert hasattr(Page, "wait_for_timeout")


def test_collect_scrolls_to_trigger_lazy_loading(tmp_path: Path):
    """지연 로딩 사이트라 스크롤하지 않으면 카드가 안 붙는다."""
    page = FakePage([FakeElement("https://cdn.test/a.jpg")])
    make_collector(tmp_path, page).collect([spec()], limit_per_source=5)

    assert page.mouse.wheels, "스크롤을 한 번도 하지 않았다"


def test_collect_uses_the_cards_own_href_when_it_is_the_link(tmp_path: Path):
    """유니클로 스타일링북은 <a>가 카드를 감싼다. link_selector로는 못 잡는다."""
    page = FakePage([FakeElement("https://cdn.test/a.jpg", own_href="/stylingbook/1")])
    uniqlo = SourceSpec(
        name="uniqlo_women", url="https://example.test/",
        card_selector="a", image_selector="img", link_selector=None, scroll_rounds=1,
    )

    looks = make_collector(tmp_path, page).collect([uniqlo], limit_per_source=5)

    assert looks[0].source_url == "/stylingbook/1"


def test_collect_drops_duplicate_images_within_a_source(tmp_path: Path):
    """무신사 스냅은 같은 사진을 목록에 두 번 싣는 경우가 있다.

    그대로 두면 같은 룩을 두 번 분석해 비전 API 비용을 버리고, 배정
    후보에도 중복으로 올라간다.
    """
    page = FakePage([
        FakeElement("https://cdn.test/a.jpg"),
        FakeElement("https://cdn.test/b.jpg"),
        FakeElement("https://cdn.test/a.jpg"),  # 1번과 같은 사진
    ])

    looks = make_collector(tmp_path, page).collect([spec()], limit_per_source=10)

    assert len(looks) == 2
    contents = [look.image_path.read_bytes() for look in looks]
    assert len(set(contents)) == 2


def test_collect_drops_duplicates_across_sources(tmp_path: Path):
    """소스가 달라도 같은 사진이면 한 번만 남긴다."""
    page = FakePage([FakeElement("https://cdn.test/same.jpg")])
    a = spec("musinsa_snap")
    b = spec("uniqlo_men")

    looks = make_collector(tmp_path, page).collect([a, b], limit_per_source=10)

    assert len(looks) == 1
    assert looks[0].source == "musinsa_snap"  # 먼저 본 쪽이 남는다


def test_collect_removes_the_duplicate_file_from_disk(tmp_path: Path):
    """중복은 건너뛰기만 하지 말고 파일도 남기지 않는다."""
    page = FakePage([
        FakeElement("https://cdn.test/a.jpg"),
        FakeElement("https://cdn.test/a.jpg"),
    ])

    make_collector(tmp_path, page).collect([spec()], limit_per_source=10)

    assert len(list(tmp_path.glob("musinsa_snap-*"))) == 1
