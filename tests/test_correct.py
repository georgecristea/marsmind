"""correct.py — reverse a WRONGLY-APPLIED plan step.

Physical mode's correction tool: inverse events come from the step's OWN
event list and go through the Engine; anything not auto-invertible is a
printed MANUAL note (never a silent partial reverse). Ends by reopening
the step and asking the player to CONFIRM the tracker vs the table.
"""
import sys, tempfile, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from tmlib import Engine, EventError, Store
from test_new_game import SETUP
import correct
import planlib

THREATS = "test threats block"
EXIT = "test exit: card VP; repeatable: greenery from plant production"


class CorrectBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(self.tmp.name)
        self.store.init(SETUP)
        self.eng = Engine(self.store)

    def tearDown(self):
        self.tmp.cleanup()

    def game(self):
        return self.store.load_game()


class TestReversePlayAndPlace(CorrectBase):
    def _do_step(self):
        # unknown-to-db card → explicit cost, no behavior: exact reversal
        self.eng.res("Zed", "mc", +30)
        self.eng.hand_add(["Test Dome"])
        planlib.set_plan(self.store, [
            {"id": "1a", "summary": "Play Test Dome; city on 05",
             "volatility": "safe", "cue": "your city tile on 05",   # cue gate
             "events": [
                 {"method": "play", "args": ["Zed", "Test Dome"],
                  "kwargs": {"cost": 10}},
                 {"method": "place", "args": ["Zed", "city", "05"]}]}], threats=THREATS, exit_=EXIT)
        planlib.mark_done(self.store, "1a", confirm="ok")

    def test_reversal_restores_mc_hand_and_board(self):
        self._do_step()
        g = self.game()
        self.assertEqual(g["me"]["resources"]["mc"], 20)
        self.assertIn("05", g["board"])
        lines = correct.reverse_step(self.store, "1a")
        g = self.game()
        self.assertEqual(g["me"]["resources"]["mc"], 30)     # cost refunded
        self.assertNotIn("05", g.get("board", {}))           # tile removed
        self.assertIn("Test Dome", g["me"]["hand"])          # back in hand
        self.assertEqual(g["me"]["playedCards"], [])
        text = "\n".join(lines)
        self.assertIn("CONFIRM this matches the table", lines[-1])
        self.assertIn("unplay", text.lower())
        self.assertIn("unplace", text.lower())

    def test_step_is_reopened_and_logged(self):
        self._do_step()
        correct.reverse_step(self.store, "1a")
        self.assertFalse(planlib.load_plan(self.store)["steps"][0]["done"])
        log = (Path(self.tmp.name) / "state" / "log.md").read_text()
        self.assertIn("CORRECTION", log)
        self.assertIn("Reopened", log)

    def test_every_inverse_event_is_printed(self):
        self._do_step()
        lines = correct.reverse_step(self.store, "1a")
        applied = [l for l in lines if "✓" in l]
        # unplay + hand return + MC refund + unplace, each named
        self.assertGreaterEqual(len(applied), 4)


class TestManualNotes(CorrectBase):
    def test_convert_is_named_manual_and_skipped(self):
        self.eng.res("Zed", "heat", +8)
        planlib.set_plan(self.store, [
            {"id": "1a", "summary": "convert heat", "volatility": "safe",
             "events": [{"method": "convert", "args": ["Zed", "heat"]}]}], threats=THREATS, exit_=EXIT)
        planlib.mark_done(self.store, "1a")
        lines = correct.reverse_step(self.store, "1a")
        text = "\n".join(lines)
        self.assertIn("MANUAL", text)
        self.assertIn("convert", text)
        self.assertIn("res/tr/sync --force", text)
        g = self.game()
        self.assertEqual(g["me"]["resources"]["heat"], 0)    # NOT auto-undone
        self.assertEqual(g["globals"]["temperature"], -28)
        self.assertFalse(planlib.load_plan(self.store)["steps"][0]["done"])

    def test_milestone_and_standard_named_manual(self):
        self.eng.res("Zed", "mc", +40)
        planlib.set_plan(self.store, [
            {"id": "1a", "summary": "SP asteroid", "volatility": "safe",
             "events": [{"method": "standard", "args": ["Zed", "asteroid"]}]}], threats=THREATS, exit_=EXIT)
        planlib.mark_done(self.store, "1a")
        text = "\n".join(correct.reverse_step(self.store, "1a"))
        self.assertIn("MANUAL", text)
        self.assertIn("standard", text)


