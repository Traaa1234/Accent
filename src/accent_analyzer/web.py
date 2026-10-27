"""Bridge for the browser version: the Flask app runs inside Pyodide (a Web Worker) and
the page's requests are passed in here instead of over the network.

The browser decodes every recording to 16 kHz mono WAV before it arrives, so no ffmpeg
is needed. Data lives in a folder the worker keeps in the browser's IndexedDB.
"""

from __future__ import annotations

import io
import json
import os
import zipfile
from pathlib import Path

BACKUP_PATH = "/backup"
RESTORE_PATH = "/restore"
_client = None


def _data_dir() -> Path:
    return Path(os.environ.get("ACCENT_DATA_DIR", "/data"))


def client():
    global _client
    if _client is None:
        from accent_analyzer.app import create_app

        _client = create_app(_data_dir()).test_client()
    return _client


def backup() -> bytes:
    """Everything in the data folder as one zip file."""
    buf = io.BytesIO()
    root = _data_dir()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(root.rglob("*")):
            if f.is_file():
                z.write(f, f.relative_to(root).as_posix())
    return buf.getvalue()


def restore(data: bytes) -> None:
    """Replace the data folder with the contents of a backup zip."""
    global _client
    root = _data_dir().resolve()
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise ValueError("That isn't an Accent Coach backup file.") from exc
    names = [n for n in z.namelist() if not n.endswith("/")]
    if "history.db" not in names:
        raise ValueError("That isn't an Accent Coach backup file (no history.db inside).")
    for n in names:
        if not (root / n).resolve().is_relative_to(root):
            raise ValueError("Unsafe path in backup file.")
    for f in sorted(root.rglob("*"), reverse=True):
        f.unlink() if f.is_file() else f.rmdir()
    z.extractall(root)
    _client = None


def handle(method: str, path: str, json_body=None, fields: dict | None = None,
           files: dict | None = None) -> dict:
    """Run one request through the Flask app. `files` maps a form field to
    (filename, bytes). Returns {status, type, body: bytes}."""
    try:
        if path == BACKUP_PATH:
            return {"status": 200, "type": "application/zip", "body": backup()}
        if path == RESTORE_PATH:
            restore(next(iter((files or {}).values()))[1])
            return _json(200, {"restored": True})
    except (ValueError, StopIteration) as exc:
        return _json(400, {"error": str(exc) or "No file received."})
    kwargs = {"headers": {"X-Accent-App": "1"}}
    if json_body is not None:
        kwargs["json"] = json_body
    elif fields or files:
        data = dict(fields or {})
        for name, (filename, content) in (files or {}).items():
            data[name] = (io.BytesIO(bytes(content)), filename, "audio/wav")
        kwargs["data"] = data
        kwargs["content_type"] = "multipart/form-data"
    resp = client().open(path, method=method, **kwargs)
    try:
        return {"status": resp.status_code, "type": resp.headers.get("Content-Type", ""), "body": resp.get_data()}
    finally:
        resp.close()


def _json(status: int, data: dict) -> dict:
    return {"status": status, "type": "application/json", "body": json.dumps(data).encode()}
