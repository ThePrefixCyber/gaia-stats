import copy
import csv
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import urlopen

from gaia_stats.analysis import normalize, ruleset, select, summarize, skill_context
from gaia_stats.__main__ import ingest, handler_for

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name="Jubilant-rover-3041"):
    return json.loads((FIXTURES / (name + ".json")).read_text())


class AnalysisTests(unittest.TestCase):
    def test_real_games_reconcile_all_player_scores(self):
        rows = [r for path in FIXTURES.glob("*.json")
                for r in normalize(json.loads(path.read_text()))]
        self.assertEqual(len(rows), 14)
        self.assertTrue(all(r["score_verified"] for r in rows))
        self.assertEqual(sum(r["ruleset"] == "base" for r in rows), 4)
        self.assertEqual(sum(r["ruleset"] == "lost-fleet" for r in rows), 10)
        self.assertEqual({r["game_id"] for r in rows if r["score"] == 194}, {"Jubilant-rover-3041"})

    def test_base_and_expansion_never_mix(self):
        rows = normalize(fixture()) + normalize(fixture("cohort/Shiny-cypress-1384"))
        self.assertEqual(len(select(rows, {"ruleset": "base"})), 4)
        self.assertEqual(len(select(rows, {"ruleset": "lost-fleet"})), 4)
        for filters in ({}, {"ruleset": "all"}):
            with self.assertRaises(ValueError):
                select(rows, filters)

    def test_conflicting_or_unsupported_expansions_rejected(self):
        game = fixture()
        game["data"]["options"]["lostFleet"] = False
        with self.assertRaises(ValueError):
            ruleset(game)
        game = fixture()
        game["game"]["expansions"].append("unofficial-ships")
        with self.assertRaises(ValueError):
            ruleset(game)

    def test_base_factions_do_not_determine_ruleset(self):
        rows = normalize(fixture("Proper-outpost-7588"))
        self.assertEqual({r["faction"] for r in rows}, {"gleens", "ivits"})
        self.assertTrue(all(r["ruleset"] == "lost-fleet" for r in rows))

    def test_setup_builds_and_passive_charging_excluded(self):
        row = normalize(fixture())[0]
        self.assertNotIn("PI", row["build_order"])
        self.assertEqual(row["build_order"], "m → ts → lab → m → gf")
        self.assertTrue(any("spaceshipAction" in move for move in row["opening_moves"]))
        self.assertFalse(any(move.startswith("tinkeroids charge ") for move in row["opening_moves"]))
        self.assertEqual(len(select([row], {"ruleset": "lost-fleet", "official_center_sectors": "true"})), 1)

    def test_actual_rank_uses_net_score_not_bid_adjusted_score(self):
        rows = normalize(fixture("Modern-riddle-1723"))
        self.assertEqual([r["rank"] for r in rows], [1, 2, 3, 4])
        self.assertEqual([r["bid"] for r in rows], [0, 17, 18, 0])

    def test_ties_share_win_and_rank(self):
        game = fixture()
        for p in game["players"]:
            p["score"] = 200
        rows = normalize(game)
        self.assertEqual([r["rank"] for r in rows], [1, 1, 1, 1])
        self.assertEqual([r["win_share"] for r in rows], [.25] * 4)

    def test_unknown_vp_sources_preserved_and_score_mismatch_flagged(self):
        game = fixture()
        game["data"]["advancedLog"].append({"player": 0, "changes": {"future-artifact": {"vp": 7}}})
        row = normalize(game)[0]
        self.assertEqual(row["vp_sources"]["future-artifact"], 7)
        self.assertEqual(row["score_delta"], -7)
        self.assertEqual(select([row], {"ruleset": "lost-fleet"}), [])

    def test_incomplete_cancelled_dropped_solo_excluded(self):
        for change in [lambda g: g.update(cancelled=True),
                       lambda g: g.update(status="running"),
                       lambda g: g["players"][0].update(dropped=True),
                       lambda g: g["data"]["players"][0].update(isAutoma=True),
                       lambda g: g["data"].update(advancedLog=[])]:
            game = fixture()
            change(game)
            with self.assertRaises(ValueError):
                normalize(game)

    def test_conditional_filtering_and_small_sample_labels(self):
        rows = normalize(fixture())
        chosen = select(rows, {"ruleset": "lost-fleet", "faction": "tinkeroids",
                               "round1": "lfsector3", "technology": "advtech-qaction",
                               "opponent": "xenos", "min_elo": "250"})
        self.assertEqual(len(chosen), 1)
        self.assertFalse(summarize(chosen)[0]["enough_samples"])
        self.assertEqual(select(rows, {"ruleset": "lost-fleet", "round1": "score1"}), [])

    def test_all_skills_includes_unrated_and_top_players_use_pregame_elo(self):
        rows = normalize(fixture()) + normalize(fixture("Comfy-snail-3333"))
        rows[0]["elo"] = None
        self.assertEqual(len(select(rows, {"ruleset": "lost-fleet", "skill": "all"})), 8)
        top = select(rows, {"ruleset": "lost-fleet", "skill": "top"})
        self.assertEqual([r["elo"] for r in top], [415])
        custom = select(rows, {"ruleset": "lost-fleet", "skill": "custom", "min_elo": "400"})
        self.assertEqual(sorted(r["elo"] for r in custom), [411, 415])

    def test_top_threshold_is_stable_across_situational_filters(self):
        rows = normalize(fixture()) + normalize(fixture("Comfy-snail-3333"))
        filters = {"ruleset": "lost-fleet", "skill": "top"}
        threshold = skill_context(rows, filters)["thresholds"][4]
        self.assertAlmostEqual(threshold, 412.2)
        self.assertEqual(skill_context(rows, {**filters, "faction": "xenos", "round1": "score1"})["thresholds"][4], threshold)
        self.assertEqual(select(rows, {**filters, "faction": "xenos"}), [])
        # Base and two-player expansion ratings cannot move the four-player cutoff.
        more = rows + normalize(fixture("Modern-riddle-1723")) + normalize(fixture("Proper-outpost-7588"))
        context = skill_context(more, filters)
        self.assertEqual(context["thresholds"][4], threshold)
        self.assertAlmostEqual(context["thresholds"][2], 199.8)

    def test_top_rating_ties_included_and_unrated_only_has_no_top_results(self):
        rows = normalize(fixture())
        for row in rows:
            row["elo"] = 400
        self.assertEqual(len(select(rows, {"ruleset": "lost-fleet", "skill": "top"})), 4)
        for row in rows:
            row["elo"] = None
        self.assertEqual(select(rows, {"ruleset": "lost-fleet", "skill": "top"}), [])

    def test_table_strength_filter_matches_existing_notebook_approach(self):
        rows = normalize(fixture("Proper-outpost-7588"))
        self.assertEqual(rows[0]["table_elo"], 187)
        self.assertEqual(select(rows, {"ruleset": "lost-fleet", "skill": "all", "min_table_elo": "200"}), [])
        for filters in [{"skill": "top", "min_elo": "200"}, {"skill": "custom"},
                        {"skill": "custom", "min_elo": "nan"}, {"min_table_elo": "inf"}]:
            with self.assertRaises(ValueError):
                select(rows, {"ruleset": "lost-fleet", **filters})

    def test_ingest_deduplicates_and_reports_rejections(self):
        with tempfile.TemporaryDirectory() as folder:
            bad = Path(folder) / "bad.json"
            broken = fixture()
            broken["slug"] = "broken-ledger"
            broken["players"][0]["score"] += 5
            bad.write_text(json.dumps(broken))
            output = Path(folder) / "out.json"
            sample = FIXTURES / "Jubilant-rover-3041.json"
            ingest([sample, sample, bad], output)
            dataset = json.loads(output.read_text())
            self.assertEqual(len(dataset["rows"]), 4)
            self.assertEqual(len(dataset["rejected"]), 1)


class HTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        rows = normalize(fixture()) + normalize(fixture("cohort/Shiny-cypress-1384"))
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), handler_for({"rows": rows, "rejected": []}))
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def test_both_tabs_api_and_csv_are_separated(self):
        page = urlopen(self.url).read().decode()
        self.assertIn('role="tablist"', page)
        for version in ("base", "lost-fleet"):
            data = json.load(urlopen(self.url + "/api/analysis?ruleset=" + version))
            self.assertTrue(all(r["ruleset"] == version for r in data["rows"]))
            self.assertEqual(data["games"], 1)
            export = urlopen(self.url + "/api/export?ruleset=" + version + "&faction=xenos")
            records = list(csv.DictReader(io.StringIO(export.read().decode())))
            self.assertTrue(all(r["ruleset"] == version and r["faction"] == "xenos" for r in records))
            self.assertIn(version, export.headers["Content-Disposition"])

    def test_missing_ruleset_and_bad_filter_fail(self):
        for route in ("/api/analysis", "/api/export", "/api/analysis?ruleset=base&min_elo=oops"):
            with self.assertRaises(HTTPError) as exc:
                urlopen(self.url + route)
            self.assertEqual(exc.exception.code, 400)

    def test_top_players_api_and_export_use_same_subset(self):
        query = "?ruleset=lost-fleet&skill=top"
        data = json.load(urlopen(self.url + "/api/analysis" + query))
        records = list(csv.DictReader(io.StringIO(urlopen(self.url + "/api/export" + query).read().decode())))
        self.assertEqual(data["skill"]["mode"], "top")
        self.assertEqual([r["faction"] for r in records], [r["faction"] for r in data["rows"]])
        self.assertEqual([r["faction"] for r in records], ["moweyds"])


if __name__ == "__main__":
    unittest.main()
