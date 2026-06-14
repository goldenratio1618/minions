const state = {
  game: null,
  color: localStorage.getItem("minions-color") || "yellow",
  board: 0,
  mode: "select",
  selectedUnit: null,
  selectedTemplate: null,
  selectedCard: null,
  spellTarget: null,
  terrainSpawnSource: null,
  drag: null,
  dragGhost: null,
  pathPreview: [],
  suppressClick: false,
  terrain: "firestorm",
  vsAI: false,
  aiColor: null,
  aiThinking: false,
};

const HEX_WIDTH = 80;
const HEX_HEIGHT = 70;
const HEX_STEP_X = HEX_WIDTH * 0.75;
const HEX_STEP_Y = HEX_HEIGHT * 0.5;
const MAP_PADDING = 34;
const MAP_ROTATION = (2 * Math.PI) / 3;
const HEX_DIRECTIONS = [
  [1, 0],
  [1, 1],
  [0, 1],
  [-1, 0],
  [-1, -1],
  [0, -1],
];

function rotatedBoardMetrics(size = 10) {
  const points = [];
  for (let q = 0; q < size; q++) {
    for (let r = 0; r < size; r++) {
      points.push(rawRotatedHexPosition(q, r));
    }
  }
  const minX = Math.min(...points.map((point) => point.x));
  const maxX = Math.max(...points.map((point) => point.x));
  const minY = Math.min(...points.map((point) => point.y));
  const maxY = Math.max(...points.map((point) => point.y));
  return {
    minX,
    minY,
    width: maxX - minX + HEX_WIDTH + MAP_PADDING * 2,
    height: maxY - minY + HEX_HEIGHT + MAP_PADDING * 2,
  };
}

const BOARD_METRICS = rotatedBoardMetrics();

const $ = (id) => document.getElementById(id);

function notice(message, good = false) {
  const el = $("notice");
  el.textContent = message || "";
  el.style.color = good ? "#376d30" : "";
}

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || "Request failed");
  return data;
}

function resetInteractionState() {
  state.mode = "select";
  state.selectedCard = null;
  state.spellTarget = null;
  state.terrainSpawnSource = null;
  state.drag = null;
  state.pathPreview = [];
  state.suppressClick = false;
  removeDragGhost();
  drawPathPreview([]);
}

async function refreshGame() {
  if (!state.game) return;
  const data = await api(`/api/games/${state.game.code}`);
  state.game = data.game;
  if (state.board >= state.game.boards.length) state.board = 0;
  renderGame();
}

async function action(actionName, payload = {}) {
  if (!state.game) return;
  try {
    const data = await api(`/api/games/${state.game.code}/actions`, {
      method: "POST",
      body: JSON.stringify({ color: state.color, action: actionName, payload }),
    });
    state.game = data.game;
    state.pathPreview = data.result && data.result.path ? data.result.path : [];
    renderGame();
    notice("Done.", true);
    await maybeAutoPlayAI();
  } catch (err) {
    resetInteractionState();
    try {
      await refreshGame();
    } catch (_refreshErr) {
      renderGame();
    }
    notice(err.message);
  }
}

async function aiTurn(color = state.color, silent = false) {
  if (!state.game) return;
  try {
    state.aiThinking = true;
    renderGame();
    if (!silent) notice("AI is thinking...", true);
    const data = await api(`/api/games/${state.game.code}/ai-turn`, {
      method: "POST",
      body: JSON.stringify({ color, timeLimit: 10 }),
    });
    state.game = data.game;
    state.pathPreview = [];
    state.aiThinking = false;
    renderGame();
    const count = data.result && data.result.actions ? data.result.actions.length : 0;
    const elapsed = data.result && data.result.elapsedSeconds ? data.result.elapsedSeconds.toFixed(2) : "0.00";
    notice(`AI played ${count} action${count === 1 ? "" : "s"} in ${elapsed}s.`, true);
  } catch (err) {
    state.aiThinking = false;
    renderGame();
    notice(err.message);
  }
}

async function maybeAutoPlayAI() {
  if (!state.vsAI || !state.game || state.aiThinking || state.game.winner) return;
  while (state.vsAI && state.game && state.game.turn === state.aiColor && !state.game.winner) {
    await aiTurn(state.aiColor, true);
  }
}

function configureHumanGame(color) {
  state.color = color;
  state.vsAI = false;
  state.aiColor = null;
  state.aiThinking = false;
  localStorage.setItem("minions-color", state.color);
}

function configureAIGame(color) {
  state.color = color;
  state.vsAI = true;
  state.aiColor = opponentColor();
  state.aiThinking = false;
  localStorage.setItem("minions-color", state.color);
}

function board() {
  return state.game.boards[state.board] || state.game.boards[0];
}

function team() {
  return state.game.teams[state.color];
}

function opponentColor() {
  return state.color === "yellow" ? "blue" : "yellow";
}

function unitById(id) {
  return board().units.find((unit) => unit.id === id);
}

function unitAt(hexKey) {
  return board().units.find((unit) => unit.hex === hexKey);
}

function hexKey(q, r) {
  return `${q},${r}`;
}

