"""
Shared persistent event loop for all Celery tasks.

Every task module MUST use ``run_async()`` from here instead of creating
its own ``asyncio.new_event_loop()``.  A single loop guarantees that
pooled asyncpg connections (which are bound to the loop that created them)
stay valid across all task invocations.
"""

import asyncio
from typing import TypeVar

_T = TypeVar("_T")

_task_loop: asyncio.AbstractEventLoop | None = None


def run_async(coro) -> _T:  # type: ignore[type-var]
    """Run *coro* on the worker-wide event loop (created once, reused)."""
    global _task_loop
    if _task_loop is None or _task_loop.is_closed():
        _task_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(_task_loop)
    return _task_loop.run_until_complete(coro)
