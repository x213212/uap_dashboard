#!/usr/bin/env python3
"""Build a map-ready nine-body ephemeris product from saved Horizons raw data.

This command has no HTTP client.  It validates an existing immutable receipt
and its compressed raw artifacts, then derives a small structured JSONL-gzip
product.  The current product is intentionally heliocentric/bodycentric: it
is a reference layer, not a topocentric explanation for any sighting.
"""

from __future__ import annotations

import argparse
from datetime import date
import gzip
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from typing import Any

try:  # Works both as `python uap_lab/ephemeris_export.py` and as a package import.
    import audit_data
    import collect
except ModuleNotFoundError:  # pragma: no cover - covered by the direct-script path
    from uap_lab import audit_data, collect


ROOT = Path(__file__).resolve().parent
DEFAULT_DATA_ROOT = ROOT / "data"
DEFAULT_OUTPUT_ROOT = DEFAULT_DATA_ROOT / "derived" / "ephemeris"
HORIZONS_SOURCE_ID = "nasa_horizons_9_bodies"
EPHEMERIS_SCHEMA_VERSION = "uap.ephemeris.v1"
MANIFEST_SCHEMA_VERSION = "uap.ephemeris_export_manifest.v1"


class EphemerisExportError(RuntimeError):
    """A saved snapshot cannot safely become a derived ephemeris product."""


def read_snapshot_receipt(input_root: Path, snapshot_id: str) -> tuple[Path, dict[str, Any]]:
    if not snapshot_id or "/" in snapshot_id or "\\" in snapshot_id or snapshot_id in {".", ".."}:
        raise EphemerisExportError("snapshot ID is unsafe")
    target = input_root / "receipts" / HORIZONS_SOURCE_ID / f"{snapshot_id}.json"
    if not target.is_file() or target.is_symlink():
        raise EphemerisExportError(f"Horizons receipt does not exist: {target}")
    try:
        receipt = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EphemerisExportError(f"cannot read Horizons receipt: {target}: {exc}") from exc
    if receipt.get("source_id") != HORIZONS_SOURCE_ID or receipt.get("snapshot_id") != snapshot_id:
        raise EphemerisExportError("receipt source or snapshot identity does not match its path")
    return target, receipt


def source_for_export(registry_path: Path) -> collect.Source:
    _registry, sources = collect.load_registry(registry_path)
    source = sources.get(HORIZONS_SOURCE_ID)
    if source is None or source.kind != "nasa_horizons_planets":
        raise EphemerisExportError("Horizons source is missing or has an unexpected registry kind")
    return source


