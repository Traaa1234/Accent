"use strict";
/* Accent Coach front end. Plain JS; every piece of data reaches the DOM via textContent. */

const SVGNS = "http://www.w3.org/2000/svg";
const view = document.getElementById("view");
const state = { app: null, prompts: null, promptMode: "passage", passage: 0, topic: 0, drill: null };

/* ---------- small helpers ---------- */
function h(tag, cls, parent, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text;
  if (parent) parent.appendChild(n);
  return n;
}
function el(tag, attrs, parent, text) {
  const n = document.createElementNS(SVGNS, tag);
  for (const k in attrs || {}) n.setAttribute(k, attrs[k]);
  if (text != null) n.textContent = text;
  if (parent) parent.appendChild(n);
  return n;
}
function button(label, cls, parent, onClick) {
  const b = h("button", "btn " + (cls || ""), parent, label);
  b.type = "button";
  if (onClick) b.addEventListener("click", onClick);
  return b;
}
const isNum = v => typeof v === "number" && isFinite(v);
const pct = v => isNum(v) ? Math.round(v * 100) + "%" : "n/a";
const hz = v => isNum(v) ? Math.round(v) + " Hz" : "n/a";
const MON = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
function niceDate(iso) {
  const d = new Date(iso);
  return MON[d.getMonth()] + " " + d.getDate() + ", " + String(d.getHours()).padStart(2, "0") + ":" + String(d.getMinutes()).padStart(2, "0");
}
function toast(msg) {
  const t = document.getElementById("toast");
  t.textContent = msg; t.classList.add("show");
  clearTimeout(toast.timer); toast.timer = setTimeout(() => t.classList.remove("show"), 2200);
}
const tip = document.getElementById("tip");
function showTip(x, y, title, value, note) {
  tip.replaceChildren();
  h("div", "t", tip, title);
  if (value) h("div", "v", tip, value);
  if (note) h("div", "t", tip, note);
  tip.style.display = "block";
  const w = tip.offsetWidth, ht = tip.offsetHeight;
  let left = x + 14, top = y - ht - 10;
  if (left + w > innerWidth - 8) left = x - w - 14;
  if (top < 8) top = y + 16;
  tip.style.left = Math.max(8, left) + "px"; tip.style.top = top + "px";
}
const hideTip = () => { tip.style.display = "none"; };

async function api(path, opts = {}) {
  const init = { method: opts.method || "GET", headers: {} };
  if (init.method !== "GET") init.headers["X-Accent-App"] = "1";
  if (opts.json) { init.headers["Content-Type"] = "application/json"; init.body = JSON.stringify(opts.json); }
  if (opts.form) init.body = opts.form;
  const res = await fetch(path, init);
  const data = res.headers.get("content-type")?.includes("json") ? await res.json() : null;
  if (!res.ok) throw new Error((data && data.error) || `Request failed (${res.status})`);
  return data;
}
async function refreshState() { state.app = await api("/api/state"); return state.app; }

/* ---------- router ---------- */
const ROUTES = { record: viewRecord, results: viewResults, progress: viewProgress, practice: viewPractice, settings: viewSettings };
let cleanup = null;
async function route() {
  if (cleanup) { cleanup(); cleanup = null; }
  hideTip();
  const [name, arg] = (location.hash.slice(1) || "record").split("/");
  const fn = ROUTES[name] || viewRecord;
  for (const a of document.querySelectorAll("nav a")) {
    if (a.dataset.route === name) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
  }
  view.className = name === "progress" ? "wide" : "";
  view.replaceChildren();
  try { await fn(arg); } catch (err) { h("p", "status error", view, err.message); }
  view.focus({ preventScroll: true });
}
addEventListener("hashchange", route);

/* =====================================================================
   RECORD
   ===================================================================== */