function parseHex(key) {
  const [q, r] = key.split(",").map(Number);
  return { q, r };
}

function svgIcon(name, extraClass = "") {
  const cls = `unit-icon ${extraClass}`.trim();
  const attrs = `class="${cls}" viewBox="0 0 24 24" aria-hidden="true" focusable="false"`;
  const icons = {
    sword: `<svg ${attrs}><path d="M10.7 3h2.6v3h3.2v2.4h-3.2v7.1l2 2L12 22l-3.3-4.5 2-2V8.4H7.5V6h3.2z"/></svg>`,
    bow: `<svg ${attrs}><path d="M6 3c7 3 7 15 0 18" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"/><path d="M6 3v18" fill="none" stroke="currentColor" stroke-width="1.4"/><path d="M5 12h14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/><path d="M19 12l-4-3v6z"/></svg>`,
    cannon: `<svg ${attrs}><circle cx="8" cy="17" r="2.2"/><circle cx="17" cy="17" r="2.2"/><path d="M4 13l11-7 5 5-9 5H5z"/></svg>`,
    shield: `<svg ${attrs}><path d="M12 2l8 3v6c0 5.2-3.2 9-8 11-4.8-2-8-5.8-8-11V5z" fill="currentColor"/></svg>`,
    anchor: `<svg ${attrs}><path d="M12 4a2 2 0 110 4 2 2 0 010-4zm-1 5h2v8.1c1.8-.3 3.2-1.4 4.1-3.2l1.8.9C17.6 17.6 15.1 19 12 19s-5.6-1.4-6.9-4.2l1.8-.9c.9 1.8 2.3 2.9 4.1 3.2V9zm-4-1h10v2H7z"/></svg>`,
    footprints: `<svg ${attrs}><ellipse cx="8" cy="8" rx="2.3" ry="3.4" transform="rotate(-18 8 8)"/><circle cx="6" cy="3.8" r=".8"/><circle cx="8" cy="3.2" r=".75"/><circle cx="10" cy="3.8" r=".7"/><ellipse cx="16" cy="16" rx="2.3" ry="3.4" transform="rotate(-18 16 16)"/><circle cx="14" cy="11.8" r=".8"/><circle cx="16" cy="11.2" r=".75"/><circle cx="18" cy="11.8" r=".7"/></svg>`,
    wings: `<svg ${attrs}><path d="M12 16c-4.5-.2-7.8-2.4-9.5-6.2C6 9.4 9 10.6 12 14c3-3.4 6-4.6 9.5-4.2C19.8 13.6 16.5 15.8 12 16z" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/><path d="M7 10.5c1.5.6 3 1.8 5 3.5 2-1.7 3.5-2.9 5-3.5" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/></svg>`,
    lumbering: `<svg ${attrs}><circle cx="7" cy="5" r="2.2"/><path d="M7 8v8M7 10l12 1M7 16l-3 5M8 16l4 5" fill="none" stroke="currentColor" stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round"/></svg>`,
  };
  return icons[name] || "";
}

function attackIcon(range, extraClass = "") {
  if (range >= 3) return svgIcon("cannon", extraClass);
  if (range === 2) return svgIcon("bow", extraClass);
  return svgIcon("sword", extraClass);
}

function speedIcon(unit) {
  const stats = unit.stats || unit;
  const parts = [];
  if (stats.flying) parts.push(svgIcon("wings"));
  if (stats.lumbering) parts.push(svgIcon("lumbering"));
  if (!parts.length) parts.push(svgIcon("footprints"));
  return parts.join("");
}

function unitToken(unit, preview = false) {
  const tpl = unit.template || unit;
  const stats = unit.stats || unit;
  const hasNoMovementLeft =
    unit.id &&
    unit.moved &&
    unit.movementRemaining !== null &&
    unit.movementRemaining !== undefined &&
    unit.movementRemaining <= 0;
  const statusClass = unit.id
    ? unit.exhausted
      ? "state-exhausted"
      : unit.attacked
        ? "state-attacked"
        : hasNoMovementLeft
          ? "state-moved"
          : "state-ready"
    : "";
  const attack = stats.attack !== undefined ? stats.attack : tpl.attack;
  const atk = stats.flurry
    ? `<span class="stat-value">${attack}</span>${attackIcon(stats.range)}${attackIcon(stats.range, "mirror")}`
    : `<span class="stat-value">${attack}</span>${attackIcon(stats.range)}`;
  const defenseIcon = stats.persistent ? svgIcon("anchor") : svgIcon("shield");
  const defenseInner = `<span class="stat-value">${stats.defense}</span>${defenseIcon}`;
  const defense = stats.ward ? `<span class="warded">${defenseInner}</span>` : defenseInner;
  const ability = [
    stats.spawn ? "⬡→⬡" : "",
    stats.blink ? "✦" : "",
  ].filter(Boolean).join("");
  const terrain = (stats.terrainSpawn || tpl.terrainSpawn || []).map((kind) => kind.slice(0, 4).toUpperCase()).join(" ");
  return `
    <div class="unit-token ${preview ? "preview-token" : ""} ${unit.team || "yellow"} ${unit.exhausted ? "exhausted" : ""} ${statusClass}">
      <div class="cost-line">$${tpl.cost}/${tpl.rebate}</div>
      <div class="unit-name">${tpl.name}</div>
      <div class="speed-line">${stats.speed} ${speedIcon({ stats })}</div>
      <div class="ability-line">${ability}</div>
      <div class="terrain-line">${terrain}</div>
      <div class="combat-line"><span>${atk}</span><span>${defense}</span></div>
    </div>
  `;
}

