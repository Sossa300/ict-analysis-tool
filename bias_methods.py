"""
bias_methods.py – Verbreitete Methoden, einen Daily Bias zu bestimmen,
als feste Regeln (für den Vergleich im Backtest).

Jede Methode bekommt einen MethodContext (nur Daten VOR dem Entscheidungs-
zeitpunkt) und gibt zurück: BULLISH, BEARISH oder None (= kein Signal).

Quellen (Stand Recherche 10/2026, meist Community-Beschreibungen):
  - TTrades Daily Bias / Candle-2-Closure (TradingView-Skript "TTrades Daily Bias [TFO]")
  - ICT Midnight Open / Premium-Discount (LuxAlgo-, TradingView-Beschreibungen)
  - Session-Range-Sweep (Asia/London), SMT-Divergenz (TJR-/ICT-Community)
  - Daily + 4H-Kerze gleichfarbig (Tradesharpe-Skript)
  - Intraday-Momentum (Gao, Han, Li, Zhou: "Intraday Momentum: The First
    Half-Hour Return Predicts the Last Half-Hour Return")
  - Klassiker: Pivot-Punkt, gleitende Durchschnitte, Vortageskerze
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

import config
from structure import BEARISH, BULLISH

BULL, BEAR = BULLISH, BEARISH


@dataclass
class MethodContext:
    h1: pd.DataFrame              # H1-Kerzen, die bis zum Zeitpunkt GESCHLOSSEN sind
    d_done: pd.DataFrame          # abgeschlossene Tageskerzen
    w_done: pd.DataFrame          # abgeschlossene Wochenkerzen
    day: pd.Series                # laufende Tageskerze (bis jetzt)
    week: pd.Series               # laufende Wochenkerze (bis jetzt)
    h4_done: pd.DataFrame         # abgeschlossene H4-Kerzen
    now: pd.Timestamp             # Entscheidungszeitpunkt (NY-Zeit)
    price: float                  # letzter Preis (Schluss der letzten H1-Kerze)
    symbol: str
    tool_bias: str | None = None  # finaler Bias des Tools (oder None bei NEUTRAL)
    tool_daily_trend: str | None = None
    tool_h4_phase: str | None = None
    smt_other: "MethodContext | None" = None   # korreliertes Instrument (für SMT)


def _today(ctx: MethodContext) -> pd.DataFrame:
    """H1-Kerzen des laufenden Handelstages bis jetzt."""
    return ctx.h1[ctx.h1.index >= ctx.day["start"]]


def _color(row) -> str | None:
    if row["Close"] > row["Open"]:
        return BULL
    if row["Close"] < row["Open"]:
        return BEAR
    return None


# ---------------------------------------------------------------------------
# ICT / Smart Money
# ---------------------------------------------------------------------------
def ttrades_candle2(ctx):
    """Schluss über PDH -> bull; unter PDL -> bear; PDH gesweept + Schluss zurück -> bear;
    PDL gesweept + zurück -> bull; Inside Day -> Farbe der Vortageskerze; Outside -> keins."""
    if len(ctx.d_done) < 2:
        return None
    p, p1 = ctx.d_done.iloc[-1], ctx.d_done.iloc[-2]
    if p["Close"] > p1["High"]:
        return BULL
    if p["Close"] < p1["Low"]:
        return BEAR
    sh, sl = p["High"] > p1["High"], p["Low"] < p1["Low"]
    if sh and sl:
        return None
    if sh:
        return BEAR
    if sl:
        return BULL
    return _color(p)


def pd_nur_fortsetzung(ctx):
    if len(ctx.d_done) < 2:
        return None
    p, p1 = ctx.d_done.iloc[-1], ctx.d_done.iloc[-2]
    return BULL if p["Close"] > p1["High"] else BEAR if p["Close"] < p1["Low"] else None


def pd_nur_reversal(ctx):
    if len(ctx.d_done) < 2:
        return None
    p, p1 = ctx.d_done.iloc[-1], ctx.d_done.iloc[-2]
    if p1["Low"] <= p["Close"] <= p1["High"]:
        sh, sl = p["High"] > p1["High"], p["Low"] < p1["Low"]
        if sh and not sl:
            return BEAR
        if sl and not sh:
            return BULL
    return None


def _midnight_open(ctx):
    t = pd.Timestamp(f"{ctx.now.date()} 00:00", tz=config.TZ_NY)
    bar = ctx.h1[ctx.h1.index == t]
    return float(bar["Open"].iloc[0]) if not bar.empty else None


def midnight_discount(ctx):
    """ICT: unter dem Midnight Open = Discount -> bullish; darüber = Premium -> bearish."""
    mo = _midnight_open(ctx)
    if mo is None or ctx.price == mo:
        return None
    return BULL if ctx.price < mo else BEAR


def midnight_momentum(ctx):
    r = midnight_discount(ctx)
    return {BULL: BEAR, BEAR: BULL}.get(r)


def dayopen_discount(ctx):
    """Unter der Tageseröffnung (18:00 bzw. 17:00 NY) -> bullish (Power of 3: Manipulation unter Open)."""
    o = ctx.day["Open"]
    return None if ctx.price == o else (BULL if ctx.price < o else BEAR)


def dayopen_momentum(ctx):
    return {BULL: BEAR, BEAR: BULL}.get(dayopen_discount(ctx))


def weekopen_discount(ctx):
    o = ctx.week["Open"]
    return None if ctx.price == o else (BULL if ctx.price < o else BEAR)


def weekopen_momentum(ctx):
    return {BULL: BEAR, BEAR: BULL}.get(weekopen_discount(ctx))


def _session(ctx, name):
    """Start/Ende einer Session am Tag der Entscheidung (Zeiten aus config.SESSIONS)."""
    import sessions
    return sessions.window(name, ctx.now.tz_convert(config.TZ_BERLIN).date())


def _asia(ctx):
    s, e = _session(ctx, "Asia")
    w = ctx.h1[(ctx.h1.index >= s) & (ctx.h1.index < e)]
    return (float(w["High"].max()), float(w["Low"].min())) if not w.empty else None


def _after_asia(ctx):
    a = _asia(ctx)
    if a is None:
        return None, None
    return a, ctx.h1[ctx.h1.index >= _session(ctx, "Asia")[1]]


def asia_sweep_reversal(ctx):
    """Judas Swing: nur EINE Seite der Asia-Range gesweept, Preis wieder in der Range -> Gegenrichtung."""
    a, after = _after_asia(ctx)
    if a is None or after.empty:
        return None
    hi, lo = a
    sh, sl = after["High"].max() > hi, after["Low"].min() < lo
    if lo <= ctx.price <= hi:
        if sl and not sh:
            return BULL
        if sh and not sl:
            return BEAR
    return None


def asia_breakout(ctx):
    """Einseitiger Ausbruch: nur eine Seite genommen und Preis noch jenseits -> Fortsetzung."""
    a, after = _after_asia(ctx)
    if a is None or after.empty:
        return None
    hi, lo = a
    sh, sl = after["High"].max() > hi, after["Low"].min() < lo
    if sh and not sl and ctx.price > hi:
        return BULL
    if sl and not sh and ctx.price < lo:
        return BEAR
    return None


def london_fortsetzung(ctx):
    """Richtung von London-Open (09:00 Berlin) bis jetzt -> NY setzt fort."""
    t = _session(ctx, "London")[0]
    bar = ctx.h1[ctx.h1.index == t]
    if bar.empty:
        return None
    o = float(bar["Open"].iloc[0])
    return None if ctx.price == o else (BULL if ctx.price > o else BEAR)


def london_umkehr(ctx):
    return {BULL: BEAR, BEAR: BULL}.get(london_fortsetzung(ctx))


def smt_divergenz(ctx):
    """
    Seit Tagesbeginn: Nimmt EIN Instrument das PDL, das korrelierte aber nicht -> bullish.
    Nimmt eins das PDH, das andere nicht -> bearish. (US100 vs. ES, EURUSD vs. GBPUSD)
    """
    o = ctx.smt_other
    if o is None or len(ctx.d_done) < 1 or len(o.d_done) < 1:
        return None
    ta, tb = _today(ctx), _today(o)
    if ta.empty or tb.empty:
        return None
    pa, pb = ctx.d_done.iloc[-1], o.d_done.iloc[-1]
    low_a, low_b = ta["Low"].min() < pa["Low"], tb["Low"].min() < pb["Low"]
    high_a, high_b = ta["High"].max() > pa["High"], tb["High"].max() > pb["High"]
    bull = low_a != low_b
    bear = high_a != high_b
    if bull and not bear:
        return BULL
    if bear and not bull:
        return BEAR
    return None


def dol_naeher(ctx):
    """Draw on Liquidity: Preis läuft zum NÄHEREN, heute noch unberührten Level (PDH oder PDL)."""
    if len(ctx.d_done) < 1:
        return None
    p = ctx.d_done.iloc[-1]
    t = _today(ctx)
    h_open = t.empty or t["High"].max() <= p["High"]
    l_open = t.empty or t["Low"].min() >= p["Low"]
    if h_open and l_open:
        return BULL if (p["High"] - ctx.price) < (ctx.price - p["Low"]) else BEAR
    if h_open:
        return BULL
    if l_open:
        return BEAR
    return None


# ---------------------------------------------------------------------------
# Klassische Methoden
# ---------------------------------------------------------------------------
def vortag_farbe(ctx):
    return _color(ctx.d_done.iloc[-1]) if len(ctx.d_done) else None


def vortag_schlusslage(ctx):
    """Schluss im oberen Drittel der Vortagesrange -> bullish, unteres Drittel -> bearish."""
    if not len(ctx.d_done):
        return None
    p = ctx.d_done.iloc[-1]
    rng = p["High"] - p["Low"]
    if rng <= 0:
        return None
    pos = (p["Close"] - p["Low"]) / rng
    return BULL if pos >= 2 / 3 else BEAR if pos <= 1 / 3 else None


def daily_h4_gleichfarbig(ctx):
    """Vortageskerze und letzte H4-Kerze haben dieselbe Farbe -> diese Richtung."""
    if not len(ctx.d_done) or ctx.h4_done.empty:
        return None
    a, b = _color(ctx.d_done.iloc[-1]), _color(ctx.h4_done.iloc[-1])
    return a if a is not None and a == b else None


def pivot_punkt(ctx):
    if not len(ctx.d_done):
        return None
    p = ctx.d_done.iloc[-1]
    pp = (p["High"] + p["Low"] + p["Close"]) / 3
    return None if ctx.price == pp else (BULL if ctx.price > pp else BEAR)


def _sma(ctx, n):
    if len(ctx.d_done) < n:
        return None
    return float(ctx.d_done["Close"].iloc[-n:].mean())


def sma20(ctx):
    m = _sma(ctx, 20)
    return None if m is None else (BULL if ctx.price > m else BEAR)


def sma50(ctx):
    m = _sma(ctx, 50)
    return None if m is None else (BULL if ctx.price > m else BEAR)


def overnight_momentum(ctx):
    """US100: Bewegung seit RTH-Schluss (16:00 NY am Vortag). Forex: seit Tagesbeginn."""
    if ctx.symbol == "US100":
        t = pd.Timestamp(f"{ctx.day['start'].date()} 16:00", tz=config.TZ_NY)
        bar = ctx.h1[ctx.h1.index == t - pd.Timedelta(hours=1)]   # Kerze 15:00–16:00
        if bar.empty:
            return None
        ref = float(bar["Close"].iloc[0])
    else:
        ref = float(ctx.day["Open"])
    return None if ctx.price == ref else (BULL if ctx.price > ref else BEAR)


def vorwoche_farbe(ctx):
    return _color(ctx.w_done.iloc[-1]) if len(ctx.w_done) else None


def immer_bullish(ctx):
    return BULL


# ---------------------------------------------------------------------------
# Dieses Tool
# ---------------------------------------------------------------------------
def tool_bias(ctx):
    return ctx.tool_bias


def tool_daily_trend(ctx):
    return ctx.tool_daily_trend


def tool_trend_bei_h4_retracement(ctx):
    import structure
    return ctx.tool_daily_trend if ctx.tool_h4_phase == structure.H4_RETRACE else None


# Name -> (Funktion, Gruppe)
METHODS = {
    "TTrades Candle-2-Closure":      (ttrades_candle2, "ICT"),
    "PD nur Fortsetzung":            (pd_nur_fortsetzung, "ICT"),
    "PD nur Reversal":               (pd_nur_reversal, "ICT"),
    "Midnight Open Discount":        (midnight_discount, "ICT"),
    "Midnight Open Momentum":        (midnight_momentum, "ICT"),
    "Tagesopen Discount (Po3)":      (dayopen_discount, "ICT"),
    "Tagesopen Momentum":            (dayopen_momentum, "ICT"),
    "Weekly Open Discount":          (weekopen_discount, "ICT"),
    "Weekly Open Momentum":          (weekopen_momentum, "ICT"),
    "Asia-Sweep Umkehr (Judas)":     (asia_sweep_reversal, "ICT"),
    "Asia-Ausbruch einseitig":       (asia_breakout, "Session"),
    "London-Richtung Fortsetzung":   (london_fortsetzung, "Session"),
    "London-Richtung Umkehr":        (london_umkehr, "Session"),
    "SMT-Divergenz":                 (smt_divergenz, "ICT"),
    "DOL näheres PDH/PDL":           (dol_naeher, "ICT"),
    "Vortag Kerzenfarbe":            (vortag_farbe, "Klassisch"),
    "Vortag Schlusslage":            (vortag_schlusslage, "Klassisch"),
    "Daily+H4 gleichfarbig":         (daily_h4_gleichfarbig, "Klassisch"),
    "Pivot-Punkt":                   (pivot_punkt, "Klassisch"),
    "SMA 20 Tage":                   (sma20, "Klassisch"),
    "SMA 50 Tage":                   (sma50, "Klassisch"),
    "Overnight-Momentum":            (overnight_momentum, "Studie"),
    "Vorwoche Kerzenfarbe":          (vorwoche_farbe, "Klassisch"),
    "Tool: finaler Bias":            (tool_bias, "Tool"),
    "Tool: Daily-Trend":             (tool_daily_trend, "Tool"),
    "Tool: Trend bei H4-Retracement": (tool_trend_bei_h4_retracement, "Tool"),
    "Immer bullish (Vergleich)":     (immer_bullish, "Vergleich"),
}


def predict_all(ctx: MethodContext) -> dict[str, str | None]:
    out = {}
    for name, (fn, _) in METHODS.items():
        try:
            out[name] = fn(ctx)
        except (KeyError, IndexError, ValueError):
            out[name] = None
    return out
