from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from rssx.app import create_app
from rssx.config import Config
from rssx.db import connect, init_schema


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "rssx-test.db"


@pytest.fixture
def client(db_path: Path) -> Iterator[TestClient]:
    app = create_app(Config(db_path=db_path), run_startup_fetch=False)
    with TestClient(app) as c:
        yield c


def init_test_db(db_path: Path) -> None:
    conn = connect(db_path)
    try:
        init_schema(conn)
    finally:
        conn.close()
