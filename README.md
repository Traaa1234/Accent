# accent-analyzer

Acoustic analysis and coaching for speakers (NZE, AuE, British, Indian English, ...)
training toward a General American accent. It measures intonation (pitch register,
range, phrase-final rises/falls, phrase onsets) and maps off-target metrics to
coaching drills.

**Status:** deliverables 1–5 of 6: audio pipeline, F0 extraction, register metrics,
phrase-ending (HRT) and onset analysis, 3-second window movement, HTML/PDF reports,
session history with progression warnings, coaching library and recommendations.
See [docs/PLAN.md](docs/PLAN.md) for the roadmap.

## Setup

Requires [uv](https://docs.astral.sh/uv/) and `ffmpeg` on `PATH`.

```bash
uv sync
uv run accent-analyzer analyze recording.m4a
uv run accent-analyzer analyze recording.m4a --json
uv run accent-analyzer analyze recording.m4a --name "Monday morning" -o report.html -o report.pdf
uv run accent-analyzer analyze recording.m4a --name "Monday morning" --history ~/.accent_history.db
uv run accent-analyzer history --history ~/.accent_history.db --last 10
uv run accent-analyzer analyze recording.m4a --accent nze --history ~/.accent_history.db
uv run accent-analyzer coach --history ~/.accent_history.db --focus hrt -o plan.html
uv run accent-analyzer analyze recording.m4a --pitch-method yin --f0-min 70 --f0-max 260
```

## Pitch tracking

The default autocorrelation tracker uses 40 ms Hann frames with a 10 ms hop, searches
80–320 Hz, and marks a frame voiced when the normalized autocorrelation peak exceeds
0.3 and the frame is within 40 dB of the loudest frame. F0 = 0 means unvoiced.
`--pitch-method yin` uses librosa's pYIN, which is slower but more resistant to octave
errors. Adjust `--f0-min/--f0-max` to the speaker's range: lower for deep voices, higher
for high ones.

## Metrics (so far)

| Metric | Target (AmE) |
|---|---|
| Mean / median F0, p10 / p90 | (reported only) |
| Std dev | ≥ 60 Hz |
| Range ratio p90/p10 | 2.5–4.0× |
| Voiced ratio | 60–80% |
| HRT: rising phrase endings (Δ > +10 Hz over last 500 ms) | ≤ 25% |
| HIGH onsets (first 500 ms > 1.15 × mean F0) | ≥ 40% |
| LOW onsets (< 0.9 × mean F0) | ≤ 20% |
| 3 s windows falling / level / rising (±5 Hz/s) | 50–65% / 25–35% / 10–20% |

Phrases are split at unvoiced runs ≥ 0.20 s, falling back to 0.12 s when that
yields fewer than 15 phrase endings; both results are reported. Fewer than 10
measurable endings triggers an "insufficient data" caveat.

## Reports

`-o/--output` writes a report; the format follows the extension (`.html` or `.pdf`) and
the flag can be repeated. The HTML file is self-contained (charts embedded) and follows
the viewer's light/dark setting. Sections: headline verdict, scorecard, pitch contour,
phrase-ending histogram (with both pause thresholds and a table of every ending),
3-second window and onset breakdowns, findings, and coaching recommendations. With
`--history`, the report adds a "compared with previous sessions" section.

## Session history

`--history PATH` (or `ACCENT_HISTORY=PATH`) stores each analysis in SQLite: time, name,
session/take, duration, all metrics, and the phrase-end and onset distributions. Takes
are grouped into sessions by date unless you pass `--session`; `--date` backfills older
recordings. After each analysis, and in `accent-analyzer history`, these rules run:

| Flag | Rule |
|---|---|
| Register deflation | mean F0 falls on 3+ consecutive recordings, > 30 Hz in total |
| Complacency regression | HRT rises on 2+ consecutive recordings after a breakthrough (HRT ≤ 25%) |
| Integration milestone | HRT < 25%, HIGH onsets > 40%, range > 2.6× in one recording (first / repeat) |
| Fatigue | latest take in a session worse than take 1 on 2+ of: HRT +15 pts, HIGH onsets −15 pts, range −0.3×, std −15 Hz, mean F0 −20 Hz |
| Register-independent HRT | HRT ≤ 25% in most animated (> 180 Hz) *and* calm (< 160 Hz) recordings = robust; animated only = fragile (last 10 recordings with 10+ endings) |

## Coaching

Nine modules live in [`src/accent_analyzer/coaching/modules.toml`](src/accent_analyzer/coaching/modules.toml),
each with a description, target, triggers, drills, practice sentences, key words and
progress indicators. Edit the file to change content or thresholds; no code changes needed.

| Module | Triggered by |
|---|---|
| HRT | HRT > 25% |
| Pitch range | range ratio < 2.5× or std dev < 60 Hz |
| Phrase onset height | HIGH onsets < 30% or LOW onsets > 40% |
| Connected speech | voiced ratio < 50% |
| T-flapping | accent: NZE, AuE, British, Indian (audio detection planned for v2) |
| Rhoticity | accent: NZE, AuE, British (audio detection planned for v2) |
| Dark /l/ | accent: Indian, British (audio detection planned for v2) |
| NZE/AuE vowel shift | accent: NZE, AuE |
| Vocabulary swaps | accent: NZE, AuE, British, Indian |

Measured problems rank first, by how far past the threshold the metric is; accent-based
modules follow. HRT and onset modules are marked *provisional* when fewer than 10
phrase endings were measurable. `--accent` is remembered in the history, so set it once.
`analyze` shows the top 4 and puts them in the report; `coach` gives the full plan with
current / previous / best values for each progress indicator.

## Tests

```bash
uv run pytest            # includes the slower pYIN test
uv run pytest -m "not slow"
```
