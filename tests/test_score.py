"""score.py — full + abort scoring; award funding/scoring."""
import sys, tempfile, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from tmlib import Store, Engine, EventError, AWARDS, AWARD_COSTS
from test_new_game import SETUP
import score


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(self.tmp.name)
        self.store.init(SETUP)
        self.eng = Engine(self.store)

    def tearDown(self):
        self.tmp.cleanup()

    def game(self):
        return self.store.load_game()


class TestAwardFunding(Base):
    def test_award_costs_escalate(self):
        self.assertEqual(AWARD_COSTS, (8, 14, 20))
        self.assertEqual(AWARDS, ("Landlord", "Banker", "Scientist",
                                  "Thermalist", "Miner"))

    def test_fund_award_charges_and_records(self):
        self.eng.res("Zed", "mc", +30)
        self.eng.award("Zed", "Banker")
        g = self.game()
        self.assertEqual(g["awardsFunded"], {"Banker": "Zed"})
        self.assertEqual(g["me"]["resources"]["mc"], 22)

    def test_second_award_costs_14(self):
        self.eng.res("Zed", "mc", +30)
        self.eng.res("Anna", "mc", +30)
        self.eng.award("Zed", "Banker")
        self.eng.award("Anna", "Landlord")
        self.assertEqual(self.game()["opponents"]["Anna"]["resources"]["mc"], 16)

    def test_max_three_awards(self):
        self.eng.res("Zed", "mc", +60)
        for a in ("Banker", "Landlord", "Scientist"):
            self.eng.award("Zed", a)
        with self.assertRaises(EventError):
            self.eng.award("Zed", "Miner")

    def test_bogus_award_rejected(self):
        self.eng.res("Zed", "mc", +30)
        with self.assertRaises(EventError):
            self.eng.award("Zed", "Bankor")


class TestScoring(Base):
    def _mid_game(self):
        self.eng.res("Zed", "mc", +80)
        self.eng.tr("Zed", +15)                      # TR 35
        self.eng.hand_add(["Comet"])
        self.eng.play("Zed", "Comet")                # +2 TR (temp+ocean) → 37
        self.eng.milestone("Zed", "Terraformer")     # 5 VP (eligible)
        self.eng.res("Anna", "mc", +40)
        self.eng.res("Anna", "plants", +8)
        self.eng.convert("Anna", "plants")              # greenery: TR 21, 1 tile

    def test_abort_mode_ranks_now(self):
        self._mid_game()
        r = score.compute(self.game(), mode="abort")
        by = {p["name"]: p for p in r["players"]}
        g = by["Zed"]
        self.assertEqual(g["tr"], 37)
        self.assertEqual(g["milestoneVP"], 0)           # abort skips milestones
        self.assertEqual(g["cardVP"], 0)                # Comet has no VP
        anna = by["Anna"]
        self.assertEqual(anna["tileVP"], 1)             # greenery
        self.assertEqual(anna["total"], 22)
        self.assertEqual(r["players"][0]["rank"], 1)    # sorted by total

    def test_full_mode_includes_milestones_and_awards(self):
        self._mid_game()
        self.eng.award("Zed", "Banker")
        self.eng.prod("Zed", "mc", +3)               # leads Banker
        r = score.compute(self.game(), mode="full")
        g = {p["name"]: p for p in r["players"]}["Zed"]
        self.assertEqual(g["milestoneVP"], 5)
        self.assertEqual(g["awardVP"], 5)               # 1st place Banker
        self.assertIn(g["total"],
                      (g["tr"] + g["cardVP"] + g["tileVP"] + 5 + 5,))

    def test_award_second_place_2vp(self):
        self._mid_game()
        self.eng.award("Zed", "Banker")
        self.eng.prod("Zed", "mc", +3)
        self.eng.prod("Anna", "mc", +2)                 # 2nd Banker
        r = score.compute(self.game(), mode="full")
        anna = {p["name"]: p for p in r["players"]}["Anna"]
        self.assertEqual(anna["awardVP"], 2)

    def test_card_vp_from_db(self):
        self.eng.res("Zed", "mc", +80)
        self.eng.hand_add(["Trees"])                    # 1 VP automated card
        self.eng.play("Zed", "Trees", ignore_requirements=True)
        r = score.compute(self.game(), mode="abort")
        g = {p["name"]: p for p in r["players"]}["Zed"]
        self.assertEqual(g["cardVP"], 1)

    def test_immigration_shuttles_auto_counts_cities(self):
        self.eng.res("Zed", "mc", +80)
        self.eng.hand_add(["Immigration Shuttles"])     # 1 VP per 3 cities
        self.eng.play("Zed", "Immigration Shuttles")
        for pl, sid in (("Zed", "03"), ("Anna", "05"), ("Anna", "08")):
            self.eng.place(pl, "city", sid)
        r = score.compute(self.game(), mode="abort")
        g = {p["name"]: p for p in r["players"]}["Zed"]
        self.assertEqual(g["cardVP"], 1)                # floor(3 / 3)
        self.assertFalse(any("Immigration Shuttles" in m for m in g["manualVP"]))

    def test_immigration_shuttles_zero_below_three_cities(self):
        self.eng.res("Zed", "mc", +80)
        self.eng.hand_add(["Immigration Shuttles"])
        self.eng.play("Zed", "Immigration Shuttles")
        self.eng.place("Anna", "city", "05")
        self.eng.place("Anna", "city", "08")
        r = score.compute(self.game(), mode="abort")
        g = {p["name"]: p for p in r["players"]}["Zed"]
        self.assertEqual(g["cardVP"], 0)                # floor(2 / 3)
        self.assertFalse(any("Immigration Shuttles" in m for m in g["manualVP"]))

    def test_my_formula_card_scores_its_tracked_zero(self):
        # W2-A: my own play records the count (explicit 0 — I am the
        # record of my own actions), so Birds is exact, never "manual".
        self.eng.res("Zed", "mc", +80)
        self.eng.hand_add(["Birds"])                    # 1 VP per animal
        self.eng.play("Zed", "Birds", ignore_requirements=True)
        r = score.compute(self.game(), mode="abort")
        g = {p["name"]: p for p in r["players"]}["Zed"]
        self.assertEqual(g["cardVP"], 0)
        self.assertFalse(any("Birds" in m for m in g["manualVP"]))
        self.assertEqual(g["formulaVPCards"], [])