async function viewRecord() {
  const app = state.app || await refreshState();
  state.prompts = state.prompts || await api("/api/prompts");
  h("h1", "", view, "Record");
  h("p", "lede", view, "Read a passage or talk freely for about a minute. More speech means more phrase endings to measure.");

  if (!app.settings.accent && app.count === 0) welcomeCard();

  // --- what to say ---
  const sayCard = h("section", "card", view);
  const head = h("div", "row", sayCard);
  h("h2", "", head, "What to say");
  h("span", "spacer", head);
  const seg = h("div", "seg", head);
  seg.setAttribute("role", "group"); seg.setAttribute("aria-label", "Prompt type");
  const modes = [["passage", "Read a passage"], ["topic", "Talk about a topic"], ["free", "Your own"]];
  if (state.drill) modes.unshift(["drill", "Drill: " + state.drill.name]);
  if (!modes.some(m => m[0] === state.promptMode)) state.promptMode = modes[0][0];
  const body = h("div", "", sayCard);
  for (const [id, label] of modes) {
    const b = h("button", "", seg, label); b.type = "button";
    b.setAttribute("aria-pressed", String(state.promptMode === id));
    b.addEventListener("click", () => {
      state.promptMode = id;
      for (const x of seg.children) x.setAttribute("aria-pressed", String(x === b));
      renderPrompt(body);
    });
  }
  renderPrompt(body);

  // --- recorder ---
  const recCard = h("section", "card", view);
  const grid = h("div", "recorder", recCard);
  const wrap = h("div", "rec-wrap", grid);
  const ring = el("svg", { class: "rec-ring", viewBox: "0 0 132 132", "aria-hidden": "true" }, wrap);
  el("circle", { class: "track", cx: 66, cy: 66, r: 62 }, ring);
  const C = 2 * Math.PI * 62;
  const fill = el("circle", { class: "fill", cx: 66, cy: 66, r: 62, "stroke-dasharray": C, "stroke-dashoffset": C,
    transform: "rotate(-90 66 66)" }, ring);
  const recBtn = h("button", "rec-btn", wrap);
  recBtn.type = "button"; recBtn.setAttribute("aria-label", "Start recording");
  const micIcon = () => {
    recBtn.replaceChildren();
    const s = el("svg", { viewBox: "0 0 24 24", width: 40, height: 40, "aria-hidden": "true" }, recBtn);
    el("path", { d: "M12 14a3 3 0 0 0 3-3V5a3 3 0 1 0-6 0v6a3 3 0 0 0 3 3Zm5-3a5 5 0 0 1-10 0H5a7 7 0 0 0 6 6.92V21h2v-3.08A7 7 0 0 0 19 11h-2Z", fill: "#fff" }, s);
  };
  micIcon();
  const side = h("div", "", grid);
  const timer = h("div", "timer", side, "0:00");
  h("div", "muted small", side, "Aim for at least 1:00. The ring turns full at one minute.");
  const meter = h("div", "meter", side); const level = h("div", "", meter);
  meter.setAttribute("aria-hidden", "true");
  const nameRow = h("div", "row", side);
  const nameInput = h("input", "", nameRow);
  nameInput.type = "text"; nameInput.placeholder = "Name this take (optional)"; nameInput.maxLength = 80;
  nameInput.setAttribute("aria-label", "Name this take");
  if (state.drill) nameInput.value = "Drill: " + state.drill.name;
  const status = h("p", "status", side);
  status.setAttribute("aria-live", "polite");

  // --- upload ---
  const drop = h("div", "drop", view);
  drop.style.marginTop = "14px";
  h("span", "", drop, "Already have a recording? Drop the file here or ");
  const pick = button("choose a file", "", drop);
  const fileInput = h("input", "", drop);
  fileInput.type = "file"; fileInput.hidden = true;
  fileInput.accept = ".m4a,.mp3,.wav,.flac,.aac,.webm,.ogg,.mp4,audio/*";
  pick.addEventListener("click", () => fileInput.click());
  fileInput.addEventListener("change", () => fileInput.files[0] && upload(fileInput.files[0], fileInput.files[0].name));
  drop.addEventListener("dragover", e => { e.preventDefault(); drop.classList.add("over"); });
  drop.addEventListener("dragleave", () => drop.classList.remove("over"));
  drop.addEventListener("drop", e => {
    e.preventDefault(); drop.classList.remove("over");
    const f = e.dataTransfer.files[0]; if (f) upload(f, f.name);
  });

  // --- recording logic ---
  let rec = null, stream = null, chunks = [], started = 0, tick = null, actx = null, raf = null;
  const fmt = s => Math.floor(s / 60) + ":" + String(Math.floor(s % 60)).padStart(2, "0");
  const setStatus = (msg, error) => { status.textContent = msg; status.classList.toggle("error", !!error); };

  function stopMedia() {
    clearInterval(tick); cancelAnimationFrame(raf);
    if (stream) stream.getTracks().forEach(t => t.stop());
    if (actx) actx.close();
    stream = null; actx = null; level.style.width = "0";
  }
  cleanup = () => { if (rec && rec.state === "recording") { rec.onstop = null; rec.stop(); } stopMedia(); };

  async function start() {
    if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
      setStatus("This browser can't record audio. Try Chrome, Edge or Firefox, or upload a file below.", true); return;
    }
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: false } });
    } catch (err) {
      setStatus(err.name === "NotAllowedError"
        ? "Microphone access was blocked. Allow it in the address bar (the mic icon), then try again."
        : "No microphone found. Plug one in or upload a file below.", true);
      return;
    }
    const mime = ["audio/webm;codecs=opus", "audio/ogg;codecs=opus", "audio/mp4"].find(t => MediaRecorder.isTypeSupported(t)) || "";
    rec = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined);
    chunks = [];
    rec.ondataavailable = e => { if (e.data.size) chunks.push(e.data); };
    rec.onstop = finish;
    rec.start(1000);
    started = performance.now();
    recBtn.classList.add("recording");
    recBtn.setAttribute("aria-label", "Stop recording");
    recBtn.replaceChildren(); h("span", "stop", recBtn);
    setStatus("Recording… press the button again to stop.");
    tick = setInterval(() => {
      const s = (performance.now() - started) / 1000;
      timer.textContent = fmt(s);
      fill.setAttribute("stroke-dashoffset", String(C * (1 - Math.min(1, s / 60))));
    }, 250);
    // Input level meter, so it's obvious the mic is picking you up.
    actx = new AudioContext();
    const an = actx.createAnalyser(); an.fftSize = 1024;
    actx.createMediaStreamSource(stream).connect(an);
    const buf = new Float32Array(an.fftSize);
    const draw = () => {
      an.getFloatTimeDomainData(buf);
      let sum = 0; for (const v of buf) sum += v * v;
      const db = 20 * Math.log10(Math.sqrt(sum / buf.length) + 1e-9);
      level.style.width = Math.max(0, Math.min(100, (db + 60) / 50 * 100)) + "%";
      raf = requestAnimationFrame(draw);
    };
    draw();
  }

  async function finish() {
    const secs = (performance.now() - started) / 1000;
    const type = rec.mimeType || "audio/webm";
    stopMedia();
    recBtn.classList.remove("recording"); micIcon(); recBtn.setAttribute("aria-label", "Start recording");
    if (secs < 3) { setStatus("That was under 3 seconds. Try again and speak for about a minute.", true); return; }
    const ext = type.includes("ogg") ? ".ogg" : type.includes("mp4") ? ".mp4" : ".webm";
    await upload(new Blob(chunks, { type }), "recording" + ext);
  }

  async function upload(blob, filename) {
    const form = new FormData();
    form.append("audio", blob, filename);
    form.append("name", nameInput.value.trim());
    recBtn.disabled = true; pick.disabled = true;
    status.replaceChildren(); h("span", "spinner", status); status.append(" Analyzing… this takes a few seconds.");
    status.classList.remove("error");
    try {
      const result = await api("/api/recordings", { method: "POST", form });
      state.lastResult = result;
      state.drill = null;
      await refreshState();
      location.hash = "#results/" + result.id;
    } catch (err) {
      setStatus(err.message, true);
    } finally {
      recBtn.disabled = false; pick.disabled = false;
    }
  }
  recBtn.addEventListener("click", () => (rec && rec.state === "recording") ? rec.stop() : start());

  // --- recent takes ---
  if (app.count) {
    const recent = await api("/api/recordings");
    const card = h("section", "card", view);
    h("h2", "", card, "Recent takes");
    const list = h("div", "row", card);
    list.style.marginTop = "8px";
    for (const r of recent.records.slice(-4).reverse()) {
      const a = h("a", "btn", list, r.label + " · HRT " + pct(r.metrics.hrt_rate));
      a.href = "#results/" + r.id;
    }
  }
}

