"""應用組態。

讀取 `.env` 與環境變數。pydantic-settings v2；`.env` 裡已不再使用的舊鍵會被忽略（extra="ignore"）。
"""

from __future__ import annotations

import os
from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# 允許的 LLM provider。網頁備援（用 Chrome 操控 ChatGPT／Gemini 網頁）已移除且禁止：
# 結果不可重現、呼叫次數記不到（手冊步驟 1、第 10.1 節第 6 條）。
LLM_PROVIDERS = ("codex", "gemini", "template", "fake")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=None if os.environ.get("REDDIT_TRACKER_NO_DOTENV") == "1" else ".env",
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
    # 429 只重試 1 次：每次 HTTP 嘗試都扣一格（手冊 6.7）。
    gemini_max_429_retries: int = 1

    # --- LLM 每日額度（依模型計數，所有用途共用；手冊步驟 1、6.7）---
    llm_daily_limit: int = 60
    llm_quota_state_path: str = "/tmp/reddit-tracker-llm-quota.json"

    # --- Codex CLI（綜合日報撰稿預設 provider；吃本機 ChatGPT 訂閱登入，不用 API key）---
    codex_bin: str = "/Applications/ChatGPT.app/Contents/Resources/codex-cli/bin/codex"
    codex_model: str = "gpt-6.1-sol"
    codex_reasoning_effort: str = "low"
    codex_timeout_seconds: float = 300.0
    # 失敗只重試 1 次；每次 subprocess 嘗試都扣一格額度。
    codex_max_retries: int = 1

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

    # --- 事件合併（手冊步驟 3；規格 docs/v5/CLUSTERING.md「共同實體與兩段門檻」）---
    # 實驗一凍結（tag exp1-frozen）時，這些數值與兩個 seeds 檔一起凍結。
    cluster_high_threshold: float = 0.45       # ≥ 高門檻：≥ high_min_entities 個共同實體就合併
    cluster_low_threshold: float = 0.28        # 介於兩門檻：≥ mid_min_entities 個；低於低門檻不合併
    cluster_high_min_entities: int = 1
    cluster_mid_min_entities: int = 2
    cluster_cross_lang_min_entities: int = 2   # 編輯會議程式跨語言合併
    cluster_llm_merge_min_entities: int = 1    # find_same_events 說合併時程式要確認的共同實體數
    name_glossary_path: str = "reddit_tracker/seeds/name_glossary.yaml"
    entity_common_words_path: str = "reddit_tracker/seeds/entity_common_words.yaml"

    # --- v2.0 綜合日報（規格見 docs/v5/DAILY_EDITION.md）---
    daily_edition_enabled: bool = False
    # pipeline＝現有流水線（實驗三對照組）；mas＝六個角色。預設 pipeline，不改線上行為。
    daily_mode: str = "pipeline"
    daily_writer: str = "codex"                 # codex / gemini / template / fake（不得是 web）
    # 11/15 定案：P 與 M 共用 Codex CLI 這一個模型字串（不是 Gemini）。之後不換。
    # PR #1 整合在 Mac 實測的 CLI 版本；11/15 前模型定案。
    daily_model_version: str = "gpt-6.1-sol | codex-cli 0.164.0-alpha.11.1 | reasoning_effort=low"
    daily_prepare_hour: int = 6
    daily_prepare_minute: int = 0
    daily_delivery_hour: int = 8
    daily_delivery_minute: int = 35
    daily_site_dir: str = "site/daily"
    # P 組影子版（手冊步驟 10、12、8.3）：DAILY_MODE=mas 時 06:00 先跑 P 影子、M 再從同一份快照跑。
    # 影子不寫 daily_editions、不發 Telegram；預設關閉，pipeline 模式不看這個旗標。
    daily_shadow_enabled: bool = False
    # P 影子一個太平洋日最多用幾格 LLM 額度（含編輯會議與重試）；M 至少保有 LLM_DAILY_LIMIT 減這個數。
    daily_shadow_llm_limit: int = 12
    # 影子跑完後，盲計稿與抽查稿匯出到這裡的 YYYY-MM-DD/（已 gitignore；對照表在 _private/）
    daily_annotation_dir: str = "annotation"
    gemini_daily_model: str = "gemini-3.5-flash-lite"

    # --- 舊排程（候選探索、舊版日報編採與發送）已在 commit 2d95c07 移除；設 true 也不會復活 ---
    legacy_jobs_enabled: bool = False

    # --- Misc ---
    log_level: str = "INFO"

    @field_validator("daily_writer")
    @classmethod
    def _check_provider(cls, value: str) -> str:
        value = value.strip().lower()
        if value not in LLM_PROVIDERS:
            raise ValueError(f"LLM provider 只允許 {'/'.join(LLM_PROVIDERS)}，不得是 {value!r}")
        return value

    @field_validator("daily_shadow_llm_limit")
    @classmethod
    def _check_shadow_limit(cls, value: int) -> int:
        if value < 1:
            raise ValueError("DAILY_SHADOW_LLM_LIMIT 至少要 1")
        return value

    @field_validator("daily_mode")
    @classmethod
    def _check_mode(cls, value: str) -> str:
        value = value.strip().lower()
        if value not in ("pipeline", "mas"):
            raise ValueError(f"DAILY_MODE 只允許 pipeline / mas：{value!r}")
        return value


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
