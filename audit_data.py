#!/usr/bin/env python3
"""Verify locally stored UAP collection receipts without network or mutation.

The collector keeps raw gzip payloads and canonical JSONL gzip payloads along
with their recorded hashes.  This auditor re-computes those checks locally and
reports source-level counts, plus a specific completeness/duplicate warning for
the nine-body Horizons control series.  It never fetches, rewrites, or deletes
an artifact.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass
import gzip
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Iterable


RECEIPT_SCHEMA_VERSION = "uap.collection_receipt.v1"
HORIZONS_SOURCE_ID = "nasa_horizons_9_bodies"
PLANETS: tuple[tuple[str, str], ...] = (
    ("199", "Mercury"),
    ("299", "Venus"),
    ("399", "Earth"),
    ("499", "Mars"),
    ("599", "Jupiter"),
    ("699", "Saturn"),
    ("799", "Uranus"),
    ("899", "Neptune"),
    ("999", "Pluto"),
)
READ_CHUNK_BYTES = 1024 * 1024
MAX_AUDIT_COMPRESSED_BYTES = 2 * 1024 * 1024 * 1024
MAX_AUDIT_UNCOMPRESSED_BYTES = 1 * 1024 * 1024 * 1024


class AuditError(RuntimeError):
    """A receipt or its locally referenced immutable artifact is invalid."""


@dataclass(frozen=True)
class AuditedReceipt:
    receipt_path: Path
    source_id: str
    snapshot_id: str
    canonical_records: int
    canonical_rows: tuple[dict[str, Any], ...]


def safe_artifact_path(input_root: Path, relative: Any) -> Path:
    if not isinstance(relative, str) or not relative:
        raise AuditError("artifact path is missing")
    candidate = Path(relative)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise AuditError(f"unsafe artifact path in receipt: {relative!r}")
    target = (input_root / candidate).resolve()
    root = input_root.resolve()
    if root not in target.parents:
        raise AuditError(f"artifact path escapes input root: {relative!r}")
    if not target.is_file() or target.is_symlink():
        raise AuditError(f"receipt points to missing/non-regular artifact: {relative!r}")
    return target


def _nonnegative_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise AuditError(f"receipt field {field} must be a non-negative integer")
    return value


def _file_size_and_sha256(path: Path) -> tuple[int, str]:
    hasher = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        while chunk := handle.read(READ_CHUNK_BYTES):
            size += len(chunk)
            if size > MAX_AUDIT_COMPRESSED_BYTES:
                raise AuditError(f"compressed artifact exceeds audit ceiling: {path}")
            hasher.update(chunk)
    return size, hasher.hexdigest()


def read_gzip_artifact(
    *,
    input_root: Path,
    artifact: dict[str, Any],
    required_keys: tuple[str, ...],
    retain_payload: bool,
) -> bytes | None:
    for key in ("path", "gzip_bytes", "gzip_sha256", *required_keys):
        if key not in artifact:
            raise AuditError(f"artifact lacks receipt field: {key}")
    target = safe_artifact_path(input_root, artifact["path"])
    expected_compressed = _nonnegative_int(artifact["gzip_bytes"], "gzip_bytes")
    expected_uncompressed = _nonnegative_int(
        artifact["raw_bytes"] if "raw_bytes" in required_keys else artifact["uncompressed_bytes"],
        "raw_bytes" if "raw_bytes" in required_keys else "uncompressed_bytes",
    )
    if expected_compressed > MAX_AUDIT_COMPRESSED_BYTES:
        raise AuditError(f"receipt compressed artifact exceeds audit ceiling: {target}")
    if expected_uncompressed > MAX_AUDIT_UNCOMPRESSED_BYTES:
        raise AuditError(f"receipt uncompressed artifact exceeds audit ceiling: {target}")
    compressed_size, compressed_hash = _file_size_and_sha256(target)
    if compressed_size != expected_compressed:
        raise AuditError(f"gzip byte count mismatch: {target}")
    if compressed_hash != artifact["gzip_sha256"]:
        raise AuditError(f"gzip SHA-256 mismatch: {target}")
    hasher = hashlib.sha256()
    size = 0
    chunks: list[bytes] | None = [] if retain_payload else None
    try:
        with gzip.open(target, "rb") as handle:
            while chunk := handle.read(READ_CHUNK_BYTES):
                size += len(chunk)
                if size > expected_uncompressed or size > MAX_AUDIT_UNCOMPRESSED_BYTES:
                    raise AuditError(f"uncompressed artifact exceeds receipt/audit ceiling: {target}")
                hasher.update(chunk)
                if chunks is not None:
                    chunks.append(chunk)
    except (OSError, EOFError) as exc:
        raise AuditError(f"invalid gzip artifact: {target}: {exc}") from exc
    raw_bytes_key = "raw_bytes" if "raw_bytes" in required_keys else "uncompressed_bytes"
    raw_sha_key = "raw_sha256" if "raw_sha256" in required_keys else "uncompressed_sha256"
    if size != artifact[raw_bytes_key]:
        raise AuditError(f"uncompressed byte count mismatch: {target}")
    if hasher.hexdigest() != artifact[raw_sha_key]:
        raise AuditError(f"uncompressed SHA-256 mismatch: {target}")
    return b"".join(chunks) if chunks is not None else None


def parse_canonical_rows(payload: bytes, receipt_path: Path) -> tuple[dict[str, Any], ...]:
    records: list[dict[str, Any]] = []
    try:
        lines = payload.decode("utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise AuditError(f"canonical payload is not UTF-8: {receipt_path}") from exc
    for line_number, line in enumerate(lines, start=1):
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise AuditError(f"invalid canonical JSON at {receipt_path}:{line_number}") from exc
        if not isinstance(row, dict):
            raise AuditError(f"canonical row is not an object at {receipt_path}:{line_number}")
        records.append(row)
    return tuple(records)


def audit_receipt(input_root: Path, receipt_path: Path) -> AuditedReceipt:
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AuditError(f"invalid receipt JSON: {receipt_path}: {exc}") from exc
    if receipt.get("schema_version") != RECEIPT_SCHEMA_VERSION:
        raise AuditError(f"unsupported receipt schema: {receipt_path}")
    source_id = receipt.get("source_id")
    snapshot_id = receipt.get("snapshot_id")
    raw_files = receipt.get("raw_files")
    canonical = receipt.get("canonical")
    if not isinstance(source_id, str) or not source_id:
        raise AuditError(f"receipt lacks source_id: {receipt_path}")
    if not isinstance(snapshot_id, str) or not snapshot_id:
        raise AuditError(f"receipt lacks snapshot_id: {receipt_path}")
    if not isinstance(raw_files, list) or not isinstance(canonical, dict):
        raise AuditError(f"receipt lacks raw_files/canonical: {receipt_path}")
    for raw in raw_files:
        if not isinstance(raw, dict):
            raise AuditError(f"receipt raw_files entry is not an object: {receipt_path}")
        read_gzip_artifact(
            input_root=input_root,
            artifact=raw,
            required_keys=("raw_bytes", "raw_sha256"),
            retain_payload=False,
        )
    canonical_payload = read_gzip_artifact(
        input_root=input_root,
        artifact=canonical,
        required_keys=("uncompressed_bytes", "uncompressed_sha256"),
        retain_payload=True,
    )
    if canonical_payload is None:  # narrow type proof; canonical needs JSON parsing below
        raise AuditError(f"canonical payload missing after audit: {receipt_path}")
    rows = parse_canonical_rows(canonical_payload, receipt_path)
    if canonical.get("records") != len(rows):
        raise AuditError(f"canonical record count mismatch: {receipt_path}")
    if any(row.get("source_id") != source_id for row in rows):
        raise AuditError(f"canonical source_id mismatch: {receipt_path}")
    return AuditedReceipt(
        receipt_path=receipt_path,
        source_id=source_id,
        snapshot_id=snapshot_id,
        canonical_records=len(rows),
        canonical_rows=rows,
    )


def horizons_summary(receipts: Iterable[AuditedReceipt]) -> dict[str, Any] | None:
    relevant = [receipt for receipt in receipts if receipt.source_id == HORIZONS_SOURCE_ID]
    if not relevant:
        return None
    expected = dict(PLANETS)
    by_date: dict[str, list[AuditedReceipt]] = defaultdict(list)
    incomplete: list[dict[str, Any]] = []
    for receipt in relevant:
        rows = receipt.canonical_rows
        body_pairs = [(str(row.get("body_id")), str(row.get("title"))) for row in rows]
        observed_dates = {str(row.get("observed_at_start")) for row in rows}
        if len(observed_dates) != 1 or dict(body_pairs) != expected or len(body_pairs) != len(expected):
            incomplete.append(
                {
                    "receipt": receipt.receipt_path.name,
                    "snapshot_id": receipt.snapshot_id,
                    "body_pairs": body_pairs,
                    "observed_dates": sorted(observed_dates),
                }
            )
            continue
        by_date[next(iter(observed_dates))].append(receipt)
    duplicate_dates = {
        day: [receipt.snapshot_id for receipt in snapshots]
        for day, snapshots in sorted(by_date.items())
        if len(snapshots) > 1
    }
    return {
        "expected_bodies": [name for _id, name in PLANETS],
        "complete_dates": sorted(by_date),
        "complete_snapshot_count": sum(len(items) for items in by_date.values()),
        "duplicate_date_snapshots": duplicate_dates,
        "incomplete_or_invalid_snapshots": incomplete,
    }


def audit(input_root: Path) -> dict[str, Any]:
    receipts_root = input_root / "receipts"
    if not receipts_root.is_dir():
        raise AuditError(f"receipts directory does not exist: {receipts_root}")
    audited: list[AuditedReceipt] = []
    errors: list[dict[str, str]] = []
    for receipt_path in sorted(receipts_root.glob("*/*.json")):
        try:
            audited.append(audit_receipt(input_root, receipt_path))
        except AuditError as exc:
            errors.append({"receipt": receipt_path.relative_to(input_root).as_posix(), "error": str(exc)})
    source_snapshots = Counter(receipt.source_id for receipt in audited)
    source_records = Counter()
    source_unique_ids: dict[str, set[str]] = defaultdict(set)
    for receipt in audited:
        source_records[receipt.source_id] += receipt.canonical_records
        for row in receipt.canonical_rows:
            source_record_id = row.get("source_record_id")
            if isinstance(source_record_id, str) and source_record_id:
                source_unique_ids[receipt.source_id].add(source_record_id)
    horizons = horizons_summary(audited)
    warnings: list[dict[str, Any]] = []
    if horizons and horizons["duplicate_date_snapshots"]:
        warnings.append(
            {
                "kind": "duplicate_horizons_date_snapshots",
                "detail": horizons["duplicate_date_snapshots"],
                "action": "retain immutable receipts but count one current observation per source_record_id",
            }
        )
    return {
        "schema_version": "uap.local_data_audit.v1",
        "network_contacted": False,
        "input_root": str(input_root),
        "receipt_count": len(audited),
        "valid_receipt_count": len(audited),
        "error_count": len(errors),
        "errors": errors,
        "source_snapshot_counts": dict(sorted(source_snapshots.items())),
        "source_canonical_record_counts": dict(sorted(source_records.items())),
        "source_unique_record_counts": {
            source_id: len(ids) for source_id, ids in sorted(source_unique_ids.items())
        },
        "horizons_nine_body_control": horizons,
        "warnings": warnings,
        "ok": not errors,
    }


def command_audit(args: argparse.Namespace) -> int:
    report = audit(args.input_root)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["ok"] else 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify local collection receipt hashes and canonical counts without network access."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    audit_parser = subparsers.add_parser("audit", help="audit existing local collection artifacts")
    audit_parser.add_argument("--input-root", type=Path, default=Path(__file__).resolve().parent / "data")
    audit_parser.set_defaults(handler=command_audit)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.handler(args))
    except AuditError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
