"""Settings shared by the local server and the browser version (no Flask here)."""

MIN_SECONDS = 3.0
VOICE_RANGES = {
    "low": {"label": "Low voice", "f0_min": 60.0, "f0_max": 250.0},
    "medium": {"label": "Medium voice", "f0_min": 80.0, "f0_max": 320.0},
    "high": {"label": "High voice", "f0_min": 120.0, "f0_max": 400.0},
}
DEFAULT_SETTINGS = {"accent": None, "voice": "medium", "pitch_method": "autocorr", "level": "intermediate"}
