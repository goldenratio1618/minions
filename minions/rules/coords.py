from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List

from .constants import BOARD_SIZE


@dataclass(frozen=True, order=True)
class Hex:
    q: int
    r: int

    def to_key(self) -> str:
        return f"{self.q},{self.r}"

    @classmethod
    def from_key(cls, key: str) -> "Hex":
        q_text, r_text = key.split(",", 1)
        return cls(int(q_text), int(r_text))

    def to_dict(self) -> dict:
        return {"q": self.q, "r": self.r}


DIRECTIONS = (
    Hex(1, 0),
    Hex(1, -1),
    Hex(0, -1),
    Hex(-1, 0),
    Hex(-1, 1),
    Hex(0, 1),
)


def in_bounds(hex_: Hex) -> bool:
    return 0 <= hex_.q < BOARD_SIZE and 0 <= hex_.r < BOARD_SIZE


def add(a: Hex, b: Hex) -> Hex:
    return Hex(a.q + b.q, a.r + b.r)


def neighbors(hex_: Hex) -> List[Hex]:
    return [candidate for candidate in (add(hex_, d) for d in DIRECTIONS) if in_bounds(candidate)]


def distance(a: Hex, b: Hex) -> int:
    dq = a.q - b.q
    dr = a.r - b.r
    return int((abs(dq) + abs(dr) + abs(dq + dr)) / 2)


def all_hexes() -> List[Hex]:
    return [Hex(q, r) for q in range(BOARD_SIZE) for r in range(BOARD_SIZE)]


def rotate_180(hex_: Hex) -> Hex:
    return Hex(BOARD_SIZE - 1 - hex_.q, BOARD_SIZE - 1 - hex_.r)


def reflect_long_axis(hex_: Hex) -> Hex:
    return Hex(BOARD_SIZE - 1 - hex_.r, BOARD_SIZE - 1 - hex_.q)


def reflect_necromancer_axis(hex_: Hex) -> Hex:
    return Hex(hex_.r, hex_.q)


def yellow_spawn_center() -> Hex:
    return Hex(1, BOARD_SIZE - 2)


def blue_spawn_center() -> Hex:
    return Hex(BOARD_SIZE - 2, 1)


def spawn_cluster(center: Hex) -> List[Hex]:
    cluster = [center] + neighbors(center)
    if len(cluster) != 7:
        raise ValueError(f"spawn center {center} does not produce a 7-hex cluster")
    return cluster


def as_keys(hexes: Iterable[Hex]) -> List[str]:
    return [hex_.to_key() for hex_ in sorted(hexes)]
