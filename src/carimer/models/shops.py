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

from carimer.models.common import RawModel, to_datetime, to_int, to_str, to_str_list
from carimer.models.facets import CategoryNode
from carimer.transport.errors import ParseError

__all__ = ["Shop", "ShopsProduct", "ShopsVariant"]


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
        product_id = to_str(payload.get("name"))
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
