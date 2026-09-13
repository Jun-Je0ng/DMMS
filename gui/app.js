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

const _CFG           = window.DMMS_CONFIG || {};
const IS_LIVE        = true;   // always live — use sim_runner.py for simulation
const DATA_URL       = "../data/live_events.json";
const IMAGE_BASE_URL = "../data/";
const LOADED_API_URL = "/api/loaded";
const ADVANCE_MS          = 2500;
const LIVE_POLL_MS        = 1500;
const ZOOM_CLICK_DELAY_MS = 220;
const CAROUSEL_THRESHOLD  = 4;   // beyond this many tiles, use a horizontal carousel

const CAN_COLORS = [
  "#888888","#aaaaaa","#666666","#999999",
  "#777777","#bbbbbb","#555555","#b0b0b0",
];

// Apply display scale from config.js
(function () {
  const scale = (_CFG.uiScale && isFinite(_CFG.uiScale)) ? _CFG.uiScale : 1;
  document.documentElement.style.setProperty("--ui-scale", String(scale));
}());

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

// Statuses that always go to Needs Attention regardless of flight info.
// unmatched_scan is intentionally NOT here — a scan with a known barcode
// should route to its CAN just like a normal matched bag.
const ATTENTION_STATUSES = new Set(["manual", "duplicate", "ambiguous"]);

const CAMERA_ICON =
  '<svg viewBox="0 0 24 24"><path fill="currentColor" d="M4 5h3l1.5-2h7L17 5h3a2 2 0 0 1 2 2v11a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2Zm8 3.5a4.5 4.5 0 1 0 0 9 4.5 4.5 0 0 0 0-9Zm0 2a2.5 2.5 0 1 1 0 5 2.5 2.5 0 0 1 0-5Z"/></svg>';

const el = (id) => document.getElementById(id);

// ── Dismiss modal ─────────────────────────────────────────────────────────────

let _pendingDismissCallback = null;

function ensureDismissModal() {
  if (el("dismiss-modal")) return;
  const modal = document.createElement("div");
  modal.id        = "dismiss-modal";
  modal.className = "dismiss-modal";
  modal.hidden    = true;
  modal.innerHTML = `
    <div class="dismiss-modal-box">
      <p class="dismiss-modal-title">Remove Bag from Board</p>
      <p class="dismiss-modal-info" id="dismiss-modal-info"></p>
      <div class="dismiss-modal-actions">
        <button id="dismiss-btn-loaded" class="dismiss-btn dismiss-btn-loaded">
          Mark as Loaded
        </button>
        <button id="dismiss-btn-remove" class="dismiss-btn dismiss-btn-remove">
          Remove from Board
        </button>
        <button id="dismiss-btn-cancel" class="dismiss-btn dismiss-btn-cancel">
          Cancel
        </button>
      </div>
    </div>
  `;
  document.body.appendChild(modal);
  el("dismiss-btn-loaded").onclick  = () => { _resolveDismiss(true);  };
  el("dismiss-btn-remove").onclick  = () => { _resolveDismiss(false); };
  el("dismiss-btn-cancel").onclick  = _closeDismissModal;
  modal.addEventListener("click", (e) => { if (e.target === modal) _closeDismissModal(); });
}

function _resolveDismiss(markLoaded) {
  const cb = _pendingDismissCallback;  // capture before close nulls it
  _closeDismissModal();
  if (cb) cb(markLoaded);
}

function _closeDismissModal() {
  const m = el("dismiss-modal");
  if (m) m.hidden = true;
  _pendingDismissCallback = null;
}

function showDismissModal(event, callback) {
  ensureDismissModal();
  const info = el("dismiss-modal-info");
  if (info) {
    const parts = [
      event.flight_number || "Unknown flight",
      event.destination   || null,
      event.id            || null,
      event._dupCount > 1 ? `×${event._dupCount} duplicate scans` : null,
    ].filter(Boolean);
    info.textContent = parts.join(" · ");
  }
  _pendingDismissCallback = callback;
  el("dismiss-modal").hidden = false;
}

// ── Can configuration ────────────────────────────────────────────────────────

const CAN_STORAGE_KEY     = "dmms:cans";
const FLIGHTS_STORAGE_KEY = "dmms:flights";
const STORAGE_KEYS = {
  dismissed:   "dmms:dismissed",
  resetOffset: "dmms:liveResetOffset",
  demoIndex:   "dmms:demoIndex",
  settings:    "dmms:settings",
  loaded:      "dmms:loaded",
};

