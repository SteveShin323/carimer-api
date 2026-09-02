"""``Client`` / ``AsyncClient`` — the public facade (03 §3.9).

Both classes expose the same names; the async one returns awaitables and async
iterators. No event-loop wrapping in either direction: a sync facade that drives an
event loop breaks inside notebooks and other already-running loops (03 §1.6).
"""

from __future__ import annotations

from types import TracebackType
from typing import TYPE_CHECKING, Any

from carimer.api import items as items_api
from carimer.api import master as master_api
from carimer.api import search as search_api
from carimer.api import suggest as suggest_api
from carimer.api import users as users_api
from carimer.catalog.cache import TTLCache
from carimer.catalog.categories import AsyncCategories, Categories
from carimer.catalog.facets_client import AsyncFacetsClient, FacetsClient
from carimer.catalog.fallback import fallback_value_map
from carimer.models.enums import ItemKind
from carimer.models.item import Item
from carimer.models.misc import DesiredPriceInfo, SimilarItem, Suggestion
from carimer.models.profile import Badge, Profile, Review, SellerItem
from carimer.models.search import SearchItem, SearchPage, is_mercari_item_id
from carimer.models.shops import ShopsProduct
from carimer.search import monitor, pager, paginate
from carimer.search.attributes import AsyncAttributeResolver, AttributeResolver
from carimer.search.query import SearchQuery, as_query
from carimer.transport.asyncio import AsyncTransport
from carimer.transport.base import TransportOptions
from carimer.transport.errors import ShopsItemError
from carimer.transport.sync import SyncTransport

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator, Sequence

__all__ = ["AsyncClient", "Client"]


