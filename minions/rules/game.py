from __future__ import annotations

import random
import secrets
import string
from dataclasses import dataclass, field
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
)


class RuleError(ValueError):
    pass


@dataclass
class TeamState:
    color: str
    souls: int = 0
    mana: int = 0
    researched: Dict[str, UnitTemplate] = field(default_factory=dict)
    deck: List[str] = field(default_factory=build_deck)
    hand: List[dict] = field(default_factory=list)
    players: List[str] = field(default_factory=list)

    def draw(self, count: int = 1) -> None:
        for _ in range(count):
            if not self.deck:
                self.deck = build_deck()
            self.hand.append(make_card(self.deck.pop()))

    def to_dict(self) -> dict:
        return {
            "color": self.color,
            "souls": self.souls,
            "mana": self.mana,
            "researched": [unit.to_dict() for unit in self.researched.values()],
            "hand": [serialize_card(card) for card in self.hand],
            "deckCount": len(self.deck),
            "players": list(self.players),
        }


@dataclass
class BoardState:
    index: int
    map: BoardMap
    units: Dict[str, UnitInstance] = field(default_factory=dict)
    reinforcements: Dict[str, List[str]] = field(default_factory=lambda: {"yellow": [], "blue": []})
    terrain: Dict[str, Optional[str]] = field(default_factory=lambda: {terrain.value: None for terrain in Terrain})
    spawn_locked: Dict[str, bool] = field(default_factory=lambda: {"yellow": False, "blue": False})
    last_mover_id: Optional[str] = None
    resigned_by: Optional[str] = None
    winner: Optional[str] = None

    def to_dict(self, game: "Game") -> dict:
        terrain_map = {kind: hex_key for kind, hex_key in self.terrain.items()}
        self.map.terrain = {kind: (Hex.from_key(hex_key) if hex_key else None) for kind, hex_key in terrain_map.items()}
        return {
            "index": self.index,
            "map": self.map.to_dict(),
            "units": [unit.to_dict(game.template(unit.template_id), game.unit_stats(unit)) for unit in self.units.values()],
            "reinforcements": {
                team: [game.template(template_id).to_dict() for template_id in template_ids]
                for team, template_ids in self.reinforcements.items()
            },
            "terrain": terrain_map,
            "spawnLocked": dict(self.spawn_locked),
            "lastMoverId": self.last_mover_id,
            "resignedBy": self.resigned_by,
            "winner": self.winner,
        }


@dataclass
class Game:
    code: str
    board_count: int
    boards: List[BoardState]
    teams: Dict[str, TeamState]
    turn: str = "yellow"
    phase: str = Phase.SPAWN.value
    scores: Dict[str, int] = field(default_factory=lambda: {"yellow": 0, "blue": 0})
    winner: Optional[str] = None
    turn_number: int = 1
    unit_catalog: Dict[str, UnitTemplate] = field(default_factory=dict)
    log: List[str] = field(default_factory=list)

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
            "scores": dict(self.scores),
            "boardPointsToWin": self.board_points_to_win,
            "winner": self.winner,
            "teams": {color: team.to_dict() for color, team in self.teams.items()},
            "boards": [board.to_dict(self) for board in self.boards],
            "baseUnits": {key: unit.to_dict() for key, unit in BASE_UNITS.items()},
            "auxiliaryUnits": all_auxiliary_units(),
            "terrainLabels": TERRAIN_LABELS,
            "log": self.log[-80:],
        }


def _code() -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(6))


def create_game(board_count: int, seed: Optional[int] = None) -> Game:
    if not 1 <= board_count <= 9:
        raise RuleError("board count must be between 1 and 9")
    rng = random.Random(seed)
    teams = {
        "yellow": TeamState("yellow", souls=0, deck=build_deck(rng.randrange(1_000_000_000))),
        "blue": TeamState("blue", souls=4 * board_count, deck=build_deck(rng.randrange(1_000_000_000))),
    }
    game = Game(code=_code(), board_count=board_count, boards=[], teams=teams)
    for index in range(board_count):
        board = BoardState(index=index, map=generate_map(seed=rng.randrange(1_000_000_000)))
        reset_board(game, board, opener="yellow", initial=True)
        game.boards.append(board)
    game.log.append(f"Game {game.code} created with {board_count} board(s). Yellow goes first.")
    _draw_turn_spells(game, "yellow")
    return game