// ── Display settings (timeout + auto-scroll) ─────────────────────────────────

function loadSettings() {
  try {
    const s = JSON.parse(localStorage.getItem(STORAGE_KEYS.settings) || "null");
    if (s && typeof s === "object") {
      return { timeoutEnabled: false, timeoutSecs: 30, autoScrollEnabled: false, ...s };
    }
  } catch { /* ignore */ }
  return { timeoutEnabled: false, timeoutSecs: 30, autoScrollEnabled: false };
}
function saveSettings() {
  try { localStorage.setItem(STORAGE_KEYS.settings, JSON.stringify(settings)); } catch { /* ok */ }
}
const settings = loadSettings();

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

async function loadCansFromFile() {
  try {
    const r = await fetch("/api/cans");
    if (!r.ok) throw new Error();
    const data = await r.json();
    if (Array.isArray(data) && data.length) {
      try { localStorage.setItem(CAN_STORAGE_KEY, JSON.stringify(data)); } catch {}
      return data;
    }
  } catch {}
  return null;
}

async function loadFlightsFromFile() {
  try {
    const r = await fetch("/api/flights");
    if (!r.ok) throw new Error();
    const data = await r.json();
    if (Array.isArray(data)) {
      try { localStorage.setItem(FLIGHTS_STORAGE_KEY, JSON.stringify(data)); } catch {}
      return data;
    }
  } catch {}
  return null;
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
  loaded:          loadLoaded(),
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
function loadLoaded() {
  try { return new Set(JSON.parse(localStorage.getItem(STORAGE_KEYS.loaded) || "[]")); }
  catch { return new Set(); }
}
function saveLoaded(set) {
  try { localStorage.setItem(STORAGE_KEYS.loaded, JSON.stringify([...set])); } catch { /* ok */ }
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

// ── Airline IATA helper ─────────────────────────────────────────────────────

function iataCode(flightNumber) {
  // "QF298" → "QF", "NZ499" → "NZ", "SG334" → "SG"
  const m = String(flightNumber || "").match(/^([A-Z]{2,3})/i);
  return m ? m[1].toUpperCase() : null;
}

function airlineLogoUrl(flightNumber) {
  const code = iataCode(flightNumber);
  if (!code) return null;
  return `resources/airlines/${code}.png`;
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
      ? `<span class="can-flight-display">${can.flight.toUpperCase()}</span>`
      : `<span class="can-flight-display can-no-flight">— unassigned —</span>`;

    // Look up departure time for this can's assigned flight
    const flightData = can.flight
      ? state.flights.find((f) => f.flight_number && f.flight_number.toUpperCase() === can.flight.toUpperCase())
      : null;
    const depLabel = (flightData && flightData.departure_time)
      ? `<span class="can-dep-time" title="Scheduled departure">${flightData.departure_time}</span>`
      : "";
    const destLabel = (flightData && flightData.destination)
      ? `<span class="can-dest-display">${flightData.destination}${flightData.destination_name ? " · " + flightData.destination_name : ""}</span>`
      : "";

    const section = document.createElement("section");
    section.className   = "quadrant";
    section.dataset.can = String(i);
    section.dataset.canId = can.id;
    section.style.setProperty("--cat", color);
    const logoUrl = can.flight ? airlineLogoUrl(can.flight) : null;
    const logoHtml = logoUrl
      ? `<img class="airline-logo" src="${logoUrl}"
              alt="${iataCode(can.flight) || ""}"
              onerror="this.style.display='none';this.nextElementSibling.style.display='inline-block'"
         /><span class="quadrant-dot" style="display:none"></span>`
      : `<span class="quadrant-dot"></span>`;

    section.innerHTML = `
      <div class="quadrant-sidebar">
        <div class="sidebar-logo-wrap">
          ${logoHtml}
        </div>
        <span class="quadrant-label">
          <span class="can-name-display">${can.label}</span>
        </span>
        ${flightLabel}
        ${destLabel}
        ${depLabel}
        <span class="quadrant-count" id="quadrant-count-${i}">0</span>
      </div>
      <div class="quadrant-content">
        <div class="tile-grid" id="quadrant-grid-${i}"></div>
      </div>
    `;
    container.appendChild(section);
  });
}

