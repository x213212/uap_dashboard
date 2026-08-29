#!/usr/bin/env python3
"""Read a local UFOSINT public SQLite export without contacting a provider.

This adapter is deliberately separate from :mod:`collect`.  ``ufo_public.db``
is a large, aggregator-derived artifact, so a future download connector must
be explicitly approved before this module is given a file to read.  Once a
file is present locally, this module:

* opens it with SQLite ``mode=ro`` only;
* uses ``(source_db_id, source_record_id)`` rather than the rebuild-unstable
  local ``sighting.id`` as the source identity;
* streams records in bounded batches instead of loading the database into RAM;
* emits the project canonical event shape, without narratives, raw JSON,
  witness names, or source-location precision finer than a 0.1-degree grid.

It has no URL, HTTP, or downloader dependency by design.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
import math
from pathlib import Path
import re
import sqlite3
import sys
from typing import Any, Iterator


CANONICAL_SCHEMA_VERSION = "uap.global_event.v1"
ADAPTER_SCHEMA_VERSION = "uap.ufosint_adapter.v1"
DEFAULT_SOURCE_ID = "ufosint_public_sqlite"
DEFAULT_SOURCE_ROLE = "global_deduplicated_sightings"
DEFAULT_PORTAL_URL = "https://github.com/UFOSINT/ufo-dedup"
DEFAULT_BATCH_SIZE = 2_000

# These may exist in a public UFOSINT release but are never selected, copied,
# or emitted.  The canonical ``summary`` field is retained with a null value
# solely because it is part of the common project event schema.
SENSITIVE_SOURCE_COLUMNS = frozenset(
    {
        "description",
        "summary",
        "notes",
        "raw_json",
        "witness_names",
        "witness_age",
        "witness_sex",
        "source_ref",
        "page_volume",
        "location_raw_text",
        "raw_text",
    }
)


class UfosintAdapterError(RuntimeError):
    """A local UFOSINT file cannot safely be interpreted by this adapter."""


@dataclass(frozen=True)
class UfosintInspection:
    """Non-sensitive, local-only facts about a candidate SQLite artifact."""

    schema_version: str
    database_path: str
    database_bytes: int
    sighting_rows: int
    tables: tuple[str, ...]
    sighting_columns: tuple[str, ...]
    stable_identity: str
    privacy_filter: str


def _quote_identifier(identifier: str) -> str:
    """Quote a schema identifier from our inspected SQLite metadata."""

    return '"' + identifier.replace('"', '""') + '"'


def _database_path(path: Path) -> Path:
    resolved = path.resolve()
    if not resolved.is_file():
        raise UfosintAdapterError(f"UFOSINT database is not a regular file: {path}")
    return resolved


def _open_read_only(path: Path) -> sqlite3.Connection:
    """Open a local database read-only; never create or alter a SQLite file."""

    resolved = _database_path(path)
    connection = sqlite3.connect(f"{resolved.as_uri()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only = ON")
    return connection


def _table_columns(connection: sqlite3.Connection) -> dict[str, set[str]]:
    rows = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
    ).fetchall()
    tables: dict[str, set[str]] = {}
    for row in rows:
        table = str(row["name"])
        columns = connection.execute(f"PRAGMA table_info({_quote_identifier(table)})").fetchall()
        tables[table] = {str(column["name"]) for column in columns}
    return tables


def _validate_schema(table_columns: dict[str, set[str]]) -> set[str]:
    sighting = table_columns.get("sighting")
    if sighting is None:
        raise UfosintAdapterError("UFOSINT database lacks required sighting table")
    missing = {"source_db_id", "source_record_id"} - sighting
    if missing:
        names = ", ".join(sorted(missing))
        raise UfosintAdapterError(f"UFOSINT sighting table lacks stable identity fields: {names}")
    return sighting


def inspect_database(path: Path) -> UfosintInspection:
    """Inspect a local file without exposing any event rows or text fields."""

    resolved = _database_path(path)
    connection = _open_read_only(resolved)
    try:
        tables = _table_columns(connection)
        sighting_columns = _validate_schema(tables)
        sighting_rows = connection.execute("SELECT count(*) FROM \"sighting\"").fetchone()[0]
    except sqlite3.Error as exc:
        raise UfosintAdapterError(f"cannot inspect local SQLite database: {exc}") from exc
    finally:
        connection.close()
    return UfosintInspection(
        schema_version=ADAPTER_SCHEMA_VERSION,
        database_path=str(resolved),
        database_bytes=resolved.stat().st_size,
        sighting_rows=int(sighting_rows),
        tables=tuple(sorted(tables)),
        sighting_columns=tuple(sorted(sighting_columns)),
        stable_identity="source_db_id:source_record_id",
        privacy_filter=(
            "drops narratives/raw JSON/witness fields and rounds map coordinates to 0.1 degree"
        ),
    )


def _select_or_null(alias: str, columns: set[str], column: str, output: str) -> str:
    if column in columns:
        return f"{alias}.{_quote_identifier(column)} AS {_quote_identifier(output)}"
    return f"NULL AS {_quote_identifier(output)}"


def _query_for_schema(table_columns: dict[str, set[str]]) -> str:
    """Build a read-only query that tolerates additive UFOSINT schema changes."""

    sighting = _validate_schema(table_columns)
    select_parts = [
        _select_or_null("s", sighting, "source_db_id", "source_db_id"),
        _select_or_null("s", sighting, "source_record_id", "source_record_id"),
        _select_or_null("s", sighting, "origin_id", "origin_id"),
        _select_or_null("s", sighting, "origin_record_id", "origin_record_id"),
        _select_or_null("s", sighting, "date_event", "date_event"),
        _select_or_null("s", sighting, "date_end", "date_end"),
        _select_or_null("s", sighting, "sighting_datetime", "sighting_datetime"),
        _select_or_null("s", sighting, "lat", "latitude"),
        _select_or_null("s", sighting, "lng", "longitude"),
        _select_or_null("s", sighting, "shape", "shape"),
        _select_or_null("s", sighting, "standardized_shape", "standardized_shape"),
        _select_or_null("s", sighting, "color", "color"),
        _select_or_null("s", sighting, "primary_color", "primary_color"),
        _select_or_null("s", sighting, "hynek", "hynek"),
        _select_or_null("s", sighting, "vallee", "vallee"),
        _select_or_null("s", sighting, "event_type", "event_type"),
        _select_or_null("s", sighting, "quality_score", "quality_score"),
        _select_or_null("s", sighting, "hoax_likelihood", "hoax_likelihood"),
        _select_or_null("s", sighting, "has_media", "has_media"),
        _select_or_null("s", sighting, "has_description", "has_description"),
        _select_or_null("s", sighting, "movement_type", "movement_type"),
        _select_or_null("s", sighting, "movement_categories", "movement_categories"),
        _select_or_null("s", sighting, "duration", "duration"),
        _select_or_null("s", sighting, "num_objects", "num_objects"),
        _select_or_null("s", sighting, "num_witnesses", "num_witnesses"),
    ]
    joins: list[str] = []

    source_database = table_columns.get("source_database", set())
    if {"id", "name"}.issubset(source_database):
        joins.append(
            "LEFT JOIN \"source_database\" AS sd ON sd.\"id\" = s.\"source_db_id\""
        )
        select_parts.append('sd."name" AS "source_database_name"')
    else:
        select_parts.append('NULL AS "source_database_name"')

    source_origin = table_columns.get("source_origin", set())
    if "origin_id" in sighting and {"id", "name"}.issubset(source_origin):
        joins.append('LEFT JOIN "source_origin" AS so ON so."id" = s."origin_id"')
        select_parts.append('so."name" AS "origin_name"')
    else:
        select_parts.append('NULL AS "origin_name"')

    location = table_columns.get("location", set())
    if "location_id" in sighting and "id" in location:
        joins.append('LEFT JOIN "location" AS l ON l."id" = s."location_id"')
        select_parts.extend(
            [
                _select_or_null("l", location, "city", "location_city"),
                _select_or_null("l", location, "state", "location_state"),
                _select_or_null("l", location, "country", "location_country"),
                _select_or_null("l", location, "geocode_src", "location_geocode_source"),
            ]
        )
    else:
        select_parts.extend(
            [
                'NULL AS "location_city"',
                'NULL AS "location_state"',
                'NULL AS "location_country"',
                'NULL AS "location_geocode_source"',
            ]
        )

    ordering = ['s."source_db_id"', 's."source_record_id"']
    if "id" in sighting:
        ordering.append('s."id"')
    return " ".join(
        [
            "SELECT",
            ", ".join(select_parts),
            'FROM "sighting" AS s',
            *joins,
            "ORDER BY " + ", ".join(ordering),
        ]
    )


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


ISO_FRAGMENT = re.compile(r"^\d{4}(?:-\d{2})?(?:-\d{2})?(?:[T ][0-9:.+-]+Z?)?$")


def _clean_iso_fragment(value: Any) -> str | None:
    text = _clean_text(value)
    if text is None or len(text) > 64 or not ISO_FRAGMENT.fullmatch(text):
        return None
    return text


def _time_precision(value: str | None) -> str | None:
    if value is None:
        return None
    if re.fullmatch(r"\d{4}", value):
        return "year"
    if re.fullmatch(r"\d{4}-\d{2}", value):
        return "month"
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return "day"
    if "T" in value or " " in value:
        return "datetime"
    return "source_unspecified"


def _finite_float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _published_coordinates(latitude: Any, longitude: Any) -> tuple[float | None, float | None]:
    lat = _finite_float(latitude)
    lon = _finite_float(longitude)
    if lat is None or lon is None or not -90 <= lat <= 90 or not -180 <= lon <= 180:
        return None, None
    # The map uses event-density cells, not witness addresses.  Keep an
    # intentionally coarse public derivative while the original local artifact
    # remains immutable and access-controlled.
    return round(lat, 1), round(lon, 1)


def _country_code(value: Any) -> str | None:
    text = _clean_text(value)
    if text is None or not re.fullmatch(r"[A-Za-z]{2}", text):
        return None
    return text.upper()


def _location_name(row: sqlite3.Row) -> str | None:
    # Do not fall back to location.raw_text: free-text source locations can
    # contain more precise information than a public density map needs.
    parts = [
        _clean_text(row["location_city"]),
        _clean_text(row["location_state"]),
        _country_code(row["location_country"]),
    ]
    distinct: list[str] = []
    for part in parts:
        if part and part not in distinct:
            distinct.append(part)
    return ", ".join(distinct) or None


def _bounded_int(value: Any, *, minimum: int, maximum: int) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if minimum <= parsed <= maximum else None


def _bounded_float(value: Any, *, minimum: float, maximum: float) -> float | None:
    parsed = _finite_float(value)
    return parsed if parsed is not None and minimum <= parsed <= maximum else None


def _canonical_record(row: sqlite3.Row, *, source_id: str, source_role: str, portal_url: str) -> dict[str, Any]:
    source_db_id = _bounded_int(row["source_db_id"], minimum=0, maximum=2_147_483_647)
    source_record_id = _clean_text(row["source_record_id"])
    if source_db_id is None or source_record_id is None:
        raise UfosintAdapterError("UFOSINT row has an empty stable source identity")

    observed_at = _clean_iso_fragment(row["sighting_datetime"])
    if observed_at is None:
        observed_at = _clean_iso_fragment(row["date_event"])
    observed_end = _clean_iso_fragment(row["date_end"])
    latitude, longitude = _published_coordinates(row["latitude"], row["longitude"])
    source_database_name = _clean_text(row["source_database_name"])
    origin_name = _clean_text(row["origin_name"])
    title_suffix = source_database_name or f"source {source_db_id}"

    record: dict[str, Any] = {
        "schema_version": CANONICAL_SCHEMA_VERSION,
        "source_id": source_id,
        # UFOSINT documents this pair, rather than sighting.id, as stable
        # across its rebuilds.
        "source_record_id": f"{source_db_id}:{source_record_id}",
        "canonical_event_id": None,
        "record_type": "sighting",
        "observed_at_start": observed_at,
        "observed_at_end": observed_end,
        "time_precision": _time_precision(observed_at),
        "location_name": _location_name(row),
        "country_code": _country_code(row["location_country"]),
        "latitude": latitude,
        "longitude": longitude,
        "coordinate_precision": "0.1_degree_privacy_grid" if latitude is not None else None,
        "venue": None,
        "title": f"UFOSINT sighting ({title_suffix})",
        "summary": None,
        "original_source_url": None,
        "source_portal_url": portal_url,
        "status": None,
        "explanation": None,
        "media_url": None,
        "source_role": source_role,
    }
    extras = {
        "upstream_source_database_id": source_db_id,
        "upstream_source_database": source_database_name,
        "upstream_origin_id": _bounded_int(
            row["origin_id"], minimum=0, maximum=2_147_483_647
        ),
        "upstream_origin": origin_name,
        "upstream_origin_record_id": _clean_text(row["origin_record_id"]),
        "shape_source": _clean_text(row["shape"]),
        "shape_standardized": _clean_text(row["standardized_shape"]),
        "color_source": _clean_text(row["color"]),
        "color_primary": _clean_text(row["primary_color"]),
        "hynek": _clean_text(row["hynek"]),
        "vallee": _clean_text(row["vallee"]),
        "event_type": _clean_text(row["event_type"]),
        "quality_score": _bounded_int(row["quality_score"], minimum=0, maximum=100),
        "hoax_likelihood": _bounded_float(row["hoax_likelihood"], minimum=0.0, maximum=1.0),
        "has_media": _bounded_int(row["has_media"], minimum=0, maximum=1),
        "has_description": _bounded_int(row["has_description"], minimum=0, maximum=1),
        "movement_type": _clean_text(row["movement_type"]),
        "movement_categories": _clean_text(row["movement_categories"]),
        "duration_source": _clean_text(row["duration"]),
        "number_objects": _bounded_int(row["num_objects"], minimum=0, maximum=1_000_000),
        "number_witnesses": _bounded_int(row["num_witnesses"], minimum=0, maximum=1_000_000),
        "location_geocode_source": _clean_text(row["location_geocode_source"]),
        "coordinate_treatment": "rounded_to_0.1_degree_for_public_density_map",
    }
    record.update({key: value for key, value in extras.items() if value is not None})
    return record


def iter_canonical_records(
    path: Path,
    *,
    source_id: str = DEFAULT_SOURCE_ID,
    source_role: str = DEFAULT_SOURCE_ROLE,
    portal_url: str = DEFAULT_PORTAL_URL,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> Iterator[dict[str, Any]]:
    """Yield privacy-filtered canonical records from an already-local database.

    This makes no network requests and retains only one SQLite fetch batch in
    memory.  It intentionally does not write a receipt: that must be done by
    the future, explicitly approved streaming connector that owns the raw
    artifact's hash and acquisition provenance.
    """

    if batch_size <= 0:
        raise UfosintAdapterError("batch_size must be positive")
    if not source_id or not source_role or not portal_url.startswith("https://"):
        raise UfosintAdapterError("source context must contain non-empty ID/role and HTTPS portal")
    connection = _open_read_only(path)
    try:
        table_columns = _table_columns(connection)
        query = _query_for_schema(table_columns)
        cursor = connection.execute(query)
        while rows := cursor.fetchmany(batch_size):
            for row in rows:
                yield _canonical_record(
                    row,
                    source_id=source_id,
                    source_role=source_role,
                    portal_url=portal_url,
                )
    except sqlite3.Error as exc:
        raise UfosintAdapterError(f"cannot read local SQLite database: {exc}") from exc
    finally:
        connection.close()


def command_inspect(args: argparse.Namespace) -> int:
    inspection = inspect_database(args.database)
    print(json.dumps(asdict(inspection), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Inspect a local UFOSINT SQLite file without network access or event export."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    inspect_parser = subparsers.add_parser("inspect", help="read schema/counts only")
    inspect_parser.add_argument("--database", type=Path, required=True)
    inspect_parser.set_defaults(handler=command_inspect)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.handler(args))
    except UfosintAdapterError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