def reset_board(game: Game, board: BoardState, opener: str, initial: bool = False) -> None:
    board.units.clear()
    board.reinforcements = {"yellow": [], "blue": []}
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
    if key in {h.to_key() for h in board.map.graveyards}:
        return False
    if unit_on_hex(board, key) is not None or terrain_on_hex(board, key) is not None:
        return False
    if hex_ in board.map.water and not stats["flying"]:
        return False
    return True


def can_enter(game: Game, board: BoardState, unit: UnitInstance, hex_: Hex, allow_friendly_swap: bool = True) -> Tuple[bool, str]:
    key = hex_.to_key()
    stats = game.unit_stats(unit)
    if hex_ in board.map.water and not stats["flying"]:
        return False, "only flying units can enter water"
    terrain = terrain_on_hex(board, key)
    if not terrain_allows_entry(terrain, stats):
        return False, f"{game.template(unit.template_id).name} cannot enter {terrain}"
    occupant = unit_on_hex(board, key)
    if occupant:
        if occupant.team == unit.team and allow_friendly_swap:
            return True, ""
        return False, "destination is occupied"
    return True, ""


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
    if template.id != "zombie" and template.id not in game.teams[color].researched:
        raise RuleError("that unit has not been researched")
    if game.teams[color].souls < template.cost:
        raise RuleError("not enough souls")
    game.teams[color].souls -= template.cost
    board.reinforcements[color].append(template.id)
    game.log.append(f"{color.title()} bought {template.name} for board {board.index + 1}.")


def research_unit(game: Game, color: str) -> UnitTemplate:
    ensure_turn(game, color)
    if game.teams[color].souls < 1:
        raise RuleError("research costs $1")
    game.teams[color].souls -= 1
    unit = generate_random_unit()
    game.teams[color].researched[unit.id] = unit
    game.unit_catalog[unit.id] = unit
    game.log.append(f"{color.title()} researched {unit.name} (${unit.cost}/{unit.rebate}).")
    return unit


def _spawner_is_ready(game: Game, board: BoardState, source: UnitInstance, require_spawn: bool = True) -> None:
    if source.team != game.turn:
        raise RuleError("spawner must be friendly")
    if source.exhausted:
        raise RuleError("exhausted units cannot spawn")
    stats = game.unit_stats(source)
    if require_spawn and not stats["spawn"]:
        raise RuleError("unit does not have spawn")


def spawn_reinforcement(
    game: Game,
    color: str,
    board_index: int,
    source_id: str,
    template_id: str,
    q: int,
    r: int,
    free: bool = False,
    via_spell: bool = False,
) -> UnitInstance:
    ensure_turn(game, color)
    if game.phase != Phase.SPAWN.value and not via_spell:
        raise RuleError("unit spawning is only available in spawn phase")
    board = board_at(game, board_index)
    if board.spawn_locked.get(color):
        raise RuleError("the board opener cannot spawn on that opening turn")
    source = unit_at(board, source_id)
    _spawner_is_ready(game, board, source, require_spawn=not via_spell)
    destination = Hex(q, r)
    if destination not in neighbors(Hex.from_key(source.hex)):
        raise RuleError("spawn destination must be adjacent")
    stats = effective_stats(game.template(template_id), [])
    if not is_unit_spawn_destination(game, board, destination, stats):
        raise RuleError("spawn destination must be legal and unoccupied")
    if not free:
        try:
            board.reinforcements[color].remove(template_id)
        except ValueError:
            raise RuleError("that unit is not in this board's reinforcements")
    unit = UnitInstance(new_unit_id(), template_id, color, destination.to_key(), exhausted=True)
    board.units[unit.id] = unit
    game.log.append(f"{color.title()} spawned {game.template(template_id).name} on board {board.index + 1}.")
    return unit


