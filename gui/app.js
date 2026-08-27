// Kiosk display driver. Fetches Rian's mock_events.json today; once the
// camera subsystem serves live events (from events_with_flights.csv), this
// fetch swaps to that endpoint — nothing else here changes, as long as the
// shape stays { id, timestamp, status, flight_number, destination, photo_path }.
// Served via run_gui.py from the repo root, so paths are relative to that.
const DATA_URL = "../python/camera_subsystem/mock_events.json";
const IMAGE_BASE_URL = "../python/camera_subsystem/";
const ADVANCE_MS = 4000;
const SENSOR_PULSE_MS = 900;

const ICONS = {
  check: '<svg viewBox="0 0 24 24"><path fill="currentColor" d="m9.5 16.2-3.5-3.5 1.4-1.4 2.1 2.1 6.1-6.1 1.4 1.4Z"/></svg>',
  warning: '<svg viewBox="0 0 24 24"><path fill="currentColor" d="M12 3 1 21h22Zm0 4.6L18.9 19H5.1ZM11 10h2v5h-2Zm0 6h2v2h-2Z"/></svg>',
  duplicate: '<svg viewBox="0 0 24 24"><path fill="currentColor" d="M16 1H4a2 2 0 0 0-2 2v14h2V3h12Zm3 4H8a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h11a2 2 0 0 0 2-2V7a2 2 0 0 0-2-2Zm0 16H8V7h11Z"/></svg>',
  critical: '<svg viewBox="0 0 24 24"><path fill="currentColor" d="M11 15h2v2h-2Zm0-8h2v6h-2ZM3.5 19h17a1 1 0 0 0 .87-1.5l-8.5-14.7a1 1 0 0 0-1.74 0l-8.5 14.7A1 1 0 0 0 3.5 19Z"/></svg>',
  question: '<svg viewBox="0 0 24 24"><path fill="currentColor" d="M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20Zm.75 15h-1.5v-1.5h1.5Zm1.53-6.2c-.5.55-.9.98-.9 1.95h-1.5c0-1.35.62-2.02 1.2-2.65.5-.55.9-.98.9-1.6 0-.9-.73-1.5-1.75-1.5-.9 0-1.63.5-1.9 1.3l-1.4-.55C9.4 6.5 10.6 5.6 12.03 5.6c1.8 0 3.22 1.15 3.22 2.9 0 1.05-.55 1.7-1.97 3.3Z"/></svg>',
  clock: '<svg viewBox="0 0 24 24"><path fill="currentColor" d="M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20Zm.75 5v5.4l4.2 2.5-.75 1.3-5-3V7Z"/></svg>',
};

const STATUS_CONFIG = {
  matched: {
    label: "Matched",
    detail: "Barcode and camera snapshot paired successfully.",
    icon: ICONS.check,
    className: "status-matched",
  },
  manual: {
    label: "Manual check required",
    detail: "No scan found in the verification window — identify this bag by hand.",
    icon: ICONS.warning,
    className: "status-manual",
    flagged: true,
  },
  duplicate: {
    label: "Duplicate scan",
    detail: "This tag is already active on the current loop.",
    icon: ICONS.duplicate,
    className: "status-duplicate",
    flagged: true,
  },
  unmatched_scan: {
    label: "Unmatched scan",
    detail: "A barcode was read but no paired event was found.",
    icon: ICONS.critical,
    className: "status-unmatched_scan",
    flagged: true,
  },
  ambiguous: {
    label: "Ambiguous match",
    detail: "More than one possible match was found — verify by hand.",
    icon: ICONS.question,
    className: "status-ambiguous",
    flagged: true,
  },
};

const WAITING_CONFIG = {
  label: "Waiting",
  detail: "Waiting for the next bag to reach the sensor.",
  icon: ICONS.clock,
  className: "status-waiting",
};

const el = (id) => document.getElementById(id);

const state = {
  events: [],
  index: -1,
  playing: false,
  timer: null,
};

function formatTimestamp(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleString(undefined, {
    month: "short", day: "numeric",
    hour: "2-digit", minute: "2-digit", second: "2-digit",
  });
}

function setField(id, value, { unknownIfEmpty = false } = {}) {
  const node = el(id);
  if (value === null || value === undefined || value === "") {
    node.textContent = unknownIfEmpty ? "Unknown" : "—";
    node.classList.toggle("unknown", unknownIfEmpty);
  } else {
    node.textContent = value;
    node.classList.remove("unknown");
  }
}