function renderPrompt(body) {
  body.replaceChildren();
  const P = state.prompts;
  if (state.promptMode === "passage") {
    const row = h("div", "row", body); row.style.marginTop = "10px";
    const sel = h("select", "", row);
    sel.setAttribute("aria-label", "Passage");
    P.passages.forEach((p, i) => { const o = h("option", "", sel, p.title); o.value = i; });
    sel.value = state.passage;
    const text = h("p", "prompt-text", body, P.passages[state.passage].text);
    sel.addEventListener("change", () => { state.passage = +sel.value; text.textContent = P.passages[state.passage].text; });
    h("p", "muted small", body, "Read at your normal pace. Pause naturally at full stops.");
  } else if (state.promptMode === "topic") {
    const text = h("p", "prompt-topic", body, P.topics[state.topic]);
    h("p", "muted small", body, "Talk for a minute or more. Don't script it; natural speech is what we want to measure.");
    button("Another topic", "", body, () => { state.topic = (state.topic + 1) % P.topics.length; text.textContent = P.topics[state.topic]; });
  } else if (state.promptMode === "drill") {
    const d = state.drill;
    h("p", "muted small", body, "Read each sentence twice, applying the drill. Pause between sentences.");
    const ul = h("ul", "sentences", body);
    ul.style.fontSize = "18px";
    for (const s of d.examples) h("li", "", ul, s);
  } else {
    h("p", "prompt-text", body, "Say anything you like: a story, your plans for the week, an explanation of your work.");
  }
}

