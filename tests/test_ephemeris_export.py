from __future__ import annotations

from datetime import date
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest


LAB_ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, LAB_ROOT / filename)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


collect = load_module("collect", "collect.py")
audit_data = load_module("audit_data", "audit_data.py")
ephemeris_export = load_module("uap_ephemeris_export", "ephemeris_export.py")


def gzip_artifact(root: Path, relative: str, payload: bytes, *, raw: bool) -> dict[str, object]:
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    compressed = gzip.compress(payload, compresslevel=9, mtime=0)
    target.write_bytes(compressed)
    result: dict[str, object] = {
        "path": relative,
        "gzip_bytes": len(compressed),
        "gzip_sha256": hashlib.sha256(compressed).hexdigest(),
    }
    if raw:
        result.update({"raw_bytes": len(payload), "raw_sha256": hashlib.sha256(payload).hexdigest()})
    else:
        result.update(
            {
                "uncompressed_bytes": len(payload),
                "uncompressed_sha256": hashlib.sha256(payload).hexdigest(),
            }
        )
    return result


def horizons_payload(body_id: str, body_name: str) -> bytes:
    result = f"""Target body name: {body_name} ({body_id})                   {{source: DE441}}
Center body name: Sun (10)                        {{source: DE441}}
Center-site name: BODYCENTRIC
$$SOE
 2026-Aug-13 00:00     04 25 42.18 +24 08 26.2  04 35 18.51 +03 19 26.3        n.a.       n.a.   -5.725   0.709  0.30811269403859  -1.5363445
 2026-Aug-14 00:00     04 52 46.95 +25 42 27.3  05 00 41.32 +03 13 59.2        n.a.       n.a.   -5.733   0.705  0.30754409308547  -0.4299777
$$EOE
"""
    return json.dumps(
        {"signature": {"source": "NASA/JPL Horizons API", "version": "1.2"}, "result": result}
    ).encode("utf-8")


def write_horizons_fixture(root: Path, snapshot_id: str) -> Path:
    start = date(2026, 8, 13)
    raw_files: list[dict[str, object]] = []
    for body_id, body_name in collect.PLANETS:
        raw = gzip_artifact(
            root,
            f"raw/nasa_horizons_9_bodies/{snapshot_id}/{body_id}.raw.json.gz",
            horizons_payload(body_id, body_name),
            raw=True,
        )
        raw["request_url"] = collect.horizons_url(body_id, start)
        raw_files.append(raw)
    canonical = gzip_artifact(
        root,
        f"canonical/nasa_horizons_9_bodies/{snapshot_id}/events.jsonl.gz",
        b"",
        raw=False,
    )
    canonical["records"] = 0
    receipt = {
        "schema_version": "uap.collection_receipt.v1",
        "source_id": "nasa_horizons_9_bodies",
        "snapshot_id": snapshot_id,
        "raw_files": raw_files,
        "canonical": canonical,
    }
    receipt_path = root / "receipts" / "nasa_horizons_9_bodies" / f"{snapshot_id}.json"
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    registry = {
        "schema_version": "uap.source_registry.v1",
        "sources": [
            {
                "id": "nasa_horizons_9_bodies",
                "name": "Horizons",
                "access": "OPEN_BATCH",
                "kind": "nasa_horizons_planets",
                "url": "https://ssd.jpl.nasa.gov/api/horizons.api",
                "portal_url": "https://ssd.jpl.nasa.gov/horizons/",
                "role": "astronomy_control",
                "expected_bytes_per_run": 100000,
                "max_response_bytes": 1048576,
                "requests_per_run": 9,
            }
        ],
    }
    registry_path = root / "sources.json"
    registry_path.write_text(json.dumps(registry), encoding="utf-8")
    return registry_path


class EphemerisExportTests(unittest.TestCase):
    def test_export_is_offline_verified_complete_and_non_overwriting(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            snapshot_id = "snapshot-a"
            registry_path = write_horizons_fixture(root, snapshot_id)
            output_root = root / "derived"

            dry_run = ephemeris_export.build_export(
                input_root=root,
                registry_path=registry_path,
                output_root=output_root,
                snapshot_id=snapshot_id,
                dry_run=True,
            )
            self.assertFalse(dry_run["network_contacted"])
            self.assertTrue(dry_run["raw_receipt_audited"])
            self.assertEqual(dry_run["record_count"], 9)
            self.assertFalse(Path(dry_run["output_records_path"]).exists())

            result = ephemeris_export.build_export(
                input_root=root,
                registry_path=registry_path,
                output_root=output_root,
                snapshot_id=snapshot_id,
                dry_run=False,
            )
            records_path = Path(result["output_records_path"])
            records = [json.loads(line) for line in gzip.decompress(records_path.read_bytes()).splitlines()]
            self.assertEqual([row["body_id"] for row in records], [body_id for body_id, _ in collect.PLANETS])
            self.assertTrue(all(row["altitude_deg"] is None for row in records))
            self.assertTrue(all(row["observer_mode"] == collect.HORIZONS_OBSERVER_MODE for row in records))
            with self.assertRaises(ephemeris_export.EphemerisExportError):
                ephemeris_export.build_export(
                    input_root=root,
                    registry_path=registry_path,
                    output_root=output_root,
                    snapshot_id=snapshot_id,
                    dry_run=False,
                )


if __name__ == "__main__":
    unittest.main()
