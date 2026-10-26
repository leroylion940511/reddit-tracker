"""應用組態。

讀取 `.env` 與環境變數。沿用 v3 的 settings pattern，改 pydantic-settings v2。
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

    # --- Reddit ---
    reddit_scraper: str = "public_json"       # public_json / praw / fake
    reddit_client_id: str | None = None
    reddit_client_secret: str | None = None
    reddit_user_agent: str = "reddit_tracker/0.1 by unknown"

    # --- DB ---
    database_url: str = "sqlite:///./reddit_tracker.db"

    # --- LLM (M3+) ---
    llm_provider: str = "anthropic"             # anthropic / minimax / gemini / web / fake
    anthropic_api_key: str | None = None

    minimax_api_key: str | None = None
    minimax_base_url: str = "https://api.minimaxi.chat/v1"
    minimax_model: str = "MiniMax-Text-01"

    # --- Gemini Developer API (Free Tier guardrails) ---
    # API 的實際 RPM/TPM/RPD 以 AI Studio 顯示為準。這些是本機保守上限，避免
    # scheduler 一次回補把免費額度耗盡；日界線採 Gemini 的 Pacific time。
    gemini_api_key: str | None = None
    gemini_scoring_model: str = "gemini-3.5-flash-lite"
    gemini_qa_model: str = "gemini-3.5-flash"
    gemini_newsroom_model: str = "gemini-3.5-flash-lite"
    gemini_scoring_daily_limit: int = 450
    gemini_qa_daily_limit: int = 50
    # Newsroom 將整期稿件合併成一個 JSON request；保留更小的日上限，避免
    # 試刊或重試和既有 scoring/QA 共用免費額度時失控。
    gemini_newsroom_daily_limit: int = 12
    gemini_requests_per_minute: int = 5
    gemini_timeout_seconds: float = 60.0
    gemini_max_429_retries: int = 2
    gemini_quota_state_path: str = "/tmp/reddit-tracker-gemini-quota.json"
    gemini_fallback_provider: str = "web"       # web / fake

    # --- 零 API-key LLM（已登入的瀏覽器工作階段）---
    # `web` provider 只透過本機 Chrome DevTools 連線到使用者手動登入的分頁；
    # 絕不把帳密 / cookie 寫進設定或 DB，也不會連到非 localhost 的 CDP。
    web_llm_provider: str = "chatgpt"            # chatgpt / gemini
    web_llm_cdp_url: str = "http://127.0.0.1:9222"
    web_llm_timeout_seconds: float = 180.0
    web_llm_poll_interval_seconds: float = 1.0
    web_llm_settle_seconds: float = 3.0
    web_llm_lock_path: str = "/tmp/reddit-tracker-web-llm.lock"

    # --- Telegram (M4+) ---
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None

    # --- v5 AI Newsroom trial ---
    newsroom_writer: str = "gemini"            # gemini / template
    newsroom_template_fallback: bool = True
    newsroom_delivery_timezone: str = "Asia/Taipei"
    newsroom_preparation_hour: int = 5
    newsroom_preparation_minute: int = 30
    newsroom_delivery_hour: int = 8
    newsroom_delivery_minute: int = 30
    # v5 owns its candidate intake. This deliberately does not start v4's
    # scoring, Top-5, polling, or bot jobs.
    newsroom_discovery_interval_minutes: int = 90

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
    daily_writer: str = "gemini"                # gemini / template
    daily_prepare_hour: int = 6
    daily_prepare_minute: int = 0
    daily_delivery_hour: int = 8
    daily_delivery_minute: int = 35
    daily_site_dir: str = "site/daily"
    gemini_daily_model: str = "gemini-3.5-flash-lite"
    # 每天約 12 次（編輯會議 1＋頭版 1＋10 版）；留給重試與重編。實際免費額度以 AI Studio 為準。
    gemini_daily_limit: int = 60

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
