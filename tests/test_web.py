"""The browser bridge: Flask requests passed in-process, WAV-only audio, backup/restore."""

import io
import json
import wave
import zipfile

import numpy as np
import pytest

from accent_analyzer import web
from synth import nze_like


def _wav_bytes(samples, sr=16_000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
        w.writeframes((np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes())
    return buf.getvalue()


@pytest.fixture
def bridge(tmp_path, monkeypatch):
    monkeypatch.setenv("ACCENT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("ACCENT_HISTORY", raising=False)
    monkeypatch.setattr(web, "_client", None)
    return web


def _json(resp):
    return json.loads(bytes(resp["body"]))


def test_record_list_backup_restore(bridge):
    samples, sr = nze_like(), 16_000
    assert _json(bridge.handle("GET", "/api/state"))["count"] == 0
    resp = bridge.handle("POST", "/api/recordings", fields={"name": "First"},
                         files={"audio": ("recording.wav", _wav_bytes(samples, sr))})
    assert resp["status"] == 201, resp
    rid = _json(resp)["id"]
    assert _json(bridge.handle("GET", "/api/state"))["count"] == 1
    audio = bridge.handle("GET", f"/api/recordings/{rid}/audio")
    assert audio["status"] == 200 and bytes(audio["body"][:4]) == b"RIFF"

    zipped = bridge.handle("GET", web.BACKUP_PATH)["body"]
    assert "history.db" in zipfile.ZipFile(io.BytesIO(zipped)).namelist()
    assert bridge.handle("DELETE", f"/api/recordings/{rid}")["status"] == 200
    assert _json(bridge.handle("GET", "/api/state"))["count"] == 0
    assert bridge.handle("POST", web.RESTORE_PATH, files={"backup": ("b.zip", zipped)})["status"] == 200
    assert _json(bridge.handle("GET", "/api/state"))["count"] == 1


def test_settings_json_and_bad_restore(bridge):
    resp = bridge.handle("PUT", "/api/settings", json_body={"voice": "low"})
    assert _json(resp)["voice"] == "low"
    bad = bridge.handle("POST", web.RESTORE_PATH, files={"backup": ("x.zip", b"not a zip")})
    assert bad["status"] == 400 and "backup" in _json(bad)["error"]


def test_build_web_site(tmp_path):
    import importlib.util
    from pathlib import Path

    script = Path(__file__).resolve().parent.parent / "scripts" / "build_web.py"
    spec = importlib.util.spec_from_file_location("build_web", script)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    out = mod.build(tmp_path / "site")
    html = (out / "index.html").read_text()
    assert html.index("platform.js") < html.index("app.js") and "/static/" not in html
    names = zipfile.ZipFile(out / "accent_analyzer.zip").namelist()
    assert "accent_analyzer/web.py" in names and "flask/__init__.py" in names
    assert not any(n.endswith((".so", ".pyc")) for n in names)
    assert {"worker.js", "app.css", ".nojekyll"} <= {p.name for p in out.iterdir()}
