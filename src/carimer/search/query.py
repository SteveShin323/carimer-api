"""``SearchQuery`` — the immutable ``searchCondition`` builder (03 §3.4).

Every builder method returns a new query, so a base query can be branched safely. The
type rules encoded here are the ones that bite: ``sizeId``/``sellerId``/``shopIds``/
``skuIds`` are **string** arrays (a number gives 400, which is what breaks size filters
in take-kun/mercapi), while the id filters are integers (01 §3.2).
"""

from __future__ import annotations

import dataclasses
import warnings
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Self

from carimer.models.enums import (
    ENDPOINT_ONLY_SORTS,
    WEB_SORT_COMBINATIONS,
    Condition,
    ItemType,
    Order,
    ShippingMethod,
    ShippingPayer,
    Sort,
    Status,
    ThumbnailType,
)
from carimer.search.attributes import AttributeFilter, AttributeResolverProtocol, AttributeSection

__all__ = ["JST_OFFSET_SECONDS", "SearchQuery"]

#: ``createdAfterDate`` / ``createdBeforeDate`` are interpreted by the server as JST
#: (UTC+9), so a plain unix timestamp filters 9 hours too early (01 §3.2, probe7c).
JST_OFFSET_SECONDS = 32_400

#: The 22 keys the web app always sends, in capture order (01 §3.1).
CONDITION_KEYS: tuple[str, ...] = (
    "keyword",
    "excludeKeyword",
    "sort",
    "order",
    "status",
    "sizeId",
    "categoryId",
    "brandId",
    "sellerId",
    "priceMin",
    "priceMax",
    "itemConditionId",
    "shippingPayerId",
    "shippingFromArea",
    "shippingMethod",
    "colorId",
    "hasCoupon",
    "attributes",
    "itemTypes",
    "skuIds",
    "shopIds",
    "excludeShippingMethodIds",
)