function welcomeCard() {
  const card = h("section", "card welcome", view);
  h("h2", "", card, "Welcome! One quick question first");
  h("p", "muted", card, "Which English do you speak now? It adds coaching for features the microphone can't measure yet (vowels, /r/, T-flaps).");
  const row = h("div", "row", card);
  for (const a of state.app.accents) {
    button(a.name, "", row, async () => {
      await api("/api/settings", { method: "PUT", json: { accent: a.id } });
      await refreshState();
      card.remove();
      toast("Saved: " + a.name);
    });
  }
}

/* =====================================================================
   RESULTS
   ===================================================================== */
async function viewResults(id) {
  const app = state.app || await refreshState();
  if (!app.count) {
    const e = h("div", "empty", view);
    h("h1", "", e, "No recordings yet");
    h("p", "", e, "Record your first take and the results appear here.");
    const a = h("a", "btn primary", e, "Go to Record"); a.href = "#record";
    return;
  }
  const list = await api("/api/recordings");
  const rid = +(id || app.latest_id);
  const r = (state.lastResult && state.lastResult.id === rid) ? state.lastResult : await api("/api/recordings/" + rid);

  // header: picker + actions
  const head = h("div", "row", view);
  const titleBox = h("div", "", head);
  h("h1", "", titleBox, r.label);
  h("p", "muted small", titleBox, niceDate(r.date) + " · " + (r.duration ?? "?") + " s · " + r.register + " register");
  h("span", "spacer", head);
  const sel = h("select", "", head);
  sel.setAttribute("aria-label", "Choose a recording");
  for (const x of list.records.slice().reverse()) {
    const o = h("option", "", sel, x.label + " — " + niceDate(x.date)); o.value = x.id;
  }
  sel.value = rid;
  sel.addEventListener("change", () => { location.hash = "#results/" + sel.value; });

  if (r.metrics_only) {
    h("p", "card", view, "This recording was added from the command line, so the app doesn't have its audio. Its numbers are in Progress.");
    return;
  }
  const actions = h("div", "row", view); actions.style.marginTop = "10px";
  const full = h("a", "btn", actions, "Full report"); full.href = `/api/recordings/${rid}/report.html`; full.target = "_blank"; full.rel = "noopener";
  const pdf = h("a", "btn", actions, "Download PDF"); pdf.href = `/api/recordings/${rid}/report.pdf`;
  h("span", "spacer", actions);
  button("Delete take", "danger", actions, async () => {
    if (!confirm("Delete this take and its audio? This can't be undone.")) return;
    await api("/api/recordings/" + rid, { method: "DELETE" });
    state.lastResult = null; await refreshState(); toast("Take deleted");
    location.hash = "#results";
  });

  // verdict + KPIs
  const v = h("section", "card", view);
  h("h2", "", v, "Verdict");
  h("p", "verdict", v, r.headline);
  const kpis = h("div", "kpis", view);
  const card = (label, key, fmt) => {
    const row = r.scorecard.find(s => s.key === key);
    const k = h("div", "kpi", kpis);
    h("div", "label", k, label);
    h("div", "value", k, fmt(r.metrics[key]));
    if (row && row.status_text) {
      const icon = row.status === "on_target" ? "✓" : row.status === "above" ? "▲" : "▼";
      h("span", "chip " + (row.status === "on_target" ? "ok" : row.status === "unknown" ? "na" : "off"), k, icon + " target " + row.target);
    }
  };
  card("HRT (rising endings)", "hrt_rate", pct);
  card("HIGH phrase onsets", "high_onset_rate", pct);
  card("Range ratio", "range_ratio", v => isNum(v) ? v.toFixed(2) + "×" : "n/a");
  card("Voiced ratio", "voiced_ratio", pct);

  // contour with playable phrase endings
  const cc = h("section", "card", view);
  h("h2", "", cc, "Your pitch, with every phrase ending");
  h("p", "muted small", cc, "Click a ▲ or ▼ (or a chip below) to hear that phrase. Rising endings are what American listeners hear as questions.");
  const leg = h("div", "legend", cc);
  const l1 = h("span", "", leg); h("span", "dotkey", l1); l1.append("pitch");
  const l2 = h("span", "", leg); h("span", "mk rising", l2, "▲"); l2.append("rising end");
  const l3 = h("span", "", leg); h("span", "mk falling", l3, "▼"); l3.append("falling end");
  const chartBox = h("div", "chart", cc);
  const audio = h("audio", "", cc);
  audio.controls = true; audio.preload = "metadata"; audio.src = `/api/recordings/${rid}/audio`;
  const chips = h("div", "ends", cc);
  const player = phrasePlayer(audio);
  const drawContour = () => contourChart(chartBox, r, player);
  drawContour();
  const ro = new ResizeObserver(() => drawContour()); ro.observe(chartBox);
  cleanup = () => { ro.disconnect(); audio.pause(); };
  r.ends.forEach((e, i) => {
    const b = h("button", "endchip", chips);
    b.type = "button";
    h("span", "mk " + e.direction, b, e.direction === "rising" ? "▲" : e.direction === "falling" ? "▼" : "■");
    b.append(`${e.delta > 0 ? "+" : ""}${Math.round(e.delta)} Hz · ${e.time.toFixed(1)}s`);
    b.setAttribute("aria-label", `Play phrase ending at ${e.time.toFixed(1)} seconds, ${e.direction} ${Math.round(Math.abs(e.delta))} hertz`);
    b.addEventListener("click", () => player.play(i));
    player.chips[i] = b;
  });
  const ph = r.phrasing;
  const thr = Object.entries(ph.by_threshold).map(([t, a]) => `${t}s pauses: ${a.n_ends} endings, HRT ${pct(a.hrt_rate)}`).join(" · ");
  h("p", "muted small", cc, `Phrases split at pauses ≥ ${ph.pause_threshold.toFixed(2)}s${ph.used_fallback ? " (fallback for continuous speech)" : ""}. ${thr}.`);

  // onsets + windows
  const g = h("div", "grid2", view);
  const on = h("section", "card", g);
  h("h2", "", on, "How you start phrases");
  h("p", "muted small", on, "Americans launch phrases high after a pause, then step down.");
  barRows(on, [
    ["HIGH", ph.onsets.high, [0.40, 1], "series"],
    ["MID", ph.onsets.mid, null, "series"],
    ["LOW", ph.onsets.low, [0, 0.20], "series"],
  ]);
  const wn = h("section", "card", g);
  h("h2", "", wn, "Pitch movement in 3-second windows");
  h("p", "muted small", wn, `${r.windows.n} windows. Native speech mostly falls through a phrase.`);
  barRows(wn, [
    ["Falling ▼", r.windows.falling, [0.50, 0.65], "falling"],
    ["Level", r.windows.level, [0.25, 0.35], "level"],
    ["Rising ▲", r.windows.rising, [0.10, 0.20], "rising"],
  ]);

  // coaching
  const co = h("section", "card", view);
  h("h2", "", co, "What to practice next");
  if (!r.recommendations.length) h("p", "muted", co, "Nothing triggered. Keep recording to confirm the pattern holds.");
  for (const rec of r.recommendations) {
    const box = h("div", "reco", co);
    const top = h("div", "row", box);
    h("strong", "", top, rec.name);
    if (rec.provisional) h("span", "badge plan", top, "provisional");
    h("span", "spacer", top);
    const go = h("a", "btn", top, "Practice this"); go.href = "#practice/" + rec.id;
    h("p", "muted small", box, rec.reasons.join("; "));
    if (rec.drills[0]) h("p", "small", box, "Start with: " + rec.drills[0].name + " — " + rec.drills[0].steps[0]);
  }

  // findings + flags + scorecard
  const fl = h("section", "card", view);
  h("h2", "", fl, "Findings");
  flagList(fl, [...r.progress, ...r.findings]);
  const det = h("details", "card", view);
  h("summary", "", det, "Full scorecard");
  const wrap = h("div", "table-wrap", det);
  const t = h("table", "", wrap);
  const hr = h("tr", "", h("thead", "", t));
  for (const c of ["Metric", "Value", "Target", "Status"]) h("th", "", hr, c);
  const tb = h("tbody", "", t);
  for (const s of r.scorecard) {
    const tr = h("tr", "", tb);
    h("td", "", tr, s.label);
    h("td", "num", tr, s.value);
    h("td", "num", tr, s.target);
    const td = h("td", "", tr);
    if (s.status_text) h("span", "chip " + (s.status === "on_target" ? "ok" : "off"), td,
      (s.status === "on_target" ? "✓ " : s.status === "above" ? "▲ " : "▼ ") + s.status_text);
  }
}

