# Gaia Stats

## Deploy on your Ubuntu VPS

For a fresh Ubuntu 24.04 VPS, run these commands in its SSH session:

```bash
sudo apt-get update
sudo apt-get install -y git
sudo git clone https://github.com/ThePrefixCyber/gaia-stats.git /opt/gaia-stats
sudo bash /opt/gaia-stats/deploy/install-vps.sh
```

The installer creates a restricted `gaia-stats` service account, installs the small
web dependency set in a virtual environment, configures Gunicorn with systemd,
and serves the app through Nginx on port 80. It permits SSH and HTTP/HTTPS before
enabling UFW. A Vultr firewall, if attached, must also allow inbound TCP 80/443
and your SSH access. It disables Ubuntu's default Nginx site symlink, not other
site configurations. Review `deploy/install-vps.sh` before running on a VPS that
already hosts other applications.

Open `http://YOUR_SERVER_IP/`. The service starts on boot and survives SSH
disconnects. The initial dataset contains only four verified examples. The
dataset and raw imports live in `/var/lib/gaia-stats`, outside the Git checkout,
and are preserved during code updates. Add a domain and HTTPS before adding
login credentials or private features; the initial explorer is public/read-only.

Pull additional finished games by their BGS slug:

```bash
sudo bash /opt/gaia-stats/deploy/pull-games.sh Jubilant-rover-3041 Comfy-snail-3333
```

Refresh the browser after importing; the dataset reloads automatically. Downloads
are paced and game IDs are deduplicated during import. Archive-wide discovery and
automatic scheduling remain future work.

Update code and restart without replacing data:

```bash
cd /opt/gaia-stats
sudo git pull --ff-only
sudo .venv/bin/pip install -r requirements-web.txt
sudo systemctl restart gaia-stats
```

Diagnostics: `sudo journalctl -u gaia-stats -n 50 --no-pager` and
`sudo systemctl status gaia-stats --no-pager`. Back up `/var/lib/gaia-stats`
outside this VPS. The optional Render configuration below is an alternative.

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/ThePrefixCyber/gaia-stats)

## Persistent browser deployment

Click **Deploy to Render**, sign in, authorize this repository and review the
Blueprint. It creates one paid always-on Python web service and a 1 GB persistent
disk. At the rates checked on 2026-11-01 this is about **$7.25/month**, before
additional usage or taxes; review Render's displayed price before deploying.
Render supplies HTTPS and an `onrender.com` URL, independent of the development
workspace. No VPS or custom domain is required. Commits to `main` automatically
redeploy this service.

The app uses Gunicorn, a read-only HTTP interface and the same analysis code as
the local explorer. The dataset is stored at `/var/data/gaia/analysis.json`, on
the persistent disk. The first boot seeds the four regression sample games only
when no dataset exists. Restarts and deploys preserve an existing dataset.
This is an initial small-data explorer, not yet a complete archive dashboard.

To pull additional **finished game slugs**, open the service's Render Shell:

```bash
python -m gaia_stats fetch Jubilant-rover-3041 Comfy-snail-3333 Proper-outpost-7588 Modern-riddle-1723 --directory /var/data/gaia/raw
python -m gaia_stats ingest /var/data/gaia/raw/*.json --output /var/data/gaia/analysis.json
```

Add more game slugs from the BGS finished-game list to the first command, then
repeat the second command over the entire raw directory. Downloads are sequential
and paced; unsupported or unreconciled games are reported and excluded. The
import atomically replaces the dataset and the app reloads it on the next request.
An entirely invalid import leaves the previous dataset intact. Back up raw files
and the normalized JSON externally as the archive grows; a persistent disk alone
is not a backup strategy. Raw exports are not exposed by the web app.

**Automatic discovery and scheduled archive refresh are not configured yet.**
The fetch command currently takes explicit game slugs. The inherited Selenium
notebook and historical name list remain available for later archive integration.