function rawRotatedHexPosition(q, r) {
  const x = (q - r) * HEX_STEP_X;
  const y = (q + r) * HEX_STEP_Y;
  return {
    x: Math.cos(MAP_ROTATION) * x - Math.sin(MAP_ROTATION) * y,
    y: Math.sin(MAP_ROTATION) * x + Math.cos(MAP_ROTATION) * y,
  };
}

function hexPosition(q, r) {
  const raw = rawRotatedHexPosition(q, r);
  const x = raw.x - BOARD_METRICS.minX + MAP_PADDING;
  const y = raw.y - BOARD_METRICS.minY + MAP_PADDING;
  if (state.color === "yellow") {
    return {
      x: BOARD_METRICS.width - HEX_WIDTH - x,
      y: BOARD_METRICS.height - HEX_HEIGHT - y,
    };
  }
  return {
    x,
    y,
  };
}

function setMode(mode) {
  state.mode = mode;
  state.selectedCard = null;
  state.spellTarget = null;
  renderGame();
}

function renderGame() {
  const root = $("game-root");
  if (!state.game) {
    root.className = "game-root empty-state";
    root.textContent = "Create or join a game to start.";
    return;
  }
  root.className = "game-root";
  const currentBoard = board();
  const active = state.game.turn === state.color && !state.aiThinking;
  const selected = state.selectedUnit ? unitById(state.selectedUnit) : null;
  root.innerHTML = `
    <div class="status-strip">
      <div>
        <span class="status-pill">Code ${state.game.code}</span>
        <span class="status-pill">You ${state.color}</span>
        ${state.vsAI ? `<span class="status-pill">AI ${state.aiColor}</span>` : '<span class="status-pill">Players game</span>'}
        <span class="status-pill">Turn ${state.game.turn}</span>
        ${state.aiThinking ? '<span class="status-pill">AI thinking</span>' : ""}
        <span class="status-pill">Score Y ${state.game.scores.yellow} / B ${state.game.scores.blue}</span>
      </div>
      <div>
        <span class="status-pill">Yellow $${state.game.teams.yellow.souls}</span>
        <span class="status-pill">Blue $${state.game.teams.blue.souls}</span>
        <span class="status-pill">Mana ${team().mana}</span>
      </div>
    </div>
    <div class="game-layout">
      <div>
        <div class="board-tabs">
          ${state.game.boards.map((b, idx) => `<button class="secondary ${idx === state.board ? "active" : ""}" data-board="${idx}">Board ${idx + 1}</button>`).join("")}
        </div>
        <div class="action-bar">
          <select id="terrain-select">
            ${Object.entries(state.game.terrainLabels).map(([kind, label]) => `<option value="${kind}" ${kind === state.terrain ? "selected" : ""}>${label}</option>`).join("")}
          </select>
          <button ${!active || !state.game.canRedo ? "disabled" : ""} onclick="action('redo')">Redo</button>
          <button ${!active || currentBoard.winner ? "disabled" : ""} onclick="confirm('Resign this board? Your opponent gets a board point now.') && action('resign_board', {board:${state.board}})">Resign Board</button>
          <button ${!active ? "disabled" : ""} onclick="action('end_turn')">End Turn</button>
          <span class="action-hint">${state.vsAI && state.game.turn === state.aiColor ? "The AI is taking its turn." : "Drag units to move or attack. Drag reinforcements onto legal spawn hexes. Right-click a unit to undo its last operation."}</span>
        </div>
        <div class="map-wrap"><div class="hex-map">${renderMap(currentBoard)}</div></div>
      </div>
      <aside class="side-panel">
        <section class="side-section">
          <h3>Selection</h3>
          <div class="mini-card">${selected ? renderSelectedUnit(selected) : "No unit selected."}</div>
        </section>
        <section class="side-section">
          <h3>Hover</h3>
          <div id="hover-card" class="hover-card mini-card">Hover a tile to inspect it.</div>
        </section>
        <section class="side-section" data-drop-zone="reinforcements">
          <h3>Reinforcements</h3>
          <div class="compact-list">${renderReinforcements(currentBoard)}</div>
        </section>
        <section class="side-section">
          <h3>Research & Buy</h3>
          <div class="mini-actions">
            <button onclick="action('research')">Research $1</button>
            <button onclick="action('buy', {board:${state.board}, templateId:'zombie'})">Buy Zombie $2</button>
          </div>
          <div class="compact-list">${renderResearch()}</div>
        </section>
        <section class="side-section">
          <h3>Spells</h3>
          <div class="compact-list">${renderHand()}</div>
        </section>
        <section class="side-section">
          <h3>Turn Actions</h3>
          <div class="compact-list">${renderTurnHistory()}</div>
        </section>
        <section class="side-section">
          <h3>Log</h3>
          <div class="log">${state.game.log.slice().reverse().map((line) => `<div>${line}</div>`).join("")}</div>
        </section>
      </aside>
    </div>
  `;
  document.querySelectorAll("[data-board]").forEach((button) => {
    button.addEventListener("click", () => {
      state.board = Number(button.dataset.board);
      state.selectedUnit = null;
      state.pathPreview = [];
      renderGame();
    });
  });
  document.querySelectorAll(".bench-unit[data-template]").forEach((button) => {
    button.addEventListener("pointerdown", (event) => handleBenchPointerDown(event, button.dataset.template));
  });
  const terrainSelect = $("terrain-select");
  if (terrainSelect) terrainSelect.addEventListener("change", (event) => (state.terrain = event.target.value));
}

