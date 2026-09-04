// Kiosk display driver — MUL Baggage Routing
//
// Two modes, chosen by a URL param:
//   gui/           -> demo mode: steps through mock_events.json, then generates
//                     random bags once the fixture runs out.
//   gui/?live=1    -> live mode: polls python/camera_subsystem/live_events.json
//                     written by main.py as real bags arrive.
//
// Both feeds share the same event shape:
//   { id, timestamp, status, flight_number, destination, photo_path }
//
// Cans are dynamic — managed in cans.html, persisted in localStorage.
// This page listens for storage changes and re-renders instantly when cans
// are added, removed, or reassigned from the management tab.

const IS_LIVE = new URLSearchParams(location.search).has("live");
const DATA_URL    = IS_LIVE
  ? "../python/camera_subsystem/live_events.json"
  : "../python/camera_subsystem/mock_events.json";
const IMAGE_BASE_URL = "../python/camera_subsystem/";
const ADVANCE_MS          = 2500;
const LIVE_POLL_MS        = 1500;
const ZOOM_CLICK_DELAY_MS = 220;

const CAN_COLORS = [
  "#2461c8","#c47a00","#0f8a60","#7050b8",
  "#1788b8","#b85010","#186040","#9040a0",
];

const STATUS_WEIGHTS = [
  ["matched",        70],
  ["manual",         10],
  ["duplicate",       8],
  ["unmatched_scan",  6],
  ["ambiguous",       6],
];

const STATUS_INFO = {
  manual:        { label: "Manual check",    className: "status-manual"         },
  duplicate:     { label: "Duplicate scan",  className: "status-duplicate"      },
  unmatched_scan:{ label: "Unmatched scan",  className: "status-unmatched_scan" },
  ambiguous:     { label: "Ambiguous match", className: "status-ambiguous"      },
};

const NO_ROUTE_INFO = { label: "No can match", className: "status-ambiguous" };

const CAMERA_ICON =
  '<svg viewBox="0 0 24 24"><path fill="currentColor" d="M4 5h3l1.5-2h7L17 5h3a2 2 0 0 1 2 2v11a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2Zm8 3.5a4.5 4.5 0 1 0 0 9 4.5 4.5 0 0 0 0-9Zm0 2a2.5 2.5 0 1 1 0 5 2.5 2.5 0 0 1 0-5Z"/></svg>';

const el = (id) => document.getElementById(id);

// ── Can configuration ────────────────────────────────────────────────────────

const CAN_STORAGE_KEY     = "dmms:cans";
const FLIGHTS_STORAGE_KEY = "dmms:flights";
const STORAGE_KEYS = {
  dismissed:   "dmms:dismissed",
  resetOffset: "dmms:liveResetOffset",
  demoIndex:   "dmms:demoIndex",
};

let _canSeq = 0;
function nextCanId() { return `can_${++_canSeq}`; }
function canColor(i) { return CAN_COLORS[i % CAN_COLORS.length]; }

function defaultCans() {
  return [
    { id: nextCanId(), label: "Can 1", flight: "" },
    { id: nextCanId(), label: "Can 2", flight: "" },
    { id: nextCanId(), label: "Can 3", flight: "" },
    { id: nextCanId(), label: "Can 4", flight: "" },
  ];
}

function loadCans() {
  try {
    const parsed = JSON.parse(localStorage.getItem(CAN_STORAGE_KEY) || "null");
    if (Array.isArray(parsed) && parsed.length) return parsed;
  } catch { /* ignore */ }
  return defaultCans();
}

function loadFlightsFromStorage() {
  try {
    const p = JSON.parse(localStorage.getItem(FLIGHTS_STORAGE_KEY) || "null");
    if (Array.isArray(p)) return p;
  } catch { /* ignore */ }
  return [];
}

// ── Application state ────────────────────────────────────────────────────────

const state = {
  cans:            loadCans(),
  events:          [],
  flights:         loadFlightsFromStorage(),
  index:           -1,
  playing:         false,
  timer:           null,
  dismissed:       new Set(),
  seq:             0,
  liveResetOffset: 0,
};

// ── localStorage helpers ─────────────────────────────────────────────────────

