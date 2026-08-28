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
    state.dismissed.add(event.id);
    render();
  });

  return tile;
}

function openZoom(event) {
  const img = el("zoom-image");
  img.src = IMAGE_BASE_URL + event.photo_path;
  img.alt = `Snapshot of ${event.id || "bag"}`;
  const sub = [event.id, formatTime(event.timestamp)].filter(Boolean).join(" · ");
  el("zoom-caption").textContent = `${event.flight_number || "Unknown flight"} · ${sub}`;
  el("zoom-overlay").hidden = false;
}

function closeZoom() {
  el("zoom-overlay").hidden = true;
}

function fillGrid(gridEl, items, { emptyText, statusChipFor = null }) {
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
    const chip = statusChipFor ? statusChipFor(event) : null;
    gridEl.appendChild(makeTile(event, { statusChip: chip }));
  });
}

function render() {
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

  buckets.forEach((items, i) => {
    fillGrid(el(`quadrant-grid-${i}`), items, { emptyText: "Waiting for next bag…" });
    el(`quadrant-count-${i}`).textContent = String(items.length);
  });

  fillGrid(el("attention-grid"), attention, {
    emptyText: "No bags need attention",
    statusChipFor: (event) => STATUS_INFO[event.status],
  });

  // Scanned = In a can + Needs attention + Loaded, always.
  el("stat-total").textContent = String(scannedSoFar.length);
  el("stat-routed").textContent = String(visible.length - attention.length);
  el("stat-flagged").textContent = String(attention.length);
  el("stat-loaded").textContent = String(loaded);
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

el("zoom-overlay").addEventListener("click", closeZoom);
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") closeZoom();
});

buildQuadrantShells();
render();

if (IS_LIVE) {
  document.body.classList.add("live-mode");
  const banner = el("mode-banner");
  banner.classList.add("live");
  banner.innerHTML = '<strong>LIVE</strong>: polling <code>live_events.json</code> from main.py.';

  // Clears everything currently shown, and the stats, without needing to
  // restart main.py or reload the page. live_events.json only ever grows
  // (main.py appends forever within a run), so this permanently skips
  // everything raw-index-wise up to right now -- not just marking it
  // dismissed, which would still count toward Scanned/Loaded forever.
  // New bags from the next poll onward show up and count normally.
  el("btn-reset").addEventListener("click", () => {
    state.liveResetOffset += state.events.length;
    state.events = [];
    state.dismissed = new Set();
    state.index = -1;
    render();
  });

  pollLive();
  setInterval(pollLive, LIVE_POLL_MS);
} else {
  el("btn-prev").addEventListener("click", () => { setPlaying(false); stepBackward(); });
  el("btn-next").addEventListener("click", () => { setPlaying(false); stepForward(); });
  el("btn-play").addEventListener("click", () => setPlaying(!state.playing));

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
