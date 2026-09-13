// ─────────────────────────────────────────────────────────────────────────────
// DMMS GUI Configuration
//
// This is only the BOOTSTRAP value, used for the instant the page paints
// before app.js's first /api/settings poll resolves. The real, editable
// copy is gui/settings.json, written by the Settings page (settings.html,
// or the "⚙ Settings" button on the main board) — change it there, no
// file editing or restart needed, it applies to every open board tab
// within a couple of seconds. Editing the number below still works as a
// same-day fallback if you'd rather not open the page.
// ─────────────────────────────────────────────────────────────────────────────

window.DMMS_CONFIG = {

  // ── Display scale ──────────────────────────────────────────────────────────
  //   1.0  = default (laptop / standard monitor)
  //   1.25 = slightly larger
  //   1.5  = recommended for 30"+ screens and TVs
  //   2.0  = large-format / 4K TV at distance
  uiScale: 1.0,

};

// ─────────────────────────────────────────────────────────────────────────────
// Flights and cans: gui/flights.json and gui/cans.json (via /api/flights and
// /api/cans) are the source of truth, edited from cans.html — localStorage
// is only a same-browser fallback for when the server isn't reachable.
//
// Camera index, Arduino serial port/baud, trigger token, and pairing/loop
// timing: gui/settings.json (via /api/settings), edited from settings.html.
// Those apply the next time run.py / sim_runner.py is (re)started — see
// server/settings.py for how they're merged over config.py's defaults.
// ─────────────────────────────────────────────────────────────────────────────
