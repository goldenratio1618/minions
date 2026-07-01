from __future__ import annotations

import copy
import math
import random
import secrets
import string
from collections import deque
from dataclasses import dataclass, field, replace
from typing import Dict, List, Optional, Tuple

from .constants import OPPONENT, Phase, TERRAIN_LABELS, TEAMS, Terrain
from .coords import Hex, distance, neighbors
from .maps import BoardMap, generate_map, terrain_allows_entry
from .spells import SPELLS, build_deck, make_card, serialize_card
from .units import (
    BASE_UNITS,
    TimedEffect,
    UnitInstance,
    UnitTemplate,
    all_auxiliary_units,
    effective_stats,
    generate_random_unit,
    new_unit_id,
    thematic_unit_name,
    unique_unit_name,
)


class RuleError(ValueError):
    pass


GAME_MODE_RANDOM_UNITS = "random_units"
GAME_MODE_SUBSCRIPTIONS = "subscriptions"
GAME_MODE_LABELS = {
    GAME_MODE_RANDOM_UNITS: "Random Units",
    GAME_MODE_SUBSCRIPTIONS: "Subscriptions",
}
SUBSCRIPTION_AMOUNTS = (2, 3, 5, 8, 13)
DEFAULT_SUBSCRIPTION_LENGTH = 5
RESEARCH_COST = 2


@dataclass
class TurnAction:
    sequence: int
    kind: str
    board: Optional[int]
    summary: str
    unit_ids: List[str] = field(default_factory=list)
    path: List[str] = field(default_factory=list)
    color: Optional[str] = None
    action_name: Optional[str] = None
    payload: dict = field(default_factory=dict)
    before: Optional[dict] = field(default=None, repr=False)

    def to_dict(self) -> dict:
        return {
            "sequence": self.sequence,
            "kind": self.kind,
            "board": self.board,
            "summary": self.summary,
            "unitIds": list(self.unit_ids),
            "path": list(self.path),
        }


@dataclass
class TeamState:
    color: str
    souls: int = 0
    mana: int = 0
    researched: Dict[str, UnitTemplate] = field(default_factory=dict)
    deck: List[str] = field(default_factory=build_deck)
    hand: List[dict] = field(default_factory=list)
    players: List[str] = field(default_factory=list)
    turns_started: int = 0
    oversubscribed: bool = False

    def draw_card(self) -> dict:
        if not self.deck:
            self.deck = build_deck()
        return make_card(self.deck.pop())

    def draw(self, count: int = 1) -> None:
        for _ in range(count):
            self.hand.append(self.draw_card())

    def to_dict(self) -> dict:
        return {
            "color": self.color,
            "souls": self.souls,
            "mana": self.mana,
            "researched": [unit.to_dict() for unit in self.researched.values()],
            "hand": [serialize_card(card) for card in self.hand],
            "deckCount": len(self.deck),
            "players": list(self.players),
            "turnsStarted": self.turns_started,
            "oversubscribed": self.oversubscribed,
        }


@dataclass
class Subscription:
    id: str
    team: str
    template_id: str
    amount: int
    cost: int
    total_units: float
    purchased_team_turn: int
    purchased_count: int = 0


@dataclass
class BoardState:
    index: int
    map: BoardMap
    units: Dict[str, UnitInstance] = field(default_factory=dict)
    reinforcements: Dict[str, List[str]] = field(default_factory=lambda: {"yellow": [], "blue": []})
    subscriptions: Dict[str, List[Subscription]] = field(default_factory=lambda: {"yellow": [], "blue": []})
    spells: Dict[str, List[dict]] = field(default_factory=lambda: {"yellow": [], "blue": []})
    terrain: Dict[str, Optional[str]] = field(default_factory=lambda: {terrain.value: None for terrain in Terrain})
    spawn_locked: Dict[str, bool] = field(default_factory=lambda: {"yellow": False, "blue": False})
    last_mover_id: Optional[str] = None
    resigned_by: Optional[str] = None
    winner: Optional[str] = None

    def to_dict(self, game: "Game") -> dict:
        terrain_map = {kind: hex_key for kind, hex_key in self.terrain.items()}
        self.map.terrain = {kind: (Hex.from_key(hex_key) if hex_key else None) for kind, hex_key in terrain_map.items()}
        spawned_units = []
        spawned_terrain = []
        for action in game.turn_history:
            if action.board != self.index:
                continue
            if action.kind == "spawn" and action.unit_ids:
                spawned_units.append(action.unit_ids[0])
            if action.kind == "terrain" and action.payload.get("terrain"):
                spawned_terrain.append(action.payload["terrain"])
        return {
            "index": self.index,
            "map": self.map.to_dict(),
            "units": [unit.to_dict(game.template(unit.template_id), game.unit_stats(unit)) for unit in self.units.values()],
            "reinforcements": {
                team: [game.template(template_id).to_dict() for template_id in template_ids]
                for team, template_ids in self.reinforcements.items()
            },
            "spells": {
                team: [serialize_card(card) for card in cards]
                for team, cards in self.spells.items()
            },
            "subscriptions": {
                team: [_subscription_to_dict(game, subscription) for subscription in subscriptions]
                for team, subscriptions in self.subscriptions.items()
            },
            "terrain": terrain_map,
            "spawnLocked": dict(self.spawn_locked),
            "lastMoverId": self.last_mover_id,
            "resignedBy": self.resigned_by,
            "winner": self.winner,
            "newlySpawnedUnits": spawned_units,
            "newlySpawnedTerrain": spawned_terrain,
        }


@dataclass
class Game:
    code: str
    board_count: int
    boards: List[BoardState]
    teams: Dict[str, TeamState]
    mode: str = GAME_MODE_RANDOM_UNITS
    subscription_length: int = DEFAULT_SUBSCRIPTION_LENGTH
    turn: str = "yellow"
    phase: str = Phase.SPAWN.value
    scores: Dict[str, int] = field(default_factory=lambda: {"yellow": 0, "blue": 0})
    winner: Optional[str] = None
    turn_number: int = 1
    unit_catalog: Dict[str, UnitTemplate] = field(default_factory=dict)
    log: List[str] = field(default_factory=list)
    turn_history: List[TurnAction] = field(default_factory=list)
    next_action_id: int = 1
    redo_snapshot: Optional[dict] = field(default=None, repr=False)
    redo_label: Optional[str] = None

    @property
    def board_points_to_win(self) -> int:
        return self.board_count if self.board_count <= 3 else self.board_count - 1

    def template(self, template_id: str) -> UnitTemplate:
        if template_id in BASE_UNITS:
            return BASE_UNITS[template_id]
        if template_id in self.unit_catalog:
            return self.unit_catalog[template_id]
        for team in self.teams.values():
            if template_id in team.researched:
                return team.researched[template_id]
        raise RuleError(f"unknown unit template: {template_id}")

    def unit_stats(self, unit: UnitInstance) -> dict:
        return effective_stats(self.template(unit.template_id), unit.effects)

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "boardCount": self.board_count,
            "turn": self.turn,
            "phase": self.phase,
            "turnNumber": self.turn_number,
            "mode": self.mode,
            "modeLabel": GAME_MODE_LABELS[self.mode],
            "subscriptionLength": self.subscription_length,
            "subscriptionAmounts": list(SUBSCRIPTION_AMOUNTS),
            "researchCost": RESEARCH_COST,
            "scores": dict(self.scores),
            "boardPointsToWin": self.board_points_to_win,
            "winner": self.winner,
            "teams": {color: team.to_dict() for color, team in self.teams.items()},
            "boards": [board.to_dict(self) for board in self.boards],
            "baseUnits": {key: unit.to_dict() for key, unit in BASE_UNITS.items()},
            "auxiliaryUnits": all_auxiliary_units(),
            "terrainLabels": TERRAIN_LABELS,
            "turnHistory": [action.to_dict() for action in self.turn_history],
            "canRedo": self.redo_snapshot is not None,
            "redoLabel": self.redo_label,
            "log": self.log[-80:],
        }


