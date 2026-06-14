from __future__ import annotations

import copy
import time
from dataclasses import dataclass, field
from typing import List, Optional, Set, Tuple

from minions.ai.actions import ActionCandidate, candidate_actions
from minions.ai.evaluation import DEFAULT_WEIGHTS, EvaluationWeights, evaluate_game, unit_template_value
from minions.rules.constants import Phase
from minions.rules.game import Game, RuleError, apply_action


@dataclass
class TurnResult:
    color: str
    actions: List[dict] = field(default_factory=list)
    score_before: float = 0.0
    score_after: float = 0.0
    elapsed_seconds: float = 0.0
    timed_out: bool = False

    def to_dict(self) -> dict:
        return {
            "color": self.color,
            "actions": list(self.actions),
            "scoreBefore": self.score_before,
            "scoreAfter": self.score_after,
            "elapsedSeconds": self.elapsed_seconds,
            "timedOut": self.timed_out,
        }


def play_turn(
    game: Game,
    color: str,
    time_limit: float = 55.0,
    weights: EvaluationWeights = DEFAULT_WEIGHTS,
    max_actions: int = 220,
) -> TurnResult:
    """Play one complete AI turn by mutating ``game``.

    The AI always keeps the existing reducer as the authority. Candidate actions
    are scored by applying them to a deep copy, and only the selected candidate
    is applied to the real game.
    """

    if game.turn != color:
        raise RuleError(f"it is {game.turn}'s turn")
    start = time.monotonic()
    deadline = start + max(0.1, time_limit)
    result = TurnResult(color=color, score_before=evaluate_game(game, color, weights))

    try:
        if game.phase == Phase.SPAWN.value:
            _run_economy(game, color, result, weights, deadline, max_actions)
            _greedy_loop(
                game,
                color,
                result,
                weights,
                deadline,
                {"discard", "spell", "spawn", "terrain"},
                max_actions=max_actions,
                min_delta=0.25,
            )
            if _has_time(deadline) and game.phase == Phase.SPAWN.value:
                _apply(game, color, ActionCandidate("set_phase", {"phase": Phase.MOVEMENT.value}, "phase"), result)

        _greedy_loop(
            game,
            color,
            result,
            weights,
            deadline,
            {"attack", "discard", "spell", "move", "blink"},
            max_actions=max_actions,
            min_delta=0.2,
        )
    finally:
        if game.turn == color and not game.winner:
            try:
                _apply(game, color, ActionCandidate("end_turn", {}, "end"), result)
            except RuleError:
                pass
        result.elapsed_seconds = time.monotonic() - start
        result.score_after = evaluate_game(game, color, weights)
        result.timed_out = time.monotonic() >= deadline
    return result


def _run_economy(
    game: Game,
    color: str,
    result: TurnResult,
    weights: EvaluationWeights,
    deadline: float,
    max_actions: int,
) -> None:
    while _has_time(deadline) and len(result.actions) < max_actions and game.phase == Phase.SPAWN.value:
        team = game.teams[color]
        candidate = _best_buy(game, color)
        if candidate and _apply(game, color, candidate, result):
            continue
        should_research = (
            team.souls >= 1
            and len(team.researched) < _target_research_count(game)
            and (team.souls == 1 or team.souls >= 3)
        )
        if should_research:
            if _apply(game, color, ActionCandidate("research", {}, "economy", description="research"), result):
                continue
        break


def _best_buy(game: Game, color: str) -> Optional[ActionCandidate]:
    team = game.teams[color]
    board_order = sorted(game.boards, key=lambda board: _board_priority(game, color, board), reverse=True)

    best_researched: Optional[Tuple[float, ActionCandidate]] = None
    for template in team.researched.values():
        if team.souls < template.cost:
            continue
        for board in board_order:
            score = unit_template_value(template) / max(1, template.cost) + _board_priority(game, color, board)
            candidate = ActionCandidate(
                "buy",
                {"board": board.index, "templateId": template.id},
                "economy",
                board.index,
                f"buy {template.name}",
            )
            if best_researched is None or score > best_researched[0]:
                best_researched = (score, candidate)
    if best_researched:
        return best_researched[1]

    if team.souls >= 2:
        for board in board_order:
            if len(board.reinforcements[color]) <= 2:
                return ActionCandidate(
                    "buy",
                    {"board": board.index, "templateId": "zombie"},
                    "economy",
                    board.index,
                    "buy Zombie",
                )
        if team.souls >= 4 and board_order:
            board = board_order[0]
            return ActionCandidate(
                "buy",
                {"board": board.index, "templateId": "zombie"},
                "economy",
                board.index,
                "buy Zombie",
            )
    return None


