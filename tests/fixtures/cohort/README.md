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

Phase-aware scoring regressions (normalization v2):

- Silly-rocket-2154: {"url": "https://boardgamers.space/api/gameplay/Silly-rocket-2154", "raw_sha256": "bfea249f49c126fe6e05f8019b07db859a56464b0a4146a4f997cbee1294f450", "reduction": "VP events and phase markers only; player identities and non-scoring moves removed"}

- Shiny-cypress-1384: {"url": "https://boardgamers.space/api/gameplay/Shiny-cypress-1384", "raw_sha256": "93404348fe02e77d597e914c14a91c3d44690ab842893bccbd6c4b268b05e3a7", "reduction": "VP events and phase markers only; player identities and non-scoring moves removed"}

- Vibrant-flagship-1713: {"url": "https://boardgamers.space/api/gameplay/Vibrant-flagship-1713", "raw_sha256": "16779c75a657a7056e9bb0c52b904e27bdb164d35736ae01376828874c9e4c71", "reduction": "VP events and phase markers only; player identities and non-scoring moves removed"}

The three existing LF fixtures now retain their original final `data.phase` value,
`endGame`, in addition to the already retained end-game log marker.
