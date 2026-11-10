"""THE REGRESSION GATE (scripts/replay_gate.py) over REAL games.

Two layers:

1. Every game the gate can find is replayed and checked. The app-log games
   (the online game night, the autopilot games rebuilt from the vendor's own
   game.db) must reproduce the app's BOARD, TR, globals, milestones and
   awards exactly; the event-log games (the physical / early practice
   sessions, log.md only) must not contain an event shape today's engine
   has stopped accepting. Every real-game log lives under private/ or in a
   vendor checkout, so each of those tests SKIPS when its files are absent —
   nothing private is ever copied into the repository or into a fixture.

2. One unit test per defect the gate exposed, each built from the exact log
   lines that produced it, so the fix cannot silently regress. They use tiny
   synthetic logs, no private data.
"""
import json
import sys
from collections import defaultdict
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import applog_parser as P                      # noqa: E402
import replay_applog as R                      # noqa: E402
import replay_gate as G                        # noqa: E402
import tmlib                                   # noqa: E402
from tmlib import Engine, EventError, Store    # noqa: E402


# ── helpers for the synthetic-log unit tests ─────────────────────

def make_setup(players, expansions=("base", "corporateEra")):
    colors = ["green", "red", "yellow", "orange", "blue"]
    return {
        "playerCount": len(players),
        "players": [{"name": n, "color": colors[i], "isMe": i == 0,
                     "aliases": []} for i, n in enumerate(players)],
        "expansions": list(expansions),
        "map": "tharsis", "draft": False, "houseRules": [],
        "seatingOrder": list(players), "firstPlayerGen1": players[0],
        "gameMode": "app-practice",
    }


def run_log(text, players, expansions=("base", "corporateEra")):
    """Replay a synthetic app log; returns (game state, Report)."""
    setup = make_setup(players, expansions)
    tmp = tempfile.TemporaryDirectory()
    try:
        store = Store(Path(tmp.name))
        store.init(json.loads(json.dumps(setup)))
        eng = Engine(store)
        rep = R.Report()
        events = P.parse_log(text, list(players))
        rep.lines_seen = len(text.splitlines())
        R.Replayer(eng, rep, verbose=False).run(P.group_blocks(events))
        return rep.game, rep
    finally:
        tmp.cleanup()


def pool_of(game, name):
    return game["me"] if game["me"]["name"] == name else game["opponents"][name]


def fresh_engine(players, expansions=("base", "corporateEra")):
    tmp = tempfile.TemporaryDirectory()
    store = Store(Path(tmp.name))
    store.init(make_setup(players, expansions))
    return Engine(store), tmp


# ── 1. the gate over every real game we can find ─────────────────

class TestGateOnRealGames(unittest.TestCase):
    """One test per discovered game; skipped when its files are absent."""


def _app_game_test(name, loader):
    def test(self):
        try:
            applog, setup, final = loader()
        except (FileNotFoundError, OSError, KeyError) as e:
            raise unittest.SkipTest(f"{name}: {e}")
        res = G.replay_app_game(name, applog, setup, final)
        self.assertEqual(res.problems, [], f"{name}: board/TR/globals differ "
                                           "from the app's own final state")
        self.assertTrue(res.rows, f"{name}: nothing compared")
    return test


def _event_game_test(name, d):
    def test(self):
        if not (d / "setup.json").exists() or not (d / "log.md").exists():
            raise unittest.SkipTest(f"{name}: no setup.json / log.md")
        res = G.replay_event_log(name, json.loads((d / "setup.json").read_text()),
                                 (d / "log.md").read_text())
        shape = [m for cls, m in res.refusals if cls == "shape"]
        self.assertEqual(shape, [], f"{name}: today's engine no longer accepts "
                                    "an event shape this game logged")
    return test


def _install_game_tests():
    for name, loader in G.app_targets({}):
        slug = name.replace("/", "_").replace(":", "_").replace("-", "_")
        setattr(TestGateOnRealGames, f"test_app_{slug}",
                _app_game_test(name, loader))
    for name, d in G.event_targets():
        slug = name.replace("/", "_").replace("-", "_")
        setattr(TestGateOnRealGames, f"test_events_{slug}",
                _event_game_test(name, d))


