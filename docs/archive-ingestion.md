# Local archive collector and Lost Fleet variant normalization

The collector is implemented and covered by mocked transport/listing/export tests.
It has not performed an external bulk fetch, configured a schedule, or written a
production dataset. Verify the listing envelope and pagination against the live
API before enabling a full run. Current supported listing shape is a JSON array
of objects with a `slug`; unknown envelopes fail explicitly, never as empty EOF.

```bash
python -m gaia_stats.archive --mode lost-fleet --directory /tmp/gaia-archive \\
  --page-size 10 --max-pages 100 --max-downloads 100 --interval 1
python -m gaia_stats.archive --mode base --directory /tmp/gaia-archive
```

Modes must be explicit. Discovery uses `/api/game/status/ended` with `count`,
`skip`, `boardgame=gaia-project`, plus `expansion=lost-fleet` for LF. The base
listing may include expansion games: full-export normalization rejects any mode
mismatch rather than mixing records. Full payloads come from `/api/gameplay/SLUG`.
No option-field or expansion classification is inferred from faction names.

## Persistence and pacing

- SQLite stores the discovered queue, acceptance/quarantine state, retries,
  source URLs, fetch times, hashes, and per-mode pagination checkpoints.
- Resumes overlap earlier pages to accommodate offset movement. Completed passes
  restart at the beginning and deduplicate IDs without redownloading previously
  accepted/rejected exports. No unverified newest-first ordering is assumed:
  incremental discovery conservatively scans pages again, not only a guessed
  recent window. It does not repeatedly load the entire raw archive.
- Default requests are paced by at least one second. Transient transport errors
  have bounded immediate retries and exponential persisted retry delays.
  Retry-After is honored; long delays defer to subsequent invocations. Server
  cooldowns prevent other queued requests, including the other mode, from
  ignoring a rate limit. A filesystem lock prevents concurrent collectors.
- Gzip responses are decoded with bounded compressed and decompressed size.
  Exact decoded response bytes are retained under `MODE/raw/SLUG.json`, alongside
  provenance and a SHA-256 matching those bytes. Normalized accepted rows are
  separate per-game JSON files. Rejected exports retain raw evidence and reasons.
- Solo, cancelled, dropped, unsupported expansion, mismatched mode/slug,
  conflicting metadata and unreconciled VP ledgers do not enter accepted rows.
- Queue insertion and page checkpoints commit together. Raw/normalized files are
  atomically installed. Disk failures propagate rather than claiming persistence.
  Existing accepted rows and the live `analysis.json` are not overwritten.

There is intentionally no production aggregation/publishing job or scheduler in
this milestone. Parser improvements may require an explicit future revalidation
command for quarantined exports; rejected entries are not automatically retried
as if they were network failures.

## Verified 4-QIC option contract

The documented BGS schema names `lostFleet2pQicTech`, with false default and
required Lost Fleet/two-player scope. Both `game.options` and `data.options` are
examined. Non-booleans or conflicting explicit values are rejected. Rows retain
`lf_2p_4qic_observed` (null if absent), `lf_2p_4qic_sources`, and an effective value
separately, so an omitted flag is not represented as observed false.

Selection accepts `lf_2p_4qic_mode`:

- `standard-only` (default): exclude two-player LF records explicitly enabling it.
- `include-both`: include standard and enabled-variant records.
- `variant-only`: only two-player LF records enabling it.

Base-game selections are unaffected. Numeric player-Elo and existing setup
filters compose with this mode. Top-Elo reference populations are calculated
within the selected variant mode; missing initial Elo remains null and is
excluded by numeric/top filters, but retained by all-skill mode. API records,
counts, summaries and CSV use the same selection; summaries keep mode groups
separate. API metadata reports mode and excluded-record count before other
filters. Deployment health verification explicitly includes both modes to compare
full dataset counts, independently of the user-facing default exclusion.

These controls are backend groundwork; the new LF chart/table UI is not yet
implemented. Tests use mutations of existing real exports to verify flag cases;
they are synthetic option cases, not claims that those games used the variant.
The named real variant examples and 30-export reference pack still require local
materialization and validation.
