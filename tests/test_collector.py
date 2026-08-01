import contextlib
from pathlib import Path

import pytest

from willy.collector.collector import Collector
from willy.collector.sources import SourceSpec


class FakeElement:
    def __init__(self, image_url: str | None, link: str | None = None):
        self._image = image_url
        self._link = link
        self.screenshot_calls: list[Path] = []

    def query_selector(self, selector: str):
        if selector == "img":
            return FakeImage(self._image) if self._image else None
        if selector == "a":
            return FakeLink(self._link) if self._link else None
        return None

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


class FakePage:
    def __init__(self, elements: list[FakeElement]):
        self._elements = elements
        self.visited: list[str] = []

    def goto(self, url: str, **kwargs):
        self.visited.append(url)

    def wait_for_timeout(self, ms: int):
        pass

    def mouse_wheel(self, dx: int, dy: int):
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
        downloader=downloader or (lambda url, dest: dest.write_bytes(b"\xff\xd8original")),
    )


def test_collect_downloads_original_when_url_present(tmp_path: Path):
    page = FakePage([FakeElement("https://cdn.test/a.jpg", "https://x.test/1")])
    looks = make_collector(tmp_path, page).collect([spec()], limit_per_source=5)

    assert len(looks) == 1
    assert looks[0].capture_method == "original_url"
    assert looks[0].image_path.read_bytes() == b"\xff\xd8original"
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
        downloader=lambda url, dest: dest.write_bytes(b"\xff\xd8original"),
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
