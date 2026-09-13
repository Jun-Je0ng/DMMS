// ─────────────────────────────────────────────────────────────────────────────
// DMMS — shared helpers for the mobile bag-confirmation prototypes
//   gui/mobile_swipe.html   (swipe-through-a-deck, tick/cross per bag)
//   gui/mobile_keypad.html  (type a bag's tag number, confirm one at a time)
//
// Both pages poll the same data/live_events.json feed the kiosk board
// (app.js) uses, and both write confirmations to /api/loaded/mark or
// /api/loaded/unmark (served by run_gui.py, persisted to data/loaded.json)
// instead of localStorage — a phone is a different browser/origin-profile
// than the kiosk, so localStorage can't be shared. The kiosk board polls
// /api/loaded too (see app.js pollServerLoaded), so a bag confirmed here
// disappears from the board, and a bag confirmed at the kiosk shows up
// here as already loaded.
// ─────────────────────────────────────────────────────────────────────────────

const DMMS_DATA_URL   = "../data/live_events.json";
const DMMS_IMAGE_BASE = "../data/";
const DMMS_LOADED_URL = "/api/loaded";
const DMMS_POLL_MS    = 1500;

function dmmsFixPath(p) {
  return String(p || "").replace(/\\/g, "/");
}

function dmmsImageUrl(photoPath) {
  if (!photoPath) return null;
  return DMMS_IMAGE_BASE + dmmsFixPath(photoPath);
}

function dmmsFormatTime(iso) {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleTimeString(undefined, {
      hour: "2-digit", minute: "2-digit", second: "2-digit",
    });
  } catch { return ""; }
}

// Every bag gets a short "tag" number — its 1-based position in the full
// live_events.json feed. Identical scheme to gui/app.js's stampTags(),
// so the number shown here always matches the number on the kiosk tile.
function dmmsStampTags(events) {
  events.forEach((e, i) => { e._tag = i + 1; });
  return events;
}

async function dmmsFetchEvents() {
  const r = await fetch(DMMS_DATA_URL, { cache: "no-store" });
  if (!r.ok) throw new Error("events fetch failed: " + r.status);
  const events = await r.json();
  return dmmsStampTags(Array.isArray(events) ? events : []);
}

async function dmmsFetchLoaded() {
  const r = await fetch(DMMS_LOADED_URL, { cache: "no-store" });
  if (!r.ok) throw new Error("loaded fetch failed: " + r.status);
  const records = await r.json();
  return Array.isArray(records) ? records : [];
}

async function dmmsMarkLoaded(event, source) {
  const r = await fetch(`${DMMS_LOADED_URL}/mark`, {
    method:  "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      id:            event.id,
      flight_number: event.flight_number || null,
      tag:           event._tag || null,
      source:        source || "mobile",
    }),
  });
  if (!r.ok) throw new Error("mark failed: " + r.status);
  return r.json();
}

async function dmmsUnmarkLoaded(id) {
  const r = await fetch(`${DMMS_LOADED_URL}/unmark`, {
    method:  "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ id }),
  });
  if (!r.ok) throw new Error("unmark failed: " + r.status);
  return r.json();
}

// Only "matched" bags carry a real, resolved flight_number — everything
// else (manual / duplicate / unmatched_scan / ambiguous) belongs in the
// kiosk's Needs Attention tray, not a flight-specific confirmation deck.
function dmmsBagsForFlight(events, flightNumber) {
  const fn = String(flightNumber || "").trim().toUpperCase();
  if (!fn) return [];
  return events
    .filter((e) => e.status === "matched" && String(e.flight_number || "").toUpperCase() === fn)
    .sort((a, b) => a._tag - b._tag);
}

// Small toast/snackbar used by both pages for confirmation feedback.
function dmmsToast(msg, kind) {
  let host = document.getElementById("dmms-toast-host");
  if (!host) {
    host = document.createElement("div");
    host.id = "dmms-toast-host";
    host.className = "dmms-toast-host";
    document.body.appendChild(host);
  }
  const t = document.createElement("div");
  t.className = "dmms-toast" + (kind ? ` dmms-toast-${kind}` : "");
  t.textContent = msg;
  host.appendChild(t);
  requestAnimationFrame(() => t.classList.add("show"));
  setTimeout(() => {
    t.classList.remove("show");
    setTimeout(() => t.remove(), 250);
  }, 2200);
}
