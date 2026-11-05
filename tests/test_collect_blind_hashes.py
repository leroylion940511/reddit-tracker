"""scripts/collect_blind_hashes.py：只讀當天資料夾的 mapping.sha256，--write 才寫檔。"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

H1 = "a" * 64
H2 = "b" * 64


def _module():
    spec = importlib.util.spec_from_file_location("collect_blind_hashes", Path("scripts/collect_blind_hashes.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _day(root: Path, name: str, digest: str) -> None:
    (root / name).mkdir(parents=True)
    (root / name / "mapping.sha256").write_text(digest + "\n", encoding="utf-8")


@pytest.fixture
def root(tmp_path):
    root = tmp_path / "annotation"
    _day(root, "2026-11-09", H1)
    (root / "2026-11-10").mkdir()
    (root / "2026-11-10" / "README.txt").write_text("0 篇\n", encoding="utf-8")
    _day(root, "2026-11-11", H2)
    # 對照表本體放 _private；腳本不能讀它
    (root / "_private" / "2026-11-09").mkdir(parents=True)
    (root / "_private" / "2026-11-09" / "mapping.json").write_text("{}", encoding="utf-8")
    return root


def test_prints_without_write(root, tmp_path, capsys):
    out = tmp_path / "docs" / "blind_mapping.sha256"
    assert _module().main(["--start", "2026-11-09", "--end", "2026-11-11", "--root", str(root), "--out", str(out)]) == 0
    captured = capsys.readouterr()
    assert captured.out == f"2026-11-09  {H1}\n2026-11-11  {H2}\n"
    assert "2026-11-10" in captured.err
    assert not out.exists()


def test_write_appends_and_skips_known_days(root, tmp_path):
    module = _module()
    out = tmp_path / "docs" / "blind_mapping.sha256"
    args = ["--root", str(root), "--out", str(out), "--write"]
    module.main(["--start", "2026-11-09", "--end", "2026-11-09", *args])
    assert out.read_text(encoding="utf-8") == f"2026-11-09  {H1}\n"
    module.main(["--start", "2026-11-09", "--end", "2026-11-11", *args])
    assert out.read_text(encoding="utf-8") == f"2026-11-09  {H1}\n2026-11-11  {H2}\n"


def test_changed_hash_for_recorded_day_stops(root, tmp_path):
    out = tmp_path / "blind_mapping.sha256"
    out.write_text(f"2026-11-09  {H2}\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="人工確認"):
        _module().main(["--start", "2026-11-09", "--end", "2026-11-09", "--root", str(root), "--out", str(out), "--write"])
    assert out.read_text(encoding="utf-8") == f"2026-11-09  {H2}\n"


def test_rejects_private_root_and_bad_hash(root):
    module = _module()
    with pytest.raises(SystemExit, match="_private"):
        module.main(["--start", "2026-11-09", "--end", "2026-11-09", "--root", str(root / "_private")])
    (root / "2026-11-11" / "mapping.sha256").write_text("not-a-hash\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="SHA-256"):
        module.main(["--start", "2026-11-11", "--end", "2026-11-11", "--root", str(root)])
