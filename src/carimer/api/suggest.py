"""Keyword autocomplete (01 §8.2)."""

from __future__ import annotations

from typing import Any

from carimer.transport.base import BASE_URL, Request

__all__ = ["suggest_terms"]


def suggest_terms(word: str, *, category_id: int | None = None) -> Request:
    """``category_id`` scopes the suggestions to one category, as the web search box does.

    It changes the result set outright rather than filtering it: ``リング`` answers ten
    entries unscoped and one under category 83 (probe15).
    """
    params: dict[str, Any] = {"word": word, "brand_category_result_included": "true"}
    if category_id is not None:
        params["category_id"] = int(category_id)
    return Request("GET", f"{BASE_URL}/search_index/terms", params=params)
