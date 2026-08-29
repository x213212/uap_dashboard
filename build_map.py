#!/usr/bin/env python3
"""Build a map-ready, reproducible observation lake from collection receipts.

The collector deliberately preserves source payloads as immutable gzip files.
This program is the separate *derived-data* step: it reads only canonical
JSONL files referenced by valid receipts, writes GeoParquet observation
versions, creates a local DuckDB catalogue, and emits compact GeoJSON map
layers.  It never contacts a provider and never mutates raw evidence.

It keeps three concepts distinct:

* an ``observation`` is one source's report or control record;
* an ``observation version`` is that record as seen in one source snapshot;
* a map feature is a privacy-filtered, rebuildable view of the current version.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
import gzip
import hashlib
import json
import math
from pathlib import Path
import re
import struct
import sys
import tempfile
from typing import Any, Iterable, Iterator

try:
    import duckdb
    import pyarrow as pa
    import pyarrow.parquet as pq
except ImportError as exc:  # pragma: no cover - exercised at CLI use time
    raise SystemExit(
        "build_map.py requires duckdb and pyarrow. Install the map-build dependencies first."
    ) from exc


ROOT = Path(__file__).resolve().parent
DEFAULT_INPUT_ROOT = ROOT / "data"
DEFAULT_DERIVED_ROOT = DEFAULT_INPUT_ROOT / "derived"
DEFAULT_WAREHOUSE_PATH = DEFAULT_INPUT_ROOT / "warehouse" / "uap.duckdb"
OBSERVATION_SCHEMA_VERSION = "uap.observation.v1"
MAP_RELEASE_SCHEMA_VERSION = "uap.map_release.v1"
RECEIPT_SCHEMA_VERSION = "uap.collection_receipt.v1"

YEAR_RE = re.compile(r"^(?P<year>\d{4})(?:[-/]?(?P<month>\d{2}))?")


@dataclass(frozen=True)
class ReceiptInput:
    receipt_path: Path
    source_id: str
    snapshot_id: str
    collected_at: datetime
    canonical_path: Path
    snapshot_raw_sha256: str


def utc_now() -> datetime:
    return datetime.now(UTC)


def utc_stamp(value: datetime | None = None) -> str:
    return (value or utc_now()).strftime("%Y%m%dT%H%M%S%fZ")


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        handle.write(payload)
        temporary = Path(handle.name)
    temporary.replace(path)


def write_json(path: Path, payload: Any) -> None:
    atomic_write(
        path,
        (json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode(
            "utf-8"
        ),
    )


def parse_datetime(value: Any) -> datetime | None:
    """Parse an unambiguous ISO-like source time without inventing precision."""

    if not isinstance(value, str) or not value.strip():
        return None
    normalized = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def year_month_from_source_time(value: Any, parsed: datetime | None) -> tuple[int | None, int | None]:
    if parsed is not None:
        return parsed.year, parsed.month
    if not isinstance(value, str):
        return None, None
    match = YEAR_RE.match(value.strip())
    if not match:
        return None, None
    year = int(match.group("year"))
    month_text = match.group("month")
    month = int(month_text) if month_text and 1 <= int(month_text) <= 12 else None
    return year, month


def safe_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def valid_lat_lon(latitude: Any, longitude: Any) -> tuple[float, float] | None:
    lat = safe_float(latitude)
    lon = safe_float(longitude)
    if lat is None or lon is None or not -90 <= lat <= 90 or not -180 <= lon <= 180:
        return None
    return lat, lon


def point_wkb(longitude: float, latitude: float) -> bytes:
    """Return little-endian OGC WKB for a WGS84 Point (x=longitude, y=latitude)."""

    return struct.pack("<BIdd", 1, 1, longitude, latitude)


def record_role(record: dict[str, Any]) -> str:
    record_type = str(record.get("record_type") or "")
    source_role = str(record.get("source_role") or "")
    if record_type in {"sighting", "curated_incident"}:
        return "sighting"
    if record_type.startswith("astronomy_control_"):
        return "astronomy_control"
    if "control" in source_role:
        return "other_control"
    if "document" in record_type or "archive" in source_role:
        return "official_document"
    return "other"


def privacy_tier(record: dict[str, Any], has_geometry: bool) -> str:
    """Describe publication posture without inferring a source licence."""

    if not has_geometry:
        return "no_geometry"
    if record.get("coordinate_precision"):
        return "source_published_coarse_or_unknown"
    return "source_published_precision_unspecified"


def compact_extra(record: dict[str, Any]) -> str:
    known = {
        "schema_version",
        "source_id",
        "source_record_id",
        "canonical_event_id",
        "record_type",
        "observed_at_start",
        "observed_at_end",
        "time_precision",
        "location_name",
        "country_code",
        "latitude",
        "longitude",
        "coordinate_precision",
        "venue",
        "title",
        "summary",
        "original_source_url",
        "source_portal_url",
        "status",
        "explanation",
        "media_url",
        "source_role",
    }
    extra = {key: value for key, value in record.items() if key not in known}
    return json.dumps(extra, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def receipt_inputs(input_root: Path) -> Iterator[ReceiptInput]:
    receipts_root = input_root / "receipts"
    if not receipts_root.is_dir():
        raise RuntimeError(f"no receipts directory: {receipts_root}")
    for receipt_path in sorted(receipts_root.glob("*/*.json")):
        try:
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"invalid receipt: {receipt_path}: {exc}") from exc
        if receipt.get("schema_version") != RECEIPT_SCHEMA_VERSION:
            continue
        source_id = receipt.get("source_id")
        snapshot_id = receipt.get("snapshot_id")
        collected_at = parse_datetime(receipt.get("collected_at"))
        canonical = receipt.get("canonical")
        if (
            not isinstance(source_id, str)
            or not isinstance(snapshot_id, str)
            or collected_at is None
            or not isinstance(canonical, dict)
            or not isinstance(canonical.get("path"), str)
        ):
            raise RuntimeError(f"receipt lacks required fields: {receipt_path}")
        canonical_path = input_root / canonical["path"]
        if not canonical_path.is_file():
            raise RuntimeError(f"receipt points to missing canonical payload: {canonical_path}")
        raw_hashes = sorted(
            item["raw_sha256"]
            for item in receipt.get("raw_files", [])
            if isinstance(item, dict) and isinstance(item.get("raw_sha256"), str)
        )
        if not raw_hashes:
            raise RuntimeError(f"receipt has no raw SHA-256 values: {receipt_path}")
        yield ReceiptInput(
            receipt_path=receipt_path,
            source_id=source_id,
            snapshot_id=snapshot_id,
            collected_at=collected_at,
            canonical_path=canonical_path,
            snapshot_raw_sha256=sha256_text("\n".join(raw_hashes)),
        )


def canonical_rows(receipt: ReceiptInput) -> Iterator[dict[str, Any]]:
    with gzip.open(receipt.canonical_path, mode="rt", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise RuntimeError(
                    f"invalid canonical JSON at {receipt.canonical_path}:{line_number}: {exc}"
                ) from exc
            if not isinstance(row, dict):
                raise RuntimeError(
                    f"canonical row is not an object at {receipt.canonical_path}:{line_number}"
                )
            yield row


def observation_row(record: dict[str, Any], receipt: ReceiptInput) -> dict[str, Any]:
    source_id = str(record.get("source_id") or receipt.source_id)
    if source_id != receipt.source_id:
        raise RuntimeError(
            f"source mismatch in {receipt.canonical_path}: {source_id} != {receipt.source_id}"
        )
    source_record_id = str(record.get("source_record_id") or "")
    if not source_record_id:
        raise RuntimeError(f"canonical record has no source_record_id: {receipt.canonical_path}")
    observed_start_raw = record.get("observed_at_start")
    observed_end_raw = record.get("observed_at_end")
    observed_start = parse_datetime(observed_start_raw)
    observed_end = parse_datetime(observed_end_raw)
    observed_year, observed_month = year_month_from_source_time(observed_start_raw, observed_start)
    coordinate = valid_lat_lon(record.get("latitude"), record.get("longitude"))
    if coordinate is None:
        latitude = longitude = None
        geometry = None
        xmin = ymin = xmax = ymax = None
    else:
        latitude, longitude = coordinate
        geometry = point_wkb(longitude, latitude)
        xmin = xmax = longitude
        ymin = ymax = latitude
    key_material = f"{source_id}\x00{source_record_id}"
    observation_key = sha256_text(key_material)
    observation_version_id = sha256_text(f"{key_material}\x00{receipt.snapshot_id}")
    role = record_role(record)
    has_geometry = geometry is not None
    return {
        "schema_version": OBSERVATION_SCHEMA_VERSION,
        "observation_id": observation_key,
        "observation_version_id": observation_version_id,
        "source_id": source_id,
        "source_record_id": source_record_id,
        "snapshot_id": receipt.snapshot_id,
        "collected_at_utc": receipt.collected_at,
        "snapshot_raw_sha256": receipt.snapshot_raw_sha256,
        "record_type": str(record.get("record_type") or ""),
        "record_role": role,
        "observed_at_start_raw": str(observed_start_raw) if observed_start_raw is not None else None,
        "observed_at_end_raw": str(observed_end_raw) if observed_end_raw is not None else None,
        "observed_at_start_utc": observed_start,
        "observed_at_end_utc": observed_end,
        "time_precision": record.get("time_precision"),
        "observed_year": observed_year,
        "observed_month": observed_month,
        "geom_original_wkb": geometry,
        "geom_display_wkb": geometry,
        "longitude": longitude,
        "latitude": latitude,
        "bbox_xmin": xmin,
        "bbox_ymin": ymin,
        "bbox_xmax": xmax,
        "bbox_ymax": ymax,
        "coordinate_precision_source": record.get("coordinate_precision"),
        "coordinate_precision_m": None,
        "location_method": "source_coordinates" if has_geometry else "not_geocoded",
        "privacy_tier": privacy_tier(record, has_geometry),
        "location_name": record.get("location_name"),
        "country_code": record.get("country_code"),
        "venue": record.get("venue"),
        "title": record.get("title"),
        "summary_redacted": record.get("summary"),
        "status": record.get("status"),
        "explanation": record.get("explanation"),
        "original_source_url": record.get("original_source_url"),
        "source_portal_url": record.get("source_portal_url"),
        "media_url": record.get("media_url"),
        "rights_status": "source_published_check_terms",
        "canonical_event_id": record.get("canonical_event_id"),
        "normalizer_schema_version": record.get("schema_version"),
        "extra_json": compact_extra(record),
    }


OBSERVATION_FIELDS: tuple[tuple[str, pa.DataType], ...] = (
    ("schema_version", pa.string()),
    ("observation_id", pa.string()),
    ("observation_version_id", pa.string()),
    ("source_id", pa.string()),
    ("source_record_id", pa.string()),
    ("snapshot_id", pa.string()),
    ("collected_at_utc", pa.timestamp("us", tz="UTC")),
    ("snapshot_raw_sha256", pa.string()),
    ("record_type", pa.string()),
    ("record_role", pa.string()),
    ("observed_at_start_raw", pa.string()),
    ("observed_at_end_raw", pa.string()),
    ("observed_at_start_utc", pa.timestamp("us", tz="UTC")),
    ("observed_at_end_utc", pa.timestamp("us", tz="UTC")),
    ("time_precision", pa.string()),
    ("observed_year", pa.int32()),
    ("observed_month", pa.int8()),
    ("geom_original_wkb", pa.binary()),
    ("geom_display_wkb", pa.binary()),
    ("longitude", pa.float64()),
    ("latitude", pa.float64()),
    ("bbox_xmin", pa.float64()),
    ("bbox_ymin", pa.float64()),
    ("bbox_xmax", pa.float64()),
    ("bbox_ymax", pa.float64()),
    ("coordinate_precision_source", pa.string()),
    ("coordinate_precision_m", pa.float64()),
    ("location_method", pa.string()),
    ("privacy_tier", pa.string()),
    ("location_name", pa.string()),
    ("country_code", pa.string()),
    ("venue", pa.string()),
    ("title", pa.string()),
    ("summary_redacted", pa.string()),
    ("status", pa.string()),
    ("explanation", pa.string()),
    ("original_source_url", pa.string()),
    ("source_portal_url", pa.string()),
    ("media_url", pa.string()),
    ("rights_status", pa.string()),
    ("canonical_event_id", pa.string()),
    ("normalizer_schema_version", pa.string()),
    ("extra_json", pa.string()),
)


def geo_parquet_schema() -> pa.Schema:
    """Return the stable observation schema with GeoParquet 1.1 metadata."""

    schema = pa.schema([pa.field(name, field_type) for name, field_type in OBSERVATION_FIELDS])
    geometry_metadata = {
        "version": "1.1.0",
        "primary_column": "geom_display_wkb",
        "columns": {
            "geom_display_wkb": {
                "encoding": "WKB",
                "geometry_types": ["Point"],
                "bbox": [-180.0, -90.0, 180.0, 90.0],
            },
            "geom_original_wkb": {
                "encoding": "WKB",
                "geometry_types": ["Point"],
                "bbox": [-180.0, -90.0, 180.0, 90.0],
            },
        },
    }
    metadata = {
        b"geo": json.dumps(geometry_metadata, separators=(",", ":")).encode("utf-8"),
        b"uap_observation_schema": OBSERVATION_SCHEMA_VERSION.encode("utf-8"),
    }
    return schema.with_metadata(metadata)


def arrow_table(rows: list[dict[str, Any]]) -> pa.Table:
    schema = geo_parquet_schema()
    columns = {name: [row.get(name) for row in rows] for name, _field_type in OBSERVATION_FIELDS}
    return pa.Table.from_pydict(columns, schema=schema)


def safe_partition(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value) or "unknown"


COUNTRY_LABEL_MAP_PATH = Path(__file__).resolve().parent / "country_label_map.json"
_COUNTRY_LABELS: dict[str, dict[str, Any]] | None = None


def country_label_map() -> dict[str, dict[str, Any]]:
    """Source country labels resolved to ISO 3166-1 alpha-2 where unambiguous.

    Sources write their own bucket names ("USA", "Scandanavian and Finland",
    "The Moon"), so the same country arrives under several spellings and some
    labels name no single country at all.  The map keeps the original label and
    only adds a code when the label resolves to exactly one country.
    """

    global _COUNTRY_LABELS
    if _COUNTRY_LABELS is None:
        try:
            document = json.loads(COUNTRY_LABEL_MAP_PATH.read_text(encoding="utf-8"))
            _COUNTRY_LABELS = document.get("labels", {})
        except OSError:
            _COUNTRY_LABELS = {}
    return _COUNTRY_LABELS


def map_feature(row: dict[str, Any]) -> dict[str, Any] | None:
    if row["longitude"] is None or row["latitude"] is None:
        return None
    resolved_country = country_label_map().get(row["country_code"] or "", {})
    properties = {
        "observation_id": row["observation_id"],
        "source_id": row["source_id"],
        "source_record_id": row["source_record_id"],
        "record_role": row["record_role"],
        "record_type": row["record_type"],
        "observed_at_start": row["observed_at_start_raw"],
        "time_precision": row["time_precision"],
        "coordinate_precision": row["coordinate_precision_source"],
        "privacy_tier": row["privacy_tier"],
        "location_name": row["location_name"],
        "country_code": row["country_code"],
        "country_iso_a2": resolved_country.get("iso_a2"),
        "location_scope": resolved_country.get("scope"),
        "venue": row["venue"],
        "title": row["title"],
        "status": row["status"],
        # The source's own wording of what was reported.  It is evidence text:
        # the map shows it verbatim and never rewrites or translates it.
        "summary": row["summary_redacted"],
        "explanation": row["explanation"],
        "media_url": row["media_url"],
        "original_source_url": row["original_source_url"],
        "source_portal_url": row["source_portal_url"],
    }
    return {
        "type": "Feature",
        "id": row["observation_id"],
        "geometry": {"type": "Point", "coordinates": [row["longitude"], row["latitude"]]},
        "properties": {key: value for key, value in properties.items() if value is not None},
    }


def write_geojson_gzip(path: Path, rows: Iterable[dict[str, Any]]) -> int:
    features = [feature for row in rows if (feature := map_feature(row)) is not None]
    payload = json.dumps(
        {"type": "FeatureCollection", "features": features},
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    compressed = gzip.compress(payload, compresslevel=9, mtime=0)
    atomic_write(path, compressed)
    return len(features)


def map_artifact_manifest(path: Path, release_root: Path, feature_count: int) -> dict[str, Any]:
    """Describe a generated map artifact without making it a source of truth."""

    digest = hashlib.sha256()
    byte_count = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
            byte_count += len(chunk)
    return {
        "path": path.relative_to(release_root).as_posix(),
        "feature_count": feature_count,
        "compressed_bytes": byte_count,
        "compressed_sha256": digest.hexdigest(),
        "content_type": "application/geo+json",
        "content_encoding": "gzip",
    }


def sql_path(path: Path) -> str:
    return str(path.resolve()).replace("'", "''")


def create_catalogue(warehouse_path: Path, parquet_glob: str, release_id: str, manifest: dict[str, Any]) -> None:
    warehouse_path.parent.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect(str(warehouse_path))
    try:
        input_glob = parquet_glob.replace("'", "''")
        connection.execute(
            "CREATE OR REPLACE VIEW observation_versions AS "
            f"SELECT * FROM read_parquet('{input_glob}', hive_partitioning=false)"
        )
        connection.execute(
            "CREATE OR REPLACE VIEW observations_current AS "
            "SELECT * EXCLUDE (_current_rank) FROM ("
            " SELECT *, row_number() OVER ("
            "   PARTITION BY source_id, source_record_id "
            "   ORDER BY collected_at_utc DESC, snapshot_id DESC"
            " ) AS _current_rank "
            " FROM observation_versions"
            ") WHERE _current_rank = 1"
        )
        connection.execute(
            "CREATE OR REPLACE VIEW map_sightings_current AS "
            "SELECT * FROM observations_current "
            "WHERE record_role = 'sighting' AND geom_display_wkb IS NOT NULL"
        )
        connection.execute(
            "CREATE OR REPLACE VIEW map_controls_current AS "
            "SELECT * FROM observations_current "
            "WHERE record_role <> 'sighting' AND geom_display_wkb IS NOT NULL"
        )
        connection.execute(
            "CREATE TABLE IF NOT EXISTS map_build_runs ("
            "release_id VARCHAR PRIMARY KEY, built_at TIMESTAMPTZ, manifest_json VARCHAR)"
        )
        connection.execute(
            "INSERT OR REPLACE INTO map_build_runs VALUES (?, ?, ?)",
            [release_id, utc_now(), json.dumps(manifest, ensure_ascii=False, sort_keys=True)],
        )
    finally:
        connection.close()


def build_release(
    *, input_root: Path, derived_root: Path, warehouse_path: Path, release_id: str
) -> dict[str, Any]:
    release_root = derived_root / "releases" / release_id
    versions_root = release_root / "observation_versions" / "schema=v1"
    map_root = release_root / "map_features"
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    current: dict[str, dict[str, Any]] = {}
    source_counter: Counter[str] = Counter()
    role_counter: Counter[str] = Counter()
    input_receipts: list[dict[str, str]] = []
    version_count = 0

    for receipt in receipt_inputs(input_root):
        input_receipts.append(
            {
                "source_id": receipt.source_id,
                "snapshot_id": receipt.snapshot_id,
                "receipt": receipt.receipt_path.relative_to(input_root).as_posix(),
            }
        )
        for record in canonical_rows(receipt):
            row = observation_row(record, receipt)
            year = str(row["observed_year"]) if row["observed_year"] is not None else "unknown"
            month = f"{row['observed_month']:02d}" if row["observed_month"] is not None else "unknown"
            grouped[(safe_partition(row["source_id"]), year, month)].append(row)
            version_count += 1
            source_counter[row["source_id"]] += 1
            role_counter[row["record_role"]] += 1
            existing = current.get(row["observation_id"])
            if existing is None or (
                row["collected_at_utc"], row["snapshot_id"]
            ) > (existing["collected_at_utc"], existing["snapshot_id"]):
                current[row["observation_id"]] = row

    if not grouped:
        raise RuntimeError("no valid canonical records found in collection receipts")
    parquet_paths: list[str] = []
    for (source_id, year, month), rows in sorted(grouped.items()):
        parquet_path = (
            versions_root
            / f"source_id={source_id}"
            / f"observed_year={year}"
            / f"observed_month={month}"
            / "observations.parquet"
        )
        parquet_path.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(arrow_table(rows), parquet_path, compression="zstd", compression_level=9)
        parquet_paths.append(parquet_path.relative_to(release_root).as_posix())

    current_rows = list(current.values())
    sightings = [row for row in current_rows if row["record_role"] == "sighting"]
    controls = [row for row in current_rows if row["record_role"] != "sighting"]
    sightings_path = map_root / "sightings_current.geojson.gz"
    controls_path = map_root / "controls_current.geojson.gz"
    sighting_features = write_geojson_gzip(sightings_path, sightings)
    control_features = write_geojson_gzip(controls_path, controls)
    manifest = {
        "schema_version": MAP_RELEASE_SCHEMA_VERSION,
        "release_id": release_id,
        "built_at": utc_now().isoformat(),
        "input_root": str(input_root.resolve()),
        "input_receipts": input_receipts,
        "observation_schema_version": OBSERVATION_SCHEMA_VERSION,
        "observation_version_count": version_count,
        "observation_current_count": len(current_rows),
        "source_record_counts": dict(sorted(source_counter.items())),
        "role_version_counts": dict(sorted(role_counter.items())),
        "map_features": {
            "sightings_current": sighting_features,
            "controls_current": control_features,
        },
        "map_artifacts": {
            "sightings_current": map_artifact_manifest(
                sightings_path, release_root, sighting_features
            ),
            "controls_current": map_artifact_manifest(
                controls_path, release_root, control_features
            ),
        },
        "parquet_paths": parquet_paths,
        "h3": {
            "computed": False,
            "reason": "H3 is a derived optional layer; no H3 runtime is installed in this build.",
        },
        "rebuild_contract": "Delete this release and rerun build_map.py; raw evidence is untouched.",
    }
    write_json(release_root / "manifest.json", manifest)
    derived_root.mkdir(parents=True, exist_ok=True)
    write_json(derived_root / "current_release.json", manifest)
    parquet_glob = str((versions_root / "**" / "*.parquet").resolve())
    create_catalogue(warehouse_path, parquet_glob, release_id, manifest)
    return manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-root", type=Path, default=DEFAULT_INPUT_ROOT)
    parser.add_argument("--derived-root", type=Path, default=DEFAULT_DERIVED_ROOT)
    parser.add_argument("--warehouse", type=Path, default=DEFAULT_WAREHOUSE_PATH)
    parser.add_argument(
        "--release-id",
        default=None,
        help="immutable output release identifier; defaults to a UTC timestamp",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    release_id = args.release_id or utc_stamp()
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", release_id):
        raise SystemExit("--release-id may contain only letters, digits, dot, underscore, and hyphen")
    try:
        manifest = build_release(
            input_root=args.input_root,
            derived_root=args.derived_root,
            warehouse_path=args.warehouse,
            release_id=release_id,
        )
    except RuntimeError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps({"ok": True, **manifest}, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