// ── Tile building ────────────────────────────────────────────────────────────

const tileCache = new Map();

function makeTile(event, { statusChip = null } = {}) {
  const tile = document.createElement("div");
  tile.className  = "tile";
  tile.title      = "Click to zoom · double-click to clear once loaded";
  tile.dataset.eventId = event.id || "";
  tile._eventRef  = event;

  const photo = document.createElement("div");
  photo.className = "tile-photo";
  photo.innerHTML = CAMERA_ICON;

  if (event.photo_path) {
    const img = document.createElement("img");
    img.alt = `Snapshot of ${event.id || "bag"}`;
    const fallbackIcon = photo.querySelector("svg");
    img.onload  = () => { img.classList.add("loaded"); if (fallbackIcon) fallbackIcon.style.display = "none"; };
    img.onerror = () => { img.classList.remove("loaded"); if (fallbackIcon) fallbackIcon.style.display = ""; };
    img.dataset.photoPath = event.photo_path;
    img.src = IMAGE_BASE_URL + event.photo_path;
    photo.appendChild(img);
  }

  const sub = [event.id, formatTime(event.timestamp)].filter(Boolean).join(" · ");
  // Only show destination on the tile if it differs from the can's assigned flight
  // (catches connecting/misrouted bags); otherwise it's redundant — shown in sidebar
  const eventDest  = (event.destination || "").toUpperCase();
  const canDest    = (event._expectedDest || "").toUpperCase();
  const showDest   = eventDest && (!canDest || eventDest !== canDest);
  const caption = document.createElement("div");
  caption.className = "tile-caption";
  caption.innerHTML = `
    <div class="tile-flight">${event.flight_number || "?"}</div>
    ${showDest ? `<div class="tile-destination">${event.destination}</div>` : ""}
    <div class="tile-sub">${sub}</div>
  `;

  tile.appendChild(photo);

  // Bag tag — the short number staff type into the mobile keypad
  // confirmation page, and the number the swipe page shows per card.
  if (event._tag) {
    const tag = document.createElement("span");
    tag.className   = "tile-tag";
    tag.textContent = `#${event._tag}`;
    tile.appendChild(tag);
  }

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
    const ev = tile._eventRef;
    showDismissModal(ev, (markLoaded) => {
      // Dismiss all related event IDs so the tile disappears
      const ids = (ev._groupIds && ev._groupIds.length) ? ev._groupIds : [ev.id];
      ids.forEach((id) => state.dismissed.add(id));
      if (IS_LIVE) saveDismissed(state.dismissed);
      // Only increment loaded counter on explicit confirmation, counting as 1 bag
      if (markLoaded) {
        state.loaded.add(ev.id);   // ev.id is canonical (group key for dup groups)
        if (IS_LIVE) saveLoaded(state.loaded);
        postMarkLoaded(ev, "board");

        // Duplicates are already bundled via _groupIds and dismissed above.
        // Auto-dismissal by flight number removed — too broad (would clear all
        // bags on the same flight). Barcode-level linking requires a consistent
        // barcode field from the scanner; wire it here when available.
      }
      render();
    });
  });

  // Countdown bar (shown when auto-clear timeout is enabled)
  if (settings.timeoutEnabled) {
    const bar = document.createElement("div");
    bar.className = "tile-countdown";
    bar.style.setProperty("--countdown-dur", settings.timeoutSecs + "s");
    tile.appendChild(bar);
    tile.dataset.expiresAt = String(Date.now() + settings.timeoutSecs * 1000);
  }

  return tile;
}

// In-page zoom modal (built once, reused for every tile). This used to
// open the photo in a new window via window.open(), but that's blocked
// outright by kiosk-mode browsers (Chrome --kiosk and similar disable
// window.open entirely) and is also routinely blocked by ordinary popup
// blockers whenever the call doesn't fire perfectly synchronously with the
// click — it didn't here, see ZOOM_CLICK_DELAY_MS above, needed to tell a
// zoom click apart from the first half of a double-click. An in-page
// modal, the same pattern as the "Mobile Access" QR popup, sidesteps both.
let _zoomModalEl = null;

