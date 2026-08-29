#!/usr/bin/env python3
"""Assemble a static, publishable build of the map application.

``serve_map.py`` is a local reader: it filters the release manifest, allow-lists
every path and hash-checks each asset before binding a port.  A static host does
none of that, so this tool has to do the filtering ahead of time -- it copies
only what the browser is allowed to see, writes the public projection of the
release manifest instead of the internal one, and leaves out the optional
high-resolution texture pack that is installed separately.

The output is a directory: publishing it anywhere is a separate, human decision.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Any

ROOT = Path(__file__).resolve().parent
DEFAULT_OUTPUT = ROOT / "dist"
# Installed on demand by earth_texture_500m.py; far too large to publish.
EXCLUDED_ASSET_DIRECTORIES = ("earth_lod1/l3",)
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
NOTICE = """# Attribution and licences

Sighting reports
: UAPDrop. "UAP Sightings Open Dataset." UAPDrop, https://www.uapdrop.com/data.html
: Released under CC BY 4.0 (https://creativecommons.org/licenses/by/4.0/).
: The underlying government records remain in the public domain under their
  originating archives' terms; each record keeps its own source reference.

Astronomy control
: NASA/JPL fireball and ephemeris data. NASA content used factually and without
  implying endorsement may be used without explicit permission; NASA is
  acknowledged as the source.

Earth texture
: NASA Earth Observatory, Blue Marble Next Generation.

Country outlines and land
: Natural Earth 1:50m admin-0 and 1:110m land (public domain).

2D basemap tiles
: (c) OpenStreetMap contributors, ODbL. Tiles are requested by the viewer's
  browser from OpenStreetMap only while the 2D basemap layer is enabled.

The report text shown on the map is the source's own wording, reproduced
verbatim and never rewritten or translated.
"""


# --- publication audit -----------------------------------------------------
#
# A static host serves whatever is in the directory, so "only publish what we
# are licensed to publish" cannot rest on anyone remembering it.  The build
# fails unless every shipped file maps to a licence and every attribution the
# licences require is actually on the page.

RIGHTS_TARGETS_PATH = ROOT / "source_rights_targets.json"
BASEMAP_MANIFEST_PATH = ROOT / "map_app" / "assets" / "basemap_manifest.json"

ASSET_CLASSES: tuple[tuple[str, str], ...] = (
    (r"^map_app/assets/earth_lod1/.+\.jpg$", "nasa_earth_texture"),
    (r"^map_app/assets/nasa_blue_marble_[0-9x_]+\.jpg$", "nasa_earth_texture"),
    (r"^map_app/assets/ne_[0-9a-z_]+\.geojson$", "natural_earth"),
    (r"^map_app/assets/[a-z0-9_]+\.json$", "repository"),
    (r"^map_app/(index\.html|styles\.css|app\.js|map_config\.json)$", "repository"),
    (r"^data/derived/releases/[^/]+/map_features/[a-z_]+\.geojson\.gz$", "release_data"),
    (r"^data/derived/current_release\.json$", "repository"),
    (r"^(NOTICE\.md|index\.html|\.nojekyll)$", "repository"),
    (r"^DATA_ARCHITECTURE_FOR_MAP_[0-9]+_ZH\.md$", "repository"),
)

# Attribution each shipped class must carry on the published page.
REQUIRED_ATTRIBUTION: dict[str, tuple[str, ...]] = {
    "nasa_earth_texture": ("NASA",),
    "natural_earth": ("Natural Earth",),
    "uapdrop": ("UAPDrop", "CC BY 4.0", "creativecommons.org/licenses/by/4.0"),
    "nasa_fireball": ("NASA",),
    "openstreetmap": ("OpenStreetMap", "openstreetmap.org/copyright"),
}


def classify(relative_path: str) -> str | None:
    for pattern, class_name in ASSET_CLASSES:
        if re.match(pattern, relative_path):
            return class_name
    return None


def publishable_sources() -> dict[str, dict[str, Any]]:
    document = json.loads(RIGHTS_TARGETS_PATH.read_text(encoding="utf-8"))
    return {
        source_id: entry.get("verdict") or {}
        for source_id, entry in document.get("sources", {}).items()
    }


def shipped_record_sources(output: Path) -> dict[str, set[str]]:
    sources: dict[str, set[str]] = {}
    for path in sorted((output / "data").rglob("*.geojson.gz")):
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            collection = json.load(handle)
        sources[path.name] = {
            str(feature.get("properties", {}).get("source_id"))
            for feature in collection.get("features", [])
        }
    return sources


def audit_publication(output: Path) -> dict[str, Any]:
    failures: list[str] = []
    warnings: list[str] = []

    unclassified = []
    classes: set[str] = set()
    for path in sorted(output.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(output).as_posix()
        class_name = classify(relative)
        if class_name is None:
            unclassified.append(relative)
        else:
            classes.add(class_name)
    if unclassified:
        failures.append(
            f"{len(unclassified)} shipped file(s) map to no licence rule: "
            + ", ".join(unclassified[:5])
        )

    verdicts = publishable_sources()
    record_sources = shipped_record_sources(output)
    shipped_source_ids: set[str] = set()
    for layer, ids in record_sources.items():
        for source_id in sorted(ids):
            shipped_source_ids.add(source_id)
            verdict = verdicts.get(source_id)
            if verdict is None:
                failures.append(f"{layer}: {source_id} has no rights review")
            elif verdict.get("publishable") is not True:
                failures.append(
                    f"{layer}: {source_id} is not cleared for publication "
                    f"(verdict {verdict.get('state')}, publishable {verdict.get('publishable')!r})"
                )

    page = (output / "map_app" / "index.html").read_text(encoding="utf-8")
    required: set[str] = set()
    for class_name in classes:
        required.update(REQUIRED_ATTRIBUTION.get(class_name, ()))
    for source_id in shipped_source_ids:
        required.update(REQUIRED_ATTRIBUTION.get(source_id, ()))
    config = json.loads((output / "map_app" / "map_config.json").read_text(encoding="utf-8"))
    uses_osm = any(
        "openstreetmap.org" in str(basemap.get("tile_url_template", ""))
        for basemap in (config.get("basemaps") or {}).values()
    )
    if uses_osm:
        required.update(REQUIRED_ATTRIBUTION["openstreetmap"])
        warnings.append(
            "The 2D basemap sends viewers' browsers to the OpenStreetMap tile servers. "
            "A public deployment should stay within the OSM tile usage policy or switch to "
            "an own tile source."
        )
    missing = sorted(token for token in required if token not in page)
    if missing:
        failures.append("required attribution missing from the page: " + ", ".join(missing))

    if not (output / "NOTICE.md").is_file():
        failures.append("NOTICE.md is missing from the build")

    return {
        "compliant": not failures,
        "shipped_classes": sorted(classes),
        "shipped_record_sources": {layer: sorted(ids) for layer, ids in record_sources.items()},
        "attribution_verified": sorted(required),
        "failures": failures,
        "warnings": warnings,
    }


def copy_map_app(output: Path) -> int:
    source = ROOT / "map_app"
    target = output / "map_app"
    excluded = {(source / "assets" / name).resolve() for name in EXCLUDED_ASSET_DIRECTORIES}

    def ignore(directory: str, names: list[str]) -> set[str]:
        base = Path(directory).resolve()
        return {name for name in names if (base / name).resolve() in excluded}

    shutil.copytree(source, target, ignore=ignore)
    return sum(1 for path in target.rglob("*") if path.is_file())


def public_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    """Only the fields the browser needs; never input roots or receipts."""

    return {key: manifest[key] for key in PUBLIC_RELEASE_FIELDS if key in manifest}


def copy_release(output: Path) -> dict[str, Any]:
    manifest_path = ROOT / "data" / "derived" / "current_release.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    release_id = manifest["release_id"]
    target_manifest = output / "data" / "derived" / "current_release.json"
    target_manifest.parent.mkdir(parents=True, exist_ok=True)
    target_manifest.write_text(
        json.dumps(public_manifest(manifest), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    copied = []
    release_root = ROOT / "data" / "derived" / "releases" / release_id
    for key, artifact in (manifest.get("map_artifacts") or {}).items():
        relative = artifact["path"]
        source = release_root / relative
        destination = output / "data" / "derived" / "releases" / release_id / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        digest = hashlib.sha256(destination.read_bytes()).hexdigest()
        if digest != artifact.get("compressed_sha256"):
            raise SystemExit(f"{key}: copied artifact does not match the manifest digest")
        copied.append({"key": key, "path": relative, "bytes": destination.stat().st_size})
    return {"release_id": release_id, "artifacts": copied}


def regenerate_manifests(output: Path) -> dict[str, Any]:
    """Re-sign the texture manifests against what actually shipped."""

    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "earth_texture_lod.py"),
            "--assets-root",
            str(output / "map_app" / "assets"),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def directory_bytes(path: Path) -> int:
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def build(output: Path, force: bool) -> dict[str, Any]:
    if output.exists():
        if not force:
            raise SystemExit(f"{output} already exists; pass --force to replace it")
        shutil.rmtree(output)
    output.mkdir(parents=True)

    files = copy_map_app(output)
    release = copy_release(output)
    manifests = regenerate_manifests(output)
    shutil.copy2(
        ROOT / "DATA_ARCHITECTURE_FOR_MAP_20260813_ZH.md",
        output / "DATA_ARCHITECTURE_FOR_MAP_20260813_ZH.md",
    )
    (output / "NOTICE.md").write_text(NOTICE, encoding="utf-8")
    # GitHub Pages skips paths beginning with an underscore unless this exists.
    (output / ".nojekyll").write_text("", encoding="utf-8")
    (output / "index.html").write_text(
        '<!doctype html><meta charset="utf-8">'
        '<meta http-equiv="refresh" content="0; url=map_app/">'
        '<title>全球 UAP 資料圖譜</title>'
        '<a href="map_app/">全球 UAP 資料圖譜</a>\n',
        encoding="utf-8",
    )

    audit = audit_publication(output)
    if not audit["compliant"]:
        # Refuse to leave an unpublishable build on disk.
        shutil.rmtree(output)
        raise SystemExit(
            "publication audit failed:\n  - " + "\n  - ".join(audit["failures"])
        )

    return {
        "output": str(output),
        "audit": audit,
        "map_app_files": files,
        "release": release,
        "texture_levels": manifests["levels"],
        "optional_levels": manifests["optional_levels"],
        "total_bytes": directory_bytes(output),
        "total_files": sum(1 for path in output.rglob("*") if path.is_file()),
        "published": False,
        "note": "Static build only. Publishing it is a separate, human decision.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--force", action="store_true", help="replace an existing output directory")
    arguments = parser.parse_args()
    report = build(arguments.output.resolve(), arguments.force)
    report["total_megabytes"] = round(report["total_bytes"] / 1048576, 1)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
