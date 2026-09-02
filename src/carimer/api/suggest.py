"""Keyword autocomplete (01 §8.2)."""

from __future__ import annotations

from carimer.transport.base import BASE_URL, Request

__all__ = ["suggest_terms"]


def suggest_terms(word: str) -> Request:
    return Request(
        "GET",
        f"{BASE_URL}/search_index/terms",
        params={"word": word, "brand_category_result_included": "true"},
    )