class TestSimpleInverses(CorrectBase):
    def test_res_and_tr_events_negated(self):
        planlib.set_plan(self.store, [
            {"id": "1a", "summary": "gains", "volatility": "safe",
             "events": [{"method": "res", "args": ["Zed", "mc", 5]},
                        {"method": "tr", "args": ["Zed", 2]}]}], threats=THREATS, exit_=EXIT)
        planlib.mark_done(self.store, "1a")
        self.assertEqual(self.game()["me"]["tr"], 22)
        correct.reverse_step(self.store, "1a")
        g = self.game()
        self.assertEqual(g["me"]["resources"]["mc"], 0)
        self.assertEqual(g["me"]["tr"], 20)

    def test_prod_event_negated(self):
        planlib.set_plan(self.store, [
            {"id": "1a", "summary": "prod", "volatility": "safe",
             "events": [{"method": "prod", "args": ["Zed", "energy", 2]}]}], threats=THREATS, exit_=EXIT)
        planlib.mark_done(self.store, "1a")
        correct.reverse_step(self.store, "1a")
        self.assertEqual(self.game()["me"]["production"]["energy"], 0)

    def test_use_action_ledger_cleared(self):
        self.eng.register_action("Ironworks")
        self.eng.res("Zed", "energy", +4)   # Ironworks: spend 4 energy
        planlib.set_plan(self.store, [
            {"id": "1a", "summary": "Ironworks action", "volatility": "safe",
             "events": [{"method": "use_action", "args": ["Ironworks"]}]}], threats=THREATS, exit_=EXIT)
        planlib.mark_done(self.store, "1a")
        self.assertTrue(self.game()["me"]["actionsThisGen"]["Ironworks"]["used"])
        correct.reverse_step(self.store, "1a")
        self.assertFalse(self.game()["me"]["actionsThisGen"]["Ironworks"]["used"])