@dataclass(frozen=True, slots=True)
class SearchQuery:
    """Search conditions. Serialise with :meth:`to_condition`.

    Defaults mirror the web app: 販売中 only, おすすめ順 (01 §3.1). Note that
    ``status=[]`` means *everything* (on sale + trading + sold out), not "unset" —
    take-kun/mercapi defaults to that and so returns sold items unexpectedly.
    """

    keyword: str = ""
    exclude_keyword: str = ""
    sort_by: Sort = Sort.SCORE
    order_by: Order = Order.DESC
    statuses: tuple[Status, ...] = (Status.ON_SALE,)
    size_id_values: tuple[str, ...] = ()
    category_ids: tuple[int, ...] = ()
    brand_ids: tuple[int, ...] = ()
    seller_id_values: tuple[str, ...] = ()
    price_min: int = 0
    price_max: int = 0
    condition_ids: tuple[int, ...] = ()
    shipping_payer_ids: tuple[int, ...] = ()
    shipping_from_areas: tuple[int, ...] = ()
    shipping_methods: tuple[ShippingMethod, ...] = ()
    color_ids: tuple[int, ...] = ()
    has_coupon: bool = False
    attribute_filters: tuple[AttributeFilter, ...] = ()
    pending_attributes: tuple[tuple[str, tuple[str, ...]], ...] = ()
    pending_sizes: tuple[tuple[str, tuple[str, ...]], ...] = ()
    item_type_values: tuple[ItemType, ...] = ()
    sku_ids: tuple[str, ...] = ()
    shop_ids: tuple[str, ...] = ()
    exclude_shipping_method_ids: tuple[int, ...] = ()
    created_after_ts: int | None = None
    created_before_ts: int | None = None
    thumbnail_types: tuple[ThumbnailType, ...] = ()
    extra: dict[str, Any] = field(default_factory=dict)

    # -- builders -------------------------------------------------------------

    def with_keyword(self, keyword: str) -> Self:
        return dataclasses.replace(self, keyword=keyword)

    def exclude(self, keyword: str) -> Self:
        return dataclasses.replace(self, exclude_keyword=keyword)

    def sort(self, sort_by: Sort, order_by: Order = Order.DESC) -> Self:
        """Warn on a combination the web UI does not offer (01 §3.5 — it is ignored).

        A sort that belongs to another endpoint gets its own message: reaching this
        method with one means it is headed for ``entities:search``, which is precisely
        where it does nothing. ``search_by_image`` never comes through here.
        """
        elsewhere = ENDPOINT_ONLY_SORTS.get(sort_by)
        if elsewhere is not None:
            warnings.warn(f"{sort_by.value} {elsewhere}", UserWarning, stacklevel=2)
        elif (sort_by, order_by) not in WEB_SORT_COMBINATIONS:
            warnings.warn(
                f"{sort_by.value} + {order_by.value} is not one of the five combinations the web "
                f"UI offers; the server ignores it and sorts descending (01 §3.5)",
                UserWarning,
                stacklevel=2,
            )
        return dataclasses.replace(self, sort_by=sort_by, order_by=order_by)

    def price(self, minimum: int = 0, maximum: int = 0) -> Self:
        """``0`` means unbounded on either side."""
        if maximum != 0 and minimum > maximum:
            raise ValueError(f"price_min ({minimum}) must not exceed price_max ({maximum})")
        return dataclasses.replace(self, price_min=int(minimum), price_max=int(maximum))

    def status(self, *statuses: Status) -> Self:
        """``status()`` with no argument means *all* statuses, like the web 「すべて」."""
        return dataclasses.replace(self, statuses=tuple(statuses))

    def sold_out(self) -> Self:
        """The web 「売り切れ」 checkbox = SOLD_OUT + TRADING."""
        return self.status(Status.SOLD_OUT, Status.TRADING)

    def conditions(self, *conditions: Condition | int) -> Self:
        return dataclasses.replace(self, condition_ids=_ints(conditions))

    def shipping_payer(self, *payers: ShippingPayer | int) -> Self:
        return dataclasses.replace(self, shipping_payer_ids=_ints(payers))

    def categories(self, *category_ids: int | str) -> Self:
        return dataclasses.replace(self, category_ids=_ints(category_ids))

    def brands(self, *brand_ids: int | str) -> Self:
        return dataclasses.replace(self, brand_ids=_ints(brand_ids))

    def size_ids(self, *size_ids: str | int) -> Self:
        """Legacy ``sizeId`` filter. Values are strings; integers give 400."""
        return dataclasses.replace(self, size_id_values=_strs(size_ids))

    def seller_ids(self, *seller_ids: str | int) -> Self:
        return dataclasses.replace(self, seller_id_values=_strs(seller_ids))

    def shops(self, *shop_ids: str) -> Self:
        return dataclasses.replace(self, shop_ids=_strs(shop_ids))

    def skus(self, *sku_ids: str) -> Self:
        return dataclasses.replace(self, sku_ids=_strs(sku_ids))

    def attr(self, section: AttributeSection | str, *display_names_ja: str) -> Self:
        """Filter on a dynamic attribute by Japanese display name.

        Values in one section are OR-ed, different sections AND-ed (01 §3.2), so
        ``.attr(COLOR, "ブラック系", "ホワイト系")`` means "black or white". Names are
        resolved to UUIDs at serialisation time by the client's resolver — there is no
        negative filter in the API, so "exclude auctions" is expressed as
        ``.attr(LISTING_FORMAT, "通常出品")``.
        """
        if not display_names_ja:
            raise ValueError("at least one display name is required")
        section_id = section.value if isinstance(section, AttributeSection) else section
        pending = (*self.pending_attributes, (section_id, tuple(display_names_ja)))
        return dataclasses.replace(self, pending_attributes=pending)

    def sizes(self, group_name_ja: str, *names: str) -> Self:
        """Size filter via the attribute route: group name → leaf names (02 §5).

        Equivalent to :meth:`size_ids` — the legacy ``sizeId`` values and the attribute
        UUIDs return the same result set (verified in probe6).
        """
        if not names:
            raise ValueError("at least one size name is required")
        pending = (*self.pending_sizes, (group_name_ja, tuple(names)))
        return dataclasses.replace(self, pending_sizes=pending)

    def attributes(self, *filters: AttributeFilter) -> Self:
        """Add already-resolved attribute filters (UUIDs known up front).

        Use ``.attr(section, *display_names)`` when you would rather name the values
        and let the resolver look the UUIDs up.
        """
        return dataclasses.replace(self, attribute_filters=(*self.attribute_filters, *filters))

    def item_types(self, *types: ItemType) -> Self:
        return dataclasses.replace(self, item_type_values=tuple(types))

    def shipping_method(self, *methods: ShippingMethod) -> Self:
        return dataclasses.replace(self, shipping_methods=tuple(methods))

    def shipping_from(self, *prefecture_ids: int) -> Self:
        """App-only 「発送元の地域」 filter. 1 北海道, 13 東京都 confirmed (02 §6)."""
        return dataclasses.replace(self, shipping_from_areas=_ints(prefecture_ids))

    def exclude_shipping_methods(self, *method_ids: int) -> Self:
        return dataclasses.replace(self, exclude_shipping_method_ids=_ints(method_ids))

    def created_after(self, when: int | datetime) -> Self:
        """Filter on ``created >= when``; serialisation adds the JST offset."""
        return dataclasses.replace(self, created_after_ts=_timestamp(when))

    def created_before(self, when: int | datetime) -> Self:
        return dataclasses.replace(self, created_before_ts=_timestamp(when))

    def thumbnail_type(self, *types: ThumbnailType) -> Self:
        """Ask for a specific thumbnail image format.

        This is a *top-level* body field, not part of ``searchCondition``, so it is
        carried on the query and read by ``build_search_body``. Default (no call) sends
        an empty array, which the server answers with webp URLs (01 §3.1).
        """
        return dataclasses.replace(self, thumbnail_types=tuple(types))

    def with_extra(self, **fields: Any) -> Self:
        """Pass through a ``searchCondition`` field this package does not model yet."""
        merged = {**self.extra, **fields}
        return dataclasses.replace(self, extra=merged)

    # -- serialisation --------------------------------------------------------

    def to_condition(self, resolver: AttributeResolverProtocol | None = None) -> dict[str, Any]:
        """Always emit the 22 keys, then the hidden/extra ones that are set."""
        condition: dict[str, Any] = {
            "keyword": self.keyword,
            "excludeKeyword": self.exclude_keyword,
            "sort": self.sort_by.value,
            "order": self.order_by.value,
            "status": [s.request_value for s in self.statuses],
            "sizeId": list(self.size_id_values),
            "categoryId": list(self.category_ids),
            "brandId": list(self.brand_ids),
            "sellerId": list(self.seller_id_values),
            "priceMin": self.price_min,
            "priceMax": self.price_max,
            "itemConditionId": list(self.condition_ids),
            "shippingPayerId": list(self.shipping_payer_ids),
            "shippingFromArea": list(self.shipping_from_areas),
            "shippingMethod": [m.value for m in self.shipping_methods],
            "colorId": list(self.color_ids),
            "hasCoupon": self.has_coupon,
            "attributes": self._attributes(resolver),
            "itemTypes": [t.value for t in self.item_type_values],
            "skuIds": list(self.sku_ids),
            "shopIds": list(self.shop_ids),
            "excludeShippingMethodIds": list(self.exclude_shipping_method_ids),
        }
        if self.created_after_ts is not None:
            condition["createdAfterDate"] = str(self.created_after_ts + JST_OFFSET_SECONDS)
        if self.created_before_ts is not None:
            condition["createdBeforeDate"] = str(self.created_before_ts + JST_OFFSET_SECONDS)
        condition.update(self.extra)
        return condition

    def _attributes(self, resolver: AttributeResolverProtocol | None) -> list[dict[str, Any]]:
        """Merge every filter for one section into a single ``{id, values}`` entry.

        Values inside a section are OR-ed, different sections are AND-ed (01 §3.2).
        Named filters added with ``.attr()`` are resolved here, at serialisation time.
        """
        merged: dict[str, list[str]] = {}
        for attribute in self.attribute_filters:
            merged.setdefault(attribute.id, [])
            for value in attribute.values:
                if value not in merged[attribute.id]:
                    merged[attribute.id].append(value)
        if self.pending_attributes or self.pending_sizes:
            if resolver is None:
                from carimer.transport.errors import UnknownFacetValue

                pending = ", ".join(
                    [section for section, _ in self.pending_attributes]
                    + [group for group, _ in self.pending_sizes]
                )
                raise UnknownFacetValue(
                    f"named attribute filters ({pending}) need an AttributeResolver; "
                    "call the query through a Client, which supplies one"
                )
            for section, names in self.pending_attributes:
                _merge(merged, resolver.resolve(section, *names))
            for group, names in self.pending_sizes:
                _merge(merged, _resolve_size(resolver, group, names))
        return [{"id": key, "values": values} for key, values in merged.items()]

    def with_resolved(self, *filters: AttributeFilter) -> Self:
        """Replace the pending named filters with already-resolved ones.

        ``AsyncClient`` uses this: ``to_condition()`` is synchronous, so the async
        resolver runs first and hands the result back here.
        """
        return dataclasses.replace(
            self,
            attribute_filters=(*self.attribute_filters, *filters),
            pending_attributes=(),
            pending_sizes=(),
        )


def _merge(merged: dict[str, list[str]], attribute: AttributeFilter) -> None:
    values = merged.setdefault(attribute.id, [])
    for value in attribute.values:
        if value not in values:
            values.append(value)


def _resolve_size(resolver: AttributeResolverProtocol, group: str, names: tuple[str, ...]) -> AttributeFilter:
    resolve_size = getattr(resolver, "resolve_size", None)
    if resolve_size is None:
        raise TypeError(f"{type(resolver).__name__} cannot resolve size groups")
    resolved: AttributeFilter = resolve_size(group, *names)
    return resolved


def _ints(values: Iterable[int | str]) -> tuple[int, ...]:
    return tuple(int(value) for value in values)


def _strs(values: Iterable[str | int]) -> tuple[str, ...]:
    return tuple(str(value) for value in values)


def _timestamp(when: int | datetime) -> int:
    if isinstance(when, datetime):
        return int(when.timestamp())
    return int(when)


def as_query(query: SearchQuery | str) -> SearchQuery:
    """Accept a bare keyword wherever a query is expected."""
    return SearchQuery(keyword=query) if isinstance(query, str) else query


def condition_keys() -> Sequence[str]:
    return CONDITION_KEYS
