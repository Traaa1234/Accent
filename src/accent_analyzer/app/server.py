"""Local web app: record, analyze, review progress and practice, in the browser.

Runs on 127.0.0.1 only. Recordings, analyses and settings live in a data folder
(default ~/.accent_analyzer); the history database is shared with the CLI.
"""

from __future__ import annotations

import io
import json
import os
import shutil
import tomllib
import uuid
from datetime import datetime
from urllib.parse import urlsplit
from importlib import resources
from pathlib import Path

from flask import Flask, Response, abort, jsonify, request, send_file

from accent_analyzer.analysis.audio import SUPPORTED_EXTENSIONS, AudioLoadError
from accent_analyzer.analysis.pipeline import analyze_file
from accent_analyzer.app.payload import metrics_only_payload, result_payload
from accent_analyzer.coaching import ACCENTS, load_library, recommend
from accent_analyzer.coaching.library import ACCENT_NAMES
from accent_analyzer.dashboard import dashboard_data, render_dashboard
from accent_analyzer.history import HistoryStore, progression
from accent_analyzer.reports import build_pdf, render_html

DEFAULT_DATA_DIR = Path("~/.accent_analyzer")
MIN_SECONDS = 3.0
MAX_UPLOAD_MB = 200
VOICE_RANGES = {
    "low": {"label": "Low voice", "f0_min": 60.0, "f0_max": 250.0},
    "medium": {"label": "Medium voice", "f0_min": 80.0, "f0_max": 320.0},
    "high": {"label": "High voice", "f0_min": 120.0, "f0_max": 400.0},
}
DEFAULT_SETTINGS = {"accent": None, "voice": "medium", "pitch_method": "autocorr"}
MIME_EXT = {
    "audio/webm": ".webm", "audio/ogg": ".ogg", "audio/mp4": ".mp4", "audio/x-m4a": ".m4a",
    "audio/aac": ".aac", "audio/mpeg": ".mp3", "audio/wav": ".wav", "audio/x-wav": ".wav",
    "audio/wave": ".wav", "audio/flac": ".flac", "video/webm": ".webm",
}
AUDIO_MIME = {".webm": "audio/webm", ".ogg": "audio/ogg", ".mp4": "audio/mp4", ".m4a": "audio/mp4",
              ".aac": "audio/aac", ".mp3": "audio/mpeg", ".wav": "audio/wav", ".flac": "audio/flac"}
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
APP_HEADER = "X-Accent-App"


class Paths:
    def __init__(self, data_dir: Path, history: Path):
        self.data = data_dir
        self.history = history
        self.recordings = data_dir / "recordings"
        self.analyses = data_dir / "analyses"
        self.settings = data_dir / "settings.json"
        for d in (self.data, self.recordings, self.analyses):
            d.mkdir(parents=True, exist_ok=True)

    def audio_for(self, record_id: int) -> Path | None:
        found = sorted(self.recordings.glob(f"{record_id}.*"))
        return found[0] if found else None

    def analysis_for(self, record_id: int) -> Path:
        return self.analyses / f"{record_id}.json"


def _ext_for(upload) -> str | None:
    name_ext = Path(upload.filename or "").suffix.lower()
    if name_ext in SUPPORTED_EXTENSIONS:
        return name_ext
    mime = (upload.mimetype or "").split(";")[0].strip().lower()
    return MIME_EXT.get(mime)


