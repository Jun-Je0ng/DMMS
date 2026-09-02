// Kiosk display driver.
//
// Two modes, chosen by a URL param so the same page serves both:
//   gui/               -> demo mode: steps through Rian's mock_events.json,
//                          then keeps generating random bags once it runs out.
//   gui/?live=1        -> live mode: polls python/camera_subsystem/live_events.json,
//                          written by main.py as real bags come through. New
//                          bags appear on their own; no Play/Next needed.
// Both feeds use the same shape: { id, timestamp, status, flight_number,
// destination, photo_path }, so nothing else in this file needs to know
// which mode it's in beyond the branches below.
const IS_LIVE = new URLSearchParams(location.search).has("live");
const DATA_URL = IS_LIVE
  ? "../python/camera_subsystem/live_events.json"
  : "../python/camera_subsystem/mock_events.json";
const FLIGHTS_URL = "../python/camera_subsystem/flights.csv";
const IMAGE_BASE_URL = "../python/camera_subsystem/";
const ADVANCE_MS = 2500;
const LIVE_POLL_MS = 1500;
const ZOOM_CLICK_DELAY_MS = 220;
const CAN_COUNT = 4;
const CAN_LABELS = ["Can 1", "Can 2", "Can 3", "Can 4"];

// Weighted so most bags come through clean, matching the "180 scans is
// viable, not 100%" note from the site visit — a handful still need a human.
const STATUS_WEIGHTS = [
  ["matched", 70],
  ["manual", 10],
  ["duplicate", 8],
  ["unmatched_scan", 6],
  ["ambiguous", 6],
];

// Only "matched" bags are confidently routed to a can. Everything else — no
// scan found, a repeat read, an unpaired scan, more than one possible match —
// goes to the Needs Attention tray instead of a best-guess quadrant, per the
// original site-visit workflow: no confirmed can ID means a handler scans
// and places the bag by hand rather than the system guessing for them.
const STATUS_INFO = {
  manual: { label: "Manual check", className: "status-manual" },
  duplicate: { label: "Duplicate scan", className: "status-duplicate" },
  unmatched_scan: { label: "Unmatched scan", className: "status-unmatched_scan" },
  ambiguous: { label: "Ambiguous match", className: "status-ambiguous" },
};

const CAMERA_ICON =
  '<svg viewBox="0 0 24 24"><path fill="currentColor" d="M4 5h3l1.5-2h7L17 5h3a2 2 0 0 1 2 2v11a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2Zm8 3.5a4.5 4.5 0 1 0 0 9 4.5 4.5 0 0 0 0-9Zm0 2a2.5 2.5 0 1 1 0 5 2.5 2.5 0 0 1 0-5Z"/></svg>';

const el = (id) => document.getElementById(id);

const state = {
  events: [],
  flights: [],
  index: -1,
  playing: false,
  timer: null,
  dismissed: new Set(),
  seq: 0,
  // How many of the raw events from live_events.json (which only ever grows,
  // main.py appends forever within a run) to skip. Reset sets this to "all
  // of them, as of right now" so stats genuinely go back to zero instead of
  // just clearing the board while still counting old bags as history.
  liveResetOffset: 0,
};

// Board and attention.html are separate windows with separate polling loops
// and separate in-memory `state` -- in live mode, dismissing a tile or
// resetting has to reach both, so that state is mirrored through
// localStorage (shared across same-origin windows) instead of living only
// in one window's memory. Demo mode stays purely in-memory: its ids aren't
// stable across a reload (regenerated from the mock fixture + a counter),
// so persisting dismissed ids there would misapply to unrelated bags.
const STORAGE_KEYS = { dismissed: "dmms:dismissed", resetOffset: "dmms:liveResetOffset" };

function loadDismissed() {
  try {
    return new Set(JSON.parse(localStorage.getItem(STORAGE_KEYS.dismissed) || "[]"));
  } catch {
    return new Set();
  }
}

function saveDismissed(set) {
  try {
    localStorage.setItem(STORAGE_KEYS.dismissed, JSON.stringify([...set]));
  } catch {
    /* private-browsing or storage disabled -- this window just won't sync */
  }
}

function loadResetOffset() {
  const n = Number(localStorage.getItem(STORAGE_KEYS.resetOffset));
  return Number.isFinite(n) ? n : 0;
}

function saveResetOffset(n) {
  try {
    localStorage.setItem(STORAGE_KEYS.resetOffset, String(n));
  } catch {
    /* private-browsing or storage disabled -- this window just won't sync */
  }
}

