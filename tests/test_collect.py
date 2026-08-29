from __future__ import annotations

from contextlib import redirect_stdout
from datetime import date
import io
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


MODULE_PATH = Path(__file__).resolve().parents[1] / "collect.py"
SPEC = importlib.util.spec_from_file_location("uap_collect", MODULE_PATH)
assert SPEC and SPEC.loader
collect = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = collect
SPEC.loader.exec_module(collect)


HORIZONS_SAMPLE_RESULT = """Target body name: Mercury (199)                   {source: DE441}
Center body name: Sun (10)                        {source: DE441}
Center-site name: BODYCENTRIC
$$SOE
 2026-Aug-13 00:00     04 25 42.18 +24 08 26.2  04 35 18.51 +03 19 26.3        n.a.       n.a.   -5.725   0.709  0.30811269403859  -1.5363445
 2026-Aug-14 00:00     04 52 46.95 +25 42 27.3  05 00 41.32 +03 13 59.2        n.a.       n.a.   -5.733   0.705  0.30754409308547  -0.4299777
$$EOE
"""


def horizons_sample_payload(*, signature_source: str = "NASA/JPL Horizons API") -> bytes:
    return json.dumps(
        {
            "signature": {"source": signature_source, "version": "1.2"},
            "result": HORIZONS_SAMPLE_RESULT,
        }
    ).encode("utf-8")


class GlobalUapCollectorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.uapdrop = collect.Source(
            source_id="uapdrop",
            name="UAPDrop",
            access="OPEN_BATCH",
            kind="uapdrop_csv",
            url="https://example.test/uapdrop.csv",
            portal_url="https://example.test/",
            role="reported_sightings",
        )

    def test_uapdrop_normalization_preserves_upstream_identity(self) -> None:
        payload = (
            "source_key,external_id,title,summary,location_name,country_code,latitude,longitude,observed_at,coordinate_precision,source_url\n"
            "hatch,H-1,Example,Details,Somewhere,AR,-42.9,-71.8,2020-01-02,city,https://upstream.example/case\n"
        ).encode()
        records = collect.normalize_uapdrop(self.uapdrop, payload)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["source_record_id"], "H-1")
        self.assertEqual(records[0]["upstream_source_key"], "hatch")
        self.assertEqual(records[0]["country_code"], "AR")
        self.assertEqual(records[0]["latitude"], -42.9)
        self.assertEqual(records[0]["original_source_url"], "https://upstream.example/case")

    def test_observatory_normalization_does_not_invent_coordinates(self) -> None:
        source = collect.Source(
            source_id="uap_observatory",
            name="UAP Observatory",
            access="OPEN_BATCH",
            kind="uap_observatory_csv",
            url="https://example.test/incidents.csv",
            portal_url=None,
            role="curated_incidents",
        )
        payload = (
            "id,title,status,credibility_tier,date_start,date_end,location,related_entity_ids,source_ids,notes\n"
            "INC-1,Case,draft,Tier A,1981-01-08,1981-02-17,France,ORG-1,SRC-1,Note\n"
        ).encode()
        record = collect.normalize_uap_observatory(source, payload)[0]
        self.assertIsNone(record["latitude"])
        self.assertEqual(record["observed_at_end"], "1981-02-17")
        self.assertEqual(record["upstream_source_ids"], "SRC-1")

    def test_nasa_fireball_coordinates_are_signed(self) -> None:
        source = collect.Source(
            source_id="nasa_fireball",
            name="NASA",
            access="OPEN_BATCH",
            kind="nasa_fireball_json",
            url="https://example.test/fireballs",
            portal_url=None,
            role="false_positive_control",
        )
        payload = b'{"fields":["date","lat","lat-dir","lon","lon-dir","energy"],"data":[["2020-01-01 00:00:00","8.0","S","52.5","W","2.3"]]}'
        record = collect.normalize_nasa_fireball(source, payload)[0]
        self.assertEqual(record["latitude"], -8.0)
        self.assertEqual(record["longitude"], -52.5)
        self.assertEqual(record["record_type"], "astronomy_control_fireball")

    def test_horizons_url_includes_body_and_day(self) -> None:
        url = collect.horizons_url("499", date(2026, 8, 13))
        self.assertIn("COMMAND=%27499%27", url)
        self.assertIn("START_TIME=%272026-08-13%27", url)
        self.assertIn("CENTER=%27500%4010%27", url)

    def test_horizons_error_is_not_normalized_as_ephemeris(self) -> None:
        source = collect.Source(
            source_id="nasa_horizons_9_bodies",
            name="Horizons",
            access="OPEN_BATCH",
            kind="nasa_horizons_planets",
            url="https://example.test/horizons",
            portal_url=None,
            role="astronomy_control",
        )
        with self.assertRaises(collect.CollectionError):
            collect.normalize_horizons_body(
                source,
                "499",
                "Mars",
                "https://example.test/error",
                b'{"error":"bad query","result":"error text"}',
                date(2026, 8, 13),
            )

    def test_horizons_normalizes_structured_heliocentric_reference(self) -> None:
        source = collect.Source(
            source_id="nasa_horizons_9_bodies",
            name="Horizons",
            access="OPEN_BATCH",
            kind="nasa_horizons_planets",
            url="https://example.test/horizons",
            portal_url=None,
            role="astronomy_control",
        )
        start = date(2026, 8, 13)
        record = collect.normalize_horizons_body(
            source,
            "199",
            "Mercury",
            collect.horizons_url("199", start),
            horizons_sample_payload(),
            start,
        )[0]
        ephemeris = record["ephemeris"]
        self.assertEqual(record["observed_at_start"], "2026-08-13T00:00:00Z")
        self.assertEqual(record["time_precision"], "minute")
        self.assertEqual(ephemeris["observer_mode"], "heliocentric_bodycentric_reference")
        self.assertEqual(ephemeris["azimuth_altitude_status"], "not_applicable_non_topocentric")
        self.assertIsNone(ephemeris["azimuth_deg"])
        self.assertIsNone(ephemeris["altitude_deg"])
        self.assertAlmostEqual(ephemeris["ra_icrf_deg"], 66.42575)
        self.assertAlmostEqual(ephemeris["dec_icrf_deg"], 24.1406111111)
        self.assertAlmostEqual(ephemeris["range_au"], 0.30811269403859)
        self.assertEqual(ephemeris["api_signature_version"], "1.2")

    def test_horizons_rejects_unexpected_api_signature(self) -> None:
        start = date(2026, 8, 13)
        with self.assertRaises(collect.CollectionError):
            collect.parse_horizons_ephemeris(
                body_id="199",
                body_name="Mercury",
                query_url=collect.horizons_url("199", start),
                payload=horizons_sample_payload(signature_source="untrusted proxy"),
                start=start,
            )

    def test_horizons_date_receipt_blocks_a_duplicate_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            receipt_dir = Path(temp_dir) / "receipts" / "nasa_horizons_9_bodies"
            receipt_dir.mkdir(parents=True)
            request_urls = [
                collect.horizons_url(body_id, date(2026, 8, 13))
                for body_id, _name in collect.PLANETS
            ]
            (receipt_dir / "snapshot.json").write_text(
                json.dumps({"request_urls": request_urls}), encoding="utf-8"
            )
            self.assertTrue(
                collect.horizons_date_already_archived(Path(temp_dir), date(2026, 8, 13))
            )
            self.assertFalse(
                collect.horizons_date_already_archived(Path(temp_dir), date(2026, 8, 14))
            )

    def test_source_selection_refuses_restricted_source(self) -> None:
        source = collect.Source(
            source_id="restricted",
            name="Restricted",
            access="ARCHIVE_REQUEST",
            kind=None,
            url="https://example.test/restricted",
            portal_url=None,
            role="archive",
        )
        selected = collect.select_sources({"restricted": source}, ["restricted"], False)
        self.assertEqual(selected, [source])
        self.assertNotEqual(selected[0].access, "OPEN_BATCH")

    def test_offline_plan_has_a_bounded_initial_batch(self) -> None:
        registry_path = Path(__file__).resolve().parents[1] / "sources.json"
        _registry, sources = collect.load_registry(registry_path)
        plan = collect.collection_plan(
            collect.select_sources(sources, [], True),
            absolute_response_limit=512 * 1024 * 1024,
            total_budget_bytes=64 * 1024 * 1024,
        )
        self.assertFalse(plan["network_contacted"])
        self.assertEqual(plan["request_count"], 12)
        self.assertEqual(plan["estimated_download_bytes"], 12_231_072)
        self.assertEqual(plan["source_hard_cap_bytes"], 51_380_224)
        self.assertLessEqual(plan["source_hard_cap_bytes"], plan["global_budget_bytes"])

    def test_review_queue_sources_are_never_in_all_open(self) -> None:
        registry_path = Path(__file__).resolve().parents[1] / "sources.json"
        _registry, sources = collect.load_registry(registry_path)
        selected_ids = {
            source.source_id for source in collect.select_sources(sources, [], True)
        }
        self.assertNotIn("geipan_cases_witnesses_csv", selected_ids)
        self.assertNotIn("ufosint_public_sqlite", selected_ids)
        self.assertNotIn("global_meteor_network_meteor", selected_ids)
        self.assertNotIn("nara_uap_bulk", selected_ids)
        self.assertNotIn("war_gov_uap", selected_ids)
        self.assertNotIn("spain_defense_ufo_files", selected_ids)
        self.assertNotIn("chile_sefaa", selected_ids)
        self.assertNotIn("australia_naa_ufo_records", selected_ids)
        self.assertNotIn("phenomainon_research", selected_ids)

    def test_review_command_is_offline_and_exposes_admission_state(self) -> None:
        registry_path = Path(__file__).resolve().parents[1] / "sources.json"
        output = io.StringIO()
        with redirect_stdout(output):
            status = collect.command_review(SimpleNamespace(registry=registry_path))
        self.assertEqual(status, 0)
        queue = json.loads(output.getvalue())
        self.assertFalse(queue["network_contacted"])
        indexed = {row["source_id"]: row for row in queue["sources"]}
        self.assertEqual(
            indexed["geipan_cases_witnesses_csv"]["queue_state"], "admission_review"
        )
        self.assertEqual(
            indexed["nara_uap_bulk"]["next_action"],
            "LOCAL_MANIFEST_PARSER_READY_REMOTE_INDEX_COLLECTION_PENDING",
        )

    def test_request_budget_stops_a_response_without_network(self) -> None:
        class FakeResponse:
            headers: dict[str, str] = {}

            def __init__(self, payload: bytes) -> None:
                self.payload = payload

            def __enter__(self) -> "FakeResponse":
                return self

            def __exit__(self, *_args: object) -> None:
                return None

            def read(self, count: int) -> bytes:
                result, self.payload = self.payload[:count], self.payload[count:]
                return result

        budget = collect.DownloadBudget(max_bytes=3)
        with patch.object(collect, "urlopen", return_value=FakeResponse(b"abcd")):
            with self.assertRaises(collect.CollectionError):
                collect.request_bytes(
                    "https://example.test/file",
                    max_bytes=10,
                    timeout_seconds=1,
                    budget=budget,
                )
        self.assertEqual(budget.used_bytes, 3)

    def test_streamed_artifact_is_hashed_atomic_and_bounded(self) -> None:
        class FakeResponse:
            def __init__(self, payload: bytes) -> None:
                self.headers = {"Content-Length": str(len(payload))}
                self.payload = payload

            def __enter__(self) -> "FakeResponse":
                return self

            def __exit__(self, *_args: object) -> None:
                return None

            def geturl(self) -> str:
                return "https://example.test/final.db"

            def read(self, count: int) -> bytes:
                result, self.payload = self.payload[:count], self.payload[count:]
                return result

        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "raw" / "artifact.db"
            budget = collect.DownloadBudget(max_bytes=32)
            with patch.object(collect, "urlopen", return_value=FakeResponse(b"sqlite-bytes")):
                artifact = collect.stream_response_to_path(
                    "https://example.test/source.db",
                    target_path=target,
                    max_bytes=16,
                    timeout_seconds=1,
                    budget=budget,
                )
            self.assertEqual(target.read_bytes(), b"sqlite-bytes")
            self.assertEqual(artifact.path, target)
            self.assertEqual(artifact.byte_count, len(b"sqlite-bytes"))
            self.assertEqual(
                artifact.sha256,
                "6a70d98b55f71fa10b6d012fbd7aebc45daa182bf722e9b7f07f855dabf2703f",
            )
            self.assertEqual(budget.used_bytes, len(b"sqlite-bytes"))

    def test_streamed_artifact_never_overwrites_existing_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "artifact.db"
            target.write_bytes(b"keep-me")
            with self.assertRaises(collect.CollectionError):
                collect.stream_response_to_path(
                    "https://example.test/source.db",
                    target_path=target,
                    max_bytes=16,
                    timeout_seconds=1,
                    budget=collect.DownloadBudget(max_bytes=16),
                )
            self.assertEqual(target.read_bytes(), b"keep-me")


if __name__ == "__main__":
    unittest.main()
