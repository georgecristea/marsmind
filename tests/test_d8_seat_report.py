"""D8 — structurally validated seat reports (Codex C2).

A seat's free-form end-of-game report named hidden opening keeps: the
advisor received hidden information and the game stopped being clean
strategy evidence. The same breach class exists for every seat model.

`scripts/seat_report.py <pid>` composes the seat's report SOLELY from the
public projection of the seat's own /api/player view (pass state, one line
of public actions this generation, MC/TR, hand COUNT) plus, separately,
exact technical errors the seat passes in with --error. It REFUSES to
print any report in which a card name outside the seat's PUBLIC tableau
appears — whether the name came from --note, --error or the app log.

Every card name below is drawn from cards/db.json at test time, so the
test never carries a card-specific literal; the stubbed view puts a
sentinel string into every private field of the vendor's PlayerViewModel
so leakage of any non-public field is caught structurally.
"""
import io
import json
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import seat_report  # noqa: E402

DB_NAMES = sorted(c["name"] for c in
                  json.loads((ROOT / "cards" / "db.json").read_text())["cards"])
PUBLIC_CARD = DB_NAMES[0]          # in the seat's tableau
HIDDEN_CARD = DB_NAMES[-1]         # never public in this game
SENTINEL = "ZZ-PRIVATE-FIELD-ZZ"


def _view(*, passed=False, phase="action", tableau=(PUBLIC_CARD,)):
    """A /api/player payload for the seat: public fields as the vendor's
    PublicPlayerModel names them, every PlayerViewModel-private field
    populated with a sentinel."""
    private_card = {"name": SENTINEL}
    return {
        "id": "p-seat",
        "cardsInHand": [private_card, {"name": HIDDEN_CARD}],
        "dealtCorporationCards": [private_card],
        "dealtPreludeCards": [private_card],
        "dealtProjectCards": [private_card],
        "dealtCeoCards": [private_card],
        "draftedCards": [private_card],
        "ceoCardsInHand": [private_card],
        "pickedCorporationCard": [private_card],
        "preludeCardsInHand": [private_card],
        "waitingFor": {"type": "or", "title": SENTINEL},
        "game": {"phase": phase, "generation": 4,
                 "passedPlayers": ["red"] if passed else []},
        "thisPlayer": {
            "name": "Ana", "color": "red", "isActive": not passed,
            "megacredits": 23, "terraformRating": 27,
            "cardsInHandNbr": 2, "actionsTakenThisRound": 2,
            "actionsThisGeneration": [],
            "tableau": [{"name": n} for n in tableau],
        },
        "players": [
            {"name": "Ana", "color": "red", "terraformRating": 27,
             "tableau": [{"name": n} for n in tableau]},
            {"name": "Zed", "color": "blue", "terraformRating": 20,
             "tableau": [{"name": HIDDEN_CARD}]},
        ],
    }


def _log(*entries):
    """LogMessage entries: (message, data, private_pid_or_None)."""
    out = []
    for message, data, private in entries:
        e = {"message": message, "data": data}
        if private:
            e["playerId"] = private
        out.append(e)
    return out


def _player(color):
    return {"type": int(seat_report.DataType.PLAYER), "value": color}


def _card(name):
    return {"type": int(seat_report.DataType.CARD), "value": name}


def _run(argv, view=None, log=None):
    """Run main() with injected fetchers; returns (exit, stdout, stderr)."""
    view = _view() if view is None else view
    log = [] if log is None else log
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = seat_report.main(argv, get=lambda pid: view,
                              logs=lambda pid, gen: log)
    return rc, out.getvalue(), err.getvalue()