_install_game_tests()


class TestGateCli(unittest.TestCase):
    def test_all_runs_and_reports_every_target(self):
        results, bad = G.run_all()
        self.assertTrue(results, "the gate found no games at all")
        self.assertEqual(bad, 0,
                         "\n".join(f"{r.name}: {r.problems}"
                                   for r in results if not r.ok))

    def test_committed_fixture_is_always_available(self):
        """The one target that never skips: it lives in the repository."""
        names = [n for n, _ in G.app_targets({})]
        self.assertIn("fixture:replay-4p-wgt", names)
        results, _ = G.run_all(only="fixture:replay-4p-wgt")
        self.assertEqual([r.skipped for r in results], [None])

    def test_tile_labels_follow_the_vendor_enum(self):
        names = G.tile_enum_names()
        self.assertEqual(names[:3], ("GREENERY", "OCEAN", "CITY"))
        self.assertEqual(G.tile_label(0), "greenery")
        self.assertEqual(G.tile_label(2), "city")
        # a multi-word tile squashes to the engine's own label spelling
        self.assertEqual(G.tile_label(4), "commercialdistrict")
        if G.TILETYPE_TS.exists():
            self.assertEqual(names[:len(G.TILE_ENUM_FALLBACK)],
                             G.TILE_ENUM_FALLBACK,
                             "the offline fallback drifted from TileType.ts")


class TestLogMdInversion(unittest.TestCase):
    """log.md lines → the `apply.py batch` event shape."""

    P = ["Zed", "Ana"]

    def ev(self, msg):
        return G.logmd_events(msg, self.P)

    def test_resource_and_production_and_tr(self):
        self.assertEqual(self.ev("Zed: -8 MC → 2"),
                         [{"method": "res", "args": ["Zed", "mc", -8]}])
        self.assertEqual(self.ev("Ana: -1 ENERGY production → 1"),
                         [{"method": "prod", "args": ["Ana", "energy", -1]}])
        self.assertEqual(self.ev("Zed: TR +2 → 23"),
                         [{"method": "tr", "args": ["Zed", 2]}])

    def test_plays_places_and_conversions(self):
        self.assertEqual(
            self.ev("Zed played Aquifer Pumping (paid 8 MC + 5 steel) "
                    "→ balance 10 MC"),
            [{"method": "play", "args": ["Zed", "Aquifer Pumping"]}])
        self.assertEqual(self.ev("Ana played Geothermal Power (~−11 MC → ~16)"),
                         [{"method": "play", "args": ["Ana", "Geothermal Power"]}])
        self.assertEqual(self.ev("Zed placed ocean on 04, +2 steel"),
                         [{"method": "place", "args": ["Zed", "ocean", "04"]}])
        self.assertEqual(
            self.ev("Zed: spent 8 plants → greenery, oxygen 12% → 13%, TR → 37"),
            [{"method": "convert", "args": ["Zed", "plants"]}])

    def test_research_standard_and_claims(self):
        self.assertEqual(
            self.ev("Research: dealt ['A', 'B'], kept ['B'] (−3 MC → 18)"),
            [{"method": "dealt", "args": [["A", "B"]], "kwargs": {"kept": ["B"]}}])
        self.assertEqual(self.ev("Ana: research kept 5 cards (−15 MC → 33)"),
                         [{"method": "research", "args": ["Ana"],
                           "kwargs": {"kept": 5}}])
        self.assertEqual(
            self.ev("Zed: standard project greenery, −23 MC, greenery tile, "
                    "oxygen 13% → 14%"),
            [{"method": "standard", "args": ["Zed", "greenery"]}])
        self.assertEqual(self.ev("Ana funded award Landlord (−20 MC)"),
                         [{"method": "award", "args": ["Ana", "Landlord"]}])
        self.assertEqual(self.ev("Zed claimed milestone Builder (−8 MC)"),
                         [{"method": "milestone", "args": ["Zed", "Builder"]}])

    def test_narrative_lines_are_not_events(self):
        for line in ("Executed plan step(s): 1a",
                     "Plan set: 1a, 1b, 2a",
                     "Gen2 Zed: kept Rover Construction + Rad-Chem Factory",
                     "Ben gen1: ThorGate (48MC, 1 energy prod), kept 5."):
            self.assertIsNone(self.ev(line), line)

    def test_every_event_name_is_a_real_engine_verb(self):
        eng, tmp = fresh_engine(self.P)
        try:
            for msg in ("Zed: -8 MC → 2", "Ana: -1 ENERGY production → 1",
                        "Zed: TR +2 → 23", "Sync: oxygen = 4%",
                        "Zed played X (paid 1 MC) → balance 1 MC",
                        "Zed placed ocean on 04",
                        "Zed: spent 8 heat, temperature -30°C → -28°C, TR → 21",
                        "Research: dealt ['A'], kept [] (−0 MC → 1)",
                        "Ana: research kept 1 cards (−3 MC → 1)",
                        "Zed: standard project aquifer, −18 MC, oceans 0 → 1",
                        "Ana funded award Landlord (−20 MC)",
                        "Zed claimed milestone Builder (−8 MC)",
                        "Action used: Search For Life ✓",
                        "Hand +['A'] → ['A']",
                        "Production (end of gen 1): Zed +21 MC"):
                for ev in (G.logmd_events(msg, self.P) or []):
                    self.assertTrue(callable(getattr(eng, ev["method"], None)),
                                    f"{msg!r} → no engine verb {ev['method']!r}")
        finally:
            tmp.cleanup()


