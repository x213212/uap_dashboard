from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest


MODULE_PATH = Path(__file__).resolve().parents[1] / "source_inventory.py"
SPEC = importlib.util.spec_from_file_location("uap_source_inventory", MODULE_PATH)
assert SPEC and SPEC.loader
inventory = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = inventory
SPEC.loader.exec_module(inventory)


class SourceInventoryTests(unittest.TestCase):
    def fixture_registry(self, root: Path) -> Path:
        atlas = root / "atlas.md"
        atlas.write_text(
            "# Atlas title\n"
            "## Region A\n"
            "[Official source](https://example.test/official) and https://example.test/bare|\n"
            "## Region B\n"
            "[Repeated label](https://example.test/official)\n",
            encoding="utf-8",
        )
        registry = root / "sources.json"
        registry.write_text(
            json.dumps(
                {
                    "schema_version": "uap.source_registry.v1",
                    "atlas_path": "atlas.md",
                    "sources": [
                        {
                            "id": "fixture_source",
                            "access": "OPEN_QUERY",
                            "url": "https://example.test/official",
                            "portal_url": "https://example.test/portal",
                            "role": "official_cases",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        return registry

    def test_inventory_deduplicates_urls_and_retains_context(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            report = inventory.build_inventory(self.fixture_registry(Path(temp_dir)))
        self.assertFalse(report["network_contacted"])
        self.assertEqual(report["url_count"], 3)
        self.assertEqual(report["registry_managed_url_count"], 2)
        by_url = {entry["url"]: entry for entry in report["entries"]}
        official = by_url["https://example.test/official"]
        self.assertEqual(official["labels"], ["Official source", "Repeated label"])
        self.assertEqual(official["sections"], ["Region A", "Region B"])
        self.assertEqual(official["source_ids"], ["fixture_source"])
        self.assertEqual(official["registry_access"], ["OPEN_QUERY"])
        self.assertEqual(official["admission_posture"], "registry_managed")
        self.assertEqual(by_url["https://example.test/bare"]["admission_posture"], "atlas_reference_only")

    def test_csv_and_write_output_do_not_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            report = inventory.build_inventory(self.fixture_registry(root))
            rendered = inventory.render_csv(report)
            self.assertIn("https://example.test/official", rendered)
            output = root / "inventory.csv"
            inventory.write_output(output, rendered)
            with self.assertRaisesRegex(inventory.InventoryError, "overwrite"):
                inventory.write_output(output, rendered)

    def test_inventory_retains_country_table_context_only_for_country_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            registry = self.fixture_registry(root)
            (root / "atlas.md").write_text(
                "# Atlas title\n"
                "## Geographic sources\n"
                "| 國家／區域 | Source |\n"
                "| --- | --- |\n"
                "| Exampleland | [Local archive](https://example.test/local) |\n"
                "\n"
                "## Controls\n"
                "| Type | Source |\n"
                "| --- | --- |\n"
                "| Weather | [Control](https://example.test/control) |\n",
                encoding="utf-8",
            )
            report = inventory.build_inventory(registry)
        by_url = {entry["url"]: entry for entry in report["entries"]}
        self.assertEqual(
            by_url["https://example.test/local"]["country_or_regions"],
            ["Exampleland"],
        )
        self.assertEqual(
            by_url["https://example.test/control"]["country_or_regions"],
            [],
        )
        self.assertIn("country_or_regions", inventory.render_csv(report))


if __name__ == "__main__":
    unittest.main()
