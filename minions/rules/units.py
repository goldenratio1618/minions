from __future__ import annotations

import math
import random
import secrets
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Tuple, Union

from .constants import TERRAIN_LABELS, Terrain

AttackValue = Union[int, str]


@dataclass(frozen=True)
class UnitTemplate:
    id: str
    name: str
    cost: int
    rebate: int
    attack: AttackValue
    defense: int
    speed: int
    range: int
    spawn: bool = False
    persistent: bool = False
    blink: bool = False
    flurry: bool = False
    ward: int = 0
    flying: bool = False
    lumbering: bool = False
    terrain_spawn: Tuple[str, ...] = ()
    minion: bool = True
    generated: bool = False

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "cost": self.cost,
            "rebate": self.rebate,
            "attack": self.attack,
            "defense": self.defense,
            "speed": self.speed,
            "range": self.range,
            "spawn": self.spawn,
            "persistent": self.persistent,
            "blink": self.blink,
            "flurry": self.flurry,
            "ward": self.ward,
            "flying": self.flying,
            "lumbering": self.lumbering,
            "terrainSpawn": list(self.terrain_spawn),
            "terrainSpawnLabels": [TERRAIN_LABELS[kind] for kind in self.terrain_spawn],
            "minion": self.minion,
            "generated": self.generated,
            "power": unit_power(self),
            "observedPriceExpression": self.cost * self.cost - self.rebate * self.rebate,
        }


@dataclass
class TimedEffect:
    name: str
    caster: str
    attack_delta: int = 0
    attack_set: Optional[int] = None
    defense_multiplier: float = 1.0
    ward_bonus: int = 0
    persistent: bool = False
    lumbering: bool = False
    spawn: bool = False
    shackle: bool = False
    critical: bool = False

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "caster": self.caster,
            "attackDelta": self.attack_delta,
            "attackSet": self.attack_set,
            "defenseMultiplier": self.defense_multiplier,
            "wardBonus": self.ward_bonus,
            "persistent": self.persistent,
            "lumbering": self.lumbering,
            "spawn": self.spawn,
            "shackle": self.shackle,
            "critical": self.critical,
        }


@dataclass
class UnitInstance:
    id: str
    template_id: str
    team: str
    hex: str
    damage: int = 0
    exhausted: bool = False
    moved: bool = False
    attacked: bool = False
    movement_remaining: Optional[int] = None
    flurry_remaining: Optional[int] = None
    star_attacks_remaining: Optional[int] = None
    effects: List[TimedEffect] = field(default_factory=list)

    def to_dict(self, template: UnitTemplate, stats: dict) -> dict:
        return {
            "id": self.id,
            "templateId": self.template_id,
            "team": self.team,
            "hex": self.hex,
            "damage": self.damage,
            "exhausted": self.exhausted,
            "moved": self.moved,
            "attacked": self.attacked,
            "movementRemaining": self.movement_remaining,
            "flurryRemaining": self.flurry_remaining,
            "starAttacksRemaining": self.star_attacks_remaining,
            "effects": [effect.to_dict() for effect in self.effects],
            "template": template.to_dict(),
            "stats": stats,
        }


def new_unit_id(prefix: str = "u") -> str:
    return f"{prefix}_{secrets.token_hex(4)}"


BASE_UNITS: Dict[str, UnitTemplate] = {
    "necromancer": UnitTemplate(
        id="necromancer",
        name="Necromancer",
        cost=0,
        rebate=0,
        attack="*",
        defense=10,
        speed=1,
        range=1,
        spawn=True,
        persistent=True,
        minion=False,
    ),
    "zombie": UnitTemplate(
        id="zombie",
        name="Zombie",
        cost=2,
        rebate=0,
        attack=1,
        defense=1,
        speed=1,
        range=1,
        spawn=True,
        lumbering=True,
    ),
}


