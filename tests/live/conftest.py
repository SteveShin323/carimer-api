"""Live-test fixtures. Every request here hits the real api.mercari.jp.

Budget: ≤20 calls per phase, ≤70 in total including the scenario suite, ≥0.5 s
apart. The transport default already paces at 0.6 s here and keeps
concurrency at 1.

The two constants below are the budget; ``tests/conftest.py`` reports the actual count
at the end of every live session so a drift is visible rather than inferred.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from carimer.transport.base import TransportOptions
from carimer.transport.sync import SyncTransport

if TYPE_CHECKING:
    from collections.abc import Iterator

#: The live-call budget.
MAX_CALLS_PER_PHASE = 20
MAX_CALLS_TOTAL = 70

LIVE_OPTIONS = TransportOptions(min_interval=0.6)


@pytest.fixture
def transport() -> Iterator[SyncTransport]:
    with SyncTransport(LIVE_OPTIONS) as t:
        yield t
