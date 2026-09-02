"""New-listing watcher (03 §3.7).

``SORT_CREATED_TIME`` is not strictly ordered — 39 inversions in 120 results (01 §3.5) —
so polling the "newest" sort misses listings. The watcher instead narrows on
``createdAfterDate``, which the server reads as JST and ``SearchQuery`` therefore
serialises with a +32,400 s offset (01 §3.2).

Three safeguards, because each has been observed to matter:

* the window is asked for one minute wider than needed, so a listing that appears
  between two polls is not skipped;
* every item is re-checked client-side against ``since``, so a server-side change in
  the date handling cannot produce false positives;
* ids already reported are remembered, because deep pages repeat results.

Shops items are excluded by default: their ``created`` moves like an update timestamp
(``created == updated`` in most observations, 01 §3.3), which would report the same
storefront product over and over.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING, Any, Protocol

from carimer.models.enums import ItemType
from carimer.search.query import SearchQuery, as_query

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from carimer.models.search import SearchItem
    from carimer.search.paginate import AsyncSearcher, SyncSearcher

__all__ = ["OVERLAP_SECONDS", "awatch_new_listings", "watch_new_listings"]

_log = logging.getLogger(__name__)

#: Ask for a slightly wider window than strictly needed, to survive clock skew.
OVERLAP_SECONDS = 60


class NewListingCallback(Protocol):
    def __call__(self, items: list[SearchItem]) -> Any: ...


def _prepare(query: SearchQuery | str, include_shops: bool) -> SearchQuery:
    prepared = as_query(query)
    if not include_shops and not prepared.item_type_values:
        prepared = prepared.item_types(ItemType.MERCARI)
    return prepared


def _newest(items: Iterable[SearchItem]) -> int | None:
    stamps = [int(item.created.timestamp()) for item in items if item.created]
    return max(stamps) if stamps else None


def _select(items: Iterable[SearchItem], since: int, seen: set[str]) -> list[SearchItem]:
    """Items created after ``since`` that have not been reported yet, newest first."""
    fresh = [
        item
        for item in items
        if item.id not in seen and item.created and int(item.created.timestamp()) > since
    ]
    fresh.sort(key=lambda item: item.created.timestamp() if item.created else 0, reverse=True)
    return fresh


def watch_new_listings(
    client: SyncSearcher,
    query: SearchQuery | str,
    *,
    on_new: NewListingCallback,
    interval: float = 60,
    since: int | None = None,
    include_shops: bool = False,
    max_cycles: int | None = None,
    page_size: int = 120,
    now: Callable[[], float] = time.time,
    sleep: Callable[[float], Any] = time.sleep,
) -> int:
    """Poll for new listings until ``max_cycles`` is reached; returns the final ``since``.

    The first cycle only seeds state (no callback) unless ``since`` is given explicitly.
    ``now``/``sleep`` are injectable so tests can drive a fake clock.
    """
    watched = _prepare(query, include_shops)
    seen: set[str] = set()
    cursor = since
    cycle = 0
    while max_cycles is None or cycle < max_cycles:
        if cursor is None:
            page = client.search(watched, page_size=page_size)
            seen.update(item.id for item in page.items)
            cursor = _newest(page.items) or int(now())
            _log.debug("seeded watcher at since=%d with %d ids", cursor, len(seen))
        else:
            page = client.search(watched.created_after(cursor - OVERLAP_SECONDS), page_size=page_size)
            fresh = _select(page.items, cursor, seen)
            if fresh:
                seen.update(item.id for item in fresh)
                cursor = max(cursor, _newest(fresh) or cursor)
                on_new(fresh)
        cycle += 1
        if max_cycles is None or cycle < max_cycles:
            sleep(interval)
    return cursor if cursor is not None else int(now())


async def awatch_new_listings(
    client: AsyncSearcher,
    query: SearchQuery | str,
    *,
    on_new: NewListingCallback,
    interval: float = 60,
    since: int | None = None,
    include_shops: bool = False,
    max_cycles: int | None = None,
    page_size: int = 120,
    now: Callable[[], float] = time.time,
) -> int:
    """Async twin of :func:`watch_new_listings`. ``on_new`` may be a coroutine function."""
    watched = _prepare(query, include_shops)
    seen: set[str] = set()
    cursor = since
    cycle = 0
    while max_cycles is None or cycle < max_cycles:
        if cursor is None:
            page = await client.search(watched, page_size=page_size)
            seen.update(item.id for item in page.items)
            cursor = _newest(page.items) or int(now())
        else:
            page = await client.search(watched.created_after(cursor - OVERLAP_SECONDS), page_size=page_size)
            fresh = _select(page.items, cursor, seen)
            if fresh:
                seen.update(item.id for item in fresh)
                cursor = max(cursor, _newest(fresh) or cursor)
                result = on_new(fresh)
                if asyncio.iscoroutine(result):
                    await result
        cycle += 1
        if max_cycles is None or cycle < max_cycles:
            await asyncio.sleep(interval)
    return cursor if cursor is not None else int(now())
