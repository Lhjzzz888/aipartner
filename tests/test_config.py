import pytest

from driving_school_rights.config import ConfigError, load_config


def test_load_config_reads_server_env(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "server-side-test-key")
    monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-chat-test")

    config = load_config()

    assert config.api_key == "server-side-test-key"
    assert config.api_base_url == "https://api.deepseek.com"
    assert config.model == "deepseek-chat-test"


def test_load_config_uses_safe_defaults(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    for name in (
        "DEEPSEEK_BASE_URL",
        "DEEPSEEK_MODEL",
        "MAX_UPLOAD_MB",
        "MAX_PDF_PAGES",
        "MAX_TEXT_CHARS",
        "MAX_CALLS_PER_SESSION",
        "MAX_CALLS_PER_DAY",
    ):
        monkeypatch.delenv(name, raising=False)

    config = load_config()

    assert config.model == "deepseek-flash"
    assert config.api_base_url == "https://api.deepseek.com"
    assert config.max_upload_mb == 10
    assert config.max_pdf_pages == 30
    assert config.max_text_chars == 15000
    assert config.max_calls_per_session == 5
    assert config.max_calls_per_day == 100


def test_load_config_rejects_missing_api_key(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    with pytest.raises(ConfigError, match="DEEPSEEK_API_KEY"):
        load_config()
