"""Grid refs (app row J), --ignore-requirements, or-choice order, unplace
<player>, and the `paid N MC (base C)` trace line (groundwork for
discounts). Each was a friction entry from a real online game:

- the online app labels the bottom row J (it skips the letter I); our
  board rows are A..I. `place Carl ocean J5` failed as "off the board".
- `play` had no --ignore-requirements; Inventrix / Adaptation
  Technology plays were hand-logged as res/prod events.
- `play … --choice 1` on Artificial Photosynthesis applied the PLANT
  branch — the db lists energy first, the card text lists plants first.
  Contract: choice indices follow the ORDER THE CARD TEXT lists the
  options; without --choice the engine prints the branches and refuses.
- `unplace` took only <space>; `place` takes <player> <type> <space>.
"""
import json, subprocess, sys, tempfile, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import tmlib
from tmlib import Store, Engine, EventError
from test_new_game import SETUP
from test_cli import run, SETUP_ANSWERS


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

    def log(self):
        return self.store.log_path.read_text()


# ── app row J ───────────────────────────────────────────────────

class TestGridRowJ(unittest.TestCase):
    def test_app_row_j_is_our_row_i(self):
        self.assertEqual(tmlib.grid_to_space("J5"), "63")
        self.assertEqual(tmlib.grid_to_space("J1"), "59")
        self.assertEqual(tmlib.grid_to_space("j5"), "63")

    def test_our_row_i_still_works(self):
        self.assertEqual(tmlib.grid_to_space("I5"), "63")
        self.assertEqual(tmlib.grid_to_space("I1"), "59")

    def test_beyond_the_board_rejected(self):
        with self.assertRaises(EventError):
            tmlib.grid_to_space("K1")
        with self.assertRaises(EventError):
            tmlib.grid_to_space("J6")

    def test_genuine_tenth_row_refuses_the_alias(self):
        # A board that really has a row at y=9 makes "J" ambiguous — refuse
        # rather than silently pick one.
        board = {str(i): {"id": f"{i:02d}", "x": i, "y": 8} for i in range(1, 6)}
        board["77"] = {"id": "77", "x": 1, "y": 9}
        with self.assertRaises(EventError) as cm:
            tmlib.grid_to_space("J1", board)
        self.assertIn("10th row", str(cm.exception))

    def test_app_label_and_space_to_grid(self):
        self.assertEqual(tmlib.space_to_grid("63"), "I5")
        self.assertEqual(tmlib.app_label("63"), "J5")
        self.assertEqual(tmlib.app_label(59), "J1")
        self.assertEqual(tmlib.app_label("17"), "C4")     # rows above I unchanged
        self.assertEqual(tmlib.space_to_grid("17"), "C4")
        with self.assertRaises(EventError):
            tmlib.app_label("99")


class TestPlaceRowJ(Base):
    def test_place_ocean_on_j5_lands_on_63_and_prints_the_app_label(self):
        msg = self.eng.place("Anna", "ocean", "J5")
        self.assertIn("63", self.game()["board"])
        self.assertEqual(self.game()["board"]["63"]["tile"], "ocean")
        self.assertIn("J5", msg)          # what the player sees in the app
        self.assertIn("I5", msg)          # what render_board prints


# ── ignore-requirements ───────────────────────────────────────────────────

class TestIgnoreRequirements(Base):
    def setUp(self):
        super().setUp()
        self.eng.res("Zed", "mc", +30)
        self.eng.hand_add(["Wave Power"])      # min 3 oceans; we have 0

    def test_refused_without_the_flag(self):
        with self.assertRaises(EventError) as cm:
            self.eng.play("Zed", "Wave Power")
        self.assertIn("requirement", str(cm.exception))
        self.assertEqual(self.game()["me"]["production"]["energy"], 0)

    def test_applied_with_the_flag_and_log_says_why(self):
        msg = self.eng.play("Zed", "Wave Power",
                            ignore_requirements="Inventrix ±2")
        self.assertEqual(self.game()["me"]["production"]["energy"], 1)
        self.assertIn("waived", msg.lower())
        self.assertIn("Inventrix ±2", msg)
        log = self.log()
        self.assertIn("waived", log.lower())
        self.assertIn("Inventrix ±2", log)

    def test_bare_true_still_names_the_waiver(self):
        msg = self.eng.play("Zed", "Wave Power", ignore_requirements=True)
        self.assertIn("waived", msg.lower())


