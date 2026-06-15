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
  mapPan: null,
  mapZoom: Math.min(2.4, Math.max(0.55, Number(localStorage.getItem("minions-map-zoom")) || 1)),
  mapViews: {},
  pathPreview: [],
  suppressClick: false,
  vsAI: false,
  aiColor: null,
  aiThinking: false,
  historyOpen: false,
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
  const contentType = res.headers.get("Content-Type") || "";
  const text = await res.text();
  let data = {};
  if (contentType.includes("application/json") && text) {
    try {
      data = JSON.parse(text);
    } catch (_err) {
      data = {};
    }
  }
  if (!res.ok) {
    const error = new Error(data.error || `Request failed with HTTP ${res.status}`);
    error.data = data;
    throw error;
  }
  if (!contentType.includes("application/json")) {
    throw new Error(`Expected JSON but received ${contentType || "an unknown response type"}`);
  }
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
  const mapView = currentMapViewSnapshot();
  const data = await api(`/api/games/${state.game.code}`);
  state.game = data.game;
  if (state.board >= state.game.boards.length) state.board = 0;
  if (mapView && Number.isFinite(mapView.zoom)) state.mapZoom = mapView.zoom;
  renderGame();
  restoreCapturedMapView(mapView);
}

async function action(actionName, payload = {}) {
  if (!state.game) return;
  const mapView = currentMapViewSnapshot();
  try {
    const data = await api(`/api/games/${state.game.code}/actions`, {
      method: "POST",
      body: JSON.stringify({ color: state.color, action: actionName, payload }),
    });
    state.game = data.game;
    state.pathPreview = data.result && data.result.path ? data.result.path : [];
    if (mapView && Number.isFinite(mapView.zoom)) state.mapZoom = mapView.zoom;
    renderGame();
    restoreCapturedMapView(mapView);
    notice("Done.", true);
    await maybeAutoPlayAI();
  } catch (err) {
    resetInteractionState();
    if (err.data && err.data.game) {
      state.game = err.data.game;
      if (mapView && Number.isFinite(mapView.zoom)) state.mapZoom = mapView.zoom;
      renderGame();
      restoreCapturedMapView(mapView);
    } else {
      try {
        await refreshGame();
      } catch (_refreshErr) {
        renderGame();
      }
    }
    notice(err.message);
  }
}

