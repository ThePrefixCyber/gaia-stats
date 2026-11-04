# Original site artwork and style

The classic landing page and both cohort modes use the same cover image that
Timothy Gladyshev displays on [gpstats.dev](https://gpstats.dev/). The centered
42em cover layout, dark image border, simple heading and yellow classic action
buttons follow the original page and its `/css/cover.css`. Existing statistical
controls and data calculations are retained.

## Cover image

- Original URL: https://gpstats.dev/img/gaia-project-cover.jpeg
- Local file: `web/art/gaia-project-cover.jpeg`
- Retrieved: 2026-11-04. Original bytes, 1920 × 1080, 476,664 bytes.
- SHA-256: `0a3c4fa255efb3324b49d4a314e5a66bd4ff6ae9df4dbd37429a2372cfd67496`
- Gaia Project illustration and graphic design: **Dennis Lohausen**.
- Publisher/rightsholder credited by the game: **Feuerland Spiele**.
- Credit source: [official Gaia Project rules, credits on page 3](https://www.feuerland-spiele.de/fileadmin/game/Gaia_Project/Regelbuch.pdf).

The upstream notebook project's README identifies its code as MIT-licensed.
That statement is not a separate license grant for this game illustration.
The image is restored here at the site owner's request, with its original
creator and publisher credited. Do not relicense it as this project's code.

## Original fog background

Tim's homepage initializes `VANTA.FOG` with highlight `0x59ff00` and midtone
`0xef00ff`. The shared presentation restores that same effect and color setup
with locally hosted, pinned copies of the libraries used by his page:

| Dependency | Exact upstream source | License |
| --- | --- | --- |
| Three.js r119 | https://cdnjs.cloudflare.com/ajax/libs/three.js/r119/three.min.js | MIT, three.js authors |
| Vanta 0.5.21 FOG | https://cdn.jsdelivr.net/npm/vanta@0.5.21/dist/vanta.fog.min.js | MIT, Teng Bao |

Full notices are retained in `web/art/vendor/three-LICENSE.txt` and
`web/art/vendor/vanta-LICENSE.txt`. The library files are unmodified.

The optional effect loads after the page is ready, never blocks statistics,
and stops when the cover is off-screen, the tab is hidden, or chart focus mode
is active. Reduced-motion users receive the static palette without loading
the animation libraries. A pause/resume control remembers the user's choice
for the session. The cover remains available if WebGL or scripts fail.

No analytics, donation widgets, third-party tracking scripts, or remote asset
requests from the original page are carried over. The original site's missing
`style.css` is not treated as a usable source. The live page, cover stylesheet,
cover asset and fog initialization were inspected directly on 2026-11-04.
