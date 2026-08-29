#!/usr/bin/env python3
"""Inspect locally supplied GEIPAN CSV headers before any event import.

CNES/GEIPAN publishes one case-level CSV and one testimony/observation-level
CSV.  The exact relational fields are documented separately in its workbook,
and source exports can evolve.  This module therefore reads *only each local
file's header*, identifies safe join-key candidates, and emits no event rows.

There is deliberately no provider URL or network code here.  A future GEIPAN
normalizer must consume a reviewed manifest produced from the actual approved
CSV snapshot rather than assume that a historical header still applies.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import csv
import hashlib
import json
from pathlib import Path
import re
import sys
import unicodedata
from typing import Any


SCHEMA_VERSION = "uap.geipan_local_schema.v1"
MAX_HEADER_BYTES = 128 * 1024
DELIMITER_CANDIDATES = (";", "|", ",", "\t")


class GeipanSchemaError(RuntimeError):
    """A local GEIPAN file cannot safely be inspected as a CSV header."""


@dataclass(frozen=True)
class HeaderInspection:
    label: str
    path: str
    file_bytes: int
    header_sha256: str
    encoding: str
    delimiter: str
    headers: tuple[str, ...]
    normalized_headers: tuple[str, ...]
    identifier_candidates: tuple[str, ...]
    case_key_candidates: tuple[str, ...]
    privacy_named_headers: tuple[str, ...]


def normalize_header(value: str) -> str:
    """Canonicalize a header name for comparisons, never for event content."""

    decomposed = unicodedata.normalize("NFKD", value)
    without_marks = "".join(char for char in decomposed if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", "_", without_marks.lower()).strip("_")


def _read_header_bytes(path: Path) -> tuple[Path, bytes]:
    resolved = path.resolve()
    if not resolved.is_file():
        raise GeipanSchemaError(f"CSV is not a regular file: {path}")
    with resolved.open("rb") as handle:
        # ``readline`` deliberately stops before the first event row.  GEIPAN
        # field names are ordinary one-line CSV headers; reject an anomalous
        # multi-line header rather than scanning content to recover it.
        payload = handle.readline(MAX_HEADER_BYTES + 1)
    if not payload:
        raise GeipanSchemaError(f"CSV is empty: {path}")
    if len(payload) > MAX_HEADER_BYTES:
        raise GeipanSchemaError(f"CSV header exceeds {MAX_HEADER_BYTES} bytes: {path}")
    return resolved, payload


def _decode_header(payload: bytes) -> tuple[str, str]:
    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return payload.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    raise GeipanSchemaError("CSV header cannot be decoded")


def _parse_headers(text: str) -> tuple[str, tuple[str, ...]]:
    first_line = text.splitlines()[0] if text.splitlines() else text
    delimiter_scores = {
        delimiter: first_line.count(delimiter) for delimiter in DELIMITER_CANDIDATES
    }
    delimiter, count = max(delimiter_scores.items(), key=lambda item: item[1])
    if count <= 0:
        raise GeipanSchemaError("CSV header has no recognized delimiter")
    try:
        row = next(csv.reader([first_line], delimiter=delimiter))
    except csv.Error as exc:
        raise GeipanSchemaError(f"CSV header cannot be parsed: {exc}") from exc
    headers = tuple(header.strip() for header in row)
    if len(headers) < 2 or any(not header for header in headers):
        raise GeipanSchemaError("CSV header must contain at least two non-empty fields")
    normalized = tuple(normalize_header(header) for header in headers)
    if any(not header for header in normalized) or len(set(normalized)) != len(normalized):
        raise GeipanSchemaError("CSV header has duplicate or unnormalizable field names")
    return delimiter, headers


def _identifier_candidates(headers: tuple[str, ...]) -> tuple[str, ...]:
    normalized = {header: normalize_header(header) for header in headers}
    return tuple(
        header
        for header, key in normalized.items()
        if key == "id" or key.endswith("_id") or key.startswith("id_") or "identifiant" in key
    )


def _case_key_candidates(headers: tuple[str, ...]) -> tuple[str, ...]:
    normalized = {header: normalize_header(header) for header in headers}
    return tuple(
        header
        for header, key in normalized.items()
        if key in {"case_id", "cas_id", "id_cas", "identifiant_cas"}
        or ("cas" in key and ("id" in key or "identifiant" in key))
        or ("case" in key and ("id" in key or "identifiant" in key))
    )


def _privacy_named_headers(headers: tuple[str, ...]) -> tuple[str, ...]:
    markers = ("nom", "prenom", "adresse", "mail", "email", "telephone", "tel", "identite")
    return tuple(
        header
        for header in headers
        if any(marker in normalize_header(header) for marker in markers)
    )


def inspect_header(path: Path, *, label: str) -> HeaderInspection:
    """Return only CSV schema facts; no data row is read or emitted."""

    if label not in {"cases", "testimonies"}:
        raise GeipanSchemaError("label must be cases or testimonies")
    resolved, payload = _read_header_bytes(path)
    text, encoding = _decode_header(payload)
    delimiter, headers = _parse_headers(text)
    return HeaderInspection(
        label=label,
        path=str(resolved),
        file_bytes=resolved.stat().st_size,
        header_sha256=hashlib.sha256((delimiter.join(headers) + "\n").encode("utf-8")).hexdigest(),
        encoding=encoding,
        delimiter=delimiter,
        headers=headers,
        normalized_headers=tuple(normalize_header(header) for header in headers),
        identifier_candidates=_identifier_candidates(headers),
        case_key_candidates=_case_key_candidates(headers),
        privacy_named_headers=_privacy_named_headers(headers),
    )


def _shared_headers(cases: HeaderInspection, testimonies: HeaderInspection) -> tuple[str, ...]:
    case_by_normalized = dict(zip(cases.normalized_headers, cases.headers, strict=True))
    testimony_normalized = set(testimonies.normalized_headers)
    return tuple(
        case_by_normalized[key]
        for key in cases.normalized_headers
        if key in testimony_normalized
    )


def _join_key_candidates(cases: HeaderInspection, testimonies: HeaderInspection) -> tuple[str, ...]:
    def semantic_case_key(header: str) -> str | None:
        key = normalize_header(header)
        if key in {"case_id", "id_case", "cas_id", "id_cas", "identifiant_cas"}:
            return "case_id"
        if ("cas" in key or "case" in key) and ("id" in key or "identifiant" in key):
            return "case_id"
        return None

    case_normalized = set(cases.normalized_headers)
    testimony_normalized = set(testimonies.normalized_headers)
    case_keys = {semantic_case_key(value) for value in cases.case_key_candidates}
    testimony_keys = {semantic_case_key(value) for value in testimonies.case_key_candidates}
    strong = sorted((case_keys & testimony_keys) - {None})
    if strong:
        return tuple(strong)
    # The output is intentionally a candidate—not an automatically chosen key.
    return tuple(
        key
        for key in sorted(case_normalized & testimony_normalized)
        if key in {"case_id", "cas_id", "id_cas", "identifiant_cas"}
    )


def inspect_pair(cases_csv: Path, testimonies_csv: Path) -> dict[str, Any]:
    """Inspect both local headers and state whether an explicit join review is needed."""

    cases = inspect_header(cases_csv, label="cases")
    testimonies = inspect_header(testimonies_csv, label="testimonies")
    join_candidates = _join_key_candidates(cases, testimonies)
    return {
        "schema_version": SCHEMA_VERSION,
        "network_contacted": False,
        "records_read": 0,
        "inputs": [asdict(cases), asdict(testimonies)],
        "shared_headers": _shared_headers(cases, testimonies),
        "case_join_key_candidates": join_candidates,
        "admission_result": (
            "candidate_join_key_found_manual_relation_and_privacy_review_required"
            if join_candidates
            else "no_safe_join_key_inferred_manual_schema_mapping_required"
        ),
        "next_action": (
            "Confirm case-to-testimony cardinality against the official GEIPAN workbook; "
            "do not join or import event rows yet."
        ),
    }


def command_inspect(args: argparse.Namespace) -> int:
    report = inspect_pair(args.cases_csv, args.testimonies_csv)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Read local GEIPAN CSV headers only; makes no network request or row import."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    inspect_parser = subparsers.add_parser("inspect", help="inspect two locally supplied CSV headers")
    inspect_parser.add_argument("--cases-csv", type=Path, required=True)
    inspect_parser.add_argument("--testimonies-csv", type=Path, required=True)
    inspect_parser.set_defaults(handler=command_inspect)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.handler(args))
    except GeipanSchemaError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