function ensureZoomModal() {
  if (_zoomModalEl) return _zoomModalEl;
  const modal = document.createElement("div");
  modal.className = "zoom-modal";
  modal.hidden = true;
  modal.innerHTML =
    '<div class="zoom-modal-box">' +
      '<button class="zoom-modal-close" aria-label="Close">&times;</button>' +
      '<div class="zoom-modal-title"></div>' +
      '<img class="zoom-modal-img" alt="" />' +
    "</div>";
  document.body.appendChild(modal);

  const close = () => { modal.hidden = true; };
  modal.addEventListener("click", (e) => { if (e.target === modal) close(); });
  modal.querySelector(".zoom-modal-close").addEventListener("click", close);
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !modal.hidden) close();
  });

  _zoomModalEl = modal;
  return modal;
}

function openZoom(event) {
  if (!event.photo_path) return;
  const modal = ensureZoomModal();
  const sub   = [event.id, formatTime(event.timestamp)].filter(Boolean).join(" · ");
  modal.querySelector(".zoom-modal-title").textContent = `${event.flight_number || "Unknown"} · ${sub}`;
  const img = modal.querySelector(".zoom-modal-img");
  img.src   = IMAGE_BASE_URL + event.photo_path;
  img.alt   = `Snapshot of ${event.id || "bag"}`;
  modal.hidden = false;
}

// ── Grid filling ─────────────────────────────────────────────────────────────

