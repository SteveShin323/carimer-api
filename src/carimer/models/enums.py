"""Fixed enums (02-filter-catalog.md §6).

Only values the API has confirmed as enums live here. Anything that is data — category
ids, brand ids, attribute value UUIDs — comes from ``facets:suggest`` or the master
datasets at runtime (03 §1.2).
"""

from __future__ import annotations

from enum import IntEnum, StrEnum

__all__ = [
    "WEB_SORT_COMBINATIONS",
    "Condition",
    "ItemKind",
    "ItemType",
    "Order",
    "ShippingMethod",
    "ShippingPayer",
    "Sort",
    "Status",
    "ThumbnailType",
]


class Sort(StrEnum):
    SCORE = "SORT_SCORE"
    CREATED_TIME = "SORT_CREATED_TIME"
    PRICE = "SORT_PRICE"
    NUM_LIKES = "SORT_NUM_LIKES"


class Order(StrEnum):
    DESC = "ORDER_DESC"
    ASC = "ORDER_ASC"


#: The five combinations the web UI offers. Others are accepted but silently treated as
#: DESC (01 §3.5), so the query builder warns instead of failing.
WEB_SORT_COMBINATIONS: frozenset[tuple[Sort, Order]] = frozenset(
    {
        (Sort.SCORE, Order.DESC),
        (Sort.CREATED_TIME, Order.DESC),
        (Sort.PRICE, Order.ASC),
        (Sort.PRICE, Order.DESC),
        (Sort.NUM_LIKES, Order.DESC),
    }
)


class Status(StrEnum):
    """Item status, normalised across the three spellings the API uses.

    search request ``STATUS_ON_SALE`` / search response ``ITEM_STATUS_ON_SALE`` /
    detail response ``on_sale`` all map onto one member.
    """

    ON_SALE = "on_sale"
    TRADING = "trading"
    SOLD_OUT = "sold_out"
    STOP = "stop"
    CANCEL = "cancel"
    UNKNOWN = "unknown"

    @property
    def request_value(self) -> str:
        """The ``searchCondition.status`` spelling. Only three are filterable."""
        return f"STATUS_{self.name}"

    @classmethod
    def parse(cls, raw: object) -> Status:
        if isinstance(raw, cls):
            return raw
        if not isinstance(raw, str) or not raw:
            return cls.UNKNOWN
        key = raw.removeprefix("ITEM_STATUS_").removeprefix("STATUS_").lower()
        try:
            return cls(key)
        except ValueError:
            return cls.UNKNOWN


class ItemType(StrEnum):
    """``searchCondition.itemTypes`` — the web app's 出品者 (個人 / ショップ) filter."""

    MERCARI = "ITEM_TYPE_MERCARI"
    BEYOND = "ITEM_TYPE_BEYOND"


class ItemKind(StrEnum):
    """Which detail endpoint an item belongs to (03 §1.4)."""

    MERCARI = "mercari"
    SHOPS = "shops"


class ShippingMethod(StrEnum):
    """発送オプション."""

    ANONYMOUS = "SHIPPING_METHOD_ANONYMOUS"
    JAPAN_POST = "SHIPPING_METHOD_JAPAN_POST"
    NO_OPTION = "SHIPPING_METHOD_NO_OPTION"


class Condition(IntEnum):
    """商品の状態 1~6."""

    NEW = 1
    LIKE_NEW = 2
    NO_VISIBLE_DAMAGE = 3
    SLIGHT_DAMAGE = 4
    DAMAGED = 5
    POOR = 6


class ShippingPayer(IntEnum):
    """配送料の負担: 1 着払い(購入者), 2 送料込み(出品者)."""

    BUYER = 1
    SELLER = 2


class ThumbnailType(StrEnum):
    """``thumbnailTypes`` — the image format of ``items[].thumbnails`` (01 §3.1).

    The enum is ``mercari.platform.searchadapterjp.v2.ImgType`` and only these two
    values are accepted; every other candidate answers 400 (probe12, probe12b).
    Sending nothing keeps the default, which is webp.
    """

    WEBP = "WEBP"
    JPEG = "JPEG"
