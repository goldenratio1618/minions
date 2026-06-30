const state = {
  game: null,
  color: localStorage.getItem("minions-color") || "yellow",
  board: 0,
  mode: "select",
  selectedUnit: null,
  selectedTemplate: null,
  pendingSubscription: null,
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
  researchViewOpponent: false,
  tutorialStep: 0,
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
  state.pendingSubscription = null;
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
    await maybeAutoPlayAI(mapView);
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

async function aiTurn(color = state.color, silent = false, preservedMapView = null) {
  if (!state.game) return;
  const mapView = preservedMapView || currentMapViewSnapshot();
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

async function maybeAutoPlayAI(preservedMapView = null) {
  if (!state.vsAI || !state.game || state.aiThinking || state.game.winner) return;
  while (state.vsAI && state.game && state.game.turn === state.aiColor && !state.game.winner) {
    await aiTurn(state.aiColor, true, preservedMapView);
  }
}

function configureHumanGame(color) {
  state.color = color;
  state.vsAI = false;
  state.aiColor = null;
  state.aiThinking = false;
  state.pendingSubscription = null;
  state.researchViewOpponent = false;
  localStorage.setItem("minions-color", state.color);
}

function configureAIGame(color) {
  state.color = color;
  state.vsAI = true;
  state.aiColor = opponentColor();
  state.aiThinking = false;
  state.pendingSubscription = null;
  state.researchViewOpponent = false;
  localStorage.setItem("minions-color", state.color);
}

function board() {
  return state.game.boards[state.board] || state.game.boards[0];
}

function team() {
  return state.game.teams[state.color];
}

function teamFor(color) {
  return state.game.teams[color];
}

function opponentColor() {
  return state.color === "yellow" ? "blue" : "yellow";
}

function isSubscriptionsMode() {
  return state.game && state.game.mode === "subscriptions";
}

function visibleResearchColor() {
  return state.researchViewOpponent ? opponentColor() : state.color;
}

function boardSubscriptions(color = state.color, b = board()) {
  return (b.subscriptions && b.subscriptions[color]) || [];
}

function graveyardCounts(b) {
  const graves = new Set(b.map.graveyards || []);
  const counts = { yellow: 0, blue: 0 };
  (b.units || []).forEach((unit) => {
    if (graves.has(unit.hex)) counts[unit.team] += 1;
  });
  return counts;
}

function projectedIncome(color) {
  if (!state.game) return 0;
  return state.game.boards.reduce((total, b) => total + 3 + graveyardCounts(b)[color], 0);
}

function subscriptionAvailableNextTurn(color) {
  const income = state.game.turn === color ? projectedIncome(color) : 0;
  return teamFor(color).souls + income;
}

function subscriptionTotalUnits(unit, amount) {
  if (!state.game || !unit || !unit.cost) return 0;
  return (amount * state.game.subscriptionLength) / unit.cost;
}

function subscriptionSchedule(subscription, color, turns = null) {
  const horizon = turns || state.game.subscriptionLength || 1;
  let purchased = Number(subscription.purchasedCount || 0);
  const teamTurns = Number(teamFor(color).turnsStarted || 0);
  const purchasedTeamTurn = Number(subscription.purchasedTeamTurn || teamTurns);
  const totalUnits = Number(subscription.totalUnits || 0);
  const cost = Number(subscription.cost || (subscription.template && subscription.template.cost) || 1);
  const amount = Number(subscription.amount || 0);
  const schedule = [];
  for (let offset = 1; offset <= horizon; offset += 1) {
    const age = Math.max(0, teamTurns + offset - purchasedTeamTurn);
    const cumulative = Math.min(totalUnits, (amount * age) / cost);
    const targetCount = Math.floor(cumulative + 0.5);
    const count = Math.max(0, targetCount - purchased);
    purchased += count;
    schedule.push({ turn: offset, count, spend: count * cost });
  }
  return schedule;
}

function hypotheticalSubscription(unit, amount, color = state.color) {
  return {
    amount,
    cost: unit.cost,
    totalUnits: subscriptionTotalUnits(unit, amount),
    purchasedCount: 0,
    purchasedTeamTurn: teamFor(color).turnsStarted || 0,
    template: unit,
  };
}

function subscriptionNextSpend(color, hypothetical = null) {
  if (!isSubscriptionsMode()) return 0;
  const subscriptions = state.game.boards.flatMap((b) => boardSubscriptions(color, b));
  if (hypothetical) subscriptions.push(hypothetical);
  return subscriptions.reduce((total, subscription) => {
    const next = subscriptionSchedule(subscription, color, 1)[0];
    return total + (next ? next.spend : 0);
  }, 0);
}

function subscriptionWouldWarn(unit, amount, color = state.color) {
  if (!isSubscriptionsMode() || !unit) return false;
  const hypothetical = hypotheticalSubscription(unit, amount, color);
  return subscriptionNextSpend(color, hypothetical) > subscriptionAvailableNextTurn(color);
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

function reverseIcon() {
  return `
    <svg class="ui-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <path d="M7 7h11l-3-3m3 3-3 3M17 17H6l3 3m-3-3 3-3" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
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
  wrap.scrollLeft = saved.left;
  wrap.scrollTop = saved.top;
  requestAnimationFrame(() => {
    wrap.scrollLeft = saved.left;
    wrap.scrollTop = saved.top;
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
        <label>
          Game Type
          <select id="mode-input">
            <option value="random_units">Random Units</option>
            <option value="subscriptions">Subscriptions</option>
          </select>
        </label>
        <label id="subscription-length-field">
          Subscription Length
          <input id="subscription-length-input" type="number" min="1" max="30" value="5" />
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
  const modeInput = $("mode-input");
  const subscriptionLengthField = $("subscription-length-field");
  const createGame = $("create-game");
  const playAI = $("play-ai");
  const joinGame = $("join-game");
  if (!colorInput || !createGame || createGame.dataset.wired) return;
  createGame.dataset.wired = "true";
  playAI.dataset.wired = "true";
  joinGame.dataset.wired = "true";
  colorInput.value = state.color;
  const updateSubscriptionLengthVisibility = () => {
    if (subscriptionLengthField) subscriptionLengthField.hidden = modeInput.value !== "subscriptions";
  };
  updateSubscriptionLengthVisibility();
  modeInput.addEventListener("change", updateSubscriptionLengthVisibility);
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
        body: JSON.stringify({
          boards: Number($("boards-input").value || 1),
          mode: modeInput.value,
          subscriptionLength: Number($("subscription-length-input").value || 5),
        }),
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
        body: JSON.stringify({
          boards: Number($("boards-input").value || 1),
          mode: modeInput.value,
          subscriptionLength: Number($("subscription-length-input").value || 5),
        }),
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
  const subscriptionStatus = isSubscriptionsMode() ? ["yellow", "blue"].map((color) => {
    const due = subscriptionNextSpend(color);
    const available = subscriptionAvailableNextTurn(color);
    const income = state.game.turn === color ? projectedIncome(color) : 0;
    return `<span class="status-pill ${due > available ? "danger-pill" : ""}">${color[0].toUpperCase()} subs $${due} / $${available}${income ? ` (+$${income})` : ""}</span>`;
  }).join("") : "";
  const researchCost = state.game.researchCost || 2;
  const researchBlocked = !active || team().oversubscribed || team().souls < researchCost;
  const researchLabel = team().oversubscribed ? "oversubscribed" : `Research $${researchCost}`;
  const researchTitle = team().oversubscribed ? "Subscriptions were due but could not all be purchased this turn." : "";
  root.innerHTML = `
    <div class="status-strip">
      <div>
        <span class="status-pill">Code ${state.game.code}</span>
        <span class="status-pill">${state.game.modeLabel || "Random Units"}</span>
        <span class="status-pill">You ${state.color}</span>
        ${state.vsAI ? `<span class="status-pill">AI ${state.aiColor}</span>` : '<span class="status-pill">Players game</span>'}
        <span class="status-pill">Turn ${state.game.turn}</span>
        ${state.aiThinking ? '<span class="status-pill">AI thinking</span>' : ""}
        <span class="status-pill">Score Y ${state.game.scores.yellow} / B ${state.game.scores.blue}</span>
      </div>
      <div>
        <span class="status-pill">Yellow $${state.game.teams.yellow.souls}</span>
        <span class="status-pill">Blue $${state.game.teams.blue.souls}</span>
        ${subscriptionStatus}
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
          <div class="panel-header">
            <h3>Research & Buy</h3>
            <button class="icon-button secondary" type="button" title="${state.researchViewOpponent ? "Show your research" : "Show opponent research"}" onclick="toggleResearchView()">${reverseIcon()}</button>
          </div>
          ${isSubscriptionsMode() ? renderSubscriptionSummary(state.color) : ""}
          <div class="mini-actions research-actions">
            <button ${researchBlocked ? "disabled" : ""} title="${researchTitle}" onclick="action('research')">${researchLabel}</button>
            <button ${!active || team().souls < 2 ? "disabled" : ""} onclick="action('buy', {board:${state.board}, templateId:'zombie'})">Buy Zombie $2</button>
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
      state.pendingSubscription = null;
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
  for (const teamState of Object.values(state.game.teams || {})) {
    const researched = (teamState.researched || []).find((unit) => unit.id === templateId);
    if (researched) return researched;
  }
  for (const b of state.game.boards || []) {
    for (const units of Object.values(b.reinforcements || {})) {
      const reinforcement = units.find((unit) => unit.id === templateId);
      if (reinforcement) return reinforcement;
    }
    for (const subscriptions of Object.values(b.subscriptions || {})) {
      const subscription = subscriptions.find((candidate) => candidate.templateId === templateId);
      if (subscription) return subscription.template;
    }
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

function renderSubscriptionBars(schedule) {
  const maxCount = Math.max(1, ...schedule.map((item) => item.count));
  return `
    <div class="subscription-bars">
      ${schedule.map((item) => `
        <div class="subscription-bar-row">
          <span>T+${item.turn}</span>
          <div class="subscription-bar-track"><div class="subscription-bar-fill" style="width:${(item.count / maxCount) * 100}%"></div></div>
          <strong>${item.count}</strong>
        </div>
      `).join("")}
    </div>
  `;
}

function updateHoverSubscription(templateId, amount, label = "Subscription") {
  const card = $("hover-card");
  const unit = findTemplate(templateId);
  if (!card || !unit || !isSubscriptionsMode()) return;
  const subscription = hypotheticalSubscription(unit, amount, state.color);
  const schedule = subscriptionSchedule(subscription, state.color);
  const total = subscriptionTotalUnits(unit, amount);
  const spend = schedule.reduce((sum, item) => sum + item.spend, 0);
  card.innerHTML = `
    <div class="hover-props"><span>${label}</span><span>$${amount}</span><span>${total.toFixed(2)} total</span></div>
    <div class="hover-unit-name">${unit.name}</div>
    ${renderSubscriptionBars(schedule)}
    <div class="hover-unit-stats">Expected full fulfillment over ${state.game.subscriptionLength} turn${state.game.subscriptionLength === 1 ? "" : "s"}: $${spend} spend.</div>
  `;
}

function updateHoverActiveSubscription(subscription, color = state.color) {
  const card = $("hover-card");
  if (!card || !subscription || !isSubscriptionsMode()) return;
  const schedule = subscriptionSchedule(subscription, color);
  card.innerHTML = `
    <div class="hover-props"><span>Active</span><span>$${subscription.amount}</span><span>${subscription.purchasedCount} bought</span></div>
    <div class="hover-unit-name">${subscription.template.name}</div>
    ${renderSubscriptionBars(schedule)}
    <div class="hover-unit-stats">Fulfillment request ${Number(subscription.fulfillmentRequest || 0).toFixed(2)}; ${subscription.age} turn${subscription.age === 1 ? "" : "s"} old.</div>
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

function renderSubscriptionSummary(color) {
  const due = subscriptionNextSpend(color);
  const available = subscriptionAvailableNextTurn(color);
  const income = state.game.turn === color ? projectedIncome(color) : 0;
  return `
    <div class="subscription-summary ${due > available ? "warning" : ""}">
      <strong>Next subscriptions $${due}</strong>
      <span>Available $${available}${income ? ` after +$${income} income` : ""}</span>
    </div>
  `;
}

function renderSubscriptionButtons(unit, enabled) {
  const amounts = state.game.subscriptionAmounts || [2, 3, 5, 8, 13];
  return `
    <div class="subscription-buttons">
      ${amounts.map((amount) => {
        const total = subscriptionTotalUnits(unit, amount);
        const tooSmall = total < 0.5;
        const selected = state.pendingSubscription && state.pendingSubscription.templateId === unit.id && state.pendingSubscription.amount === amount;
        const warning = !tooSmall && subscriptionWouldWarn(unit, amount);
        return `<button type="button" class="subscription-button ${selected ? "active" : ""} ${warning ? "danger-outline" : ""}" ${!enabled || tooSmall ? "disabled" : ""} title="${tooSmall ? "Too small for this unit" : `${total.toFixed(2)} units over the subscription`}" onclick="selectSubscriptionAmount('${unit.id}', ${amount})">$${amount}</button>`;
      }).join("")}
    </div>
  `;
}

function renderActiveSubscriptionCard(subscription, color) {
  const schedule = subscriptionSchedule(subscription, color, Math.min(3, state.game.subscriptionLength));
  const nextCount = schedule.length ? schedule[0].count : 0;
  return `
    <div class="mini-card subscription-card active-subscription">
      <strong>${subscription.template.name} $${subscription.template.cost}/${subscription.template.rebate}</strong>
      <button class="bench-unit subscription-unit active" type="button" onmouseenter="updateHoverActiveSubscriptionById('${subscription.id}', '${color}')" onfocus="updateHoverActiveSubscriptionById('${subscription.id}', '${color}')" onclick="updateHoverActiveSubscriptionById('${subscription.id}', '${color}')">${unitToken({ ...subscription.template, team: color })}</button>
      <div class="bench-stats">$${subscription.amount}; ${subscription.purchasedCount} bought; next ${nextCount}</div>
      <div class="muted bench-help">Board ${state.board + 1} subscription.</div>
    </div>
  `;
}

function renderResearchUnitCard(unit, color, activeOwn) {
  const pending = state.pendingSubscription && state.pendingSubscription.templateId === unit.id;
  const label = isSubscriptionsMode() ? "Researched design" : "Researched minion";
  const click = isSubscriptionsMode()
    ? activeOwn
      ? `confirmSubscription('${unit.id}')`
      : `updateHoverUnitTemplate('${unit.id}', '${label}')`
    : activeOwn
      ? `action('buy', {board:${state.board}, templateId:'${unit.id}'})`
      : `updateHoverUnitTemplate('${unit.id}', '${label}')`;
  return `
    <div class="mini-card ${pending ? "subscription-pending-card" : ""}">
      <strong>${unit.name} $${unit.cost}/${unit.rebate}</strong>
      <button class="bench-unit ${pending ? "subscription-pending" : ""}" type="button" ${!isSubscriptionsMode() && activeOwn ? `data-template="${unit.id}" data-source="research"` : ""} onmouseenter="updateHoverUnitTemplate('${unit.id}', '${label}')" onfocus="updateHoverUnitTemplate('${unit.id}', '${label}')" onclick="${click}">${unitToken({ ...unit, team: color })}</button>
      <div class="bench-stats">${unit.speed} speed, ${unit.range} range, ${unit.attack}/${unit.defense}</div>
      ${isSubscriptionsMode() && activeOwn ? renderSubscriptionButtons(unit, true) : `<div class="muted bench-help">${activeOwn ? "Click or drag to Reinforcements to buy." : `${color} research.`}</div>`}
      ${isSubscriptionsMode() && activeOwn ? '<div class="muted bench-help">Choose $ amount, then click the unit.</div>' : ""}
    </div>
  `;
}

function renderResearch() {
  const color = visibleResearchColor();
  const researched = teamFor(color).researched || [];
  const subscriptions = isSubscriptionsMode() ? boardSubscriptions(color) : [];
  if (!researched.length && !subscriptions.length) {
    return `<div class="mini-card research-empty">No ${state.researchViewOpponent ? "opponent " : ""}research on this board.</div>`;
  }
  const cards = [
    ...subscriptions.map((subscription) => renderActiveSubscriptionCard(subscription, color)),
    ...researched.map((unit) => renderResearchUnitCard(unit, color, color === state.color && state.game.turn === state.color && !state.aiThinking)),
  ];
  const densityClass = cards.length >= 2 ? "dense" : "single";
  return `<div class="reinforcement-list research-bench-list ${densityClass} ${cards.length > 6 ? "scrollable" : ""}">${cards.join("")}</div>`;
}

function selectSubscriptionAmount(templateId, amount) {
  if (!isSubscriptionsMode() || state.game.turn !== state.color || state.aiThinking) return;
  const unit = findTemplate(templateId);
  if (!unit) return;
  if (subscriptionTotalUnits(unit, amount) < 0.5) return;
  state.pendingSubscription = { templateId, amount };
  renderGame();
  updateHoverSubscription(templateId, amount, "Planned subscription");
  notice(`Click ${unit.name} to subscribe on board ${state.board + 1}.`, true);
}

function confirmSubscription(templateId) {
  if (!state.pendingSubscription || state.pendingSubscription.templateId !== templateId) {
    updateHoverUnitTemplate(templateId, "Researched design");
    return;
  }
  const amount = state.pendingSubscription.amount;
  state.pendingSubscription = null;
  action("subscribe", { board: state.board, templateId, amount });
}

function findSubscriptionById(id, color) {
  return boardSubscriptions(color).find((subscription) => subscription.id === id);
}

function updateHoverActiveSubscriptionById(id, color) {
  const subscription = findSubscriptionById(id, color);
  if (subscription) updateHoverActiveSubscription(subscription, color);
}

function toggleResearchView() {
  state.researchViewOpponent = !state.researchViewOpponent;
  state.pendingSubscription = null;
  renderGame();
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

function renderGeneratedUnit(unit, alpha, turnNumber = 1, powerMultiplier = 1) {
  return `
    <div class="unit-preview">${unitToken(unit, true)}</div>
    <pre>${JSON.stringify({ alpha, turnNumber, powerMultiplier, unit }, null, 2)}</pre>
  `;
}

const TUTORIAL_UNITS = {
  necromancer: { id: "necromancer", name: "Necromancer", cost: 0, rebate: 0, attack: "*", defense: 10, speed: 1, range: 1, spawn: true, persistent: true, blink: false, flurry: false, ward: 0, flying: false, lumbering: false, terrainSpawn: [], minion: false },
  zombie: { id: "zombie", name: "Zombie", cost: 2, rebate: 0, attack: 1, defense: 1, speed: 1, range: 1, spawn: true, persistent: false, blink: false, flurry: false, ward: 0, flying: false, lumbering: true, terrainSpawn: [], minion: true },
  attacker: { id: "attacker", name: "Crypt Claw", cost: 4, rebate: 1, attack: 3, defense: 2, speed: 2, range: 1, spawn: false, persistent: false, blink: false, flurry: false, ward: 0, flying: false, lumbering: false, terrainSpawn: [], minion: true },
  defender: { id: "defender", name: "Bone Guard", cost: 4, rebate: 1, attack: 2, defense: 4, speed: 1, range: 1, spawn: true, persistent: false, blink: false, flurry: false, ward: 0, flying: false, lumbering: false, terrainSpawn: [], minion: true },
  flyer: { id: "flyer", name: "Pale Moth", cost: 5, rebate: 2, attack: 2, defense: 3, speed: 3, range: 2, spawn: false, persistent: false, blink: false, flurry: false, ward: 0, flying: true, lumbering: false, terrainSpawn: [], minion: true },
};

function tutorialToken(kind, team, label = "") {
  return `<div class="tutorial-token ${label ? "tutorial-token-damaged" : ""}">${unitToken({ ...TUTORIAL_UNITS[kind], team }, true)}${label ? `<span>${label}</span>` : ""}</div>`;
}

function tutorialBoardExample(kind) {
  const cells = Array.from({ length: 25 }, () => ({ cls: "", html: "" }));
  const set = (index, cls, html) => {
    cells[index] = { cls, html };
  };
  if (kind === "spawn") {
    [1, 6, 7, 12, 17, 18, 23].forEach((index) => set(index, "graveyard", '<span class="tutorial-grave">GY</span>'));
    set(10, "spawn-yellow", tutorialToken("necromancer", "yellow"));
    set(11, "graveyard", tutorialToken("zombie", "yellow"));
    set(12, "graveyard highlight", '<span class="tutorial-grave">GY</span><span class="tutorial-plus">+</span>');
    set(13, "graveyard", tutorialToken("zombie", "yellow"));
    set(14, "spawn-blue", tutorialToken("necromancer", "blue"));
    set(8, "graveyard", tutorialToken("zombie", "blue"));
    set(18, "graveyard", tutorialToken("zombie", "blue"));
  } else if (kind === "attack") {
    [2, 6, 8, 12, 16, 18, 22].forEach((index) => set(index, "graveyard", '<span class="tutorial-grave">GY</span>'));
    set(5, "spawn-yellow", tutorialToken("necromancer", "yellow"));
    set(9, "spawn-blue", tutorialToken("necromancer", "blue"));
    set(11, "graveyard", tutorialToken("zombie", "yellow"));
    set(12, "graveyard", tutorialToken("attacker", "yellow"));
    set(13, "graveyard highlight", tutorialToken("defender", "blue", "3 dmg"));
    set(17, "graveyard", tutorialToken("zombie", "blue"));
  } else {
    [1, 3, 6, 8, 11, 13, 16, 18, 21, 23].forEach((index) => set(index, "graveyard", '<span class="tutorial-grave">GY</span>'));
    set(5, "spawn-yellow", tutorialToken("necromancer", "yellow"));
    set(19, "spawn-blue", tutorialToken("necromancer", "blue"));
    set(6, "graveyard", tutorialToken("zombie", "yellow"));
    set(8, "graveyard", tutorialToken("zombie", "yellow"));
    set(11, "graveyard", tutorialToken("zombie", "blue"));
    set(13, "graveyard", tutorialToken("zombie", "blue"));
    set(12, "water", tutorialToken("flyer", "yellow"));
  }
  return `<div class="tutorial-board">${cells.map((cell) => `<div class="tutorial-cell ${cell.cls}">${cell.html}</div>`).join("")}</div>`;
}

const TUTORIAL_STEPS = [
  {
    title: "Turn Shape",
    body: "Each turn starts in spawn phase, then may switch once to movement. Spawn reinforcements beside ready Spawn units, play spawn-phase spells, then move and attack with units across any board before ending the turn for income.",
    board: tutorialBoardExample("overview"),
  },
  {
    title: "Random Units",
    body: "In Random Units, research reveals a generated minion design for $2. Buying that design places one copy into the current board's reinforcements and consumes that researched copy. Zombies can still be bought for $2, but they are usually filler.",
    board: tutorialBoardExample("overview"),
  },
  {
    title: "Subscriptions",
    body: "In Subscriptions, research still reveals generated designs, but the $2, $3, $5, $8, and $13 buttons create board-specific delivery plans. At the start of your later turns, due subscribed units are bought automatically into that board's reinforcements if you can afford them.",
    board: tutorialBoardExample("overview"),
  },
  {
    title: "Spawning",
    body: "A reinforcement can spawn onto an adjacent legal hex beside a ready friendly Spawn unit. This example has a necromancer and zombies holding graveyards, with a new zombie spawning onto an adjacent graveyard. Newly spawned units enter exhausted.",
    board: tutorialBoardExample("spawn"),
  },
  {
    title: "Attacks And Fester",
    body: "A 3 attack Crypt Claw can damage a 4 defense Bone Guard without killing it. Because Bone Guard is now damaged, Fester can deal the final point and destroy it. Spells that require damaged enemies cannot start the damage by themselves.",
    board: tutorialBoardExample("attack"),
  },
  {
    title: "Board Pressure",
    body: "Graveyards matter because end-turn income counts occupied graveyards, and starting your turn with eight graveyards on a board wins that board. Necromancers are still the highest-value targets, so protect yours while building graveyard control.",
    board: tutorialBoardExample("overview"),
  },
];

function renderTutorial() {
  const root = $("tutorial-root");
  if (!root) return;
  const step = TUTORIAL_STEPS[state.tutorialStep] || TUTORIAL_STEPS[0];
  root.innerHTML = `
    <div class="tutorial-layout">
      <aside class="tutorial-steps">
        ${TUTORIAL_STEPS.map((item, index) => `<button class="secondary ${index === state.tutorialStep ? "active" : ""}" onclick="setTutorialStep(${index})">${index + 1}. ${item.title}</button>`).join("")}
      </aside>
      <section class="tutorial-panel">
        <h2>${step.title}</h2>
        <p>${step.body}</p>
        ${step.board}
        <div class="mini-actions">
          <button class="secondary" ${state.tutorialStep === 0 ? "disabled" : ""} onclick="setTutorialStep(${state.tutorialStep - 1})">Previous</button>
          <button class="secondary" ${state.tutorialStep >= TUTORIAL_STEPS.length - 1 ? "disabled" : ""} onclick="setTutorialStep(${state.tutorialStep + 1})">Next</button>
        </div>
      </section>
    </div>
  `;
}

function setTutorialStep(index) {
  state.tutorialStep = clamp(index, 0, TUTORIAL_STEPS.length - 1);
  renderTutorial();
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
    const turnNumber = Number($("unit-turn-input").value || 1);
    const data = await api(`/api/generators/unit?turnNumber=${encodeURIComponent(turnNumber)}`);
    $("unit-lab").innerHTML = renderGeneratedUnit(data.unit, data.alpha, data.turnNumber, data.powerMultiplier);
    notice("Generated unit.", true);
  } catch (err) {
    notice(err.message);
  }
});

window.action = action;
window.aiTurn = aiTurn;
window.setMode = setMode;
window.selectCardById = selectCardById;
window.selectSubscriptionAmount = selectSubscriptionAmount;
window.confirmSubscription = confirmSubscription;
window.updateHoverActiveSubscriptionById = updateHoverActiveSubscriptionById;
window.updateHoverUnitTemplate = updateHoverUnitTemplate;
window.toggleResearchView = toggleResearchView;
window.setTutorialStep = setTutorialStep;
window.state = state;

renderTutorial();
renderGame();