function fillGrid(gridEl, items, { emptyText, statusChipFor = null, layout = 'grid' }, seenIds) {
  if (layout === "row") {
    // Single horizontal row — carousel kicks in past the threshold
    gridEl.classList.add("row-layout");
    gridEl.classList.remove("grid-layout");
    const useCarousel = items.length > CAROUSEL_THRESHOLD;
    gridEl.classList.toggle("carousel-mode", useCarousel);
  } else {
    // 2-D CSS grid (attention tray etc.)
    gridEl.classList.add("grid-layout");
    gridEl.classList.remove("row-layout", "carousel-mode");
    const { cols, rows } = gridDims(items.length);
    gridEl.style.setProperty("--cols", cols);
    gridEl.style.setProperty("--rows", rows);
  }

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
        const group = { ...event, id: key, _dupCount: 1, _groupIds: [event.id] };
        dupMap.set(key, group);
        out.push(group);
      } else {
        const g = dupMap.get(key);
        g._dupCount += 1;
        g._groupIds.push(event.id);
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
  const loaded       = state.loaded.size;

  const buckets   = Array.from({ length: state.cans.length }, () => []);
  const attention = [];

  visible.forEach((event) => {
    if (ATTENTION_STATUSES.has(event.status)) {
      attention.push(event);
      return;
    }
    const idx = canIndexFor(event);
    if (idx >= 0 && idx < state.cans.length) {
      // Tag expected destination so the tile can suppress it if it matches
      const canFlight = state.flights.find(
        (f) => f.flight_number && state.cans[idx].flight &&
               f.flight_number.toUpperCase() === state.cans[idx].flight.toUpperCase()
      );
      event._expectedDest = canFlight ? (canFlight.destination || "").toUpperCase() : "";
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
      fillGrid(gridEl, buckets[i], { emptyText: "Waiting for bags…", layout: "row" }, seenIds);
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
    const dupPhotoMap = new Map(); // FLIGHT -> latest photo_path
    collapsed.forEach((event) => {
      // Keep eventRef current so dblclick always dismisses all accumulated ids
      const tile = tileCache.get(event.id);
      if (tile) tile._eventRef = event;
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
      if (event._dupCount && event.photo_path && event.flight_number) {
        dupPhotoMap.set(event.flight_number.toUpperCase(), event.photo_path);
      }
    });

    // Propagate latest duplicate photo to matching quadrant tiles
    if (dupPhotoMap.size) {
      tileCache.forEach((tile, id) => {
        if (id.startsWith("__dup__")) return;
        const ev = tile._eventRef;
        if (!ev || !ev.flight_number) return;
        const latestPath = dupPhotoMap.get(ev.flight_number.toUpperCase());
        if (!latestPath) return;
        const img = tile.querySelector(".tile-photo img");
        if (img && img.dataset.photoPath !== latestPath) {
          img.dataset.photoPath = latestPath;
          img.classList.remove("loaded");
          img.src = IMAGE_BASE_URL + latestPath;
        }
      });
    }
  }

  for (const id of tileCache.keys()) {
    if (!seenIds.has(id)) tileCache.delete(id);
  }

  if (el("stat-total"))   el("stat-total").textContent   = String(scannedSoFar.length);
  if (el("stat-routed"))  el("stat-routed").textContent  = String(visible.length - attention.length);
  if (el("stat-flagged")) el("stat-flagged").textContent = String(attention.length);
  if (el("stat-loaded"))  el("stat-loaded").textContent  = String(loaded);
}

// ── Timeout checker ──────────────────────────────────────────────────────────

function checkTimeouts() {
  if (!settings.timeoutEnabled) return;
  const now = Date.now();
  let anyExpired = false;
  tileCache.forEach((tile, id) => {
    const exp = Number(tile.dataset.expiresAt);
    if (!exp || state.dismissed.has(id)) return;
    if (now >= exp) {
      const ev = tile._eventRef;
      const ids = (ev && ev._groupIds && ev._groupIds.length) ? ev._groupIds : [id];
      ids.forEach((i) => state.dismissed.add(i));
      if (IS_LIVE) saveDismissed(state.dismissed);
      anyExpired = true;
    }
  });
  if (anyExpired) render();
}
setInterval(checkTimeouts, 1000);

// ── Carousel auto-scroll ─────────────────────────────────────────────────────

function tickCarousels() {
  if (!settings.autoScrollEnabled) return;
  document.querySelectorAll(".tile-grid.carousel-mode").forEach((grid) => {
    const maxScroll = grid.scrollWidth - grid.clientWidth;
    if (maxScroll <= 2) return;
    if (grid.scrollLeft >= maxScroll - 10) {
      grid.scrollTo({ left: 0, behavior: "smooth" });
    } else {
      const firstTile = grid.querySelector(".tile");
      const tileW = firstTile ? (firstTile.offsetWidth + 6) : 130;
      grid.scrollBy({ left: tileW, behavior: "smooth" });
    }
  });
}
setInterval(tickCarousels, 3000);

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
  if (btn) btn.textContent = playing ? "Pause" : "Play";
  clearInterval(state.timer);
  if (playing) state.timer = setInterval(stepForward, ADVANCE_MS);
}

// ── Live polling ─────────────────────────────────────────────────────────────

// Every bag gets a short, human-friendly "tag" number — its 1-based
// position in the full live_events.json feed. This is the same number
// the mobile keypad confirmation page (mobile_keypad.html) asks staff
// to type in, and the same one the swipe page (mobile_swipe.html)
// shows on each card, so it has to be computed identically everywhere:
// stamped on the raw (unsliced, un-reset) event list, in feed order.
function stampTags(rawEvents) {
  rawEvents.forEach((event, i) => { event._tag = i + 1; });
  return rawEvents;
}

function setLiveEvents(rawEvents) {
  stampTags(rawEvents);
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

// ── Mobile confirmation sync ─────────────────────────────────────────────────
// The mobile swipe/keypad pages (served from the same origin) mark bags
// "Loaded" through /api/loaded/mark instead of localStorage, because a
// phone is a different browser than the kiosk. Pull that shared state in
// on every poll and fold it into the board's own dismissed/loaded sets so
// a bag confirmed on a phone disappears from the board just like one
// double-click-confirmed at the kiosk.
function pollServerLoaded() {
  fetch(LOADED_API_URL)
    .then((r) => (r.ok ? r.json() : []))
    .then((records) => {
      if (!Array.isArray(records) || !records.length) return;
      let changed = false;
      records.forEach((rec) => {
        const id = rec && rec.id;
        if (!id || state.loaded.has(id)) return;
        state.loaded.add(id);
        state.dismissed.add(id);
        changed = true;
      });
      if (changed) {
        saveLoaded(state.loaded);
        saveDismissed(state.dismissed);
        render();
      }
    })
    .catch(() => { /* mobile sync is best-effort — board still works offline */ });
}

// ── Live settings sync (Settings page → this board, no reload) ──────────────
// gui/settings.html writes uiScale to gui/settings.json via POST
// /api/settings. Poll it here so every open board tab (and attention.html)
// picks up a display-scale change within one poll interval, the same way
// cans/flights already sync from cans.html — just via the file API instead
// of the "storage" event, since settings.html isn't guaranteed to share
// localStorage with every tab that might have this board open.
let _lastAppliedUiScale = null;

function pollSettings() {
  fetch("/api/settings")
    .then((r) => (r.ok ? r.json() : {}))
    .then((saved) => {
      const scale = (saved && isFinite(saved.uiScale) && saved.uiScale > 0)
        ? saved.uiScale
        : ((_CFG.uiScale && isFinite(_CFG.uiScale)) ? _CFG.uiScale : 1);
      if (scale !== _lastAppliedUiScale) {
        document.documentElement.style.setProperty("--ui-scale", String(scale));
        _lastAppliedUiScale = scale;
      }
    })
    .catch(() => { /* best-effort — config.js's value stays in effect */ });
}

// Fire-and-forget: tell the server a bag was confirmed loaded (or the
// confirmation was undone) so mobile pages and other kiosk windows see it.
function postMarkLoaded(event, source) {
  fetch(`${LOADED_API_URL}/mark`, {
    method:  "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      id:            event.id,
      flight_number: event.flight_number || null,
      tag:           event._tag || null,
      source:        source || "board",
    }),
  }).catch(() => { /* best-effort */ });
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
  btn.textContent = "Blocked — click to allow";
}

