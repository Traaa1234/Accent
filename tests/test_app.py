import io
import json
import os
import socket
import subprocess
import threading

import numpy as np
import pytest
import soundfile as sf

from accent_analyzer.app import create_app
from accent_analyzer.app.launcher import find_free_server, install_shortcut, running_instance, serve
from accent_analyzer.history import HistoryStore
import synth

H = {"X-Accent-App": "1"}


def wav_bytes(audio) -> bytes:
    buf = io.BytesIO()
    sf.write(buf, audio, synth.SR, format="WAV")
    return buf.getvalue()


@pytest.fixture(scope="module")
def nze_wav():
    return wav_bytes(synth.nze_like())


@pytest.fixture
def app(tmp_path):
    return create_app(tmp_path / "data", tmp_path / "history.db")


@pytest.fixture
def client(app):
    return app.test_client()


def upload(client, data: bytes, filename="take.wav", name="", mimetype=None):
    return client.post(
        "/api/recordings", headers=H,
        data={"audio": (io.BytesIO(data), filename, mimetype) if mimetype else (io.BytesIO(data), filename),
              "name": name},
        content_type="multipart/form-data",
    )


# --- pages & guards ---------------------------------------------------------------

def test_index_and_static(client):
    assert b"Accent Coach" in client.get("/").data
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/static/app.css").status_code == 200


def test_rejects_foreign_host(client):
    assert client.get("/api/state", headers={"Host": "evil.example"}).status_code == 403
    assert client.get("/api/state", headers={"Host": "127.0.0.1:8765"}).status_code == 200


def test_writes_need_app_header(client):
    assert client.put("/api/settings", json={"accent": "nze"}).status_code == 403
    assert client.post("/api/recordings").status_code == 403
    assert client.delete("/api/recordings/1").status_code == 403


# --- settings & content -------------------------------------------------------------

def test_state_defaults(client):
    s = client.get("/api/state").get_json()
    assert s["count"] == 0 and s["latest_id"] is None
    assert s["settings"] == {"accent": None, "voice": "medium", "pitch_method": "autocorr"}
    assert {a["id"] for a in s["accents"]} == {"nze", "aue", "british", "indian", "other"}
    assert next(a for a in s["accents"] if a["id"] == "other")["name"] == "Other"


def test_settings_validate_and_persist(app, client):
    assert client.put("/api/settings", headers=H, json={"accent": "klingon"}).status_code == 400
    assert client.put("/api/settings", headers=H, json={"voice": "falsetto"}).status_code == 400
    assert client.put("/api/settings", headers=H, json={"pitch_method": "crepe"}).status_code == 400
    r = client.put("/api/settings", headers=H, json={"accent": "nze", "voice": "low", "pitch_method": "yin"})
    assert r.get_json() == {"accent": "nze", "voice": "low", "pitch_method": "yin"}
    fresh = create_app(app.config["PATHS"].data, app.config["PATHS"].history).test_client()
    assert fresh.get("/api/settings").get_json()["voice"] == "low"


def test_prompts(client):
    p = client.get("/api/prompts").get_json()
    assert len(p["passages"]) == 4 and len(p["topics"]) == 10
    assert all(len(x["text"].split()) > 90 for x in p["passages"])  # ~1 minute of reading


# --- recording lifecycle ------------------------------------------------------------

def test_upload_analyze_and_fetch(app, client, nze_wav):
    client.put("/api/settings", headers=H, json={"accent": "nze"})
    r = upload(client, nze_wav, name="Monday")
    assert r.status_code == 201, r.get_json()
    p = r.get_json()
    assert p["label"] == "Monday" and p["accent"] == "nze" and p["has_audio"]
    assert p["metrics"]["hrt_rate"] >= 0.6
    assert len(p["ends"]) == p["phrasing"]["n_ends"] == 20
    assert all(e["play_from"] < e["time"] < e["play_to"] for e in p["ends"])
    assert len(p["contour"]["t"]) == len(p["contour"]["f0"]) > 1000
    assert p["recommendations"][0]["id"] == "hrt"
    paths = app.config["PATHS"]
    assert paths.audio_for(p["id"]).suffix == ".wav"
    assert paths.analysis_for(p["id"]).is_file()
    assert not list(paths.recordings.glob("incoming-*"))
    assert client.get(f"/api/recordings/{p['id']}").get_json()["metrics"] == p["metrics"]
    audio = client.get(f"/api/recordings/{p['id']}/audio")
    assert audio.status_code == 200 and audio.mimetype == "audio/wav"
    assert client.get("/api/state").get_json()["latest_id"] == p["id"]


def test_browser_formats_by_mimetype(client, tmp_path):
    wav = tmp_path / "in.wav"
    sf.write(wav, synth.short_clip(), synth.SR)
    webm = tmp_path / "in.webm"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav), "-c:a", "libopus", str(webm)], check=True)
    # MediaRecorder blobs may arrive without a useful file name.
    r = upload(client, webm.read_bytes(), filename="blob", mimetype="audio/webm;codecs=opus")
    assert r.status_code == 201, r.get_json()


