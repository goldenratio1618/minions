from __future__ import annotations

from enum import Enum


BOARD_SIZE = 10
TEAMS = ("yellow", "blue")


class Phase(str, Enum):
    SPAWN = "spawn"
    MOVEMENT = "movement"


class Terrain(str, Enum):
    FIRESTORM = "firestorm"
    EARTHQUAKE = "earthquake"
    FLOOD = "flood"
    WHIRLWIND = "whirlwind"


TERRAIN_LABELS = {
    Terrain.FIRESTORM.value: "Firestorm",
    Terrain.EARTHQUAKE.value: "Earthquake",
    Terrain.FLOOD.value: "Flood",
    Terrain.WHIRLWIND.value: "Whirlwind",
}


OPPONENT = {
    "yellow": "blue",
    "blue": "yellow",
}
