"""
Tests für signals.py: Signal A (Original), Signal B (H4-Retracement), Modus-Wechsel.
"""

import os
import sys
from types import SimpleNamespace

import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import bias  # noqa: E402
import signals  # noqa: E402
import structure as st  # noqa: E402
from tests.test_bias import LEER, _report  # noqa: E402
from tests.test_structure import _daily_bullish, _h4  # noqa: E402


def lage(h4_trend, h4_kind, price=16):
    """Daily bullish (Kerzen 0..18), H4 mit vorgegebenem Trend."""
    df, res = _daily_bullish()
    h4 = _h4(h4_trend, h4_kind)
    htf = st.htf_trend(res, df, h4, last_price=price)
    rep = _report(price)
    b = bias.compute_bias(htf, res, df, rep, LEER)
    return SimpleNamespace(htf=htf, daily=res, h4=h4, bias=b, report=rep,
                           d_done=df, today=LEER)


# --- Signal B -------------------------------------------------------------------
def test_signal_b_aktiv_bei_h4_retracement():
    a = lage(st.BEARISH, "MSS")                   # H4 läuft gegen den bullishen Daily
    s = signals.retracement_signal(a)
    assert s.active and s.direction == st.BULLISH
    assert any("Retracement" in r for r in s.reasons)


def test_signal_b_inaktiv_wenn_h4_mit_daily():
    s = signals.retracement_signal(lage(st.BULLISH, "BOS"))
    assert not s.active and "nicht aktiv" in s.text


# --- Modus-Wechsel ---------------------------------------------------------------
def test_modus_original_laesst_bias_unveraendert():
    a = lage(st.BEARISH, "MSS")
    assert signals.bias_for_mode(a, "original") is a.bias
    assert signals.bias_for_mode(a, "beide") is a.bias


def test_modus_retracement_nimmt_signal_b():
    a = lage(st.BEARISH, "MSS")
    b = signals.bias_for_mode(a, "retracement")
    assert b.bias == st.BULLISH and b.mode == "Retracement"
    assert b is not a.bias                        # Original bleibt unangetastet
    assert all(t.price > a.report.last_price for t in b.targets)


def test_modus_retracement_ohne_signal_ist_neutral():
    b = signals.bias_for_mode(lage(st.BULLISH, "BOS"), "retracement")
    assert b.bias == bias.NEUTRAL


def test_unbekannter_modus():
    with pytest.raises(ValueError):
        signals.bias_for_mode(lage(st.BULLISH, "BOS"), "quatsch")


# --- Urteil + Backtest-Statistik ---------------------------------------------------
def test_urteil():
    A = signals.Signal("A", st.BULLISH, "")
    B = signals.Signal("B", st.BULLISH, "")
    N = signals.Signal("B", None, "")
    assert "BEIDE" in signals.verdict(A, B)
    assert "Nur Signal A" in signals.verdict(A, N)
    assert "widersprechen" in signals.verdict(A, signals.Signal("B", st.BEARISH, ""))
    assert "Kein Signal" in signals.verdict(N, N)


def test_backtest_statistik(tmp_path):
    df = pd.DataFrame({"Bewegung_Tagesende": [1.0, -1.0, 2.0, 0.5],
                       signals.RETRACE_COLUMN: [st.BULLISH, st.BULLISH, st.BULLISH, None]})
    df.to_csv(tmp_path / "methoden_US100.csv", sep=";", decimal=",",
              index=False, encoding="utf-8-sig")
    txt = signals.history_stats("US100", signals.RETRACE_COLUMN, str(tmp_path))
    assert "67%" in txt and "3 Tagen" in txt
    assert "noch kein Backtest" in signals.history_stats("EURGBP", signals.RETRACE_COLUMN,
                                                         str(tmp_path))
