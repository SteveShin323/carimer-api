"""Facet-side models: the ``facets:suggest`` entries and the category tree nodes."""

from __future__ import annotations

from typing import Any, Self

from carimer.models.common import RawModel, to_int, to_str

__all__ = ["Brand", "CategoryNode", "Facet", "FacetSection", "Size", "SizeGroup"]


class Brand(RawModel):
    """``items[].itemBrand`` — ``{"id": "3272", "name": "Apple", "subName": "Apple"}``."""

    id: int | None = None
    name: str | None = None
    sub_name: str | None = None

    @classmethod
    def from_api(cls, payload: dict[str, Any] | None) -> Brand | None:
        if not payload:
            return None
        return cls(
            id=to_int(payload.get("id")),
            name=to_str(payload.get("name")),
            sub_name=to_str(payload.get("subName") or payload.get("sub_name")),
            raw=payload,
        )


class Size(RawModel):
    """``items[].itemSize`` — the legacy numeric size id plus its label."""

    id: str | None = None
    name: str | None = None

    @classmethod
    def from_api(cls, payload: dict[str, Any] | None) -> Size | None:
        if not payload:
            return None
        return cls(id=to_str(payload.get("id")), name=to_str(payload.get("name")), raw=payload)


class Facet(RawModel):
    """One entry from ``facets:suggest`` (01 §4.2).

    ``searchable_value`` is what goes into ``searchCondition`` — a plain value for the
    fixed filters (``category_id`` → ``859``) or a value UUID for the dynamic attribute
    sections. ``facet_id`` is passed straight back to fetch the children.
    No count is provided by the API.
    """

    facet_id: str
    name: str | None = None
    name_en: str | None = None
    searchable_key: str | None = None
    searchable_value: str | None = None
    leaf: bool = True
    selected: bool = False
    name_reading: str | None = None
    color_hex: str | None = None

    @property
    def id_as_int(self) -> int | None:
        """``searchable_value`` as an int, for ``category_id`` / ``brand_id`` facets."""
        return to_int(self.searchable_value)

    @classmethod
    def from_api(cls, payload: dict[str, Any]) -> Self:
        names = payload.get("displayNamesMap") or {}
        metadata = payload.get("metadata") or {}
        return cls(
            facet_id=to_str(payload.get("facetId")) or "",
            name=to_str(names.get("ja")),
            name_en=to_str(names.get("en")),
            searchable_key=to_str(payload.get("searchableKey")),
            searchable_value=to_str(payload.get("searchableValue")),
            leaf=bool(payload.get("leaf")),
            selected=bool(payload.get("selected")),
            name_reading=to_str(metadata.get("nameReading")),
            color_hex=to_str(metadata.get("colorHex")),
            raw=payload,
        )


class FacetSection(Facet):
    """A top-level sidebar section (the ``facetId: ""`` response).

    For fixed filters ``searchable_value`` is the search field key (``category_id``);
    for the six dynamic sections it is the attribute UUID (02 §1).
    """

    @property
    def is_attribute_section(self) -> bool:
        """True when the section is filtered through ``attributes`` rather than a field."""
        value = self.searchable_value or ""
        return len(value) == 36 and value.count("-") == 4


class CategoryNode(RawModel):
    """A node of the current (ntiers) category tree, from
    ``master/v2/datasets/item_categories`` (01 §9).
    """

    id: int
    name: str
    level: int | None = None
    parent_id: int | None = None
    parent_name: str | None = None
    root_id: int | None = None
    root_name: str | None = None
    display_order: int | None = None
    has_child: bool = False
    short_label: str | None = None

    @classmethod
    def from_api(cls, payload: dict[str, Any]) -> CategoryNode | None:
        node_id = to_int(payload.get("id"))
        name = to_str(payload.get("name"))
        if node_id is None or name is None:
            return None
        return cls(
            id=node_id,
            name=name,
            level=to_int(payload.get("level")),
            parent_id=to_int(payload.get("parentCategoryId")) or None,
            parent_name=to_str(payload.get("parentCategoryName")),
            root_id=to_int(payload.get("rootCategoryId")) or None,
            root_name=to_str(payload.get("rootCategoryName")),
            display_order=to_int(payload.get("displayOrder")),
            has_child=bool(payload.get("hasChild")),
            short_label=to_str(payload.get("shortLabel")),
            raw=payload,
        )


class SizeGroup(RawModel):
    """A size group (洋服のサイズ, メンズ靴のサイズ …) and its value UUID."""

    name: str
    value: str
    facet_id: str

    @classmethod
    def from_facet(cls, facet: Facet) -> SizeGroup | None:
        if not facet.name or not facet.searchable_value:
            return None
        return cls(name=facet.name, value=facet.searchable_value, facet_id=facet.facet_id, raw=facet.raw)
