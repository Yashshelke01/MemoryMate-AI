import threading

from tests.conftest import DEMO, OTHER
from tests.fakes import make_record

FACT = {
    "content": "Currently learning Python",
    "category": "skill",
    "subject": "Python",
    "normalized_subject": "python",
    "source_quote": "I'm learning Python.",
    "operation_hint": "new",
}


def chat(client, message="I'm learning Python.", user=DEMO, conv=None):
    if getattr(client, "_memorymate_test_user", None) != user:
        email = f"{user}@example.test"
        client.post("/auth/login", json={"email": email, "password": "MemoryMate-test-password-1"})
        client._memorymate_test_user = user
    return client.post("/chat", json={"message": message, "conversation_id": conv})


def test_chat_saves_retrieves_and_returns_real_evidence(client, repo, ai):
    ai.facts_to_extract = [FACT]
    r = chat(client, "I'm learning Python. What should I do?")
    assert r.status_code == 200
    body = r.json()
    assert body["conversation_id"].startswith("conv_")
    assert body["memory_operations"] == {"created": 1, "updated": 0, "superseded": 0}
    assert len(repo.rows) == 1
    saved = next(iter(repo.rows.values()))
    assert saved["user_id"] == DEMO and saved["status"] == "active"
    # Evidence is exactly what was passed to generation, taken from DB records.
    used_ids = [m["memory_id"] for m in body["memories_used"]]
    assert used_ids == ai.generate_calls[0]["memories"] == [saved["memory_id"]]
    assert body["memories_used"][0]["type"] == "skill"


def test_no_memories_returns_empty_evidence(client, ai):
    r = chat(client, "What is my favorite language?")
    assert r.status_code == 200
    assert r.json()["memories_used"] == []
    assert r.json()["memory_operations"] == {"created": 0, "updated": 0, "superseded": 0}
    assert ai.generate_calls[0]["memories"] == []


def test_supplied_conversation_id_is_kept_and_recent_turns_follow(client, ai):
    first = chat(client, "hello").json()
    cid = first["conversation_id"]
    chat(client, "and again", conv=cid)
    assert ai.generate_calls[0]["recent_turns"] == []
    assert [t["role"] for t in ai.generate_calls[1]["recent_turns"]] == ["user", "assistant"]
    # Another user reusing the conversation id gets no one else's history.
    foreign = chat(client, "hi", user=OTHER, conv=cid)
    assert foreign.status_code == 404
    assert len(ai.generate_calls) == 2


def test_extraction_failure_is_503_and_nothing_saved_or_answered(client, repo, ai):
    ai.extract_error = RuntimeError("secret-key-123 provider exploded")
    r = chat(client)
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "extraction_unavailable"
    assert "secret-key-123" not in r.text
    assert repo.rows == {} and ai.generate_calls == []


def test_malformed_extraction_output_is_503(client, ai):
    ai.facts_to_extract = [{"content": "x", "category": "not-a-category", "subject": "y"}]
    r = chat(client)
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "extraction_unavailable"


def test_persistence_failure_is_503_and_no_answer(client, ai):
    ai.facts_to_extract = [FACT]
    ai.upsert_error = RuntimeError("graph down")
    r = chat(client)
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "persistence_unavailable"
    assert ai.generate_calls == []


def test_retrieval_failure_does_not_generate_ungrounded_answer(client, ai):
    ai.retrieve_error = RuntimeError("graph down")
    r = chat(client)
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "retrieval_unavailable"
    assert ai.generate_calls == []


def test_llm_failure_reports_what_was_saved(client, repo, ai):
    ai.facts_to_extract = [FACT]
    ai.llm_error = RuntimeError("provider key sk-live-abc")
    r = chat(client, "I'm learning Python. What should I do?")
    assert r.status_code == 503
    err = r.json()["error"]
    assert err["code"] == "generation_unavailable"
    assert err["details"]["memory_operations"]["created"] == 1
    assert "sk-live-abc" not in r.text
    assert len(repo.rows) == 1