def _code() -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(6))


def _normalize_game_mode(mode: str) -> str:
    if mode in GAME_MODE_LABELS:
        return mode
    raise RuleError("unknown game mode")


def _normalize_subscription_length(length: int) -> int:
    if not 1 <= length <= 30:
        raise RuleError("subscription length must be between 1 and 30")
    return length


def create_game(
    board_count: int,
    seed: Optional[int] = None,
    mode: str = GAME_MODE_RANDOM_UNITS,
    subscription_length: int = DEFAULT_SUBSCRIPTION_LENGTH,
) -> Game:
    if not 1 <= board_count <= 9:
        raise RuleError("board count must be between 1 and 9")
    mode = _normalize_game_mode(mode)
    subscription_length = _normalize_subscription_length(subscription_length)
    rng = random.Random(seed)
    teams = {
        "yellow": TeamState("yellow", souls=0, deck=build_deck(rng.randrange(1_000_000_000)), turns_started=1),
        "blue": TeamState("blue", souls=4 * board_count, deck=build_deck(rng.randrange(1_000_000_000))),
    }
    game = Game(
        code=_code(),
        board_count=board_count,
        boards=[],
        teams=teams,
        mode=mode,
        subscription_length=subscription_length,
    )
    for index in range(board_count):
        board = BoardState(index=index, map=generate_map(seed=rng.randrange(1_000_000_000)))
        reset_board(game, board, opener="yellow", initial=True)
        game.boards.append(board)
    game.log.append(f"Game {game.code} created with {board_count} board(s) in {GAME_MODE_LABELS[mode]} mode. Yellow goes first.")
    _draw_turn_spells(game, "yellow")
    return game


def _snapshot(game: Game, turn_history: Optional[List[TurnAction]] = None) -> dict:
    return {
        "boards": copy.deepcopy(game.boards),
        "teams": copy.deepcopy(game.teams),
        "turn": game.turn,
        "phase": game.phase,
        "mode": game.mode,
        "subscription_length": game.subscription_length,
        "scores": copy.deepcopy(game.scores),
        "winner": game.winner,
        "turn_number": game.turn_number,
        "unit_catalog": copy.deepcopy(game.unit_catalog),
        "log": copy.deepcopy(game.log),
        "turn_history": copy.deepcopy(turn_history) if turn_history is not None else None,
        "next_action_id": game.next_action_id,
    }


def _restore_snapshot(game: Game, snapshot: dict, turn_history: Optional[List[TurnAction]] = None) -> None:
    game.boards = copy.deepcopy(snapshot["boards"])
    game.teams = copy.deepcopy(snapshot["teams"])
    game.turn = snapshot["turn"]
    game.phase = snapshot["phase"]
    game.mode = snapshot.get("mode", GAME_MODE_RANDOM_UNITS)
    game.subscription_length = snapshot.get("subscription_length", DEFAULT_SUBSCRIPTION_LENGTH)
    game.scores = copy.deepcopy(snapshot["scores"])
    game.winner = snapshot["winner"]
    game.turn_number = snapshot["turn_number"]
    game.unit_catalog = copy.deepcopy(snapshot["unit_catalog"])
    game.log = copy.deepcopy(snapshot["log"])
    if turn_history is not None:
        game.turn_history = copy.deepcopy(turn_history)
    elif snapshot["turn_history"] is not None:
        game.turn_history = copy.deepcopy(snapshot["turn_history"])
    else:
        game.turn_history = []
    game.next_action_id = snapshot["next_action_id"]


def _record_turn_action(
    game: Game,
    before: dict,
    kind: str,
    board_index: Optional[int],
    summary: str,
    unit_ids: Optional[List[str]] = None,
    path: Optional[List[str]] = None,
    color: Optional[str] = None,
    action_name: Optional[str] = None,
    payload: Optional[dict] = None,
    clear_redo: bool = True,
) -> None:
    game.turn_history.append(
        TurnAction(
            sequence=game.next_action_id,
            kind=kind,
            board=board_index,
            summary=summary,
            unit_ids=unit_ids or [],
            path=path or [],
            color=color,
            action_name=action_name,
            payload=copy.deepcopy(payload) if payload is not None else {},
            before=before,
        )
    )
    game.next_action_id += 1
    if clear_redo:
        game.redo_snapshot = None
        game.redo_label = None


def undo_unit_action(game: Game, color: str, board_index: int, unit_id: str) -> None:
    ensure_turn(game, color)
    for action_index in range(len(game.turn_history) - 1, -1, -1):
        action = game.turn_history[action_index]
        if action.board == board_index and unit_id in action.unit_ids and action.before is not None:
            redo_snapshot = _snapshot(game, game.turn_history)
            redo_label = action.summary
            skipped = _replay_without_turn_action(game, action_index)
            _prune_unsupported_spawn_dependencies(game, color)
            game.redo_snapshot = redo_snapshot
            game.redo_label = redo_label
            if skipped:
                game.log.append(f"{color.title()} undid: {action.summary}. Skipped {skipped} now-illegal later operation(s).")
            else:
                game.log.append(f"{color.title()} undid: {action.summary}. Replayed later operations.")
            return
    raise RuleError("that unit has no operation to undo this turn")


def redo_turn_action(game: Game, color: str) -> None:
    ensure_turn(game, color)
    if game.redo_snapshot is None:
        raise RuleError("nothing to redo")
    snapshot = game.redo_snapshot
    label = game.redo_label
    _restore_snapshot(game, snapshot)
    game.redo_snapshot = None
    game.redo_label = None
    game.log.append(f"{color.title()} redid: {label or 'last undo'}.")


