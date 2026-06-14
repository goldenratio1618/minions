from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from minions.rules.constants import OPPONENT
from minions.rules.coords import Hex, distance
from minions.rules.game import Game
from minions.rules.units import UnitInstance, UnitTemplate, attack_for_power


@dataclass(frozen=True)
class EvaluationWeights:
    board_point: float = 5200.0
    match_win: float = 100000.0
    soul: float = 7.9
    mana: float = 2.4
    card: float = 4.5
    researched: float = 0.30
    reinforcement: float = 0.46
    material: float = 1.64
    graveyard: float = 80.0
    graveyard_next: float = 6.1
    enemy_necromancer_pressure: float = 7.6
    own_necromancer_danger: float = 8.1
    damage: float = 3.4
    spawn_network: float = 4.7
    activation: float = 0.35


DEFAULT_WEIGHTS = EvaluationWeights()


def evaluate_game(game: Game, color: str, weights: EvaluationWeights = DEFAULT_WEIGHTS) -> float:
    opponent = OPPONENT[color]
    if game.winner == color:
        return weights.match_win
    if game.winner == opponent:
        return -weights.match_win
    return _team_score(game, color, weights) - _team_score(game, opponent, weights)


def _team_score(game: Game, color: str, weights: EvaluationWeights) -> float:
    team = game.teams[color]
    score = game.scores[color] * weights.board_point
    card_count = sum(len(board.spells[color]) for board in game.boards)
    score += team.souls * weights.soul + team.mana * weights.mana + card_count * weights.card
    score += sum(unit_template_value(unit) * weights.researched for unit in team.researched.values())
    for board in game.boards:
        score += _board_team_score(game, board, color, weights)
    return score


def _board_team_score(game: Game, board, color: str, weights: EvaluationWeights) -> float:
    graveyard_keys = {hex_.to_key() for hex_ in board.map.graveyards}
    enemy_necro = _necromancer(board, OPPONENT[color])
    own_necro = _necromancer(board, color)
    score = 0.0
    for unit in board.units.values():
        if unit.team != color:
            continue
        score += unit_instance_value(game, unit) * weights.material
        if unit.hex in graveyard_keys:
            score += weights.graveyard
        score += _graveyard_proximity(board, unit) * weights.graveyard_next
        if game.unit_stats(unit)["spawn"]:
            score += weights.spawn_network
        if unit.moved and game.template(unit.template_id).minion:
            score += weights.activation
        if enemy_necro:
            score += max(0, 7 - distance(Hex.from_key(unit.hex), Hex.from_key(enemy_necro.hex))) * weights.enemy_necromancer_pressure
        score -= unit.damage * weights.damage

    for template_id in board.reinforcements[color]:
        score += unit_template_value(game.template(template_id)) * weights.reinforcement

    if own_necro:
        for enemy in board.units.values():
            if enemy.team == color:
                continue
            proximity = max(0, 6 - distance(Hex.from_key(enemy.hex), Hex.from_key(own_necro.hex)))
            score -= proximity * weights.own_necromancer_danger
    return score


def unit_template_value(template: UnitTemplate) -> float:
    attack = attack_for_power(template.attack)
    value = template.cost * 12 + template.rebate * 3
    value += attack * 6 + template.defense * 5 + template.speed * 8 + template.range * 9
    if template.spawn:
        value += 18
    if template.persistent:
        value += 12
    if template.blink:
        value += 8
    if template.flurry:
        value += 8
    if template.flying:
        value += 10
    if template.lumbering:
        value -= 7
    value += template.ward * 7
    value += len(template.terrain_spawn) * 4
    if not template.minion:
        value += 500
    return max(1.0, value)


def unit_instance_value(game: Game, unit: UnitInstance) -> float:
    value = unit_template_value(game.template(unit.template_id))
    stats = game.unit_stats(unit)
    value += max(0, stats["attackPower"] - attack_for_power(game.template(unit.template_id).attack)) * 5
    value += max(0, stats["defense"] - game.template(unit.template_id).defense) * 3
    if unit.exhausted:
        value -= 5
    if unit.attacked:
        value -= 2
    return value


def _graveyard_proximity(board, unit: UnitInstance) -> float:
    if not board.map.graveyards:
        return 0.0
    unit_hex = Hex.from_key(unit.hex)
    nearest = min(distance(unit_hex, graveyard) for graveyard in board.map.graveyards)
    return max(0.0, 7.0 - nearest)


def _necromancer(board, color: str) -> Optional[UnitInstance]:
    return next((unit for unit in board.units.values() if unit.team == color and unit.template_id == "necromancer"), None)
