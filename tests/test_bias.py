"""
Tests für Schritt 3: Previous-Day-Logik, FVGs, Draw on Liquidity, Daily Bias.
"""

import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import bias  # noqa: E402
import levels  # noqa: E402
import pois  # noqa: E402
import structure as st  # noqa: E402
from tests.test_structure import PFAD, kerzen  # noqa: E402


def zwei_tage(vortag_davor, vortag):
    """Zwei Tageskerzen als (High, Low, Close)."""
    return kerzen([vortag_davor, vortag])


# --- Previous-Day-Logik -----------------------------------------------------
# Tag davor immer: High 110, Low 100
def test_schluss_ueber_pdh_ist_bullishe_fortsetzung():
    s = bias.previous_day_signal(zwei_tage((110, 100, 105), (115, 104, 112)))
    assert (s.kind, s.direction) == (bias.PD_FORTSETZUNG, st.BULLISH)


def test_schluss_unter_pdl_ist_bearishe_fortsetzung():
    s = bias.previous_day_signal(zwei_tage((110, 100, 105), (106, 95, 98)))
    assert (s.kind, s.direction) == (bias.PD_FORTSETZUNG, st.BEARISH)


def test_pdh_sweep_zurueck_in_range_ist_bearishes_reversal():
    s = bias.previous_day_signal(zwei_tage((110, 100, 105), (112, 103, 107)))
    assert (s.kind, s.direction) == (bias.PD_REVERSAL, st.BEARISH)


def test_pdl_sweep_zurueck_in_range_ist_bullishes_reversal():
    s = bias.previous_day_signal(zwei_tage((110, 100, 105), (106, 98, 104)))
    assert (s.kind, s.direction) == (bias.PD_REVERSAL, st.BULLISH)


def test_inside_day():
    s = bias.previous_day_signal(zwei_tage((110, 100, 105), (108, 102, 106)))
    assert (s.kind, s.direction) == (bias.PD_INSIDE, None)


def test_outside_day_in_range_geschlossen():
    s = bias.previous_day_signal(zwei_tage((110, 100, 105), (112, 98, 104)))
    assert (s.kind, s.direction) == (bias.PD_OUTSIDE, None)


def test_nur_docht_ueber_pdh_ist_keine_fortsetzung():
    # Hoch 115 über 110, aber Schluss genau auf 110 -> kein Körper darüber
    s = bias.previous_day_signal(zwei_tage((110, 100, 105), (115, 104, 110)))
    assert s.kind == bias.PD_REVERSAL


# --- Fair Value Gaps --------------------------------------------------------
def test_bullishes_fvg_und_mitigation():
    # Kerze 0 High 10 < Kerze 2 Low 12 -> bullishes FVG 10–12
    base = [(10, 8, 9), (14, 9, 13), (16, 12, 15)]
    f = pois.find_fvgs(kerzen(base))[0]
    assert (f.direction, f.bottom, f.top, f.pos) == (st.BULLISH, 10, 12, 1)
    assert f.mitigation == pois.KEINE
    assert pois.find_fvgs(kerzen(base + [(15, 11, 14)]))[0].mitigation == pois.TEILWEISE
    assert pois.find_fvgs(kerzen(base + [(15, 9.5, 10)]))[0].mitigation == pois.VOLLSTAENDIG


def test_bearishes_fvg():
    # Kerze 0 Low 20 > Kerze 2 High 18 -> bearishes FVG 18–20
    f = pois.find_fvgs(kerzen([(22, 20, 21), (21, 16, 17), (18, 15, 16)]))[0]
    assert (f.direction, f.bottom, f.top) == (st.BEARISH, 18, 20)


def test_kein_fvg_bei_ueberlappung():
    assert pois.find_fvgs(kerzen([(10, 8, 9), (12, 9, 11), (13, 9.5, 12)])) == []


# --- Daily Bias -------------------------------------------------------------
# Kursverlauf aus test_structure (bullish, BOS bei Kerze 8 und 14), danach
# eine Kerze, die über dem Hoch vom Vortag SCHLIESST (bullishe Fortsetzung).
#   Daily-Bein: Protected Low 14, Bein-Hoch 24, Equilibrium 19
#   Preis 23,5 -> Premium (schlecht für bullish)
#   Erwartete Konfidenz: 50 +10 (BOS) +15 (PD) -10 (Premium) +10 (DOL) = 75
def _report(last_price, pdh=24.0, pdh_taken=False):
    lv = {
        "PDH": levels.Level("PDH", pdh, None, "", pdh_taken),
        "PDL": levels.Level("PDL", 21.0, None, "", False),
        "PWH": levels.Level("PWH", 30.0, None, "", False),
        "PWL": levels.Level("PWL", 5.0, None, "", False),
    }
    return levels.LevelReport(None, last_price, None, None, lv)


def _bullish_setup():
    df = kerzen(PFAD[:16] + [(24, 21, 23.5)])
    res = st.analyze(df, "Daily", n=2)
    htf = st.htf_trend(res, df, None, last_price=23.5)
    return df, res, htf


LEER = pd.DataFrame(columns=["Open", "High", "Low", "Close"])


def test_bullisher_bias_mit_konfidenz():
    df, res, htf = _bullish_setup()
    b = bias.compute_bias(htf, res, df, _report(23.5), LEER)
    assert b.bias == st.BULLISH
    assert b.confidence == 75
    assert b.dol.name == "PDH" and b.dol.price == 24.0
    assert any("Premium" in r for r in b.contra)


def test_dol_springt_wenn_pdh_genommen():
    df, res, htf = _bullish_setup()
    b = bias.compute_bias(htf, res, df, _report(23.5, pdh_taken=True), LEER)
    assert b.dol.name == "PWH"


def test_dol_nur_in_bias_richtung():
    df, res, htf = _bullish_setup()
    b = bias.compute_bias(htf, res, df, _report(23.5), LEER)
    assert all(t.price > 23.5 for t in b.targets)      # nichts unter dem Preis


def test_widerspruch_previous_day_gegen_daily_ist_neutral():
    # Kerzen 0..18: Daily bullish, aber Kerze 18 schließt unter dem Tief von 17
    df = kerzen()[:19]
    res = st.analyze(df, "Daily", n=2)
    htf = st.htf_trend(res, df, None, last_price=16)
    b = bias.compute_bias(htf, res, df, _report(16), LEER)
    assert res.trend == st.BULLISH
    assert b.bias == bias.NEUTRAL
    assert any("WIDERSPRUCH" in r for r in b.contra)


def test_htf_unklar_ist_neutral():
    df = kerzen()[:8]
    res = st.analyze(df, "Daily", n=2)
    htf = st.htf_trend(res, df, None, last_price=12)
    b = bias.compute_bias(htf, res, df, _report(12), LEER)
    assert b.bias == bias.NEUTRAL and b.confidence == 0


def test_zu_schwach_ist_neutral(monkeypatch):
    import config
    monkeypatch.setattr(config, "BIAS_MIN_CONFIDENCE", 80)
    df, res, htf = _bullish_setup()
    b = bias.compute_bias(htf, res, df, _report(23.5), LEER)
    assert b.confidence == 75 and b.bias == bias.NEUTRAL