function renderSelectedUnit(unit) {
  return `
    <strong>${unit.template.name}</strong>
    <div>${unit.team} at ${unit.hex}; damage ${unit.damage}/${unit.stats.defense}${unit.exhausted ? "; exhausted" : ""}</div>
    <div class="mini-actions">
      <button onclick="setMode('move')">Move</button>
      <button onclick="setMode('attack')">Attack</button>
      <button onclick="action('blink_unit', {board:${state.board}, unitId:'${unit.id}'})">Blink</button>
    </div>
  `;
}

function findTemplate(templateId) {
  const base = Object.values(state.game.baseUnits || {}).find((unit) => unit.id === templateId);
  if (base) return base;
  const researched = (team().researched || []).find((unit) => unit.id === templateId);
  if (researched) return researched;
  for (const candidate of board().reinforcements[state.color] || []) {
    if (candidate.id === templateId) return candidate;
  }
  return null;
}

function renderMap(b) {
  const water = new Set(b.map.water);
  const graves = new Set(b.map.graveyards);
  const terrainByHex = {};
  Object.entries(b.terrain).forEach(([kind, key]) => {
    if (key) terrainByHex[key] = kind;
  });
  const spawnClass = {};
  Object.entries(b.map.spawnTiles).forEach(([team, keys]) => keys.forEach((key) => (spawnClass[key] = `spawn-${team}`)));
  let html = "";
  for (let q = 0; q < b.map.size; q++) {
    for (let r = 0; r < b.map.size; r++) {
      const key = hexKey(q, r);
      const { x, y } = hexPosition(q, r);
      const unit = unitAt(key);
      const classes = [
        "hex",
        water.has(key) ? "water" : "",
        graves.has(key) ? "graveyard" : "",
        spawnClass[key] || "",
        state.selectedUnit && unit && unit.id === state.selectedUnit ? "selected" : "",
      ].join(" ");
      html += `
        <button class="${classes}" style="left:${x}px; top:${y}px" data-key="${key}" data-q="${q}" data-r="${r}" data-unit="${unit ? unit.id : ""}">
          <span class="coord">${key}</span>
          ${graves.has(key) ? '<span class="grave-mark">GY</span>' : ""}
          ${terrainByHex[key] ? `<span class="terrain-chip">${terrainByHex[key].slice(0, 5).toUpperCase()}</span>` : ""}
          ${unit ? unitToken(unit) : ""}
        </button>
      `;
    }
  }
  html += renderPathOverlay();
  setTimeout(() => {
    document.querySelectorAll(".hex").forEach((hex) => {
      hex.addEventListener("click", () => handleHexClick(Number(hex.dataset.q), Number(hex.dataset.r), hex.dataset.unit || null));
      hex.addEventListener("dblclick", () => handleHexDoubleClick(Number(hex.dataset.q), Number(hex.dataset.r), hex.dataset.unit || null));
      hex.addEventListener("contextmenu", (event) => handleHexContextMenu(event, hex.dataset.unit || null));
      hex.addEventListener("pointerdown", (event) => handleHexPointerDown(event, Number(hex.dataset.q), Number(hex.dataset.r), hex.dataset.unit || null));
      hex.addEventListener("mouseenter", () => updateHoverCard(hex.dataset.key));
      hex.addEventListener("focus", () => updateHoverCard(hex.dataset.key));
    });
  }, 0);
  return `<div class="hex-map-inner" style="width:${BOARD_METRICS.width}px; height:${BOARD_METRICS.height}px">${html}</div>`;
}

function renderPathOverlay() {
  const paths = (state.game.turnHistory || [])
    .filter((entry) => entry.board === state.board && entry.kind === "move" && entry.path && entry.path.length > 1)
    .map((entry) => entry.path);
  const lines = paths.map((path) => pathSvg(path, "path-history")).join("");
  const preview = state.pathPreview && state.pathPreview.length > 1 ? pathSvg(state.pathPreview, "path-preview") : "";
  return `<svg id="path-overlay" class="path-overlay" width="${BOARD_METRICS.width}" height="${BOARD_METRICS.height}" viewBox="0 0 ${BOARD_METRICS.width} ${BOARD_METRICS.height}">${lines}${preview}</svg>`;
}

function pathSvg(path, cls) {
  const points = path
    .map((key) => {
      const { q, r } = parseHex(key);
      const { x, y } = hexPosition(q, r);
      return `${x + HEX_WIDTH / 2},${y + HEX_HEIGHT / 2}`;
    })
    .join(" ");
  return `<polyline class="${cls}" points="${points}"></polyline>`;
}

