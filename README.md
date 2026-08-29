# Global UAP / sighting collection lab

![The 3D globe at 240 px/degree with country outlines, report clusters and source
attribution](docs/screenshot-globe.jpg)

*The globe with the optional 240 px/degree surface installed: Natural Earth
country outlines, UAPDrop sighting clusters, and every source credited in the
footer. Rendered locally — nothing on this view comes from a network service.*

This is a standalone, read-only collector for the user's global sighting-source
project.  It deliberately lives outside the trading-system code and does not
contact broker, cloud, SSH, or trading services.

It is designed for two different things:

1. preserve reports that a source explicitly makes available for batch use;
2. preserve the *source map* for the much larger set of archives, government
   collections, and local research groups that require permission or a manual
   record request.

The current worldwide source atlas is:

`../qagain_loop/docs/GLOBAL_UAP_USO_SOURCE_ATLAS_20260813_ZH.md`

## Commands

```bash
# Every de-duplicated source URL currently recorded in the atlas.
python3 uap_lab/collect.py sources --urls

# Full offline source table: URL, country/region context (when stated in the
# atlas), link label, atlas section, and admission posture.
# This reads only local Markdown/JSON and makes no network request.
python3 uap_lab/source_inventory.py export --format csv

# Optionally create a new CSV file. The exporter refuses to overwrite a file.
python3 uap_lab/source_inventory.py export --format csv --output /tmp/uap_source_inventory.csv

# The full 193-country A/B/C/D source-route table for a future map join.
# It reads only the local coverage ledger; it is not an event table or a rate.
python3 uap_lab/coverage_inventory.py export --format csv

# Optionally make a non-overwriting JSON file for a map or review workflow.
python3 uap_lab/coverage_inventory.py export --format json --output /tmp/uap_country_coverage.json

# Just the C/D countries that still lack a verified local first-party mother
# archive. This is a source-research queue, never a list of zero sightings.
python3 uap_lab/coverage_inventory.py gaps --format csv

# Offline source-admission queue: why every larger/global source is or is not
# eligible for a future connector. This never contacts any provider.
python3 uap_lab/collect.py review

# Network-free preflight: list exactly what would be fetched, the estimated
# bytes, per-response ceilings, and the run-wide hard budget.
python3 uap_lab/collect.py collect --all-open --dry-run

# Fetch the initial legal/open batch sources and compress raw snapshots.
python3 uap_lab/collect.py collect --all-open

# A narrow run is safer while validating a provider.
python3 uap_lab/collect.py collect --source uapdrop --source uap_observatory

# Refresh the eight planets plus Pluto (the historical nine-planet set) as
# Sun-centred/bodycentric reference controls for a specific UTC date.
python3 uap_lab/collect.py collect --source nasa_horizons_9_bodies --date 2026-08-13

# Rebuild a compact, map-ready nine-body reference table from an already saved
# and hash-verified Horizons snapshot.  This has no network client.
python3 uap_lab/ephemeris_export.py \
  --snapshot-id 20260813T010454984327Z \
  --dry-run
```

## Map application

```bash
# Validate every local asset (hashes each texture tile and release artifact),
# then serve the map read-only on the loopback interface.
python3 serve_map.py

# Reachable from another machine on the LAN, e.g. a browser outside WSL.
python3 serve_map.py --host 0.0.0.0 --port 8765
```

The globe is rendered with WebGL2 at device resolution and textured from a local
Blue Marble pyramid: the level is chosen each frame from the on-screen
pixels-per-degree demand, and only the tiles intersecting the current view are
requested. The shipped levels reach 60 px/degree.

### Optional high-resolution surface (240 px/degree)

The sharpest level is a separate download because it costs about 400 MB to fetch
and 330 MB on disk, so it is not shipped with the repository:

```bash
python3 earth_texture_500m.py --status      # is it installed?
python3 earth_texture_500m.py --install     # download, cut tiles, re-sign manifests
python3 earth_texture_500m.py --uninstall   # drop back to the shipped levels
```

