"""HTTP request/response models (PROJECT_CONTRACT.md section 4)."""

from __future__ import annotations

import re
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

from app.models.contracts import MemoryCategory

USER_ID_PATTERN = r"^[A-Za-z0-9_.\-]{1,64}$"
MEMORY_ID_PATTERN = r"^mem_[A-Za-z0-9\-]{1,64}$"
CONVERSATION_ID_PATTERN = r"^conv_[A-Za-z0-9\-]{1,64}$"

UserId = Annotated[str, StringConstraints(pattern=USER_ID_PATTERN)]
ConversationId = Annotated[str, StringConstraints(pattern=CONVERSATION_ID_PATTERN)]

_STRICT = ConfigDict(extra="forbid")


# ----- chat -------------------------------------------------------------------
class ChatRequest(BaseModel):
    model_config = _STRICT

    user_id: UserId
    # Upper bound is also enforced from settings in the service layer.
    message: str = Field(min_length=1, max_length=20000)
    conversation_id: ConversationId | None = None

    @field_validator("message")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("message must not be blank")
        return v


class ChatInput(BaseModel):
    """Public request deliberately omits user_id; auth supplies it server-side."""
    model_config = _STRICT
    message: str = Field(min_length=1, max_length=20000)
    conversation_id: ConversationId | None = None

    @field_validator("message")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("message must not be blank")
        return v


class SignupRequest(BaseModel):
    model_config = _STRICT
    full_name: str = Field(min_length=2, max_length=100)
    email: str = Field(min_length=3, max_length=254)
    mobile_number: str = Field(min_length=8, max_length=16)
    age: int = Field(ge=13, le=120)
    password: str = Field(min_length=10, max_length=128)

    @field_validator("full_name")
    @classmethod
    def _normalize_full_name(cls, value: str) -> str:
        value = " ".join(value.split())
        letters = [char for char in value if char.isalpha()]
        if len(letters) < 2 or any(
            not (char.isalpha() or char in " -.'’") for char in value
        ):
            raise ValueError("Enter a valid full name using letters, spaces, apostrophes, periods, or hyphens.")
        return value

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, value: str) -> str:
        value = value.strip().lower()
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
            raise ValueError("Enter a valid email address.")
        return value

    @field_validator("mobile_number")
    @classmethod
    def _normalize_mobile_number(cls, value: str) -> str:
        value = re.sub(r"[\s().-]", "", value)
        if not re.fullmatch(r"\+[1-9]\d{6,14}", value):
            raise ValueError("Enter a valid international mobile number with its country code.")
        return value


class LoginRequest(BaseModel):
    model_config = _STRICT
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=128)

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, value: str) -> str:
        value = value.strip().lower()
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
            raise ValueError("Enter a valid email address.")
        return value


class UserResponse(BaseModel):
    user_id: str
    email: str
    full_name: str = ""
    mobile_number: str | None = None
    age: int | None = None
    created_at: str


class ConversationSummary(BaseModel):
    conversation_id: ConversationId
    title: str
    created_at: str
    updated_at: str
    message_count: int


class ConversationListResponse(BaseModel):
    items: list[ConversationSummary]


class ConversationMessage(BaseModel):
    message_id: str
    role: str
    content: str
    created_at: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class ConversationResponse(BaseModel):
    conversation_id: ConversationId
    title: str
    created_at: str
    updated_at: str
    messages: list[ConversationMessage]


class MemoryUsed(BaseModel):
    memory_id: str
    content: str
    type: MemoryCategory
    subject: str
    updated_at: str
    relationship: str | None = None


class MemoryOperations(BaseModel):
    created: int = 0
    updated: int = 0
    superseded: int = 0


class ChatResponse(BaseModel):
    conversation_id: str
    answer: str
    memories_used: list[MemoryUsed]
    memory_operations: MemoryOperations


# ----- memories ---------------------------------------------------------------
class PublicProvenance(BaseModel):
    kind: str = "user_statement"
    source_message_id: str | None = None
    supersedes_memory_id: str | None = None


class MemoryItem(BaseModel):
    memory_id: str
    user_id: str
    content: str
    category: MemoryCategory
    subject: str
    created_at: str
    updated_at: str
    provenance: PublicProvenance


class MemoryListResponse(BaseModel):
    items: list[MemoryItem]
    limit: int
    offset: int
    total: int


class MemoryPatchFields(BaseModel):
    model_config = _STRICT

    content: str | None = Field(default=None, min_length=1, max_length=500)
    category: MemoryCategory | None = None
    subject: str | None = Field(default=None, min_length=1, max_length=200)

    @field_validator("content", "subject")
    @classmethod
    def _strip(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.strip()
        if not v:
            raise ValueError("must not be blank")
        return v

    @model_validator(mode="after")
    def _at_least_one(self) -> "MemoryPatchRequest":
        if self.content is None and self.category is None and self.subject is None:
            raise ValueError("at least one of content, category, subject is required")
        return self


class MemoryPatchRequest(MemoryPatchFields):
    user_id: UserId


class MemoryPatchInput(MemoryPatchFields):
    pass


class MemoryPatched(BaseModel):
    memory_id: str
    user_id: str
    content: str
    category: MemoryCategory
    subject: str
    updated_at: str


class MemoryPatchResponse(BaseModel):
    memory: MemoryPatched


class MemoryDeleteRequest(BaseModel):
    model_config = _STRICT

    user_id: UserId


class MemoryDeleteInput(BaseModel):
    model_config = _STRICT


class MemoryDeleteResponse(BaseModel):
    deleted: bool
    memory_id: str


# ----- graph ------------------------------------------------------------------
class GraphNode(BaseModel):
    id: str
    label: str
    type: str


class GraphEdge(BaseModel):
    source: str
    target: str
    type: str


class GraphResponse(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]


# ----- health -----------------------------------------------------------------
class HealthResponse(BaseModel):
    status: str
    dependencies: dict[str, str]
