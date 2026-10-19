"""
Tests für Schritt 2: Swings, BOS, MSS und HTF-Trend.

Der Beispiel-Kursverlauf (20 Tageskerzen) ist so gebaut, dass wir genau
wissen, was herauskommen muss:

  Kerze  3: Swing High 15   (bestätigt bei Kerze 5)
  Kerze  6: Swing Low   9   (bestätigt bei Kerze 8)
  Kerze  8: Schluss 15,5 > 15        -> BOS bullish
  Kerze 10: Swing High 20   (bestätigt bei Kerze 12)
  Kerze 13: Swing Low  14   (bestätigt bei Kerze 15)
  Kerze 14: Schluss 20,5 > 20        -> BOS bullish
  Kerze 16: Swing High 23   (bestätigt bei Kerze 18)
  Kerze 19: Schluss 13,5 < 14        -> MSS bearish (Trendwechsel)
"""

import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import structure as st  # noqa: E402

#          High  Low  Close
PFAD = [
    (10,  8,    9),     # 0
    (11,  9,   10),     # 1
    (12, 10,   11),     # 2
    (15, 12,   14),     # 3  Swing High 15
    (14, 11,   12),     # 4
    (13, 10,   11),     # 5
    (12,  9,   10),     # 6  Swing Low 9
    (13,  9.5, 12),     # 7
    (16, 12,   15.5),   # 8  BOS bullish
    (18, 15,   17),     # 9
    (20, 17,   19),     # 10 Swing High 20
    (19, 16,   17),     # 11
    (18, 15,   16),     # 12
    (17, 14,   15),     # 13 Swing Low 14
    (21, 16,   20.5),   # 14 BOS bullish
    (22, 18,   21),     # 15
    (23, 19,   22),     # 16 Swing High 23
    (22, 18,   19),     # 17
    (20, 15,   16),     # 18
    (18, 13,   13.5),   # 19 MSS bearish
]


def kerzen(pfad=PFAD):
    idx = pd.bdate_range("2026-09-01", periods=len(pfad))
    df = pd.DataFrame(pfad, columns=["High", "Low", "Close"], index=idx)
    df["Open"] = df["Close"].shift(1).fillna(df["Low"])
    return df


# --- Swings -----------------------------------------------------------------
def test_swings_werden_richtig_erkannt():
    sw = st.find_swings(kerzen(), n=2)
    highs = [(s.pos, s.price) for s in sw if s.kind == "high"]
    lows = [(s.pos, s.price) for s in sw if s.kind == "low"]
    assert highs == [(3, 15), (10, 20), (16, 23)]
    assert lows == [(6, 9), (13, 14)]


def test_swing_erst_nach_n_kerzen_bestaetigt():
    sw = st.find_swings(kerzen(), n=2)
    assert sw[0].pos == 3 and sw[0].confirmed_pos == 5
    # Ohne die 2 Kerzen rechts davon gibt es den Swing noch nicht
    assert st.find_swings(kerzen()[:5], n=2) == []


def test_swing_laenge_ist_einstellbar():
    sw = st.find_swings(kerzen(), n=3)
    assert all(s.confirmed_pos == s.pos + 3 for s in sw)
    # Mit n=3 braucht der Swing bei Kerze 3 drei Kerzen rechts (4, 5, 6)
    assert st.find_swings(kerzen()[:6], n=3) == []
    assert [s.pos for s in st.find_swings(kerzen()[:7], n=3)] == [3]


def test_equal_highs_nur_ein_swing():
    pfad = [(10, 8, 9), (11, 9, 10), (15, 12, 14), (15, 12, 13),
            (12, 10, 11), (11, 9, 10)]
    highs = [s.pos for s in st.find_swings(kerzen(pfad), n=2) if s.kind == "high"]
    assert highs == [2]


# --- BOS / MSS --------------------------------------------------------------
def test_bos_und_mss():
    df = kerzen()
    br = st.find_breaks(df, st.find_swings(df, 2))
    assert [(b.kind, b.direction, b.pos, b.level) for b in br] == [
        ("BOS", st.BULLISH, 8, 15),
        ("BOS", st.BULLISH, 14, 20),
        ("MSS", st.BEARISH, 19, 14),
    ]


def test_trend_vor_und_nach_dem_mss():
    assert st.analyze(kerzen()[:19], "Daily", n=2).trend == st.BULLISH
    res = st.analyze(kerzen(), "Daily", n=2)
    assert res.trend == st.BEARISH
    assert any("frisch" in r for r in res.reasons)