function flagList(parent, items) {
  const ul = h("ul", "flags", parent);
  const icon = { good: "✓", info: "•", warning: "!" };
  if (!items.length) h("li", "muted", ul, "Nothing to flag.");
  for (const f of items) {
    const li = h("li", "", ul);
    const s = h("span", "sev " + f.severity, li, icon[f.severity]); s.setAttribute("aria-label", f.severity);
    h("span", "", li, f.message);
  }
}

function barRows(parent, rows) {
  const box = h("div", "bars", parent);
  for (const [name, value, target, cls] of rows) {
    const row = h("div", "bar-row", box);
    h("span", "name", row, name);
    const track = h("div", "bar-track", row);
    if (target) {
      const t = h("div", "target", track);
      t.style.left = target[0] * 100 + "%"; t.style.width = (target[1] - target[0]) * 100 + "%";
      t.title = "target " + Math.round(target[0] * 100) + "–" + Math.round(target[1] * 100) + "%";
    }
    const f = h("div", "fill " + cls, track);
    f.style.width = (isNum(value) ? value * 100 : 0) + "%";
    h("span", "val", row, pct(value));
  }
  h("p", "muted small", parent, "Shaded = native American target range.");
}

/* plays one phrase of the recording at a time */
function phrasePlayer(audio) {
  const p = { audio, chips: [], marks: [], current: -1, stopAt: null, ends: [] };
  const mark = i => {
    p.chips.forEach((c, j) => c && c.classList.toggle("playing", j === i));
    p.marks.forEach((m, j) => m && m.classList.toggle("playing", j === i));
  };
  audio.addEventListener("timeupdate", () => {
    if (p.stopAt != null && audio.currentTime >= p.stopAt) { audio.pause(); p.stopAt = null; }
    if (p.onTime) p.onTime(audio.currentTime);
  });
  audio.addEventListener("pause", () => { p.current = -1; mark(-1); });
  p.play = i => {
    const e = p.ends[i];
    p.current = i; mark(i);
    audio.currentTime = e.play_from; p.stopAt = e.play_to;
    audio.play().catch(() => {});
  };
  return p;
}

