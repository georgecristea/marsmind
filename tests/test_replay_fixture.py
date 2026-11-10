"""Replay a real 4-player online game with World Government Terraforming
(aliased) through the engine — the regression fixture for the app-log parser
and the card database.

Fixture: tests/fixtures/replay-4p-wgt/{applog.txt,setup.json,final-state.json}
— the online app's full log export of a 4-player game (base + Corporate Era,
WGT on; player names aliased) and the app's authoritative final state.

scripts/replay_applog.py rebuilds the game in a temp session by feeding every
log line to the Engine; every explicit "gained/lost/stole" line is treated as
truth and reconciled against what the card db did, each difference recorded
as a GAP. This test pins what the engine reproduces exactly (globals, TR,
tiles) and marks what it cannot yet (see the expectedFailure tests, whose
docstrings carry the observed-vs-expected numbers and the gap list) so the
discount / bespoke-card fixes turn them green.

REPLAY REPORT (observed by the replay at the time of writing — regenerate with
  scripts/replay_applog.py tests/fixtures/replay-4p-wgt/applog.txt \
      --setup tests/fixtures/replay-4p-wgt/setup.json --out /tmp/replay \
      --expect tests/fixtures/replay-4p-wgt/final-state.json):

  see REPORT_SNAPSHOT at the bottom of this file.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import applog_parser as P                      # noqa: E402
import replay_applog as R                      # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "replay-4p-wgt"
APPLOG = FIXTURE / "applog.txt"
SETUP = FIXTURE / "setup.json"
FINAL = FIXTURE / "final-state.json"

PLAYERS = ["Anna", "Carl", "Diana", "Ben"]

# The app's TileType enum values that occur in final-state.json, mapped to
# the engine's tile labels (board.json / db.json behavior.tile.type spelling).
APP_TILE = {0: "greenery", 1: "ocean", 2: "city", 4: "commercialdistrict",
            9: "miningrights", 10: "moholearea", 11: "naturalpreserve",
            12: "nuclearzone"}


# ── parser (pure functions, no I/O) ──────────────────────────────

class TestParserGrammar(unittest.TestCase):
    def ev(self, line):
        return P.parse_line(line, PLAYERS)

    def test_played_and_corp_are_the_same_verb(self):
        e = self.ev("Anna played Inventrix")
        self.assertEqual((e["kind"], e["player"], e["card"]),
                         ("played", "Anna", "Inventrix"))

    def test_generation_and_first_player(self):
        self.assertEqual(self.ev("Generation 3"), {"kind": "generation", "n": 3})
        e = self.ev("First player this generation is Diana")
        self.assertEqual((e["kind"], e["player"]), ("first_player", "Diana"))

    def test_gained_lines_normalise_resources(self):
        e = self.ev("Carl gained 2 titanium")
        self.assertEqual((e["kind"], e["resource"], e["n"]), ("gained", "titanium", 2))
        e = self.ev("Ben gained 4 M€")
        self.assertEqual((e["resource"], e["n"]), ("mc", 4))
        e = self.ev("Ben gained 4 TR")
        self.assertEqual((e["resource"], e["n"]), ("tr", 4))
        e = self.ev("Anna gained 1 plant")
        self.assertEqual(e["resource"], "plants")

    def test_gained_from_ocean_and_from_card(self):
        e = self.ev("Diana gained 2 M€ from 1 ocean(s)")
        self.assertEqual((e["kind"], e["resource"], e["n"], e["source"]),
                         ("gained", "mc", 2, "ocean"))
        e = self.ev("Anna gained 2 plants from Arctic Algae")
        self.assertEqual((e["resource"], e["n"], e["source"]),
                         ("plants", 2, "Arctic Algae"))

    def test_production_lines(self):
        e = self.ev("Ben gained 5 M€ production")
        self.assertEqual((e["kind"], e["resource"], e["n"]), ("gained_prod", "mc", 5))
        e = self.ev("Diana lost 2 M€ production")
        self.assertEqual((e["kind"], e["resource"], e["n"]), ("lost_prod", "mc", 2))
        e = self.ev("Diana lost 1 heat production because of Carl")
        self.assertEqual((e["kind"], e["resource"], e["n"], e["by"]),
                         ("lost_prod", "heat", 1, "Carl"))
        # corp / card effects credit their source (Saturn Systems on a
        # Jovian play) — the line is a gain like any other, not a gap
        e = self.ev("Anna gained 1 M€ production because of Saturn Systems")
        self.assertEqual((e["kind"], e["resource"], e["n"], e["source"]),
                         ("gained_prod", "mc", 1, "Saturn Systems"))
        e = self.ev("Ben gained 5 M€ production")
        self.assertIsNone(e["source"])

    def test_steal_and_removal(self):
        e = self.ev("Carl stole 1 energy production from Diana")
        self.assertEqual((e["kind"], e["resource"], e["n"], e["from"], e["prod"]),
                         ("stole", "energy", 1, "Diana", True))
        e = self.ev("Diana stole 3 M€ from Ben")
        self.assertEqual((e["kind"], e["resource"], e["n"], e["from"], e["prod"]),
                         ("stole", "mc", 3, "Ben", False))
        e = self.ev("Ben lost 4 plants because of Diana")
        self.assertEqual((e["kind"], e["resource"], e["n"], e["by"]),
                         ("lost", "plants", 4, "Diana"))

    def test_placed_tiles(self):
        e = self.ev("Carl placed ocean tile at 63")
        self.assertEqual((e["kind"], e["tile"], e["space"]), ("placed", "ocean", "63"))
        e = self.ev("Diana placed Nuclear Zone tile at 03")
        self.assertEqual((e["tile"], e["space"]), ("Nuclear Zone", "03"))

    def test_actions_and_standard_projects(self):
        e = self.ev("Diana used Equatorial Magnetizer action")
        self.assertEqual((e["kind"], e["card"]), ("used_action", "Equatorial Magnetizer"))
        e = self.ev("Carl used Power Plant:SP standard project")
        self.assertEqual((e["kind"], e["project"]), ("used_standard", "power_plant"))
        e = self.ev("Diana used Convert Heat standard action")
        self.assertEqual((e["kind"], e["project"]), ("used_standard", "convert_heat"))
        e = self.ev("Carl used Convert Plants standard action")
        self.assertEqual(e["project"], "convert_plants")
        e = self.ev("Diana used Sell Patents standard project")
        self.assertEqual(e["project"], "sell_patents")
        e = self.ev("Diana sold 1 patents")
        self.assertEqual((e["kind"], e["n"]), ("sold", 1))

    def test_milestone_award_wgt(self):
        e = self.ev("Ben funded Banker award")
        self.assertEqual((e["kind"], e["award"]), ("funded", "Banker"))
        e = self.ev("Diana claimed Builder milestone")
        self.assertEqual((e["kind"], e["milestone"]), ("claimed", "Builder"))
        e = self.ev("Anna acted as World Government and increased temperature")
        self.assertEqual((e["kind"], e["param"]), ("wgt", "temperature"))
        e = self.ev("Carl acted as World Government and increased oxygen level")
        self.assertEqual(e["param"], "oxygen")
        e = self.ev("Ben acted as World Government and placed an ocean")
        self.assertEqual(e["param"], "oceans")

    def test_cards_bought_drawn_kept(self):
        e = self.ev("Carl bought 2 card(s)")
        self.assertEqual((e["kind"], e["n"]), ("bought", 2))
        e = self.ev("You bought Power Supply Consortium,Bribed Committee")
        self.assertEqual((e["kind"], e["cards"]),
                         ("you_bought", ["Power Supply Consortium", "Bribed Committee"]))
        e = self.ev("Anna drew 3 card(s)")
        self.assertEqual((e["kind"], e["n"]), ("drew", 3))
        e = self.ev("Anna kept 5 project cards")
        self.assertEqual((e["kind"], e["n"]), ("kept", 5))

    def test_card_resources_and_misc(self):
        e = self.ev("Diana added 3 Microbe(s) to Nitrite Reducing Bacteria")
        self.assertEqual((e["kind"], e["n"], e["card"]),
                         ("card_resource", 3, "Nitrite Reducing Bacteria"))
        e = self.ev("Diana removed 3 resource(s) from Diana's Nitrite Reducing Bacteria")
        self.assertEqual((e["kind"], e["verb"], e["n"]), ("card_resource", "remove", 3))
        e = self.ev("Diana copied Nuclear Power production with Robotic Workforce")
        self.assertEqual((e["kind"], e["card"], e["via"]),
                         ("copied", "Nuclear Power", "Robotic Workforce"))
        self.assertEqual(self.ev("Final greenery placement")["kind"], "final_greenery")
        self.assertEqual(self.ev("Ben passed")["kind"], "passed")
        self.assertEqual(self.ev("Anna ended turn")["kind"], "ended_turn")
        self.assertEqual(self.ev("Good luck Anna!")["kind"], "ignore")
        self.assertEqual(self.ev("This game id was <gameId>")["kind"], "ignore")
        self.assertEqual(self.ev("some line the grammar has never seen")["kind"], "unknown")

    def test_every_fixture_line_is_recognised(self):
        events = P.parse_log(APPLOG.read_text(), PLAYERS)
        unknown = [e for e in events if e["kind"] == "unknown"]
        self.assertEqual(unknown, [], f"unrecognised lines: {unknown}")

    def test_blocks_merge_you_lines_and_wgt_ocean(self):
        events = P.parse_log(APPLOG.read_text(), PLAYERS)
        blocks = P.group_blocks(events)
        heads = [b["head"] for b in blocks]
        # "Carl bought 2 card(s)" + "You bought A,B" → one bought head with cards
        bought = next(h for h in heads if h["kind"] == "bought" and h["player"] == "Carl")
        self.assertEqual(bought["cards"], ["Power Supply Consortium", "Bribed Committee"])
        # WGT ocean: the "placed ocean tile at 13" line BEFORE the WGT line is its hex
        wgt_ocean = next(h for h in heads if h["kind"] == "wgt" and h["param"] == "oceans")
        self.assertEqual((wgt_ocean["player"], wgt_ocean["space"]), ("Ben", "13"))
        # no stray 'you_bought'/'you_drew' events survive grouping
        for b in blocks:
            for e in [b["head"], *b["tail"]]:
                self.assertNotIn(e["kind"], ("you_bought", "you_drew"))
        # the consequence lines of a play stay attached to it
        ice = next(b for b in blocks if b["head"].get("card") == "Ice Asteroid")
        self.assertEqual([e["kind"] for e in ice["tail"]],
                         ["placed", "gained", "placed", "gained"])
        # final greenery placements are their own blocks
        finals = [b for b in blocks if b["head"]["kind"] == "final_placed"]
        self.assertEqual([(b["head"]["player"], b["head"]["space"]) for b in finals],
                         [("Carl", "27"), ("Ben", "41")])


# ── the replay itself ────────────────────────────────────────────

class TestReplay4pWgt(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.report = R.replay(APPLOG, SETUP, Path(cls.tmp.name), verbose=False)
        cls.game = cls.report.game
        cls.final = json.loads(FINAL.read_text())

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def pool(self, name):
        g = self.game
        return g["me"] if g["me"]["name"] == name else g["opponents"][name]

    def test_every_line_was_consumed(self):
        self.assertEqual(self.report.unknown_lines, [])
        self.assertEqual(self.report.lines_seen, 595)

    def test_final_globals(self):
        exp = self.final["globals"]
        got = self.game["globals"]
        self.assertEqual(got["temperature"], exp["temperature"])
        self.assertEqual(got["oxygen"], exp["oxygen"])
        self.assertEqual(got["oceans"], exp["oceans"])
        # The app keeps the counter at 10 while it runs the final production
        # phase + final greenery placement; the engine's produce() closes the
        # generation (→ 11) and records gen 10 as the last history entry.
        self.assertEqual(self.game["generation"], exp["generation"] + 1)
        self.assertEqual(self.game["history"][-1]["generation"], exp["generation"])

    def test_tr_exact(self):
        got = {p: self.pool(p)["tr"] for p in PLAYERS}
        exp = {p: self.final["players"][p]["tr"] for p in PLAYERS}
        self.assertEqual(got, exp)

    def test_tiles_exact(self):
        """space id → (tile type, owner). Oceans are owned by nobody in the
        app (owner null) while the engine records the placer — normalised to
        None on both sides. The two RESERVED-AREA cities (01 Ganymede Colony,
        02 Phobos Space Haven) are off-map in board.json and place() rejects
        them; the engine represents them as the card in the owner's tableau,
        which is what we assert for those two."""
        exp_onmap, exp_offmap = {}, {}
        for sid, ttype, owner in self.final["tiles"]:
            label = APP_TILE[ttype]
            (exp_offmap if sid in ("01", "02") else exp_onmap)[sid] = (
                label, None if label == "ocean" else owner)
        got = {sid: (t["tile"], None if t["tile"] == "ocean" else t["player"])
               for sid, t in self.game["board"].items()}
        self.assertEqual(got, exp_onmap)
        reserved = {"01": "Ganymede Colony", "02": "Phobos Space Haven"}
        for sid, (label, owner) in exp_offmap.items():
            self.assertEqual(label, "city")
            self.assertIn(reserved[sid],
                          [c["name"] for c in self.pool(owner)["playedCards"]])

    def test_tableaux_exact(self):
        for p in PLAYERS:
            exp = [c for c in self.final["players"][p]["tableau"]][1:]  # [0] = corp
            got = [c["name"] for c in self.pool(p)["playedCards"]]
            self.assertEqual(got, exp, p)
            self.assertEqual(self.pool(p)["corporation"],
                             self.final["players"][p]["corp"], p)

    def test_milestones_and_awards(self):
        self.assertEqual(self.game["milestonesClaimed"],
                         {"Builder": "Diana", "Mayor": "Carl", "Terraformer": "Diana"})
        self.assertEqual(self.game["awardsFunded"],
                         {"Banker": "Ben", "Scientist": "Anna", "Landlord": "Carl"})

    # (d) production — exact per player. Every production change is an
    # explicit log line, so the reconciliation makes this exact by
    # construction; the gaps it needed are the engine's to-do list. The one
    # exception is Carl's energy production (next test).
    def test_production_exact(self):
        got = {p: dict(self.pool(p)["production"]) for p in PLAYERS}
        exp = {p: dict(self.final["players"][p]["production"]) for p in PLAYERS}
        got["Carl"].pop("energy")
        exp["Carl"].pop("energy")
        self.assertEqual(got, exp)

    @unittest.expectedFailure
    def test_carl_energy_production_fixture_anomaly(self):
        """FIXTURE ANOMALY, not an engine gap. The export shows Carl using
        the Power Plant SP three times (gens 1, 2, 3) and the app prints no
        production line for that SP, so the engine's +1 per use is trusted →
        engine 4. The app's final state says 3 — and its final heat 6 /
        energy 3 for Carl are only consistent with 3 (with 4 the heat pile
        would be 13). One of the three Power Plant lines left no trace (an
        undone action is the likely story). Observed: engine 4, app 3."""
        self.assertEqual(self.pool("Carl")["production"]["energy"],
                         self.final["players"]["Carl"]["production"]["energy"])

    # Stocks the export does account for: steel/titanium (the replay's
    # max-metal payment model, validated here — every player's final steel
    # and titanium match) and plants.
    def test_metal_and_plant_stocks_exact(self):
        for p in PLAYERS:
            for r in ("steel", "titanium", "plants"):
                self.assertEqual(self.pool(p)["resources"][r],
                                 self.final["players"][p]["resources"][r], (p, r))

    # (e) MC — the log never states what a card COST, only what was gained,
    # so the engine's MC drifts by exactly the discounts/rebates it does not
    # model. Ben (CrediCor: rebate modelled, no discount card) is exact and
    # asserted for real; the other three were the discount to-do list:
    #   Diana engine 58 vs app 61, 21 MC topped up → 24 MC unmodelled =
    #          Teractor −3 on 8 earth cards (Business Contacts, Nuclear Zone,
    #          Sponsors, Olympus Conference, Business Network, Cartel,
    #          Investment Loan, Import of Advanced GHG) — exactly 24.
    #   Anna   engine 39 vs app 41, 64 MC topped up → 66 MC unmodelled =
    #          Earth Catapult −2 on 26 cards (~50) + Space Station −2 on 5
    #          space cards (10) + Earth Office −3 (3) + Advanced Alloys.
    #   Carl   engine 54 vs app 55, 20 MC topped up → 21 MC unmodelled =
    #          ThorGate −3 (power tags + Power Plant SP), Research Outpost −1,
    #          Indentured Workers −8 — and the Power Plant anomaly above.
    def test_mc_ben_exact(self):
        self.assertEqual(self.pool("Ben")["resources"]["mc"],
                         self.final["players"]["Ben"]["resources"]["mc"])

    def test_mc_exact_after_discounts(self):
        """With corp/tableau discounts applied by the
        engine AND budgeted by the replay, Diana / Anna / Ben MC match the
        app exactly (top-ups fell from 99 MC to 6 for the whole game)."""
        for p in ("Diana", "Anna", "Ben"):
            self.assertEqual(self.pool(p)["resources"]["mc"],
                             self.final["players"][p]["resources"]["mc"], p)

    @unittest.expectedFailure
    def test_carl_mc_exact(self):
        """expectedFailure: Carl engine 69 vs app 55. The app's final state
        shows Immigrant City did NOT fire on Carl's own standard-project
        cities / off-Mars cities the way the engine's CITY_TRIGGERS assumes
        (+1 MC prod per city), so his income drifts +14 over the game.
        Open item: pin Immigrant City's exact trigger set against the app
        source (open follow-up)."""
        self.assertEqual(self.pool("Carl")["resources"]["mc"],
                         self.final["players"]["Carl"]["resources"]["mc"])

    @unittest.expectedFailure
    def test_heat_exact(self):
        """expectedFailure: Anna engine 14 vs app 9 — Local Heat Trapping's
        cost (spend 5 heat) is not in db.json; Carl engine 13 vs app 6 —
        the Power Plant anomaly above (leftover energy → heat)."""
        for p in PLAYERS:
            self.assertEqual(self.pool(p)["resources"]["heat"],
                             self.final["players"][p]["resources"]["heat"], p)

    def test_report_lists_gaps_with_card_names(self):
        kinds = {g["kind"] for g in self.report.gaps}
        self.assertTrue(kinds)                      # a perfect engine has none — yet
        for g in self.report.gaps:
            self.assertIn("what", g)
            self.assertIn("line", g)


REPORT_SNAPSHOT = """
=== REPLAY SUMMARY ===
lines: 595, gaps: 87, unknown lines: 0
globals: {'temperature': 8, 'oxygen': 14, 'oceans': 9} generation 11
  Diana  TR  45  res {'mc': 58, 'steel': 4, 'titanium': 3, 'plants': 4, 'energy': 0, 'heat': 7}  prod {'mc': 10, 'steel': 1, 'titanium': 3, 'plants': 2, 'energy': 0, 'heat': 3}  topups {'mc': 21}
  Anna    TR  27  res {'mc': 39, 'steel': 0, 'titanium': 1, 'plants': 3, 'energy': 3, 'heat': 14}  prod {'mc': 10, 'steel': 0, 'titanium': 1, 'plants': 2, 'energy': 3, 'heat': 4}  topups {'mc': 64}
  Carl    TR  29  res {'mc': 54, 'steel': 0, 'titanium': 0, 'plants': 3, 'energy': 4, 'heat': 13}  prod {'mc': 23, 'steel': 0, 'titanium': 0, 'plants': 4, 'energy': 4, 'heat': 0}  topups {'mc': 20}
  Ben     TR  31  res {'mc': 52, 'steel': 0, 'titanium': 1, 'plants': 4, 'energy': 4, 'heat': 6}  prod {'mc': 18, 'steel': 0, 'titanium': 1, 'plants': 4, 'energy': 4, 'heat': 2}