The manifest declares the pack whether or not it is installed, so the map says a
sharper version exists instead of silently topping out, and the sidebar carries
the install command. **A page left open picks the pack up on its own** — install
it in a terminal and the globe switches to 240 px/degree without a reload.

### Texture pyramid

```bash
# Re-derive the shipped 15/30/60 px/degree levels from the native tiles and
# re-sign the manifests. Run this after changing any texture asset.
python3 earth_texture_lod.py

# Prepare the Natural Earth country outlines and labels.
python3 earth_country_layer.py
```

### Static build

```bash
# Assemble a publishable directory in dist/.
python3 build_pages.py --force
```

`serve_map.py` filters the release manifest, allow-lists every path and hash-checks
each asset at request time; a static host does none of that, so the build does it
ahead of time. It writes the public projection of the release manifest, leaves out
the optional texture pack, and then **audits itself**: every shipped file must map
to a licence rule, every record's `source_id` must have a rights verdict cleared
for publication, and every attribution those licences require must actually appear
on the page. A build that fails the audit is deleted rather than left on disk.

### Deploying the build

`dist/` is a plain static directory: any static host will serve it, and the app
needs no server-side code. It carries the shipped 60 px/degree levels and comes
to about 46 MB.

```bash
# 1. Collect and build the data, if you have not already.
python3 collect.py collect
python3 build_map.py

# 2. Assemble and audit the static build.
python3 build_pages.py --force

# 3. Publish dist/ as the gh-pages branch.
cd dist
git init -q && git add -A && git commit -qm "Publish map build"
git push -f git@github.com:<owner>/<repo>.git HEAD:gh-pages
```

Then set **Settings → Pages → Source** to the `gh-pages` branch, root folder.

Before you publish, three things are worth knowing:

- **Publishing makes the data public.** The audit only clears what the rights
  review has cleared; if you add a source, review it first with
  `source_rights_review.py` or the build will refuse to ship it.
- **GitHub Pages needs a public repository** on free plans. Serving a private
  project's build requires a paid plan, or a different host.
- **The 2D basemap sends viewers to the OpenStreetMap tile servers.** That is
  fine for casual traffic and already attributed; a busy site should serve its
  own tiles or ship with the 2D layer off.

Rebuild and repeat step 3 to update. The release data changes only when you
re-run `build_map.py`, so a texture or interface change is a small push.

## Licence

The code is MIT (`LICENSE`). The shipped assets and anything you collect are not:
see `THIRD_PARTY_NOTICES.md` for the NASA, Natural Earth and per-source terms,
and for which sources are cleared for publication.

## What is not in this repository

`data/` and `corpora/` are excluded. Raw snapshots, canonical records and built
releases are produced locally by `collect.py` and `build_map.py`; the video
corpora are third-party content that has not been through a rights review. The
optional 240 px/degree texture pack is excluded too — install it with
`earth_texture_500m.py --install`.

`map_app/assets/earth_lod1_manifest.json` and `basemap_manifest.json` are
generated and hold the digest of every texture tile, so installing the optional
pack rewrites them. Before committing, put them back in the shipped state:

```bash
python3 earth_texture_lod.py --exclude-optional   # manifest as a clone sees it
git add -A && git commit
python3 earth_texture_lod.py                      # restore your local pack
```

An open map page picks the pack back up on its own; no reload needed.

## Source rights review

Admitting a source is a rights decision before it is an engineering one.

```bash
python3 source_rights_review.py targets     # declared review targets and coverage
python3 source_rights_review.py probe       # fetch only licence/terms pages
python3 source_rights_review.py report      # verdicts beside their evidence
```

`probe` refuses to fetch a registry data endpoint or any path beneath one, so the
tool cannot be turned into a scraper. Each fetch leaves a receipt under
`data/rights_review/` with the HTTP status, byte count, content digest and the
clauses quoted verbatim. Verdicts stay human: the tool gathers evidence and flags
obvious signals, it never decides admission on its own. Findings live in
`SOURCE_ADMISSION_REVIEW_20260830_ZH.md`.