EXISTING_UNITS: List[UnitTemplate] = [
    UnitTemplate("skeleton", "Skeleton", 4, 2, 5, 2, 1, 1, flying=True, persistent=True),
    UnitTemplate("serpent", "Serpent", 4, 2, 3, 1, 2, 1, spawn=True),
    UnitTemplate("warg", "Warg", 3, 1, 1, 1, 3, 1),
    UnitTemplate("ghost", "Ghost", 3, 0, 1, 4, 1, 1, flying=True, ward=1, terrain_spawn=(Terrain.FLOOD.value,)),
    UnitTemplate("wight", "Wight", 4, 1, 5, 3, 2, 2, flurry=True, lumbering=True),
    UnitTemplate("haunt", "Haunt", 5, 1, 2, 2, 2, 3, blink=True, lumbering=True, terrain_spawn=(Terrain.EARTHQUAKE.value,)),
    UnitTemplate("shrieker", "Shrieker", 5, 2, 3, 1, 3, 1),
    UnitTemplate("specter", "Specter", 4, 2, 1, 5, 2, 1, flying=True),
    UnitTemplate("rat", "Rat", 2, 1, 5, 1, 1, 1, spawn=True, persistent=True),
    UnitTemplate("sorcerer", "Sorcerer", 5, 2, "**", 3, 2, 1, flurry=True, blink=True, persistent=True),
    UnitTemplate("witch", "Witch", 4, 1, 1, 1, 2, 2, flying=True),
    UnitTemplate("vampire", "Vampire", 4, 2, 3, 5, 1, 1, persistent=True, flying=True),
    UnitTemplate("gargoyle", "Gargoyle", 4, 1, 5, 7, 1, 1, flying=True, ward=1),
    UnitTemplate("lich", "Lich", 5, 2, 7, 2, 1, 2),
    UnitTemplate("void", "Void", 4, 0, "*", 2, 3, 1, blink=True, terrain_spawn=(Terrain.WHIRLWIND.value,)),
    UnitTemplate("cerberus", "Cerberus", 5, 3, 2, 3, 3, 1, flurry=True, persistent=True, terrain_spawn=(Terrain.FIRESTORM.value,)),
    UnitTemplate("wraith", "Wraith", 5, 2, 4, 7, 2, 2, flying=True, lumbering=True, spawn=True, persistent=True),
    UnitTemplate("horror", "Horror", 3, 0, 10, 6, 1, 1, flurry=True, blink=True, ward=1),
    UnitTemplate("banshee", "Banshee", 6, 4, 9, 2, 2, 1, persistent=True, flying=True),
]


def attack_for_power(attack: AttackValue) -> int:
    if attack == "*":
        return 2
    if attack == "**":
        return 4
    return int(attack)


def unit_power(unit: UnitTemplate) -> float:
    a = attack_for_power(unit.attack)
    d = unit.defense
    s = unit.speed
    r = unit.range
    flurry = 1 if unit.flurry else 0
    spawn = 1 if unit.spawn else 0
    persistent = 1 if unit.persistent else 0
    ward = 1 if unit.ward else 0
    blink = 1 if unit.blink else 0
    flying = 1 if unit.flying else 0
    lumbering = 1 if unit.lumbering else 0
    terrain_spawn = len(unit.terrain_spawn)
    core = 1.5 * a + (a - 1) * flurry + (1 + spawn * 0.5) * (
        s + d + (d - 2) * persistent * 0.75 + (d - 1) * ward * 0.5
    )
    core = max(core, 0.1)
    return (
        core
        * (3**r)
        * ((2 + 0.5 * blink) ** (s * (1 - lumbering) + 0.5 * flying))
        * (1 + 0.05 * terrain_spawn)
    )


def fit_alpha(units: Sequence[UnitTemplate] = EXISTING_UNITS) -> float:
    powers = [unit_power(unit) for unit in units]
    observed = [unit.cost * unit.cost - unit.rebate * unit.rebate for unit in units]
    numerator = sum(power * obs for power, obs in zip(powers, observed))
    denominator = sum(power * power for power in powers)
    return numerator / denominator


ALPHA = fit_alpha()


def observed_expression(unit: UnitTemplate) -> int:
    return unit.cost * unit.cost - unit.rebate * unit.rebate


def predicted_expression(unit: UnitTemplate, alpha: float = ALPHA) -> float:
    return alpha * unit_power(unit)


def _weighted_choice(rng: random.Random, values: Sequence[Tuple[int, float]]) -> int:
    roll = rng.random()
    total = 0.0
    for value, weight in values:
        total += weight
        if roll <= total:
            return value
    return values[-1][0]


def _sample_stat(rng: random.Random) -> int:
    return max(1, int(math.floor(1 + rng.expovariate(0.3))))


def _sample_cost_rebate(target: float, rng: random.Random) -> Tuple[int, int]:
    ratio = min(2.8, max(1.15, rng.gauss(2.0, 0.25)))
    cost_float = math.sqrt(max(target, 1.0) / max(1 - 1 / (ratio * ratio), 0.05))
    cost = max(1, int(round(cost_float)))
    rebate = int(round(cost / ratio))
    rebate = max(0, min(cost - 1, rebate))
    if cost * cost - rebate * rebate < target * 0.7:
        cost += 1
    cost, rebate = _greedy_refine_cost_rebate(cost, rebate, target)
    return cost, rebate


def _price_expression(cost: int, rebate: int) -> int:
    return cost * cost - rebate * rebate


