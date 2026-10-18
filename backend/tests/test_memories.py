from tests.conftest import DEMO, OTHER
from tests.fakes import make_record


def add(repo, **kw):
    rec = make_record(**kw)
    repo.rows[rec["memory_id"]] = rec
    return rec


def delete(client, memory_id, user=DEMO):
    if getattr(client, "_memorymate_test_user", None) != user:
        client.post("/auth/login", json={"email": f"{user}@example.test", "password": "MemoryMate-test-password-1"})
        client._memorymate_test_user = user
    return client.request("DELETE", f"/memories/{memory_id}", json={})


def patch(client, memory_id, user=DEMO, **fields):
    if getattr(client, "_memorymate_test_user", None) != user:
        client.post("/auth/login", json={"email": f"{user}@example.test", "password": "MemoryMate-test-password-1"})
        client._memorymate_test_user = user
    return client.patch(f"/memories/{memory_id}", json=fields)


def test_list_shape_pagination_and_active_only(client, repo):
    a = add(repo, content="A", subject="a", updated_at="2020-01-01T00:00:00Z")
    b = add(repo, content="B", subject="b", updated_at="2026-10-17T11:00:00Z")
    add(repo, content="old", subject="c", status="superseded")
    r = client.get(f"/memories/{DEMO}")
    body = r.json()
    assert r.status_code == 200
    assert (body["limit"], body["offset"], body["total"]) == (50, 0, 2)
    assert [i["memory_id"] for i in body["items"]] == [b["memory_id"], a["memory_id"]]
    item = body["items"][0]
    assert set(item) == {"memory_id", "user_id", "content", "category", "subject",
                         "created_at", "updated_at", "provenance"}
    assert set(item["provenance"]) == {"kind", "source_message_id", "supersedes_memory_id"}
    page = client.get(f"/memories/{DEMO}?limit=1&offset=1").json()
    assert [i["memory_id"] for i in page["items"]] == [a["memory_id"]] and page["total"] == 2


def test_list_empty_and_bad_params(client):
    assert client.get(f"/memories/{DEMO}").json()["items"] == []
    assert client.get(f"/memories/{DEMO}?limit=0").status_code == 422
    assert client.get(f"/memories/{DEMO}?limit=101").status_code == 422
    assert client.get(f"/memories/{DEMO}?offset=-1").status_code == 422


def test_isolation_between_users(client, repo):
    mine = add(repo, user_id=DEMO)
    assert client.get(f"/memories/{OTHER}").status_code == 404
    assert client.get(f"/memories/intruder").status_code == 404
    assert patch(client, mine["memory_id"], user=OTHER, content="hacked").status_code == 404
    assert delete(client, mine["memory_id"], user=OTHER).status_code == 404
    assert repo.rows[mine["memory_id"]]["content"] == "Currently learning Python"


def test_patch_updates_preserving_created_at_and_provenance(client, repo):
    rec = add(repo, content="Can study one hour each day", category="commitment",
              subject="Daily Study Availability", updated_at="2020-01-01T00:00:00Z")
    r = patch(client, rec["memory_id"], content="Can study two hours each day")
    assert r.status_code == 200
    m = r.json()["memory"]
    assert set(m) == {"memory_id", "user_id", "content", "category", "subject", "updated_at"}
    assert m["content"] == "Can study two hours each day"
    assert m["category"] == "commitment" and m["subject"] == "Daily Study Availability"
    assert m["updated_at"] > "2020-01-01T00:00:00Z"
    stored = repo.rows[rec["memory_id"]]
    assert stored["created_at"] == rec["created_at"] and stored["provenance"] == rec["provenance"]


def test_patch_changes_category_and_subject_and_normalizes(client, repo):
    rec = add(repo)
    r = patch(client, rec["memory_id"], category="goal", subject="  Build   AI Project ")
    assert r.status_code == 200
    stored = repo.rows[rec["memory_id"]]
    assert stored["category"] == "goal" and stored["normalized_subject"] == "build ai project"


def test_patch_validation(client, repo):
    rec = add(repo)
    assert patch(client, rec["memory_id"]).status_code == 422  # nothing to change
    assert patch(client, rec["memory_id"], category="nope").status_code == 422
    assert patch(client, rec["memory_id"], content="x" * 501).status_code == 422
    assert patch(client, rec["memory_id"], content="  ").status_code == 422
    assert patch(client, "not-a-memory-id", content="x").status_code == 422


def test_patch_and_delete_missing_and_foreign_are_indistinguishable(client, repo):
    foreign = add(repo, user_id=OTHER)
    missing = "mem_00000000-0000-0000-0000-000000000000"
    a = patch(client, missing, content="x")
    b = patch(client, foreign["memory_id"], content="x")
    assert a.status_code == b.status_code == 404 and a.json() == b.json()
    c = delete(client, missing)
    d = delete(client, foreign["memory_id"])
    assert c.status_code == d.status_code == 404 and c.json() == d.json()
    assert a.json()["error"]["code"] == "memory_not_found"


def test_patch_superseded_record_is_404(client, repo):
    rec = add(repo, status="superseded")
    assert patch(client, rec["memory_id"], content="x").status_code == 404


def test_delete_removes_from_list_and_retrieval(client, repo, ai):
    rec = add(repo, content="Currently learning Python")
    r = delete(client, rec["memory_id"])
    assert r.status_code == 200 and r.json() == {"deleted": True, "memory_id": rec["memory_id"]}
    assert client.get(f"/memories/{DEMO}").json()["total"] == 0
    client.post("/auth/login", json={"email": f"{DEMO}@example.test", "password": "MemoryMate-test-password-1"})
    chat = client.post("/chat", json={"message": "python?"}).json()
    assert chat["memories_used"] == []
    assert delete(client, rec["memory_id"]).status_code == 404  # already gone


def test_repository_failure_is_503_and_not_leaked(client, repo):
    rec = add(repo)
    repo.fail_with = RuntimeError("Cypher error MATCH (n) password=hunter2")
    for r in (
        client.get(f"/memories/{DEMO}"),
        patch(client, rec["memory_id"], content="x"),
        delete(client, rec["memory_id"]),
        client.get(f"/graph/{DEMO}"),
    ):
        assert r.status_code == 503
        assert r.json()["error"]["code"] == "database_unavailable"
        assert "hunter2" not in r.text and "Cypher" not in r.text


def test_malformed_repository_record_is_503(client, repo):
    repo.rows["mem_x"] = {"memory_id": "mem_x", "user_id": DEMO}
    r = client.get(f"/memories/{DEMO}")
    assert r.status_code == 503