function loadDismissed() {
  try { return new Set(JSON.parse(localStorage.getItem(STORAGE_KEYS.dismissed) || "[]")); }
  catch { return new Set(); }
}
function saveDismissed(set) {
  try { localStorage.setItem(STORAGE_KEYS.dismissed, JSON.stringify([...set])); } catch { /* ok */ }
}
function loadResetOffset() {
  const n = Number(localStorage.getItem(STORAGE_KEYS.resetOffset));
  return Number.isFinite(n) ? n : 0;
}
function saveResetOffset(n) {
  try { localStorage.setItem(STORAGE_KEYS.resetOffset, String(n)); } catch { /* ok */ }
}

function dismissTile(id) {
  state.dismissed.add(id);
  if (IS_LIVE) saveDismissed(state.dismissed);
  render();
}

// ── Live storage sync from cans.html ─────────────────────────────────────────

window.addEventListener("storage", (e) => {
  if (e.key === CAN_STORAGE_KEY) {
    state.cans = loadCans();
    tileCache.clear();
    buildQuadrantShells();
    render();
  }
  if (e.key === FLIGHTS_STORAGE_KEY) {
    state.flights = loadFlightsFromStorage();
  }
  // Follower windows (attention.html) track the driver's demo index
  if (e.key === STORAGE_KEYS.demoIndex && !el("quadrants") && !IS_LIVE) {
    const idx = Number(e.newValue);
    if (Number.isFinite(idx)) { state.index = idx; render(); }
  }
});

// ── Utilities ────────────────────────────────────────────────────────────────

function formatTime(iso) {
  if (!iso) return "";
  return new Date(iso).toLocaleTimeString(undefined, {
    hour: "2-digit", minute: "2-digit", second: "2-digit",
  });
}

function gridDims(count) {
  if (count <= 1) return { cols: 1, rows: 1 };
  const cols = Math.ceil(Math.sqrt(count));
  return { cols, rows: Math.ceil(count / cols) };
}

function parseFlightsCsv(text) {
  return text.trim().split("\n").slice(1)
    .map((l) => l.split(","))
    .filter((c) => c.length >= 2)
    .map((c) => ({
      flight_number:    c[0].trim(),
      destination:      c[1].trim(),
      destination_name: (c[2] || "").trim(),
    }));
}

function randomStatus() {
  const total = STATUS_WEIGHTS.reduce((s, [, w]) => s + w, 0);
  let roll = Math.random() * total;
  for (const [status, weight] of STATUS_WEIGHTS) {
    if (roll < weight) return status;
    roll -= weight;
  }
  return "matched";
}

function generateRandomEvent() {
  state.seq += 1;
  const status = randomStatus();
  const pool = state.flights.length
    ? state.flights
    : [{ flight_number: "QF000", destination: "SYD", destination_name: "Sydney" }];
  const flight  = pool[Math.floor(Math.random() * pool.length)];
  const isKnown = status !== "manual";
  return {
    id:            `bag_${state.seq}`,
    timestamp:     new Date().toISOString(),
    status,
    flight_number: isKnown ? flight.flight_number : null,
    destination:   isKnown ? flight.destination   : null,
    photo_path:    null,
  };
}

// ── Can routing ──────────────────────────────────────────────────────────────

function canIndexFor(event) {
  const anyFlightConfigured = state.cans.some((c) => c.flight);
  if (!anyFlightConfigured) {
    // Demo fallback: hash-based distribution when no flights are set
    const key = String(event.id || event.flight_number || "");
    let hash = 0;
    for (let i = 0; i < key.length; i++) hash = ((hash * 31) + key.charCodeAt(i)) >>> 0;
    return hash % state.cans.length;
  }
  if (!event.flight_number) {
    // Check for an unassigned catch-all can (flight === "")
    const catchAll = state.cans.findIndex((c) => !c.flight);
    return catchAll; // -1 if none
  }
  const fn = event.flight_number.toUpperCase();
  // First try exact match on a named flight
  const exact = state.cans.findIndex((c) => c.flight && c.flight.toUpperCase() === fn);
  if (exact >= 0) return exact;
  // Fall back to catch-all can
  return state.cans.findIndex((c) => !c.flight);
}

// ── Quadrant shell building ──────────────────────────────────────────────────

