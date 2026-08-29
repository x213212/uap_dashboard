#!/usr/bin/env python3
"""Create a bounded, offline GMN incremental-query contract.

Global Meteor Network data are a natural-phenomenon control layer, not UFO
evidence.  The public Datasette table can be large, so this planner produces a
small parameterized cursor query without sending it.  A future approved
connector must execute exactly this bounded contract, validate the returned
schema, and preserve cursor receipts before it can be promoted from review.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta
import json
import sys
from typing import Any
from urllib.parse import urlencode


SCHEMA_VERSION = "uap.gmn_incremental_plan.v1"
GMN_TABLE = "meteor"
GMN_QUERY_ENDPOINT = (
    "https://explore.globalmeteornetwork.org/gmn_data_store/-/query.json"
)
DEFAULT_PAGE_SIZE = 500
MAX_PAGE_SIZE = 1_000
MAX_INCREMENTAL_WINDOW = timedelta(days=31)

# Fields sufficient to retain a meteor trajectory as a false-positive control
# without mirroring station/camera tables or unnecessary orbital detail.
SELECT_COLUMNS = (
    "unique_trajectory_identifier",
    "beginning_utc_time",
    "updated_at",
    "shower_iau_no",
    "latbeg_n_deg",
    "lonbeg_e_deg",
    "htbeg_km",
    "latend_n_deg",
    "lonend_e_deg",
    "htend_km",
    "duration_sec",
    "peak_absmag",
    "qc_deg",
)


class GmnPlanError(RuntimeError):
    """The requested incremental window is unsafe or ambiguous."""


def parse_utc_timestamp(value: str) -> datetime:
    """Accept an explicit ISO-8601 instant and normalize it to UTC."""

    raw = value.strip()
    if not raw:
        raise GmnPlanError("UTC timestamp cannot be empty")
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise GmnPlanError(f"invalid ISO-8601 UTC timestamp: {value!r}") from exc
    if parsed.tzinfo is None:
        raise GmnPlanError("timestamp must include UTC offset or Z")
    return parsed.astimezone(UTC)


def iso_z(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def validate_page_size(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= MAX_PAGE_SIZE:
        raise GmnPlanError(f"page size must be an integer from 1 to {MAX_PAGE_SIZE}")
    return value


def validate_cursor_identifier(value: str) -> str:
    # It is passed as a SQL parameter—not interpolated—but a bounded printable
    # identifier makes receipts and URLs safe to log and compare.
    if len(value) > 128 or any(ord(char) < 32 for char in value):
        raise GmnPlanError("cursor identifier must be at most 128 printable characters")
    return value


def build_incremental_sql() -> str:
    selected = ", ".join(f'"{column}"' for column in SELECT_COLUMNS)
    return (
        f"SELECT {selected} FROM \"{GMN_TABLE}\" "
        "WHERE ("
        "\"updated_at\" > :after_updated_at "
        "OR (\"updated_at\" = :after_updated_at "
        "AND \"unique_trajectory_identifier\" > :after_identifier)"
        ") "
        "AND \"updated_at\" <= :until_updated_at "
        "ORDER BY \"updated_at\", \"unique_trajectory_identifier\" "
        "LIMIT :page_size"
    )


def build_plan(
    *,
    after_updated_at: str,
    until_updated_at: str,
    after_identifier: str = "",
    page_size: int = DEFAULT_PAGE_SIZE,
) -> dict[str, Any]:
    """Return a no-contact, composite-cursor plan for a single GMN page."""

    after = parse_utc_timestamp(after_updated_at)
    until = parse_utc_timestamp(until_updated_at)
    if until <= after:
        raise GmnPlanError("until_updated_at must be later than after_updated_at")
    if until - after > MAX_INCREMENTAL_WINDOW:
        raise GmnPlanError(
            f"incremental window must not exceed {MAX_INCREMENTAL_WINDOW.days} days"
        )
    identifier = validate_cursor_identifier(after_identifier)
    size = validate_page_size(page_size)
    params = {
        "after_updated_at": iso_z(after),
        "after_identifier": identifier,
        "until_updated_at": iso_z(until),
        "page_size": str(size),
        "_shape": "objects",
    }
    sql = build_incremental_sql()
    url_params = {"sql": sql, **params}
    return {
        "schema_version": SCHEMA_VERSION,
        "network_contacted": False,
        "source_id": "global_meteor_network_meteor",
        "source_role": "false_positive_control",
        "license": "CC-BY-4.0",
        "endpoint": GMN_QUERY_ENDPOINT,
        "request_url": GMN_QUERY_ENDPOINT + "?" + urlencode(url_params),
        "sql": sql,
        "params": params,
        "selected_columns": list(SELECT_COLUMNS),
        "page_row_cap": size,
        "cursor_contract": {
            "order": ["updated_at", "unique_trajectory_identifier"],
            "input": {
                "after_updated_at": params["after_updated_at"],
                "after_identifier": identifier,
            },
            "upper_bound": params["until_updated_at"],
            "advance_rule": (
                "Set the next cursor to updated_at and unique_trajectory_identifier "
                "from the final successfully normalized row only."
            ),
        },
        "normalization_contract": {
            "record_role": "false_positive_control",
            "record_type": "astronomy_control_meteor_trajectory",
            "identity": "unique_trajectory_identifier",
            "geometry": "separate start/end source coordinates; never infer a sighting location",
        },
        "next_action": (
            "Review API response schema and authorization with a one-page approved probe; "
            "do not execute this URL from the planner."
        ),
    }


def command_plan(args: argparse.Namespace) -> int:
    plan = build_plan(
        after_updated_at=args.after_updated_at,
        until_updated_at=args.until_updated_at,
        after_identifier=args.after_identifier,
        page_size=args.page_size,
    )
    print(json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create a no-contact, bounded Global Meteor Network incremental query plan."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    plan_parser = subparsers.add_parser("plan", help="print a query only; do not request it")
    plan_parser.add_argument("--after-updated-at", required=True)
    plan_parser.add_argument("--until-updated-at", required=True)
    plan_parser.add_argument("--after-identifier", default="")
    plan_parser.add_argument("--page-size", type=int, default=DEFAULT_PAGE_SIZE)
    plan_parser.set_defaults(handler=command_plan)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.handler(args))
    except GmnPlanError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