function contourChart(box, r, player) {
  box.replaceChildren();
  const W = box.clientWidth, H = 290, m = { t: 10, r: 14, b: 28, l: 44 };
  const pw = W - m.l - m.r, ph = H - m.t - m.b;
  const c = r.contour;
  const svg = el("svg", { width: W, height: H, role: "img", "aria-label": "Pitch over time with phrase endings" }, box);
  if (!c.t.length) { el("text", { x: W / 2, y: H / 2, "text-anchor": "middle" }, svg, "No voiced speech detected"); return; }
  const dur = Math.max(r.duration || c.t[c.t.length - 1], 1);
  const lo = Math.min(...c.f0, c.low || Infinity) * 0.9, hi = Math.max(...c.f0, c.high || 0) * 1.06;
  const x = t => m.l + (t / dur) * pw;
  const y = f => m.t + ph * (1 - (f - lo) / (hi - lo));
  if (c.high) el("rect", { class: "band", x: m.l, y: y(hi), width: pw, height: Math.max(0, y(c.high) - y(hi)) }, svg);
  const step = (hi - lo) > 200 ? 100 : 50;
  for (let f = Math.ceil(lo / step) * step; f <= hi; f += step) {
    el("line", { class: "gridline", x1: m.l, x2: m.l + pw, y1: y(f), y2: y(f) }, svg);
    el("text", { x: m.l - 6, y: y(f) + 4, "text-anchor": "end" }, svg, f + (f + step > hi ? " Hz" : ""));
  }
  el("line", { class: "baseline", x1: m.l, x2: m.l + pw, y1: m.t + ph, y2: m.t + ph }, svg);
  const tstep = [1, 2, 5, 10, 15, 30, 60, 120].find(s => dur / s <= Math.max(2, pw / 70)) || 300;
  for (let t = 0; t <= dur; t += tstep) el("text", { x: x(t), y: H - 8, "text-anchor": "middle" }, svg, t + "s");
  if (c.mean) {
    el("line", { class: "meanline", x1: m.l, x2: m.l + pw, y1: y(c.mean), y2: y(c.mean) }, svg);
    el("text", { class: "lbl", x: m.l + pw - 2, y: y(c.mean) - 5, "text-anchor": "end" }, svg, "your mean " + Math.round(c.mean) + " Hz");
  }
  if (c.high) el("text", { x: m.l + 6, y: y(c.high) - 5 }, svg, "high-onset zone");
  // one path of tiny squares is far lighter than thousands of circles
  let d = "";
  for (let i = 0; i < c.t.length; i++) d += `M${x(c.t[i]).toFixed(1)},${y(c.f0[i]).toFixed(1)}h1.6v1.6h-1.6z`;
  el("path", { class: "f0dot", d }, svg);
  const head = el("line", { class: "playhead", y1: m.t, y2: m.t + ph, visibility: "hidden" }, svg);
  player.onTime = t => {
    head.setAttribute("x1", x(t)); head.setAttribute("x2", x(t));
    head.setAttribute("visibility", player.audio.paused ? "hidden" : "visible");
  };
  player.ends = r.ends;
  player.marks = [];
  r.ends.forEach((e, i) => {
    const cx = x(e.time), cy = y(e.end_hz);
    const g = el("g", { tabindex: 0, role: "button", "aria-label": `Play phrase at ${e.time.toFixed(1)} seconds, ${e.direction}` }, svg);
    el("circle", { cx, cy, r: 13, fill: "transparent" }, g);  // generous hit area
    const pts = e.direction === "rising" ? [[cx, cy - 7], [cx - 6.5, cy + 5], [cx + 6.5, cy + 5]]
      : e.direction === "falling" ? [[cx, cy + 7], [cx - 6.5, cy - 5], [cx + 6.5, cy - 5]]
      : [[cx - 5, cy - 5], [cx + 5, cy - 5], [cx + 5, cy + 5], [cx - 5, cy + 5]];
    player.marks[i] = el("polygon", { class: "endmark " + e.direction, points: pts.map(p => p.join(",")).join(" ") }, g);
    const sign = e.delta > 0 ? "+" : "";
    const tipOn = (px, py) => showTip(px, py, `${e.direction} ending at ${e.time.toFixed(1)}s`,
      `${sign}${Math.round(e.delta)} Hz (${Math.round(e.start_hz)} → ${Math.round(e.end_hz)})`, "Click to play");
    g.addEventListener("pointermove", ev => tipOn(ev.clientX, ev.clientY));
    g.addEventListener("pointerleave", hideTip);
    g.addEventListener("focus", () => { const b = g.getBoundingClientRect(); tipOn(b.left + b.width / 2, b.top); });
    g.addEventListener("blur", hideTip);
    g.addEventListener("click", () => player.play(i));
    g.addEventListener("keydown", ev => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); player.play(i); } });
  });
}

