"""Shared fixtures. Reports the live API call count at the end of the session.

The counter lives in the transport (``carimer.transport.base.CALL_COUNTER``) so every
request the package makes is counted, including those issued indirectly by
``AttributeResolver`` / ``FacetsClient``. Live calls are capped per phase (≤20) and in
total (≤70), so each phase report quotes this number.

Unit tests also go through the transport (respx intercepts them), so the report is
emitted only when live tests were actually selected — otherwise the number would mix
mocked and real requests.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from carimer.transport.base import CALL_COUNTER

if TYPE_CHECKING:
    from collections.abc import Iterator


def _live_tests_selected(session: pytest.Session) -> bool:
    return any(item.get_closest_marker("live") is not None for item in session.items)


def _phase_budget(session: pytest.Session) -> int | None:
    """The per-phase cap when a single phase was selected, else the total cap.

    Keeps the budget in one place (``tests/live/conftest.py``) instead of in prose.
    """
    from tests.live.conftest import MAX_CALLS_PER_PHASE, MAX_CALLS_TOTAL

    phases = {marker for item in session.items for marker in item.keywords if marker.startswith("phase")}
    return MAX_CALLS_PER_PHASE if len(phases) == 1 else MAX_CALLS_TOTAL


@pytest.fixture(scope="session", autouse=True)
def live_call_report(request: pytest.FixtureRequest) -> Iterator[None]:
    if not _live_tests_selected(request.session):
        yield
        return
    CALL_COUNTER.reset()
    yield
    reporter = request.config.pluginmanager.get_plugin("terminalreporter")
    if reporter is None:
        return
    budget = _phase_budget(request.session)
    over = " (OVER BUDGET)" if budget is not None and CALL_COUNTER.total > budget else ""
    suffix = f" / budget {budget}{over}" if budget is not None else ""
    reporter.write_sep("-", f"live API calls: {CALL_COUNTER.total}{suffix}")
    for path, count in sorted(CALL_COUNTER.by_path.items(), key=lambda kv: -kv[1]):
        reporter.write_line(f"  {count:>3}  {path}")
