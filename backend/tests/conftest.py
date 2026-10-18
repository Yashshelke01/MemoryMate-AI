import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.services.auth_service import hash_password
from tests.fakes import FakeAI, FakeRepository

DEMO = "demo-user-1"
OTHER = "demo-user-2"
TEST_PASSWORD = "MemoryMate-test-password-1"
TEST_PASSWORD_HASH = hash_password(TEST_PASSWORD)


@pytest.fixture
def repo() -> FakeRepository:
    return FakeRepository()


@pytest.fixture
def ai(repo) -> FakeAI:
    return FakeAI(repo)


@pytest.fixture
def settings() -> Settings:
    return Settings(_env_file=None, sqlite_db_path=":memory:", chat_timeout_seconds=5)


@pytest.fixture
def make_client(settings, repo, ai):
    def _make(**setting_overrides):
        values = {"sqlite_db_path": ":memory:", **setting_overrides}
        s = settings.model_copy(update=values)
        app = create_app(s, ai.overrides(repo))
        client = TestClient(app, raise_server_exceptions=False)
        app.state.sqlite_store.create_user(f"{DEMO}@example.test", TEST_PASSWORD_HASH, user_id=DEMO)
        app.state.sqlite_store.create_user(f"{OTHER}@example.test", TEST_PASSWORD_HASH, user_id=OTHER)
        client.post("/auth/login", json={"email": f"{DEMO}@example.test", "password": TEST_PASSWORD})
        client._memorymate_test_user = DEMO
        return client

    return _make


@pytest.fixture
def client(make_client) -> TestClient:
    return make_client()
