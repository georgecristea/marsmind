"""research.py — one-shot research-phase evaluator.
Collapses cards.py + clock.py + payback.py into a single call so the
table-hot research phase needs one tool call, not six."""
import sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import research


def game(temp=-12, o2=2, oceans=5, gen=7, mc=46):
    return {"generation": gen,
            "globals": {"temperature": temp, "oxygen": o2, "oceans": oceans},
            "me": {"resources": {"mc": mc}, "playedCards": []}}


class TestWindows(unittest.TestCase):
    def test_min_requirement_not_met_yet(self):
        e = research.evaluate(game(o2=2), ["Worms"])[0]
        self.assertEqual(e["window"], "closed — opens later (min 4% O2, now 2%)")

    def test_min_requirement_met(self):
        e = research.evaluate(game(o2=3), ["Methane From Titan"])[0]
        self.assertTrue(e["window"].startswith("open"))

    def test_max_requirement_expired(self):
        e = research.evaluate(game(oceans=6), ["Dust Seals"])[0]
        self.assertEqual(e["window"], "EXPIRED (max 3 oceans, now 6)")

    def test_max_requirement_closing(self):
        e = research.evaluate(game(oceans=2), ["Dust Seals"])[0]
        self.assertEqual(e["window"], "open but CLOSING (max 3 oceans, now 2)")

    def test_tag_requirement_flagged_manual(self):
        e = research.evaluate(game(), ["Tectonic Stress Power"])[0]
        self.assertIn("manual", e["window"])


class TestPayback(unittest.TestCase):
    def test_production_card_gets_payback(self):
        e = research.evaluate(game(), ["Methane From Titan"])[0]
        self.assertIn("payback", e)
        self.assertEqual(e["payback"]["perGen"], 6)  # heat 2×1 + plants 2×2

    def test_non_production_card_has_no_payback(self):
        e = research.evaluate(game(), ["Flooding"])[0]
        self.assertNotIn("payback", e)


class TestEffectScaling(unittest.TestCase):
    """--tableau makes per-tag conditional cards machine-flagged."""

    def test_worms_alone_is_zero_effect(self):
        # 1 microbe tag incl. itself, per 2 → floor(1/2) = ×0
        e = research.evaluate(game(o2=5), ["Worms"], tableau=[])[0]
        s = e["scaling"]
        self.assertEqual(s["tag"], "microbe")
        self.assertEqual(s["per"], 2)
        self.assertEqual(s["tagCount"], 1)
        self.assertEqual(s["multiplier"], 0)
        self.assertTrue(s["zeroEffect"])

    def test_worms_with_one_microbe_played_scales_once(self):
        e = research.evaluate(game(o2=5), ["Worms"], tableau=["Ants"])[0]
        self.assertEqual(e["scaling"]["tagCount"], 2)
        self.assertEqual(e["scaling"]["multiplier"], 1)

    def test_insects_with_four_plant_tags(self):
        tab = ["Grass", "Bushes", "Heather", "Kelp Farming"]
        e = research.evaluate(game(o2=7), ["Insects"], tableau=tab)[0]
        self.assertEqual(e["scaling"]["tag"], "plant")
        self.assertEqual(e["scaling"]["per"], 1)
        # Insects itself is a microbe card: no self plant tag
        self.assertEqual(e["scaling"]["tagCount"], 4)
        self.assertEqual(e["scaling"]["multiplier"], 4)
        self.assertFalse(e["scaling"]["zeroEffect"])

    def test_no_tableau_means_no_scaling_key(self):
        e = research.evaluate(game(o2=5), ["Worms"])[0]
        self.assertNotIn("scaling", e)

    def test_non_scaling_card_untouched(self):
        e = research.evaluate(game(), ["Flooding"], tableau=["Grass"])[0]
        self.assertNotIn("scaling", e)


ENABLER_HAND = ["Worms", "Insects", "Mangrove", "Ecological Zone"]