function drawPathPreview(path) {
  state.pathPreview = path || [];
  const overlay = $("path-overlay");
  if (!overlay) return;
  overlay.querySelectorAll(".path-preview").forEach((line) => line.remove());
  if (state.pathPreview.length > 1) {
    overlay.insertAdjacentHTML("beforeend", pathSvg(state.pathPreview, "path-preview"));
  }
}

function boardLookups(b) {
  const water = new Set(b.map.water);
  const graves = new Set(b.map.graveyards);
  const terrainByHex = {};
  Object.entries(b.terrain).forEach(([kind, key]) => {
    if (key) terrainByHex[key] = kind;
  });
  const spawnByHex = {};
  Object.entries(b.map.spawnTiles).forEach(([team, keys]) => keys.forEach((key) => (spawnByHex[key] = team)));
  return { water, graves, terrainByHex, spawnByHex };
}

function inBounds(q, r) {
  const size = board().map.size;
  return q >= 0 && q < size && r >= 0 && r < size;
}

function hexNeighbors(key) {
  const { q, r } = parseHex(key);
  return HEX_DIRECTIONS.map(([dq, dr]) => ({ q: q + dq, r: r + dr }))
    .filter((hex) => inBounds(hex.q, hex.r))
    .map((hex) => hexKey(hex.q, hex.r));
}

function terrainAllowsEntry(kind, stats) {
  if (!kind) return true;
  if (kind === "firestorm") return stats.defense >= 4;
  if (kind === "earthquake") return stats.speed >= 2;
  if (kind === "flood") return stats.flying;
  if (kind === "whirlwind") return stats.persistent;
  return true;
}

function canEnterForMove(unit, key, final) {
  const b = board();
  const { water, terrainByHex } = boardLookups(b);
  const stats = unit.stats;
  if (water.has(key) && !stats.flying) return false;
  if (!terrainAllowsEntry(terrainByHex[key], stats)) return false;
  const occupant = unitAt(key);
  if (!occupant || occupant.id === unit.id) return true;
  if (final) return false;
  if (occupant.team === unit.team) return true;
  return Boolean(stats.flying);
}

function findClientPath(unit, destinationKey) {
  if (!unit || destinationKey === unit.hex) return [unit ? unit.hex : destinationKey];
  const maxSteps = unit.movementRemaining === null || unit.movementRemaining === undefined ? unit.stats.speed : unit.movementRemaining;
  if (maxSteps <= 0) return [];
  const queue = [[unit.hex, [unit.hex]]];
  const seen = new Set([unit.hex]);
  while (queue.length) {
    const [key, path] = queue.shift();
    if (path.length - 1 >= maxSteps) continue;
    for (const next of hexNeighbors(key)) {
      if (seen.has(next)) continue;
      const final = next === destinationKey;
      if (!canEnterForMove(unit, next, final)) continue;
      const nextPath = [...path, next];
      if (final) return nextPath;
      seen.add(next);
      queue.push([next, nextPath]);
    }
  }
  return [];
}

function updateHoverCard(key) {
  const card = $("hover-card");
  if (!card || !state.game) return;
  const b = board();
  const { water, graves, terrainByHex, spawnByHex } = boardLookups(b);
  const unit = unitAt(key);
  const properties = [];
  properties.push(`Hex ${key}`);
  properties.push(water.has(key) ? "Water" : "Plain");
  if (graves.has(key)) properties.push("Graveyard");
  if (spawnByHex[key]) properties.push(`${spawnByHex[key]} spawn`);
  if (terrainByHex[key]) properties.push(state.game.terrainLabels[terrainByHex[key]]);
  card.innerHTML = `
    <div class="hover-props">${properties.map((property) => `<span>${property}</span>`).join("")}</div>
    ${
      unit
        ? `<div class="hover-unit-name">${unit.template.name}</div><div class="hover-unit-preview">${unitToken(unit, true)}</div><div class="hover-unit-stats">${unit.team}; ${unit.stats.speed} speed, ${unit.stats.range} range, ${unit.stats.attack}/${unit.stats.defense}${unit.exhausted ? "; exhausted" : ""}</div>`
        : '<div class="hover-empty">No unit on this tile.</div>'
    }
  `;
}

function updateHoverUnitTemplate(templateId, label = "Unit") {
  const card = $("hover-card");
  const unit = findTemplate(templateId);
  if (!card || !unit) return;
  const terrain = (unit.terrainSpawn || []).map((kind) => state.game.terrainLabels[kind] || kind).join(", ");
  card.innerHTML = `
    <div class="hover-props"><span>${label}</span><span>$${unit.cost}/${unit.rebate}</span><span>${unit.speed} speed</span><span>${unit.range} range</span></div>
    <div class="hover-unit-name">${unit.name}</div>
    <div class="hover-unit-preview">${unitToken({ ...unit, team: state.color }, true)}</div>
    <div class="hover-unit-stats">${unit.attack}/${unit.defense}${terrain ? `; spawns ${terrain}` : ""}</div>
  `;
}

