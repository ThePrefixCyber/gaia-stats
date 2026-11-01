Reduced public regression evidence, collected 2026-11-01. No usernames, user IDs,
presence, timestamps, or full raw dumps. Retains setup/round-one moves, VP-only ledger
changes, scoring markers, technologies, options, pregame Elo and results. Later moves
are omitted; indices are remapped for the retained setup/round-one events.

- https://boardgamers.space/api/gameplay/Admirable-falcon-401
  Original SHA256 7cbccd40bc8e9a2d943115877129d849ddfb10586c100fcecd8ce51f4e8d79e7
  Covers Darkanians and Space Giants.
- https://boardgamers.space/api/gameplay/Eclipsed-council-7948
  Original SHA256 c92a923d4a68b3b219a1a9da0722fb873fe3d7c23c29469a05a300e7e2f019e6
  Covers two-player 4-QIC variant; Tinkeroids and Hadsch Hallas.
- Listing fixtures retain only `_id` from saved public JSON arrays:
  https://boardgamers.space/api/game/status/ended?count=11&skip=0&boardgame=gaia-project&expansion=lost-fleet
  and skip=10. The last/first row overlap proves the UI's lookahead pagination.

These are parser regression examples, not a statistical sample to publish.
