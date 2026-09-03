"""Seller-side request builders (01 §7).

``_user_format=profile`` is not optional: without it ``created`` and ``num_sell_items``
come back as 0 (reproduced in probe11), which is the mercapi-node 0.2.0 bug.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from carimer.transport.base import BASE_URL, Request

__all__ = [
    "MAX_LIMIT",
    "get_profile",
    "get_reviews",
    "get_seller_items",
    "has_identity_verified_badge",
    "seller_badges",
]

#: 100 is accepted, 200 answers 400 ``InvalidRequest`` (01 §7.2).
MAX_LIMIT = 100


def get_profile(user_id: str) -> Request:
    return Request(
        "GET",
        f"{BASE_URL}/users/get_profile",
        params={"user_id": user_id, "_user_format": "profile"},
    )


def get_seller_items(
    seller_id: str,
    *,
    limit: int = MAX_LIMIT,
    status: Sequence[str] = ("on_sale",),
    max_pager_id: int | None = None,
    exclude_archived: bool = False,
) -> Request:
    """``status`` is a CSV of ``on_sale`` / ``trading`` / ``sold_out``; the web sends ``on_sale``."""
    if limit > MAX_LIMIT:
        raise ValueError(f"limit must be <= {MAX_LIMIT} (200 answers 400 InvalidRequest)")
    params: dict[str, Any] = {
        "seller_id": seller_id,
        "limit": limit,
        "status": ",".join(status),
        "with_auction": "true",
    }
    if exclude_archived:
        params["exclude_archived_item"] = "true"
    if max_pager_id is not None:
        params["max_pager_id"] = max_pager_id
    return Request("GET", f"{BASE_URL}/items/get_items", params=params)


def get_reviews(
    user_id: str,
    *,
    limit: int = MAX_LIMIT,
    max_pager_id: int | None = None,
    subject: Sequence[str] = ("seller", "buyer"),
    fame: Sequence[str] = ("good", "normal", "bad"),
) -> Request:
    if limit > MAX_LIMIT:
        raise ValueError(f"limit must be <= {MAX_LIMIT}")
    params: dict[str, Any] = {
        "user_id": user_id,
        "subject": ",".join(subject),
        "fame": ",".join(fame),
        "limit": limit,
    }
    if max_pager_id is not None:
        params["max_pager_id"] = max_pager_id
    return Request("GET", f"{BASE_URL}/reviews/history", params=params)


def seller_badges(user_id: str, *, fetch_seller_rank_badge: bool = True) -> Request:
    """``fetch_seller_rank_badge`` is what unlocks badge id 10100 (``出品者レベルN``).

    The web sends it and the field name it uses is ``user_id``; the gateway accepts
    either spelling, and probe13d confirmed the flag — not the spelling — is what
    changes the response. Without it a seller whose only badge is the rank badge comes
    back as an empty list.
    """
    return Request(
        "POST",
        f"{BASE_URL}/services/usersocialjp/v1/stats/badges",
        json={"user_id": user_id, "fetch_seller_rank_badge": fetch_seller_rank_badge},
    )


def has_identity_verified_badge(user_id: str) -> Request:
    return Request(
        "POST",
        f"{BASE_URL}/services/usersocialjp/v1/stats/has_identity_verified_badge",
        json={"userId": user_id},
    )
