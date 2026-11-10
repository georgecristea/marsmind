"""PHOBOS state library — all game-state reads/writes go through here.

Iron rules: state lives only in files; every change is validated,
applied by code (never by hand), and logged to state/log.md.
"""
from __future__ import annotations

class EventError(Exception):
    """An event that is illegal or can't be applied to current state."""



RESOURCES = ("mc", "steel", "titanium", "plants", "energy", "heat")

GLOBAL_START = {"temperature": -30, "oxygen": 0, "oceans": 0}
STARTING_TR = 20  # multiplayer base game


def _zeros() -> dict:
    return {r: 0 for r in RESOURCES}


def player_pool(game: dict, name: str) -> dict:
    """The state pool of a player by CANONICAL name: game['me'] for me,
    game['opponents'][name] otherwise. Unknown names are refused — a price
    or a metric for a player who is not in the game is never silently
    computed from an empty pool."""
    if name == game["me"].get("name"):
        return game["me"]
    opps = game.get("opponents") or {}
    if name not in opps:
        raise EventError(f"Unknown player {name!r} (not me, not an opponent)")
    return opps[name]


def all_pools(game: dict) -> list[tuple[str, dict]]:
    """[(player name, state pool)] for me + every opponent (fog-tolerant:
    a missing opponents map reads as none)."""
    return ([(game["me"].get("name"), game["me"])]
            + list((game.get("opponents") or {}).items()))


def validate_setup(setup: dict) -> None:
    """Reject inconsistent setup before any state is written (findings 2/6/11)."""
    players = setup["players"]
    names = [p["name"] for p in players]
    # 2-6: the official box caps at 5, the online app allows 6.
    if not 2 <= len(players) <= 6 or setup.get("playerCount") != len(players):
        raise EventError(f"playerCount must be 2-6 and match players ({len(players)})")
    if len({n.lower() for n in names}) != len(names):
        raise EventError(f"Player names must be unique: {names}")
    colors = [p["color"].lower() for p in players]
    if len(set(colors)) != len(colors):
        raise EventError(f"Player colors must be unique: {colors}")
    if sum(1 for p in players if p.get("isMe")) != 1:
        raise EventError("Exactly one player must have isMe=true")
    if sorted(setup["seatingOrder"]) != sorted(names):
        raise EventError(
            f"seatingOrder {setup['seatingOrder']} must be a permutation of "
            f"player names {names} — check for typos")
    if setup["firstPlayerGen1"] not in names:
        raise EventError(
            f"firstPlayerGen1 {setup['firstPlayerGen1']!r} is not a player: {names}")


# What the shipped data actually backs. extract_cards.py filters to the
# BASE + CORP_ERA manifests by construction, and extract_board.py reads
# TharsisBoard.ts with Tharsis-specific volcano and Noctis handling.
# `wgt` (the solar phase) and the draft variant add no cards, so they need
# no data.
BACKED_EXPANSIONS = {"base", "corporateEra", "wgt"}
BACKED_MAPS = {"tharsis"}


def setup_coverage_warnings(setup: dict) -> list[str]:
    """Setup choices the shipped data cannot back — ADVISORY, never fatal.

    validate_setup checks players, colours and seating; nothing checked the
    expansions or the map, so a Prelude or Hellas game could be created and
    would only fail in play: an unknown card raises "not in cards/db.json"
    on `play`, and a different map makes every hex id and placement bonus
    wrong. The player may knowingly accept degraded tracking (unknown cards
    can be driven with an explicit --cost); the point is that the choice is
    visible at setup instead of discovered in generation 4.
    """
    out = []
    extra = [e for e in (setup.get("expansions") or [])
             if e and e not in BACKED_EXPANSIONS]
    if extra:
        out.append(
            f"expansion(s) {', '.join(sorted(extra))} are NOT in cards/db.json "
            f"(it holds base + corporateEra only). Their cards will fail `play` "
            f"with 'not in cards/db.json'; you can still drive them with an "
            f"explicit --cost, but tags, VP and effects will not be tracked.")
    game_map = (setup.get("map") or "tharsis").lower()
    if game_map not in BACKED_MAPS:
        out.append(
            f"map {game_map!r} is NOT the board in board.json (tharsis). Hex "
            f"ids, placement bonuses and adjacency will all be wrong — "
            f"`spaces`, `place` and the rendered map cannot be trusted.")
    return out


def new_game_state(setup: dict) -> dict:
    """Fresh game.json content from a setup.json-shaped config."""
    me = next(p for p in setup["players"] if p["isMe"])
    opponents = [p for p in setup["players"] if not p["isMe"]]
    return {
        "generation": 1,
        "firstPlayer": setup["firstPlayerGen1"],
        "globals": dict(GLOBAL_START),
        "me": {
            "name": me["name"],
            "corporation": None,
            "tr": STARTING_TR,
            "resources": _zeros(),
            "production": _zeros(),
            "hand": [],  # ordered list = recommended play order (a contract)
            "playedCards": [],
            "dealtLog": [],
            "actionsThisGen": {},
            "tiles": {"cities": 0, "greeneries": 0, "special": 0},
            "milestones": [],
        },
        "milestonesClaimed": {},
        "awardsFunded": {},
        "opponents": {
            p["name"]: {
                "corporation": None,
                "tr": STARTING_TR,
                "resources": _zeros(),
                "production": _zeros(),
                "estimated": True,      # simulated since last mat snapshot
                "lastObservedGen": None,
                "tagCounts": {},
                "tiles": {"cities": 0, "greeneries": 0, "special": 0},
                "playedCards": [],
            }
            for p in opponents
        },
    }


import json
from pathlib import Path


class Store:
    """Reads/writes state files under <root>/state/. The files are the truth."""

    def __init__(self, root: str | Path = ".", state_dir: str | Path | None = None):
        self.state_dir = Path(state_dir) if state_dir else Path(root) / "state"
        self.setup_path = self.state_dir / "setup.json"
        self.game_path = self.state_dir / "game.json"
        self.log_path = self.state_dir / "log.md"

    def init(self, setup: dict) -> dict:
        """Write setup.json + fresh game.json + log.md header. Never overwrites."""
        if self.game_path.exists():
            raise FileExistsError(
                f"{self.game_path} already exists — refusing to overwrite a live game"
            )
        validate_setup(setup)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self._write_json(self.setup_path, setup)
        game = new_game_state(setup)
        self._write_json(self.game_path, game)
        self.log_path.write_text("# Game log\n\n")
        return game

    def load_setup(self) -> dict:
        return json.loads(self.setup_path.read_text())

    def load_game(self) -> dict:
        return json.loads(self.game_path.read_text())

    def save_game(self, game: dict) -> None:
        self._write_json(self.game_path, game)

    def log(self, gen_tag: str, message: str) -> None:
        with self.log_path.open("a") as f:
            f.write(f"- {gen_tag} — {message}\n")

    @staticmethod
    def _write_json(path: Path, data: dict) -> None:
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")




PARAM_SCALE = {
    "temperature": {"min": -30, "max": 8, "step": 2, "unit": "°C"},
    "oxygen": {"min": 0, "max": 14, "step": 1, "unit": "%"},
    "oceans": {"min": 0, "max": 9, "step": 1, "unit": ""},
}


# Tile types that ARE cities on the map (score.py keeps its own copy for
# adjacency VP): the plain city plus Capital's own tile.
CITY_TILES = ("city", "capital")

# On the board but owned by nobody for scoring purposes: an ocean belongs
# to the table, and a LAND CLAIM is a reservation marker, not a tile (the
# vendor's Landlord filters it out by name for exactly this reason).
LAND_CLAIM = "landclaim"      # the tile vocabulary is alnum-squashed
NON_SCORING_TILES = ("ocean", LAND_CLAIM)

# The app modes (planlib.APP_MODES quotes the same pair): the app log/API
# names every card-resource add/remove, so a played accumulator card's
# count is KNOWN from the play onward. In physical mode an opponent's
# later accumulator actions may never be logged, so their count stays
# UNKNOWN (absent) until observed — a stale 0 is a lie at scoring time.
APP_MODES = ("app-practice", "app-online")

MILESTONES = ("Terraformer", "Mayor", "Gardener", "Builder", "Planner")
AWARDS = ("Landlord", "Banker", "Scientist", "Thermalist", "Miner")
AWARD_COSTS = (8, 14, 20)
MILESTONE_COST = 8
CARD_KEEP_COST = 3  # MC per card kept at research phase
BUY0_REFUSED = "GATE research buy-0 REFUSED: "
MAX_MILESTONES = 3
STEEL_VALUE = 2
TITANIUM_VALUE = 3


STANDARD_PROJECTS = {
    "sell_patents": 0,
    "power_plant": 11,
    "asteroid": 14,
    "aquifer": 18,
    "greenery": 23,
    "city": 25,
}


# ══════════════════════════════════════════════════════════════════════
# HAND-CODED CARD RULES — the ONLY two places in the engine where a card
# name may be a string literal (tests/test_no_card_literals.py enforces it).
# Everything else is read from cards/db.json: card-cost discounts come from
# `cardDiscount`, blue-card actions from `actionBehavior`, formula VP from
# `vpData`.  What is left here is what the vendor itself implements as a
# TypeScript hook (a card's `bespokeMethods` in the db names them), so there
# is no data to extract yet.
# ══════════════════════════════════════════════════════════════════════

# card-table: corporations
# Corporation abilities. `bespokeMethods` in the db names the vendor hook;
# the value here is the number/flag our engine needs to apply it.
CORP_RULES: dict[str, dict] = {
    # +N MC back after paying for a card / standard project whose PRINTED
    # cost is ≥ rebateMinBase (discounts do not disqualify it).
    "CrediCor": {"rebate": 4, "rebateMinBase": 20},
    "Helion": {"heatAsMC": True},
    "Interplanetary Cinematics": {"eventMC": 2},
    # "As your first action in the game, draw 3 cards" — the app prompts
    # "Take first action / Pass" in generation 1 (docs/actions.md)
    "Inventrix": {"widensRequirements": True, "firstActionPrompt": True},
    "Mining Guild": {"oreTileSteelProduction": 1},
    "Saturn Systems": {"jovianTagMCProduction": 1},
    "Tharsis Republic": {"marsCityMCProduction": 1, "ownCityMC": 3,
                         "firstActionPrompt": True, "freeFirstCity": True},
    # the card-tag part of ThorGate is db data (cardDiscount); only the
    # standard-project half is a vendor hook (getStandardProjectDiscount)
    "ThorGate": {"standardDiscount": {"power_plant": 3}},
    "United Nations Mars Initiative": {"trBoostCost": 3, "trBoostStep": 1},
}
# card-table: end

# card-table: triggers
# Persistent card effects the vendor implements as onTilePlaced /
# onCardPlayed / getCardDiscount hooks — there is no declarative behavior
# in the db to read, so they are modelled here by name.
# "when a city tile is placed" (any player's city, reserved-area cities
# included — the app fired both on Ganymede Colony).
CITY_TRIGGERS: dict[str, dict] = {
    "Immigrant City": {"production": {"mc": 1}},
    "Rover Construction": {"stock": {"mc": 2}},
}
# "when anyone places an ocean tile" — the app fires them on a World
# Government ocean too (verified in an app log: Arctic Algae +2 plants
# after every WGT ocean).
OCEAN_TRIGGERS: dict[str, dict] = {
    "Arctic Algae": {"stock": {"plants": 2}},
}
# "The next card you play this generation costs N less"
NEXT_CARD_DISCOUNT: dict[str, int] = {"Indentured Workers": 8}
# "When you play a science tag, add a science resource here, or remove one
# to draw a card" — the player's choice each time (play(olympus=…)).
OLYMPUS_CONFERENCE = "Olympus Conference"
# played cards that widen global requirements by ±2 steps (menu.py)
REQUIREMENT_WIDENERS = ("Adaptation Technology",)
# card-table: end


_CORP_RULES_LC = {k.lower(): v for k, v in CORP_RULES.items()}


def corp_rule(corp: str | None, key: str, default=None):
    """One corporation ability by name (case-insensitive; unknown → default)."""
    return _CORP_RULES_LC.get(str(corp or "").lower(), {}).get(key, default)


