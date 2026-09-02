"""Personal-listing detail model (01 §5).

The detail endpoint is snake_case with real numbers and lower-case status, while search
is camelCase with stringified numbers and ``ITEM_STATUS_*``. Both funnel into the same
``Status`` enum and the same ``Auction`` model.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import Field

from carimer.models.common import RawModel, to_bool, to_datetime, to_int, to_str, to_str_list
from carimer.models.enums import Status
from carimer.models.facets import Brand, CategoryNode
from carimer.models.search import Auction
from carimer.transport.errors import ParseError

__all__ = ["ConvertedPrice", "EmbeddedSeller", "Item", "ItemAttribute", "ItemComment"]


class EmbeddedSeller(RawModel):
    """The seller block inside an item. Public fields only."""

    id: str | None = None
    name: str | None = None
    photo_url: str | None = None
    num_sell_items: int | None = None
    num_ratings: int | None = None
    score: int | None = None
    star_rating_score: int | None = None
    ratings: dict[str, int] = Field(default_factory=dict)
    is_official: bool = False
    quick_shipper: bool = False

    @classmethod
    def from_api(cls, payload: dict[str, Any] | None) -> EmbeddedSeller | None:
        if not payload:
            return None
        ratings = payload.get("ratings") or {}
        return cls(
            id=to_str(payload.get("id")),
            name=to_str(payload.get("name")),
            photo_url=to_str(payload.get("photo_url")),
            num_sell_items=to_int(payload.get("num_sell_items")),
            num_ratings=to_int(payload.get("num_ratings")),
            score=to_int(payload.get("score")),
            star_rating_score=to_int(payload.get("star_rating_score")),
            ratings={k: v for k, v in ((k, to_int(v)) for k, v in ratings.items()) if v is not None},
            is_official=bool(to_bool(payload.get("is_official"))),
            quick_shipper=bool(to_bool(payload.get("quick_shipper"))),
            raw=payload,
        )


class ItemAttribute(RawModel):
    """One row of 商品の特徴 (``item_attributes``).

    Value ids are the same UUIDs the search ``attributes`` filter takes, so a listing's
    attributes can be turned straight back into a filter. Non-UI rows such as
    ``photo_description`` are present too, which is what ``show_on_ui`` marks.
    """

    id: str | None = None
    text: str | None = None
    values: list[tuple[str, str]] = Field(default_factory=list)
    show_on_ui: bool = True
    deep_facet_filterable: bool = False

    @classmethod
    def from_api(cls, payload: dict[str, Any]) -> ItemAttribute:
        values = [
            (to_str(value.get("id")) or "", to_str(value.get("text")) or "")
            for value in payload.get("values") or []
            if isinstance(value, dict)
        ]
        show = to_bool(payload.get("show_on_ui"))
        return cls(
            id=to_str(payload.get("id")),
            text=to_str(payload.get("text")),
            values=[pair for pair in values if pair != ("", "")],
            show_on_ui=True if show is None else show,
            deep_facet_filterable=bool(to_bool(payload.get("deep_facet_filterable"))),
            raw=payload,
        )


class ItemComment(RawModel):
    id: str | None = None
    message: str | None = None
    user_id: str | None = None
    user_name: str | None = None
    created: datetime | None = None

    @classmethod
    def from_api(cls, payload: dict[str, Any]) -> ItemComment:
        user = payload.get("user") or {}
        return cls(
            id=to_str(payload.get("id")),
            message=to_str(payload.get("message")),
            user_id=to_str(user.get("id")),
            user_name=to_str(user.get("name")),
            created=to_datetime(payload.get("created")),
            raw=payload,
        )


class ConvertedPrice(RawModel):
    """Only present when ``country_code`` was passed (01 §5)."""

    price: float
    currency_code: str
    rate_updated: datetime | None = None

    @classmethod
    def from_api(cls, payload: dict[str, Any] | None) -> ConvertedPrice | None:
        if not payload:
            return None
        price, currency = payload.get("price"), to_str(payload.get("currency_code"))
        if not isinstance(price, int | float) or not currency:
            return None
        return cls(
            price=float(price),
            currency_code=currency,
            rate_updated=to_datetime(payload.get("rate_updated")),
            raw=payload,
        )


class Item(RawModel):
    """A personal listing's detail."""

    id: str
    name: str
    price: int
    status: Status = Status.UNKNOWN
    description: str | None = None
    created: datetime | None = None
    updated: datetime | None = None
    photos: list[str] = Field(default_factory=list)
    thumbnails: list[str] = Field(default_factory=list)
    seller: EmbeddedSeller | None = None
    buyer_id: str | None = None
    category_id: int | None = None
    category_path: list[CategoryNode] = Field(default_factory=list)
    brand: Brand | None = None
    condition_id: int | None = None
    condition_name: str | None = None
    shipping_payer_id: int | None = None
    shipping_payer_name: str | None = None
    shipping_method_id: int | None = None
    shipping_method_name: str | None = None
    shipping_from_area: str | None = None
    shipping_duration: str | None = None
    num_likes: int | None = None
    num_comments: int | None = None
    comments: list[ItemComment] = Field(default_factory=list)
    attributes: list[ItemAttribute] = Field(default_factory=list)
    colors: list[str] = Field(default_factory=list)
    hash_tags: list[str] = Field(default_factory=list)
    auction: Auction | None = None
    converted_price: ConvertedPrice | None = None
    is_no_price: bool = False
    is_shop_item: bool = False
    is_anonymous_shipping: bool = False
    is_offerable: bool = False
    pager_id: int | None = None

    @property
    def sold_out(self) -> bool:
        return self.status is Status.SOLD_OUT

    @property
    def ui_attributes(self) -> list[ItemAttribute]:
        """Attributes the web page actually shows (drops ``photo_description`` etc.)."""
        return [attr for attr in self.attributes if attr.show_on_ui and attr.values]

    @property
    def filterable_attributes(self) -> list[ItemAttribute]:
        """Attributes whose ids/values can be fed back into a search filter.

        Not the same set as :attr:`ui_attributes`: 色 arrives with
        ``show_on_ui: false`` yet ``deep_facet_filterable: true``, and its value id is
        exactly the UUID the search ``attributes`` filter expects (probe11).
        """
        return [attr for attr in self.attributes if attr.deep_facet_filterable and attr.values]

    @classmethod
    def from_api(cls, payload: dict[str, Any]) -> Item:
        """Accepts either the whole ``{"result": "OK", "data": {...}}`` or just ``data``."""
        data = payload.get("data") if "data" in payload else payload
        if not isinstance(data, dict):
            raise ParseError("data", payload)
        item_id = to_str(data.get("id"))
        if not item_id:
            raise ParseError("id", payload)
        name = to_str(data.get("name"))
        if name is None:
            raise ParseError("name", payload)
        price = to_int(data.get("price"))
        if price is None:
            raise ParseError("price", payload)
        category = data.get("item_category_ntiers") or data.get("item_category") or {}
        parents = data.get("parent_categories_ntiers") or []
        return cls(
            id=item_id,
            name=name,
            price=price,
            status=Status.parse(data.get("status")),
            description=to_str(data.get("description")),
            created=to_datetime(data.get("created")),
            updated=to_datetime(data.get("updated")),
            photos=to_str_list(data.get("photos")),
            thumbnails=to_str_list(data.get("thumbnails")),
            seller=EmbeddedSeller.from_api(data.get("seller")),
            buyer_id=to_str((data.get("buyer") or {}).get("id")),
            category_id=to_int(category.get("id")),
            category_path=_category_path(parents, category),
            brand=Brand.from_api(data.get("item_brand")),
            condition_id=to_int((data.get("item_condition") or {}).get("id")),
            condition_name=to_str((data.get("item_condition") or {}).get("name")),
            shipping_payer_id=to_int((data.get("shipping_payer") or {}).get("id")),
            shipping_payer_name=to_str((data.get("shipping_payer") or {}).get("name")),
            shipping_method_id=to_int((data.get("shipping_method") or {}).get("id")),
            shipping_method_name=to_str((data.get("shipping_method") or {}).get("name")),
            shipping_from_area=to_str((data.get("shipping_from_area") or {}).get("name")),
            shipping_duration=to_str((data.get("shipping_duration") or {}).get("name")),
            num_likes=to_int(data.get("num_likes")),
            num_comments=to_int(data.get("num_comments")),
            comments=[ItemComment.from_api(c) for c in data.get("comments") or [] if c],
            attributes=[ItemAttribute.from_api(a) for a in data.get("item_attributes") or [] if a],
            colors=[
                name
                for name in (to_str(color.get("name")) for color in data.get("colors") or [] if color)
                if name
            ],
            hash_tags=to_str_list(data.get("hash_tags")),
            auction=Auction.from_detail(data.get("auction_info")),
            converted_price=ConvertedPrice.from_api(data.get("converted_price")),
            is_no_price=bool(to_bool(data.get("is_no_price"))),
            is_shop_item=to_str(data.get("is_shop_item")) == "yes",
            is_anonymous_shipping=bool(to_bool(data.get("is_anonymous_shipping"))),
            is_offerable=bool(to_bool(data.get("is_offerable"))),
            pager_id=to_int(data.get("pager_id")),
            raw=data,
        )


def _category_path(parents: list[dict[str, Any]], leaf: dict[str, Any]) -> list[CategoryNode]:
    nodes = [node for node in (CategoryNode.from_api(p) for p in parents if p) if node]
    leaf_node = CategoryNode.from_api(leaf) if leaf else None
    if leaf_node is not None and leaf_node.id not in {node.id for node in nodes}:
        nodes.append(leaf_node)
    return nodes
