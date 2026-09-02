"""Dynamic attribute filters (01 §3.2 ``attributes``, 02 §1, §3-5).

Six web sidebar sections (色, 割引オプション, あんしん鑑定, 出品形式, 保証付き整備品,
タイムセール割引率) plus サイズ are sent as
``attributes: [{"id": <section UUID>, "values": [<value UUID>]}]``. Any other key
spelling (``valueIds`` …) is silently ignored by the server, which is why none of the
three reference wrappers supports these filters.

Section UUIDs are the only attribute constants in the code (03 §1.2); every *value*
UUID is resolved at runtime from ``facets:suggest`` and falls back to the bundled
snapshot only if the live lookup fails.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from carimer.transport.errors import CarimerError, UnknownFacetValue

if TYPE_CHECKING:
    from carimer.catalog.facets_client import AsyncFacetsClient, FacetsClient
    from carimer.models.facets import Facet

__all__ = [
    "NO_MATCH_VALUE",
    "AsyncAttributeResolver",
    "AttributeFilter",
    "AttributeResolver",
    "AttributeResolverProtocol",
    "AttributeSection",
]

_log = logging.getLogger(__name__)

#: The shared "none of the above" value used by 通常商品 / 通常出品 / 利用不可 (02 §4).
NO_MATCH_VALUE = "B38F1DC9286E0B80812D9B19DB14298C1FF1116CA8332D9EE9061026635C9088"


class AttributeSection(StrEnum):
    """Attribute section UUIDs (02 §1 snapshot).

    A change here is detected by ``scripts/health_check.py``, which compares the live
    section list against the bundled fallback.
    """

    COLOR = "7bd3eacc-ae45-4d73-bc57-a611c9432014"
    SIZE = "f42ae390-04ff-46ea-808b-f5d97cb45db4"
    DISCOUNT = "47295d80-5839-4237-bbfc-deb44b4e7999"
    APPRAISAL = "e6cec404-5b34-46aa-8316-cda6695a85f3"
    LISTING_FORMAT = "d664efe3-ae5a-4824-b729-e789bf93aba9"
    REFURBISHED = "88ddea4d-0c5e-4117-81e9-02c0848cbab4"
    TIME_SALE = "015c63d8-e3ec-4a66-b1b1-030c278ad7cc"


@dataclass(frozen=True, slots=True)
class AttributeFilter:
    """One section and the value UUIDs selected in it (OR within a section)."""

    id: str
    values: tuple[str, ...]

    def to_condition(self) -> dict[str, object]:
        return {"id": self.id, "values": list(self.values)}


@runtime_checkable
class AttributeResolverProtocol(Protocol):
    """Turns a section identifier plus Japanese display names into UUIDs."""

    def resolve(self, section: str, *display_names_ja: str) -> AttributeFilter: ...


def _match(facets: list[Facet], name: str) -> str | None:
    """Exact match on ``displayNamesMap.ja``. No alias table: a near-miss would filter
    on the wrong value silently.
    """
    for facet in facets:
        if facet.name == name and facet.searchable_value:
            return facet.searchable_value
    return None


def _fallback_values(fallback: dict[str, dict[str, str]], section: str) -> dict[str, str]:
    return fallback.get(section) or {}


class AttributeResolver:
    """Resolves display names to value UUIDs: cache → ``facets:suggest`` → fallback.

    ``fallback`` maps ``section UUID → {display name: value UUID}`` and comes from the
    bundled ``fallback_catalog.json``. It is used only when the live lookup fails, and
    always with a warning, because the snapshot can be stale.
    """

    def __init__(
        self,
        facets: FacetsClient | None = None,
        fallback: dict[str, dict[str, str]] | None = None,
    ) -> None:
        self._facets = facets
        self._fallback = fallback or {}

    def resolve(self, section: str, *display_names_ja: str) -> AttributeFilter:
        if not display_names_ja:
            raise ValueError("at least one display name is required")
        values = tuple(self._resolve_one(section, name) for name in display_names_ja)
        return AttributeFilter(id=section, values=values)

    def resolve_size(self, group_name_ja: str, *names: str) -> AttributeFilter:
        """Two-step lookup: size group → leaf values (02 §5)."""
        section = AttributeSection.SIZE.value
        group_value = self._resolve_one(section, group_name_ja)
        leaves = self._values(section, group_value)
        resolved: list[str] = []
        for name in names:
            value = _match(leaves, name) or _fallback_values(self._fallback, group_value).get(name)
            if value is None:
                raise UnknownFacetValue(
                    f"size {name!r} not found in group {group_name_ja!r}; "
                    f"available: {', '.join(sorted(f.name or '' for f in leaves))}"
                )
            resolved.append(value)
        return AttributeFilter(id=section, values=tuple(resolved))

    def _resolve_one(self, section: str, name: str) -> str:
        if name in {"通常商品", "通常出品", "利用不可"}:
            return NO_MATCH_VALUE
        value = _match(self._values(section), name)
        if value is not None:
            return value
        fallback = _fallback_values(self._fallback, section).get(name)
        if fallback is not None:
            _log.warning(
                "attribute value %r for section %s came from the bundled snapshot; "
                "the live facets lookup did not return it",
                name,
                section,
            )
            return fallback
        known = ", ".join(sorted(f.name or "" for f in self._values(section)))
        raise UnknownFacetValue(f"no attribute value named {name!r} in section {section}; known: {known}")

    def _values(self, section: str, group_value: str = "") -> list[Facet]:
        if self._facets is None:
            return []
        try:
            return self._facets.children(section, group_value)
        except CarimerError as exc:  # transport/parse failure → snapshot
            _log.warning("facets lookup for section %s failed (%s); using the snapshot", section, exc)
            return []


class AsyncAttributeResolver:
    """Async twin of :class:`AttributeResolver`.

    ``SearchQuery.to_condition()`` is synchronous, so ``AsyncClient`` resolves pending
    named filters with ``prepare()`` before serialising the query.
    """

    def __init__(
        self,
        facets: AsyncFacetsClient | None = None,
        fallback: dict[str, dict[str, str]] | None = None,
    ) -> None:
        self._facets = facets
        self._fallback = fallback or {}

    async def resolve(self, section: str, *display_names_ja: str) -> AttributeFilter:
        if not display_names_ja:
            raise ValueError("at least one display name is required")
        values = tuple([await self._resolve_one(section, name) for name in display_names_ja])
        return AttributeFilter(id=section, values=values)

    async def resolve_size(self, group_name_ja: str, *names: str) -> AttributeFilter:
        section = AttributeSection.SIZE.value
        group_value = await self._resolve_one(section, group_name_ja)
        leaves = await self._values(section, group_value)
        resolved: list[str] = []
        for name in names:
            value = _match(leaves, name) or _fallback_values(self._fallback, group_value).get(name)
            if value is None:
                raise UnknownFacetValue(f"size {name!r} not found in group {group_name_ja!r}")
            resolved.append(value)
        return AttributeFilter(id=section, values=tuple(resolved))

    async def _resolve_one(self, section: str, name: str) -> str:
        if name in {"通常商品", "通常出品", "利用不可"}:
            return NO_MATCH_VALUE
        value = _match(await self._values(section), name)
        if value is not None:
            return value
        fallback = _fallback_values(self._fallback, section).get(name)
        if fallback is not None:
            _log.warning("attribute value %r for section %s came from the bundled snapshot", name, section)
            return fallback
        raise UnknownFacetValue(f"no attribute value named {name!r} in section {section}")

    async def _values(self, section: str, group_value: str = "") -> list[Facet]:
        if self._facets is None:
            return []
        try:
            return await self._facets.children(section, group_value)
        except CarimerError as exc:
            _log.warning("facets lookup for section %s failed (%s); using the snapshot", section, exc)
            return []
