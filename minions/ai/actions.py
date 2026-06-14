from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence, Set

from minions.rules.constants import Phase, TERRAIN_LABELS
from minions.rules.coords import Hex, all_hexes, distance, neighbors
from minions.rules.game import (
    Game,
    RuleError,
    apply_action,
    is_empty,
    is_unit_spawn_destination,
    terrain_on_hex,
    unit_on_hex,
)
from minions.rules.spells import SPELLS
from minions.rules.units import effective_stats


@dataclass(frozen=True)
class ActionCandidate:
    action: str
    payload: dict
    category: str
    board: Optional[int] = None
    description: str = ""


def candidate_actions(
    game: Game,
    color: str,
    categories: Optional[Set[str]] = None,
    validate: bool = True,
) -> List[ActionCandidate]:
    """Return candidate actions for the active player.

    This is intentionally an AI-facing candidate generator, not a formal rules
    API. It generates plausible actions, then can dry-run them through the real
    reducer so the AI never relies on duplicated legality logic.
    """

    if game.winner or game.turn != color:
        return []
    raw: List[ActionCandidate] = []
    raw.extend(_economy_candidates(game, color, categories))
    raw.extend(_spawn_candidates(game, color, categories))
    raw.extend(_terrain_candidates(game, color, categories))
    raw.extend(_spell_candidates(game, color, categories))
    raw.extend(_movement_candidates(game, color, categories))
    raw.extend(_attack_candidates(game, color, categories))
    raw.extend(_blink_candidates(game, color, categories))
    if _wants(categories, "phase") and game.phase == Phase.SPAWN.value:
        raw.append(ActionCandidate("set_phase", {"phase": Phase.MOVEMENT.value}, "phase", description="enter movement"))
    if _wants(categories, "end"):
        raw.append(ActionCandidate("end_turn", {}, "end", description="end turn"))

    deduped = _dedupe(raw)
    if not validate:
        return deduped
    return [candidate for candidate in deduped if is_legal_action(game, color, candidate)]


def legal_actions(game: Game, color: str, categories: Optional[Set[str]] = None) -> List[ActionCandidate]:
    return candidate_actions(game, color, categories=categories, validate=True)


def is_legal_action(game: Game, color: str, candidate: ActionCandidate) -> bool:
    trial = copy.deepcopy(game)
    try:
        apply_action(trial, color, candidate.action, copy.deepcopy(candidate.payload), clear_redo=False)
    except (RuleError, KeyError, ValueError, TypeError):
        return False
    return True


def _wants(categories: Optional[Set[str]], category: str) -> bool:
    return categories is None or category in categories


def _dedupe(candidates: Sequence[ActionCandidate]) -> List[ActionCandidate]:
    seen = set()
    result = []
    for candidate in candidates:
        key = (candidate.action, _freeze(candidate.payload), candidate.category)
        if key in seen:
            continue
        seen.add(key)
        result.append(candidate)
    return result


def _freeze(value):
    if isinstance(value, dict):
        return tuple(sorted((key, _freeze(item)) for key, item in value.items()))
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def _friendly_units(board, color: str):
    return [unit for unit in board.units.values() if unit.team == color]


def _enemy_units(board, color: str):
    return [unit for unit in board.units.values() if unit.team != color]


def _is_minion(game: Game, unit) -> bool:
    return game.template(unit.template_id).minion


def _economy_candidates(game: Game, color: str, categories: Optional[Set[str]]) -> Iterable[ActionCandidate]:
    if not _wants(categories, "economy") or game.phase != Phase.SPAWN.value:
        return []
    team = game.teams[color]
    candidates: List[ActionCandidate] = []
    if team.souls >= 1:
        candidates.append(ActionCandidate("research", {}, "economy", description="research a minion"))
    buyable = ["zombie"] + sorted(team.researched.keys())
    for board in game.boards:
        for template_id in buyable:
            template = game.template(template_id)
            if team.souls >= template.cost:
                candidates.append(
                    ActionCandidate(
                        "buy",
                        {"board": board.index, "templateId": template_id},
                        "economy",
                        board.index,
                        f"buy {template.name}",
                    )
                )
    return candidates


def _spawn_candidates(game: Game, color: str, categories: Optional[Set[str]]) -> Iterable[ActionCandidate]:
    if not _wants(categories, "spawn") or game.phase != Phase.SPAWN.value:
        return []
    candidates: List[ActionCandidate] = []
    for board in game.boards:
        if board.spawn_locked.get(color):
            continue
        reinforcement_ids = sorted(set(board.reinforcements[color]))
        if not reinforcement_ids:
            continue
        sources = [
            unit
            for unit in _friendly_units(board, color)
            if not unit.exhausted and game.unit_stats(unit)["spawn"]
        ]
        for template_id in reinforcement_ids:
            stats = effective_stats(game.template(template_id), [])
            for source in sources:
                for destination in neighbors(Hex.from_key(source.hex)):
                    if not is_unit_spawn_destination(game, board, destination, stats):
                        continue
                    candidates.append(
                        ActionCandidate(
                            "spawn",
                            {
                                "board": board.index,
                                "sourceId": source.id,
                                "templateId": template_id,
                                "q": destination.q,
                                "r": destination.r,
                            },
                            "spawn",
                            board.index,
                            f"spawn {game.template(template_id).name}",
                        )
                    )
    return candidates


