"""
Tests für bias_methods.py – prüft, ob jede wichtige Regel wie beschrieben greift.
"""

import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import bias_methods as bm  # noqa: E402

TZ = "America/New_York"
NOW = pd.Timestamp("2026-10-14 09:00", tz=TZ)


def ny(s):
    return pd.Timestamp(s, tz=TZ)


def days(*hlco):
    """Tageskerzen als (High, Low, Close, Open)."""
    idx = pd.bdate_range("2026-10-08", periods=len(hlco))
    return pd.DataFrame(hlco, columns=["High", "Low", "Close", "Open"], index=idx)


def h1(bars):
    """bars: {Zeit: (Open, High, Low, Close)}"""
    idx = [ny(t) for t in bars]
    return pd.DataFrame(list(bars.values()), columns=["Open", "High", "Low", "Close"],
                        index=pd.DatetimeIndex(idx))


def ctx(d_done=None, bars=None, price=100.0, day_open=100.0, week_open=100.0, other=None):
    bars = bars or {"2026-10-14 08:00": (100, 100, 100, price)}
    return bm.MethodContext(
        h1=h1(bars), d_done=d_done if d_done is not None else days((110, 100, 105, 102)),
        w_done=days((110, 90, 100, 95)),
        day=pd.Series({"start": ny("2026-10-13 18:00"), "Open": day_open}),
        week=pd.Series({"Open": week_open}),
        h4_done=pd.DataFrame(columns=["Open", "High", "Low", "Close"]),
        now=NOW, price=price, symbol="US100", smt_other=other)


# --- TTrades Candle-2-Closure ----------------------------------------------
def test_ttrades_regeln():
    f = bm.ttrades_candle2
    # Tag davor: High 110, Low 100
    assert f(ctx(days((110, 100, 105, 102), (115, 104, 112, 106)))) == bm.BULL   # Schluss > PDH
    assert f(ctx(days((110, 100, 105, 102), (106, 95, 98, 104)))) == bm.BEAR     # Schluss < PDL
    assert f(ctx(days((110, 100, 105, 102), (112, 103, 107, 104)))) == bm.BEAR   # PDH-Sweep zurück
    assert f(ctx(days((110, 100, 105, 102), (106, 98, 104, 101)))) == bm.BULL    # PDL-Sweep zurück
    assert f(ctx(days((110, 100, 105, 102), (108, 102, 107, 103)))) == bm.BULL   # Inside, grün
    assert f(ctx(days((110, 100, 105, 102), (112, 98, 104, 105)))) is None       # Outside


# --- Midnight Open / Tagesopen ---------------------------------------------
def test_midnight_open():
    bars = {"2026-10-14 00:00": (100, 101, 99, 100.5), "2026-10-14 08:00": (99, 99, 98, 98.5)}
    assert bm.midnight_discount(ctx(bars=bars, price=98.5)) == bm.BULL      # unter Open
    assert bm.midnight_momentum(ctx(bars=bars, price=98.5)) == bm.BEAR
    assert bm.midnight_discount(ctx(bars=bars, price=101.0)) == bm.BEAR


def test_tagesopen_und_weekly_open():
    assert bm.dayopen_discount(ctx(price=99, day_open=100)) == bm.BULL
    assert bm.weekopen_momentum(ctx(price=99, week_open=100)) == bm.BEAR


# --- Asia-Range ---------------------------------------------------------------
ASIA = {"2026-10-13 20:00": (102, 105, 101, 103), "2026-10-13 23:00": (103, 104, 100, 101)}


def test_asia_sweep_umkehr():
    # Asia: High 105, Low 100. London sticht auf 99 (nur unten), Preis zurück auf 101
    bars = dict(ASIA, **{"2026-10-14 03:00": (101, 101.5, 99, 100.5),
                         "2026-10-14 08:00": (100.5, 101.2, 100.4, 101)})
    assert bm.asia_sweep_reversal(ctx(bars=bars, price=101)) == bm.BULL
    assert bm.asia_breakout(ctx(bars=bars, price=101)) is None


def test_asia_ausbruch():
    bars = dict(ASIA, **{"2026-10-14 03:00": (104, 107, 103.5, 106.5)})
    assert bm.asia_breakout(ctx(bars=bars, price=106.5)) == bm.BULL
    assert bm.asia_sweep_reversal(ctx(bars=bars, price=106.5)) is None


# --- SMT-Divergenz -------------------------------------------------------------
def test_smt_divergenz():
    # Vortag beider Instrumente: Low 100. A fällt heute auf 99 (PDL genommen), B nur auf 101.
    a_bars = {"2026-10-13 20:00": (102, 103, 99, 101)}
    b_bars = {"2026-10-13 20:00": (102, 103, 101, 102)}
    b = ctx(bars=b_bars)
    a = ctx(bars=a_bars, other=b)
    assert bm.smt_divergenz(a) == bm.BULL
    # Beide nehmen das PDL -> keine Divergenz
    assert bm.smt_divergenz(ctx(bars=a_bars, other=ctx(bars=a_bars))) is None


# --- DOL ---------------------------------------------------------------------
def test_dol_naeheres_level():
    # Vortag High 110, Low 100: Preis 108 -> PDH näher -> bullish
    assert bm.dol_naeher(ctx(price=108)) == bm.BULL
    assert bm.dol_naeher(ctx(price=102)) == bm.BEAR


def test_alle_methoden_laufen_ohne_fehler():
    preds = bm.predict_all(ctx())
    assert set(preds) == set(bm.METHODS)
    assert all(v in (bm.BULL, bm.BEAR, None) for v in preds.values())
