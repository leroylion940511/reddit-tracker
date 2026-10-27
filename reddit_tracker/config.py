"""應用組態。

讀取 `.env` 與環境變數。pydantic-settings v2；`.env` 裡已不再使用的舊鍵會被忽略（extra="ignore"）。
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Reddit（只剩 probe 腳本探測登錄表的 reddit 來源時使用）---
    reddit_user_agent: str = "reddit_tracker/0.1 by unknown"

    # --- DB ---
    database_url: str = "sqlite:///./reddit_tracker.db"

    # --- Gemini Developer API (Free Tier guardrails) ---
    # API 的實際 RPM/TPM/RPD 以 AI Studio 顯示為準。這些是本機保守上限，避免
    # scheduler 一次回補把免費額度耗盡；日界線採 Gemini 的 Pacific time。
    gemini_api_key: str | None = None
    gemini_requests_per_minute: int = 5
    gemini_timeout_seconds: float = 60.0
    gemini_max_429_retries: int = 2
    gemini_quota_state_path: str = "/tmp/reddit-tracker-gemini-quota.json"

    # --- Codex CLI（綜合日報撰稿預設 provider；吃本機 ChatGPT 訂閱登入，不用 API key）---
    codex_bin: str = "/Applications/ChatGPT.app/Contents/Resources/codex-cli/bin/codex"
    codex_model: str = "gpt-6.1-sol"
    codex_reasoning_effort: str = "low"
    codex_timeout_seconds: float = 300.0

    # --- Telegram（綜合日報發行）---
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None

    # --- 排程時區（收集與日報共用）---
    newsroom_delivery_timezone: str = "Asia/Taipei"

    # --- 多來源收集（v2.0 綜合日報）---
    # RSSHub 為本機獨立服務，只綁 127.0.0.1；key 只放 .env，不寫進登錄表或 DB。
    rsshub_base_url: str = "http://127.0.0.1:1200"
    rsshub_access_key: str | None = None
    news_sources_path: str = "reddit_tracker/seeds/news_sources.yaml"
    # 預設關閉：部署收集層程式與 migration 不會自動改變線上 newsroom 行為。
    news_collection_enabled: bool = False
    news_collection_tick_minutes: int = 15

    # --- v2.0 綜合日報（規格見 docs/v5/DAILY_EDITION.md）---
    daily_edition_enabled: bool = False
    daily_writer: str = "codex"                 # codex / gemini / template
    daily_prepare_hour: int = 6
    daily_prepare_minute: int = 0
    daily_delivery_hour: int = 8
    daily_delivery_minute: int = 35
    daily_site_dir: str = "site/daily"
    gemini_daily_model: str = "gemini-3.5-flash-lite"
    # 每天約 12 次（編輯會議 1＋頭版 1＋10 版）；留給重試與重編。實際免費額度以 AI Studio 為準。
    gemini_daily_limit: int = 60

    # --- Misc ---
    log_level: str = "INFO"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
