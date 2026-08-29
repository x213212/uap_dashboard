from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest


MODULE_PATH = Path(__file__).resolve().parents[1] / "nara_manifest.py"
SPEC = importlib.util.spec_from_file_location("nara_manifest", MODULE_PATH)
assert SPEC and SPEC.loader
nara_manifest = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = nara_manifest
SPEC.loader.exec_module(nara_manifest)


INDEX_HTML = """
<table>
  <tr><th>Level</th><th>Title</th><th>Metadata</th><th>Zip</th></tr>
  <tr>
    <td>Series</td>
    <td><a href="https://catalog.archives.gov/id/595175">Project Blue Book Administrative Files</a></td>
    <td><a href="/medialz/bulk-downloads/uaps/JSON/catalog-export-595175.json">metadata</a></td>
    <td><a href="https://catalog.archives.gov/medialz/bulk-downloads/uaps/ZIP/595175.zip">595175.zip (2.84 MB)</a></td>
  </tr>
  <tr>
    <td>Series</td>
    <td><a href="https://catalog.archives.gov/id/597821">Sanitized Case Files</a></td>
    <td><a href="/medialz/bulk-downloads/uaps/JSON/catalog-export-597821.json">metadata</a></td>
    <td>
      <a href="https://catalog.archives.gov/medialz/bulk-downloads/uaps/ZIP/597821-images-1.zip">images-1.zip (79.90 GB)</a>
      <a href="https://catalog.archives.gov/medialz/bulk-downloads/uaps/ZIP/597821-pdfs-1.zip">pdfs-1.zip (81.11 GB)</a>
    </td>
  </tr>
  <tr>
    <td>Item</td>
    <td><a href="https://catalog.archives.gov/id/617148">Unavailable record</a></td>
    <td><a href="/medialz/bulk-downloads/uaps/JSON/catalog-export-617148.json">metadata</a></td>
    <td>Not Available Online</td>
  </tr>
  <tr>
    <td>Series</td>
    <td><a href="https://catalog.archives.gov/id/595175">Project Blue Book Administrative Files</a></td>
    <td><a href="/medialz/bulk-downloads/uaps/JSON/catalog-export-595175.json">metadata</a></td>
    <td><a href="https://catalog.archives.gov/medialz/bulk-downloads/uaps/ZIP/595175.zip">595175.zip (2.84 MB)</a></td>
  </tr>
</table>
"""


class NaraManifestTests(unittest.TestCase):
    def test_parser_extracts_metadata_without_fetching_media(self) -> None:
        document = nara_manifest.build_manifest_document(INDEX_HTML)
        self.assertFalse(document["network_contacted"])
        self.assertEqual(document["stats"]["metadata_item_count"], 3)
        self.assertEqual(document["stats"]["media_artifact_count"], 3)
        self.assertEqual(document["stats"]["declared_media_bytes_known"], 161_012_840_000)

        by_naid = {item["naid"]: item for item in document["items"]}
        self.assertEqual(by_naid["595175"]["title"], "Project Blue Book Administrative Files")
        self.assertEqual(
            by_naid["595175"]["metadata_url"],
            "https://www.archives.gov/medialz/bulk-downloads/uaps/JSON/catalog-export-595175.json",
        )
        self.assertEqual(by_naid["597821"]["media_artifacts"][0]["declared_bytes"], 79_900_000_000)
        self.assertEqual(by_naid["617148"]["online_status"], "not_available_or_metadata_only")

    def test_manifest_writer_refuses_overwrite(self) -> None:
        document = nara_manifest.build_manifest_document(INDEX_HTML)
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "manifest.json"
            nara_manifest.atomic_write_json(path, document)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["schema_version"], nara_manifest.SCHEMA_VERSION)
            with self.assertRaises(RuntimeError):
                nara_manifest.atomic_write_json(path, document)


if __name__ == "__main__":
    unittest.main()
