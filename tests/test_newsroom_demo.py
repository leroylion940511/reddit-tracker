"""End-to-end offline demo test: seed → plan → evidence → draft → render."""

from __future__ import annotations

from reddit_tracker.newsroom.demo import run_demo


def test_run_demo_writes_an_inspectable_newsroom_html_and_isolated_db(tmp_path):
    output = tmp_path / "daily-paper.html"

    result = run_demo(output_path=output)

    html = output.read_text(encoding="utf-8")
    assert result.item_count == 8
    assert result.artifact_count == 6
    assert result.database_path.exists()
    assert "AI 編輯室每日報" in html
    assert "工作裡最難談的，往往不是工作" in html
    assert "讀者檔案 agent" in html
    assert "脈絡查核 agent" in html
    assert "https://www.reddit.com/r/" in html
    assert "❤️ 多看這類" in result.telegram_preview


def test_demo_refuses_to_overwrite_existing_outputs(tmp_path):
    output = tmp_path / "daily-paper.html"
    output.write_text("existing", encoding="utf-8")

    try:
        run_demo(output_path=output)
    except FileExistsError as exc:
        assert "refusing to overwrite" in str(exc)
    else:  # pragma: no cover - test guard
        raise AssertionError("expected FileExistsError")
