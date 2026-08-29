from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import unittest


MODULE_PATH = Path(__file__).resolve().parents[1] / "source_rights_review.py"
SPEC = importlib.util.spec_from_file_location("uap_source_rights_review", MODULE_PATH)
assert SPEC and SPEC.loader
review = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = review
SPEC.loader.exec_module(review)


class ReviewTargetGuardTests(unittest.TestCase):
    """The guard is the reason this tool can be run unattended."""

    DATA_ENDPOINTS = (
        "https://example.org/rest/v1/public/sightings.csv",
        "https://example.org/downloads",
    )

    def test_rejects_the_registry_data_endpoint(self) -> None:
        with self.assertRaises(review.RightsReviewError):
            review.assert_review_target(
                "https://example.org/rest/v1/public/sightings.csv", self.DATA_ENDPOINTS
            )

    def test_rejects_a_path_beneath_a_data_endpoint(self) -> None:
        with self.assertRaises(review.RightsReviewError):
            review.assert_review_target(
                "https://example.org/downloads/ufo_public.db", self.DATA_ENDPOINTS
            )

    def test_rejects_plain_http(self) -> None:
        with self.assertRaises(review.RightsReviewError):
            review.assert_review_target("http://example.org/terms", self.DATA_ENDPOINTS)

    def test_allows_a_terms_page_on_the_same_host(self) -> None:
        review.assert_review_target("https://example.org/terms-of-use", self.DATA_ENDPOINTS)

    def test_allows_a_similar_prefix_that_is_not_a_path_segment(self) -> None:
        # "/downloads-policy" is not beneath "/downloads".
        review.assert_review_target("https://example.org/downloads-policy", self.DATA_ENDPOINTS)


class ClauseExtractionTests(unittest.TestCase):
    def test_decisive_restriction_is_quoted_before_a_passing_mention(self) -> None:
        text = (
            "Our licence page explains the project. "
            "Reproduction and extraction of the content are strictly prohibited without consent. "
            "Please cite the dataset in your work."
        )
        clauses = review.extract_clauses(text)
        self.assertEqual(clauses[0]["family"], "restriction")
        self.assertIn("strictly prohibited", clauses[0]["text"])

    def test_clauses_are_verbatim_and_deduplicated(self) -> None:
        text = "The data are released under the CC BY 4.0 license. " * 3
        clauses = review.extract_clauses(text)
        self.assertEqual(len(clauses), 1)
        self.assertEqual(clauses[0]["text"], "The data are released under the CC BY 4.0 license.")

    def test_markup_and_scripts_are_stripped_before_matching(self) -> None:
        payload = b"<html><script>var licence='none';</script><p>All rights reserved by us.</p></html>"
        clauses = review.extract_clauses(review.visible_text(payload))
        self.assertTrue(any("All rights reserved" in clause["text"] for clause in clauses))
        self.assertFalse(any("var licence" in clause["text"] for clause in clauses))


class ProbeReceiptTests(unittest.TestCase):
    def probe(self, response: dict[str, object], kind: str = "terms_page") -> dict[str, object]:
        original = review.fetch
        review.fetch = lambda url: response  # type: ignore[assignment]
        try:
            return review.probe_target(
                "fixture", {"kind": kind, "url": "https://example.org/terms"}, set()
            )
        finally:
            review.fetch = original

    def test_receipt_records_bytes_and_digest_of_what_was_read(self) -> None:
        payload = b"<p>The data are released under the CC BY 4.0 license.</p>"
        receipt = self.probe({"http_status": 200, "payload": payload, "error": None})
        self.assertEqual(receipt["http_status"], 200)
        self.assertEqual(receipt["bytes"], len(payload))
        self.assertEqual(len(receipt["sha256"]), 64)
        self.assertTrue(receipt["clauses"])

    def test_a_refusal_is_recorded_as_evidence(self) -> None:
        receipt = self.probe({"http_status": 403, "payload": b"", "error": "Forbidden"})
        self.assertTrue(receipt["signals"]["access_blocked"])
        self.assertEqual(receipt["clauses"], [])
        self.assertIsNone(receipt["sha256"])

    def test_missing_repository_licence_is_flagged(self) -> None:
        payload = json.dumps({"full_name": "org/repo", "license": None}).encode("utf-8")
        receipt = self.probe(
            {"http_status": 200, "payload": payload, "error": None}, kind="github_repo"
        )
        self.assertTrue(receipt["signals"]["no_declared_license"])

    def test_unknown_target_kind_is_refused(self) -> None:
        with self.assertRaises(review.RightsReviewError):
            review.probe_target("fixture", {"kind": "data_export", "url": "https://x/y"}, set())


class RegistryContractTests(unittest.TestCase):
    def test_data_endpoints_are_read_from_the_registry_id_key(self) -> None:
        registry = {"sources": [{"id": "fixture", "url": "https://example.org/data.csv"}]}
        endpoints = review.registry_data_endpoints(registry)
        self.assertEqual(endpoints["fixture"], {"https://example.org/data.csv"})

    def test_shipped_targets_document_is_valid_and_matches_the_registry(self) -> None:
        document = review.load_targets()
        registry = review.read_json(review.REGISTRY_PATH)
        known = {entry["id"] for entry in registry["sources"]}
        for source_id, entry in document["sources"].items():
            self.assertIn(source_id, known, f"{source_id} is not a registered source")
            endpoints = review.registry_data_endpoints(registry).get(source_id, set())
            for target in entry["targets"]:
                # Every shipped target must still satisfy the guard.
                review.assert_review_target(target["url"], endpoints)


if __name__ == "__main__":
    unittest.main()
