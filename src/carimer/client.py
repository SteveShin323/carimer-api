"""``Client`` / ``AsyncClient`` — the public facade (03 §3.9).

Both classes expose the same names; the async one returns awaitables and async
iterators. No event-loop wrapping in either direction: a sync facade that drives an
event loop breaks inside notebooks and other already-running loops (03 §1.6).
"""

from __future__ import annotations

import secrets
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
from carimer.models.enums import ItemKind, RelatedComponentType, ThumbnailType
from carimer.models.item import Item
from carimer.models.misc import DesiredPriceInfo, RelatedComponent, SimilarItem, Suggestion
from carimer.models.profile import Badge, Profile, Review, SellerItem
from carimer.models.search import ImageSearchPage, SearchItem, SearchPage, is_mercari_item_id
from carimer.models.shops import ShopsProduct
from carimer.search import monitor, pager, paginate
from carimer.search.attributes import AsyncAttributeResolver, AttributeResolver
from carimer.search.image import encode_image
from carimer.search.query import SearchQuery, as_query
from carimer.storefront import AsyncShopsClient, ShopsClient
from carimer.transport.asyncio import AsyncTransport
from carimer.transport.base import TransportOptions
from carimer.transport.errors import ShopsItemError
from carimer.transport.sync import SyncTransport

