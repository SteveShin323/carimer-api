"""``max_pager_id`` paging for the legacy seller endpoints (01 §7.2, §7.3).

Both ``items/get_items`` and ``reviews/history`` page the same way: take the last row's
``pager_id``, subtract one, send it as ``max_pager_id``. ``meta.has_next`` says whether
to continue (overlap between pages measured as 0 in probe6/probe7).
"""

from __future__ import annotations

from typing import Any

__all__ = ["has_next", "next_max_pager_id", "rows"]


def rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    data = payload.get("data")
    return [row for row in data or [] if isinstance(row, dict)] if isinstance(data, list) else []


def has_next(payload: dict[str, Any]) -> bool:
    return bool((payload.get("meta") or {}).get("has_next"))


def next_max_pager_id(page_rows: list[dict[str, Any]]) -> int | None:
    """One below the smallest ``pager_id`` on the page.

    Using the minimum rather than the last row keeps this correct even if the server
    stops returning rows in descending ``pager_id`` order.
    """
    ids = [int(row["pager_id"]) for row in page_rows if str(row.get("pager_id", "")).isdigit()]
    return min(ids) - 1 if ids else None