# ── 2. the defects the gate exposed, each from its own log line ──

class TestOwnChoiceCardKeepsItsTableauEntry(unittest.TestCase):
    """P8 (games/2026-08-28-game2), the app's own log lines:

        Zed played Sabotage
        Anna lost 2 steel because of Zed

    Sabotage needs `--target` and `--choice`, which the export never names.
    The replay refused the play outright and the card never reached
    playedCards — MY OWN tableau lost two cards (and their VP) while the
    opponent path had had an observe_play fallback since P7.
    """
    LOG = """Generation 1
Zed played Helion
Zed kept 0 project cards
Anna played Mining Guild
Anna gained 1 steel production
Anna gained 5 steel
Anna kept 0 project cards
Zed played Sabotage
Anna lost 2 steel because of Zed
Zed passed
Anna passed
"""

    def test_the_card_is_recorded_for_me_too(self):
        game, rep = run_log(self.LOG, ["Zed", "Anna"])
        self.assertIn("Sabotage",
                      [c["name"] for c in game["me"]["playedCards"]])
        self.assertIn("observed",
                      [g["kind"] for g in rep.gaps if g["label"] == "Sabotage"])
        self.assertNotIn("refused",
                         [g["kind"] for g in rep.gaps if g["label"] == "Sabotage"])

    def test_the_victim_still_loses_what_the_log_says(self):
        """The consequence line is applied exactly once — the play being
        recorded as an observation must not swallow or double it."""
        without = self.LOG.replace("Zed played Sabotage\n", "").replace(
            "Anna lost 2 steel because of Zed\n", "")
        before, _ = run_log(without, ["Zed", "Anna"])
        after, _ = run_log(self.LOG, ["Zed", "Anna"])
        self.assertEqual(before["opponents"]["Anna"]["resources"]["steel"]
                         - after["opponents"]["Anna"]["resources"]["steel"], 2)


