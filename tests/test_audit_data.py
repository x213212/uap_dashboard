from __future__ import annotations

import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest


MODULE_PATH = Path(__file__).resolve().parents[1] / "audit_data.py"
SPEC = importlib.util.spec_from_file_location("uap_audit_data", MODULE_PATH)
assert SPEC and SPEC.loader
audit_data = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = audit_data
SPEC.loader.exec_module(audit_data)


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


def write_horizons_receipt(root: Path, snapshot: str) -> None:
    records = [
        {
            "source_id": "nasa_horizons_9_bodies",
            "source_record_id": f"{body_id}-2026-08-13",
            "body_id": body_id,
            "title": name,
            "observed_at_start": "2026-08-13",
        }
        for body_id, name in audit_data.PLANETS
    ]
    canonical_payload = (
        "".join(json.dumps(record, sort_keys=True) + "\n" for record in records).encode("utf-8")
    )
    raw = gzip_artifact(root, f"raw/nasa_horizons_9_bodies/{snapshot}/source.raw.gz", b"raw", raw=True)
    canonical = gzip_artifact(
        root,
        f"canonical/nasa_horizons_9_bodies/{snapshot}/events.jsonl.gz",
        canonical_payload,
        raw=False,
    )
    canonical["records"] = len(records)
    receipt = {
        "schema_version": "uap.collection_receipt.v1",
        "source_id": "nasa_horizons_9_bodies",
        "snapshot_id": snapshot,
        "raw_files": [raw],
        "canonical": canonical,
    }
    target = root / "receipts" / "nasa_horizons_9_bodies" / f"{snapshot}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(receipt), encoding="utf-8")


class AuditDataTests(unittest.TestCase):
    def test_reports_complete_nine_body_control_and_duplicate_snapshot_warning(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_horizons_receipt(root, "snapshot-a")
            write_horizons_receipt(root, "snapshot-b")
            report = audit_data.audit(root)

        self.assertTrue(report["ok"])
        self.assertFalse(report["network_contacted"])
        self.assertEqual(report["error_count"], 0)
        self.assertEqual(report["source_canonical_record_counts"]["nasa_horizons_9_bodies"], 18)
        self.assertEqual(report["source_unique_record_counts"]["nasa_horizons_9_bodies"], 9)
        horizons = report["horizons_nine_body_control"]
        assert horizons
        self.assertEqual(horizons["complete_dates"], ["2026-08-13"])
        self.assertEqual(horizons["expected_bodies"], [name for _id, name in audit_data.PLANETS])
        self.assertEqual(horizons["incomplete_or_invalid_snapshots"], [])
        self.assertIn("2026-08-13", horizons["duplicate_date_snapshots"])

    def test_hash_mutation_is_an_error_not_a_silent_count(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_horizons_receipt(root, "snapshot-a")
            raw = root / "raw/nasa_horizons_9_bodies/snapshot-a/source.raw.gz"
            raw.write_bytes(b"not the hashed gzip")
            report = audit_data.audit(root)

        self.assertFalse(report["ok"])
        self.assertEqual(report["error_count"], 1)
        self.assertIn("gzip byte count mismatch", report["errors"][0]["error"])


if __name__ == "__main__":
    unittest.main()