def _replay_without_turn_action(game: Game, action_index: int) -> int:
    target = game.turn_history[action_index]
    previous = copy.deepcopy(game.turn_history[:action_index])
    subsequent = copy.deepcopy(game.turn_history[action_index + 1 :])
    _restore_snapshot(game, target.before, previous)
    skipped = 0
    for later_action in subsequent:
        if not later_action.action_name or later_action.color is None:
            skipped += 1
            continue
        try:
            apply_action(game, later_action.color, later_action.action_name, later_action.payload, clear_redo=False)
        except RuleError:
            skipped += 1
    return skipped


def _unit_can_support_unit_spawn(game: Game, board: BoardState, unit: UnitInstance) -> bool:
    return unit.team == game.turn and not unit.exhausted and game.unit_stats(unit)["spawn"]


def _unit_can_support_terrain_spawn(game: Game, board: BoardState, unit: UnitInstance, terrain: str) -> bool:
    return unit.team == game.turn and not unit.exhausted and terrain in game.unit_stats(unit)["terrainSpawn"]


def _has_adjacent_support(
    game: Game,
    board: BoardState,
    hex_key: str,
    predicate,
) -> bool:
    target = Hex.from_key(hex_key)
    for unit in board.units.values():
        if target in neighbors(Hex.from_key(unit.hex)) and predicate(unit):
            return True
    return False


def _find_unsupported_spawn_dependency(game: Game, move_action: TurnAction) -> Optional[int]:
    if move_action.kind != "move" or not move_action.unit_ids or move_action.before is None or move_action.board is None:
        return None
    board_index = move_action.board
    moved_unit_id = move_action.unit_ids[0]
    before_boards: List[BoardState] = move_action.before["boards"]
    if board_index >= len(before_boards):
        return None
    before_board = before_boards[board_index]
    moved_before = before_board.units.get(moved_unit_id)
    if moved_before is None:
        return None
    before_stats = effective_stats(game.template(moved_before.template_id), moved_before.effects)
    before_hex = Hex.from_key(moved_before.hex)
    current_board = board_at(game, board_index)
    terrain_spawn = set(before_stats["terrainSpawn"])
    for index, action in enumerate(game.turn_history):
        if action.sequence >= move_action.sequence or action.board != board_index:
            continue
        if action.before is None:
            continue
        if action.kind == "spawn" and before_stats["spawn"] and action.unit_ids:
            spawned_unit = current_board.units.get(action.unit_ids[0])
            if spawned_unit is None:
                continue
            spawned_hex = Hex.from_key(spawned_unit.hex)
            if spawned_hex not in neighbors(before_hex):
                continue
            if not _has_adjacent_support(game, current_board, spawned_unit.hex, lambda unit: _unit_can_support_unit_spawn(game, current_board, unit)):
                return index
        if action.kind == "terrain":
            terrain = action.payload.get("terrain")
            q = action.payload.get("q")
            r = action.payload.get("r")
            if not terrain or terrain not in terrain_spawn or q is None or r is None:
                continue
            terrain_hex = current_board.terrain.get(terrain)
            if terrain_hex != f"{q},{r}":
                continue
            if Hex.from_key(terrain_hex) not in neighbors(before_hex):
                continue
            if not _has_adjacent_support(
                game,
                current_board,
                terrain_hex,
                lambda unit, terrain=terrain: _unit_can_support_terrain_spawn(game, current_board, unit, terrain),
            ):
                return index
    return None


def _prune_unsupported_spawn_dependencies(game: Game, color: str) -> None:
    pruned = 0
    while True:
        move_action = next((action for action in reversed(game.turn_history) if action.kind == "move"), None)
        if move_action is None:
            break
        unsupported_index = _find_unsupported_spawn_dependency(game, move_action)
        if unsupported_index is None:
            break
        summary = game.turn_history[unsupported_index].summary
        skipped = _replay_without_turn_action(game, unsupported_index)
        pruned += 1 + skipped
        game.log.append(f"{color.title()} movement invalidated {summary}; replay skipped {skipped} later operation(s).")
    if pruned:
        game.redo_snapshot = None
        game.redo_label = None


def reset_board(game: Game, board: BoardState, opener: str, initial: bool = False) -> None:
    board.units.clear()
    board.reinforcements = {"yellow": [], "blue": []}
    board.subscriptions = {"yellow": [], "blue": []}
    board.terrain = {terrain.value: None for terrain in Terrain}
    board.last_mover_id = None
    board.resigned_by = None
    board.winner = None
    board.spawn_locked = {"yellow": False, "blue": False}
    board.spawn_locked[opener] = True
    for team in TEAMS:
        center = board.map.spawn_centers[team]
        necro = UnitInstance(new_unit_id("nec"), "necromancer", team, center.to_key())
        board.units[necro.id] = necro
        board.reinforcements[team].append("zombie")
        for hex_ in board.map.spawn_tiles[team]:
            if hex_ == center:
                continue
            zombie = UnitInstance(new_unit_id("zom"), "zombie", team, hex_.to_key())
            board.units[zombie.id] = zombie
    if not initial:
        game.log.append(f"Board {board.index + 1} reset. {opener.title()} opens and skips spawning this turn.")


def join_game(game: Game, color: str, name: str) -> None:
    if color not in TEAMS:
        raise RuleError("choose yellow or blue")
    clean_name = (name or color.title()).strip()[:32]
    if clean_name and clean_name not in game.teams[color].players:
        game.teams[color].players.append(clean_name)
    game.log.append(f"{clean_name} joined {color}.")


def ensure_turn(game: Game, color: str) -> None:
    if game.winner:
        raise RuleError("the match is over")
    if color != game.turn:
        raise RuleError(f"it is {game.turn}'s turn")


def board_at(game: Game, index: int) -> BoardState:
    try:
        return game.boards[index]
    except IndexError:
        raise RuleError("unknown board")


def unit_at(board: BoardState, unit_id: str) -> UnitInstance:
    if unit_id not in board.units:
        raise RuleError("unknown unit")
    return board.units[unit_id]


def unit_on_hex(board: BoardState, hex_key: str) -> Optional[UnitInstance]:
    for unit in board.units.values():
        if unit.hex == hex_key:
            return unit
    return None


def terrain_on_hex(board: BoardState, hex_key: str) -> Optional[str]:
    for kind, terrain_hex in board.terrain.items():
        if terrain_hex == hex_key:
            return kind
    return None


def _subscription_age(game: Game, subscription: Subscription, turns_started: Optional[int] = None) -> int:
    team_turns = game.teams[subscription.team].turns_started if turns_started is None else turns_started
    return max(0, team_turns - subscription.purchased_team_turn)


def _subscription_cumulative_units(game: Game, subscription: Subscription, age: int) -> float:
    if subscription.cost <= 0:
        return 0.0
    uncapped = subscription.amount * max(0, age) / subscription.cost
    return min(subscription.total_units, uncapped)


