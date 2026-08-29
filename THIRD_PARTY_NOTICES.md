# Third-party notices

The MIT licence in `LICENSE` covers the code in this repository. It does not
cover the third-party assets shipped alongside it, nor any data you collect with
these tools. Those keep the terms below.

## Assets in this repository

### NASA Blue Marble Next Generation — `map_app/assets/nasa_blue_marble_*.jpg`, `map_app/assets/earth_lod1/**`

Source
: NASA Earth Observatory, Blue Marble Next Generation with topography and
  bathymetry — <https://science.nasa.gov/earth/earth-observatory/blue-marble-next-generation/base-topography-bathymetry/>

Terms
: NASA content used in a factual manner that does not imply endorsement may be
  used without explicit permission. NASA must be acknowledged as the source.
  The NASA insignia may not be used. See
  <https://www.nasa.gov/nasa-brand-center/images-and-media/>.

### Natural Earth — `map_app/assets/ne_110m_land.geojson`, `map_app/assets/ne_50m_admin_0_countries.geojson`

Source
: Natural Earth vector release v5.1.2 — <https://www.naturalearthdata.com/>

Terms
: Public domain. Country outlines are a cartographic product at 1:50m and
  1:110m scale; they are not a legal boundary claim, and this project asserts no
  position on any territorial question.

## Data these tools collect

Nothing under `data/` is redistributed by this repository. Running `collect.py`
downloads records from the providers listed in `sources.json`, and each provider's
terms then apply to what you hold and to anything you publish from it.

The reviewed positions are recorded in `source_rights_targets.json` with their
evidence in `data/rights_review/`, and summarised in
`SOURCE_ADMISSION_REVIEW_20260830_ZH.md`:

| Source | Verdict | Terms |
| --- | --- | --- |
| UAPDrop | cleared for publication | CC BY 4.0, attribution to UAPDrop required |
| NASA/JPL fireball and ephemeris | cleared for publication | NASA media usage, acknowledge NASA |
| Global Meteor Network | cleared for publication | CC BY 4.0, cite the network and its papers |
| NARA | cleared per item | US federal works are public domain; donated holdings may be restricted |
| GEIPAN / CNES | local or educational use only | All rights reserved by CNES; extraction and derivative works are forbidden outside that exception, and each reproduction must carry the CNES notice |
| NUFORC | not cleared | Site blocks automated access; bulk extraction needs written permission |
| UFOSINT `ufo-dedup` | not cleared | No licence declared; upstream MUFON and CUFOS records restrict redistribution |

If you publish a build, `build_pages.py` re-checks this: every shipped file must
map to a licence, every record's source must be cleared, and every required
attribution must appear on the page. A build that fails the audit is deleted.

## Report text

Sighting descriptions shown on the map are the source's own wording, reproduced
verbatim. They are not rewritten, summarised or translated, and they remain the
work of whoever wrote them.

## OpenStreetMap

The optional 2D basemap requests tiles directly from the OpenStreetMap tile
servers when a viewer enables it. Those tiles are © OpenStreetMap contributors,
available under the Open Database Licence. A public deployment should stay within
the OpenStreetMap tile usage policy or serve its own tiles.
