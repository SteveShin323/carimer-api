"""`client.shops` — the Mercari Shops storefront, which search can filter but not read.

`SearchQuery.shops()` narrows results to a storefront; until now there was no way to
open one. These methods do that: its products, the storefront record, and the reviews
buyers left on its products. Every listing pages with `pageToken`.

Products come back as :class:`~carimer.models.shops.ShopsProductSummary`, whose `id`
goes straight into `client.get_detail()` for the full record.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from carimer.api import items as items_api
from carimer.api import shops as shops_api
from carimer.models.enums import ShopProductOrder
from carimer.models.shops import ShopDetail, ShopReview, ShopsProduct, ShopsProductSummary

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator, Sequence

    from carimer.transport.asyncio import AsyncTransport
    from carimer.transport.sync import SyncTransport

__all__ = ["DEFAULT_MAX_PAGES", "AsyncShopsClient", "ShopsClient"]

#: Same stop as the search iterators: a storefront can be very large.
DEFAULT_MAX_PAGES = 50


def _products(payload: dict[str, Any]) -> tuple[list[ShopsProductSummary], str]:
    rows = payload.get("products") or []
    products = [ShopsProductSummary.from_api(row) for row in rows if row]
    return products, str(payload.get("nextPageToken") or "")


def _reviews(payload: dict[str, Any]) -> tuple[list[ShopReview], str]:
    rows = payload.get("productReviews") or []
    reviews = [ShopReview.from_api(row) for row in rows if row]
    return reviews, str(payload.get("nextPageToken") or "")


class ShopsClient:
    """Blocking storefront reader. Reached as ``client.shops``."""

    def __init__(self, transport: SyncTransport) -> None:
        self._transport = transport

    def details(self, shop_id: str) -> ShopDetail:
        """The storefront record: name, description, rating, follower count, policies."""
        return ShopDetail.from_api(self._transport.send(shops_api.shop_details(shop_id)))

    def products(
        self,
        shop_id: str,
        *,
        page_token: str = "",
        page_size: int = shops_api.MAX_PRODUCTS_PAGE_SIZE,
        order_by: ShopProductOrder = ShopProductOrder.NEWEST,
    ) -> tuple[list[ShopsProductSummary], str]:
        """One page. Returns ``(products, next_page_token)``."""
        request = shops_api.shop_products(
            shop_id, page_token=page_token, page_size=page_size, order_by=order_by
        )
        return _products(self._transport.send(request))

    def iter_products(
        self,
        shop_id: str,
        *,
        max_items: int | None = None,
        max_pages: int = DEFAULT_MAX_PAGES,
        page_size: int = shops_api.MAX_PRODUCTS_PAGE_SIZE,
        order_by: ShopProductOrder = ShopProductOrder.NEWEST,
    ) -> Iterator[ShopsProductSummary]:
        token = ""
        yielded = 0
        for _ in range(max_pages):
            products, token = self.products(shop_id, page_token=token, page_size=page_size, order_by=order_by)
            if not products:
                return
            for product in products:
                yield product
                yielded += 1
                if max_items is not None and yielded >= max_items:
                    return
            if not token:
                return

    def reviews(
        self,
        shop_id: str,
        *,
        page_token: str = "",
        page_size: int = shops_api.MAX_REVIEWS_PAGE_SIZE,
    ) -> tuple[list[ShopReview], str]:
        request = shops_api.shop_reviews(shop_id, page_token=page_token, page_size=page_size)
        return _reviews(self._transport.send(request))

    def iter_reviews(
        self,
        shop_id: str,
        *,
        max_items: int | None = None,
        max_pages: int = DEFAULT_MAX_PAGES,
        page_size: int = shops_api.MAX_REVIEWS_PAGE_SIZE,
    ) -> Iterator[ShopReview]:
        token = ""
        yielded = 0
        for _ in range(max_pages):
            reviews, token = self.reviews(shop_id, page_token=token, page_size=page_size)
            if not reviews:
                return
            for review in reviews:
                yield review
                yielded += 1
                if max_items is not None and yielded >= max_items:
                    return
            if not token:
                return

    def batch_products(self, product_ids: Sequence[str]) -> list[ShopsProduct]:
        """Several Shops products in one call, instead of one `get_shops_product` each.

        The rows carry the same top-level fields as the detail endpoint but leave
        `productDetail` mostly empty, so this is for filling in names, prices and
        thumbnails — not a replacement for the detail call.
        """
        if not product_ids:
            return []
        payload = self._transport.send(items_api.shops_products_batch(product_ids))
        return [ShopsProduct.from_api(row) for row in payload.get("products") or [] if row]


class AsyncShopsClient:
    """The same names, awaited."""

    def __init__(self, transport: AsyncTransport) -> None:
        self._transport = transport

    async def details(self, shop_id: str) -> ShopDetail:
        return ShopDetail.from_api(await self._transport.send(shops_api.shop_details(shop_id)))

    async def products(
        self,
        shop_id: str,
        *,
        page_token: str = "",
        page_size: int = shops_api.MAX_PRODUCTS_PAGE_SIZE,
        order_by: ShopProductOrder = ShopProductOrder.NEWEST,
    ) -> tuple[list[ShopsProductSummary], str]:
        request = shops_api.shop_products(
            shop_id, page_token=page_token, page_size=page_size, order_by=order_by
        )
        return _products(await self._transport.send(request))

    async def iter_products(
        self,
        shop_id: str,
        *,
        max_items: int | None = None,
        max_pages: int = DEFAULT_MAX_PAGES,
        page_size: int = shops_api.MAX_PRODUCTS_PAGE_SIZE,
        order_by: ShopProductOrder = ShopProductOrder.NEWEST,
    ) -> AsyncIterator[ShopsProductSummary]:
        token = ""
        yielded = 0
        for _ in range(max_pages):
            products, token = await self.products(
                shop_id, page_token=token, page_size=page_size, order_by=order_by
            )
            if not products:
                return
            for product in products:
                yield product
                yielded += 1
                if max_items is not None and yielded >= max_items:
                    return
            if not token:
                return

    async def reviews(
        self,
        shop_id: str,
        *,
        page_token: str = "",
        page_size: int = shops_api.MAX_REVIEWS_PAGE_SIZE,
    ) -> tuple[list[ShopReview], str]:
        request = shops_api.shop_reviews(shop_id, page_token=page_token, page_size=page_size)
        return _reviews(await self._transport.send(request))

    async def iter_reviews(
        self,
        shop_id: str,
        *,
        max_items: int | None = None,
        max_pages: int = DEFAULT_MAX_PAGES,
        page_size: int = shops_api.MAX_REVIEWS_PAGE_SIZE,
    ) -> AsyncIterator[ShopReview]:
        token = ""
        yielded = 0
        for _ in range(max_pages):
            reviews, token = await self.reviews(shop_id, page_token=token, page_size=page_size)
            if not reviews:
                return
            for review in reviews:
                yield review
                yielded += 1
                if max_items is not None and yielded >= max_items:
                    return
            if not token:
                return

    async def batch_products(self, product_ids: Sequence[str]) -> list[ShopsProduct]:
        if not product_ids:
            return []
        payload = await self._transport.send(items_api.shops_products_batch(product_ids))
        return [ShopsProduct.from_api(row) for row in payload.get("products") or [] if row]
