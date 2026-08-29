#!/usr/bin/env python3
"""Export the 193-member-country UAP source-coverage ledger offline.

The country ledger is deliberately separate from the URL atlas: A/B/C/D is a
source-route availability judgement, not a count of reports, downloads, or a
probability of any phenomenon.  This exporter turns that human-maintained
ledger into a stable JSON/CSV join table for a future map without contacting a
provider or opening any source document.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
import io
import json
from pathlib import Path
import re
import sys
import tempfile
from typing import Any


ROOT = Path(__file__).resolve().parent
DEFAULT_LEDGER = ROOT / "GLOBAL_COUNTRY_COVERAGE_LEDGER_20260813_ZH.md"
HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
TABLE_DIVIDER = re.compile(r"^:?-{3,}:?$")
MARKDOWN_LINK = re.compile(r"\[([^\]]+)\]\((https?://[^\s)]+)\)")
ISO_ALPHA2 = re.compile(r"^[A-Z]{2}$")

MEMBER_REGIONS = {
    "歐洲": 45,
    "美洲": 35,
    "非洲": 54,
    "亞洲": 45,
    "大洋洲": 14,
}
STATUS_MEANINGS = {
    "A": "已驗本地／官方來源入口；仍須逐來源權利、隱私與格式審查",
    "B": "歷史館藏、正式申請或實驗線索；只可先走 finding aid／授權",
    "C": "僅跨境官方紀錄或全球基線；未驗本地一手母庫",
    "D": "本輪未驗合格本地入口；不代表不存在",
}
MEMBER_COUNTRY_COUNT = sum(MEMBER_REGIONS.values())


class CoverageInventoryError(RuntimeError):
    """The local country coverage ledger is unavailable or internally inconsistent."""


@dataclass(frozen=True)
class CoverageRow:
    country_name: str
    iso_alpha2: str
    coverage_status: str
    entry_summary: str
    region: str


def parse_table_cells(raw_line: str) -> list[str] | None:
    stripped = raw_line.strip()
    if not (stripped.startswith("|") and stripped.endswith("|")):
        return None
    return [cell.strip() for cell in stripped[1:-1].split("|")]


def is_table_divider(cells: list[str]) -> bool:
    return bool(cells) and all(
        bool(TABLE_DIVIDER.fullmatch(cell.replace(" ", ""))) for cell in cells
    )


def plain_markdown(value: str) -> str:
    """Keep a compact, link-free description for a map join table."""
    value = MARKDOWN_LINK.sub(lambda match: match.group(1), value)
    value = re.sub(r"[`*_]", "", value)
    return " ".join(value.split())


def member_region_from_heading(title: str) -> str | None:
    for region in MEMBER_REGIONS:
        if title.startswith(f"{region}（") or title.startswith(f"{region}("):
            return region
    return None


def parse_declared_snapshot(lines: list[str]) -> dict[str, dict[str, int]]:
    """Read the editorial snapshot table so row edits cannot leave it stale."""
    in_snapshot = False
    table_active = False
    declared: dict[str, dict[str, int]] = {}
    for raw_line in lines:
        heading = HEADING.match(raw_line)
        if heading:
            in_snapshot = heading.group(2).startswith("覆蓋快照")
            table_active = False
            continue
        if not in_snapshot:
            continue
        cells = parse_table_cells(raw_line)
        if cells is None:
            if table_active:
                break
            continue
        if is_table_divider(cells):
            continue
        first = plain_markdown(cells[0]) if cells else ""
        if first == "分區":
            table_active = True
            continue
        if not table_active or len(cells) != 6:
            continue
        label = plain_markdown(cells[0]).replace("193 會員國合計", "合計")
        if label not in {*MEMBER_REGIONS, "合計"}:
            continue
        try:
            values = [int(plain_markdown(value)) for value in cells[1:]]
        except ValueError as exc:
            raise CoverageInventoryError(f"invalid snapshot counts for {label}") from exc
        declared[label] = dict(zip(("A", "B", "C", "D", "total"), values, strict=True))
    return declared


def parse_ledger(path: Path) -> tuple[list[CoverageRow], dict[str, dict[str, int]]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise CoverageInventoryError(f"cannot read country coverage ledger: {path}: {exc}") from exc

    rows: list[CoverageRow] = []
    current_region: str | None = None
    table_active = False
    for raw_line in lines:
        heading = HEADING.match(raw_line)
        if heading:
            current_region = member_region_from_heading(heading.group(2))
            table_active = False
            continue
        if current_region is None:
            continue
        cells = parse_table_cells(raw_line)
        if cells is None:
            table_active = False
            continue
        if is_table_divider(cells):
            continue
        first = plain_markdown(cells[0]) if cells else ""
        if first == "國家":
            table_active = True
            continue
        if not table_active:
            continue
        if len(cells) != 4:
            raise CoverageInventoryError(
                f"expected four cells in {current_region} coverage row: {raw_line!r}"
            )
        country_name, iso_alpha2, coverage_status, entry_summary = (
            plain_markdown(value) for value in cells
        )
        if not country_name:
            raise CoverageInventoryError(f"blank country name in {current_region}")
        if not ISO_ALPHA2.fullmatch(iso_alpha2):
            raise CoverageInventoryError(f"invalid ISO alpha-2 code for {country_name}: {iso_alpha2!r}")
        if coverage_status not in STATUS_MEANINGS:
            raise CoverageInventoryError(
                f"invalid coverage status for {country_name}: {coverage_status!r}"
            )
        if not entry_summary:
            raise CoverageInventoryError(f"blank entry summary for {country_name}")
        rows.append(
            CoverageRow(
                country_name=country_name,
                iso_alpha2=iso_alpha2,
                coverage_status=coverage_status,
                entry_summary=entry_summary,
                region=current_region,
            )
        )
    return rows, parse_declared_snapshot(lines)


def status_counts(rows: list[CoverageRow]) -> dict[str, int]:
    return {status: sum(row.coverage_status == status for row in rows) for status in STATUS_MEANINGS}


def validate_complete_ledger(
    rows: list[CoverageRow], declared_snapshot: dict[str, dict[str, int]]
) -> None:
    if len(rows) != MEMBER_COUNTRY_COUNT:
        raise CoverageInventoryError(
            f"expected {MEMBER_COUNTRY_COUNT} UN-member rows, found {len(rows)}"
        )
    country_names = [row.country_name for row in rows]
    duplicate_names = sorted({name for name in country_names if country_names.count(name) > 1})
    if duplicate_names:
        raise CoverageInventoryError(f"duplicate country names: {', '.join(duplicate_names)}")
    iso_codes = [row.iso_alpha2 for row in rows]
    duplicate_iso = sorted({code for code in iso_codes if iso_codes.count(code) > 1})
    if duplicate_iso:
        raise CoverageInventoryError(f"duplicate ISO alpha-2 codes: {', '.join(duplicate_iso)}")

    computed_by_region: dict[str, dict[str, int]] = {}
    for region, expected_count in MEMBER_REGIONS.items():
        region_rows = [row for row in rows if row.region == region]
        if len(region_rows) != expected_count:
            raise CoverageInventoryError(
                f"expected {expected_count} rows for {region}, found {len(region_rows)}"
            )
        computed_by_region[region] = {
            **status_counts(region_rows),
            "total": len(region_rows),
        }
    computed_total = {**status_counts(rows), "total": len(rows)}
    expected_snapshot_keys = {*MEMBER_REGIONS, "合計"}
    if set(declared_snapshot) != expected_snapshot_keys:
        raise CoverageInventoryError("coverage snapshot table is absent or missing a region/total row")
    for region, computed in {**computed_by_region, "合計": computed_total}.items():
        if declared_snapshot[region] != computed:
            raise CoverageInventoryError(
                f"stale coverage snapshot for {region}: "
                f"declared={declared_snapshot[region]!r}, computed={computed!r}"
            )


def build_inventory(
    ledger_path: Path = DEFAULT_LEDGER, *, validate_complete: bool = True
) -> dict[str, Any]:
    ledger_path = ledger_path.resolve()
    rows, declared_snapshot = parse_ledger(ledger_path)
    if validate_complete:
        validate_complete_ledger(rows, declared_snapshot)
    counts = status_counts(rows)
    entries = [
        {
            "country_name": row.country_name,
            "iso_alpha2": row.iso_alpha2,
            "region": row.region,
            "membership_scope": "UN_member_193",
            "coverage_status": row.coverage_status,
            "coverage_status_meaning": STATUS_MEANINGS[row.coverage_status],
            "entry_summary": row.entry_summary,
        }
        for row in rows
    ]
    return {
        "schema_version": "uap.country_coverage_inventory.v1",
        "network_contacted": False,
        "ledger_path": str(ledger_path),
        "scope": "source_entry_coverage_only_not_reports_downloads_or_probability",
        "membership_scope": "UN_member_193",
        "country_count": len(entries),
        "status_counts": counts,
        "strict_local_mother_archive_gap_count": counts["C"] + counts["D"],
        "region_summaries": [
            {
                "region": region,
                "country_count": sum(row.region == region for row in rows),
                "status_counts": status_counts([row for row in rows if row.region == region]),
            }
            for region in MEMBER_REGIONS
        ],
        "entries": entries,
    }


def render_csv(inventory: dict[str, Any]) -> str:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(
        output,
        fieldnames=(
            "country_name",
            "iso_alpha2",
            "region",
            "membership_scope",
            "coverage_status",
            "coverage_status_meaning",
            "entry_summary",
        ),
    )
    writer.writeheader()
    writer.writerows(inventory["entries"])
    return output.getvalue()


def build_gap_inventory(inventory: dict[str, Any]) -> dict[str, Any]:
    """Return only C/D countries without implying that either has zero reports."""
    statuses = ("C", "D")
    entries = [
        entry for entry in inventory["entries"] if entry["coverage_status"] in statuses
    ]
    report = {
        **inventory,
        "schema_version": "uap.country_source_gap_inventory.v1",
        "scope": (
            "countries_without_a_verified_local_first_party_mother_archive_"
            "not_reports_downloads_or_probability"
        ),
        "included_statuses": list(statuses),
        "country_count": len(entries),
        "status_counts": {
            status: sum(entry["coverage_status"] == status for entry in entries)
            for status in statuses
        },
        "region_summaries": [
            {
                "region": region["region"],
                "country_count": sum(entry["region"] == region["region"] for entry in entries),
                "status_counts": {
                    status: sum(
                        entry["region"] == region["region"]
                        and entry["coverage_status"] == status
                        for entry in entries
                    )
                    for status in statuses
                },
            }
            for region in inventory["region_summaries"]
        ],
        "entries": entries,
    }
    report.pop("strict_local_mother_archive_gap_count", None)
    return report


def write_output(path: Path, content: str) -> None:
    if path.exists() or path.is_symlink():
        raise CoverageInventoryError(f"refusing to overwrite output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        handle.write(content.encode("utf-8"))
        temporary = Path(handle.name)
    try:
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()


def command_export(args: argparse.Namespace) -> int:
    inventory = build_inventory(args.ledger)
    return emit_inventory(inventory, args)


def command_gaps(args: argparse.Namespace) -> int:
    inventory = build_gap_inventory(build_inventory(args.ledger))
    return emit_inventory(inventory, args)


def emit_inventory(inventory: dict[str, Any], args: argparse.Namespace) -> int:
    content = (
        json.dumps(inventory, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        if args.format == "json"
        else render_csv(inventory)
    )
    if args.output:
        write_output(args.output, content)
        print(
            json.dumps(
                {"output": str(args.output), "network_contacted": False},
                ensure_ascii=False,
            )
        )
    else:
        sys.stdout.write(content)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Export the local 193-country UAP source-coverage ledger without network access."
    )
    parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    subparsers = parser.add_subparsers(dest="command", required=True)
    export = subparsers.add_parser("export", help="output country coverage in JSON or CSV")
    export.add_argument("--format", choices=("json", "csv"), default="json")
    export.add_argument("--output", type=Path)
    export.set_defaults(handler=command_export)
    gaps = subparsers.add_parser(
        "gaps", help="output only C/D country source gaps in JSON or CSV"
    )
    gaps.add_argument("--format", choices=("json", "csv"), default="json")
    gaps.add_argument("--output", type=Path)
    gaps.set_defaults(handler=command_gaps)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.handler(args))
    except CoverageInventoryError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
