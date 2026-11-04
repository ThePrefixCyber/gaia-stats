# Incremental storage validation, 2026-11-04

Scope: storage changes stacked on the reviewed pre-bid/eligibility, artwork and
Free-slot branches, plus the LF-only collector hotfix from main. No live data,
service settings, raw exports or production files were changed by this validation.

## Tests

The full Python suite covers parsing, eligibility, scoring, legacy plots, archive
cursor/failure paths, atomic releases, deployment and paired migration. Storage
regressions additionally check:

- Base raw collection changes never add/replace static base rows or move pointer.
- An added LF game normalizes once, allocates one object and shares base inode.
- Source no-ops and irrelevant legacy formatting do not create releases.
- Changed seed creates an independent base snapshot; prior bytes stay identical.
- Old merged base requires explicit CSV-only migration; archive-only records stay
  in the preserved old generation and LF identity preservation stays enforced.
- Missing unchanged LF raw and missing archive database preserve processed LF.
- Corrupt raw or processed objects, unsafe paths, broken hardlinks and interrupted
  swaps fail closed, without losing the selected release or deleting candidates.
- Standalone contract verification runs without importing app code, supports old
  inline and new indexed LF, checks every object and score, and version 2 rejects
  raw overlays even when their counts and scores are otherwise valid.

Independent code review found no blocking correctness/safety issue. Its two
storage caveats were handled or documented: migration copies only referenced LF
objects and accounts for their space; publication still validates existing data
and writes a small complete index, rather than claiming all CPU work is O(delta).

## Recorded real-data exercise

The complete committed historical four-player CSV was used, not synthetic rows:
`data/remote_four_players_data.csv`, SHA-256
`32d360bcc0e4896bba27ff6e936530274d18759abd33b2fcfac133b533e35432`.

With current pre-bid whole-game eligibility it yields 3,018 games and 12,072
player records; 2,669 source games are rejected by the importer. Every served
base payload exactly matched its CSV-built seed. Original CSV and raw hashes
were unchanged after the exercise.

Five eligible recorded public LF games supplied 16 player records. Adding the
last real game, `Eclipsed-council-7948`, produced:

- Exactly one raw normalization and one additional processed-game object.
- The same base inode and hash across generations.
- 75,800 bytes of additional unique file data, including the new release's
  manifest/index, instead of copying the 49,610,752-byte base database.
- Two release generations total; repeating unchanged publication created none.
- Successful base and LF statistics routes. Four-player responses reported
  3,018 base games / 12,072 records and 3 LF games / 12 records.

Local measurements: seed build 2.93 s, initial publication 1.14 s, one-game
incremental publication 1.64 s, unchanged publication 0.84 s. These are this test
machine's timings, not a VPS throughput or production-size promise. Small LF
indexes and manifests still grow with retained generations; the large datasets
are not duplicated each cycle.

## Remaining deployment checks

Actual production 2/3-player original CSVs are not in this checkout. They live in
the preserved VPS classic-cache paths listed in `PREBID_ROLLOUT.md`. Stage the
complete production bundle with those files and the production archive, compare
migration counts/hashes, run the exact candidate contract and verify both modes
before approval/activation. Observe a real LF refresh and no-op afterward.

No historical generations were cleaned up. That requires an exact inventory,
validated archive/rollback preservation, and separately approved permanent paths.