class TestHandActivations(unittest.TestCase):
    """Enabler cards are priced against the HAND."""

    def test_viral_enhancers_activates_four_hand_cards(self):
        e = research.evaluate(game(), ["Viral Enhancers"], hand=ENABLER_HAND)[0]
        self.assertEqual(sorted(e["activates"]["cards"]), sorted(ENABLER_HAND))
        self.assertEqual(sorted(e["activates"]["tags"]),
                         ["animal", "microbe", "plant"])

    def test_viral_enhancers_with_empty_hand_is_zero(self):
        e = research.evaluate(game(), ["Viral Enhancers"], hand=[])[0]
        self.assertEqual(e["activates"]["cards"], [])

    def test_when_you_play_a_card_matches_every_hand_card(self):
        e = research.evaluate(game(), ["Earth Catapult"], hand=ENABLER_HAND)[0]
        self.assertEqual(len(e["activates"]["cards"]), 4)
        self.assertTrue(e["activates"]["any"])

    def test_plain_production_card_prints_nothing_new(self):
        e = research.evaluate(game(), ["Tundra Farming"], hand=ENABLER_HAND)[0]
        self.assertNotIn("activates", e)

    def test_no_hand_means_no_activation_key(self):
        e = research.evaluate(game(), ["Viral Enhancers"])[0]
        self.assertNotIn("activates", e)


class TestVpThreshold(unittest.TestCase):
    """Accumulator VP = count to the next threshold."""

    def test_tardigrades_seven_microbes_next_at_eight(self):
        e = research.evaluate(game(), ["Tardigrades"],
                              resources={"Tardigrades": 7})[0]
        t = e["vpFormula"]
        self.assertEqual((t["points"], t["per"], t["unit"]), (1, 4, "microbes"))
        self.assertEqual(t["now"], 7)
        self.assertEqual(t["vpNow"], 1)
        self.assertEqual(t["nextAt"], 8)

    def test_herbivores_three_animals_next_at_four(self):
        e = research.evaluate(game(), ["Herbivores"],
                              resources={"Herbivores": 3})[0]
        self.assertEqual(e["vpFormula"]["per"], 2)
        self.assertEqual(e["vpFormula"]["nextAt"], 4)
        self.assertEqual(e["vpFormula"]["vpNow"], 1)

    def test_divisor_shown_without_resources(self):
        e = research.evaluate(game(), ["Birds"])[0]
        self.assertEqual(e["vpFormula"]["per"], 1)
        self.assertNotIn("now", e["vpFormula"])

    def test_unparseable_formula_left_verbatim(self):
        e = research.evaluate(game(), ["Search For Life"])[0]
        self.assertNotIn("vpFormula", e)
        self.assertTrue(isinstance(e["vp"], str))

    def test_fixed_vp_untouched(self):
        e = research.evaluate(game(), ["Tundra Farming"])[0]
        self.assertNotIn("vpFormula", e)
        self.assertEqual(e["vpValue"], 10)


class TestLandWarning(unittest.TestCase):
    """Land hook: tile / plant-production cards flagged when the board
    is nearly full (free land <= players)."""

    def _game(self):
        g = game()
        g["opponents"] = {"a": {}, "b": {}, "c": {}, "d": {}}   # 5 players
        return g

    def _with_free(self, free, names):
        from unittest import mock
        with mock.patch.object(research.tmlib, "occupied_space_ids",
                               lambda game: set(), create=True), \
             mock.patch.object(research.tmlib, "free_land",
                               lambda occ, board=None: free, create=True):
            return research.evaluate(self._game(), names)

    def test_full_board_flags_tile_and_plant_cards(self):
        es = self._with_free(0, ["Mangrove", "Ganymede Colony",
                                 "Tundra Farming", "Capital"])
        for e in es:
            self.assertEqual(e.get("landWarning"), 0, e["name"])

    def test_full_board_leaves_non_tile_cards_alone(self):
        es = self._with_free(0, ["Viral Enhancers", "Flooding"])
        for e in es:
            self.assertNotIn("landWarning", e, e["name"])

    def test_plenty_of_land_no_flag(self):
        es = self._with_free(30, ["Mangrove", "Tundra Farming"])
        for e in es:
            self.assertNotIn("landWarning", e, e["name"])

    def test_missing_tmlib_helpers_do_not_crash(self):
        from unittest import mock
        with mock.patch.object(research, "tmlib", object()):
            e = research.evaluate(self._game(), ["Mangrove"])[0]
        self.assertNotIn("landWarning", e)


