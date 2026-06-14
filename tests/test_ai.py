import unittest

from minions.ai.actions import legal_actions
from minions.ai.player import play_turn
from minions.rules.constants import Phase
from minions.rules.game import create_game, end_turn


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


if __name__ == "__main__":
    unittest.main()
