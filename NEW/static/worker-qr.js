// ─────────────────────────────────────────────────────────────────────────
// "Worker QR" popup for the main board.
//
// This computer's LAN address changes depending on where it's plugged in,
// so instead of a fixed URL, this asks the server what address it's
// actually bound to right now (GET /api/server-info) and renders that as
// a QR code a phone camera can scan straight into the worker view for
// this MUL — as long as the phone is on the same network as this
// computer, regardless of what that network is.
//
// QR rendering uses vendor/qrcode.js (vendored, MIT-licensed — see
// vendor/QRCODE-LICENSE.txt) so this works with zero internet access.
// ─────────────────────────────────────────────────────────────────────────

(function () {
  const el = (id) => document.getElementById(id);
  const btn   = el("btn-worker-qr");
  const modal = el("worker-qr-modal");
  if (!btn || !modal) return;

  const mulId = btn.dataset.mulId || "1";

  // Cache the server info for the session — the LAN IP won't change
  // while the server keeps running.
  let cachedInfo = null;

  function drawQr(canvasId, text) {
    const canvas = el(canvasId);
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

  async function fetchServerInfo() {
    if (cachedInfo) return cachedInfo;
    const r = await fetch("/api/server-info", { cache: "no-store" });
    if (!r.ok) throw new Error("server-info fetch failed");
    cachedInfo = await r.json();
    return cachedInfo;
  }

  async function openModal() {
    modal.hidden = false;
    const note = el("worker-qr-note");
    note.textContent = "Detecting this computer's network address…";
    el("worker-qr-url").textContent = "";

    try {
      const info = await fetchServerInfo();
      if (!info.lan_ip) throw new Error("no LAN IP detected");

      const url = `http://${info.lan_ip}:${info.port}/worker/${mulId}`;

      el("worker-qr-url").textContent = url;
      drawQr("worker-qr-canvas", url);
      note.textContent = "Scan with a phone on the same Wi-Fi/network as this computer.";
    } catch (err) {
      console.error(err);
      note.textContent =
        "Couldn't detect a network address for this computer — check its Wi-Fi/Ethernet " +
        "connection and that the server was started with host 0.0.0.0.";
    }
  }

  function closeModal() { modal.hidden = true; }

  btn.addEventListener("click", openModal);
  el("worker-qr-close").addEventListener("click", closeModal);
  modal.addEventListener("click", (e) => { if (e.target === modal) closeModal(); });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !modal.hidden) closeModal();
  });
}());
