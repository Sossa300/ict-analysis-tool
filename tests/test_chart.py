"""
Tests für chart.py: Hilfsfunktionen und ob aus einer Analyse Charts entstehen.
"""

import contextlib
import io
import os
import sys

import pandas as pd
import plotly.graph_objects as go

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import chart  # noqa: E402
import config  # noqa: E402
import data  # noqa: E402
import main as tool  # noqa: E402
from tests.beispieldaten import make_sample_h1  # noqa: E402


def test_ohne_preis():
    assert chart._ohne_preis("✓ London High 30.201,00 (gebr.)") == "✓ London High"
    assert chart._ohne_preis("DOL ▶ 29.648,00") == "DOL ▶"


def test_rgba():
    assert chart._rgba("#3987e5", 0.2) == "rgba(57,135,229,0.2)"


def test_zeit_auf_x_achse():
    t = pd.Timestamp("2026-10-14 09:30", tz=config.TZ_NY)
    assert chart._bx(t) == pd.Timestamp("2026-10-14 15:30")      # Berliner Uhrzeit
    assert chart._bx(pd.Timestamp("2026-10-14")) == pd.Timestamp("2026-10-14")


def test_nur_drei_timeframe_farben_je_design():
    for t in chart.THEMES.values():
        assert set(t["tf"]) == {"Daily", "H4", "M15"}
        assert len(set(t["tf"].values())) == 3


def _analyse():
    tf = data.build_timeframes(make_sample_h1(), config.INSTRUMENTS["US100"])
    as_of = pd.Timestamp("2026-10-14 09:00", tz=config.TZ_NY)
    tf = data.cut_at(tf, as_of)
    with contextlib.redirect_stdout(io.StringIO()):
        return tool.analyze_and_print("US100", tf, as_of, "beide")


def test_charts_entstehen(tmp_path):
    a = _analyse()
    figs = chart.build_all(a, "US100", "dark")
    assert "Daily" in figs and "H4" in figs
    assert "M15" in figs                         # ohne M15-Daten: H1 als Ersatz
    assert "H1-Ersatz" in figs["M15"].layout.title.text
    for fig in figs.values():
        assert isinstance(fig, go.Figure)
        assert any(isinstance(tr, go.Candlestick) for tr in fig.data)
    assert "H1" in figs and "Detail" in figs["H1"].layout.title.text
    paths = chart.write_html(figs, "US100", str(tmp_path))
    assert len(paths) == 4 and all(os.path.exists(p) for p in paths)


def test_preisachse_am_rechten_rand():
    a = _analyse()
    for fig in chart.build_all(a, "US100").values():
        assert fig.layout.yaxis.side == "right"
        assert fig.layout.margin.r <= 20            # kein breiter Rand mehr rechts


def test_freier_bereich_ueberspringt_wochenende():
    fr = pd.Timestamp("2026-10-16 20:00")             # Freitag
    t = chart._future(fr, pd.Timedelta(hours=4), 2, daily=False)
    assert t.weekday() == 0                            # landet am Montag
    assert chart._future(pd.Timestamp("2026-10-16"), None, 1, daily=True) == \
        pd.Timestamp("2026-10-19")


def test_h1_linien_beginnen_an_entstehung():
    a = _analyse()
    fig = chart.build_chart(a, "US100", "H1")
    pdh = next(tr for tr in fig.data if tr.name in ("Sweep-Punkte gültig", "Sweep-Punkte ungültig")
               and "PDH" in (tr.hovertext or ""))
    # PDH 120 entstand Mo 12.10. 22:00 NY = Di 04:00 Berlin
    assert pd.Timestamp(pdh.x[0]) == pd.Timestamp("2026-10-13 04:00")


def test_sweep_punkte_im_chart():
    a = _analyse()
    fig = chart.build_chart(a, "US100", "H4", "light")
    namen = {tr.name for tr in fig.data}
    assert namen & {"Sweep-Punkte gültig", "Sweep-Punkte ungültig"}
    texte = " ".join(an.text for an in fig.layout.annotations)
    assert "PDH" in texte and "Preis" in texte
