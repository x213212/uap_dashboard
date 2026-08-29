#!/usr/bin/env python3
"""Reusable rights review for the UAP source registry.

Admitting a source is a rights decision before it is an engineering one, and
today that decision was made by hand: open the provider's licence page, read the
clause, write the verdict.  This tool makes that repeatable and auditable.

It reads only pages a reviewer has explicitly declared as licence, terms or
package-metadata endpoints, and it refuses to fetch a registry data endpoint --
so it can never become a scraper, whatever it is pointed at.  Each fetch leaves
a receipt with the HTTP status, byte count, SHA-256 of the exact bytes read and
the clauses matched verbatim.  The verdict itself stays human: the tool gathers
evidence and flags obvious signals, it never decides admission on its own.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import html
import json
from pathlib import Path
import re
from typing import Any, Iterable
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

ROOT = Path(__file__).resolve().parent
REGISTRY_PATH = ROOT / "sources.json"
TARGETS_PATH = ROOT / "source_rights_targets.json"
RECEIPT_ROOT = ROOT / "data" / "rights_review"
TARGETS_SCHEMA_VERSION = "uap.source_rights_targets.v1"
RECEIPT_SCHEMA_VERSION = "uap.source_rights_receipt.v1"
USER_AGENT = "uap-lab source admission review (licence pages only; no data access)"
MAX_RESPONSE_BYTES = 4 * 1024 * 1024
TIMEOUT_SECONDS = 30
MAX_CLAUSES = 12
MAX_CLAUSE_CHARS = 400

TARGET_KINDS = frozenset({"terms_page", "licence_page", "github_repo", "package_metadata"})
VERDICT_STATES = frozenset({"PASS", "PASS_WITH_CONDITIONS", "CONDITIONAL", "REJECT", "PENDING"})

# Clause families worth quoting back, in the languages the registry actually
# spans.  A hit is evidence to read, never an automatic verdict.
# Ordered by how decisive the family is: a reviewer needs the clause that
# forbids or grants reuse before the one that merely mentions a licence.
CLAUSE_PATTERNS: tuple[tuple[str, str], ...] = (
    ("restriction", r"prohibit|forbidden|interdit|strictement|restrict|may not|not permitted|all rights reserved|tous droits réservés"),
    ("licence", r"licen[cs]e|CC[ -]BY|creative commons|public domain|licence ouverte|etalab|domaine public"),
    ("redistribution", r"redistribut|reproduc|extract|derivative|scrap|bulk|reuse|réutilisation|diffusion"),
    ("permission", r"permission|authoris|authoriz|written consent|autorisation"),
    ("attribution", r"attribution|cite|citation|credit|mention"),
)


class RightsReviewError(RuntimeError):
    """Raised when a review target or registry contract is violated."""


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise RightsReviewError(f"cannot read {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise RightsReviewError(f"invalid JSON at {path}: {exc}") from exc


def registry_data_endpoints(registry: dict[str, Any]) -> dict[str, set[str]]:
    """Every URL the registry treats as a data endpoint, per source."""

    endpoints: dict[str, set[str]] = {}
    for entry in registry.get("sources", []):
        # The registry keys entries as "id"; collect.py renames it on export.
        source_id = entry.get("id") or entry.get("source_id")
        if not source_id:
            continue
        urls = {
            str(entry[key])
            for key in ("url", "download_url", "api_url", "export_url")
            if entry.get(key)
        }
        endpoints[source_id] = urls
    return endpoints


def normalise(url: str) -> tuple[str, str]:
    parts = urlsplit(url)
    return parts.netloc.lower(), parts.path.rstrip("/").lower()


def assert_review_target(url: str, data_endpoints: Iterable[str]) -> None:
    """Refuse anything that could pull data rather than terms.

    This is the property that makes the tool safe to run unattended: a review
    target may never be a registry data endpoint, nor a path beneath one.
    """

    parts = urlsplit(url)
    if parts.scheme != "https":
        raise RightsReviewError(f"review target must be https: {url}")
    host, path = normalise(url)
    for endpoint in data_endpoints:
        endpoint_host, endpoint_path = normalise(endpoint)
        if host != endpoint_host:
            continue
        if path == endpoint_path or (endpoint_path and path.startswith(f"{endpoint_path}/")):
            raise RightsReviewError(
                f"refusing to fetch a registry data endpoint as a review target: {url}"
            )
    return None


def visible_text(payload: bytes) -> str:
    text = payload.decode("utf-8", errors="replace")
    text = re.sub(r"<script.*?</script>|<style.*?</style>", " ", text, flags=re.S | re.I)
    text = html.unescape(re.sub(r"<[^>]+>", " ", text))
    return re.sub(r"\s+", " ", text).strip()


def extract_clauses(text: str) -> list[dict[str, str]]:
    """Quote back the sentences a reviewer needs to read, verbatim."""

    clauses: list[dict[str, str]] = []
    seen: set[str] = set()
    # A sentence ends at a period that is not part of a number: splitting on
    # every dot would truncate "CC BY 4.0" to "CC BY 4." and lose the licence.
    body = r"(?:[^.]|\.(?=\d))"
    for family, pattern in CLAUSE_PATTERNS:
        for match in re.finditer(rf"{body}*?(?:{pattern}){body}*\.", text, re.I):
            sentence = match.group(0).strip()
            if not 25 < len(sentence) <= MAX_CLAUSE_CHARS or sentence in seen:
                continue
            seen.add(sentence)
            clauses.append({"family": family, "text": sentence})
            if len(clauses) >= MAX_CLAUSES:
                return clauses
    return clauses


def fetch(url: str) -> dict[str, Any]:
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
    try:
        with urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            payload = response.read(MAX_RESPONSE_BYTES + 1)
            status = response.status
    except HTTPError as error:
        # A refusal is evidence too: a provider blocking automated access has
        # told the reviewer something about consent.
        return {"http_status": error.code, "payload": b"", "error": str(error.reason)}
    except (URLError, TimeoutError, OSError) as error:
        return {"http_status": None, "payload": b"", "error": str(error)}
    if len(payload) > MAX_RESPONSE_BYTES:
        raise RightsReviewError(f"review target exceeds {MAX_RESPONSE_BYTES} bytes: {url}")
    return {"http_status": status, "payload": payload, "error": None}


def github_licence_signal(payload: bytes) -> dict[str, Any] | None:
    try:
        document = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    licence = document.get("license")
    return {
        "declared_license": (licence or {}).get("spdx_id"),
        "declared_license_name": (licence or {}).get("name"),
        "archived": document.get("archived"),
        "full_name": document.get("full_name"),
    }


def probe_target(source_id: str, target: dict[str, Any], data_endpoints: set[str]) -> dict[str, Any]:
    kind = target.get("kind")
    url = target.get("url")
    if kind not in TARGET_KINDS or not isinstance(url, str):
        raise RightsReviewError(f"{source_id}: invalid review target {target!r}")
    assert_review_target(url, data_endpoints)

    result = fetch(url)
    payload = result["payload"]
    receipt: dict[str, Any] = {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "source_id": source_id,
        "target_kind": kind,
        "url": url,
        "fetched_at": utc_now(),
        "http_status": result["http_status"],
        "error": result["error"],
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest() if payload else None,
        "clauses": [],
        "signals": {},
    }
    if not payload:
        # 401/403 is the provider declining automated access; record and stop.
        receipt["signals"]["access_blocked"] = result["http_status"] in (401, 403)
        return receipt
    if kind == "github_repo":
        signal = github_licence_signal(payload)
        if signal is not None:
            receipt["signals"].update(signal)
            receipt["signals"]["no_declared_license"] = not signal.get("declared_license")
            return receipt
    receipt["clauses"] = extract_clauses(visible_text(payload))
    return receipt


def load_targets() -> dict[str, Any]:
    document = read_json(TARGETS_PATH)
    if document.get("schema_version") != TARGETS_SCHEMA_VERSION:
        raise RightsReviewError(f"unsupported review target document: {TARGETS_PATH}")
    sources = document.get("sources")
    if not isinstance(sources, dict):
        raise RightsReviewError("review target document lacks sources")
    for source_id, entry in sources.items():
        verdict = (entry.get("verdict") or {}).get("state", "PENDING")
        if verdict not in VERDICT_STATES:
            raise RightsReviewError(f"{source_id}: unknown verdict state {verdict!r}")
    return document


def command_targets(_arguments: argparse.Namespace) -> int:
    document = load_targets()
    registry = read_json(REGISTRY_PATH)
    known = {entry.get("id") or entry.get("source_id") for entry in registry.get("sources", [])}
    rows = []
    for source_id, entry in sorted(document["sources"].items()):
        if source_id not in known:
            raise RightsReviewError(f"review target names an unregistered source: {source_id}")
        verdict = entry.get("verdict") or {}
        rows.append(
            {
                "source_id": source_id,
                "targets": [target["url"] for target in entry.get("targets", [])],
                "verdict": verdict.get("state", "PENDING"),
                "license": verdict.get("license"),
                "decided_at": verdict.get("decided_at"),
            }
        )
    unreviewed = sorted(known - set(document["sources"]))
    print(
        json.dumps(
            {
                "reviewed": rows,
                "registered_without_review_targets": unreviewed,
                "coverage": f"{len(rows)}/{len(known)}",
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def command_probe(arguments: argparse.Namespace) -> int:
    document = load_targets()
    registry = read_json(REGISTRY_PATH)
    endpoints = registry_data_endpoints(registry)
    selected = arguments.source_id or sorted(document["sources"])
    written = []
    for source_id in selected:
        entry = document["sources"].get(source_id)
        if entry is None:
            raise RightsReviewError(f"no review targets declared for {source_id}")
        data_endpoints = endpoints.get(source_id, set())
        for target in entry.get("targets", []):
            receipt = probe_target(source_id, target, data_endpoints)
            directory = RECEIPT_ROOT / source_id
            directory.mkdir(parents=True, exist_ok=True)
            stamp = receipt["fetched_at"].replace(":", "").replace("-", "")
            digest = hashlib.sha256(receipt["url"].encode("utf-8")).hexdigest()[:8]
            path = directory / f"{stamp}_{digest}.json"
            path.write_text(
                json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            written.append({"source_id": source_id, "url": receipt["url"],
                            "http_status": receipt["http_status"],
                            "clauses": len(receipt["clauses"]),
                            "receipt": str(path.relative_to(ROOT))})
    print(json.dumps({"probed": written, "network_contacted": True}, ensure_ascii=False, indent=2))
    return 0


def latest_receipts(source_id: str) -> list[dict[str, Any]]:
    directory = RECEIPT_ROOT / source_id
    if not directory.is_dir():
        return []
    by_url: dict[str, dict[str, Any]] = {}
    for path in sorted(directory.glob("*.json")):
        receipt = read_json(path)
        by_url[receipt.get("url", str(path))] = receipt
    return list(by_url.values())


def command_report(arguments: argparse.Namespace) -> int:
    document = load_targets()
    registry = read_json(REGISTRY_PATH)
    access = {
        (entry.get("id") or entry.get("source_id")): entry.get("access")
        for entry in registry.get("sources", [])
    }
    report = []
    for source_id, entry in sorted(document["sources"].items()):
        verdict = entry.get("verdict") or {}
        receipts = latest_receipts(source_id)
        report.append(
            {
                "source_id": source_id,
                "registry_access": access.get(source_id),
                "verdict": verdict.get("state", "PENDING"),
                "license": verdict.get("license"),
                "publishable": verdict.get("publishable"),
                "basis": verdict.get("basis"),
                "decided_at": verdict.get("decided_at"),
                "evidence": [
                    {
                        "url": receipt["url"],
                        "http_status": receipt["http_status"],
                        "fetched_at": receipt["fetched_at"],
                        "sha256": receipt["sha256"],
                        "signals": receipt.get("signals") or {},
                        "clauses": [clause["text"] for clause in receipt.get("clauses", [])][
                            : arguments.clauses
                        ],
                    }
                    for receipt in receipts
                ],
            }
        )
    stale = [row["source_id"] for row in report if not row["evidence"]]
    print(
        json.dumps(
            {
                "reviewed": report,
                "without_evidence_receipts": stale,
                "note": "Verdicts are human decisions; receipts are the evidence they rest on.",
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("targets", help="list declared review targets without network access")
    probe = sub.add_parser("probe", help="fetch declared licence/terms pages only")
    probe.add_argument("source_id", nargs="*", help="limit to these sources")
    report = sub.add_parser("report", help="render verdicts with their evidence receipts")
    report.add_argument("--clauses", type=int, default=3, help="clauses quoted per target")
    return parser


def main() -> int:
    parser = build_parser()
    arguments = parser.parse_args()
    handlers = {"targets": command_targets, "probe": command_probe, "report": command_report}
    try:
        return handlers[arguments.command](arguments)
    except RightsReviewError as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False), flush=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
