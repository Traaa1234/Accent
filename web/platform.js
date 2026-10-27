"use strict";
/* Browser-only version: answers the app's /api/... requests with Python running in a
   Web Worker (Pyodide), so nothing is uploaded anywhere. Loaded before app.js. */
(function () {
  const cfg = window.ACCENT_WEB || {};
  const worker = new Worker("worker.js?" + new URLSearchParams({
    pyodide: new URL(cfg.pyodide || "https://cdn.jsdelivr.net/pyodide/v0.27.7/full/", location.href).href,
    bundle: new URL(cfg.bundle || "accent_analyzer.zip", location.href).href,
  }));
  const pending = new Map();
  let nextId = 1;

  /* ---- loading banner ---- */
  const banner = document.createElement("div");
  banner.className = "boot";
  banner.setAttribute("role", "status");
  const bannerText = document.createElement("span");
  bannerText.textContent = "Loading the analysis engine…";
  const spin = document.createElement("span");
  spin.className = "boot-spin";
  banner.append(spin, bannerText);
  document.body.prepend(banner);
  const setBanner = (text, failed) => {
    bannerText.textContent = text;
    banner.classList.toggle("failed", !!failed);
  };

  worker.onmessage = e => {
    const m = e.data;
    if (m.type === "progress") setBanner(m.text + " This can take 20–60 seconds the first time.");
    else if (m.type === "ready") banner.remove();
    else if (m.type === "fatal") setBanner("The analysis engine couldn't start: " + m.error + ". Try reloading, or use a recent Chrome, Edge, Firefox or Safari.", true);
    else if (m.type === "response") {
      const p = pending.get(m.id);
      pending.delete(m.id);
      if (p) p(new Response(m.body, { status: m.status, headers: { "Content-Type": m.contentType } }));
    }
  };

  /* ---- audio: decode anything the browser can play to 16 kHz mono 16-bit WAV ---- */
  const SR = 16000;
  async function toWav(blob) {
    const buf = await blob.arrayBuffer();
    const Ctx = window.OfflineAudioContext || window.webkitOfflineAudioContext;
    let decoded;
    try { decoded = await new Ctx(1, 1, 44100).decodeAudioData(buf); }
    catch { throw new Error("Couldn't read that audio. Try an m4a, mp3, wav or webm file."); }
    const ctx = new Ctx(1, Math.max(1, Math.ceil(decoded.duration * SR)), SR);
    const src = ctx.createBufferSource();
    src.buffer = decoded; src.connect(ctx.destination); src.start();
    const pcm = (await ctx.startRendering()).getChannelData(0);
    const out = new DataView(new ArrayBuffer(44 + pcm.length * 2));
    const str = (o, s) => { for (let i = 0; i < s.length; i++) out.setUint8(o + i, s.charCodeAt(i)); };
    str(0, "RIFF"); out.setUint32(4, 36 + pcm.length * 2, true); str(8, "WAVEfmt ");
    out.setUint32(16, 16, true); out.setUint16(20, 1, true); out.setUint16(22, 1, true);
    out.setUint32(24, SR, true); out.setUint32(28, SR * 2, true); out.setUint16(32, 2, true);
    out.setUint16(34, 16, true); str(36, "data"); out.setUint32(40, pcm.length * 2, true);
    for (let i = 0; i < pcm.length; i++) {
      const v = Math.max(-1, Math.min(1, pcm[i]));
      out.setInt16(44 + i * 2, v < 0 ? v * 0x8000 : v * 0x7fff, true);
    }
    return out.buffer;
  }
  const stem = name => (name || "recording").replace(/\.[^.]*$/, "");

  async function send(msg, transfer) {
    const id = nextId++;
    const res = new Promise(resolve => pending.set(id, resolve));
    worker.postMessage({ id, ...msg }, transfer || []);
    return res;
  }

  async function platformFetch(path, init = {}) {
    const method = (init.method || "GET").toUpperCase();
    const msg = { method, path: path.split("?")[0] };
    const transfer = [];
    if (typeof init.body === "string") msg.json = JSON.parse(init.body);
    else if (init.body instanceof FormData) {
      msg.fields = {}; msg.files = {};
      for (const [k, v] of init.body.entries()) {
        if (typeof v === "string") { msg.fields[k] = v; continue; }
        const isZip = /\.zip$/i.test(v.name || "");
        const data = isZip ? await v.arrayBuffer() : await toWav(v);
        msg.files[k] = { name: isZip ? v.name : stem(v.name) + ".wav", data };
        transfer.push(data);
      }
    }
    return send(msg, transfer).catch(err => new Response(JSON.stringify({ error: String(err.message || err) }),
      { status: 400, headers: { "Content-Type": "application/json" } }));
  }

  /* Files (recordings, reference clips) become blob: URLs, cached per path. */
  const mediaCache = new Map();
  async function media(url) {
    if (url.startsWith("blob:")) return url;
    if (!mediaCache.has(url)) {
      mediaCache.set(url, platformFetch(url).then(async res => {
        if (!res.ok) throw new Error("not found");
        return URL.createObjectURL(await res.blob());
      }).catch(err => { mediaCache.delete(url); throw err; }));
    }
    return mediaCache.get(url);
  }

  function download(blob, name) {
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob); a.download = name;
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 5000);
  }

  /* Settings → "Where your data lives" for the browser version, with backup/restore. */
  function dataCard(view, ui) {
    const { h, button, toast, refreshState } = ui;
    const info = h("section", "card", view);
    h("h2", "", info, "Where your data lives");
    h("p", "small", info, "Only in this browser, on this device. Nothing is uploaded: the analysis runs on your own computer or phone.");
    h("p", "muted small", info, "Clearing this site's data (or browsing in a private window) erases it, and other browsers or devices can't see it. Download a backup now and then; you can restore it in any browser.");
    const row = h("div", "row", info);
    button("Download backup", "", row, async () => {
      const res = await platformFetch("/backup");
      download(await res.blob(), `accent-coach-backup-${new Date().toISOString().slice(0, 10)}.zip`);
    });
    const file = h("input", "", row); file.type = "file"; file.hidden = true; file.accept = ".zip";
    button("Restore a backup", "", row, () => file.click());
    file.addEventListener("change", async () => {
      if (!file.files[0]) return;
      if (!confirm("Replace everything in this browser with the backup?")) { file.value = ""; return; }
      const form = new FormData(); form.append("backup", file.files[0]);
      const res = await platformFetch("/restore", { method: "POST", body: form });
      const data = await res.json();
      file.value = "";
      if (!res.ok) { toast(data.error || "Restore failed"); return; }
      mediaCache.clear(); await refreshState(); toast("Backup restored");
    });
  }

  if (navigator.storage && navigator.storage.persist) navigator.storage.persist().catch(() => {});

  window.AccentPlatform = {
    kind: "web", features: { reports: false, pyin: false },
    fetch: platformFetch, media, dataCard,
  };
})();