def verified_ephemeris_rows(
    *, input_root: Path, registry_path: Path, snapshot_id: str
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Validate receipt/raw data and derive exactly one row for each body."""

    receipt_path, receipt = read_snapshot_receipt(input_root, snapshot_id)
    try:
        audited = audit_data.audit_receipt(input_root, receipt_path)
    except audit_data.AuditError as exc:
        raise EphemerisExportError(f"immutable receipt audit failed: {exc}") from exc
    if audited.source_id != HORIZONS_SOURCE_ID:
        raise EphemerisExportError("audited receipt is not a Horizons snapshot")
    raw_files = receipt.get("raw_files")
    if not isinstance(raw_files, list):
        raise EphemerisExportError("Horizons receipt has no raw file list")
    expected_names = dict(collect.PLANETS)
    if len(raw_files) != len(expected_names):
        raise EphemerisExportError("Horizons receipt does not have exactly nine raw artifacts")

    source = source_for_export(registry_path)
    rows_by_body: dict[str, dict[str, Any]] = {}
    for raw in raw_files:
        if not isinstance(raw, dict):
            raise EphemerisExportError("Horizons receipt contains a non-object raw artifact")
        query_url = raw.get("request_url")
        if not isinstance(query_url, str):
            raise EphemerisExportError("Horizons raw artifact lacks a request URL")
        try:
            body_id = collect.horizons_query_value(query_url, "COMMAND")
            start = date.fromisoformat(collect.horizons_query_value(query_url, "START_TIME"))
            payload = audit_data.read_gzip_artifact(
                input_root=input_root,
                artifact=raw,
                required_keys=("raw_bytes", "raw_sha256"),
                retain_payload=True,
            )
        except (collect.CollectionError, audit_data.AuditError, ValueError) as exc:
            raise EphemerisExportError(f"invalid Horizons raw artifact: {exc}") from exc
        if body_id not in expected_names or body_id in rows_by_body or payload is None:
            raise EphemerisExportError("Horizons raw artifact set has an invalid or duplicate body ID")
        try:
            ephemeris = collect.parse_horizons_ephemeris(
                body_id=body_id,
                body_name=expected_names[body_id],
                query_url=query_url,
                payload=payload,
                start=start,
            )
        except collect.CollectionError as exc:
            raise EphemerisExportError(f"cannot parse Horizons {body_id}: {exc}") from exc
        if ephemeris.get("schema_version") != EPHEMERIS_SCHEMA_VERSION:
            raise EphemerisExportError("derived ephemeris schema does not match the exporter contract")
        rows_by_body[body_id] = {
            **ephemeris,
            "source_id": source.source_id,
            "source_portal_url": source.portal_url or source.url,
            "snapshot_id": snapshot_id,
            "source_record_id": f"{body_id}-{start.isoformat()}",
            "original_source_url": query_url,
        }
    if set(rows_by_body) != set(expected_names):
        raise EphemerisExportError("Horizons snapshot is missing one or more historical-nine bodies")
    rows = [rows_by_body[body_id] for body_id, _name in collect.PLANETS]
    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "network_contacted": False,
        "source_id": source.source_id,
        "source_portal_url": source.portal_url or source.url,
        "snapshot_id": snapshot_id,
        "receipt_path": receipt_path.relative_to(input_root).as_posix(),
        "record_count": len(rows),
        "bodies": [row["body_name"] for row in rows],
        "observer_mode": collect.HORIZONS_OBSERVER_MODE,
        "observer_center": collect.HORIZONS_OBSERVER_CENTER,
        "topocentric_match_permitted": False,
        "raw_receipt_audited": True,
    }
    return rows, manifest


def write_new_file(path: Path, payload: bytes) -> None:
    """Atomically write a new file without overwriting a prior derived product."""

    if path.exists() or path.is_symlink():
        raise EphemerisExportError(f"refusing to overwrite output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        handle.write(payload)
        temporary = Path(handle.name)
    try:
        if path.exists() or path.is_symlink():
            raise EphemerisExportError(f"refusing to overwrite output: {path}")
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()


def output_paths(output_root: Path, snapshot_id: str) -> tuple[Path, Path]:
    target_root = output_root / HORIZONS_SOURCE_ID / snapshot_id
    return target_root / "ephemeris.jsonl.gz", target_root / "manifest.json"


def build_export(
    *, input_root: Path, registry_path: Path, output_root: Path, snapshot_id: str, dry_run: bool
) -> dict[str, Any]:
    rows, manifest = verified_ephemeris_rows(
        input_root=input_root,
        registry_path=registry_path,
        snapshot_id=snapshot_id,
    )
    records_payload = (
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows).encode("utf-8")
    )
    records_gzip = gzip.compress(records_payload, compresslevel=9, mtime=0)
    records_path, manifest_path = output_paths(output_root, snapshot_id)
    result = {
        **manifest,
        "output_records_path": str(records_path),
        "output_manifest_path": str(manifest_path),
        "records_uncompressed_bytes": len(records_payload),
        "records_gzip_bytes": len(records_gzip),
        "records_uncompressed_sha256": hashlib.sha256(records_payload).hexdigest(),
        "records_gzip_sha256": hashlib.sha256(records_gzip).hexdigest(),
        "dry_run": dry_run,
    }
    if dry_run:
        return result
    if records_path.exists() or records_path.is_symlink() or manifest_path.exists() or manifest_path.is_symlink():
        raise EphemerisExportError("refusing to overwrite an existing ephemeris product")
    manifest_payload = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + b"\n"
    write_new_file(records_path, records_gzip)
    try:
        write_new_file(manifest_path, manifest_payload)
    except EphemerisExportError:
        # Keep the already written product immutable rather than deleting a
        # potentially inspectable artifact. The caller can choose a new root.
        raise
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-root", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument("--registry", type=Path, default=ROOT / "sources.json")
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--snapshot-id", required=True)
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = build_export(
            input_root=args.input_root,
            registry_path=args.registry,
            output_root=args.output_root,
            snapshot_id=args.snapshot_id,
            dry_run=args.dry_run,
        )
    except (EphemerisExportError, collect.CollectionError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
