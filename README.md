# Minions of Darkness

Minions of Darkness is a browser-playable prototype backed mostly by Python. The code is intentionally modular because the rules are expected to move: maps live in `minions/rules/maps.py`, unit templates and random generation live in `minions/rules/units.py`, spell cards live in `minions/rules/spells.py`, and turn/action resolution lives in `minions/rules/game.py`.

Run locally:

```bash
python -m minions.app --host 127.0.0.1 --port 8000
```

Then open `http://127.0.0.1:8000`.

## AI Player

Use **Play vs AI** in the top bar to create a local game against the AI. Choose the number of boards and your color first; the AI takes the other color and automatically plays whenever it is the AI's turn.

The same turn-playing functionality is available through:

```bash
POST /api/games/{code}/ai-turn
{"color": "yellow", "timeLimit": 10}
```

The AI is a rules-validated heuristic planner: it generates candidate economy, spawn, terrain, spell, movement, attack, blink, and end-turn actions, scores each by dry-running the existing `apply_action` reducer on a copied game, and applies the best sequence it finds before its time limit.

For quick local weight tuning, run:

```bash
python3 scripts/tune_ai.py --seconds 60 --games 4 --boards 1 --per-turn-seconds 0.04 --max-turns 35
```

## Production Deployment

The EC2 deployment runs nginx on port 80 and proxies to the Python app on `127.0.0.1:8000`. The nginx config is in `deploy/nginx-minions.conf`; the systemd service is in `deploy/minions.service`.

## Game Setup

The game is played by yellow and blue on a chosen number of boards. Creating a game returns a six-character code; another player can join that code and choose yellow or blue. Yellow goes first. Blue starts with `$4 * number_of_boards`.

Each board is a 10 by 10 axial hex grid rendered as a diamond. A generated map has exactly ten graveyards, symmetric water, seven yellow spawn tiles, and seven blue spawn tiles. Current maps use about half the original water density, typically 4 to 10 water tiles. The spawn tiles are arranged as one center tile surrounded by six allied tiles on opposite sides of the rotated board. Spawn tiles never contain water. Graveyards are never adjacent to other graveyards, and every graveyard must have a non-water path to both starting necromancer hexes. Generated maps are either rotationally symmetric by 180 degrees or reflectionally symmetric along the axis that swaps the blue and yellow necromancer starts. At least two graveyards are within distance 1 of turn-one spawn tiles.

Each board starts with one necromancer per color on the central spawn tile and six allied zombies around it. Whenever a board starts or resets, both sides also get one free zombie in that board's reinforcements.

## Units

Units have attack, defense, speed, range, cost, rebate, and optional abilities:

- Spawn: can spawn units from reinforcements adjacent to itself.
- Persistent: unsummon attacks deal 1 damage instead.
- Blink: can return to reinforcements on its team's turn.
- Flurry: can split numerical attack damage among enemies in range.
- Ward: spells targeting this unit cost 1 more mana per Ward.
- Flying: can move through and land or spawn on water, and can move over enemy units.
- Lumbering: cannot both move and attack.
- Terrain spawn: can move one of the unique terrain hexes adjacent to itself.

Units heal all damage at the end of each turn. Newly spawned units are exhausted. Exhausted units cannot move, attack, spawn units, or spawn terrain, including when a spell asks that unit to spawn.

Necromancers are not minions and cannot be targeted by minion-only spells or abilities. A necromancer has `*` attack, 7 defense, Persistent, Spawn, 1 speed, and 1 range.

Zombies are minions with `$2/0`, speed 1, range 1, attack 1, defense 1, Lumbering, and Spawn.

## Terrain

Each board has exactly one copy of each terrain. If a terrain is spawned somewhere else, it moves.

- Firestorm: only units with at least 4 defense can enter or move through it.
- Earthquake: only units with at least 2 speed can enter or move through it.
- Flood: only flying units can enter or move through it.
- Whirlwind: only persistent units can enter or move through it.

A plain empty hex has no unit, graveyard, water, terrain, or other map feature.

## Spells

The spell deck contains ten copies of Fester, Unsummon, Stumble, Shield, and Reposition. It contains two copies of each rare spell: Dismember, Critical Hit, Double Stumble, Weaken, Freeze Ray, Lumbering, Shackle, Blink, Persistent, the four terrain spells, Terraform, Normalize, Lesser Spawn, Spawn, and Raise Zombie.

By default spells cost 0 mana. Some spells cost 1 mana. Players may cast spells only on their turn. Discarding a card gives 1 mana; cantrip cards also resolve when discarded. Duration effects last until the start of the caster's next turn. Spawn-phase-only spells can only be cast in the spawn phase.

At the start of each team's turn, that team draws one random spell card into each board's spell hand. There is no maximum hand size. Yellow draws for the opening turn when the game is created; blue draws when blue's first turn starts.

## Turn Flow

Turns start in the spawn phase. A team may buy zombies, buy researched units into a board's reinforcements, research new random unit designs for `$1`, spawn reinforcements, and cast spawn-phase spells. Switching to the movement phase is one-way.

During movement, a player may move and attack with units in any order. An individual unit must move before attacking. Once a unit attacks, it cannot move again except through spells or Blink. Movement is one hex at a time; friendly units can trade places. If another unit acts after a unit has partially moved, the first unit loses remaining movement. Flurry attacks are not atomic and can continue spending their remaining damage.

At end of turn, the active team collects `3 + occupied graveyards` souls per board, all units heal all damage, and the turn passes.

## Winning Boards and Match

The target board points are equal to the number of boards for games with up to three boards, otherwise `boards - 1`.

A team wins a board point when it kills the opposing necromancer, starts its turn occupying at least eight graveyards on that board, or receives the opponent's resignation for that board. Resignation is processed at the start of the winning team's next turn. When a board ends, the winning team immediately opens the reset board and cannot spawn on that opening turn; the second player can spawn immediately.

## Random Units and Cost Fit

Random units sample attack and defense from exponential distributions with minimum 1 and lambda 0.3. Speed uses weights `[0.5, 0.3, 0.2]` for speeds 1, 2, and 3. Range uses weights `[0.7, 0.2, 0.1]` for ranges 1, 2, and 3. Each keyword has probability 0.2, and each terrain-spawn option has probability 0.05.

Power is computed as:

```text
(
1.5*A + (A-1)*FLURRY + (1+SPAWN*0.5)*(S + D + (D-2)*PERSISTENT*0.75 + (D-1)*WARD*0.5)
)
* 3^R
* (2+0.5*BLINK)^(S*(1-LUMBERING)+0.5*FLYING)
* (1 + 0.05*TERRAINSPAWN)
```

`A` treats `*` as 2 and `**` as 4. The fitted expression is:

```text
(Cost - Rebate) * (Cost + Rebate) = alpha * Unit Power
```

The app includes the existing units as auxiliary data, generates `static/unit-fit.svg`, and labels each existing unit on the fit plot.