function handleHexClick(q, r, unitId) {
  if (state.suppressClick) return;
  const key = hexKey(q, r);
  if (state.selectedCard) {
    handleSpellClick(q, r, unitId);
    return;
  }
  if (state.terrainSpawnSource) {
    action("spawn_terrain", {
      board: state.board,
      sourceId: state.terrainSpawnSource.unitId,
      terrain: state.terrainSpawnSource.terrain,
      q,
      r,
    });
    state.terrainSpawnSource = null;
    return;
  }
  if (unitId) {
    state.selectedUnit = unitId;
    renderGame();
  } else {
    state.selectedUnit = null;
    renderGame();
  }
}

function handleHexDoubleClick(q, r, unitId) {
  if (!unitId || state.game.turn !== state.color) return;
  const unit = unitById(unitId);
  if (!unit || unit.team !== state.color) return;
  const terrains = unit.stats.terrainSpawn || unit.template.terrainSpawn || [];
  if (!terrains.length) return;
  let terrain = terrains[0];
  if (terrains.length > 1) {
    const choices = terrains.map((kind) => state.game.terrainLabels[kind] || kind).join(", ");
    const answer = window.prompt(`Choose terrain to spawn: ${choices}`, state.game.terrainLabels[terrain] || terrain);
    if (!answer) return;
    const normalized = answer.trim().toLowerCase();
    terrain = terrains.find((kind) => kind === normalized || (state.game.terrainLabels[kind] || "").toLowerCase() === normalized);
    if (!terrain) {
      notice("That terrain is not available to this unit.");
      return;
    }
  }
  state.terrainSpawnSource = { unitId, terrain };
  state.selectedUnit = unitId;
  notice(`Select an adjacent empty hex for ${state.game.terrainLabels[terrain]}.`, true);
}

function handleHexContextMenu(event, unitId) {
  if (!unitId || state.game.turn !== state.color) return;
  const unit = unitById(unitId);
  if (!unit || unit.team !== state.color) return;
  event.preventDefault();
  action("undo_unit", { board: state.board, unitId });
}

function handleHexPointerDown(event, q, r, unitId) {
  if (event.button !== 0 || !unitId || state.game.turn !== state.color || state.selectedCard) return;
  const unit = unitById(unitId);
  if (!unit || unit.team !== state.color) return;
  state.drag = {
    kind: "unit",
    unitId,
    startKey: hexKey(q, r),
    lastKey: hexKey(q, r),
  };
  state.selectedUnit = unitId;
  drawPathPreview([unit.hex]);
  createDragGhost(unitToken(unit), event.clientX, event.clientY);
  event.preventDefault();
}

function handleBenchPointerDown(event, templateId) {
  if (event.button !== 0 || state.game.turn !== state.color || state.selectedCard) return;
  state.drag = {
    kind: "reinforcement",
    templateId,
    startKey: null,
    lastKey: null,
  };
  state.selectedTemplate = templateId;
  const template = findTemplate(templateId);
  if (template) createDragGhost(unitToken({ ...template, team: state.color }), event.clientX, event.clientY);
  event.preventDefault();
}

function hexElementUnderPointer(event) {
  const element = document.elementFromPoint(event.clientX, event.clientY);
  return element ? element.closest(".hex") : null;
}

function dropZoneUnderPointer(event) {
  const element = document.elementFromPoint(event.clientX, event.clientY);
  return element ? element.closest("[data-drop-zone]") : null;
}

function createDragGhost(html, clientX, clientY) {
  removeDragGhost();
  const ghost = document.createElement("div");
  ghost.className = "drag-ghost";
  ghost.innerHTML = html;
  document.body.appendChild(ghost);
  state.dragGhost = ghost;
  moveDragGhost(clientX, clientY);
}

function moveDragGhost(clientX, clientY) {
  if (!state.dragGhost) return;
  state.dragGhost.style.left = `${clientX}px`;
  state.dragGhost.style.top = `${clientY}px`;
}

function removeDragGhost() {
  if (state.dragGhost) {
    state.dragGhost.remove();
    state.dragGhost = null;
  }
}

function handlePointerMove(event) {
  if (!state.drag || !state.game) return;
  moveDragGhost(event.clientX, event.clientY);
  const hex = hexElementUnderPointer(event);
  if (!hex) {
    drawPathPreview([]);
    return;
  }
  const key = hex.dataset.key;
  state.drag.lastKey = key;
  if (state.drag.kind === "unit") {
    const unit = unitById(state.drag.unitId);
    const occupant = unitAt(key);
    if (unit && (!occupant || occupant.id === unit.id)) {
      drawPathPreview(findClientPath(unit, key));
    } else {
      drawPathPreview([]);
    }
  }
}

