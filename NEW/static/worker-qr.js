// ─────────────────────────────────────────────────────────────────────────
// Always-visible "Worker QR" code on the main board (top-right corner).
//
// Handlers scan it with a phone to open the worker loading view for this
// MUL, so nobody has to touch the board's GUI.
//
// This computer's LAN address changes depending on where it's plugged in,
// so instead of a fixed URL, this asks the server what address it's
// actually bound to right now (GET /api/server-info) and renders that as
// a QR code — the phone must be on the same network as this computer.
//
// The board reloads itself every few seconds, so the last known address is
// cached in sessionStorage and the QR is drawn immediately on load (no
// blank flash), then refreshed in the background.
//
// QR rendering uses vendor/qrcode.js (vendored, MIT-licensed — see
// vendor/QRCODE-LICENSE.txt) so this works with zero internet access.
// ─────────────────────────────────────────────────────────────────────────

(function () {
  const dock = document.getElementById("qr-dock");
  if (!dock) return;

  const canvas = document.getElementById("qr-dock-canvas");
  const mulId  = dock.dataset.mulId || "1";
  const CACHE_KEY = "dmms_server_info";

  function drawQr(text) {
    const ctx = canvas.getContext("2d");
    ctx.fillStyle = "#ffffff";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    if (!window.qrcode || !text) return;

    // Level M (15% error correction) — good balance of density vs.
    // resilience to a slightly dirty/glared phone-camera scan.
    const qr = new window.qrcode(0, 0); // 0 = QRErrorCorrectLevel.M
    qr.addData(text);
    qr.make();

    const n     = qr.getModuleCount();
    const quiet = 2; // modules of white border — keeps scanners happy
    const cell  = canvas.width / (n + quiet * 2);

    ctx.fillStyle = "#000000";
    for (let r = 0; r < n; r++) {
      for (let c = 0; c < n; c++) {
        if (qr.isDark(r, c)) {
          ctx.fillRect(
            Math.round((c + quiet) * cell),
            Math.round((r + quiet) * cell),
            Math.ceil(cell),
            Math.ceil(cell)
          );
        }
      }
    }
  }

  function show(info) {
    if (!info || !info.lan_ip) {
      dock.classList.add("qr-dock-offline");
      dock.title = "No network address found";
      return;
    }
    dock.classList.remove("qr-dock-offline");
    const url = `http://${info.lan_ip}:${info.port}/worker/${mulId}`;
    if (dock.dataset.url === url) return;   // already showing this one
    dock.dataset.url = url;
    dock.title = url;   // hover tooltip, handy for debugging
    drawQr(url);
  }

  function readCache() {
    try { return JSON.parse(sessionStorage.getItem(CACHE_KEY)); }
    catch (e) { return null; }
  }

  function writeCache(info) {
    try { sessionStorage.setItem(CACHE_KEY, JSON.stringify(info)); }
    catch (e) { /* private mode etc. — fine, just refetch next time */ }
  }

  // 1) Draw instantly from the last known address, if we have one.
  show(readCache());

  // 2) Confirm / refresh from the server.
  fetch("/api/server-info", { cache: "no-store" })
    .then((r) => {
      if (!r.ok) throw new Error("server-info fetch failed");
      return r.json();
    })
    .then((info) => { writeCache(info); show(info); })
    .catch((err) => {
      console.error(err);
      if (!dock.dataset.url) show(null);
    });
}());
