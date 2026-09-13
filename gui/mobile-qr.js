// ─────────────────────────────────────────────────────────────────────────────
// "Mobile Access" QR popup for the main board (gui/index.html only).
//
// The kiosk's LAN address changes depending on where it's plugged in, so
// instead of a URL painted on the wall, this asks the server what address
// it's actually bound to right now (GET /api/server-info, added in
// run_gui.py) and renders that as a QR code a phone camera can scan
// straight into mobile_swipe.html / mobile_keypad.html.
//
// QR rendering uses vendor/qrcode.js (vendored, MIT-licensed — see
// vendor/QRCODE-LICENSE.txt) so this works with zero internet access on
// site; nothing is fetched from a CDN.
// ─────────────────────────────────────────────────────────────────────────────

(function () {
  const el = (id) => document.getElementById(id);
  const btn   = el("btn-mobile-access");
  const modal = el("qr-modal");
  if (!btn || !modal) return;

  // Cache the server info for the session — the kiosk's IP won't change
  // while it's running, no need to re-fetch every time the modal opens.
  let cachedInfo = null;

  function drawQr(canvasId, text) {
    const canvas = el(canvasId);
    const ctx = canvas.getContext("2d");
    ctx.fillStyle = "#ffffff";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    if (!window.qrcode || !text) return;

    // Level M (15% error correction) — a good balance of density vs.
    // resilience to a slightly dirty/glared phone-camera scan; typeNumber
    // 0 lets the library pick the smallest QR version that fits the URL.
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

  async function fetchServerInfo() {
    if (cachedInfo) return cachedInfo;
    const r = await fetch("/api/server-info", { cache: "no-store" });
    if (!r.ok) throw new Error("server-info fetch failed");
    cachedInfo = await r.json();
    return cachedInfo;
  }

  async function openModal() {
    modal.hidden = false;
    const note = el("qr-modal-note");
    note.textContent = "Detecting this computer's network address…";

    try {
      const info = await fetchServerInfo();
      if (!info.lan_ip) throw new Error("no LAN IP detected");
      const base       = `http://${info.lan_ip}:${info.port}/gui/`;
      const swipeUrl   = base + "mobile_swipe.html";
      const keypadUrl  = base + "mobile_keypad.html";

      el("qr-url-swipe").textContent  = swipeUrl;
      el("qr-url-keypad").textContent = keypadUrl;
      drawQr("qr-canvas-swipe", swipeUrl);
      drawQr("qr-canvas-keypad", keypadUrl);
      note.textContent = "Phone must be on the same Wi-Fi/network as this computer.";
    } catch (err) {
      console.error(err);
      note.textContent =
        "Couldn't detect a network address for this computer — check its Wi-Fi/Ethernet " +
        "connection, or use \"Open on this device\" below if you're testing from here.";
      el("qr-url-swipe").textContent  = "";
      el("qr-url-keypad").textContent = "";
    }
  }

  function closeModal() { modal.hidden = true; }

  btn.addEventListener("click", openModal);
  el("qr-modal-close").addEventListener("click", closeModal);
  modal.addEventListener("click", (e) => { if (e.target === modal) closeModal(); });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !modal.hidden) closeModal();
  });
}());