function handlePointerUp(event) {
  if (!state.drag || !state.game) return;
  const drag = state.drag;
  state.drag = null;
  const dropZone = dropZoneUnderPointer(event);
  const hex = hexElementUnderPointer(event);
  removeDragGhost();
  drawPathPreview([]);
  if (drag.kind === "unit") {
    const unit = unitById(drag.unitId);
    if (!unit) return;
    if (dropZone && dropZone.dataset.dropZone === "reinforcements") {
      state.suppressClick = true;
      if (unit.stats.blink) {
        action("blink_unit", { board: state.board, unitId: drag.unitId });
      } else {
        notice("Only units with Blink can be dragged back to reinforcements.");
      }
      setTimeout(() => {
        state.suppressClick = false;
      }, 0);
      return;
    }
    if (!hex) return;
    const q = Number(hex.dataset.q);
    const r = Number(hex.dataset.r);
    const unitId = hex.dataset.unit || null;
    if (unitId && unitId !== drag.unitId) {
      const target = unitById(unitId);
      if (target && target.team !== unit.team) {
        state.suppressClick = true;
        action("attack", { board: state.board, attackerId: drag.unitId, targetId: unitId });
      }
    } else if (hex.dataset.key !== drag.startKey) {
      state.suppressClick = true;
      action("move", { board: state.board, unitId: drag.unitId, q, r });
    }
  } else if (drag.kind === "reinforcement") {
    if (!hex) return;
    const q = Number(hex.dataset.q);
    const r = Number(hex.dataset.r);
    state.suppressClick = true;
    action("spawn", { board: state.board, templateId: drag.templateId, q, r });
  }
  if (state.suppressClick) {
    setTimeout(() => {
      state.suppressClick = false;
    }, 0);
  }
}

function renderReinforcements(b) {
  const list = b.reinforcements[state.color] || [];
  if (!list.length) return '<div class="mini-card">No reinforcements on this board.</div>';
  return list.map((unit) => `
    <div class="mini-card">
      <strong>${unit.name} $${unit.cost}/${unit.rebate}</strong>
      <button class="bench-unit ${state.selectedTemplate === unit.id ? "active" : ""}" type="button" data-template="${unit.id}" onmouseenter="updateHoverUnitTemplate('${unit.id}', 'Reinforcement')" onfocus="updateHoverUnitTemplate('${unit.id}', 'Reinforcement')" onclick="state.selectedTemplate='${unit.id}'">${unitToken({ ...unit, team: state.color })}</button>
      <div>${unit.speed} speed, ${unit.range} range, ${unit.attack}/${unit.defense}</div>
      <div class="muted">Drag onto a legal adjacent spawn hex.</div>
    </div>
  `).join("");
}

function renderResearch() {
  const researched = team().researched || [];
  if (!researched.length) return '<div class="mini-card">No researched minions yet.</div>';
  return researched.map((unit) => `
    <div class="mini-card">
      <strong>${unit.name} $${unit.cost}/${unit.rebate}</strong>
      <button class="bench-unit" type="button" onmouseenter="updateHoverUnitTemplate('${unit.id}', 'Researched minion')" onfocus="updateHoverUnitTemplate('${unit.id}', 'Researched minion')" onclick="action('buy', {board:${state.board}, templateId:'${unit.id}'})">${unitToken({ ...unit, team: state.color })}</button>
      <div>${unit.speed} speed, ${unit.range} range, ${unit.attack}/${unit.defense}</div>
      <button class="secondary" onclick="action('buy', {board:${state.board}, templateId:'${unit.id}'})">Buy</button>
    </div>
  `).join("");
}

function renderHand() {
  const hand = team().hand || [];
  if (!hand.length) return '<div class="mini-card">No spells in hand.</div>';
  return hand.map((card) => `
    <div class="mini-card">
      <strong>${card.name}${card.manaCost ? ` (${card.manaCost} mana)` : ""}</strong>
      <div>${card.duration ? "Duration. " : ""}${card.cantrip ? "Cantrip. " : ""}${card.spawnPhaseOnly ? "Spawn only. " : ""}${card.text}</div>
      <div class="mini-actions">
        <button class="secondary ${state.selectedCard && state.selectedCard.cardId === card.cardId ? "active" : ""}" onclick="selectCardById('${card.cardId}', false)">Cast</button>
        <button class="secondary" onclick="selectCardById('${card.cardId}', true)">Discard</button>
      </div>
    </div>
  `).join("");
}

function renderTurnHistory() {
  const history = (state.game.turnHistory || []).filter((entry) => entry.board === null || entry.board === state.board);
  if (!history.length) return '<div class="mini-card">No operations recorded this turn.</div>';
  return history.map((entry) => `
    <div class="mini-card turn-action">
      <strong>${entry.sequence}. ${entry.kind}</strong>
      <div>${entry.summary}</div>
      ${entry.path && entry.path.length > 1 ? `<div class="muted">${entry.path.join(" → ")}</div>` : ""}
    </div>
  `).join("");
}

function selectCardById(cardId, discard) {
  const card = (team().hand || []).find((candidate) => candidate.cardId === cardId);
  if (card) selectCard(card, discard);
}

function selectCard(card, discard) {
  state.selectedCard = { ...card, discard };
  state.spellTarget = null;
  state.mode = "spell";
  notice(discard && !card.cantrip ? "Discarding for mana." : `Select a target for ${card.name}.`, true);
  if (discard && !card.cantrip) {
    action("discard_spell", { cardId: card.cardId });
  } else {
    renderGame();
  }
}

