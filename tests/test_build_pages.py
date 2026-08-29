from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest


MODULE_PATH = Path(__file__).resolve().parents[1] / "build_pages.py"
SPEC = importlib.util.spec_from_file_location("uap_build_pages", MODULE_PATH)
assert SPEC and SPEC.loader
build_pages = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = build_pages
SPEC.loader.exec_module(build_pages)


class PublicManifestTests(unittest.TestCase):
    """A static host has no allow-list, so the filtering happens at build time."""

    MANIFEST = {
        "schema_version": "uap.map_release.v1",
        "release_id": "fixture-v1",
        "built_at": "2026-08-30T00:00:00Z",
        "map_features": {"sightings_current": 1},
        "map_artifacts": {"sightings_current": {"path": "map_features/x.geojson.gz"}},
        "input_root": "/srv/uap_lab/data",
        "input_receipts": [{"receipt": "receipts/uapdrop/snapshot.json"}],
        "warehouse": "/srv/uap_lab/data/warehouse",
    }

    def test_internal_paths_and_receipts_are_dropped(self) -> None:
        public = build_pages.public_manifest(self.MANIFEST)
        self.assertNotIn("input_root", public)
        self.assertNotIn("input_receipts", public)
        self.assertNotIn("warehouse", public)

    def test_browser_facing_fields_survive(self) -> None:
        public = build_pages.public_manifest(self.MANIFEST)
        self.assertEqual(public["release_id"], "fixture-v1")
        self.assertIn("map_artifacts", public)
        self.assertIn("map_features", public)

    def test_no_unexpected_field_is_published(self) -> None:
        public = build_pages.public_manifest({**self.MANIFEST, "operator_notes": "internal"})
        self.assertNotIn("operator_notes", public)
        self.assertTrue(set(public) <= set(build_pages.PUBLIC_RELEASE_FIELDS))


class OptionalPackExclusionTests(unittest.TestCase):
    def test_the_installed_pack_is_excluded_from_a_published_build(self) -> None:
        # The 500 m pack is installed on demand; publishing it would ship ~330 MB
        # that the map is designed to work without.
        self.assertIn("earth_lod1/l3", build_pages.EXCLUDED_ASSET_DIRECTORIES)


class PublicationAuditTests(unittest.TestCase):
    """The audit is the gate: an unlicensed build must not survive it."""

    def scaffold(self, root: Path, source_id: str) -> Path:
        import gzip

        output = root / "dist"
        (output / "map_app" / "assets").mkdir(parents=True)
        (output / "map_app" / "index.html").write_text(
            "UAPDrop CC BY 4.0 creativecommons.org/licenses/by/4.0 NASA Natural Earth "
            "OpenStreetMap openstreetmap.org/copyright",
            encoding="utf-8",
        )
        for name in ("styles.css", "app.js"):
            (output / "map_app" / name).write_text("fixture", encoding="utf-8")
        (output / "map_app" / "map_config.json").write_text(
            json.dumps({"basemaps": {"osm": {"tile_url_template": "https://tile.openstreetmap.org/{z}/{x}/{y}.png"}}}),
            encoding="utf-8",
        )
        layer = output / "data" / "derived" / "releases" / "fixture-v1" / "map_features"
        layer.mkdir(parents=True)
        payload = json.dumps(
            {
                "type": "FeatureCollection",
                "features": [{"type": "Feature", "properties": {"source_id": source_id}}],
            }
        ).encode("utf-8")
        (layer / "sightings_current.geojson.gz").write_bytes(gzip.compress(payload, mtime=0))
        (output / "NOTICE.md").write_text("notice", encoding="utf-8")
        return output

    def test_a_cleared_source_passes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = self.scaffold(Path(temp_dir), "uapdrop")
            audit = build_pages.audit_publication(output)
            self.assertTrue(audit["compliant"], audit["failures"])
            self.assertIn("UAPDrop", audit["attribution_verified"])

    def test_a_rejected_source_fails_the_build(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = self.scaffold(Path(temp_dir), "ufosint_public_sqlite")
            audit = build_pages.audit_publication(output)
            self.assertFalse(audit["compliant"])
            self.assertTrue(any("not cleared" in failure for failure in audit["failures"]))

    def test_an_unreviewed_source_fails_the_build(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = self.scaffold(Path(temp_dir), "some_unreviewed_feed")
            audit = build_pages.audit_publication(output)
            self.assertFalse(audit["compliant"])
            self.assertTrue(any("no rights review" in failure for failure in audit["failures"]))

    def test_a_stray_file_fails_the_build(self) -> None:
        # This is not hypothetical: the first audit run caught a server log that
        # had been written into map_app/ and would have shipped request records.
        with tempfile.TemporaryDirectory() as temp_dir:
            output = self.scaffold(Path(temp_dir), "uapdrop")
            (output / "map_app" / "serve_map.log").write_text("127.0.0.1 - -", encoding="utf-8")
            audit = build_pages.audit_publication(output)
            self.assertFalse(audit["compliant"])
            self.assertTrue(any("no licence rule" in failure for failure in audit["failures"]))

    def test_missing_attribution_fails_the_build(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = self.scaffold(Path(temp_dir), "uapdrop")
            (output / "map_app" / "index.html").write_text("no credits here", encoding="utf-8")
            audit = build_pages.audit_publication(output)
            self.assertFalse(audit["compliant"])
            self.assertTrue(
                any("attribution missing" in failure for failure in audit["failures"])
            )


if __name__ == "__main__":
    unittest.main()
