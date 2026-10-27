"""Build the browser-only version of Accent Coach (a static site for GitHub Pages).

    uv run python scripts/build_web.py [OUT_DIR] [--pyodide-url URL]

The page is the app's own front end; platform.js answers its /api/... requests with
the same Python code running in the browser (Pyodide), so the site needs no server.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import importlib.util
import json
import shutil
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "src" / "accent_analyzer" / "app" / "static"
WEB = ROOT / "web"
# Pure-Python packages bundled from the local environment (numpy, scipy and sqlite3
# come from Pyodide's own builds).
VENDORED = ("flask", "werkzeug", "itsdangerous", "blinker", "jinja2", "markupsafe", "click")
SKIP_SUFFIXES = {".pyc", ".so", ".pyd"}


def package_dir(name: str) -> Path:
    spec = importlib.util.find_spec(name)
    if spec is None or not spec.submodule_search_locations:
        raise SystemExit(f"{name} isn't installed; run `uv sync` first")
    return Path(next(iter(spec.submodule_search_locations)))


def add_tree(z: zipfile.ZipFile, src: Path, arc_root: str, skip_dirs: set[str] = frozenset()) -> None:
    for f in sorted(src.rglob("*")):
        rel = f.relative_to(src)
        if not f.is_file() or f.suffix in SKIP_SUFFIXES or "__pycache__" in rel.parts:
            continue
        if rel.parts and rel.parts[0] in skip_dirs:
            continue
        z.write(f, f"{arc_root}/{rel.as_posix()}")


def build(out: Path, pyodide_url: str | None = None) -> Path:
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    bundle = out / "accent_analyzer.zip"
    with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED) as z:
        pkg = ROOT / "src" / "accent_analyzer"
        add_tree(z, pkg, "accent_analyzer")
        for name in VENDORED:
            add_tree(z, package_dir(name), name)
            # Metadata too: Flask's test client asks importlib.metadata for versions.
            info = Path(importlib.metadata.distribution(name)._path)
            add_tree(z, info, info.name)
    version = hashlib.sha256(bundle.read_bytes()).hexdigest()[:10]

    for name in ("app.css", "app.js"):
        shutil.copy2(STATIC / name, out / name)
    for name in ("platform.js", "worker.js"):
        shutil.copy2(WEB / name, out / name)

    config = {"bundle": f"accent_analyzer.zip?v={version}"}
    if pyodide_url:
        config["pyodide"] = pyodide_url
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    html = html.replace('href="/static/app.css"', f'href="app.css?v={version}"')
    html = html.replace(
        '<script src="/static/app.js"></script>',
        f"<script>window.ACCENT_WEB = {json.dumps(config)};</script>\n"
        f'<script src="platform.js?v={version}"></script>\n'
        f'<script src="app.js?v={version}"></script>',
    )
    if "platform.js" not in html:
        raise SystemExit("index.html changed: couldn't find the app.js script tag")
    (out / "index.html").write_text(html, encoding="utf-8")
    (out / ".nojekyll").write_text("", encoding="utf-8")  # serve files as-is on GitHub Pages
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("out", nargs="?", default="site", type=Path)
    parser.add_argument("--pyodide-url", help="Pyodide 0.27.x 'full' folder URL (default: jsDelivr CDN)")
    args = parser.parse_args()
    out = build(args.out, args.pyodide_url)
    size = sum(f.stat().st_size for f in out.rglob("*") if f.is_file())
    print(f"Built {out} ({size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