tiles: 34 on board

=== ENGINE vs APP FINAL STATE ===
  ok  temperature: engine 8 app 8
  ok  oxygen: engine 14 app 14
  ok  oceans: engine 9 app 9
  ok  Diana TR: engine 45 app 45
  DIFF Diana mc stock: engine 58 app 61 (net of top-ups 37)
  ok  Anna TR: engine 27 app 27
  DIFF Anna mc stock: engine 39 app 41 (net of top-ups -25)
  DIFF Anna heat stock: engine 14 app 9
  ok  Carl TR: engine 29 app 29
  DIFF Carl energy prod: engine 4 app 3
  DIFF Carl mc stock: engine 54 app 55 (net of top-ups 34)
  DIFF Carl energy stock: engine 4 app 3
  DIFF Carl heat stock: engine 13 app 6
  ok  Ben TR: engine 31 app 31
  tiles: DIFF missing ['01', '02'] extra []

=== GAPS (engine vs log) ===
-- db-tile (1)
  L308  Mining Rights: db has no behavior.tile for this special tile — type 'miningrights' inferred from the card name
-- emulated (41)
  L50   Equatorial Magnetizer action: no engine verb for blue-card action effects — −1 energy prod → +1 TR via prod/tr (the log prints only the prod loss)
  L65   Power Supply Consortium: stole 1 energy prod from Diana via attack/res/prod
  L90   Equatorial Magnetizer action: no engine verb for blue-card action effects — −1 energy prod → +1 TR via prod/tr (the log prints only the prod loss)
  L117  Hired Raiders: stole 3 mc from Ben via attack/res/prod
  L125  Power Infrastructure action: no engine verb for blue-card action effects — spent 3 energy for 3 MC (energy cost not in log)
  L131  Equatorial Magnetizer action: no engine verb for blue-card action effects — −1 energy prod → +1 TR via prod/tr (the log prints only the prod loss)
  L151  Space Mirrors action: no engine verb for blue-card action effects — paid 7 MC for +1 energy prod (cost not in log)
  L156  Power Infrastructure action: no engine verb for blue-card action effects — spent 1 energy for 1 MC (energy cost not in log)
  L173  Equatorial Magnetizer action: no engine verb for blue-card action effects — −1 energy prod → +1 TR via prod/tr (the log prints only the prod loss)
  L194  Power Infrastructure action: no engine verb for blue-card action effects — spent 3 energy for 3 MC (energy cost not in log)
  L203  Space Mirrors action: no engine verb for blue-card action effects — paid 7 MC for +1 energy prod (cost not in log)
  L217  Cloud Seeding: Diana −1 heat prod because of Carl via prod (decreaseAnyProduction not modelled)
  L238  Development Center action: no engine verb for blue-card action effects — spent 1 energy to draw (cost not in log)
  L249  SP sell_patents: sold 1 card(s) for 1 MC via res (card names not exported; standard(sell_patents) needs them)
  L260  Power Infrastructure action: no engine verb for blue-card action effects — spent 2 energy for 2 MC (energy cost not in log)
  L303  Development Center action: no engine verb for blue-card action effects — spent 1 energy to draw (cost not in log)
  L312  Water Import From Europa action: no engine verb for blue-card action effects — paid 12 MC (0 titanium modelled) → ocean via raise_param + place
  L329  Equatorial Magnetizer action: no engine verb for blue-card action effects — −1 energy prod → +1 TR via prod/tr (the log prints only the prod loss)
  L336  Power Infrastructure action: no engine verb for blue-card action effects — spent 3 energy for 3 MC (energy cost not in log)
  L340  Steelworks action: no engine verb for blue-card action effects — spent 4 energy → +2 steel + O2 step via res/raise_param
  L343  Martian Rails action: no engine verb for blue-card action effects — spent 1 energy for 3 MC (one per city on Mars)
  L364  SP convert_plants: O2 reached 8% → temperature +1 step for the raiser (not modelled outside wgt()) — applied via raise_param
  L377  Martian Rails action: no engine verb for blue-card action effects — spent 1 energy for 5 MC (one per city on Mars)
  L381  Nitrite Reducing Bacteria action: no engine verb for blue-card action effects — removed 3 microbes → +1 TR via tr(+1)
  L387  Steelworks action: no engine verb for blue-card action effects — spent 4 energy → +2 steel + O2 step via res/raise_param
  L390  Development Center action: no engine verb for blue-card action effects — spent 1 energy to draw (cost not in log)
  L393  SP sell_patents: sold 1 card(s) for 1 MC via res (card names not exported; standard(sell_patents) needs them)
  L402  SP sell_patents: sold 2 card(s) for 2 MC via res (card names not exported; standard(sell_patents) needs them)
  L406  Power Infrastructure action: no engine verb for blue-card action effects — spent 2 energy for 2 MC (energy cost not in log)
  L410  Equatorial Magnetizer action: no engine verb for blue-card action effects — −1 energy prod → +1 TR via prod/tr (the log prints only the prod loss)
  L464  Martian Rails action: no engine verb for blue-card action effects — spent 1 energy for 6 MC (one per city on Mars)
  L467  Equatorial Magnetizer action: no engine verb for blue-card action effects — −1 energy prod → +1 TR via prod/tr (the log prints only the prod loss)
  L469  SP sell_patents: sold 1 card(s) for 1 MC via res (card names not exported; standard(sell_patents) needs them)
  L472  Water Splitting Plant action: no engine verb for blue-card action effects — spent 3 energy → O2 step via raise_param
  L478  Development Center action: no engine verb for blue-card action effects — spent 1 energy to draw (cost not in log)
  L481  Power Infrastructure action: no engine verb for blue-card action effects — spent 2 energy for 2 MC (energy cost not in log)
  L540  SP sell_patents: sold 2 card(s) for 2 MC via res (card names not exported; standard(sell_patents) needs them)
  L551  Martian Rails action: no engine verb for blue-card action effects — spent 1 energy for 7 MC (one per city on Mars)
  L561  Equatorial Magnetizer action: no engine verb for blue-card action effects — −1 energy prod → +1 TR via prod/tr (the log prints only the prod loss)
  L564  SP sell_patents: sold 6 card(s) for 6 MC via res (card names not exported; standard(sell_patents) needs them)
  L571  SP sell_patents: sold 1 card(s) for 1 MC via res (card names not exported; standard(sell_patents) needs them)
