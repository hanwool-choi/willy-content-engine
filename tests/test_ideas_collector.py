import contextlib

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


def browser_source() -> IdeaSource:
    return IdeaSource(
        name="eyesmag", label="아이즈", url="https://c.test/f",
        kind="eyesmag", group="drop", needs_browser=True,
    )


def test_collects_from_multiple_sources():
    http = FakeHttp({"https://a.test/feed": RSS, "https://b.test/os": EOMISAE})

    items, failed = collect_ideas(sources=[rss_source(), eomisae_source()], http=http)

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

    items, failed = collect_ideas(sources=[rss_source(), eomisae_source()], http=http)

    assert failed == ["hypebeast"]
    assert [item.source for item in items] == ["eomisae_os"]


def test_applies_hot_badges():
    """수집 결과에 뱃지가 이미 매겨져 있어야 화면이 판정을 다시 하지 않는다."""
    http = FakeHttp({"https://b.test/os": EOMISAE})

    items, _ = collect_ideas(sources=[eomisae_source()], http=http)

    assert items[0].is_hot is True  # 좋아요 9 >= 5


def test_browser_source_is_skipped_without_page_factory():
    """로컬 앱은 브라우저를 띄우지 않는다. 그 소스만 빠지고 나머지는 모은다."""
    http = FakeHttp({"https://a.test/feed": RSS})

    items, failed = collect_ideas(sources=[rss_source(), browser_source()], http=http)

    assert failed == []
    assert all(item.source != "eyesmag" for item in items)


def test_browser_source_uses_page_factory_when_given():
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

    items, failed = collect_ideas(
        sources=[browser_source()],
        http=FakeHttp({}),
        page_factory=lambda: contextlib.nullcontext(page),
    )

    assert failed == []
    assert page.visited == ["https://c.test/f"]
    assert items[0].title == "협업 컬렉션 소식입니다"
