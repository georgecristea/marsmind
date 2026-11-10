"""score.py against the FINAL TABLE of every real game we have.

score.py is the only VP source at a physical table and it was never once
run on game night — the audit ranked it the number-one flag, with three
counting bugs and a measured 21-VP error on the eventual winner. The
replay gate already reconstructs every recorded game and holds the app's
own final state, so scoring is checkable for free: replay the game, score
the resulting state, compare with what the app said.

What is asserted, per player and per game:
  * TR — the app's own number;
  * tiles — greeneries and cities, THE tile counter vs the app's board;
  * milestones and awards — 5 VP per claim, and (where the app exports its
    victoryPointsBreakdown) the exact award VP;
  * card VP — exact equality for a tableau with no formula-VP card. A
    formula card (1 VP per animal …) is a disclosed FLOOR, never an
    equality claim, so those players assert `<=` instead.

Every game whose files live under private/ (git-ignored) SKIPS when they
are absent, so this module is green on a fresh clone.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import applog_parser as P                            # noqa: E402
import replay_applog as R                            # noqa: E402
import replay_gate as G                              # noqa: E402
import score                                         # noqa: E402
import tmlib                                         # noqa: E402
from tmlib import Engine, Store                      # noqa: E402

MILESTONE_VP = score.MILESTONE_VP
CITY_LABELS = tmlib.CITY_TILES


def _replay(applog: str, setup: dict, final: dict):
    """The replayed game state + the name-conformed final table."""
    applog, final = G.conform_names(applog, setup, final)
    with tempfile.TemporaryDirectory() as tmp:
        store = Store(Path(tmp))
        store.init(json.loads(json.dumps(setup)))
        eng = Engine(store)
        rep = R.Report()
        players = [p["name"] for p in setup["players"]]
        R.Replayer(eng, rep, verbose=False).run(
            P.group_blocks(P.parse_log(applog, players)))
        return rep.game, final, players


def _tiles_of(final: dict, player: str) -> dict:
    got = {"greeneries": 0, "cities": 0}
    for _sid, tid, owner in final["tiles"]:
        if owner != player:
            continue
        label = G.tile_label(tid)
        if label == "greenery":
            got["greeneries"] += 1
        elif label in CITY_LABELS:
            got["cities"] += 1
    return got


class ScoreSmokeTest(unittest.TestCase):
    """One test per recorded game (populated below)."""


def _make(name, loader):
    def test(self):
        try:
            applog, setup, final = loader()
        except (FileNotFoundError, OSError, KeyError) as e:
            raise unittest.SkipTest(f"{name}: {e}")
        game, final, players = _replay(applog, setup, final)
        rows = {r["name"]: r for r in score.compute(game, "full")["players"]}
        claims = final.get("milestones") or {}
        for p in players:
            row, fin = rows[p], final["players"][p]
            self.assertEqual(row["tr"], fin["tr"], f"{name} {p} TR")

            counts = tmlib.tile_counts(game, p)
            want = _tiles_of(final, p)
            self.assertEqual(counts["greeneries"], want["greeneries"],
                             f"{name} {p} greeneries")
            self.assertEqual(counts["cities"], want["cities"],
                             f"{name} {p} cities")

            if claims:          # some exports carry only the VP breakdown
                mine = sum(1 for who in claims.values() if who == p)
                self.assertEqual(row["milestoneVP"], mine * MILESTONE_VP,
                                 f"{name} {p} milestone VP")

            vp = fin.get("vp")
            if not vp:            # a vendor-db save carries no VP breakdown
                continue
            self.assertEqual(row["milestoneVP"], vp["milestones"],
                             f"{name} {p} milestones vs app")
            self.assertEqual(row["awardVP"], vp["awards"],
                             f"{name} {p} awards vs app")
            self.assertEqual(row["tileVP"], vp["greenery"] + vp["city"],
                             f"{name} {p} tile VP vs app")
            if row["formulaVPCards"]:
                # a disclosed floor, not an equality claim
                self.assertLessEqual(row["cardVP"], vp["victoryPoints"],
                                     f"{name} {p} card VP floor")
            else:
                self.assertEqual(row["cardVP"], vp["victoryPoints"],
                                 f"{name} {p} card VP vs app")
            self.assertEqual(row["total"],
                             vp["total"] - (vp["victoryPoints"] - row["cardVP"]),
                             f"{name} {p} total (net of uncounted card VP)")
    test.__name__ = f"test_{name.replace(':', '_').replace('/', '_').replace('-', '_')}"
    return test


for _name, _loader in G.app_targets({}):
    _t = _make(_name, _loader)
    setattr(ScoreSmokeTest, _t.__name__, _t)


if __name__ == "__main__":
    unittest.main()
