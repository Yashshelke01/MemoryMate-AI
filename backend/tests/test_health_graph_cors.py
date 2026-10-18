import pytest

from app.config import Settings
from tests.conftest import DEMO, OTHER
from tests.fakes import make_record


def test_health_ok(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "dependencies": {"falkordb": "ok", "llm": "configured"}}


def test_health_reports_falkordb_down(client, repo):
    repo.healthy = False
    d = client.get("/health").json()
    assert d["dependencies"]["falkordb"] == "unavailable" and d["status"] == "degraded"
    repo.healthy = True
    repo.fail_with = RuntimeError("boom secret")
    r = client.get("/health")
    assert r.json()["dependencies"]["falkordb"] == "unavailable" and "secret" not in r.text


def test_health_with_nothing_wired(settings):
    from fastapi.testclient import TestClient

    from app.main import create_app

    isolated = settings.model_copy(update={"llm_api_key": None})
    d = TestClient(create_app(isolated, {"repository": None, "llm_is_configured": None})).get("/health").json()
    assert d["dependencies"] == {"falkordb": "unavailable", "llm": "not_configured"}


def test_graph_nodes_and_edges(client, repo):
    a = make_record(content="Currently learning Python")
    b = make_record(content="Wants to build an AI project", category="goal", subject="AI project")
    c = make_record(user_id=OTHER, content="not mine")
    for r in (a, b, c):
        repo.rows[r["memory_id"]] = r
    repo.relationships = [
        {"source": a["memory_id"], "target": b["memory_id"]},
        {"source": a["memory_id"], "target": c["memory_id"]},  # cross-user edge must be ignored
    ]
    g = client.get(f"/graph/{DEMO}").json()
    ids = {n["id"] for n in g["nodes"]}
    assert ids == {f"user:{DEMO}", a["memory_id"], b["memory_id"]}
    has = [e for e in g["edges"] if e["type"] == "HAS_MEMORY"]
    assert {e["target"] for e in has} == {a["memory_id"], b["memory_id"]}
    rel = [e for e in g["edges"] if e["type"] == "RELATED_TO"]
    assert rel == [{"source": a["memory_id"], "target": b["memory_id"], "type": "RELATED_TO"}]
    assert all(e["source"] in ids and e["target"] in ids for e in g["edges"])
    assert client.get("/graph/intruder").status_code == 404


def test_cors_allows_configured_origin_only(client):
    ok = client.options("/chat", headers={"Origin": "http://localhost:5500",
                                          "Access-Control-Request-Method": "POST",
                                          "Access-Control-Request-Headers": "content-type"})
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:5500"
    bad = client.options("/chat", headers={"Origin": "http://evil.example",
                                           "Access-Control-Request-Method": "POST"})
    assert "access-control-allow-origin" not in bad.headers


def test_wildcard_cors_rejected():
    with pytest.raises(ValueError):
        Settings(_env_file=None, cors_origins="*")


def test_unknown_route_uses_stable_error_shape(client):
    r = client.get("/nope")
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"
