from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    telegram_bot_token: str = Field(...)
    telegram_chat_id: int = Field(...)
    # Only Telegram is proxied. The Supercell token is bound to this host's own
    # IP address, so clashroyale.com must be reached directly.
    telegram_proxy: str | None = None
    cr_api_token: str = Field(...)
    cr_clan_tag: str = Field(...)
    cr_api_base_url: str = "https://api.clashroyale.com/v1"

    db_path: Path = Path("./data.db")
    migrations_dir: Path = Path("./migrations")

    poll_interval_seconds: int = 300
    roster_interval_seconds: int = 3600
    miss_penalty: int = 50
    reminder_grace_minutes: int = 30

    log_level: str = "INFO"


def get_settings() -> Settings:
    return Settings()
