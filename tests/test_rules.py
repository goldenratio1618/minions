import unittest

from minions.rules.constants import Phase, Terrain
from minions.rules.coords import Hex, neighbors, reflect_necromancer_axis
from minions.rules.game import apply_action, can_enter, create_game, end_turn, is_unit_spawn_destination, move_unit, research_unit, set_phase, unit_on_hex
from minions.rules.maps import generate_map
from minions.rules.units import ALPHA, BASE_UNITS, EXISTING_UNITS, UnitInstance, attack_for_power, generate_random_unit, predicted_expression


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
        self.assertEqual(BASE_UNITS["necromancer"].defense, 10)
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

    def test_resign_board_scores_now_and_resets_on_opponent_turn(self):
        game = create_game(board_count=2, seed=19)
        board = game.boards[0]
        original_necromancers = sorted(unit.id for unit in board.units.values() if unit.template_id == "necromancer")
        apply_action(game, "yellow", "resign_board", {"board": 0})
        self.assertEqual(game.scores["blue"], 1)
        self.assertIsNone(game.winner)
        self.assertEqual(board.winner, "blue")
        self.assertEqual(board.resigned_by, "yellow")
        self.assertEqual(sorted(unit.id for unit in board.units.values() if unit.template_id == "necromancer"), original_necromancers)

        end_turn(game, "yellow")
        reset_board = game.boards[0]
        self.assertEqual(game.turn, "blue")
        self.assertIsNone(reset_board.winner)
        self.assertIsNone(reset_board.resigned_by)
        self.assertNotEqual(sorted(unit.id for unit in reset_board.units.values() if unit.template_id == "necromancer"), original_necromancers)
        self.assertEqual(game.scores["blue"], 1)

    def test_resign_board_can_end_match_immediately(self):
        game = create_game(board_count=1, seed=20)
        apply_action(game, "yellow", "resign_board", {"board": 0})
        self.assertEqual(game.scores["blue"], 1)
        self.assertEqual(game.winner, "blue")

    def test_research_creates_extensible_template(self):
        game = create_game(board_count=1, seed=4)
        game.teams["yellow"].souls = 3
        unit = research_unit(game, "yellow")
        self.assertIn(unit.id, game.teams["yellow"].researched)

    def test_purchased_researched_unit_is_consumed(self):
        game = create_game(board_count=1, seed=4)
        game.teams["yellow"].souls = 10
        unit = research_unit(game, "yellow")
        game.teams["yellow"].souls = 10
        apply_action(game, "yellow", "buy", {"board": 0, "templateId": unit.id})
        self.assertNotIn(unit.id, game.teams["yellow"].researched)
        self.assertIn(unit.id, game.boards[0].reinforcements["yellow"])

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

    def test_blue_can_spawn_without_changing_phase_and_spawned_unit_is_exhausted(self):
        game = create_game(board_count=1, seed=12)
        board = game.boards[0]
        end_turn(game, "yellow")
        destination = None
        for source in board.units.values():
            if source.team != "blue":
                continue
            for candidate in neighbors(Hex.from_key(source.hex)):
                if is_unit_spawn_destination(game, board, candidate, BASE_UNITS["zombie"].to_dict()):
                    destination = candidate
                    break
            if destination:
                break
        self.assertIsNotNone(destination)
        result = apply_action(game, "blue", "spawn", {"board": 0, "templateId": "zombie", "q": destination.q, "r": destination.r})
        unit = board.units[result["unitId"]]
        self.assertTrue(unit.exhausted)
        self.assertEqual(unit.hex, destination.to_key())

    def test_reinforcements_can_spawn_on_graveyards_and_legal_terrain(self):
        game = create_game(board_count=1, seed=12)
        board = game.boards[0]
        end_turn(game, "yellow")
        spawner = None
        grave_destination = None
        for candidate in board.units.values():
            if candidate.team != "blue":
                continue
            destination = next((hex_ for hex_ in neighbors(Hex.from_key(candidate.hex)) if unit_on_hex(board, hex_.to_key()) is None), None)
            if destination:
                spawner = candidate
                grave_destination = destination
                break
        self.assertIsNotNone(spawner)
        self.assertIsNotNone(grave_destination)
        board.map.water.discard(grave_destination)
        board.map.graveyards.add(grave_destination)
        result = apply_action(game, "blue", "spawn", {"board": 0, "sourceId": spawner.id, "templateId": "zombie", "q": grave_destination.q, "r": grave_destination.r})
        self.assertEqual(board.units[result["unitId"]].hex, grave_destination.to_key())

        skeleton = next(unit for unit in EXISTING_UNITS if unit.id == "skeleton")
        game.unit_catalog[skeleton.id] = skeleton
        board.reinforcements["blue"].append(skeleton.id)
        terrain_spawner = None
        terrain_destination = None
        for candidate in board.units.values():
            if candidate.team != "blue" or candidate.exhausted:
                continue
            destination = next(
                (hex_ for hex_ in neighbors(Hex.from_key(candidate.hex)) if unit_on_hex(board, hex_.to_key()) is None and hex_ != grave_destination),
                None,
            )
            if destination:
                terrain_spawner = candidate
                terrain_destination = destination
                break
        self.assertIsNotNone(terrain_spawner)
        self.assertIsNotNone(terrain_destination)
        board.map.water.discard(terrain_destination)
        board.terrain[Terrain.FLOOD.value] = terrain_destination.to_key()
        result = apply_action(
            game,
            "blue",
            "spawn",
            {"board": 0, "sourceId": terrain_spawner.id, "templateId": skeleton.id, "q": terrain_destination.q, "r": terrain_destination.r},
        )
        self.assertEqual(board.units[result["unitId"]].hex, terrain_destination.to_key())

    def test_terrain_spawn_does_not_require_spawn_keyword(self):
        game = create_game(board_count=1, seed=16)
        board = game.boards[0]
        end_turn(game, "yellow")
        board.units.clear()
        board.map.water.clear()
        ghost = next(unit for unit in EXISTING_UNITS if unit.id == "ghost")
        game.unit_catalog[ghost.id] = ghost
        board.units["ghost"] = UnitInstance("ghost", ghost.id, "blue", "5,5")
        apply_action(game, "blue", "spawn_terrain", {"board": 0, "sourceId": "ghost", "terrain": Terrain.FLOOD.value, "q": 6, "r": 5})
        self.assertEqual(board.terrain[Terrain.FLOOD.value], "6,5")

    def test_friendly_units_are_pass_through_not_destinations(self):
        game = create_game(board_count=1, seed=13)
        board = game.boards[0]
        mover = None
        blocked_hex = None
        for candidate_mover in board.units.values():
            if candidate_mover.team != "yellow":
                continue
            empty_neighbor = next((hex_ for hex_ in neighbors(Hex.from_key(candidate_mover.hex)) if unit_on_hex(board, hex_.to_key()) is None), None)
            if empty_neighbor:
                mover = candidate_mover
                blocked_hex = empty_neighbor
                break
        self.assertIsNotNone(mover)
        blocker = next(unit for unit in board.units.values() if unit.team == "yellow" and unit.id != mover.id)
        blocker.hex = blocked_hex.to_key()
        blocked_hex = Hex.from_key(blocker.hex)
        self.assertTrue(can_enter(game, board, mover, blocked_hex, final=False)[0])
        self.assertFalse(can_enter(game, board, mover, blocked_hex, final=True)[0])

    def test_undo_and_redo_restore_turn_state(self):
        game = create_game(board_count=1, seed=14)
        board = game.boards[0]
        end_turn(game, "yellow")
        unit = next(unit for unit in board.units.values() if unit.team == "blue" and unit.template_id == "zombie")
        current = Hex.from_key(unit.hex)
        occupied = {unit.hex for unit in board.units.values()}
        destination = next(hex_ for hex_ in neighbors(current) if hex_.to_key() not in occupied and hex_ not in board.map.water)
        original_hex = unit.hex
        apply_action(game, "blue", "move", {"board": 0, "unitId": unit.id, "q": destination.q, "r": destination.r})
        self.assertEqual(unit.hex, destination.to_key())
        self.assertEqual(len(game.turn_history), 1)
        apply_action(game, "blue", "undo_unit", {"board": 0, "unitId": unit.id})
        restored = game.boards[0].units[unit.id]
        self.assertEqual(restored.hex, original_hex)
        self.assertTrue(game.redo_snapshot)
        apply_action(game, "blue", "redo", {})
        redone = game.boards[0].units[unit.id]
        self.assertEqual(redone.hex, destination.to_key())

    def test_undo_replays_later_legal_actions_and_skips_illegal_ones(self):
        game = create_game(board_count=1, seed=15)
        board = game.boards[0]
        end_turn(game, "yellow")
        board.units.clear()
        board.map.water.clear()
        unit_a = UnitInstance("a", "zombie", "blue", "5,5")
        unit_b = UnitInstance("b", "zombie", "blue", "5,6")
        unit_c = UnitInstance("c", "zombie", "blue", "7,7")
        board.units = {unit.id: unit for unit in (unit_a, unit_b, unit_c)}

        apply_action(game, "blue", "move", {"board": 0, "unitId": "a", "q": 6, "r": 5})
        apply_action(game, "blue", "move", {"board": 0, "unitId": "b", "q": 5, "r": 5})
        apply_action(game, "blue", "move", {"board": 0, "unitId": "c", "q": 7, "r": 6})

        apply_action(game, "blue", "undo_unit", {"board": 0, "unitId": "a"})

        self.assertEqual(game.boards[0].units["a"].hex, "5,5")
        self.assertEqual(game.boards[0].units["b"].hex, "5,6")
        self.assertEqual(game.boards[0].units["c"].hex, "7,6")
        self.assertEqual([action.unit_ids[0] for action in game.turn_history], ["c"])
        self.assertTrue(game.redo_snapshot)

    def test_moving_last_unit_spawner_undoes_dependent_spawn(self):
        game = create_game(board_count=1, seed=17)
        board = game.boards[0]
        end_turn(game, "yellow")
        board.units.clear()
        board.map.water.clear()
        board.reinforcements["blue"] = ["zombie"]
        board.units["spawner"] = UnitInstance("spawner", "zombie", "blue", "5,5")
        result = apply_action(game, "blue", "spawn", {"board": 0, "sourceId": "spawner", "templateId": "zombie", "q": 6, "r": 5})
        spawned_id = result["unitId"]
        apply_action(game, "blue", "move", {"board": 0, "unitId": "spawner", "q": 4, "r": 5})
        current_board = game.boards[0]
        self.assertNotIn(spawned_id, current_board.units)
        self.assertEqual(current_board.units["spawner"].hex, "4,5")
        self.assertEqual(current_board.reinforcements["blue"], ["zombie"])

    def test_moving_last_terrain_spawner_undoes_dependent_terrain(self):
        game = create_game(board_count=1, seed=18)
        board = game.boards[0]
        end_turn(game, "yellow")
        board.units.clear()
        board.map.water.clear()
        ghost = next(unit for unit in EXISTING_UNITS if unit.id == "ghost")
        game.unit_catalog[ghost.id] = ghost
        board.units["ghost"] = UnitInstance("ghost", ghost.id, "blue", "5,5")
        apply_action(game, "blue", "spawn_terrain", {"board": 0, "sourceId": "ghost", "terrain": Terrain.FLOOD.value, "q": 6, "r": 5})
        apply_action(game, "blue", "move", {"board": 0, "unitId": "ghost", "q": 4, "r": 5})
        current_board = game.boards[0]
        self.assertIsNone(current_board.terrain[Terrain.FLOOD.value])
        self.assertEqual(current_board.units["ghost"].hex, "4,5")


if __name__ == "__main__":
    unittest.main()
