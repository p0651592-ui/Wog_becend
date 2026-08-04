from __future__ import annotations

import os


class Settings:
    """Runtime settings loaded from environment variables."""

    project_name: str = os.getenv("PROJECT_NAME", "WOG Backend")
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./wog.db")
    telegram_bot_token: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    telegram_chat_id: str = os.getenv("TELEGRAM_CHAT_ID", "")
    cors_origins: list[str] = [
        origin.strip()
        for origin in os.getenv("CORS_ORIGINS", "*").split(",")
        if origin.strip()
    ]


settings = Settings()
