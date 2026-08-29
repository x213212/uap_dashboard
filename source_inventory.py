#!/usr/bin/env python3
"""Export the global UAP source atlas as a local, machine-readable URL inventory.

The atlas intentionally contains much more than the small set of automatically
collectable providers: national archives, regional report channels, control
data, rights pages and upstream directories.  This tool extracts every URL
from the atlas and registry, preserving the nearest atlas section, link label,
and (when a link is in an atlas country table) country/region context.  It
makes no network request and does not decide that an URL is safe to collect
merely because it is listed.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass, field
import io
import json
from pathlib import Path
import re
import sys
import tempfile
from typing import Any


ROOT = Path(__file__).resolve().parent
DEFAULT_REGISTRY = ROOT / "sources.json"
MARKDOWN_LINK = re.compile(r"\[([^\]]+)\]\((https?://[^\s)]+)\)")
BARE_URL = re.compile(r"(?<!\()(?<!\[)(https?://[^\s<>\])]+)")
HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
TABLE_DIVIDER = re.compile(r"^:?-{3,}:?$")
COUNTRY_TABLE_HEADERS = {
    "國家",
    "國家／區域",
    "國家/區域",
    "地區／國家",
    "地區/國家",
}


class InventoryError(RuntimeError):
    """Local source atlas/registry input is unavailable or malformed."""


@dataclass
class InventoryEntry:
    url: str
    labels: set[str] = field(default_factory=set)
    sections: set[str] = field(default_factory=set)
    country_or_regions: set[str] = field(default_factory=set)
    source_ids: set[str] = field(default_factory=set)
    registry_roles: set[str] = field(default_factory=set)
    registry_access: set[str] = field(default_factory=set)
    seen_in_atlas: bool = False
    seen_in_registry: bool = False


def clean_url(value: str) -> str:
    return value.rstrip(".,;:。）」」|")


def load_registry(path: Path) -> dict[str, Any]:
    try:
        registry = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise InventoryError(f"cannot read registry: {path}: {exc}") from exc
    if registry.get("schema_version") != "uap.source_registry.v1":
        raise InventoryError("unsupported source registry schema")
    if not isinstance(registry.get("sources"), list):
        raise InventoryError("registry lacks sources list")
    return registry


def atlas_path(registry: dict[str, Any], registry_path: Path) -> Path:
    relative = registry.get("atlas_path")
    if not isinstance(relative, str) or not relative:
        raise InventoryError("registry lacks atlas_path")
    candidate = (registry_path.parent / relative).resolve()
    if not candidate.is_file():
        raise InventoryError(f"atlas file does not exist: {candidate}")
    return candidate


def add_entry(entries: dict[str, InventoryEntry], url: str) -> InventoryEntry:
    normalized = clean_url(url)
    if not normalized.startswith(("https://", "http://")):
        raise InventoryError(f"non-HTTP URL in local source input: {url!r}")
    return entries.setdefault(normalized, InventoryEntry(url=normalized))


def parse_table_cells(raw_line: str) -> list[str] | None:
    """Return Markdown table cells without adding a general Markdown parser."""
    stripped = raw_line.strip()
    if not (stripped.startswith("|") and stripped.endswith("|")):
        return None
    return [cell.strip() for cell in stripped[1:-1].split("|")]


def clean_table_cell(value: str) -> str:
    """Make a display-only country context from a Markdown table cell."""
    without_links = MARKDOWN_LINK.sub(lambda match: match.group(1), value)
    return re.sub(r"[`*_]", "", without_links).strip()


def is_table_divider(cells: list[str]) -> bool:
    return bool(cells) and all(
        bool(TABLE_DIVIDER.fullmatch(cell.replace(" ", ""))) for cell in cells
    )


def extract_atlas(entries: dict[str, InventoryEntry], path: Path) -> None:
    current_section = "(atlas preamble)"
    country_table_active = False
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        heading = HEADING.match(raw_line)
        if heading:
            current_section = heading.group(2)
            country_table_active = False
        cells = parse_table_cells(raw_line)
        row_country_or_region: str | None = None
        if cells is None:
            country_table_active = False
        elif is_table_divider(cells):
            pass
        elif clean_table_cell(cells[0]) in COUNTRY_TABLE_HEADERS:
            country_table_active = True
        elif country_table_active:
            row_country_or_region = clean_table_cell(cells[0])
        markdown_ranges: list[tuple[int, int]] = []
        for match in MARKDOWN_LINK.finditer(raw_line):
            entry = add_entry(entries, match.group(2))
            entry.labels.add(match.group(1).strip())
            entry.sections.add(current_section)
            if row_country_or_region:
                entry.country_or_regions.add(row_country_or_region)
            entry.seen_in_atlas = True
            markdown_ranges.append(match.span(2))
        for match in BARE_URL.finditer(raw_line):
            # A Markdown destination is already recorded with its label; avoid
            # adding a second unlabeled copy from the same characters.
            if any(start <= match.start(1) < end for start, end in markdown_ranges):
                continue
            entry = add_entry(entries, match.group(1))
            entry.sections.add(current_section)
            if row_country_or_region:
                entry.country_or_regions.add(row_country_or_region)
            entry.seen_in_atlas = True


def extract_registry(entries: dict[str, InventoryEntry], registry: dict[str, Any]) -> None:
    for source in registry["sources"]:
        if not isinstance(source, dict):
            raise InventoryError("registry source is not an object")
        source_id = source.get("id")
        if not isinstance(source_id, str) or not source_id:
            raise InventoryError("registry source lacks ID")
        for field_name in ("url", "portal_url"):
            value = source.get(field_name)
            if not isinstance(value, str) or not value:
                continue
            entry = add_entry(entries, value)
            entry.source_ids.add(source_id)
            entry.registry_roles.add(str(source.get("role") or ""))
            entry.registry_access.add(str(source.get("access") or ""))
            entry.seen_in_registry = True


def build_inventory(registry_path: Path = DEFAULT_REGISTRY) -> dict[str, Any]:
    registry_path = registry_path.resolve()
    registry = load_registry(registry_path)
    entries: dict[str, InventoryEntry] = {}
    atlas = atlas_path(registry, registry_path)
    extract_atlas(entries, atlas)
    extract_registry(entries, registry)
    rows = [
        {
            "url": item.url,
            "labels": sorted(item.labels),
            "sections": sorted(item.sections),
            "country_or_regions": sorted(item.country_or_regions),
            "source_ids": sorted(item.source_ids),
            "registry_roles": sorted(role for role in item.registry_roles if role),
            "registry_access": sorted(access for access in item.registry_access if access),
            "seen_in_atlas": item.seen_in_atlas,
            "seen_in_registry": item.seen_in_registry,
            "admission_posture": (
                "registry_managed" if item.seen_in_registry else "atlas_reference_only"
            ),
        }
        for _url, item in sorted(entries.items())
    ]
    return {
        "schema_version": "uap.source_url_inventory.v1",
        "network_contacted": False,
        "registry_path": str(registry_path),
        "atlas_path": str(atlas),
        "url_count": len(rows),
        "registry_managed_url_count": sum(1 for row in rows if row["seen_in_registry"]),
        "atlas_reference_only_url_count": sum(1 for row in rows if not row["seen_in_registry"]),
        "entries": rows,
    }


def render_csv(inventory: dict[str, Any]) -> str:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(
        output,
        fieldnames=(
            "url",
            "labels",
            "sections",
            "country_or_regions",
            "source_ids",
            "registry_roles",
            "registry_access",
            "seen_in_atlas",
            "seen_in_registry",
            "admission_posture",
        ),
    )
    writer.writeheader()
    for entry in inventory["entries"]:
        writer.writerow(
            {
                key: " | ".join(entry[key]) if isinstance(entry[key], list) else entry[key]
                for key in writer.fieldnames
            }
        )
    return output.getvalue()


def write_output(path: Path, content: str) -> None:
    if path.exists() or path.is_symlink():
        raise InventoryError(f"refusing to overwrite output: {path}")
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
    inventory = build_inventory(args.registry)
    if args.format == "json":
        content = json.dumps(inventory, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    else:
        content = render_csv(inventory)
    if args.output:
        write_output(args.output, content)
        print(json.dumps({"output": str(args.output), "network_contacted": False}, ensure_ascii=False))
    else:
        sys.stdout.write(content)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Export every locally recorded global UAP source URL without network access."
    )
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    subparsers = parser.add_subparsers(dest="command", required=True)
    export = subparsers.add_parser("export", help="output URL inventory in JSON or CSV")
    export.add_argument("--format", choices=("json", "csv"), default="json")
    export.add_argument("--output", type=Path)
    export.set_defaults(handler=command_export)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.handler(args))
    except InventoryError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
