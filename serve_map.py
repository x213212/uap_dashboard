#!/usr/bin/env python3
"""Validate and serve the local, read-only UAP map application.

The server exposes only the ``uap_lab`` directory, marks immutable release
GeoJSON as gzip-encoded JSON, and performs an offline integrity check before it
binds a port.  It never contacts a provider and never edits a release.
"""

from __future__ import annotations

import argparse
from functools import partial
import gzip
import hashlib
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import sys
from typing import Any
from urllib.parse import urlsplit
import webbrowser


ROOT = Path(__file__).resolve().parent
MAP_RELEASE_SCHEMA_VERSION = "uap.map_release.v1"
BASEMAP_SCHEMA_VERSION = "uap.basemap_asset.v1"
MAP_APP_CONFIG_SCHEMA_VERSION = "uap.map_app_config.v1"
EARTH_TEXTURE_LOD_SCHEMA_VERSION = "uap.earth_texture_lod.v1"
EARTH_TEXTURE_LOD_PYRAMID_SCHEMA_VERSION = "uap.earth_texture_lod.v2"
RELEASE_ID_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
PUBLIC_RELEASE_FIELDS = (
    "schema_version",
    "release_id",
    "built_at",
    "observation_schema_version",
    "observation_version_count",
    "observation_current_count",
    "map_features",
    "map_artifacts",
    "h3",
)


class MapValidationError(RuntimeError):
    """Raised when a local map asset fails its release contract."""





