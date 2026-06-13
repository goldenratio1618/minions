from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Callable, Dict, Iterable, List, Optional, Set

from .constants import BOARD_SIZE, TERRAIN_LABELS, Terrain
from .coords import (
    Hex,
    all_hexes,
    as_keys,
    blue_spawn_center,
    distance,
    neighbors,
    reflect_long_axis,
    rotate_180,
    spawn_cluster,
    yellow_spawn_center,
)


Symmetry = Callable[[Hex], Hex]


@dataclass
class BoardMap:
    water: Set[Hex]
    graveyards: Set[Hex]
    spawn_tiles: Dict[str, List[Hex]]
    spawn_centers: Dict[str, Hex]
    symmetry: str
    terrain: Dict[str, Optional[Hex]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for terrain in Terrain:
            self.terrain.setdefault(terrain.value, None)

    def occupied_static(self) -> Set[Hex]:
        blocked = set(self.water) | set(self.graveyards)
        for tiles in self.spawn_tiles.values():
            blocked.update(tiles)
        blocked.update(hex_ for hex_ in self.terrain.values() if hex_ is not None)
        return blocked

    def is_symmetric(self) -> bool:
        fn = rotate_180 if self.symmetry == "rotational" else reflect_long_axis
        for collection in (self.water, self.graveyards):
            if {fn(hex_) for hex_ in collection} != collection:
                return False
        return True

    def graveyards_near_spawns(self) -> int:
        spawn_hexes = set(self.spawn_tiles["yellow"] + self.spawn_tiles["blue"])
        return sum(1 for gy in self.graveyards if any(distance(gy, spawn) <= 1 for spawn in spawn_hexes))

    def graveyards_are_separated(self) -> bool:
        for graveyard in self.graveyards:
            if any(neighbor in self.graveyards for neighbor in neighbors(graveyard)):
                return False
        return True

    def graveyards_connect_to_necromancers(self) -> bool:
        for center in self.spawn_centers.values():
            if not self.graveyards <= _reachable_without_water({center}, self.water):
                return False
        return True

    def to_dict(self) -> dict:
        return {
            "size": BOARD_SIZE,
            "water": as_keys(self.water),
            "graveyards": as_keys(self.graveyards),
            "spawnTiles": {team: as_keys(hexes) for team, hexes in self.spawn_tiles.items()},
            "spawnCenters": {team: hex_.to_key() for team, hex_ in self.spawn_centers.items()},
            "symmetry": self.symmetry,
            "terrain": {kind: (hex_.to_key() if hex_ else None) for kind, hex_ in self.terrain.items()},
            "terrainLabels": TERRAIN_LABELS,
        }


def _pair_allowed(pair: Set[Hex], target: Set[Hex], forbidden: Set[Hex], separated: bool) -> bool:
    if pair & forbidden or pair & target:
        return False
    if not separated:
        return True
    pair_list = list(pair)
    for index, hex_ in enumerate(pair_list):
        if any(distance(hex_, other) <= 1 for other in pair_list[index + 1 :]):
            return False
        if any(distance(hex_, other) <= 1 for other in target):
            return False
    return True


def _symmetric_add(target: Set[Hex], hex_: Hex, symmetry: Symmetry, forbidden: Set[Hex], separated: bool = False) -> bool:
    partner = symmetry(hex_)
    pair = {hex_, partner}
    if not _pair_allowed(pair, target, forbidden, separated):
        return False
    target.update(pair)
    return True


def _trim_to_count(target: Set[Hex], count: int, symmetry: Symmetry, rng: random.Random) -> Set[Hex]:
    while len(target) > count:
        hex_ = rng.choice(sorted(target))
        target.discard(hex_)
        target.discard(symmetry(hex_))
    return target


def _fill_symmetric(
    target: Set[Hex],
    count: int,
    symmetry: Symmetry,
    forbidden: Set[Hex],
    rng: random.Random,
    separated: bool = False,
) -> Set[Hex]:
    candidates = all_hexes()
    rng.shuffle(candidates)
    for hex_ in candidates:
        if len(target) >= count:
            break
        partner = symmetry(hex_)
        pair = {hex_, partner}
        if len(target | pair) > count:
            continue
        if not _pair_allowed(pair, target, forbidden, separated):
            continue
        target.update(pair)
    return target


def _reachable_without_water(starts: Set[Hex], water: Set[Hex]) -> Set[Hex]:
    frontier = [start for start in starts if start not in water]
    seen = set(frontier)
    while frontier:
        hex_ = frontier.pop()
        for neighbor in neighbors(hex_):
            if neighbor in water or neighbor in seen:
                continue
            seen.add(neighbor)
            frontier.append(neighbor)
    return seen


def _spawn_data() -> tuple[Dict[str, List[Hex]], Dict[str, Hex]]:
    yellow_center = yellow_spawn_center()
    blue_center = blue_spawn_center()
    return (
        {
            "yellow": spawn_cluster(yellow_center),
            "blue": spawn_cluster(blue_center),
        },
        {
            "yellow": yellow_center,
            "blue": blue_center,
        },
    )


def generate_map(seed: Optional[int] = None) -> BoardMap:
    rng = random.Random(seed)
    spawn_tiles, spawn_centers = _spawn_data()
    spawn_hexes = set(spawn_tiles["yellow"] + spawn_tiles["blue"])
    symmetry_name, symmetry = rng.choice(
        [
            ("rotational", rotate_180),
            ("reflectional", reflect_long_axis),
        ]
    )

    graveyards: Set[Hex] = set()
    yellow_near_spawn = [
        hex_
        for spawn in spawn_tiles["yellow"]
        for hex_ in neighbors(spawn)
        if hex_ not in spawn_hexes
    ]
    rng.shuffle(yellow_near_spawn)
    for hex_ in yellow_near_spawn:
        if len(graveyards) >= 4:
            break
        _symmetric_add(graveyards, hex_, symmetry, spawn_hexes, separated=True)

    _fill_symmetric(graveyards, 10, symmetry, spawn_hexes, rng, separated=True)

    water_count = rng.randrange(10, 21)
    if water_count % 2 == 1:
        water_count += 1
    water_count = min(water_count, 20)
    water: Set[Hex] = set()
    forbidden_water = spawn_hexes | graveyards
    _fill_symmetric(water, water_count, symmetry, forbidden_water, rng)
    _trim_to_count(water, water_count, symmetry, rng)

    board_map = BoardMap(
        water=water,
        graveyards=graveyards,
        spawn_tiles=spawn_tiles,
        spawn_centers=spawn_centers,
        symmetry=symmetry_name,
    )
    if not _map_is_valid(board_map):
        for retry in range(100):
            candidate = generate_map(seed=rng.randrange(1_000_000_000))
            if _map_is_valid(candidate):
                return candidate
        raise RuntimeError("could not generate a valid map")
    return board_map


def _map_is_valid(board_map: BoardMap) -> bool:
    spawn_hexes = set(board_map.spawn_tiles["yellow"] + board_map.spawn_tiles["blue"])
    return (
        len(board_map.graveyards) == 10
        and not board_map.water & spawn_hexes
        and not board_map.water & board_map.graveyards
        and board_map.is_symmetric()
        and board_map.graveyards_are_separated()
        and board_map.graveyards_connect_to_necromancers()
        and board_map.graveyards_near_spawns() >= 2
    )


def terrain_allows_entry(terrain: Optional[str], unit_stats: dict) -> bool:
    if terrain is None:
        return True
    if terrain == Terrain.FIRESTORM.value:
        return unit_stats["defense"] >= 4
    if terrain == Terrain.EARTHQUAKE.value:
        return unit_stats["speed"] >= 2
    if terrain == Terrain.FLOOD.value:
        return unit_stats["flying"]
    if terrain == Terrain.WHIRLWIND.value:
        return unit_stats["persistent"]
    return True


def serialize_hexes(hexes: Iterable[Hex]) -> List[str]:
    return as_keys(hexes)
