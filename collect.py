#!/usr/bin/env python3
"""Immutable, rights-aware collection of globally published UAP data.

Only registry entries explicitly tagged OPEN_BATCH may be contacted by the
``collect`` command.  The larger source atlas remains discoverable through the
``sources --urls`` command without turning every public web page into a scrape
target.
"""

from __future__ import annotations

import argparse
from collections import Counter
import csv
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
import gzip
import hashlib
import io
import json
import math
from pathlib import Path
import re
import sys
import tempfile
from typing import Any, Callable, Iterable
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parent
DEFAULT_REGISTRY = ROOT / "sources.json"
DEFAULT_DATA_ROOT = ROOT / "data"
SCHEMA_VERSION = "uap.global_event.v1"
USER_AGENT = "uap-source-atlas/0.1 (research; contact via source-atlas)"
URL_PATTERN = re.compile(r"https?://[^\s)<>\]]+")
DEFAULT_PER_RESPONSE_LIMIT_BYTES = 512 * 1024 * 1024
DEFAULT_TOTAL_DOWNLOAD_BUDGET_BYTES = 64 * 1024 * 1024
READ_CHUNK_BYTES = 1024 * 1024

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

# The collector deliberately uses a Sun-centred, bodycentric observer table.
# This keeps Earth in the historical nine-body set, but it is a heliocentric
# reference product -- never a topocentric explanation for a sighting.
HORIZONS_SIGNATURE_SOURCE = "NASA/JPL Horizons API"
HORIZONS_OBSERVER_CENTER = "500@10"
HORIZONS_OBSERVER_MODE = "heliocentric_bodycentric_reference"
HORIZONS_TIME_SCALE = "UTC"
HORIZONS_MONTHS = {
    "Jan": 1,
    "Feb": 2,
    "Mar": 3,
    "Apr": 4,
    "May": 5,
    "Jun": 6,
    "Jul": 7,
    "Aug": 8,
    "Sep": 9,
    "Oct": 10,
    "Nov": 11,
    "Dec": 12,
}
HORIZONS_OBSERVER_ROW = re.compile(
    r"^\s*"
    r"(?P<date>\d{4}-[A-Za-z]{3}-\d{2})\s+"
    r"(?P<time>\d{2}:\d{2})\s+"
    r"(?P<icrf_ra_hour>\d{1,2})\s+(?P<icrf_ra_minute>\d{1,2})\s+"
    r"(?P<icrf_ra_second>\d+(?:\.\d+)?)\s+"
    r"(?P<icrf_dec_sign>[+-])(?P<icrf_dec_degree>\d{1,2})\s+"
    r"(?P<icrf_dec_minute>\d{1,2})\s+(?P<icrf_dec_second>\d+(?:\.\d+)?)\s+"
    r"(?P<apparent_ra_hour>\d{1,2})\s+(?P<apparent_ra_minute>\d{1,2})\s+"
    r"(?P<apparent_ra_second>\d+(?:\.\d+)?)\s+"
    r"(?P<apparent_dec_sign>[+-])(?P<apparent_dec_degree>\d{1,2})\s+"
    r"(?P<apparent_dec_minute>\d{1,2})\s+(?P<apparent_dec_second>\d+(?:\.\d+)?)\s+"
    r"(?P<azimuth>\S+)\s+(?P<altitude>\S+)\s+"
    r"(?P<apparent_magnitude>\S+)\s+(?P<surface_brightness>\S+)\s+"
    r"(?P<range_au>\S+)\s+(?P<range_rate_km_s>\S+)\s*$"
)


@dataclass(frozen=True)
class Source:
    source_id: str
    name: str
    access: str
    kind: str | None
    url: str
    portal_url: str | None
    role: str
    expected_bytes_per_run: int | None = None
    max_response_bytes: int | None = None
    requests_per_run: int = 1
    refresh_hint: str | None = None
    source_metadata: dict[str, Any] | None = None


class CollectionError(RuntimeError):
    pass


@dataclass
class DownloadBudget:
    """A run-wide byte budget, separate from the limit for one response."""

    max_bytes: int
    used_bytes: int = 0

    @property
    def remaining_bytes(self) -> int:
        return self.max_bytes - self.used_bytes

    def consume(self, byte_count: int) -> None:
        if byte_count < 0:
            raise CollectionError("download byte count cannot be negative")
        if byte_count > self.remaining_bytes:
            raise CollectionError("refusing response: run-wide download budget exhausted")
        self.used_bytes += byte_count


@dataclass(frozen=True)
class StreamedArtifact:
    """An immutable byte-for-byte provider artifact stored without RAM buffering."""

    path: Path
    byte_count: int
    sha256: str
    headers: dict[str, str]
    final_url: str