class TestClockHistory(unittest.TestCase):
    """Clock hook: history is passed to the clock; gensLeft stays the
    pessimistic payback horizon."""

    def test_history_bearing_game_keeps_gens_left(self):
        g = game()
        g["history"] = [{"temperature": -30, "oxygen": 0, "oceans": 0},
                        {"temperature": -26, "oxygen": 1, "oceans": 1}]
        e = research.evaluate(g, ["Methane From Titan"])[0]
        self.assertIn("gensLeft", e["payback"])
        s = research.summary(g, [e])
        self.assertEqual(s["gensLeft"], e["payback"]["gensLeft"])


class TestBasics(unittest.TestCase):
    def test_unknown_card_flagged(self):
        e = research.evaluate(game(), ["Totally Made Up Card"])[0]
        self.assertTrue(e.get("unknown"))

    def test_summary_totals_keep_cost(self):
        entries = research.evaluate(game(), ["Worms", "Flooding"])
        s = research.summary(game(), entries)
        self.assertEqual(s["keepCostAll"], 6)
        self.assertEqual(s["mc"], 46)


class TestOneClock(unittest.TestCase):
    """research.py once said "11 gens left" while clock.py said 8 —
    it hard-coded players=2. ONE clock: research.py derives the estimate
    exactly as clock.py / advise.py do (player count from state/setup)."""

    def _five_player(self, gen=3):
        g = game(temp=-24, o2=2, oceans=1, gen=gen)
        g["opponents"] = {n: {} for n in ("Ana", "Ben", "Carl", "Diana")}
        return g

    def test_gens_left_matches_clock_estimate_for_player_count(self):
        import clock
        g = self._five_player()
        want = clock.estimate(g["globals"], g["generation"], players=5)
        s = research.summary(g, [])
        self.assertEqual(s["gensLeft"], want["gensLeft"])
        # regression: the old hard-coded 2-player prior gave a longer clock
        two = clock.estimate(g["globals"], g["generation"], players=2)
        self.assertNotEqual(s["gensLeft"], two["gensLeft"])

    def test_payback_horizon_uses_the_same_clock(self):
        import clock
        g = self._five_player()
        want = clock.estimate(g["globals"], g["generation"], players=5)
        e = research.evaluate(g, ["Methane From Titan"])[0]
        self.assertEqual(e["payback"]["gensLeft"], want["gensLeft"])

    def test_setup_player_count_wins_over_opponent_count(self):
        import clock
        g = self._five_player()
        est = research.clock_estimate(g, setup={"playerCount": 3})
        self.assertEqual(est["gensLeft"],
                         clock.estimate(g["globals"], 3, players=3)["gensLeft"])

    def test_declared_final_generation_pins_the_clock(self):
        g = self._five_player(gen=8)
        g["declaredFinalGeneration"] = 8
        self.assertEqual(research.summary(g, [])["gensLeft"], 0)

    def test_cli_prints_the_number_clock_py_prints(self):
        import json, os, subprocess, tempfile
        g = self._five_player(gen=5)
        g["globals"] = {"temperature": -14, "oxygen": 5, "oceans": 3}
        scripts = Path(__file__).resolve().parent.parent / "scripts"
        with tempfile.TemporaryDirectory() as d:
            state = Path(d) / "game.json"
            state.write_text(json.dumps(g))
            c = subprocess.run([sys.executable, str(scripts / "clock.py"),
                                "--state", str(state)],
                               capture_output=True, text=True, check=True)
            r = subprocess.run([sys.executable, str(scripts / "research.py"),
                                "--state", str(state), "--quick",
                                "Worms", "Flooding"],
                               capture_output=True, text=True, check=True)
        want = json.loads(c.stdout)["gensLeft"]
        self.assertIn(f"{want} gens left", r.stdout.splitlines()[0])


