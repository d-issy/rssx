from pathlib import Path

import pytest

from rssx.db import connect, init_schema


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "rssx-test.db"


def init_test_db(db_path: Path) -> None:
    conn = connect(db_path)
    try:
        init_schema(conn)
    finally:
        conn.close()