function renderVerdict(status) {
  const cfg = STATUS_CONFIG[status] || WAITING_CONFIG;
  const banner = el("verdict");
  banner.className = `verdict ${cfg.className}`;
  el("verdict-icon").innerHTML = cfg.icon;
  el("verdict-label").textContent = cfg.label;
  el("verdict-detail").textContent = cfg.detail;
}

function renderPhoto(photoPath) {
  const img = el("bag-photo");
  const fallback = el("photo-fallback");
  el("photo-path-text").textContent = photoPath
    ? `python/camera_subsystem/${photoPath}`
    : "";

  if (!photoPath) {
    img.classList.remove("loaded");
    fallback.style.display = "flex";
    return;
  }

  img.onload = () => {
    img.classList.add("loaded");
    fallback.style.display = "none";
  };
  img.onerror = () => {
    img.classList.remove("loaded");
    fallback.style.display = "flex";
  };
  img.src = IMAGE_BASE_URL + photoPath;
}

function renderStats() {
  const seen = state.events.slice(0, state.index + 1);
  const matched = seen.filter((e) => e.status === "matched").length;
  const flagged = seen.filter((e) => STATUS_CONFIG[e.status]?.flagged).length;
  el("stat-total").textContent = seen.length;
  el("stat-matched").textContent = matched;
  el("stat-flagged").textContent = flagged;
}

function pulseSensor(event) {
  const dot = el("sensor-dot");
  el("sensor-state").textContent = "Baggage detected";
  el("sensor-time").textContent = `${event.id} · triggered ${formatTimestamp(event.timestamp)}`;
  dot.classList.add("active");
  setTimeout(() => {
    dot.classList.remove("active");
    el("sensor-state").textContent = "Idle";
  }, SENSOR_PULSE_MS);
}

// tag_id isn't in the current event shape — barcode/tag pairing is Aaron's
// subsystem and hasn't been merged into events_with_flights.csv yet. Once it
// is (as a `tag_id` field), this renders it automatically; until then this
// panel is honest that there's nothing to show rather than faking a value.
function renderBarcode(event) {
  const valueNode = el("barcode-value");
  if (event.tag_id) {
    valueNode.textContent = event.tag_id;
    valueNode.classList.remove("unknown");
    el("barcode-read-state").textContent = "Read OK";
  } else {
    valueNode.textContent = "Not wired up yet";
    valueNode.classList.add("unknown");
    el("barcode-read-state").textContent = "Waiting on barcode scanner subsystem";
  }
}

function renderIdle() {
  el("sensor-state").textContent = "Idle";
  el("sensor-time").textContent = "No bag detected yet";
  renderBarcode({});
  renderPhoto(null);
  setField("field-flight", null);
  setField("field-destination", null);
  setField("field-timestamp", null);
  renderVerdict(null);
  renderStats();
}

function renderCurrent() {
  const event = state.events[state.index];
  if (!event) {
    renderIdle();
    return;
  }

  pulseSensor(event);
  renderBarcode(event);
  renderPhoto(event.photo_path);
  setField("field-flight", event.flight_number, { unknownIfEmpty: event.status === "manual" });
  setField("field-destination", event.destination, { unknownIfEmpty: event.status === "manual" });
  setField("field-timestamp", formatTimestamp(event.timestamp));
  renderVerdict(event.status);
  renderStats();
}

function goTo(index) {
  if (!state.events.length) return;
  state.index = ((index % state.events.length) + state.events.length) % state.events.length;
  renderCurrent();
}

function stepForward() { goTo(state.index + 1); }
function stepBackward() { goTo(state.index - 1); }

function setPlaying(playing) {
  state.playing = playing;
  el("btn-play").textContent = playing ? "⏸" : "▶";
  clearInterval(state.timer);
  if (playing) {
    if (state.index === -1) stepForward();
    state.timer = setInterval(stepForward, ADVANCE_MS);
  }
}

el("btn-prev").addEventListener("click", () => { setPlaying(false); stepBackward(); });
el("btn-next").addEventListener("click", () => { setPlaying(false); stepForward(); });
el("btn-play").addEventListener("click", () => setPlaying(!state.playing));

fetch(DATA_URL)
  .then((r) => r.json())
  .then((events) => {
    state.events = events;
    renderIdle();
  })
  .catch((err) => {
    el("sensor-state").textContent = "Failed to load mock data";
    console.error(err);
  });
