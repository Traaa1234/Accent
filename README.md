# accent-analyzer

Acoustic analysis and coaching for speakers (NZE, AuE, British, Indian English, ...)
training toward a General American accent. It measures intonation (pitch register,
range, phrase-final rises/falls, phrase onsets) and maps off-target metrics to
coaching drills.

**Status:** deliverables 1–2 of 6: audio pipeline, F0 extraction, register metrics,
phrase-ending (HRT) and onset analysis, 3-second window movement.
See [docs/PLAN.md](docs/PLAN.md) for the roadmap.

## Setup

Requires [uv](https://docs.astral.sh/uv/) and `ffmpeg` on `PATH`.

```bash
uv sync
uv run accent-analyzer analyze recording.m4a
uv run accent-analyzer analyze recording.m4a --json
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

## Tests

```bash
uv run pytest            # includes the slower pYIN test
uv run pytest -m "not slow"
```