def _subscription_fulfillment_request(game: Game, subscription: Subscription, turns_started: Optional[int] = None) -> float:
    age = _subscription_age(game, subscription, turns_started=turns_started)
    return _subscription_cumulative_units(game, subscription, age) - subscription.purchased_count


def _subscription_due_count(game: Game, subscription: Subscription, turns_started: int, purchased_count: int) -> int:
    age = _subscription_age(game, subscription, turns_started=turns_started)
    cumulative = _subscription_cumulative_units(game, subscription, age)
    target_count = int(math.floor(cumulative + 0.5))
    return max(0, target_count - purchased_count)


def _subscription_schedule(game: Game, subscription: Subscription, turns: Optional[int] = None) -> List[dict]:
    horizon = turns or game.subscription_length
    purchased = subscription.purchased_count
    schedule = []
    team_turns = game.teams[subscription.team].turns_started
    for offset in range(1, horizon + 1):
        due = _subscription_due_count(game, subscription, team_turns + offset, purchased)
        purchased += due
        schedule.append({"turn": offset, "count": due, "spend": due * subscription.cost})
    return schedule


def _subscription_to_dict(game: Game, subscription: Subscription) -> dict:
    template = game.template(subscription.template_id)
    return {
        "id": subscription.id,
        "team": subscription.team,
        "templateId": subscription.template_id,
        "template": template.to_dict(),
        "amount": subscription.amount,
        "cost": subscription.cost,
        "totalUnits": subscription.total_units,
        "purchasedTeamTurn": subscription.purchased_team_turn,
        "purchasedCount": subscription.purchased_count,
        "age": _subscription_age(game, subscription),
        "fulfillmentRequest": _subscription_fulfillment_request(game, subscription),
        "schedule": _subscription_schedule(game, subscription),
    }


def _subscription_is_complete(game: Game, subscription: Subscription) -> bool:
    age = _subscription_age(game, subscription)
    return age >= game.subscription_length and _subscription_fulfillment_request(game, subscription) < 0.5


def _prune_completed_subscriptions(game: Game, color: str) -> None:
    for board in game.boards:
        board.subscriptions[color] = [
            subscription
            for subscription in board.subscriptions[color]
            if not _subscription_is_complete(game, subscription)
        ]


def fulfill_subscriptions(game: Game, color: str) -> None:
    team = game.teams[color]
    team.oversubscribed = False
    if game.mode != GAME_MODE_SUBSCRIPTIONS:
        return
    skipped = set()
    purchased = 0
    oversubscribed = False
    while True:
        due: List[Tuple[float, int, Subscription]] = []
        for board in game.boards:
            for subscription in board.subscriptions[color]:
                key = (board.index, subscription.id)
                if key in skipped:
                    continue
                request = _subscription_fulfillment_request(game, subscription)
                if request >= 0.5:
                    due.append((request, board.index, subscription))
        if not due:
            break
        request, board_index, subscription = max(due, key=lambda item: (item[0], -item[1], item[2].id))
        template = game.template(subscription.template_id)
        if team.souls >= template.cost:
            team.souls -= template.cost
            board_at(game, board_index).reinforcements[color].append(template.id)
            subscription.purchased_count += 1
            purchased += 1
        else:
            skipped.add((board_index, subscription.id))
            oversubscribed = True
    team.oversubscribed = oversubscribed
    _prune_completed_subscriptions(game, color)
    if purchased:
        game.log.append(f"{color.title()} received {purchased} subscribed unit(s).")
    if oversubscribed:
        game.log.append(f"{color.title()} was oversubscribed; research is unavailable this turn.")


def is_empty(game: Game, board: BoardState, hex_: Hex) -> bool:
    key = hex_.to_key()
    return (
        key not in {h.to_key() for h in board.map.water}
        and key not in {h.to_key() for h in board.map.graveyards}
        and unit_on_hex(board, key) is None
        and terrain_on_hex(board, key) is None
    )


def is_unit_spawn_destination(game: Game, board: BoardState, hex_: Hex, stats: dict) -> bool:
    key = hex_.to_key()
    if unit_on_hex(board, key) is not None:
        return False
    if hex_ in board.map.water and not stats["flying"]:
        return False
    terrain = terrain_on_hex(board, key)
    if not terrain_allows_entry(terrain, stats):
        return False
    return True


def can_enter(game: Game, board: BoardState, unit: UnitInstance, hex_: Hex, final: bool = True) -> Tuple[bool, str]:
    key = hex_.to_key()
    stats = game.unit_stats(unit)
    if hex_ in board.map.water and not stats["flying"]:
        return False, "only flying units can enter water"
    terrain = terrain_on_hex(board, key)
    if not terrain_allows_entry(terrain, stats):
        return False, f"{game.template(unit.template_id).name} cannot enter {terrain}"
    occupant = unit_on_hex(board, key)
    if occupant and occupant.id != unit.id:
        if final:
            return False, "destination is occupied"
        if occupant.team == unit.team:
            return True, ""
        if stats["flying"]:
            return True, ""
        return False, "destination is occupied"
    return True, ""


def _movement_path(game: Game, board: BoardState, unit: UnitInstance, destination: Hex) -> List[Hex]:
    current = Hex.from_key(unit.hex)
    if destination == current:
        raise RuleError("choose a different destination")
    stats = game.unit_stats(unit)
    max_steps = stats["speed"] if unit.movement_remaining is None else unit.movement_remaining
    if max_steps <= 0:
        raise RuleError("no movement remaining")
    queue = deque([(current, [current])])
    seen = {current}
    while queue:
        hex_, path = queue.popleft()
        if len(path) - 1 >= max_steps:
            continue
        for neighbor in neighbors(hex_):
            if neighbor in seen:
                continue
            is_final = neighbor == destination
            ok, _reason = can_enter(game, board, unit, neighbor, final=is_final)
            if not ok:
                continue
            next_path = path + [neighbor]
            if is_final:
                return next_path
            seen.add(neighbor)
            queue.append((neighbor, next_path))
    raise RuleError("no legal path to destination")


def _note_action(board: BoardState, acting_unit_id: str) -> None:
    if board.last_mover_id and board.last_mover_id != acting_unit_id and board.last_mover_id in board.units:
        board.units[board.last_mover_id].movement_remaining = 0


def set_phase(game: Game, color: str, phase: str) -> None:
    ensure_turn(game, color)
    if phase not in (Phase.SPAWN.value, Phase.MOVEMENT.value):
        raise RuleError("unknown phase")
    if game.phase == Phase.MOVEMENT.value and phase == Phase.SPAWN.value:
        raise RuleError("cannot return to spawn phase")
    game.phase = phase
    game.log.append(f"{color.title()} entered the {phase} phase.")


