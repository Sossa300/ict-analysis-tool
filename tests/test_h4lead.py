"""
Tests für die H4-Führung: Daily unklar -> H4 mit Liquidity Sweep + MSS
bestimmt den Bias.

H4-Beispielverlauf (Open, High, Low, Close):
  Kerze 6 : Swing High 20,6 (bestätigt bei Kerze 8)
  Kerze 7 : Schluss 18,6 unter Swing Low 19 (Kerze 4) -> BOS bearish
  Kerze 8 : Swing Low 18,0 (bestätigt bei Kerze 10)
  Kerze 11: Ablehnungskerze: Docht bis 17,0 unter das Swing Low 18,
            kleiner bullisher Körper, Schluss 18,5 -> Liquidity Sweep
  Kerze 13: Schluss 20,9 über Swing High 20,6 -> MSS bullish
"""

import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import bias  # noqa: E402
import config  # noqa: E402
import structure as st  # noqa: E402
import sweeps  # noqa: E402
from tests.test_bias import LEER, _report  # noqa: E402
from tests.test_structure import kerzen  # noqa: E402

H4_PFAD = [
    (20.0, 20.5, 19.5, 19.8),   # 0
    (19.8, 21.0, 19.6, 20.8),   # 1
    (20.8, 22.0, 20.5, 21.5),   # 2
    (21.5, 21.6, 20.0, 20.2),   # 3
    (20.2, 20.4, 19.0, 19.2),   # 4  Swing Low 19
    (19.2, 20.0, 19.1, 19.8),   # 5
    (19.8, 20.6, 19.4, 20.4),   # 6  Swing High 20,6
    (20.4, 20.5, 18.5, 18.6),   # 7  BOS bearish
    (18.6, 19.5, 18.0, 19.2),   # 8  Swing Low 18
    (19.2, 19.4, 18.6, 18.9),   # 9
    (18.9, 19.0, 18.3, 18.5),   # 10
    (18.4, 18.6, 17.0, 18.5),   # 11 Sweep (Ablehnungskerze)
    (18.5, 19.5, 18.4, 19.4),   # 12
    (19.4, 21.0, 19.3, 20.9),   # 13 MSS bullish
]


def h4(rows=H4_PFAD):
    idx = pd.date_range("2026-10-12 18:00", periods=len(rows), freq="4h",
                        tz="America/New_York")
    df = pd.DataFrame(rows, columns=["Open", "High", "Low", "Close"], index=idx)
    return df, st.analyze(df, "H4", n=2)


# --- LQS-Muster (automatische H4-Prüfung) -----------------------------------
def test_ablehnungskerze_unter_tief():
    df, _ = h4()
    assert sweeps.lqs_pattern(df, 11, 18.0, "low") == (sweeps.MUSTER_A, 11, 11)


def test_ablehnungskerze_ueber_hoch():
    df = pd.DataFrame([(99.5, 102.0, 99.0, 99.2)], columns=["Open", "High", "Low", "Close"])
    assert sweeps.lqs_pattern(df, 0, 100.0, "high")[0] == sweeps.MUSTER_A


def test_zwei_kerzen_umkehr_unter_tief():
    # bearisher Körper 2,0 unter 100, danach bullisher Körper 2,2 zurück darüber
    df = pd.DataFrame([(101.0, 101.2, 98.5, 99.0), (99.0, 101.5, 98.8, 101.2)],
                      columns=["Open", "High", "Low", "Close"])
    assert sweeps.lqs_pattern(df, 0, 100.0, "low") == (sweeps.MUSTER_B, 0, 1)


def test_kleinere_gegenkerze_ist_kein_lqs():
    df = pd.DataFrame([(101.0, 101.2, 98.5, 99.0), (99.0, 100.5, 98.8, 100.2)],
                      columns=["Open", "High", "Low", "Close"])
    assert sweeps.lqs_pattern(df, 0, 100.0, "low") is None


# --- H4-Umkehr finden -------------------------------------------------------
def test_h4_umkehr_gefunden():
    df, res = h4()
    assert res.trend == st.BULLISH and res.last_break.kind == "MSS"
    rev = bias.find_h4_reversal(df, res)
    assert rev is not None
    assert (rev.direction, rev.level, rev.pattern, rev.sweep_extreme) == \
        (st.BULLISH, 18.0, sweeps.MUSTER_A, 17.0)
    assert rev.mss.pos == 13 and rev.bos_after is False