class TestReverseActionEffects(CorrectBase):
    """P8 #23 — since the ACTION_EFFECTS cards became mechanical, reversing
    a `use_action` step must undo the resources/globals/TR too, not just
    free the once-per-generation ledger."""

    def _use_in_a_step(self, card, events=None, **play_kw):
        self.eng.res("Zed", "mc", +99)
        self.eng.hand_add([card])
        self.eng.play("Zed", card, **play_kw)
        planlib.set_plan(self.store, [
            {"id": "1a", "summary": f"{card} action", "volatility": "safe",
             "events": events or [{"method": "use_action", "args": [card]}]}],
            threats=THREATS, exit_=EXIT)
        planlib.mark_done(self.store, "1a")

    def test_physics_complex_reversed_energy_and_science_resource(self):
        self.eng.res("Zed", "energy", +6)
        self._use_in_a_step("Physics Complex")
        g = self.game()
        self.assertEqual(g["me"]["resources"]["energy"], 0)
        self.assertEqual(g["me"]["cardResources"]["Physics Complex"], 1)
        correct.reverse_step(self.store, "1a")
        g = self.game()
        self.assertEqual(g["me"]["resources"]["energy"], 6)
        self.assertEqual(g["me"]["cardResources"]["Physics Complex"], 0)
        self.assertFalse(
            g["me"]["actionsThisGen"]["Physics Complex"]["used"])

    def test_aquifer_pumping_reversed_mc_ocean_and_tr(self):
        self._use_in_a_step("Aquifer Pumping")
        g = self.game()
        mc_after, tr_after = g["me"]["resources"]["mc"], g["me"]["tr"]
        self.assertEqual(g["globals"]["oceans"], 1)
        correct.reverse_step(self.store, "1a")
        g = self.game()
        self.assertEqual(g["me"]["resources"]["mc"], mc_after + 8)
        self.assertEqual(g["globals"]["oceans"], 0)
        self.assertEqual(g["me"]["tr"], tr_after - 1)
        self.assertFalse(
            g["me"]["actionsThisGen"]["Aquifer Pumping"]["used"])

    def test_caretaker_contract_reversed_heat_and_tr(self):
        self.eng.res("Zed", "heat", +8)
        self._use_in_a_step("Caretaker Contract",
                            ignore_requirements="test: temperature waived")
        g = self.game()
        self.assertEqual(g["me"]["resources"]["heat"], 0)
        tr_after = g["me"]["tr"]
        correct.reverse_step(self.store, "1a")
        g = self.game()
        self.assertEqual(g["me"]["resources"]["heat"], 8)
        self.assertEqual(g["me"]["tr"], tr_after - 1)
        self.assertFalse(
            g["me"]["actionsThisGen"]["Caretaker Contract"]["used"])

    def test_reversal_trace_names_every_inverse(self):
        self.eng.res("Zed", "energy", +4)
        self._use_in_a_step("Ironworks")
        lines = correct.reverse_step(self.store, "1a")
        text = "\n".join(lines)
        self.assertIn("✓", text)
        self.assertIn("Ironworks", text)
        g = self.game()
        self.assertEqual(g["me"]["resources"]["energy"], 4)
        self.assertEqual(g["me"]["resources"]["steel"], 0)
        self.assertEqual(g["globals"]["oxygen"], 0)

    def test_uninvertible_effect_prints_manual_and_still_frees_the_ledger(self):
        self.eng.res("Zed", "energy", +6)
        self._use_in_a_step("Physics Complex")
        g = self.game()                       # the resource is gone already
        g["me"]["cardResources"]["Physics Complex"] = 0
        self.store.save_game(g)
        lines = correct.reverse_step(self.store, "1a")
        text = "\n".join(lines)
        self.assertIn("MANUAL", text)
        self.assertIn("Physics Complex", text)
        g = self.game()
        self.assertEqual(g["me"]["resources"]["energy"], 0)   # NOT half-undone
        self.assertFalse(
            g["me"]["actionsThisGen"]["Physics Complex"]["used"])


class TestGuards(CorrectBase):
    def test_open_step_rejected(self):
        planlib.set_plan(self.store, [
            {"id": "1a", "summary": "x", "volatility": "safe", "events": []}], threats=THREATS, exit_=EXIT)
        with self.assertRaises(EventError):
            correct.reverse_step(self.store, "1a")

    def test_unknown_label_rejected(self):
        planlib.set_plan(self.store, [
            {"id": "1a", "summary": "x", "volatility": "safe", "events": []}], threats=THREATS, exit_=EXIT)
        with self.assertRaises(EventError):
            correct.reverse_step(self.store, "9z")

    def test_cli_step_command(self):
        import subprocess
        self.eng.res("Zed", "mc", +5)
        planlib.set_plan(self.store, [
            {"id": "1a", "summary": "spend", "volatility": "safe",
             "events": [{"method": "res", "args": ["Zed", "mc", -5]}]}], threats=THREATS, exit_=EXIT)
        planlib.mark_done(self.store, "1a")
        script = Path(__file__).resolve().parent.parent / "scripts" / "correct.py"
        r = subprocess.run([sys.executable, str(script), "step", "1a"],
                           cwd=self.tmp.name, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("CONFIRM this matches the table", r.stdout)
        self.assertEqual(self.game()["me"]["resources"]["mc"], 5)


if __name__ == "__main__":
    unittest.main()
