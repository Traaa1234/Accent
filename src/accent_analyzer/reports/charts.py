"""Matplotlib charts for the per-recording report.

Every function takes an AnalysisResult (or history rows) and a Theme and returns
PNG bytes, so the HTML report can embed a light and a dark rendering and the PDF
can reuse the light one.
"""

from __future__ import annotations

import io
import math

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from accent_analyzer.analysis.phrasing import BIG_HZ, HIGH_ONSET, LEVEL_HZ, LOW_ONSET  # noqa: E402
from accent_analyzer.reports.theme import Theme  # noqa: E402
from accent_analyzer.targets import TARGETS  # noqa: E402

DPI = 160
WIDTH = 9.0  # inches


def _figure(theme: Theme, height: float, ncols: int = 1):
    fig, axes = plt.subplots(1, ncols, figsize=(WIDTH, height), dpi=DPI, squeeze=False)
    fig.patch.set_facecolor(theme.surface)
    for ax in axes.flat:
        _style_axes(ax, theme)
    return fig, axes[0] if ncols > 1 else axes[0][0]


def _style_axes(ax, theme: Theme) -> None:
    ax.set_facecolor(theme.surface)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(theme.axis)
        ax.spines[side].set_linewidth(0.8)
    ax.tick_params(colors=theme.muted, labelsize=8, length=3, width=0.6)
    ax.grid(True, axis="y", color=theme.grid, linewidth=0.6)
    ax.set_axisbelow(True)
    ax.xaxis.label.set_color(theme.ink_secondary)
    ax.yaxis.label.set_color(theme.ink_secondary)
    ax.xaxis.label.set_size(9)
    ax.yaxis.label.set_size(9)


def _empty(ax, theme: Theme, message: str) -> None:
    ax.text(0.5, 0.5, message, transform=ax.transAxes, ha="center", va="center", color=theme.muted, fontsize=9)
    ax.set_xticks([])
    ax.set_yticks([])


def _png(fig) -> bytes:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=fig.get_facecolor(), bbox_inches="tight", pad_inches=0.15)
    plt.close(fig)
    return buf.getvalue()


def _legend(ax, theme: Theme, **kwargs) -> None:
    leg = ax.legend(frameon=False, fontsize=8, labelcolor=theme.ink_secondary, **kwargs)
    if leg:
        for handle in leg.legend_handles:
            handle.set_alpha(1)


def pitch_contour(result, theme: Theme) -> bytes:
    fig, ax = _figure(theme, 3.2)
    track = result.track
    if not track.voiced.any():
        _empty(ax, theme, "No voiced speech detected")
        return _png(fig)

    mean = result.register.mean_f0
    t_max = float(track.times[-1])
    # Onset target zone: phrase starts above 1.15 × mean count as HIGH.
    top = max(track.voiced_f0.max(), mean * HIGH_ONSET) * 1.08
    ax.axhspan(mean * HIGH_ONSET, top, color=theme.band, linewidth=0, zorder=0)
    ax.set_ylim(min(track.voiced_f0.min(), mean * LOW_ONSET) * 0.92, top)
    ax.scatter(track.times[track.voiced], track.voiced_f0, s=2.5, color=theme.series,
               alpha=0.55, linewidths=0, label="F0", zorder=2, rasterized=True)
    ax.axhline(mean, color=theme.ink_secondary, linewidth=1, zorder=3)
    ax.axhline(mean * LOW_ONSET, color=theme.axis, linewidth=0.8, zorder=1)
    labels = [
        (mean, f"mean {mean:.0f} Hz", theme.ink_secondary),
        (mean * HIGH_ONSET, f"high-onset zone ≥ {HIGH_ONSET:g}× mean", theme.muted),
        (mean * LOW_ONSET, f"low onset < {LOW_ONSET:g}× mean", theme.muted),
    ]
    for y, text, color in labels:
        ax.text(t_max, y, f" {text}", va="center", ha="left", fontsize=7.5, color=color, clip_on=False)

    ends = result.phrasing.primary.ends
    for direction, marker, color, label in (
        ("rising", "^", theme.rising, "rising end ▲"),
        ("falling", "v", theme.falling, "falling end ▼"),
    ):
        pts = [(e.time, e.end_hz) for e in ends if e.direction == direction]
        if pts:
            x, y = zip(*pts)
            ax.scatter(x, y, s=46, marker=marker, color=color, edgecolors=theme.surface,
                       linewidths=1.5, label=label, zorder=4)
    ax.set_xlim(0, max(t_max, 1))
    ax.set_xlabel("Time (s)")
    ax.set_ylabel("F0 (Hz)")
    _legend(ax, theme, loc="upper left", ncols=3, bbox_to_anchor=(0, 1.0))
    return _png(fig)


