#!/usr/bin/env python3
"""Prepare the Natural Earth country layer served to the 3D globe.

The globe only had a land silhouette, so nothing on it said which country you
were looking at.  This tool trims the Natural Earth admin-0 download to the
fields the map actually draws (traditional-Chinese name, label anchor, label
rank), rounds coordinates to about 11 m, and records the asset in the basemap
manifest so the server keeps hash-checking it like every other local asset.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
CACHE = ROOT / "data" / "cache" / "natural_earth"
ASSETS = ROOT / "map_app" / "assets"
SOURCE_NAME = "ne_50m_admin_0_countries.geojson"
TARGET_NAME = "ne_50m_admin_0_countries.geojson"
SOURCE_URL = (
    "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/v5.1.2/geojson/"
    + SOURCE_NAME
)
COORDINATE_DIGITS = 4
KEPT_PROPERTIES = (
    "NAME",
    "NAME_ZHT",
    "NAME_ZH",
    "NAME_EN",
    "ISO_A2",
    # Natural Earth writes -99 for France and Norway in ISO_A2; the _EH variant
    # carries the real code, and the map joins reports on it.
    "ISO_A2_EH",
    "CONTINENT",
    "LABELRANK",
    "LABEL_X",
    "LABEL_Y",
    "MIN_LABEL",
    "MAX_LABEL",
)


def round_ring(ring: list[list[float]]) -> list[list[float]]:
    rounded: list[list[float]] = []
    for point in ring:
        longitude = round(float(point[0]), COORDINATE_DIGITS)
        latitude = round(float(point[1]), COORDINATE_DIGITS)
        if rounded and rounded[-1][0] == longitude and rounded[-1][1] == latitude:
            continue
        rounded.append([longitude, latitude])
    if len(rounded) < 4:
        return []
    return rounded


def build() -> dict[str, Any]:
    source = CACHE / SOURCE_NAME
    if not source.is_file():
        raise SystemExit(f"missing Natural Earth download: {source}")
    collection = json.loads(source.read_text(encoding="utf-8"))

    features = []
    vertices = 0
    for feature in collection.get("features", []):
        geometry = feature.get("geometry") or {}
        kind = geometry.get("type")
        if kind == "Polygon":
            polygons = [geometry.get("coordinates") or []]
        elif kind == "MultiPolygon":
            polygons = geometry.get("coordinates") or []
        else:
            continue
        cleaned = []
        for polygon in polygons:
            rings = [ring for ring in (round_ring(r) for r in polygon) if ring]
            if rings:
                cleaned.append(rings)
                vertices += sum(len(ring) for ring in rings)
        if not cleaned:
            continue
        source_properties = feature.get("properties") or {}
        properties = {
            key: source_properties.get(key)
            for key in KEPT_PROPERTIES
            if source_properties.get(key) not in (None, "")
        }
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "MultiPolygon", "coordinates": cleaned},
                "properties": properties,
            }
        )

    payload = {
        "type": "FeatureCollection",
        "name": "ne_50m_admin_0_countries",
        "features": features,
    }
    target = ASSETS / TARGET_NAME
    target.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    byte_count = target.stat().st_size

    manifest_path = ASSETS / "basemap_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["country_layer"] = {
        "asset_id": "natural-earth-ne_50m_admin_0_countries-v5.1.2",
        "path": TARGET_NAME,
        "source_url": SOURCE_URL,
        "source_page": (
            "https://www.naturalearthdata.com/downloads/50m-cultural-vectors/"
            "50m-admin-0-countries/"
        ),
        "source_repository_tag": "v5.1.2",
        "bytes": byte_count,
        "sha256": digest,
        "media_type": "application/geo+json",
        "coordinate_reference_system": "OGC:CRS84",
        "license": "public_domain",
        "license_url": "https://www.naturalearthdata.com/about/terms-of-use/",
        "feature_count": len(features),
        "name_field": "NAME_ZHT",
        "usage": (
            "Country outlines and labels for orientation only. Natural Earth boundaries are a "
            "1:50m cartographic product, not a legal boundary claim, and the map does not "
            "assert any sovereignty position."
        ),
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return {
        "features": len(features),
        "vertices": vertices,
        "bytes": byte_count,
        "sha256": digest,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    print(json.dumps(build(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