if __name__ == "__main__":
    unittest.main()


class TestOpponentTileVP(Base):
    """P8 #20: the tracker put an opponent on 75 VP against the app's 96.
    City-adjacency VP has to be counted for EVERY player from the board —
    the threat ranking is built on those numbers."""

    def test_opponent_city_scores_adjacent_greeneries(self):
        self.eng.place("Anna", "city", "03")            # adj: 04, 09, 08
        self.eng.place("Anna", "greenery", "08")
        self.eng.place("Anna", "greenery", "09")
        self.eng.tiles_fix("Anna", "greeneries", 2)
        self.eng.tiles_fix("Anna", "cities", 1)
        r = score.compute(self.game(), mode="abort")
        anna = {p["name"]: p for p in r["players"]}["Anna"]
        self.assertEqual(anna["tileVP"], 4)             # 2 greeneries + 2 adjacency

    def test_any_players_greenery_counts_for_the_city_owner(self):
        self.eng.place("Anna", "city", "03")
        self.eng.place("Zed", "greenery", "08")         # my greenery, their city
        self.eng.tiles_fix("Anna", "cities", 1)
        r = score.compute(self.game(), mode="abort")
        anna = {p["name"]: p for p in r["players"]}["Anna"]
        self.assertEqual(anna["tileVP"], 1)

    def test_capital_is_a_city_for_adjacency(self):
        self.eng.place("Anna", "capital", "03", card="Capital")
        self.eng.place("Anna", "greenery", "08")
        self.eng.tiles_fix("Anna", "greeneries", 1)
        r = score.compute(self.game(), mode="abort")
        anna = {p["name"]: p for p in r["players"]}["Anna"]
        self.assertEqual(score.city_adjacency_vp(self.game(), "Anna"), 1)
        self.assertEqual(anna["tileVP"], 2)             # greenery + Capital adjacency

    def test_offmars_city_is_not_flagged_as_unplaced(self):
        self.eng.tiles_fix("Anna", "cities", 1)
        g = self.game()
        g["opponents"]["Anna"]["tiles"]["citiesOffMars"] = 1
        self.store.save_game(g)
        r = score.compute(self.game(), mode="abort")
        anna = {p["name"]: p for p in r["players"]}["Anna"]
        self.assertFalse([m for m in anna["manualVP"] if "without recorded" in m],
                         anna["manualVP"])