def spawn_terrain(game: Game, color: str, board_index: int, source_id: str, terrain: str, q: int, r: int, via_spell: bool = False) -> None:
    ensure_turn(game, color)
    if terrain not in TERRAIN_LABELS:
        raise RuleError("unknown terrain")
    board = board_at(game, board_index)
    source = unit_at(board, source_id)
    if source.team != color:
        raise RuleError("terrain must be spawned by a friendly unit")
    if not via_spell:
        if game.phase != Phase.SPAWN.value:
            raise RuleError("terrain spawning is only available in spawn phase")
        _spawner_is_ready(game, board, source)
        if terrain not in game.template(source.template_id).terrain_spawn:
            raise RuleError("that unit cannot spawn this terrain")
    else:
        _spawner_is_ready(game, board, source, require_spawn=False)
    destination = Hex(q, r)
    if destination not in neighbors(Hex.from_key(source.hex)):
        raise RuleError("terrain destination must be adjacent")
    if not is_empty(game, board, destination):
        raise RuleError("terrain destination must be empty plain hex")
    board.terrain[terrain] = destination.to_key()
    game.log.append(f"{color.title()} moved {TERRAIN_LABELS[terrain]} to board {board.index + 1}.")


def move_unit(game: Game, color: str, board_index: int, unit_id: str, q: int, r: int) -> None:
    ensure_turn(game, color)
    if game.phase != Phase.MOVEMENT.value:
        raise RuleError("movement happens in the movement phase")
    board = board_at(game, board_index)
    unit = unit_at(board, unit_id)
    _note_action(board, unit.id)
    if unit.team != color:
        raise RuleError("cannot move enemy units")
    if unit.exhausted:
        raise RuleError("exhausted units cannot move")
    if unit.attacked:
        raise RuleError("units cannot move after attacking")
    stats = game.unit_stats(unit)
    if unit.movement_remaining is None:
        unit.movement_remaining = stats["speed"]
    if unit.movement_remaining <= 0:
        raise RuleError("no movement remaining")
    current = Hex.from_key(unit.hex)
    destination = Hex(q, r)
    if destination not in neighbors(current):
        raise RuleError("move one adjacent hex at a time")
    ok, reason = can_enter(game, board, unit, destination)
    if not ok:
        raise RuleError(reason)
    occupant = unit_on_hex(board, destination.to_key())
    if occupant and occupant.team == unit.team:
        occupant.hex = unit.hex
    unit.hex = destination.to_key()
    unit.moved = True
    unit.movement_remaining -= 1
    board.last_mover_id = unit.id
    game.log.append(f"{color.title()} moved {game.template(unit.template_id).name}.")


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
    if game.phase != Phase.MOVEMENT.value:
        raise RuleError("attacks happen in the movement phase")
    board = board_at(game, board_index)
    attacker = unit_at(board, attacker_id)
    target = unit_at(board, target_id)
    _note_action(board, attacker.id)
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
        _unsummon_unit(game, board, target)
        attacker.star_attacks_remaining -= 1
    else:
        total = int(attack_value)
        if stats["flurry"]:
            if attacker.flurry_remaining is None:
                attacker.flurry_remaining = total
            damage = amount or attacker.flurry_remaining
            if damage <= 0 or damage > attacker.flurry_remaining:
                raise RuleError("invalid flurry amount")
            attacker.flurry_remaining -= damage
        else:
            if attacker.attacked:
                raise RuleError("unit has already attacked")
            damage = total
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
    card = next((candidate for candidate in team.hand if candidate["cardId"] == card_id), None)
    if not card:
        raise RuleError("card is not in hand")
    spell_id = card["spellId"]
    spell = SPELLS[spell_id]
    if discarded and not spell.cantrip:
        team.hand.remove(card)
        team.mana += 1
        game.log.append(f"{color.title()} discarded {spell.name} for 1 mana.")
        return
    if spell.spawn_phase_only and game.phase != Phase.SPAWN.value:
        raise RuleError(f"{spell.name} can only be played in spawn phase")
    board = board_at(game, int(payload.get("board", 0)))
    target = unit_at(board, payload["targetId"]) if payload.get("targetId") else None
    if not discarded:
        _charge_spell(game, color, spell_id, target if target and target.team != color else None)
    _resolve_spell(game, color, board, spell_id, payload)
    team.hand.remove(card)
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
        _friendly_minion(game, color, board, target_id).effects.append(TimedEffect("Spawn", color, spawn=True))
    elif spell_id == "raise_zombie":
        target = _friendly_minion(game, color, board, target_id)
        spawn_reinforcement(game, color, board.index, target.id, "zombie", int(payload["q"]), int(payload["r"]), free=True, via_spell=True)
    else:
        raise RuleError("spell is not implemented")


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
    ok, reason = can_enter(game, board, target, destination, allow_friendly_swap=False)
    if not ok:
        raise RuleError(reason)
    target.hex = destination.to_key()
    target.exhausted = target.exhausted or exhaust