For local production-server checks:

```bash
pip install -r requirements-web.txt
GAIA_DATASET=data/analysis.json gunicorn 'gaia_stats.wsgi:create_app()' --bind 127.0.0.1:8000
```

![screenshot](https://user-images.githubusercontent.com/54454071/191138235-c8122774-90af-40db-a3ca-365aa44c5a8d.png)

Statistical analysis and texting service [web app](https://gpstats.dev) for a boardgame called Gaia Project. 

Gaia Project is a deterministic perfect-information multiplayer boardgame with a large statespace created by Jens Drögemüller and Helge Ostertag. 
The competitive euro-style game focuses on economy building, competition for actions/locations, 
and victory point accumulation.
This project aims to help (especially new) players analyze the validity of various approaches, develop strategies, and advance their skills.

This repo contains a set of Jupyter Notebooks presenting the code used to create the [app](https://gpstats.dev). These notebooks:
1. Scrape and parse Gaia Project game data from [boardgamers.space](https://www.boardgamers.space/boardgame/gaia-project)
2. Create interactive plots to show performance of various strategies
3. Send SMS turn reminder messages to users on their turn

[Game Rules](https://images.zmangames.com/filer_public/ce/89/ce890bfd-227e-4249-a52a-976bc5f20d19/en_gaia_rulebook_lo.pdf)

[Active Discord Community](https://discord.gg/KwFHt2DQ)

## Installation
```bash
pip install -r requirements.txt
```

## Base Game and Lost Fleet opening explorer

A new dependency-free Python 3.10+ analysis path lives in `gaia_stats/`.
It runs alongside the original notebooks. The deployed Flask app is not part of
this repository; the local explorer provides a separate integration surface.

```bash
# Smoke-test using four reduced, real public game exports (14 player records).
python -m gaia_stats ingest tests/fixtures/*.json --output data/analysis.json
python -m gaia_stats serve --dataset data/analysis.json
# Open http://127.0.0.1:8000
python -m unittest discover -s tests -v
```

For actual analysis, supply downloaded BGS game JSON files or the existing
newline-delimited `data/game_data_raw.txt` instead of the fixture glob.
The importer deduplicates games and reports rejected records in its output.
The sample collection is too small to recommend strategies.

The **Base Game** and **Lost Fleet** tabs have independent filters and CSV
downloads. Both API endpoints require an explicit `ruleset=base` or
`ruleset=lost-fleet`; there is no combined statistics mode. The parser uses
explicit BGS expansion flags, never faction names, and rejects unknown or
conflicting expansion configurations, cancelled/incomplete games, solo/Automa,
withdrawn players, and games with unreconciled score ledgers.

Each player record retains round-one build sequence and original opening moves,
the six round scorings, final scorings, available technologies, map configuration,
opponent factions, bid, Elo and expansion state. VP sources retain BGS identifiers
so new ship/artifact sources are not silently discarded. Final score is verified
against all logged VP changes plus the initial 10 VP. Actual net final scores
determine rank; ties share first-place credit. Bid is exposed separately.

The explorer includes **All skill levels**, **Top players** and **Custom Elo
cutoff** modes. All skill levels includes unrated records. Top players selects
records at or above the 90th percentile of pregame Elo, computed separately for
each ruleset and player count before faction/scoring filters. The threshold and
rated reference sample count are shown; ties are included. This is the top 10%
of player-game ratings in the imported dataset, not the top 10% of unique players
or a platform-wide leaderboard. Frequent players contribute multiple records.
Custom mode accepts a numeric minimum individual starting Elo. An additional
minimum **table-average Elo** filter preserves the approach used in
`stats_workbook.ipynb` (`MIN_AVG_ELO = 200`); it is independent of player-skill mode
and is off by default. Each ruleset tab remembers its own selections.

The explorer filters by faction, opponents, player count, scoring tiles,
technology, player skill, table-average Elo, layout, auction and balance settings. Opening groups
remain split by faction, player count, layout, auction and balance version.
It shows sample size, observed mean VP, win share and mean Elo; fewer than five
samples is labelled limited evidence. Five samples is a display threshold, not
a statistical significance claim. Results are descriptive, not causal estimates
or proven optimal openings. Elo filtering is not skill adjustment. Exact map
geometry and full opening actions are retained for later analysis; the current
groups compare building sequences, not complete action policies.

Next integration work: connect Tim's production archive/update job, add these
ruleset tabs to the deployed app, broaden fixtures to cover Darkanians and all
expansion mechanics, and add conditional comparisons for ship exploration,
artifacts, booster/technology choices and map geometry. Existing notebooks and
their base-game outputs remain unchanged.

## Notebooks

#### <a href="https://nbviewer.org/github/TimGladyshev/bgs_data_gaia/blob/master/texting_app.ipynb"><img src="https://img.shields.io/badge/nbviewer-texting__app-informational"/></a>
Working example of a simple Flask app that allows registration features, and a threaded texting service.
<br></br>
#### <a href="https://nbviewer.org/github/TimGladyshev/bgs_data_gaia/blob/master/fetch_names.ipynb"><img src="https://img.shields.io/badge/nbviewer-fetch__names-informational"/></a>
Uses Selenium to scrape names for all completed games. Names are used to create links to the game data api.
<br></br>
#### <a href="https://nbviewer.org/github/TimGladyshev/bgs_data_gaia/blob/master/fetch_jsons.ipynb"><img src="https://img.shields.io/badge/nbviewer-fetch__jsons-informational"/></a>
Fetches jsons from the game data [api](https://www.boardgamers.space/api/game/Modern-riddle-1723) and stores locally as raw json.
<br></br>
#### <a href="https://nbviewer.org/github/TimGladyshev/bgs_data_gaia/blob/master/parse_jsons.ipynb"><img src="https://img.shields.io/badge/nbviewer-parse__jsons-informational"/></a>
Parses json game data to pandas df and saves as pickle or csv.
<br></br>
### others:
Create the plotly figures for the site. 
* <a href="https://nbviewer.org/github/TimGladyshev/bgs_data_gaia/blob/master/advanced_techs.ipynb"><img src="https://img.shields.io/badge/nbviewer-advanced__techs-informational"/></a> : advanced technology tile frequency, impact on win probability/score
* <a href="https://nbviewer.org/github/TimGladyshev/bgs_data_gaia/blob/master/basic_tech.ipynb"><img src="https://img.shields.io/badge/nbviewer-basic__tech-informational"/></a> : standard technology tile tile frequency, impact on win probability/score
* <a href="https://nbviewer.org/github/TimGladyshev/bgs_data_gaia/blob/master/final_scorings_deltas.ipynb"><img src="https://img.shields.io/badge/nbviewer-final__scoring__deltas-informational"/></a> : final scoring tile impact on win probability/score
* <a href="https://nbviewer.org/github/TimGladyshev/bgs_data_gaia/blob/master/r1_strucs.ipynb"><img src="https://img.shields.io/badge/nbviewer-r1__structs-informational"/></a> : round one structures frequency and impact on score
* <a href="https://nbviewer.org/github/TimGladyshev/bgs_data_gaia/blob/master/round_scoring.ipynb"><img src="https://img.shields.io/badge/nbviewer-round__scoring-informational"/></a> : round scoring impact on win probability/score
* <a href="https://nbviewer.org/github/TimGladyshev/bgs_data_gaia/blob/master/scoring_methods.ipynb"><img src="https://img.shields.io/badge/nbviewer-scoring__methods-informational"/></a> : score distribution over possible sources and resulting position


## Contributing
Pull requests are welcome. For major changes, please open an issue first to discuss what you would like to change. I will add any new plots to the site.

## License
[MIT](https://choosealicense.com/licenses/mit/)
