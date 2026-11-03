# Historical listing identifier correction

This records the first, leading-hyphen repair. The later evidence-based character
set and URL encoding update is documented in
[HISTORICAL_PUNCTUATION.md](HISTORICAL_PUNCTUATION.md); that update supersedes the
initial single-leading-hyphen restriction described below.

On 2026-11-03, base cursor discovery stopped after `Polite-mind-1174` at
`2021-12-15T14:34:58.633Z`, with 1712 committed pages and an incomplete cursor
checkpoint. The collector rejected the next page before advancing its queue or
cursor. Independently inspected public response evidence supplied by the connected
worker identifies row 10 (the last retained row of a ten-record page) as
`_id: -remote-Christmas-party`,
`endedAt: 2021-12-15T05:37:34.775Z`, status ended, base game. The page returned HTTP
200. Row 11, `Correct-heart-5433`, is the lookahead. The leading hyphen conflicts
with our old alphanumeric-first validator;
the listing itself is not evidence of a malformed game.

The fix shares one identifier validator between listing/cursor parsing, explicit
fetch filenames and release publication. It permits one leading hyphen followed
by an alphanumeric character, preserving the existing 121-character maximum and
the remaining ASCII letters/digits/underscore/hyphen vocabulary. Empty IDs,
hyphen-only IDs, leading underscores, multiple leading hyphens, slashes,
backslashes, dots, percent escapes, query/fragment delimiters, whitespace, control
characters and Unicode remain rejected. No identifier is renamed or sanitized.

The exact identifier is retained in the API URL, SQLite key, raw/provenance file,
cursor and published player-game rows. Manual use of the legacy explicit fetch CLI
requires its normal option separator, for example:

```sh
python -m gaia_stats fetch --directory /path/to/raw -- -remote-Christmas-party
```

No checkpoint reset, skipped page, changed eligibility, altered statistics or
new completion rule is needed. The retained checkpoint will retry the same page;
lookahead continuity and existing deduplication then apply normally. Existing
data and the historical seed remain untouched by preparing this code change.

Unknown identifier failures additionally report bounded diagnostic fields: page
index, ID field types, original lengths and at most 160 characters of each ID.
Other listing metadata is not copied into health diagnostics. A genuinely unsafe
or unknown identifier still stops discovery without queue/cursor advancement.
The refresh failure-isolation policy is unchanged: it is not broadened from
historical HTTP 400 to arbitrary validation failures. This resolves the confirmed
identifier defect directly rather than making an unverified page pass or treating
it as end-of-history.

Tests use the actual public ID and timestamp with a renamed existing normalized
fixture to exercise the reported retained-row boundary and next cursor, plus a
separate lookahead placement, cursor resume, export storage and publication.
They do not claim independent validation of the real historical gameplay export.
Direct BGS access remains outside this executor's configured network allowlist;
the actual listing evidence came from the connected worker. Traversal/length
regressions, CLI parsing, preserved prior identities and failure diagnostics are
covered locally. No production changes are performed here.
