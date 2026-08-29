#!/usr/bin/env python3
"""Parse a saved NARA UAP bulk-index page into a metadata-only manifest.

This intentionally has no network client.  A caller may give it an HTML file
saved from NARA's official UAP bulk page; it records the linked catalog JSON
and the *declared* ZIP artifact sizes.  It never fetches a JSON, ZIP, PDF,
image, video, or audio file.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from html.parser import HTMLParser
import hashlib
import json
from pathlib import Path
import re
import sys
import tempfile
from typing import Any
from urllib.parse import urljoin, urlparse


SCHEMA_VERSION = "nara.uap.metadata_manifest.v1"
DEFAULT_INDEX_URL = "https://www.archives.gov/research/catalog/catalog-bulk-downloads/uap-bulk-download"
METADATA_RE = re.compile(r"catalog-export-(?P<naid>\d+)\.json$", re.IGNORECASE)
SIZE_RE = re.compile(r"(?P<number>[0-9][0-9,]*(?:\.[0-9]+)?)\s*(?P<unit>KB|MB|GB|TB)\b", re.I)
SIZE_MULTIPLIERS = {
    "KB": 1_000,
    "MB": 1_000_000,
    "GB": 1_000_000_000,
    "TB": 1_000_000_000_000,
}


@dataclass(frozen=True)
class Link:
    href: str
    text: str


@dataclass(frozen=True)
class TableCell:
    text: str
    links: tuple[Link, ...]


@dataclass(frozen=True)
class MediaArtifact:
    url: str
    label: str
    declared_bytes: int | None


@dataclass(frozen=True)
class ManifestItem:
    naid: str
    title: str
    metadata_url: str
    media_artifacts: tuple[MediaArtifact, ...]
    online_status: str


class TableRowParser(HTMLParser):
    """Small tolerant HTML table parser; NARA's page is a sequence of rows."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[tuple[TableCell, ...]] = []
        self._current_cells: list[TableCell] | None = None
        self._text_parts: list[str] | None = None
        self._links: list[Link] | None = None
        self._link_href: str | None = None
        self._link_text_parts: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "tr":
            self._current_cells = []
            self._text_parts = None
            self._links = None
        elif tag in {"td", "th"} and self._current_cells is not None:
            self._text_parts = []
            self._links = []
        elif tag == "a" and self._text_parts is not None:
            href = dict(attrs).get("href")
            self._link_href = href if isinstance(href, str) else None
            self._link_text_parts = []

    def handle_data(self, data: str) -> None:
        if self._text_parts is not None:
            self._text_parts.append(data)
        if self._link_text_parts is not None:
            self._link_text_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._link_text_parts is not None:
            if self._link_href and self._links is not None:
                self._links.append(
                    Link(href=self._link_href, text=normalize_space("".join(self._link_text_parts)))
                )
            self._link_href = None
            self._link_text_parts = None
        elif tag in {"td", "th"} and self._text_parts is not None and self._current_cells is not None:
            self._current_cells.append(
                TableCell(
                    text=normalize_space("".join(self._text_parts)),
                    links=tuple(self._links or []),
                )
            )
            self._text_parts = None
            self._links = None
        elif tag == "tr" and self._current_cells is not None:
            if self._current_cells:
                self.rows.append(tuple(self._current_cells))
            self._current_cells = None
            self._text_parts = None
            self._links = None


def normalize_space(value: str) -> str:
    return " ".join(value.replace("\u00a0", " ").split())


def declared_size_bytes(value: str) -> int | None:
    match = SIZE_RE.search(normalize_space(value))
    if match is None:
        return None
    number = float(match.group("number").replace(",", ""))
    return round(number * SIZE_MULTIPLIERS[match.group("unit").upper()])


def absolute_https_url(href: str, base_url: str) -> str | None:
    absolute = urljoin(base_url, href)
    parsed = urlparse(absolute)
    if parsed.scheme != "https" or not parsed.netloc:
        return None
    return absolute


def item_from_row(row: tuple[TableCell, ...], base_url: str) -> ManifestItem | None:
    links: list[Link] = [link for cell in row for link in cell.links]
    normalized_links = [
        Link(href=absolute, text=link.text)
        for link in links
        if (absolute := absolute_https_url(link.href, base_url)) is not None
    ]
    metadata_link: Link | None = None
    naid: str | None = None
    for link in normalized_links:
        match = METADATA_RE.search(urlparse(link.href).path)
        if match is not None:
            metadata_link = link
            naid = match.group("naid")
            break
    if metadata_link is None or naid is None:
        return None
    media_artifacts = tuple(
        MediaArtifact(
            url=link.href,
            label=link.text,
            declared_bytes=declared_size_bytes(link.text),
        )
        for link in normalized_links
        if urlparse(link.href).path.lower().endswith(".zip")
    )
    title_link = next(
        (
            link
            for link in normalized_links
            if link.href != metadata_link.href and not urlparse(link.href).path.lower().endswith(".zip")
        ),
        None,
    )
    title = title_link.text if title_link is not None and title_link.text else ""
    if not title and len(row) >= 2:
        title = row[1].text
    return ManifestItem(
        naid=naid,
        title=title,
        metadata_url=metadata_link.href,
        media_artifacts=media_artifacts,
        online_status="online" if media_artifacts else "not_available_or_metadata_only",
    )


def parse_manifest_html(html: str, *, base_url: str = DEFAULT_INDEX_URL) -> list[ManifestItem]:
    parser = TableRowParser()
    parser.feed(html)
    parser.close()
    by_metadata_url: dict[str, ManifestItem] = {}
    for row in parser.rows:
        item = item_from_row(row, base_url)
        if item is None:
            continue
        existing = by_metadata_url.get(item.metadata_url)
        if existing is None:
            by_metadata_url[item.metadata_url] = item
            continue
        # The official page sometimes lists the same series in more than one
        # section. Prefer the occurrence with more explicitly linked artifacts.
        if len(item.media_artifacts) > len(existing.media_artifacts):
            by_metadata_url[item.metadata_url] = item
    return sorted(by_metadata_url.values(), key=lambda item: (int(item.naid), item.metadata_url))


def build_manifest_document(html: str, *, base_url: str = DEFAULT_INDEX_URL) -> dict[str, Any]:
    items = parse_manifest_html(html, base_url=base_url)
    media_artifact_count = sum(len(item.media_artifacts) for item in items)
    declared_media_bytes = sum(
        artifact.declared_bytes or 0
        for item in items
        for artifact in item.media_artifacts
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "network_contacted": False,
        "source_index_url": base_url,
        "input_html_sha256": hashlib.sha256(html.encode("utf-8")).hexdigest(),
        "stats": {
            "metadata_item_count": len(items),
            "media_artifact_count": media_artifact_count,
            "declared_media_bytes_known": declared_media_bytes,
        },
        "items": [asdict(item) for item in items],
    }


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    if path.exists() or path.is_symlink():
        raise RuntimeError(f"refusing to overwrite existing manifest: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        temporary_path = Path(handle.name)
        handle.write(
            (json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
        )
    temporary_path.replace(path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--html-file", type=Path, required=True, help="saved official NARA index HTML")
    parser.add_argument("--output", type=Path, required=True, help="new manifest JSON path")
    parser.add_argument("--base-url", default=DEFAULT_INDEX_URL)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        html = args.html_file.read_text(encoding="utf-8")
        manifest = build_manifest_document(html, base_url=args.base_url)
        atomic_write_json(args.output, manifest)
    except (OSError, RuntimeError, UnicodeDecodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(
        json.dumps(
            {"ok": True, "output": str(args.output), "stats": manifest["stats"]},
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