class TestCardVPFloor(Base):
    """P8 #20b: formula-VP cards silently scored 0, so an opponent's card
    VP read 15 against the app's 28. The floor and what is NOT in it are
    printed per player, in both modes."""

    def _ben_with_formula_cards(self):
        self.eng.observe_play("Anna", "Birds")          # 1 VP per animal
        self.eng.observe_play("Anna", "Ants")           # 1 VP per 2 microbes
        self.eng.observe_play("Anna", "Trees")          # flat 1 VP

    def test_row_lists_uncountable_formula_cards(self):
        self._ben_with_formula_cards()
        r = score.compute(self.game(), mode="abort")
        anna = {p["name"]: p for p in r["players"]}["Anna"]
        self.assertEqual(anna["cardVP"], 1)                     # Trees only
        self.assertEqual(sorted(anna["formulaVPCards"]), ["Ants", "Birds"])

    def test_card_vp_line_names_them_with_bounds(self):
        self._ben_with_formula_cards()
        r = score.compute(self.game(), mode="abort")
        anna = {p["name"]: p for p in r["players"]}["Anna"]
        line = score.card_vp_line(anna)
        self.assertIn("card VP known 1", line)
        # W2-A contract: an uncounted card never appears without its
        # bound — unobserved resource counts have no sane cap
        self.assertIn("Birds unbounded", line)
        self.assertIn("Ants unbounded", line)

    def test_card_vp_line_when_all_countable(self):
        self.eng.observe_play("Anna", "Trees")
        r = score.compute(self.game(), mode="abort")
        anna = {p["name"]: p for p in r["players"]}["Anna"]
        self.assertIn("card VP known 1", score.card_vp_line(anna))
        self.assertNotIn("not countable", score.card_vp_line(anna))

    def _resources(self, player, counts):
        """The engine's tracked per-card resource counts."""
        g = self.game()
        pool = g["me"] if g["me"]["name"] == player else g["opponents"][player]
        pool.setdefault("cardResources", {}).update(counts)
        self.store.save_game(g)

    def test_own_formula_card_scores_from_the_tracked_count(self):
        self.eng.res("Zed", "mc", +80)
        self.eng.hand_add(["Physics Complex"])
        self.eng.play("Zed", "Physics Complex", ignore_requirements=True)
        self._resources("Zed", {"Physics Complex": 9})   # 2 VP per science
        r = score.compute(self.game(), mode="abort")
        me = {p["name"]: p for p in r["players"]}["Zed"]
        self.assertEqual(me["cardVP"], 18)
        self.assertEqual(me["formulaVPCards"], [])
        self.assertFalse([m for m in me["manualVP"] if "Physics" in m],
                         me["manualVP"])
        self.assertIn("all card VP counted", score.card_vp_line(me))

    def test_divisor_formula_rounds_down(self):
        self.eng.observe_play("Anna", "Ants")            # 1 VP per 2 microbes
        self._resources("Anna", {"Ants": 5})
        r = score.compute(self.game(), mode="abort")
        anna = {p["name"]: p for p in r["players"]}["Anna"]
        self.assertEqual(anna["cardVP"], 2)
        self.assertEqual(anna["formulaVPCards"], [])

    def test_untracked_count_stays_in_the_floor(self):
        self.eng.observe_play("Anna", "Tardigrades")     # no count known
        r = score.compute(self.game(), mode="abort")
        anna = {p["name"]: p for p in r["players"]}["Anna"]
        self.assertEqual(anna["cardVP"], 0)
        self.assertEqual(anna["formulaVPCards"], ["Tardigrades"])
        self.assertIn("Tardigrades", score.card_vp_line(anna))

    def test_zero_resources_counts_as_known(self):
        self.eng.observe_play("Anna", "Birds")
        self._resources("Anna", {"Birds": 0})
        r = score.compute(self.game(), mode="abort")
        anna = {p["name"]: p for p in r["players"]}["Anna"]
        self.assertEqual(anna["cardVP"], 0)
        self.assertEqual(anna["formulaVPCards"], [])

    def test_board_formula_card_is_never_read_off_a_resource_count(self):
        """Capital's '1 per adjacent ocean tile' is a BOARD formula — a
        stray resource count must not be mistaken for it."""
        self.eng.observe_play("Anna", "Capital")
        self._resources("Anna", {"Capital": 3})
        r = score.compute(self.game(), mode="abort")
        anna = {p["name"]: p for p in r["players"]}["Anna"]
        self.assertEqual(anna["cardVP"], 0)
        self.assertEqual(anna["formulaVPCards"], ["Capital"])

    def _cli(self, *argv):
        import contextlib, io
        from unittest import mock
        state = str(Path(self.tmp.name) / "state" / "game.json")
        buf = io.StringIO()
        with mock.patch.object(sys, "argv",
                               ["score.py", "--state", state, *argv]), \
                contextlib.redirect_stdout(buf):
            self.assertEqual(score.main(), 0)
        return buf.getvalue()

    def test_cli_prints_the_floor_and_bound_in_abort_and_full(self):
        self._ben_with_formula_cards()
        for argv in ([], ["--abort"]):
            out = self._cli(*argv)
            self.assertIn("card VP known 1", out)
            self.assertIn("Birds unbounded", out)
            self.assertIn("Ants unbounded", out)
            self.assertIn("≥", out)               # the total carries the bound
            self.assertNotIn("not countable", out)


