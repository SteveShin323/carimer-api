"""Mercari Shops models (01 §6).

Shops products share no field names with personal listings: camelCase, ISO timestamps,
no numeric condition id, no status field (sale state lives in ``productTags``), plus
``variants`` which personal listings do not have. Hence a separate model, with
``Client.get_detail()`` routing before the request.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import Field

from carimer.models.common import RawModel, to_bool, to_datetime, to_int, to_str, to_str_list
from carimer.models.facets import CategoryNode
from carimer.transport.errors import ParseError

__all__ = [
    "Shop",
    "ShopDetail",
    "ShopReview",
    "ShopsProduct",
    "ShopsProductSummary",
    "ShopsVariant",
]


def _bare_id(name: str | None) -> str | None:
    """Strip the resource prefix from a Shops resource name.

    The same product arrives under three spellings: a bare id from
    ``marketplaces/shops/products/{id}``, ``products/{id}`` from the storefront listing
    and ``marketplaces/shops/products/{id}`` from ``products:batchGet``. Normalising
    here is what lets an id from a listing go straight back into ``get_detail()``.
    """
    return None if name is None else name.rsplit("/", 1)[-1] or None


class Shop(RawModel):
    """A Shops storefront. Search only fills ``id`` (+ ``shopName`` alongside it)."""

    id: str | None = None
    display_name: str | None = None
    thumbnail: str | None = None
    score: float | None = None
    review_count: int | None = None

    @classmethod
    def from_api(cls, payload: dict[str, Any] | None, *, display_name: str | None = None) -> Shop | None:
        if not payload and not display_name:
            return None
        payload = payload or {}
        stats = payload.get("shopStats") or {}
        score = stats.get("score")
        return cls(
            id=to_str(payload.get("id") or payload.get("name")),
            display_name=to_str(payload.get("displayName")) or display_name,
            thumbnail=to_str(payload.get("thumbnail")),
            score=float(score) if isinstance(score, int | float | str) and str(score).strip() else None,
            review_count=to_int(stats.get("reviewCount")),
            raw=payload,
        )


class ShopsVariant(RawModel):
    """A purchasable variant (size / quantity). No equivalent for personal listings."""

    id: str | None = None
    display_name: str | None = None
    size: str | None = None
    quantity: int | None = None
    max_per_order: int | None = None

    @classmethod
    def from_api(cls, payload: dict[str, Any]) -> ShopsVariant:
        return cls(
            id=to_str(payload.get("variantId")),
            display_name=to_str(payload.get("displayName")),
            size=to_str(payload.get("size")),
            quantity=to_int(payload.get("quantity")),
            max_per_order=to_int(payload.get("maxQuantityPerOrder")),
            raw=payload,
        )


class ShopsProduct(RawModel):
    """A Mercari Shops product detail.

    ``name`` in the payload is the product id; the human name is ``displayName``. This
    model exposes them as ``id`` and ``display_name``.
    """

    id: str
    display_name: str
    price: int
    tags: list[str] = Field(default_factory=list)
    thumbnail: str | None = None
    photos: list[str] = Field(default_factory=list)
    description: str | None = None
    shop: Shop | None = None
    created: datetime | None = None
    updated: datetime | None = None
    category_path: list[CategoryNode] = Field(default_factory=list)
    condition_name: str | None = None
    shipping_payer_name: str | None = None
    shipping_method_name: str | None = None
    shipping_from_area: str | None = None
    likes_count: int | None = None
    review_count: int | None = None
    variants: list[ShopsVariant] = Field(default_factory=list)
    is_blocked_shop: bool = False

    @property
    def sold_out(self) -> bool:
        """Shops has no status field; the sale state is a tag (01 §6)."""
        return "sold_out" in self.tags

    @classmethod
    def from_api(cls, payload: dict[str, Any]) -> ShopsProduct:
        product_id = _bare_id(to_str(payload.get("name")))
        if not product_id:
            raise ParseError("name", payload)
        display_name = to_str(payload.get("displayName"))
        if display_name is None:
            raise ParseError("displayName", payload)
        price = to_int(payload.get("price"))
        if price is None:
            raise ParseError("price", payload)
        detail = payload.get("productDetail") or {}
        stats = detail.get("productStats") or {}
        return cls(
            id=product_id,
            display_name=display_name,
            price=price,
            tags=to_str_list(payload.get("productTags")),
            thumbnail=to_str(payload.get("thumbnail")),
            photos=to_str_list(detail.get("photos")),
            description=to_str(detail.get("description")),
            shop=Shop.from_api(detail.get("shop")),
            created=to_datetime(payload.get("createTime")),
            updated=to_datetime(payload.get("updateTime")),
            category_path=_categories(detail.get("categories")),
            condition_name=to_str((detail.get("condition") or {}).get("displayName")),
            shipping_payer_name=to_str((detail.get("shippingPayer") or {}).get("displayName")),
            shipping_method_name=to_str((detail.get("shippingMethod") or {}).get("displayName")),
            shipping_from_area=to_str((detail.get("shippingFromArea") or {}).get("displayName")),
            likes_count=to_int(stats.get("likesCount")),
            review_count=to_int(stats.get("reviewCount")),
            variants=[ShopsVariant.from_api(v) for v in detail.get("variants") or [] if v],
            is_blocked_shop=bool(payload.get("isBlockedShop")),
            raw=payload,
        )


def _categories(categories: Any) -> list[CategoryNode]:
    """``categories`` runs leaf → root; the model exposes root → leaf like ``Item``."""
    nodes: list[CategoryNode] = []
    for entry in categories or []:
        if not isinstance(entry, dict):
            continue
        node = CategoryNode.from_api(
            {
                "id": entry.get("categoryId"),
                "name": entry.get("displayName"),
                "parentCategoryId": entry.get("parentId"),
                "rootCategoryId": entry.get("rootId"),
                "hasChild": entry.get("hasChild"),
            }
        )
        if node is not None:
            nodes.append(node)
    return list(reversed(nodes))


class ShopsProductSummary(RawModel):
    """One row of a storefront listing (`bff/shops/v1/shops/{id}/products`).

    Not a thinner :class:`ShopsProduct`: the listing renames the timestamps
    (`createdAt`/`updatedAt`), replaces `productTags` with a plain `inStock` flag, and
    returns `thumbnails` as asset objects rather than one URL string. `id` is
    normalised, so it can be passed straight to `get_detail()`.
    """

    id: str
    display_name: str
    price: int
    in_stock: bool | None = None
    thumbnails: list[str] = Field(default_factory=list)
    created: datetime | None = None
    updated: datetime | None = None
    category_id: str | None = None

    @classmethod
    def from_api(cls, payload: dict[str, Any]) -> ShopsProductSummary:
        product_id = _bare_id(to_str(payload.get("name")))
        if not product_id:
            raise ParseError("name", payload)
        display_name = to_str(payload.get("displayName"))
        if display_name is None:
            raise ParseError("displayName", payload)
        price = to_int(payload.get("price"))
        if price is None:
            raise ParseError("price", payload)
        details = payload.get("details") or {}
        return cls(
            id=product_id,
            display_name=display_name,
            price=price,
            in_stock=to_bool(payload.get("inStock")),
            thumbnails=_asset_uris(payload.get("thumbnails")),
            created=to_datetime(payload.get("createdAt")),
            updated=to_datetime(payload.get("updatedAt")),
            category_id=_bare_id(to_str((details.get("category") or {}).get("name"))),
            raw=payload,
        )


class ShopDetail(RawModel):
    """`bff/shops/v1/contents/shops/{id}/details` — the storefront itself plus its stats.

    `score` and `review_count` also exist on :class:`Shop`, which search fills from a
    different payload; this model is the full storefront record.
    """

    id: str | None = None
    name: str | None = None
    description: str | None = None
    thumbnail: str | None = None
    status: str | None = None
    score: float | None = None
    review_count: int | None = None
    followed_count: int | None = None
    badges: list[str] = Field(default_factory=list)
    created: datetime | None = None
    updated: datetime | None = None
    #: The storefront's own policy text: business days, pricing, payment, shipping,
    #: returns. Keys are left as the API spells them.
    policies: dict[str, str] = Field(default_factory=dict)

    @classmethod
    def from_api(cls, payload: dict[str, Any]) -> ShopDetail:
        info = payload.get("shopInfo") or {}
        stats = payload.get("shopReviewStats") or {}
        score = stats.get("score")
        policies = {
            key: value
            for key, value in (payload.get("shopDescription") or {}).items()
            if isinstance(value, str) and value
        }
        return cls(
            id=to_str(info.get("id")),
            name=to_str(info.get("name")),
            description=to_str(info.get("description")),
            thumbnail=to_str(info.get("thumbnailUri")),
            status=to_str(info.get("shopStatus")),
            score=float(score) if isinstance(score, int | float) else None,
            review_count=to_int(stats.get("count")),
            followed_count=to_int(payload.get("shopFollowedCount")),
            badges=to_str_list(payload.get("shopBadges")),
            created=to_datetime(info.get("createdAt")),
            updated=to_datetime(info.get("updatedAt")),
            policies=policies,
            raw=payload,
        )


class ShopReview(RawModel):
    """One buyer review on a storefront's product.

    Unrelated to :class:`~carimer.models.profile.Review`, which is the personal-listing
    seller rating from ``reviews/history``: this one is per product, carries a
    `RATING_*` value instead of `good/normal/bad`, and names no user — only an opaque
    `account_id`.
    """

    id: str
    rating: str | None = None
    comment: str | None = None
    product_id: str | None = None
    product_name: str | None = None
    shop_id: str | None = None
    account_id: str | None = None
    created: datetime | None = None
    updated: datetime | None = None

    @property
    def is_good(self) -> bool:
        return self.rating == "RATING_GOOD"

    @classmethod
    def from_api(cls, payload: dict[str, Any]) -> ShopReview:
        review_id = to_str(payload.get("id"))
        if not review_id:
            raise ParseError("id", payload)
        product = payload.get("product") or {}
        return cls(
            id=review_id,
            rating=to_str(payload.get("rating")),
            comment=to_str(payload.get("comment")),
            product_id=_bare_id(to_str(payload.get("productId"))),
            product_name=to_str(product.get("displayName")),
            shop_id=to_str(payload.get("shopId")),
            account_id=to_str(payload.get("accountId")),
            created=to_datetime(payload.get("createTime")),
            updated=to_datetime(payload.get("updateTime")),
            raw=payload,
        )


def _asset_uris(assets: Any) -> list[str]:
    """`thumbnails` here is a list of `{name, type, uri}` rather than of URL strings."""
    out: list[str] = []
    for asset in assets or []:
        uri = to_str(asset.get("uri")) if isinstance(asset, dict) else to_str(asset)
        if uri:
            out.append(uri)
    return out