class Client:
    """Blocking client."""

    def __init__(
        self,
        *,
        options: TransportOptions | None = None,
        transport: SyncTransport | None = None,
        cache_dir: str | None = None,
    ) -> None:
        self._transport = transport or SyncTransport(options)
        cache = TTLCache(cache_dir=cache_dir)
        self.facets = FacetsClient(self._transport, cache=cache)
        self.categories = Categories(self._transport)
        self.attributes = AttributeResolver(self.facets, fallback_value_map())

    @property
    def transport(self) -> SyncTransport:
        return self._transport

    def __enter__(self) -> Client:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        self._transport.close()

    def search(
        self,
        query: SearchQuery | str,
        *,
        page_token: str = "",
        page_size: int = 120,
    ) -> SearchPage:
        prepared = as_query(query)
        request = search_api.search_request(
            prepared.to_condition(self.attributes),
            page_token=page_token,
            page_size=page_size,
            session_id=self._transport.search_session_id,
            device_uuid=self._transport.device_uuid,
            thumbnail_types=[t.value for t in prepared.thumbnail_types],
        )
        return SearchPage.from_api(self._transport.send(request))

    def iter_pages(
        self,
        query: SearchQuery | str,
        *,
        max_pages: int = paginate.DEFAULT_MAX_PAGES,
        page_size: int = 120,
    ) -> Iterator[SearchPage]:
        return paginate.iter_pages(self, query, max_pages=max_pages, page_size=page_size)

    def iter_items(
        self,
        query: SearchQuery | str,
        *,
        max_items: int | None = None,
        max_pages: int = paginate.DEFAULT_MAX_PAGES,
        page_size: int = 120,
    ) -> Iterator[SearchItem]:
        return paginate.iter_items(self, query, max_items=max_items, max_pages=max_pages, page_size=page_size)

    # -- item detail ----------------------------------------------------------

    def get_item(self, item_id: str, *, country_code: str | None = None) -> Item:
        """A personal listing.

        Raises :class:`ShopsItemError` for a Shops id without sending anything: the
        server's 400 in that case is indistinguishable from a malformed id (01 §5).
        """
        _reject_shops_id(item_id)
        request = items_api.get_item(item_id, country_code=country_code)
        return Item.from_api(self._transport.send(request))

    def get_shops_product(self, product_id: str) -> ShopsProduct:
        return ShopsProduct.from_api(self._transport.send(items_api.get_shops_product(product_id)))

    def get_detail(self, ref: SearchItem | str) -> Item | ShopsProduct:
        """Route to the right detail endpoint *before* sending (03 §1.4)."""
        item_id, kind = _detail_target(ref)
        if kind is ItemKind.SHOPS:
            return self.get_shops_product(item_id)
        return self.get_item(item_id)

    def similar_items(self, item_id: str, *, limit: int = 15) -> list[SimilarItem]:
        payload = self._transport.send(items_api.similar_items(item_id, limit=limit))
        return [SimilarItem.from_api(raw) for raw in payload.get("items") or [] if raw]

    def desired_price_info(self, item_id: str) -> DesiredPriceInfo:
        payload = self._transport.send(items_api.desired_price_info(item_id))
        return DesiredPriceInfo.from_api(payload)

    # -- seller ---------------------------------------------------------------

    def get_profile(self, user_id: str) -> Profile:
        return Profile.from_api(self._transport.send(users_api.get_profile(user_id)))

    def iter_seller_items(
        self,
        seller_id: str,
        *,
        status: Sequence[str] = ("on_sale",),
        limit: int = users_api.MAX_LIMIT,
        max_pages: int | None = None,
        max_items: int | None = None,
    ) -> Iterator[SellerItem]:
        """Walk ``items/get_items`` with ``max_pager_id`` (01 §7.2)."""
        max_pager_id: int | None = None
        seen: set[str] = set()
        page_index = 0
        while max_pages is None or page_index < max_pages:
            payload = self._transport.send(
                users_api.get_seller_items(seller_id, limit=limit, status=status, max_pager_id=max_pager_id)
            )
            page_rows = pager.rows(payload)
            if not page_rows:
                return
            for row in page_rows:
                item = SellerItem.from_api(row)
                if item.id in seen:
                    continue
                seen.add(item.id)
                yield item
                if max_items is not None and len(seen) >= max_items:
                    return
            if not pager.has_next(payload):
                return
            max_pager_id = pager.next_max_pager_id(page_rows)
            if max_pager_id is None:
                return
            page_index += 1

    def iter_reviews(
        self,
        user_id: str,
        *,
        max_items: int | None = None,
        max_pages: int | None = None,
        limit: int = users_api.MAX_LIMIT,
        subject: Sequence[str] = ("seller", "buyer"),
        fame: Sequence[str] = ("good", "normal", "bad"),
    ) -> Iterator[Review]:
        """Walk ``reviews/history`` the same way (01 §7.3)."""
        max_pager_id: int | None = None
        yielded = 0
        page_index = 0
        while max_pages is None or page_index < max_pages:
            payload = self._transport.send(
                users_api.get_reviews(
                    user_id, limit=limit, max_pager_id=max_pager_id, subject=subject, fame=fame
                )
            )
            page_rows = pager.rows(payload)
            if not page_rows:
                return
            for row in page_rows:
                yield Review.from_api(row)
                yielded += 1
                if max_items is not None and yielded >= max_items:
                    return
            if not pager.has_next(payload):
                return
            max_pager_id = pager.next_max_pager_id(page_rows)
            if max_pager_id is None:
                return
            page_index += 1

    def seller_badges(self, user_id: str) -> list[Badge]:
        payload = self._transport.send(users_api.seller_badges(user_id))
        return [Badge.from_api(raw) for raw in payload.get("badges") or [] if raw]

    def is_identity_verified(self, user_id: str) -> bool:
        payload = self._transport.send(users_api.has_identity_verified_badge(user_id))
        return bool(payload.get("hasBadge"))

    # -- misc -----------------------------------------------------------------

    def suggest_keywords(self, text: str) -> list[Suggestion]:
        payload = self._transport.send(suggest_api.suggest_terms(text))
        parsed = (Suggestion.from_api(raw) for raw in payload.get("data") or [] if raw)
        return [suggestion for suggestion in parsed if suggestion is not None]

    def master(self, name: str) -> dict[str, Any]:
        """Raw master dataset. Routing and the ``Accept`` header follow 03 §3.3."""
        return self._transport.send(master_api.dataset(name))

    def watch_new_listings(
        self,
        query: SearchQuery | str,
        *,
        on_new: monitor.NewListingCallback,
        interval: float = 60,
        since: int | None = None,
        include_shops: bool = False,
        max_cycles: int | None = None,
    ) -> int:
        """Poll for newly listed items; see :func:`carimer.search.monitor.watch_new_listings`."""
        return monitor.watch_new_listings(
            self,
            query,
            on_new=on_new,
            interval=interval,
            since=since,
            include_shops=include_shops,
            max_cycles=max_cycles,
        )


