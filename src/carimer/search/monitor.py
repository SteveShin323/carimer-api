"""New-listing watcher (03 §3.7).

``SORT_CREATED_TIME`` is not strictly ordered — 39 inversions in 120 results (01 §3.5) —
so the watcher does not rely on the first page alone. It narrows on
``createdAfterDate`` and exhausts the window up to a per-cycle page cap. The server
reads that value as JST and ``SearchQuery`` therefore serialises it with a +32,400 s
offset (01 §3.2).

Three safeguards, because each has been observed to matter:

* the window is asked for one minute wider than needed, so a listing that appears
  between two polls is not skipped;
* every item is re-checked client-side against ``since``, so a server-side change in
  the date handling cannot produce false positives;
* ids already reported are remembered within the retained overlap window, because deep
  pages repeat results.

Shops items are excluded by default: their ``created`` moves like an update timestamp
(``created == updated`` in most observations, 01 §3.3), which would report the same
storefront product over and over.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING, Any, Protocol

from carimer.models.enums import ItemType, Order, Sort
from carimer.search.paginate import DEFAULT_MAX_PAGES, aiter_pages, iter_pages
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
    prepared = as_query(query).sort(Sort.CREATED_TIME, Order.DESC)
    if not include_shops and not prepared.item_type_values:
        prepared = prepared.item_types(ItemType.MERCARI)
    return prepared


def _newest(items: Iterable[SearchItem]) -> int | None:
    stamps = [int(item.created.timestamp()) for item in items if item.created]
    return max(stamps) if stamps else None


def _select(items: Iterable[SearchItem], since: int, seen: dict[str, int]) -> list[SearchItem]:
    """Items created after ``since`` that have not been reported yet, newest first."""
    by_id: dict[str, SearchItem] = {}
    for item in items:
        if item.id in seen or not item.created or int(item.created.timestamp()) <= since:
            continue
        previous = by_id.get(item.id)
        if previous is None or (previous.created and item.created > previous.created):
            by_id[item.id] = item
    fresh = list(by_id.values())
    fresh.sort(key=lambda item: item.created.timestamp() if item.created else 0, reverse=True)
    return fresh


def _remember(seen: dict[str, int], items: Iterable[SearchItem]) -> None:
    for item in items:
        if item.created:
            seen[item.id] = int(item.created.timestamp())


def _prune_seen(seen: dict[str, int], since: int) -> None:
    cutoff = since - OVERLAP_SECONDS
    stale = [item_id for item_id, created in seen.items() if created < cutoff]
    for item_id in stale:
        del seen[item_id]


def _warn_truncated(max_pages_per_cycle: int, cursor: int) -> None:
    _log.warning(
        "watch cycle hit max_pages_per_cycle=%d; watermark remains at since=%d and "
        "listings beyond the cap may be missed if the result window changes",
        max_pages_per_cycle,
        cursor,
    )


def watch_new_listings(
    client: SyncSearcher,
    query: SearchQuery | str,
    *,
    on_new: NewListingCallback,
    interval: float = 60,
    since: int | None = None,
    include_shops: bool = False,
    max_cycles: int | None = None,
    max_pages_per_cycle: int = DEFAULT_MAX_PAGES,
    page_size: int = 120,
    now: Callable[[], float] = time.time,
    sleep: Callable[[float], Any] = time.sleep,
) -> int:
    """Poll for new listings until ``max_cycles`` is reached; returns the final ``since``.

    The first cycle only seeds state (no callback) unless ``since`` is given explicitly.
    ``now``/``sleep`` are injectable so tests can drive a fake clock.
    """
    if max_pages_per_cycle < 1:
        raise ValueError("max_pages_per_cycle must be at least 1")
    watched = _prepare(query, include_shops)
    seen: dict[str, int] = {}
    cursor = since
    cycle = 0
    while max_cycles is None or cycle < max_cycles:
        if cursor is None:
            page = client.search(watched, page_size=page_size)
            _remember(seen, page.items)
            cursor = _newest(page.items) or int(now())
            _prune_seen(seen, cursor)
            _log.debug("seeded watcher at since=%d with %d ids", cursor, len(seen))
        else:
            items: list[SearchItem] = []
            truncated = False
            for page in iter_pages(
                client,
                watched.created_after(cursor - OVERLAP_SECONDS),
                max_pages=max_pages_per_cycle,
                page_size=page_size,
            ):
                items.extend(page.items)
                truncated = truncated or page.truncated
            fresh = _select(items, cursor, seen)
            if fresh:
                _remember(seen, fresh)
                on_new(fresh)
            if truncated:
                _warn_truncated(max_pages_per_cycle, cursor)
            else:
                cursor = max(cursor, _newest(items) or cursor)
                _prune_seen(seen, cursor)
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
    max_pages_per_cycle: int = DEFAULT_MAX_PAGES,
    page_size: int = 120,
    now: Callable[[], float] = time.time,
) -> int:
    """Async twin of :func:`watch_new_listings`. ``on_new`` may be a coroutine function."""
    if max_pages_per_cycle < 1:
        raise ValueError("max_pages_per_cycle must be at least 1")
    watched = _prepare(query, include_shops)
    seen: dict[str, int] = {}
    cursor = since
    cycle = 0
    while max_cycles is None or cycle < max_cycles:
        if cursor is None:
            page = await client.search(watched, page_size=page_size)
            _remember(seen, page.items)
            cursor = _newest(page.items) or int(now())
            _prune_seen(seen, cursor)
        else:
            items: list[SearchItem] = []
            truncated = False
            async for page in aiter_pages(
                client,
                watched.created_after(cursor - OVERLAP_SECONDS),
                max_pages=max_pages_per_cycle,
                page_size=page_size,
            ):
                items.extend(page.items)
                truncated = truncated or page.truncated
            fresh = _select(items, cursor, seen)
            if fresh:
                _remember(seen, fresh)
                result = on_new(fresh)
                if asyncio.iscoroutine(result):
                    await result
            if truncated:
                _warn_truncated(max_pages_per_cycle, cursor)
            else:
                cursor = max(cursor, _newest(items) or cursor)
                _prune_seen(seen, cursor)
        cycle += 1
        if max_cycles is None or cycle < max_cycles:
            await asyncio.sleep(interval)
    return cursor if cursor is not None else int(now())
