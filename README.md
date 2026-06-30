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

Games can be created in either **Random Units** or **Subscriptions** mode. Random Units is the original mode: researched generated units are bought one copy at a time, with the research cost subtracted from the later purchase cost. Subscriptions uses the same board, turn, spell, spawn, movement, attack, and win rules, but generated units are delivered by fixed-length board subscriptions. Subscription length is chosen at game setup and does not change during play.

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

Units cannot have both Spawn and Blink.

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

Turns start in the spawn phase. A team may buy zombies, buy or subscribe to researched units, research new random unit designs for `$2`, spawn reinforcements, and cast spawn-phase spells. Switching to the movement phase is one-way.

In Random Units mode, buying a researched generated unit places one copy into the current board's reinforcements and consumes that researched copy. The printed purchase cost for a researched generated unit has the `$2` research cost subtracted after the unit's normal generated cost is computed, so it can be negative. In Subscriptions mode, researched generated units are not bought directly. Each researched unit shows `$2`, `$3`, `$5`, `$8`, and `$13` subscription buttons. Buttons whose total delivery would be less than half a unit are unavailable. Choosing a button and then the unit creates a subscription on the current board only. At the start of that team's later turns, due subscribed units are automatically bought into that board's reinforcements while the team has enough money. If any due subscription cannot be bought, that team is oversubscribed and cannot research during that turn.

During movement, a player may move and attack with units in any order. An individual unit must move before attacking. Once a unit attacks, it cannot move again except through spells or Blink. Movement is one hex at a time; friendly units can trade places. If another unit acts after a unit has partially moved, the first unit loses remaining movement. Flurry attacks are not atomic and can continue spending their remaining damage.

At end of turn, the active team collects `3 + occupied graveyards` souls per board, all units heal all damage, and the turn passes.

## Winning Boards and Match

The target board points are equal to the number of boards for games with up to three boards, otherwise `boards - 1`.

A team wins a board point when it kills the opposing necromancer, starts its turn occupying at least eight graveyards on that board, or receives the opponent's resignation for that board. Resignation is processed at the start of the winning team's next turn. When a board ends, the winning team immediately opens the reset board and cannot spawn on that opening turn; the second player can spawn immediately.

## Random Units and Cost Fit

Random units become stronger as the game progresses. The progression reaches its late-game values at turn 31, synchronized with the cost-efficiency multiplier below.

At turn 1, attack uses exponential lambda `0.75`, defense uses lambda `0.70`, speed weights are `[0.72, 0.23, 0.05]` for speeds 1, 2, and 3, range weights are `[0.82, 0.15, 0.03]` for ranges 1, 2, and 3, positive keyword probability is `0.08`, terrain-spawn probability is `0.03`, lumbering probability is `0.30`, and special attack conversion probability is `0.10`.

At turn 31 and later, attack uses exponential lambda `0.24`, defense uses lambda `0.22`, speed weights are `[0.28, 0.42, 0.30]`, range weights are `[0.45, 0.35, 0.20]`, positive keyword probability is `0.30`, terrain-spawn probability is `0.18`, lumbering probability is `0.08`, and special attack conversion probability is `0.30`. Intermediate turns linearly interpolate between those values. Spawn and Blink are rolled from those keyword chances but are mutually exclusive; if both roll, one is randomly dropped.

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

After power is computed for a generated unit, it is multiplied for pricing by `max(0.5, 2 - 0.05 * (turn_number - 1))`. Early generated units are therefore less cost efficient; by turn 31 the multiplier has reached `0.5`.

The app includes the existing units as auxiliary data, generates `static/unit-fit.svg`, and labels each existing unit on the fit plot.