def positive_int(value: Any, *, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise CollectionError(f"{field_name} must be a positive integer")
    return value


def utc_now() -> datetime:
    return datetime.now(UTC)


def utc_stamp(value: datetime | None = None) -> str:
    return (value or utc_now()).strftime("%Y%m%dT%H%M%S%fZ")


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def safe_float(value: str | None) -> float | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        return float(str(value))
    except ValueError:
        return None


def signed_coordinate(value: str | None, direction: str | None) -> float | None:
    numeric = safe_float(value)
    if numeric is None:
        return None
    return -abs(numeric) if direction in {"S", "W"} else abs(numeric)


def atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        handle.write(payload)
        temp_path = Path(handle.name)
    temp_path.replace(path)


def write_json(path: Path, payload: Any) -> None:
    atomic_write(
        path,
        (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
            "utf-8"
        ),
    )


def gzip_payload(payload: bytes) -> bytes:
    return gzip.compress(payload, compresslevel=9, mtime=0)


def load_registry(path: Path) -> tuple[dict[str, Any], dict[str, Source]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if raw.get("schema_version") != "uap.source_registry.v1":
        raise CollectionError("unsupported source registry schema")
    entries = raw.get("sources")
    if not isinstance(entries, list):
        raise CollectionError("source registry has no source list")
    sources: dict[str, Source] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise CollectionError("source registry contains a non-object entry")
        source_id = str(entry.get("id", ""))
        if not re.fullmatch(r"[a-z0-9_]+", source_id):
            raise CollectionError(f"invalid source id: {source_id!r}")
        if source_id in sources:
            raise CollectionError(f"duplicate source id: {source_id}")
        url = str(entry.get("url", ""))
        if not url.startswith("https://"):
            raise CollectionError(f"source {source_id} does not use https")
        access = str(entry.get("access", ""))
        expected_bytes = entry.get("expected_bytes_per_run")
        max_response_bytes = entry.get("max_response_bytes")
        requests_per_run = entry.get("requests_per_run", 1)
        if access == "OPEN_BATCH":
            if expected_bytes is None or max_response_bytes is None:
                raise CollectionError(
                    f"OPEN_BATCH source {source_id} needs expected_bytes_per_run and max_response_bytes"
                )
            expected_bytes = positive_int(
                expected_bytes, field_name=f"{source_id}.expected_bytes_per_run"
            )
            max_response_bytes = positive_int(
                max_response_bytes, field_name=f"{source_id}.max_response_bytes"
            )
            requests_per_run = positive_int(
                requests_per_run, field_name=f"{source_id}.requests_per_run"
            )
        else:
            if expected_bytes is not None:
                expected_bytes = positive_int(
                    expected_bytes, field_name=f"{source_id}.expected_bytes_per_run"
                )
            if max_response_bytes is not None:
                max_response_bytes = positive_int(
                    max_response_bytes, field_name=f"{source_id}.max_response_bytes"
                )
            requests_per_run = positive_int(
                requests_per_run, field_name=f"{source_id}.requests_per_run"
            )
        sources[source_id] = Source(
            source_id=source_id,
            name=str(entry.get("name", source_id)),
            access=access,
            kind=str(entry["kind"]) if entry.get("kind") else None,
            url=url,
            portal_url=(str(entry["portal_url"]) if entry.get("portal_url") else None),
            role=str(entry.get("role", "")),
            expected_bytes_per_run=expected_bytes,
            max_response_bytes=max_response_bytes,
            requests_per_run=requests_per_run,
            refresh_hint=(str(entry["refresh_hint"]) if entry.get("refresh_hint") else None),
            source_metadata={
                key: value
                for key, value in entry.items()
                if key
                not in {
                    "id",
                    "name",
                    "access",
                    "kind",
                    "url",
                    "portal_url",
                    "role",
                    "expected_bytes_per_run",
                    "max_response_bytes",
                    "requests_per_run",
                    "refresh_hint",
                }
            },
        )
    return raw, sources


def atlas_urls(registry: dict[str, Any], registry_path: Path) -> list[str]:
    urls: set[str] = set()
    for entry in registry.get("sources", []):
        if isinstance(entry, dict):
            for key in ("url", "portal_url"):
                value = entry.get(key)
                if isinstance(value, str) and value.startswith(("https://", "http://")):
                    urls.add(value.rstrip(".,"))
    relative = registry.get("atlas_path")
    if isinstance(relative, str):
        atlas = (registry_path.parent / relative).resolve()
        if atlas.is_file():
            for url in URL_PATTERN.findall(atlas.read_text(encoding="utf-8")):
                urls.add(url.rstrip(".,"))
    return sorted(urls)


def request_bytes(
    url: str,
    *,
    max_bytes: int,
    timeout_seconds: float,
    budget: DownloadBudget,
) -> tuple[bytes, dict[str, str]]:
    if max_bytes <= 0:
        raise CollectionError("response byte limit must be positive")
    if budget.remaining_bytes <= 0:
        raise CollectionError("refusing request: run-wide download budget exhausted")
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
    try:
        with urlopen(request, timeout=timeout_seconds) as response:  # nosec B310: HTTPS registry only
            final_url = response.geturl() if hasattr(response, "geturl") else url
            if not str(final_url).startswith("https://"):
                raise CollectionError(f"refusing redirect to non-HTTPS URL: {final_url}")
            headers = {key.lower(): value for key, value in response.headers.items()}
            advertised = headers.get("content-length")
            allowed = min(max_bytes, budget.remaining_bytes)
            try:
                advertised_size = int(advertised) if advertised else None
            except ValueError as exc:
                raise CollectionError(f"refusing {url}: invalid Content-Length") from exc
            if advertised_size is not None and advertised_size < 0:
                raise CollectionError(f"refusing {url}: invalid negative Content-Length")
            if advertised_size is not None and advertised_size > allowed:
                raise CollectionError(
                    f"refusing {url}: declared {advertised_size} bytes exceeds the current budget"
                )
            chunks: list[bytes] = []
            total = 0
            while True:
                remaining_response = max_bytes - total
                remaining_run = budget.remaining_bytes
                read_size = min(READ_CHUNK_BYTES, remaining_response, remaining_run)
                if read_size <= 0:
                    raise CollectionError(f"refusing {url}: response exceeds the current budget")
                chunk = response.read(read_size)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise CollectionError(f"refusing {url}: response exceeds --max-bytes")
                if advertised_size is not None and total > advertised_size:
                    raise CollectionError(f"refusing {url}: response exceeds Content-Length")
                budget.consume(len(chunk))
                chunks.append(chunk)
                if advertised_size is not None and total == advertised_size:
                    break
            if advertised_size is not None and total != advertised_size:
                raise CollectionError(f"refusing {url}: response ended before Content-Length")
            return b"".join(chunks), headers
    except CollectionError:
        raise
    except Exception as exc:  # urllib exposes several implementation-specific errors
        raise CollectionError(f"request failed for {url}: {type(exc).__name__}: {exc}") from exc


def stream_response_to_path(
    url: str,
    *,
    target_path: Path,
    max_bytes: int,
    timeout_seconds: float,
    budget: DownloadBudget,
) -> StreamedArtifact:
    """Download one bounded artifact to disk without accumulating it in memory.

    The output does not appear at ``target_path`` until the response has been
    completely read, hashed, and checked against both byte budgets.  It is the
    primitive intended for future large SQLite/PDF/media *approved* sources;
    callers still decide whether a source is authorised to reach this function.
    """

    if max_bytes <= 0:
        raise CollectionError("response byte limit must be positive")
    if budget.remaining_bytes <= 0:
        raise CollectionError("refusing request: run-wide download budget exhausted")
    if target_path.exists() or target_path.is_symlink():
        raise CollectionError(f"refusing to overwrite existing artifact: {target_path}")
    target_path.parent.mkdir(parents=True, exist_ok=True)
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
    temporary_path: Path | None = None
    try:
        with urlopen(request, timeout=timeout_seconds) as response:  # nosec B310: HTTPS registry only
            final_url = response.geturl() if hasattr(response, "geturl") else url
            if not str(final_url).startswith("https://"):
                raise CollectionError(f"refusing redirect to non-HTTPS URL: {final_url}")
            headers = {key.lower(): value for key, value in response.headers.items()}
            advertised = headers.get("content-length")
            try:
                advertised_size = int(advertised) if advertised else None
            except ValueError as exc:
                raise CollectionError(f"refusing {url}: invalid Content-Length") from exc
            allowed = min(max_bytes, budget.remaining_bytes)
            if advertised_size is not None and (advertised_size < 0 or advertised_size > allowed):
                raise CollectionError(f"refusing {url}: declared size exceeds the current budget")
            hasher = hashlib.sha256()
            total = 0
            with tempfile.NamedTemporaryFile(dir=target_path.parent, delete=False) as handle:
                temporary_path = Path(handle.name)
                while True:
                    remaining_response = max_bytes - total
                    remaining_run = budget.remaining_bytes
                    read_size = min(READ_CHUNK_BYTES, remaining_response, remaining_run)
                    if read_size <= 0:
                        raise CollectionError(f"refusing {url}: response exceeds the current budget")
                    chunk = response.read(read_size)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > max_bytes:
                        raise CollectionError(f"refusing {url}: response exceeds --max-bytes")
                    if advertised_size is not None and total > advertised_size:
                        raise CollectionError(f"refusing {url}: response exceeds Content-Length")
                    budget.consume(len(chunk))
                    hasher.update(chunk)
                    handle.write(chunk)
                    if advertised_size is not None and total == advertised_size:
                        break
            if advertised_size is not None and total != advertised_size:
                raise CollectionError(f"refusing {url}: response ended before Content-Length")
            temporary_path.replace(target_path)
            return StreamedArtifact(
                path=target_path,
                byte_count=total,
                sha256=hasher.hexdigest(),
                headers=headers,
                final_url=str(final_url),
            )
    except CollectionError:
        raise
    except Exception as exc:  # urllib exposes several implementation-specific errors
        raise CollectionError(f"request failed for {url}: {type(exc).__name__}: {exc}") from exc
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def blank_record(*, source: Source, source_record_id: str, record_type: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "source_id": source.source_id,
        "source_record_id": source_record_id,
        "canonical_event_id": None,
        "record_type": record_type,
        "observed_at_start": None,
        "observed_at_end": None,
        "time_precision": None,
        "location_name": None,
        "country_code": None,
        "latitude": None,
        "longitude": None,
        "coordinate_precision": None,
        "venue": None,
        "title": None,
        "summary": None,
        "original_source_url": None,
        "source_portal_url": source.portal_url or source.url,
        "status": None,
        "explanation": None,
        "media_url": None,
        "source_role": source.role,
    }


def normalize_uapdrop(source: Source, payload: bytes) -> list[dict[str, Any]]:
    text = payload.decode("utf-8-sig")
    records: list[dict[str, Any]] = []
    for index, row in enumerate(csv.DictReader(io.StringIO(text)), start=1):
        source_record_id = row.get("external_id") or f"row-{index}"
        record = blank_record(
            source=source, source_record_id=source_record_id, record_type="sighting"
        )
        record.update(
            {
                "observed_at_start": row.get("observed_at") or None,
                "time_precision": "source_unspecified" if row.get("observed_at") else None,
                "location_name": row.get("location_name") or None,
                "country_code": row.get("country_code") or None,
                "latitude": safe_float(row.get("latitude")),
                "longitude": safe_float(row.get("longitude")),
                "coordinate_precision": row.get("coordinate_precision") or None,
                "title": row.get("title") or None,
                "summary": row.get("summary") or None,
                "original_source_url": row.get("source_url") or None,
                "upstream_source_key": row.get("source_key") or None,
            }
        )
        records.append(record)
    return records


def normalize_uap_observatory(source: Source, payload: bytes) -> list[dict[str, Any]]:
    text = payload.decode("utf-8-sig")
    records: list[dict[str, Any]] = []
    for index, row in enumerate(csv.DictReader(io.StringIO(text)), start=1):
        source_record_id = row.get("id") or f"row-{index}"
        record = blank_record(
            source=source, source_record_id=source_record_id, record_type="curated_incident"
        )
        record.update(
            {
                "observed_at_start": row.get("date_start") or None,
                "observed_at_end": row.get("date_end") or None,
                "time_precision": "date" if row.get("date_start") else None,
                "location_name": row.get("location") or None,
                "title": row.get("title") or None,
                "summary": row.get("notes") or None,
                "status": row.get("status") or None,
                "credibility_tier": row.get("credibility_tier") or None,
                "related_entity_ids": row.get("related_entity_ids") or None,
                "upstream_source_ids": row.get("source_ids") or None,
            }
        )
        records.append(record)
    return records


def normalize_nasa_fireball(source: Source, payload: bytes) -> list[dict[str, Any]]:
    response = json.loads(payload.decode("utf-8"))
    fields = response.get("fields")
    data = response.get("data")
    if not isinstance(fields, list) or not isinstance(data, list):
        raise CollectionError("NASA fireball payload does not contain fields and data")
    records: list[dict[str, Any]] = []
    for index, values in enumerate(data, start=1):
        if not isinstance(values, list):
            raise CollectionError("NASA fireball payload contains a non-list row")
        row = {str(key): value for key, value in zip(fields, values, strict=False)}
        observed_at = str(row.get("date", "")) or None
        source_record_id = observed_at or f"row-{index}"
        record = blank_record(
            source=source, source_record_id=source_record_id, record_type="astronomy_control_fireball"
        )
        record.update(
            {
                "observed_at_start": observed_at,
                "time_precision": "second" if observed_at else None,
                "latitude": signed_coordinate(row.get("lat"), row.get("lat-dir")),
                "longitude": signed_coordinate(row.get("lon"), row.get("lon-dir")),
                "coordinate_precision": "source_unspecified" if row.get("lat") else None,
                "title": "NASA/JPL fireball",
                "summary": json.dumps(row, ensure_ascii=False, sort_keys=True),
                "original_source_url": source.url,
            }
        )
        records.append(record)
    return records


def horizons_url(body_id: str, start: date) -> str:
    params = {
        "format": "json",
        # Horizons treats a comma-separated value as multiple command tokens
        # unless these API values retain the single quotes used in its examples.
        "COMMAND": f"'{body_id}'",
        "OBJ_DATA": "'YES'",
        "MAKE_EPHEM": "'YES'",
        "EPHEM_TYPE": "'OBSERVER'",
        # Sun-centred output keeps the Earth row valid too.  A geocentric
        # observer table is disallowed when Earth itself is the target.
        "CENTER": f"'{HORIZONS_OBSERVER_CENTER}'",
        "START_TIME": f"'{start.isoformat()}'",
        "STOP_TIME": f"'{(start + timedelta(days=1)).isoformat()}'",
        "STEP_SIZE": "'1 d'",
        "QUANTITIES": "'1,2,4,9,20'",
    }
    return "https://ssd.jpl.nasa.gov/api/horizons.api?" + urlencode(params)


def horizons_query_value(query_url: str, name: str) -> str:
    """Return one quoted Horizons query value, or fail closed on ambiguity."""

    values = parse_qs(urlparse(query_url).query).get(name, [])
    if len(values) != 1:
        raise CollectionError(f"Horizons query lacks one {name} value")
    value = values[0].strip("'")
    if not value:
        raise CollectionError(f"Horizons query has an empty {name} value")
    return value


def horizons_hms_to_degrees(hour: str, minute: str, second: str) -> float:
    """Convert a Horizons RA `HH MM SS.s` value to degrees with range checks."""

    try:
        parsed_hour = int(hour)
        parsed_minute = int(minute)
        parsed_second = float(second)
    except ValueError as exc:
        raise CollectionError("Horizons RA is not numeric") from exc
    if not (0 <= parsed_hour <= 23 and 0 <= parsed_minute <= 59 and 0 <= parsed_second < 60):
        raise CollectionError("Horizons RA is outside its HMS range")
    return 15.0 * (parsed_hour + parsed_minute / 60.0 + parsed_second / 3600.0)


def horizons_dms_to_degrees(sign: str, degree: str, minute: str, second: str) -> float:
    """Convert a Horizons DEC `+DD MM SS.s` value to signed degrees."""

    try:
        parsed_degree = int(degree)
        parsed_minute = int(minute)
        parsed_second = float(second)
    except ValueError as exc:
        raise CollectionError("Horizons DEC is not numeric") from exc
    if sign not in {"+", "-"}:
        raise CollectionError("Horizons DEC lacks a sign")
    if not (0 <= parsed_degree <= 90 and 0 <= parsed_minute <= 59 and 0 <= parsed_second < 60):
        raise CollectionError("Horizons DEC is outside its DMS range")
    if parsed_degree == 90 and (parsed_minute != 0 or parsed_second != 0):
        raise CollectionError("Horizons DEC exceeds a pole")
    value = parsed_degree + parsed_minute / 60.0 + parsed_second / 3600.0
    return -value if sign == "-" else value


def horizons_epoch_utc(value_date: str, value_time: str) -> str:
    """Parse the fixed English date token emitted by the requested Horizons table."""

    match = re.fullmatch(r"(?P<year>\d{4})-(?P<month>[A-Za-z]{3})-(?P<day>\d{2})", value_date)
    time_match = re.fullmatch(r"(?P<hour>\d{2}):(?P<minute>\d{2})", value_time)
    if match is None or time_match is None:
        raise CollectionError("Horizons observer-table epoch has an unknown format")
    month = HORIZONS_MONTHS.get(match.group("month").title())
    if month is None:
        raise CollectionError("Horizons observer-table epoch has an unknown month")
    try:
        parsed = datetime(
            int(match.group("year")),
            month,
            int(match.group("day")),
            int(time_match.group("hour")),
            int(time_match.group("minute")),
            tzinfo=UTC,
        )
    except ValueError as exc:
        raise CollectionError("Horizons observer-table epoch is invalid") from exc
    return parsed.isoformat().replace("+00:00", "Z")


def horizons_optional_number(value: str) -> float | None:
    """Parse a Horizons numeric cell without treating `n.a.` as zero."""

    if value.strip().lower() in {"n.a.", "n.a", "na", "n/a"}:
        return None
    try:
        parsed = float(value)
    except ValueError as exc:
        raise CollectionError(f"Horizons table value is not numeric: {value!r}") from exc
    if not math.isfinite(parsed):
        raise CollectionError(f"Horizons table value is not finite: {value!r}")
    return parsed


def horizons_table_lines(result: str) -> list[str]:
    """Extract only the data rows between Horizons' explicit table sentinels."""

    lines = result.splitlines()
    try:
        start_index = next(index for index, line in enumerate(lines) if line.strip() == "$$SOE")
        end_index = next(
            index
            for index, line in enumerate(lines[start_index + 1 :], start=start_index + 1)
            if line.strip() == "$$EOE"
        )
    except StopIteration as exc:
        raise CollectionError("Horizons response lacks complete $$SOE/$$EOE sentinels") from exc
    rows = [line for line in lines[start_index + 1 : end_index] if line.strip()]
    if not rows:
        raise CollectionError("Horizons observer table has no rows")
    return rows


def parse_horizons_ephemeris(
    *, body_id: str, body_name: str, query_url: str, payload: bytes, start: date
) -> dict[str, Any]:
    """Return a compact, map-safe heliocentric reference record from raw JSON.

    The collector intentionally accepts only the declared Sun-centred,
    bodycentric request. A topocentric matching product needs a separate
    privacy-aware query contract and must not silently inherit these values.
    """

    try:
        response = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CollectionError(f"Horizons response for {body_name} is not valid JSON") from exc
    if not isinstance(response, dict):
        raise CollectionError(f"Horizons response for {body_name} is not an object")
    if response.get("error"):
        raise CollectionError(f"Horizons returned an API error for {body_name}: {response['error']}")
    signature = response.get("signature")
    if not isinstance(signature, dict):
        raise CollectionError(f"Horizons response for {body_name} lacks an API signature")
    signature_source = signature.get("source")
    signature_version = signature.get("version")
    if signature_source != HORIZONS_SIGNATURE_SOURCE or not isinstance(signature_version, str):
        raise CollectionError(f"Horizons response for {body_name} has an unexpected API signature")
    result = response.get("result")
    if not isinstance(result, str):
        raise CollectionError(f"Horizons response for {body_name} lacks result text")

    if horizons_query_value(query_url, "COMMAND") != body_id:
        raise CollectionError(f"Horizons query/body mismatch for {body_name}")
    if horizons_query_value(query_url, "CENTER") != HORIZONS_OBSERVER_CENTER:
        raise CollectionError("Horizons query uses an unsupported observer center")
    if horizons_query_value(query_url, "START_TIME") != start.isoformat():
        raise CollectionError(f"Horizons query/date mismatch for {body_name}")
    if not re.search(rf"Target body name:.*\({re.escape(body_id)}(?:\s|\))", result):
        raise CollectionError(f"Horizons target header does not match {body_name}")
    if "Center body name: Sun (10)" not in result or "Center-site name: BODYCENTRIC" not in result:
        raise CollectionError("Horizons response is not the declared heliocentric/bodycentric table")

    selected: re.Match[str] | None = None
    selected_epoch: str | None = None
    for line in horizons_table_lines(result):
        match = HORIZONS_OBSERVER_ROW.fullmatch(line)
        if match is None:
            raise CollectionError("Horizons observer-table row has an unsupported schema")
        epoch_utc = horizons_epoch_utc(match.group("date"), match.group("time"))
        if epoch_utc[:10] == start.isoformat():
            selected = match
            selected_epoch = epoch_utc
            break
    if selected is None or selected_epoch is None:
        raise CollectionError(f"Horizons observer table lacks the requested UTC date for {body_name}")

    range_au = horizons_optional_number(selected.group("range_au"))
    range_rate_km_s = horizons_optional_number(selected.group("range_rate_km_s"))
    if range_au is None or range_rate_km_s is None:
        raise CollectionError(f"Horizons observer table lacks range data for {body_name}")
    azimuth = horizons_optional_number(selected.group("azimuth"))
    altitude = horizons_optional_number(selected.group("altitude"))
    # A BODYCENTRIC Sun observer has no terrestrial horizon. Never turn the
    # provider's `n.a.` into a zero-degree false-positive control.
    if azimuth is not None or altitude is not None:
        raise CollectionError("heliocentric Horizons response unexpectedly contains horizontal coordinates")

    return {
        "schema_version": "uap.ephemeris.v1",
        "body_id": body_id,
        "body_name": body_name,
        "epoch_utc": selected_epoch,
        "epoch_time_scale": HORIZONS_TIME_SCALE,
        "observer_center": HORIZONS_OBSERVER_CENTER,
        "observer_mode": HORIZONS_OBSERVER_MODE,
        "coordinate_frame": "ICRF",
        "ra_icrf_deg": horizons_hms_to_degrees(
            selected.group("icrf_ra_hour"),
            selected.group("icrf_ra_minute"),
            selected.group("icrf_ra_second"),
        ),
        "dec_icrf_deg": horizons_dms_to_degrees(
            selected.group("icrf_dec_sign"),
            selected.group("icrf_dec_degree"),
            selected.group("icrf_dec_minute"),
            selected.group("icrf_dec_second"),
        ),
        "apparent_coordinate_frame": "body_equator_apparent",
        "apparent_ra_deg": horizons_hms_to_degrees(
            selected.group("apparent_ra_hour"),
            selected.group("apparent_ra_minute"),
            selected.group("apparent_ra_second"),
        ),
        "apparent_dec_deg": horizons_dms_to_degrees(
            selected.group("apparent_dec_sign"),
            selected.group("apparent_dec_degree"),
            selected.group("apparent_dec_minute"),
            selected.group("apparent_dec_second"),
        ),
        "range_au": range_au,
        "range_rate_km_s": range_rate_km_s,
        "azimuth_deg": None,
        "altitude_deg": None,
        "azimuth_altitude_status": "not_applicable_non_topocentric",
        "api_signature_source": signature_source,
        "api_signature_version": signature_version,
        "raw_sha256": sha256_bytes(payload),
    }


def normalize_horizons_body(
    source: Source, body_id: str, body_name: str, query_url: str, payload: bytes, start: date
) -> list[dict[str, Any]]:
    ephemeris = parse_horizons_ephemeris(
        body_id=body_id,
        body_name=body_name,
        query_url=query_url,
        payload=payload,
        start=start,
    )
    record = blank_record(
        source=source,
        source_record_id=f"{body_id}-{start.isoformat()}",
        record_type="astronomy_control_ephemeris",
    )
    record.update(
        {
            "observed_at_start": ephemeris["epoch_utc"],
            "time_precision": "minute",
            "title": f"{body_name} heliocentric reference ephemeris",
            "summary": (
                "NASA/JPL Horizons Sun-centred bodycentric reference; "
                "not a topocentric sighting match."
            ),
            "original_source_url": query_url,
            "body_id": body_id,
            "observer_center": HORIZONS_OBSERVER_CENTER,
            "raw_sha256": ephemeris["raw_sha256"],
            "normalizer_version": "horizons_observer_text_v1",
            "ephemeris": ephemeris,
        }
    )
    return [record]


NORMALIZERS: dict[str, Callable[[Source, bytes], list[dict[str, Any]]]] = {
    "uapdrop_csv": normalize_uapdrop,
    "uap_observatory_csv": normalize_uap_observatory,
    "nasa_fireball_json": normalize_nasa_fireball,
}


def known_raw_hashes(output_root: Path, source_id: str) -> set[str]:
    hashes: set[str] = set()
    receipts = output_root / "receipts" / source_id
    if not receipts.is_dir():
        return hashes
    for receipt_path in receipts.glob("*.json"):
        try:
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for item in receipt.get("raw_files", []):
            if isinstance(item, dict) and isinstance(item.get("raw_sha256"), str):
                hashes.add(item["raw_sha256"])
    return hashes


def horizons_date_already_archived(output_root: Path, start: date) -> bool:
    """Avoid re-saving a new Horizons banner for an already sealed UTC day."""

    receipts = output_root / "receipts" / "nasa_horizons_9_bodies"
    if not receipts.is_dir():
        return False
    target = start.isoformat()
    for receipt_path in receipts.glob("*.json"):
        try:
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        request_urls = receipt.get("request_urls")
        if not isinstance(request_urls, list):
            continue
        matching = 0
        for request_url in request_urls:
            if not isinstance(request_url, str):
                continue
            values = parse_qs(urlparse(request_url).query).get("START_TIME", [])
            if values and values[0].strip("'") == target:
                matching += 1
        if matching == len(PLANETS):
            return True
    return False


def write_snapshot(
    *,
    output_root: Path,
    source: Source,
    snapshot_id: str,
    raw_files: list[tuple[str, bytes, str]],
    records: Iterable[dict[str, Any]],
    collected_at: str,
    request_urls: list[str],
) -> dict[str, Any]:
    raw_dir = output_root / "raw" / source.source_id / snapshot_id
    canonical_dir = output_root / "canonical" / source.source_id / snapshot_id
    receipt_path = output_root / "receipts" / source.source_id / f"{snapshot_id}.json"
    raw_receipts: list[dict[str, Any]] = []
    for filename, payload, url in raw_files:
        compressed = gzip_payload(payload)
        target = raw_dir / f"{filename}.gz"
        atomic_write(target, compressed)
        raw_receipts.append(
            {
                "path": target.relative_to(output_root).as_posix(),
                "request_url": url,
                "raw_bytes": len(payload),
                "raw_sha256": sha256_bytes(payload),
                "gzip_bytes": len(compressed),
                "gzip_sha256": sha256_bytes(compressed),
            }
        )
    rows = list(records)
    canonical_bytes = (
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows)
    ).encode("utf-8")
    canonical_target = canonical_dir / "events.jsonl.gz"
    canonical_compressed = gzip_payload(canonical_bytes)
    atomic_write(canonical_target, canonical_compressed)
    receipt = {
        "schema_version": "uap.collection_receipt.v1",
        "source_id": source.source_id,
        "source_name": source.name,
        "source_role": source.role,
        "snapshot_id": snapshot_id,
        "collected_at": collected_at,
        "request_urls": request_urls,
        "raw_files": raw_receipts,
        "canonical": {
            "path": canonical_target.relative_to(output_root).as_posix(),
            "records": len(rows),
            "uncompressed_bytes": len(canonical_bytes),
            "uncompressed_sha256": sha256_bytes(canonical_bytes),
            "gzip_bytes": len(canonical_compressed),
            "gzip_sha256": sha256_bytes(canonical_compressed),
        },
    }
    write_json(receipt_path, receipt)
    return receipt


def collect_standard_source(
    *,
    source: Source,
    output_root: Path,
    max_bytes: int,
    timeout_seconds: float,
    budget: DownloadBudget,
) -> dict[str, Any]:
    if source.kind not in NORMALIZERS:
        raise CollectionError(f"no normalizer for {source.source_id}")
    payload, _headers = request_bytes(
        source.url,
        max_bytes=max_bytes,
        timeout_seconds=timeout_seconds,
        budget=budget,
    )
    raw_hash = sha256_bytes(payload)
    if raw_hash in known_raw_hashes(output_root, source.source_id):
        return {"source_id": source.source_id, "decision": "UNCHANGED", "raw_sha256": raw_hash}
    records = NORMALIZERS[source.kind](source, payload)
    now = utc_now()
    return write_snapshot(
        output_root=output_root,
        source=source,
        snapshot_id=utc_stamp(now),
        raw_files=[("source.raw", payload, source.url)],
        records=records,
        collected_at=now.isoformat(),
        request_urls=[source.url],
    )


def collect_horizons(
    *,
    source: Source,
    output_root: Path,
    max_bytes: int,
    timeout_seconds: float,
    start: date,
    budget: DownloadBudget,
) -> dict[str, Any]:
    if horizons_date_already_archived(output_root, start):
        return {
            "source_id": source.source_id,
            "decision": "UNCHANGED",
            "reason": "utc_date_already_archived",
            "date": start.isoformat(),
        }
    raw_files: list[tuple[str, bytes, str]] = []
    records: list[dict[str, Any]] = []
    for body_id, body_name in PLANETS:
        query_url = horizons_url(body_id, start)
        payload, _headers = request_bytes(
            query_url,
            max_bytes=max_bytes,
            timeout_seconds=timeout_seconds,
            budget=budget,
        )
        raw_files.append((f"{body_id}_{body_name.lower()}.raw.json", payload, query_url))
        records.extend(normalize_horizons_body(source, body_id, body_name, query_url, payload, start))
    hashes = known_raw_hashes(output_root, source.source_id)
    if raw_files and all(sha256_bytes(payload) in hashes for _name, payload, _url in raw_files):
        return {
            "source_id": source.source_id,
            "decision": "UNCHANGED",
            "bodies": len(raw_files),
        }
    now = utc_now()
    return write_snapshot(
        output_root=output_root,
        source=source,
        snapshot_id=utc_stamp(now),
        raw_files=raw_files,
        records=records,
        collected_at=now.isoformat(),
        request_urls=[url for _name, _payload, url in raw_files],
    )


def select_sources(
    sources: dict[str, Source], requested: list[str], all_open: bool
) -> list[Source]:
    if all_open and requested:
        raise CollectionError("--all-open cannot be combined with --source")
    if all_open:
        return [source for source in sources.values() if source.access == "OPEN_BATCH"]
    if not requested:
        raise CollectionError("choose at least one --source or use --all-open")
    missing = sorted(set(requested) - set(sources))
    if missing:
        raise CollectionError("unknown source IDs: " + ", ".join(missing))
    return [sources[source_id] for source_id in requested]


def effective_response_limit(source: Source, absolute_limit: int) -> int:
    if absolute_limit <= 0:
        raise CollectionError("--max-bytes must be positive")
    return min(absolute_limit, source.max_response_bytes or absolute_limit)


def collection_plan(
    selected: Iterable[Source], *, absolute_response_limit: int, total_budget_bytes: int
) -> dict[str, Any]:
    """Create a network-free preflight record for a collection run."""

    if total_budget_bytes <= 0:
        raise CollectionError("--max-total-bytes must be positive")
    entries: list[dict[str, Any]] = []
    estimated_total = 0
    source_hard_cap_total = 0
    request_total = 0
    for source in selected:
        allowed = source.access == "OPEN_BATCH"
        response_limit = effective_response_limit(source, absolute_response_limit)
        requests = source.requests_per_run
        expected = source.expected_bytes_per_run
        source_cap = response_limit * requests
        if allowed:
            request_total += requests
            source_hard_cap_total += source_cap
            estimated_total += expected or 0
        entries.append(
            {
                "source_id": source.source_id,
                "access": source.access,
                "eligible_for_collection": allowed,
                "reason": None if allowed else "not explicitly approved for batch collection",
                "request_count": requests if allowed else 0,
                "estimated_bytes_per_run": expected if allowed else None,
                "max_bytes_per_response": response_limit if allowed else None,
                "source_hard_cap_bytes": source_cap if allowed else None,
                "refresh_hint": source.refresh_hint,
                "url": source.url,
            }
        )
    return {
        "schema_version": "uap.collection_plan.v1",
        "network_contacted": False,
        "global_budget_bytes": total_budget_bytes,
        "estimated_download_bytes": estimated_total,
        "source_hard_cap_bytes": source_hard_cap_total,
        "request_count": request_total,
        "sources": entries,
    }


def command_sources(args: argparse.Namespace) -> int:
    registry, sources = load_registry(args.registry)
    if args.urls:
        print("\n".join(atlas_urls(registry, args.registry)))
        return 0
    rows = [
        {
            "id": source.source_id,
            "access": source.access,
            "role": source.role,
            "url": source.url,
            "expected_bytes_per_run": source.expected_bytes_per_run,
            "max_response_bytes": source.max_response_bytes,
            "requests_per_run": source.requests_per_run,
            "refresh_hint": source.refresh_hint,
            "metadata": source.source_metadata,
        }
        for source in sources.values()
    ]
    print(json.dumps(rows, ensure_ascii=False, indent=2))
    return 0


def command_review(args: argparse.Namespace) -> int:
    """Print the source-admission queue without contacting any provider."""

    _registry, sources = load_registry(args.registry)
    rows: list[dict[str, Any]] = []
    access_counter: Counter[str] = Counter()
    for source in sources.values():
        metadata = source.source_metadata or {}
        is_active = source.access == "OPEN_BATCH"
        is_review = source.access.endswith("_REVIEW")
        queue_state = (
            "active_collector"
            if is_active
            else "admission_review"
            if is_review
            else "manual_or_permission_required"
        )
        access_counter[source.access] += 1
        rows.append(
            {
                "source_id": source.source_id,
                "queue_state": queue_state,
                "access": source.access,
                "admission_state": metadata.get("admission_state"),
                "kind": source.kind,
                "role": source.role,
                "url": source.url,
                "portal_url": source.portal_url,
                "expected_bytes_per_run": source.expected_bytes_per_run,
                "max_response_bytes": source.max_response_bytes,
                "requests_per_run": source.requests_per_run,
                "full_media_policy": metadata.get("full_media_policy"),
                "next_action": (
                    "may_be_previewed_or_collected_with_collect"
                    if is_active
                    else metadata.get("admission_state")
                    or "manual_terms_or_access_review"
                ),
            }
        )
    print(
        json.dumps(
            {
                "schema_version": "uap.source_admission_queue.v1",
                "network_contacted": False,
                "access_counts": dict(sorted(access_counter.items())),
                "sources": rows,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def command_collect(args: argparse.Namespace) -> int:
    _registry, sources = load_registry(args.registry)
    selected = select_sources(sources, args.source, args.all_open)
    planned = collection_plan(
        selected,
        absolute_response_limit=args.max_bytes,
        total_budget_bytes=args.max_total_bytes,
    )
    if args.dry_run:
        print(json.dumps({"dry_run": True, **planned}, ensure_ascii=False, indent=2))
        return 0
    blocked = [entry for entry in planned["sources"] if not entry["eligible_for_collection"]]
    if blocked:
        print(json.dumps({"ok": False, **planned}, ensure_ascii=False, indent=2))
        return 2
    results: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    budget = DownloadBudget(max_bytes=args.max_total_bytes)
    for source in selected:
        response_limit = effective_response_limit(source, args.max_bytes)
        try:
            if source.kind == "nasa_horizons_planets":
                result = collect_horizons(
                    source=source,
                    output_root=args.output_root,
                    max_bytes=response_limit,
                    timeout_seconds=args.timeout_seconds,
                    start=args.date,
                    budget=budget,
                )
            else:
                result = collect_standard_source(
                    source=source,
                    output_root=args.output_root,
                    max_bytes=response_limit,
                    timeout_seconds=args.timeout_seconds,
                    budget=budget,
                )
            results.append(result)
        except CollectionError as exc:
            failures.append({"source_id": source.source_id, "error": str(exc)})
    print(
        json.dumps(
            {
                "ok": not failures,
                "output_root": str(args.output_root),
                "plan": planned,
                "network_bytes_used": budget.used_bytes,
                "network_bytes_remaining": budget.remaining_bytes,
                "results": results,
                "failures": failures,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if not failures else 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    subparsers = parser.add_subparsers(dest="command", required=True)

    source_parser = subparsers.add_parser("sources", help="list registered source entries")
    source_parser.add_argument("--urls", action="store_true", help="print all known atlas URLs only")
    source_parser.set_defaults(handler=command_sources)

    review_parser = subparsers.add_parser(
        "review", help="show the offline source-admission queue and no-contact next actions"
    )
    review_parser.set_defaults(handler=command_review)

    collect_parser = subparsers.add_parser("collect", help="collect only explicitly open batch sources")
    collect_parser.add_argument("--source", action="append", default=[])
    collect_parser.add_argument("--all-open", action="store_true")
    collect_parser.add_argument("--dry-run", action="store_true")
    collect_parser.add_argument("--output-root", type=Path, default=DEFAULT_DATA_ROOT)
    collect_parser.add_argument(
        "--max-bytes",
        type=int,
        default=DEFAULT_PER_RESPONSE_LIMIT_BYTES,
        help="absolute ceiling for one response; source-specific ceilings remain in force",
    )
    collect_parser.add_argument(
        "--max-total-bytes",
        type=int,
        default=DEFAULT_TOTAL_DOWNLOAD_BUDGET_BYTES,
        help="hard ceiling for all responses in one run (default: 64 MiB)",
    )
    collect_parser.add_argument("--timeout-seconds", type=float, default=60.0)
    collect_parser.add_argument(
        "--date",
        type=date.fromisoformat,
        default=utc_now().date(),
        help="UTC date for the nine-body Horizons control snapshot",
    )
    collect_parser.set_defaults(handler=command_collect)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.handler(args))
    except CollectionError as exc:
        parser.error(str(exc))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