class AsyncClient:
    """Asyncio client."""

    def __init__(
        self,
        *,
        options: TransportOptions | None = None,
        transport: AsyncTransport | None = None,
        cache_dir: str | None = None,
    ) -> None:
        self._transport = transport or AsyncTransport(options)
        cache = TTLCache(cache_dir=cache_dir)
        self.facets = AsyncFacetsClient(self._transport, cache=cache)
        self.categories = AsyncCategories(self._transport)
        self.attributes = AsyncAttributeResolver(self.facets, fallback_value_map())

    @property
    def transport(self) -> AsyncTransport:
        return self._transport

    async def __aenter__(self) -> AsyncClient:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._transport.aclose()

    async def search(
        self,
        query: SearchQuery | str,
        *,
        page_token: str = "",
        page_size: int = 120,
    ) -> SearchPage:
        prepared = await self.resolve_attributes(as_query(query))
        request = search_api.search_request(
            prepared.to_condition(),
            page_token=page_token,
            page_size=page_size,
            session_id=self._transport.search_session_id,
            device_uuid=self._transport.device_uuid,
            thumbnail_types=[t.value for t in prepared.thumbnail_types],
        )
        return SearchPage.from_api(await self._transport.send(request))

    async def resolve_attributes(self, query: SearchQuery) -> SearchQuery:
        """Resolve ``.attr()`` / ``.sizes()`` names before the (sync) serialisation.

        ``to_condition()`` cannot await, so the async client resolves first and hands
        the UUIDs back to the query.
        """
        if not (query.pending_attributes or query.pending_sizes):
            return query
        resolved = [
            await self.attributes.resolve(section, *names) for section, names in query.pending_attributes
        ]
        resolved += [
            await self.attributes.resolve_size(group, *names) for group, names in query.pending_sizes
        ]
        return query.with_resolved(*resolved)

    def iter_pages(
        self,
        query: SearchQuery | str,
        *,
        max_pages: int = paginate.DEFAULT_MAX_PAGES,
        page_size: int = 120,
    ) -> AsyncIterator[SearchPage]:
        return paginate.aiter_pages(self, query, max_pages=max_pages, page_size=page_size)

    def iter_items(
        self,
        query: SearchQuery | str,
        *,
        max_items: int | None = None,
        max_pages: int = paginate.DEFAULT_MAX_PAGES,
        page_size: int = 120,
    ) -> AsyncIterator[SearchItem]:
        return paginate.aiter_items(
            self, query, max_items=max_items, max_pages=max_pages, page_size=page_size
        )

    # -- item detail ----------------------------------------------------------

    async def get_item(self, item_id: str, *, country_code: str | None = None) -> Item:
        """A personal listing.

        Raises :class:`ShopsItemError` for a Shops id without sending anything: the
        server's 400 in that case is indistinguishable from a malformed id (01 §5).
        """
        _reject_shops_id(item_id)
        request = items_api.get_item(item_id, country_code=country_code)
        return Item.from_api(await self._transport.send(request))

    async def get_shops_product(self, product_id: str) -> ShopsProduct:
        return ShopsProduct.from_api(await self._transport.send(items_api.get_shops_product(product_id)))

    async def get_detail(self, ref: SearchItem | str) -> Item | ShopsProduct:
        """Route to the right detail endpoint *before* sending (03 §1.4)."""
        item_id, kind = _detail_target(ref)
        if kind is ItemKind.SHOPS:
            return await self.get_shops_product(item_id)
        return await self.get_item(item_id)

    async def similar_items(self, item_id: str, *, limit: int = 15) -> list[SimilarItem]:
        payload = await self._transport.send(items_api.similar_items(item_id, limit=limit))
        return [SimilarItem.from_api(raw) for raw in payload.get("items") or [] if raw]

    async def desired_price_info(self, item_id: str) -> DesiredPriceInfo:
        payload = await self._transport.send(items_api.desired_price_info(item_id))
        return DesiredPriceInfo.from_api(payload)

    # -- seller ---------------------------------------------------------------

    async def get_profile(self, user_id: str) -> Profile:
        return Profile.from_api(await self._transport.send(users_api.get_profile(user_id)))

    async def iter_seller_items(
        self,
        seller_id: str,
        *,
        status: Sequence[str] = ("on_sale",),
        limit: int = users_api.MAX_LIMIT,
        max_pages: int | None = None,
        max_items: int | None = None,
    ) -> AsyncIterator[SellerItem]:
        """Walk ``items/get_items`` with ``max_pager_id`` (01 §7.2)."""
        max_pager_id: int | None = None
        seen: set[str] = set()
        page_index = 0
        while max_pages is None or page_index < max_pages:
            payload = await self._transport.send(
                users_api.get_seller_items(seller_id, limit=limit, status=status, max_pager_id=max_pager_id)
            )
            page_rows = pager.rows(payload)
            if not page_rows:
                return
            for row in page_rows:
                item = SellerItem.from_api(row)
                if item.id in seen:
                    continue
                seen.add(item.id)
                yield item
                if max_items is not None and len(seen) >= max_items:
                    return
            if not pager.has_next(payload):
                return
            max_pager_id = pager.next_max_pager_id(page_rows)
            if max_pager_id is None:
                return
            page_index += 1

    async def iter_reviews(
        self,
        user_id: str,
        *,
        max_items: int | None = None,
        max_pages: int | None = None,
        limit: int = users_api.MAX_LIMIT,
        subject: Sequence[str] = ("seller", "buyer"),
        fame: Sequence[str] = ("good", "normal", "bad"),
    ) -> AsyncIterator[Review]:
        """Walk ``reviews/history`` the same way (01 §7.3)."""
        max_pager_id: int | None = None
        yielded = 0
        page_index = 0
        while max_pages is None or page_index < max_pages:
            payload = await self._transport.send(
                users_api.get_reviews(
                    user_id, limit=limit, max_pager_id=max_pager_id, subject=subject, fame=fame
                )
            )
            page_rows = pager.rows(payload)
            if not page_rows:
                return
            for row in page_rows:
                yield Review.from_api(row)
                yielded += 1
                if max_items is not None and yielded >= max_items:
                    return
            if not pager.has_next(payload):
                return
            max_pager_id = pager.next_max_pager_id(page_rows)
            if max_pager_id is None:
                return
            page_index += 1

    async def seller_badges(self, user_id: str) -> list[Badge]:
        payload = await self._transport.send(users_api.seller_badges(user_id))
        return [Badge.from_api(raw) for raw in payload.get("badges") or [] if raw]

    async def is_identity_verified(self, user_id: str) -> bool:
        payload = await self._transport.send(users_api.has_identity_verified_badge(user_id))
        return bool(payload.get("hasBadge"))

    # -- misc -----------------------------------------------------------------

    async def suggest_keywords(self, text: str) -> list[Suggestion]:
        payload = await self._transport.send(suggest_api.suggest_terms(text))
        parsed = (Suggestion.from_api(raw) for raw in payload.get("data") or [] if raw)
        return [suggestion for suggestion in parsed if suggestion is not None]

    async def master(self, name: str) -> dict[str, Any]:
        """Raw master dataset. Routing and the ``Accept`` header follow 03 §3.3."""
        return await self._transport.send(master_api.dataset(name))

    async def watch_new_listings(
        self,
        query: SearchQuery | str,
        *,
        on_new: monitor.NewListingCallback,
        interval: float = 60,
        since: int | None = None,
        include_shops: bool = False,
        max_cycles: int | None = None,
    ) -> int:
        """Poll for newly listed items; see :func:`carimer.search.monitor.awatch_new_listings`."""
        return await monitor.awatch_new_listings(
            self,
            query,
            on_new=on_new,
            interval=interval,
            since=since,
            include_shops=include_shops,
            max_cycles=max_cycles,
        )


def _reject_shops_id(item_id: str) -> None:
    if not is_mercari_item_id(item_id):
        raise ShopsItemError(
            f"{item_id!r} is not a personal listing id (m + digits); use get_shops_product() "
            "or get_detail(), which routes automatically"
        )


def _detail_target(ref: SearchItem | str) -> tuple[str, ItemKind]:
    """Decide the endpoint from ``kind`` when available, else from the id shape."""
    if isinstance(ref, str):
        return ref, ItemKind.MERCARI if is_mercari_item_id(ref) else ItemKind.SHOPS
    return ref.id, ref.kind