-- mismatch (25)
  L127  Immigrant City: Carl mc production: engine +0, log +1 → corrected +1
  L179  WGT oceans: Anna plants stock: engine +0, log +2 → corrected +2 [log sources: Arctic Algae +2]
  L206  Comet: Anna plants stock: engine +2, log +4 → corrected +2 [log sources: Arctic Algae +2]
  L226  WGT oceans: Anna plants stock: engine +0, log +2 → corrected +2 [log sources: Arctic Algae +2]
  L241  Research Outpost: Anna mc stock: engine +0, log +2 → corrected +2
  L241  Research Outpost: Carl mc production: engine +0, log +1 → corrected +1
  L274  WGT oceans: Anna plants stock: engine +0, log +2 → corrected +2 [log sources: Arctic Algae +2]
  L290  Ganymede Colony: Anna mc stock: engine +0, log +2 → corrected +2
  L290  Ganymede Colony: Carl mc production: engine +0, log +1 → corrected +1
  L306  Mining Rights: Diana titanium production: engine +0, log +1 → corrected +1
  L312  Water Import From Europa action: Anna plants stock: engine +0, log +2 → corrected +2 [log sources: Arctic Algae +2]
  L357  Noctis City: Anna mc stock: engine +0, log +2 → corrected +2
  L357  Noctis City: Ben energy production: engine +0, log -1 → corrected -1
  L357  Noctis City: Carl mc production: engine +0, log +1 → corrected +1
  L372  SP city: Anna mc stock: engine +0, log +2 → corrected +2
  L395  Robotic Workforce: Diana energy production: engine +0, log +3 → corrected +3
  L395  Robotic Workforce: Diana mc production: engine +0, log -2 → corrected -2
  L438  SP city: Anna mc stock: engine +0, log +2 → corrected +2
  L444  Giant Ice Asteroid: Anna plants stock: engine -6, log -2 → corrected +4 [log sources: Arctic Algae +2, Arctic Algae +2]
  L458  Terraforming Ganymede: Ben TR: engine +0, log +4 → corrected +4
  L504  Open City: Anna mc stock: engine +0, log +2 → corrected +2
  L504  Open City: Carl mc production: engine +4, log +5 → corrected +1
  L530  Zeppelins: Carl mc production: engine +8, log +7 → corrected -1
  L557  Phobos Space Haven: Anna mc stock: engine +0, log +2 → corrected +2
  L557  Phobos Space Haven: Carl mc production: engine +0, log +1 → corrected +1
