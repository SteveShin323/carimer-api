"""Search response models (01-api-spec.md §3.3).

Parsing is deliberately lenient: only ``id``, ``name`` and ``price`` are required, every
other field is Optional, and the untouched payload stays in ``raw`` (03 §1.3). Numbers
arrive as strings in this endpoint and as real numbers in the detail endpoints, so all
coercion goes through ``models.common``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import Field

from carimer.models.common import RawModel, to_bool, to_datetime, to_int, to_str, to_str_list
from carimer.models.enums import ItemKind, Status
from carimer.models.facets import Brand, Size
from carimer.models.shops import Shop
from carimer.transport.errors import ParseError

__all__ = ["Auction", "QuerySuggestChip", "SearchItem", "SearchPage"]

_MERCARI_ID_PREFIX = "m"


def is_mercari_item_id(item_id: str) -> bool:
    """``m`` + digits is a personal listing; Shops ids are 22-char base62 (01 §3.3).

    ``get_detail`` routes on this *before* sending, because the server's 400 for a Shops
    id passed to ``items/get`` is indistinguishable from a malformed id (01 §5).
    """
    return item_id.startswith(_MERCARI_ID_PREFIX) and item_id[1:].isdigit()


class Auction(RawModel):
    """Normalises the two shapes of auction data.

    search   ``auction {bidDeadline: ISO, totalBid, highestBid, initialPrice}``
    detail   ``auction_info {expected_end_time: unix, total_bids, highest_bid, state, …}``
    """

    auction_id: str | None = None
    bid_deadline: datetime | None = None
    total_bids: int | None = None
    highest_bid: int | None = None
    initial_price: int | None = None
    state: str | None = None
    auction_type: str | None = None

    @classmethod
    def from_search(cls, payload: dict[str, Any] | None) -> Auction | None:
        if not payload:
            return None
        return cls(
            auction_id=to_str(payload.get("id")),
            bid_deadline=to_datetime(payload.get("bidDeadline")),
            total_bids=to_int(payload.get("totalBid")),
            highest_bid=to_int(payload.get("highestBid")),
            initial_price=to_int(payload.get("initialPrice")),
            raw=payload,
        )

    @classmethod
    def from_detail(cls, payload: dict[str, Any] | None) -> Auction | None:
        if not payload:
            return None
        return cls(
            auction_id=to_str(payload.get("id")),
            bid_deadline=to_datetime(payload.get("expected_end_time") or payload.get("bid_deadline")),
            total_bids=to_int(payload.get("total_bids")),
            highest_bid=to_int(payload.get("highest_bid")),
            initial_price=to_int(payload.get("initial_price")),
            state=to_str(payload.get("state")),
            auction_type=to_str(payload.get("auction_type")),
            raw=payload,
        )


class SearchItem(RawModel):
    """One element of ``items[]``."""

    id: str
    kind: ItemKind
    name: str
    price: int
    status: Status = Status.UNKNOWN
    is_no_price: bool = False
    created: datetime | None = None
    updated: datetime | None = None
    thumbnails: list[str] = Field(default_factory=list)
    photos: list[str] = Field(default_factory=list)
    seller_id: str | None = None
    buyer_id: str | None = None
    category_id: int | None = None
    condition_id: int | None = None
    shipping_payer_id: int | None = None
    shipping_method_id: int | None = None
    brand: Brand | None = None
    size: Size | None = None
    sizes: list[Size] = Field(default_factory=list)
    shop: Shop | None = None
    shop_name: str | None = None
    auction: Auction | None = None
    is_liked: bool = False

    @property
    def is_shops(self) -> bool:
        return self.kind is ItemKind.SHOPS

    @property
    def sold_out(self) -> bool:
        """Beware the inverted check in marvinody/mercari (``status != SOLD_OUT``)."""
        return self.status is Status.SOLD_OUT

    @classmethod
    def from_api(cls, payload: dict[str, Any]) -> SearchItem:
        item_id = to_str(payload.get("id"))
        if not item_id:
            raise ParseError("id", payload)
        name = to_str(payload.get("name"))
        if name is None:
            raise ParseError("name", payload)
        price = to_int(payload.get("price"))
        if price is None:
            raise ParseError("price", payload)
        item_type = to_str(payload.get("itemType"))
        if item_type == "ITEM_TYPE_BEYOND":
            kind = ItemKind.SHOPS
        elif item_type == "ITEM_TYPE_MERCARI":
            kind = ItemKind.MERCARI
        else:
            # Unknown/absent itemType: fall back to the id shape.
            kind = ItemKind.MERCARI if is_mercari_item_id(item_id) else ItemKind.SHOPS
        photos = [
            uri for uri in (to_str(photo.get("uri")) for photo in payload.get("photos") or [] if photo) if uri
        ]
        return cls(
            id=item_id,
            kind=kind,
            name=name,
            price=price,
            status=Status.parse(payload.get("status")),
            is_no_price=bool(to_bool(payload.get("isNoPrice"))),
            created=to_datetime(payload.get("created")),
            updated=to_datetime(payload.get("updated")),
            thumbnails=to_str_list(payload.get("thumbnails")),
            photos=photos,
            seller_id=_non_zero(to_str(payload.get("sellerId"))),
            buyer_id=_non_zero(to_str(payload.get("buyerId"))),
            category_id=to_int(payload.get("categoryId")),
            condition_id=to_int(payload.get("itemConditionId")),
            shipping_payer_id=_non_zero_int(to_int(payload.get("shippingPayerId"))),
            shipping_method_id=_non_zero_int(to_int(payload.get("shippingMethodId"))),
            brand=Brand.from_api(payload.get("itemBrand")),
            size=Size.from_api(payload.get("itemSize")),
            sizes=[s for s in (Size.from_api(x) for x in payload.get("itemSizes") or []) if s],
            shop=Shop.from_api(payload.get("shop"), display_name=to_str(payload.get("shopName"))),
            shop_name=to_str(payload.get("shopName")),
            auction=Auction.from_search(payload.get("auction")),
            is_liked=bool(to_bool(payload.get("isLiked"))),
            raw=payload,
        )


class QuerySuggestChip(RawModel):
    """A keyword chip from ``components[].querySuggest`` (the "pro / plus / 256gb" row)."""

    label: str
    keyword: str

    @classmethod
    def from_api(cls, payload: dict[str, Any]) -> QuerySuggestChip | None:
        keyword = to_str(payload.get("searchableValue"))
        if not keyword or payload.get("searchableKey") != "keyword":
            return None
        names = payload.get("displayNamesMap") or {}
        label = to_str(names.get("ja")) or to_str(names.get("en")) or keyword
        return cls(label=label, keyword=keyword, raw=payload)


class SearchPage(RawModel):
    """One page of results plus the page's metadata."""

    items: list[SearchItem] = Field(default_factory=list)
    next_page_token: str = ""
    prev_page_token: str = ""
    approx_total: int | None = None
    #: Set by ``iter_pages`` on the last page it yields when it stopped at ``max_pages``
    #: while the server still offered a next token. It describes the *walk*, not the
    #: page: a single ``client.search()`` never sets it, so the same page can arrive
    #: with ``truncated=True`` from ``iter_pages(q, max_pages=1)`` and ``False`` from
    #: ``search(q)``. Check ``has_next`` to ask about the page itself.
    truncated: bool = False
    query_chips: list[QuerySuggestChip] = Field(default_factory=list)
    search_condition_echo: dict[str, Any] = Field(default_factory=dict)
    search_condition_id: str | None = None

    @property
    def has_next(self) -> bool:
        return bool(self.next_page_token) and bool(self.items)

    @classmethod
    def from_api(cls, payload: dict[str, Any]) -> SearchPage:
        """``approx_total`` is ``meta.numFound``.

        Treat it as an estimate only: it is capped at 15,000, changes between pages of
        the same query and depends on the sort index (01 §3.4). Never compute a page
        count from it.
        """
        meta = payload.get("meta") or {}
        items = [SearchItem.from_api(raw) for raw in payload.get("items") or [] if raw]
        return cls(
            items=items,
            next_page_token=to_str(meta.get("nextPageToken")) or "",
            prev_page_token=to_str(meta.get("previousPageToken")) or "",
            approx_total=to_int(meta.get("numFound")),
            query_chips=_chips(payload.get("components") or []),
            search_condition_echo=payload.get("searchCondition") or {},
            search_condition_id=to_str(payload.get("searchConditionId")),
            raw=payload,
        )


def _chips(components: list[dict[str, Any]]) -> list[QuerySuggestChip]:
    chips: list[QuerySuggestChip] = []
    for component in components:
        facets = (((component or {}).get("querySuggest") or {}).get("suggestFacets") or {}).get("facets")
        for facet in facets or []:
            chip = QuerySuggestChip.from_api(facet)
            if chip is not None:
                chips.append(chip)
    return chips


def _non_zero(value: str | None) -> str | None:
    """Shops items report ``"0"`` for seller-side ids (01 §3.3)."""
    return None if value in (None, "", "0") else value


def _non_zero_int(value: int | None) -> int | None:
    return None if value in (None, 0) else value