class TestFirewall(unittest.TestCase):
    def test_hidden_card_in_note_is_rejected_and_never_printed(self):
        rc, out, err = _run(["p-seat", "--note",
                             f"kept {HIDDEN_CARD} for next generation"])
        self.assertEqual(rc, 2)
        self.assertEqual(out, "", "a refused report prints NOTHING on stdout")
        self.assertIn("REFUSED", err)
        self.assertNotIn(HIDDEN_CARD, err, "the reason must not echo the name")
        self.assertIn("public tableau", err)

    def test_public_tableau_card_is_reported(self):
        rc, out, err = _run(["p-seat", "--note", f"played {PUBLIC_CARD}"])
        self.assertEqual(rc, 0, err)
        self.assertIn(PUBLIC_CARD, out)

    def test_opponent_public_card_is_not_the_seats_to_report(self):
        # HIDDEN_CARD sits in Zed's tableau (public to everyone) but the
        # seat's own report is bounded by the SEAT's tableau — the
        # strictest reading of D8, and the one the advisor can verify.
        rc, out, _ = _run(["p-seat", "--note", f"Zed played {HIDDEN_CARD}"])
        self.assertEqual(rc, 2)
        self.assertEqual(out, "")

    def test_error_channel_passes_through_verbatim(self):
        msg = ("HTTP 400 Not a valid space id | sent: "
               '{"type":"space","spaceId":"15"}')
        rc, out, err = _run(["p-seat", "--error", msg])
        self.assertEqual(rc, 0, err)
        self.assertIn(f"ERROR: {msg}", out)

    def test_error_naming_a_hidden_card_is_rejected(self):
        rc, out, err = _run(["p-seat", "--error",
                             f"HTTP 400 Unknown card name {HIDDEN_CARD}"])
        self.assertEqual(rc, 2)
        self.assertEqual(out, "")
        self.assertNotIn(HIDDEN_CARD, err)

    def test_public_name_containing_a_shorter_card_name_is_fine(self):
        # A tableau card whose name embeds another card's name (e.g.
        # "<X> Outpost" vs "<X>") must not trip the scanner — public
        # names are masked before the hidden scan.
        long = next((n for n in DB_NAMES
                     if any(o != n and o in n for o in DB_NAMES)), None)
        if long is None:
            self.skipTest("db has no nested card names")
        view = _view(tableau=(long,))
        rc, out, err = _run(["p-seat", "--note", f"played {long}"], view=view)
        self.assertEqual(rc, 0, err)
        self.assertIn(long, out)


class TestPublicOnly(unittest.TestCase):
    def test_report_contains_no_private_field(self):
        rc, out, err = _run(["p-seat"])
        self.assertEqual(rc, 0, err)
        self.assertNotIn(SENTINEL, out)
        self.assertNotIn(HIDDEN_CARD, out)
        self.assertNotIn(SENTINEL, err)

    def test_public_projection_whitelists_fields(self):
        pub = seat_report.public_view(_view())
        self.assertEqual(set(pub), set(seat_report.PUBLIC_FIELDS))
        self.assertNotIn(SENTINEL, json.dumps(pub))
        self.assertNotIn(HIDDEN_CARD, json.dumps(pub))

    def test_private_log_entries_are_withheld(self):
        # a private LogMessage (playerId set — "You drew X") must never
        # reach the action line, even though the app sends it to the seat
        log = _log(("${0} drew ${1}", [_player("red"), _card(HIDDEN_CARD)], "p-seat"),
                   ("${0} played ${1}", [_player("red"), _card(PUBLIC_CARD)], None),
                   ("${0} played ${1}", [_player("blue"), _card(HIDDEN_CARD)], None))
        rc, out, err = _run(["p-seat"], log=log)
        self.assertEqual(rc, 0, err)
        self.assertIn(f"Ana played {PUBLIC_CARD}", out)
        self.assertNotIn(HIDDEN_CARD, out)

    def test_public_log_line_naming_a_non_tableau_card_is_withheld(self):
        # e.g. a sold/discarded card named by the app's own public log:
        # withheld and counted, the report itself is still produced
        log = _log(("${0} discarded ${1}", [_player("red"), _card(HIDDEN_CARD)], None),
                   ("${0} passed", [_player("red")], None))
        rc, out, err = _run(["p-seat"], log=log)
        self.assertEqual(rc, 0, err)
        self.assertNotIn(HIDDEN_CARD, out)
        self.assertIn("1 log line withheld", out)
        self.assertIn("Ana passed", out)


class TestShape(unittest.TestCase):
    def test_pass_state_mc_tr_and_hand_count(self):
        rc, out, err = _run(["p-seat"], view=_view(passed=True))
        self.assertEqual(rc, 0, err)
        self.assertIn("status: passed", out)
        self.assertIn("MC 23", out)
        self.assertIn("TR 27", out)
        self.assertIn("hand 2 cards", out)
        self.assertIn("gen 4", out)

    def test_active_and_ended_states(self):
        _, out, _ = _run(["p-seat"], view=_view(passed=False))
        self.assertIn("status: active", out)
        _, out, _ = _run(["p-seat"], view=_view(phase="end"))
        self.assertIn("status: GAME ENDED", out)

    def test_no_log_falls_back_to_public_counters(self):
        _, out, _ = _run(["p-seat"])
        self.assertIn("did: 2 action(s) this round", out)


if __name__ == "__main__":
    unittest.main()
