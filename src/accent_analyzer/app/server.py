"""Local web app: record, analyze, review progress and practice, in the browser.

Runs on 127.0.0.1 only. Recordings, analyses and settings live in a data folder
(default ~/.accent_analyzer); the history database is shared with the CLI.
"""

from __future__ import annotations

import io
import json
import os
import re
import shutil
import tomllib
import uuid
from datetime import date, datetime
from urllib.parse import urlsplit
from importlib import resources
from pathlib import Path

from flask import Flask, Response, abort, jsonify, request, send_file

from accent_analyzer.analysis.audio import SUPPORTED_EXTENSIONS, AudioLoadError
from accent_analyzer.analysis.compare import REFERENCE_F0, compare_takes, shadow
from accent_analyzer.analysis.pipeline import analyze_file
from accent_analyzer.app.payload import metrics_only_payload, result_payload
from accent_analyzer.coaching import ACCENTS, load_library, recommend
from accent_analyzer.coaching.library import ACCENT_NAMES
from accent_analyzer.coaching.routine import LEVELS, build_routine, passages as _passages, streak, weekly_summary
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
DEFAULT_SETTINGS = {"accent": None, "voice": "medium", "pitch_method": "autocorr", "level": "intermediate"}
KEEP_PRACTICE_FILES = 40
MIME_EXT = {
    "audio/webm": ".webm", "audio/ogg": ".ogg", "audio/mp4": ".mp4", "audio/x-m4a": ".m4a",
    "audio/aac": ".aac", "audio/mpeg": ".mp3", "audio/wav": ".wav", "audio/x-wav": ".wav",
    "audio/wave": ".wav", "audio/flac": ".flac", "video/webm": ".webm",
}
AUDIO_MIME = {".webm": "audio/webm", ".ogg": "audio/ogg", ".mp4": "audio/mp4", ".m4a": "audio/mp4",
              ".aac": "audio/aac", ".mp3": "audio/mpeg", ".wav": "audio/wav", ".flac": "audio/flac"}
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
APP_HEADER = "X-Accent-App"


def host_allowed(hostname: str | None, env=os.environ) -> bool:
    """Local addresses, plus this codespace's own forwarded address when running in
    GitHub Codespaces (e.g. "<codespace>-8765.app.github.dev"). Codespaces puts its
    own GitHub sign-in in front of that address; any other host is refused, which
    blocks DNS-rebinding attacks."""
    if hostname in LOCAL_HOSTS:
        return True
    name, domain = env.get("CODESPACE_NAME"), env.get("GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN")
    if hostname and name and domain:
        return re.fullmatch(rf"{re.escape(name)}-\d+\.{re.escape(domain)}", hostname) is not None
    return False


