from __future__ import annotations

import random
import secrets
from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass(frozen=True)
class Spell:
    id: str
    name: str
    count: int
    mana_cost: int = 0
    duration: bool = False
    cantrip: bool = False
    spawn_phase_only: bool = False
    text: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "count": self.count,
            "manaCost": self.mana_cost,
            "duration": self.duration,
            "cantrip": self.cantrip,
            "spawnPhaseOnly": self.spawn_phase_only,
            "text": self.text,
        }


SPELLS: Dict[str, Spell] = {
    "fester": Spell("fester", "Fester", 10, text="Deal 1 damage to target damaged enemy minion."),
    "unsummon": Spell("unsummon", "Unsummon", 10, text="Deal a * attack to target damaged enemy minion."),
    "stumble": Spell("stumble", "Stumble", 10, text="Move target damaged enemy minion 1 hex."),
    "shield": Spell("shield", "Shield", 10, duration=True, spawn_phase_only=True, text="Double defense of target friendly minion and it gains Ward."),
    "reposition": Spell("reposition", "Reposition", 10, spawn_phase_only=True, text="Move target friendly minion 1 hex. It becomes exhausted."),
    "dismember": Spell("dismember", "Dismember", 2, mana_cost=1, text="Deal 3 damage to target damaged enemy minion."),
    "critical_hit": Spell("critical_hit", "Critical Hit", 2, mana_cost=1, text="The next attack by target friendly minion deals double damage."),
    "double_stumble": Spell("double_stumble", "Double Stumble", 2, mana_cost=1, text="Move target damaged enemy minion 2 hexes."),
    "weaken": Spell("weaken", "Weaken", 2, duration=True, cantrip=True, text="Target enemy minion gets -1 attack."),
    "freeze_ray": Spell("freeze_ray", "Freeze Ray", 2, mana_cost=1, duration=True, text="Target enemy minion's attack becomes 0."),
    "lumbering": Spell("lumbering", "Lumbering", 2, duration=True, text="Target enemy minion gains lumbering."),
    "shackle": Spell("shackle", "Shackle", 2, duration=True, text="Target enemy minion's speed and range are reduced to 1."),
    "blink": Spell("blink", "Blink", 2, spawn_phase_only=True, text="Return target friendly minion to your reinforcements."),
    "persistent": Spell("persistent", "Persistent", 2, duration=True, spawn_phase_only=True, text="Target friendly minion gains Persistent."),
    "firestorm": Spell("firestorm", "Firestorm", 2, spawn_phase_only=True, text="Target friendly unit spawns Firestorm."),
    "earthquake": Spell("earthquake", "Earthquake", 2, spawn_phase_only=True, text="Target friendly unit spawns Earthquake."),
    "flood": Spell("flood", "Flood", 2, spawn_phase_only=True, text="Target friendly unit spawns Flood."),
    "whirlwind": Spell("whirlwind", "Whirlwind", 2, spawn_phase_only=True, text="Target friendly unit spawns Whirlwind."),
    "terraform": Spell("terraform", "Terraform", 2, mana_cost=1, text="Target unit spawns any terrain."),
    "normalize": Spell("normalize", "Normalize", 2, cantrip=True, text="Remove target terrain from the board."),
    "lesser_spawn": Spell("lesser_spawn", "Lesser Spawn", 2, cantrip=True, text="Target friendly minion spawns another minion adjacent to itself."),
    "spawn": Spell("spawn", "Spawn", 2, text="Target friendly minion gains spawn until end of turn."),
    "raise_zombie": Spell("raise_zombie", "Raise Zombie", 2, text="Target friendly minion spawns a free zombie adjacent to itself."),
}


def build_deck(seed: Optional[int] = None) -> List[str]:
    rng = random.Random(seed)
    deck: List[str] = []
    for spell in SPELLS.values():
        deck.extend([spell.id] * spell.count)
    rng.shuffle(deck)
    return deck


def make_card(spell_id: str) -> dict:
    return {"cardId": f"card_{secrets.token_hex(4)}", "spellId": spell_id}


def serialize_card(card: dict) -> dict:
    spell = SPELLS[card["spellId"]]
    data = spell.to_dict()
    data["cardId"] = card["cardId"]
    return data


def spell_catalog() -> List[dict]:
    return [spell.to_dict() for spell in SPELLS.values()]
