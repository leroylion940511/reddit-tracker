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
            assert {"source_items", "source_fetch_runs"} <= tables
        finally:
            engine.dispose()

        command.downgrade(config, "7778060d74e7")
        engine = create_engine(f"sqlite:///{database_path}")
        try:
            assert "reader_profiles" not in inspect(engine).get_table_names()
            assert "candidate_posts" in inspect(engine).get_table_names()
        finally:
            engine.dispose()
    finally:
        get_settings.cache_clear()