class TestQuick(unittest.TestCase):
    """Draft fast path — one compact line per card, well under 1 s."""

    TAGS = ("KEEP", "PASS", "DENY-only", "JUDGE")

    def _tag(self, line):
        return line.rsplit("→ ", 1)[1].split(" ")[0]

    def test_one_line_per_card_with_name_cost_window_verdict(self):
        lines = research.quick_lines(game(o2=2),
                                     ["Worms", "Flooding", "Dust Seals"])
        self.assertEqual(len(lines), 3)
        for line, name in zip(lines, ["Worms", "Flooding", "Dust Seals"]):
            self.assertEqual(line.count("\n"), 0)
            self.assertTrue(line.startswith(name), line)
            self.assertIn("+3=", line)          # cost(+3 keep)
            self.assertIn(self._tag(line), self.TAGS, line)

    def test_closed_window_says_opens_in_n_steps(self):
        line = research.quick_lines(game(o2=2), ["Worms"])[0]
        self.assertIn("opens in 2 steps", line)

    def test_open_window_says_open(self):
        line = research.quick_lines(game(o2=3), ["Methane From Titan"])[0]
        self.assertIn("open", line)

    def test_expired_window_is_pass(self):
        line = research.quick_lines(game(oceans=6), ["Dust Seals"])[0]
        self.assertIn("EXPIRED", line)
        self.assertEqual(self._tag(line), "PASS")

    def test_closing_window_counts_steps_to_close(self):
        line = research.quick_lines(game(oceans=2), ["Dust Seals"])[0]
        self.assertIn("CLOSES in 2 steps", line)

    def test_production_card_gets_payback_one_liner_and_keep(self):
        g = game(temp=-24, o2=2, oceans=1, gen=2)     # long clock
        line = research.quick_lines(g, ["Methane From Titan"])[0]
        self.assertIn("/gen", line)
        self.assertEqual(self._tag(line), "KEEP")

    def test_vp_card_shows_mc_per_vp(self):
        line = research.quick_lines(game(oceans=2), ["Dust Seals"])[0]
        self.assertIn("MC/VP", line)

    def test_effect_card_without_machine_value_is_judge(self):
        line = research.quick_lines(game(), ["Viral Enhancers"])[0]
        self.assertEqual(self._tag(line), "JUDGE")

    def test_zero_effect_scaling_is_deny_only(self):
        line = research.quick_lines(game(o2=5), ["Worms"], tableau=[])[0]
        self.assertEqual(self._tag(line), "DENY-only")

    def test_unknown_card_line(self):
        line = research.quick_lines(game(), ["Totally Made Up Card"])[0]
        self.assertIn("NOT IN DB", line)

    def test_quick_is_fast(self):
        import time
        research.quick_lines(game(), ["Worms"])       # warm the db cache
        t = time.perf_counter()
        research.quick_lines(game(o2=2), ["Worms", "Flooding", "Dust Seals",
                                          "Methane From Titan"])
        self.assertLess(time.perf_counter() - t, 0.5)

    def _run(self, *args):
        import json, subprocess, tempfile
        scripts = Path(__file__).resolve().parent.parent / "scripts"
        with tempfile.TemporaryDirectory() as d:
            state = Path(d) / "game.json"
            state.write_text(json.dumps(game(o2=2)))
            r = subprocess.run([sys.executable, str(scripts / "research.py"),
                                "--state", str(state), *args],
                               capture_output=True, text=True, check=True)
        return r.stdout.splitlines()

    def test_cli_auto_quick_for_three_cards_without_context_flags(self):
        out = self._run("Worms", "Flooding", "Dust Seals")
        self.assertEqual(len(out), 4)              # header + 3 card lines
        self.assertNotIn("=" * 20, "\n".join(out))

    def test_cli_full_flag_restores_the_long_report(self):
        out = self._run("--full", "Worms", "Flooding", "Dust Seals")
        self.assertIn("=" * 20, "\n".join(out))

    def test_cli_tableau_flag_keeps_the_long_report(self):
        out = self._run("--tableau", "Ants", "Worms", "Flooding")
        self.assertIn("=" * 20, "\n".join(out))


