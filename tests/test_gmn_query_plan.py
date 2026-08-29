from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest
from urllib.parse import parse_qs, urlparse


MODULE_PATH = Path(__file__).resolve().parents[1] / "gmn_query_plan.py"
SPEC = importlib.util.spec_from_file_location("uap_gmn_query_plan", MODULE_PATH)
assert SPEC and SPEC.loader
gmn = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = gmn
SPEC.loader.exec_module(gmn)


class GmnQueryPlanTests(unittest.TestCase):
    def test_plan_is_no_contact_bounded_and_uses_composite_cursor(self) -> None:
        plan = gmn.build_plan(
            after_updated_at="2026-08-01T00:00:00Z",
            after_identifier="20260801000000_A",
            until_updated_at="2026-08-02T00:00:00+00:00",
            page_size=250,
        )
        self.assertFalse(plan["network_contacted"])
        self.assertEqual(plan["page_row_cap"], 250)
        self.assertEqual(
            plan["cursor_contract"]["order"], ["updated_at", "unique_trajectory_identifier"]
        )
        self.assertIn('"updated_at" = :after_updated_at', plan["sql"])
        self.assertIn('"unique_trajectory_identifier" > :after_identifier', plan["sql"])
        self.assertNotIn("select *", plan["sql"].lower())
        self.assertNotIn("description", plan["selected_columns"])

        request = urlparse(plan["request_url"])
        self.assertEqual(request.scheme, "https")
        self.assertEqual(request.path, "/gmn_data_store/-/query.json")
        params = parse_qs(request.query)
        self.assertEqual(params["page_size"], ["250"])
        self.assertEqual(params["after_identifier"], ["20260801000000_A"])
        self.assertIn("sql", params)

    def test_rejects_unbounded_or_ambiguous_windows(self) -> None:
        with self.assertRaisesRegex(gmn.GmnPlanError, "later"):
            gmn.build_plan(
                after_updated_at="2026-08-02T00:00:00Z",
                until_updated_at="2026-08-02T00:00:00Z",
            )
        with self.assertRaisesRegex(gmn.GmnPlanError, "31 days"):
            gmn.build_plan(
                after_updated_at="2026-01-01T00:00:00Z",
                until_updated_at="2026-02-02T00:00:00Z",
            )
        with self.assertRaisesRegex(gmn.GmnPlanError, "include UTC"):
            gmn.build_plan(
                after_updated_at="2026-08-01T00:00:00",
                until_updated_at="2026-08-02T00:00:00Z",
            )
        with self.assertRaisesRegex(gmn.GmnPlanError, "1 to"):
            gmn.build_plan(
                after_updated_at="2026-08-01T00:00:00Z",
                until_updated_at="2026-08-02T00:00:00Z",
                page_size=1001,
            )


if __name__ == "__main__":
    unittest.main()