def buy_reinforcement(game: Game, color: str, board_index: int, template_id: str) -> None:
    ensure_turn(game, color)
    board = board_at(game, board_index)
    template = game.template(template_id)
    if game.mode == GAME_MODE_SUBSCRIPTIONS and template.id != "zombie":
        raise RuleError("generated units are delivered by subscriptions in this mode")
    if template.id != "zombie" and template.id not in game.teams[color].researched:
        raise RuleError("that unit has not been researched")
    if game.teams[color].souls < template.cost:
        raise RuleError("not enough souls")
    game.teams[color].souls -= template.cost
    board.reinforcements[color].append(template.id)
    if template.id != "zombie":
        game.teams[color].researched.pop(template.id, None)
    game.log.append(f"{color.title()} bought {template.name} for board {board.index + 1}.")


def research_unit(game: Game, color: str) -> UnitTemplate:
    ensure_turn(game, color)
    if game.teams[color].oversubscribed:
        raise RuleError("oversubscribed")
    if game.teams[color].souls < RESEARCH_COST:
        raise RuleError(f"research costs ${RESEARCH_COST}")
    game.teams[color].souls -= RESEARCH_COST
    unit = generate_random_unit(turn_number=game.turn_number)
    if game.mode == GAME_MODE_RANDOM_UNITS:
        unit = replace(unit, cost=unit.cost - RESEARCH_COST)
    name = thematic_unit_name(unit)
    unit = replace(unit, name=unique_unit_name(name, (template.name for template in game.unit_catalog.values())))
    game.teams[color].researched[unit.id] = unit
    game.unit_catalog[unit.id] = unit
    game.log.append(f"{color.title()} researched {unit.name} (${unit.cost}/{unit.rebate}).")
    return unit


def subscribe_unit(game: Game, color: str, board_index: int, template_id: str, amount: int) -> Subscription:
    ensure_turn(game, color)
    if game.mode != GAME_MODE_SUBSCRIPTIONS:
        raise RuleError("subscriptions are not enabled in this game")
    if amount not in SUBSCRIPTION_AMOUNTS:
        raise RuleError("unknown subscription amount")
    if template_id not in game.teams[color].researched:
        raise RuleError("that unit has not been researched")
    board = board_at(game, board_index)
    template = game.template(template_id)
    total_units = amount * game.subscription_length / template.cost
    if total_units < 0.5:
        raise RuleError("that subscription is too small for this unit")
    subscription = Subscription(
        id=f"sub_{secrets.token_hex(4)}",
        team=color,
        template_id=template_id,
        amount=amount,
        cost=template.cost,
        total_units=total_units,
        purchased_team_turn=game.teams[color].turns_started,
    )
    board.subscriptions[color].append(subscription)
    game.log.append(f"{color.title()} subscribed to {template.name} at ${amount} on board {board.index + 1}.")
    return subscription


def _spawner_is_ready(game: Game, board: BoardState, source: UnitInstance, require_spawn: bool = True) -> None:
    if source.team != game.turn:
        raise RuleError("spawner must be friendly")
    if source.exhausted:
        raise RuleError("exhausted units cannot spawn")
    stats = game.unit_stats(source)
    if require_spawn and not stats["spawn"]:
        raise RuleError("unit does not have spawn")


def _find_spawner_for_destination(
    game: Game,
    board: BoardState,
    color: str,
    destination: Hex,
    require_spawn: bool = True,
) -> UnitInstance:
    candidates = sorted(
        (unit for unit in board.units.values() if unit.team == color and destination in neighbors(Hex.from_key(unit.hex))),
        key=lambda unit: unit.id,
    )
    for unit in candidates:
        try:
            _spawner_is_ready(game, board, unit, require_spawn=require_spawn)
            return unit
        except RuleError:
            continue
    raise RuleError("no ready friendly spawner is adjacent to that hex")


def spawn_reinforcement(
    game: Game,
    color: str,
    board_index: int,
    source_id: Optional[str],
    template_id: str,
    q: int,
    r: int,
    free: bool = False,
    via_spell: bool = False,
    unit_id: Optional[str] = None,
) -> Tuple[UnitInstance, str]:
    ensure_turn(game, color)
    board = board_at(game, board_index)
    if board.spawn_locked.get(color):
        raise RuleError("the board opener cannot spawn on that opening turn")
    destination = Hex(q, r)
    source = unit_at(board, source_id) if source_id else _find_spawner_for_destination(game, board, color, destination, require_spawn=not via_spell)
    _spawner_is_ready(game, board, source, require_spawn=not via_spell)
    if destination not in neighbors(Hex.from_key(source.hex)):
        raise RuleError("spawn destination must be adjacent")
    stats = effective_stats(game.template(template_id), [])
    if not is_unit_spawn_destination(game, board, destination, stats):
        raise RuleError("spawn destination must be legal and unoccupied")
    _note_action(board, source.id)
    if not free:
        try:
            board.reinforcements[color].remove(template_id)
        except ValueError:
            raise RuleError("that unit is not in this board's reinforcements")
    unit = UnitInstance(unit_id or new_unit_id(), template_id, color, destination.to_key(), exhausted=True)
    board.units[unit.id] = unit
    game.log.append(f"{color.title()} spawned {game.template(template_id).name} on board {board.index + 1}.")
    return unit, source.id


def spawn_terrain(game: Game, color: str, board_index: int, source_id: str, terrain: str, q: int, r: int, via_spell: bool = False) -> None:
    ensure_turn(game, color)
    if terrain not in TERRAIN_LABELS:
        raise RuleError("unknown terrain")
    board = board_at(game, board_index)
    source = unit_at(board, source_id)
    if source.team != color:
        raise RuleError("terrain must be spawned by a friendly unit")
    if not via_spell:
        _spawner_is_ready(game, board, source, require_spawn=False)
        if terrain not in game.template(source.template_id).terrain_spawn:
            raise RuleError("that unit cannot spawn this terrain")
    else:
        _spawner_is_ready(game, board, source, require_spawn=False)
    destination = Hex(q, r)
    if destination not in neighbors(Hex.from_key(source.hex)):
        raise RuleError("terrain destination must be adjacent")
    if not is_empty(game, board, destination):
        raise RuleError("terrain destination must be empty plain hex")
    _note_action(board, source.id)
    board.terrain[terrain] = destination.to_key()
    game.log.append(f"{color.title()} moved {TERRAIN_LABELS[terrain]} to board {board.index + 1}.")


def move_unit(game: Game, color: str, board_index: int, unit_id: str, q: int, r: int) -> List[str]:
    ensure_turn(game, color)
    board = board_at(game, board_index)
    unit = unit_at(board, unit_id)
    if unit.team != color:
        raise RuleError("cannot move enemy units")
    if unit.exhausted:
        raise RuleError("exhausted units cannot move")
    if unit.attacked:
        raise RuleError("units cannot move after attacking")
    destination = Hex(q, r)
    path = _movement_path(game, board, unit, destination)
    _note_action(board, unit.id)
    if unit.movement_remaining is None:
        unit.movement_remaining = game.unit_stats(unit)["speed"]
    unit.hex = destination.to_key()
    unit.moved = True
    unit.movement_remaining -= len(path) - 1
    board.last_mover_id = unit.id
    game.log.append(f"{color.title()} moved {game.template(unit.template_id).name}.")
    return [hex_.to_key() for hex_ in path]


