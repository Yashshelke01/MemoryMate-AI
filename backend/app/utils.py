from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from functools import partial
from typing import Any, Callable, TypeVar

import anyio

from app.errors import AppError

T = TypeVar("T")

_WS_RE = re.compile(r"\s+")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4()}"


def normalize_subject(subject: str) -> str:
    """Lowercased, whitespace-normalized matching key."""
    return _WS_RE.sub(" ", subject.strip()).lower()


async def run_blocking(
    fn: Callable[..., T], *args: Any, timeout: float, on_timeout: AppError, **kwargs: Any
) -> T:
    """Run a blocking callable in a worker thread with a deadline.

    The thread cannot be killed on timeout, so callers must treat a timeout as
    "outcome unknown" for writes.
    """
    try:
        with anyio.fail_after(timeout):
            return await anyio.to_thread.run_sync(
                partial(fn, *args, **kwargs), abandon_on_cancel=True
            )
    except TimeoutError:
        raise on_timeout from None