class Paths:
    def __init__(self, data_dir: Path, history: Path):
        self.data = data_dir
        self.history = history
        self.recordings = data_dir / "recordings"
        self.analyses = data_dir / "analyses"
        self.settings = data_dir / "settings.json"
        self.references = data_dir / "references"
        self.references_index = self.references / "index.json"
        self.practice = data_dir / "practice"
        for d in (self.data, self.recordings, self.analyses, self.references, self.practice):
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
    data_dir = Path(data_dir or os.environ.get("ACCENT_DATA_DIR") or DEFAULT_DATA_DIR).expanduser()
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
        if not host_allowed(urlsplit("//" + request.host).hostname):
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
            if "level" in body:
                if body["level"] not in LEVELS:
                    return jsonify(error="Unknown level"), 400
                settings["level"] = body["level"]
            if "pitch_method" in body:
                if body["pitch_method"] not in ("autocorr", "yin"):
                    return jsonify(error="Unknown pitch method"), 400
                settings["pitch_method"] = body["pitch_method"]
            paths.settings.write_text(json.dumps(settings, indent=2), encoding="utf-8")
        return jsonify(settings)

    @app.get("/api/prompts")
    def prompts():
        text = resources.files("accent_analyzer.coaching").joinpath("prompts.toml").read_text(encoding="utf-8")
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

    # ---- practice: references, shadowing, A/B, daily routine ------------------------
    def save_upload(field: str, folder: Path, stem: str | None = None) -> Path:
        upload = request.files.get(field)
        if upload is None:
            raise ValueError("No audio received.")
        ext = _ext_for(upload)
        if ext is None:
            raise ValueError("Unsupported audio format. Use m4a, mp3, wav, flac, webm, ogg or mp4.")
        path = folder / f"{stem or uuid.uuid4().hex}{ext}"
        upload.save(path)
        return path

    def analyze_practice(path: Path, f0: tuple[float, float] | None = None):
        settings = load_settings()
        voice = VOICE_RANGES[settings["voice"]]
        lo, hi = f0 or (voice["f0_min"], voice["f0_max"])
        result = analyze_file(path, pitch_method=settings["pitch_method"], f0_min=lo, f0_max=hi)
        if result.register.n_voiced == 0:
            raise ValueError("No voice detected in that recording.")
        return result

    def prune_practice() -> None:
        files = sorted(paths.practice.iterdir(), key=lambda f: f.stat().st_mtime, reverse=True)
        for f in files[KEEP_PRACTICE_FILES:]:
            f.unlink(missing_ok=True)

    def references() -> list[dict]:
        try:
            return json.loads(paths.references_index.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []

    def reference_file(ref_id: str) -> Path | None:
        if not re.fullmatch(r"[0-9a-f]{32}", ref_id):
            return None
        found = sorted(paths.references.glob(ref_id + ".*"))
        return found[0] if found else None

    @app.get("/api/references")
    def list_references():
        return jsonify(references())

    @app.post("/api/references")
    def add_reference():
        ref_id = uuid.uuid4().hex
        try:
            path = save_upload("audio", paths.references, ref_id)
            result = analyze_practice(path, REFERENCE_F0)
        except (ValueError, AudioLoadError) as exc:
            for f in paths.references.glob(ref_id + ".*"):
                f.unlink(missing_ok=True)
            return jsonify(error=str(exc)), 400
        name = (request.form.get("name") or "").strip()[:80] or Path(request.files["audio"].filename or "Reference").stem
        entry = {"id": ref_id, "name": name, "duration": round(result.duration, 1),
                 "added": datetime.now().isoformat(timespec="minutes"),
                 "warning": "Long clip: shadowing works best with 5-30 seconds." if result.duration > 45 else None}
        paths.references_index.write_text(json.dumps(references() + [entry], indent=2), encoding="utf-8")
        return jsonify(entry), 201

    @app.delete("/api/references/<ref_id>")
    def delete_reference(ref_id: str):
        path = reference_file(ref_id)
        if path is None:
            abort(404)
        path.unlink(missing_ok=True)
        paths.references_index.write_text(json.dumps([r for r in references() if r["id"] != ref_id], indent=2),
                                          encoding="utf-8")
        return jsonify(deleted=ref_id)

    @app.get("/api/references/<ref_id>/audio")
    def reference_audio(ref_id: str):
        path = reference_file(ref_id)
        if path is None:
            abort(404)
        return send_file(path, mimetype=AUDIO_MIME.get(path.suffix, "application/octet-stream"), conditional=True)

    @app.get("/api/practice/<name>")
    def practice_audio(name: str):
        if not re.fullmatch(r"[0-9a-f]{32}\.[a-z0-9]+", name):
            abort(404)
        path = paths.practice / name
        if not path.is_file():
            abort(404)
        return send_file(path, mimetype=AUDIO_MIME.get(path.suffix, "application/octet-stream"), conditional=True)

    @app.post("/api/shadow")
    def shadow_take():
        ref = reference_file(request.form.get("reference", ""))
        if ref is None:
            return jsonify(error="Pick a reference clip first."), 400
        try:
            take = save_upload("audio", paths.practice)
            result = shadow(analyze_practice(ref, REFERENCE_F0), analyze_practice(take))
        except (ValueError, AudioLoadError) as exc:
            return jsonify(error=str(exc)), 400
        prune_practice()
        return jsonify({**result.to_dict(), "take_audio": f"/api/practice/{take.name}"})

    @app.post("/api/ab")
    def ab_compare():
        try:
            a = save_upload("audio_a", paths.practice)
            b = save_upload("audio_b", paths.practice)
            result = compare_takes(analyze_practice(a), analyze_practice(b))
        except (ValueError, AudioLoadError) as exc:
            return jsonify(error=str(exc)), 400
        prune_practice()
        return jsonify({**result.to_dict(), "audio_a": f"/api/practice/{a.name}", "audio_b": f"/api/practice/{b.name}"})

    @app.get("/api/routine")
    def routine():
        settings = load_settings()
        level = request.args.get("level") or settings["level"]
        if level not in LEVELS:
            return jsonify(error="Unknown level"), 400
        today = date.today()
        with store() as st:
            records, days = st.all(), st.drill_days()
        latest = records[-1] if records else None
        metrics = {k: latest.get(k) for k in latest.metrics} if latest else None
        data = build_routine(today, level, metrics, settings["accent"])
        passage_ids = [p["id"] for p in _passages()]
        rec_step = next(s for s in data["steps"] if s["id"] == "record")
        rec_step["passage_index"] = passage_ids.index(rec_step["passage"])
        return jsonify(routine=data, week=weekly_summary(records, days, today), done_today=today in days)

    @app.post("/api/routine/done")
    def routine_done():
        body = request.get_json(silent=True) or {}
        rid = body.get("recording_id")
        with store() as st:
            st.log_drill(date.today(), level=load_settings()["level"], minutes=5,
                         recording_id=rid if isinstance(rid, int) else None)
            days = st.drill_days()
        return jsonify(done=True, streak=streak(days))

    return app
