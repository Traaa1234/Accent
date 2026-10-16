"""Start the local web server, and create a double-click desktop shortcut."""

from __future__ import annotations

import json
import os
import shutil
import socket
import sys
import threading
import urllib.request
import webbrowser
from pathlib import Path

from werkzeug.serving import make_server

HOST = "127.0.0.1"
DEFAULT_PORT = 8765


def port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind((HOST, port))
        except OSError:
            return False
    return True


def running_instance(port: int) -> bool:
    """True if Accent Coach is already answering on this port."""
    try:
        with urllib.request.urlopen(f"http://{HOST}:{port}/api/state", timeout=1.5) as resp:
            return "accents" in json.loads(resp.read().decode("utf-8"))
    except (OSError, ValueError):
        return False


def find_free_server(app, port: int, attempts: int = 10):
    # werkzeug's make_server calls sys.exit() on a busy port, so check first.
    for p in range(port, port + attempts):
        if port_free(p):
            return make_server(HOST, p, app, threaded=True), p
    raise OSError(f"No free port between {port} and {port + attempts - 1}")


def serve(app, port: int = DEFAULT_PORT, open_browser: bool = True, echo=print) -> None:
    if not port_free(port) and running_instance(port):
        url = f"http://localhost:{port}/"
        echo(f"Accent Coach is already running at {url}; opening it.")
        if open_browser:
            webbrowser.open(url)
        return
    server, port = find_free_server(app, port)
    url = f"http://localhost:{port}/"
    echo(f"Accent Coach is running at {url}")
    echo("Keep this window open while you use the app. Close it (or press Ctrl+C) to stop.")
    if open_browser:
        threading.Timer(0.6, webbrowser.open, args=(url,)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        echo("Stopped.")
    finally:
        server.server_close()


def desktop_dir() -> Path:
    home = Path.home()
    candidates = [home / "OneDrive" / "Desktop", home / "Desktop"] if os.name == "nt" else [home / "Desktop"]
    for c in candidates:
        if c.is_dir():
            return c
    return home


def executable() -> str:
    found = shutil.which("accent-analyzer")
    if found:
        return found
    argv0 = Path(sys.argv[0])
    return str(argv0.resolve()) if argv0.exists() else "accent-analyzer"


def install_shortcut(directory: Path | None = None, exe: str | None = None) -> Path:
    """Write a double-clickable launcher that runs `accent-analyzer app`."""
    directory = directory or desktop_dir()
    exe = exe or executable()
    if os.name == "nt":
        path = directory / "Accent Coach.cmd"
        path.write_text(f'@echo off\r\ntitle Accent Coach\r\n"{exe}" app\r\n', encoding="utf-8")
    else:
        suffix = ".command" if sys.platform == "darwin" else ".sh"
        path = directory / f"Accent Coach{suffix}"
        path.write_text(f'#!/bin/sh\nexec "{exe}" app\n', encoding="utf-8")
        path.chmod(0o755)
    return path
