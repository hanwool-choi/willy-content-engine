"""Playwright 세션. 헤드리스가 아니라 화면을 띄워 진행을 볼 수 있게 한다."""
from __future__ import annotations

from contextlib import contextmanager

from playwright.sync_api import sync_playwright

# 무신사 robots.txt는 Claude-User 등 사용자 주도 에이전트를 허용한다.
# 정체를 숨기지 않는다.
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)


@contextmanager
def browser_page(headless: bool = False):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(
            user_agent=USER_AGENT, viewport={"width": 1440, "height": 900}
        )
        page = context.new_page()
        try:
            yield page
        finally:
            context.close()
            browser.close()
