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
    # 預設值對 public JSON (~10 QPM) 已校準；OAuth 過了可手動下調 interval。
    poll_subreddit_minutes: int = 90
    poll_keyword_hours: int = 12
    discovery_per_sub_limit: int = 30         # /new 每 sub 抓多少
    discovery_per_keyword_limit: int = 30     # search 每詞抓多少

    # --- Scraper (public JSON) 速率 ---
    # PublicJSONScraper 對單一連線的最小請求間隔；預設 6.5s ≈ 9 QPM，
    # 留 buffer 對 Reddit ~10 QPM 限制。OAuth (PRAW) 路徑會忽略此值。
    public_json_min_interval_seconds: float = 6.5

    # --- Scoring 排程（M3）---
    scoring_minutes: int = 30                 # 每 30 分鐘掃未評分 candidate
    scoring_batch_limit: int = 50             # 單批最多評幾篇

    # --- Push 排程（M4）---
    # 預設 01:00 UTC = 09:00 Asia/Taipei
    daily_push_hour_utc: int = 1
    daily_push_minute_utc: int = 0
    breaking_check_minutes: int = 10

    # --- Tracked polling 排程（M5）---
    # select_due_posts 自己按 tier 過濾，這個 interval 只是『多久檢查一次有沒有 due』
    # 設成 15 分鐘以對齊 tier='hot' 的最細頻率即可。
    polling_minutes: int = 15

    # --- Detection 排程（M5.3–5.6）---
    # 比 snapshot 重（一篇 tracked 一輪要打 3 個 endpoint），預設 60 分鐘
    detection_minutes: int = 60

    # --- Milestone push 排程（M5.8）---
    # 騎 breaking_check 同節奏即可
    milestone_check_minutes: int = 10

    # --- QA idle sweep（M6）---
    # 5 分鐘無互動 → 強制關 session；scheduler 每分鐘掃一次即可
    qa_idle_sweep_minutes: int = 1
    qa_idle_ttl_seconds: int = 300

    # --- Misc ---
    log_level: str = "INFO"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
