# Build plan

## Layout

```
src/accent_analyzer/
  analyzer.py          click CLI (`accent-analyzer`)
  targets.py           AmE target ranges, shared by metrics / reports / coaching
  analysis/
    audio.py           ffmpeg decode -> 16 kHz mono float32, DC removal, peak normalize
    pitch.py           F0 tracking: autocorr (default), pYIN (--pitch-method yin), CREPE (planned)
    metrics.py         register & variability metrics
    phrasing.py        pause detection (adaptive 0.20s -> 0.12s), phrase-end direction, onsets
    windows.py         3-second sliding-window slope classification
    interpret.py       single-recording interpretation rules -> Findings
    pipeline.py        analyze_file() -> AnalysisResult (the object everything downstream reads)
  reports/             [3] matplotlib charts -> HTML (Jinja-free string templates) + PDF (reportlab)
  history/             [4] SQLite store, trajectory queries, progression warnings
  coaching/            [5] module library (data, not code) + recommendation engine
  dashboard/           [6] static HTML dashboard generated from history
tests/
  synth.py             synthetic harmonic signals with known F0 contours
```

Every analysis stage takes plain numpy arrays / dataclasses and returns dataclasses,
so reports, history and coaching consume one `AnalysisResult` object and never
re-run DSP.

## Deliverables

1. **Core pipeline + F0 + basic metrics** — done.
2. **Phrasing** — done. Pause runs from F0=0, adaptive threshold (report both 0.20s and
   0.12s results), phrase-end Δ over last 500 ms (first-third vs last-third mean),
   Rising/Falling/Level + BIG/MOD/Small, HRT%, onset ratio HIGH/MID/LOW,
   3 s window slopes. Fixtures: NZE-like, AmE-like, short clip, continuous speech.
3. **Reports**: headline verdict, scorecard, contour, phrase-end histogram,
   window breakdown, onset distribution, recommendations; HTML first, then PDF.
4. **History**: SQLite (`recordings` table + JSON blob of distributions), trajectory
   queries, register-deflation / complacency-regression / integration-milestone /
   fatigue flags.
5. **Coaching**: the 9 modules as structured data with trigger predicates on
   `AnalysisResult`; engine ranks triggered modules by distance from target.
6. **Dashboard**: HRT/falls trajectory, mean-F0 bars, radar vs best-ever, sortable table.
7. **Later**: shadowing (DTW-aligned contour correlation), A/B mode, daily drill tracker.

## v2 phonetic features (not in v1)

These need segment timing, so they depend on forced alignment
(whisper-timestamped or Montreal Forced Aligner):

| Feature | Measurement | v1 surrogate |
|---|---|---|
| T-flapping | voicing continuity through intervocalic /t/ | none reliable; drill list only |
| Dark /l/ | F2 lowering at syllable-final /l/ | none; drill list only |
| Rhoticity | F3 lowering (< ~2000 Hz) on post-vocalic /r/ | none; drill list only |
| NZE vowel shift | F1/F2 scatter for KIT/DRESS/TRAP | triggered by self-identified accent |

Without alignment there is no honest acoustic surrogate for the segmental features,
so v1 will offer those modules from self-reported background instead of claiming
detection.

## Design decisions that differ from the spec

* **Phrase-end pitch uses the median** of each third of the 500 ms window, not the
  mean, so a single octave jump or creaky frame can't flip the direction.
* **3-second windows fit within phrases**: one shared slope, a separate intercept per
  phrase. A plain line fit across a pause reads the reset (low end of one phrase,
  high start of the next) as a rise; on the AmE-like fixture that made 52% of
  windows "rising". `analyze_windows(track)` without phrases gives the plain fit.
* **Phrase boundaries include start and end of speech**, so N internal pauses give
  N + 1 phrase endings and onsets. The adaptive fallback counts phrase endings.
* **Interpretation rules done in step 2**: small-sample caveat (both thresholds),
  direction asymmetry, voiced-ratio bands, foundation vs direction axes,
  integration milestone. Register-independent HRT needs history (step 4); each
  result already carries its register label (animated > 180 Hz, calm < 160 Hz).

## Known calibration risks

* **Range-ratio target (2.5–4.0×)** is wide for p90/p10. The AmE-like fixture, whose
  contours span roughly 85–300 Hz, measures 2.16×. Autocorrelation octave
  errors inflate this metric directly, so it should be validated against pYIN on
  real recordings before trusting coaching triggers that depend on it.
* Voiced ratio depends on the confidence threshold and silence gate; it measures
  "frames with periodic energy", which reads lower than "time spent talking".
