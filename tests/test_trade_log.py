"""
Tests für trade_log.py (eigene Backtests dokumentieren) und die R-Kurve.
"""

import os
import sys

import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import chart  # noqa: E402
import trade_log as tl  # noqa: E402


def test_r_long_und_short():
    assert tl.compute_r("Long", 100, 95, 110) == 2.0       # +10 bei Risiko 5
    assert tl.compute_r("Long", 100, 95, 95) == -1.0       # Stop getroffen
    assert tl.compute_r("Short", 100, 104, 92) == 2.0      # Short: 8 Gewinn / 4 Risiko


def test_r_ungueltige_eingaben():
    with pytest.raises(ValueError):
        tl.compute_r("Long", 100, 100, 110)                # kein Risiko
    with pytest.raises(ValueError):
        tl.compute_r("Long", 100, 105, 110)                # Stop über Einstieg bei Long


def test_ergebnis_kategorie():
    assert tl.outcome(1.5) == "Gewinn"
    assert tl.outcome(-1.0) == "Verlust"
    assert tl.outcome(0.05) == "Break-even"


def _trade(**kw):
    t = {"Datum": "2026-10-19", "Uhrzeit": "15:30", "Instrument": "US100",
         "Richtung": "Short", "Signal": "Signal B (H4-Retracement)", "Sweep_Punkt": "PDH",
         "POI": "H4-FVG", "LQS_Muster": "a) Ablehnungskerze", "Checkliste_erfuellt": "ja",
         "Einstieg": 100.0, "Stop": 104.0, "Ziel": 90.0, "Ausstieg": 92.0,
         "Notizen": "Test", "Screenshot": ""}
    t.update(kw)
    return t


def test_speichern_laden_und_statistik(tmp_path):
    path = str(tmp_path / "bt" / "backtests.csv")
    tl.add(_trade(), path)                                  # +2 R
    tl.add(_trade(Ausstieg=104.0, Signal="Signal A (Original)"), path)   # -1 R
    df = tl.add(_trade(Ausstieg=100.2), path)               # -0,05 R -> Break-even
    assert list(df["R"]) == [2.0, -1.0, -0.05]
    assert list(df["Ergebnis"]) == ["Gewinn", "Verlust", "Break-even"]

    back = tl.load(path)                                    # deutsches CSV wieder einlesen
    assert len(back) == 3 and float(back["R"].iloc[0]) == 2.0

    s = tl.stats(back)
    assert s["Trades"] == 3 and s["Gewinner"] == 1 and s["Verlierer"] == 1
    assert s["Trefferquote"] == 0.5                         # Break-even zählt nicht mit
    assert s["Summe R"] == pytest.approx(0.95)
    assert s["Profitfaktor"] == pytest.approx(2.0)
    assert s["Max. Drawdown (R)"] == pytest.approx(-1.05)

    g = tl.by_group(back, "Signal")
    assert set(g["Signal"]) == {"Signal A (Original)", "Signal B (H4-Retracement)"}


def test_ungueltiger_trade_wird_nicht_gespeichert(tmp_path):
    path = str(tmp_path / "bt.csv")
    with pytest.raises(ValueError):
        tl.add(_trade(Stop=100.0), path)
    assert not os.path.exists(path)


def test_neu_berechnen_nach_bearbeiten():
    df = pd.DataFrame([_trade(), _trade(Stop=100.0)])
    out = tl.recompute(df)
    assert out["R"].iloc[0] == 2.0 and out["Ergebnis"].iloc[1] == "ungültig"


def test_leere_statistik():
    assert tl.stats(pd.DataFrame(columns=tl.COLUMNS)) == {"Trades": 0}


def test_r_kurve():
    df = tl.recompute(pd.DataFrame([_trade(), _trade(Ausstieg=104.0)]))
    fig = chart.equity_curve(df)
    assert list(fig.data[0].y) == [2.0, 1.0]
    assert fig.data[0].showlegend is False                 # eine Linie -> keine Legende