def _terrain_candidates(game: Game, color: str, categories: Optional[Set[str]]) -> Iterable[ActionCandidate]:
    if not _wants(categories, "terrain") or game.phase != Phase.SPAWN.value:
        return []
    candidates: List[ActionCandidate] = []
    for board in game.boards:
        for source in _friendly_units(board, color):
            if source.exhausted:
                continue
            for terrain in game.unit_stats(source)["terrainSpawn"]:
                for destination in neighbors(Hex.from_key(source.hex)):
                    if not is_empty(game, board, destination):
                        continue
                    candidates.append(
                        ActionCandidate(
                            "spawn_terrain",
                            {
                                "board": board.index,
                                "sourceId": source.id,
                                "terrain": terrain,
                                "q": destination.q,
                                "r": destination.r,
                            },
                            "terrain",
                            board.index,
                            f"spawn {TERRAIN_LABELS[terrain]}",
                        )
                    )
    return candidates


def _movement_candidates(game: Game, color: str, categories: Optional[Set[str]]) -> Iterable[ActionCandidate]:
    if not _wants(categories, "move") or game.phase != Phase.MOVEMENT.value:
        return []
    candidates: List[ActionCandidate] = []
    hexes = all_hexes()
    for board in game.boards:
        for unit in _friendly_units(board, color):
            if unit.exhausted or unit.attacked:
                continue
            stats = game.unit_stats(unit)
            max_steps = stats["speed"] if unit.movement_remaining is None else unit.movement_remaining
            if max_steps <= 0:
                continue
            current = Hex.from_key(unit.hex)
            for destination in hexes:
                if destination == current or distance(current, destination) > max_steps:
                    continue
                if unit_on_hex(board, destination.to_key()) is not None:
                    continue
                candidates.append(
                    ActionCandidate(
                        "move",
                        {"board": board.index, "unitId": unit.id, "q": destination.q, "r": destination.r},
                        "move",
                        board.index,
                        f"move {game.template(unit.template_id).name}",
                    )
                )
    return candidates


def _attack_candidates(game: Game, color: str, categories: Optional[Set[str]]) -> Iterable[ActionCandidate]:
    if not _wants(categories, "attack") or game.phase != Phase.MOVEMENT.value:
        return []
    candidates: List[ActionCandidate] = []
    for board in game.boards:
        enemies = _enemy_units(board, color)
        for attacker in _friendly_units(board, color):
            if attacker.exhausted:
                continue
            stats = game.unit_stats(attacker)
            if stats["lumbering"] and attacker.moved:
                continue
            if not stats["flurry"] and attacker.attacked:
                continue
            if stats["flurry"] and attacker.flurry_remaining == 0:
                continue
            if stats["attack"] in ("*", "**") and attacker.star_attacks_remaining == 0:
                continue
            for target in enemies:
                if distance(Hex.from_key(attacker.hex), Hex.from_key(target.hex)) > stats["range"]:
                    continue
                payload = {"board": board.index, "attackerId": attacker.id, "targetId": target.id}
                if stats["flurry"] and isinstance(stats["attack"], int):
                    remaining = attacker.flurry_remaining if attacker.flurry_remaining is not None else int(stats["attack"])
                    lethal = max(1, game.unit_stats(target)["defense"] - target.damage)
                    for amount in sorted({1, min(remaining, lethal), remaining}):
                        if 0 < amount <= remaining:
                            candidates.append(
                                ActionCandidate(
                                    "attack",
                                    {**payload, "amount": amount},
                                    "attack",
                                    board.index,
                                    f"attack for {amount}",
                                )
                            )
                else:
                    candidates.append(ActionCandidate("attack", payload, "attack", board.index, "attack"))
    return candidates


def _blink_candidates(game: Game, color: str, categories: Optional[Set[str]]) -> Iterable[ActionCandidate]:
    if not _wants(categories, "blink") or game.phase != Phase.MOVEMENT.value:
        return []
    candidates: List[ActionCandidate] = []
    for board in game.boards:
        for unit in _friendly_units(board, color):
            if game.unit_stats(unit)["blink"] and game.template(unit.template_id).minion:
                candidates.append(
                    ActionCandidate(
                        "blink_unit",
                        {"board": board.index, "unitId": unit.id},
                        "blink",
                        board.index,
                        f"blink {game.template(unit.template_id).name}",
                    )
                )
    return candidates