function buildQuadrantShells() {
  const container = el("quadrants");
  if (!container) return;

  container.innerHTML = "";
  state.cans.forEach((can, i) => {
    const color = canColor(i);
    const flightLabel = can.flight
      ? `<span class="can-flight-display" style="color:${color}">${can.flight.toUpperCase()}</span>`
      : `<span class="can-flight-display can-no-flight">— unassigned —</span>`;

    const section = document.createElement("section");
    section.className   = "quadrant";
    section.dataset.can = String(i);
    section.dataset.canId = can.id;
    section.style.setProperty("--cat", color);
    section.innerHTML = `
      <div class="quadrant-header">
        <span class="quadrant-label">
          <span class="quadrant-dot"></span>
          ${flightLabel}
          <span class="can-name-display">${can.label}</span>
        </span>
        <div class="quadrant-actions">
          <span class="quadrant-count" id="quadrant-count-${i}">0</span>
        </div>
      </div>
      <div class="tile-grid" id="quadrant-grid-${i}"></div>
    `;
    container.appendChild(section);
  });
}

// ── Tile building ────────────────────────────────────────────────────────────

const tileCache = new Map();

function makeTile(event, { statusChip = null } = {}) {
  const tile = document.createElement("div");
  tile.className = "tile";
  tile.title     = "Click to zoom · double-click to clear once loaded";
  tile.dataset.eventId = event.id || "";

  const photo = document.createElement("div");
  photo.className = "tile-photo";
  photo.innerHTML = CAMERA_ICON;

  if (event.photo_path) {
    const img = document.createElement("img");
    img.alt = `Snapshot of ${event.id || "bag"}`;
    const fallbackIcon = photo.querySelector("svg");
    img.onload  = () => { img.classList.add("loaded"); if (fallbackIcon) fallbackIcon.style.display = "none"; };
    img.onerror = () => { img.classList.remove("loaded"); if (fallbackIcon) fallbackIcon.style.display = ""; };
    img.src = IMAGE_BASE_URL + event.photo_path;
    photo.appendChild(img);
  }

  const sub = [event.id, formatTime(event.timestamp)].filter(Boolean).join(" · ");
  const caption = document.createElement("div");
  caption.className = "tile-caption";
  caption.innerHTML = `
    <div class="tile-flight">${event.flight_number || "Unknown flight"}</div>
    <div class="tile-destination">${event.destination || "Unknown destination"}</div>
    <div class="tile-sub">${sub}</div>
  `;

  tile.appendChild(photo);

  if (statusChip) {
    const chip = document.createElement("span");
    chip.className   = `tile-status-chip ${statusChip.className}`;
    chip.textContent = statusChip.label;
    tile.appendChild(chip);
  }

  tile.appendChild(caption);

  let clickTimer = null;
  tile.addEventListener("click", () => {
    if (!event.photo_path) return;
    clearTimeout(clickTimer);
    clickTimer = setTimeout(() => openZoom(event), ZOOM_CLICK_DELAY_MS);
  });
  tile.addEventListener("dblclick", () => {
    clearTimeout(clickTimer);
    dismissTile(event.id);
  });

  return tile;
}

function openZoom(event) {
  if (!event.photo_path) return;
  const popup = window.open("", "_blank", "width=720,height=640");
  if (!popup) return;
  const sub = [event.id, formatTime(event.timestamp)].filter(Boolean).join(" · ");
  popup.document.title = `${event.flight_number || "Unknown"} · ${sub}`;
  popup.document.body.style.cssText =
    "margin:0;height:100vh;display:flex;align-items:center;justify-content:center;background:#0b1524;";
  const img = popup.document.createElement("img");
  img.src   = IMAGE_BASE_URL + event.photo_path;
  img.alt   = `Snapshot of ${event.id || "bag"}`;
  img.style.cssText = "max-width:100%;max-height:100%;object-fit:contain;";
  popup.document.body.appendChild(img);
}

// ── Grid filling ─────────────────────────────────────────────────────────────

function fillGrid(gridEl, items, { emptyText, statusChipFor = null }, seenIds) {
  const { cols, rows } = gridDims(items.length);
  gridEl.style.setProperty("--cols", cols);
  gridEl.style.setProperty("--rows", rows);

  if (!items.length) {
    // Only rebuild if not already showing the empty state
    if (!gridEl.querySelector(".tile-empty")) {
      gridEl.innerHTML = "";
      const empty = document.createElement("div");
      empty.className   = "tile-empty";
      empty.textContent = emptyText;
      gridEl.appendChild(empty);
    }
    return;
  }

  // Build/retrieve tiles first
  const newTiles = items.map((event) => {
    seenIds.add(event.id);
    let tile = tileCache.get(event.id);
    if (!tile) {
      const chip = statusChipFor ? statusChipFor(event) : null;
      tile = makeTile(event, { statusChip: chip });
      tileCache.set(event.id, tile);
    }
    return tile;
  });

  // Remove children that are no longer in the list (includes stale empty-state)
  const newSet = new Set(newTiles);
  [...gridEl.children].forEach((child) => {
    if (!newSet.has(child)) child.remove();
  });

  // Insert/reorder without touching tiles already in the right position
  newTiles.forEach((tile, i) => {
    const current = gridEl.children[i];
    if (current !== tile) gridEl.insertBefore(tile, current || null);
  });
}