def _kill_unit(game: Game, board: BoardState, unit: UnitInstance, killer: str) -> None:
    template = game.template(unit.template_id)
    if not template.minion:
        score_board(game, board, killer, "necromancer killed")
        return
    game.teams[unit.team].souls += template.rebate
    del board.units[unit.id]
    game.log.append(f"{template.name} died; {unit.team} gained ${template.rebate} rebate.")


def _unsummon_unit(game: Game, board: BoardState, unit: UnitInstance) -> None:
    template = game.template(unit.template_id)
    if game.unit_stats(unit)["persistent"]:
        unit.damage += 1
        if unit.damage >= game.unit_stats(unit)["defense"]:
            _kill_unit(game, board, unit, OPPONENT[unit.team])
        return
    if not template.minion:
        unit.damage += 1
        return
    board.reinforcements[unit.team].append(unit.template_id)
    del board.units[unit.id]
    game.log.append(f"{template.name} was unsummoned to {unit.team}'s reinforcements.")


def attack_unit(game: Game, color: str, board_index: int, attacker_id: str, target_id: str, amount: Optional[int] = None) -> None:
    ensure_turn(game, color)
    board = board_at(game, board_index)
    attacker = unit_at(board, attacker_id)
    target = unit_at(board, target_id)
    if attacker.team != color or target.team == color:
        raise RuleError("choose a friendly attacker and enemy target")
    if attacker.exhausted:
        raise RuleError("exhausted units cannot attack")
    stats = game.unit_stats(attacker)
    if stats["lumbering"] and attacker.moved:
        raise RuleError("lumbering units cannot both move and attack")
    if distance(Hex.from_key(attacker.hex), Hex.from_key(target.hex)) > stats["range"]:
        raise RuleError("target is out of range")
    attack_value = stats["attack"]
    if attack_value in ("*", "**"):
        if attacker.star_attacks_remaining is None:
            attacker.star_attacks_remaining = 2 if attack_value == "**" else 1
        if attacker.star_attacks_remaining <= 0:
            raise RuleError("no unsummon attacks remaining")
        _note_action(board, attacker.id)
        _unsummon_unit(game, board, target)
        attacker.star_attacks_remaining -= 1
    else:
        total = int(attack_value)
        if stats["flurry"]:
            if attacker.flurry_remaining is None:
                attacker.flurry_remaining = total
            target_health = game.unit_stats(target)["defense"] - target.damage
            damage = amount if amount is not None else min(attacker.flurry_remaining, target_health)
            if damage <= 0 or damage > attacker.flurry_remaining:
                raise RuleError("invalid flurry amount")
            _note_action(board, attacker.id)
            attacker.flurry_remaining -= damage
        else:
            if attacker.attacked:
                raise RuleError("unit has already attacked")
            damage = total
            _note_action(board, attacker.id)
        critical_effect = next((effect for effect in attacker.effects if effect.critical), None)
        if critical_effect:
            damage *= 2
            attacker.effects.remove(critical_effect)
        target.damage += damage
        if target.damage >= game.unit_stats(target)["defense"]:
            _kill_unit(game, board, target, color)
    attacker.attacked = True
    game.log.append(f"{color.title()} attacked on board {board.index + 1}.")


def blink_unit(game: Game, color: str, board_index: int, unit_id: str) -> None:
    ensure_turn(game, color)
    board = board_at(game, board_index)
    unit = unit_at(board, unit_id)
    if unit.team != color:
        raise RuleError("can only blink friendly units")
    template = game.template(unit.template_id)
    if not game.unit_stats(unit)["blink"]:
        raise RuleError("unit does not have Blink")
    if not template.minion:
        raise RuleError("necromancers cannot be returned to reinforcements")
    board.reinforcements[color].append(unit.template_id)
    del board.units[unit.id]
    game.log.append(f"{template.name} blinked back to reinforcements.")


def _target_minion(game: Game, board: BoardState, unit_id: str) -> UnitInstance:
    target = unit_at(board, unit_id)
    if not game.template(target.template_id).minion:
        raise RuleError("spell must target a minion")
    return target


def _require_damaged_enemy(game: Game, color: str, board: BoardState, unit_id: str) -> UnitInstance:
    target = _target_minion(game, board, unit_id)
    if target.team == color:
        raise RuleError("target must be an enemy")
    if target.damage <= 0:
        raise RuleError("target must already be damaged")
    return target


def _charge_spell(game: Game, color: str, spell_id: str, target: Optional[UnitInstance]) -> None:
    spell = SPELLS[spell_id]
    cost = spell.mana_cost
    if target:
        cost += game.unit_stats(target)["ward"]
    if game.teams[color].mana < cost:
        raise RuleError(f"{spell.name} costs {cost} mana")
    game.teams[color].mana -= cost


def cast_spell(game: Game, color: str, card_id: str, payload: dict, discarded: bool = False) -> None:
    ensure_turn(game, color)
    team = game.teams[color]
    board = board_at(game, int(payload.get("board", 0)))
    card = next((candidate for candidate in board.spells[color] if candidate["cardId"] == card_id), None)
    if not card:
        raise RuleError("card is not in this board's hand")
    spell_id = card["spellId"]
    spell = SPELLS[spell_id]
    if discarded and not spell.cantrip:
        board.spells[color].remove(card)
        team.mana += 1
        game.log.append(f"{color.title()} discarded {spell.name} for 1 mana.")
        return
    target = unit_at(board, payload["targetId"]) if payload.get("targetId") else None
    if not discarded:
        _charge_spell(game, color, spell_id, target if target and target.team != color else None)
    _resolve_spell(game, color, board, spell_id, payload)
    board.spells[color].remove(card)
    if discarded:
        team.mana += 1
        game.log.append(f"{color.title()} discarded {spell.name} and used its cantrip.")
    else:
        game.log.append(f"{color.title()} cast {spell.name}.")


