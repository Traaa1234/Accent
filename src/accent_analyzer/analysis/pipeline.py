"""End-to-end analysis of one recording."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from accent_analyzer.analysis.audio import Audio, load_audio
from accent_analyzer.analysis.interpret import interpret, register_label
from accent_analyzer.analysis.metrics import RegisterMetrics, register_metrics
from accent_analyzer.analysis.phrasing import PhrasingResult, analyze_phrasing
from accent_analyzer.analysis.pitch import DEFAULT_F0_MAX, DEFAULT_F0_MIN, PitchTrack, extract_f0
from accent_analyzer.analysis.windows import WindowAnalysis, analyze_windows
from accent_analyzer.targets import Status, evaluate


@dataclass
class AnalysisResult:
    source: str
    duration: float
    track: PitchTrack
    register: RegisterMetrics
    phrasing: PhrasingResult
    windows: WindowAnalysis
    findings: list = field(default_factory=list)

    def metrics(self) -> dict[str, float]:
        """Flat headline metrics: what the scorecard, history and coaching triggers use."""
        p = self.phrasing.primary
        return {
            **{k: v for k, v in self.register.to_dict().items() if k not in ("n_frames", "n_voiced")},
            "pause_threshold": p.pause_threshold,
            "n_phrase_ends": p.n_ends,
            "hrt_rate": p.hrt_rate,
            "fall_rate": p.fall_rate,
            "level_rate": p.level_rate,
            "mean_rise_hz": p.mean_rise_hz,
            "mean_fall_hz": p.mean_fall_hz,
            "high_onset_rate": p.high_onset_rate,
            "mid_onset_rate": p.mid_onset_rate,
            "low_onset_rate": p.low_onset_rate,
            **self.windows.summary(),
        }

    def statuses(self) -> dict[str, Status]:
        return evaluate(self.metrics())

    @property
    def register_label(self) -> str:
        return register_label(self.register.mean_f0)

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "duration": self.duration,
            "pitch_method": self.track.method,
            "pitch_params": self.track.params,
            "register_label": self.register_label,
            "metrics": self.metrics(),
            "statuses": {k: s.value for k, s in self.statuses().items()},
            "phrasing": self.phrasing.to_dict(),
            "windows": self.windows.to_dict(),
            "findings": [f.to_dict() for f in self.findings],
        }


def analyze_track(track: PitchTrack, source: str = "", duration: float | None = None) -> AnalysisResult:
    register = register_metrics(track)
    phrasing = analyze_phrasing(track)
    result = AnalysisResult(
        source=source,
        duration=register.duration if duration is None else duration,
        track=track,
        register=register,
        phrasing=phrasing,
        windows=analyze_windows(track, phrasing.primary.phrases),
    )
    result.findings = interpret(result)
    return result


def analyze_audio(
    audio: Audio,
    pitch_method: str = "autocorr",
    f0_min: float = DEFAULT_F0_MIN,
    f0_max: float = DEFAULT_F0_MAX,
) -> AnalysisResult:
    track = extract_f0(audio.samples, audio.sr, pitch_method, f0_min=f0_min, f0_max=f0_max)
    return analyze_track(track, source=str(audio.source), duration=audio.duration)


def analyze_file(path: str | Path, **kwargs) -> AnalysisResult:
    return analyze_audio(load_audio(path), **kwargs)