def game_with_prod(prod=None, **kw):
    g = game(**kw)
    g["me"]["production"] = {"mc": 0, "steel": 0, "titanium": 0, "plants": 0,
                             "energy": 0, "heat": 0} | (prod or {})
    return g


class TestProductionDecreaseRequirement(unittest.TestCase):
    """P8 #4: Food Factory (plant production −1) was rated KEEP for a
    player with no plant production — the card is unplayable until the
    production exists."""

    def test_flags_the_missing_production(self):
        e = research.evaluate(game_with_prod(), ["Food Factory"])[0]
        self.assertEqual(e["prodBlocked"],
                         [{"resource": "plants", "need": 1, "have": 0}])
        self.assertIn("needs plant production ≥ 1 (have 0) — unplayable now",
                      e["prodBlockedText"])

    def test_quick_line_prints_it_and_downgrades_the_verdict(self):
        line = research.quick_lines(game_with_prod(), ["Food Factory"])[0]
        self.assertIn("needs plant production ≥ 1 (have 0) — unplayable now",
                      line)
        self.assertNotIn("→ KEEP", line)

    def test_no_flag_once_the_production_exists(self):
        g = game_with_prod({"plants": 1}, temp=-24, o2=2, oceans=1, gen=2)
        e = research.evaluate(g, ["Food Factory"])[0]
        self.assertNotIn("prodBlocked", e)
        line = research.quick_lines(g, ["Food Factory"])[0]
        self.assertNotIn("unplayable now", line)
        self.assertIn("→ KEEP", line)

    def test_unknown_production_is_never_claimed_unplayable(self):
        """A state without a production block (fixtures, partial views)
        must not produce a false 'unplayable' claim."""
        e = research.evaluate(game(), ["Food Factory"])[0]
        self.assertNotIn("prodBlocked", e)

    def test_full_report_prints_the_line(self):
        import contextlib, io, json, tempfile
        from unittest import mock
        buf = io.StringIO()
        with tempfile.TemporaryDirectory() as d:
            state = Path(d) / "game.json"
            state.write_text(json.dumps(game_with_prod()))
            with mock.patch.object(sys, "argv",
                                   ["research.py", "--state", str(state),
                                    "--full", "Food Factory"]), \
                    contextlib.redirect_stdout(buf):
                research.main()
        self.assertIn("needs plant production ≥ 1 (have 0) — unplayable now",
                      buf.getvalue())


class TestWindfallPricing(unittest.TestCase):
    """P8 #5: Imported Hydrogen was priced as 'ocean ×1 = 14 → PASS',
    ignoring the 3 plants it also gains (KB: a windfall plant/steel/
    titanium/card ≈ 2 MC)."""

    def test_imported_hydrogen_prices_the_three_plants(self):
        line = research.quick_lines(game(), ["Imported Hydrogen"])[0]
        self.assertIn("ocean ×1", line)
        self.assertIn("plants ×3", line)
        self.assertIn("= 20", line)                  # 14 ocean + 6 windfall
        self.assertIn("→ KEEP", line)

    def test_windfall_rate_is_two_mc_per_unit(self):
        self.assertEqual(research.WINDFALL["plants"], 2)
        self.assertEqual(research.WINDFALL["steel"], 2)
        self.assertEqual(research.WINDFALL["titanium"], 2)
        self.assertEqual(research.WINDFALL["cards"], 2)
        self.assertEqual(research.WINDFALL["heat"], 1)   # KB: 2 heat = 2 MC

    def test_trigger_card_text_is_not_mistaken_for_a_windfall(self):
        """'When you play a plant tag … gain 1 plant' is a trigger, not a
        one-shot gain — Viral Enhancers stays a JUDGE card."""
        line = research.quick_lines(game(), ["Viral Enhancers"])[0]
        self.assertIn("→ JUDGE", line)

    def test_drawn_cards_are_priced(self):
        card = research._resolve("Business Contacts")
        self.assertIn("drawCard", card.get("behavior") or {})
        line = research.quick_lines(game(), ["Business Contacts"])[0]
        self.assertIn("cards ×", line)


if __name__ == "__main__":
    unittest.main()
