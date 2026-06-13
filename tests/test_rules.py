import unittest

from minions.rules.constants import Phase
from minions.rules.coords import Hex, neighbors, reflect_necromancer_axis
from minions.rules.game import create_game, end_turn, move_unit, research_unit, set_phase
from minions.rules.maps import generate_map
from minions.rules.units import ALPHA, EXISTING_UNITS, attack_for_power, generate_random_unit, predicted_expression


class MapGeneratorTests(unittest.TestCase):
    def test_map_must_rules(self):
        for seed in range(100):
            board_map = generate_map(seed=seed)
            spawn_hexes = set(board_map.spawn_tiles["yellow"] + board_map.spawn_tiles["blue"])
            self.assertEqual(len(board_map.graveyards), 10)
            self.assertTrue(board_map.is_symmetric())
            self.assertFalse(board_map.water & spawn_hexes)
            self.assertFalse(board_map.water & board_map.graveyards)
            self.assertGreaterEqual(board_map.graveyards_near_spawns(), 2)
            self.assertTrue(board_map.graveyards_are_separated())
            self.assertTrue(board_map.graveyards_connect_to_necromancers())
            self.assertEqual(board_map.spawn_centers["yellow"].to_key(), "1,8")
            self.assertEqual(board_map.spawn_centers["blue"].to_key(), "8,1")
            self.assertLessEqual(len(board_map.water), 10)
            self.assertEqual(reflect_necromancer_axis(board_map.spawn_centers["yellow"]), board_map.spawn_centers["blue"])


class UnitGeneratorTests(unittest.TestCase):
    def test_alpha_and_costs_are_sane(self):
        self.assertGreater(ALPHA, 0)
        self.assertEqual(attack_for_power("*"), 2)
        self.assertEqual(attack_for_power("**"), 4)
        unit = generate_random_unit(seed=7)
        self.assertGreaterEqual(unit.cost, 1)
        self.assertGreaterEqual(unit.rebate, 0)
        self.assertLess(unit.rebate, unit.cost)
        self.assertGreater(predicted_expression(unit), 0)

    def test_sorcerer_auxiliary_stats(self):
        sorcerer = next(unit for unit in EXISTING_UNITS if unit.id == "sorcerer")
        self.assertTrue(sorcerer.flurry)
        self.assertTrue(sorcerer.blink)
        self.assertTrue(sorcerer.persistent)

    def test_generated_cost_rebate_is_locally_refined(self):
        for seed in range(25):
            unit = generate_random_unit(seed=seed)
            target = predicted_expression(unit)
            current = abs(unit.cost * unit.cost - unit.rebate * unit.rebate - target)
            for cost, rebate in (
                (unit.cost + 1, unit.rebate),
                (unit.cost - 1, unit.rebate),
                (unit.cost, unit.rebate + 1),
                (unit.cost, unit.rebate - 1),
            ):
                if cost >= 1 and 0 <= rebate < cost:
                    candidate = abs(cost * cost - rebate * rebate - target)
                    self.assertGreaterEqual(candidate, current)


class GameplayTests(unittest.TestCase):
    def test_create_game_and_end_turn_income(self):
        game = create_game(board_count=2, seed=3)
        self.assertEqual(game.turn, "yellow")
        self.assertEqual(game.teams["blue"].souls, 8)
        self.assertEqual(game.boards[0].reinforcements["yellow"], ["zombie"])
        self.assertEqual(game.boards[0].reinforcements["blue"], ["zombie"])
        self.assertEqual(len(game.teams["yellow"].hand), 2)
        self.assertEqual(len(game.teams["blue"].hand), 0)
        end_turn(game, "yellow")
        self.assertEqual(game.turn, "blue")
        self.assertEqual(game.phase, Phase.SPAWN.value)
        self.assertEqual(len(game.teams["blue"].hand), 2)
        self.assertGreaterEqual(game.teams["yellow"].souls, 6)

    def test_research_creates_extensible_template(self):
        game = create_game(board_count=1, seed=4)
        game.teams["yellow"].souls = 3
        unit = research_unit(game, "yellow")
        self.assertIn(unit.id, game.teams["yellow"].researched)

    def test_movement_is_adjacent(self):
        game = create_game(board_count=1, seed=8)
        board = game.boards[0]
        end_turn(game, "yellow")
        set_phase(game, "blue", "movement")
        unit = next(unit for unit in board.units.values() if unit.team == "blue" and unit.template_id == "zombie")
        current = Hex.from_key(unit.hex)
        occupied = {unit.hex for unit in board.units.values()}
        destination = next(hex_ for hex_ in neighbors(current) if hex_.to_key() not in occupied and hex_ not in board.map.water)
        move_unit(game, "blue", 0, unit.id, destination.q, destination.r)
        self.assertEqual(unit.hex, destination.to_key())


if __name__ == "__main__":
    unittest.main()