def phrase_end_histogram(result, theme: Theme) -> bytes:
    fig, ax = _figure(theme, 2.8)
    p = result.phrasing.primary
    if not p.ends:
        _empty(ax, theme, "No measurable phrase endings")
        return _png(fig)

    deltas = np.array([e.delta for e in p.ends])
    lim = max(100.0, math.ceil(np.abs(deltas).max() / 10) * 10 + 10)
    edges = np.arange(-lim, lim + 10, 10)
    counts, _ = np.histogram(deltas, bins=edges)
    centres = (edges[:-1] + edges[1:]) / 2
    colors = [theme.falling if c < -LEVEL_HZ else theme.rising if c > LEVEL_HZ else theme.level for c in centres]
    ax.axvspan(-LEVEL_HZ, LEVEL_HZ, color=theme.grid, linewidth=0, zorder=0)
    ax.bar(centres, counts, width=8, color=colors, zorder=2)  # 2-unit gap between bins
    for x in (-BIG_HZ, BIG_HZ):
        ax.axvline(x, color=theme.axis, linewidth=0.8, zorder=1)
    top = max(counts.max(), 1)
    ax.set_ylim(0, top * 1.35 + 0.5)
    ax.text(-lim + 2, top * 1.25, f"◀ falling  {p.n_falling}", color=theme.ink_secondary, fontsize=8.5, va="center")
    ax.text(lim - 2, top * 1.25, f"rising  {p.n_rising} ▶", color=theme.ink_secondary, fontsize=8.5, va="center", ha="right")
    ax.text(0, top * 1.25, f"level {p.n_level}", color=theme.muted, fontsize=8, va="center", ha="center")
    for x, word in ((-BIG_HZ, "BIG"), (BIG_HZ, "BIG")):
        ax.text(x, top * 1.05, word, color=theme.muted, fontsize=7, ha="right" if x < 0 else "left")

    big = sorted((e for e in p.ends if abs(e.delta) > BIG_HZ), key=lambda e: -abs(e.delta))[:4]
    for e in big:
        idx = min(np.searchsorted(edges, e.delta, side="right") - 1, len(counts) - 1)
        ax.annotate(f"{e.delta:+.0f} Hz @ {e.time:.1f}s", (centres[idx], counts[idx]),
                    xytext=(0, 10), textcoords="offset points", ha="center", fontsize=7,
                    color=theme.ink_secondary)
    ax.set_xlim(-lim, lim)
    ax.yaxis.get_major_locator().set_params(integer=True)
    ax.set_xlabel("Pitch change over last 500 ms (Hz)")
    ax.set_ylabel("Endings")
    return _png(fig)


def _rate_bars(ax, theme: Theme, rows: list[tuple[str, float, str | None, str]]) -> None:
    """Horizontal % bars, each with its target zone shaded behind it."""
    y = np.arange(len(rows))[::-1]
    for yi, (label, value, key, color) in zip(y, rows):
        target = TARGETS.get(key) if key else None
        if target:
            lo = (target.low or 0) * 100
            hi = (target.high if target.high is not None else 1) * 100
            ax.barh(yi, hi - lo, left=lo, height=0.8, color=theme.band, zorder=0)
            ax.text(hi + 1, yi + 0.27, f"target {target.label()}", fontsize=7, color=theme.muted,
                    ha="left", va="center")
        v = 0 if math.isnan(value) else value * 100
        ax.barh(yi, v, height=0.42, color=color, zorder=2)
        ax.text(v + 1, yi, "n/a" if math.isnan(value) else f"{v:.0f}%", va="center", fontsize=8.5,
                color=theme.ink, zorder=3)
    ax.set_yticks(y, [r[0] for r in rows], fontsize=9, color=theme.ink_secondary)
    ax.set_xlim(0, 105)
    ax.grid(True, axis="x", color=theme.grid, linewidth=0.6)
    ax.grid(False, axis="y")
    ax.tick_params(axis="y", length=0)
    ax.set_xlabel("% of total")


