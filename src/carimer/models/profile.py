"""Seller profile, listings, reviews and badges (01 §7).

The profile response carries empty-but-present personal fields (``email``,
``phone_number``, ``current_sales``, ``current_point``, ``num_ticket``, ``iv_code``,
``bounce_mail_flag``, ``has_detach_phone_number``, ``pp_*_url``, ``tokushouhou_*_url`` —
all 12 observed in probe11). None of them is modelled, and the recorded fixtures have
them stripped.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import Field

from carimer.models.common import RawModel, to_bool, to_datetime, to_int, to_str, to_str_list
from carimer.models.enums import Status
from carimer.models.facets import Brand
from carimer.models.search import Auction
from carimer.transport.errors import ParseError

__all__ = ["Badge", "Profile", "Review", "SellerItem"]

#: Never modelled, never stored (01 §7.1).
EXCLUDED_FIELDS = frozenset(
    {
        "email",
        "phone_number",
        "current_point",
        "current_sales",
        "num_ticket",
        "iv_code",
        "bounce_mail_flag",
        "has_detach_phone_number",
    }
)
EXCLUDED_PREFIXES = ("pp_", "tokushouhou_")


def _public_only(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in payload.items()
        if key not in EXCLUDED_FIELDS and not key.startswith(EXCLUDED_PREFIXES)
    }


class Profile(RawModel):
    """A public seller profile.

    ``raw`` also has the personal fields removed, so nothing sensitive survives even
    there. Requires ``_user_format=profile``: without it ``created`` and
    ``num_sell_items`` are 0 (probe11).
    """

    id: str
    name: str | None = None
    photo_url: str | None = None
    photo_thumbnail_url: str | None = None
    introduction: str | None = None
    created: datetime | None = None
    num_sell_items: int | None = None
    num_ratings: int | None = None
    ratings: dict[str, int] = Field(default_factory=dict)
    polarized_ratings: dict[str, int] = Field(default_factory=dict)
    score: int | None = None
    star_rating_score: int | None = None
    follower_count: int | None = None
    following_count: int | None = None
    is_official: bool = False
    is_organizational_user: bool = False
    register_sms_confirmation: bool = False
    kyc_type: str | None = None
    hide_profile: bool = False

    @classmethod
    def from_api(cls, payload: dict[str, Any]) -> Profile:
        data = payload.get("data") if "data" in payload else payload
        if not isinstance(data, dict):
            raise ParseError("data", payload)
        user_id = to_str(data.get("id"))
        if not user_id:
            raise ParseError("id", payload)
        return cls(
            id=user_id,
            name=to_str(data.get("name")),
            photo_url=to_str(data.get("photo_url")),
            photo_thumbnail_url=to_str(data.get("photo_thumbnail_url")),
            introduction=to_str(data.get("introduction")),
            created=to_datetime(data.get("created")),
            num_sell_items=to_int(data.get("num_sell_items")),
            num_ratings=to_int(data.get("num_ratings")),
            ratings=_int_map(data.get("ratings")),
            polarized_ratings=_int_map(data.get("polarized_ratings")),
            score=to_int(data.get("score")),
            star_rating_score=to_int(data.get("star_rating_score")),
            follower_count=to_int(data.get("follower_count")),
            following_count=to_int(data.get("following_count")),
            is_official=bool(to_bool(data.get("is_official"))),
            is_organizational_user=bool(to_bool(data.get("is_organizational_user"))),
            register_sms_confirmation=bool(to_bool(data.get("register_sms_confirmation"))),
            kyc_type=to_str(data.get("kyc_type")),
            hide_profile=bool(to_bool(data.get("hide_profile"))),
            raw=_public_only(data),
        )


class SellerItem(RawModel):
    """One row of ``items/get_items``. ``pager_id`` drives the paging (01 §7.2)."""

    id: str
    name: str
    price: int
    status: Status = Status.UNKNOWN
    created: datetime | None = None
    updated: datetime | None = None
    thumbnails: list[str] = Field(default_factory=list)
    pager_id: int | None = None
    category_id: int | None = None
    root_category_id: int | None = None
    brand: Brand | None = None
    num_likes: int | None = None
    num_comments: int | None = None
    item_pv: int | None = None
    shipping_from_area: str | None = None
    shipping_method_id: int | None = None
    is_no_price: bool = False
    is_archived: bool = False
    auction: Auction | None = None

    @property
    def sold_out(self) -> bool:
        return self.status is Status.SOLD_OUT

    @classmethod
    def from_api(cls, payload: dict[str, Any]) -> SellerItem:
        item_id = to_str(payload.get("id"))
        if not item_id:
            raise ParseError("id", payload)
        name = to_str(payload.get("name"))
        if name is None:
            raise ParseError("name", payload)
        price = to_int(payload.get("price"))
        if price is None:
            raise ParseError("price", payload)
        category = payload.get("item_category_ntiers") or payload.get("item_category") or {}
        area = payload.get("shipping_from_area") or {}
        return cls(
            id=item_id,
            name=name,
            price=price,
            status=Status.parse(payload.get("status")),
            created=to_datetime(payload.get("created")),
            updated=to_datetime(payload.get("updated")),
            thumbnails=to_str_list(payload.get("thumbnails")),
            pager_id=to_int(payload.get("pager_id")),
            category_id=to_int(category.get("id")),
            root_category_id=to_int(payload.get("root_category_id")),
            brand=Brand.from_api(payload.get("item_brand")),
            num_likes=to_int(payload.get("num_likes")),
            num_comments=to_int(payload.get("num_comments")),
            item_pv=to_int(payload.get("item_pv")),
            shipping_from_area=to_str(area.get("name")) if isinstance(area, dict) else to_str(area),
            shipping_method_id=to_int(payload.get("shipping_method_id")),
            is_no_price=bool(to_bool(payload.get("is_no_price"))),
            is_archived=bool(to_bool(payload.get("is_archived"))),
            auction=Auction.from_detail(payload.get("auction_info")),
            raw=payload,
        )


class Review(RawModel):
    """One row of ``reviews/history``."""

    subject: str | None = None
    fame: str | None = None
    message: str | None = None
    user_id: str | None = None
    user_name: str | None = None
    created: datetime | None = None
    pager_id: int | None = None

    @classmethod
    def from_api(cls, payload: dict[str, Any]) -> Review:
        user = payload.get("user") or {}
        return cls(
            subject=to_str(payload.get("subject")),
            fame=to_str(payload.get("fame")),
            message=to_str(payload.get("message")),
            user_id=to_str(user.get("id")),
            user_name=to_str(user.get("name")),
            created=to_datetime(payload.get("created")),
            pager_id=to_int(payload.get("pager_id")),
            raw=payload,
        )


class Badge(RawModel):
    id: str | None = None
    name: str | None = None
    description: str | None = None
    icon_url: str | None = None

    @classmethod
    def from_api(cls, payload: dict[str, Any]) -> Badge:
        return cls(
            id=to_str(payload.get("id")),
            name=to_str(payload.get("name")),
            description=to_str(payload.get("description")),
            icon_url=to_str(payload.get("iconUrl")),
            raw=payload,
        )


def _int_map(value: object) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    pairs = ((str(k), to_int(v)) for k, v in value.items())
    return {k: v for k, v in pairs if v is not None}