def split_payment(game: dict, player: str, price: int, *,
                  steel: int | None = None, titanium: int | None = None,
                  heat: int | None = None, tags=None, card=None,
                  pool: dict | None = None) -> dict:
    """THE payment splitter — every caller asks this and nothing else.

    Returns {"mc", "steel", "titanium", "heat", "shortfall"} for `price`
    (the DISCOUNTED price; discounts are card_price's job):

      * MC first, the remainder out of heat — and heat only for a
        corporation whose `corp_rule` says it spends heat as money (a
        capability, never a name).
      * steel pays only for a building tag, titanium only for a space tag.
        Give `tags` (or `card`) to let the splitter choose the ore mix;
        pass an explicit amount and it is used untouched — the tag rule is
        the ENGINE's to enforce (`play` raises), not the arithmetic's.
      * ores first when the splitter chooses them, steel before titanium so
        titanium stays for the space cards only it can pay for; one extra
        ore unit rather than not playing at all, which is what the app's
        payment dialog offers and what a table does.
      * `shortfall` = what the pools cannot cover (0 = affordable). It is
        reported, never hidden: the executor sends an MC-only payment and
        lets the app refuse, the menu drops the item, the engine raises.

    Deterministic: same state, same price, same split, every time.

    Before this there were four of these (menu tried steel first, the
    replayer titanium first and had NO heat term, the executor owned the
    MC→heat split, the engine did its own arithmetic) — and they already
    disagreed, which is how a Helion replay drifted 105 MC.
    """
    price = max(0, int(price))
    if pool is None:
        pool = player_pool(game, player)
    res = pool.get("resources") or {}

    def have(r: str) -> int:
        try:
            return max(0, int(res.get(r) or 0))
        except (TypeError, ValueError):
            return 0

    if tags is None and card is not None:
        info = card if isinstance(card, dict) else card_info(str(card))
        tags = (info or {}).get("tags")
    tags = [str(t).lower() for t in (tags or [])]
    heat_ok = bool(corp_rule(pool.get("corporation"), "heatAsMC"))

    pick_steel = steel is None and "building" in tags
    pick_ti = titanium is None and "space" in tags
    # Per-player metal rates. A tableau card can raise them (Advanced
    # Alloys: "each steel/titanium you have is worth 1 M€ extra"), and the
    # app publishes the result per player as steelValue / titaniumValue.
    # Absent those keys this is exactly the module constants, so nothing
    # that does not supply them changes behaviour. Never a card branch.
    sv = int(pool.get("steelValue") or STEEL_VALUE)
    tv = int(pool.get("titaniumValue") or TITANIUM_VALUE)
    steel = 0 if steel is None else max(0, int(steel))
    titanium = 0 if titanium is None else max(0, int(titanium))
    need = max(0, price - steel * sv - titanium * tv)
    if pick_steel:
        steel = min(have("steel"), need // sv)
        need -= steel * sv
    if pick_ti:
        titanium = min(have("titanium"), need // tv)
        need -= titanium * tv
    cash = have("mc") + (have("heat") if heat_ok and heat is None
                         else max(0, int(heat or 0)))
    if need > cash:                 # over-pay with one more ore, not fold
        if pick_steel and have("steel") > steel:
            steel += 1
            need = max(0, need - sv)
        elif pick_ti and have("titanium") > titanium:
            titanium += 1
            need = max(0, need - tv)
    if heat is None:
        heat = min(have("heat"), max(0, need - have("mc"))) if heat_ok else 0
    else:
        heat = max(0, int(heat))
    mc = max(0, need - heat)
    return {"mc": mc, "steel": steel, "titanium": titanium, "heat": heat,
            "shortfall": max(0, mc - have("mc"))}


def requirement_widened(pool: dict) -> bool:
    """Does this player read every GLOBAL requirement ±2 steps?

    Two sources, both already declared above: the corporation ability
    (`widensRequirements`) and a played card in REQUIREMENT_WIDENERS. Only
    the corp half was ever consulted at play time, so a player holding the
    CARD had legal plays refused by the engine — the P8 app log has four of
    them ("Wave Power … min 3 oceans, now 1" while the widener was in the
    tableau, and the app allowed every one).
    """
    if corp_rule(pool.get("corporation"), "widensRequirements"):
        return True
    played = {(c.get("name") or "").lower()
              for c in (pool.get("playedCards") or [])}
    return any(w.lower() in played for w in REQUIREMENT_WIDENERS)


def requirement_gap_steps(req: str | None, globals_: dict) -> int | None:
    """How many parameter steps short of (or past) a requirement we are.

    0 = the window is open; N > 0 = it needs N more raises, or it expired N
    raises ago; None = not a global-parameter requirement (tags, cities …),
    which the ±2 window does not cover.
    """
    if not req:
        return 0
    import research as _research
    info = _research._window_info(req, globals_)
    status = info.get("status")
    if status in ("none", "open", "closing"):
        return 0
    if status == "closed":
        return int(info.get("steps") or 0)
    if status == "expired":
        m = _research._REQ.match(req.strip())
        param = info.get("param")
        if not m or not param:
            return None
        val, step = int(m.group(2)), PARAM_SCALE[param]["step"]
        return -(-(globals_[param] - val) // step)
    return None


def card_info(name: str) -> dict | None:
    """cards/db.json lookup that never raises (module-level: the pure price
    model needs the db without an Engine)."""
    if not name:
        return None
    try:
        import cards as _cards
        return _cards.find(name)
    except Exception:
        return None


def tags_of_cards(names, db: dict | None = None, resolve=None,
                  include_events: bool = False) -> dict:
    """{tag: count} over a list of card names.

    EVENT cards are skipped: their tags do not persist once played (the
    rule strategy/04 keeps quoting). `resolve` lets a caller supply its own
    name lookup (research.py resolves typed/OCR'd names fuzzily) without
    forking the counting rule.
    """
    look = resolve or (lambda n: card_info(n) if db is None
                       else _cards_find(n, db))
    counts: dict[str, int] = {}
    for name in names or []:
        info = look(str(name))
        if not info or (not include_events and info.get("type") == "event"):
            continue
        for t in info.get("tags") or []:
            counts[t] = counts.get(t, 0) + 1
    return counts


def _cards_find(name: str, db: dict | None):
    try:
        import cards as _cards
        return _cards.find(name, db)
    except Exception:
        return None


def persisting_tags(game: dict, name: str, db: dict | None = None,
                    extra_info: dict | None = None,
                    pool: dict | None = None) -> dict:
    """THE tag counter — {tag: count} of a player's PERSISTING tags.

    Played cards (events excluded — their tags leave play with them) PLUS
    the CORPORATION's own tags, which every consumer must count: Mining
    Guild is two building tags towards Builder, Inventrix a science tag
    towards Scientist. `score.py` forgot them and `menu.py` did not, so the
    same award had two answers at the same table.

    An opponent whose tableau is not tracked (a physical table: no app, no
    photo yet) falls back to the event-driven `tagCounts` counter.
    `extra_info` is the card being played right now, not yet in
    playedCards ("including this" wording).
    """
    pool = player_pool(game, name) if pool is None else pool
    played = pool.get("playedCards") or []
    counts = tags_of_cards([e.get("name", "") for e in played], db)
    if not played:
        for t, n in (pool.get("tagCounts") or {}).items():
            if isinstance(n, int) and n > 0:
                counts[t] = counts.get(t, 0) + n
    corp = _cards_find(pool.get("corporation") or "", db)
    for t in (corp or {}).get("tags") or []:
        counts[t] = counts.get(t, 0) + 1
    if extra_info and extra_info.get("type") != "event":
        for t in extra_info.get("tags") or []:
            counts[t] = counts.get(t, 0) + 1
    return counts


def tile_counts(game: dict, name: str, pool: dict | None = None) -> dict:
    """THE tile counter — a player's tiles from `game["board"]`, the record
    of what is physically on the map (AGENTS.md: never the derived cache),
    with the per-player counter as a FLOOR because a mat photo carries no
    hexes and undercounting a tile that is on the table is the worse error.

    Keys: citiesOnMars · citiesOffMars · cities (both) · greeneries ·
    special · landlord.

    Oceans belong to nobody and never score. Reserved-area cities (Ganymede
    Colony, Phobos Space Haven) have no hex at all: they live only in the
    counter, and `cities` already includes them — which is why summing the
    raw `tiles` dict counted them TWICE for Landlord.
    """
    pool = player_pool(game, name) if pool is None else pool
    cache = pool.get("tiles") or {}
    spaces = None
    on_board = {"cities": 0, "greeneries": 0, "special": 0}
    for sid, occ in (game.get("board") or {}).items():
        if occ.get("player") != name:
            continue
        tile = occ.get("tile")
        if tile in NON_SCORING_TILES:
            continue
        if tile in CITY_TILES:
            if spaces is None:
                spaces = Engine._board()
            if (spaces.get(str(sid)) or {}).get("offMap"):
                continue          # a reserved-area slot, counted below
            on_board["cities"] += 1
        elif tile == "greenery":
            on_board["greeneries"] += 1
        else:
            on_board["special"] += 1

    def cached(key: str) -> int:
        try:
            return max(0, int(cache.get(key, 0) or 0))
        except (TypeError, ValueError):
            return 0

    off_mars = cached("citiesOffMars")
    on_mars = max(on_board["cities"], cached("cities") - off_mars)
    greeneries = max(on_board["greeneries"], cached("greeneries"))
    special = max(on_board["special"], cached("special"))
    return {"citiesOnMars": on_mars, "citiesOffMars": off_mars,
            "cities": on_mars + off_mars, "greeneries": greeneries,
            "special": special,
            "landlord": on_mars + off_mars + greeneries + special}


def cities_in_play(game: dict) -> int:
    """Every city tile in play, reserved-area ones included (Greenhouses,
    'per 3 cities' VP) — THE tile counter, summed over every player."""
    return sum(tile_counts(game, name, pool)["cities"]
               for name, pool in all_pools(game))


def cities_on_mars(game: dict) -> int:
    """City tiles ON MARS only (Zeppelins, Martian Rails): reserved-area
    cities never count, and a city on the board whose owner is not tracked
    still does."""
    total = sum(tile_counts(game, name, pool)["citiesOnMars"]
                for name, pool in all_pools(game))
    known = {name for name, _ in all_pools(game)}
    spaces = None
    for sid, occ in (game.get("board") or {}).items():
        if occ.get("tile") not in CITY_TILES or occ.get("player") in known:
            continue
        if spaces is None:
            spaces = Engine._board()
        if not (spaces.get(str(sid)) or {}).get("offMap"):
            total += 1
    return total


def award_metric(game: dict, name: str, award: str,
                 db: dict | None = None) -> int | None:
    """One award's metric for one player — asked here by score.py, menu.py
    and (through menu) races.py, so the ranking, the AVAILABLE ACTIONS
    entry and the race table can never disagree."""
    pool = player_pool(game, name)
    res = {**_zeros(), **(pool.get("resources") or {})}
    prod = {**_zeros(), **(pool.get("production") or {})}
    if award == "Landlord":
        return tile_counts(game, name, pool)["landlord"]
    if award == "Banker":
        return prod["mc"]
    if award == "Scientist":
        return persisting_tags(game, name, db, pool=pool).get("science", 0)
    if award == "Thermalist":
        return res["heat"]
    if award == "Miner":
        return res["steel"] + res["titanium"]
    return None


def award_metrics(game: dict, name: str, db: dict | None = None) -> dict:
    return {a: award_metric(game, name, a, db) for a in AWARDS}


def card_discount_spec(name: str) -> tuple[str, dict] | None:
    """(canonical name, cardDiscount) of a tableau card / corporation that
    lowers card prices — vendor data, not a table of ours."""
    info = card_info(name)
    spec = (info or {}).get("cardDiscount")
    if not isinstance(spec, dict) or not isinstance(spec.get("amount"), int):
        return None
    return info["name"], spec


def greenery_plant_cost(corp: str | None) -> int:
    """Plants a greenery conversion costs this player: 8, or the db's
    `greeneryDiscount` off it (Ecoline's printed 7)."""
    beh = (card_info(corp or "") or {}).get("behavior") or {}
    off = beh.get("greeneryDiscount")
    return 8 - off if isinstance(off, int) else 8


def _discount_sources_of(pool: dict) -> list[str]:
    """Corp + every tableau card of a player = the names that may carry a
    `cardDiscount` in the db."""
    sources = [pool["corporation"]] if pool.get("corporation") else []
    sources += [c["name"] for c in pool.get("playedCards") or []]
    return sources


def _rebate_amount(corp: str | None, base_cost: int) -> int:
    amount = corp_rule(corp, "rebate")
    if amount and base_cost >= corp_rule(corp, "rebateMinBase", 0):
        return amount
    return 0


def standard_project_rebates(pool: dict, project: str) -> list[tuple[str, int]]:
    """[(card, MC)] for every TABLEAU card of this player whose db behavior
    carries `standardProjectRebate` = {"amount": N, "except": [project…]}
    and does not except `project` — the vendor's onStandardProject hook as
    data (the corporation's own rebate is CORP_RULES, not here). The refund
    arrives AFTER the project is paid: it never makes a project affordable."""
    out: list[tuple[str, int]] = []
    for entry in pool.get("playedCards") or []:
        beh = (card_info(entry.get("name") or "") or {}).get("behavior") or {}
        spec = beh.get("standardProjectRebate")
        if not isinstance(spec, dict):
            continue
        amount = spec.get("amount")
        if not isinstance(amount, int) or amount <= 0:
            continue
        if project in (spec.get("except") or []):
            continue
        out.append((entry["name"], amount))
    return out


def _quote(base: int, discount: int, notes: list[str], rebate: int,
           next_card: bool, rebate_notes: list[str] | None = None) -> dict:
    return {"base": base, "discount": discount, "notes": notes,
            "price": max(0, base - discount), "rebate": rebate,
            "rebateNotes": rebate_notes or [], "next_card": next_card}


def card_price(game: dict, player: str, card_info: dict) -> dict:
    """THE price model for a card, pure over the game dict (no state
    mutation, no store). `player` = canonical name. Returns
    {base, discount, notes, price, rebate, rebateNotes, next_card}: `price`
    is the MC the play charges before ores/heat cover part of it, `rebate`
    the MC that comes back after paying (corp rule and/or any tableau card
    carrying `standardProjectRebate`, which stack), `rebateNotes` naming
    each source, `next_card` whether a pending
    next-card discount (Indentured Workers) is part of the quote (the play
    consumes it). Engine.play() charges exactly this; menu.py quotes
    exactly this."""
    pool = player_pool(game, player)
    tags = set(card_info.get("tags") or [])
    base = int(card_info.get("cost") or 0)
    total, notes = 0, []
    for src in _discount_sources_of(pool):
        hit = card_discount_spec(src)
        if not hit:
            continue
        canon, spec = hit
        if spec.get("tag") and spec["tag"] not in tags:
            continue
        total += spec["amount"]
        notes.append(f"{canon} −{spec['amount']}")
    next_card = False
    nxt = pool.get("nextCardDiscount")
    if nxt and nxt.get("gen") == game.get("generation"):
        total += nxt["amount"]
        notes.append(f"{nxt['source']} −{nxt['amount']}")
        next_card = True
    return _quote(base, total, notes,
                  _rebate_amount(pool.get("corporation"), base), next_card)


def standard_project_price(game: dict, player: str, project: str) -> dict:
    """THE price model for a standard project (same shape as
    card_price; next_card is always False). Engine.standard() charges
    exactly this; menu.py quotes exactly this. `rebate` is the SUM of every
    source that pays back after the project is paid — the corporation rule
    and every tableau card carrying `standardProjectRebate` — and
    `rebateNotes` names each one."""
    if project not in STANDARD_PROJECTS:
        raise EventError(
            f"Unknown standard project {project!r}: {list(STANDARD_PROJECTS)}")
    pool = player_pool(game, player)
    base = STANDARD_PROJECTS[project]
    total, notes = 0, []
    for src in _discount_sources_of(pool):
        off = (corp_rule(src, "standardDiscount") or {}).get(project, 0)
        if off:
            total += off
            notes.append(f"{(card_info(src) or {}).get('name', src)} −{off}")
    corp = pool.get("corporation")
    rebate = _rebate_amount(corp, base)
    rebate_notes = [f"{corp} +{rebate}"] if rebate else []
    for card, amount in standard_project_rebates(pool, project):
        rebate += amount
        rebate_notes.append(f"{card} +{amount}")
    return _quote(base, total, notes, rebate, False, rebate_notes)


# Resource names the vendor's Behavior vocabulary uses in `spend` blocks,
# mapped to our pool keys. `resourcesHere` (resources ON the acting card)
# is handled separately.
SPEND_RESOURCES = {"megacredits": "mc", "mc": "mc", "steel": "steel",
                   "titanium": "titanium", "plants": "plants",
                   "energy": "energy", "heat": "heat"}


def research_log_line(cards, kept, charged: int, balance: int,
                      drafted: bool = False, suffix: str = "") -> str:
    """THE research log line — one composer, two callers (`Engine.dealt`
    on the apply.py lane, `execute.py pick` on the API lane). shape.py
    parses my per-generation buys out of it, so the shape is frozen:
    changing it silently blinds the buy-0 gate (fix-plan item 4a, where
    the API lane never wrote the line at all)."""
    cards, kept = list(cards), list(kept)
    if drafted:
        body = (f"Research: drafted {','.join(cards)} → kept "
                f"{','.join(kept)} (−{charged} MC → {balance})")
    else:
        body = (f"Research: dealt {cards}, kept {kept} "
                f"(−{charged} MC → {balance})")
    return body + suffix


def buy0_override_tag(reason: str) -> str:
    """The logged tag for a buy-0 gate the caller overrode (both lanes)."""
    return f" — buy-0 gate OVERRIDDEN: {reason.strip()}"


class Engine:
    """Applies validated events to game state. One method = one event type."""

    """Applies validated events to game state. One method = one event type."""

    def __init__(self, store: Store):
        self.store = store
        self.setup = store.load_setup()
        self._card_db = None

    def card(self, name: str) -> dict | None:
        """Exact db.json lookup (case-insensitive); None if unknown."""
        if self._card_db is None:
            import cards as _cards
            try:
                self._card_db = _cards.load_db()
            except FileNotFoundError:
                self._card_db = {"cards": []}
        import cards as _cards
        return _cards.find(name, self._card_db)

    # ── helpers ──────────────────────────────────────────────

    def resolve_player(self, ref: str) -> str:
        """Name / alias / color → canonical player name (case-insensitive)."""
        want = ref.strip().lower()
        for p in self.setup["players"]:
            candidates = [p["name"], p["color"], *p.get("aliases", [])]
            if want in (c.lower() for c in candidates):
                return p["name"]
        raise EventError(f"Unknown player reference: {ref!r}")

    def _is_me(self, name: str) -> bool:
        return next(p for p in self.setup["players"] if p["name"] == name)["isMe"]

    def _commit(self, game: dict, message: str) -> str:
        self.store.save_game(game)
        self.store.log(f"G{game['generation']}", message)
        return message

    # ── events ───────────────────────────────────────────────

    def res(self, player: str, resource: str, delta: int) -> str:
        name = self.resolve_player(player)
        game = self.store.load_game()
        if self._is_me(name):
            if resource not in RESOURCES:
                raise EventError(f"Unknown resource: {resource!r}")
            pool = game["me"]["resources"]
            new = pool[resource] + delta
            if new < 0:
                raise EventError(f"{name} {resource} would go negative ({new})")
            pool[resource] = new
        else:
            if resource not in RESOURCES:
                raise EventError(f"Unknown resource: {resource!r}")
            pool = game["opponents"][name]["resources"]
            new = pool[resource] + delta
            if new < 0:
                raise EventError(f"{name} {resource} estimate would go negative ({new})")
            pool[resource] = new
        sign = "+" if delta >= 0 else ""
        return self._commit(game, f"{name}: {sign}{delta} {resource.upper()} → {new}")

    def prod(self, player: str, resource: str, delta: int) -> str:
        name = self.resolve_player(player)
        game = self.store.load_game()
        floor = -5 if resource == "mc" else 0
        if resource not in RESOURCES:
            raise EventError(f"Unknown resource: {resource!r}")
        if self._is_me(name):
            pool = game["me"]["production"]
        else:
            pool = game["opponents"][name]["production"]
        new = pool[resource] + delta
        if new < floor:
            raise EventError(
                f"{name} {resource} production would drop below {floor} ({new})"
            )
        pool[resource] = new
        sign = "+" if delta >= 0 else ""
        return self._commit(
            game, f"{name}: {sign}{delta} {resource.upper()} production → {new}"
        )


# Global parameter scales

    def _corp_of(self, game: dict, name: str) -> str | None:
        pool = game["me"] if self._is_me(name) else game["opponents"][name]
        return pool.get("corporation")

    def _corp_holders(self, game: dict, rule: str) -> list[tuple[str, int]]:
        """[(player, rule value)] for every player whose corporation carries
        this CORP_RULES ability — never a corp name in the calling code."""
        return [(n, corp_rule(p.get("corporation"), rule))
                for n, p in self._all_pools(game)
                if corp_rule(p.get("corporation"), rule)]

    def _my_corp_rule(self, game: dict, name: str, rule: str, default=None):
        return corp_rule(self._corp_of(game, name), rule, default)

    def _all_pools(self, game: dict) -> list[tuple[str, dict]]:
        """[(player name, state pool)] for me + every opponent."""
        return all_pools(game)

    def _fire_triggers(self, game: dict, table: dict, parts: list,
                       why: str) -> None:
        """Apply a name-keyed trigger table (CITY_TRIGGERS/OCEAN_TRIGGERS)
        for every player holding one of its cards in their tableau."""
        for holder, pool in self._all_pools(game):
            for entry in pool.get("playedCards", []):
                spec = table.get(entry["name"])
                if not spec:
                    continue
                for r, d in (spec.get("production") or {}).items():
                    pool["production"][r] += d
                    parts.append(f"{entry['name']} ({holder}): {d:+} "
                                 f"{r.upper()} production → "
                                 f"{pool['production'][r]} ({why})")
                for r, d in (spec.get("stock") or {}).items():
                    pool["resources"][r] += d
                    parts.append(f"{entry['name']} ({holder}): {d:+} "
                                 f"{r.upper()} → {pool['resources'][r]} ({why})")

    def _on_city_placed(self, game: dict, owner: str, parts: list,
                        on_mars: bool = True) -> None:
        """Tharsis Republic: +1 MC prod to every Tharsis player when any city
        lands ON MARS; +3 MC to the owner if the city is their own. Then the
        CITY_TRIGGERS cards (Immigrant City, Rover Construction) for ANY
        city, reserved-area ones included (verified in an app log)."""
        if on_mars:
            for holder, n in self._corp_holders(game, "marsCityMCProduction"):
                pool = self._tr_pool(game, holder)
                corp = pool.get("corporation")
                pool["production"]["mc"] += n
                parts.append(f"{corp} ({holder}): +{n} MC production")
                own = corp_rule(corp, "ownCityMC", 0)
                if holder == owner and own:
                    pool["resources"]["mc"] += own
                    parts.append(f"{corp} ({holder}): +{own} MC (own city)")
        self._fire_triggers(game, CITY_TRIGGERS, parts, "city placed")

    def _on_ocean_placed(self, game: dict) -> list[str]:
        """OCEAN_TRIGGERS (Arctic Algae +2 plants) for every holder —
        fired by card/standard/action oceans AND World Government oceans
        (the app does; verified in its log)."""
        parts: list[str] = []
        self._fire_triggers(game, OCEAN_TRIGGERS, parts, "ocean placed")
        return parts

    # ── discounts & rebates — ONE price model. The public API
    # (price / standard_price) is pure over the game dict; play() and
    # standard() charge through the same functions the menu quotes from.

    price = staticmethod(card_price)
    standard_price = staticmethod(standard_project_price)

    def _discount_sources(self, game: dict, name: str) -> tuple[dict, list[str]]:
        pool = game["me"] if self._is_me(name) else game["opponents"][name]
        return pool, _discount_sources_of(pool)

    def _card_discount(self, game: dict, name: str,
                       info: dict) -> tuple[int, list[str], bool]:
        """Total MC off a card's printed cost for this player right now:
        corp + tableau `cardDiscount` entries matching the card's tags, plus
        a pending next-card discount. Returns (total, notes,
        next_card_discount_consumed) — from card_price()."""
        q = card_price(game, name, info)
        return q["discount"], q["notes"], q["next_card"]

    def _standard_discount(self, game: dict, name: str,
                           project: str) -> tuple[int, list[str]]:
        q = standard_project_price(game, name, project)
        return q["discount"], q["notes"]

    def _credicor_rebate(self, game: dict, name: str, base_cost: int,
                         parts: list) -> None:
        """CrediCor: +4 MC after paying for a card or standard project whose
        BASE (printed) cost is ≥ 20 — discounts do not disqualify it, and
        it applies to any player with the corp (not only me)."""
        corp = self._corp_of(game, name)
        rebate = _rebate_amount(corp, base_cost)
        if rebate:
            pool = self._tr_pool(game, name)
            pool["resources"]["mc"] += rebate
            parts.append(f"{corp}: +{rebate} MC rebate (base cost "
                         f"{base_cost} ≥ {corp_rule(corp, 'rebateMinBase')})")

    def _card_rebates(self, game: dict, name: str, project: str,
                      parts: list) -> None:
        """Every tableau card of this player whose db behavior carries
        `standardProjectRebate` and does not except `project` pays its
        amount back — data-driven (standard_project_rebates), any card, any
        player. Called after the project is paid, never before."""
        pool = self._tr_pool(game, name)
        for card, amount in standard_project_rebates(pool, project):
            pool["resources"]["mc"] += amount
            parts.append(f"{card}: +{amount} MC rebate (after paying for a "
                         f"standard project) → {pool['resources']['mc']} MC")

    def _set_next_card_discount(self, game: dict, name: str, card: str,
                                parts: list) -> None:
        amount = NEXT_CARD_DISCOUNT.get(card)
        if amount:
            pool = self._tr_pool(game, name)
            pool["nextCardDiscount"] = {"gen": game["generation"],
                                        "amount": amount, "source": card}
            parts.append(f"{card}: next card {name} plays this generation "
                         f"costs {amount} MC less")

    def free_action_city(self, player: str) -> str:
        """A corp's free first-action city placement (Tharsis Republic's
        printed setup text). No MC cost and — unlike the standard project
        City — no universal +1 MC production (that bonus is specific to
        the standard project's own printed text, not a rule every city
        placement gets). Only the tile counter and any corp trigger
        (_on_city_placed) apply. Call `place()` separately for the hex's
        own hex-bonus/hex-position bookkeeping, same as any other tile.
        """
        name = self.resolve_player(player)
        game = self.store.load_game()
        pool = game["me"] if self._is_me(name) else game["opponents"][name]
        pool["tiles"]["cities"] += 1
        parts = [f"{name}: free first-action city tile"]
        self._on_city_placed(game, name, parts)
        return self._commit(game, ", ".join(parts))

    def _tr_pool(self, game: dict, name: str) -> dict:
        return game["me"] if self._is_me(name) else game["opponents"][name]

    def tr(self, player: str, delta: int) -> str:
        name = self.resolve_player(player)
        game = self.store.load_game()
        pool = self._tr_pool(game, name)
        pool["tr"] += delta
        sign = "+" if delta >= 0 else ""
        return self._commit(game, f"{name}: TR {sign}{delta} → {pool['tr']}")

    # Global-track thresholds, from the vendor's own constants.ts
    # (TEMPERATURE_BONUS_FOR_HEAT_1/2, TEMPERATURE_FOR_OCEAN_BONUS,
    # OXYGEN_LEVEL_FOR_TEMPERATURE_BONUS) — Game.increaseTemperature and
    # Game.increaseOxygenLevel grant them to the player who raised the
    # parameter:
    #   temperature reaching −24 / −20 → that player +1 heat production
    #   temperature reaching 0 °C      → that player places a bonus ocean
    #   oxygen reaching 8 %            → a FREE temperature step for them
    #                                    (with its own TR, and whatever the
    #                                    temperature track then pays out)
    # The venus track's own 8/16 bonuses are deliberately absent: the venus
    # parameter is not in PARAM_SCALE, so the engine does not track it yet.
    TEMP_HEAT_BONUS = (-24, -20)
    TEMP_OCEAN_BONUS = 0
    OXYGEN_TEMP_BONUS = 8

    def _bump_param(self, game: dict, param: str,
                    actor: str | None = None) -> tuple[bool, str]:
        """Raise one step if below cap. Returns (raised, describe-string).
        actor (resolved name) collects any track-threshold bonus."""
        scale = PARAM_SCALE[param]
        cur = game["globals"][param]
        if cur >= scale["max"]:
            return False, f"{param} already maxed at {cur}{scale['unit']}"
        new = cur + scale["step"]
        game["globals"][param] = new
        desc = f"{param} {cur}{scale['unit']} → {new}{scale['unit']}"
        if param == "temperature":
            if new in self.TEMP_HEAT_BONUS:
                if actor is None:
                    desc += (" — → TABLE: temp-track bonus +1 heat prod "
                             "(log prod event for whoever raised it)")
                else:
                    pool = (game["me"] if self._is_me(actor)
                            else game["opponents"][actor])
                    pool["production"]["heat"] += 1
                    desc += (f" — track bonus: {actor} +1 heat prod "
                             f"(→ {pool['production']['heat']})")
            if new == self.TEMP_OCEAN_BONUS:
                desc += (" — BONUS OCEAN from the temperature track: "
                         f"{actor or 'the raiser'} places an ocean now "
                         "(log place + raise oceans events)")
        if param == "oxygen" and new == self.OXYGEN_TEMP_BONUS:
            # 8 % O2 grants a free temperature step to the same player.
            # That step is a normal raise: it pays its own TR and can chain
            # the −24/−20 heat bonus or the 0 °C ocean, so it recurses
            # through this very function.
            bonus_raised, bonus_desc = self._bump_param(
                game, "temperature", actor=actor)
            note = f"8% O2 track bonus: free temperature step, {bonus_desc}"
            if bonus_raised and actor is not None:
                # the delta, not a running total: the caller adds the TR for
                # the oxygen raise ITSELF after this returns, so a
                # before → after here would be a number the player never sees
                self._tr_pool(game, actor)["tr"] += 1
                note += f", {actor} +1 TR"
            elif bonus_raised:
                note += (" — → TABLE: +1 TR for whoever raised the oxygen "
                         "(log a tr event)")
            desc += f" — {note}"
        if param == "oceans":
            for note in self._on_ocean_placed(game):
                desc += f" — {note}"
        return True, desc

    def raise_param(self, param: str, by: str) -> str:
        """Player raises a global parameter one step and gains 1 TR."""
        if param not in PARAM_SCALE:
            raise EventError(f"Unknown global parameter: {param!r}")
        name = self.resolve_player(by)
        game = self.store.load_game()
        raised, desc = self._bump_param(game, param, actor=name)
        if not raised:
            raise EventError(desc)
        pool = self._tr_pool(game, name)
        pool["tr"] += 1
        return self._commit(game, f"{name}: {desc}, TR → {pool['tr']}")

    def sync_global(self, param: str, value: int, force: bool = False) -> str:
        """Photo/text sync: adopt observed value. Parameters only move up
        unless force=True (correction of a phantom raise)."""
        if param not in PARAM_SCALE:
            raise EventError(f"Unknown global parameter: {param!r}")
        scale = PARAM_SCALE[param]
        game = self.store.load_game()
        cur = game["globals"][param]
        if value < cur and not force:
            raise EventError(
                f"{param} can only move up (currently {cur}, observed {value} — "
                "check the reading)"
            )
        if not (scale["min"] <= value <= scale["max"]) or (
            (value - scale["min"]) % scale["step"] != 0
        ):
            raise EventError(f"{param}={value} is not on the scale")
        game["globals"][param] = value
        return self._commit(game, f"Sync: {param} = {value}{scale['unit']}")

    def convert(self, player: str, kind: str) -> str:
        """8 heat → temperature step, or 8 plants → greenery (+O2). TR if raised.

        The log line is the RECEIPT of the conversion: it ends with the
        standard action's name as the app prints it ("Convert Heat standard
        action"), so the listener's own-line scan (an own head whose effect
        the log already records since the last drain) matches the app's
        echo of a conversion the executor sent, and absorbs it instead of
        spending 8 heat again (D3 / H1b). The prefix "<player>: spent N
        heat, temperature" / "spent N plants → greenery" is what the
        event-log replay inverts — unchanged.
        """
        name = self.resolve_player(player)
        game = self.store.load_game()
        me = self._is_me(name)
        pool = game["me"]["resources"] if me else game["opponents"][name]["resources"]
        if kind == "heat":
            if pool["heat"] < 8:
                if me:
                    raise EventError(f"Need 8 heat, have {pool['heat']}")
                # Opponent stocks are ESTIMATES — a real
                # conversion the app accepted must not be refused over a
                # 1-2 unit tracking gap (same policy as play()'s payment
                # floor). Clamp to 0 and flag the estimate gap.
                parts_extra = (f" (estimate was {pool['heat']}, short of 8 "
                               "— clamped, estimate gap absorbed)")
                pool["heat"] = 0
            else:
                pool["heat"] -= 8
                parts_extra = ""
            if game["globals"]["temperature"] >= PARAM_SCALE["temperature"]["max"]:
                raise EventError(
                    "Temperature is maxed — heat conversion gains nothing; "
                    "keep the heat (Helion can spend it as MC)")
            raised, desc = self._bump_param(game, "temperature", actor=name)
            parts = [f"{name}: spent 8 heat{parts_extra}", desc]
        elif kind == "plants":
            need = greenery_plant_cost(self._corp_of(game, name))
            have = pool["plants"]
            if have < need:
                if me:
                    raise EventError(f"Need {need} plants, have {have}")
                pool["plants"] = 0     # estimate gap absorbed (see heat)
            else:
                pool["plants"] -= need
            tiles = (game["me"] if me else game["opponents"][name])["tiles"]
            tiles["greeneries"] += 1
            raised, desc = self._bump_param(game, "oxygen", actor=name)
            parts = [f"{name}: spent {need} plants → greenery", desc]
        else:
            raise EventError(f"Unknown conversion: {kind!r}")
        if raised:
            pool = self._tr_pool(game, name)
            pool["tr"] += 1
            parts.append(f"TR → {pool['tr']}")
        receipt = {"heat": "Convert Heat", "plants": "Convert Plants"}[kind]
        return self._commit(game, ", ".join(parts) + f" ({receipt} standard action)")

    # ── hand management (ordered list = play-order contract) ─

    def hand_add(self, cards: list[str]) -> str:
        game = self.store.load_game()
        game["me"]["hand"].extend(cards)
        return self._commit(game, f"Hand +{cards} → {game['me']['hand']}")

    def hand_remove(self, card: str) -> str:
        game = self.store.load_game()
        try:
            game["me"]["hand"].remove(card)
        except ValueError:
            raise EventError(f"{card!r} is not in hand: {game['me']['hand']}")
        return self._commit(game, f"Hand −{card!r} → {game['me']['hand']}")

    def hand_reorder(self, new_order: list[str]) -> str:
        game = self.store.load_game()
        if sorted(new_order) != sorted(game["me"]["hand"]):
            raise EventError(
                f"Reorder must contain exactly the current hand "
                f"{game['me']['hand']}, got {new_order}"
            )
        game["me"]["hand"] = list(new_order)
        return self._commit(game, f"Hand reordered → {new_order}")

    # ── playing cards ────────────────────────────────────────

    def _persistent_tag_count(self, game: dict, name: str, tag: str,
                              extra_info: dict | None = None) -> int:
        """One player's persisting tags of `tag` — THE tag counter
        (`persisting_tags`), so a card's per-tag amount, a requirement, a
        milestone and an award all count the same thing."""
        pool = game["me"] if self._is_me(name) else game["opponents"][name]
        return persisting_tags(game, name, extra_info=extra_info,
                               pool=pool).get(tag, 0)

    def _events_played_all(self, game: dict) -> int:
        n = 0
        for pool in [game["me"]] + list(game["opponents"].values()):
            for entry in pool.get("playedCards", []):
                info = self.card(entry["name"])
                if info and info.get("type") == "event":
                    n += 1
        return n

    def _cities_in_play(self, game: dict) -> int:
        """Every city tile incl. reserved-area ones (Greenhouses counts
        Ganymede Colony + Phobos Space Haven cities too) — THE tile
        counter."""
        return cities_in_play(game)

    def _cities_on_mars(self, game: dict) -> int:
        """City tiles ON MARS only — Zeppelins, Martian Rails.

        THE tile counter (`cities_on_mars`): the board is the record of
        what is physically on the map (AGENTS.md), the per-player counter
        is a FLOOR because an opponent's mat photo carries no hexes, and
        reserved-area cities (Ganymede Colony, Phobos Space Haven) never
        count. verify.py's board_drift reports the divergence; --sync
        repairs it."""
        return cities_on_mars(game)

    def _resolve_dynamic(self, game: dict, name: str, spec: dict,
                         card_info: dict | None) -> tuple[int, str] | None:
        """Resolve a dynamic per-tag/per-count amount spec to (n, why).
        Formerly these printed '→ TABLE' and were hand-applied (Satellites,
        Toll Station, Worms, Media Archives, Greenhouses) — every one a
        drift source. Returns None if the shape is unknown."""
        if not isinstance(spec, dict):
            return None
        if "tag" in spec:
            tag, per = spec["tag"], spec.get("per", 1)
            if spec.get("others"):
                # 'others' = every player except the actor
                total = sum(self._persistent_tag_count(game, o, tag)
                            for o in game["opponents"] if o != name)
                if not self._is_me(name):
                    me_name = next(p["name"] for p in self.setup["players"]
                                   if p.get("isMe"))
                    total += self._persistent_tag_count(game, me_name, tag)
                return total // per, f"{tag} tags of others: {total}"
            total = self._persistent_tag_count(game, name, tag,
                                               extra_info=card_info)
            return total // per, f"own {tag} tags incl. this: {total}"
        if spec.get("eventsPlayed"):
            n = self._events_played_all(game)
            return n, f"events ever played (all): {n}"
        if "cities" in spec:
            where = spec["cities"] if isinstance(spec["cities"], dict) else {}
            if str(where.get("where", "")).lower() == "onmars":
                n = self._cities_on_mars(game)
                return n, f"city tiles ON MARS: {n}"
            n = self._cities_in_play(game)
            return n, f"city tiles in play: {n}"
        if "resourcesHere" in spec:
            # resources sitting on the acting card (Physics Complex science,
            # Predators animals …) — tracked in pool["cardResources"].
            cname = (card_info or {}).get("name")
            n = self.card_resources(game, name, cname)
            return n, f"resources on {cname}: {n}"
        return None

    def card_resources(self, game: dict, name: str, card: str | None) -> int:
        """Resources tracked on one of a player's cards (0 when unknown)."""
        if not card:
            return 0
        return int((self._tr_pool(game, name).get("cardResources")
                    or {}).get(card, 0))

    def _apply_targeted(self, game: dict, name: str, behavior: dict,
                        steps: list[str], card_name: str | None,
                        target: str | None = None, choice: int | None = None,
                        copy: str | None = None) -> None:
        """Behavior keys that need a TARGET / CHOICE / COPY from the
        table (never guessed): stealProduction (Power Supply Consortium),
        removeAny (Sabotage), removeAnyPlants (asteroids — with a target;
        without one it stays a TABLE step), decreaseAnyProduction (Fish…),
        copyProduction (Robotic Workforce)."""
        label = card_name or "card"

        def pool_of(n):
            return game["me"] if self._is_me(n) else game["opponents"][n]

        steal = behavior.get("stealProduction")
        if isinstance(steal, dict):
            if not target:
                raise EventError(f"{label} needs its victim: --target <player>")
            victim = self.resolve_player(target)
            kind, n = steal.get("type", "energy"), int(steal.get("count", 1))
            vp, mine = pool_of(victim)["production"], pool_of(name)["production"]
            if vp[kind] - n < 0:
                raise EventError(f"{victim} has {vp[kind]} {kind} production "
                                 f"— cannot lose {n}")
            vp[kind] -= n
            mine[kind] += n
            steps.append(f"{label}: stole {n} {kind} production from {victim} "
                         f"({victim} → {vp[kind]}, {name} → {mine[kind]})")

        dec = behavior.get("decreaseAnyProduction")
        if isinstance(dec, dict):
            kind, n = dec.get("type", "plants"), int(dec.get("count", 1))
            if not target:
                steps.append(f"→ TABLE: {label}: decrease any {kind} production "
                             f"{n} (name the victim: --target <player>)")
            else:
                victim = self.resolve_player(target)
                vp = pool_of(victim)["production"]
                if vp[kind] - n < 0:
                    raise EventError(f"{victim} has {vp[kind]} {kind} "
                                     f"production — cannot lose {n}")
                vp[kind] -= n
                steps.append(f"{label}: {victim} −{n} {kind} production → {vp[kind]}")

        rm = behavior.get("removeAny")
        if isinstance(rm, dict):
            options = rm.get("options") or []
            menu = "; ".join(
                f"--choice {i} = up to {list(o.values())[0]} "
                f"{ {'megacredits': 'MC'}.get(list(o)[0], list(o)[0]) }"
                for i, o in enumerate(options))
            if not target:
                raise EventError(f"{label} needs a victim: --target <player> "
                                 f"and a resource: {menu}")
            if choice is None or not 0 <= choice < len(options):
                raise EventError(f"{label}: say which resource — {menu}")
            victim = self.resolve_player(target)
            r, n = next(iter(options[choice].items()))
            r = {"megacredits": "mc"}.get(r, r)
            vres = pool_of(victim)["resources"]
            taken = min(int(n), vres[r])
            vres[r] -= taken
            steps.append(f"{label}: {victim} lost {taken} {r} (up to {n}) → {vres[r]}")

        rp = behavior.get("removeAnyPlants")
        if isinstance(rp, int):
            if not target:
                steps.append(f"→ TABLE: {label}: remove up to {rp} plants from "
                             "any player (log with --target <player>, or "
                             "apply.py attack)")
            else:
                victim = self.resolve_player(target)
                vres = pool_of(victim)["resources"]
                taken = min(rp, vres["plants"])
                vres["plants"] -= taken
                steps.append(f"{label}: {victim} lost {taken} plants "
                             f"(up to {rp}) → {vres['plants']}")

        cp = behavior.get("copyProduction")
        if cp:
            if not copy:
                raise EventError(f"{label} copies a production box — name the "
                                 "card: --copy \"<your building card>\"")
            src = self.card(copy)
            if src is None:
                raise EventError(f"{copy!r} not in cards/db.json")
            owned = {c["name"] for c in pool_of(name).get("playedCards", [])}
            if src["name"] not in owned:
                raise EventError(f"{src['name']} is not in {name}'s tableau: "
                                 f"{sorted(owned)}")
            need_tag = cp if isinstance(cp, str) else "building"
            if need_tag not in (src.get("tags") or []):
                raise EventError(f"{src['name']} has no {need_tag} tag "
                                 f"({src.get('tags')}) — {label} cannot copy it")
            prod = (src.get("behavior") or {}).get("production")
            if not prod:
                raise EventError(f"{src['name']} has no production box to copy")
            steps.append(f"{label}: copying {src['name']}'s production box")
            self._apply_behavior(game, name, {"production": prod}, steps,
                                 card_info=src)

    def _branch_executable(self, game: dict, name: str, branch: dict,
                           card_name: str | None = None) -> bool:
        """Can this player actually take this or-branch right now?

        Two ways a branch is impossible: it needs a HOST card ("add 3
        microbes to ANOTHER card") and no played card holds that resource,
        or its `spend` block costs more than the player has (Electro
        Catapult with no plants; Regolith Eaters with 1 microbe on it)."""
        need = branch.get("addResourcesToAnother")
        if isinstance(need, dict):
            kind = str(need.get("type") or "")
            pool = self._tr_pool(game, name)
            for entry in pool.get("playedCards", []):
                other = entry.get("name") if isinstance(entry, dict) else entry
                if other == card_name:        # "ANOTHER card" excludes itself
                    continue
                if card_holds_resource(self.card(other), kind):
                    return True
            return False
        spend = branch.get("spend")
        if isinstance(spend, dict):
            res = self._tr_pool(game, name)["resources"]
            for key, val in spend.items():
                if not isinstance(val, int):
                    continue
                if key == "resourcesHere":
                    if self.card_resources(game, name, card_name) < val:
                        return False
                    continue
                r = SPEND_RESOURCES.get(key)
                if r and res.get(r, 0) < val:
                    return False
        return True

    def _resolve_or(self, game: dict, name: str, behavior: dict,
                    steps: list[str], card_info: dict | None,
                    choice: int | None, or_text: str | None) -> dict:
        """Collapse an `or` behavior to the branch that applies.

        No choice given: when exactly ONE branch is executable the app
        auto-resolves it and so do we; when several are, MY play is refused
        (the branch has to be exact) and an OPPONENT's is flagged instead —
        their state is an estimate and a log line must never be blocked.

        `"or": {"deferred": true, …}` marks a choice the engine CANNOT
        make because it is not made at play time: the app asks for it
        later, out of something the engine does not hold yet (the hex a
        tile lands on, and the placement bonus that comes with it).
        Refusing the play would be wrong — the play is legal, only the
        branch is open — so a missing choice becomes a TABLE step naming
        the menu. Pass `--choice N` and the arithmetic is exact."""
        label = (card_info or {}).get("name") or "card"
        branches = or_branches(card_info, behavior=behavior, text=or_text)
        menu = "; ".join(f"--choice {b['index']} = {b['title']}"
                         for b in branches)
        rest = {k: v for k, v in behavior.items() if k != "or"}
        deferred = bool((behavior.get("or") or {}).get("deferred"))
        picked = None
        if choice is None:
            doable = [b for b in branches
                      if self._branch_executable(game, name, b, label)]
            if deferred and len(doable) != 1:
                steps.append(f"→ TABLE: {label}: the app decides this from "
                             f"the placement — say which and the numbers are "
                             f"exact ({menu})")
                return rest
            if len(doable) == 1:
                picked = doable[0]
                steps.append(
                    f"or-choice AUTO {picked['index']} = {picked['title']} "
                    "— the only branch you can execute")
            elif not self._is_me(name):
                steps.append(f"→ TABLE: {name}'s or-branch not recorded "
                             f"({menu}) — log it with apply.py res/note")
            else:
                raise EventError(
                    f"{label} is an or-choice card — say which branch: {menu}")
        else:
            if not 0 <= choice < len(branches):
                raise EventError(
                    f"choice={choice} out of range; {label} has "
                    f"{len(branches)} branches: {menu}")
            picked = branches[choice]
            steps.append(f"or-choice {choice} = {picked['title']}"
                         + ("" if picked["textOrder"] else
                            " (db order — text order could not be derived)"))
        if picked is not None:
            rest.update({k: v for k, v in picked.items()
                         if k not in ("title", "index", "textOrder")})
        return rest

    def _apply_spend(self, game: dict, name: str, spend: dict,
                     steps: list[str], card_info: dict | None,
                     steel: int = 0, titanium: int = 0) -> None:
        """The Behavior vocabulary's `spend` block: pay a card/action cost.

        canUseSteel / canUseTitanium let ore cover an MC cost (Aquifer
        Pumping "STEEL MAY BE USED"); the units come from the caller
        (`apply.py action use … --steel N`). MINE: short of the cost raises
        BEFORE any mutation. An OPPONENT's stock is an estimate, so it
        clamps to 0 and says so instead of refusing a move the app allowed.
        """
        me = self._is_me(name)
        pool = self._tr_pool(game, name)
        res = pool["resources"]
        label = (card_info or {}).get("name") or "card"
        cname = (card_info or {}).get("name")

        # ore offered against the MC part of the cost
        ore: list[tuple[str, int]] = []
        covered = 0
        for flag, r, value in (("canUseSteel", "steel", STEEL_VALUE),
                               ("canUseTitanium", "titanium", TITANIUM_VALUE)):
            offered = steel if r == "steel" else titanium
            if not offered:
                continue
            if not spend.get(flag):
                raise EventError(f"{label}: {r} may not pay for this action")
            if offered > res[r]:
                if me:
                    raise EventError(
                        f"{label}: {offered} {r} offered, have {res[r]}")
                offered = res[r]
            ore.append((r, offered))
            covered += offered * value

        debits: list[tuple[str, int]] = []
        here = None
        for key, val in spend.items():
            if key in ("canUseSteel", "canUseTitanium"):
                continue
            if key == "resourcesHere" and isinstance(val, int):
                here = val
                continue
            r = SPEND_RESOURCES.get(key)
            if r is None or not isinstance(val, int):
                steps.append(f"→ TABLE: {label}: spend {val!r} {key} "
                             "(not modelled — log it by hand)")
                continue
            n = max(0, val - covered) if r == "mc" else val
            if r == "mc":
                covered = 0
            debits.append((r, n))

        # validate everything before the first mutation
        if here is not None:
            have = self.card_resources(game, name, cname)
            if have < here:
                if me:
                    raise EventError(
                        f"{label}: costs {here} resource(s) from the card, "
                        f"it holds {have}")
                steps.append(f"(estimate had {have} on {cname} — clamped)")
                here = have
        short = [(r, n) for r, n in debits if res[r] < n]
        if short and me:
            r, n = short[0]
            raise EventError(f"{label}: costs {n} {r}, have {res[r]}")

        for r, n in ore:
            res[r] -= n
            steps.append(f"−{n} {r} → {res[r]}")
        for r, n in debits:
            if res[r] < n:
                steps.append(f"(estimate had {res[r]} {r} — clamped)")
                n = res[r]
            res[r] -= n
            steps.append(f"−{n} {r} → {res[r]}")
        if here:
            cr = pool.setdefault("cardResources", {})
            cr[cname] = cr.get(cname, 0) - here
            steps.append(f"−{here} {self.resource_word(card_info)} on "
                         f"{cname} → {cr[cname]}")

    @staticmethod
    def resource_word(card_info: dict | None) -> str:
        """The card resource this card holds ('science', 'microbe'…), from
        the db's `resourceType`; 'resource' when it holds none."""
        return (card_info or {}).get("resourceType") or "resource"

    def _apply_behavior(self, game: dict, name: str, behavior: dict,
                        steps: list[str], card_info: dict | None = None,
                        target: str | None = None, choice: int | None = None,
                        copy: str | None = None, steel: int = 0,
                        titanium: int = 0, or_text: str | None = None,
                        from_card: str | None = None) -> None:
        """THE interpreter for the vendor's Behavior vocabulary — one
        generic path for a card's play effect AND for a blue card's
        `actionBehavior`. Appends trace steps (auto-applied and
        TABLE-manual alike) and raises EventError BEFORE any mutation when
        a cost cannot be paid or a production delta is illegal."""
        me = self._is_me(name)
        board = game["me"] if me else game["opponents"][name]
        if isinstance(behavior.get("or"), dict):
            behavior = self._resolve_or(game, name, behavior, steps,
                                        card_info, choice, or_text)
        if isinstance(behavior.get("spend"), dict):
            self._apply_spend(game, name, behavior["spend"], steps,
                              card_info, steel=steel, titanium=titanium)
        res, prod = board["resources"], board["production"]

        def _canon(d):
            if not isinstance(d, dict):
                return d
            alias = {"megacredits": "mc"}
            return {alias.get(k, k): v for k, v in d.items()}

        # resolve dynamic per-tag/per-count amounts to ints first
        prod_delta = _canon(behavior.get("production"))
        dyn_notes: list[str] = []
        if isinstance(prod_delta, dict):
            resolved = {}
            for r, d in prod_delta.items():
                if isinstance(d, dict):
                    hit = self._resolve_dynamic(game, name, d, card_info)
                    if hit is None:
                        resolved = None
                        break
                    resolved[r] = hit[0]
                    dyn_notes.append(f"{r} production: {hit[1]}")
                else:
                    resolved[r] = d
            prod_delta = resolved

        # validate production deltas (all-or-nothing)
        if isinstance(prod_delta, dict) and all(
                isinstance(v, int) for v in prod_delta.values()):
            for r, d in prod_delta.items():
                if r not in RESOURCES:
                    prod_delta = None
                    break
            else:
                for r, d in prod_delta.items():
                    floor = -5 if r == "mc" else 0
                    if prod[r] + d < floor:
                        raise EventError(
                            f"{name} {r} production would drop below {floor} "
                            f"({prod[r]}{d:+}) — card not playable")
        else:
            prod_delta = None
        if prod_delta is None and "production" in behavior:
            steps.append(f"→ TABLE: adjust production per card ({behavior['production']})")
        elif prod_delta:
            steps.extend(dyn_notes)
            for r, d in prod_delta.items():
                prod[r] += d
                steps.append(f"{r.upper()} production {prod[r]-d} → {prod[r]}")

        stock = _canon(behavior.get("stock"))
        if isinstance(stock, dict):
            for r, d in stock.items():
                if r in RESOURCES and isinstance(d, dict):
                    hit = self._resolve_dynamic(game, name, d, card_info)
                    if hit is not None:
                        d = hit[0]
                        steps.append(f"{r} gain: {hit[1]}")
                if r in RESOURCES and isinstance(d, int):
                    res[r] = max(0, res[r] + d)
                    steps.append(f"{r.upper()} {res[r]-d} → {res[r]}")
                else:
                    steps.append(f"→ TABLE: gain {d} {r}")

        for param, n in (behavior.get("global") or {}).items():
            if param not in PARAM_SCALE or not isinstance(n, int):
                steps.append(f"→ TABLE: adjust {param} by {n}")
                continue
            for _ in range(n):
                raised, desc = self._bump_param(game, param, actor=name)
                if raised:
                    board["tr"] += 1
                    steps.append(f"{desc} → TR {board['tr']}")
                else:
                    steps.append(f"({desc} — no TR)")

        if "ocean" in behavior:
            spec = behavior["ocean"] if isinstance(behavior["ocean"], dict) else {}
            count = spec.get("count", 1)
            count = count if isinstance(count, int) and count > 0 else 1
            for _ in range(count):
                raised, desc = self._bump_param(game, "oceans")
                if raised:
                    board["tr"] += 1
                    steps.append(f"{desc} → TR {board['tr']}")
                    steps.append("→ TABLE: place the ocean tile (name the hex; "
                                 "gain its placement bonus + 2 MC per adjacent ocean)")
                else:
                    # The app's Game.addOcean returns before addTile when
                    # canAddOcean() is false: the card resolves for its
                    # cost, tags and printed VP, and NOTHING downstream
                    # fires — no tile, no TR, no placement bonus, no
                    # ocean-adjacency MC, no ocean-trigger card. No
                    # placement obligation is emitted, so a plan's place
                    # step has nothing to stand on (place() refuses too).
                    steps.append(
                        f"(oceans maxed at {game['globals']['oceans']}/"
                        f"{PARAM_SCALE['oceans']['max']} — the ocean is "
                        "SUPPRESSED: no tile to place, no TR, no placement "
                        "bonus, no adjacency MC, no ocean triggers; the "
                        "card still counts for its tags and printed VP)")

        tr_spec = behavior.get("tr")
        if isinstance(tr_spec, dict):
            # Terraforming Ganymede: +1 TR per own Jovian tag incl. this
            hit = self._resolve_dynamic(game, name, tr_spec, card_info)
            if hit is None:
                steps.append(f"→ TABLE: TR = {tr_spec!r} (resolve manually)")
            else:
                board["tr"] += hit[0]
                steps.append(f"TR +{hit[0]} ({hit[1]}) → {board['tr']}")
        elif isinstance(tr_spec, int):
            board["tr"] += tr_spec
            steps.append(f"TR {tr_spec:+} → {board['tr']}")

        if "greenery" in behavior:
            board["tiles"]["greeneries"] += 1
            raised, desc = self._bump_param(game, "oxygen", actor=name)
            if raised:
                board["tr"] += 1
                steps.append(f"greenery tile, {desc} → TR {board['tr']}")
            else:
                steps.append("greenery tile (O2 maxed — no TR)")
            steps.append("→ TABLE: place the greenery (adjacent to your tiles)")
        if "city" in behavior:
            board["tiles"]["cities"] += 1
            if behavior["city"].get("space"):
                # reserved-area placement (Ganymede Colony, Phobos Space
                # Haven): off-Mars, fixed slot -- never triggers Tharsis,
                # never counts for "cities ON MARS" (Zeppelins, Martian Rails)
                board["tiles"]["citiesOffMars"] = (
                    board["tiles"].get("citiesOffMars", 0) + 1)
                steps.append("city tile → TABLE: place it on the RESERVED "
                             "AREA (off-Mars, no Tharsis trigger)")
            else:
                steps.append("city tile → TABLE: place it (not adjacent to a city)")
        if isinstance(behavior.get("tile"), dict):
            # SPECIAL tiles (Commercial District, Nuclear Zone, Mohole Area…).
            # Never counted before P7: `tiles.special` stayed 0 while the
            # board held the tile, and Landlord is sum(tiles.values()) — so
            # every special tile silently deflated the award metric.
            board["tiles"]["special"] = board["tiles"].get("special", 0) + 1
            steps.append("special tile → TABLE: place it")

        card_name = (card_info or {}).get("name")
        if isinstance(behavior.get("addResources"), int) and card_name:
            cr = board.setdefault("cardResources", {})
            cr[card_name] = cr.get(card_name, 0) + behavior["addResources"]
            steps.append(f"{card_name}: +{behavior['addResources']} "
                         f"{self.resource_word(card_info)} on the card "
                         f"→ {cr[card_name]}")

        rm_any = behavior.get("removeResourcesFromAnyCard")
        if isinstance(rm_any, dict):
            kind = rm_any.get("type", "resource")
            source = rm_any.get("source", "all")
            count = rm_any.get("count", 1)
            if from_card:
                # the host was named (apply.py … --from-card): track it only
                # when it is one of the ACTOR's own cards — resources on
                # somebody else's card are not in our state.
                host_info = self.card(from_card)
                host = (host_info or {}).get("name") or from_card
                owned = {c["name"] for c in board.get("playedCards", [])}
                if host in owned:
                    cr = board.setdefault("cardResources", {})
                    have = cr.get(host, 0)
                    if have < count:
                        raise EventError(
                            f"{host} holds {have} {kind}(s), cannot lose {count}")
                    cr[host] = have - count
                    steps.append(f"−{count} {kind} from {host} → {cr[host]}")
                else:
                    steps.append(f"→ TABLE: {count} {kind} came off {host} "
                                 "(not this player's card — not tracked)")
            else:
                steps.append(
                    f"→ TABLE: remove {count} {kind} from any card "
                    f"(source: {source}) — name it with --from-card "
                    "<card> to track it when it is your own")

        draw = behavior.get("drawCard")
        if draw is not None:
            n = draw.get("count", 1) if isinstance(draw, dict) else draw
            pay = " (buy it or discard it)" if isinstance(draw, dict) and \
                draw.get("pay") else ""
            steps.append(f"→ TABLE: draw {n} card(s){pay} — log with "
                         "`apply.py hand add <card>`")

        host = behavior.get("addResourcesToAnother") or \
            behavior.get("addResourcesToAnyCard")
        if isinstance(host, dict):
            # Resources on somebody else's card are not tracked by the
            # engine — name the host at the table and log it there.
            steps.append(
                f"→ TABLE: add {host.get('count', 1)} {host.get('type', 'resource')} "
                "to ANOTHER card (pick the host card; the engine tracks card "
                "resources only for cards it applies effects to)")

        self._apply_targeted(game, name, behavior, steps, card_name,
                             target=target, choice=choice, copy=copy)

        rebate = behavior.get("standardProjectRebate")
        if isinstance(rebate, dict):
            # a PERSISTENT effect: nothing happens at play time; standard()
            # reads it from the tableau after every paid standard project
            skipped = ", ".join(rebate.get("except") or []) or "none"
            steps.append(f"effect registered: +{rebate.get('amount')} MC "
                         f"after each paid standard project (except: {skipped})")

        handled = {"production", "stock", "global", "ocean", "tr",
                   "greenery", "city", "spend", "or", "drawCard",
                   "addResources", "addResourcesToAnother",
                   "addResourcesToAnyCard", "removeResourcesFromAnyCard",
                   "stealProduction", "standardProjectRebate",
                   "removeAny", "removeAnyPlants", "decreaseAnyProduction",
                   "copyProduction"}
        for key, val in behavior.items():
            if key in handled:
                continue
            steps.append(f"→ TABLE: {key} = {val!r} (resolve "
                         "manually; log follow-ups via apply.py)")

    def play(self, player: str, card: str, cost: int | None = None,
             steel: int = 0, titanium: int = 0, heat: int = 0,
             ignore_requirements: bool = False,
             choice: int | None = None, target: str | None = None,
             copy: str | None = None, olympus: str | None = None,
             no_effects: bool = False,
             count_known: bool | None = None) -> str:
        """Knobs: target = victim for steal/remove cards; copy = card
        whose production box Robotic Workforce duplicates; olympus =
        'add' (default) | 'draw' for the Olympus Conference science
        trigger; no_effects = charge + record only, apply NO db effects
        (the advisor logs res/prod events by hand for odd cards);
        count_known = the caller's channel sees every later add/remove
        on this card (the applog replay passes True), so a played
        accumulator card records an explicit 0 instead of staying
        UNKNOWN. Default: True for me and in app modes, False for a
        physical-mode opponent (their accumulator actions may never be
        logged, and a stale 0 understates them at scoring time)."""
        name = self.resolve_player(player)
        game = self.store.load_game()
        gen = game["generation"]
        info = self.card(card)
        waiver = None
        if info is not None:
            card = info["name"]                     # canonical spelling
            # A closed/expired requirement
            # window refuses the play — the app would too. Override for
            # ability corps (Inventrix ±2, Adaptation Technology) with
            # ignore_requirements=<why> — the waiver is logged.
            if info.get("requirements"):
                import research as _research
                w = _research._window(info["requirements"], game["globals"])
                if w.startswith("closed") or w.startswith("EXPIRED"):
                    # ±2 steps for a player with the ability (corp OR the
                    # card): the same window menu.py already quotes.
                    steps = requirement_gap_steps(info["requirements"],
                                                  game["globals"])
                    if (not ignore_requirements and steps is not None
                            and steps <= 2
                            and requirement_widened(self._tr_pool(game, name))):
                        ignore_requirements = (
                            f"±2-step window ({w}, {steps} step(s) off)")
                    if not ignore_requirements:
                        raise EventError(
                            f"{card!r} requirement not met: {w} "
                            "(play … --ignore-requirements \"why\" to "
                            "override, e.g. Inventrix ±2, Adaptation "
                            "Technology)")
                    why = (ignore_requirements
                           if isinstance(ignore_requirements, str)
                           else "no reason given")
                    waiver = (f"requirement WAIVED ({w}) — "
                              f"--ignore-requirements: {why}")
        override = cost is not None            # --cost pins the price
        if cost is None:
            if info is None or info["type"] == "corporation":
                raise EventError(
                    f"{card!r} not in cards/db.json — give its cost explicitly "
                    "(play ... --cost N)")
            cost = info["cost"]
        behavior = (info or {}).get("behavior")
        steps: list[str] = []
        if waiver:
            steps.append(waiver)
        # or-choice cards (Artificial Photosynthesis, Imported Hydrogen) are
        # resolved inside _apply_behavior (_resolve_or): a choice is recorded
        # via choice=N in CARD-TEXT order, a single executable branch is
        # auto-applied the way the app does, and anything else refuses (mine)
        # or is flagged (an opponent's estimate) rather than being guessed.
        base_cost = (info["cost"] if info and isinstance(info.get("cost"), int)
                     else cost)
        # Corp/tableau discounts come off the printed cost unless the
        # caller pinned the price with --cost (then the trace says so).
        disc_notes: list[str] = []
        used_next = False
        if info is not None and not override:
            disc, disc_notes, used_next = self._card_discount(game, name, info)
            cost = max(0, base_cost - disc)
        if (info or {}).get("bespoke"):
            steps.append("→ TABLE: BESPOKE card — db behavior may be partial; "
                         "read the card text and log any extra effects")
        me = self._is_me(name)
        if me:
            me_board = game["me"]
            if card not in me_board["hand"]:
                raise EventError(f"{card!r} is not in hand: {me_board['hand']}")
            res = me_board["resources"]
            if steel > res["steel"] or titanium > res["titanium"]:
                raise EventError(
                    f"Not enough steel/titanium (have {res['steel']}/{res['titanium']})"
                )
            if heat:
                if not self._my_corp_rule(game, name, "heatAsMC"):
                    raise EventError("Only Helion can spend heat as MC")
                if heat > res["heat"]:
                    raise EventError(f"Not enough heat (have {res['heat']})")
            tags = (info or {}).get("tags")
            if tags is not None:
                if steel and "building" not in tags:
                    raise EventError(
                        f"Steel pays only for building-tag cards; {card} tags: {tags}")
                if titanium and "space" not in tags:
                    raise EventError(
                        f"Titanium pays only for space-tag cards; {card} tags: {tags}")
            elif steel or titanium:
                steps.append("⚠ verify at table: card not in db — steel/titanium "
                             "payment tag rule unchecked")
            mc_due = split_payment(game, name, cost, steel=steel,
                                   titanium=titanium, heat=heat)["mc"]
            if mc_due > res["mc"]:
                raise EventError(f"Need {mc_due} MC, have {res['mc']}")
            steps.insert(0, self._paid_line(mc_due, base_cost, cost,
                                            disc_notes, override))
            if behavior and not no_effects:
                self._apply_behavior(game, name, behavior, steps,
                                     card_info=info, target=target,
                                     choice=choice, copy=copy)  # may raise
            res["mc"] -= mc_due
            res["steel"] -= steel
            res["titanium"] -= titanium
            res["heat"] -= heat
            if used_next:
                me_board.pop("nextCardDiscount", None)
            corp = self._corp_of(game, name)
            self._credicor_rebate(game, name, base_cost, steps)
            bonus = corp_rule(corp, "eventMC")
            if bonus and (info or {}).get("type") == "event":
                res["mc"] += bonus
                steps.append(f"{corp}: +{bonus} MC (event)")
            me_board["hand"].remove(card)
            me_board["playedCards"].append({"name": card, "gen": gen})
            if info and info["type"] == "active" and info.get("action"):
                entry = {"used": False}
                entry.update(self._action_costs(info))
                me_board["actionsThisGen"][card] = entry
                steps.append(f"blue action registered: {info['action']}")
            pay = f"{mc_due} MC" + (f" + {steel} steel" if steel else "") + (
                f" + {titanium} Ti" if titanium else "") + (
                f" + {heat} heat" if heat else "")
            head = f"{name} played {card} (paid {pay}) → balance {res['mc']} MC"
        else:
            opp = game["opponents"][name]
            if behavior and not no_effects:
                self._apply_behavior(game, name, behavior, steps,
                                     card_info=info, target=target,
                                     choice=choice, copy=copy)
            # Same payment semantics as my branch — `cost` is the
            # card's GROSS cost and steel/titanium/heat cover part of it.
            # Opponent stocks are estimates, so every subtraction floors at
            # 0 instead of raising (their pile may be larger than we think).
            ores = opp["resources"]
            mc_due = split_payment(game, name, cost, steel=steel,
                                   titanium=titanium, heat=heat)["mc"]
            steps.insert(0, self._paid_line(mc_due, base_cost, cost,
                                            disc_notes, override))
            ores["mc"] = max(0, ores["mc"] - mc_due)
            for res_name, spent in (("steel", steel), ("titanium", titanium),
                                    ("heat", heat)):
                if spent:
                    ores[res_name] = max(0, ores[res_name] - spent)
                    steps.append(f"paid {spent} {res_name}")
            if used_next:
                opp.pop("nextCardDiscount", None)
            ocorp = self._corp_of(game, name)
            self._credicor_rebate(game, name, base_cost, steps)
            bonus = corp_rule(ocorp, "eventMC")
            if bonus and (info or {}).get("type") == "event":
                opp["resources"]["mc"] += bonus
                steps.append(f"{ocorp}: +{bonus} MC (event)")
            opp["playedCards"].append({"name": card, "gen": gen})
            for t in (info or {}).get("tags", []):
                opp["tagCounts"][t] = opp["tagCounts"].get(t, 0) + 1
            head = (f"{name} played {card} "
                    f"(~−{cost} MC → ~{opp['resources']['mc']})")
        if no_effects:
            steps.append("NO EFFECTS applied (--no-effects): cost charged, card "
                         "+ tags recorded — log the card's res/prod/tr/tile "
                         "events by hand now")
        else:
            if "jovian" in (info or {}).get("tags", []):
                for holder, n in self._corp_holders(game,
                                                    "jovianTagMCProduction"):
                    pool = self._tr_pool(game, holder)
                    pool["production"]["mc"] += n
                    steps.append(f"{pool.get('corporation')} ({holder}): "
                                 f"+{n} MC production (Jovian)")
            if behavior and "city" in behavior:
                self._on_city_placed(game, name, steps,
                                     on_mars=not behavior["city"].get("space"))
            self._olympus_trigger(game, name, info, steps, olympus)
            self._set_next_card_discount(game, name, card, steps)
        # Accumulator cards (resourceType in the db): the tile enters play
        # holding 0 — record that FACT when the channel will also see the
        # later adds/removes; otherwise leave the count UNKNOWN (absent),
        # which score.py turns into an explicit bound instead of a lie.
        # no_effects skips db effects, not bookkeeping: the 0 is a fact.
        if (info or {}).get("resourceType"):
            known = (count_known if count_known is not None
                     else me or self.setup.get("gameMode") in APP_MODES)
            if known:
                self._tr_pool(game, name).setdefault(
                    "cardResources", {}).setdefault(card, 0)
        if steps:
            head += "\n  " + "\n  ".join(
                f"{i}. {st}" for i, st in enumerate(steps, 1))
        return self._commit(game, head)

    @staticmethod
    def _paid_line(mc_due: int, base_cost: int, cost: int,
                   notes: list[str] | None = None,
                   override: bool = False) -> str:
        """Trace line for the MC actually charged vs the printed cost, with
        the discounts that produced the applied price:
        'paid 3 MC (base 6, −3: Teractor −3)'. A --cost override skips the
        auto-discounts and says so."""
        line = f"paid {mc_due} MC (base {base_cost}"
        if notes and cost != base_cost:
            line += f", −{base_cost - cost}: " + ", ".join(notes)
        elif notes:
            line += ", discounts: " + ", ".join(notes)
        line += ")"
        if override:
            line += f" — --cost {cost} override (auto-discounts skipped)"
        return line

    def _olympus_trigger(self, game: dict, name: str, info: dict | None,
                         steps: list[str], olympus: str | None) -> None:
        """Olympus Conference: when its owner plays a science tag (incl.
        itself) — add a science resource (default) or remove one to draw
        a card (olympus='draw'). The choice is the player's each time (e.g.
        add on Gene Repair, draw on Robotic Workforce)."""
        if "science" not in (info or {}).get("tags", []):
            return
        pool = self._tr_pool(game, name)
        olympus_card = OLYMPUS_CONFERENCE
        if not any(c["name"] == olympus_card
                   for c in pool.get("playedCards", [])):
            return
        cr = pool.setdefault("cardResources", {})
        n = cr.get(olympus_card, 0)
        mode = (olympus or "add").lower()
        if mode == "draw":
            if n < 1:
                raise EventError(f"{olympus_card} has no science resource "
                                 "to remove — use --olympus add")
            cr[olympus_card] = n - 1
            steps.append(f"{olympus_card}: −1 science (→ {n-1}) to DRAW a "
                         "card → TABLE/APP: `hand add <card>`"
                         if self._is_me(name) else
                         f"{olympus_card}: −1 science (→ {n-1}), drew a card")
        elif mode == "add":
            cr[olympus_card] = n + 1
            steps.append(f"{olympus_card}: +1 science (→ {n+1}; say "
                         "--olympus draw if a card was drawn instead)")
        else:
            raise EventError(f"olympus={olympus!r}: use add or draw")

    # ── per-generation action ledger (saturation-check data) ─

    @staticmethod
    def _action_costs(info: dict | None) -> dict:
        """Per-use MC / heat cost of a blue-card action, from the db's
        `actionBehavior.spend` (the cheapest branch of an or-action); the
        prose fallback covers the handful of cards the vendor implements as
        TypeScript instead of an ActionCard block."""
        costs: dict[str, int] = {}
        branches = action_spend_options(info)
        for key, field in (("megacredits", "mcCost"), ("heat", "heatCost")):
            amounts = [int(b.get(key, 0)) for b in branches]
            if amounts and any(amounts):
                costs[field] = min(amounts)
        if branches:
            return costs
        import re as _re
        text = (info or {}).get("action") or ""
        m = _re.search(r"[Ss]pend (\d+)\s*M", text)
        if m:
            costs["mcCost"] = int(m.group(1))
        m = _re.search(r"[Ss]pend (\d+)\s*heat", text)
        if m:
            costs["heatCost"] = int(m.group(1))
        return costs

    def _unspent_action_cost(self, game: dict, name: str, action: str,
                             info: dict | None) -> dict:
        """The per-use cost of a blue-card action that the card's OWN
        `actionBehavior` does not pay, as a `spend` block.

        A structured action carries `actionBehavior.spend` and the
        interpreter charges it. The handful of actions the vendor writes as
        TypeScript instead have no spend block at all — their price lives
        only in the prose, which `_action_costs` already parsed into the
        ledger at registration time (`{"used": false, "mcCost": 1}`). Until
        this, nothing spent it: the ledger knew the price and the sandbox
        used the action for free (P9 issue 3 — Search For Life mispredicted
        MC by −1 in every generation it was used).

        Returns {} whenever ANY behavior branch declares a spend, because
        `_action_costs` derives the ledger figure from exactly that block
        and charging it again would double the price.
        """
        if any(action_spend_options(info)):
            return {}
        entry = (game["me"]["actionsThisGen"].get(action)
                 if self._is_me(name) else None)
        costs = {k: v for k, v in (entry or {}).items()
                 if k in ("mcCost", "heatCost")}
        if not costs:
            costs = self._action_costs(info)
        spend = {}
        for field, key in (("mcCost", "megacredits"), ("heatCost", "heat")):
            n = costs.get(field)
            if isinstance(n, int) and n > 0:
                spend[key] = n
        return spend

    def _action_behavior(self, game: dict, name: str, action: str,
                         info: dict | None) -> tuple[dict | None, bool]:
        """(behavior to interpret, whether the card models its effect).

        The behavior is the db's `actionBehavior` plus — when the card has
        no spend block of its own — the registered per-use cost, so ONE
        interpreter applies both, and `_reverse_behavior` refunds both.
        """
        behavior = (info or {}).get("actionBehavior")
        modelled = isinstance(behavior, dict)
        extra = self._unspent_action_cost(game, name, action, info)
        if extra:
            base = behavior if modelled else {}
            behavior = {**base, "spend": {**(base.get("spend") or {}), **extra}}
        return behavior, modelled

    def register_action(self, action: str) -> str:
        game = self.store.load_game()
        entry = {"used": False}
        info = self.card(action)
        if info and info.get("action"):
            entry.update(self._action_costs(info))
        # play() keys the ledger by db spelling; a raw key
        # here would duplicate the entry and the saturation renderer would
        # keep showing the db-spelled one as AVAILABLE after `action use`.
        action = self._ledger_key(game, action)
        game["me"]["actionsThisGen"][action] = entry
        return self._commit(game, f"Action registered: {action} (available)")

    def _ledger_key(self, game: dict, action: str) -> str:
        """Canonical actionsThisGen key: existing entry (case-insensitive),
        else the db spelling, else the raw string."""
        for k in game["me"]["actionsThisGen"]:
            if k.lower() == action.lower():
                return k
        info = self.card(action)
        return info["name"] if info else action

    def attack(self, target: str, resource: str, n: int,
               by: str | None = None) -> str:
        """Removal/attack event. The EFFECT applies now
        (the target's ledger is truth regardless of attacker); the
        ATTRIBUTION pends when unknown — threat-analysis needs the who.
        """
        name = self.resolve_player(target)
        game = self.store.load_game()
        pool = (game["me"] if self._is_me(name)
                else game["opponents"][name])["resources"]
        res = resource if resource in pool else {"megacredits": "mc"}.get(resource, resource)
        if res not in pool:
            raise EventError(f"Unknown resource {resource!r}")
        pool[res] = max(0, pool[res] - n)
        parts = [f"ATTACK on {name}: -{n} {res} → {pool[res]}"]
        if by is not None:
            attacker = self.resolve_player(by)
            parts.append(f"by {attacker}")
        else:
            game.setdefault("pendingAttribution", []).append(
                {"gen": game["generation"], "target": name,
                 "resource": res, "n": n})
            parts.append("attacker UNKNOWN — ask WHO did it "
                         "(threat-analysis needs the attribution)")
        return self._commit(game, ", ".join(parts))

    def attribute(self, index: int, attacker: str) -> str:
        """Resolve a pending attack attribution by list index."""
        game = self.store.load_game()
        pending = game.get("pendingAttribution", [])
        if not (0 <= index < len(pending)):
            raise EventError(f"No pending attribution #{index}; have {len(pending)}")
        entry = pending.pop(index)
        who = self.resolve_player(attacker)
        return self._commit(
            game, f"Attribution resolved: {who} was the attacker "
                  f"(-{entry['n']} {entry['resource']} on {entry['target']}, "
                  f"G{entry['gen']})")

    def declare_final(self) -> str:
        """The table declared THIS the last generation.
        Pins the clock; advisor flips to pure-VP mode."""
        game = self.store.load_game()
        game["declaredFinalGeneration"] = game["generation"]
        return self._commit(
            game, f"TABLE DECLARED generation {game['generation']} FINAL "
                  "— pure-VP mode: no production purchases, spend "
                  "everything, hold award metrics")

    def tiles_fix(self, player: str, kind: str, value: int) -> str:
        """Correction event: set a tile counter to an observed value.

        For reconciliation only (phantom reversals, missed play bumps) —
        normal counter movement stays with play/convert/standard.
        """
        name = self.resolve_player(player)
        game = self.store.load_game()
        pool = game["me"] if self._is_me(name) else game["opponents"][name]
        tiles = pool["tiles"]
        # `special` post-dates some saved games; seed the canonical counters
        # so reconciliation never fails on an older game.json
        for canon in ("cities", "greeneries", "special"):
            tiles.setdefault(canon, 0)
        if kind not in tiles:
            raise EventError(
                f"Unknown tile counter {kind!r}; have {sorted(tiles)}")
        old = tiles[kind]
        tiles[kind] = value
        return self._commit(
            game, f"{name}: tiles.{kind} corrected {old} → {value}")

    def use_action(self, action: str, player: str | None = None,
                   choice: int | str | None = None, steel: int = 0,
                   titanium: int = 0, target: str | None = None,
                   from_card: str | None = None,
                   gen: int | None = None) -> str:
        """Blue-card action, driven by the card's `actionBehavior` (the
        vendor's own ActionCard `action:` block, extracted into
        cards/db.json) through the SAME interpreter that applies a card's
        play behavior — no per-card code. Mine: the once-per-generation
        ledger (registered on play) plus the effect; an opponent's
        (`--player`): the effect only, their ledger is not tracked.

        steel / titanium: ore paid towards an MC cost the card allows
        (Aquifer Pumping "STEEL MAY BE USED", Water Import From Europa) —
        `apply.py action use … --steel N`. from_card: the host a "remove 1
        X from any card" action took its resource from.

        choice: which branch of an or-action — an int index in CARD-TEXT
        order, or a case-insensitive substring of the branch's title
        (`resolve_branch_choice`, the transmitter's own matcher). Prefer
        the title: the app's live branch order is not the card's, so the
        same integer names different branches in the two layers — that is
        how a "remove 3 microbes" step once executed "add 1 microbe".

        gen: the SOURCE generation of the event, when it is a drained
        app-log line rather than a fresh use (the listener knows which
        generation's log it is reading). The ledger is per generation and
        every use is stamped with it (`{"used": true, "gen": N}`), so a
        reflection older than the tracker's generation is a use that was
        already counted when its generation closed: it is ABSORBED — no
        effect, the current ledger untouched (D3 / H1c: a generation-7
        Nitrite action drained after the turnover marked generation 8's
        slot used). No `gen` = the current generation.
        """
        game = self.store.load_game()
        name = self.resolve_player(player) if player else game["me"]["name"]
        me = self._is_me(name)
        parts: list[str] = []
        info = self.card(action)
        if me:
            ledger = game["me"]["actionsThisGen"]
            action = self._ledger_key(game, action)
            if action not in ledger:
                raise EventError(
                    f"Unknown action {action!r}; register it first. Ledger: {list(ledger)}"
                )
            if gen is not None and gen < game["generation"]:
                # narrative for the event-log replay (not "Action used: …")
                return self._commit(
                    game, f"Action of generation {gen} absorbed: {action} — "
                          f"generation {game['generation']} ledger untouched "
                          f"(the use was counted when generation {gen} closed)")
            if ledger[action]["used"]:
                raise EventError(f"{action!r} already used this generation")
        else:
            action = info["name"] if info else action
            opp = game["opponents"][name]
            if not any(c["name"] == action for c in opp.get("playedCards", [])):
                parts.append(f"⚠ {action} is not in {name}'s tracked tableau "
                             "(play never logged?) — effect applied anyway")
        behavior, modelled = self._action_behavior(game, name, action, info)
        if isinstance(behavior, dict) and isinstance(behavior.get("or"), dict):
            # ONE grammar with the transmitter: a title selector is resolved
            # here, against this card's own branch labels, before anything
            # downstream sees an index.
            choice = resolve_branch_choice(
                choice,
                or_branches(info, behavior=behavior,
                            text=(info or {}).get("action")),
                label=(info or {}).get("name") or action)
        if isinstance(behavior, dict):
            self._apply_behavior(game, name, behavior, parts, card_info=info,
                                 target=target, choice=choice, steel=steel,
                                 titanium=titanium, from_card=from_card,
                                 or_text=(info or {}).get("action"))
        if not modelled and not me:
            parts.append("effect not modeled — log res/prod events by hand")
        if me:
            ledger[action]["used"] = True
            ledger[action]["gen"] = game["generation"]
            head = f"Action used: {action} \u2713"
        else:
            head = f"{name} used action {action}"
        if parts:
            head += ": " + ", ".join(parts)
        return self._commit(game, head)

    # `apply.py action use <card>` names this verb "action".
    action = use_action

    def unuse_action(self, action: str, player: str | None = None,
                     choice: int | None = None, steel: int = 0,
                     titanium: int = 0, from_card: str | None = None) -> str:
        """Inverse of use_action — correct.py's reversal of a wrongly
        applied `use_action` plan step: undo the behavior's mechanics
        (resources, card resources, production, TR, a raised global and the
        TR it granted, tile counters) AND free the once-per-generation
        ledger. `choice`/`steel`/`titanium` must match the use.

        The inverse is GENERIC — _reverse_behavior negates the same
        behavior dict use_action applied. EventError = not invertible from
        the current state (the resource is already gone, the parameter is
        not where the raise left it, the effect has no inverse at all);
        nothing is committed then, so the caller can print a MANUAL line and
        still reset the ledger."""
        game = self.store.load_game()
        name = self.resolve_player(player) if player else game["me"]["name"]
        me = self._is_me(name)
        parts: list[str] = []
        info = self.card(action)
        canon = (self._ledger_key(game, action) if me
                 else (info["name"] if info else action))
        behavior, _modelled = self._action_behavior(game, name, canon, info)
        if isinstance(behavior, dict) and isinstance(behavior.get("or"), dict):
            # the inverse reads the same selector the use did, in the same
            # grammar (`choice` must match the use — a title is a value the
            # step already carries)
            choice = resolve_branch_choice(
                choice,
                or_branches(info, behavior=behavior,
                            text=(info or {}).get("action")),
                label=canon)
        if isinstance(behavior, dict):
            self._reverse_behavior(game, name, behavior, parts, info,
                                   choice=choice, steel=steel,
                                   titanium=titanium, from_card=from_card)
        else:
            parts.append("no mechanical effect was applied — ledger only")
        if me:
            ledger = game["me"]["actionsThisGen"]
            if canon in ledger:
                ledger[canon]["used"] = False
                ledger[canon].pop("gen", None)
                parts.append("ledger: available again")
            else:
                entry = {"used": False}
                if info and info.get("action"):
                    entry.update(self._action_costs(info))
                ledger[canon] = entry
                parts.append("ledger: re-registered (available)")
            head = f"Action reversed: {canon}"
        else:
            head = f"{name}'s action reversed: {canon}"
        if parts:
            head += ": " + ", ".join(parts)
        return self._commit(game, head)

    def _reverse_behavior(self, game: dict, name: str, behavior: dict,
                          parts: list[str], card_info: dict | None,
                          choice: int | None = None, steel: int = 0,
                          titanium: int = 0,
                          from_card: str | None = None) -> None:
        """GENERIC inverse of a behavior dict: refund `spend`, take back
        `stock`, negate `production`/`tr`/`addResources`, walk a raised
        global back one step per raise (with the TR it granted), and undo
        tile counters. Anything with no inverse raises EventError with a
        MANUAL message — never a half-undo."""
        me = self._is_me(name)
        pool = self._tr_pool(game, name)
        res, prod = pool["resources"], pool["production"]
        label = (card_info or {}).get("name") or "card"
        cname = (card_info or {}).get("name")

        if isinstance(behavior.get("or"), dict):
            branches = or_branches(card_info, behavior=behavior,
                                   text=(card_info or {}).get("action"))
            menu = "; ".join(f"--choice {b['index']} = {b['title']}"
                             for b in branches)
            deferred = bool((behavior.get("or") or {}).get("deferred"))
            if choice is None and deferred:
                # nothing was applied without a choice (see _resolve_or)
                parts.append("no branch was applied — nothing to take back")
                behavior = {k: v for k, v in behavior.items() if k != "or"}
            elif choice is None or not 0 <= choice < len(branches):
                raise EventError(
                    f"{label}: which branch was used? ({menu})")
            else:
                picked = branches[choice]
                behavior = {k: v for k, v in behavior.items() if k != "or"}
                behavior.update({k: v for k, v in picked.items()
                                 if k not in ("title", "index", "textOrder")})

        def refund(r: str, n: int) -> None:
            if not n:
                return
            res[r] += n
            parts.append(f"+{n} {r} → {res[r]}")

        def take(r: str, n: int) -> None:
            if not n:
                return
            if res[r] < n:
                if me:
                    raise EventError(
                        f"{label}: cannot take back {n} {r} — only "
                        f"{res[r]} left (spent since?)")
                parts.append(f"(estimate had {res[r]} {r} — clamped)")
                res[r] = 0
            else:
                res[r] -= n
            parts.append(f"−{n} {r} → {res[r]}")

        def card_delta(n: int) -> None:
            """+n resources back onto / off the acting card."""
            cr = pool.setdefault("cardResources", {})
            have = cr.get(cname, 0)
            if have + n < 0:
                raise EventError(
                    f"{label}: {-n} {self.resource_word(card_info)}(s) to "
                    f"remove, the card holds {have}")
            cr[cname] = have + n
            parts.append(f"{n:+} {self.resource_word(card_info)} on {cname} "
                         f"→ {cr[cname]}")

        def lower_param(param: str) -> None:
            """Undo one raised step AND the TR it granted."""
            scale = PARAM_SCALE[param]
            cur = game["globals"][param]
            if cur <= scale["min"]:
                raise EventError(
                    f"{label}: {param} is at {cur}{scale['unit']} — the "
                    "raise it granted is not in the tracker to undo")
            if cur >= scale["max"]:
                parts.append(
                    f"⚠ {param} sits at the cap — if the action found it "
                    "already maxed it raised nothing; check the table")
            new = cur - scale["step"]
            game["globals"][param] = new
            parts.append(f"{param} {cur}{scale['unit']} → "
                         f"{new}{scale['unit']}")
            pool["tr"] -= 1
            parts.append(f"TR −1 → {pool['tr']}")
            if param == "oceans":
                self._unfire_triggers(game, OCEAN_TRIGGERS, parts,
                                      "ocean undone")

        # what the action GAVE comes back off first, then its cost is refunded
        stock = behavior.get("stock")
        if isinstance(stock, dict):
            for key, val in stock.items():
                r = SPEND_RESOURCES.get(key, key)
                if r not in RESOURCES:
                    raise EventError(
                        f"{label}: cannot invert `stock {key}` — undo it by "
                        "hand (apply.py res/prod)")
                if isinstance(val, dict):
                    hit = self._resolve_dynamic(game, name, val, card_info)
                    if hit is None:
                        raise EventError(
                            f"{label}: cannot invert the dynamic gain "
                            f"{val!r} — undo it by hand")
                    val = hit[0]
                take(r, int(val))

        prod_delta = behavior.get("production")
        if isinstance(prod_delta, dict):
            for key, val in prod_delta.items():
                r = SPEND_RESOURCES.get(key, key)
                if r not in RESOURCES or not isinstance(val, int):
                    raise EventError(
                        f"{label}: cannot invert `production {key}: {val!r}`"
                        " — undo it by hand (apply.py prod)")
                floor = -5 if r == "mc" else 0
                if prod[r] - val < floor:
                    raise EventError(
                        f"{label}: taking back {val} {r} production would "
                        f"drop below {floor} — undo it by hand")
                prod[r] -= val
                parts.append(f"{r.upper()} production {prod[r]+val} → {prod[r]}")

        for param, n in (behavior.get("global") or {}).items():
            if param not in PARAM_SCALE or not isinstance(n, int):
                raise EventError(f"{label}: cannot invert `global {param}` "
                                 "— undo it by hand (apply.py sync --force)")
            for _ in range(n):
                lower_param(param)

        if "ocean" in behavior:
            spec = behavior["ocean"] if isinstance(behavior["ocean"], dict) else {}
            count = spec.get("count", 1)
            count = count if isinstance(count, int) and count > 0 else 1
            for _ in range(count):
                lower_param("oceans")
            parts.append("→ TABLE: take the ocean tile back off the board "
                         "(apply.py unplace <hex>) if it was placed")

        if "greenery" in behavior:
            pool["tiles"]["greeneries"] = max(
                0, pool["tiles"].get("greeneries", 0) - 1)
            lower_param("oxygen")
            parts.append("→ TABLE: apply.py unplace <hex> for the greenery")
        if "city" in behavior:
            pool["tiles"]["cities"] = max(0, pool["tiles"].get("cities", 0) - 1)
            parts.append("→ TABLE: apply.py unplace <hex> for the city")
        if isinstance(behavior.get("tile"), dict):
            pool["tiles"]["special"] = max(
                0, pool["tiles"].get("special", 0) - 1)
            parts.append("→ TABLE: apply.py unplace <hex> for the special tile")

        tr_spec = behavior.get("tr")
        if isinstance(tr_spec, int):
            pool["tr"] -= tr_spec
            parts.append(f"TR {-tr_spec:+} → {pool['tr']}")
        elif tr_spec is not None:
            raise EventError(f"{label}: cannot invert a dynamic TR gain "
                             f"({tr_spec!r}) — undo it by hand")

        if isinstance(behavior.get("addResources"), int) and cname:
            card_delta(-behavior["addResources"])

        rm_any = behavior.get("removeResourcesFromAnyCard")
        if isinstance(rm_any, dict):
            count = rm_any.get("count", 1)
            kind = rm_any.get("type", "resource")
            if from_card:
                host_info = self.card(from_card)
                host = (host_info or {}).get("name") or from_card
                owned = {c["name"] for c in pool.get("playedCards", [])}
                if host in owned:
                    cr = pool.setdefault("cardResources", {})
                    cr[host] = cr.get(host, 0) + count
                    parts.append(f"+{count} {kind} back on {host} → {cr[host]}")
                else:
                    parts.append(f"→ TABLE: put {count} {kind} back on {host}")
            else:
                parts.append(f"→ TABLE: put {count} {kind} back on the card "
                             "it was taken from")

        if behavior.get("drawCard") is not None:
            parts.append("→ TABLE: the drawn card goes back "
                         "(apply.py hand remove <card>)")

        spend = behavior.get("spend")
        if isinstance(spend, dict):
            covered = 0
            for flag, r, value in (("canUseSteel", "steel", STEEL_VALUE),
                                   ("canUseTitanium", "titanium",
                                    TITANIUM_VALUE)):
                offered = steel if r == "steel" else titanium
                if offered and spend.get(flag):
                    refund(r, offered)
                    covered += offered * value
            for key, val in spend.items():
                if key in ("canUseSteel", "canUseTitanium"):
                    continue
                if key == "resourcesHere" and isinstance(val, int):
                    card_delta(val)
                    continue
                r = SPEND_RESOURCES.get(key)
                if r is None or not isinstance(val, int):
                    raise EventError(
                        f"{label}: cannot invert `spend {key}: {val!r}` — "
                        "refund it by hand (apply.py res)")
                refund(r, max(0, val - covered) if r == "mc" else val)
                if r == "mc":
                    covered = 0

        handled = {"spend", "stock", "production", "global", "ocean", "tr",
                   "greenery", "city", "tile", "addResources", "drawCard",
                   "removeResourcesFromAnyCard"}
        left = [k for k in behavior if k not in handled]
        if left:
            raise EventError(
                f"{label}: no generic inverse for {left} — MANUAL: undo it "
                "by hand (apply.py res/prod/tr/sync --force)")

    def _unfire_triggers(self, game: dict, table: dict, parts: list,
                         why: str) -> None:
        """Inverse of _fire_triggers (a reversed ocean/city trigger)."""
        for holder, pool in self._all_pools(game):
            for entry in pool.get("playedCards", []):
                spec = table.get(entry["name"])
                if not spec:
                    continue
                for r, d in (spec.get("production") or {}).items():
                    pool["production"][r] -= d
                    parts.append(f"{entry['name']} ({holder}): {-d:+} "
                                 f"{r.upper()} production → "
                                 f"{pool['production'][r]} ({why})")
                for r, d in (spec.get("stock") or {}).items():
                    pool["resources"][r] = max(0, pool["resources"][r] - d)
                    parts.append(f"{entry['name']} ({holder}): {-d:+} "
                                 f"{r.upper()} → {pool['resources'][r]} "
                                 f"({why})")

    # ── research phase ───────────────────────────────────────

    def _zero_buy_gate(self, game: dict, kept: list[str],
                       override: str | None) -> str:
        """Zero-buy research gate (fix-plan W1-B, ×2 evidence — game5
        bought one card in gens 2-9; KB: two consecutive zero-buy
        research phases are a hard trigger). Recording MY research with
        zero kept cards when the PREVIOUS generation's research was also
        zero-kept is refused unless `override` carries a reason (logged).
        The refusal names the variable and the evidence — it never says
        what to buy. Returns the log suffix ('' or the OVERRIDDEN tag)."""
        if kept:
            return ""
        gen = game["generation"]
        evidence = self.zero_buy_evidence(game)
        if evidence is None:
            return ""
        if override and override.strip():
            return buy0_override_tag(override)
        self.store.log(f"G{gen}", BUY0_REFUSED + evidence)
        raise EventError(
            f"RESEARCH kept=0 REFUSED — {evidence}. Record it anyway with "
            f"--override \"<reason>\" (the reason is logged)")

    def dealt(self, cards: list[str], kept: list[str],
              drafted: bool = False, override: str | None = None) -> str:
        """Research phase. drafted=True (draft variant): the four cards
        were assembled pick-1-pass, logged as a distinct event.
        `override`: reason to record a SECOND consecutive zero-kept
        research past the buy-0 gate (logged)."""
        game = self.store.load_game()
        gate_tag = self._zero_buy_gate(game, kept, override)
        remaining = list(cards)
        for k in kept:
            if k not in remaining:
                raise EventError(
                    f"kept {kept} must be drawn from dealt {cards} without duplicates")
            remaining.remove(k)
        due = CARD_KEEP_COST * len(kept)
        res = game["me"]["resources"]
        if due > res["mc"]:
            raise EventError(f"Keeping {len(kept)} cards costs {due} MC, have {res['mc']}")
        res["mc"] -= due
        entry = {"gen": game["generation"], "dealt": list(cards), "kept": list(kept)}
        if drafted:
            entry["drafted"] = True
        game["me"]["dealtLog"].append(entry)
        game["me"]["hand"].extend(kept)
        return self._commit(
            game,
            research_log_line(cards, kept, due, res["mc"], drafted=drafted,
                              suffix=gate_tag))

    def note_research(self, cards: list[str], kept: list[str], charged: int,
                      drafted: bool = False, suffix: str = "") -> str:
        """Record a research phase the APP already resolved (the API path:
        `execute.py pick`). The caller has moved the cards into the hand and
        charged the price — this only writes the dealtLog entry and the SAME
        log line `dealt` writes, because that line is where shape.py reads my
        buys from (fix-plan item 4a: on the API path it was never written and
        the buy-0 gate went blind for a whole game)."""
        game = self.store.load_game()
        entry = {"gen": game["generation"], "dealt": list(cards),
                 "kept": list(kept)}
        if drafted:
            entry["drafted"] = True
        game["me"].setdefault("dealtLog", []).append(entry)
        return self._commit(
            game,
            research_log_line(cards, kept, charged,
                              game["me"]["resources"]["mc"],
                              drafted=drafted, suffix=suffix))

    def zero_buy_evidence(self, game: dict | None = None) -> str | None:
        """The buy-0 gate's FACT, or None when keeping zero cards now would
        not be the second consecutive zero-buy research. Shared by the
        engine's own gate (`dealt`) and the API path (`execute.py pick`),
        which must refuse BEFORE transmitting."""
        game = game if game is not None else self.store.load_game()
        gen = game["generation"]
        log = game["me"].get("dealtLog") or []
        prev = [e for e in log if e.get("gen") == gen - 1]
        if not prev or prev[-1].get("kept"):
            return None
        counts = {e["gen"]: len(e.get("kept") or []) for e in log}
        return (f"zero cards kept at research in gen {gen - 1} and "
                f"again in gen {gen}; cards kept by generation: "
                + ", ".join(f"g{g}:{counts[g]}" for g in sorted(counts))
                + f", g{gen}:0")

    # ── corporation & milestones ─────────────────────────────

    def research(self, player: str, kept: int) -> str:
        """Opponent research phase: they kept N cards (−3 MC each).

        Own keeps go through dealt() (full card knowledge). At the table the
        keep COUNT is public — log it every research phase for every
        opponent, or their MC simulation drifts by 3 per card.
        """
        name = self.resolve_player(player)
        if self._is_me(name):
            raise EventError("Use dealt() for your own research (cards + kept)")
        game = self.store.load_game()
        opp = game["opponents"][name]
        cost = CARD_KEEP_COST * kept
        opp["resources"]["mc"] = max(0, opp["resources"]["mc"] - cost)
        return self._commit(
            game, f"{name}: research kept {kept} cards (−{cost} MC → "
                  f"{opp['resources']['mc']})")

    def corp(self, player: str, corporation: str, mc: int) -> str:
        name = self.resolve_player(player)
        game = self.store.load_game()
        pool = game["me"] if self._is_me(name) else game["opponents"][name]
        pool["corporation"] = corporation
        pool["resources"]["mc"] += mc
        bal = pool["resources"]["mc"]
        parts = [f"{name} is {corporation} (start {mc} MC → {bal})"]
        # starting stock/production come from db.json, not manual events
        info = self.card(corporation)
        beh = (info or {}).get("behavior") or {}
        res_key = {"steel": "steel", "titanium": "titanium", "plants": "plants",
                   "heat": "heat", "energy": "energy", "megacredits": None,
                   "mc": None}
        for k, v in (beh.get("stock") or {}).items():
            rk = res_key.get(k, k)
            if rk and rk in pool["resources"] and isinstance(v, int):
                pool["resources"][rk] += v
                parts.append(f"+{v} {rk}")
        for k, v in (beh.get("production") or {}).items():
            rk = res_key.get(k, k)
            if rk and rk in pool["production"] and isinstance(v, int):
                pool["production"][rk] += v
                parts.append(f"+{v} {rk} prod")
        return self._commit(game, ", ".join(parts))

    _board_cache = None

    @classmethod
    def _board(cls) -> dict:
        if cls._board_cache is None:
            path = Path(__file__).resolve().parent.parent / "board.json"
            spaces = json.loads(path.read_text())["spaces"]
            cls._board_cache = {sp["id"]: sp for sp in spaces}
        return cls._board_cache

    @staticmethod
    def _oceans_on_board(game: dict) -> int:
        """Ocean tiles actually down — game["board"], never the derived
        counters (the app's own canAddOcean counts board spaces)."""
        return sum(1 for t in (game.get("board") or {}).values()
                   if t.get("tile") == "ocean")

    def place(self, player: str, tile: str, space_id: str,
              card: str | None = None) -> str:
        """Record a tile on a named hex; grant placement bonus + ocean adjacency.

        Position only — tile *counters* move via play/convert/standard events.

        `card` names the card that produced a SPECIAL tile. It is what makes
        an ocean-reserved hex legal: some special tiles are placed "ON AN AREA
        RESERVED FOR OCEAN" (Mohole Area). That exemption used to be a
        hardcoded tile name the CLI had no way to pass, so the card could not
        be recorded at all; the rule now reads `behavior.tile.on` from
        db.json and stores the specific tile type.
        """
        name = self.resolve_player(player)
        spaces = self._board()
        space_id = grid_to_space(space_id, spaces)   # 'C4' or '17'
        sp = spaces.get(str(space_id))
        if sp is None or sp.get("offMap"):
            raise EventError(f"Unknown board space {space_id!r}")
        game = self.store.load_game()
        occupied = game.setdefault("board", {})
        held = occupied.get(str(space_id))
        # A LAND CLAIM is a reservation, not a tile: it blocks everyone
        # else, and its owner builds straight over it (the app's own rule).
        if held and not (held.get("tile") == LAND_CLAIM
                         and held.get("player") == name):
            raise EventError(
                f"Space {space_id} already holds {held['player']}'s "
                f"{held['tile']}")
        # cards whose tile goes ON AN AREA RESERVED FOR OCEAN (db behavior
        # tile.on == "ocean"): Mohole Area in base/CE
        card_beh = (self.card(card) or {}).get("behavior") or {} if card else {}
        if tile == "ocean" and self._oceans_on_board(game) >= \
                PARAM_SCALE["oceans"]["max"]:
            # The supply of ocean tiles is the board count (the app's
            # canAddOcean): with all of them down, a card's ocean was
            # SUPPRESSED at play time (no placement obligation, no TR, no
            # bonus) — a place step here would simulate a hex bonus and
            # adjacency MC the app never pays.
            raise EventError(
                f"oceans maxed: {PARAM_SCALE['oceans']['max']} ocean tiles "
                "are already on the board — no ocean to place (a card's "
                "ocean is suppressed at the cap: no tile, no TR, no bonus)")
        if tile == "ocean" and not sp["oceanReserved"]:
            # …and the mirror image: a card whose ocean goes ON AN AREA NOT
            # RESERVED FOR OCEAN (db behavior ocean.on == "land"). The rule
            # was read from behavior.tile / behavior.greenery only, so such
            # an ocean was refused outright — one dropped off the board in a
            # replayed 5-player game and took the ocean track (and a TR)
            # with it.
            grant = card_beh.get("ocean")
            if not (isinstance(grant, dict) and grant.get("on") == "land"):
                raise EventError(f"Space {space_id} is not ocean-reserved")
        # Two encodings for the same idea: a SPECIAL tile carries
        # behavior.tile.on, a greenery carries behavior.greenery.on
        # (Protected Valley). Reading only the first still rejected
        # Protected Valley on an ocean area.
        card_tile = card_beh.get("tile")
        if not isinstance(card_tile, dict) and isinstance(
                card_beh.get("greenery"), dict):
            card_tile = card_beh["greenery"]
        if isinstance(card_tile, dict):
            if card_tile.get("type"):
                tile = str(card_tile["type"])
        # A caller may also name the specific tile directly (library path,
        # predates the CLI `--card` route) — both stay supported.
        ocean_space_specials = {"moholearea"}
        on_ocean = (tile in ocean_space_specials
                    or (isinstance(card_tile, dict)
                        and card_tile.get("on") == "ocean"))
        if tile != "ocean" and sp["oceanReserved"] and not on_ocean:
            raise EventError(
                f"Space {space_id} is ocean-reserved"
                + ("" if card else " (pass card=… if a special tile from a "
                                  "card is placed on an ocean area)"))
        # Cards that place a greenery on an ocean area do so "disregarding
        # normal placement restrictions" — the adjacent-to-your-own-tile
        # rule is waived too, not just the ocean reservation.
        if tile == "greenery" and not on_ocean:
            legal = {m["id"] for m in self.legal_spaces("greenery", name)}
            if str(space_id) not in legal:
                raise EventError(
                    f"Greenery must be adjacent to a tile {name} owns "
                    f"(oceans are owned by no one); legal: {sorted(legal)}")
        occupied[str(space_id)] = {"tile": tile, "player": name}
        me = self._is_me(name)
        # Print OUR grid label and, when it differs, the app's (row I → J)
        grid, app = space_to_grid(space_id, spaces), app_label(space_id, spaces)
        parts = [f"{name} placed {tile} on {space_id} [{grid}"
                 + (f", app {app}" if app != grid else "") + "]"
                 + (f" ({sp['name']})" if sp.get("name") else "")]
        if tile == LAND_CLAIM:
            # a reservation, not a tile: no placement bonus, no adjacency,
            # no counter — only the block on every other player
            return self._commit(
                game, parts[0] + " (marker only — no bonus, scores nothing; "
                                 "only its owner may build here)")
        # Placement gains are PUBLIC and deterministic — a player at
        # the table sees exactly which bonus an opponent picked up. They are
        # granted to whoever placed, not only to me; skipping them drifted
        # every opponent's mat on every build.
        pool = game["me"] if me else game["opponents"][name]
        res = pool["resources"]
        bonus_res = {"steel": "steel", "titanium": "titanium",
                     "plant": "plants", "heat": "heat"}
        gains = {}
        for b in sp.get("bonus", []):
            gains[b] = gains.get(b, 0) + 1
        for b, n in gains.items():
            if b in bonus_res:
                res[bonus_res[b]] += n
                parts.append(f"+{n} {bonus_res[b]}")
            elif b == "mc":
                res["mc"] += n
                parts.append(f"+{n} MC")
            else:
                parts.append(f"→ TABLE: +{n} {b} (draw/track manually)"
                             if me else f"+{n} {b} (drawn, hidden)")
        adj_oceans = sum(
            1 for a in sp.get("adjacent", [])
            if occupied.get(a, {}).get("tile") == "ocean")
        if adj_oceans:
            res["mc"] += 2 * adj_oceans
            parts.append(f"+{2*adj_oceans} MC ({adj_oceans} adjacent ocean)")
        ore_prod = self._my_corp_rule(game, name, "oreTileSteelProduction", 0)
        if ore_prod and any(b in ("steel", "titanium")
                            for b in sp.get("bonus", [])):
            pool["production"]["steel"] += ore_prod
            parts.append(f"{self._corp_of(game, name)}: "
                         f"+{ore_prod} steel production")
        return self._commit(game, ", ".join(parts))

    def unplace(self, space_id: str, player: str | None = None) -> str:
        """Remove a wrongly recorded tile (bonuses reversed via res/tr events).

        `player` is optional (older callers pass only the space); when
        given it must own the tile — a typo'd hex is caught here instead of
        deleting somebody else's tile."""
        game = self.store.load_game()
        occupied = game.get("board", {})
        space_id = grid_to_space(space_id, self._board())
        if str(space_id) not in occupied:
            raise EventError(f"No tile recorded on space {space_id}")
        held = occupied[str(space_id)]
        if player is not None:
            name = self.resolve_player(player)
            if held["player"] != name:
                raise EventError(
                    f"Space {space_id} ({space_to_grid(space_id)}) holds "
                    f"{held['player']}'s {held['tile']}, not {name}'s — "
                    "check the hex before unplacing")
        gone = occupied.pop(str(space_id))
        return self._commit(
            game, f"UNPLACED {gone['player']}'s {gone['tile']} from {space_id} "
                  f"({space_to_grid(space_id)}) "
                  "(correction; reverse bonuses separately)")

    def unplay(self, player: str, card: str) -> str:
        """Remove a wrongly recorded card play (effects reversed separately)."""
        name = self.resolve_player(player)
        game = self.store.load_game()
        board = game["me"] if self._is_me(name) else game["opponents"][name]
        played = board["playedCards"]
        hit = next((c for c in played if c["name"].lower() == card.lower()), None)
        if hit is None:
            raise EventError(f"{name} has no played card {card!r}")
        played.remove(hit)
        board.get("actionsThisGen", {}).pop(hit["name"], None)
        # the count belongs to the play that is being erased
        board.get("cardResources", {}).pop(hit["name"], None)
        return self._commit(
            game, f"UNPLAYED {hit['name']} for {name} "
                  "(correction; reverse effects separately)")

    def legal_spaces(self, tile: str, player: str | None = None) -> list[dict]:
        """Enumerate legal hexes for a tile type with exact bonuses/adjacency.

        Greenery rule (official): must be adjacent to a tile the player OWNS
        when any such hex is free — and placed oceans are owned by NO ONE.
        Pass player to apply that filter (defaults to me for greenery).
        """
        game = self.store.load_game()
        occupied = game.get("board", {})
        if tile == "ocean" and self._oceans_on_board(game) >= \
                PARAM_SCALE["oceans"]["max"]:
            return []          # every ocean tile is down: nothing to place
        if tile == "greenery" and player is None:
            player = game["me"]["name"]
        # a LAND CLAIM reserves a hex FOR ITS OWNER: it blocks everybody
        # else and stays legal for the player who placed it
        claimant = self.resolve_player(player) if player else None
        out = []
        for sid, sp in self._board().items():
            held = occupied.get(sid)
            if sp.get("offMap") or (held is not None
                                    and not (held.get("tile") == LAND_CLAIM
                                             and held.get("player") == claimant)):
                continue
            if (tile == "ocean") != bool(sp["oceanReserved"]):
                continue
            adj = sp.get("adjacent", [])
            out.append({
                "id": sid,
                "name": sp.get("name"),
                "bonus": sp.get("bonus", []),
                "adjacentOceans": sum(
                    1 for a in adj if occupied.get(a, {}).get("tile") == "ocean"),
                "adjacentTiles": {a: occupied[a] for a in adj if a in occupied},
            })
        if tile == "greenery" and player:
            name = self.resolve_player(player)
            own = {sid for sid, t in occupied.items()
                   if t.get("player") == name
                   and t.get("tile") not in NON_SCORING_TILES}
            if own:
                spaces = self._board()
                constrained = [
                    m for m in out
                    if any(a in own
                           for a in spaces[m["id"]].get("adjacent", []))]
                if constrained:
                    return constrained
        return out

    def set_generation(self, n: int) -> str:
        """Correction: force the generation counter (e.g. a premature
        produce() ran before all seats' real turns were logged). Never
        used for normal turnover — that's produce()'s job."""
        if n < 1:
            raise EventError(f"generation must be >= 1, got {n}")
        game = self.store.load_game()
        old = game["generation"]
        game["generation"] = n
        return self._commit(
            game, f"CORRECTION: generation {old} → {n} (forced)")

    def set_first_player(self, player: str) -> str:
        """Override the computed first player (table exception); logged."""
        name = self.resolve_player(player)
        game = self.store.load_game()
        old = game["firstPlayer"]
        game["firstPlayer"] = name
        return self._commit(
            game, f"First player exception: {old} → {name} (table override)")

    def add_alias(self, player: str, alias: str) -> str:
        """Add a player alias; reject collisions; log it (iron rule 3)."""
        name = self.resolve_player(player)
        want = alias.strip().lower()
        for p in self.setup["players"]:
            taken = [p["name"], p["color"], *p.get("aliases", [])]
            if want in (t.lower() for t in taken) and p["name"] != name:
                raise EventError(
                    f"Alias {alias!r} collides with player {p['name']} "
                    f"({'name/color/alias'})")
        for p in self.setup["players"]:
            if p["name"] == name:
                p.setdefault("aliases", []).append(alias)
        self.store._write_json(self.store.setup_path, self.setup)
        game = self.store.load_game()
        self.store.log(f"G{game['generation']}", f"Alias added: {name} ← {alias!r}")
        return f"{name} ← alias {alias!r}"

    def _milestone_eligibility(self, game: dict, name: str,
                               milestone: str) -> str:
        """Check the claim requirement from state. My data is full-fidelity →
        hard block when ineligible. Opponent data is event-driven and may
        have gaps → return a ⚠ warning string instead of blocking."""
        me = self._is_me(name)
        pool = game["me"] if me else game["opponents"][name]
        if milestone == "Terraformer":
            have, need, what = pool["tr"], 35, "TR"
        elif milestone == "Mayor":
            # THE tile counter (board first, counter as a floor)
            have, need, what = tile_counts(game, name, pool)["cities"], 3, "cities"
        elif milestone == "Gardener":
            have = tile_counts(game, name, pool)["greeneries"]
            need, what = 3, "greeneries"
        elif milestone == "Builder":
            # THE tag counter: events don't persist, the corporation's own
            # tags do (Mining Guild carries two building tags)
            have = persisting_tags(game, name, pool=pool).get("building", 0)
            need, what = 8, "building tags"
        elif milestone == "Planner":
            if not me:
                return ""            # opponent hand size unknown — can't judge
            have, need, what = len(pool["hand"]), 16, "cards in hand"
        else:
            return ""
        if have >= need:
            return ""
        detail = f"{milestone} needs {need} {what}, {name} has {have} tracked"
        if me:
            raise EventError(detail)
        return f"⚠ {detail} — recording anyway (opponent tracking may have gaps)"

    def award(self, player: str, award: str) -> str:
        canon = {a.lower(): a for a in AWARDS}.get(award.strip().lower())
        if canon is None:
            raise EventError(f"Unknown award {award!r}; valid: {AWARDS}")
        name = self.resolve_player(player)
        game = self.store.load_game()
        funded = game.setdefault("awardsFunded", {})
        if canon in funded:
            raise EventError(f"{canon} already funded by {funded[canon]}")
        if len(funded) >= len(AWARD_COSTS):
            raise EventError(f"All {len(AWARD_COSTS)} awards funded: {funded}")
        cost = AWARD_COSTS[len(funded)]
        if self._is_me(name):
            res = game["me"]["resources"]
            if res["mc"] < cost:
                raise EventError(f"Award #{len(funded)+1} costs {cost} MC, "
                                 f"have {res['mc']}")
            res["mc"] -= cost
        else:
            opp = game["opponents"][name]
            opp["resources"]["mc"] = max(0, opp["resources"]["mc"] - cost)
        funded[canon] = name
        return self._commit(game, f"{name} funded award {canon} (−{cost} MC)")

    def milestone(self, player: str, milestone: str) -> str:
        canon = {m.lower(): m for m in MILESTONES}.get(milestone.strip().lower())
        if canon is None:
            raise EventError(f"Unknown milestone {milestone!r}; valid: {MILESTONES}")
        milestone = canon
        name = self.resolve_player(player)
        game = self.store.load_game()
        claimed = game["milestonesClaimed"]
        if milestone in claimed:
            raise EventError(f"{milestone} already claimed by {claimed[milestone]}")
        if len(claimed) >= MAX_MILESTONES:
            raise EventError(f"All {MAX_MILESTONES} milestones claimed: {claimed}")
        warn = self._milestone_eligibility(game, name, milestone)
        if self._is_me(name):
            res = game["me"]["resources"]
            if res["mc"] < MILESTONE_COST:
                raise EventError(f"Milestone costs {MILESTONE_COST} MC, have {res['mc']}")
            res["mc"] -= MILESTONE_COST
            game["me"]["milestones"].append(milestone)
        else:
            opp = game["opponents"][name]
            opp["resources"]["mc"] = max(0, opp["resources"]["mc"] - MILESTONE_COST)
        claimed[milestone] = name
        msg = f"{name} claimed milestone {milestone} (−{MILESTONE_COST} MC)"
        if warn:
            msg += f" {warn}"
        return self._commit(game, msg)


# Standard projects: name → (cost, description)

    # ── the names docs/PLAYBOOK.md documents ─────────────────────────
    # A plan step's `events` name ENGINE methods, but the playbook (and the
    # advisor's memory of it) carries the `apply.py` CLI verbs. Three of
    # them differed, and each one aborted a LIVE set_plan with an
    # AttributeError mid-turn in the 4p WGT game. The engine answers to
    # both spellings now; the CLI stays the single documented surface.
    def freecity(self, player: str) -> str:
        """`apply.py freecity` — alias of free_action_city (still call
        place() separately for the hex, exactly as the CLI does)."""
        return self.free_action_city(player)

    def sell(self, cards: list[str] | None = None,
             player: str | None = None) -> str:
        """`apply.py sell` — the app's Sell patents, 1 MC per card."""
        name = player or self.store.load_game()["me"]["name"]
        return self.standard(name, "sell_patents", cards=list(cards or []))

    def standard(self, player: str, project: str, cards: list[str] | None = None,
                 heat: int | None = None) -> str:
        """heat: heat spent as MC (standard projects take MC/heat only —
        never steel/titanium). execute.py's payment splitter sends exactly
        this to the app (asteroid 14 = mc 0 + heat 14), so the tracker has
        to model it or it refuses the event it just transmitted. Same rule
        as play(): only a corporation whose rule spends heat as MC may pass
        it.

        `heat=None` (the default, and what every event without an explicit
        payment carries) = ask THE payment model: MC first, the shortfall
        out of heat when — and only when — the corporation's rule allows
        it. Before this the default was a hard 0, so the tracker refused
        the standard project the app had just accepted ("asteroid costs 14
        MC, have 12" with the heat pile untouched). The rule stays in
        `split_payment`; nothing here names a corporation."""
        name = self.resolve_player(player)
        if project not in STANDARD_PROJECTS:
            raise EventError(
                f"Unknown standard project {project!r}: {list(STANDARD_PROJECTS)}"
            )
        game = self.store.load_game()
        me = self._is_me(name)
        base_cost = STANDARD_PROJECTS[project]
        # ThorGate's Power Plant −3 (any player); CrediCor keys on base
        disc, disc_notes = self._standard_discount(game, name, project)
        cost = max(0, base_cost - disc)
        parts = [f"{name}: standard project {project}"]

        # pay — THE payment model (split_payment), the same one the menu
        # asks for affordability and execute.py builds the payload with
        if heat is not None:
            if heat < 0:
                raise EventError("heat payment cannot be negative")
            if heat and not self._my_corp_rule(game, name, "heatAsMC"):
                raise EventError("Only Helion can spend heat as MC")
        pay = split_payment(game, name, cost, heat=heat)
        # a caller may over-declare heat; nobody pays more than the price
        mc_due, heat_due = pay["mc"], min(pay["heat"], cost)
        if me:
            res = game["me"]["resources"]
            if heat_due > res["heat"]:
                raise EventError(f"Not enough heat (have {res['heat']})")
            if res["mc"] < mc_due:
                raise EventError(
                    f"{project} costs {cost} MC"
                    + (f" ({heat_due} paid with heat, {mc_due} MC due)"
                       if heat_due else "")
                    + f", have {res['mc']}")
            res["mc"] -= mc_due
            res["heat"] -= heat_due
        else:
            # opponent stocks are estimates — floor instead of raising
            ores = game["opponents"][name]["resources"]
            ores["mc"] = max(0, ores["mc"] - mc_due)
            if heat_due:
                ores["heat"] = max(0, ores["heat"] - heat_due)
        if cost or disc:
            paid = f"−{mc_due} MC" + (f" + {heat_due} heat" if heat_due else "")
            parts.append(paid + (f" (base {base_cost}, "
                                 + ", ".join(disc_notes) + ")"
                                 if disc else ""))
        # rebates come AFTER the gross price was checked and paid (above):
        # the corporation rule, then every tableau card carrying
        # `standardProjectRebate` — the vendor fires onStandardProject on
        # every card of the tableau, corporation included, so they stack
        self._credicor_rebate(game, name, base_cost, parts)
        self._card_rebates(game, name, project, parts)

        # effect
        board = game["me"] if me else game["opponents"][name]
        if project == "sell_patents":
            if not me:
                raise EventError("Opponent card sales: log MC estimate directly")
            cards = cards or []
            for c in cards:
                if c not in game["me"]["hand"]:
                    raise EventError(f"{c!r} not in hand")
                game["me"]["hand"].remove(c)
            game["me"]["resources"]["mc"] += len(cards)
            parts.append(f"sold {cards} → +{len(cards)} MC")
        elif project == "power_plant":
            prod = game["me"]["production"] if me else game["opponents"][name]["production"]
            prod["energy"] += 1
            parts.append("+1 energy production")
        elif project == "asteroid":
            raised, desc = self._bump_param(game, "temperature", actor=name)
            parts.append(desc)
            if raised:
                self._tr_pool(game, name)["tr"] += 1
        elif project == "aquifer":
            raised, desc = self._bump_param(game, "oceans")
            parts.append(desc)
            if raised:
                self._tr_pool(game, name)["tr"] += 1
        elif project == "greenery":
            board["tiles"]["greeneries"] += 1
            raised, desc = self._bump_param(game, "oxygen", actor=name)
            parts.append("greenery tile, " + desc)
            if raised:
                self._tr_pool(game, name)["tr"] += 1
        elif project == "city":
            board["tiles"]["cities"] += 1
            prod = game["me"]["production"] if me else game["opponents"][name]["production"]
            prod["mc"] += 1
            parts.append("city tile, +1 MC production")
            self._on_city_placed(game, name, parts)
        return self._commit(game, ", ".join(parts))

    # ── production phase / generation turnover ───────────────

    def wgt(self, param: str, space_id: str | None = None) -> str:
        """World Government Terraforming step (verified vs the app's
        Game.ts): after all passes, the generation's FIRST player raises one
        parameter one step in the SOLAR phase — NO TR, NO -24/-20 heat bonus;
        a WGT ocean gets NO placement bonus and NO ocean-adjacency MC, but
        ocean-trigger cards DO fire (Arctic Algae, OCEAN_TRIGGERS — the
        app pays +2 plants on every WGT ocean). The 8% O2
        -> temperature bump and the 0 C bonus ocean
        still chain (equally bonus-free). Once per generation, plus the
        pending bonus ocean."""
        if not wgt_enabled(self.setup):
            raise EventError("WGT is not enabled in setup.json (expansions "
                             "'wgt' or a house rule) — add it before logging")
        if param not in PARAM_SCALE:
            raise EventError(f"Unknown global parameter: {param!r}")
        game = self.store.load_game()
        gen = game["generation"]
        chooser = game["firstPlayer"]
        pending = bool(game.get("wgtBonusOceanPending"))
        if game.get("wgtDoneGen") == gen and not (pending and param == "oceans"):
            raise EventError(
                f"WGT step already logged for generation {gen}"
                + (" — only the pending 0°C bonus ocean may follow "
                   "(wgt oceans --hex H)" if pending else ""))
        parts = [f"WGT ({chooser}, no TR/bonuses)"]

        def bump_temp() -> None:
            cur = game["globals"]["temperature"]
            if cur >= PARAM_SCALE["temperature"]["max"]:
                parts.append("temperature already maxed")
                return
            new = cur + PARAM_SCALE["temperature"]["step"]
            game["globals"]["temperature"] = new
            parts.append(f"temperature {cur}°C → {new}°C")
            if new in self.TEMP_HEAT_BONUS:
                parts.append("(-24/-20 heat-prod bonus NOT granted: solar phase)")
            if new == self.TEMP_OCEAN_BONUS:
                game["wgtBonusOceanPending"] = True
                parts.append(f"BONUS OCEAN from 0°C: {chooser} places it now, "
                             "no bonuses — log `apply.py wgt oceans --hex H`")

        if param == "temperature":
            if game["globals"]["temperature"] >= PARAM_SCALE["temperature"]["max"]:
                raise EventError("temperature already maxed")
            bump_temp()
        elif param == "oxygen":
            cur = game["globals"]["oxygen"]
            if cur >= PARAM_SCALE["oxygen"]["max"]:
                raise EventError("oxygen already maxed")
            new = cur + PARAM_SCALE["oxygen"]["step"]
            game["globals"]["oxygen"] = new
            parts.append(f"oxygen {cur}% → {new}%")
            if new == self.OXYGEN_TEMP_BONUS:
                parts.append("8% bonus: temperature +1 step (no TR)")
                bump_temp()
        else:  # oceans
            if game["globals"]["oceans"] >= PARAM_SCALE["oceans"]["max"]:
                raise EventError("oceans already maxed")
            if space_id is None:
                raise EventError("WGT ocean needs its hex: wgt oceans --hex C4")
            spaces = self._board()
            sid = str(grid_to_space(space_id, spaces))
            sp = spaces.get(sid)
            if sp is None or sp.get("offMap"):
                raise EventError(f"Unknown board space {space_id!r}")
            if not sp["oceanReserved"]:
                raise EventError(f"Space {sid} is not ocean-reserved")
            occupied = game.setdefault("board", {})
            if sid in occupied:
                o = occupied[sid]
                raise EventError(f"Space {sid} already holds {o['player']}'s {o['tile']}")
            occupied[sid] = {"tile": "ocean", "player": chooser}
            game["globals"]["oceans"] += 1
            parts.append(f"ocean placed on {sid}"
                         + (f" ({sp['name']})" if sp.get("name") else "")
                         + f" → oceans {game['globals']['oceans']}/9; placement "
                           "bonus + adjacency MC NOT granted (solar phase)")
            # the app DOES fire "when anyone places an ocean" cards
            # (Arctic Algae +2 plants after every WGT ocean)
            parts.extend(self._on_ocean_placed(game))
            if pending:
                game["wgtBonusOceanPending"] = False
        if not (pending and param == "oceans"):
            game["wgtDoneGen"] = gen
        return self._commit(game, ", ".join(parts))

    def produce(self, skip_wgt: str | None = None) -> str:
        game = self.store.load_game()
        me = game["me"]
        # WGT: the free solar-phase step precedes production. Refuse
        # to close the generation without it unless Mars is terraformed or the
        # caller documents why (produce.py --skip-wgt "<reason>").
        if wgt_enabled(self.setup) and not skip_wgt:
            maxed = all(game["globals"][k] >= PARAM_SCALE[k]["max"]
                        for k in PARAM_SCALE)
            if game.get("wgtBonusOceanPending"):
                raise EventError(
                    "WGT 0°C bonus ocean still unplaced — log `apply.py wgt "
                    "oceans --hex H` before produce.py")
            if not maxed and game.get("wgtDoneGen") != game["generation"]:
                raise EventError(
                    f"WGT step not logged for generation {game['generation']} "
                    f"({game['firstPlayer']} chooses) — `apply.py wgt "
                    "<temperature|oxygen|oceans> [--hex H]` first, or "
                    "`produce.py --skip-wgt \"<reason>\"`")
        elif skip_wgt:
            self.store.log(f"G{game['generation']}", f"WGT step skipped: {skip_wgt}")
        res, prod = me["resources"], me["production"]

        # 1. energy → heat, 2. income
        leftover_energy = res["energy"]
        res["heat"] += leftover_energy + prod["heat"]
        res["energy"] = prod["energy"]
        mc_income = me["tr"] + prod["mc"]
        res["mc"] += mc_income
        for r in ("steel", "titanium", "plants"):
            res[r] += prod[r]

        # 3. opponents: full simulated income (estimated until next mat snapshot)
        for opp in game["opponents"].values():
            ores, oprod = opp["resources"], opp["production"]
            ores["heat"] += ores["energy"] + oprod["heat"]
            ores["energy"] = oprod["energy"]
            ores["mc"] += opp["tr"] + oprod["mc"]
            for r in ("steel", "titanium", "plants"):
                ores[r] += oprod[r]
            opp["estimated"] = True

        # 4. ledger reset (the generation stamp goes with the use),
        # 5. generation & first player advance
        for entry in me["actionsThisGen"].values():
            entry["used"] = False
            entry.pop("gen", None)
        old_gen = game["generation"]
        game["generation"] = old_gen + 1
        # globals as the generation closes (= start of the next) feed
        # clock.estimate's observed fill rate (stalling tables need it).
        game.setdefault("history", []).append(
            {"generation": old_gen, **{k: game["globals"][k] for k in GLOBAL_START}})
        seating = self.setup["seatingOrder"]
        if game["firstPlayer"] not in seating:
            raise EventError(
                f"firstPlayer {game['firstPlayer']!r} not in seatingOrder "
                f"{seating} — fix via apply.py note + extend the script, "
                "never hand-edit state")
        i = seating.index(game["firstPlayer"])
        game["firstPlayer"] = seating[(i + 1) % len(seating)]

        msg = (
            f"Production (end of gen {old_gen}): {me['name']} "
            f"+{mc_income} MC (TR {me['tr']} + prod {prod['mc']}), "
            f"energy→heat ({leftover_energy}+{prod['heat']} heat), "
            f"opponents simulated. → Generation {game['generation']}, "
            f"first player {game['firstPlayer']}"
        )
        self.store.save_game(game)
        self.store.log(f"G{old_gen}", msg)
        self._log_standings(game)
        return msg

    def _log_standings(self, game: dict) -> None:
        """Every turnover path logs the standings line — the CLI
        (produce.py), the LISTENER (replay_applog calls produce directly)
        and the e2e alike. shape.py's VP slope reads its history from
        state/log.md, and in app modes the listener owns turnover: with
        the line living in produce.py only, a whole 12-generation game
        logged none and vpSlope stayed null (fix-plan item 4a).
        Scoring must never break a turnover, so a failure is silent."""
        try:
            import score
            self.store.log(f"G{game['generation']}",
                           score.standings_line(game))
        except Exception:
            pass

    def snap(self, player: str, field: str, value: int) -> str:
        """Public-anchor absorption: set an OBSERVED absolute
        value on an opponent quantity (tr, any resource name, or
        'card:<Card Name>' for the resources sitting ON a card — animals,
        microbes, fighters, science: they are VP at scoring time). Logs
        the unexplained delta instead of erroring — the physical table's
        TR markers/boards/cards are truth; the simulation follows. Never
        raises on inconsistency."""
        name = self.resolve_player(player)
        if self._is_me(name):
            raise EventError("snap is for opponents; your own state uses res/tr/sync")
        if field.startswith("card:"):
            card = field[len("card:"):].strip()
            if not card:
                raise EventError("snap card:<Card Name> needs the card name")
            return self.sync_card_resources(name, {card: value})
        game = self.store.load_game()
        opp = game["opponents"][name]
        prov = opp.setdefault("provenance", {})
        if field == "tr":
            old, opp["tr"] = opp["tr"], value
        elif field in RESOURCES:
            old = opp["resources"][field]
            opp["resources"][field] = value
        else:
            raise EventError(f"snap: unknown field {field!r} (tr or resource)")
        prov[field if field == "tr" else "resources"] = "observed"
        prov["asOfGen"] = game["generation"]
        delta = value - old
        if delta == 0:
            return self._commit(game, f"{name}: {field} {value} confirmed (observed)")
        return self._commit(
            game, f"{name}: {field} {old} → {value} ({delta:+} unexplained — "
                  "absorbed; observed value wins)")

    def sync_own(self, player: str = "me", tr=None, mc=None, steel=None,
                 titanium=None, plants=None, energy=None, heat=None,
                 prod_mc=None, prod_steel=None, prod_titanium=None,
                 prod_plants=None, prod_energy=None, prod_heat=None) -> str:
        """Own-panel sync (`apply.py sync me --mc N …`): set my values
        from a panel photo/screenshot, each delta logged as a correction.
        Opponents are refused — their verb is observe."""
        if player.strip().lower() != "me":
            name = self.resolve_player(player)
            if not self._is_me(name):
                raise EventError(
                    f"sync is for your own panel; use `observe {name} …` "
                    "for opponents")
        game = self.store.load_game()
        me = game["me"]
        changes, confirmed = [], []

        def adopt(pool, key, observed, label):
            if observed is None:
                return
            old = pool[key]
            if observed == old:
                confirmed.append(f"{label} {old}")
            else:
                changes.append(f"{label} {old} → {observed} ({observed - old:+})")
                pool[key] = observed

        adopt(me, "tr", tr, "TR")
        for k, v in {"mc": mc, "steel": steel, "titanium": titanium,
                     "plants": plants, "energy": energy, "heat": heat}.items():
            adopt(me["resources"], k, v, k.upper())
        for k, v in {"mc": prod_mc, "steel": prod_steel, "titanium": prod_titanium,
                     "plants": prod_plants, "energy": prod_energy,
                     "heat": prod_heat}.items():
            adopt(me["production"], k, v, f"{k.upper()} prod")
        if not changes and not confirmed:
            raise EventError("sync me: give at least one --mc/--steel/…/--tr value")
        msg = f"Own panel sync (gen {game['generation']}): "
        msg += ("CORRECTION " + "; ".join(changes)) if changes else "no drift"
        if confirmed:
            msg += " — confirmed: " + ", ".join(confirmed)
        return self._commit(game, msg)

    def observe(self,  player, tr=None, mc=None, steel=None, titanium=None,
                        plants=None, energy=None, heat=None, prod_mc=None,
                        prod_steel=None, prod_titanium=None, prod_plants=None,
                        prod_energy=None, prod_heat=None):
        """Between-generation mat snapshot: adopt observed values (reconcile).

        Reports drift vs the simulated balances, then observed wins. Partial
        observations are fine — unseen fields keep their simulated values.
        """
        name = self.resolve_player(player)
        if self._is_me(name):
            raise EventError("observe is for opponents; your own state uses res/prod/sync")
        game = self.store.load_game()
        opp = game["opponents"][name]
        drifts, parts = [], []

        def adopt(pool, key, observed, label):
            if observed is None:
                return
            old = pool[key]
            if observed != old:
                sign = "+" if observed - old >= 0 else ""
                drifts.append(f"{label} {sign}{observed - old} (sim {old} → obs {observed})")
            pool[key] = observed

        opp.setdefault("provenance", {})["resources"] = "observed"
        opp["provenance"]["asOfGen"] = game["generation"]
        if tr is not None:
            adopt(opp, "tr", tr, "TR")
        obs_res = {"mc": mc, "steel": steel, "titanium": titanium,
                   "plants": plants, "energy": energy, "heat": heat}
        for k, v in obs_res.items():
            adopt(opp["resources"], k, v, k.upper())
        obs_prod = {"mc": prod_mc, "steel": prod_steel, "titanium": prod_titanium,
                    "plants": prod_plants, "energy": prod_energy, "heat": prod_heat}
        for k, v in obs_prod.items():
            adopt(opp["production"], k, v, f"{k.upper()} prod")

        opp["estimated"] = False
        opp["lastObservedGen"] = game["generation"]
        parts.append(f"Observed {name} mat (gen {game['generation']})")
        parts.append("drift: " + "; ".join(drifts) if drifts else "matches simulation")
        return self._commit(game, ", ".join(parts))

    def observe_play(self, player: str, card: str,
                     allow_me: bool = False) -> str:
        """Tableau diff (verify.py): a card seen in the public app tableau.
        Bookkeeping ONLY — playedCards (+ tagCounts for an opponent, + the
        blue-action ledger for me), one log line. No cost/production/global
        side effects: the numeric sync that follows adopts those from the
        app (applying them here would double-count, and opponent corp
        discounts are unknown).

        MY OWN cards need allow_me=True: a play of mine normally goes
        through play(), and silently skipping its cost would be a drift
        source. verify.py's own-tableau sync is the one legitimate caller —
        it runs right after adopting the app's figures wholesale."""
        name = self.resolve_player(player)
        me = self._is_me(name)
        if me and not allow_me:
            raise EventError(
                "observe_play is for opponents; your own plays go through "
                "play() — pass allow_me=True only for the app-tableau sync "
                "(bookkeeping, no cost, no effects)")
        info = self.card(card)
        if info is not None:
            card = info["name"]
        game = self.store.load_game()
        pool = game["me"] if me else game["opponents"][name]
        if any(e["name"] == card for e in pool["playedCards"]):
            raise EventError(f"{name} already has {card} in playedCards")
        pool["playedCards"].append({"name": card, "gen": game["generation"]})
        if me:
            if info and info.get("type") == "active" and info.get("action"):
                entry = {"used": False}
                entry.update(self._action_costs(info))
                pool["actionsThisGen"].setdefault(card, entry)
        else:
            for t in (info or {}).get("tags", []):
                pool["tagCounts"][t] = pool["tagCounts"].get(t, 0) + 1
        return self._commit(game, f"{name} played {card} [observed from app]")

    def sync_card_resources(self, player: str, counts: dict) -> str:
        """Adopt the observed per-card accumulators (animals, microbes,
        science resources, floaters, fighters) for one player. ABSOLUTE
        values, not deltas — the observation is the record. They are VP at
        scoring time, so every change is logged. An explicit 0 is KEPT
        (an observed zero is knowledge); only a count that was never
        observed stays absent, and score.py bounds it instead of
        pretending it is 0."""
        name = self.resolve_player(player)
        game = self.store.load_game()
        pool = self._tr_pool(game, name)
        cur = pool.setdefault("cardResources", {})
        changed = []
        for card, n in (counts or {}).items():
            if not isinstance(n, int) or n < 0:
                raise EventError(
                    f"{card}: card-resource count must be a non-negative "
                    f"integer, got {n!r}")
            info = self.card(card)
            canon = info["name"] if info else card
            old = cur.get(canon)               # None = never observed
            if n == old:
                continue
            cur[canon] = n
            changed.append(
                f"{canon} {'unknown' if old is None else old} → {n}")
        if not changed:
            return f"{name}: card resources — no change"
        return self._commit(
            game, f"{name}: card resources adopted from the app: "
                  + "; ".join(changed))


class GameManager:
    """Multi-game sessions: games/<date>-gameN/ per game; state → active game.

    The harness (scripts, strategy KB, card DB) is shared; every game gets a
    fresh, isolated state folder. `state` is a symlink to the active game so
    all documented paths (state/game.json, state/log.md) keep working.
    """

    def __init__(self, root: str | Path = ".", today: str | None = None):
        self.root = Path(root)
        self.games_dir = self.root / "games"
        self.state_link = self.root / "state"
        if today is None:
            from datetime import date
            today = date.today().isoformat()
        self.today = today

    def active_dir(self) -> Path | None:
        if self.state_link.is_symlink() and self.state_link.exists():
            return self.state_link.resolve()
        return None

    def start(self, setup: dict) -> Path:
        if self.state_link.exists() and not self.state_link.is_symlink():
            raise EventError(
                f"{self.state_link} is a real directory (legacy layout). "
                "Move it aside (e.g. into games/) before starting a new game.")
        if self.active_dir() is not None:
            raise EventError(
                f"A game is already active ({self.active_dir().name}); "
                "end it first (session end)"
            )
        self.games_dir.mkdir(parents=True, exist_ok=True)
        n = 1
        while (self.games_dir / f"{self.today}-game{n}").exists():
            n += 1
        game_dir = self.games_dir / f"{self.today}-game{n}"
        game_dir.mkdir()

        setup = dict(setup, startedAt=self.today)
        Store(self.root, state_dir=game_dir).init(setup)

        if self.state_link.is_symlink() or self.state_link.exists():
            self.state_link.unlink()
        self.state_link.symlink_to(game_dir)
        return game_dir

    def link_player(self, name: str, player_id: str, force: bool = False) -> str:
        """Persist an opponent's app playerId into the active game's
        setup.json (without it every opponent id lives in conversation
        memory instead of state -- a silent violation of the
        never-use-memory rule, and no whole-game status check can be
        built)."""
        game_dir = self.active_dir()
        if game_dir is None:
            raise EventError("No active game to link a player into")
        setup_path = game_dir / "setup.json"
        meta = json.loads(setup_path.read_text())
        for p in meta["players"]:
            if p["name"] == name:
                existing = p.get("playerId")
                if existing and existing != player_id and not force:
                    raise EventError(
                        f"{name} already linked to {existing!r}; pass "
                        f"force=True to relink to {player_id!r}")
                p["playerId"] = player_id
                setup_path.write_text(
                    json.dumps(meta, indent=2, ensure_ascii=False) + "\n")
                return f"{name} linked to app playerId {player_id}"
        raise EventError(f"No player named {name!r} in setup.json")

    def end(self, note: str = "") -> Path:
        game_dir = self.active_dir()
        if game_dir is None:
            raise EventError("No active game to end")
        setup_path = game_dir / "setup.json"
        meta = json.loads(setup_path.read_text())
        meta["endedAt"] = self.today
        if note:
            meta["result"] = note
        setup_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n")
        with (game_dir / "log.md").open("a") as f:
            f.write(f"- Game ended {self.today}" + (f" — {note}" if note else "") + "\n")
        self.state_link.unlink()
        return game_dir

    def list_games(self) -> list[dict]:
        active = self.active_dir()
        out = []
        if not self.games_dir.exists():
            return out
        for d in sorted(self.games_dir.iterdir()):
            if not (d / "setup.json").exists():
                continue
            meta = json.loads((d / "setup.json").read_text())
            out.append({
                "dir": d.name,
                "startedAt": meta.get("startedAt"),
                "endedAt": meta.get("endedAt"),
                "result": meta.get("result"),
                "players": [p["name"] for p in meta.get("players", [])],
                "active": active is not None and d.resolve() == active.resolve(),
            })
        return out


# ── board scarcity ───────────────────────────────────────────
# A game can end with dozens of unconverted plants on a board with ZERO
# free land;
# nothing surfaced the scarcity, so plant production kept being bought.

def occupied_space_ids(game: dict) -> set[str]:
    """Space ids holding any tracked tile (all players) in state/game.json."""
    return {str(sid) for sid in (game.get("board") or {})}


def free_land(occupied: set[str], board: dict | None = None) -> int:
    """Number of on-map land spaces (board.json type == 'land', offMap False)
    with no tile. `board` defaults to cards-dir board.json loaded lazily."""
    spaces = (board["spaces"] if board and "spaces" in board
              else list((board or Engine._board()).values()))
    return sum(1 for sp in spaces
               if sp.get("type") == "land" and not sp.get("offMap")
               and str(sp["id"]) not in occupied)


def card_holds_resource(info: dict | None, kind: str) -> bool:
    """True when this card can HOLD `kind` resources (microbe, animal,
    science, floater…) on itself — the db's `resourceType`, extracted from
    the vendor's own card class. Used to decide whether an or-branch that
    needs a host card ("add 3 microbes to ANOTHER card") is executable."""
    held = (info or {}).get("resourceType")
    if not held:
        return False
    return str(held).lower().rstrip("s") == str(kind).lower().rstrip("s")


def action_spend_options(info: dict | None) -> list[dict]:
    """Every way a blue-card action can be PAID, from the db's
    `actionBehavior.spend`: one dict per or-branch (a branch with no cost
    contributes an empty dict), [] when the card has no structured action.
    menu.py prices availability from exactly this."""
    beh = (info or {}).get("actionBehavior")
    if not isinstance(beh, dict):
        return []
    inner = beh.get("or")
    branches = (inner.get("behaviors") or []) if isinstance(inner, dict) else [beh]
    out = []
    for b in branches:
        spend = b.get("spend")
        out.append(dict(spend) if isinstance(spend, dict) else {})
    return out


def resolve_branch_choice(choice, branches: list[dict],
                          label: str = "card"):
    """ONE selector grammar, shared with the transmitter: `choice` is an
    int index into `branches` (card-text order) OR a case-insensitive
    substring of a branch's title.

    An index means different branches in different orderings — the app's
    live prompt hides branches the player cannot execute and the db may
    list them in yet another order — so a title is the selector that
    survives the trip between the layers. The matching itself is
    `appapi.match_branch`, the SAME helper the transmitter resolves the
    live prompt with; there is no second matcher and no card is named
    anywhere in it. An ambiguous or unmatched title raises EventError
    naming the candidates; nothing is applied."""
    if choice is None or isinstance(choice, bool):
        return choice
    if isinstance(choice, int):
        return choice
    s = str(choice).strip()
    if s.isdigit():
        return int(s)
    from appapi import match_branch          # sibling, pure stdlib: no cycle
    try:
        return match_branch([b.get("title", "") for b in branches], s)
    except ValueError as e:
        raise EventError(f"{label}: {e}") from None


def or_branches(info: dict | None, behavior: dict | None = None,
                text: str | None = None) -> list[dict]:
    """Or-choice branches of a card (or of its blue action) in CARD-TEXT
    order.

    The db (vendor behavior) may list the branches in a different order
    from the printed card: Artificial Photosynthesis reads "plant production
    1 step OR energy production 2 steps" but the db lists energy first, so
    `--choice 1` applied plants. Rule: each branch is anchored to the card's
    text by the earliest occurrence of a word that appears in its own title
    and in no other branch's title (whole-word match); branches are sorted
    by that position. Unanchorable branches or ties keep db order (flagged
    via `textOrder=False`). Each returned dict = the branch plus `index`
    (the --choice value), `title`, `textOrder`.

    `behavior`/`text` default to the card's play behavior and `effects`;
    use_action passes `actionBehavior` and the `action` prose instead."""
    import re as _re
    beh = behavior if behavior is not None else ((info or {}).get("behavior") or {})
    raw = ((beh.get("or") or {}).get("behaviors") or []) if isinstance(
        beh.get("or"), dict) else []
    words = [set(_re.findall(r"[a-z0-9]+", str(b.get("title", "")).lower()))
             for b in raw]
    text = str(text if text is not None
               else ((info or {}).get("effects") or "")).lower()
    keyed = []
    for i, b in enumerate(raw):
        others = set().union(*(w for j, w in enumerate(words) if j != i))
        pos = [m.start() for w in words[i] - others
               for m in _re.finditer(rf"\b{_re.escape(w)}\b", text)]
        keyed.append((min(pos) if pos else None, i, b))
    anchored = (all(k[0] is not None for k in keyed)
                and len({k[0] for k in keyed}) == len(keyed))
    if anchored:
        keyed.sort(key=lambda k: k[0])
    out = []
    for idx, (_, i, b) in enumerate(keyed):
        d = dict(b)
        d["index"] = idx
        d["title"] = b.get("title") or "branch " + json.dumps(
            {k: v for k, v in b.items() if k != "title"})
        d["textOrder"] = anchored
        out.append(d)
    return out


def grid_to_space(ref, board: dict | None = None) -> str:
    """'C4' → '17'. Rows A (top) … I, hexes numbered left→right within the
    row — the same labels render_board.py prints AND the online app's log
    panel uses ("placed at C4"), so pasted log lines need no translation.
    Numeric ids pass through unchanged.

    The app SKIPS the letter I — its bottom row is J. 'J5' is
    accepted as our 'I5' (space 63) whenever the board has no genuine
    tenth row; a board that really has one makes 'J' ambiguous → refused."""
    s = str(ref).strip().upper()
    spaces = board or Engine._board()
    if s in spaces:
        return s
    if len(s) < 2 or not s[0].isalpha() or not s[1:].isdigit():
        raise EventError(f"Not a space id or grid ref: {ref!r}")
    row = ord(s[0]) - ord("A")
    if s[0] >= APP_SKIPPED_ROW_LETTER:
        # the app has no row I: its J is our 9th row (y=8). Only safe on a
        # 9-row board — with a genuine 10th row the letter is ambiguous.
        if any(sp.get("y", -1) >= 9 and not sp.get("offMap")
               for sp in spaces.values()):
            raise EventError(
                f"Grid ref {ref!r} is ambiguous: this board has a genuine "
                "10th row (the app's J = our I only on a 9-row board) — "
                "use the space id")
        row -= 1
    in_row = sorted((sp for sp in spaces.values()
                     if sp.get("y") == row and not sp.get("offMap")),
                    key=lambda sp: sp["x"])
    n = int(s[1:])
    if not in_row or n < 1 or n > len(in_row):
        raise EventError(f"Grid ref {ref!r} is off the board")
    return str(in_row[n - 1]["id"])


APP_SKIPPED_ROW_LETTER = "J"   # the online app labels rows A..H, J (no I)


def space_to_grid(space_id, board: dict | None = None) -> str:
    """'63' → 'I5': OUR grid label (render_board.grid_label, rows A..I)."""
    spaces = board or Engine._board()
    sp = spaces.get(str(space_id).strip())
    if sp is None or sp.get("offMap") or sp.get("y") is None:
        raise EventError(f"Unknown board space {space_id!r}")
    in_row = sorted(s2["x"] for s2 in spaces.values()
                    if s2.get("y") == sp["y"] and not s2.get("offMap"))
    return f"{chr(ord('A') + sp['y'])}{in_row.index(sp['x']) + 1}"


def app_label(space_id, board: dict | None = None) -> str:
    """'63' → 'J5': the label the ONLINE APP shows the player for a space (it
    skips the letter I, so our row I is its row J). Print this next to our
    label whenever the player has the app in front of them."""
    ours = space_to_grid(space_id, board)
    if ours[0] >= "I":
        return chr(ord(ours[0]) + 1) + ours[1:]
    return ours


def wgt_enabled(setup: dict) -> bool:
    """World Government Terraforming (Venus Next solar-phase option).
    On when setup.expansions lists "wgt" or a house rule names it."""
    exp = {str(e).strip().lower() for e in setup.get("expansions", [])}
    if exp & {"wgt", "worldgovernment", "solarphase"}:
        return True
    return any("world government" in str(r).lower() or "wgt" in str(r).lower()
               for r in setup.get("houseRules", []))
