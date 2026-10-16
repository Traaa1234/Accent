import subprocess

import numpy as np
import pytest
import soundfile as sf

from accent_analyzer.analysis.audio import (
    AudioLoadError,
    PEAK_TARGET,
    TARGET_SR,
    convert_to_wav,
    load_audio,
)
from accent_analyzer.analysis.pitch import extract_f0_autocorr
from synth import harmonic_tone


def _stereo_44k(path, f0=150.0, seconds=1.0, gain=0.1):
    t = np.arange(int(44_100 * seconds)) / 44_100
    mono = gain * np.sin(2 * np.pi * f0 * t)
    sf.write(path, np.stack([mono, mono], axis=1), 44_100)


def test_wav_is_resampled_downmixed_and_normalized(tmp_path):
    src = tmp_path / "in.wav"
    _stereo_44k(src)
    audio = load_audio(src)
    assert audio.sr == TARGET_SR
    assert audio.samples.ndim == 1
    assert audio.samples.dtype == np.float32
    assert audio.duration == pytest.approx(1.0, abs=0.01)
    assert np.max(np.abs(audio.samples)) == pytest.approx(PEAK_TARGET, abs=1e-3)


@pytest.mark.parametrize("ext,codec", [(".m4a", "aac"), (".mp3", "libmp3lame"), (".flac", "flac")])
def test_compressed_formats_decode(tmp_path, ext, codec):
    wav = tmp_path / "in.wav"
    sf.write(wav, harmonic_tone(180, 1.0), 16_000)
    out = tmp_path / f"in{ext}"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav), "-c:a", codec, str(out)], check=True
    )
    audio = load_audio(out)
    track = extract_f0_autocorr(audio.samples, audio.sr)
    assert np.median(track.voiced_f0) == pytest.approx(180, rel=0.01)


def test_convert_to_wav(tmp_path):
    src = tmp_path / "in.wav"
    _stereo_44k(src)
    out = convert_to_wav(src, tmp_path / "out.wav")
    info = sf.info(out)
    assert info.samplerate == TARGET_SR and info.channels == 1 and info.subtype == "PCM_16"


def test_unsupported_extension(tmp_path):
    bad = tmp_path / "notes.txt"
    bad.write_text("hi")
    with pytest.raises(AudioLoadError, match="Unsupported"):
        load_audio(bad)


def test_missing_file(tmp_path):
    with pytest.raises(AudioLoadError, match="not found"):
        load_audio(tmp_path / "nope.wav")


def test_corrupt_file(tmp_path):
    bad = tmp_path / "broken.m4a"
    bad.write_bytes(b"not really audio")
    with pytest.raises(AudioLoadError, match="ffmpeg"):
        load_audio(bad)
