from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest


MODULE_PATH = Path(__file__).resolve().parents[1] / "coverage_inventory.py"
SPEC = importlib.util.spec_from_file_location("uap_coverage_inventory", MODULE_PATH)
assert SPEC and SPEC.loader
coverage = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = coverage
SPEC.loader.exec_module(coverage)


class CoverageInventoryTests(unittest.TestCase):
    def fixture_ledger(self, root: Path) -> Path:
        ledger = root / "ledger.md"
        ledger.write_text(
            "# Ledger\n"
            "## 覆蓋快照\n"
            "| 分區 | A：本地／官方入口 | B：館藏／申請線索 | C：僅全球基線 | D：未驗到入口 | 合計 |\n"
            "| --- | ---: | ---: | ---: | ---: | ---: |\n"
            "| 歐洲 | 1 | 0 | 0 | 0 | 1 |\n"
            "| 美洲 | 0 | 1 | 0 | 0 | 1 |\n"
            "| 非洲 | 0 | 0 | 1 | 0 | 1 |\n"
            "| 亞洲 | 0 | 0 | 0 | 1 | 1 |\n"
            "| 大洋洲 | 0 | 0 | 0 | 0 | 0 |\n"
            "| **193 會員國合計** | **1** | **1** | **1** | **1** | **4** |\n"
            "## 歐洲（1／1）\n"
            "| 國家 | ISO | 狀態 | 已定位入口或缺口說明 |\n"
            "| --- | --- | --- | --- |\n"
            "| Linkland | LL | A | [Local archive](https://example.test/local) confirmed |\n"
            "## 美洲（1／1）\n"
            "| 國家 | ISO | 狀態 | 已定位入口或缺口說明 |\n"
            "| --- | --- | --- | --- |\n"
            "| Archiveia | AA | B | historical finding aid |\n"
            "## 非洲（1／1）\n"
            "| 國家 | ISO | 狀態 | 已定位入口或缺口說明 |\n"
            "| --- | --- | --- | --- |\n"
            "| Baseline | BB | C | global-only |\n"
            "## 亞洲（1／1）\n"
            "| 國家 | ISO | 狀態 | 已定位入口或缺口說明 |\n"
            "| --- | --- | --- | --- |\n"
            "| Gapland | GG | D | no verified route |\n"
            "## 大洋洲（0／0）\n"
            "| 國家 | ISO | 狀態 | 已定位入口或缺口說明 |\n"
            "| --- | --- | --- | --- |\n"
            "## 地圖實務補充（非 193 會員國）\n"
            "| 地區／國家 | ISO／慣用碼 | 狀態 | 說明 |\n"
            "| --- | --- | --- | --- |\n"
            "| Extra | XX | D | must be excluded |\n",
            encoding="utf-8",
        )
        return ledger

    def test_actual_ledger_is_complete_and_machine_readable(self) -> None:
        report = coverage.build_inventory()
        self.assertFalse(report["network_contacted"])
        self.assertEqual(report["country_count"], 193)
        self.assertEqual(report["status_counts"], {"A": 41, "B": 144, "C": 0, "D": 8})
        self.assertEqual(report["strict_local_mother_archive_gap_count"], 8)
        self.assertEqual(len(report["entries"]), 193)

    def test_fixture_parses_rows_and_excludes_supplement(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            report = coverage.build_inventory(
                self.fixture_ledger(Path(temp_dir)), validate_complete=False
            )
        self.assertEqual(report["country_count"], 4)
        self.assertEqual(report["status_counts"], {"A": 1, "B": 1, "C": 1, "D": 1})
        self.assertEqual(report["strict_local_mother_archive_gap_count"], 2)
        self.assertEqual(report["entries"][0]["entry_summary"], "Local archive confirmed")
        self.assertEqual(report["entries"][0]["membership_scope"], "UN_member_193")

    def test_gap_inventory_keeps_only_c_and_d_without_calling_them_zeroes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            report = coverage.build_inventory(
                self.fixture_ledger(Path(temp_dir)), validate_complete=False
            )
        gaps = coverage.build_gap_inventory(report)
        self.assertEqual(gaps["schema_version"], "uap.country_source_gap_inventory.v1")
        self.assertEqual(gaps["included_statuses"], ["C", "D"])
        self.assertEqual(gaps["country_count"], 2)
        self.assertEqual(gaps["status_counts"], {"C": 1, "D": 1})
        self.assertNotIn("strict_local_mother_archive_gap_count", gaps)
        self.assertEqual([entry["iso_alpha2"] for entry in gaps["entries"]], ["BB", "GG"])

    def test_csv_and_output_are_non_overwriting(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            report = coverage.build_inventory(self.fixture_ledger(root), validate_complete=False)
            rendered = coverage.render_csv(report)
            self.assertIn("Linkland", rendered)
            output = root / "coverage.csv"
            coverage.write_output(output, rendered)
            with self.assertRaisesRegex(coverage.CoverageInventoryError, "overwrite"):
                coverage.write_output(output, rendered)

    def test_complete_validation_rejects_stale_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = self.fixture_ledger(Path(temp_dir))
            rows, declared = coverage.parse_ledger(path)
            with self.assertRaisesRegex(coverage.CoverageInventoryError, "expected 193"):
                coverage.validate_complete_ledger(rows, declared)


if __name__ == "__main__":
    unittest.main()