def _spell_candidates(game: Game, color: str, categories: Optional[Set[str]]) -> Iterable[ActionCandidate]:
    if not (_wants(categories, "spell") or _wants(categories, "discard")):
        return []
    candidates: List[ActionCandidate] = []
    for board in game.boards:
        for card in list(board.spells[color]):
            spell = SPELLS[card["spellId"]]
            if spell.spawn_phase_only and game.phase != Phase.SPAWN.value:
                continue
            if _wants(categories, "discard") and not spell.cantrip:
                candidates.append(
                    ActionCandidate(
                        "discard_spell",
                        {"board": board.index, "cardId": card["cardId"]},
                        "discard",
                        board.index,
                        f"discard {spell.name}",
                    )
                )
            payloads = _spell_payloads(game, color, board, card)
            if _wants(categories, "spell"):
                for payload in payloads:
                    candidates.append(
                        ActionCandidate(
                            "cast_spell",
                            payload,
                            "spell",
                            board.index,
                            f"cast {spell.name}",
                        )
                    )
            if _wants(categories, "discard") and spell.cantrip:
                for payload in payloads:
                    candidates.append(
                        ActionCandidate(
                            "discard_spell",
                            payload,
                            "discard",
                            board.index,
                            f"discard/cantrip {spell.name}",
                        )
                    )
    return candidates


def _spell_payloads(game: Game, color: str, board, card: dict) -> List[dict]:
    spell_id = card["spellId"]
    payloads: List[dict] = []
    friendly = _friendly_units(board, color)
    enemies = _enemy_units(board, color)
    friendly_minions = [unit for unit in friendly if _is_minion(game, unit)]
    enemy_minions = [unit for unit in enemies if _is_minion(game, unit)]
    damaged_enemy_minions = [unit for unit in enemy_minions if unit.damage > 0]

    def base(**items):
        return {"board": board.index, "cardId": card["cardId"], **items}

    if spell_id in ("fester", "unsummon", "dismember"):
        payloads.extend(base(targetId=target.id) for target in damaged_enemy_minions)
    elif spell_id in ("stumble", "double_stumble"):
        max_distance = 2 if spell_id == "double_stumble" else 1
        for target in damaged_enemy_minions:
            for destination in _hexes_within(Hex.from_key(target.hex), max_distance):
                if destination.to_key() == target.hex:
                    continue
                payloads.append(base(targetId=target.id, q=destination.q, r=destination.r))
    elif spell_id in ("shield", "persistent", "critical_hit", "spawn"):
        payloads.extend(base(targetId=target.id) for target in friendly_minions)
    elif spell_id == "reposition":
        for target in friendly_minions:
            for destination in neighbors(Hex.from_key(target.hex)):
                payloads.append(base(targetId=target.id, q=destination.q, r=destination.r))
    elif spell_id in ("weaken", "freeze_ray", "lumbering", "shackle"):
        payloads.extend(base(targetId=target.id) for target in enemy_minions)
    elif spell_id == "blink":
        payloads.extend(base(targetId=target.id) for target in friendly_minions)
    elif spell_id in ("firestorm", "earthquake", "flood", "whirlwind"):
        for target in friendly:
            for destination in neighbors(Hex.from_key(target.hex)):
                payloads.append(base(targetId=target.id, q=destination.q, r=destination.r))
    elif spell_id == "terraform":
        for target in friendly:
            for terrain in TERRAIN_LABELS:
                for destination in neighbors(Hex.from_key(target.hex)):
                    payloads.append(base(targetId=target.id, terrain=terrain, q=destination.q, r=destination.r))
    elif spell_id == "normalize":
        for terrain, hex_key in board.terrain.items():
            if not hex_key:
                continue
            hex_ = Hex.from_key(hex_key)
            payloads.append(base(terrain=terrain, q=hex_.q, r=hex_.r))
        for hex_ in all_hexes():
            terrain = terrain_on_hex(board, hex_.to_key())
            if terrain:
                payloads.append(base(terrain=terrain, q=hex_.q, r=hex_.r))
    elif spell_id == "lesser_spawn":
        reinforcement_ids = sorted(set(board.reinforcements[color]))
        for target in friendly_minions:
            for template_id in reinforcement_ids:
                for destination in neighbors(Hex.from_key(target.hex)):
                    payloads.append(base(targetId=target.id, templateId=template_id, q=destination.q, r=destination.r))
    elif spell_id == "raise_zombie":
        for target in friendly_minions:
            for destination in neighbors(Hex.from_key(target.hex)):
                payloads.append(base(targetId=target.id, q=destination.q, r=destination.r))
    return payloads


def _hexes_within(center: Hex, max_distance: int) -> List[Hex]:
    return [hex_ for hex_ in all_hexes() if distance(center, hex_) <= max_distance]