def test_foreign_or_inactive_records_never_reach_llm_or_evidence(client, repo, ai):
    mine = make_record(DEMO)
    foreign = make_record(OTHER, content="Other user's secret")
    stale = make_record(DEMO, status="superseded", content="Old value")
    ai.retrieve_override = [foreign, stale, mine, mine]  # also a duplicate
    r = chat(client)
    assert [m["memory_id"] for m in r.json()["memories_used"]] == [mine["memory_id"]]
    assert ai.generate_calls[0]["memories"] == [mine["memory_id"]]


def test_context_capped_at_ten(client, ai):
    ai.retrieve_override = [make_record(content=f"fact {i}", subject=f"s{i}") for i in range(25)]
    r = chat(client)
    assert len(r.json()["memories_used"]) == 10


def test_evidence_cannot_include_records_not_retrieved(client, ai):
    ai.retrieve_override = [make_record()]
    injected = make_record(content="invented")
    original = ai.build_context
    ai.build_context = lambda q, m: {"question": q, "memories": list(m) + [injected]}
    r = chat(client)
    ids = [m["memory_id"] for m in r.json()["memories_used"]]
    assert injected["memory_id"] not in ids and len(ids) == 1
    ai.build_context = original


def test_chat_rejects_client_supplied_identity(client):
    r = client.post("/chat", json={"user_id": "intruder", "message": "hello"})
    assert r.status_code == 422


def test_validation_errors_are_422_without_echoing_input(client):
    assert client.post("/chat", json={"message": "   "}).status_code == 422
    assert client.post("/chat", json={"message": "x" * 20001}).status_code == 422
    assert client.post("/chat", json={}).status_code == 422
    assert client.post("/chat", json={"message": "hi", "conversation_id": "bad"}).status_code == 422
    assert client.post("/chat", json={"message": "hi", "extra": 1}).status_code == 422
    r = client.post("/chat", json={"user_id": "intruder", "message": "SENSITIVE-TEXT"})
    assert r.status_code == 422 and "SENSITIVE-TEXT" not in r.text
    assert r.json()["error"]["code"] == "validation_error"


def test_message_longer_than_configured_limit_is_400(make_client):
    c = make_client(max_message_chars=10)
    c.post("/auth/login", json={"email": f"{DEMO}@example.test", "password": "MemoryMate-test-password-1"})
    r = c.post("/chat", json={"message": "x" * 11})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "message_too_long"


def test_fact_count_is_capped(make_client, repo, ai):
    ai.facts_to_extract = [{**FACT, "content": f"c{i}", "subject": f"s{i}"} for i in range(30)]
    c = make_client(max_facts_per_message=3)
    r = chat(c)
    assert r.json()["memory_operations"]["created"] == 3
    assert len(repo.rows) == 3


def test_duplicate_submission_does_not_create_duplicates(client, repo, ai):
    ai.facts_to_extract = [FACT]
    results = []

    def go():
        results.append(chat(client).json()["memory_operations"]["created"])

    threads = [threading.Thread(target=go) for _ in range(4)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sum(results) == 1
    assert len(repo.rows) == 1
    assert ai.max_concurrent_upserts == 1  # per-user write path is serialized


def test_chat_timeout_is_503(make_client, ai):
    ai.delay_extract = 0.6
    c = make_client(chat_timeout_seconds=0.1)
    r = chat(c)
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "timeout"


def test_missing_modules_report_503_not_fake_success(settings):
    from fastapi.testclient import TestClient

    from app.main import create_app
    from app.services.auth_service import hash_password

    c = TestClient(
        create_app(
            settings,
            {
                "extract_facts": None,
                "upsert_memories": None,
                "retrieve_memories": None,
                "build_context": None,
                "generate_answer": None,
                "repository": None,
                "llm_is_configured": None,
            },
        ),
        raise_server_exceptions=False,
    )  # deterministic: no actual provider/database modules are wired
    c.app.state.sqlite_store.create_user("demo@example.test", hash_password("MemoryMate-test-password-1"), user_id=DEMO)
    c.post("/auth/login", json={"email": "demo@example.test", "password": "MemoryMate-test-password-1"})
    r = c.post("/chat", json={"message": "hi"})
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "extraction_unavailable"
