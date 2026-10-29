"""回歸集 fixtures：10/27 刊出版與離線重編版（整個 session 只重編一次）。"""

from __future__ import annotations

import pytest

from .checks import referenced_titles
from .rebuild import load_cases, published_view, rebuild_view


@pytest.fixture(scope="session")
def published():
    return published_view()


@pytest.fixture(scope="session")
def rebuilt(tmp_path_factory):
    needed = {t for case in load_cases() for t in referenced_titles(case)}
    return rebuild_view(tmp_path_factory.mktemp("rebuild_1027"), needed)
