# accent-analyzer

Acoustic analysis and coaching for speakers (NZE, AuE, British, Indian English, ...)
training toward a General American accent. It measures intonation (pitch register,
range, phrase-final rises/falls, phrase onsets) and maps off-target metrics to
coaching drills.

**Status:** deliverables 1–6 done, plus a local web app with shadowing, A/B contrast
and a daily drill tracker. Next on the roadmap: phonetic feature detection
(T-flaps, dark /l/, rhoticity, vowels) via forced alignment.
See [docs/PLAN.md](docs/PLAN.md) for the roadmap.

## Quick start: the app

Needs [uv](https://docs.astral.sh/uv/), `ffmpeg` and `git` on your PATH.

```
uv tool install "git+https://github.com/traaa1234/accent@claude/lucid-planck-hf04ep"
accent-analyzer app --install-shortcut     # optional: "Accent Coach" launcher on your desktop
accent-analyzer app                        # opens http://localhost:8765 in your browser
```

* **Record**: read a passage, talk about a topic, or drop in an audio file. A ring
  fills at one minute, and a level meter shows the mic is picking you up.
* **Results**: verdict, key numbers, your pitch contour with every phrase ending;
  click a ▲/▼ to hear that phrase. Full HTML/PDF report and delete buttons.
* **Progress**: the dashboard, always current.
* **Practice**, in four tabs:
  * **Today**: a 5-minute routine (warm-up, a focus drill from your weakest area,
    10 rotating target words, a recorded passage), streak counter, 7-day strip and
    weekly summary. Beginner / intermediate / advanced change the material, not the time.
  * **Shadow**: add native-speaker clips (5–30 s), listen, record your copy. Scores
    contour match, range match and phrase-ending agreement, with both pitch lines overlaid.
  * **A/B contrast**: two takes of one sentence; which sounds more American, and why.
  * **Modules**: the full coaching library, recommended ones first.
* **Settings**: accent background, voice range, pitch tracker.

Everything stays on your computer: the server only listens on 127.0.0.1, and
recordings live in `~/.accent_analyzer` (history shared with the command line via
`ACCENT_HISTORY`). Keep the app's terminal window open while using it; close it to stop.
Launching again while it's running just reopens the browser tab.

## Command line

The app and the command line share the same analysis and history.

```bash
uv sync
uv run accent-analyzer analyze recording.m4a
uv run accent-analyzer analyze recording.m4a --json
uv run accent-analyzer analyze recording.m4a --name "Monday morning" -o report.html -o report.pdf
uv run accent-analyzer analyze recording.m4a --name "Monday morning" --history ~/.accent_history.db
uv run accent-analyzer history --history ~/.accent_history.db --last 10
uv run accent-analyzer analyze recording.m4a --accent nze --history ~/.accent_history.db
uv run accent-analyzer coach --history ~/.accent_history.db --focus hrt -o plan.html
uv run accent-analyzer dashboard --history ~/.accent_history.db --open
uv run accent-analyzer analyze recording.m4a --pitch-method yin --f0-min 70 --f0-max 260
uv run accent-analyzer shadow --reference clips/anchor.wav --user my_take.m4a
uv run accent-analyzer compare take_a.m4a take_b.m4a
uv run accent-analyzer drill --day monday --level intermediate --history ~/.accent_history.db --done
```

**Shadowing and A/B** compare contours in semitones relative to each speaker's own
median pitch (so a low voice copying a high one is judged on shape), after a 5-frame
median filter removes octave glitches, aligned with DTW to absorb speaking-rate
differences. Shadow score = 60% contour correlation + 20% range match + 20%
phrase-ending agreement. A/B weighs the final ending (35%), share of falling endings
(25%), range (20%) and phrase-onset height (20%).

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

## Dashboard

`accent-analyzer dashboard --history PATH [-o file.html] [--open]` writes one
self-contained, offline HTML file (no CDN) that follows light/dark mode:

* KPI tiles for the latest recording with change vs the previous one
* HRT and falling-endings trajectory on one % axis, crosshair tooltip (arrow keys work too)
* Mean pitch bars with calm/animated reference lines; register-deflation runs are
  highlighted and labelled
* Radar of the latest recording vs your best-ever (highest average score among
  recordings with 10+ phrase endings); each axis is scaled so the outer ring is the target
* Current progression flags and a sortable table of every recording
* With more than 10 recordings, a Last 10 / Last 30 / All control scopes everything

## Tests

```bash
uv run pytest            # includes the slower pYIN test
uv run pytest -m "not slow"
```