function dismissTile(id) {
  state.dismissed.add(id);
  if (IS_LIVE) saveDismissed(state.dismissed);
  render();
}

function formatTime(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  return d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

// Balances tile count into a roughly square grid, same approach a video call
// uses: 1 bag fills the whole quadrant, 2 split it evenly, 4 make a 2x2, etc.
function gridDims(count) {
  if (count <= 1) return { cols: 1, rows: 1 };
  const cols = Math.ceil(Math.sqrt(count));
  const rows = Math.ceil(count / cols);
  return { cols, rows };
}

function parseFlightsCsv(text) {
  const lines = text.trim().split("\n").slice(1); // drop header row
  return lines
    .map((line) => line.split(","))
    .filter((cols) => cols.length >= 2)
    .map(([flight_number, destination]) => ({ flight_number: flight_number.trim(), destination: destination.trim() }));
}

function randomStatus() {
  const total = STATUS_WEIGHTS.reduce((sum, [, weight]) => sum + weight, 0);
  let roll = Math.random() * total;
  for (const [status, weight] of STATUS_WEIGHTS) {
    if (roll < weight) return status;
    roll -= weight;
  }
  return "matched";
}

// Endless demo feed: generates a bag in the same shape as a real event, so
// Play can run indefinitely instead of stopping once the mock fixture runs
// out. No photo_path — there's no real photo behind a generated bag, and the
// camera fallback icon makes that honestly visible rather than faking one.
function generateRandomEvent() {
  state.seq += 1;
  const status = randomStatus();
  const pool = state.flights.length ? state.flights : [{ flight_number: "QF000", destination: "Unknown" }];
  const flight = pool[Math.floor(Math.random() * pool.length)];
  const isKnown = status !== "manual";
  return {
    id: `bag_${state.seq}`,
    timestamp: new Date().toISOString(),
    status,
    flight_number: isKnown ? flight.flight_number : null,
    destination: isKnown ? flight.destination : null,
    photo_path: null,
  };
}

// Demo-only stand-in for real can assignment. The barcode subsystem (not
// merged in yet) will presumably send an explicit field — this checks for
// one first (`can`, 0-based or a label) and only falls back to a hash of the
// bag id if it's missing, so wiring in the real field later is automatic.
function canIndexFor(event) {
  if (event.can !== undefined && event.can !== null) {
    const n = Number(event.can);
    if (!Number.isNaN(n)) return ((n % CAN_COUNT) + CAN_COUNT) % CAN_COUNT;
  }
  const key = String(event.id || event.flight_number || "");
  let hash = 0;
  for (let i = 0; i < key.length; i++) hash = (hash * 31 + key.charCodeAt(i)) >>> 0;
  return hash % CAN_COUNT;
}

function buildQuadrantShells() {
  const container = el("quadrants");
  if (!container) return; // attention.html has no quadrants -- that's the whole point
  container.innerHTML = "";
  for (let i = 0; i < CAN_COUNT; i++) {
    const section = document.createElement("section");
    section.className = "quadrant";
    section.dataset.can = String(i);
    section.innerHTML = `
      <div class="quadrant-header">
        <span class="quadrant-label"><span class="quadrant-dot"></span>${CAN_LABELS[i]}</span>
        <span class="quadrant-count" id="quadrant-count-${i}">0</span>
      </div>
      <div class="tile-grid" id="quadrant-grid-${i}"></div>
    `;
    container.appendChild(section);
  }
}

function makeTile(event, { statusChip = null } = {}) {
  const tile = document.createElement("div");
  tile.className = "tile";
  tile.title = "Click to zoom · double-click to clear once loaded";

  const photo = document.createElement("div");
  photo.className = "tile-photo";
  photo.innerHTML = CAMERA_ICON;

  if (event.photo_path) {
    const img = document.createElement("img");
    img.alt = `Snapshot of ${event.id || "bag"}`;
    // The fallback camera icon sits behind the img; with object-fit:
    // contain, a photo whose aspect ratio doesn't match the tile leaves a
    // letterboxed gap the icon would otherwise show through, so hide it
    // outright once a real photo is actually showing.
    const fallbackIcon = photo.querySelector("svg");
    img.onload = () => {
      img.classList.add("loaded");
      if (fallbackIcon) fallbackIcon.style.display = "none";
    };
    img.onerror = () => {
      img.classList.remove("loaded");
      if (fallbackIcon) fallbackIcon.style.display = "";
    };
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
    chip.className = `tile-status-chip ${statusChip.className}`;
    chip.textContent = statusChip.label;
    tile.appendChild(chip);
  }
  tile.appendChild(caption);

  // A double-click fires two click events before dblclick -- delay opening
  // the zoom view just long enough to cancel it if a second click follows,
  // so double-clicking dismisses a tile without also flashing the zoom open.
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

// Opens the full photo in its own browser window (rather than an in-page
// overlay) so a handler can drag it to a second monitor or keep it up
// alongside the board without it sitting on top of the live tiles.
function openZoom(event) {
  if (!event.photo_path) return;
  // No noopener/noreferrer here: this popup only ever shows content we write
  // into it ourselves (never navigates anywhere external), and those flags
  // make window.open() return null by spec, which left the popup blank --
  // the window still opened, we just lost the reference needed to fill it.
  const popup = window.open("", "_blank", "width=720,height=640");
  if (!popup) return; // actually blocked by the browser's popup blocker
  const sub = [event.id, formatTime(event.timestamp)].filter(Boolean).join(" · ");
  const title = `${event.flight_number || "Unknown flight"} · ${sub}`;
  popup.document.title = title;
  popup.document.body.style.cssText =
    "margin:0;height:100vh;display:flex;align-items:center;justify-content:center;background:#111;";
  const img = popup.document.createElement("img");
  img.src = IMAGE_BASE_URL + event.photo_path;
  img.alt = `Snapshot of ${event.id || "bag"}`;
  img.style.cssText = "max-width:100%;max-height:100%;object-fit:contain;";
  popup.document.body.appendChild(img);
}

// Tiles are cached by event id and reused across renders instead of being
// torn down and rebuilt every poll -- rebuilding recreated the <img> each
// time, which reset it to "unloaded" and made the photo visibly flicker
// (fallback icon -> photo) on every LIVE_POLL_MS tick, worst on Needs
// Attention bags since those sit the longest before a handler clears them.
const tileCache = new Map(); // event.id -> tile element

function fillGrid(gridEl, items, { emptyText, statusChipFor = null }, seenIds) {
  gridEl.innerHTML = "";
  const { cols, rows } = gridDims(items.length);
  gridEl.style.setProperty("--cols", cols);
  gridEl.style.setProperty("--rows", rows);

  if (!items.length) {
    const empty = document.createElement("div");
    empty.className = "tile-empty";
    empty.textContent = emptyText;
    gridEl.appendChild(empty);
    return;
  }
  items.forEach((event) => {
    seenIds.add(event.id);
    let tile = tileCache.get(event.id);
    if (!tile) {
      const chip = statusChipFor ? statusChipFor(event) : null;
      tile = makeTile(event, { statusChip: chip });
      tileCache.set(event.id, tile);
    }
    gridEl.appendChild(tile);
  });
}

function render() {
  // Pick up dismissals/resets made in the *other* window (board vs.
  // attention.html) since the last poll -- see the STORAGE_KEYS comment.
  if (IS_LIVE) state.dismissed = loadDismissed();

  const scannedSoFar = state.events.slice(0, state.index + 1);
  const visible = scannedSoFar.filter((e) => !state.dismissed.has(e.id));
  const loaded = scannedSoFar.length - visible.length;

  const buckets = Array.from({ length: CAN_COUNT }, () => []);
  const attention = [];

  visible.forEach((event) => {
    if (STATUS_INFO[event.status]) {
      attention.push(event);
    } else {
      buckets[canIndexFor(event)].push(event);
    }
  });

  const seenIds = new Set();

  if (el("quadrants")) {
    buckets.forEach((items, i) => {
      fillGrid(el(`quadrant-grid-${i}`), items, { emptyText: "Waiting for next bag…" }, seenIds);
      el(`quadrant-count-${i}`).textContent = String(items.length);
    });
  }

  const attentionGrid = el("attention-grid");
  if (attentionGrid) {
    fillGrid(attentionGrid, attention, {
      emptyText: "No bags need attention",
      statusChipFor: (event) => STATUS_INFO[event.status],
    }, seenIds);
  }

  for (const id of tileCache.keys()) {
    if (!seenIds.has(id)) tileCache.delete(id);
  }

  // Scanned = In a can + Needs attention + Loaded, always. Not every stat
  // tile exists on every page (attention.html only has "Waiting").
  if (el("stat-total")) el("stat-total").textContent = String(scannedSoFar.length);
  if (el("stat-routed")) el("stat-routed").textContent = String(visible.length - attention.length);
  if (el("stat-flagged")) el("stat-flagged").textContent = String(attention.length);
  if (el("stat-loaded")) el("stat-loaded").textContent = String(loaded);
}

function goTo(index) {
  if (!state.events.length) return;
  const max = state.events.length - 1;
  state.index = Math.max(-1, Math.min(index, max));
  render();
}

function stepForward() {
  if (state.index + 1 >= state.events.length) {
    state.events.push(generateRandomEvent());
  }
  goTo(state.index + 1);
}
function stepBackward() { goTo(state.index - 1); }

function setPlaying(playing) {
  state.playing = playing;
  el("btn-play").textContent = playing ? "⏸" : "▶";
  clearInterval(state.timer);
  if (playing) {
    state.timer = setInterval(stepForward, ADVANCE_MS);
  }
}

// Live mode has no demo timeline to scrub or generate — bags just arrive.
function setLiveEvents(rawEvents) {
  state.liveResetOffset = loadResetOffset(); // pick up a Reset from the other window

  if (rawEvents.length < state.liveResetOffset) {
    // main.py restarted -- live_events.json went back to (near-)empty, so
    // any earlier manual reset point is stale and would otherwise eat the
    // first few genuinely new bags of this new run.
    state.liveResetOffset = 0;
    state.dismissed = new Set();
    saveResetOffset(0);
    saveDismissed(state.dismissed);
    tileCache.clear(); // a restarted main.py can reuse ids from the old run
  }
  state.events = rawEvents.slice(state.liveResetOffset);
  state.index = state.events.length - 1;
  render();
}

function pollLive() {
  fetch(DATA_URL)
    .then((r) => r.json())
    .then(setLiveEvents)
    .catch((err) => console.error(err));
}

// Opens (or refocuses, since it's a named window) the Needs Attention tray
// as its own window -- a full window gives those photos far more room than
// the strip they used to share with the board. Carries the current query
// string (?live=1) so the attention window polls the same feed.
//
// The auto-open call below (not a click) is exactly what popup blockers
// exist to stop -- no script trick gets around that, it's the browser
// deliberately refusing window.open() outside a real click. Rather than
// fail silently and leave someone hunting for a small footer button, flag
// the button itself as the fix when that happens.
function openAttentionWindow() {
  const win = window.open("attention.html" + location.search, "dmms-attention", "width=900,height=760");
  // Some blockers return a real handle but close it right back up async,
  // rather than returning null outright -- catch that case too.
  const flagIfBlocked = () => {
    if (!win || win.closed) flagAttentionBlocked();
  };
  if (!win) flagAttentionBlocked();
  else setTimeout(flagIfBlocked, 300);
}

function flagAttentionBlocked() {
  const btn = el("btn-open-attention");
  if (!btn) return;
  btn.classList.add("attention-blocked");
  btn.textContent = "⚠ Blocked by browser — click to allow Needs Attention popup";
}

const openAttentionBtn = el("btn-open-attention");
if (openAttentionBtn) {
  openAttentionBtn.addEventListener("click", () => {
    openAttentionBtn.classList.remove("attention-blocked");
    openAttentionBtn.textContent = "Needs Attention ↗";
    openAttentionWindow();
  });
  openAttentionWindow(); // auto-open on load; falls back to the flagged button above if blocked
}

buildQuadrantShells();
render();

if (IS_LIVE) {
  document.body.classList.add("live-mode");
  const banner = el("mode-banner");
  if (banner) {
    banner.classList.add("live");
    banner.innerHTML = '<strong>LIVE</strong>: polling <code>live_events.json</code> from main.py.';
  }

  // Clears everything currently shown, and the stats, without needing to
  // restart main.py or reload the page. live_events.json only ever grows
  // (main.py appends forever within a run), so this permanently skips
  // everything raw-index-wise up to right now -- not just marking it
  // dismissed, which would still count toward Scanned/Loaded forever.
  // New bags from the next poll onward show up and count normally. Only the
  // board page has this button; the offset/dismissed reset is persisted so
  // the attention window (which just polls) picks it up on its next tick.
  const resetBtn = el("btn-reset");
  if (resetBtn) {
    resetBtn.addEventListener("click", () => {
      state.liveResetOffset += state.events.length;
      state.events = [];
      state.dismissed = new Set();
      state.index = -1;
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
  if (nextBtn) nextBtn.addEventListener("click", () => { setPlaying(false); stepForward(); });
  if (playBtn) playBtn.addEventListener("click", () => setPlaying(!state.playing));

  Promise.all([
    fetch(DATA_URL).then((r) => r.json()),
    fetch(FLIGHTS_URL).then((r) => r.text()).then(parseFlightsCsv),
  ])
    .then(([events, flights]) => {
      state.events = events;
      state.flights = flights;
      state.seq = events.length;
      render();
    })
    .catch((err) => console.error(err));
}
