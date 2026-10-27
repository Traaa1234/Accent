"use strict";
/* Runs the Python app (accent_analyzer + Flask) in Pyodide, off the page's main thread.
   Data lives in /data, which is stored in this browser's IndexedDB. */

const params = new URLSearchParams(self.location.search);
const PYODIDE = params.get("pyodide");
const BUNDLE = params.get("bundle");
let py = null;

const say = text => self.postMessage({ type: "progress", text });

function syncfs(populate) {
  return new Promise((resolve, reject) => py.FS.syncfs(populate, err => (err ? reject(err) : resolve())));
}

const ready = (async () => {
  say("Starting Python…");
  importScripts(PYODIDE + "pyodide.js");
  py = await loadPyodide({ indexURL: PYODIDE });
  say("Downloading the maths libraries (first visit only)…");
  await py.loadPackage(["numpy", "scipy", "sqlite3"]);
  say("Loading your saved data…");
  py.FS.mkdirTree("/data");
  py.FS.mount(py.FS.filesystems.IDBFS, {}, "/data");
  await syncfs(true);
  say("Loading Accent Coach…");
  const zip = await (await fetch(BUNDLE)).arrayBuffer();
  py.unpackArchive(zip, "zip", { extractDir: "/app" });
  py.runPython(`
import os, sys
sys.path.insert(0, "/app")
os.environ["ACCENT_DATA_DIR"] = "/data"
from accent_analyzer import web
web.client()
`);
  return py.pyimport("accent_analyzer.web");
})();
ready.catch(err => {
  console.error(err);
  const last = String(err && err.message || err).trim().split("\n").pop();
  self.postMessage({ type: "fatal", error: last });
});
ready.then(() => self.postMessage({ type: "ready" }));

let queue = Promise.resolve();
self.onmessage = e => {
  // One request at a time: the Python side and the IndexedDB sync aren't re-entrant.
  queue = queue.then(() => run(e.data));
};

async function run({ id, method, path, json, fields, files }) {
  try {
    const web = await ready;
    const toPy = v => (v == null ? null : py.toPy(v));
    const filesPy = files ? py.toPy(Object.fromEntries(
      Object.entries(files).map(([k, f]) => [k, [f.name, new Uint8Array(f.data)]]))) : null;
    const out = web.handle(method, path, toPy(json), toPy(fields), filesPy);
    const res = out.toJs({ dict_converter: Object.fromEntries });
    out.destroy();
    const body = res.body instanceof Uint8Array ? res.body.slice() : new Uint8Array(0);
    if (method !== "GET") await syncfs(false);
    self.postMessage({ type: "response", id, status: res.status, contentType: res.type, body }, [body.buffer]);
  } catch (err) {
    const msg = String(err && err.message || err).split("\n").filter(Boolean).pop();
    const body = new TextEncoder().encode(JSON.stringify({ error: "Something went wrong: " + msg }));
    self.postMessage({ type: "response", id, status: 500, contentType: "application/json", body }, [body.buffer]);
  }
}
