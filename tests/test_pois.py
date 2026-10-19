"""
Tests für Modul 2: Displacement, Order Blocks, Sweep-Bestätigung, Stufe A/B.
Jede Kerze wird als (Open, High, Low, Close) angegeben.
"""

import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pois  # noqa: E402
import structure as st  # noqa: E402


def ohlc(rows, freq="4h"):
    idx = pd.date_range("2026-10-05 18:00", periods=len(rows), freq=freq,
                        tz="America/New_York")
    return pd.DataFrame(rows, columns=["Open", "High", "Low", "Close"], index=idx)


# Bullisher Order Block:
#   Kerze 2: Swing High 12 (bestätigt bei Kerze 4)
#   Kerze 5: letzte BEARISHE Kerze vor dem Impuls -> Order Block 9,4–10,4
#   Kerze 6: bullishe Displacement-Kerze, Schluss 12,6 > 12 -> BOS
#   Außerdem: Kerze 5 High 10,4 < Kerze 7 Low 12,2 -> bullishes FVG 10,4–12,2
OB_PFAD = [
    (10.0, 10.5, 9.5, 10.2),    # 0
    (10.2, 11.0, 10.0, 10.8),   # 1
    (10.8, 12.0, 10.6, 11.5),   # 2  Swing High 12
    (11.5, 11.6, 10.6, 10.8),   # 3
    (10.8, 11.0, 10.0, 10.2),   # 4
    (10.2, 10.4, 9.4, 9.6),     # 5  bearish -> Order Block
    (9.6, 12.8, 9.5, 12.6),     # 6  Displacement + BOS
    (12.6, 13.0, 12.2, 12.8),   # 7
]


def _ob(rows):
    df = ohlc(rows)
    breaks = st.find_breaks(df, st.find_swings(df, 2))
    return df, breaks, pois.find_order_blocks(df, breaks, "H4")


# --- Displacement -----------------------------------------------------------
def test_displacement_erkannt():
    df = ohlc(OB_PFAD)
    assert pois.is_displacement(df, 6, st.BULLISH) is True
    assert pois.is_displacement(df, 6, st.BEARISH) is False   # falsche Richtung
    assert pois.is_displacement(df, 1, st.BULLISH) is False   # normale Kerze


def test_grosse_kerze_mit_viel_docht_ist_kein_displacement():
    rows = list(OB_PFAD)
    rows[6] = (9.6, 12.8, 9.5, 10.6)        # groß, aber Körper nur 1,0 von 3,3
    assert pois.is_displacement(ohlc(rows), 6, st.BULLISH) is False


# --- Order Block ------------------------------------------------------------
def test_bullisher_order_block():
    df, breaks, obs = _ob(OB_PFAD)
    assert [(b.kind, b.pos) for b in breaks] == [("BOS", 6)]
    assert len(obs) == 1
    ob = obs[0]
    assert (ob.direction, ob.pos, ob.bottom, ob.top) == (st.BULLISH, 5, 9.4, 10.4)
    assert ob.displacement and ob.mitigation == pois.KEINE


def test_kein_order_block_ohne_displacement():
    rows = list(OB_PFAD)
    rows[6] = (11.8, 12.3, 11.7, 12.1)      # kleine Kerze bricht knapp -> kein Impuls
    _, breaks, obs = _ob(rows)
    assert breaks                            # Struktur ist gebrochen ...
    assert obs == []                         # ... aber ohne Displacement kein OB


def test_order_block_mitigation():
    _, _, obs = _ob(OB_PFAD + [(12.8, 13.0, 10.0, 10.5)])   # läuft in den OB
    assert obs[0].mitigation == pois.TEILWEISE
    _, _, obs = _ob(OB_PFAD + [(12.8, 13.0, 9.3, 9.5)])     # läuft durch
    assert obs[0].mitigation == pois.VOLLSTAENDIG


def test_bearisher_order_block_gespiegelt():
    # Alle Preise an 20 spiegeln: aus Hochs werden Tiefs, Open/Close tauschen Rolle
    rows = [(20 - o, 20 - l, 20 - h, 20 - c) for o, h, l, c in OB_PFAD]
    _, breaks, obs = _ob(rows)
    assert breaks[0].direction == st.BEARISH
    ob = obs[0]
    assert (ob.direction, ob.pos) == (st.BEARISH, 5)
    assert (round(ob.bottom, 6), round(ob.top, 6)) == (9.6, 10.6)


def test_fvg_durch_displacement():
    fvgs = pois.find_fvgs(ohlc(OB_PFAD), "H4")
    f = next(x for x in fvgs if x.pos == 6)
    assert (f.direction, f.bottom, f.top, f.displacement) == (st.BULLISH, 10.4, 12.2, True)


