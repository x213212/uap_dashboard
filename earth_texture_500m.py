#!/usr/bin/env python3
"""Install the optional NASA Blue Marble 500 m texture pack for the 3D globe.

The 3D globe was capped at the 21600x10800 asset (60 px/degree), so any zoom
past ~5x magnified those pixels.  The 500 m Blue Marble ships as eight
21600x21600 quadrants covering 90 degrees each, i.e. 86400x43200 or
240 px/degree, which covers the application's maximum globe zoom.

The pack is optional because it costs about 400 MB of download and 330 MB on
disk: the map ships with the 60 px/degree levels and only reaches 240 px/degree
once this pack is installed.  Run with --install to fetch and build it, or
--uninstall to drop back to the shipped levels.

Each quadrant is cut into 900x900 tiles on a 96x48 grid (3.75 degrees per
tile).  Tiles stay small so the browser only resides the few that are visible
(4.3 MB of texture memory each); cutting never resamples because 21600 divides
exactly into 24 tiles.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from multiprocessing import Pool
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any
from urllib.request import Request, urlopen

from PIL import Image

Image.MAX_IMAGE_PIXELS = None

ROOT = Path(__file__).resolve().parent
CACHE = ROOT / "data" / "cache" / "bmng_500m"
ASSETS = ROOT / "map_app" / "assets"
LEVEL_DIRECTORY = ASSETS / "earth_lod1" / "l3"
TILE_SIZE = 900
TILES_PER_QUADRANT = 24
COLUMNS = 96
ROWS = 48
JPEG_QUALITY = 92
SOURCE_BASE = (
    "https://assets.science.nasa.gov/content/dam/science/esd/eo/images/bmng/"
    "bmng-topography-bathymetry/june"
)
# Quadrant letter -> grid origin (column, row) in the 48x24 level-3 grid.
QUADRANTS = {
    "A1": (0, 0),
    "B1": (24, 0),
    "C1": (48, 0),
    "D1": (72, 0),
    "A2": (0, 24),
    "B2": (24, 24),
    "C2": (48, 24),
    "D2": (72, 24),
}


DOWNLOAD_CHUNK = 4 * 1024 * 1024


def download_quadrant(quadrant: str) -> Path:
    """Stream one 90-degree quadrant to the cache, resuming nothing on failure."""

    path = source_path(quadrant)
    if path.is_file() and path.stat().st_size > 0:
        return path
    url = f"{SOURCE_BASE}/{path.name}"
    partial = path.with_suffix(".jpg.part")
    CACHE.mkdir(parents=True, exist_ok=True)
    request = Request(url, headers={"User-Agent": "uap-lab earth texture installer"})
    with urlopen(request, timeout=120) as response, partial.open("wb") as handle:
        while True:
            chunk = response.read(DOWNLOAD_CHUNK)
            if not chunk:
                break
            handle.write(chunk)
    partial.replace(path)
    return path


def rebuild_manifest() -> None:
    """Re-emit the LOD manifest so the new level is declared and hash-checked."""

    subprocess.run([sys.executable, str(ROOT / "earth_texture_lod.py")], check=True)


def pack_status() -> dict[str, Any]:
    tiles = sorted(LEVEL_DIRECTORY.glob("tile_*.jpg")) if LEVEL_DIRECTORY.is_dir() else []
    sources = [q for q in QUADRANTS if source_path(q).is_file()]
    installed = len(tiles) == COLUMNS * ROWS
    return {
        "pack": "nasa_blue_marble_500m",
        "pixels_per_degree": (COLUMNS * TILE_SIZE) / 360,
        "installed": installed,
        "tiles_present": len(tiles),
        "tiles_expected": COLUMNS * ROWS,
        "tile_bytes": sum(path.stat().st_size for path in tiles),
        "source_quadrants_cached": len(sources),
        "source_bytes": sum(source_path(q).stat().st_size for q in sources),
        "install_command": "python3 earth_texture_500m.py --install",
        "uninstall_command": "python3 earth_texture_500m.py --uninstall",
    }


def sha256_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    byte_count = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
            byte_count += len(chunk)
    return digest.hexdigest(), byte_count


def source_path(quadrant: str) -> Path:
    return CACHE / f"world.topo.bathy.200406.3x21600x21600.{quadrant}.jpg"


def cut_quadrant(job: tuple[str, bool]) -> dict[str, Any]:
    quadrant, force = job
    origin_column, origin_row = QUADRANTS[quadrant]
    path = source_path(quadrant)
    pending = []
    for row in range(TILES_PER_QUADRANT):
        for column in range(TILES_PER_QUADRANT):
            target = LEVEL_DIRECTORY / (
                f"tile_{origin_column + column:02d}_{origin_row + row:02d}.jpg"
            )
            if force or not target.is_file():
                pending.append((column, row, target))
    if not pending:
        return {"quadrant": quadrant, "written": 0}

    with Image.open(path) as image:
        image.draft(None, None)
        image.load()
        if image.size != (
            TILE_SIZE * TILES_PER_QUADRANT,
            TILE_SIZE * TILES_PER_QUADRANT,
        ):
            raise SystemExit(f"{quadrant}: unexpected source size {image.size}")
        rgb = image.convert("RGB")
    for column, row, target in pending:
        box = (
            column * TILE_SIZE,
            row * TILE_SIZE,
            (column + 1) * TILE_SIZE,
            (row + 1) * TILE_SIZE,
        )
        tile = rgb.crop(box)
        tile.save(target, format="JPEG", quality=JPEG_QUALITY, optimize=True)
        tile.close()
    rgb.close()
    return {"quadrant": quadrant, "written": len(pending)}


def verify_sources() -> list[dict[str, Any]]:
    receipts = []
    for quadrant in QUADRANTS:
        path = source_path(quadrant)
        if not path.is_file():
            raise SystemExit(f"missing 500 m source quadrant: {path}")
        digest, byte_count = sha256_file(path)
        receipts.append(
            {
                "quadrant": quadrant,
                "path": str(path.relative_to(ROOT)),
                "source_url": f"{SOURCE_BASE}/{path.name}",
                "bytes": byte_count,
                "sha256": digest,
            }
        )
    return receipts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="re-cut tiles that exist")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument(
        "--install",
        action="store_true",
        help="download the 500 m quadrants if missing, cut them, and rebuild the manifest",
    )
    parser.add_argument(
        "--uninstall",
        action="store_true",
        help="remove the installed level-3 tiles and rebuild the manifest without them",
    )
    parser.add_argument("--status", action="store_true", help="report pack state and exit")
    parser.add_argument(
        "--keep-sources",
        action="store_true",
        help="with --uninstall, keep the downloaded quadrants in the cache",
    )
    arguments = parser.parse_args()

    if arguments.status:
        print(json.dumps(pack_status(), ensure_ascii=False, indent=2))
        return 0

    if arguments.uninstall:
        if LEVEL_DIRECTORY.is_dir():
            shutil.rmtree(LEVEL_DIRECTORY)
        if not arguments.keep_sources:
            for quadrant in QUADRANTS:
                source_path(quadrant).unlink(missing_ok=True)
        rebuild_manifest()
        print(json.dumps({"uninstalled": True, **pack_status()}, ensure_ascii=False, indent=2))
        return 0

    if arguments.install:
        for quadrant in QUADRANTS:
            path = download_quadrant(quadrant)
            print(json.dumps({"quadrant": quadrant, "bytes": path.stat().st_size}), flush=True)

    LEVEL_DIRECTORY.mkdir(parents=True, exist_ok=True)
    receipts = verify_sources()
    (CACHE / "source_receipts.json").write_text(
        json.dumps(
            {
                "asset_id": "nasa-blue-marble-next-generation-topography-bathymetry-june-2004-500m",
                "source_page": (
                    "https://science.nasa.gov/earth/earth-observatory/blue-marble-next-generation/"
                    "base-topography-bathymetry/"
                ),
                "width": TILE_SIZE * COLUMNS,
                "height": TILE_SIZE * ROWS,
                "quadrants": receipts,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    jobs = [(quadrant, arguments.force) for quadrant in QUADRANTS]
    with Pool(processes=max(1, arguments.workers)) as pool:
        for result in pool.imap_unordered(cut_quadrant, jobs):
            print(json.dumps(result), flush=True)

    written = sorted(LEVEL_DIRECTORY.glob("tile_*.jpg"))
    if len(written) != COLUMNS * ROWS:
        raise SystemExit(f"level 3 grid is incomplete: {len(written)} of {COLUMNS * ROWS}")
    if arguments.install:
        rebuild_manifest()
    print(json.dumps(pack_status(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
