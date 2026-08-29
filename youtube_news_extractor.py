#!/usr/bin/env python3
"""Discover UFO/UAP news videos on YouTube without downloading media.

The legacy ``youtubenews`` project collected Google News and RSS titles despite
its name.  This standalone extractor keeps the useful keyword/deduplication
idea, but uses yt-dlp's metadata-only YouTube search/channel inventory mode.

Results are discovery manifests, not verified sightings or evidence that a
reported object is extraterrestrial.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parent
DEFAULT_OUTPUT_ROOT = ROOT / "data" / "discovery" / "youtube_news"
SCHEMA_VERSION = "uap.youtube_news_discovery.v1"
DEFAULT_QUERIES = (
    "UAP news",
    "UFO news",
    "幽浮 新聞",
    "外星人 新聞",
    "不明空中現象",
)
DEFAULT_KEYWORDS = (
    "UAP",
    "UFO",
    "USO",
    "OVNI",
    "幽浮",
    "飛碟",
    "外星人",
    "外星生命",
    "不明飛行物",
    "不明空中現象",
    "不明水下物",
)
VIDEO_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{6,20}$")


class ExtractionError(RuntimeError):
    """Raised when metadata discovery cannot complete safely."""


def utc_now() -> datetime:
    return datetime.now(UTC)


def utc_stamp(value: datetime | None = None) -> str:
    return (value or utc_now()).strftime("%Y%m%dT%H%M%S%fZ")


def positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return parsed


def resolve_yt_dlp(explicit: Path | None = None) -> Path:
    candidates: list[Path] = []
    if explicit is not None:
        candidates.append(explicit.expanduser())
    else:
        discovered = shutil.which("yt-dlp")
        if discovered:
            candidates.append(Path(discovered))
        candidates.append(ROOT.parent / "twtalk_member_analyzer" / ".venv" / "bin" / "yt-dlp")

    for candidate in candidates:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate.resolve()
    if explicit is not None:
        raise ExtractionError(f"yt-dlp is not an executable file: {explicit}")
    raise ExtractionError("yt-dlp was not found on PATH or in twtalk_member_analyzer/.venv")


def youtube_search_target(query: str, max_results: int) -> str:
    cleaned = query.strip()
    if not cleaned:
        raise ExtractionError("YouTube search query cannot be empty")
    return f"ytsearch{max_results}:{cleaned}"


def metadata_command(yt_dlp: Path, target: str, max_results: int) -> list[str]:
    """Build a command that cannot request audio or video downloads."""

    return [
        str(yt_dlp),
        "--flat-playlist",
        "--playlist-end",
        str(max_results),
        "--skip-download",
        "--no-warnings",
        "--dump-single-json",
        target,
    ]


def _latin_token_match(text: str, keyword: str) -> bool:
    return bool(
        re.search(
            rf"(?<![A-Za-z0-9]){re.escape(keyword)}(?![A-Za-z0-9])",
            text,
            flags=re.IGNORECASE,
        )
    )


def matching_keywords(title: str, keywords: Iterable[str]) -> list[str]:
    matches: list[str] = []
    folded_title = title.casefold()
    for raw_keyword in keywords:
        keyword = raw_keyword.strip()
        if not keyword:
            continue
        if keyword.isascii() and any(character.isalnum() for character in keyword):
            matched = _latin_token_match(title, keyword)
        else:
            matched = keyword.casefold() in folded_title
        if matched and keyword not in matches:
            matches.append(keyword)
    return matches


def _integer_or_none(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _published_fields(entry: dict[str, Any]) -> tuple[str | None, str | None]:
    timestamp = entry.get("release_timestamp") or entry.get("timestamp")
    if isinstance(timestamp, (int, float)) and not isinstance(timestamp, bool):
        published_at = datetime.fromtimestamp(timestamp, UTC).isoformat().replace("+00:00", "Z")
        return published_at[:10], published_at

    upload_date = entry.get("upload_date")
    if isinstance(upload_date, str) and re.fullmatch(r"\d{8}", upload_date):
        return f"{upload_date[:4]}-{upload_date[4:6]}-{upload_date[6:]}", None
    return None, None


def normalize_entry(
    entry: dict[str, Any],
    *,
    discovery_label: str,
    keywords: Iterable[str],
) -> dict[str, Any] | None:
    video_id = entry.get("id")
    title = entry.get("title")
    if not isinstance(video_id, str) or not VIDEO_ID_PATTERN.fullmatch(video_id):
        return None
    if not isinstance(title, str) or not title.strip():
        return None

    matches = matching_keywords(title, keywords)
    if not matches:
        return None
    published_date, published_at = _published_fields(entry)
    return {
        "record_type": "youtube_news_video_metadata",
        "source_record_id": video_id,
        "platform": "youtube",
        "title": title.strip(),
        "channel_name": entry.get("channel") or entry.get("uploader"),
        "channel_id": entry.get("channel_id"),
        "channel_handle": entry.get("uploader_id"),
        "published_date": published_date,
        "published_at_utc": published_at,
        "duration_seconds": _integer_or_none(entry.get("duration")),
        "view_count": _integer_or_none(entry.get("view_count")),
        "live_status": entry.get("live_status"),
        "availability": entry.get("availability"),
        "matched_keywords": matches,
        "discovered_by": [discovery_label],
        "original_source_url": f"https://www.youtube.com/watch?v={video_id}",
        "collection_posture": "metadata_only_no_media_download",
        "evidence_posture": "discovery_only_not_verified_event_evidence",
    }


def records_from_payload(
    payload: dict[str, Any],
    *,
    discovery_label: str,
    keywords: Iterable[str],
) -> list[dict[str, Any]]:
    entries = payload.get("entries")
    if not isinstance(entries, list):
        raise ExtractionError("yt-dlp response does not contain an entries list")
    records: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        normalized = normalize_entry(
            entry,
            discovery_label=discovery_label,
            keywords=keywords,
        )
        if normalized is not None:
            records.append(normalized)
    return records


def merge_records(records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    by_video_id: dict[str, dict[str, Any]] = {}
    for incoming in records:
        video_id = incoming["source_record_id"]
        existing = by_video_id.get(video_id)
        if existing is None:
            by_video_id[video_id] = dict(incoming)
            continue

        for field in (
            "title",
            "channel_name",
            "channel_id",
            "channel_handle",
            "published_date",
            "published_at_utc",
            "duration_seconds",
            "view_count",
            "live_status",
            "availability",
        ):
            if existing.get(field) is None and incoming.get(field) is not None:
                existing[field] = incoming[field]
        for field in ("matched_keywords", "discovered_by"):
            existing[field] = list(dict.fromkeys([*existing[field], *incoming[field]]))

    return sorted(
        by_video_id.values(),
        key=lambda row: (
            row.get("published_at_utc") or row.get("published_date") or "",
            row["source_record_id"],
        ),
        reverse=True,
    )


def run_metadata_command(command: list[str], timeout_seconds: int) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        raise ExtractionError(f"yt-dlp metadata request timed out after {timeout_seconds}s") from exc
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "unknown yt-dlp error").strip()
        raise ExtractionError(f"yt-dlp metadata request failed: {detail[-1000:]}")
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise ExtractionError("yt-dlp returned malformed JSON") from exc
    if not isinstance(payload, dict):
        raise ExtractionError("yt-dlp returned a non-object JSON payload")
    return payload


def atomic_write_new(path: Path, payload: dict[str, Any]) -> None:
    if path.exists():
        raise ExtractionError(f"refusing to overwrite existing manifest: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temporary_name, path)
    except Exception:
        Path(temporary_name).unlink(missing_ok=True)
        raise


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Discover UFO/UAP news video metadata on YouTube; never download media."
    )
    parser.add_argument(
        "--query",
        action="append",
        default=[],
        help="YouTube search query; repeatable. Defaults to multilingual UFO/UAP news queries.",
    )
    parser.add_argument(
        "--channel",
        action="append",
        default=[],
        help="YouTube channel/videos URL to scan; repeatable.",
    )
    parser.add_argument(
        "--keyword",
        action="append",
        default=[],
        help="Required title keyword; repeatable. Defaults to UFO/UAP terms.",
    )
    parser.add_argument("--max-results", type=positive_int, default=25, help="Per query/channel limit.")
    parser.add_argument("--timeout", type=positive_int, default=120, help="Seconds per yt-dlp call.")
    parser.add_argument("--yt-dlp", type=Path, help="Explicit yt-dlp executable.")
    parser.add_argument("--output", type=Path, help="New immutable JSON manifest path.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the exact metadata-only request plan without contacting YouTube.",
    )
    return parser


def build_jobs(queries: Iterable[str], channels: Iterable[str], max_results: int) -> list[dict[str, str]]:
    jobs: list[dict[str, str]] = []
    for query in queries:
        cleaned = query.strip()
        if cleaned:
            jobs.append(
                {
                    "kind": "youtube_search",
                    "label": f"search:{cleaned}",
                    "target": youtube_search_target(cleaned, max_results),
                }
            )
    for channel in channels:
        cleaned = channel.strip()
        if not re.match(r"^https://(?:www\.)?youtube\.com/", cleaned, flags=re.IGNORECASE):
            raise ExtractionError(f"channel must be an HTTPS youtube.com URL: {channel}")
        jobs.append({"kind": "youtube_channel", "label": f"channel:{cleaned}", "target": cleaned})
    return jobs


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.query:
        queries = tuple(args.query)
    elif args.channel:
        queries = ()
    else:
        queries = DEFAULT_QUERIES
    keywords = tuple(args.keyword) if args.keyword else DEFAULT_KEYWORDS
    yt_dlp = resolve_yt_dlp(args.yt_dlp)
    jobs = build_jobs(queries, args.channel, args.max_results)
    if not jobs:
        raise ExtractionError("provide at least one --query or --channel")

    snapshot_id = utc_stamp()
    output = args.output or DEFAULT_OUTPUT_ROOT / f"{snapshot_id}.json"
    commands = [metadata_command(yt_dlp, job["target"], args.max_results) for job in jobs]
    plan = {
        "schema_version": SCHEMA_VERSION,
        "snapshot_id": snapshot_id,
        "network_contacted": False,
        "media_downloaded": False,
        "output": str(output.resolve()),
        "keywords": list(keywords),
        "jobs": [
            {
                "kind": job["kind"],
                "label": job["label"],
                "command": command,
            }
            for job, command in zip(jobs, commands, strict=True)
        ],
    }
    if args.dry_run:
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return 0

    collected: list[dict[str, Any]] = []
    for job, command in zip(jobs, commands, strict=True):
        payload = run_metadata_command(command, args.timeout)
        collected.extend(
            records_from_payload(
                payload,
                discovery_label=job["label"],
                keywords=keywords,
            )
        )

    records = merge_records(collected)
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "snapshot_id": snapshot_id,
        "collected_at_utc": utc_now().isoformat().replace("+00:00", "Z"),
        "source_id": "youtube_metadata_search",
        "network_contacted": True,
        "media_downloaded": False,
        "article_content_downloaded": False,
        "query_count": sum(job["kind"] == "youtube_search" for job in jobs),
        "channel_count": sum(job["kind"] == "youtube_channel" for job in jobs),
        "max_results_per_job": args.max_results,
        "keywords": list(keywords),
        "jobs": [{"kind": job["kind"], "label": job["label"]} for job in jobs],
        "record_count": len(records),
        "records": records,
    }
    atomic_write_new(output, manifest)
    print(output.resolve())
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ExtractionError as exc:
        raise SystemExit(f"error: {exc}") from exc
