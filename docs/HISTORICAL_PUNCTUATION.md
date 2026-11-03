# Historical punctuation and safe export URLs

Production cursor discovery failed on `Gpit-round10[table-5]` after
`Bold-operation-5410` (`2021-08-26T03:06:57.799Z`). Independent connected inspection
confirmed normal-TLS HTTP 200 for the exact listing and
`https://boardgamers.space/api/gameplay/Gpit-round10%5Btable-5%5D`, matching `_id`
and export `slug`: noncancelled base game, round six, three players. This confirms
identity, not independent statistical eligibility. The ID is the zero-based
page-index 10 lookahead row; it must be retained for the following page, not skipped.

The old whitelist rejected its brackets. A scan of the committed upstream
`data/game_names.txt` at parent revision `4cb0c2a` found 35,441 distinct historical
names, maximum length 25, with twelve rejected by that whitelist:

```text
GPIT-Turn2-Table[7]
GPIT-TURN2-TABLE[5]
GIPT-TURN6-TABLE[004]
GIPT-TURN1-TABLE[005]
----------------------
GIPT-TURN10-TABLE[007]
GPIT-TURN9-TABLE9[2P]
GPIT-TURN5-TABLE[008]
GIPT-TURN03-TABLE[011]
Gpit-round10[table-5]
duker`s-private-game
GPIT-Turn2-Table[4]-
```

That is evidence for square brackets, a backtick and all-hyphen names in historical
data, not a complete contract for every BGS identifier. Only the reported bracketed
game was independently checked live for this repair. The other names are supported
by the committed historical list; no successful live export is claimed for them.

## Narrow correction

The shared validator retains a nonempty ASCII identifier of at most 121 characters,
starting with a letter, digit or hyphen. Remaining characters are letters, digits,
underscore, hyphen, square brackets or backtick. An all-hyphen identifier is valid.
Dots, path separators, percent signs, query/fragment delimiters, whitespace, control
characters, Unicode and other punctuation remain rejected. This does not allow
arbitrary opaque IDs or introduce a storage migration.

Both export download paths now percent-encode the entire identifier as one URL
path segment (`quote(..., safe='')`). Brackets become `%5B`/`%5D` and backticks
become `%60`. The original string remains the SQLite identity, cursor ID and
single local filename component; it is not sanitized, decoded or renamed.
Query encoding remains the existing `urlencode` over the cursor JSON. Publisher
validation uses the same whitelist, preventing a collector/publisher mismatch.
No game ID is interpolated into a shell command. Manual shell use must quote IDs
literally and use the CLI's `--` separator where required.

The explicit legacy fetcher now also checks returned `slug` equality before
writing a file, matching the archive collector's existing protection against a
different export response. Existing files remain intact on mismatch. The normal
score reconciliation and eligibility checks still decide whether an export enters
statistics; accepting a name does not automatically accept a game.

The retained cursor can retry the same page with no reset. Queue deduplication,
lookahead, transaction boundaries, pacing, cooldowns and publication guards are
unchanged. Unknown identifiers still fail without page advancement or a false
end-of-history claim. No new partial-publication exception is introduced.

## Checks and limitations

Regressions cover every name in the historical list, encoded requests, exact local
filenames/provenance, bracketed lookahead followed by retention and cursor restart,
publication and response-cache replacement, preserved seed/prior identities,
wrong-export rejection and malicious path/URL inputs. Integration tests use these
historical names on existing fixture gameplay; they do not claim to normalize the
real three-player export. The full archive may contain other character patterns
not represented in this historical list; those need evidence before expansion.

Direct BGS access remains outside this executor's enforced allowlist and the web
tool could not retrieve the API JSON. Live evidence came from the independent
connected worker; a public-profile search also corroborated the reported name.
No TLS bypass, credential, network, server, timer, retention or statistical change
is part of this repair.