// ── Attention collapsing ─────────────────────────────────────────────────────
// Groups duplicate scans of the same flight into one stacked tile so the
// attention tray doesn't fill up when a bag is scanned several times.
// Manual / unmatched / ambiguous events stay as individual tiles.
function collapseAttention(events) {
  const dupMap = new Map(); // groupKey -> synthetic group event
  const out    = [];

  events.forEach((event) => {
    if (event.status === "duplicate" && event.flight_number) {
      const key = `__dup__${event.flight_number}|${event.destination || ""}`;
      if (!dupMap.has(key)) {
        const group = { ...event, id: key, _dupCount: 1 };
        dupMap.set(key, group);
        out.push(group);
      } else {
        const g = dupMap.get(key);
        g._dupCount += 1;
        if (event.photo_path) g.photo_path = event.photo_path;
        g.timestamp = event.timestamp;
      }
    } else {
      out.push(event);
    }
  });

  return out;
}

// ── Render ───────────────────────────────────────────────────────────────────

function render() {
  if (IS_LIVE) state.dismissed = loadDismissed();

  const scannedSoFar = state.events.slice(0, state.index + 1);
  const visible      = scannedSoFar.filter((e) => !state.dismissed.has(e.id));
  const loaded       = scannedSoFar.length - visible.length;

  const buckets   = Array.from({ length: state.cans.length }, () => []);
  const attention = [];

  visible.forEach((event) => {
    if (STATUS_INFO[event.status]) {
      attention.push(event);
      return;
    }
    const idx = canIndexFor(event);
    if (idx >= 0 && idx < state.cans.length) {
      buckets[idx].push(event);
    } else {
      event._noRoute = true;
      attention.push(event);
    }
  });

  const seenIds = new Set();

  if (el("quadrants")) {
    state.cans.forEach((_, i) => {
      const gridEl  = el(`quadrant-grid-${i}`);
      const countEl = el(`quadrant-count-${i}`);
      if (!gridEl) return;
      fillGrid(gridEl, buckets[i], { emptyText: "Waiting for bags…" }, seenIds);
      if (countEl) countEl.textContent = String(buckets[i].length);
    });
  }

  const attentionGrid = el("attention-grid");
  if (attentionGrid) {
    const collapsed = collapseAttention(attention);
    fillGrid(attentionGrid, collapsed, {
      emptyText: "No bags need attention",
      statusChipFor: (event) => event._noRoute ? NO_ROUTE_INFO : STATUS_INFO[event.status],
    }, seenIds);
    // Update duplicate count badges in-place on cached tiles (no DOM flash)
    collapsed.forEach((event) => {
      if (event._dupCount > 1) {
        const tile = tileCache.get(event.id);
        if (!tile) return;
        let badge = tile.querySelector(".dup-count-badge");
        if (!badge) {
          badge = document.createElement("span");
          badge.className = "dup-count-badge";
          tile.appendChild(badge);
        }
        badge.textContent = `×${event._dupCount} scans`;
      }
    });
  }

  for (const id of tileCache.keys()) {
    if (!seenIds.has(id)) tileCache.delete(id);
  }

  if (el("stat-total"))   el("stat-total").textContent   = String(scannedSoFar.length);
  if (el("stat-routed"))  el("stat-routed").textContent  = String(visible.length - attention.length);
  if (el("stat-flagged")) el("stat-flagged").textContent = String(attention.length);
  if (el("stat-loaded"))  el("stat-loaded").textContent  = String(loaded);
}

// ── Demo playback ────────────────────────────────────────────────────────────

function goTo(index) {
  if (!state.events.length) return;
  state.index = Math.max(-1, Math.min(index, state.events.length - 1));
  // Broadcast playback position so attention.html follows along
  if (el("quadrants")) {
    try { localStorage.setItem(STORAGE_KEYS.demoIndex, String(state.index)); } catch {}
  }
  render();
}