async function aiTurn(color = state.color, silent = false) {
  if (!state.game) return;
  const mapView = currentMapViewSnapshot();
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
    if (mapView && Number.isFinite(mapView.zoom)) state.mapZoom = mapView.zoom;
    renderGame();
    restoreCapturedMapView(mapView);
    const count = data.result && data.result.actions ? data.result.actions.length : 0;
    const elapsed = data.result && data.result.elapsedSeconds ? data.result.elapsedSeconds.toFixed(2) : "0.00";
    notice(`AI played ${count} action${count === 1 ? "" : "s"} in ${elapsed}s.`, true);
  } catch (err) {
    state.aiThinking = false;
    if (mapView && Number.isFinite(mapView.zoom)) state.mapZoom = mapView.zoom;
    renderGame();
    restoreCapturedMapView(mapView);
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

function notebookIcon() {
  return `
    <svg class="ui-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <path d="M7 4h10a2 2 0 012 2v14H7a2 2 0 01-2-2V6a2 2 0 012-2z" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/>
      <path d="M9 4v16M12 8h4M12 12h4M12 16h3" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
    </svg>
  `;
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

function isNumericAttack(value) {
  return typeof value === "number" && Number.isFinite(value);
}

function currentHealth(unit) {
  const stats = unit.stats || unit;
  const defense = Number(stats.defense);
  if (!Number.isFinite(defense)) return stats.defense;
  return Math.max(0, defense - Number(unit.damage || 0));
}

function healthClass(unit) {
  const tpl = unit.template || unit;
  const base = Number(tpl.defense);
  const health = Number(currentHealth(unit));
  if (!Number.isFinite(base) || !Number.isFinite(health) || health === base) return "";
  return health < base ? "health-damaged" : "health-boosted";
}

function flurryAttackValue(unit, stats, attack) {
  if (!stats.flurry || !isNumericAttack(attack)) return { value: attack, adjusted: false };
  if (unit.flurryRemaining === null || unit.flurryRemaining === undefined) return { value: attack, adjusted: false };
  return { value: unit.flurryRemaining, adjusted: unit.flurryRemaining !== attack };
}

function unitToken(unit, preview = false) {
  const tpl = unit.template || unit;
  const stats = unit.stats || unit;
  const onGraveyard = Boolean(unit.hex && state.game && boardLookups(board()).graves.has(unit.hex));
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
  const flurryAttack = flurryAttackValue(unit, stats, attack);
  const attackClass = flurryAttack.adjusted ? " adjusted-stat" : "";
  const atk = stats.flurry
    ? `${attackIcon(stats.range)}<span class="stat-value${attackClass}">${flurryAttack.value}</span>${attackIcon(stats.range, "mirror")}`
    : `<span class="stat-value">${flurryAttack.value}</span>${attackIcon(stats.range)}`;
  const defenseIcon = stats.persistent ? svgIcon("anchor") : svgIcon("shield");
  const defenseInner = `<span class="stat-value health-value ${healthClass(unit)}">${currentHealth(unit)}</span>${defenseIcon}`;
  const defense = stats.ward ? `<span class="warded">${defenseInner}</span>` : defenseInner;
  const movementKeywordCount = (stats.flying ? 1 : 0) + (stats.lumbering ? 1 : 0);
  const abilityKeywordCount = (stats.spawn ? 1 : 0) + (stats.blink ? 1 : 0);
  const ability = [
    stats.spawn ? "⬡→⬡" : "",
    stats.blink ? "✦" : "",
  ].filter(Boolean).join("");
  const terrain = (stats.terrainSpawn || tpl.terrainSpawn || []).map((kind) => kind.slice(0, 4).toUpperCase()).join(" ");
  return `
    <div class="unit-token ${preview ? "preview-token" : ""} ${unit.team || "yellow"} ${onGraveyard ? "on-graveyard" : ""} ${unit.exhausted ? "exhausted" : ""} movement-keywords-${movementKeywordCount} ability-keywords-${abilityKeywordCount} ${statusClass}">
      <div class="cost-line">$${tpl.cost}/${tpl.rebate}</div>
      <div class="unit-name">${tpl.name}</div>
      <div class="speed-line">${stats.speed} ${speedIcon({ stats })}</div>
      <div class="ability-line">${ability}</div>
      <div class="terrain-line">${terrain}</div>
      <div class="combat-line ${stats.flurry ? "flurry-combat" : ""}"><span>${atk}</span><span>${defense}</span></div>
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

function mapViewKey(index = state.board) {
  return state.game ? `${state.game.code}:${index}` : `board:${index}`;
}

function saveMapView(wrap) {
  if (!wrap || !state.game) return;
  const index = Number(wrap.dataset.boardIndex || state.board);
  state.mapViews[mapViewKey(index)] = {
    left: wrap.scrollLeft,
    top: wrap.scrollTop,
    zoom: state.mapZoom,
  };
}

function currentMapViewSnapshot() {
  const wrap = document.querySelector(".map-wrap[data-map-wrap]");
  if (!wrap || !state.game) return null;
  const index = Number(wrap.dataset.boardIndex || state.board);
  return {
    index,
    left: wrap.scrollLeft,
    top: wrap.scrollTop,
    zoom: state.mapZoom,
  };
}

function restoreCapturedMapView(snapshot) {
  if (!snapshot || !state.game) return;
  state.mapViews[mapViewKey(snapshot.index)] = {
    left: snapshot.left,
    top: snapshot.top,
    zoom: snapshot.zoom,
  };
  restoreMapView();
}

function captureMapView() {
  const wrap = document.querySelector(".map-wrap[data-map-wrap]");
  saveMapView(wrap);
}

function applySavedMapZoom() {
  const saved = state.mapViews[mapViewKey()];
  if (saved && Number.isFinite(saved.zoom)) {
    state.mapZoom = saved.zoom;
  }
}

function restoreMapView() {
  const wrap = document.querySelector(".map-wrap[data-map-wrap]");
  if (!wrap || !state.game) return;
  const saved = state.mapViews[mapViewKey()];
  if (!saved) return;
  requestAnimationFrame(() => {
    requestAnimationFrame(() => {
      wrap.scrollLeft = saved.left;
      wrap.scrollTop = saved.top;
    });
  });
}

function sessionFormHtml() {
  return `
    <form id="session-form" class="session-form session-card">
      <div class="session-primary-row">
        <label>
          Boards
          <input id="boards-input" type="number" min="1" max="9" value="1" />
        </label>
        <label>
          Your Color
          <select id="color-input">
            <option value="yellow">Yellow</option>
            <option value="blue">Blue</option>
          </select>
        </label>
        <button type="button" id="create-game">New Game vs Players</button>
        <button type="button" id="play-ai">Play vs AI</button>
      </div>
      <div class="session-join-row">
        <label>
          Code
          <input id="code-input" maxlength="6" autocomplete="off" />
        </label>
        <button type="button" id="join-game">Join</button>
      </div>
    </form>
  `;
}

function renderEmptyGame() {
  const root = $("game-root");
  root.className = "game-root empty-state session-empty";
  root.innerHTML = sessionFormHtml();
  wireSessionForm();
}

function wireSessionForm() {
  const colorInput = $("color-input");
  const createGame = $("create-game");
  const playAI = $("play-ai");
  const joinGame = $("join-game");
  if (!colorInput || !createGame || createGame.dataset.wired) return;
  createGame.dataset.wired = "true";
  playAI.dataset.wired = "true";
  joinGame.dataset.wired = "true";
  colorInput.value = state.color;
  colorInput.addEventListener("change", (event) => {
    state.color = event.target.value;
    localStorage.setItem("minions-color", state.color);
    if (state.vsAI) state.aiColor = opponentColor();
    renderGame();
  });
  createGame.addEventListener("click", async () => {
    try {
      configureHumanGame(colorInput.value);
      const data = await api("/api/games", {
        method: "POST",
        body: JSON.stringify({ boards: Number($("boards-input").value || 1) }),
      });
      state.game = data.game;
      renderGame();
      notice(`Created players game ${state.game.code}.`, true);
    } catch (err) {
      notice(err.message);
    }
  });
  playAI.addEventListener("click", async () => {
    try {
      configureAIGame(colorInput.value);
      const data = await api("/api/games", {
        method: "POST",
        body: JSON.stringify({ boards: Number($("boards-input").value || 1) }),
      });
      state.game = data.game;
      renderGame();
      notice(`Started game ${state.game.code}. You are ${state.color}; AI is ${state.aiColor}.`, true);
      await maybeAutoPlayAI();
    } catch (err) {
      state.aiThinking = false;
      renderGame();
      notice(err.message);
    }
  });
  joinGame.addEventListener("click", async () => {
    try {
      configureHumanGame(colorInput.value);
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
}

function renderGame() {
  const root = $("game-root");
  if (!state.game) {
    renderEmptyGame();
    return;
  }
  captureMapView();
  applySavedMapZoom();
  root.className = "game-root";
  const currentBoard = board();
  const active = state.game.turn === state.color && !state.aiThinking;
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
        <button id="history-toggle" class="icon-button secondary" type="button" aria-expanded="${state.historyOpen ? "true" : "false"}" aria-controls="history-popover" title="Turn actions and log">${notebookIcon()}</button>
      </div>
      <div id="history-popover" class="history-popover" ${state.historyOpen ? "" : "hidden"}>
        <section>
          <h3>Turn Actions</h3>
          <div class="compact-list scroll-list actions-scroll">${renderTurnHistory()}</div>
        </section>
        <section>
          <h3>Log</h3>
          <div class="log">${state.game.log.slice().reverse().map((line) => `<div>${line}</div>`).join("")}</div>
        </section>
      </div>
    </div>
    <div class="game-layout">
      <div class="map-column">
        <div class="action-bar">
          <div class="board-selector">
            ${state.game.boards.map((b, idx) => `<button class="secondary ${idx === state.board ? "active" : ""}" data-board="${idx}">Board ${idx + 1}</button>`).join("")}
          </div>
          <button ${!active || !state.game.canRedo ? "disabled" : ""} onclick="action('redo')">Redo</button>
          <button ${!active || currentBoard.winner ? "disabled" : ""} onclick="confirm('Resign this board? Your opponent gets a board point now.') && action('resign_board', {board:${state.board}})">Resign Board</button>
          <button ${!active ? "disabled" : ""} onclick="action('end_turn')">End Turn</button>
          <button class="info-button secondary" type="button" title="${state.vsAI && state.game.turn === state.aiColor ? "The AI is taking its turn." : "Drag units to move or attack. Drag reinforcements onto legal spawn hexes. Right-click a unit to undo its last operation."}" aria-label="Turn controls help">i</button>
        </div>
        <div class="map-wrap" data-map-wrap data-board-index="${state.board}">${renderMap(currentBoard)}</div>
      </div>
      <aside class="side-panel">
        <section class="side-section panel-reinforcements" data-drop-zone="reinforcements">
          <h3>Reinforcements</h3>
          <div class="compact-list">${renderReinforcements(currentBoard)}</div>
        </section>
        <section class="side-section panel-research">
          <h3>Research & Buy</h3>
          <div class="mini-actions research-actions">
            <button onclick="action('research')">Research $1</button>
            <button onclick="action('buy', {board:${state.board}, templateId:'zombie'})">Buy Zombie $2</button>
          </div>
          <div class="compact-list research-list">${renderResearch()}</div>
        </section>
        <section class="side-section panel-spells">
          <h3>Spells</h3>
          <div class="compact-list scroll-list spells-scroll">${renderHand(currentBoard)}</div>
        </section>
        <section class="side-section panel-hover">
          <h3>Hover</h3>
          <div id="hover-card" class="hover-card mini-card">Hover a tile to inspect it.</div>
        </section>
      </aside>
    </div>
  `;
  const historyToggle = $("history-toggle");
  if (historyToggle) {
    historyToggle.addEventListener("click", (event) => {
      event.stopPropagation();
      state.historyOpen = !state.historyOpen;
      renderGame();
    });
  }
  document.querySelectorAll("[data-board]").forEach((button) => {
    button.addEventListener("click", () => {
      state.board = Number(button.dataset.board);
      state.selectedUnit = null;
      state.selectedCard = null;
      state.spellTarget = null;
      state.pathPreview = [];
      renderGame();
    });
  });
  document.querySelectorAll(".bench-unit[data-template]").forEach((button) => {
    button.addEventListener("pointerdown", (event) => handleBenchPointerDown(event, button.dataset.template, button.dataset.source || "reinforcement"));
  });
  wireMapInteractions();
  restoreMapView();
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

function mapDimensions(zoom = state.mapZoom) {
  return {
    width: BOARD_METRICS.width * zoom,
    height: BOARD_METRICS.height * zoom,
  };
}

function terrainMarker(kind) {
  if (kind === "firestorm") return `<span class="terrain-mark terrain-firestorm-mark"><span>4</span>${svgIcon("shield")}</span>`;
  if (kind === "earthquake") return `<span class="terrain-mark terrain-earthquake-mark"><span>2</span>${svgIcon("footprints")}</span>`;
  if (kind === "flood") return `<span class="terrain-mark terrain-flood-mark">${svgIcon("wings")}</span>`;
  if (kind === "whirlwind") return `<span class="terrain-mark terrain-whirlwind-mark">${svgIcon("anchor")}</span>`;
  return "";
}

function hexSurfaceClasses(key, lookups) {
  return [
    lookups.water.has(key) ? "water" : "",
    lookups.graves.has(key) ? "graveyard" : "",
    lookups.terrainByHex[key] ? `terrain-${lookups.terrainByHex[key]}` : "",
    lookups.spawnByHex[key] ? `spawn-${lookups.spawnByHex[key]}` : "",
  ].filter(Boolean);
}

function renderMap(b) {
  const lookups = boardLookups(b);
  let html = "";
  for (let q = 0; q < b.map.size; q++) {
    for (let r = 0; r < b.map.size; r++) {
      const key = hexKey(q, r);
      const { x, y } = hexPosition(q, r);
      const unit = unitAt(key);
      const terrain = lookups.terrainByHex[key];
      const classes = [
        "hex",
        ...hexSurfaceClasses(key, lookups),
        state.selectedUnit && unit && unit.id === state.selectedUnit ? "selected" : "",
      ].join(" ");
      html += `
        <button class="${classes}" style="left:${x}px; top:${y}px" data-key="${key}" data-q="${q}" data-r="${r}" data-unit="${unit ? unit.id : ""}">
          <span class="coord">${key}</span>
          ${terrain ? terrainMarker(terrain) : ""}
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
  const dimensions = mapDimensions();
  return `<div class="hex-map" style="width:${dimensions.width}px; height:${dimensions.height}px"><div class="hex-map-inner" style="width:${BOARD_METRICS.width}px; height:${BOARD_METRICS.height}px; transform:scale(${state.mapZoom})">${html}</div></div>`;
}

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

function applyMapZoom(wrap, nextZoom, clientX, clientY) {
  const previousZoom = state.mapZoom;
  const zoom = clamp(nextZoom, 0.55, 2.4);
  if (Math.abs(zoom - previousZoom) < 0.001) return;
  const rect = wrap.getBoundingClientRect();
  const offsetX = clientX - rect.left;
  const offsetY = clientY - rect.top;
  const anchorX = (wrap.scrollLeft + offsetX) / previousZoom;
  const anchorY = (wrap.scrollTop + offsetY) / previousZoom;
  state.mapZoom = zoom;
  localStorage.setItem("minions-map-zoom", String(zoom));
  const dimensions = mapDimensions(zoom);
  const map = wrap.querySelector(".hex-map");
  const inner = wrap.querySelector(".hex-map-inner");
  if (map) {
    map.style.width = `${dimensions.width}px`;
    map.style.height = `${dimensions.height}px`;
  }
  if (inner) inner.style.transform = `scale(${zoom})`;
  wrap.scrollLeft = anchorX * zoom - offsetX;
  wrap.scrollTop = anchorY * zoom - offsetY;
  saveMapView(wrap);
}

function handleMapWheel(event) {
  event.preventDefault();
  const factor = event.deltaY < 0 ? 1.12 : 1 / 1.12;
  applyMapZoom(event.currentTarget, state.mapZoom * factor, event.clientX, event.clientY);
}

function handleMapPointerDown(event) {
  if (event.button !== 0 || state.drag || !event.currentTarget.contains(event.target)) return;
  if (event.target.closest(".unit-token")) return;
  state.mapPan = {
    wrap: event.currentTarget,
    startX: event.clientX,
    startY: event.clientY,
    scrollLeft: event.currentTarget.scrollLeft,
    scrollTop: event.currentTarget.scrollTop,
    moved: false,
  };
}

function wireMapInteractions() {
  document.querySelectorAll(".map-wrap[data-map-wrap]").forEach((wrap) => {
    if (wrap.dataset.mapWired) return;
    wrap.dataset.mapWired = "true";
    wrap.addEventListener("wheel", handleMapWheel, { passive: false });
    wrap.addEventListener("pointerdown", handleMapPointerDown);
  });
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
  const lookups = boardLookups(b);
  const { water, graves, terrainByHex, spawnByHex } = lookups;
  const unit = unitAt(key);
  const properties = [];
  properties.push(`Hex ${key}`);
  properties.push(water.has(key) ? "Water" : "Plain");
  if (graves.has(key)) properties.push("Graveyard");
  if (spawnByHex[key]) properties.push(`${spawnByHex[key]} spawn`);
  if (terrainByHex[key]) properties.push(state.game.terrainLabels[terrainByHex[key]]);
  if (!unit) {
    const terrain = terrainByHex[key];
    card.innerHTML = `
      <div class="hover-props">${properties.map((property) => `<span>${property}</span>`).join("")}</div>
      <div class="hover-hex-preview ${hexSurfaceClasses(key, lookups).join(" ")}"><span class="coord">${key}</span>${terrain ? terrainMarker(terrain) : ""}</div>
    `;
    return;
  }
  card.innerHTML = `
    <div class="hover-props">${properties.map((property) => `<span>${property}</span>`).join("")}</div>
    <div class="hover-unit-name">${unit.template.name}</div>
    <div class="hover-unit-preview">${unitToken(unit, true)}</div>
    <div class="hover-unit-stats">${unit.team}; ${unit.stats.speed} speed, ${unit.stats.range} range, ${unit.stats.attack}/${currentHealth(unit)} health${unit.exhausted ? "; exhausted" : ""}</div>
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
    terrain = promptTerrainChoice(terrains, terrain);
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
  if (!event.target.closest(".unit-token")) return;
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

function handleBenchPointerDown(event, templateId, source = "reinforcement") {
  if (event.button !== 0 || state.game.turn !== state.color || state.selectedCard) return;
  state.drag = {
    kind: source === "research" ? "research" : "reinforcement",
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

function flurryRemaining(unit) {
  const attack = unit && unit.stats ? unit.stats.attack : null;
  if (!unit || !unit.stats.flurry || !isNumericAttack(attack)) return null;
  return unit.flurryRemaining === null || unit.flurryRemaining === undefined ? attack : unit.flurryRemaining;
}

function promptFlurryDamage(attacker, target) {
  const remaining = flurryRemaining(attacker);
  if (!remaining || remaining <= 0) return null;
  const suggested = Math.max(1, Math.min(remaining, Number(currentHealth(target)) || remaining));
  const answer = window.prompt(`Enter the amount of flurry damage to deal, up to ${remaining}.`, String(suggested));
  if (answer === null) return null;
  const amount = Number(answer);
  if (!Number.isInteger(amount) || amount <= 0 || amount > remaining) {
    notice(`Enter a whole number from 1 to ${remaining}.`);
    return null;
  }
  return amount;
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
  if (state.mapPan) {
    const pan = state.mapPan;
    const dx = event.clientX - pan.startX;
    const dy = event.clientY - pan.startY;
    if (Math.abs(dx) > 2 || Math.abs(dy) > 2) pan.moved = true;
    if (pan.moved) {
      pan.wrap.classList.add("panning");
      pan.wrap.scrollLeft = pan.scrollLeft - dx;
      pan.wrap.scrollTop = pan.scrollTop - dy;
      event.preventDefault();
    }
    return;
  }
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
  if (state.mapPan) {
    const panned = state.mapPan.moved;
    state.mapPan.wrap.classList.remove("panning");
    saveMapView(state.mapPan.wrap);
    state.mapPan = null;
    if (panned) {
      state.suppressClick = true;
      setTimeout(() => {
        state.suppressClick = false;
      }, 0);
    }
    return;
  }
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
        const amount = event.altKey && flurryRemaining(unit) ? promptFlurryDamage(unit, target) : null;
        if (event.altKey && flurryRemaining(unit) && amount === null) return;
        const payload = { board: state.board, attackerId: drag.unitId, targetId: unitId };
        if (amount !== null) payload.amount = amount;
        state.suppressClick = true;
        action("attack", payload);
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
  } else if (drag.kind === "research") {
    if (dropZone && dropZone.dataset.dropZone === "reinforcements") {
      state.suppressClick = true;
      action("buy", { board: state.board, templateId: drag.templateId });
    }
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
  const densityClass = list.length >= 2 ? "dense" : "single";
  return `<div class="reinforcement-list ${densityClass} ${list.length > 6 ? "scrollable" : ""}">${list.map((unit) => `
    <div class="mini-card">
      <strong>${unit.name} $${unit.cost}/${unit.rebate}</strong>
      <button class="bench-unit ${state.selectedTemplate === unit.id ? "active" : ""}" type="button" data-template="${unit.id}" onmouseenter="updateHoverUnitTemplate('${unit.id}', 'Reinforcement')" onfocus="updateHoverUnitTemplate('${unit.id}', 'Reinforcement')" onclick="state.selectedTemplate='${unit.id}'">${unitToken({ ...unit, team: state.color })}</button>
      <div class="bench-stats">${unit.speed} speed, ${unit.range} range, ${unit.attack}/${unit.defense}</div>
      <div class="muted bench-help">Drag onto a legal adjacent spawn hex.</div>
    </div>
  `).join("")}</div>`;
}

function renderResearch() {
  const researched = team().researched || [];
  if (!researched.length) return '<div class="mini-card research-empty">No researched minions yet.</div>';
  const densityClass = researched.length >= 2 ? "dense" : "single";
  return `<div class="reinforcement-list research-bench-list ${densityClass} ${researched.length > 6 ? "scrollable" : ""}">${researched.map((unit) => `
    <div class="mini-card">
      <strong>${unit.name} $${unit.cost}/${unit.rebate}</strong>
      <button class="bench-unit" type="button" data-template="${unit.id}" data-source="research" onmouseenter="updateHoverUnitTemplate('${unit.id}', 'Researched minion')" onfocus="updateHoverUnitTemplate('${unit.id}', 'Researched minion')" onclick="action('buy', {board:${state.board}, templateId:'${unit.id}'})">${unitToken({ ...unit, team: state.color })}</button>
      <div class="bench-stats">${unit.speed} speed, ${unit.range} range, ${unit.attack}/${unit.defense}</div>
      <div class="muted bench-help">Click or drag to Reinforcements to buy.</div>
    </div>
  `).join("")}</div>`;
}

function renderHand(b = board()) {
  const hand = (b.spells && b.spells[state.color]) || [];
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
  const hand = (board().spells && board().spells[state.color]) || [];
  const card = hand.find((candidate) => candidate.cardId === cardId);
  if (card) selectCard(card, discard);
}

function selectCard(card, discard) {
  state.selectedCard = { ...card, discard };
  state.spellTarget = null;
  state.mode = "spell";
  notice(discard && !card.cantrip ? "Discarding for mana." : `Select a target for ${card.name}.`, true);
  if (discard && !card.cantrip) {
    action("discard_spell", { board: state.board, cardId: card.cardId });
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

function promptTerrainChoice(terrains, fallback) {
  const labels = terrains.map((kind) => state.game.terrainLabels[kind] || kind);
  const answer = window.prompt(`Choose terrain: ${labels.join(", ")}`, state.game.terrainLabels[fallback] || fallback || labels[0]);
  if (!answer) return null;
  const normalized = answer.trim().toLowerCase();
  return terrains.find((kind) => kind === normalized || (state.game.terrainLabels[kind] || "").toLowerCase() === normalized) || null;
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
    let terrain = null;
    if (card.id === "terraform") {
      terrain = promptTerrainChoice(Object.keys(state.game.terrainLabels), "firestorm");
      if (!terrain) {
        notice("Choose a terrain for Terraform.");
        return;
      }
    }
    const payload = {
      board: state.board,
      cardId: card.cardId,
      targetId: state.spellTarget,
      q,
      r,
      terrain,
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
  const html = `<div class="map-wrap" data-map-wrap>${renderMap(fakeBoard)}</div><pre>${JSON.stringify(map, null, 2)}</pre>`;
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

$("generate-map").addEventListener("click", async () => {
  try {
    const data = await api("/api/generators/map");
    $("map-lab").innerHTML = renderGeneratedMap(data.map);
    wireMapInteractions();
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

renderGame();
