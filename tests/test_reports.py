import re

import numpy as np
import pytest
import soundfile as sf
from click.testing import CliRunner

from accent_analyzer.analysis.pipeline import analyze_track
from accent_analyzer.analysis.pitch import PitchTrack
from accent_analyzer.analyzer import cli
from accent_analyzer.reports import build_pdf, render_html, write_report
from accent_analyzer.reports import charts
from accent_analyzer.reports.theme import DARK, LIGHT
from accent_analyzer.reports.verdict import headline, scorecard
from accent_analyzer.targets import Status
import synth

SECTIONS = ("Verdict", "Scorecard", "Pitch contour", "Phrase endings", "3-second windows",
            "Phrase onsets", "Findings", "Coaching recommendations")
PNG = b"\x89PNG"


@pytest.fixture(scope="module")
def silent():
    f0 = np.zeros(300)
    return analyze_track(PitchTrack(f0=f0, times=0.02 + 0.01 * np.arange(300), confidence=f0), "silent.wav")


def test_html_has_all_sections(nze):
    html = render_html(nze)
    for section in SECTIONS:
        assert f"<h2>{section}</h2>" in html
    assert "Compared with previous sessions" not in html  # no history given
    assert html.count("<picture>") == 4
    assert html.count('media="screen and (prefers-color-scheme: dark)"') == 4
    assert "nan" not in re.sub(r"data:image/png;base64,[^\"']+", "", html).lower()


def test_html_escapes_title(nze):
    html = render_html(nze, title="<script>alert(1)</script>")
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_html_lists_phrase_endings_and_both_thresholds(nze):
    html = render_html(nze)
    assert "Phrase endings as a table" in html
    assert html.count("<td class='num'>0.20s</td>") == 1 and html.count("<td class='num'>0.12s</td>") == 1


def test_scorecard_statuses(nze):
    rows = {r.key: r for r in scorecard(nze)}
    assert rows["hrt_rate"].status is Status.ABOVE and rows["hrt_rate"].icon == "▲"
    assert rows["voiced_ratio"].status is Status.ON_TARGET
    assert rows["mean_f0"].status_text == ""  # no target, no status chip


def test_headline_prioritises_hrt_for_nze(nze):
    text = headline(nze)
    assert "Biggest gaps: HRT (rising phrase endings) 70%" in text
    assert "calm register" in text


def test_headline_for_ame_and_short(ame, short):
    assert "Holding up: HRT" in headline(ame)
    assert "treat the HRT figure as indicative" in headline(short)


def test_history_section(nze, ame):
    history = [nze.metrics(), ame.metrics(), nze.metrics()]
    html = render_html(nze, history=history)
    assert "Compared with previous sessions" in html
    assert charts.trajectory(history, LIGHT).startswith(PNG)


def test_recommendations_rendered(nze):
    recs = [{"title": "HRT: fall at the full stop", "why": "Rises sound like questions.",
             "drills": ["News anchor mode", "Hand chop"]}]
    html = render_html(nze, recommendations=recs)
    assert "HRT: fall at the full stop" in html and "<li>Hand chop</li>" in html


@pytest.mark.parametrize("chart", [charts.pitch_contour, charts.phrase_end_histogram,
                                   charts.window_breakdown, charts.onset_breakdown])
@pytest.mark.parametrize("theme", [LIGHT, DARK])
def test_charts_render_on_empty_result(silent, chart, theme):
    assert chart(silent, theme).startswith(PNG)


def test_silent_recording_report(silent):
    html = render_html(silent)
    assert "No voiced speech detected" not in html  # message is inside the PNG, page still renders
    assert "<h2>Verdict</h2>" in html
    assert build_pdf(silent).startswith(b"%PDF")


def test_pdf(nze, ame):
    pdf = build_pdf(nze, history=[ame.metrics(), nze.metrics()])
    assert pdf.startswith(b"%PDF")
    assert len(re.findall(rb"/Type /Page\b", pdf)) >= 2


def test_write_report_by_extension(nze, tmp_path):
    assert write_report(nze, tmp_path / "r.html").read_text().startswith("<!doctype html>")
    assert write_report(nze, tmp_path / "r.pdf").read_bytes().startswith(b"%PDF")
    with pytest.raises(ValueError):
        write_report(nze, tmp_path / "r.docx")


def test_cli_writes_reports(tmp_path):
    wav = tmp_path / "take.wav"
    sf.write(wav, synth.short_clip(), synth.SR)
    html, pdf = tmp_path / "out.html", tmp_path / "out.pdf"
    result = CliRunner().invoke(cli, ["analyze", str(wav), "-o", str(html), "-o", str(pdf), "--name", "Monday"])
    assert result.exit_code == 0, result.output
    assert "Accent report · Monday" in html.read_text()
    assert pdf.read_bytes().startswith(b"%PDF")


def test_cli_rejects_bad_report_extension(tmp_path):
    wav = tmp_path / "take.wav"
    sf.write(wav, synth.short_clip(), synth.SR)
    result = CliRunner().invoke(cli, ["analyze", str(wav), "-o", str(tmp_path / "out.txt")])
    assert result.exit_code != 0 and ".html or .pdf" in result.output