if TYPE_CHECKING:
    import os
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
        #: Mercari Shops storefronts — what ``SearchQuery.shops()`` can filter by but
        #: search alone cannot read.
        self.shops = ShopsClient(self._transport)

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

    # -- image search ---------------------------------------------------------

    def search_by_image(
        self,
        image: bytes | str | os.PathLike[str],
        query: SearchQuery | str | None = None,
        *,
        page_size: int = 30,
    ) -> ImageSearchPage:
        """Search by picture — the camera button in the web search box.

        ``image`` is either the image bytes or a **filesystem path**; a string is always
        read as a path. Every normal filter still applies: pass a ``SearchQuery`` to
        narrow by price, condition, category and the rest. Its ``sort`` is replaced by
        ``SORT_SIMILARITY``, which is the only ordering this endpoint has.

        The response's ``image_id`` is what pages two onwards send instead of uploading
        the picture again — :meth:`iter_image_pages` does that for you.
        """
        return self._image_page(query, photo_b64=encode_image(image), page_size=page_size)

    def _image_page(
        self,
        query: SearchQuery | str | None,
        *,
        photo_b64: str | None = None,
        image_id: str | None = None,
        page_token: str = "",
        page_size: int = 30,
    ) -> ImageSearchPage:
        prepared = as_query(query if query is not None else "")
        request = search_api.image_search_request(
            prepared.to_condition(self.attributes),
            photo_b64=photo_b64,
            image_id=image_id,
            page_token=page_token,
            page_size=page_size,
            session_id=self._transport.search_session_id,
        )
        return ImageSearchPage.from_api(self._transport.send(request))

    def iter_image_pages(
        self,
        image: bytes | str | os.PathLike[str],
        query: SearchQuery | str | None = None,
        *,
        max_pages: int = paginate.DEFAULT_MAX_PAGES,
        page_size: int = 30,
    ) -> Iterator[ImageSearchPage]:
        """Walk image-search pages, uploading the picture exactly once.

        A separate walk from :meth:`iter_pages` rather than a variation of it: this
        endpoint carries its page token at the top level, reports no total at all, and
        the second request has to quote the ``image_id`` the first one returned.
        """
        page = self.search_by_image(image, query, page_size=page_size)
        image_id = page.image_id
        token = ""
        for index in range(max_pages):
            if index:
                page = self._image_page(query, image_id=image_id, page_token=token, page_size=page_size)
                if not page.items:
                    return
            last = index == max_pages - 1
            yield page.model_copy(update={"truncated": last and page.has_next})
            if not page.has_next or not image_id:
                return
            token = page.next_page_token

    def iter_image_items(
        self,
        image: bytes | str | os.PathLike[str],
        query: SearchQuery | str | None = None,
        *,
        max_items: int | None = None,
        max_pages: int = paginate.DEFAULT_MAX_PAGES,
        page_size: int = 30,
    ) -> Iterator[SearchItem]:
        seen: set[str] = set()
        for page in self.iter_image_pages(image, query, max_pages=max_pages, page_size=page_size):
            for item in page.items:
                if item.id in seen:
                    continue
                seen.add(item.id)
                yield item
                if max_items is not None and len(seen) >= max_items:
                    return

    # -- item detail ----------------------------------------------------------

    def get_item(self, item_id: str, *, country_code: str | None = None) -> Item:
        """A personal listing.

        Raises :class:`ShopsItemError` for a Shops id without sending anything: the
        server's 400 in that case is indistinguishable from a malformed id (01 §5).
        """
        _reject_shops_id(item_id)
        request = items_api.get_item(item_id, country_code=country_code)
        return Item.from_api(self._transport.send(request))

    def get_shops_product(self, product_id: str, *, image_type: ThumbnailType | None = None) -> ShopsProduct:
        """``image_type`` switches the asset URLs between webp (default) and jpeg."""
        request = items_api.get_shops_product(product_id, image_type=image_type)
        return ShopsProduct.from_api(self._transport.send(request))

    def get_detail(self, ref: SearchItem | str) -> Item | ShopsProduct:
        """Route to the right detail endpoint *before* sending (03 §1.4)."""
        item_id, kind = _detail_target(ref)
        if kind is ItemKind.SHOPS:
            return self.get_shops_product(item_id)
        return self.get_item(item_id)

    def similar_items(self, item_id: str, *, limit: int = 15) -> list[SimilarItem]:
        payload = self._transport.send(items_api.similar_items(item_id, limit=limit))
        return [SimilarItem.from_api(raw) for raw in payload.get("items") or [] if raw]

    def related_component(
        self,
        item_id: str,
        component_type: RelatedComponentType = RelatedComponentType.CLOSE_MATCH,
        *,
        page_size: int = 10,
        view_request_id: str | None = None,
    ) -> RelatedComponent:
        """One of the product page's recommendation shelves.

        ``similar_items`` is a single axis; the web page shows several
        (``この商品に近い商品``, ``見た目が近い商品``, ``このアイテムに合わせる``), each its own
        ``component_type`` with its own title. Some are empty for a given item —
        that is normal, not an error.

        ``view_request_id`` ties several calls to one item view, as the web does; a new
        one is generated when it is omitted. Pass the shelf's own value if you intend to
        page it yourself.
        """
        request = items_api.related_component(
            item_id,
            component_type,
            view_request_id=view_request_id or _new_view_request_id(),
            page_size=page_size,
        )
        return RelatedComponent.from_api(self._transport.send(request))

    def iter_related_items(
        self,
        item_id: str,
        component_type: RelatedComponentType = RelatedComponentType.CLOSE_MATCH_FEED,
        *,
        max_items: int | None = None,
        max_pages: int = paginate.DEFAULT_MAX_PAGES,
        page_size: int = 10,
    ) -> Iterator[SimilarItem]:
        """Walk a shelf via ``relateditems/loadmore``.

        Only the feed-shaped shelves hand out a ``loadMoreToken``, so the default is
        ``CLOSE_MATCH_FEED``; a shelf without one simply yields its single page.

        Unlike the page iterators there is nowhere to hang a ``truncated`` flag, so this
        **stops silently** once it has fetched the first shelf plus ``max_pages`` more
        pages — note that this counts one page higher than ``iter_pages``. Use
        ``max_items`` when you need to know you got everything.
        """
        view_request_id = _new_view_request_id()
        component = self.related_component(
            item_id, component_type, page_size=page_size, view_request_id=view_request_id
        )
        seen: set[str] = set()
        for _ in range(max_pages):
            for item in component.items:
                if item.id in seen:
                    continue
                seen.add(item.id)
                yield item
                if max_items is not None and len(seen) >= max_items:
                    return
            if not component.has_next:
                return
            payload = self._transport.send(
                items_api.related_loadmore(
                    view_request_id=view_request_id,
                    page_token=component.load_more_token,
                    page_size=page_size,
                )
            )
            component = RelatedComponent.from_api(payload)

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
        exclude_archived: bool = False,
    ) -> Iterator[SellerItem]:
        """Walk ``items/get_items`` with ``max_pager_id`` (01 §7.2).

        ``exclude_archived`` drops listings the seller has archived, which is what the
        web profile page asks for alongside ``status=on_sale,trading,sold_out``.
        """
        max_pager_id: int | None = None
        seen: set[str] = set()
        page_index = 0
        while max_pages is None or page_index < max_pages:
            payload = self._transport.send(
                users_api.get_seller_items(
                    seller_id,
                    limit=limit,
                    status=status,
                    max_pager_id=max_pager_id,
                    exclude_archived=exclude_archived,
                )
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

    def suggest_keywords(self, text: str, *, category_id: int | None = None) -> list[Suggestion]:
        """``category_id`` scopes the suggestions, as the web search box does."""
        payload = self._transport.send(suggest_api.suggest_terms(text, category_id=category_id))
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
        max_pages_per_cycle: int = paginate.DEFAULT_MAX_PAGES,
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
            max_pages_per_cycle=max_pages_per_cycle,
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
        self.shops = AsyncShopsClient(self._transport)

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

    # -- image search ---------------------------------------------------------

    async def search_by_image(
        self,
        image: bytes | str | os.PathLike[str],
        query: SearchQuery | str | None = None,
        *,
        page_size: int = 30,
    ) -> ImageSearchPage:
        """Search by picture. See :meth:`Client.search_by_image`."""
        return await self._image_page(query, photo_b64=encode_image(image), page_size=page_size)

    async def _image_page(
        self,
        query: SearchQuery | str | None,
        *,
        photo_b64: str | None = None,
        image_id: str | None = None,
        page_token: str = "",
        page_size: int = 30,
    ) -> ImageSearchPage:
        prepared = await self.resolve_attributes(as_query(query if query is not None else ""))
        request = search_api.image_search_request(
            prepared.to_condition(),
            photo_b64=photo_b64,
            image_id=image_id,
            page_token=page_token,
            page_size=page_size,
            session_id=self._transport.search_session_id,
        )
        return ImageSearchPage.from_api(await self._transport.send(request))

    async def iter_image_pages(
        self,
        image: bytes | str | os.PathLike[str],
        query: SearchQuery | str | None = None,
        *,
        max_pages: int = paginate.DEFAULT_MAX_PAGES,
        page_size: int = 30,
    ) -> AsyncIterator[ImageSearchPage]:
        page = await self.search_by_image(image, query, page_size=page_size)
        image_id = page.image_id
        token = ""
        for index in range(max_pages):
            if index:
                page = await self._image_page(query, image_id=image_id, page_token=token, page_size=page_size)
                if not page.items:
                    return
            last = index == max_pages - 1
            yield page.model_copy(update={"truncated": last and page.has_next})
            if not page.has_next or not image_id:
                return
            token = page.next_page_token

    async def iter_image_items(
        self,
        image: bytes | str | os.PathLike[str],
        query: SearchQuery | str | None = None,
        *,
        max_items: int | None = None,
        max_pages: int = paginate.DEFAULT_MAX_PAGES,
        page_size: int = 30,
    ) -> AsyncIterator[SearchItem]:
        seen: set[str] = set()
        async for page in self.iter_image_pages(image, query, max_pages=max_pages, page_size=page_size):
            for item in page.items:
                if item.id in seen:
                    continue
                seen.add(item.id)
                yield item
                if max_items is not None and len(seen) >= max_items:
                    return

    # -- item detail ----------------------------------------------------------

    async def get_item(self, item_id: str, *, country_code: str | None = None) -> Item:
        """A personal listing.

        Raises :class:`ShopsItemError` for a Shops id without sending anything: the
        server's 400 in that case is indistinguishable from a malformed id (01 §5).
        """
        _reject_shops_id(item_id)
        request = items_api.get_item(item_id, country_code=country_code)
        return Item.from_api(await self._transport.send(request))

    async def get_shops_product(
        self, product_id: str, *, image_type: ThumbnailType | None = None
    ) -> ShopsProduct:
        request = items_api.get_shops_product(product_id, image_type=image_type)
        return ShopsProduct.from_api(await self._transport.send(request))

    async def get_detail(self, ref: SearchItem | str) -> Item | ShopsProduct:
        """Route to the right detail endpoint *before* sending (03 §1.4)."""
        item_id, kind = _detail_target(ref)
        if kind is ItemKind.SHOPS:
            return await self.get_shops_product(item_id)
        return await self.get_item(item_id)

    async def similar_items(self, item_id: str, *, limit: int = 15) -> list[SimilarItem]:
        payload = await self._transport.send(items_api.similar_items(item_id, limit=limit))
        return [SimilarItem.from_api(raw) for raw in payload.get("items") or [] if raw]

    async def related_component(
        self,
        item_id: str,
        component_type: RelatedComponentType = RelatedComponentType.CLOSE_MATCH,
        *,
        page_size: int = 10,
        view_request_id: str | None = None,
    ) -> RelatedComponent:
        """See :meth:`Client.related_component`."""
        request = items_api.related_component(
            item_id,
            component_type,
            view_request_id=view_request_id or _new_view_request_id(),
            page_size=page_size,
        )
        return RelatedComponent.from_api(await self._transport.send(request))

    async def iter_related_items(
        self,
        item_id: str,
        component_type: RelatedComponentType = RelatedComponentType.CLOSE_MATCH_FEED,
        *,
        max_items: int | None = None,
        max_pages: int = paginate.DEFAULT_MAX_PAGES,
        page_size: int = 10,
    ) -> AsyncIterator[SimilarItem]:
        view_request_id = _new_view_request_id()
        component = await self.related_component(
            item_id, component_type, page_size=page_size, view_request_id=view_request_id
        )
        seen: set[str] = set()
        for _ in range(max_pages):
            for item in component.items:
                if item.id in seen:
                    continue
                seen.add(item.id)
                yield item
                if max_items is not None and len(seen) >= max_items:
                    return
            if not component.has_next:
                return
            payload = await self._transport.send(
                items_api.related_loadmore(
                    view_request_id=view_request_id,
                    page_token=component.load_more_token,
                    page_size=page_size,
                )
            )
            component = RelatedComponent.from_api(payload)

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
        exclude_archived: bool = False,
    ) -> AsyncIterator[SellerItem]:
        """Walk ``items/get_items`` with ``max_pager_id`` (01 §7.2)."""
        max_pager_id: int | None = None
        seen: set[str] = set()
        page_index = 0
        while max_pages is None or page_index < max_pages:
            payload = await self._transport.send(
                users_api.get_seller_items(
                    seller_id,
                    limit=limit,
                    status=status,
                    max_pager_id=max_pager_id,
                    exclude_archived=exclude_archived,
                )
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

    async def suggest_keywords(self, text: str, *, category_id: int | None = None) -> list[Suggestion]:
        payload = await self._transport.send(suggest_api.suggest_terms(text, category_id=category_id))
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
        max_pages_per_cycle: int = paginate.DEFAULT_MAX_PAGES,
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
            max_pages_per_cycle=max_pages_per_cycle,
        )


def _new_view_request_id() -> str:
    """The web's ``itemViewRequestId``: 32 hex characters, one per item view."""
    return secrets.token_hex(16)


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
