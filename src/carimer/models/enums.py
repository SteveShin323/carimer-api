"""Fixed enums (02-filter-catalog.md §6).

Only values the API has confirmed as enums live here. Anything that is data — category
ids, brand ids, attribute value UUIDs — comes from ``facets:suggest`` or the master
datasets at runtime (03 §1.2).
"""

from __future__ import annotations

from enum import IntEnum, StrEnum

__all__ = [
    "ENDPOINT_ONLY_SORTS",
    "WEB_SORT_COMBINATIONS",
    "Condition",
    "ItemKind",
    "ItemType",
    "Order",
    "RelatedComponentType",
    "ShippingMethod",
    "ShippingPayer",
    "ShopProductOrder",
    "Sort",
    "Status",
    "ThumbnailType",
]


class Sort(StrEnum):
    SCORE = "SORT_SCORE"
    CREATED_TIME = "SORT_CREATED_TIME"
    PRICE = "SORT_PRICE"
    NUM_LIKES = "SORT_NUM_LIKES"
    #: Image search only. ``search_by_image`` sets it; ``entities:search`` ignores it.
    SIMILARITY = "SORT_SIMILARITY"


class Order(StrEnum):
    DESC = "ORDER_DESC"
    ASC = "ORDER_ASC"


#: The five combinations the web UI offers. Others are accepted but silently treated as
#: DESC (01 §3.5), so the query builder warns instead of failing. ``SORT_SIMILARITY`` is
#: not here because it belongs to a different endpoint — see :data:`ENDPOINT_ONLY_SORTS`.
WEB_SORT_COMBINATIONS: frozenset[tuple[Sort, Order]] = frozenset(
    {
        (Sort.SCORE, Order.DESC),
        (Sort.CREATED_TIME, Order.DESC),
        (Sort.PRICE, Order.ASC),
        (Sort.PRICE, Order.DESC),
        (Sort.NUM_LIKES, Order.DESC),
    }
)


#: Sorts that belong to an endpoint of their own. ``search_by_image`` sets these itself,
#: so seeing one arrive through ``SearchQuery.sort()`` means it is about to be sent to
#: ``entities:search``, where it has no meaning — a mistake worth its own message rather
#: than the generic "not one of the five combinations" one.
ENDPOINT_ONLY_SORTS: dict[Sort, str] = {
    Sort.SIMILARITY: "applies only to search_by_image(); entities:search ignores it",
}


class RelatedComponentType(StrEnum):
    """``relateditems/component`` — ``mercari.platform.similaritemjp.v2.ComponentType``.

    The enum has nine members in the web bundle; these five are the ones the server
    accepts. ``SIMILAR_ITEM``, ``USERS_ALSO_VIEWED`` and ``SIMILAR_ITEM_HEADER`` answer
    500 ``unsupported component type``, and ``UNSPECIFIED`` answers 500
    ``component_type is required`` (probe18), so they are left out.
    """

    #: この商品に近い商品.
    CLOSE_MATCH = "COMPONENT_TYPE_CLOSE_MATCH"
    #: この商品に近い商品, the feed variant — the one that carries a ``loadMoreToken``.
    CLOSE_MATCH_FEED = "COMPONENT_TYPE_CLOSE_MATCH_FEED"
    #: 見た目が近い商品 — visual similarity, a different axis from ``list-similar-items``.
    SIMILAR_LOOKS = "COMPONENT_TYPE_SIMILAR_LOOKS"
    #: 見た目が近い商品, the thumbnail placement. Often empty.
    SIMILAR_LOOKS_ON_ITEM_THUMBNAIL = "COMPONENT_TYPE_SIMILAR_LOOKS_ON_ITEM_THUMBNAIL"
    #: このアイテムに合わせる. Answers ``dataType: "ITEM"`` and is often empty.
    COMPLEMENTARY_ITEMS = "COMPONENT_TYPE_COMPLEMENTARY_ITEMS"


class ShopProductOrder(StrEnum):
    """``orderBy`` for the Shops storefront listing — the web's three sort buttons.

    An unrecognised value is ignored silently rather than rejected (probe15), which is
    why this is an enum and not a free string.
    """

    #: 新着順 — the web sends an empty string.
    NEWEST = ""
    #: 安い順.
    PRICE_ASC = "price asc"
    #: 高い順.
    PRICE_DESC = "price desc"


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
