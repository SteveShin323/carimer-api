#!/usr/bin/env python
"""Live health check for the endpoints and filter definitions this package depends on.

Required checks must pass; optional ones report ``skipped`` when the live data does not
offer a target (no auction on the first page, no Shops item, a seller with no badges).
Exit code 1 if any required check fails.

The facet-section check is deliberately narrow: the live section list has been observed
changing within a day (01 §4.4), so only the five stably observed sections are required
and the remaining difference against the bundled snapshot is reported as a diff, not a
failure. Otherwise one Mercari sidebar change turns the cron permanently red.

Usage:
    python scripts/health_check.py [--json out.json] [--markdown] [--quiet]

Calls: 11-13.
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import json
import time
import traceback
from typing import Any

from carimer import AttributeSection, Client, ItemKind, ItemType, SearchQuery
from carimer.catalog.fallback import fallback_value_map
from carimer.transport.base import CALL_COUNTER, TransportOptions

REQUIRED_SECTIONS = {"category_id", "brand_id", "status", "item_condition_id", "price"}
BASE_QUERY = SearchQuery("iphone 15").price(10_000, 80_000)


@dataclasses.dataclass
class Check:
    name: str
    required: bool
    status: str = "pending"  # pass | fail | skipped
    detail: str = ""
    diff: dict[str, Any] = dataclasses.field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status in {"pass", "skipped"}


class HealthCheck:
    def __init__(self, client: Client) -> None:
        self.client = client
        self.checks: list[Check] = []

    def run(self) -> list[Check]:
        page = self._search()
        self._item_detail(page)
        self._profile(page)
        self._sections()
        self._colors()
        self._shops_detail(page)
        self._auction_parsing()
        self._regular_listing_filter()
        self._created_after_offset()
        self._badges(page)
        self._desired_price(page)
        return self.checks

    # -- required -------------------------------------------------------------

    def _search(self) -> Any:
        check = Check("search", required=True)
        self.checks.append(check)
        try:
            page = self.client.search(BASE_QUERY, page_size=120)
            if not page.items:
                check.status, check.detail = "fail", "no items returned"
                return page
            in_range = all(10_000 <= item.price <= 80_000 for item in page.items)
            check.status = "pass" if in_range else "fail"
            check.detail = f"{len(page.items)} items, approx_total={page.approx_total}"
            if not in_range:
                check.detail += " — price filter not honoured"
            return page
        except Exception as exc:
            check.status, check.detail = "fail", _describe(exc)
            return None

    def _item_detail(self, page: Any) -> None:
        check = Check("item_detail", required=True)
        self.checks.append(check)
        try:
            item = next(i for i in page.items if i.kind is ItemKind.MERCARI)
            detail = self.client.get_item(item.id)
            check.status = "pass" if detail.id == item.id and detail.price > 0 else "fail"
            check.detail = f"{detail.id} price={detail.price} status={detail.status.value}"
        except Exception as exc:
            check.status, check.detail = "fail", _describe(exc)

    def _profile(self, page: Any) -> None:
        check = Check("profile", required=True)
        self.checks.append(check)
        try:
            seller_id = next(i.seller_id for i in page.items if i.seller_id)
            profile = self.client.get_profile(seller_id)
            leaked = [
                field
                for field in ("email", "phone_number", "current_sales", "current_point")
                if field in profile.raw
            ]
            created_ok = profile.created is not None
            check.status = "pass" if created_ok and not leaked else "fail"
            check.detail = f"created={profile.created} num_sell_items={profile.num_sell_items}"
            if not created_ok:
                check.detail += " — created empty, is _user_format=profile still honoured?"
            if leaked:
                check.detail += f" — personal fields present in raw: {leaked}"
        except Exception as exc:
            check.status, check.detail = "fail", _describe(exc)

    def _sections(self) -> None:
        check = Check("facet_sections", required=True)
        self.checks.append(check)
        try:
            sections = self.client.facets.sections()
            values = {section.searchable_value for section in sections if section.searchable_value}
            missing = sorted(REQUIRED_SECTIONS - values)
            snapshot = {
                entry["searchable_value"] for entry in _snapshot_sections() if entry.get("searchable_value")
            }
            check.diff = {
                "count": len(sections),
                "added_vs_snapshot": sorted(values - snapshot),
                "removed_vs_snapshot": sorted(snapshot - values),
            }
            check.status = "pass" if not missing else "fail"
            check.detail = f"{len(sections)} sections"
            if missing:
                check.detail += f" — required missing: {missing}"
        except Exception as exc:
            check.status, check.detail = "fail", _describe(exc)

    def _created_after_offset(self) -> None:
        """The JST offset is silent when it breaks: results would just be 9 h stale."""
        check = Check("created_after_jst_offset", required=True)
        self.checks.append(check)
        try:
            since = int(time.time()) - 3600
            query = BASE_QUERY.with_keyword("iphone").created_after(since).item_types(ItemType.MERCARI)
            page = self.client.search(query, page_size=20)
            stale = [i for i in page.items if i.created and i.created.timestamp() < since]
            echo = page.raw.get("searchCondition", {}).get("createdAfterDate")
            check.status = "pass" if not stale else "fail"
            check.detail = f"{len(page.items)} items, echo={echo}, stale={len(stale)}"
        except Exception as exc:
            check.status, check.detail = "fail", _describe(exc)

    # -- optional -------------------------------------------------------------

    def _colors(self) -> None:
        check = Check("color_values", required=False)
        self.checks.append(check)
        try:
            values = self.client.facets.attribute_values(AttributeSection.COLOR.value)
            live = {facet.name for facet in values if facet.name}
            snapshot = set(fallback_value_map().get(AttributeSection.COLOR.value, {}))
            check.diff = {
                "count": len(live),
                "added_vs_snapshot": sorted(live - snapshot),
                "removed_vs_snapshot": sorted(snapshot - live),
            }
            check.status = "pass" if live else "fail"
            check.detail = f"{len(live)} colors"
            if live != snapshot:
                check.detail += " — differs from the bundled snapshot"
        except Exception as exc:
            check.status, check.detail = "fail", _describe(exc)

    def _shops_detail(self, page: Any) -> None:
        check = Check("shops_detail", required=False)
        self.checks.append(check)
        try:
            item = next((i for i in page.items if i.kind is ItemKind.SHOPS), None)
            if item is None:
                check.status, check.detail = "skipped", "no Shops item on the first page"
                return
            product = self.client.get_shops_product(item.id)
            check.status = "pass" if product.display_name else "fail"
            check.detail = f"{product.id} price={product.price} sold_out={product.sold_out}"
        except Exception as exc:
            check.status, check.detail = "fail", _describe(exc)

    def _auction_parsing(self) -> None:
        check = Check("auction_parsing", required=False)
        self.checks.append(check)
        try:
            page = self.client.search(
                BASE_QUERY.attr(AttributeSection.LISTING_FORMAT, "オークション"), page_size=20
            )
            if not page.items:
                check.status, check.detail = "skipped", "no auction listings right now"
                return
            parsed = [i for i in page.items if i.auction and i.auction.bid_deadline]
            check.status = "pass" if len(parsed) == len(page.items) else "fail"
            check.detail = f"{len(parsed)}/{len(page.items)} auctions parsed"
        except Exception as exc:
            check.status, check.detail = "fail", _describe(exc)

    def _regular_listing_filter(self) -> None:
        check = Check("regular_listing_filter", required=False)
        self.checks.append(check)
        try:
            page = self.client.search(
                BASE_QUERY.attr(AttributeSection.LISTING_FORMAT, "通常出品"), page_size=20
            )
            if not page.items:
                check.status, check.detail = "skipped", "no regular listings returned"
                return
            auctions = [item.id for item in page.items if item.auction]
            check.status = "pass" if not auctions else "fail"
            check.detail = f"{len(page.items)} items, auctions={len(auctions)}"
        except Exception as exc:
            check.status, check.detail = "fail", _describe(exc)

    def _badges(self, page: Any) -> None:
        check = Check("seller_badges", required=False)
        self.checks.append(check)
        try:
            seller_id = next(i.seller_id for i in page.items if i.seller_id)
            verified = self.client.is_identity_verified(seller_id)
            check.status, check.detail = "pass", f"identity_verified={verified}"
        except Exception as exc:
            check.status, check.detail = "fail", _describe(exc)

    def _desired_price(self, page: Any) -> None:
        check = Check("desired_price", required=False)
        self.checks.append(check)
        try:
            item = next(i for i in page.items if i.kind is ItemKind.MERCARI)
            info = self.client.desired_price_info(item.id)
            check.status = "pass" if info.item_id == item.id else "fail"
            check.detail = f"registered_count={info.registered_count}"
        except Exception as exc:
            check.status, check.detail = "fail", _describe(exc)


def _snapshot_sections() -> list[dict[str, Any]]:
    from carimer.catalog.fallback import fallback_sections

    return fallback_sections()


def _describe(exc: Exception) -> str:
    return f"{type(exc).__name__}: {exc}".strip()[:300]


def to_markdown(report: dict[str, Any]) -> str:
    lines = [
        f"# carimer API health — {report['checked_at']}",
        "",
        f"**{report['summary']}** · {report['api_calls']} API calls",
        "",
        "| check | required | status | detail |",
        "|---|---|---|---|",
    ]
    for check in report["checks"]:
        icon = {"pass": "✅", "fail": "❌", "skipped": "⏭️"}.get(check["status"], "❔")
        lines.append(
            f"| `{check['name']}` | {'yes' if check['required'] else 'no'} | "
            f"{icon} {check['status']} | {check['detail']} |"
        )
    diffs = [
        c
        for c in report["checks"]
        if c.get("diff", {}).get("added_vs_snapshot") or c.get("diff", {}).get("removed_vs_snapshot")
    ]
    if diffs:
        lines += ["", "## Drift against the bundled snapshot", ""]
        for check in diffs:
            diff = check["diff"]
            lines.append(
                f"- `{check['name']}`: added={diff.get('added_vs_snapshot')} "
                f"removed={diff.get('removed_vs_snapshot')}"
            )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", type=str, default=None, help="write the JSON report to this path")
    parser.add_argument("--markdown", action="store_true", help="print a markdown summary too")
    parser.add_argument("--quiet", action="store_true", help="print only the JSON report")
    parser.add_argument("--min-interval", type=float, default=0.6)
    args = parser.parse_args(argv)

    CALL_COUNTER.reset()
    started = time.monotonic()
    with Client(options=TransportOptions(min_interval=args.min_interval)) as client:
        try:
            checks = HealthCheck(client).run()
        except Exception:  # a crash outside a check is itself a failure
            traceback.print_exc()
            checks = [Check("harness", required=True, status="fail", detail="unhandled exception")]

    failures = [check for check in checks if check.required and not check.ok]
    report = {
        "checked_at": dt.datetime.now(tz=dt.UTC).isoformat(timespec="seconds"),
        "duration_seconds": round(time.monotonic() - started, 1),
        "api_calls": CALL_COUNTER.total,
        "calls_by_path": dict(sorted(CALL_COUNTER.by_path.items())),
        "summary": "all required checks passed"
        if not failures
        else f"{len(failures)} required check(s) failed",
        "ok": not failures,
        "checks": [dataclasses.asdict(check) for check in checks],
    }

    payload = json.dumps(report, ensure_ascii=False, indent=2)
    if args.json:
        with open(args.json, "w", encoding="utf-8") as handle:
            handle.write(payload + "\n")
    if args.quiet:
        print(payload)
    else:
        print(payload)
        if args.markdown:
            print()
            print(to_markdown(report))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