function stepForward() {
  if (state.index + 1 >= state.events.length) state.events.push(generateRandomEvent());
  goTo(state.index + 1);
}
function stepBackward() { goTo(state.index - 1); }

function setPlaying(playing) {
  state.playing = playing;
  const btn = el("btn-play");
  if (btn) btn.textContent = playing ? "⏸" : "▶";
  clearInterval(state.timer);
  if (playing) state.timer = setInterval(stepForward, ADVANCE_MS);
}

// ── Live polling ─────────────────────────────────────────────────────────────

function setLiveEvents(rawEvents) {
  state.liveResetOffset = loadResetOffset();
  if (rawEvents.length < state.liveResetOffset) {
    state.liveResetOffset = 0;
    state.dismissed = new Set();
    saveResetOffset(0);
    saveDismissed(state.dismissed);
    tileCache.clear();
  }
  state.events = rawEvents.slice(state.liveResetOffset);
  state.index  = state.events.length - 1;
  render();
}

function pollLive() {
  fetch(DATA_URL)
    .then((r) => r.json())
    .then(setLiveEvents)
    .catch((err) => console.error(err));
}

// ── Attention window ─────────────────────────────────────────────────────────

function openAttentionWindow() {
  const win = window.open("attention.html" + location.search, "dmms-attention", "width=900,height=760");
  const flagIfBlocked = () => { if (!win || win.closed) flagAttentionBlocked(); };
  if (!win) flagAttentionBlocked();
  else setTimeout(flagIfBlocked, 300);
}

function flagAttentionBlocked() {
  const btn = el("btn-open-attention");
  if (!btn) return;
  btn.classList.add("attention-blocked");
  btn.textContent = "⚠ Blocked — click to allow";
}

// ── Manage Cans window ────────────────────────────────────────────────────────

function openCansWindow() {
  window.open("cans.html", "dmms-cans", "width=900,height=620");
}

// ── Wiring ───────────────────────────────────────────────────────────────────

const manageCansBtn = el("btn-manage-cans");
if (manageCansBtn) manageCansBtn.addEventListener("click", openCansWindow);

const openAttentionBtn = el("btn-open-attention");
if (openAttentionBtn) {
  openAttentionBtn.addEventListener("click", () => {
    openAttentionBtn.classList.remove("attention-blocked");
    openAttentionBtn.textContent = "Needs Attention ↗";
    openAttentionWindow();
  });
  openAttentionWindow();
}

// ── Boot ─────────────────────────────────────────────────────────────────────

buildQuadrantShells();
render();

if (IS_LIVE) {
  document.body.classList.add("live-mode");
  const banner = el("mode-banner");
  if (banner) {
    banner.classList.add("live");
    banner.innerHTML = "<strong>LIVE</strong> &mdash; polling <code>live_events.json</code> from main.py.";
  }

  const resetBtn = el("btn-reset");
  if (resetBtn) {
    resetBtn.addEventListener("click", () => {
      state.liveResetOffset += state.events.length;
      state.events    = [];
      state.dismissed = new Set();
      state.index     = -1;
      tileCache.clear();
      saveResetOffset(state.liveResetOffset);
      saveDismissed(state.dismissed);
      render();
    });
  }

  pollLive();
  setInterval(pollLive, LIVE_POLL_MS);
} else {
  const prevBtn = el("btn-prev");
  const nextBtn = el("btn-next");
  const playBtn = el("btn-play");
  if (prevBtn) prevBtn.addEventListener("click", () => { setPlaying(false); stepBackward(); });
  if (nextBtn) nextBtn.addEventListener("click", () => { setPlaying(false); stepForward();  });
  if (playBtn) playBtn.addEventListener("click", () => setPlaying(!state.playing));

  fetch(DATA_URL)
    .then((r) => r.json())
    .then((events) => {
      state.events  = events;
      state.flights = loadFlightsFromStorage();
      state.seq     = events.length;
      // Follower windows (attention.html) pick up the driver's current position
      if (!el("quadrants")) {
        const saved = Number(localStorage.getItem(STORAGE_KEYS.demoIndex));
        if (Number.isFinite(saved)) state.index = saved;
      }
      render();
    })
    .catch((err) => console.error(err));
}
