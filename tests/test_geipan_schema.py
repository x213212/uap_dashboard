from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest


MODULE_PATH = Path(__file__).resolve().parents[1] / "geipan_schema.py"
SPEC = importlib.util.spec_from_file_location("uap_geipan_schema", MODULE_PATH)
assert SPEC and SPEC.loader
geipan = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = geipan
SPEC.loader.exec_module(geipan)


class GeipanSchemaTests(unittest.TestCase):
    def test_pair_inspection_reads_headers_only_and_finds_candidate_relation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            cases = root / "cases.csv"
            testimonies = root / "testimonies.csv"
            cases.write_text(
                "ID Cas;Classification;Date observation;Latitude;Longitude\n"
                "CAS-99;D;2024-01-02;48.123;2.456\n",
                encoding="utf-8",
            )
            testimonies.write_text(
                "case_id|ID Témoignage|Nom témoin|Adresse témoin\n"
                "CAS-99|T-1|Jane Example|1 rue privée\n",
                encoding="utf-8",
            )
            report = geipan.inspect_pair(cases, testimonies)

        self.assertFalse(report["network_contacted"])
        self.assertEqual(report["records_read"], 0)
        self.assertEqual(report["case_join_key_candidates"], ("case_id",))
        self.assertEqual(report["shared_headers"], ())
        self.assertEqual(
            report["admission_result"],
            "candidate_join_key_found_manual_relation_and_privacy_review_required",
        )
        input_by_label = {item["label"]: item for item in report["inputs"]}
        self.assertEqual(input_by_label["cases"]["delimiter"], ";")
        self.assertEqual(input_by_label["testimonies"]["delimiter"], "|")
        self.assertIn("Nom témoin", input_by_label["testimonies"]["privacy_named_headers"])
        self.assertIn("Adresse témoin", input_by_label["testimonies"]["privacy_named_headers"])
        serialized = json.dumps(report, ensure_ascii=False)
        self.assertNotIn("Jane Example", serialized)
        self.assertNotIn("rue privée", serialized)
        self.assertNotIn("CAS-99", serialized)

    def test_inspection_rejects_duplicate_normalized_headers(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            bad = Path(temp_dir) / "bad.csv"
            bad.write_text("ID Cas;id_cas\n", encoding="utf-8")
            with self.assertRaisesRegex(geipan.GeipanSchemaError, "duplicate"):
                geipan.inspect_header(bad, label="cases")

    def test_inspection_never_guesses_a_relation_without_a_shared_case_key(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            cases = root / "cases.csv"
            testimonies = root / "testimonies.csv"
            cases.write_text("id_case;classification\nCASE-1;A\n", encoding="utf-8")
            testimonies.write_text("id_temoin;couleur\nT-1;blanc\n", encoding="utf-8")
            report = geipan.inspect_pair(cases, testimonies)
        self.assertEqual(report["case_join_key_candidates"], ())
        self.assertEqual(
            report["admission_result"], "no_safe_join_key_inferred_manual_schema_mapping_required"
        )


if __name__ == "__main__":
    unittest.main()
