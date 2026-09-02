"""Pagination (01 §3.4, 03 §3.6).

``meta.numFound`` is not a total: it is capped at 15,000, changes between pages of the
same query and depends on the sort index. So the page count is never computed — the
iterators walk until the page is empty or the token is, with ``max_pages`` as a hard
stop, and ``iter_items`` de-duplicates by id because deep pages repeat results.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from carimer.models.search import SearchItem, SearchPage

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator

    from carimer.search.query import SearchQuery

__all__ = ["DEFAULT_MAX_PAGES", "aiter_items", "aiter_pages", "iter_items", "iter_pages"]

DEFAULT_MAX_PAGES = 50


class SyncSearcher(Protocol):
    def search(
        self, query: SearchQuery | str, *, page_token: str = ..., page_size: int = ...
    ) -> SearchPage: ...


class AsyncSearcher(Protocol):
    async def search(
        self, query: SearchQuery | str, *, page_token: str = ..., page_size: int = ...
    ) -> SearchPage: ...


def iter_pages(
    client: SyncSearcher,
    query: SearchQuery | str,
    *,
    max_pages: int = DEFAULT_MAX_PAGES,
    page_size: int = 120,
) -> Iterator[SearchPage]:
    """Yield pages until the results run out or ``max_pages`` is reached.

    The first page is always yielded (even when empty, so ``approx_total`` is visible);
    a trailing empty page is not. The last page is flagged ``truncated`` when the walk
    stopped at ``max_pages`` while the server still offered a next token.
    """
    token = ""
    for index in range(max_pages):
        page = client.search(query, page_token=token, page_size=page_size)
        if index and not page.items:
            return
        yield _flag(page, index=index, max_pages=max_pages)
        if not _can_continue(page):
            return
        token = page.next_page_token


async def aiter_pages(
    client: AsyncSearcher,
    query: SearchQuery | str,
    *,
    max_pages: int = DEFAULT_MAX_PAGES,
    page_size: int = 120,
) -> AsyncIterator[SearchPage]:
    token = ""
    for index in range(max_pages):
        page = await client.search(query, page_token=token, page_size=page_size)
        if index and not page.items:
            return
        yield _flag(page, index=index, max_pages=max_pages)
        if not _can_continue(page):
            return
        token = page.next_page_token


def iter_items(
    client: SyncSearcher,
    query: SearchQuery | str,
    *,
    max_items: int | None = None,
    max_pages: int = DEFAULT_MAX_PAGES,
    page_size: int = 120,
) -> Iterator[SearchItem]:
    """Flatten :func:`iter_pages`, dropping ids already seen."""
    seen: set[str] = set()
    for page in iter_pages(client, query, max_pages=max_pages, page_size=page_size):
        for item in page.items:
            if item.id in seen:
                continue
            seen.add(item.id)
            yield item
            if max_items is not None and len(seen) >= max_items:
                return


async def aiter_items(
    client: AsyncSearcher,
    query: SearchQuery | str,
    *,
    max_items: int | None = None,
    max_pages: int = DEFAULT_MAX_PAGES,
    page_size: int = 120,
) -> AsyncIterator[SearchItem]:
    seen: set[str] = set()
    async for page in aiter_pages(client, query, max_pages=max_pages, page_size=page_size):
        for item in page.items:
            if item.id in seen:
                continue
            seen.add(item.id)
            yield item
            if max_items is not None and len(seen) >= max_items:
                return


def _can_continue(page: SearchPage) -> bool:
    return bool(page.items) and bool(page.next_page_token)


def _flag(page: SearchPage, *, index: int, max_pages: int) -> SearchPage:
    if index + 1 >= max_pages and _can_continue(page):
        import logging

        logging.getLogger(__name__).warning(
            "stopped at max_pages=%d while the server still offered nextPageToken=%r",
            max_pages,
            page.next_page_token,
        )
        return page.model_copy(update={"truncated": True})
    return page