def window_breakdown(result, theme: Theme) -> bytes:
    fig, ax = _figure(theme, 2.2)
    w = result.windows
    if not w.windows:
        _empty(ax, theme, "Recording too short for 3-second windows")
        return _png(fig)
    _rate_bars(ax, theme, [
        ("Falling ▼", w.falling_rate, "window_falling_rate", theme.falling),
        ("Level", w.level_rate, "window_level_rate", theme.level),
        ("Rising ▲", w.rising_rate, "window_rising_rate", theme.rising),
    ])
    return _png(fig)


def onset_breakdown(result, theme: Theme) -> bytes:
    fig, ax = _figure(theme, 2.2)
    p = result.phrasing.primary
    if not p.onsets:
        _empty(ax, theme, "No measurable phrase onsets")
        return _png(fig)
    _rate_bars(ax, theme, [
        (f"HIGH  > {HIGH_ONSET:g}×", p.high_onset_rate, "high_onset_rate", theme.series),
        ("MID", p.mid_onset_rate, None, theme.series),
        (f"LOW  < {LOW_ONSET:g}×", p.low_onset_rate, "low_onset_rate", theme.series),
    ])
    return _png(fig)


TRAJECTORY_METRICS = (
    ("hrt_rate", "HRT %", True),
    ("fall_rate", "Falls %", True),
    ("mean_f0", "Mean F0 (Hz)", False),
    ("std_f0", "Std dev (Hz)", False),
    ("range_ratio", "Range ratio (×)", False),
)


def trajectory(history: list[dict], theme: Theme) -> bytes:
    """Small multiples, one per metric (no shared or dual axis). Last point = this recording."""
    fig, axes = plt.subplots(1, len(TRAJECTORY_METRICS), figsize=(WIDTH, 2.2), dpi=DPI)
    fig.patch.set_facecolor(theme.surface)
    x = np.arange(1, len(history) + 1)
    for ax, (key, label, pct) in zip(axes, TRAJECTORY_METRICS):
        _style_axes(ax, theme)
        vals = np.array([np.nan if h.get(key) is None else h[key] for h in history], dtype=float)
        scale = 100 if pct else 1
        target = TARGETS.get(key)
        if target:
            lo = target.low if target.low is not None else 0
            hi = target.high if target.high is not None else np.nanmax(vals) * 1.2 if np.isfinite(vals).any() else lo
            ax.axhspan(lo * scale, hi * scale, color=theme.band, linewidth=0, zorder=0)
        ax.plot(x, vals * scale, color=theme.series, linewidth=2, marker="o", markersize=4, zorder=2)
        if np.isfinite(vals[-1]):
            ax.scatter([x[-1]], [vals[-1] * scale], s=50, color=theme.series, edgecolors=theme.surface,
                       linewidths=1.5, zorder=3)
            ax.annotate(f"{vals[-1] * scale:.0f}" if scale == 100 or key != "range_ratio" else f"{vals[-1]:.2f}",
                        (x[-1], vals[-1] * scale), xytext=(0, 7), textcoords="offset points",
                        ha="center", fontsize=7.5, color=theme.ink)
        ax.set_title(label, fontsize=8.5, color=theme.ink_secondary, loc="left")
        ax.set_xticks(x if len(x) <= 10 else x[:: max(1, len(x) // 6)])
        ax.margins(x=0.15, y=0.25)
    fig.suptitle("Trajectory across sessions (latest on the right)", x=0.01, ha="left",
                 fontsize=10, color=theme.ink, fontweight="bold")
    fig.tight_layout()
    return _png(fig)
