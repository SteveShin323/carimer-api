"""Phase 0 scaffolding checks: the package imports and async tests really execute."""

from __future__ import annotations

import asyncio

import carimer


def test_package_imports() -> None:
    assert carimer.__version__


async def test_async_tests_actually_run() -> None:
    """Guards ``asyncio_mode = "auto"``.

    Without it an ``async def`` test is collected, skipped with a warning and reported
    as passing, which would make every later live async test a silent no-op.
    """
    await asyncio.sleep(0)
    marker = []
    await asyncio.gather(asyncio.sleep(0), asyncio.to_thread(marker.append, 1))
    assert marker == [1]
