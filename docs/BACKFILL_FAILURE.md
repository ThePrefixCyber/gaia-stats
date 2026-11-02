# Historical discovery failure: diagnosis and bounded mitigation

Production evidence supplied on 2026-11-02: base discovery reports HTTP 400,
checkpoint `[10010, 0]`, two pages read and zero new queue entries. The current
collector resumes at 9990, re-reads 9990 and 10000, then requests 10010. That
explains the repeated checkpoint and page count; it does not prove an API cap.

The collector already drains validated pending exports after a non-rate-limited
listing error. The refresh runner then aborts before publication on any listing
error. This explains increasing accepted archive counts with unchanged served
data. The existing immutable release remains valid.

Upstream inspected at commit
`67a5bb2970dc4f0b4e6747272a952182edee2613`:

- [Pagination validation](https://github.com/boardgamers/boardgamers-mono/blob/67a5bb2970dc4f0b4e6747272a952182edee2613/apps/api/app/routes/utils.ts#L83):
  nonnegative integer skip, count capped at 100; no 10,000 cap.
- [Listing implementation](https://github.com/boardgamers/boardgamers-mono/blob/67a5bb2970dc4f0b4e6747272a952182edee2613/apps/api/app/routes/game/listings.ts#L209):
  ended games sort by lastMove descending with ordinary skip/limit. No date or
  cursor parameter is exposed. User/search/duration filters are not evidence of
  a complete archival traversal strategy.

The deployed API version and actual production 400 body are not yet verified.
Direct BGS access is outside this executor's configured network allowlist;
no access settings were changed. No speculative cursor, offset reset, query
partitioning, or end-of-history assumption is introduced.

## Local mitigation

Record failed listing URL, requested offset, HTTP status, and at most 4096 bytes
of public response text in the collector summary persisted by refresh health.
On historical-listing HTTP 400 only, with no export retries and a clean newest
pass, permit the existing publisher to validate and atomically publish accepted
exports. Both rulesets still switch together and all preservation guards apply.

The refresh is explicitly `degraded`, retains its last fully successful refresh
time and release, records `last_publication` and `last_publication_release` only
when the pointer actually changes, and exits nonzero. An unchanged-input no-op
does not advance publication time. The failed pass
and checkpoint remain visible; history is still incomplete. Subsequent runs
continue normal paced head discovery and bounded queue draining. HTTP 400 is
retried only at the normal refresh cadence, not in an added retry loop. A full
clean run clears degradation normally. Head failures, export retries, other HTTP
errors, deadlines, and publication failures retain their existing failure path.

This mitigates stale serving data, not the unresolved deep-listing failure. A
bounded live comparison of offsets 9990/10000/10010 and the returned 400 body is
still required in the existing connected environment before changing pagination.
Do not declare full base-history coverage until traversal is verified.

No production changes or migration are performed by preparing this fix. Existing
SQLite checkpoints, raw exports, seed, legacy data, pacing and budgets remain.

Regression checks cover second-head-page failure for both modes, historical 400
with successful queue draining, failed/rejected queued exports, preserved prior
rows and raw/seed bytes, both-mode degradation, no-op publication metadata, and
clean recovery. An empty head page is a successful short traversal, not a failed
second page. Any error while reading a requested head page blocks publication.

Code-update health verification intentionally remains separate from archive
freshness: a healthy rebuilt root, expected code SHA and matching base/LF counts
pass even when refresh is degraded/stale. Count mismatches still fail. Thus the
existing polling updater will not roll back healthy code solely because deep
historical discovery is failing. No deployment verifier change is needed.
