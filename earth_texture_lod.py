#!/usr/bin/env python3
"""Build the local Blue Marble texture pyramid used by the 3D globe.

The map application samples one texture level per frame.  Without intermediate
levels the globe jumps straight from the 5400x2700 overview (15 px/degree) to
the native 21600x10800 tiles (60 px/degree), so every zoom between those two
resolutions is magnified overview pixels -- the "blurry when zoomed" symptom.

This tool derives the missing levels from the already-downloaded native tiles
(no provider is contacted) and rewrites the LOD manifest as
``uap.earth_texture_lod.v2`` with one entry per level.  Every level keeps the
same 12x6 tile grid so the browser can swap a tile between levels without
recomputing geometry.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from PIL import Image

ROOT = Path(__file__).resolve().parent
ASSETS = ROOT / "map_app" / "assets"
LOD_MANIFEST = ASSETS / "earth_lod1_manifest.json"
BASEMAP_MANIFEST = ASSETS / "basemap_manifest.json"


def use_assets_root(assets_root: Path) -> None:
    """Point the generator at another asset tree, e.g. a static build."""

    global ASSETS, LOD_MANIFEST, BASEMAP_MANIFEST
    ASSETS = assets_root
    LOD_MANIFEST = ASSETS / "earth_lod1_manifest.json"
    BASEMAP_MANIFEST = ASSETS / "basemap_manifest.json"
SCHEMA_VERSION = "uap.earth_texture_lod.v2"
NATIVE_DIRECTORY = "earth_lod1"
JPEG_QUALITY = 92
# Levels that are too large to ship and are installed on demand.  They stay
# declared even when absent so the map can say a sharper version exists rather
# than silently topping out.
OPTIONAL_LEVELS = {
    3: {
        "pack": "nasa_blue_marble_500m",
        "label": "NASA Blue Marble 500 m",
        "pixels_per_degree": 240.0,
        "approximate_download_bytes": 426353871,
        "approximate_disk_bytes": 339155255,
        "install_command": "python3 earth_texture_500m.py --install",
        "uninstall_command": "python3 earth_texture_500m.py --uninstall",
    }
}


def sha256_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    byte_count = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
            byte_count += len(chunk)
    return digest.hexdigest(), byte_count


def tile_entry(column: int, row: int, relative_path: str) -> dict[str, Any]:
    digest, byte_count = sha256_file(ASSETS / relative_path)
    return {
        "column": column,
        "row": row,
        "path": relative_path,
        "bytes": byte_count,
        "sha256": digest,
    }


def level_entry(
    level: int,
    columns: int,
    rows: int,
    tile_size: int,
    tiles: list[dict[str, Any]],
) -> dict[str, Any]:
    width = columns * tile_size
    return {
        "level": level,
        # Levels may use different grids: the finest one keeps tiles small so the
        # browser only resides the few that are on screen.
        "columns": columns,
        "rows": rows,
        "tile_width": tile_size,
        "tile_height": tile_size,
        "width": width,
        "height": rows * tile_size,
        "pixels_per_degree": round(width / 360.0, 4),
        "tiles": sorted(tiles, key=lambda tile: (tile["row"], tile["column"])),
    }


def discover_dense_level(level: int) -> dict[str, Any] | None:
    """Pick up the 500 m level cut by earth_texture_500m.py, when present."""

    directory = ASSETS / NATIVE_DIRECTORY / f"l{level}"
    if not directory.is_dir():
        return None
    paths = sorted(directory.glob("tile_*.jpg"))
    if not paths:
        return None
    columns = max(int(path.stem.split("_")[1]) for path in paths) + 1
    rows = max(int(path.stem.split("_")[2]) for path in paths) + 1
    if len(paths) != columns * rows:
        raise SystemExit(f"level {level} grid is incomplete: {len(paths)} of {columns * rows}")
    with Image.open(paths[0]) as image:
        tile_size = image.width
    tiles = [
        tile_entry(
            int(path.stem.split("_")[1]),
            int(path.stem.split("_")[2]),
            f"{NATIVE_DIRECTORY}/l{level}/{path.name}",
        )
        for path in paths
    ]
    return level_entry(level, columns, rows, tile_size, tiles)


def build(force: bool = False, exclude_optional: bool = False) -> dict[str, Any]:
    manifest = json.loads(LOD_MANIFEST.read_text(encoding="utf-8"))
    columns = int(manifest["columns"])
    rows = int(manifest["rows"])
    native_tiles = manifest.get("tiles")
    if not isinstance(native_tiles, list):
        # Already a v2 manifest: recover the native level (the finest one).
        native_level = max(manifest["levels"], key=lambda entry: entry["tile_width"])
        native_tiles = native_level["tiles"]
        native_size = int(native_level["tile_width"])
    else:
        native_size = int(manifest["tile_width"])

    native_paths = {
        (int(tile["column"]), int(tile["row"])): str(tile["path"]) for tile in native_tiles
    }
    if len(native_paths) != columns * rows:
        raise SystemExit("native LOD grid is incomplete; refusing to derive levels")

    derived_sizes = [native_size // 4, native_size // 2]
    levels: list[dict[str, Any]] = []
    for index, tile_size in enumerate(derived_sizes):
        directory = ASSETS / NATIVE_DIRECTORY / f"l{index}"
        directory.mkdir(parents=True, exist_ok=True)
        tiles: list[dict[str, Any]] = []
        for (column, row), source_relative in sorted(native_paths.items()):
            relative_path = f"{NATIVE_DIRECTORY}/l{index}/tile_{column:02d}_{row:02d}.jpg"
            target = ASSETS / relative_path
            if force or not target.is_file():
                with Image.open(ASSETS / source_relative) as image:
                    image.load()
                    resized = image.convert("RGB").resize(
                        (tile_size, tile_size), Image.Resampling.LANCZOS
                    )
                resized.save(target, format="JPEG", quality=JPEG_QUALITY, optimize=True)
                resized.close()
            tiles.append(tile_entry(column, row, relative_path))
        levels.append(level_entry(index, columns, rows, tile_size, tiles))

    native_entries = [
        tile_entry(column, row, relative_path)
        for (column, row), relative_path in sorted(native_paths.items())
    ]
    levels.append(level_entry(len(derived_sizes), columns, rows, native_size, native_entries))

    optional_levels = []
    for level_index, description in sorted(OPTIONAL_LEVELS.items()):
        # --exclude-optional writes the manifest a clone should see: the pack is
        # declared but not installed, whatever this machine happens to hold.
        dense = None if exclude_optional else discover_dense_level(level_index)
        if dense is not None:
            levels.append(dense)
        optional_levels.append(
            {
                "level": level_index,
                "installed": dense is not None,
                **description,
            }
        )

    updated = {
        "schema_version": SCHEMA_VERSION,
        "asset_id": manifest.get("asset_id"),
        "source_asset_id": manifest.get("source_asset_id"),
        "source_url": manifest.get("source_url"),
        "source_sha256": manifest.get("source_sha256"),
        "source_width": levels[-1]["width"],
        "source_height": levels[-1]["height"],
        "columns": columns,
        "rows": rows,
        "media_type": "image/jpeg",
        "attribution": manifest.get("attribution"),
        "license": manifest.get("license"),
        "license_url": manifest.get("license_url"),
        "usage": (
            "Near-surface globe texture pyramid. The browser picks one level per frame from "
            "the on-screen pixels-per-degree demand and requests local tiles only."
        ),
        "levels": levels,
        "optional_levels": optional_levels,
    }
    LOD_MANIFEST.write_text(json.dumps(updated, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    basemap = json.loads(BASEMAP_MANIFEST.read_text(encoding="utf-8"))
    digest, byte_count = sha256_file(LOD_MANIFEST)
    specification = basemap.setdefault("earth_texture_lod_manifest", {})
    specification["path"] = LOD_MANIFEST.name
    specification["bytes"] = byte_count
    specification["sha256"] = digest
    specification["usage"] = (
        "Hash-checked local texture pyramid; the globe requests only the visible tiles of the "
        "level that matches the current on-screen resolution."
    )
    BASEMAP_MANIFEST.write_text(json.dumps(basemap, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    return {
        "optional_levels": optional_levels,
        "levels": [
            {
                "level": level["level"],
                "grid": f"{level['columns']}x{level['rows']}",
                "tile": level["tile_width"],
                "pixels_per_degree": level["pixels_per_degree"],
                "bytes": sum(tile["bytes"] for tile in level["tiles"]),
            }
            for level in levels
        ],
        "manifest_sha256": digest,
        "manifest_bytes": byte_count,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="re-encode tiles that already exist")
    parser.add_argument(
        "--exclude-optional",
        action="store_true",
        help="write the manifest as shipped: optional levels declared but not installed",
    )
    parser.add_argument(
        "--assets-root",
        type=Path,
        help="operate on another map_app/assets tree instead of the repository one",
    )
    arguments = parser.parse_args()
    if arguments.assets_root:
        use_assets_root(arguments.assets_root.resolve())
    report = build(force=arguments.force, exclude_optional=arguments.exclude_optional)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
