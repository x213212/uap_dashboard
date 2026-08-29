from __future__ import annotations

import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest


MODULE_PATH = Path(__file__).resolve().parents[1] / "serve_map.py"
SPEC = importlib.util.spec_from_file_location("uap_serve_map", MODULE_PATH)
assert SPEC and SPEC.loader
serve_map = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = serve_map
SPEC.loader.exec_module(serve_map)


def feature(identifier: str, role: str) -> dict[str, object]:
    return {
        "type": "Feature",
        "id": identifier,
        "geometry": {"type": "Point", "coordinates": [120.0, 23.5]},
        "properties": {
            "observation_id": identifier,
            "record_role": role,
            "source_id": "fixture",
        },
    }


class ServeMapValidationTests(unittest.TestCase):
    def write_fixture(self, root: Path) -> dict[str, Path]:
        map_app = root / "map_app"
        assets = map_app / "assets"
        assets.mkdir(parents=True)
        for filename in ("index.html", "styles.css", "app.js"):
            (map_app / filename).write_text("fixture\n", encoding="utf-8")
        (map_app / "map_config.json").write_text(
            json.dumps(
                {
                    "schema_version": "uap.map_app_config.v1",
                    "default_basemap": "osm_standard",
                    "basemaps": {
                        "osm_standard": {
                            "tile_url_template": "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
                            "prefetch": False,
                            "offline_download": False,
                            "network_mode": "visible_viewport_only",
                        }
                    },
                }
            ),
            encoding="utf-8",
        )

        basemap = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]],
                    },
                    "properties": {},
                }
            ],
        }
        basemap_bytes = json.dumps(basemap).encode("utf-8")
        basemap_path = assets / "land.geojson"
        basemap_path.write_bytes(basemap_bytes)
        (assets / "basemap_manifest.json").write_text(
            json.dumps(
                {
                    "schema_version": "uap.basemap_asset.v1",
                    "asset_id": "fixture-land",
                    "path": "land.geojson",
                    "bytes": len(basemap_bytes),
                    "sha256": hashlib.sha256(basemap_bytes).hexdigest(),
                }
            ),
            encoding="utf-8",
        )

        release_root = root / "data" / "derived" / "releases" / "fixture-v1"
        map_root = release_root / "map_features"
        map_root.mkdir(parents=True)
        collections = {
            "sightings_current": {
                "type": "FeatureCollection",
                "features": [feature("sighting-1", "sighting")],
            },
            "controls_current": {
                "type": "FeatureCollection",
                "features": [feature("control-1", "astronomy_control")],
            },
        }
        artifacts: dict[str, dict[str, object]] = {}
        paths: dict[str, Path] = {"basemap": basemap_path}
        for key, collection in collections.items():
            payload = gzip.compress(
                json.dumps(collection, separators=(",", ":")).encode("utf-8"), mtime=0
            )
            path = map_root / f"{key}.geojson.gz"
            path.write_bytes(payload)
            relative_path = path.relative_to(release_root).as_posix()
            artifacts[key] = {
                "path": relative_path,
                "feature_count": 1,
                "compressed_bytes": len(payload),
                "compressed_sha256": hashlib.sha256(payload).hexdigest(),
            }
            paths[key] = path

        manifest = {
            "schema_version": "uap.map_release.v1",
            "release_id": "fixture-v1",
            "observation_version_count": 2,
            "observation_current_count": 2,
            "map_features": {"sightings_current": 1, "controls_current": 1},
            "map_artifacts": artifacts,
        }
        manifest_payload = json.dumps(manifest)
        (release_root / "manifest.json").write_text(manifest_payload, encoding="utf-8")
        current_path = root / "data" / "derived" / "current_release.json"
        current_path.parent.mkdir(parents=True, exist_ok=True)
        current_path.write_text(manifest_payload, encoding="utf-8")
        return paths

    def add_earth_texture_pyramid(self, root: Path) -> Path:
        """Attach a two-level texture pyramid to the fixture basemap manifest."""

        assets = root / "map_app" / "assets"
        texture_bytes = b"jpeg-overview"
        (assets / "earth.jpg").write_bytes(texture_bytes)
        levels = []
        for level, tile_size in enumerate((2, 4)):
            tiles = []
            for row in range(1):
                for column in range(2):
                    relative_path = f"earth_lod1/l{level}/tile_{column:02d}_{row:02d}.jpg"
                    tile_path = assets / relative_path
                    tile_path.parent.mkdir(parents=True, exist_ok=True)
                    payload = f"tile-{level}-{column}-{row}".encode("utf-8")
                    tile_path.write_bytes(payload)
                    tiles.append(
                        {
                            "column": column,
                            "row": row,
                            "path": relative_path,
                            "bytes": len(payload),
                            "sha256": hashlib.sha256(payload).hexdigest(),
                        }
                    )
            levels.append(
                {
                    "level": level,
                    "columns": 2,
                    "rows": 1,
                    "tile_width": tile_size,
                    "tile_height": tile_size,
                    "tiles": tiles,
                }
            )
        lod_manifest = {
            "schema_version": "uap.earth_texture_lod.v2",
            "asset_id": "fixture-pyramid",
            "columns": 2,
            "rows": 1,
            "source_width": 8,
            "source_height": 4,
            "levels": levels,
        }
        lod_path = assets / "earth_lod1_manifest.json"
        lod_bytes = json.dumps(lod_manifest).encode("utf-8")
        lod_path.write_bytes(lod_bytes)

        basemap_manifest_path = assets / "basemap_manifest.json"
        basemap_manifest = json.loads(basemap_manifest_path.read_text(encoding="utf-8"))
        basemap_manifest["earth_texture"] = {
            "asset_id": "fixture-earth",
            "path": "earth.jpg",
            "bytes": len(texture_bytes),
            "sha256": hashlib.sha256(texture_bytes).hexdigest(),
            "media_type": "image/jpeg",
            "width": 8,
            "height": 4,
        }
        basemap_manifest["earth_texture_lod_manifest"] = {
            "path": lod_path.name,
            "bytes": len(lod_bytes),
            "sha256": hashlib.sha256(lod_bytes).hexdigest(),
        }
        basemap_manifest_path.write_text(json.dumps(basemap_manifest), encoding="utf-8")
        return assets

    def test_validates_multi_level_earth_texture_pyramid(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self.write_fixture(root)
            self.add_earth_texture_pyramid(root)

            report = serve_map.validate_basemap(root)["earth_texture_lod"]
            self.assertEqual(report["schema_version"], "uap.earth_texture_lod.v2")
            self.assertEqual([level["level"] for level in report["levels"]], [0, 1])
            self.assertEqual(
                [level["pixels_per_degree"] for level in report["levels"]],
                [round(4 / 360, 4), round(8 / 360, 4)],
            )
            self.assertEqual(report["tile_count"], 4)

            # Every level is servable, otherwise the browser silently keeps the
            # blurry overview texture when it asks for a finer tile.
            paths = serve_map.earth_texture_lod_public_paths(root)
            self.assertEqual(len(paths), 4)
            self.assertIn("/map_app/assets/earth_lod1/l0/tile_00_00.jpg", paths)
            self.assertIn("/map_app/assets/earth_lod1/l1/tile_01_00.jpg", paths)

    def set_optional_levels(self, root: Path, optional: list[dict[str, object]]) -> Path:
        assets = root / "map_app" / "assets"
        lod_path = assets / "earth_lod1_manifest.json"
        manifest = json.loads(lod_path.read_text(encoding="utf-8"))
        manifest["optional_levels"] = optional
        payload = json.dumps(manifest).encode("utf-8")
        lod_path.write_bytes(payload)
        basemap_path = assets / "basemap_manifest.json"
        basemap = json.loads(basemap_path.read_text(encoding="utf-8"))
        basemap["earth_texture_lod_manifest"]["bytes"] = len(payload)
        basemap["earth_texture_lod_manifest"]["sha256"] = hashlib.sha256(payload).hexdigest()
        basemap_path.write_text(json.dumps(basemap), encoding="utf-8")
        return assets

    def test_accepts_an_optional_level_that_is_not_installed(self) -> None:
        # The sharpest pack is a separate download; declaring it while absent is
        # how the map can offer it instead of silently topping out.
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self.write_fixture(root)
            self.add_earth_texture_pyramid(root)
            self.set_optional_levels(
                root,
                [{"level": 9, "installed": False, "pack": "fixture_pack", "pixels_per_degree": 240}],
            )
            report = serve_map.validate_basemap(root)["earth_texture_lod"]
            self.assertEqual(report["optional_levels"][0]["installed"], False)
            self.assertEqual([level["level"] for level in report["levels"]], [0, 1])

    def test_rejects_an_optional_level_claiming_a_missing_install(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self.write_fixture(root)
            self.add_earth_texture_pyramid(root)
            self.set_optional_levels(
                root, [{"level": 9, "installed": True, "pack": "fixture_pack"}]
            )
            with self.assertRaises(serve_map.MapValidationError):
                serve_map.validate_basemap(root)

    def test_rejects_an_installed_level_not_marked_installed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self.write_fixture(root)
            self.add_earth_texture_pyramid(root)
            self.set_optional_levels(
                root, [{"level": 1, "installed": False, "pack": "fixture_pack"}]
            )
            with self.assertRaises(serve_map.MapValidationError):
                serve_map.validate_basemap(root)

    def test_rejects_tampered_pyramid_tile(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self.write_fixture(root)
            assets = self.add_earth_texture_pyramid(root)
            (assets / "earth_lod1" / "l1" / "tile_01_00.jpg").write_bytes(b"tampered")
            with self.assertRaises(serve_map.MapValidationError):
                serve_map.validate_basemap(root)

    def test_rejects_pyramid_levels_that_do_not_grow(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self.write_fixture(root)
            assets = self.add_earth_texture_pyramid(root)
            lod_path = assets / "earth_lod1_manifest.json"
            manifest = json.loads(lod_path.read_text(encoding="utf-8"))
            manifest["levels"][1]["tile_width"] = 2
            manifest["levels"][1]["tile_height"] = 2
            payload = json.dumps(manifest).encode("utf-8")
            lod_path.write_bytes(payload)
            basemap_path = assets / "basemap_manifest.json"
            basemap = json.loads(basemap_path.read_text(encoding="utf-8"))
            basemap["earth_texture_lod_manifest"]["bytes"] = len(payload)
            basemap["earth_texture_lod_manifest"]["sha256"] = hashlib.sha256(payload).hexdigest()
            basemap_path.write_text(json.dumps(basemap), encoding="utf-8")
            with self.assertRaises(serve_map.MapValidationError):
                serve_map.validate_basemap(root)

    def test_validates_static_assets_basemap_and_release_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self.write_fixture(root)
            result = serve_map.validate_map(root)
            self.assertTrue(result["ok"])
            self.assertEqual(result["basemap"]["features"], 1)
            self.assertEqual(result["release"]["release_id"], "fixture-v1")
            self.assertEqual(
                result["release"]["layers"]["sightings_current"]["feature_count"], 1
            )

    def test_rejects_tampered_release_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paths = self.write_fixture(root)
            with paths["sightings_current"].open("ab") as handle:
                handle.write(b"tampered")
            with self.assertRaisesRegex(serve_map.MapValidationError, "SHA-256 mismatch"):
                serve_map.validate_map(root)

    def test_rejects_sighting_in_control_layer(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paths = self.write_fixture(root)
            bad_collection = {
                "type": "FeatureCollection",
                "features": [feature("control-1", "sighting")],
            }
            payload = gzip.compress(json.dumps(bad_collection).encode("utf-8"), mtime=0)
            paths["controls_current"].write_bytes(payload)

            release_root = root / "data" / "derived" / "releases" / "fixture-v1"
            manifest_path = release_root / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            artifact = manifest["map_artifacts"]["controls_current"]
            artifact["compressed_bytes"] = len(payload)
            artifact["compressed_sha256"] = hashlib.sha256(payload).hexdigest()
            payload_text = json.dumps(manifest)
            manifest_path.write_text(payload_text, encoding="utf-8")
            (root / "data" / "derived" / "current_release.json").write_text(
                payload_text, encoding="utf-8"
            )

            with self.assertRaisesRegex(serve_map.MapValidationError, "sighting leaked"):
                serve_map.validate_map(root)

    def test_network_handler_exposes_only_map_products(self) -> None:
        handler = object.__new__(serve_map.MapRequestHandler)
        handler.release_id = "fixture-v1"
        allowed = handler.allowed_paths()
        self.assertIn("/map_app/", allowed)
        self.assertIn("/map_app/map_config.json", allowed)
        self.assertIn(
            "/map_app/assets/nasa_blue_marble_200406_5400x2700.jpg",
            allowed,
        )
        self.assertIn("/map_app/assets/earth_lod1_manifest.json", allowed)
        self.assertIn(
            "/data/derived/releases/fixture-v1/map_features/sightings_current.geojson.gz",
            allowed,
        )
        self.assertNotIn("/data/raw/private.gz", allowed)
        self.assertNotIn("/data/receipts/source/snapshot.json", allowed)
        self.assertNotIn("/youtube_transcripts/video.txt", allowed)

    def collect_headers(self, path: str, status: int) -> dict[str, str]:
        """Run the handler's header pass for one request without a socket."""

        handler = object.__new__(serve_map.MapRequestHandler)
        handler.path = path
        handler.response_code = status
        headers: list[tuple[str, str]] = []
        handler.send_header = lambda key, value: headers.append((key, value))
        serve_map.SimpleHTTPRequestHandler.end_headers = lambda self: None
        try:
            serve_map.MapRequestHandler.end_headers(handler)
        finally:
            del serve_map.SimpleHTTPRequestHandler.end_headers
        return {key: value for key, value in headers}

    def test_failed_asset_response_is_never_cacheable(self) -> None:
        # A cached 404 under an immutable policy is replayed for a year, even
        # across a hard reload, because assets are fetched with force-cache.
        failed = self.collect_headers("/map_app/assets/missing.geojson?sha=abc", 404)
        self.assertEqual(failed["Cache-Control"], "no-store")
        served = self.collect_headers("/map_app/assets/missing.geojson?sha=abc", 200)
        self.assertEqual(served["Cache-Control"], "public, max-age=31536000, immutable")

    def test_failed_gzip_artifact_is_not_labelled_gzip(self) -> None:
        failed = self.collect_headers(
            "/data/derived/releases/fixture-v1/map_features/sightings_current.geojson.gz",
            404,
        )
        self.assertNotIn("Content-Encoding", failed)
        served = self.collect_headers(
            "/data/derived/releases/fixture-v1/map_features/sightings_current.geojson.gz",
            200,
        )
        self.assertEqual(served["Content-Encoding"], "gzip")

    def test_public_manifest_omits_internal_paths_and_receipts(self) -> None:
        public = serve_map.public_release_manifest(
            {
                "schema_version": "uap.map_release.v1",
                "release_id": "fixture-v1",
                "built_at": "2026-08-29T00:00:00Z",
                "map_features": {"sightings_current": 1},
                "map_artifacts": {},
                "input_root": "/private/workspace/data",
                "input_receipts": [{"receipt": "receipts/private.json"}],
                "parquet_paths": ["internal/partition.parquet"],
            }
        )
        self.assertEqual(public["release_id"], "fixture-v1")
        self.assertNotIn("input_root", public)
        self.assertNotIn("input_receipts", public)
        self.assertNotIn("parquet_paths", public)


if __name__ == "__main__":
    unittest.main()
