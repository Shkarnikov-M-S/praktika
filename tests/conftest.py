import pytest

from database import Database


@pytest.fixture(params=["sqlite", "tinydb"])
def db(request, tmp_path):
    filename = "test.db" if request.param == "sqlite" else "test.json"
    database = Database(request.param, tmp_path / filename, seed=False)
    yield database
    database.close()