def create_app(data_dir: str | Path | None = None, history_path: str | Path | None = None) -> Flask:
    data_dir = Path(data_dir or DEFAULT_DATA_DIR).expanduser()
    history = Path(history_path or os.environ.get("ACCENT_HISTORY") or data_dir / "history.db").expanduser()
    paths = Paths(data_dir, history)
    static = resources.files("accent_analyzer.app").joinpath("static")
    app = Flask(__name__, static_folder=str(static), static_url_path="/static")
    app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_MB * 1024 * 1024
    app.config["PATHS"] = paths

    # ---- helpers -----------------------------------------------------------------
    def store() -> HistoryStore:
        return HistoryStore(paths.history)

    def load_settings() -> dict:
        try:
            saved = json.loads(paths.settings.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            saved = {}
        settings = {**DEFAULT_SETTINGS, **{k: v for k, v in saved.items() if k in DEFAULT_SETTINGS}}
        if settings["voice"] not in VOICE_RANGES:
            settings["voice"] = "medium"
        return settings

    def history_rows(records) -> list[dict]:
        return [{"label": r.label, **{k: r.get(k) for k in r.metrics}} for r in records[-10:]]

    def analyze_saved(audio: Path, settings: dict, source: str):
        voice = VOICE_RANGES[settings["voice"]]
        result = analyze_file(audio, pitch_method=settings["pitch_method"],
                              f0_min=voice["f0_min"], f0_max=voice["f0_max"])
        result.source = source
        return result

    def reanalyze(record, audio: Path):
        """Re-run a stored recording with the pitch settings it was analyzed with, so
        changing Settings later never rewrites past results."""
        params = record.details.get("pitch_params") or {}
        result = analyze_file(
            audio, pitch_method=record.pitch_method or "autocorr",
            f0_min=params.get("f0_min", VOICE_RANGES["medium"]["f0_min"]),
            f0_max=params.get("f0_max", VOICE_RANGES["medium"]["f0_max"]),
        )
        result.source = record.source or audio.name
        return result

    def upto(records, record_id: int):
        """The time-ordered history up to and including this recording."""
        idx = next((i for i, r in enumerate(records) if r.id == record_id), None)
        if idx is None:
            abort(404)
        return records[idx], records[: idx + 1]

    def context_for(record_id: int):
        with store() as st:
            records = st.all()
        return upto(records, record_id)

    def build_payload(record, before) -> dict:
        progress = progression(before)
        audio = paths.audio_for(record.id)
        source = Path(record.source).expanduser() if record.source else None
        target = audio or (source if source and source.is_file() else None)
        if target is None:
            return metrics_only_payload(record, progress)
        result = reanalyze(record, target)
        payload = result_payload(result, record, progress, history_rows(before))
        payload["has_audio"] = audio is not None
        return payload

    # ---- security: local origin only, and a custom header on anything that writes --
    @app.before_request
    def guard():
        if urlsplit("//" + request.host).hostname not in LOCAL_HOSTS:
            abort(403)
        if request.method not in ("GET", "HEAD", "OPTIONS") and request.headers.get(APP_HEADER) != "1":
            abort(403)

    @app.errorhandler(413)
    def too_big(_):
        return jsonify(error=f"That file is larger than {MAX_UPLOAD_MB} MB."), 413

    # ---- pages -------------------------------------------------------------------
    @app.get("/")
    def index():
        return app.send_static_file("index.html")

    @app.get("/dashboard")
    def dashboard():
        with store() as st:
            records = st.all()
        return Response(render_dashboard(records), mimetype="text/html")

    # ---- api ---------------------------------------------------------------------
    @app.get("/api/state")
    def state():
        with store() as st:
            records = st.all()
        return jsonify(
            settings=load_settings(),
            count=len(records),
            latest_id=records[-1].id if records else None,
            accents=[{"id": a, "name": "Other" if a == "other" else ACCENT_NAMES[a]} for a in ACCENTS],
            voices=[{"id": k, **v} for k, v in VOICE_RANGES.items()],
            data_dir=str(paths.data),
            history=str(paths.history),
        )

    @app.route("/api/settings", methods=["GET", "PUT"])
    def settings_route():
        settings = load_settings()
        if request.method == "PUT":
            body = request.get_json(silent=True) or {}
            if "accent" in body:
                if body["accent"] not in (*ACCENTS, None):
                    return jsonify(error="Unknown accent"), 400
                settings["accent"] = body["accent"]
            if "voice" in body:
                if body["voice"] not in VOICE_RANGES:
                    return jsonify(error="Unknown voice range"), 400
                settings["voice"] = body["voice"]
            if "pitch_method" in body:
                if body["pitch_method"] not in ("autocorr", "yin"):
                    return jsonify(error="Unknown pitch method"), 400
                settings["pitch_method"] = body["pitch_method"]
            paths.settings.write_text(json.dumps(settings, indent=2), encoding="utf-8")
        return jsonify(settings)

    @app.get("/api/prompts")
    def prompts():
        text = resources.files("accent_analyzer.app").joinpath("prompts.toml").read_text(encoding="utf-8")
        data = tomllib.loads(text)
        return jsonify(
            passages=[{**p, "text": " ".join(p["text"].split())} for p in data["passage"]],
            topics=data["topics"]["prompts"],
        )

    @app.post("/api/recordings")
    def create_recording():
        upload = request.files.get("audio")
        if upload is None:
            return jsonify(error="No audio received."), 400
        ext = _ext_for(upload)
        if ext is None:
            return jsonify(error="Unsupported audio format. Use m4a, mp3, wav, flac, webm, ogg or mp4."), 400
        tmp = paths.recordings / f"incoming-{uuid.uuid4().hex}{ext}"
        upload.save(tmp)
        settings = load_settings()
        name = (request.form.get("name") or "").strip()[:80] or None
        display_source = Path(upload.filename or f"recording{ext}").name
        try:
            result = analyze_saved(tmp, settings, display_source)
        except (AudioLoadError, ValueError) as exc:
            tmp.unlink(missing_ok=True)
            return jsonify(error=f"Couldn't read that audio: {exc}"), 400
        if result.duration < MIN_SECONDS:
            tmp.unlink(missing_ok=True)
            return jsonify(error="That recording is under 3 seconds. Aim for 60 seconds or more."), 400
        if result.register.n_voiced == 0:
            tmp.unlink(missing_ok=True)
            return jsonify(error="No voice detected. Check your microphone and try again."), 400

        with store() as st:
            record = st.add(result, name=name, accent=settings["accent"], recorded_at=datetime.now())
            record, before = upto(st.all(), record.id)
        shutil.move(tmp, paths.recordings / f"{record.id}{ext}")
        payload = result_payload(result, record, progression(before), history_rows(before))
        payload["has_audio"] = True
        paths.analysis_for(record.id).write_text(json.dumps(payload), encoding="utf-8")
        return jsonify(payload), 201

    @app.get("/api/recordings")
    def list_recordings():
        with store() as st:
            records = st.all()
        data = dashboard_data(records)
        for row in data["records"]:
            row["has_audio"] = paths.audio_for(row["id"]) is not None
        return jsonify(data)

    @app.get("/api/recordings/<int:record_id>")
    def get_recording(record_id: int):
        cached = paths.analysis_for(record_id)
        if cached.is_file():
            return Response(cached.read_text(encoding="utf-8"), mimetype="application/json")
        record, before = context_for(record_id)
        payload = build_payload(record, before)
        if not payload.get("metrics_only"):
            cached.write_text(json.dumps(payload), encoding="utf-8")
        return jsonify(payload)

    @app.get("/api/recordings/<int:record_id>/audio")
    def get_audio(record_id: int):
        audio = paths.audio_for(record_id)
        if audio is None:
            abort(404)
        return send_file(audio, mimetype=AUDIO_MIME.get(audio.suffix, "application/octet-stream"),
                         conditional=True)

    @app.get("/api/recordings/<int:record_id>/report.<fmt>")
    def get_report(record_id: int, fmt: str):
        if fmt not in ("html", "pdf"):
            abort(404)
        record, before = context_for(record_id)
        audio = paths.audio_for(record_id)
        if audio is None:
            return jsonify(error="The app doesn't have this recording's audio."), 404
        result = reanalyze(record, audio)
        rows = history_rows(before)
        kwargs = {
            "title": record.label,
            "history": rows,
            "progress": progression(before),
            "recommendations": [r.to_report_dict() for r in recommend(result.metrics(), accent=record.accent, history=rows)],
        }
        if fmt == "html":
            return Response(render_html(result, **kwargs), mimetype="text/html")
        filename = f"accent-report-{record.recorded_at:%Y-%m-%d}-{record.id}.pdf"
        return send_file(io.BytesIO(build_pdf(result, **kwargs)), mimetype="application/pdf",
                         as_attachment=True, download_name=filename)

    @app.delete("/api/recordings/<int:record_id>")
    def delete_recording(record_id: int):
        with store() as st:
            if not st.delete(record_id):
                abort(404)
        audio = paths.audio_for(record_id)
        if audio:
            audio.unlink(missing_ok=True)
        paths.analysis_for(record_id).unlink(missing_ok=True)
        # Cached results of later recordings embed progress flags that may have changed.
        for f in paths.analyses.glob("*.json"):
            if f.stem.isdigit() and int(f.stem) > record_id:
                f.unlink(missing_ok=True)
        return jsonify(deleted=record_id)

    @app.get("/api/coaching")
    def coaching():
        settings = load_settings()
        with store() as st:
            records = st.all()
        recommended = []
        if records:
            latest = records[-1]
            recs = recommend({k: latest.get(k) for k in latest.metrics}, accent=settings["accent"],
                             limit=None, history=history_rows(records))
            recommended = [{"id": r.module.id, "reasons": list(r.reasons), "provisional": r.provisional,
                            "progress": list(r.progress)} for r in recs]
        modules = []
        for m in load_library().values():
            modules.append({
                "id": m.id, "name": m.name, "detection": m.detection, "description": m.description,
                "target": m.target, "examples": list(m.examples), "words": list(m.words),
                "drills": [{"name": d.name, "minutes": d.minutes, "steps": list(d.steps)} for d in m.drills],
                "progress": [{"text": p.text, "metric": p.metric} for p in m.progress],
            })
        return jsonify(modules=modules, recommended=recommended, has_recordings=bool(records))

    return app
