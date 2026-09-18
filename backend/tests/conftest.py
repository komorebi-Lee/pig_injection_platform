"""pytest 公共配置。

约定：
- 纯逻辑测试（arm_gateway / schemas）不需要数据库，永远运行；
- 涉及数据库的测试需要 PostgreSQL 可达，否则自动 skip 而不是报错，
  这样队友在没有起数据库时也能跑 `uv run pytest`。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def _database_available() -> bool:
    try:
        from sqlalchemy import text

        from app.db import engine

        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


@pytest.fixture(scope="session")
def db_available() -> bool:
    return _database_available()


@pytest.fixture()
def require_db(db_available: bool) -> None:
    if not db_available:
        pytest.skip("PostgreSQL 不可达，跳过数据库相关测试")
