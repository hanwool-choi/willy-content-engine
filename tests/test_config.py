from willy.config import Settings


def test_load_reads_gemini_key(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "g-key")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    settings = Settings.load()

    assert settings.gemini_api_key == "g-key"
    assert settings.anthropic_api_key == ""


def test_load_defaults_gemini_key_to_empty(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    assert Settings.load().gemini_api_key == ""
