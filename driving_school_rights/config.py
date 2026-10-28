"""Server-side configuration for the driving-school rights assistant."""

from dataclasses import dataclass
import os
from collections.abc import Mapping


class ConfigError(ValueError):
    """Raised when required or bounded application configuration is invalid."""


@dataclass(frozen=True)
class AppConfig:
    api_key: str
    api_base_url: str
    model: str
    max_upload_mb: int
    max_pdf_pages: int
    max_text_chars: int
    max_calls_per_session: int
    max_calls_per_day: int


def _positive_int(environ: Mapping[str, str], name: str, default: int) -> int:
    raw = environ.get(name, str(default)).strip()
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{name} 必须是正整数。") from exc
    if value < 1:
        raise ConfigError(f"{name} 必须是正整数。")
    return value


def load_config(environ: Mapping[str, str] | None = None) -> AppConfig:
    """Load configuration from server environment variables only."""
    source = os.environ if environ is None else environ
    api_key = source.get("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        raise ConfigError(
            "未配置 DEEPSEEK_API_KEY。请在服务端部署环境变量中配置，不要把密钥写入代码或发到公开页面。"
        )

    base_url = source.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com").strip()
    model = source.get("DEEPSEEK_MODEL", "deepseek-flash").strip()
    if not base_url or not model:
        raise ConfigError("DEEPSEEK_BASE_URL 和 DEEPSEEK_MODEL 不能为空。")

    return AppConfig(
        api_key=api_key,
        api_base_url=base_url.rstrip("/"),
        model=model,
        max_upload_mb=_positive_int(source, "MAX_UPLOAD_MB", 10),
        max_pdf_pages=_positive_int(source, "MAX_PDF_PAGES", 30),
        max_text_chars=_positive_int(source, "MAX_TEXT_CHARS", 15000),
        max_calls_per_session=_positive_int(source, "MAX_CALLS_PER_SESSION", 5),
        max_calls_per_day=_positive_int(source, "MAX_CALLS_PER_DAY", 100),
    )
