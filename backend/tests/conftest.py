import os
import pytest
from fastapi.testclient import TestClient

os.environ["DATABASE_URL"] = os.getenv(
    "TEST_DATABASE_URL", "sqlite:///./test_dataguard.db"
)
if "test" not in os.environ["DATABASE_URL"].split("/")[-1]:
    raise RuntimeError("Tests require a dedicated database with test in its name")
from app.db import engine, Session
from app.models import Base, User
from app.auth import passwords, token
from app.main import app


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    monkeypatch.setattr("app.main.enqueue", lambda run_id: None)
    yield
    Base.metadata.drop_all(engine)


@pytest.fixture
def users():
    with Session.begin() as db:
        a = User(email="a@test.local", password=passwords.hash("password"))
        b = User(email="b@test.local", password=passwords.hash("password"))
        db.add_all([a, b])
        db.flush()
        return a, b


@pytest.fixture
def client(users):
    with TestClient(app) as c:
        c.headers.update({"Authorization": "Bearer " + token(users[0])})
        yield c