## YouTube UFO/UAP news discovery

The standalone YouTube extractor inventories public video metadata only. It
never downloads video, audio, subtitles, thumbnails, comments, or article
content. Results are discovery leads, not verified sightings or evidence of an
extraterrestrial origin.

```bash
# Show the exact multilingual search plan without contacting YouTube.
python3 uap_lab/youtube_news_extractor.py --dry-run

# Search YouTube and write a new immutable JSON discovery manifest.
python3 uap_lab/youtube_news_extractor.py --max-results 25

# Scan recent videos from a particular YouTuber/channel, retaining only titles
# that match the default UFO/UAP keywords.
python3 uap_lab/youtube_news_extractor.py \
  --channel 'https://www.youtube.com/@example/videos' \
  --max-results 50

# Supply narrower searches or title keywords. Both options are repeatable.
python3 uap_lab/youtube_news_extractor.py \
  --query 'UAP congressional hearing news' \
  --keyword UAP \
  --keyword UFO \
  --output /tmp/uap-youtube-news.json
```

By default, live manifests are written beneath
`uap_lab/data/discovery/youtube_news/`. The extractor refuses to overwrite an
existing manifest and records the search/channel provenance for duplicate
videos.

## Local speech-to-text

For media the user is authorized to process, `local_whisper_transcriber.py`
runs the existing local faster-whisper model and preserves source hashes,
timestamped raw ASR, a separate normalization view, and TXT/SRT/VTT exports.
It does not use YouTube captions as model output.

```bash
twtalk_member_analyzer/.venv/bin/python \
  uap_lab/local_whisper_transcriber.py /path/to/source.webm \
  --output-dir uap_lab/corpora/video/CHANNEL_ID/items/VIDEO_ID \
  --source-id VIDEO_ID \
  --title 'Video title' \
  --url 'https://youtu.be/VIDEO_ID' \
  --language en
```

The human-readable transcript is `transcript.en.txt`; `raw.jsonl` is the
source-of-truth ASR witness. Re-running normalization must create a separate
view and must not replace that raw witness.

The initial downloader plan has 12 requests (the nine planets are nine API
requests), an approximately 12.23 MB first-run estimate, source-specific
ceilings totalling 51.38 MB, and a 64 MiB run-wide default hard budget.  A
real run can use a smaller budget, for example:

```bash
python3 uap_lab/collect.py collect --source uapdrop --max-total-bytes 16777216
```

Raw responses are kept as immutable `.gz` files; canonical records are JSONL
gzip files; every run has a JSON receipt with original and compressed SHA-256
values.  The collector does not silently overwrite a prior identical payload.
Horizons is additionally sealed at one valid snapshot per UTC date, because its
response banner changes on each retry even if the ephemeris does not.

The Horizons collector records a historical set of eight planets plus Pluto
(which is scientifically classified as a dwarf planet) from a Sun-centred,
bodycentric reference.  It preserves Earth in the set, but it is **not** a
topocentric sky match: altitude and azimuth are explicitly `null`, and the
records cannot be counted as sightings or used to explain one.  After a saved
snapshot passes its local receipt audit, `ephemeris_export.py` writes a separate
`data/derived/ephemeris/.../ephemeris.jsonl.gz` product with RA/Dec, range,
observer mode, JPL API signature, raw hash, and a non-overwriting manifest.
See [the nine-body contract](NINE_BODY_EPHEMERIS_CONTRACT_20260813_ZH.md).

Both `--max-bytes` (one response) and `--max-total-bytes` (the whole run) are
enforced while streaming.  The source registry also records expected size,
request count, source-specific ceiling, and refresh cadence, so preflight does
not need a network request merely to answer how much a run may transfer.

