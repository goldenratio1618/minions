from __future__ import annotations

import argparse
import random
import sys
import time
from dataclasses import fields, replace
from pathlib import Path
from typing import Optional


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from minions.ai.evaluation import DEFAULT_WEIGHTS, EvaluationWeights, evaluate_game
from minions.ai.player import play_turn
from minions.rules.game import create_game


def play_match(
    board_count: int,
    seed: int,
    yellow_weights: EvaluationWeights,
    blue_weights: EvaluationWeights,
    per_turn_seconds: float,
    max_turns: int,
) -> float:
    game = create_game(board_count=board_count, seed=seed)
    for _ in range(max_turns):
        if game.winner:
            break
        color = game.turn
        weights = yellow_weights if color == "yellow" else blue_weights
        play_turn(game, color, time_limit=per_turn_seconds, weights=weights, max_actions=120)
    if game.winner == "yellow":
        return 1.0
    if game.winner == "blue":
        return -1.0
    return max(-1.0, min(1.0, evaluate_game(game, "yellow", yellow_weights) / 10000.0))


def mutate(weights: EvaluationWeights, rng: random.Random, scale: float) -> EvaluationWeights:
    values = {}
    for field in fields(weights):
        value = getattr(weights, field.name)
        if field.name in ("match_win",):
            values[field.name] = value
            continue
        multiplier = max(0.1, rng.lognormvariate(0.0, scale))
        values[field.name] = value * multiplier
    return replace(weights, **values)


def evaluate_candidate(
    candidate: EvaluationWeights,
    baseline: EvaluationWeights,
    board_count: int,
    games: int,
    per_turn_seconds: float,
    max_turns: int,
    seed: int,
    deadline: Optional[float] = None,
) -> float:
    total = 0.0
    played = 0
    for index in range(games):
        if deadline is not None and time.monotonic() >= deadline:
            break
        game_seed = seed + index * 9973
        if index % 2 == 0:
            total += play_match(board_count, game_seed, candidate, baseline, per_turn_seconds, max_turns)
        else:
            total -= play_match(board_count, game_seed, baseline, candidate, per_turn_seconds, max_turns)
        played += 1
    return total / max(1, played)


def main() -> None:
    parser = argparse.ArgumentParser(description="Quick local tuning for the heuristic Minions AI.")
    parser.add_argument("--seconds", type=float, default=60.0)
    parser.add_argument("--games", type=int, default=4)
    parser.add_argument("--boards", type=int, default=1)
    parser.add_argument("--per-turn-seconds", type=float, default=0.2)
    parser.add_argument("--max-turns", type=int, default=80)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--scale", type=float, default=0.25)
    args = parser.parse_args()

    rng = random.Random(args.seed)
    baseline = DEFAULT_WEIGHTS
    best = baseline
    deadline = time.monotonic() + args.seconds
    best_score = evaluate_candidate(best, baseline, args.boards, args.games, args.per_turn_seconds, args.max_turns, args.seed, deadline)
    iteration = 0
    print(f"initial score={best_score:.3f} weights={best}")
    while time.monotonic() < deadline:
        iteration += 1
        candidate = mutate(best, rng, args.scale)
        score = evaluate_candidate(
            candidate,
            baseline,
            args.boards,
            args.games,
            args.per_turn_seconds,
            args.max_turns,
            args.seed + iteration * 100_000,
            deadline,
        )
        if score > best_score:
            best = candidate
            best_score = score
            print(f"new best iteration={iteration} score={best_score:.3f} weights={best}")
        else:
            print(f"checked iteration={iteration} score={score:.3f}")
    print(f"best score={best_score:.3f}")
    print(best)


if __name__ == "__main__":
    main()