# ── or-choice order ───────────────────────────────────────────────────

SECOND_OR_CARD = {
    # Synthetic second or-choice card: db lists the branches in the OPPOSITE
    # order of the card text, exactly like Artificial Photosynthesis.
    "name": "Test Or Card", "type": "automated", "cost": 5, "tags": [],
    "requirements": None, "vp": None, "number": "T1", "action": None,
    "module": "test",
    "effects": "Gain 3 heat or increase your MC production 1 step.",
    "behavior": {"or": {"behaviors": [
        {"production": {"megacredits": 1},
         "title": "Increase your MC production 1 step"},
        {"stock": {"heat": 3}, "title": "Gain 3 heat"},
    ]}},
}


class TestOrChoiceCardTextOrder(Base):
    def setUp(self):
        super().setUp()
        self.eng.res("Anna", "mc", +99)
        self.eng.res("Zed", "mc", +99)
        self.eng.hand_add(["Artificial Photosynthesis"])
        import cards as _cards
        db = json.loads(json.dumps(_cards.load_db()))    # private copy
        db["cards"].append(SECOND_OR_CARD)
        self.eng._card_db = db

    def opp_prod(self):
        return self.game()["opponents"]["Anna"]["production"]

    def test_choice_0_is_plants_choice_1_is_energy(self):
        # Card text: "Increase your plant production 1 step OR your energy
        # production 2 steps" → 0 = plants, 1 = energy (db order is reversed).
        self.eng.play("Anna", "Artificial Photosynthesis", choice=0)
        self.assertEqual(self.opp_prod()["plants"], 1)
        self.assertEqual(self.opp_prod()["energy"], 0)
        msg = self.eng.play("Zed", "Artificial Photosynthesis", choice=1)
        me = self.game()["me"]["production"]
        self.assertEqual(me["energy"], 2)
        self.assertEqual(me["plants"], 0)
        self.assertIn("choice 1", msg)
        self.assertIn("energy production 2 steps", msg)

    def test_no_choice_lists_branches_and_refuses(self):
        # MY play must be exact (an opponent's is flagged instead — their
        # state is an estimate and a log line must never be blocked).
        self.eng.hand_add(["Artificial Photosynthesis"])
        with self.assertRaises(EventError) as cm:
            self.eng.play("Zed", "Artificial Photosynthesis")
        text = str(cm.exception)
        self.assertIn("--choice 0", text)
        self.assertIn("--choice 1", text)
        self.assertLess(text.index("plant production 1 step"),
                        text.index("energy production 2 steps"))
        self.assertEqual(self.game()["me"]["playedCards"], [])
        self.assertEqual(self.game()["me"]["production"]["plants"], 0)

    def test_out_of_range_choice_refused(self):
        with self.assertRaises(EventError):
            self.eng.play("Anna", "Artificial Photosynthesis", choice=2)

    def test_second_or_card_follows_its_text_order(self):
        # text: "Gain 3 heat or increase your MC production 1 step"
        # → 0 = heat (db index 1), 1 = MC production (db index 0)
        self.eng.play("Anna", "Test Or Card", choice=0)
        opp = self.game()["opponents"]["Anna"]
        self.assertEqual(opp["resources"]["heat"], 3)
        self.assertEqual(opp["production"]["mc"], 0)
        self.eng.play("Anna", "Test Or Card", choice=1)
        opp = self.game()["opponents"]["Anna"]
        self.assertEqual(opp["production"]["mc"], 1)
        self.assertEqual(opp["resources"]["heat"], 3)

    def test_or_branches_helper_exposes_the_mapping(self):
        info = self.eng.card("Artificial Photosynthesis")
        titles = [b["title"] for b in tmlib.or_branches(info)]
        self.assertEqual(titles, ["Increase your plant production 1 step",
                                  "Increase your energy production 2 steps"])


# ── unplace <player> ───────────────────────────────────────────────────