def test_nur_docht_ist_nie_ein_bruch():
    pfad = list(PFAD[:9])
    pfad[8] = (16, 12, 14.5)          # Docht über 15, Körper schließt darunter
    df = kerzen(pfad)
    assert st.find_breaks(df, st.find_swings(df, 2)) == []


def test_docht_bricht_auch_keinen_mss():
    # Kerze 19 nur mit Docht unter das Swing Low 14, Schluss darüber
    pfad = list(PFAD)
    pfad[19] = (18, 13, 14.5)
    df = kerzen(pfad)
    br = st.find_breaks(df, st.find_swings(df, 2))
    assert [b.kind for b in br] == ["BOS", "BOS"]       # kein MSS
    assert st.analyze(df, "Daily", n=2).trend == st.BULLISH


def test_ohne_bruch_ist_trend_unklar():
    res = st.analyze(kerzen()[:8], "Daily", n=2)
    assert res.trend == st.UNKLAR


# --- Kerzen-MSS ---------------------------------------------------------------
# Im PFAD (bullish nach BOS bei Kerze 8) macht Kerze 10 das höchste Hoch (20),
# ihr Tief ist 17. Kerze 12 schließt bei 16 < 17 -> Kerzen-MSS nach unten.
def test_kerzen_mss_bei_schluss_unter_tief_der_high_kerze():
    df = kerzen()
    br = st.find_breaks(df, st.find_swings(df, 2), candle_mss=True)
    mss = br[1]
    assert (mss.kind, mss.direction, mss.pos, mss.source) == ("MSS", st.BEARISH, 12, "kerze")
    assert mss.level == 17 and mss.swing.pos == 10


def test_kerzen_mss_nur_per_koerper():
    pfad = list(PFAD)
    pfad[12] = (18, 15, 17.5)            # Docht unter 17, Körper schließt darüber
    df = kerzen(pfad)
    br = st.find_breaks(df, st.find_swings(df, 2), candle_mss=True)
    assert br[1].pos == 13               # erst Kerze 13 schließt unter 17 (15)


def test_kerzen_mss_ausgeschaltet():
    df = kerzen()
    br = st.find_breaks(df, st.find_swings(df, 2), candle_mss=False)
    assert all(b.source == "swing" for b in br)


def test_kerzen_mss_gespiegelt_wie_eurusd():
    # Gespiegelter PFAD: bearish, Kerze 10 macht das tiefste Tief (40-20 = 20),
    # ihr Hoch ist 40-17 = 23. Kerze 12 schließt bei 24 > 23 -> MSS nach oben.
    pfad = [(40 - lo, 40 - hi, 40 - c) for hi, lo, c in PFAD]
    df = kerzen(pfad)
    br = st.find_breaks(df, st.find_swings(df, 2), candle_mss=True)
    mss = next(b for b in br if b.source == "kerze")
    assert (mss.direction, mss.pos, mss.level, mss.swing.pos) == (st.BULLISH, 12, 23, 10)


def test_protected_low_nach_kerzen_mss_ist_das_tief():
    pfad = [(40 - lo, 40 - hi, 40 - c) for hi, lo, c in PFAD][:13]
    df = kerzen(pfad)
    res = st.analyze(df, "Daily", n=2, candle_mss=True)
    assert res.trend == st.BULLISH and res.last_break.source == "kerze"
    leg = st.daily_leg(df, res)
    assert leg.protected == 20 and leg.protected_time == df.index[10]


# --- Daily-Bein (Dealing Range) ---------------------------------------------
# Mit den Kerzen 0..18 ist der Daily bullish (letzter Bruch: BOS bei Kerze 14,
# gebrochener Swing High 20 bei Kerze 10).
#   Protected Low = tiefstes Tief zwischen Kerze 10 und 14 = 14 (Kerze 13)
#   Bein-Hoch     = höchstes Hoch ab Kerze 14             = 23 (Kerze 16)
#   Equilibrium   = (14 + 23) / 2 = 18,5
#   Retracement   = tiefstes Tief nach Kerze 16 = 15 -> Tiefe (23-15)/9 = 89 %
def _daily_bullish():
    df = kerzen()[:19]
    return df, st.analyze(df, "Daily", n=2)


