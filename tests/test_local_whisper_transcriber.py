import tempfile
import unittest
from pathlib import Path

from uap_lab.local_whisper_transcriber import (
    TranscriptSegment,
    compact_text,
    format_clock,
    write_human_outputs,
)


class LocalWhisperTranscriberTests(unittest.TestCase):
    def test_format_clock_supports_srt_and_vtt(self) -> None:
        self.assertEqual(format_clock(3661.2344), "01:01:01.234")
        self.assertEqual(format_clock(3661.2344, ","), "01:01:01,234")

    def test_compact_text_preserves_words(self) -> None:
        self.assertEqual(compact_text("  Credo\n  Mutwa  "), "Credo Mutwa")

    def test_human_outputs_have_one_cue_per_segment(self) -> None:
        segment = TranscriptSegment(
            evidence_id="video:000001",
            source_id="video",
            source_sha256="a" * 64,
            start=1.25,
            end=2.5,
            text="Test sentence.",
            language="en",
            engine="test",
            model="test",
        )
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder)
            artifacts = write_human_outputs(output, [segment], "en")
            self.assertEqual(artifacts["plain_text"], "transcript.en.txt")
            self.assertIn("00:00:01,250 --> 00:00:02,500", (output / artifacts["srt"]).read_text())
            self.assertIn("WEBVTT", (output / artifacts["vtt"]).read_text())


if __name__ == "__main__":
    unittest.main()
