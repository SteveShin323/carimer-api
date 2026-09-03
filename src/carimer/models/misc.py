"""Smaller response models: similar items, autocomplete, desired price (01 §8)."""

from __future__ import annotations

from typing import Any

from pydantic import Field

from carimer.models.common import RawModel, to_int, to_str
from carimer.models.enums import ItemKind, Status
from carimer.transport.errors import ParseError

__all__ = ["DesiredPriceInfo", "RelatedComponent", "SimilarItem", "Suggestion"]


class SimilarItem(RawModel):
    """An entry of ``relateditems/list-similar-items``.

    ``auctionInfo`` is present even for non-auction listings (``id: "0"`` and
    ``highestBid`` equal to the price), so it cannot be used to detect auctions —
    hence no ``Auction`` here (probe11).
    """

    id: str
    name: str
    price: int
    kind: ItemKind = ItemKind.MERCARI
    status: Status = Status.UNKNOWN
    thumbnail: str | None = None
    category_id: int | None = None
    highest_bid: int | None = None

    @classmethod
    def from_api(cls, payload: dict[str, Any]) -> SimilarItem:
        item_id = to_str(payload.get("id"))
        name = to_str(payload.get("name"))
        price = to_int(payload.get("price"))
        if not item_id:
            raise ParseError("id", payload)
        if name is None:
            raise ParseError("name", payload)
        if price is None:
            raise ParseError("price", payload)
        auction = payload.get("auctionInfo") or {}
        return cls(
            id=item_id,
            name=name,
            price=price,
            kind=ItemKind.SHOPS if to_str(payload.get("type")) == "ITEM_TYPE_BEYOND" else ItemKind.MERCARI,
            status=Status.parse(payload.get("status")),
            thumbnail=to_str(payload.get("thumbnail")),
            category_id=to_int(payload.get("categoryId")) or None,
            highest_bid=to_int(auction.get("highestBid")),
            raw=payload,
        )


class RelatedComponent(RawModel):
    """One recommendation shelf from ``relateditems/component``, or a page of one.

    The items are :class:`SimilarItem` because the payload is the same shape as
    ``list-similar-items`` returns, one level deeper
    (``contents[].itemContent.item``).

    ``load_more_token`` comes from ``loadMoreToken`` on a shelf and from
    ``nextPageToken`` on a ``relateditems/loadmore`` page; both feed the same call. It is
    empty when there is nothing more, and sending an empty one answers 500, so always
    check before paging.
    """

    title: str | None = None
    component_type: str | None = None
    data_type: str | None = None
    items: list[SimilarItem] = Field(default_factory=list)
    load_more_token: str = ""

    @property
    def has_next(self) -> bool:
        return bool(self.load_more_token) and bool(self.items)

    @classmethod
    def from_api(cls, payload: dict[str, Any]) -> RelatedComponent:
        items: list[SimilarItem] = []
        for content in payload.get("contents") or []:
            item = ((content or {}).get("itemContent") or {}).get("item")
            if item:
                items.append(SimilarItem.from_api(item))
        token = to_str(payload.get("loadMoreToken")) or to_str(payload.get("nextPageToken")) or ""
        return cls(
            title=to_str((payload.get("header") or {}).get("title")),
            component_type=to_str(payload.get("componentType")),
            data_type=to_str(payload.get("dataType")),
            items=items,
            load_more_token=token,
            raw=payload,
        )


class Suggestion(RawModel):
    """One autocomplete entry.

    The payload nests as ``{"MixedQuery": {"Query": {...}}}``; other wrapper shapes have
    not been observed and are skipped rather than guessed at.
    """

    keyword: str
    title: str | None = None
    subtitle: str | None = None
    score: float | None = None
    categories: list[tuple[int, str]] = Field(default_factory=list)

    @classmethod
    def from_api(cls, payload: dict[str, Any]) -> Suggestion | None:
        query = ((payload.get("MixedQuery") or {}).get("Query")) or {}
        if not query:
            return None
        params = query.get("search_params") or {}
        keyword = to_str(params.get("keyword")) or to_str(query.get("title"))
        if not keyword:
            return None
        categories: list[tuple[int, str]] = []
        for category in params.get("item_categories") or []:
            category_id = to_int(category.get("id"))
            name = to_str(category.get("name"))
            if category_id is not None and name:
                categories.append((category_id, name))
        score = query.get("score")
        return cls(
            keyword=keyword,
            title=to_str(query.get("title")),
            subtitle=to_str(query.get("subtitle")),
            score=float(score) if isinstance(score, int | float) else None,
            categories=categories,
            raw=payload,
        )


class DesiredPriceInfo(RawModel):
    """``desiredPriceItems/{id}/desiredPriceInfo`` — every value arrives as a string."""

    item_id: str | None = None
    registered_count: int = 0
    highest_desired_price: int = 0
    lowest_desired_price: int = 0
    highest_desired_price_count: int = 0

    @classmethod
    def from_api(cls, payload: dict[str, Any]) -> DesiredPriceInfo:
        name = to_str(payload.get("name")) or ""
        return cls(
            item_id=name.rsplit("/", 1)[-1] or None,
            registered_count=to_int(payload.get("registeredCount")) or 0,
            highest_desired_price=to_int(payload.get("highestDesiredPrice")) or 0,
            lowest_desired_price=to_int(payload.get("lowestDesiredPrice")) or 0,
            highest_desired_price_count=to_int(payload.get("highestDesiredPriceCount")) or 0,
            raw=payload,
        )