class TestUnplaceWithPlayer(Base):
    def setUp(self):
        super().setUp()
        self.eng.place("Anna", "city", "C4")

    def test_old_signature_still_works(self):
        self.eng.unplace("C4")
        self.assertNotIn("17", self.game()["board"])

    def test_owner_verified_when_given(self):
        with self.assertRaises(EventError) as cm:
            self.eng.unplace("C4", player="Zed")
        self.assertIn("Anna", str(cm.exception))
        self.assertIn("17", self.game()["board"])
        msg = self.eng.unplace("C4", player="ana")   # alias resolves
        self.assertIn("Anna", msg)
        self.assertNotIn("17", self.game()["board"])


# ── paid trace line ────────────────────────────────────────────

class TestPaidTraceLine(Base):
    def setUp(self):
        super().setUp()
        self.eng.res("Zed", "mc", +60)
        self.eng.res("Anna", "mc", +60)

    def test_my_play_prints_paid_and_base(self):
        self.eng.hand_add(["Business Contacts"])
        msg = self.eng.play("Zed", "Business Contacts", cost=4)
        self.assertIn("paid 4 MC (base 7)", msg)

    def test_steel_reduces_paid_not_base(self):
        self.eng.res("Zed", "steel", +2)
        self.eng.hand_add(["Mining Rights"])           # 9 MC, building
        msg = self.eng.play("Zed", "Mining Rights", steel=2)
        self.assertIn("paid 5 MC (base 9)", msg)

    def test_opponent_play_prints_paid_and_base(self):
        msg = self.eng.play("Anna", "Mining Rights")
        self.assertIn("paid 9 MC (base 9)", msg)
        self.assertIn("paid 9 MC (base 9)", self.log())


# ── CLI wiring ─────────────────────────────────────────────────

class TestCLI(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cwd = self.tmp.name
        r = run(["setup.py"], self.cwd, stdin=SETUP_ANSWERS)
        assert r.returncode == 0, r.stderr

    def tearDown(self):
        self.tmp.cleanup()

    def game(self):
        return json.loads((Path(self.cwd) / "state" / "game.json").read_text())

    def log(self):
        return (Path(self.cwd) / "state" / "log.md").read_text()

    def test_place_accepts_app_row_j(self):
        r = run(["apply.py", "place", "Anna", "ocean", "J5"], self.cwd)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.game()["board"]["63"]["tile"], "ocean")

    def test_ignore_requirements_flag(self):
        run(["apply.py", "res", "Zed", "mc", "+30"], self.cwd)
        run(["apply.py", "hand", "add", "Wave Power"], self.cwd)
        r = run(["apply.py", "play", "Zed", "Wave Power"], self.cwd)
        self.assertNotEqual(r.returncode, 0)
        r = run(["apply.py", "play", "Zed", "Wave Power",
                 "--ignore-requirements", "Inventrix +/-2"], self.cwd)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("waived", r.stdout.lower())
        self.assertIn("Inventrix +/-2", self.log())
        self.assertEqual(self.game()["me"]["production"]["energy"], 1)

    def test_choice_without_flag_lists_branches(self):
        run(["apply.py", "res", "Zed", "mc", "+30"], self.cwd)
        run(["apply.py", "hand", "add", "Artificial Photosynthesis"], self.cwd)
        r = run(["apply.py", "play", "Zed", "Artificial Photosynthesis"], self.cwd)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("--choice 0", r.stderr)
        r = run(["apply.py", "play", "Zed", "Artificial Photosynthesis",
                 "--choice", "1"], self.cwd)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.game()["me"]["production"]["energy"], 2)

    def test_unplace_both_signatures(self):
        run(["apply.py", "place", "Anna", "city", "C4"], self.cwd)
        r = run(["apply.py", "unplace", "Zed", "C4"], self.cwd)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("Anna", r.stderr)
        r = run(["apply.py", "unplace", "Anna", "C4"], self.cwd)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("17", self.game().get("board", {}))
        run(["apply.py", "place", "Anna", "city", "C4"], self.cwd)
        r = run(["apply.py", "unplace", "C4"], self.cwd)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("17", self.game().get("board", {}))
        r = run(["apply.py", "unplace", "a", "b", "c"], self.cwd)
        self.assertNotEqual(r.returncode, 0)

    def test_play_trace_has_paid_line(self):
        r = run(["apply.py", "play", "blue", "Mining Rights"], self.cwd)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("paid 9 MC (base 9)", r.stdout)


if __name__ == "__main__":
    unittest.main()