class TestConversionIntoAMaxedParameter(unittest.TestCase):
    """P7 (games/2026-08-28-game1) gen 12, two lines in a row:

        Carl used Convert Heat standard action
        Carl used Convert Heat standard action

    The second one found temperature already maxed. convert() refuses that
    (good advice at the table — the heat gains nothing), but the app took
    the 8 heat anyway, so the replay finished holding heat the app did not.
    """

    def test_the_heat_is_still_spent(self):
        eng, tmp = fresh_engine(["Zed", "Anna"])
        try:
            eng.sync_global("temperature", 8, force=True)
            eng.res("Zed", "heat", 20)
            with self.assertRaises(EventError):
                eng.convert("Zed", "heat")      # the advisor guard stands
            rep = R.Report()
            rp = R.Replayer(eng, rep, verbose=False)
            head = {"kind": "used_standard", "player": "Zed",
                    "project": "convert_heat", "line": 1}
            known = defaultdict(int)
            rp.do_standard(head, [], known)
            game = eng.store.load_game()
            self.assertEqual(game["me"]["resources"]["heat"], 12)
            self.assertEqual(known[("Zed", "res", "heat")], -8)
            self.assertIn("emulated", [g["kind"] for g in rep.gaps])
        finally:
            tmp.cleanup()


class TestSilentStandardProjectProduction(unittest.TestCase):
    """P7, the app's own log lines:

        Carl used City standard project
        Carl placed city tile at 15
        Zed gained 1 M€ production

    The City project's +1 M€ for CARL is not printed at all (the server adds
    it without the log option) — only the Tharsis Republic trigger for Zed
    is. The reconciler read Carl's silent step as engine drift and removed
    it: two opponents finished the P7 replay 2 M€ production light.
    """
    LOG = """Generation 1
Zed played Tharsis Republic
Zed kept 0 project cards
Carl played Teractor
Carl kept 0 project cards
Carl used City standard project
Carl placed city tile at 15
Zed gained 1 M€ production
Carl passed
Zed passed
"""

    def test_the_actors_silent_step_survives(self):
        game, _ = run_log(self.LOG, ["Zed", "Carl"])
        self.assertEqual(pool_of(game, "Carl")["production"]["mc"], 1)

    def test_the_printed_trigger_is_still_applied_once(self):
        game, _ = run_log(self.LOG, ["Zed", "Carl"])
        self.assertEqual(pool_of(game, "Zed")["production"]["mc"], 1)

    def test_a_printed_step_is_not_doubled(self):
        """The ONLINE build prints the actor's step, so the same block must
        not add it twice (the game-night export, Carl's City projects)."""
        log = self.LOG.replace("Zed gained 1 M€ production",
                               "Carl gained 1 M€ production")
        game, _ = run_log(log, ["Zed", "Carl"])
        self.assertEqual(pool_of(game, "Carl")["production"]["mc"], 1)


class TestProductionStealIsNotCreditedTwice(unittest.TestCase):
    """P8, the app's own log lines:

        Ben played Hackers
        Ben gained 2 M€ production
        Ben lost 1 energy production
        Ben stole 2 M€ production from Anna

    A production steal only DECREASES the victim; the thief's step is the
    card's own production box, printed on its own line and already applied
    from cards/db.json. Crediting the "stole" line as well gave the thief
    +2 M€ production over the app — a whole award metric.
    """
    HACKERS = """Generation 1
Ben played Tharsis Republic
Ben kept 0 project cards
Anna played Teractor
Anna kept 0 project cards
Anna gained 4 M€ production
Ben played Hackers
Ben gained 2 M€ production
Ben lost 1 energy production
Ben stole 2 M€ production from Anna
Ben passed
Anna passed
"""
    # Energy Tapping's own step is deferred with log:false — the steal line
    # is the ONLY evidence, so there the thief MUST be credited.
    TAPPING = """Generation 1
Ben played Tharsis Republic
Ben kept 0 project cards
Anna played Teractor
Anna kept 0 project cards
Anna gained 2 energy production
Ben played Energy Tapping
Ben stole 1 energy production from Anna
Ben passed
Anna passed
"""

    def test_declared_gain_is_not_doubled(self):
        game, _ = run_log(self.HACKERS, ["Ben", "Anna"])
        self.assertEqual(pool_of(game, "Ben")["production"]["mc"], 2)
        self.assertEqual(pool_of(game, "Anna")["production"]["mc"], 2)

    def test_silent_gain_is_still_credited(self):
        game, _ = run_log(self.TAPPING, ["Ben", "Anna"])
        self.assertEqual(pool_of(game, "Ben")["production"]["energy"], 1)
        self.assertEqual(pool_of(game, "Anna")["production"]["energy"], 1)


