from tests.conftest import DEMO, OTHER, TEST_PASSWORD


def test_signup_creates_account_and_http_only_session(make_client):
    client = make_client()
    response = client.post(
        "/auth/signup",
        json={
            "full_name": "New Person",
            "email": "new.person@example.test",
            "mobile_number": "+919876543210",
            "age": 25,
            "password": "a-safe-password-123",
        },
    )
    assert response.status_code == 201
    assert response.json()["email"] == "new.person@example.test"
    assert response.json()["full_name"] == "New Person"
    assert response.json()["mobile_number"] == "+919876543210"
    assert response.json()["age"] == 25
    assert response.json()["user_id"].startswith("usr_")
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie
    assert client.get("/auth/me").json()["user_id"] == response.json()["user_id"]


def test_login_rejects_wrong_credentials(client):
    response = client.post(
        "/auth/login", json={"email": f"{DEMO}@example.test", "password": "incorrect"}
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_credentials"


def test_signup_validates_profile_and_phone_number(make_client):
    client = make_client()
    valid = {
        "full_name": "A Valid Name",
        "email": "valid.person@example.test",
        "mobile_number": "+919876543210",
        "age": 25,
        "password": "a-safe-password-123",
    }
    for changes in (
        {"full_name": "A1"},
        {"mobile_number": "+9100"},
        {"age": 12},
        {"age": 121},
    ):
        response = client.post("/auth/signup", json={**valid, **changes})
        assert response.status_code == 422


def test_signup_allows_shared_mobile_and_login_uses_email_only(make_client):
    client = make_client()
    details = {
        "full_name": "Phone Login User",
        "email": "phone.login@example.test",
        "mobile_number": "+919876543210",
        "age": 28,
        "password": "a-safe-password-123",
    }
    created = client.post("/auth/signup", json=details)
    assert created.status_code == 201
    assert created.json()["full_name"] == details["full_name"]
    assert created.json()["mobile_number"] == details["mobile_number"]
    assert created.json()["age"] == details["age"]

    client.post("/auth/logout")
    logged_in = client.post(
        "/auth/login",
        json={"email": details["email"], "password": details["password"]},
    )
    assert logged_in.status_code == 200
    assert logged_in.json()["user_id"] == created.json()["user_id"]

    shared_mobile = client.post(
        "/auth/signup",
        json={**details, "email": "another.person@example.test"},
    )
    assert shared_mobile.status_code == 201
    assert shared_mobile.json()["user_id"] != created.json()["user_id"]
    assert shared_mobile.json()["mobile_number"] == details["mobile_number"]

    duplicate_email = client.post(
        "/auth/signup",
        json={**details, "mobile_number": "+14155550123"},
    )
    assert duplicate_email.status_code == 409
    assert duplicate_email.json()["error"]["code"] == "account_exists"

    phone_login = client.post(
        "/auth/login",
        json={"email": details["mobile_number"], "password": details["password"]},
    )
    assert phone_login.status_code == 422


def test_protected_routes_require_session(make_client):
    client = make_client()
    client.post("/auth/logout")
    assert client.get("/auth/me").status_code == 401
    assert client.post("/chat", json={"message": "hello"}).status_code == 401
    assert client.get(f"/memories/{DEMO}").status_code == 401


def test_conversation_history_survives_new_chat_and_is_user_scoped(client, ai):
    response = client.post("/chat", json={"message": "What should I do?"})
    assert response.status_code == 200
    conversation_id = response.json()["conversation_id"]

    listed = client.get("/conversations").json()["items"]
    assert len(listed) == 1
    assert listed[0]["conversation_id"] == conversation_id
    assert listed[0]["message_count"] == 2

    detail = client.get(f"/conversations/{conversation_id}").json()
    assert [item["role"] for item in detail["messages"]] == ["user", "assistant"]
    assert detail["messages"][0]["content"] == "What should I do?"

    client.post("/auth/login", json={"email": f"{OTHER}@example.test", "password": TEST_PASSWORD})
    assert client.get(f"/conversations/{conversation_id}").status_code == 404
    assert client.get("/conversations").json()["items"] == []

    assert client.delete(f"/conversations/{conversation_id}").status_code == 404
    client.post("/auth/login", json={"email": f"{DEMO}@example.test", "password": TEST_PASSWORD})
    assert client.delete(f"/conversations/{conversation_id}").status_code == 204
    assert client.delete(f"/conversations/{conversation_id}").status_code == 404
    assert client.get("/conversations").json()["items"] == []

