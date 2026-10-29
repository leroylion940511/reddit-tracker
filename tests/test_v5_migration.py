"""Alembic migration integration test against a disposable SQLite database."""

from __future__ import annotations

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from reddit_tracker.config import get_settings


def test_v5_newsroom_migration_up_and_down(tmp_path, monkeypatch):
    database_path = tmp_path / "newsroom-migration.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    get_settings.cache_clear()
    config = Config("alembic.ini")
    try:
        command.upgrade(config, "head")
        engine = create_engine(f"sqlite:///{database_path}")
        try:
            tables = set(inspect(engine).get_table_names())
            assert {
                "reader_profiles",
                "newsroom_editions",
                "edition_items",
                "edition_item_sources",
                "agent_runs",
                "agent_artifacts",
                "agent_artifact_sources",
                "reader_feedback",
            } <= tables
            reader_columns = {column["name"] for column in inspect(engine).get_columns("reader_profiles")}
            assert {"included_keywords", "excluded_keywords"} <= reader_columns
            assert {"source_items", "source_fetch_runs", "story_clusters", "daily_editions", "daily_articles"} <= tables
            assert {
                "daily_snapshots", "stories", "agent_messages", "story_versions", "page_plans",
            } <= tables
            record_columns = {column["name"] for column in inspect(engine).get_columns("llm_records")}
            assert {
                "request_hash", "prompt_text", "response_text", "latency_ms", "ok", "error",
                "role", "run_variant", "edition_date", "story_id", "model_version",
            } <= record_columns
            item_columns = {column["name"] for column in inspect(engine).get_columns("source_items")}
            assert "cluster_id" in item_columns
        finally:
            engine.dispose()

        command.downgrade(config, "7778060d74e7")
        engine = create_engine(f"sqlite:///{database_path}")
        try:
            names = set(inspect(engine).get_table_names())
            assert "reader_profiles" not in names
            assert "stories" not in names and "page_plans" not in names
            assert "candidate_posts" in names
        finally:
            engine.dispose()
    finally:
        get_settings.cache_clear()


def test_mas_migration_preserves_old_and_partially_recorded_tables(tmp_path, monkeypatch):
    """The snapshot's legacy row and the step-3 recorder's added columns both survive."""
    from sqlalchemy import text

    for partial in (False, True):
        path = tmp_path / f"legacy-{partial}.db"
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{path}")
        get_settings.cache_clear()
        cfg = Config("alembic.ini")
        command.upgrade(cfg, "a6c9e2f31d84")
        engine = create_engine(f"sqlite:///{path}")
        with engine.begin() as c:
            c.execute(text("INSERT INTO llm_records(provider,model,purpose) VALUES ('gemini','old','daily')"))
            if partial:
                c.execute(text("ALTER TABLE llm_records ADD COLUMN request_hash VARCHAR(64)"))
                c.execute(text("ALTER TABLE llm_records ADD COLUMN response_text TEXT"))
                c.execute(text("CREATE INDEX ix_llm_records_request_hash ON llm_records(request_hash)"))
                c.execute(text("UPDATE llm_records SET request_hash='saved', response_text='keep me'"))
        command.upgrade(cfg, "head")
        with engine.connect() as c:
            row = c.execute(text("SELECT model,request_hash,response_text FROM llm_records")).one()
            assert row == ("old", "saved" if partial else None, "keep me" if partial else None)
        command.downgrade(cfg, "a6c9e2f31d84")
        with engine.connect() as c:
            assert c.execute(text("SELECT model FROM llm_records")).scalar_one() == "old"
        engine.dispose()
    get_settings.cache_clear()
