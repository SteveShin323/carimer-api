"""Phase 2: body builders must reproduce the web-app capture (01 §3.1, §4.1)."""

from __future__ import annotations

from carimer.api.search import (
    build_facets_body,
    build_search_body,
    decode_facet_id,
    encode_facet_id,
    search_request,
)
from carimer.search.query import SearchQuery

# Top-level keys of the 01 §3.1 capture.
CAPTURE_TOP_LEVEL_KEYS = {
    "userId",
    "config",
    "pageSize",
    "pageToken",
    "searchSessionId",
    "source",
    "indexRouting",
    "thumbnailTypes",
    "searchCondition",
    "serviceFrom",
    "withItemBrand",
    "withItemSize",
    "withItemPromotions",
    "withItemSizes",
    "withShopname",
    "useDynamicAttribute",
    "withSuggestedItems",
    "withOfferPricePromotion",
    "withProductSuggest",
    "withParentProducts",
    "withProductArticles",
    "withSearchConditionId",
    "withAuction",
    "laplaceDeviceUuid",
}


def _body(**kwargs: object) -> dict:
    return build_search_body(
        SearchQuery("x").to_condition(),
        session_id="0" * 32,
        device_uuid="dev-uuid",
        **kwargs,  # type: ignore[arg-type]
    )


def test_search_body_key_set_matches_the_capture() -> None:
    assert set(_body()) == CAPTURE_TOP_LEVEL_KEYS


def test_search_body_fixed_values() -> None:
    body = _body()
    assert body["config"] == {"responseToggles": ["QUERY_SUGGESTION_WEB_1"]}
    assert body["source"] == "BaseSerp"
    assert body["serviceFrom"] == "suruga"
    assert body["indexRouting"] == "INDEX_ROUTING_UNSPECIFIED"
    assert body["thumbnailTypes"] == []
    assert body["pageSize"] == 120
    assert body["pageToken"] == ""
    assert body["searchSessionId"] == "0" * 32
    assert body["laplaceDeviceUuid"] == "dev-uuid"
    assert body["withAuction"] is True
    assert body["useDynamicAttribute"] is True
    assert body["withSearchConditionId"] is False
    # The web sends false, but true costs nothing and fills shopName (01 §3.1).
    assert body["withShopname"] is True


def test_search_body_flags_are_overridable() -> None:
    body = _body(with_shopname=False, with_search_condition_id=True, page_size=20, page_token="v1:3")
    assert body["withShopname"] is False
    assert body["withSearchConditionId"] is True
    assert body["pageSize"] == 20
    assert body["pageToken"] == "v1:3"


def test_search_request_targets_the_right_url() -> None:
    request = search_request(SearchQuery("x").to_condition(), session_id="s" * 32, device_uuid="d")
    assert request.method == "POST"
    assert request.url == "https://api.mercari.jp/v2/entities:search"
    assert request.json is not None and request.json["searchCondition"]["keyword"] == "x"


def test_facets_body_shape() -> None:
    body = build_facets_body(SearchQuery("").to_condition(), "", session_id="s" * 32)
    assert set(body) == {
        "facetRequests",
        "searchSessionId",
        "searchCondition",
        "useNtiersCategory",
        "useDynamicAttribute",
    }
    request = body["facetRequests"][0]
    assert request["facetId"] == ""
    assert request["withRelevantFacets"] is True
    assert request["withSelectedPaths"] is False
    assert request["config"] == {"responseToggles": ["DFF_IMPROVEMENT_FACETS_REORDER"]}
    assert "facetQuery" not in request  # omitted entirely when unset (01 §4.1)


def test_facets_body_includes_facet_query_when_given() -> None:
    body = build_facets_body(
        SearchQuery("").to_condition(),
        encode_facet_id("brand_id"),
        facet_query="apple",
        session_id="s" * 32,
    )
    assert body["facetRequests"][0]["facetQuery"] == "apple"


def test_encode_facet_id_uses_standard_base64_with_padding() -> None:
    """Standard base64 (``+/``, ``=`` kept) — not the base64url used for DPoP."""
    assert encode_facet_id("category_id", "3088") == "1\x1fY2F0ZWdvcnlfaWQfMzA4OA=="
    assert encode_facet_id("category_id") == "1\x1fY2F0ZWdvcnlfaWQf"


def test_facet_id_round_trip() -> None:
    for key, value in [("category_id", "3088"), ("brand_id", ""), ("keyword", "pro")]:
        assert decode_facet_id(encode_facet_id(key, value)) == (key, value)


def test_thumbnail_types_default_to_an_empty_array() -> None:
    """The web app sends ``[]``, which yields webp URLs (01 §3.1)."""
    assert _body()["thumbnailTypes"] == []


def test_thumbnail_types_are_serialised_when_asked_for() -> None:
    from carimer.models.enums import ThumbnailType

    body = _body(thumbnail_types=[ThumbnailType.JPEG.value])
    assert body["thumbnailTypes"] == ["JPEG"]
    assert set(body) == CAPTURE_TOP_LEVEL_KEYS  # no new top-level key
