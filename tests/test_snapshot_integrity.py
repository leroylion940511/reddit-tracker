"""母本 `data/snapshots/2026-10-27.db` 沒被改過（手冊步驟 3 做完的標準）；母本不在本機就 skip。"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "data/snapshots/2026-10-27.db"
CHECKSUM = SNAPSHOT.with_name(SNAPSHOT.name + ".sha256")


@pytest.mark.skipif(not SNAPSHOT.exists() or not CHECKSUM.exists(), reason="母本不在本機")
def test_snapshot_sha256_matches_recorded_checksum():
    expected, name = CHECKSUM.read_text(encoding="utf-8").split()[:2]
    assert Path(name).name == SNAPSHOT.name
    digest = hashlib.sha256()
    with SNAPSHOT.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    assert digest.hexdigest() == expected
