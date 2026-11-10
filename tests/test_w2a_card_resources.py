"""W2-A item 1: per-card resource counts tracked for ALL players.

The reference failure (a real 5p game): the winner's per-resource and
adjacency VP cards were invisible to the tracker, and a 5-point deficit
was relayed as a 5-point lead. The engine must accumulate per-card
resource counts (animals, microbes, fighters, science, floaters) on
playedCards entries for me AND opponents, fed by the applog replay lines
and by the apply.py verbs that express them — and a count that was never
observed must stay UNKNOWN (absent), never a silent zero.

Semantics pinned here:
- my own play of a resource-holding card records an explicit 0 (I am the
  record of my own actions — iron rule 1/3);
- an opponent's play in PHYSICAL mode stays absent: their later
  accumulator actions may never be logged, and a stale 0 is exactly the
  lie that produced the reference failure;
- in APP modes (the log/API names every add/remove) an opponent's play
  records the explicit 0 too, and the replay lane forces it via
  count_known=True regardless of the fixture's gameMode;
- sync_card_resources keeps an explicit 0 (an observed zero is
  knowledge); it no longer drops the entry;
- unplay forgets the count with the card.
"""
import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from tmlib import Store, Engine, EventError          # noqa: E402
from test_new_game import SETUP                       # noqa: E402
import applog_parser as P                             # noqa: E402
import replay_applog as R                             # noqa: E402


class Base(unittest.TestCase):
    game_mode = None                                  # None = SETUP default

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(self.tmp.name)
        setup = copy.deepcopy(SETUP)
        if self.game_mode:
            setup["gameMode"] = self.game_mode
        self.store.init(setup)
        self.eng = Engine(self.store)

    def tearDown(self):
        self.tmp.cleanup()

    def game(self):
        return self.store.load_game()

    def counts(self, player):
        g = self.game()
        pool = g["me"] if g["me"]["name"] == player else g["opponents"][player]
        return pool.get("cardResources") or {}


class TestMyPlayRecordsExplicitZero(Base):
    def test_my_resource_card_starts_at_zero_not_unknown(self):
        self.eng.res("Zed", "mc", +80)
        self.eng.hand_add(["Birds"])
        self.eng.play("Zed", "Birds", ignore_requirements="test")
        self.assertEqual(self.counts("Zed").get("Birds"), 0)

    def test_addresources_on_play_still_lands(self):
        self.eng.res("Zed", "mc", +80)
        self.eng.hand_add(["Pets"])                   # enters with 1 animal
        self.eng.play("Zed", "Pets")
        self.assertEqual(self.counts("Zed").get("Pets"), 1)

    def test_non_resource_card_gets_no_entry(self):
        self.eng.res("Zed", "mc", +80)
        self.eng.hand_add(["Comet"])
        self.eng.play("Zed", "Comet")
        self.assertNotIn("Comet", self.counts("Zed"))

    def test_no_effects_play_still_records_the_zero(self):
        self.eng.res("Zed", "mc", +80)
        self.eng.hand_add(["Birds"])
        self.eng.play("Zed", "Birds", no_effects=True,
                      ignore_requirements="test")
        self.assertEqual(self.counts("Zed").get("Birds"), 0)


class TestPhysicalOpponentStaysUnknown(Base):
    def test_opponent_play_does_not_invent_a_zero(self):
        self.eng.play("Anna", "Security Fleet")
        self.assertNotIn("Security Fleet", self.counts("Anna"))

    def test_count_known_override_records_the_zero(self):
        self.eng.play("Anna", "Security Fleet", count_known=True)
        self.assertEqual(self.counts("Anna").get("Security Fleet"), 0)

    def test_observe_play_never_claims_a_count(self):
        self.eng.observe_play("Anna", "Birds")
        self.assertNotIn("Birds", self.counts("Anna"))


class TestAppModeOpponentIsExact(Base):
    game_mode = "app-practice"

    def test_opponent_play_records_explicit_zero(self):
        self.eng.play("Anna", "Security Fleet")
        self.assertEqual(self.counts("Anna").get("Security Fleet"), 0)


class TestSyncKeepsKnowledge(Base):
    def test_sync_zero_is_recorded_not_dropped(self):
        self.eng.sync_card_resources("Anna", {"Predators": 0})
        self.assertEqual(self.counts("Anna").get("Predators"), 0)

    def test_sync_back_to_zero_keeps_the_entry(self):
        self.eng.sync_card_resources("Anna", {"Predators": 3})
        self.eng.sync_card_resources("Anna", {"Predators": 0})
        self.assertEqual(self.counts("Anna").get("Predators"), 0)

    def test_absent_to_zero_is_a_logged_change(self):
        msg = self.eng.sync_card_resources("Anna", {"Predators": 0})
        self.assertNotIn("no change", msg.lower())