-- tile-counter (2)
  L127  Immigrant City: Carl cities counter moved 0 for 1 placed tile(s) — fixed to 1
  L357  Noctis City: Ben cities counter moved 0 for 1 placed tile(s) — fixed to 2
-- topup (18)
  L37   Wave Power: Anna mc 7 < 8 needed — topped up 1 (untracked discount/rebate/payment drift)
  L42   SP power_plant: Carl mc 5 < 11 needed — topped up 6 (untracked discount/rebate/payment drift)
  L69   Nuclear Zone: Diana mc 6 < 10 needed — topped up 4 (untracked discount/rebate/payment drift)
  L88   SP power_plant: Carl mc 6 < 11 needed — topped up 5 (untracked discount/rebate/payment drift)
  L136  SP power_plant: Carl mc 7 < 11 needed — topped up 4 (untracked discount/rebate/payment drift)
  L201  Olympus Conference: Diana mc 0 < 6 needed — topped up 6 (untracked discount/rebate/payment drift)
  L206  Comet: Anna mc 5 < 21 needed — topped up 16 (untracked discount/rebate/payment drift)
  L246  Deimos Down: Diana mc 26 < 28 needed — topped up 2 (untracked discount/rebate/payment drift)
  L264  Business Network: Diana mc 1 < 4 needed — topped up 3 (untracked discount/rebate/payment drift)
  L268  Fusion Power: Anna mc 5 < 14 needed — topped up 9 (untracked discount/rebate/payment drift)
  L319  Tundra Farming: Anna mc 6 < 16 needed — topped up 10 (untracked discount/rebate/payment drift)
  L328  claimed Builder: Diana mc 6 < 8 needed — topped up 2 (untracked discount/rebate/payment drift)
  L461  Imported Hydrogen: Anna mc 12 < 13 needed — topped up 1 (untracked discount/rebate/payment drift)
  L463  Advanced Alloys: Anna mc 0 < 9 needed — topped up 9 (untracked discount/rebate/payment drift)
  L473  Local Heat Trapping: Anna mc 0 < 1 needed — topped up 1 (untracked discount/rebate/payment drift)
  L490  Import of Advanced GHG: Diana mc 5 < 9 needed — topped up 4 (untracked discount/rebate/payment drift)
  L543  Mohole Area: Anna mc 3 < 20 needed — topped up 17 (untracked discount/rebate/payment drift)
  L567  SP asteroid: Carl mc 9 < 14 needed — topped up 5 (untracked discount/rebate/payment drift)
-- top-up totals per player
  Anna: {'mc': 64}
  Carl: {'mc': 20}
  Diana: {'mc': 21}
"""


if __name__ == "__main__":
    unittest.main()
