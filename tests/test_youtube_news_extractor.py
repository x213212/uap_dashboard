from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest


MODULE_PATH = Path(__file__).resolve().parents[1] / "youtube_news_extractor.py"
SPEC = importlib.util.spec_from_file_location("youtube_news_extractor", MODULE_PATH)
assert SPEC and SPEC.loader
extractor = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = extractor
SPEC.loader.exec_module(extractor)


class YoutubeNewsExtractorTests(unittest.TestCase):
    def test_metadata_command_forbids_media_download(self) -> None:
        command = extractor.metadata_command(Path("/usr/bin/yt-dlp"), "ytsearch5:UAP news", 5)
        self.assertIn("--flat-playlist", command)
        self.assertIn("--skip-download", command)
        self.assertIn("--dump-single-json", command)
        self.assertNotIn("-x", command)

    def test_normalization_filters_titles_and_omits_description(self) -> None:
        record = extractor.normalize_entry(
            {
                "id": "abcdefghijk",
                "title": "UAP hearing: latest news",
                "channel": "Example News",
                "channel_id": "UCexample",
                "upload_date": "20260829",
                "duration": 125,
                "description": "A long narrative that must not enter the manifest.",
            },
            discovery_label="search:UAP news",
            keywords=("UAP", "UFO"),
        )
        assert record is not None
        self.assertEqual(record["source_record_id"], "abcdefghijk")
        self.assertEqual(record["published_date"], "2026-08-29")
        self.assertEqual(record["matched_keywords"], ["UAP"])
        self.assertNotIn("description", record)
        self.assertEqual(
            record["original_source_url"],
            "https://www.youtube.com/watch?v=abcdefghijk",
        )

    def test_irrelevant_title_is_rejected(self) -> None:
        self.assertIsNone(
            extractor.normalize_entry(
                {"id": "abcdefghijk", "title": "Daily weather report"},
                discovery_label="channel:https://www.youtube.com/@example/videos",
                keywords=("UAP", "幽浮"),
            )
        )

    def test_duplicate_search_hits_merge_provenance(self) -> None:
        first = extractor.normalize_entry(
            {"id": "abcdefghijk", "title": "UFO report", "channel": "News"},
            discovery_label="search:UFO news",
            keywords=("UFO", "UAP"),
        )
        second = extractor.normalize_entry(
            {"id": "abcdefghijk", "title": "UFO report", "view_count": 42},
            discovery_label="search:UAP news",
            keywords=("UFO", "UAP"),
        )
        assert first is not None and second is not None
        merged = extractor.merge_records([first, second])
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["view_count"], 42)
        self.assertEqual(
            merged[0]["discovered_by"],
            ["search:UFO news", "search:UAP news"],
        )

    def test_payload_requires_entries_list(self) -> None:
        with self.assertRaises(extractor.ExtractionError):
            extractor.records_from_payload(
                {"id": "not-a-playlist"},
                discovery_label="search:UFO news",
                keywords=("UFO",),
            )

    def test_atomic_writer_refuses_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "manifest.json"
            extractor.atomic_write_new(target, {"record_count": 0})
            self.assertEqual(json.loads(target.read_text())["record_count"], 0)
            with self.assertRaises(extractor.ExtractionError):
                extractor.atomic_write_new(target, {"record_count": 1})

    def test_channel_requires_https_youtube_url(self) -> None:
        with self.assertRaises(extractor.ExtractionError):
            extractor.build_jobs([], ["https://example.com/channel"], 10)


if __name__ == "__main__":
    unittest.main()
