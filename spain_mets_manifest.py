#!/usr/bin/env python3
"""Parse a local METS record from Spain's Defence UFO collection.

The Spanish Ministry of Defence's declassified UFO catalogue exposes a METS
download action on individual records.  This program deliberately accepts a
*saved local XML file only*: it emits a manifest for review and never follows
the referenced page-image URLs.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import re
import sys
import tempfile
from typing import Any, Iterable
import xml.etree.ElementTree as ET


SCHEMA_VERSION = "uap.spain_defense_mets_manifest.v1"
MAX_XML_BYTES = 5 * 1024 * 1024
METS_NS = "http://www.loc.gov/METS/"
XLINK_NS = "http://www.w3.org/1999/xlink"
MODS_NS = "http://www.loc.gov/mods/v3"
NS = {"mets": METS_NS, "mods": MODS_NS}


class SpainMetsError(RuntimeError):
    """A local XML artifact is not a safe METS manifest input."""


@dataclass(frozen=True)
class MetsFile:
    file_id: str | None
    mime_type: str | None
    use: str | None
    href: str | None


def _local_xml(path: Path) -> tuple[Path, bytes]:
    resolved = path.resolve()
    if not resolved.is_file():
        raise SpainMetsError(f"METS input is not a regular file: {path}")
    size = resolved.stat().st_size
    if size <= 0 or size > MAX_XML_BYTES:
        raise SpainMetsError(f"METS input must be between 1 and {MAX_XML_BYTES} bytes")
    payload = resolved.read_bytes()
    # ElementTree does not retrieve external entities itself, but reject them
    # explicitly so a later parser substitution cannot turn a metadata reader
    # into a file/network expansion vector.
    if re.search(rb"<!\s*(?:DOCTYPE|ENTITY)\b", payload, flags=re.IGNORECASE):
        raise SpainMetsError("METS input must not contain DOCTYPE or ENTITY declarations")
    return resolved, payload


def _text(element: ET.Element | None) -> str | None:
    if element is None or element.text is None:
        return None
    value = " ".join(element.text.split())
    return value or None


def _first_text(root: ET.Element, paths: Iterable[str]) -> str | None:
    for path in paths:
        value = _text(root.find(path, NS))
        if value is not None:
            return value
    return None


def _first_local_name_text(root: ET.Element, local_name: str) -> str | None:
    """Read one namespaced metadata value without relying on unsupported XPath."""

    for element in root.iter():
        if element.tag.rsplit("}", 1)[-1] == local_name:
            value = _text(element)
            if value is not None:
                return value
    return None


def _canonical_created_at(value: str | None) -> str | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value[:128]
    if parsed.tzinfo is None:
        return parsed.isoformat(timespec="seconds")
    return parsed.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _file_entries(root: ET.Element) -> list[MetsFile]:
    files: list[MetsFile] = []
    for file_group in root.findall(".//mets:fileGrp", NS):
        group_use = file_group.get("USE")
        for file_element in file_group.findall("mets:file", NS):
            location = file_element.find("mets:FLocat", NS)
            files.append(
                MetsFile(
                    file_id=file_element.get("ID"),
                    mime_type=file_element.get("MIMETYPE"),
                    use=group_use,
                    href=(location.get(f"{{{XLINK_NS}}}href") if location is not None else None),
                )
            )
    return files


def parse_manifest(path: Path) -> dict[str, Any]:
    """Create a metadata/file-reference manifest without opening any reference."""

    resolved, payload = _local_xml(path)
    try:
        root = ET.fromstring(payload)
    except ET.ParseError as exc:
        raise SpainMetsError(f"invalid METS XML: {exc}") from exc
    if root.tag != f"{{{METS_NS}}}mets":
        raise SpainMetsError("root element is not METS namespace mets")
    header = root.find("mets:metsHdr", NS)
    title = _first_text(
        root,
        (
            ".//mods:titleInfo/mods:title",
            ".//mets:dmdSec//mets:mdWrap//mets:xmlData//mods:titleInfo/mods:title",
        ),
    )
    date = _first_text(
        root,
        (
            ".//mods:originInfo/mods:dateCreated",
            ".//mets:dmdSec//mets:mdWrap//mets:xmlData//mods:originInfo/mods:dateCreated",
        ),
    )
    rights = _first_text(root, (".//mods:accessCondition",)) or _first_local_name_text(
        root, "accessCondition"
    )
    files = _file_entries(root)
    return {
        "schema_version": SCHEMA_VERSION,
        "network_contacted": False,
        "input": {
            "path": str(resolved),
            "bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        },
        "record": {
            "mets_objid": root.get("OBJID"),
            "mets_created_at": _canonical_created_at(header.get("CREATEDATE") if header else None),
            "title": title,
            "date_created_source": date,
            "rights_text": rights,
        },
        "files": [asdict(item) for item in files],
        "file_count": len(files),
        "media_policy": "manifest_only_no_href_is_fetched",
        "next_action": (
            "Review item scope, rights and selected file references before any page-image acquisition."
        ),
    }


def write_manifest(path: Path, manifest: dict[str, Any]) -> None:
    if path.exists() or path.is_symlink():
        raise SpainMetsError(f"refusing to overwrite manifest: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    content = (json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        handle.write(content)
        temporary = Path(handle.name)
    try:
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()


def command_parse(args: argparse.Namespace) -> int:
    manifest = parse_manifest(args.mets_file)
    if args.output:
        write_manifest(args.output, manifest)
        print(json.dumps({"output": str(args.output), "network_contacted": False}, ensure_ascii=False))
    else:
        print(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Parse a local Spain Defence METS file into a no-download manifest."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    parse_parser = subparsers.add_parser("parse", help="parse local XML; never fetch image hrefs")
    parse_parser.add_argument("--mets-file", type=Path, required=True)
    parse_parser.add_argument("--output", type=Path)
    parse_parser.set_defaults(handler=command_parse)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.handler(args))
    except SpainMetsError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