class TestUnplayForgetsTheCount(Base):
    def test_unplay_drops_the_card_resource_entry(self):
        self.eng.res("Zed", "mc", +80)
        self.eng.hand_add(["Birds"])
        self.eng.play("Zed", "Birds", ignore_requirements="test")
        self.eng.sync_card_resources("Zed", {"Birds": 2})
        self.eng.unplay("Zed", "Birds")
        self.assertNotIn("Birds", self.counts("Zed"))


class TestPersistence(Base):
    def test_counts_survive_reload_and_produce(self):
        self.eng.sync_card_resources("Anna", {"Predators": 4})
        self.eng.produce()                        # generation turnover
        fresh = Engine(Store(self.tmp.name))      # a new session
        g = fresh.store.load_game()
        self.assertEqual(g["opponents"]["Anna"]["cardResources"]["Predators"], 4)


class TestReplayAccumulatesForOpponents(Base):
    """Item 1(a): the applog lines 'X added N <Res> to <Card>' /
    'X removed N resource(s) from ...' accumulate on the OPPONENT's
    playedCards counts, and a replayed play records the explicit 0."""

    def replay(self, text):
        rep = R.Report()
        players = [p["name"] for p in self.eng.setup["players"]]
        events = P.parse_log(text, players)
        R.Replayer(self.eng, rep, verbose=False).run(P.group_blocks(events))
        return rep

    def test_replayed_play_records_explicit_zero(self):
        self.replay("Generation 1\nAnna played Security Fleet\n")
        self.assertEqual(self.counts("Anna").get("Security Fleet"), 0)

    def test_added_lines_accumulate(self):
        self.replay(
            "Generation 1\n"
            "Anna played Security Fleet\n"
            "Anna used Security Fleet action\n"
            "Anna added 1 Fighter to Security Fleet\n"
            "Anna used Security Fleet action\n"
            "Anna added 1 Fighter to Security Fleet\n"
            "Anna used Security Fleet action\n"
            "Anna added 1 Fighter to Security Fleet\n")
        self.assertEqual(self.counts("Anna").get("Security Fleet"), 3)

    def test_removed_lines_come_off_the_count(self):
        self.replay(
            "Generation 1\n"
            "Anna played Security Fleet\n"
            "Anna used Security Fleet action\n"
            "Anna added 1 Fighter to Security Fleet\n"
            "Anna used Security Fleet action\n"
            "Anna added 1 Fighter to Security Fleet\n")
        self.eng = Engine(self.store)             # fresh engine, same state
        self.replay("Felix played Predators\n"
                    "Felix added 1 Animal to Predators\n"
                    "Anna removed 1 resource(s) from Anna's Security Fleet\n")
        self.assertEqual(self.counts("Anna").get("Security Fleet"), 1)


class TestSnapCardField(unittest.TestCase):
    """apply.py snap <player> card:<Card Name> <n> — the physical-table
    channel for an observed accumulator (walked tableau, opponent's
    announced count). A card's resource pile is a public anchor like a TR
    marker; the observation routes through Engine.sync_card_resources
    (iron rule 2)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(self.tmp.name)
        self.store.init(copy.deepcopy(SETUP))

    def tearDown(self):
        self.tmp.cleanup()

    def run_apply(self, *args):
        return subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "apply.py"), *args],
            cwd=self.tmp.name, capture_output=True, text=True)

    def test_records_an_observed_count(self):
        r = self.run_apply("snap", "Anna", "card:Security Fleet", "3")
        self.assertEqual(r.returncode, 0, r.stderr)
        g = json.loads((Path(self.tmp.name) / "state" / "game.json").read_text())
        self.assertEqual(g["opponents"]["Anna"]["cardResources"],
                         {"Security Fleet": 3})

    def test_negative_count_refused(self):
        r = self.run_apply("snap", "Anna", "card:Security Fleet", "--", "-1")
        self.assertNotEqual(r.returncode, 0)

    def test_empty_card_name_refused(self):
        r = self.run_apply("snap", "Anna", "card:", "2")
        self.assertNotEqual(r.returncode, 0)


if __name__ == "__main__":
    unittest.main()
