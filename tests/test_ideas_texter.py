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


def _gemini_http(payload: str):
    class Http:
        def post(self, url, **kwargs):
            class Response:
                status_code = 200

                @staticmethod
                def json():
                    return {"candidates": [{"content": {"parts": [{"text": payload}]}}]}

                @staticmethod
                def raise_for_status():
                    pass

            return Response()

    return Http()


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


def test_prompt_forbids_inventing_numbers():
    """가격·발매일을 지어내면 콘텐츠 신뢰가 깨진다."""
    assert "지어내지 마라" in build_idea_prompt(PAIRS)


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
