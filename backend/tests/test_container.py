import sys
import types

from app.config import Settings
from app.container import ServiceRegistry


def _settings():
    return Settings(_env_file=None, falkordb_host="db.local", falkordb_port=7000, falkordb_graph_name="g1")


def test_missing_repository_is_unavailable_but_integrated_services_load():
    reg = ServiceRegistry(_settings())
    assert reg.get_optional("repository") is None
    assert callable(reg.get_optional("extract_facts"))
    assert callable(reg.get_optional("upsert_memories"))
    assert callable(reg.get_optional("retrieve_memories"))


def test_repository_class_gets_only_accepted_kwargs(monkeypatch):
    mod = types.ModuleType("app.db.falkordb_client")

    class GraphRepository:
        def __init__(self, host, port, graph_name):
            self.args = (host, port, graph_name)

    mod.GraphRepository = GraphRepository
    monkeypatch.setitem(sys.modules, "app.db.falkordb_client", mod)
    repo = ServiceRegistry(_settings()).get("repository")
    assert repo.args == ("db.local", 7000, "g1")


def test_get_repository_factory_preferred(monkeypatch):
    mod = types.ModuleType("app.db.falkordb_client")
    sentinel = object()
    mod.get_repository = lambda: sentinel
    mod.GraphRepository = lambda **kw: None
    monkeypatch.setitem(sys.modules, "app.db.falkordb_client", mod)
    assert ServiceRegistry(_settings()).get("repository") is sentinel


def test_constructor_failure_is_unavailable_and_retried(monkeypatch):
    mod = types.ModuleType("app.db.falkordb_client")
    calls = {"n": 0}

    def factory():
        calls["n"] += 1
        if calls["n"] == 1:
            raise ConnectionError("down")
        return "repo"

    mod.get_repository = factory
    monkeypatch.setitem(sys.modules, "app.db.falkordb_client", mod)
    reg = ServiceRegistry(_settings())
    assert reg.get_optional("repository") is None
    assert reg.get_optional("repository") == "repo"


def test_build_context_falls_back_to_llm_service(monkeypatch):
    llm = types.ModuleType("app.services.llm_service")
    llm.build_context = lambda q, m: None
    monkeypatch.setitem(sys.modules, "app.services.llm_service", llm)
    assert ServiceRegistry(_settings()).get("build_context") is llm.build_context
