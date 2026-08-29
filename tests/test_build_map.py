from __future__ import annotations

from datetime import UTC, datetime
import gzip
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

import duckdb


MODULE_PATH = Path(__file__).resolve().parents[1] / "build_map.py"
SPEC = importlib.util.spec_from_file_location("uap_map", MODULE_PATH)
assert SPEC and SPEC.loader
build_map = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = build_map
SPEC.loader.exec_module(build_map)


def canonical_record(*, source_record_id: str, latitude: float, longitude: float) -> dict[str, object]:
    return {
        "schema_version": "uap.global_event.v1",
        "source_id": "fixture_source",
        "source_record_id": source_record_id,
        "record_type": "sighting",
        "observed_at_start": "2020-01-02",
        "observed_at_end": None,
        "time_precision": "day",
        "location_name": "Fixture town",
        "country_code": "ZZ",
        "latitude": latitude,
        "longitude": longitude,
        "coordinate_precision": "city",
        "venue": "land",
        "title": "Fixture sighting",
        "summary": "A test-only record.",
        "original_source_url": "https://example.test/record",
        "source_portal_url": "https://example.test/",
        "status": "unresolved",
        "explanation": None,
        "media_url": None,
        "source_role": "reported_sightings",
    }


class MapBuildTests(unittest.TestCase):
    def write_snapshot(
        self,
        input_root: Path,
        *,
        snapshot_id: str,
        collected_at: datetime,
        record: dict[str, object],
    ) -> None:
        canonical_path = (
            input_root / "canonical" / "fixture_source" / f"{snapshot_id}.jsonl.gz"
        )
        canonical_path.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(canonical_path, "wt", encoding="utf-8") as handle:
            handle.write(json.dumps(record) + "\n")
        receipt_path = input_root / "receipts" / "fixture_source" / f"{snapshot_id}.json"
        receipt_path.parent.mkdir(parents=True, exist_ok=True)
        receipt_path.write_text(
            json.dumps(
                {
                    "schema_version": "uap.collection_receipt.v1",
                    "source_id": "fixture_source",
                    "snapshot_id": snapshot_id,
                    "collected_at": collected_at.isoformat(),
                    "raw_files": [{"raw_sha256": f"raw-{snapshot_id}"}],
                    "canonical": {
                        "path": canonical_path.relative_to(input_root).as_posix(),
                        "records": 1,
                    },
                }
            ),
            encoding="utf-8",
        )

    def test_latest_source_observation_becomes_one_map_feature(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            input_root = root / "input"
            self.write_snapshot(
                input_root,
                snapshot_id="snapshot-a",
                collected_at=datetime(2026, 1, 1, tzinfo=UTC),
                record=canonical_record(source_record_id="case-1", latitude=1.0, longitude=2.0),
            )
            self.write_snapshot(
                input_root,
                snapshot_id="snapshot-b",
                collected_at=datetime(2026, 1, 2, tzinfo=UTC),
                record=canonical_record(source_record_id="case-1", latitude=3.0, longitude=4.0),
            )
            derived_root = root / "derived"
            warehouse_path = root / "warehouse" / "uap.duckdb"
            manifest = build_map.build_release(
                input_root=input_root,
                derived_root=derived_root,
                warehouse_path=warehouse_path,
                release_id="fixture-v1",
            )
            self.assertEqual(manifest["observation_version_count"], 2)
            self.assertEqual(manifest["observation_current_count"], 1)
            self.assertEqual(manifest["map_features"]["sightings_current"], 1)
            sighting_artifact = manifest["map_artifacts"]["sightings_current"]
            self.assertEqual(sighting_artifact["feature_count"], 1)
            self.assertEqual(
                sighting_artifact["path"], "map_features/sightings_current.geojson.gz"
            )
            self.assertEqual(len(sighting_artifact["compressed_sha256"]), 64)
            self.assertGreater(sighting_artifact["compressed_bytes"], 0)
            self.assertTrue((derived_root / "releases" / "fixture-v1" / "manifest.json").is_file())

            connection = duckdb.connect(str(warehouse_path), read_only=True)
            self.assertEqual(
                connection.execute("SELECT count(*) FROM observation_versions").fetchone()[0], 2
            )
            current = connection.execute(
                "SELECT snapshot_id, latitude, longitude FROM observations_current"
            ).fetchone()
            self.assertEqual(current, ("snapshot-b", 3.0, 4.0))
            connection.close()

            with gzip.open(
                derived_root
                / "releases"
                / "fixture-v1"
                / "map_features"
                / "sightings_current.geojson.gz",
                "rt",
                encoding="utf-8",
            ) as handle:
                feature_collection = json.load(handle)
            self.assertEqual(feature_collection["features"][0]["geometry"]["coordinates"], [4.0, 3.0])


if __name__ == "__main__":
    unittest.main()
