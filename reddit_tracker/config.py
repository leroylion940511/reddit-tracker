"""應用組態。

讀取 `.env` 與環境變數。沿用 v3 的 settings pattern，改 pydantic-settings v2。
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Reddit ---
    reddit_scraper: str = "public_json"       # public_json / praw / fake
    reddit_client_id: str | None = None
    reddit_client_secret: str | None = None
    reddit_user_agent: str = "reddit_tracker/0.1 by unknown"

    # --- DB ---
    database_url: str = "sqlite:///./reddit_tracker.db"

    # --- LLM (M3+) ---
    llm_provider: str = "anthropic"             # anthropic / minimax / fake
    anthropic_api_key: str | None = None

    minimax_api_key: str | None = None
    minimax_base_url: str = "https://api.minimaxi.chat/v1"
    minimax_model: str = "MiniMax-Text-01"

    # --- Telegram (M4+) ---
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None

    # --- Discovery 排程 ---
    poll_subreddit_minutes: int = 60
    poll_keyword_hours: int = 6
    discovery_per_sub_limit: int = 50         # /new 每 sub 抓多少
    discovery_per_keyword_limit: int = 50     # search 每詞抓多少

    # --- Scoring 排程（M3）---
    scoring_minutes: int = 30                 # 每 30 分鐘掃未評分 candidate
    scoring_batch_limit: int = 50             # 單批最多評幾篇

    # --- Misc ---
    log_level: str = "INFO"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