class TestRequirementWidenerCard(unittest.TestCase):
    """P8, four of the app's own log lines the engine refused:

        Zed played Adaptation Technology
        …
        Zed played Wave Power          ('min 3 oceans', 1 on the board)
        Zed played Great Dam           ('min 4 oceans', 3 on the board)
        Zed played Natural Preserve    ('max 4% oxygen', 5%)
        Zed played Windmills           ('min 7% oxygen', 5%)

    ±2 steps on every global requirement is an ability the engine already
    knew about — but only from a CORPORATION. A player holding the card had
    legal plays refused (and every plan built on `menu.py`, which does read
    the card, disagreed with the engine that had to apply it).
    """

    def widened_engine(self):
        eng, tmp = fresh_engine(["Zed", "Anna"])
        eng.corp("Zed", "Helion", mc=200)
        eng.hand_add(["Adaptation Technology", "Wave Power", "Natural Preserve"])
        eng.play("Zed", "Adaptation Technology")
        return eng, tmp

    def test_two_steps_short_is_allowed_with_the_card(self):
        eng, tmp = self.widened_engine()
        try:
            eng.sync_global("oceans", 1)            # exactly the P8 board
            msg = eng.play("Zed", "Wave Power")     # min 3 oceans, 2 steps off
            self.assertIn("Wave Power", msg)
            self.assertIn("Wave Power",
                          [c["name"] for c in eng.store.load_game()["me"]
                           ["playedCards"]])
        finally:
            tmp.cleanup()

    def test_two_steps_past_an_expired_window_is_allowed(self):
        eng, tmp = self.widened_engine()
        try:
            eng.sync_global("oxygen", 5)            # Natural Preserve: max 4%
            eng.play("Zed", "Natural Preserve")
            self.assertIn("Natural Preserve",
                          [c["name"] for c in eng.store.load_game()["me"]
                           ["playedCards"]])
        finally:
            tmp.cleanup()

    def test_more_than_two_steps_is_still_refused(self):
        eng, tmp = self.widened_engine()
        try:
            eng.sync_global("oxygen", 12)           # Natural Preserve: max 4%
            with self.assertRaises(EventError):
                eng.play("Zed", "Natural Preserve")
        finally:
            tmp.cleanup()

    def test_without_the_card_the_window_still_closes(self):
        eng, tmp = fresh_engine(["Zed", "Anna"])
        try:
            eng.corp("Zed", "Helion", mc=200)
            eng.hand_add(["Wave Power"])
            eng.sync_global("oceans", 1)
            with self.assertRaises(EventError):
                eng.play("Zed", "Wave Power")
        finally:
            tmp.cleanup()

    def test_the_helper_reads_corp_and_tableau(self):
        self.assertTrue(tmlib.requirement_widened(
            {"corporation": "Inventrix", "playedCards": []}))
        self.assertTrue(tmlib.requirement_widened(
            {"corporation": "Helion",
             "playedCards": [{"name": "Adaptation Technology"}]}))
        self.assertFalse(tmlib.requirement_widened(
            {"corporation": "Helion", "playedCards": [{"name": "Wave Power"}]}))

    def test_gap_steps(self):
        g = {"temperature": -30, "oxygen": 5, "oceans": 1}
        self.assertEqual(tmlib.requirement_gap_steps("min 3 oceans", g), 2)
        self.assertEqual(tmlib.requirement_gap_steps("max 4% O2", g), 1)
        self.assertEqual(tmlib.requirement_gap_steps("min 1 ocean", g), 0)
        self.assertIsNone(tmlib.requirement_gap_steps("2 science tags", g))


