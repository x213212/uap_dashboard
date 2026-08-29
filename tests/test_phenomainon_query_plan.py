from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import unittest


MODULE_PATH = Path(__file__).resolve().parents[1] / "phenomainon_query_plan.py"
SPEC = importlib.util.spec_from_file_location("uap_phenomainon_query_plan", MODULE_PATH)
assert SPEC and SPEC.loader
phenom = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = phenom
SPEC.loader.exec_module(phenom)


class PhenomainonQueryPlanTests(unittest.TestCase):
    def test_overview_and_search_are_no_contact_and_never_embed_a_key(self) -> None:
        overview = phenom.plan_overview()
        search = phenom.plan_search(
            country="US", shape="triangle", year_from=1982, year_to=1986, min_sources=2, limit=25
        )
        self.assertFalse(overview["network_contacted"])
        self.assertEqual(overview["endpoint"], "https://mcp.phenomainon.com/mcp")
        self.assertEqual(overview["request_body"]["params"]["name"], "dataset_overview")
        self.assertEqual(search["request_body"]["params"]["name"], "search_cases")
        self.assertEqual(
            search["request_body"]["params"]["arguments"],
            {
                "country": "US",
                "shape": "triangle",
                "year_from": 1982,
                "year_to": 1986,
                "min_sources": 2,
                "limit": 25,
            },
        )
        serialized = json.dumps(search)
        self.assertNotIn("YOUR_KEY", serialized)
        self.assertNotIn("api_key", serialized.lower())
        self.assertEqual(search["required_headers"]["X-API-Key"], "REDACTED_REQUIRED")

    def test_stats_and_search_reject_unbounded_or_unsafe_requests(self) -> None:
        stats = phenom.plan_stats(group_by="country", shape="sphere")
        self.assertEqual(stats["request_body"]["params"]["arguments"], {"group_by": "country", "shape": "sphere"})
        with self.assertRaisesRegex(phenom.PhenomainonPlanError, "group_by"):
            phenom.plan_stats(group_by="raw_sql")
        with self.assertRaisesRegex(phenom.PhenomainonPlanError, "1 to 100"):
            phenom.plan_search(limit=101)
        with self.assertRaisesRegex(phenom.PhenomainonPlanError, "must not precede"):
            phenom.plan_search(year_from=2000, year_to=1999)
        with self.assertRaisesRegex(phenom.PhenomainonPlanError, "100 years"):
            phenom.plan_search(year_from=1800, year_to=2001)
        with self.assertRaisesRegex(phenom.PhenomainonPlanError, "safe display"):
            phenom.plan_search(shape="triangle\nforce")


if __name__ == "__main__":
    unittest.main()