def _target_research_count(game: Game) -> int:
    if game.turn_number <= 4:
        return 1
    if game.turn_number <= 10:
        return 2
    return 3


def _board_priority(game: Game, color: str, board) -> float:
    graveyard_keys = {hex_.to_key() for hex_ in board.map.graveyards}
    own_graves = sum(1 for unit in board.units.values() if unit.team == color and unit.hex in graveyard_keys)
    enemy_graves = sum(1 for unit in board.units.values() if unit.team != color and unit.hex in graveyard_keys)
    own_units = sum(1 for unit in board.units.values() if unit.team == color)
    enemy_units = sum(1 for unit in board.units.values() if unit.team != color)
    return (enemy_graves - own_graves) * 7 + (enemy_units - own_units) * 1.5 - len(board.reinforcements[color])


def _greedy_loop(
    game: Game,
    color: str,
    result: TurnResult,
    weights: EvaluationWeights,
    deadline: float,
    categories: Set[str],
    max_actions: int,
    min_delta: float,
) -> None:
    while _has_time(deadline) and len(result.actions) < max_actions and game.turn == color and not game.winner:
        current_score = evaluate_game(game, color, weights)
        setup_discard = _best_discard_setup(game, color, weights, deadline, current_score, categories)
        if setup_discard and _apply(game, color, setup_discard, result):
            continue
        best_candidate: Optional[ActionCandidate] = None
        best_score = current_score
        for candidate in candidate_actions(game, color, categories=categories, validate=False):
            if not _has_time(deadline):
                break
            score = _score_candidate(game, color, candidate, weights)
            if score is None:
                continue
            score -= _action_penalty(candidate)
            if score > best_score + min_delta:
                best_score = score
                best_candidate = candidate
        if best_candidate is None:
            break
        if not _apply(game, color, best_candidate, result):
            break


def _best_discard_setup(
    game: Game,
    color: str,
    weights: EvaluationWeights,
    deadline: float,
    current_score: float,
    categories: Set[str],
) -> Optional[ActionCandidate]:
    if "discard" not in categories or "spell" not in categories:
        return None
    best_discard: Optional[ActionCandidate] = None
    best_score = current_score
    for discard in candidate_actions(game, color, categories={"discard"}, validate=False):
        if not _has_time(deadline):
            break
        trial = copy.deepcopy(game)
        try:
            apply_action(trial, color, discard.action, copy.deepcopy(discard.payload), clear_redo=False)
        except (RuleError, KeyError, ValueError, TypeError):
            continue
        for spell in candidate_actions(trial, color, categories={"spell"}, validate=False):
            if not _has_time(deadline):
                break
            score = _score_candidate(trial, color, spell, weights)
            if score is None:
                continue
            score -= _action_penalty(discard) + _action_penalty(spell)
            if score > best_score + 0.75:
                best_score = score
                best_discard = discard
    return best_discard


def _score_candidate(
    game: Game,
    color: str,
    candidate: ActionCandidate,
    weights: EvaluationWeights,
) -> Optional[float]:
    trial = copy.deepcopy(game)
    try:
        apply_action(trial, color, candidate.action, copy.deepcopy(candidate.payload), clear_redo=False)
    except (RuleError, KeyError, ValueError, TypeError):
        return None
    return evaluate_game(trial, color, weights)


def _action_penalty(candidate: ActionCandidate) -> float:
    return {
        "move": 0.05,
        "attack": 0.02,
        "spell": 0.25,
        "discard": 1.5,
        "spawn": 0.05,
        "terrain": 0.4,
        "blink": 2.0,
    }.get(candidate.category, 0.0)


def _apply(game: Game, color: str, candidate: ActionCandidate, result: TurnResult) -> bool:
    try:
        apply_action(game, color, candidate.action, copy.deepcopy(candidate.payload))
    except RuleError:
        return False
    result.actions.append(
        {
            "action": candidate.action,
            "category": candidate.category,
            "board": candidate.board,
            "payload": copy.deepcopy(candidate.payload),
            "description": candidate.description,
        }
    )
    return True


def _has_time(deadline: float) -> bool:
    return time.monotonic() < deadline