class TestHeatPaysWhenTheCorpAllowsIt(unittest.TestCase):
    """P8: the Helion seat finished the replay holding 39 heat the app had
    already spent, because the replay topped its MC up (33 MC of `topup`
    gaps) instead of paying the shortfall out of the heat pile the way the
    app does. Both halves are invisible in the export.
    """
    LOG = """Generation 1
Zed played Helion
Zed gained 3 heat production
Zed kept 0 project cards
Anna played Teractor
Anna kept 0 project cards
Zed used Asteroid:SP standard project
Zed passed
Anna passed
"""

    def test_standard_project_shortfall_comes_out_of_heat(self):
        eng, tmp = fresh_engine(["Zed", "Anna"])
        try:
            eng.corp("Zed", "Helion", mc=10)
            eng.res("Zed", "heat", 20)
            rep = R.Report()
            rp = R.Replayer(eng, rep, verbose=False)
            known = defaultdict(int)
            rp.do_standard({"kind": "used_standard", "player": "Zed",
                            "project": "asteroid", "line": 1}, [], known)
            g = eng.store.load_game()
            self.assertEqual(g["me"]["resources"]["mc"], 0)      # 10 of 14
            self.assertEqual(g["me"]["resources"]["heat"], 16)   # 4 in heat
            self.assertEqual(rep.topups, {})
        finally:
            tmp.cleanup()

    def test_card_shortfall_comes_out_of_heat(self):
        eng, tmp = fresh_engine(["Zed", "Anna"])
        try:
            eng.corp("Zed", "Helion", mc=5)
            eng.res("Zed", "heat", 20)
            rp = R.Replayer(eng, R.Report(), verbose=False)
            info = eng.card("Wave Power")
            steel, titanium, heat = rp.metal_payment("Zed", info)
            self.assertEqual((steel, titanium), (0, 0))
            self.assertEqual(heat, info["cost"] - 5)
        finally:
            tmp.cleanup()

    def test_a_corp_without_the_ability_never_pays_in_heat(self):
        eng, tmp = fresh_engine(["Zed", "Anna"])
        try:
            eng.corp("Zed", "Teractor", mc=5)
            eng.res("Zed", "heat", 20)
            rp = R.Replayer(eng, R.Report(), verbose=False)
            self.assertEqual(rp.metal_payment("Zed", eng.card("Wave Power")),
                             (0, 0, 0))
        finally:
            tmp.cleanup()


class TestOceanTrackFollowsTheBoard(unittest.TestCase):
    """A practice game, the app's own log lines:

        Ana used Convert Heat standard action      (temperature hits 0 °C)
        Ana placed ocean tile at 28

    The 0 °C bonus ocean prints "log place + raise oceans events" and hands
    the raise to the human. In a replay nobody answers, so the tile landed
    on the board while the ocean TRACK — and the placer's TR for it — did
    not move: three practice games finished at oceans 8 against a board of
    9, and the missing TR then refused a Terraformer milestone claim.
    """
    LOG = """Generation 1
Ana played Helion
Ana kept 0 project cards
Ben played Teractor
Ben kept 0 project cards
Ana used Convert Heat standard action
Ana placed ocean tile at 28
Ana passed
Ben passed
"""

    def test_the_track_and_the_tr_follow_the_tile(self):
        game, rep = run_log(self.LOG, ["Ana", "Ben"])
        on_board = sum(1 for v in game["board"].values() if v["tile"] == "ocean")
        self.assertEqual(on_board, 1)
        self.assertEqual(game["globals"]["oceans"], 1)
        self.assertIn("ocean-counter", [g["kind"] for g in rep.gaps])

    def test_a_normal_ocean_is_not_raised_twice(self):
        log = """Generation 1
Ana played Helion
Ana kept 0 project cards
Ben played Teractor
Ben kept 0 project cards
Ana used Aquifer standard project
Ana placed ocean tile at 28
Ana passed
Ben passed
"""
        game, rep = run_log(log, ["Ana", "Ben"])
        self.assertEqual(game["globals"]["oceans"], 1)
        self.assertNotIn("ocean-counter", [g["kind"] for g in rep.gaps])