def test_daily_bein_bullish():
    df, res = _daily_bullish()
    leg = st.daily_leg(df, res)
    assert (leg.protected, leg.extreme) == (14, 23)
    assert leg.protected_time == df.index[13]
    assert leg.equilibrium == 18.5
    assert leg.retrace_extreme == 15
    assert round(leg.retrace_depth(), 2) == 0.89
    assert leg.zone(16) == "Discount" and leg.zone(21) == "Premium"
    assert leg.invalidated is False


def test_protected_low_verletzt_ohne_mss():
    # Bruch bei Kerze 6, das Tief (9) davor ist noch kein bestätigter Swing.
    # Kerze 7 schließt darunter -> kein MSS, aber Struktur verletzt.
    pfad = [(10, 8, 9), (11, 9, 10), (15, 12, 14), (14, 11, 12),
            (13, 10, 11), (12, 9, 10), (16, 11, 15.5), (15, 8.5, 8.8)]
    df = kerzen(pfad)
    res = st.analyze(df, "Daily", n=2)
    assert res.trend == st.BULLISH            # laut letztem Bruch noch bullish ...
    htf = st.htf_trend(res, df, None, last_price=8.8)
    assert htf.leg.invalidated is True        # ... aber Protected Low gebrochen
    assert htf.trend == st.UNKLAR


# --- HTF-Trend: Daily + H4 --------------------------------------------------
def _h4(trend, kind):
    """Künstliches H4-Ergebnis mit einem einzigen Bruch."""
    dummy = st.Swing("high", 0, None, 0.0, 0)
    br = [st.StructureBreak(kind, trend, 0, None, 0.0, dummy)]
    return st.TrendResult("H4", trend, [], br)


def test_daily_entscheidet_weekly_egal():
    df, res = _daily_bullish()
    weekly = st.TrendResult("Weekly", st.BEARISH)
    htf = st.htf_trend(res, df, _h4(st.BULLISH, "BOS"), 16, weekly_res=weekly)
    assert htf.trend == st.BULLISH
    assert htf.h4_phase == st.H4_MIT_DAILY


def test_h4_gegen_daily_ist_retracement_kein_widerspruch():
    df, res = _daily_bullish()
    htf = st.htf_trend(res, df, _h4(st.BEARISH, "MSS"), last_price=16)
    assert htf.trend == st.BULLISH            # Daily bleibt die Richtung
    assert htf.h4_phase == st.H4_RETRACE
    assert htf.zone == "Discount"
    assert any("Discount" in r and "erreicht" in r for r in htf.reasons_pro)


def test_h4_retracement_noch_im_premium():
    df, res = _daily_bullish()
    htf = st.htf_trend(res, df, _h4(st.BEARISH, "BOS"), last_price=21)
    assert htf.trend == st.BULLISH
    assert htf.h4_phase == st.H4_RETRACE
    assert any("noch nicht erreicht" in r for r in htf.reasons_contra)


def test_h4_mss_zurueck_beendet_retracement():
    df, res = _daily_bullish()
    htf = st.htf_trend(res, df, _h4(st.BULLISH, "MSS"), last_price=17)
    assert htf.h4_phase == st.H4_RETRACE_ENDE


def test_tiefe_des_beendeten_retracements():
    # H4: Bruch gegen Daily bei Kerze 17, MSS zurück bei Kerze 18.
    # Tiefster Punkt dazwischen = 15 -> (23 - 15) / (23 - 14) = 89 %
    df, res = _daily_bullish()
    dummy = st.Swing("low", 0, None, 0.0, 0)
    h4 = st.TrendResult("H4", st.BULLISH, [], [
        st.StructureBreak("MSS", st.BEARISH, 17, None, 0.0, dummy),
        st.StructureBreak("MSS", st.BULLISH, 18, None, 0.0, dummy),
    ])
    htf = st.htf_trend(res, df, h4, last_price=17, h4_candles=kerzen())
    assert htf.h4_phase == st.H4_RETRACE_ENDE
    assert any("89%" in r for r in htf.reasons_pro)
    assert not any("nicht erreicht" in r for r in htf.reasons_contra)


def test_daily_unklar_heisst_kein_trade():
    df = kerzen()[:8]
    htf = st.htf_trend(st.analyze(df, "Daily", n=2), df, _h4(st.BULLISH, "BOS"), 10)
    assert htf.trend == st.UNKLAR