function spellNeedsDestination(spellId) {
  return ["stumble", "double_stumble", "reposition", "firestorm", "earthquake", "flood", "whirlwind", "terraform", "lesser_spawn", "raise_zombie"].includes(spellId);
}

function spellCanTargetTerrain(spellId) {
  return spellId === "normalize";
}

function handleSpellClick(q, r, unitId) {
  const card = state.selectedCard;
  if (!card) return;
  if (spellCanTargetTerrain(card.id) && !unitId) {
    const payload = { board: state.board, cardId: card.cardId, q, r };
    action(card.discard ? "discard_spell" : "cast_spell", payload);
    state.selectedCard = null;
    return;
  }
  if (!state.spellTarget && unitId) {
    if (spellNeedsDestination(card.id)) {
      state.spellTarget = unitId;
      notice(`Target selected for ${card.name}; click the destination hex.`, true);
      return;
    }
    const payload = { board: state.board, cardId: card.cardId, targetId: unitId };
    action(card.discard ? "discard_spell" : "cast_spell", payload);
    state.selectedCard = null;
    return;
  }
  if (state.spellTarget) {
    const payload = {
      board: state.board,
      cardId: card.cardId,
      targetId: state.spellTarget,
      q,
      r,
      terrain: state.terrain,
      templateId: state.selectedTemplate,
    };
    action(card.discard ? "discard_spell" : "cast_spell", payload);
    state.selectedCard = null;
    state.spellTarget = null;
  }
}

function renderGeneratedMap(map) {
  const fakeGame = state.game;
  const fakeBoard = {
    map,
    terrain: { firestorm: null, earthquake: null, flood: null, whirlwind: null },
    units: [],
  };
  const oldGame = state.game;
  const oldBoard = state.board;
  state.game = { boards: [fakeBoard], terrainLabels: map.terrainLabels };
  state.board = 0;
  const html = `<div class="map-wrap"><div class="hex-map">${renderMap(fakeBoard)}</div></div><pre>${JSON.stringify(map, null, 2)}</pre>`;
  state.game = oldGame;
  state.board = oldBoard;
  return html;
}

function renderGeneratedUnit(unit, alpha) {
  return `
    <div class="unit-preview">${unitToken(unit, true)}</div>
    <pre>${JSON.stringify({ alpha, unit }, null, 2)}</pre>
  `;
}

document.querySelectorAll(".tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((t) => t.classList.remove("active"));
    document.querySelectorAll(".view").forEach((v) => v.classList.remove("active"));
    tab.classList.add("active");
    $(`${tab.dataset.view}-view`).classList.add("active");
  });
});

document.addEventListener("pointermove", handlePointerMove);
document.addEventListener("pointerup", handlePointerUp);

$("color-input").value = state.color;
$("color-input").addEventListener("change", (event) => {
  state.color = event.target.value;
  localStorage.setItem("minions-color", state.color);
  if (state.vsAI) state.aiColor = opponentColor();
  renderGame();
});

$("create-game").addEventListener("click", async () => {
  try {
    configureHumanGame($("color-input").value);
    const data = await api("/api/games", {
      method: "POST",
      body: JSON.stringify({ boards: Number($("boards-input").value || 1) }),
    });
    state.game = data.game;
    $("code-input").value = state.game.code;
    renderGame();
    notice(`Created players game ${state.game.code}.`, true);
  } catch (err) {
    notice(err.message);
  }
});

$("play-ai").addEventListener("click", async () => {
  try {
    configureAIGame($("color-input").value);
    const data = await api("/api/games", {
      method: "POST",
      body: JSON.stringify({ boards: Number($("boards-input").value || 1) }),
    });
    state.game = data.game;
    $("code-input").value = state.game.code;
    renderGame();
    notice(`Started game ${state.game.code}. You are ${state.color}; AI is ${state.aiColor}.`, true);
    await maybeAutoPlayAI();
  } catch (err) {
    state.aiThinking = false;
    renderGame();
    notice(err.message);
  }
});

$("join-game").addEventListener("click", async () => {
  try {
    configureHumanGame($("color-input").value);
    const code = $("code-input").value.trim().toUpperCase();
    const data = await api(`/api/games/${code}/join`, {
      method: "POST",
      body: JSON.stringify({ color: state.color, name: state.color }),
    });
    state.game = data.game;
    renderGame();
    notice(`Joined ${code} as ${state.color}.`, true);
  } catch (err) {
    notice(err.message);
  }
});

$("generate-map").addEventListener("click", async () => {
  try {
    const data = await api("/api/generators/map");
    $("map-lab").innerHTML = renderGeneratedMap(data.map);
    notice("Generated map.", true);
  } catch (err) {
    notice(err.message);
  }
});

$("generate-unit").addEventListener("click", async () => {
  try {
    const data = await api("/api/generators/unit");
    $("unit-lab").innerHTML = renderGeneratedUnit(data.unit, data.alpha);
    notice("Generated unit.", true);
  } catch (err) {
    notice(err.message);
  }
});

window.action = action;
window.aiTurn = aiTurn;
window.setMode = setMode;
window.selectCardById = selectCardById;
window.updateHoverUnitTemplate = updateHoverUnitTemplate;
window.state = state;