class TestAppFinalTable(unittest.TestCase):
    """At phase == end the app has the exact
    victoryPointsBreakdown — print it instead of 'count manually' items."""
    FIX = Path(__file__).resolve().parent / "fixtures" / "endgame-5p" / "me_end.json"

    def setUp(self):
        import copy, json
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(self.tmp.name)
        setup = copy.deepcopy(SETUP)
        setup["gameMode"] = "app-practice"
        setup["appUrl"] = "http://localhost:8080"
        next(p for p in setup["players"] if p["isMe"])["playerId"] = "p1"
        self.store.init(setup)
        self.data = json.loads(self.FIX.read_text())

    def tearDown(self):
        self.tmp.cleanup()

    def _run_main(self, payload, *argv):
        import contextlib, io, urllib.request
        from unittest import mock

        class Resp(io.BytesIO):
            def __enter__(self): return self
            def __exit__(self, *a): return False
        state = str(Path(self.tmp.name) / "state" / "game.json")
        buf = io.StringIO()
        with mock.patch.object(urllib.request, "urlopen",
                               return_value=Resp(payload)) as m, \
                mock.patch.object(sys, "argv", ["score.py", "--state", state, *argv]), \
                contextlib.redirect_stdout(buf):
            self.assertEqual(score.main(), 0)
        return buf.getvalue(), m

    def test_app_final_table_sorted_by_total(self):
        rows = score.app_final_table(self.data)
        self.assertEqual([(r["name"], r["total"]) for r in rows],
                         [("Zed", 94), ("Ben", 60), ("Ana", 54),
                          ("Carl", 52), ("Diana", 47)])
        self.assertEqual(rows[0]["milestones"], 10)
        self.assertEqual(rows[0]["victoryPoints"], 31)

    def test_app_default_on_in_app_mode_prints_table_and_estimate(self):
        import json
        out, m = self._run_main(json.dumps(self.data).encode())
        self.assertIn("id=p1", m.call_args[0][0])
        self.assertIn("Zed", out)
        self.assertIn("94", out)
        self.assertLess(out.index("Zed"), out.index("Ben"))
        self.assertIn("=== Scoring (full) ===", out)     # cross-check below

    def test_phase_not_end_falls_back(self):
        import json
        out, _ = self._run_main(json.dumps({"game": {"phase": "action"},
                                            "players": []}).encode())
        self.assertIn("not 'end'", out)
        self.assertIn("=== Scoring (full) ===", out)

    def test_abort_never_fetches(self):
        import json
        _, m = self._run_main(json.dumps(self.data).encode(), "--abort")
        m.assert_not_called()

    def test_physical_mode_needs_explicit_app_flag(self):
        import json
        setup = self.store.load_setup()
        setup["gameMode"] = "physical"
        (Path(self.tmp.name) / "state" / "setup.json").write_text(json.dumps(setup))
        _, m = self._run_main(json.dumps(self.data).encode())
        m.assert_not_called()
        out, m = self._run_main(json.dumps(self.data).encode(), "--app")
        m.assert_called_once()
        self.assertIn("Diana", out)


class TestAbortCompletenessCaveat(unittest.TestCase):
    """Abort scoring must WARN when opponents' tableaus are untracked
    (the measured norm at low relay) — silence reads as 'complete'."""

    def test_warns_on_empty_opponent_tableaus(self):
        import tempfile, subprocess, sys
        from pathlib import Path
        from tmlib import Store, Engine
        from test_new_game import SETUP
        with tempfile.TemporaryDirectory() as tmp:
            Store(tmp).init(SETUP)
            r = subprocess.run(
                [sys.executable,
                 str(Path(__file__).resolve().parent.parent / "scripts" / "score.py"),
                 "--abort", "--state", str(Path(tmp) / "state" / "game.json")],
                capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("untracked", r.stdout.lower())