For future approved large artifacts (for example a public SQLite export), the
collector also has a disk-streaming primitive: it writes to a temporary file,
enforces both budgets while hashing, rejects non-HTTPS redirects and existing
targets, then atomically exposes the artifact only after success. It is not
connected to any `*_REVIEW` source yet, so the review queue still makes no
network requests.

## Local map build

After a permitted collection has already been saved, build the map layer
without contacting any source:

```bash
python3 uap_lab/build_map.py --release-id local-map-v1
```

This writes immutable GeoParquet observation versions under
`data/derived/releases/local-map-v1/`, a privacy-filtered GeoJSON layer for
current sighting/control points, and a local DuckDB catalogue at
`data/warehouse/uap.duckdb`. The map builder keeps source observations and
candidate-event deduplication separate: a repeated source snapshot becomes one
current map point, while its older versions remain auditable.

Each generated gzip GeoJSON now has a relative path, feature count, compressed
byte count, and SHA-256 in the release manifest. Validate the selected release,
the layer-role separation, and the pinned Natural Earth basemap offline:

```bash
python3 uap_lab/serve_map.py --check
```

Open the read-only interactive map on the same machine:

```bash
python3 uap_lab/serve_map.py
```

Then visit `http://127.0.0.1:8765/map_app/`. It opens on a rotatable 3D globe
with a dark starfield and a locally pinned, hash-checked [NASA Earth Observatory
Blue Marble: Next Generation](https://science.nasa.gov/earth/earth-observatory/blue-marble-next-generation/base-topography-bathymetry/)
true-colour surface texture. The globe stays 3D while zooming in, so close
views retain the curved surface and its Earth texture. At close range it loads
only the intersecting local NASA 21,600-pixel texture tiles; it does not fetch
third-party imagery while the globe is in use. The browser app also supports
screen-space clustering, sighting versus astronomy-control toggles,
source/year/text filters, and source-traceable record details.

The optional 2D geographic view uses the public OpenStreetMap Standard raster
service in Web Mercator for road and city labels; the sidebar switch disables
network tiles and immediately falls back to the pinned Natural Earth land
silhouette. UAP and control data always come from this local release, never
from the basemap or NASA texture. Blue Marble is an overview composite rather
than current imagery; the footer provides NASA Earth Observatory attribution
and the asset manifest records the checksum and source URL.

The OSM client requests only tiles intersecting the visible viewport, relies on
normal browser HTTP caching, exposes no prefetch/offline-download feature, sends
a non-restrictive origin referrer, and keeps the required `© OpenStreetMap
contributors` link visible. These constraints follow the [OSMF tile usage
policy](https://operations.osmfoundation.org/policies/tiles/) and [OSM copyright
and licence page](https://www.openstreetmap.org/copyright). The public tile
service is best-effort; when it is unavailable, the map remains usable with the
local Natural Earth fallback. Screen clusters are a display aid, not
candidate-event deduplication or H3 statistics.

To make the map reachable from another machine on a trusted network, bind all
interfaces explicitly:

```bash
python3 uap_lab/serve_map.py --host 0.0.0.0 --port 8765
```

The server uses an allowlist: only the map application, pinned basemap, current
release manifest, two current map layers, and the public architecture note are
served. Raw evidence, receipts, canonical files, the DuckDB warehouse, and
transcripts remain unreachable. There is no authentication or TLS, so do not
expose this development server directly to the public Internet.

## Local receipt integrity audit (offline)

Verify the saved raw/canonical gzip byte sizes, SHA-256 hashes, canonical row
counts, and nine-body Horizons coverage without contacting any provider:

```bash
python3 uap_lab/audit_data.py audit
```

The auditor does not alter data. It reports immutable snapshot versions and
separate unique `source_id + source_record_id` counts, so an old duplicate
snapshot is visible rather than silently treated as another planet or sighting.

## NARA metadata manifest (offline)

If an official NARA UAP bulk-index page has been saved locally, turn it into a
reviewable list of metadata JSON and *declared* ZIP sizes without fetching any
linked artifact:

```bash
python3 uap_lab/nara_manifest.py \
  --html-file /path/to/saved-nara-uap-index.html \
  --output /path/to/new-nara-metadata-manifest.json
```

The command has no URL option by design. It will not download JSON, ZIP, PDF,
image, video, or audio content, and it refuses to overwrite a manifest.

## UFOSINT local adapter (offline)

The large UFOSINT SQLite artifact remains in the review queue and is **not**
downloaded by `collect.py`.  If a separately approved, locally present copy is
ever supplied, inspect its schema/count only—without exporting any event—via:

```bash
python3 uap_lab/ufosint_adapter.py inspect --database /approved/path/ufo_public.db
```

`ufosint_adapter.py` has no URL or network client. Its local record iterator is
tested against a SQLite fixture and uses the stable
`source_db_id:source_record_id` provenance key. It deliberately omits long
narratives, raw JSON, witness fields, and raw location text; all map
coordinates are rounded to a 0.1-degree privacy grid. A future streaming
acquisition connector still needs an explicit source/licence decision and may
not be enabled by `--all-open`.

## GEIPAN header contract (offline)

The official French GEIPAN source consists of related case and
testimony/observation CSVs.  Before any future import, inspect **only the
first header line** of locally supplied files:

```bash
python3 uap_lab/geipan_schema.py inspect \
  --cases-csv /approved/path/Base_de_donnees_des_cas.csv \
  --testimonies-csv /approved/path/Base_de_donnees_des_temoignages.csv
```

This makes no network request and reads zero event rows. It records delimiter,
encoding, field names, potential case-key aliases, and privacy-named headers;
it will not guess a case-to-testimony join when the relation is unclear. The
official CSV data are still `OPEN_BATCH_REVIEW`, so this inspection alone does
not authorize collection or normalisation.

## Global Meteor Network query plan (offline)

GMN is a CC BY 4.0 meteor-trajectory control source, not an UFO source. Its
planner generates a single bounded Datasette request but never sends it:

```bash
python3 uap_lab/gmn_query_plan.py plan \
  --after-updated-at 2026-08-01T00:00:00Z \
  --until-updated-at 2026-08-02T00:00:00Z \
  --page-size 500
```

It selects only the trajectory fields needed for natural-phenomenon controls,
limits a window to 31 days and 1,000 rows, and uses the composite
`updated_at + unique_trajectory_identifier` cursor. It is still in review:
the generated URL must first pass an approved one-page endpoint/schema probe;
the planner itself has no network client.

## Spain Defence METS manifest (offline)

Spain's official declassified UFO catalogue exposes a per-record METS action.
If a METS XML record is separately saved locally, parse its metadata and file
references without following any page-image URL:

```bash
python3 uap_lab/spain_mets_manifest.py parse \
  --mets-file /approved/path/item.mets.xml \
  --output /approved/path/item.manifest.json
```

The parser accepts only local XML, rejects DTD/entity declarations, hashes the
input, and refuses output overwrite. It cannot acquire a METS file or an image;
the Spanish source remains `METADATA_BATCH_REVIEW` until its catalogue access
contract is explicitly validated.

## Global URL inventory (offline)

Export every URL recorded in the global atlas—including sources that are not
permitted for automated collection—while retaining country/region context when
the atlas row states one, its atlas section, label, and registry posture:

```bash
python3 uap_lab/source_inventory.py export --format json
python3 uap_lab/source_inventory.py export --format csv --output /approved/path/uap-source-urls.csv
```

This is source bookkeeping only: `registry_managed` means an entry is tracked
in `sources.json`, not that it can be downloaded. `atlas_reference_only` means
it remains a discovered source/rights/control reference awaiting admission.

## Source-atlas recovery handoff (offline)

The source-discovery work has a durable handoff, so a later session does not
need to infer state from chat history or re-run broad web searches.  Start from
these documents, in this order:

1. `../qagain_loop/docs/GLOBAL_UAP_USO_SOURCE_ATLAS_20260813_ZH.md` — every
   verified parent/archive/control URL and its allowed posture.
2. `COUNTRY_SOURCE_GAP_QUEUE_20260813_ZH.md` — country-by-country leads and
   reproducible negative searches; append a result here before revisiting a
   gap.
3. `COUNTRY_SOURCE_RESEARCH_ROOTS_20260813_ZH.md` — the durable 35-country
   C/D research-route table. It separates verified local archive roots from
   unverified public roots, and does not promote any country by itself.
4. `GLOBAL_COUNTRY_COVERAGE_LEDGER_20260813_ZH.md` — the 193-member-country
   A/B/C/D availability ledger. `coverage_inventory.py export` turns this
   ledger into a no-network JSON/CSV map join table and rejects a stale
   regional snapshot.
5. `SOURCE_ADMISSION_QUEUE_20260813_ZH.md`,
   `STORAGE_AND_BANDWIDTH_ESTIMATE_20260813_ZH.md`, and
   `DATA_ARCHITECTURE_FOR_MAP_20260813_ZH.md` — connector gate, storage
   boundary, and map contract.

Baseline at 2026-08-13 (Asia/Taipei):

| Ledger item | Current value | Meaning |
| --- | ---: | --- |
| Distinct atlas URLs | 419 | URL inventory, **not** downloaded records |
| Registry-managed URLs | 34 | Tracked in `sources.json`; not an access grant |
| Atlas-only references | 385 | Discovery/right/control references awaiting admission |
| Country availability | A 41 / B 144 / C 0 / D 8 | 193 UN members; `C+D=8` have no verified local qualifying route |

Useful no-network checkpoints are:

```bash
python3 uap_lab/source_inventory.py export --format json
python3 uap_lab/coverage_inventory.py export --format json
python3 uap_lab/coverage_inventory.py gaps --format json
python3 uap_lab/collect.py sources --urls | wc -l
git -C qagain_loop diff --check
```

When a search finds only a generic national archive, press coverage, a forum,
an individual story, a global map, or a foreign/international document, record
the negative result in the gap queue and **do not** promote that country.  A
country becomes A or B only after a local owner plus a UAP-specific report,
catalogue, finding aid, or formal request route is verified.  Country A/B/C/D
is source availability only; it must never be converted automatically into a
rate or `P_report` (reported-phenomenon probability) value.  No source is a
download target until the admission, rights, privacy, and duplicate-source
gates have all passed.

## Phenomainon bounded research plan (offline)

Phenomainon is an aggregation/deduplication reference, not an independent
sighting feed. Its MCP API needs an `X-API-Key`; generate a no-contact plan
without placing a key anywhere in the repository:

```bash
python3 uap_lab/phenomainon_query_plan.py overview
python3 uap_lab/phenomainon_query_plan.py stats --group-by country
python3 uap_lab/phenomainon_query_plan.py search --country US --shape triangle --limit 25
```

Only overview, aggregate stats and a 100-record-max structured search are
available. A future approved research query must retain the original cited
catalogs and cannot be treated as a bulk export or an additional event count.

## Boundary

`OPEN_BATCH` means that the source has a public endpoint *and* a normalizer
implemented and tested here. `OPEN_BATCH_REVIEW` means a documented public
artifact exists but its normalizer, licensing, privacy filter, or streaming
contract still needs review; it cannot be bulk-fetched. `METADATA_BATCH_REVIEW`
means only the official catalogue/manifest may eventually be collected, never
the associated document or video bundles by default. `OPEN_QUERY`,
`ARCHIVE_REQUEST`, `INDEX_ONLY`, and `EXPERIMENTAL` sources are likewise listed
but intentionally cannot be bulk-fetched by this program. In particular, this
prevents accidental scraping of NUFORC, MUFON, national archives, local
investigator sites, or witness media where the site terms, privacy rights, or
copyright need a separate permission.

The astronomy data are a false-positive/control layer, not UAP evidence.
Likewise the word “unexplained” means only that the available record lacks a
settled explanation; it does not identify an object as extraterrestrial.