// ── Manage Cans window ────────────────────────────────────────────────────────

function openCansWindow() {
  window.open("cans.html", "dmms-cans", "width=900,height=620");
}

// ── Wiring ───────────────────────────────────────────────────────────────────

const manageCansBtn = el("btn-manage-cans");
if (manageCansBtn) manageCansBtn.addEventListener("click", openCansWindow);

// ── Settings toggles ─────────────────────────────────────────────────────────

const togTimeout    = el("tog-timeout");
const timeoutSecsEl = el("timeout-secs");
const togAutoscroll = el("tog-autoscroll");

if (togTimeout) {
  togTimeout.checked = settings.timeoutEnabled;
  if (timeoutSecsEl) {
    timeoutSecsEl.value    = settings.timeoutSecs;
    timeoutSecsEl.disabled = !settings.timeoutEnabled;
    timeoutSecsEl.addEventListener("change", () => {
      settings.timeoutSecs = Math.max(5, Number(timeoutSecsEl.value) || 30);
      timeoutSecsEl.value  = settings.timeoutSecs;
      saveSettings();
      tileCache.clear();
      render();
    });
  }
  togTimeout.addEventListener("change", () => {
    settings.timeoutEnabled = togTimeout.checked;
    if (timeoutSecsEl) timeoutSecsEl.disabled = !settings.timeoutEnabled;
    saveSettings();
    tileCache.clear();   // rebuild tiles with/without countdown bars
    render();
  });
}

if (togAutoscroll) {
  togAutoscroll.checked = settings.autoScrollEnabled;
  togAutoscroll.addEventListener("change", () => {
    settings.autoScrollEnabled = togAutoscroll.checked;
    saveSettings();
  });
}

const openAttentionBtn = el("btn-open-attention");
if (openAttentionBtn) {
  openAttentionBtn.addEventListener("click", () => {
    openAttentionBtn.classList.remove("attention-blocked");
    openAttentionBtn.textContent = "Needs Attention";
    openAttentionWindow();
  });
  openAttentionWindow();
}

// ── Boot ─────────────────────────────────────────────────────────────────────

// Live clock — updates every second
(function () {
  function updateClock() {
    const clockEl = document.getElementById("live-clock");
    if (!clockEl) return;
    clockEl.textContent = new Date().toLocaleTimeString(undefined, {
      hour: "2-digit", minute: "2-digit", second: "2-digit",
    });
  }
  updateClock();
  setInterval(updateClock, 1000);
}());

buildQuadrantShells();
render();

if (IS_LIVE) {
  document.body.classList.add("live-mode");

  const resetBtn = el("btn-reset");
  if (resetBtn) {
    resetBtn.addEventListener("click", () => {
      state.liveResetOffset += state.events.length;
      state.events    = [];
      state.dismissed = new Set();
      state.loaded    = new Set();
      state.index     = -1;
      tileCache.clear();
      saveResetOffset(state.liveResetOffset);
      saveDismissed(state.dismissed);
      saveLoaded(state.loaded);
      render();
    });
  }

  pollLive();
  pollServerLoaded();
  pollSettings();
  setInterval(pollLive, LIVE_POLL_MS);
  setInterval(pollServerLoaded, LIVE_POLL_MS);
  setInterval(pollSettings, LIVE_POLL_MS);
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
