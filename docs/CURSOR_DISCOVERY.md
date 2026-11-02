# Cursor discovery migration

The production HTTP 400 at offset 10010 explicitly says to use cursor pagination.
The older GitHub source does not describe the deployed contract. The following
evidence was supplied by the connected, independent inspection worker on
2026-11-02, using ordinary TLS and paced public requests:

- Deployed games-page node `18.DEGxwBSD.js` links
  [chunk 7ywATxp72.js](https://boardgamers.space/_app/immutable/chunks/7ywATxp72.js).
  Functions `jt` and `Mt` use `after=JSON.stringify({status:'ended',
  at:last.endedAt??null,id:last._id})` with `skip=0`.
- Requests reserve a lookahead row: desired count plus one, at most 100.
  The next token comes from the last retained row, not the extra row.
- Two live count=3 pages demonstrated lookahead continuity: the first page's
  third row, Blaring-sock-103-2-f475ef2c, became the second request's first row
  after Steady-brigantine-4121's cursor. All requests returned HTTP 200.
- A cursor after Fiery-horse-3056 at endedAt
  `2023-03-28T19:23:34.093Z`, obtained from offset 10000, returned older games
  successfully. This establishes that the cursor crosses the offset boundary.
- Hyper-shark-5522 has materially different endedAt and lastMove dates. Never
  derive this cursor from lastMove or an assumed legacy offset ordering.

## Local implementation

Refresh and the archive CLI now request cursor pages. The collector function's
default offset mode remains available for compatibility and its regression tests;
production refresh explicitly selects cursor mode. No deployment occurs merely
by preparing this change.

Each ruleset gets independent `cursor_scans` and `cursor_seen` records. Existing
`scans` offset checkpoints, exports, statuses, raw files and provenance are kept.
The first cursor pass starts at the head, regardless of the old offset checkpoint
or completion flag. Existing IDs deduplicate against the same archive queue.
This costs listing rereads but does not redownload already accepted games.

A page's retained entries and next token commit in one SQLite transaction.
Lookahead is not consumed or queued early: it is returned on the next page.
Restart resumes the last committed token. The two-page head pass uses its own
cursor starting at the head and does not change historical checkpoints; it still
prioritizes downloads from those head pages. Existing pacing, page/download
budgets, eligibility checks, mode separation and atomic release publication stay
in place. Cursor pages are limited to 99 retained records so count+1 never exceeds
the verified API cap.

Missing `_id`/`endedAt`, invalid timestamps, duplicate identities within a page,
repeated boundaries and revisited page tokens fail without advancing the page.
Explicit `endedAt:null` is supported and passed unchanged with its unique ID.
Missing endedAt is conservatively rejected rather than silently equated with
null until live evidence establishes that omission is intentional. Timestamp
strings are preserved, not reformatted. Tie ordering is left to the server's
composite cursor; no timestamp subtraction or invented ID ordering is used.

A successful response with no lookahead marks that traversal exhausted, including
an empty response. HTTP failures and malformed pages never imply exhaustion.
`cursor_checkpoint` exposes `(after_token, complete, pages)` separately from the
unchanged legacy `checkpoint`. Exhaustion means listing traversal exhausted, not
all queued exports accepted or universal historical coverage. Later passes restart
at the head after an exhausted traversal, resetting only cursor-cycle detection;
exports and old offset evidence remain. This also revisits games whose ending
metadata changes. Neither this API nor the current evidence establishes an
immutable archival snapshot, so concurrent updates remain a coverage limitation.

## Validation boundary

Local tests cover both modes, old-offset migration, deduplication, lookahead,
restart, head priority, transaction rollback, HTTP errors, invalid tokens/pages,
empty/exact-page exhaustion, and repeated-token cycles. Tied and null endedAt
values are tested with fixtures, not independently exercised against the live
API. The parent worker's supplied live evidence establishes non-null cursor
continuation and traversal beyond 10000. This executor made no live BGS requests.

No statistics, retention policy, access settings, timers or production data are
changed. Rollback can retain all cursor tables while older code ignores them.