def _resolve_spell(game: Game, color: str, board: BoardState, spell_id: str, payload: dict) -> None:
    target_id = payload.get("targetId")
    if spell_id == "fester":
        target = _require_damaged_enemy(game, color, board, target_id)
        target.damage += 1
        if target.damage >= game.unit_stats(target)["defense"]:
            _kill_unit(game, board, target, color)
    elif spell_id == "dismember":
        target = _require_damaged_enemy(game, color, board, target_id)
        target.damage += 3
        if target.damage >= game.unit_stats(target)["defense"]:
            _kill_unit(game, board, target, color)
    elif spell_id == "unsummon":
        _unsummon_unit(game, board, _require_damaged_enemy(game, color, board, target_id))
    elif spell_id in ("stumble", "double_stumble"):
        target = _require_damaged_enemy(game, color, board, target_id)
        max_distance = 2 if spell_id == "double_stumble" else 1
        _move_spell_target(game, board, target, payload, max_distance, exhaust=False)
    elif spell_id == "shield":
        target = _friendly_minion(game, color, board, target_id)
        target.effects.append(TimedEffect("Shield", color, defense_multiplier=2.0, ward_bonus=1))
    elif spell_id == "reposition":
        target = _friendly_minion(game, color, board, target_id)
        _move_spell_target(game, board, target, payload, 1, exhaust=True)
    elif spell_id == "critical_hit":
        _friendly_minion(game, color, board, target_id).effects.append(TimedEffect("Critical Hit", color, critical=True))
    elif spell_id == "weaken":
        _enemy_minion(game, color, board, target_id).effects.append(TimedEffect("Weaken", color, attack_delta=-1))
    elif spell_id == "freeze_ray":
        _enemy_minion(game, color, board, target_id).effects.append(TimedEffect("Freeze Ray", color, attack_set=0))
    elif spell_id == "lumbering":
        _enemy_minion(game, color, board, target_id).effects.append(TimedEffect("Lumbering", color, lumbering=True))
    elif spell_id == "shackle":
        _enemy_minion(game, color, board, target_id).effects.append(TimedEffect("Shackle", color, shackle=True))
    elif spell_id == "blink":
        target = _friendly_minion(game, color, board, target_id)
        board.reinforcements[color].append(target.template_id)
        del board.units[target.id]
    elif spell_id == "persistent":
        _friendly_minion(game, color, board, target_id).effects.append(TimedEffect("Persistent", color, persistent=True))
    elif spell_id in ("firestorm", "earthquake", "flood", "whirlwind"):
        spawn_terrain(game, color, board.index, target_id, spell_id, int(payload["q"]), int(payload["r"]), via_spell=True)
    elif spell_id == "terraform":
        terrain = payload.get("terrain")
        spawn_terrain(game, color, board.index, target_id, terrain, int(payload["q"]), int(payload["r"]), via_spell=True)
    elif spell_id == "normalize":
        terrain = payload.get("terrain") or terrain_on_hex(board, Hex(int(payload["q"]), int(payload["r"])).to_key())
        if terrain not in board.terrain:
            raise RuleError("choose terrain to normalize")
        board.terrain[terrain] = None
    elif spell_id == "lesser_spawn":
        target = _friendly_minion(game, color, board, target_id)
        template_id = payload.get("templateId") or (board.reinforcements[color][0] if board.reinforcements[color] else None)
        if not template_id:
            raise RuleError("choose a minion from reinforcements")
        spawn_reinforcement(game, color, board.index, target.id, template_id, int(payload["q"]), int(payload["r"]), via_spell=True)
    elif spell_id == "spawn":
        target = _friendly_minion(game, color, board, target_id)
        if game.unit_stats(target)["blink"]:
            raise RuleError("units cannot have both Spawn and Blink")
        target.effects.append(TimedEffect("Spawn", color, spawn=True))
    elif spell_id == "raise_zombie":
        target = _friendly_minion(game, color, board, target_id)
        spawn_reinforcement(game, color, board.index, target.id, "zombie", int(payload["q"]), int(payload["r"]), free=True, via_spell=True)
    else:
        raise RuleError("spell is not implemented")
    _mark_spawn_spell_unit(game, color, board, spell_id, target_id)


def _mark_spawn_spell_unit(game: Game, color: str, board: BoardState, spell_id: str, target_id: Optional[str]) -> None:
    if not SPELLS[spell_id].spawn_phase_only or not target_id or target_id not in board.units:
        return
    target = board.units[target_id]
    if target.team == color:
        target.moved = True
        target.attacked = True


def _friendly_minion(game: Game, color: str, board: BoardState, unit_id: str) -> UnitInstance:
    target = _target_minion(game, board, unit_id)
    if target.team != color:
        raise RuleError("target must be friendly")
    return target


def _enemy_minion(game: Game, color: str, board: BoardState, unit_id: str) -> UnitInstance:
    target = _target_minion(game, board, unit_id)
    if target.team == color:
        raise RuleError("target must be enemy")
    return target


def _move_spell_target(game: Game, board: BoardState, target: UnitInstance, payload: dict, max_distance: int, exhaust: bool) -> None:
    destination = Hex(int(payload["q"]), int(payload["r"]))
    current = Hex.from_key(target.hex)
    if distance(current, destination) > max_distance:
        raise RuleError("destination is too far")
    if not is_empty(game, board, destination):
        raise RuleError("destination must be empty")
    ok, reason = can_enter(game, board, target, destination, final=True)
    if not ok:
        raise RuleError(reason)
    target.hex = destination.to_key()
    target.exhausted = target.exhausted or exhaust


def _draw_turn_spells(game: Game, color: str) -> None:
    for board in game.boards:
        board.spells[color].append(game.teams[color].draw_card())
    game.log.append(f"{color.title()} drew {len(game.boards)} spell card(s), one per board.")


def draw_spell(game: Game, color: str) -> None:
    ensure_turn(game, color)
    raise RuleError("spell cards are drawn automatically at one card per board each turn")


def resign_board(game: Game, color: str, board_index: int) -> None:
    ensure_turn(game, color)
    board = board_at(game, board_index)
    if board.winner:
        raise RuleError("that board is already decided")
    winner = OPPONENT[color]
    board.resigned_by = color
    board.winner = winner
    game.scores[winner] += 1
    game.log.append(f"{color.title()} resigned board {board.index + 1}; {winner.title()} gained a board point.")
    if game.scores[winner] >= game.board_points_to_win:
        game.winner = winner
        game.log.append(f"{winner.title()} wins the match.")
    else:
        game.log.append(f"Board {board.index + 1} will reset at the start of {winner.title()}'s next turn.")


def score_board(game: Game, board: BoardState, winner: str, reason: str) -> None:
    if game.winner or board.winner:
        return
    board.winner = winner
    game.scores[winner] += 1
    game.log.append(f"{winner.title()} won board {board.index + 1}: {reason}.")
    if game.scores[winner] >= game.board_points_to_win:
        game.winner = winner
        game.log.append(f"{winner.title()} wins the match.")
        return
    reset_board(game, board, opener=winner)
    game.turn = winner
    game.phase = Phase.SPAWN.value


def _graveyard_occupants(board: BoardState) -> Dict[str, int]:
    graveyard_keys = {hex_.to_key() for hex_ in board.map.graveyards}
    counts = {"yellow": 0, "blue": 0}
    for unit in board.units.values():
        if unit.hex in graveyard_keys:
            counts[unit.team] += 1
    return counts


