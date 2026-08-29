from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest


MODULE_PATH = Path(__file__).resolve().parents[1] / "ufosint_adapter.py"
SPEC = importlib.util.spec_from_file_location("uap_ufosint_adapter", MODULE_PATH)
assert SPEC and SPEC.loader
adapter = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = adapter
SPEC.loader.exec_module(adapter)


class UfosintAdapterTests(unittest.TestCase):
    def build_fixture_database(self, root: Path) -> Path:
        database = root / "ufo_public.db"
        connection = sqlite3.connect(database)
        connection.executescript(
            """
            CREATE TABLE source_database (id INTEGER PRIMARY KEY, name TEXT);
            CREATE TABLE source_origin (id INTEGER PRIMARY KEY, name TEXT);
            CREATE TABLE location (
                id INTEGER PRIMARY KEY,
                raw_text TEXT,
                city TEXT,
                state TEXT,
                country TEXT,
                geocode_src TEXT
            );
            CREATE TABLE sighting (
                id INTEGER PRIMARY KEY,
                source_db_id INTEGER NOT NULL,
                source_record_id TEXT NOT NULL,
                origin_id INTEGER,
                origin_record_id TEXT,
                location_id INTEGER,
                date_event TEXT,
                date_end TEXT,
                sighting_datetime TEXT,
                lat REAL,
                lng REAL,
                shape TEXT,
                standardized_shape TEXT,
                color TEXT,
                primary_color TEXT,
                hynek TEXT,
                vallee TEXT,
                event_type TEXT,
                quality_score INTEGER,
                hoax_likelihood REAL,
                has_media INTEGER,
                has_description INTEGER,
                movement_type TEXT,
                movement_categories TEXT,
                duration TEXT,
                num_objects INTEGER,
                num_witnesses INTEGER,
                description TEXT,
                summary TEXT,
                notes TEXT,
                raw_json TEXT,
                witness_names TEXT,
                witness_age TEXT,
                witness_sex TEXT
            );
            """
        )
        connection.execute("INSERT INTO source_database VALUES (?, ?)", (2, "NUFORC"))
        connection.execute("INSERT INTO source_origin VALUES (?, ?)", (9, "NICAP"))
        connection.execute(
            "INSERT INTO location VALUES (?, ?, ?, ?, ?, ?)",
            (1, "123 Exact Witness Street", "Seattle", "WA", "us", "geonames_city_country"),
        )
        connection.execute(
            "INSERT INTO sighting VALUES (" + ", ".join("?" for _ in range(34)) + ")",
            (
                101,
                2,
                "NU-42",
                9,
                "N-18",
                1,
                "2001-02-03",
                "2001-02-04",
                "2001-02-03T21:30:00Z",
                47.61234,
                -122.34567,
                "Disc",
                "Disc",
                "red",
                "red",
                "DD",
                "FB1",
                "visual",
                78,
                0.2,
                1,
                1,
                "hover",
                '["hovering"]',
                "five minutes",
                2,
                3,
                "SENSITIVE DESCRIPTION John Example",
                "SENSITIVE SUMMARY John Example",
                "SENSITIVE NOTES John Example",
                '{"address":"123 Exact Witness Street"}',
                "John Example",
                "44",
                "M",
            ),
        )
        # A bad coordinate must not be put on the public map, even if a text
        # location exists.  A year-only date must preserve its limited time
        # precision rather than inventing a day.
        connection.execute(
            """
            INSERT INTO sighting (
                id, source_db_id, source_record_id, date_event, sighting_datetime, lat, lng,
                quality_score, hoax_likelihood
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (102, 2, "NU-43", "1987", "1987", 999.0, 10.0, 101, -1.0),
        )
        connection.commit()
        connection.close()
        return database

    def test_inspection_is_local_and_reports_stable_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = self.build_fixture_database(Path(temp_dir))
            inspection = adapter.inspect_database(database)
            self.assertEqual(inspection.sighting_rows, 2)
            self.assertEqual(inspection.stable_identity, "source_db_id:source_record_id")
            self.assertIn("sighting", inspection.tables)
            self.assertIn("witness_names", inspection.sighting_columns)
            self.assertGreater(inspection.database_bytes, 0)

    def test_adapter_streams_privacy_filtered_canonical_records(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = self.build_fixture_database(Path(temp_dir))
            records = list(adapter.iter_canonical_records(database, batch_size=1))

        self.assertEqual([record["source_record_id"] for record in records], ["2:NU-42", "2:NU-43"])
        first, second = records
        self.assertEqual(first["latitude"], 47.6)
        self.assertEqual(first["longitude"], -122.3)
        self.assertEqual(first["coordinate_precision"], "0.1_degree_privacy_grid")
        self.assertEqual(first["location_name"], "Seattle, WA, US")
        self.assertEqual(first["country_code"], "US")
        self.assertEqual(first["observed_at_start"], "2001-02-03T21:30:00Z")
        self.assertEqual(first["time_precision"], "datetime")
        self.assertEqual(first["upstream_source_database"], "NUFORC")
        self.assertEqual(first["upstream_origin"], "NICAP")
        self.assertEqual(first["summary"], None)

        sensitive_words = " ".join(json.dumps(record, ensure_ascii=False) for record in records)
        self.assertNotIn("John Example", sensitive_words)
        self.assertNotIn("Exact Witness Street", sensitive_words)
        self.assertNotIn("SENSITIVE", sensitive_words)
        for record in records:
            # ``summary`` is a mandatory project-schema key, but it must be
            # null rather than a copy of UFOSINT's upstream summary field.
            self.assertTrue((adapter.SENSITIVE_SOURCE_COLUMNS - {"summary"}).isdisjoint(record))

        self.assertIsNone(second["latitude"])
        self.assertIsNone(second["longitude"])
        self.assertIsNone(second["coordinate_precision"])
        self.assertEqual(second["observed_at_start"], "1987")
        self.assertEqual(second["time_precision"], "year")
        self.assertNotIn("quality_score", second)  # Invalid upstream score is not trusted.
        self.assertNotIn("hoax_likelihood", second)

    def test_rejects_database_without_cross_rebuild_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = Path(temp_dir) / "not_ufosint.db"
            connection = sqlite3.connect(database)
            connection.execute("CREATE TABLE sighting (id INTEGER PRIMARY KEY, date_event TEXT)")
            connection.commit()
            connection.close()
            with self.assertRaisesRegex(adapter.UfosintAdapterError, "stable identity"):
                adapter.inspect_database(database)


if __name__ == "__main__":
    unittest.main()
