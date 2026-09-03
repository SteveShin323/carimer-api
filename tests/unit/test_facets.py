"""Phase 3: facets client, cache, attribute resolution and the category tree."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
import respx

from carimer import Client, SearchQuery, TransportOptions
from carimer.api.search import FACETS_URL, encode_facet_id
from carimer.catalog.cache import TTLCache
from carimer.catalog.categories import CategoryTree
from carimer.catalog.facets_client import FacetsClient, nodes_from_dataset
from carimer.catalog.fallback import fallback_sections, fallback_value_map
from carimer.models.facets import CategoryNode
from carimer.search.attributes import NO_MATCH_VALUE, AttributeResolver, AttributeSection
from carimer.transport.base import TransportOptions as Options
from carimer.transport.errors import TransportError, UnknownFacetValue
from carimer.transport.sync import SyncTransport

FAST = TransportOptions(min_interval=0)
COLOR = AttributeSection.COLOR.value


def _facet(name: str, value: str, *, leaf: bool = True, key: str = "") -> dict[str, Any]:
    return {
        "facetId": encode_facet_id(key or "x", value),
        "displayNamesMap": {"ja": name},
        "searchableKey": key,
        "searchableValue": value,
        "leaf": leaf,
        "selected": False,
        "metadata": None,
    }


def _facets_response(facet_id: str, facets: list[dict[str, Any]], relevant: list | None = None) -> Any:
    return httpx.Response(
        200,
        json={
            "suggestedFacetMap": {
                facet_id: {
                    "suggestFacets": {"facets": facets, "nextPageToken": ""},
                    "selectedPaths": {},
                    "relevantFacets": {"facets": relevant or []},
                }
            }
        },
    )


# -- cache --------------------------------------------------------------------


def test_cache_expires_and_can_be_cleared() -> None:
    now = [0.0]
    cache = TTLCache(ttl=10, clock=lambda: now[0])
    cache.set("k", [1])
    assert cache.get("k") == [1]
    now[0] = 9.9
    assert cache.get("k") == [1]
    now[0] = 10.1
    assert cache.get("k") is None


def test_cache_disk_layer_round_trips(tmp_path: Any) -> None:
    cache = TTLCache(cache_dir=tmp_path)
    cache.set("k", {"a": 1})
    reopened = TTLCache(cache_dir=tmp_path)
    assert reopened.get("k") == {"a": 1}


def test_cache_without_dir_does_not_touch_disk(tmp_path: Any) -> None:
    TTLCache().set("k", 1)
    assert not list(tmp_path.iterdir())


# -- facets client ------------------------------------------------------------


def test_sections_are_fetched_once_and_then_cached() -> None:
    facet_id = ""
    with respx.mock as mock:
        route = mock.post(FACETS_URL).mock(
            return_value=_facets_response(facet_id, [_facet("色", COLOR, leaf=False)])
        )
        with SyncTransport(FAST) as transport:
            facets = FacetsClient(transport)
            first = facets.sections()
            second = facets.sections()
    assert route.call_count == 1, "the second call must come from the cache"
    assert [s.name for s in first] == ["色"] == [s.name for s in second]
    assert first[0].is_attribute_section is True


def test_section_is_attribute_section_only_for_uuid_values() -> None:
    with respx.mock as mock:
        mock.post(FACETS_URL).mock(
            return_value=_facets_response(
                "", [_facet("カテゴリー", "category_id", leaf=False), _facet("色", COLOR, leaf=False)]
            )
        )
        with SyncTransport(FAST) as transport:
            sections = FacetsClient(transport).sections()
    by_name = {s.name: s for s in sections}
    assert by_name["カテゴリー"].is_attribute_section is False
    assert by_name["色"].is_attribute_section is True


def test_children_requests_the_encoded_facet_id() -> None:
    facet_id = encode_facet_id("category_id", "7")
    with respx.mock as mock:
        route = mock.post(FACETS_URL).mock(
            return_value=_facets_response(
                facet_id, [_facet("スマートフォン・携帯電話", "100", key="category_id")]
            )
        )
        with SyncTransport(FAST) as transport:
            children = FacetsClient(transport).category_children(7)
    body = json.loads(route.calls[0].request.content)
    assert body["facetRequests"][0]["facetId"] == facet_id
    assert children[0].id_as_int == 100


def test_facets_requests_use_an_empty_condition_so_the_cache_stays_valid() -> None:
    with respx.mock as mock:
        route = mock.post(FACETS_URL).mock(return_value=_facets_response(encode_facet_id("brand_id", ""), []))
        with SyncTransport(FAST) as transport:
            FacetsClient(transport).brands("apple")
    body = json.loads(route.calls[0].request.content)
    assert body["searchCondition"]["keyword"] == ""
    assert body["facetRequests"][0]["facetQuery"] == "apple"


def test_brand_query_is_part_of_the_cache_key() -> None:
    facet_id = encode_facet_id("brand_id", "")
    with respx.mock as mock:
        route = mock.post(FACETS_URL).mock(
            return_value=_facets_response(facet_id, [_facet("Apple", "3272", key="brand_id")])
        )
        with SyncTransport(FAST) as transport:
            facets = FacetsClient(transport)
            facets.brands("apple")
            facets.brands("apple")
            facets.brands("nike")
    assert route.call_count == 2


def test_category_relevant_sends_the_query_and_is_never_cached() -> None:
    facet_id = encode_facet_id("category_id", "")
    with respx.mock as mock:
        route = mock.post(FACETS_URL).mock(
            return_value=_facets_response(
                facet_id, [], relevant=[_facet("スマートフォン本体", "859", key="category_id")]
            )
        )
        with SyncTransport(FAST) as transport:
            facets = FacetsClient(transport)
            first = facets.category_relevant(SearchQuery("iphone 15"))
            facets.category_relevant(SearchQuery("iphone 15"))
    assert route.call_count == 2
    assert [f.id_as_int for f in first] == [859]
    body = json.loads(route.calls[0].request.content)
    assert body["searchCondition"]["keyword"] == "iphone 15"


# -- attribute resolution -----------------------------------------------------


def test_resolve_hits_the_network_once_then_the_cache() -> None:
    facet_id = encode_facet_id(COLOR, "")
    values = [_facet("ブラック系", "340258ac"), _facet("ホワイト系", "a167b2a8")]
    with respx.mock as mock:
        route = mock.post(FACETS_URL).mock(return_value=_facets_response(facet_id, values))
        with SyncTransport(FAST) as transport:
            resolver = AttributeResolver(FacetsClient(transport))
            first = resolver.resolve(COLOR, "ブラック系", "ホワイト系")
            second = resolver.resolve(COLOR, "ブラック系")
    assert route.call_count == 1
    assert first.values == ("340258ac", "a167b2a8")
    assert second.values == ("340258ac",)


def test_attr_merges_values_of_one_section_into_a_single_entry() -> None:
    facet_id = encode_facet_id(COLOR, "")
    values = [_facet("ブラック系", "340258ac"), _facet("ホワイト系", "a167b2a8")]
    with respx.mock as mock:
        mock.post(FACETS_URL).mock(return_value=_facets_response(facet_id, values))
        with SyncTransport(FAST) as transport:
            resolver = AttributeResolver(FacetsClient(transport))
            condition = SearchQuery("x").attr(COLOR, "ブラック系", "ホワイト系").to_condition(resolver)
    assert condition["attributes"] == [{"id": COLOR, "values": ["340258ac", "a167b2a8"]}]


def test_no_match_name_is_resolved_from_live_facets_first() -> None:
    section = AttributeSection.LISTING_FORMAT.value
    facet_id = encode_facet_id(section, "")
    with respx.mock as mock:
        route = mock.post(FACETS_URL).mock(
            return_value=_facets_response(facet_id, [_facet("通常出品", NO_MATCH_VALUE)])
        )
        with SyncTransport(FAST) as transport:
            resolver = AttributeResolver(FacetsClient(transport), fallback_value_map())
            resolved = resolver.resolve(section, "通常出品")
    assert route.call_count == 1
    assert resolved.values == (NO_MATCH_VALUE,)


def test_no_match_name_must_belong_to_the_requested_section() -> None:
    facet_id = encode_facet_id(COLOR, "")
    with respx.mock as mock:
        route = mock.post(FACETS_URL).mock(
            return_value=_facets_response(facet_id, [_facet("ブラック系", "340258ac")])
        )
        with SyncTransport(FAST) as transport:
            resolver = AttributeResolver(FacetsClient(transport), fallback_value_map())
            with pytest.raises(UnknownFacetValue, match="通常出品"):
                resolver.resolve(COLOR, "通常出品")
    assert route.call_count == 1


def test_no_match_name_uses_validated_constant_when_live_lookup_fails() -> None:
    resolver = AttributeResolver(None)
    section = AttributeSection.LISTING_FORMAT.value

    assert resolver.resolve(section, "通常出品").values == (NO_MATCH_VALUE,)
    with pytest.raises(UnknownFacetValue, match="通常出品"):
        resolver.resolve(COLOR, "通常出品")


def test_falls_back_to_the_snapshot_when_the_lookup_fails(caplog: Any) -> None:
    with respx.mock as mock:
        mock.post(FACETS_URL).mock(side_effect=httpx.ConnectError("offline"))
        with SyncTransport(Options(min_interval=0, max_retries=0, backoff_base=0)) as transport:
            resolver = AttributeResolver(FacetsClient(transport), fallback_value_map())
            resolved = resolver.resolve(COLOR, "ブラック系")
    assert resolved.values == ("340258ac-e220-4722-8c35-7f73b7382831",)
    assert any("snapshot" in record.message for record in caplog.records)


def test_unknown_value_raises_even_with_a_fallback() -> None:
    with respx.mock as mock:
        mock.post(FACETS_URL).mock(return_value=_facets_response(encode_facet_id(COLOR, ""), []))
        with SyncTransport(FAST) as transport:
            resolver = AttributeResolver(FacetsClient(transport), fallback_value_map())
            with pytest.raises(UnknownFacetValue, match="ミッドナイトグリーン"):
                resolver.resolve(COLOR, "ミッドナイトグリーン")


def test_resolver_is_required_for_named_filters() -> None:
    with pytest.raises(UnknownFacetValue, match="AttributeResolver"):
        SearchQuery("x").attr(AttributeSection.COLOR, "ブラック系").to_condition()


def test_size_resolution_is_two_steps() -> None:
    section = AttributeSection.SIZE.value
    group_id = encode_facet_id(section, "")
    leaf_id = encode_facet_id(section, "95862acc")
    with respx.mock as mock:

        def handler(request: httpx.Request) -> httpx.Response:
            facet_id = json.loads(request.content)["facetRequests"][0]["facetId"]
            if facet_id == group_id:
                return _facets_response(group_id, [_facet("洋服のサイズ", "95862acc", leaf=False)])
            return _facets_response(leaf_id, [_facet("M", "d5dbe802"), _facet("L", "7cbcbdb2")])

        mock.post(FACETS_URL).mock(side_effect=handler)
        with SyncTransport(FAST) as transport:
            resolver = AttributeResolver(FacetsClient(transport))
            condition = SearchQuery("x").sizes("洋服のサイズ", "M").to_condition(resolver)
    assert condition["attributes"] == [{"id": section, "values": ["d5dbe802"]}]


def test_bundled_snapshot_has_the_sections_and_colors() -> None:
    values = fallback_value_map()
    colors = values[AttributeSection.COLOR.value]
    assert len(colors) == 16, sorted(colors)
    assert colors["ブラック系"] == "340258ac-e220-4722-8c35-7f73b7382831"
    assert len(fallback_sections()) >= 15
    sizes = values["95862acc-4aef-4ca7-8c94-eb002e71d396"]
    assert sizes["M"] == "d5dbe802-d454-4368-b988-5c14f003e507"


# -- category tree ------------------------------------------------------------


def _node(node_id: int, name: str, parent: int, level: int) -> dict[str, Any]:
    return {
        "id": node_id,
        "name": name,
        "level": level,
        "parentCategoryId": parent,
        "rootCategoryId": 7,
        "displayOrder": node_id,
        "hasChild": level < 3,
    }


TREE_PAYLOAD = {
    "itemCategories": [
        _node(7, "スマホ・タブレット・パソコン", 0, 1),
        _node(100, "スマートフォン・携帯電話", 7, 2),
        _node(859, "スマートフォン本体", 100, 3),
        _node(3088, "ファッション", 0, 1),
    ]
}


def test_category_tree_path_children_and_roots() -> None:
    tree = CategoryTree(nodes_from_dataset(TREE_PAYLOAD))
    assert len(tree) == 4
    assert [node.id for node in tree.path(859)] == [7, 100, 859]
    assert [node.id for node in tree.children(7)] == [100]
    assert {node.id for node in tree.roots()} == {7, 3088}
    assert [node.id for node in tree.search("スマート")] == [100, 859]
    assert tree.get(999) is None
    assert tree.path(999) == []


def test_category_tree_survives_a_cycle() -> None:
    nodes = [
        CategoryNode(id=1, name="a", parent_id=2),
        CategoryNode(id=2, name="b", parent_id=1),
    ]
    assert len(CategoryTree(nodes).path(1)) == 2


def test_categories_loads_the_v2_dataset_with_the_exact_accept_header() -> None:
    url = "https://api.mercari.jp/master/v2/datasets/item_categories"
    with respx.mock as mock:
        route = mock.get(url).mock(return_value=httpx.Response(200, json=TREE_PAYLOAD))
        with Client(options=FAST) as client:
            assert [n.id for n in client.categories.path(859)] == [7, 100, 859]
            client.categories.children(7)  # cached, no second request
    assert route.call_count == 1
    assert route.calls[0].request.headers["accept"] == "application/json"


def test_master_v2_406_surfaces_as_not_acceptable() -> None:
    """The mercapi-node bug: a wrong Accept header answers 406, not JSON (01 §9)."""
    from carimer.transport.errors import NotAcceptableError

    url = "https://api.mercari.jp/master/v2/datasets/item_categories"
    with respx.mock as mock:
        mock.get(url).mock(return_value=httpx.Response(406, text="no accepted candidate variant"))
        with Client(options=FAST) as client, pytest.raises(NotAcceptableError):
            client.categories.load()


async def test_async_client_resolves_named_attributes_before_serialising() -> None:
    from carimer import AsyncClient
    from carimer.api.search import SEARCH_URL

    facet_id = encode_facet_id(COLOR, "")
    with respx.mock as mock:
        mock.post(FACETS_URL).mock(
            return_value=_facets_response(facet_id, [_facet("ブラック系", "340258ac")])
        )
        search = mock.post(SEARCH_URL).mock(
            return_value=httpx.Response(200, json={"meta": {"numFound": "1"}, "items": []})
        )
        async with AsyncClient(options=FAST) as client:
            await client.search(SearchQuery("x").attr(AttributeSection.COLOR, "ブラック系"))
    body = json.loads(search.calls[0].request.content)
    assert body["searchCondition"]["attributes"] == [{"id": COLOR, "values": ["340258ac"]}]


async def test_async_no_match_name_is_resolved_from_live_facets_first() -> None:
    from carimer import AsyncClient
    from carimer.api.search import SEARCH_URL

    section = AttributeSection.LISTING_FORMAT.value
    facet_id = encode_facet_id(section, "")
    with respx.mock as mock:
        facet_route = mock.post(FACETS_URL).mock(
            return_value=_facets_response(facet_id, [_facet("通常出品", NO_MATCH_VALUE)])
        )
        search_route = mock.post(SEARCH_URL).mock(
            return_value=httpx.Response(200, json={"meta": {"numFound": "0"}, "items": []})
        )
        async with AsyncClient(options=FAST) as client:
            await client.search(SearchQuery("x").attr(AttributeSection.LISTING_FORMAT, "通常出品"))

    body = json.loads(search_route.calls[0].request.content)
    assert facet_route.call_count == 1
    assert body["searchCondition"]["attributes"] == [{"id": section, "values": [NO_MATCH_VALUE]}]


def test_transport_error_is_not_swallowed_when_no_fallback_exists() -> None:
    with respx.mock as mock:
        mock.post(FACETS_URL).mock(side_effect=httpx.ConnectError("offline"))
        with SyncTransport(Options(min_interval=0, max_retries=0, backoff_base=0)) as transport:
            facets = FacetsClient(transport)
            with pytest.raises(TransportError):
                facets.sections()