def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise MapValidationError(f"cannot read {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise MapValidationError(f"invalid JSON at {path}: {exc}") from exc


def sha256_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    byte_count = 0
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
                byte_count += len(chunk)
    except OSError as exc:
        raise MapValidationError(f"cannot read {path}: {exc}") from exc
    return digest.hexdigest(), byte_count


def safe_child(root: Path, relative_path: str) -> Path:
    if not relative_path or Path(relative_path).is_absolute():
        raise MapValidationError(f"unsafe empty or absolute path: {relative_path!r}")
    candidate = (root / relative_path).resolve()
    resolved_root = root.resolve()
    if not candidate.is_relative_to(resolved_root):
        raise MapValidationError(f"path escapes release root: {relative_path}")
    return candidate


def public_release_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    """Return only fields required by the browser-facing map application."""

    return {key: manifest[key] for key in PUBLIC_RELEASE_FIELDS if key in manifest}


def validate_basemap(root: Path) -> dict[str, Any]:
    assets_root = root / "map_app" / "assets"
    manifest_path = assets_root / "basemap_manifest.json"
    manifest = read_json(manifest_path)
    if not isinstance(manifest, dict) or manifest.get("schema_version") != BASEMAP_SCHEMA_VERSION:
        raise MapValidationError(f"unsupported basemap manifest: {manifest_path}")
    relative_path = manifest.get("path")
    if not isinstance(relative_path, str):
        raise MapValidationError("basemap manifest lacks path")
    asset_path = safe_child(assets_root, relative_path)
    digest, byte_count = sha256_file(asset_path)
    if digest != manifest.get("sha256"):
        raise MapValidationError(
            f"basemap SHA-256 mismatch: expected {manifest.get('sha256')}, got {digest}"
        )
    if byte_count != manifest.get("bytes"):
        raise MapValidationError(
            f"basemap byte count mismatch: expected {manifest.get('bytes')}, got {byte_count}"
        )
    collection = read_json(asset_path)
    if (
        not isinstance(collection, dict)
        or collection.get("type") != "FeatureCollection"
        or not isinstance(collection.get("features"), list)
    ):
        raise MapValidationError("basemap is not a GeoJSON FeatureCollection")
    result: dict[str, Any] = {
        "asset_id": manifest.get("asset_id"),
        "features": len(collection["features"]),
        "bytes": byte_count,
        "sha256": digest,
    }
    earth_texture = manifest.get("earth_texture")
    if earth_texture is None:
        return result
    if not isinstance(earth_texture, dict):
        raise MapValidationError("earth_texture must be an object when present")
    texture_path_value = earth_texture.get("path")
    if not isinstance(texture_path_value, str):
        raise MapValidationError("earth_texture lacks path")
    texture_path = safe_child(assets_root, texture_path_value)
    texture_digest, texture_bytes = sha256_file(texture_path)
    if texture_digest != earth_texture.get("sha256"):
        raise MapValidationError(
            "earth_texture SHA-256 mismatch: "
            f"expected {earth_texture.get('sha256')}, got {texture_digest}"
        )
    if texture_bytes != earth_texture.get("bytes"):
        raise MapValidationError(
            "earth_texture byte count mismatch: "
            f"expected {earth_texture.get('bytes')}, got {texture_bytes}"
        )
    if earth_texture.get("media_type") != "image/jpeg":
        raise MapValidationError("earth_texture must be image/jpeg")
    width = earth_texture.get("width")
    height = earth_texture.get("height")
    if not isinstance(width, int) or not isinstance(height, int) or width < 1 or height < 1:
        raise MapValidationError("earth_texture requires positive width and height")
    result["earth_texture"] = {
        "asset_id": earth_texture.get("asset_id"),
        "bytes": texture_bytes,
        "sha256": texture_digest,
        "width": width,
        "height": height,
    }
    texture_lod_manifest = manifest.get("earth_texture_lod_manifest")
    if texture_lod_manifest is not None:
        result["earth_texture_lod"] = validate_earth_texture_lod(
            assets_root,
            texture_lod_manifest,
        )
    country_layer = manifest.get("country_layer")
    if country_layer is not None:
        result["country_layer"] = validate_country_layer(assets_root, country_layer)
    return result


def validate_country_layer(assets_root: Path, specification: Any) -> dict[str, Any]:
    if not isinstance(specification, dict):
        raise MapValidationError("country_layer must be an object")
    relative_path = specification.get("path")
    if not isinstance(relative_path, str):
        raise MapValidationError("country_layer lacks path")
    layer_path = safe_child(assets_root, relative_path)
    digest, byte_count = sha256_file(layer_path)
    if digest != specification.get("sha256"):
        raise MapValidationError(
            f"country_layer SHA-256 mismatch: expected {specification.get('sha256')}, got {digest}"
        )
    if byte_count != specification.get("bytes"):
        raise MapValidationError(
            f"country_layer byte count mismatch: expected {specification.get('bytes')}, got {byte_count}"
        )
    collection = read_json(layer_path)
    features = collection.get("features") if isinstance(collection, dict) else None
    if (
        not isinstance(collection, dict)
        or collection.get("type") != "FeatureCollection"
        or not isinstance(features, list)
        or not features
    ):
        raise MapValidationError("country_layer is not a GeoJSON FeatureCollection")
    name_field = specification.get("name_field")
    if not isinstance(name_field, str):
        raise MapValidationError("country_layer lacks name_field")
    for feature in features:
        geometry = feature.get("geometry") if isinstance(feature, dict) else None
        if not isinstance(geometry, dict) or geometry.get("type") not in {
            "Polygon",
            "MultiPolygon",
        }:
            raise MapValidationError("country_layer feature is not a polygon")
    declared = specification.get("feature_count")
    if declared is not None and declared != len(features):
        raise MapValidationError(
            f"country_layer feature count mismatch: expected {declared}, got {len(features)}"
        )
    return {
        "asset_id": specification.get("asset_id"),
        "features": len(features),
        "bytes": byte_count,
        "sha256": digest,
        "name_field": name_field,
    }


def validate_earth_texture_lod(
    assets_root: Path,
    specification: Any,
) -> dict[str, Any]:
    if not isinstance(specification, dict):
        raise MapValidationError("earth_texture_lod_manifest must be an object")
    manifest_path_value = specification.get("path")
    if not isinstance(manifest_path_value, str):
        raise MapValidationError("earth_texture_lod_manifest lacks path")
    manifest_path = safe_child(assets_root, manifest_path_value)
    digest, byte_count = sha256_file(manifest_path)
    if digest != specification.get("sha256"):
        raise MapValidationError(
            "earth_texture_lod manifest SHA-256 mismatch: "
            f"expected {specification.get('sha256')}, got {digest}"
        )
    if byte_count != specification.get("bytes"):
        raise MapValidationError(
            "earth_texture_lod manifest byte count mismatch: "
            f"expected {specification.get('bytes')}, got {byte_count}"
        )
    manifest = read_json(manifest_path)
    if not isinstance(manifest, dict):
        raise MapValidationError("unsupported earth_texture_lod manifest")
    schema_version = manifest.get("schema_version")
    if schema_version == EARTH_TEXTURE_LOD_SCHEMA_VERSION:
        levels = [
            {
                "level": 0,
                "tile_width": manifest.get("tile_width"),
                "tile_height": manifest.get("tile_height"),
                "tiles": manifest.get("tiles"),
            }
        ]
    elif schema_version == EARTH_TEXTURE_LOD_PYRAMID_SCHEMA_VERSION:
        levels = manifest.get("levels")
        if not isinstance(levels, list) or not levels:
            raise MapValidationError("earth_texture_lod pyramid lacks levels")
    else:
        raise MapValidationError("unsupported earth_texture_lod manifest")

    columns = manifest.get("columns")
    rows = manifest.get("rows")
    if not all(isinstance(value, int) and value > 0 for value in (columns, rows)):
        raise MapValidationError("earth_texture_lod requires a positive tile grid")

    level_reports: list[dict[str, Any]] = []
    seen_levels: set[int] = set()
    previous_resolution = 0
    for index, level in enumerate(levels):
        if not isinstance(level, dict):
            raise MapValidationError("earth_texture_lod level is not an object")
        level_index = level.get("level", index)
        if not isinstance(level_index, int) or level_index in seen_levels:
            raise MapValidationError("earth_texture_lod level index is invalid or duplicated")
        seen_levels.add(level_index)
        # A level may refine the grid instead of the tile, so each one declares
        # its own columns and rows and falls back to the manifest grid.
        level_columns = level.get("columns", columns)
        level_rows = level.get("rows", rows)
        tile_width = level.get("tile_width")
        tile_height = level.get("tile_height")
        if not all(
            isinstance(value, int) and value > 0
            for value in (level_columns, level_rows, tile_width, tile_height)
        ):
            raise MapValidationError(
                "earth_texture_lod requires positive grid and tile dimensions"
            )
        width = level_columns * tile_width
        height = level_rows * tile_height
        if width != 2 * height:
            raise MapValidationError("earth_texture_lod level must cover the globe 2:1")
        if width <= previous_resolution:
            raise MapValidationError("earth_texture_lod levels must grow from coarse to fine")
        previous_resolution = width
        tiles = level.get("tiles")
        if not isinstance(tiles, list) or len(tiles) != level_columns * level_rows:
            raise MapValidationError("earth_texture_lod tile count does not match the declared grid")
        seen_coordinates: set[tuple[int, int]] = set()
        for tile in tiles:
            if not isinstance(tile, dict):
                raise MapValidationError("earth_texture_lod tile is not an object")
            column = tile.get("column")
            row = tile.get("row")
            if (
                not isinstance(column, int)
                or not isinstance(row, int)
                or not (0 <= column < level_columns and 0 <= row < level_rows)
            ):
                raise MapValidationError("earth_texture_lod tile coordinate is invalid")
            coordinate = (column, row)
            if coordinate in seen_coordinates:
                raise MapValidationError("earth_texture_lod contains duplicate tile coordinates")
            seen_coordinates.add(coordinate)
            relative_path = tile.get("path")
            if not isinstance(relative_path, str):
                raise MapValidationError("earth_texture_lod tile lacks path")
            tile_path = safe_child(assets_root, relative_path)
            tile_digest, tile_bytes = sha256_file(tile_path)
            if tile_digest != tile.get("sha256"):
                raise MapValidationError(f"earth_texture_lod SHA-256 mismatch: {relative_path}")
            if tile_bytes != tile.get("bytes"):
                raise MapValidationError(f"earth_texture_lod byte count mismatch: {relative_path}")
        level_reports.append(
            {
                "level": level_index,
                "columns": level_columns,
                "rows": level_rows,
                "tile_width": tile_width,
                "tile_height": tile_height,
                "tile_count": len(tiles),
                "pixels_per_degree": round(width / 360.0, 4),
            }
        )

    optional_levels = manifest.get("optional_levels", [])
    if not isinstance(optional_levels, list):
        raise MapValidationError("earth_texture_lod optional_levels must be a list")
    optional_reports = []
    for optional in optional_levels:
        # An optional level is declared whether or not it is installed, so the
        # map can say a sharper pack exists instead of silently topping out.
        if not isinstance(optional, dict) or not isinstance(optional.get("level"), int):
            raise MapValidationError("earth_texture_lod optional level is invalid")
        installed = optional.get("installed")
        if not isinstance(installed, bool):
            raise MapValidationError("earth_texture_lod optional level lacks installed flag")
        if installed and optional["level"] not in seen_levels:
            raise MapValidationError(
                f"earth_texture_lod optional level {optional['level']} claims to be installed "
                "but is not present in levels"
            )
        if not installed and optional["level"] in seen_levels:
            raise MapValidationError(
                f"earth_texture_lod optional level {optional['level']} is present in levels "
                "but is not marked installed"
            )
        optional_reports.append(
            {
                "level": optional["level"],
                "installed": installed,
                "pack": optional.get("pack"),
                "pixels_per_degree": optional.get("pixels_per_degree"),
            }
        )

    finest = level_reports[-1]
    if (
        manifest.get("source_width") != finest["columns"] * finest["tile_width"]
        or manifest.get("source_height") != finest["rows"] * finest["tile_height"]
    ):
        raise MapValidationError("earth_texture_lod source dimensions do not match the tile grid")

    return {
        "asset_id": manifest.get("asset_id"),
        "schema_version": schema_version,
        "columns": columns,
        "rows": rows,
        "levels": level_reports,
        "optional_levels": optional_reports,
        "tile_count": sum(report["tile_count"] for report in level_reports),
        "manifest_bytes": byte_count,
        "manifest_sha256": digest,
    }


def earth_texture_lod_tiles(manifest: Any) -> list[dict[str, Any]]:
    """Return every tile record of a v1 or v2 texture LOD manifest."""

    if not isinstance(manifest, dict):
        return []
    levels = manifest.get("levels")
    if isinstance(levels, list):
        records: list[dict[str, Any]] = []
        for level in levels:
            tiles = level.get("tiles") if isinstance(level, dict) else None
            if isinstance(tiles, list):
                records.extend(tile for tile in tiles if isinstance(tile, dict))
        return records
    tiles = manifest.get("tiles")
    return [tile for tile in tiles if isinstance(tile, dict)] if isinstance(tiles, list) else []


def basemap_asset_public_paths(root: Path) -> frozenset[str]:
    """Return the optional basemap assets declared by the manifest."""

    basemap = read_json(root / "map_app" / "assets" / "basemap_manifest.json")
    if not isinstance(basemap, dict):
        return frozenset()
    paths = set()
    for key in ("earth_texture", "country_layer"):
        specification = basemap.get(key)
        if isinstance(specification, dict) and isinstance(specification.get("path"), str):
            paths.add(f"/map_app/assets/{specification['path']}")
    return frozenset(paths)


def earth_texture_lod_public_paths(root: Path) -> frozenset[str]:
    """Return validated, browser-safe texture tile paths for the active map server."""

    basemap = read_json(root / "map_app" / "assets" / "basemap_manifest.json")
    specification = basemap.get("earth_texture_lod_manifest") if isinstance(basemap, dict) else None
    if not isinstance(specification, dict) or not isinstance(specification.get("path"), str):
        return frozenset()
    assets_root = root / "map_app" / "assets"
    manifest = read_json(safe_child(assets_root, specification["path"]))
    return frozenset(
        f"/map_app/assets/{tile['path']}"
        for tile in earth_texture_lod_tiles(manifest)
        if isinstance(tile.get("path"), str)
    )


def validate_map_config(root: Path) -> dict[str, Any]:
    path = root / "map_app" / "map_config.json"
    config = read_json(path)
    if not isinstance(config, dict) or config.get("schema_version") != MAP_APP_CONFIG_SCHEMA_VERSION:
        raise MapValidationError(f"unsupported map app config: {path}")
    default_basemap = config.get("default_basemap")
    basemaps = config.get("basemaps")
    specification = basemaps.get(default_basemap) if isinstance(basemaps, dict) else None
    if not isinstance(default_basemap, str) or not isinstance(specification, dict):
        raise MapValidationError("map app config lacks a valid default basemap")
    template = specification.get("tile_url_template")
    if not isinstance(template, str) or not all(token in template for token in ("{z}", "{x}", "{y}")):
        raise MapValidationError("default basemap lacks a z/x/y tile URL template")
    parsed = urlsplit(template.replace("{z}", "0").replace("{x}", "0").replace("{y}", "0"))
    if parsed.scheme != "https" or parsed.hostname != "tile.openstreetmap.org":
        raise MapValidationError("default public basemap must use https://tile.openstreetmap.org")
    if specification.get("prefetch") is not False or specification.get("offline_download") is not False:
        raise MapValidationError("OSM public tiles must disable prefetch and offline download")
    if specification.get("network_mode") != "visible_viewport_only":
        raise MapValidationError("OSM public tiles must use visible_viewport_only network mode")
    return {
        "default_basemap": default_basemap,
        "tile_host": parsed.hostname,
        "network_mode": specification.get("network_mode"),
    }


def validate_feature_collection(
    path: Path,
    *,
    expected_count: int,
    expected_layer: str,
    expected_compressed_bytes: int | None = None,
    expected_compressed_sha256: str | None = None,
) -> dict[str, Any]:
    digest, byte_count = sha256_file(path)
    if expected_compressed_sha256 is not None and digest != expected_compressed_sha256:
        raise MapValidationError(
            f"artifact SHA-256 mismatch for {expected_layer}: "
            f"expected {expected_compressed_sha256}, got {digest}"
        )
    if expected_compressed_bytes is not None and byte_count != expected_compressed_bytes:
        raise MapValidationError(
            f"artifact compressed_bytes mismatch for {expected_layer}: "
            f"expected {expected_compressed_bytes}, got {byte_count}"
        )
    try:
        with gzip.open(path, mode="rt", encoding="utf-8") as handle:
            collection = json.load(handle)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise MapValidationError(f"invalid gzip GeoJSON at {path}: {exc}") from exc
    if (
        not isinstance(collection, dict)
        or collection.get("type") != "FeatureCollection"
        or not isinstance(collection.get("features"), list)
    ):
        raise MapValidationError(f"not a GeoJSON FeatureCollection: {path}")
    features = collection["features"]
    if len(features) != expected_count:
        raise MapValidationError(
            f"feature count mismatch for {path}: expected {expected_count}, got {len(features)}"
        )

    identifiers: set[str] = set()
    for index, feature in enumerate(features):
        if not isinstance(feature, dict) or feature.get("type") != "Feature":
            raise MapValidationError(f"invalid feature at {path}:{index}")
        identifier = str(feature.get("id") or "")
        if not identifier:
            raise MapValidationError(f"feature lacks id at {path}:{index}")
        if identifier in identifiers:
            raise MapValidationError(f"duplicate feature id at {path}:{index}: {identifier}")
        identifiers.add(identifier)
        geometry = feature.get("geometry")
        coordinates = geometry.get("coordinates") if isinstance(geometry, dict) else None
        if (
            not isinstance(geometry, dict)
            or geometry.get("type") != "Point"
            or not isinstance(coordinates, list)
            or len(coordinates) < 2
        ):
            raise MapValidationError(f"feature is not a Point at {path}:{index}")
        try:
            longitude = float(coordinates[0])
            latitude = float(coordinates[1])
        except (TypeError, ValueError) as exc:
            raise MapValidationError(f"invalid coordinates at {path}:{index}") from exc
        if not -180 <= longitude <= 180 or not -90 <= latitude <= 90:
            raise MapValidationError(f"coordinates out of bounds at {path}:{index}")
        properties = feature.get("properties")
        role = properties.get("record_role") if isinstance(properties, dict) else None
        if expected_layer == "sightings_current" and role != "sighting":
            raise MapValidationError(f"non-sighting leaked into sighting layer at {path}:{index}")
        if expected_layer == "controls_current" and role == "sighting":
            raise MapValidationError(f"sighting leaked into control layer at {path}:{index}")

    return {
        "feature_count": len(features),
        "compressed_bytes": byte_count,
        "compressed_sha256": digest,
    }


def validate_release(root: Path) -> dict[str, Any]:
    current_path = root / "data" / "derived" / "current_release.json"
    current = read_json(current_path)
    if not isinstance(current, dict) or current.get("schema_version") != MAP_RELEASE_SCHEMA_VERSION:
        raise MapValidationError(f"unsupported current release manifest: {current_path}")
    release_id = current.get("release_id")
    if not isinstance(release_id, str) or not RELEASE_ID_RE.fullmatch(release_id):
        raise MapValidationError(f"unsafe release_id: {release_id!r}")
    release_root = root / "data" / "derived" / "releases" / release_id
    immutable_manifest = read_json(release_root / "manifest.json")
    if immutable_manifest != current:
        raise MapValidationError("current_release.json differs from immutable release manifest")

    map_counts = current.get("map_features")
    if not isinstance(map_counts, dict):
        raise MapValidationError("release manifest lacks map_features")
    artifacts = current.get("map_artifacts")
    if artifacts is not None and not isinstance(artifacts, dict):
        raise MapValidationError("map_artifacts must be an object")

    results: dict[str, Any] = {}
    fallback_paths = {
        "sightings_current": "map_features/sightings_current.geojson.gz",
        "controls_current": "map_features/controls_current.geojson.gz",
    }
    for key, fallback_path in fallback_paths.items():
        expected_count = map_counts.get(key)
        if not isinstance(expected_count, int) or expected_count < 0:
            raise MapValidationError(f"invalid map feature count for {key}: {expected_count!r}")
        specification = artifacts.get(key) if isinstance(artifacts, dict) else None
        relative_path = specification.get("path") if isinstance(specification, dict) else fallback_path
        if not isinstance(relative_path, str):
            raise MapValidationError(f"artifact {key} lacks path")
        artifact_path = safe_child(release_root, relative_path)
        result = validate_feature_collection(
            artifact_path,
            expected_count=expected_count,
            expected_layer=key,
            expected_compressed_bytes=(
                specification.get("compressed_bytes") if isinstance(specification, dict) else None
            ),
            expected_compressed_sha256=(
                specification.get("compressed_sha256") if isinstance(specification, dict) else None
            ),
        )
        if isinstance(specification, dict):
            declared_count = specification.get("feature_count")
            declared_bytes = specification.get("compressed_bytes")
            declared_digest = specification.get("compressed_sha256")
            if declared_count != result["feature_count"]:
                raise MapValidationError(f"artifact feature_count mismatch for {key}")
            if declared_bytes != result["compressed_bytes"]:
                raise MapValidationError(f"artifact compressed_bytes mismatch for {key}")
            if declared_digest != result["compressed_sha256"]:
                raise MapValidationError(f"artifact SHA-256 mismatch for {key}")
        results[key] = {"path": relative_path, **result}

    return {
        "release_id": release_id,
        "observation_version_count": current.get("observation_version_count"),
        "observation_current_count": current.get("observation_current_count"),
        "layers": results,
    }


def validate_map(root: Path = ROOT) -> dict[str, Any]:
    required_static = [
        root / "map_app" / "index.html",
        root / "map_app" / "styles.css",
        root / "map_app" / "app.js",
        root / "map_app" / "map_config.json",
    ]
    missing = [str(path) for path in required_static if not path.is_file()]
    if missing:
        raise MapValidationError(f"missing static map assets: {', '.join(missing)}")
    return {
        "ok": True,
        "root": str(root.resolve()),
        "basemap": validate_basemap(root),
        "map_config": validate_map_config(root),
        "release": validate_release(root),
    }


class MapRequestHandler(SimpleHTTPRequestHandler):
    server_version = "UAPLocalMap/1.0"
    quiet = False
    release_id = ""
    public_manifest_payload = b"{}\n"
    earth_texture_lod_paths: frozenset[str] = frozenset()
    basemap_asset_paths: frozenset[str] = frozenset()

    def allowed_paths(self) -> set[str]:
        release_prefix = f"/data/derived/releases/{self.release_id}/map_features"
        allowed = {
            "/",
            "/map_app",
            "/map_app/",
            "/map_app/index.html",
            "/map_app/styles.css",
            "/map_app/app.js",
            "/map_app/map_config.json",
            "/map_app/assets/basemap_manifest.json",
            "/map_app/assets/ne_110m_land.geojson",
            "/map_app/assets/nasa_blue_marble_200406_5400x2700.jpg",
            "/map_app/assets/earth_lod1_manifest.json",
            "/data/derived/current_release.json",
            f"{release_prefix}/sightings_current.geojson.gz",
            f"{release_prefix}/controls_current.geojson.gz",
            "/DATA_ARCHITECTURE_FOR_MAP_20260813_ZH.md",
        }
        return allowed | set(self.earth_texture_lod_paths) | set(self.basemap_asset_paths)

    def request_path(self) -> str:
        return urlsplit(self.path).path

    def send_response_only(self, code: int, message: str | None = None) -> None:
        self.response_code = code
        super().send_response_only(code, message)


    def redirect_root(self) -> bool:
        if self.request_path() != "/":
            return False
        self.send_response(302)
        self.send_header("Location", "/map_app/")
        self.end_headers()
        return True

    def reject_disallowed_path(self) -> bool:
        if self.request_path() in self.allowed_paths():
            return False
        self.send_error(404, "Map asset not found")
        return True

    def serve_public_manifest(self, *, head_only: bool) -> bool:
        if self.request_path() != "/data/derived/current_release.json":
            return False
        payload = self.public_manifest_payload
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        if not head_only:
            self.wfile.write(payload)
        return True

    def do_GET(self) -> None:  # noqa: N802 - inherited HTTP method name
        if (
            self.redirect_root()
            or self.serve_public_manifest(head_only=False)
            or self.reject_disallowed_path()
        ):
            return
        super().do_GET()

    def do_HEAD(self) -> None:  # noqa: N802 - inherited HTTP method name
        if (
            self.redirect_root()
            or self.serve_public_manifest(head_only=True)
            or self.reject_disallowed_path()
        ):
            return
        super().do_HEAD()

    def guess_type(self, path: str) -> str:
        if path.endswith(".geojson.gz") or path.endswith(".geojson"):
            return "application/geo+json; charset=utf-8"
        return super().guess_type(path)

    def end_headers(self) -> None:
        request_path = urlsplit(self.path).path
        status = getattr(self, "response_code", 200)
        failed = status >= 400
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        # The error body is HTML, never the gzip artifact the path names.
        if not failed and request_path.endswith(".geojson.gz"):
            self.send_header("Content-Encoding", "gzip")
            self.send_header("Vary", "Accept-Encoding")
        if failed:
            # An immutable error is a trap: the application fetches assets with
            # cache: "force-cache", so a cached 404 from a moment when an asset
            # was still missing would be replayed even across a hard reload.
            self.send_header("Cache-Control", "no-store")
        elif request_path.endswith("/data/derived/current_release.json"):
            self.send_header("Cache-Control", "no-store")
        elif "/data/derived/releases/" in request_path or "/map_app/assets/" in request_path:
            self.send_header("Cache-Control", "public, max-age=31536000, immutable")
        else:
            self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def log_message(self, format: str, *args: object) -> None:
        if not self.quiet:
            super().log_message(format, *args)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1", help="bind host; defaults to loopback only")
    parser.add_argument("--port", type=int, default=8765, help="bind port; use 0 for an ephemeral port")
    parser.add_argument("--check", action="store_true", help="validate assets and exit without serving")
    parser.add_argument("--open", action="store_true", help="open the map URL in the default browser")
    parser.add_argument("--quiet", action="store_true", help="suppress HTTP request logs")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not 0 <= args.port <= 65535:
        raise SystemExit("--port must be between 0 and 65535")
    try:
        validation = validate_map(ROOT)
    except MapValidationError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    if args.check:
        print(json.dumps(validation, ensure_ascii=False, indent=2, sort_keys=True))
        return 0

    handler = partial(MapRequestHandler, directory=str(ROOT))
    MapRequestHandler.quiet = args.quiet
    MapRequestHandler.release_id = validation["release"]["release_id"]
    MapRequestHandler.earth_texture_lod_paths = earth_texture_lod_public_paths(ROOT)
    MapRequestHandler.basemap_asset_paths = basemap_asset_public_paths(ROOT)
    full_manifest = read_json(ROOT / "data" / "derived" / "current_release.json")
    MapRequestHandler.public_manifest_payload = (
        json.dumps(public_release_manifest(full_manifest), ensure_ascii=False, sort_keys=True)
        + "\n"
    ).encode("utf-8")
    try:
        server = ThreadingHTTPServer((args.host, args.port), handler)
    except OSError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    actual_port = server.server_address[1]
    url = f"http://{args.host}:{actual_port}/map_app/"
    print(
        json.dumps(
            {
                "ok": True,
                "url": url,
                "release_id": validation["release"]["release_id"],
                "exposure": "map-only",
            },
            ensure_ascii=False,
        )
    )
    if args.open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
