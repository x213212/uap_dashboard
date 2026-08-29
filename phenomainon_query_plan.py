#!/usr/bin/env python3
"""Build no-contact, bounded Phenomainon MCP research requests.

Phenomainon is an aggregator-derived normalized corpus.  Its sources are
preserved on case records, but it must not be counted as an independent sixth
or seventh sighting feed.  The public MCP API requires an X-API-Key and offers
anonymous users only a small number of calls, so this module produces reviewable
JSON-RPC request bodies without ever sending one or accepting a key.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from typing import Any


SCHEMA_VERSION = "uap.phenomainon_query_plan.v1"
MCP_ENDPOINT = "https://mcp.phenomainon.com/mcp"
MAX_SEARCH_LIMIT = 100
MAX_YEAR_SPAN = 100
STATS_GROUPS = frozenset({"year", "decade", "state", "country", "shape", "theme", "source_count"})
SAFE_TOKEN = re.compile(r"^[\w .,'/-]{1,80}$", re.UNICODE)


class PhenomainonPlanError(RuntimeError):
    """A proposed aggregation query would be unbounded or malformed."""


def optional_token(value: str | None, *, field: str) -> str | None:
    if value is None or not value.strip():
        return None
    normalized = value.strip()
    if not SAFE_TOKEN.fullmatch(normalized):
        raise PhenomainonPlanError(f"{field} must be 1-80 safe display characters")
    return normalized


def optional_year(value: int | None, *, field: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not 1800 <= value <= 2100:
        raise PhenomainonPlanError(f"{field} must be a year from 1800 to 2100")
    return value


def request_body(tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": tool, "arguments": arguments},
    }


def envelope(*, tool: str, arguments: dict[str, Any], purpose: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "network_contacted": False,
        "source_id": "phenomainon_research",
        "source_role": "aggregated_deduplication_reference",
        "endpoint": MCP_ENDPOINT,
        "required_headers": {"Content-Type": "application/json", "Accept": "application/json, text/event-stream", "X-API-Key": "REDACTED_REQUIRED"},
        "request_body": request_body(tool, arguments),
        "purpose": purpose,
        "bulk_policy": "no_bulk_mirror_no_independent_event_count",
        "next_action": (
            "Use only after a researcher key/scope review; retain upstream citations and do not store an API key in this repository."
        ),
    }


def plan_overview() -> dict[str, Any]:
    return envelope(
        tool="dataset_overview",
        arguments={},
        purpose="Read one high-level coverage/health summary, not event rows.",
    )


def plan_stats(
    *,
    group_by: str,
    state: str | None = None,
    shape: str | None = None,
    theme: str | None = None,
) -> dict[str, Any]:
    if group_by not in STATS_GROUPS:
        allowed = ", ".join(sorted(STATS_GROUPS))
        raise PhenomainonPlanError(f"group_by must be one of: {allowed}")
    arguments: dict[str, Any] = {"group_by": group_by}
    for field, value in (("state", state), ("shape", shape), ("theme", theme)):
        safe = optional_token(value, field=field)
        if safe is not None:
            arguments[field] = safe
    return envelope(
        tool="stats",
        arguments=arguments,
        purpose="Request bounded aggregate counts only; no individual case detail.",
    )


def plan_search(
    *,
    country: str | None = None,
    state: str | None = None,
    shape: str | None = None,
    theme: str | None = None,
    year_from: int | None = None,
    year_to: int | None = None,
    min_sources: int | None = None,
    limit: int = 25,
) -> dict[str, Any]:
    if isinstance(limit, bool) or not 1 <= limit <= MAX_SEARCH_LIMIT:
        raise PhenomainonPlanError(f"limit must be an integer from 1 to {MAX_SEARCH_LIMIT}")
    start = optional_year(year_from, field="year_from")
    end = optional_year(year_to, field="year_to")
    if start is not None and end is not None:
        if end < start:
            raise PhenomainonPlanError("year_to must not precede year_from")
        if end - start > MAX_YEAR_SPAN:
            raise PhenomainonPlanError(f"year range must not exceed {MAX_YEAR_SPAN} years")
    if min_sources is not None and (
        isinstance(min_sources, bool) or not 1 <= min_sources <= 50
    ):
        raise PhenomainonPlanError("min_sources must be an integer from 1 to 50")
    arguments: dict[str, Any] = {"limit": limit}
    for field, value in (
        ("country", country),
        ("state", state),
        ("shape", shape),
        ("theme", theme),
    ):
        safe = optional_token(value, field=field)
        if safe is not None:
            arguments[field] = safe
    if start is not None:
        arguments["year_from"] = start
    if end is not None:
        arguments["year_to"] = end
    if min_sources is not None:
        arguments["min_sources"] = min_sources
    return envelope(
        tool="search_cases",
        arguments=arguments,
        purpose="Retrieve a small, explicit candidate set for citation back to upstream catalogs.",
    )


def command_overview(_args: argparse.Namespace) -> int:
    print(json.dumps(plan_overview(), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def command_stats(args: argparse.Namespace) -> int:
    print(
        json.dumps(
            plan_stats(group_by=args.group_by, state=args.state, shape=args.shape, theme=args.theme),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def command_search(args: argparse.Namespace) -> int:
    print(
        json.dumps(
            plan_search(
                country=args.country,
                state=args.state,
                shape=args.shape,
                theme=args.theme,
                year_from=args.year_from,
                year_to=args.year_to,
                min_sources=args.min_sources,
                limit=args.limit,
            ),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create a no-contact, bounded Phenomainon MCP request plan."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    overview = subparsers.add_parser("overview", help="plan one dataset overview request")
    overview.set_defaults(handler=command_overview)
    stats = subparsers.add_parser("stats", help="plan one aggregate-only stats request")
    stats.add_argument("--group-by", required=True)
    stats.add_argument("--state")
    stats.add_argument("--shape")
    stats.add_argument("--theme")
    stats.set_defaults(handler=command_stats)
    search = subparsers.add_parser("search", help="plan a capped structured case search")
    search.add_argument("--country")
    search.add_argument("--state")
    search.add_argument("--shape")
    search.add_argument("--theme")
    search.add_argument("--year-from", type=int)
    search.add_argument("--year-to", type=int)
    search.add_argument("--min-sources", type=int)
    search.add_argument("--limit", type=int, default=25)
    search.set_defaults(handler=command_search)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.handler(args))
    except PhenomainonPlanError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