@pytest.mark.parametrize("data,filename,message", [
    (b"hello", "notes.txt", "Unsupported"),
    (b"not really audio", "broken.m4a", "Couldn't read"),
])
def test_bad_uploads(client, data, filename, message):
    r = upload(client, data, filename=filename)
    assert r.status_code == 400 and message in r.get_json()["error"]


def test_too_short_and_silent(app, client):
    short = upload(client, wav_bytes(synth.harmonic_tone(150, 1.0)))
    assert short.status_code == 400 and "under 3 seconds" in short.get_json()["error"]
    silent = upload(client, wav_bytes(np.zeros(5 * synth.SR, dtype=np.float32)))
    assert silent.status_code == 400 and "No voice" in silent.get_json()["error"]
    assert not list(app.config["PATHS"].recordings.iterdir())  # nothing left behind


def test_reports(client, nze_wav):
    rid = upload(client, nze_wav).get_json()["id"]
    html = client.get(f"/api/recordings/{rid}/report.html")
    assert html.status_code == 200 and b"Coaching recommendations" in html.data
    pdf = client.get(f"/api/recordings/{rid}/report.pdf")
    assert pdf.data.startswith(b"%PDF") and "attachment" in pdf.headers["Content-Disposition"]
    assert client.get(f"/api/recordings/{rid}/report.docx").status_code == 404


def test_delete_and_cache_invalidation(app, client, nze_wav):
    a = upload(client, nze_wav).get_json()["id"]
    b = upload(client, nze_wav).get_json()["id"]
    paths = app.config["PATHS"]
    assert client.delete(f"/api/recordings/{a}", headers=H).status_code == 200
    assert paths.audio_for(a) is None and not paths.analysis_for(a).exists()
    assert not paths.analysis_for(b).exists()  # later cache dropped; progress may differ now
    assert client.get(f"/api/recordings/{b}").status_code == 200  # rebuilt on demand
    assert client.delete(f"/api/recordings/{a}", headers=H).status_code == 404
    assert client.get("/api/state").get_json()["count"] == 1


def test_changing_settings_never_rewrites_past_results(app, client, nze_wav):
    first = upload(client, nze_wav).get_json()
    client.put("/api/settings", headers=H, json={"voice": "high"})
    app.config["PATHS"].analysis_for(first["id"]).unlink()  # force re-analysis
    again = client.get(f"/api/recordings/{first['id']}").get_json()
    assert again["metrics"]["mean_f0"] == first["metrics"]["mean_f0"]
    assert again["metrics"]["hrt_rate"] == first["metrics"]["hrt_rate"]


def test_cli_recording_without_audio(app, client, nze):
    with HistoryStore(app.config["PATHS"].history) as store:
        rid = store.add(nze).id  # source "nze_like.wav" doesn't exist on disk
    p = client.get(f"/api/recordings/{rid}").get_json()
    assert p["metrics_only"] and p["metrics"]["hrt_rate"] is not None
    assert client.get(f"/api/recordings/{rid}/audio").status_code == 404
    assert client.get("/api/recordings/999").status_code == 404


def test_list_coaching_and_dashboard(client, nze_wav):
    client.put("/api/settings", headers=H, json={"accent": "nze"})
    upload(client, nze_wav)
    listing = client.get("/api/recordings").get_json()
    assert len(listing["records"]) == 1 and listing["records"][0]["has_audio"]
    c = client.get("/api/coaching").get_json()
    assert len(c["modules"]) == 9 and c["has_recordings"]
    assert [r["id"] for r in c["recommended"]][:3] == ["hrt", "onset", "range"]
    assert "tflap" in {r["id"] for r in c["recommended"]}
    assert b"Accent progress" in client.get("/dashboard").data


def test_upload_size_limit(app, client):
    app.config["MAX_CONTENT_LENGTH"] = 1000
    r = upload(client, b"x" * 5000)
    assert r.status_code == 413 and "larger than" in r.get_json()["error"]


# --- launcher -----------------------------------------------------------------------

def test_install_shortcut(tmp_path):
    path = install_shortcut(tmp_path, exe="/opt/bin/accent-analyzer")
    text = path.read_text()
    assert path.name.startswith("Accent Coach")
    assert '"/opt/bin/accent-analyzer" app' in text
    if os.name != "nt":
        assert os.access(path, os.X_OK)


def test_find_free_server_skips_busy_port(app):
    busy = socket.socket()
    busy.bind(("127.0.0.1", 0))
    busy.listen()
    port = busy.getsockname()[1]
    try:
        server, chosen = find_free_server(app, port)
        server.server_close()
        assert chosen != port
    finally:
        busy.close()


def test_second_launch_reuses_running_instance(app):
    server, port = find_free_server(app, 18765)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        assert running_instance(port)
        messages = []
        serve(app, port=port, open_browser=False, echo=messages.append)  # returns instead of blocking
        assert "already running" in messages[0]
    finally:
        server.shutdown()
        server.server_close()
    assert not running_instance(port)
