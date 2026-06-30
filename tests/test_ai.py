import unittest

from minions.ai.actions import ActionCandidate, legal_actions
from minions.ai.player import TurnResult, _apply, play_turn
from minions.rules.constants import Phase
from minions.rules.game import GAME_MODE_SUBSCRIPTIONS, RESEARCH_COST, create_game, end_turn


class AITests(unittest.TestCase):
    def test_legal_actions_include_core_turn_options(self):
        game = create_game(board_count=1, seed=101)
        end_turn(game, "yellow")

        economy = legal_actions(game, "blue", categories={"economy"})
        spawns = legal_actions(game, "blue", categories={"spawn"})
        phase = legal_actions(game, "blue", categories={"phase"})

        self.assertTrue(any(action.action == "buy" for action in economy))
        self.assertTrue(any(action.action == "spawn" for action in spawns))
        self.assertTrue(any(action.action == "set_phase" for action in phase))

    def test_ai_plays_a_complete_turn(self):
        game = create_game(board_count=1, seed=102)
        result = play_turn(game, "yellow", time_limit=0.5)

        self.assertEqual(game.turn, "blue")
        self.assertGreaterEqual(len(result.actions), 1)
        self.assertEqual(result.actions[-1]["action"], "end_turn")

    def test_ai_can_play_multiple_turns_without_rule_errors(self):
        game = create_game(board_count=2, seed=103)
        for _ in range(4):
            color = game.turn
            result = play_turn(game, color, time_limit=0.5)
            self.assertGreaterEqual(len(result.actions), 1)
            self.assertIn(game.phase, (Phase.SPAWN.value, Phase.MOVEMENT.value))
            if game.winner:
                break

    def test_blue_ai_moves_starting_units_after_opening_spawn(self):
        for seed in (100, 102, 104):
            game = create_game(board_count=1, seed=seed)
            play_turn(game, "yellow", time_limit=3.0)

            result = play_turn(game, "blue", time_limit=3.0)
            moves = [action for action in result.actions if action["action"] == "move"]

            self.assertGreaterEqual(len(moves), 1)

    def test_ai_actions_do_not_keep_undo_snapshots(self):
        game = create_game(board_count=1, seed=106)
        game.teams["yellow"].souls = RESEARCH_COST
        candidate = ActionCandidate("research", {}, "economy")

        self.assertTrue(_apply(game, "yellow", candidate, TurnResult("yellow")))

        self.assertTrue(game.turn_history)
        self.assertTrue(all(action.before is None for action in game.turn_history))

    def test_ai_can_research_and_subscribe_in_subscriptions_mode(self):
        game = create_game(board_count=1, seed=107, mode=GAME_MODE_SUBSCRIPTIONS, subscription_length=5)
        end_turn(game, "yellow")

        result = play_turn(game, "blue", time_limit=1.0)

        actions = [action["action"] for action in result.actions]
        self.assertIn("research", actions)
        self.assertIn("subscribe", actions)


if __name__ == "__main__":
    unittest.main()
