from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest


MODULE_PATH = Path(__file__).resolve().parents[1] / "spain_mets_manifest.py"
SPEC = importlib.util.spec_from_file_location("uap_spain_mets_manifest", MODULE_PATH)
assert SPEC and SPEC.loader
spain = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = spain
SPEC.loader.exec_module(spain)


FIXTURE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<mets:mets xmlns:mets="http://www.loc.gov/METS/"
           xmlns:mods="http://www.loc.gov/mods/v3"
           xmlns:xlink="http://www.w3.org/1999/xlink"
           OBJID="spain-ufo-6809VR">
  <mets:metsHdr CREATEDATE="2026-08-13T12:00:00Z"/>
  <mets:dmdSec ID="dmd-1"><mets:mdWrap><mets:xmlData><mods:mods>
    <mods:titleInfo><mods:title>Official declassified case title</mods:title></mods:titleInfo>
    <mods:originInfo><mods:dateCreated>1968-09-05</mods:dateCreated></mods:originInfo>
    <mods:accessCondition>CC BY 4.0 attribution required</mods:accessCondition>
  </mods:mods></mets:xmlData></mets:mdWrap></mets:dmdSec>
  <mets:fileSec><mets:fileGrp USE="reference">
    <mets:file ID="page-1" MIMETYPE="image/jpeg"><mets:FLocat xlink:href="https://example.test/page-1.jpg"/></mets:file>
    <mets:file ID="page-2" MIMETYPE="image/jpeg"><mets:FLocat xlink:href="https://example.test/page-2.jpg"/></mets:file>
  </mets:fileGrp></mets:fileSec>
</mets:mets>
"""


class SpainMetsManifestTests(unittest.TestCase):
    def test_parse_is_local_and_never_follows_page_hrefs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            mets_file = Path(temp_dir) / "fixture.xml"
            mets_file.write_text(FIXTURE_XML, encoding="utf-8")
            manifest = spain.parse_manifest(mets_file)

        self.assertFalse(manifest["network_contacted"])
        self.assertEqual(manifest["record"]["mets_objid"], "spain-ufo-6809VR")
        self.assertEqual(manifest["record"]["date_created_source"], "1968-09-05")
        self.assertEqual(manifest["record"]["rights_text"], "CC BY 4.0 attribution required")
        self.assertEqual(manifest["file_count"], 2)
        self.assertEqual(manifest["files"][0]["href"], "https://example.test/page-1.jpg")
        self.assertEqual(manifest["media_policy"], "manifest_only_no_href_is_fetched")

    def test_manifest_write_refuses_overwrite_and_dtd(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            mets_file = root / "fixture.xml"
            mets_file.write_text(FIXTURE_XML, encoding="utf-8")
            output = root / "manifest.json"
            spain.write_manifest(output, spain.parse_manifest(mets_file))
            written = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(written["file_count"], 2)
            with self.assertRaisesRegex(spain.SpainMetsError, "overwrite"):
                spain.write_manifest(output, written)

            dangerous = root / "dangerous.xml"
            dangerous.write_text("<!DOCTYPE foo [<!ENTITY x 'boom'>]><foo>&x;</foo>", encoding="utf-8")
            with self.assertRaisesRegex(spain.SpainMetsError, "DOCTYPE"):
                spain.parse_manifest(dangerous)


if __name__ == "__main__":
    unittest.main()