def _greedy_refine_cost_rebate(cost: int, rebate: int, target: float) -> Tuple[int, int]:
    def distance_to_target(candidate: Tuple[int, int]) -> float:
        return abs(_price_expression(candidate[0], candidate[1]) - target)

    current = (cost, rebate)
    while True:
        candidates = []
        for next_cost, next_rebate in (
            (current[0] + 1, current[1]),
            (current[0] - 1, current[1]),
            (current[0], current[1] + 1),
            (current[0], current[1] - 1),
        ):
            if next_cost >= 1 and 0 <= next_rebate < next_cost:
                candidates.append((next_cost, next_rebate))
        best = min(candidates + [current], key=distance_to_target)
        if distance_to_target(best) >= distance_to_target(current):
            return current
        current = best


NAME_PARTS_A = ["Ash", "Bone", "Crypt", "Dread", "Grim", "Mire", "Night", "Pale", "Rot", "Void"]
NAME_PARTS_B = ["binder", "claw", "gazer", "hound", "moth", "reaver", "shade", "skulk", "thorn", "walker"]


def generate_random_unit(seed: Optional[int] = None, alpha: float = ALPHA) -> UnitTemplate:
    rng = random.Random(seed)
    attack: AttackValue = _sample_stat(rng)
    defense = _sample_stat(rng)
    speed = _weighted_choice(rng, [(1, 0.5), (2, 0.3), (3, 0.2)])
    unit_range = _weighted_choice(rng, [(1, 0.7), (2, 0.2), (3, 0.1)])
    spawn = rng.random() < 0.2
    persistent = rng.random() < 0.2
    blink = rng.random() < 0.2
    flurry = rng.random() < 0.2
    ward = 1 if rng.random() < 0.2 else 0
    flying = rng.random() < 0.2
    lumbering = rng.random() < 0.2
    terrain_spawn = (rng.choice(tuple(terrain.value for terrain in Terrain)),) if rng.random() < 0.2 else ()
    if isinstance(attack, int) and attack >= 3 and rng.random() < 0.25:
        attack = "*"
    if isinstance(attack, int) and attack >= 6 and flurry and rng.random() < 0.25:
        attack = "**"
    if attack == 1 or attack == "*":
        flurry = False
    draft = UnitTemplate(
        id="draft",
        name="Draft",
        cost=1,
        rebate=0,
        attack=attack,
        defense=defense,
        speed=speed,
        range=unit_range,
        spawn=spawn,
        persistent=persistent,
        blink=blink,
        flurry=flurry,
        ward=ward,
        flying=flying,
        lumbering=lumbering,
        terrain_spawn=terrain_spawn,
        generated=True,
    )
    cost, rebate = _sample_cost_rebate(predicted_expression(draft, alpha), rng)
    name = f"{rng.choice(NAME_PARTS_A)} {rng.choice(NAME_PARTS_B).title()}"
    return UnitTemplate(
        id=f"gen_{secrets.token_hex(4)}",
        name=name,
        cost=cost,
        rebate=rebate,
        attack=attack,
        defense=defense,
        speed=speed,
        range=unit_range,
        spawn=spawn,
        persistent=persistent,
        blink=blink,
        flurry=flurry,
        ward=ward,
        flying=flying,
        lumbering=lumbering,
        terrain_spawn=terrain_spawn,
        generated=True,
    )


def effective_stats(template: UnitTemplate, effects: Iterable[TimedEffect]) -> dict:
    attack = template.attack
    numeric_attack = attack_for_power(attack)
    defense = float(template.defense)
    speed = template.speed
    unit_range = template.range
    spawn = template.spawn
    persistent = template.persistent
    lumbering = template.lumbering
    ward = template.ward
    critical = False
    for effect in effects:
        if isinstance(attack, int):
            numeric_attack += effect.attack_delta
            if effect.attack_set is not None:
                numeric_attack = effect.attack_set
        defense *= effect.defense_multiplier
        ward += effect.ward_bonus
        persistent = persistent or effect.persistent
        lumbering = lumbering or effect.lumbering
        spawn = spawn or effect.spawn
        if effect.shackle:
            speed = min(speed, 1)
            unit_range = min(unit_range, 1)
        critical = critical or effect.critical
    if isinstance(attack, int):
        attack = max(0, numeric_attack)
    return {
        "attack": attack,
        "attackPower": max(0, numeric_attack),
        "defense": max(1, int(math.ceil(defense))),
        "speed": max(0, speed),
        "range": max(1, unit_range),
        "spawn": spawn,
        "persistent": persistent,
        "blink": template.blink,
        "flurry": template.flurry,
        "ward": ward,
        "flying": template.flying,
        "lumbering": lumbering,
        "terrainSpawn": list(template.terrain_spawn),
        "minion": template.minion,
        "critical": critical,
    }


def all_auxiliary_units() -> List[dict]:
    return [unit.to_dict() for unit in EXISTING_UNITS]
