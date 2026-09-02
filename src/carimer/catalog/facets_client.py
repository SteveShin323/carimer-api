"""``facets:suggest`` wrapper — the source of the web sidebar (01 §4, 03 §3.8).

None of the three reference wrappers knows this endpoint, which is why they ship a
static (and now outdated) category tree and cannot express the six attribute filters.
Everything here is fetched at runtime and cached for 24 h.

Cache keys are ``(facet_id, facet_query)`` only: requests are always issued with an
*empty* search condition, because ``selected`` and ``relevantFacets`` depend on the
condition and would poison the cache. ``category_relevant`` therefore takes a query and
is never cached.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

from carimer.api import search as search_api
from carimer.catalog.cache import TTLCache
from carimer.models.facets import CategoryNode, Facet, FacetSection, SizeGroup
from carimer.search.query import SearchQuery

if TYPE_CHECKING:
    from carimer.transport.base import Request

__all__ = ["AsyncFacetsClient", "FacetsClient", "cache_key", "parse_facets", "parse_relevant"]

CATEGORY_KEY = "category_id"
BRAND_KEY = "brand_id"
SIZE_SECTION_KEY = "f42ae390-04ff-46ea-808b-f5d97cb45db4"

_EMPTY_CONDITION = SearchQuery().to_condition()


class _Sender(Protocol):
    def send(self, request: Request) -> dict[str, Any]: ...


class _AsyncSender(Protocol):
    async def send(self, request: Request) -> dict[str, Any]: ...
    @property
    def search_session_id(self) -> str: ...


def cache_key(facet_id: str, facet_query: str | None) -> str:
    return f"{facet_id}\x00{facet_query or ''}"


def build(
    facet_id: str,
    *,
    facet_query: str | None,
    session_id: str,
    condition: dict[str, Any] | None = None,
) -> Request:
    return search_api.facets_request(
        condition if condition is not None else _EMPTY_CONDITION,
        facet_id,
        facet_query=facet_query,
        with_relevant=True,
        session_id=session_id,
    )


def _section(payload: dict[str, Any], facet_id: str) -> dict[str, Any]:
    suggested = payload.get("suggestedFacetMap") or {}
    entry = suggested.get(facet_id)
    if entry is None and len(suggested) == 1:
        # The server echoes the requested facetId as the key; be forgiving if it differs.
        entry = next(iter(suggested.values()))
    return entry or {}


def parse_facets(payload: dict[str, Any], facet_id: str) -> list[dict[str, Any]]:
    facets = ((_section(payload, facet_id).get("suggestFacets")) or {}).get("facets")
    return [raw for raw in facets or [] if raw]


def parse_relevant(payload: dict[str, Any], facet_id: str) -> list[dict[str, Any]]:
    facets = ((_section(payload, facet_id).get("relevantFacets")) or {}).get("facets")
    return [raw for raw in facets or [] if raw]


class _FacetsBase:
    def __init__(self, *, cache: TTLCache | None = None) -> None:
        self._cache = cache or TTLCache()

    @property
    def cache(self) -> TTLCache:
        return self._cache

    @staticmethod
    def _facets(raw_facets: list[dict[str, Any]]) -> list[Facet]:
        return [Facet.from_api(raw) for raw in raw_facets]

    @staticmethod
    def _sections(raw_facets: list[dict[str, Any]]) -> list[FacetSection]:
        return [FacetSection.from_api(raw) for raw in raw_facets]


class FacetsClient(_FacetsBase):
    """Blocking facets client."""

    def __init__(self, transport: _Sender, *, cache: TTLCache | None = None) -> None:
        super().__init__(cache=cache)
        self._transport = transport

    def _fetch(self, facet_id: str, *, facet_query: str | None = None) -> list[dict[str, Any]]:
        key = cache_key(facet_id, facet_query)
        cached = self._cache.get(key)
        if cached is not None:
            return list(cached)
        session_id = getattr(self._transport, "search_session_id", "")
        payload = self._transport.send(build(facet_id, facet_query=facet_query, session_id=session_id))
        facets = parse_facets(payload, facet_id)
        self._cache.set(key, facets)
        return facets

    def sections(self) -> list[FacetSection]:
        """The 16 sidebar sections (02 §1)."""
        return self._sections(self._fetch(""))

    def children(self, key: str, value: str = "", *, facet_query: str | None = None) -> list[Facet]:
        """Children of ``key``/``value`` — e.g. ``("category_id", "7")``."""
        return self._facets(self._fetch(search_api.encode_facet_id(key, value), facet_query=facet_query))

    def category_children(self, category_id: int | str = "") -> list[Facet]:
        return self.children(CATEGORY_KEY, str(category_id) if category_id != "" else "")

    def category_relevant(self, query: SearchQuery | str) -> list[Facet]:
        """Keyword-driven category suggestions.

        Only populated when the query has a keyword; a category-only request returns
        none (01 §4.1, probe7). Never cached, since it depends on the condition.
        """
        condition = (SearchQuery(keyword=query) if isinstance(query, str) else query).to_condition()
        facet_id = search_api.encode_facet_id(CATEGORY_KEY)
        session_id = getattr(self._transport, "search_session_id", "")
        payload = self._transport.send(
            build(facet_id, facet_query=None, session_id=session_id, condition=condition)
        )
        return self._facets(parse_relevant(payload, facet_id))

    def brands(self, name_query: str) -> list[Facet]:
        """Brand search by (partial) name; matches both romaji and kana."""
        return self.children(BRAND_KEY, facet_query=name_query)

    def size_groups(self) -> list[SizeGroup]:
        groups = [SizeGroup.from_facet(facet) for facet in self.children(SIZE_SECTION_KEY)]
        return [group for group in groups if group is not None]

    def sizes(self, group_value: str) -> list[Facet]:
        return self.children(SIZE_SECTION_KEY, group_value)

    def attribute_values(self, section_uuid: str) -> list[Facet]:
        """Values of a dynamic attribute section (色, 出品形式 …)."""
        return self.children(section_uuid)


class AsyncFacetsClient(_FacetsBase):
    """Asyncio facets client. Same names, awaited."""

    def __init__(self, transport: _AsyncSender, *, cache: TTLCache | None = None) -> None:
        super().__init__(cache=cache)
        self._transport = transport

    async def _fetch(self, facet_id: str, *, facet_query: str | None = None) -> list[dict[str, Any]]:
        key = cache_key(facet_id, facet_query)
        cached = self._cache.get(key)
        if cached is not None:
            return list(cached)
        session_id = getattr(self._transport, "search_session_id", "")
        payload = await self._transport.send(build(facet_id, facet_query=facet_query, session_id=session_id))
        facets = parse_facets(payload, facet_id)
        self._cache.set(key, facets)
        return facets

    async def sections(self) -> list[FacetSection]:
        return self._sections(await self._fetch(""))

    async def children(self, key: str, value: str = "", *, facet_query: str | None = None) -> list[Facet]:
        facet_id = search_api.encode_facet_id(key, value)
        return self._facets(await self._fetch(facet_id, facet_query=facet_query))

    async def category_children(self, category_id: int | str = "") -> list[Facet]:
        return await self.children(CATEGORY_KEY, str(category_id) if category_id != "" else "")

    async def category_relevant(self, query: SearchQuery | str) -> list[Facet]:
        condition = (SearchQuery(keyword=query) if isinstance(query, str) else query).to_condition()
        facet_id = search_api.encode_facet_id(CATEGORY_KEY)
        session_id = getattr(self._transport, "search_session_id", "")
        payload = await self._transport.send(
            build(facet_id, facet_query=None, session_id=session_id, condition=condition)
        )
        return self._facets(parse_relevant(payload, facet_id))

    async def brands(self, name_query: str) -> list[Facet]:
        return await self.children(BRAND_KEY, facet_query=name_query)

    async def size_groups(self) -> list[SizeGroup]:
        groups = [SizeGroup.from_facet(facet) for facet in await self.children(SIZE_SECTION_KEY)]
        return [group for group in groups if group is not None]

    async def sizes(self, group_value: str) -> list[Facet]:
        return await self.children(SIZE_SECTION_KEY, group_value)

    async def attribute_values(self, section_uuid: str) -> list[Facet]:
        return await self.children(section_uuid)


def nodes_from_dataset(payload: dict[str, Any]) -> list[CategoryNode]:
    """``master/v2/datasets/item_categories`` → category nodes."""
    nodes = [CategoryNode.from_api(raw) for raw in payload.get("itemCategories") or [] if raw]
    return [node for node in nodes if node is not None]