def start_turn_checks(game: Game, color: str) -> None:
    game.teams[color].turns_started += 1
    for board in game.boards:
        if board.resigned_by == OPPONENT[color] and board.winner == color:
            reset_board(game, board, opener=color)
            continue
        counts = _graveyard_occupants(board)
        if counts[color] >= 8:
            score_board(game, board, color, "occupied at least 8 graveyards at turn start")
            if game.winner:
                return
    for board in game.boards:
        for unit in board.units.values():
            if unit.team == color:
                unit.exhausted = False
                unit.moved = False
                unit.attacked = False
                unit.movement_remaining = None
                unit.flurry_remaining = None
                unit.star_attacks_remaining = None
            unit.effects = [effect for effect in unit.effects if effect.caster != color]
        board.last_mover_id = None
    game.teams[color].mana = 0
    game.turn_history = []
    game.next_action_id = 1
    game.redo_snapshot = None
    game.redo_label = None
    fulfill_subscriptions(game, color)
    _draw_turn_spells(game, color)


def end_turn(game: Game, color: str) -> None:
    ensure_turn(game, color)
    for board in game.boards:
        board.spawn_locked[color] = False
        counts = _graveyard_occupants(board)
        game.teams[color].souls += 3 + counts[color]
        for unit in board.units.values():
            unit.damage = 0
    game.log.append(f"{color.title()} ended turn and collected income.")
    game.turn = OPPONENT[color]
    game.turn_number += 1
    game.phase = Phase.SPAWN.value
    game.turn_history = []
    game.next_action_id = 1
    game.redo_snapshot = None
    game.redo_label = None
    start_turn_checks(game, game.turn)


def apply_action(game: Game, color: str, action: str, payload: dict, clear_redo: bool = True) -> Optional[dict]:
    if action == "join":
        join_game(game, color, payload.get("name", ""))
    elif action == "set_phase":
        set_phase(game, color, payload["phase"])
    elif action == "buy":
        buy_reinforcement(game, color, int(payload.get("board", 0)), payload["templateId"])
    elif action == "subscribe":
        subscription = subscribe_unit(game, color, int(payload.get("board", 0)), payload["templateId"], int(payload["amount"]))
        return {"subscription": _subscription_to_dict(game, subscription)}
    elif action == "research":
        before = _snapshot(game)
        unit = research_unit(game, color)
        _record_turn_action(
            game,
            before,
            "research",
            None,
            f"researched {unit.name}",
            color=color,
            action_name=action,
            payload=payload,
            clear_redo=clear_redo,
        )
        return {"unit": unit.to_dict()}
    elif action == "spawn":
        before = _snapshot(game)
        board_index = int(payload.get("board", 0))
        unit, source_id = spawn_reinforcement(
            game,
            color,
            board_index,
            payload.get("sourceId"),
            payload["templateId"],
            int(payload["q"]),
            int(payload["r"]),
            unit_id=payload.get("_unitId"),
        )
        replay_payload = dict(payload)
        replay_payload["board"] = board_index
        replay_payload["sourceId"] = source_id
        replay_payload["_unitId"] = unit.id
        _record_turn_action(
            game,
            before,
            "spawn",
            board_index,
            f"spawned {game.template(unit.template_id).name}",
            [unit.id, source_id],
            color=color,
            action_name=action,
            payload=replay_payload,
            clear_redo=clear_redo,
        )
        return {"unitId": unit.id}
    elif action == "spawn_terrain":
        before = _snapshot(game)
        board_index = int(payload.get("board", 0))
        spawn_terrain(
            game,
            color,
            board_index,
            payload["sourceId"],
            payload["terrain"],
            int(payload["q"]),
            int(payload["r"]),
        )
        _record_turn_action(
            game,
            before,
            "terrain",
            board_index,
            f"spawned {TERRAIN_LABELS[payload['terrain']]}",
            [payload["sourceId"]],
            color=color,
            action_name=action,
            payload={**payload, "board": board_index},
            clear_redo=clear_redo,
        )
    elif action == "move":
        before = _snapshot(game)
        board_index = int(payload.get("board", 0))
        path = move_unit(game, color, board_index, payload["unitId"], int(payload["q"]), int(payload["r"]))
        _record_turn_action(
            game,
            before,
            "move",
            board_index,
            "moved unit",
            [payload["unitId"]],
            path,
            color=color,
            action_name=action,
            payload={**payload, "board": board_index},
            clear_redo=clear_redo,
        )
        if clear_redo:
            _prune_unsupported_spawn_dependencies(game, color)
        return {"path": path}
    elif action == "attack":
        before = _snapshot(game)
        board_index = int(payload.get("board", 0))
        amount = int(payload["amount"]) if payload.get("amount") else None
        attack_unit(game, color, board_index, payload["attackerId"], payload["targetId"], amount)
        _record_turn_action(
            game,
            before,
            "attack",
            board_index,
            "attacked unit",
            [payload["attackerId"], payload["targetId"]],
            color=color,
            action_name=action,
            payload={**payload, "board": board_index},
            clear_redo=clear_redo,
        )
    elif action == "blink_unit":
        before = _snapshot(game)
        board_index = int(payload.get("board", 0))
        blink_unit(game, color, board_index, payload["unitId"])
        _record_turn_action(
            game,
            before,
            "blink",
            board_index,
            "blinked unit",
            [payload["unitId"]],
            color=color,
            action_name=action,
            payload={**payload, "board": board_index},
            clear_redo=clear_redo,
        )
    elif action == "cast_spell":
        before = _snapshot(game)
        cast_spell(game, color, payload["cardId"], payload, discarded=False)
        _record_turn_action(
            game,
            before,
            "spell",
            int(payload.get("board", 0)),
            "cast spell",
            [payload["targetId"]] if payload.get("targetId") else [],
            color=color,
            action_name=action,
            payload=payload,
            clear_redo=clear_redo,
        )
    elif action == "discard_spell":
        before = _snapshot(game)
        cast_spell(game, color, payload["cardId"], payload, discarded=True)
        _record_turn_action(
            game,
            before,
            "discard",
            int(payload.get("board", 0)) if "board" in payload else None,
            "discarded spell",
            [payload["targetId"]] if payload.get("targetId") else [],
            color=color,
            action_name=action,
            payload=payload,
            clear_redo=clear_redo,
        )
    elif action == "draw_spell":
        draw_spell(game, color)
    elif action == "undo_unit":
        undo_unit_action(game, color, int(payload.get("board", 0)), payload["unitId"])
    elif action == "redo":
        redo_turn_action(game, color)
    elif action == "resign_board":
        resign_board(game, color, int(payload.get("board", 0)))
    elif action == "end_turn":
        end_turn(game, color)
    else:
        raise RuleError("unknown action")
    return None
