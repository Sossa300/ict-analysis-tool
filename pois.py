"""
pois.py – Points of Interest (POIs): Fair Value Gaps und Order Blocks,
Gewichtung in Stufe A (Daily) und Stufe B (H4 mit Bestätigungen).

Fair Value Gap (FVG) = Preislücke über drei Kerzen:
  Bullish FVG : High von Kerze 1 < Low von Kerze 3   -> Zone High(1) bis Low(3)
  Bearish FVG : Low von Kerze 1 > High von Kerze 3   -> Zone High(3) bis Low(1)

Order Block (OB) = letzte gegenläufige Kerze vor einer impulsiven Bewegung
(Displacement), die Struktur bricht:
  Bullish OB : letzte bearishe Kerze vor der bullishen Displacement-Kerze,
               deren Bewegung danach ein Swing High per Körper bricht.
  Bearish OB : spiegelverkehrt.
  Zone = ganze Kerze (High bis Low).

Displacement = Kerze mit großem Körper (wenig Docht) und deutlich größer als
die Kerzen davor (Grenzwerte in config.py).

Mitigation (wurde die Zone später wieder angelaufen?):
  keine        : Preis war nie wieder in der Zone
  teilweise    : Preis war in der Zone, aber nicht ganz hindurch
  vollständig  : Preis ist ganz durch die Zone gelaufen -> Zone verbraucht

Gewichtung:
  Stufe A : Daily-FVG / Daily-OB (hochwertig)
  Stufe B : H4-FVG / H4-OB, NUR mit Bestätigungen (siehe grade_pois)
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

import config
from structure import BEARISH, BULLISH, StructureBreak, Swing

KEINE, TEILWEISE, VOLLSTAENDIG = "keine", "teilweise", "vollständig"

# Namen der vier H4-Bestätigungen (in dieser Reihenfolge angezeigt)
CHECK_ZONE = "Bias-Richtung + richtiger Bereich"
CHECK_DISP = "Displacement"
CHECK_SWEEP = "Sweep vor Entstehung"
CHECK_DAILY = "Überschneidung mit Daily-POI"
CHECKS = [CHECK_ZONE, CHECK_DISP, CHECK_SWEEP, CHECK_DAILY]


@dataclass
class POI:
    kind: str                     # "FVG" oder "OB"
    direction: str                # BULLISH oder BEARISH
    top: float
    bottom: float
    pos: int                      # FVG: mittlere Kerze; OB: die OB-Kerze
    time: pd.Timestamp
    timeframe: str = ""           # "Daily", "H4", "M15"
    mitigation: str = KEINE
    displacement: bool = False    # durch Displacement entstanden?
    stufe: str | None = None      # "A", "B" oder None (zählt nicht)
    checks: dict[str, bool] = field(default_factory=dict)
    zone: str | None = None       # "Premium" / "Discount" im Daily-Bein
    tradable: bool = False        # laut harten Regeln handelbar?

    @property
    def is_open(self) -> bool:
        """Noch nicht vollständig gefüllt / durchlaufen?"""
        return self.mitigation != VOLLSTAENDIG

    @property
    def mid(self) -> float:
        return (self.top + self.bottom) / 2

    @property
    def n_checks(self) -> int:
        return sum(self.checks.values())

    def distance(self, price: float) -> float:
        """0, wenn der Preis in der Zone ist, sonst Abstand zur nächsten Kante."""
        if self.bottom <= price <= self.top:
            return 0.0
        return min(abs(price - self.top), abs(price - self.bottom))

    def overlaps(self, other: "POI") -> bool:
        return self.bottom < other.top and other.bottom < self.top


# Alter Name, damit bias.py unverändert funktioniert
FVG = POI


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------
def _avg_range(candles: pd.DataFrame) -> np.ndarray:
    """Durchschnittliche Kerzenlänge der VORHERIGEN n Kerzen (ohne Blick nach vorn)."""
    rng = candles["High"] - candles["Low"]
    avg = rng.rolling(config.DISP_AVG_PERIOD, min_periods=3).mean().shift(1)
    return avg.to_numpy()


def is_displacement(candles: pd.DataFrame, i: int, direction: str,
                    avg: np.ndarray | None = None) -> bool:
    """Ist Kerze i eine impulsive Kerze in 'direction'?"""
    if avg is None:
        avg = _avg_range(candles)
    o, h, l, c = (candles[k].iloc[i] for k in ("Open", "High", "Low", "Close"))
    rng = h - l
    if rng <= 0 or np.isnan(avg[i]):
        return False
    richtig = c > o if direction == BULLISH else c < o
    return bool(richtig
                and abs(c - o) >= config.DISP_BODY_RATIO * rng
                and rng >= config.DISP_RANGE_MULT * avg[i])


def mitigation_of(direction: str, top: float, bottom: float,
                  later: pd.DataFrame) -> str:
    """Wie weit wurde eine Zone von den späteren Kerzen angelaufen?"""
    if later.empty:
        return KEINE
    if direction == BULLISH:                 # Zone unter dem Preis, Rücklauf von oben
        lo = later["Low"].min()
        return VOLLSTAENDIG if lo <= bottom else (TEILWEISE if lo < top else KEINE)
    hi = later["High"].max()                 # Zone über dem Preis, Rücklauf von unten
    return VOLLSTAENDIG if hi >= top else (TEILWEISE if hi > bottom else KEINE)


def _later(candles: pd.DataFrame, start: int, extra: pd.DataFrame | None) -> pd.DataFrame:
    """Kerzen ab 'start' plus optionale Extra-Kerzen (z. B. heutige Intraday-Daten)."""
    parts = [candles.iloc[start:][["High", "Low"]]]
    if extra is not None and not extra.empty:
        parts.append(extra[["High", "Low"]])
    return pd.concat(parts) if len(parts) > 1 else parts[0]


# ---------------------------------------------------------------------------
# 1) Fair Value Gaps
# ---------------------------------------------------------------------------
def find_fvgs(candles: pd.DataFrame, timeframe: str = "",
              extra: pd.DataFrame | None = None) -> list[POI]:
    """
    Findet alle FVGs. extra = weitere (z. B. laufende) Kerzen, die nur für
    die Mitigation zählen, nicht für die Erkennung.
    """
    high, low = candles["High"].to_numpy(), candles["Low"].to_numpy()
    avg = _avg_range(candles)
    out: list[POI] = []
    for i in range(1, len(candles) - 1):
        if high[i - 1] < low[i + 1]:
            d, top, bottom = BULLISH, float(low[i + 1]), float(high[i - 1])
        elif low[i - 1] > high[i + 1]:
            d, top, bottom = BEARISH, float(low[i - 1]), float(high[i + 1])
        else:
            continue
        p = POI("FVG", d, top, bottom, i, candles.index[i], timeframe)
        p.displacement = is_displacement(candles, i, d, avg)   # mittlere Kerze
        # Mitigation erst ab der Kerze NACH Kerze 3
        p.mitigation = mitigation_of(d, top, bottom, _later(candles, i + 2, extra))
        out.append(p)
    return out


# ---------------------------------------------------------------------------
# 2) Order Blocks
# ---------------------------------------------------------------------------
def find_order_blocks(candles: pd.DataFrame, breaks: list[StructureBreak],
                      timeframe: str = "",
                      extra: pd.DataFrame | None = None) -> list[POI]:
    """
    Für jeden Strukturbruch (BOS/MSS, aus structure.find_breaks):
      1. Extrempunkt der Bewegung suchen (tiefstes Tief vor einem bullishen Bruch)
      2. erste Displacement-Kerze ab diesem Extrem bis zum Bruch suchen
         -> keine Displacement-Kerze = kein Order Block
      3. letzte gegenläufige Kerze direkt davor = Order Block
    """
    o, c = candles["Open"].to_numpy(), candles["Close"].to_numpy()
    high, low = candles["High"].to_numpy(), candles["Low"].to_numpy()
    avg = _avg_range(candles)
    found: dict[tuple, POI] = {}

    for b in breaks:
        bull = b.direction == BULLISH
        s, j = b.swing.pos, b.pos
        seg_ext = np.argmin(low[s:j + 1]) if bull else np.argmax(high[s:j + 1])
        ext = s + int(seg_ext)

        disp = next((k for k in range(ext, j + 1)
                     if is_displacement(candles, k, b.direction, avg)), None)
        if disp is None:
            continue

        def gegenlaeufig(k):
            return c[k] < o[k] if bull else c[k] > o[k]

        ob = next((k for k in range(disp - 1, max(disp - 1 - config.OB_LOOKBACK, -1), -1)
                   if gegenlaeufig(k)), None)
        if ob is None or (ob, b.direction) in found:
            continue

        p = POI("OB", b.direction, float(high[ob]), float(low[ob]), ob,
                candles.index[ob], timeframe, displacement=True)
        p.mitigation = mitigation_of(p.direction, p.top, p.bottom,
                                     _later(candles, j + 1, extra))
        found[(ob, b.direction)] = p
    return sorted(found.values(), key=lambda p: p.pos)


# ---------------------------------------------------------------------------
# 3) Sweep vor Entstehung (für H4-Bestätigung)
# ---------------------------------------------------------------------------
def swept_before(p: POI, candles: pd.DataFrame, swings: list[Swing],
                 lookback: int = config.H4_SWEEP_LOOKBACK) -> bool:
    """
    Wurde kurz vor der Entstehung des POIs Liquidität geholt?
    Bullish: Das tiefste Tief der letzten 'lookback' Kerzen bis zum POI hat ein
    vorher bestätigtes, noch unberührtes Swing Low unterboten. Bearish: gespiegelt.
    """
    bull = p.direction == BULLISH
    a, e = max(0, p.pos - lookback), min(len(candles), p.pos + 2)
    window = candles.iloc[a:e]
    if window.empty:
        return False
    if bull:
        q = a + int(np.argmin(window["Low"].to_numpy()))
        extreme = candles["Low"].iloc[q]
    else:
        q = a + int(np.argmax(window["High"].to_numpy()))
        extreme = candles["High"].iloc[q]

    kind = "low" if bull else "high"
    for s in swings:
        if s.kind != kind or s.confirmed_pos >= q:
            continue
        genommen = extreme < s.price if bull else extreme > s.price
        if not genommen:
            continue
        # War der Swing vorher schon genommen? Dann war dort keine Liquidität mehr.
        between = candles.iloc[s.pos + 1:q]
        vorher = (between["Low"].min() < s.price if bull
                  else between["High"].max() > s.price) if not between.empty else False
        if not vorher:
            return True
    return False


# ---------------------------------------------------------------------------
# 4) Gewichtung: Stufe A / Stufe B
# ---------------------------------------------------------------------------
def grade_pois(daily_pois: list[POI], h4_pois: list[POI], direction: str,
               leg, h4_candles: pd.DataFrame | None, h4_swings: list[Swing],
               bias_ok: bool) -> None:
    """
    Setzt stufe, checks, zone und tradable (ändert die POIs direkt).

    direction : HTF-Richtung (bullish/bearish)
    leg       : structure.DailyLeg (für Premium/Discount), darf None sein
    bias_ok   : True, wenn es einen Bias gibt (nicht NEUTRAL)

    Harte Regel 1: Ein POI GEGEN die HTF-Richtung ist nie handelbar.
    """
    good_zone = "Discount" if direction == BULLISH else "Premium"

    for p in daily_pois:
        p.stufe = "A"
        p.zone = leg.zone(p.mid) if leg else None
        p.tradable = bias_ok and p.direction == direction and p.is_open

    for p in h4_pois:
        p.zone = leg.zone(p.mid) if leg else None
        p.checks = {
            CHECK_ZONE: p.direction == direction and p.zone == good_zone,
            CHECK_DISP: p.displacement,
            CHECK_SWEEP: (h4_candles is not None
                          and swept_before(p, h4_candles, h4_swings)),
            CHECK_DAILY: any(p.overlaps(q) for q in daily_pois
                             if q.direction == p.direction and q.is_open),
        }
        zaehlt = p.checks[CHECK_ZONE] and p.n_checks >= config.H4_MIN_CONFIRMATIONS
        p.stufe = "B" if zaehlt else None
        p.tradable = bias_ok and zaehlt and p.is_open


def relevant(pois: list[POI], direction: str, price: float,
             limit: int = config.MAX_POIS_SHOWN) -> list[POI]:
    """Offene POIs in HTF-Richtung, die nächsten zuerst."""
    sel = [p for p in pois if p.is_open and p.direction == direction]
    return sorted(sel, key=lambda p: p.distance(price))[:limit]


def m15_entry_hints(m15_fvgs: list[POI], htf_pois: list[POI], direction: str,
                    since: pd.Timestamp) -> list[tuple[POI, POI]]:
    """
    M15-FVGs seit 'since' in HTF-Richtung, die IN einem handelbaren HTF-POI
    liegen. Nur ein Hinweis – Sweep und MSS davor prüfst du selbst.
    Rückgabe: Liste von (M15-FVG, zugehöriger HTF-POI)
    """
    out = []
    for f in m15_fvgs:
        if f.direction != direction or not f.is_open or f.time < since:
            continue
        host = next((h for h in htf_pois if h.tradable and f.overlaps(h)), None)
        if host is not None:
            out.append((f, host))
    return out