class TestCardResourcesFollowTheLog(unittest.TestCase):
    """A practice game, the app's own log lines:

        Zed added 3 Microbe(s) to Nitrite Reducing Bacteria
        Zed used Nitrite Reducing Bacteria action
        Zed removed 3 resource(s) from Zed's Nitrite Reducing Bacteria

    The middle stocking came from ANOTHER card, which the engine never sees.
    The replay dropped every "added/removed … to/from <card>" line, so the
    tracker thought the card was short and refused two of those actions —
    2 TR under the app at the end, and the counts are VP at scoring time.
    """
    LOG = """Generation 1
Zed played Helion
Zed kept 0 project cards
Ana played Teractor
Ana kept 0 project cards
Zed added 3 Microbe(s) to Nitrite Reducing Bacteria
Zed passed
Ana passed
"""

    def test_a_stocking_the_engine_did_not_cause_is_adopted(self):
        game, rep = run_log(self.LOG, ["Zed", "Ana"])
        self.assertEqual(game["me"]["cardResources"]
                         .get("Nitrite Reducing Bacteria"), 3)
        self.assertIn("mismatch", [g["kind"] for g in rep.gaps])

    def test_a_removal_is_adopted_too(self):
        log = self.LOG.replace(
            "Zed added 3 Microbe(s) to Nitrite Reducing Bacteria",
            "Zed added 3 Microbe(s) to Nitrite Reducing Bacteria\n"
            "Zed removed 2 resource(s) from Zed's Nitrite Reducing Bacteria")
        game, _ = run_log(log, ["Zed", "Ana"])
        self.assertEqual(game["me"]["cardResources"]
                         .get("Nitrite Reducing Bacteria"), 1)

    def test_the_engines_own_change_is_not_doubled(self):
        """Playing the card adds 3 from its db behavior AND the app prints
        the line — the reconciliation must land on 3, not 6."""
        log = """Generation 1
Zed played Helion
Zed kept 0 project cards
Ana played Teractor
Ana kept 0 project cards
Zed played Nitrite Reducing Bacteria
Zed added 3 Microbe(s) to Nitrite Reducing Bacteria
Zed passed
Ana passed
"""
        game, _ = run_log(log, ["Zed", "Ana"])
        self.assertEqual(game["me"]["cardResources"]
                         .get("Nitrite Reducing Bacteria"), 3)


class TestOceanOnAnAreaNotReservedForOcean(unittest.TestCase):
    """A 5-player practice game, the app's own log lines:

        Ana played Artificial Lake
        Ana placed ocean tile at 56

    56 is a land hex. The engine read "this tile may go on an ocean area"
    from behavior.tile / behavior.greenery but never the mirror rule,
    behavior.ocean.on == "land", so the placement was refused: the tile
    never reached the board, the ocean track stopped one short and two
    players' TR with it.
    """

    def test_the_card_grants_the_land_hex(self):
        eng, tmp = fresh_engine(["Ana", "Ben"])
        try:
            eng.corp("Ana", "Helion", mc=100)
            msg = eng.place("Ana", "ocean", "56", card="Artificial Lake")
            self.assertIn("56", msg)
            self.assertEqual(eng.store.load_game()["board"]["56"]["tile"], "ocean")
        finally:
            tmp.cleanup()

    def test_without_that_card_a_land_hex_is_still_refused(self):
        eng, tmp = fresh_engine(["Ana", "Ben"])
        try:
            eng.corp("Ana", "Helion", mc=100)
            with self.assertRaises(EventError):
                eng.place("Ana", "ocean", "56")
        finally:
            tmp.cleanup()

    def test_ocean_reserved_hexes_are_unaffected(self):
        eng, tmp = fresh_engine(["Ana", "Ben"])
        try:
            eng.corp("Ana", "Helion", mc=100)
            eng.place("Ana", "ocean", "28")
            self.assertEqual(eng.store.load_game()["board"]["28"]["tile"], "ocean")
        finally:
            tmp.cleanup()