def test_ohne_sweep_keine_umkehr():
    rows = list(H4_PFAD)
    rows[10] = (18.3, 19.0, 18.2, 18.5)    # bullish (kein 2-Kerzen-Muster davor)
    rows[11] = (17.6, 18.6, 17.0, 18.5)    # großer Körper -> keine Ablehnungskerze
    rows[12] = (18.5, 18.9, 18.3, 18.4)    # kleine bearishe Kerze danach
    df, res = h4(rows)
    assert res.last_break.kind == "MSS"    # MSS gibt es trotzdem ...
    assert bias.find_h4_reversal(df, res) is None   # ... aber ohne Sweep zählt er nicht


def test_alter_mss_zaehlt_nicht(monkeypatch):
    monkeypatch.setattr(config, "H4_LEAD_MAX_AGE", 0)
    df, res = h4()
    assert bias.find_h4_reversal(df, res) is None


# --- Bias mit H4-Führung ----------------------------------------------------
# Daily ohne Strukturbruch (unklar), letzte Kerze ist ein Inside Day.
DAILY_UNKLAR = [(10, 8, 9), (11, 9, 10), (12, 10, 11), (11.5, 10.5, 11)]


def _unklar():
    d = kerzen(DAILY_UNKLAR)
    res = st.analyze(d, "Daily", n=2)
    return d, res, st.htf_trend(res, d, None, last_price=18.5)


def test_daily_unklar_h4_fuehrt():
    # 50 +10 LQS +10 MSS -10 H4-geführt -10 Inside Day +10 Discount +10 DOL = 70
    d, dres, htf = _unklar()
    df, h4res = h4()
    rev = bias.find_h4_reversal(df, h4res)
    b = bias.compute_bias(htf, dres, d, _report(18.5), LEER,
                          h4_rev=rev, h4_candles=df, h4_res=h4res)
    assert htf.trend == st.UNKLAR
    assert b.mode == "H4" and b.bias == st.BULLISH
    assert b.confidence == 70
    assert b.leg.protected == 17.0          # H4-Bein startet am Sweep-Tief


def test_ohne_h4_umkehr_bleibt_neutral():
    d, dres, htf = _unklar()
    b = bias.compute_bias(htf, dres, d, _report(18.5), LEER, h4_rev=None)
    assert b.bias == bias.NEUTRAL and b.mode == "Daily"
    assert any("H4 geprüft" in i for i in b.info)


def test_h4_fuehrung_abschaltbar(monkeypatch):
    monkeypatch.setattr(config, "H4_LEAD", False)
    d, dres, htf = _unklar()
    df, h4res = h4()
    b = bias.compute_bias(htf, dres, d, _report(18.5), LEER,
                          h4_rev=bias.find_h4_reversal(df, h4res),
                          h4_candles=df, h4_res=h4res)
    assert b.bias == bias.NEUTRAL


def test_h4_gegen_klaren_daily_trend_gesperrt():
    # Daily bullish, aber Previous Day bearish (Widerspruch) -> NEUTRAL.
    # H4 dreht bearish -> gegen den Daily-Trend -> gesperrt (nur Retracement).
    from tests.test_structure import kerzen as dk
    d = dk()[:19]                      # bullish, letzte Kerze schließt unter dem Vortagstief
    dres = st.analyze(d, "Daily", n=2)
    htf = st.htf_trend(dres, d, None, last_price=16)
    rows = [(40 - o, 40 - l, 40 - h, 40 - c) for o, h, l, c in H4_PFAD]   # gespiegelt: bearish
    df, h4res = h4(rows)
    rev = bias.find_h4_reversal(df, h4res)
    assert rev is not None and rev.direction == st.BEARISH
    b = bias.compute_bias(htf, dres, d, _report(16), LEER,
                          h4_rev=rev, h4_candles=df, h4_res=h4res)
    assert htf.trend == st.BULLISH
    assert b.bias == bias.NEUTRAL
    assert any("Retracement" in i for i in b.info)


def test_klarer_daily_bias_wird_nicht_ueberschrieben():
    from tests.test_bias import _bullish_setup
    d, dres, htf = _bullish_setup()
    df, h4res = h4()
    b = bias.compute_bias(htf, dres, d, _report(23.5), LEER,
                          h4_rev=bias.find_h4_reversal(df, h4res),
                          h4_candles=df, h4_res=h4res)
    assert b.mode == "Daily" and b.bias == st.BULLISH and b.confidence == 75