# --- Sweep vor Entstehung ---------------------------------------------------
#   Kerze 2: Swing Low 10 (bestätigt bei Kerze 4)
#   Kerze 6: Tief 9,5 unterbietet das Swing Low -> Liquidität geholt
#   POI bei Kerze 7
SWEEP_PFAD = [
    (11.5, 12.0, 11.0, 11.2),   # 0
    (11.2, 12.0, 10.5, 10.8),   # 1
    (10.8, 11.5, 10.0, 11.2),   # 2  Swing Low 10
    (11.2, 12.0, 10.8, 11.8),   # 3
    (11.8, 12.5, 11.0, 11.2),   # 4
    (11.2, 12.0, 10.6, 10.8),   # 5
    (10.8, 11.0, 9.5, 10.9),    # 6  Sweep unter 10
    (10.9, 13.0, 10.8, 12.9),   # 7
    (12.9, 13.5, 12.5, 13.2),   # 8
]


def _poi_bei_7():
    return pois.POI("FVG", st.BULLISH, 12.5, 11.0, 7, None, "H4")


def test_sweep_vor_entstehung():
    df = ohlc(SWEEP_PFAD)
    assert pois.swept_before(_poi_bei_7(), df, st.find_swings(df, 2)) is True


def test_kein_sweep_wenn_tief_nicht_unterboten():
    rows = list(SWEEP_PFAD)
    rows[6] = (10.8, 11.0, 10.2, 10.9)      # Tief 10,2 bleibt über dem Swing Low 10
    df = ohlc(rows)
    assert pois.swept_before(_poi_bei_7(), df, st.find_swings(df, 2)) is False


# --- Stufe A / B ------------------------------------------------------------
# Daily-Bein bullish: Protected Low 10, Hoch 20 -> Equilibrium 15
LEG = st.DailyLeg(st.BULLISH, 10.0, None, 20.0, None, None, False)


def _h4(direction=st.BULLISH, top=13.0, bottom=12.0, disp=True):
    return pois.POI("OB", direction, top, bottom, 0, None, "H4", displacement=disp)


def _daily(top=14.0, bottom=12.5):
    return pois.POI("FVG", st.BULLISH, top, bottom, 0, None, "Daily")


def test_daily_poi_ist_stufe_a():
    d = _daily()
    pois.grade_pois([d], [], st.BULLISH, LEG, None, [], bias_ok=True)
    assert d.stufe == "A" and d.tradable and d.zone == "Discount"


def test_h4_mit_3_bestaetigungen_ist_stufe_b():
    h = _h4()
    pois.grade_pois([_daily()], [h], st.BULLISH, LEG, None, [], bias_ok=True)
    assert h.checks == {pois.CHECK_ZONE: True, pois.CHECK_DISP: True,
                        pois.CHECK_SWEEP: False, pois.CHECK_DAILY: True}
    assert h.n_checks == 3 and h.stufe == "B" and h.tradable


def test_h4_mit_zu_wenig_bestaetigungen_zaehlt_nicht():
    h = _h4(disp=False)                      # nur Zone + Daily = 2/4
    pois.grade_pois([_daily()], [h], st.BULLISH, LEG, None, [], bias_ok=True)
    assert h.n_checks == 2 and h.stufe is None and not h.tradable


def test_h4_im_falschen_bereich_zaehlt_nie():
    # Bullisher POI im PREMIUM (17–18): Pflicht-Bestätigung fehlt
    h = _h4(top=18.0, bottom=17.0)
    d = _daily(top=18.5, bottom=16.5)
    pois.grade_pois([d], [h], st.BULLISH, LEG, None, [], bias_ok=True)
    assert h.n_checks == 2 and h.stufe is None


def test_poi_gegen_htf_nie_handelbar():
    d = pois.POI("FVG", st.BEARISH, 14.0, 13.0, 0, None, "Daily")
    h = _h4(direction=st.BEARISH)
    pois.grade_pois([d], [h], st.BULLISH, LEG, None, [], bias_ok=True)
    assert not d.tradable and not h.tradable


def test_ohne_bias_nichts_handelbar():
    d, h = _daily(), _h4()
    pois.grade_pois([d], [h], st.BULLISH, LEG, None, [], bias_ok=False)
    assert d.stufe == "A" and not d.tradable
    assert h.stufe == "B" and not h.tradable


def test_relevant_sortiert_nach_abstand_und_filtert():
    near = _daily(top=14.0, bottom=13.0)
    far = _daily(top=11.0, bottom=10.5)
    done = _daily(top=12.0, bottom=11.5)
    done.mitigation = pois.VOLLSTAENDIG
    wrong = pois.POI("FVG", st.BEARISH, 15.0, 14.5, 0, None, "Daily")
    assert pois.relevant([far, done, wrong, near], st.BULLISH, 14.5) == [near, far]


def test_m15_hinweis_nur_in_handelbarem_poi():
    host = _daily()
    host.tradable = True
    t0 = pd.Timestamp("2026-10-14 09:30", tz="America/New_York")
    inside = pois.POI("FVG", st.BULLISH, 13.2, 13.0, 0, t0, "M15")
    outside = pois.POI("FVG", st.BULLISH, 16.0, 15.5, 0, t0, "M15")
    old = pois.POI("FVG", st.BULLISH, 13.2, 13.0, 0, t0 - pd.Timedelta(days=1), "M15")
    hints = pois.m15_entry_hints([inside, outside, old], [host], st.BULLISH, t0)
    assert hints == [(inside, host)]