def _draw_turn_spells(game: Game, color: str) -> None:
    count = len(game.boards)
    game.teams[color].draw(count)
    game.log.append(f"{color.title()} drew {count} spell card(s), one per board.")


def draw_spell(game: Game, color: str) -> None:
    ensure_turn(game, color)
    raise RuleError("spell cards are drawn automatically at one card per board each turn")


def resign_board(game: Game, color: str, board_index: int) -> None:
    ensure_turn(game, color)
    board = board_at(game, board_index)
    board.resigned_by = color
    game.log.append(f"{color.title()} resigned board {board.index + 1}; it resolves at the start of {OPPONENT[color]}'s next turn.")


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
    for board in game.boards:
        if board.resigned_by == OPPONENT[color]:
            score_board(game, board, color, "opponent resignation")
            if game.winner:
                return
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
    start_turn_checks(game, game.turn)


def apply_action(game: Game, color: str, action: str, payload: dict) -> Optional[dict]:
    if action == "join":
        join_game(game, color, payload.get("name", ""))
    elif action == "set_phase":
        set_phase(game, color, payload["phase"])
    elif action == "buy":
        buy_reinforcement(game, color, int(payload.get("board", 0)), payload["templateId"])
    elif action == "research":
        return {"unit": research_unit(game, color).to_dict()}
    elif action == "spawn":
        unit = spawn_reinforcement(
            game,
            color,
            int(payload.get("board", 0)),
            payload["sourceId"],
            payload["templateId"],
            int(payload["q"]),
            int(payload["r"]),
        )
        return {"unitId": unit.id}
    elif action == "spawn_terrain":
        spawn_terrain(
            game,
            color,
            int(payload.get("board", 0)),
            payload["sourceId"],
            payload["terrain"],
            int(payload["q"]),
            int(payload["r"]),
        )
    elif action == "move":
        move_unit(game, color, int(payload.get("board", 0)), payload["unitId"], int(payload["q"]), int(payload["r"]))
    elif action == "attack":
        amount = int(payload["amount"]) if payload.get("amount") else None
        attack_unit(game, color, int(payload.get("board", 0)), payload["attackerId"], payload["targetId"], amount)
    elif action == "blink_unit":
        blink_unit(game, color, int(payload.get("board", 0)), payload["unitId"])
    elif action == "cast_spell":
        cast_spell(game, color, payload["cardId"], payload, discarded=False)
    elif action == "discard_spell":
        cast_spell(game, color, payload["cardId"], payload, discarded=True)
    elif action == "draw_spell":
        draw_spell(game, color)
    elif action == "resign_board":
        resign_board(game, color, int(payload.get("board", 0)))
    elif action == "end_turn":
        end_turn(game, color)
    else:
        raise RuleError("unknown action")
    return None