class TestRefusalClassification(unittest.TestCase):
    """Only a verb/vocabulary the engine has DROPPED is a regression; a
    missing interactive argument or a drifted stock is a property of the
    log the gate re-reads, not of the engine."""

    def test_shape(self):
        self.assertEqual(G.refusal_class("unknown engine method 'foo'"), "shape")
        self.assertEqual(G.refusal_class("Unknown resource: 'gold'"), "shape")

    def test_argument_not_in_the_log_line(self):
        for msg in ("Sabotage needs a victim: --target <player>",
                    "Power Supply Consortium needs its victim: --target <player>",
                    "Electro Catapult is an or-choice card — say which branch",
                    "'Greenery SP' not in cards/db.json — give its cost "
                    "explicitly (play ... --cost N)",
                    "Unknown action 'Space Elevator'; register it first"):
            self.assertEqual(G.refusal_class(msg), "arg-not-in-log", msg)

    def test_state_drift(self):
        for msg in ("Need 11 MC, have 4",
                    "oxygen can only move up (currently 5, observed 4",
                    "Space 25 already holds Zed's greenery",
                    "'Wave Power' requirement not met: closed"):
            self.assertEqual(G.refusal_class(msg), "state-drift", msg)


class TestVerifyChecksTheOceanTrack(unittest.TestCase):
    """The same invariant as a live check: `verify.py` reconciles tile
    COUNTERS against the board but never the ocean TRACK, and the track
    drives both the end-of-game trigger and a TR per step. Like
    board_drift() it needs no app, so it works at the physical table."""

    def test_drift_is_reported_and_raised_to_the_board(self):
        import verify
        eng, tmp = fresh_engine(["Ana", "Ben"])
        try:
            eng.corp("Ana", "Helion", mc=100)
            eng.place("Ana", "ocean", "28")     # tile on the board…
            eng.sync_global("oceans", 0, force=True)   # …track left behind
            self.assertEqual(verify.ocean_track_drift(eng), (0, 1))
            self.assertTrue(verify.sync_ocean_track(eng))
            self.assertIsNone(verify.ocean_track_drift(eng))
        finally:
            tmp.cleanup()

    def test_a_track_ahead_of_the_board_is_reported_but_never_lowered(self):
        import verify
        eng, tmp = fresh_engine(["Ana", "Ben"])
        try:
            eng.sync_global("oceans", 2)
            self.assertEqual(verify.ocean_track_drift(eng), (2, 0))
            self.assertEqual(verify.sync_ocean_track(eng), [])
        finally:
            tmp.cleanup()

    def test_no_drift_is_silent(self):
        import verify
        eng, tmp = fresh_engine(["Ana", "Ben"])
        try:
            eng.corp("Ana", "Helion", mc=100)
            eng.place("Ana", "ocean", "28")
            eng.sync_global("oceans", 1)
            self.assertIsNone(verify.ocean_track_drift(eng))
        finally:
            tmp.cleanup()


class TestWgtInversion(unittest.TestCase):
    """The World Government step is a machine event with its own log line;
    reading it back cut the game-night log's refusals from 85 to 24 (every
    later produce() refused while the WGT step of that generation was
    missing)."""

    P = ["Zed", "Anna"]

    def ev(self, msg):
        return G.logmd_events(msg, self.P)

    def test_parameter_steps(self):
        self.assertEqual(self.ev("WGT (Anna, no TR/bonuses), "
                                 "temperature -30°C → -28°C"),
                         [{"method": "wgt", "args": ["temperature"]}])
        self.assertEqual(self.ev("WGT (Anna, no TR/bonuses), oxygen 1% → 2%"),
                         [{"method": "wgt", "args": ["oxygen"]}])

    def test_ocean_step_carries_its_hex(self):
        self.assertEqual(
            self.ev("WGT (Anna, no TR/bonuses), ocean placed on 13 → oceans "
                    "3/9; placement bonus + adjacency MC NOT granted "
                    "(solar phase)"),
            [{"method": "wgt", "args": ["oceans"], "kwargs": {"space_id": "13"}}])

    def test_the_skip_line_is_an_argument_of_the_next_produce(self):
        self.assertIsNone(self.ev("WGT step skipped: gen 9 WGT line not yet "
                                  "reported"))
        self.assertIsNotNone(G.SKIP_WGT.match("WGT step skipped: because"))


if __name__ == "__main__":
    unittest.main()
