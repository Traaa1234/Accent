"""Audio preprocessing: decode any supported format to 16 kHz mono float32, normalized."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

TARGET_SR = 16_000
# .webm/.ogg/.mp4 are what browsers record (Chrome/Edge, Firefox, Safari).
SUPPORTED_EXTENSIONS = frozenset({".m4a", ".mp3", ".wav", ".flac", ".aac", ".webm", ".ogg", ".mp4"})
PEAK_TARGET = 0.95


class AudioLoadError(RuntimeError):
    """Raised when an input file cannot be decoded."""


@dataclass(frozen=True)
class Audio:
    samples: np.ndarray  # float32, mono, peak-normalized
    sr: int
    source: Path

    @property
    def duration(self) -> float:
        return len(self.samples) / self.sr


def _check_extension(path: Path) -> None:
    if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        supported = ", ".join(sorted(SUPPORTED_EXTENSIONS))
        raise AudioLoadError(f"Unsupported format '{path.suffix}' (supported: {supported})")


def decode(path: str | Path, sr: int = TARGET_SR) -> np.ndarray:
    """Decode a file to mono float32 at `sr` using ffmpeg, without normalization."""
    path = Path(path)
    if not path.exists():
        raise AudioLoadError(f"File not found: {path}")
    _check_extension(path)
    try:
        import ffmpeg
    except ImportError:  # the browser version has no ffmpeg; it hands over WAV files
        if path.suffix.lower() == ".wav":
            return read_wav(path, sr)
        raise AudioLoadError("ffmpeg-python is not installed") from None
    try:
        out, _ = (
            ffmpeg.input(str(path))
            .output("pipe:", format="f32le", acodec="pcm_f32le", ac=1, ar=sr)
            .run(capture_stdout=True, capture_stderr=True)
        )
    except ffmpeg.Error as exc:
        stderr = exc.stderr.decode(errors="replace").strip().splitlines()
        detail = stderr[-1] if stderr else "unknown ffmpeg error"
        raise AudioLoadError(f"ffmpeg could not decode {path}: {detail}") from exc
    except FileNotFoundError as exc:
        raise AudioLoadError("ffmpeg executable not found on PATH") from exc
    return np.frombuffer(out, dtype=np.float32).copy()


def read_wav(path: str | Path, sr: int = TARGET_SR) -> np.ndarray:
    """Read a 16-bit PCM WAV with the standard library, downmixed and resampled to `sr`."""
    import wave

    try:
        with wave.open(str(path), "rb") as w:
            channels, width, rate = w.getnchannels(), w.getsampwidth(), w.getframerate()
            raw = w.readframes(w.getnframes())
    except (wave.Error, EOFError) as exc:
        raise AudioLoadError(f"Could not read WAV {Path(path).name}: {exc}") from exc
    if width != 2:
        raise AudioLoadError("Only 16-bit PCM WAV can be read without ffmpeg")
    samples = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    samples = samples.reshape(-1, channels).mean(axis=1) if channels > 1 else samples
    if rate != sr:
        from math import gcd

        from scipy.signal import resample_poly

        g = gcd(rate, sr)
        samples = resample_poly(samples, sr // g, rate // g).astype(np.float32)
    return samples


def normalize(samples: np.ndarray, peak: float = PEAK_TARGET) -> np.ndarray:
    """Remove DC offset and scale so the absolute peak equals `peak`."""
    samples = samples - np.mean(samples) if len(samples) else samples
    max_abs = np.max(np.abs(samples)) if len(samples) else 0.0
    if max_abs < 1e-9:
        return samples.astype(np.float32)
    return (samples * (peak / max_abs)).astype(np.float32)


def load_audio(path: str | Path, sr: int = TARGET_SR) -> Audio:
    """Decode, downmix, resample and normalize a recording."""
    path = Path(path)
    samples = normalize(decode(path, sr))
    if len(samples) == 0:
        raise AudioLoadError(f"No audio samples decoded from {path}")
    return Audio(samples=samples, sr=sr, source=path)


def convert_to_wav(path: str | Path, out_path: str | Path, sr: int = TARGET_SR) -> Path:
    """Write a normalized 16 kHz mono 16-bit WAV copy of `path`."""
    import soundfile as sf

    audio = load_audio(path, sr)
    out_path = Path(out_path)
    sf.write(out_path, audio.samples, sr, subtype="PCM_16")
    return out_path