/* =====================================================================
   PROGRESS
   ===================================================================== */
async function viewProgress() {
  const app = state.app || await refreshState();
  if (!app.count) {
    view.className = "";
    const e = h("div", "empty", view);
    h("h1", "", e, "Progress");
    h("p", "", e, "Your trajectory appears here after your first recording.");
    const a = h("a", "btn primary", e, "Record a take"); a.href = "#record";
    return;
  }
  const f = h("iframe", "frame", view);
  f.title = "Progress dashboard";
  f.src = "/dashboard?ts=" + Date.now();
}

/* =====================================================================
   PRACTICE
   ===================================================================== */
async function viewPractice(focus) {
  const data = await api("/api/coaching");
  h("h1", "", view, "Practice");
  h("p", "lede", view, data.has_recordings
    ? "Recommended modules come first, based on your latest take. Open one, work through the drills, then record it."
    : "Record a take first and the modules that matter most for you will be marked. Meanwhile, browse everything.");
  const recById = Object.fromEntries(data.recommended.map(r => [r.id, r]));
  const order = [...data.recommended.map(r => r.id), ...data.modules.map(m => m.id).filter(id => !recById[id])];
  const byId = Object.fromEntries(data.modules.map(m => [m.id, m]));
  order.forEach((id, idx) => {
    const m = byId[id], rec = recById[id];
    const det = h("details", "module", view);
    det.id = "module-" + id;
    if (focus ? focus === id : idx === 0 && rec) det.open = true;
    const sum = h("summary", "", det);
    h("span", "title", sum, m.name);
    if (rec) h("span", "badge rec", sum, rec.reasons[0].startsWith("your ") ? "for your accent" : "recommended");
    if (m.detection === "planned") h("span", "badge plan", sum, "not measured yet");
    const body = h("div", "body", det);
    if (rec) h("p", "small", body, "Why for you: " + rec.reasons.join("; ") + (rec.provisional ? " (provisional: short recording)" : ""));
    h("p", "", body, m.description);
    const tgt = h("p", "", body); h("strong", "", tgt, "Target: "); tgt.append(m.target);
    h("div", "label", body, "Drills");
    const ol = h("ol", "drills", body);
    for (const d of m.drills) {
      const li = h("li", "", ol);
      h("strong", "", li, d.name);
      if (d.minutes) li.append(` · ${d.minutes} min`);
      const steps = h("ul", "steps", li);
      for (const s of d.steps) h("li", "", steps, s);
    }
    if (m.examples.length) {
      h("div", "label", body, "Practice sentences");
      const ul = h("ul", "sentences", body);
      for (const s of m.examples) h("li", "", ul, s);
    }
    if (m.words.length) {
      h("div", "label", body, "Key words");
      const w = h("div", "words", body);
      for (const s of m.words) h("span", "", w, s);
    }
    if (m.progress.length) {
      h("div", "label", body, "How you'll know it's working");
      const ul = h("ul", "sentences", body);
      const live = rec ? Object.fromEntries(rec.progress.filter(p => p.metric).map(p => [p.metric, p])) : {};
      for (const p of m.progress) {
        const cur = p.metric && live[p.metric];
        h("li", "", ul, p.text + (cur && cur.current ? ` — now ${cur.current}${cur.on_target ? " ✓" : ""}` : ""));
      }
    }
    const row = h("div", "row", body); row.style.marginTop = "14px";
    button("Record this drill", "primary", row, () => {
      state.drill = { id: m.id, name: m.name, examples: m.examples.length ? m.examples : m.words };
      state.promptMode = "drill";
      location.hash = "#record";
    });
  });
  if (focus) document.getElementById("module-" + focus)?.scrollIntoView({ block: "start" });
}

