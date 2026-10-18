"""Application configuration (environment variables / .env).

Other modules (graph, extraction, LLM) should read their settings from
``get_settings()`` so there is a single source of configuration.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_DEFAULT_CORS = (
    "http://localhost:3000,http://127.0.0.1:3000,"
    "http://localhost:5500,http://127.0.0.1:5500,"
    "http://localhost:8080,http://127.0.0.1:8080"
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    app_name: str = "MemoryMate AI"
    environment: str = "development"
    log_level: str = "INFO"

    # --- Accounts and sessions -----------------------------------------------
    sqlite_db_path: str = "./memorymate.sqlite3"
    session_cookie_name: str = "memorymate_session"
    session_ttl_seconds: int = Field(default=1209600, ge=300, le=2592000)
    session_cookie_secure: bool = False

    # --- CORS -----------------------------------------------------------------
    cors_origins: str = _DEFAULT_CORS

    # --- FalkorDB (consumed by db/falkordb_client.py) ---------------------------
    falkordb_host: str = "localhost"
    falkordb_port: int = 6379
    falkordb_password: SecretStr | None = None
    falkordb_graph_name: str = "memorymate"
    falkordb_socket_timeout_seconds: float = 5.0

    # --- LLM (consumed by services/llm_service.py + memory_extractor.py) --------
    llm_provider: str = "anthropic"
    llm_model: str = ""
    llm_api_key: SecretStr | None = None
    # Optional server-side endpoint override for private gateways/emulators.
    llm_base_url: str = ""
    llm_timeout_seconds: float = 120.0

    # --- Limits & timeouts ------------------------------------------------------
    max_message_chars: int = Field(default=4000, ge=1, le=20000)
    max_facts_per_message: int = Field(default=10, ge=1, le=50)
    max_context_memories: int = Field(default=10, ge=1, le=50)
    recent_turns_max: int = Field(default=6, ge=0, le=20)
    graph_max_nodes: int = Field(default=200, ge=1, le=1000)
    # A chat performs extraction and answer generation sequentially. Leave
    # enough time for both provider requests when a remote model is slow.
    chat_timeout_seconds: float = Field(default=300.0, gt=0)
    request_timeout_seconds: float = Field(default=15.0, gt=0)
    health_timeout_seconds: float = Field(default=3.0, gt=0)

    @field_validator("cors_origins")
    @classmethod
    def _no_wildcard_cors(cls, v: str) -> str:
        if "*" in v:
            raise ValueError("CORS_ORIGINS must list explicit origins; '*' is not allowed")
        return v

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def llm_configured(self) -> bool:
        return bool(self.llm_api_key and self.llm_api_key.get_secret_value().strip())


@lru_cache
def get_settings() -> Settings:
    return Settings()
