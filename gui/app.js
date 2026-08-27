// Kiosk display driver. Fetches Rian's mock_events.json today; once the
// camera subsystem serves live events (from events_with_flights.csv), this
// fetch swaps to that endpoint — nothing else here changes, as long as the
// shape stays { id, timestamp, status, flight_number, destination, photo_path }.
// Served via run_gui.py from the repo root, so paths are relative to that.
const DATA_URL = "../python/camera_subsystem/mock_events.json";
const IMAGE_BASE_URL = "../python/camera_subsystem/";
const ADVANCE_MS = 2500;
const CAN_COUNT = 4;
const CAN_LABELS = ["Can 1", "Can 2", "Can 3", "Can 4"];

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
  index: -1,
  playing: false,
  timer: null,
  dismissed: new Set(),
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
  tile.title = "Double-click to clear once loaded";

  const photo = document.createElement("div");
  photo.className = "tile-photo";
  photo.innerHTML = CAMERA_ICON;

  if (event.photo_path) {
    const img = document.createElement("img");
    img.alt = `Snapshot of ${event.id || "bag"}`;
    img.onload = () => img.classList.add("loaded");
    img.onerror = () => img.classList.remove("loaded");
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

  tile.addEventListener("dblclick", () => {
    state.dismissed.add(event.id);
    render();
  });

  return tile;
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
  const visible = state.events
    .slice(0, state.index + 1)
    .filter((e) => !state.dismissed.has(e.id));

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

  el("stat-total").textContent = String(visible.length);
  el("stat-routed").textContent = String(visible.length - attention.length);
  el("stat-flagged").textContent = String(attention.length);
}

function goTo(index) {
  if (!state.events.length) return;
  const max = state.events.length - 1;
  state.index = Math.max(-1, Math.min(index, max));
  render();
}

function stepForward() { goTo(state.index + 1); }
function stepBackward() { goTo(state.index - 1); }

function setPlaying(playing) {
  state.playing = playing;
  el("btn-play").textContent = playing ? "⏸" : "▶";
  clearInterval(state.timer);
  if (playing) {
    if (state.index >= state.events.length - 1) state.index = -1;
    state.timer = setInterval(() => {
      if (state.index >= state.events.length - 1) {
        setPlaying(false);
        return;
      }
      stepForward();
    }, ADVANCE_MS);
  }
}

el("btn-prev").addEventListener("click", () => { setPlaying(false); stepBackward(); });
el("btn-next").addEventListener("click", () => { setPlaying(false); stepForward(); });
el("btn-play").addEventListener("click", () => setPlaying(!state.playing));

buildQuadrantShells();
render();

fetch(DATA_URL)
  .then((r) => r.json())
  .then((events) => {
    state.events = events;
    render();
  })
  .catch((err) => {
    console.error(err);
  });