/* =====================================================================
   SETTINGS
   ===================================================================== */
async function viewSettings() {
  const app = await refreshState();
  const s = app.settings;
  h("h1", "", view, "Settings");
  h("p", "lede", view, "Changes save automatically and apply to new recordings.");
  const save = async patch => {
    try { await api("/api/settings", { method: "PUT", json: patch }); await refreshState(); toast("Saved"); }
    catch (err) { toast(err.message); }
  };
  const group = (title, hint, name, options, current, onPick) => {
    const card = h("section", "card", view);
    h("h2", "", card, title);
    if (hint) h("p", "muted small", card, hint);
    const box = h("div", "options", card);
    box.setAttribute("role", "radiogroup"); box.setAttribute("aria-label", title);
    for (const o of options) {
      const lab = h("label", "option", box);
      const inp = h("input", "", lab); inp.type = "radio"; inp.name = name; inp.value = o.id ?? "";
      inp.checked = (o.id ?? null) === (current ?? null);
      inp.addEventListener("change", () => onPick(o.id ?? null));
      const txt = h("span", "", lab);
      h("div", "", txt, o.label);
      if (o.hint) h("div", "hint", txt, o.hint);
    }
  };
  group("Your English background", "Adds coaching for accent features the app can't measure from audio yet.",
    "accent", [...app.accents.map(a => ({ id: a.id, label: a.name })), { id: null, label: "Prefer not to say" }],
    s.accent, v => save({ accent: v }));
  group("Voice range", "Sets the pitch range the tracker searches. If the pitch chart shows stray dots at the top or bottom, try another range.",
    "voice", app.voices.map(v => ({ id: v.id, label: v.label, hint: `${v.f0_min}–${v.f0_max} Hz` })),
    s.voice, v => save({ voice: v }));
  group("Pitch tracker", null, "pitch_method", [
    { id: "autocorr", label: "Standard", hint: "Fast. Good for most voices." },
    { id: "yin", label: "Precise (pYIN)", hint: "Slower, fewer octave jumps. Try it if results look odd." },
  ], s.pitch_method, v => save({ pitch_method: v }));
  const info = h("section", "card", view);
  h("h2", "", info, "Where your data lives");
  h("p", "muted small", info, "Everything stays on this computer.");
  const dl = h("p", "small", info); dl.append("Recordings and settings: "); h("code", "", dl, app.data_dir);
  const hl = h("p", "small", info); hl.append("History database (shared with the command line): "); h("code", "", hl, app.history);
}

route();
