"""
sweeps.py – Sweep-Punkte als BEOBACHTUNGSLISTE.

Das Programm bewertet den Sweep NICHT. Es sagt dir nur:
  - welche Levels als Sweep-Punkt in Frage kommen (PDH/PDL/PWH/PWL,
    später auch Session Highs/Lows),
  - welche davon laut harter Regel 2 zur Daily-Richtung passen,
  - wie weit sie entfernt sind und ob der Preis sie schon erreicht hat.

Ob dort ein sauberer Liquidity Sweep (LQS) entsteht, beurteilst DU selbst im
M15 – dafür gibt das Tool eine Checkliste mit deinen LQS-Kriterien aus.

Ausnahme H4: Für die H4-Führung im Bias (Daily unklar -> H4 entscheidet)
prüft das Tool H4-Sweeps automatisch mit denselben Kriterien (lqs_pattern).

Harte Regel 2:
  Daily bearish -> nur Sweeps von HOCHS gültig (PDH, PWH, Session High)
  Daily bullish -> nur Sweeps von TIEFS gültig (PDL, PWL, Session Low)
  HTF unklar    -> kein Sweep gültig (kein Trade)
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

import config
from structure import BEARISH, BULLISH, UNKLAR

OFFEN = "offen"                          # Preis war noch nicht dort
ANGELAUFEN = "angelaufen (Docht)"        # Docht jenseits, Körper nicht
KOERPER_JENSEITS = "Körper jenseits geschlossen"


@dataclass
class SweepPoint:
    name: str                  # z. B. "PDH"
    price: float
    side: str                  # "high" oder "low"
    valid: bool                # passt zur Daily-Richtung (harte Regel 2)?
    status: str                # OFFEN / ANGELAUFEN / KOERPER_JENSEITS
    distance: float            # Level minus aktueller Preis
    since: pd.Timestamp        # ab wann beobachtet wird (Ende Vortag/Vorwoche/Session)
    relevant: bool = True      # False = z. B. NY PM ("meist irrelevant")

    @property
    def sweep_direction(self) -> str:
        """Ein Sweep über ein Hoch führt zu einem bearishen Setup und umgekehrt."""
        return BEARISH if self.side == "high" else BULLISH


def is_valid_for(side: str, htf_trend: str) -> bool:
    """Harte Regel 2: Passt ein Sweep auf dieser Seite zur HTF-Richtung?"""
    if htf_trend == BEARISH:
        return side == "high"
    if htf_trend == BULLISH:
        return side == "low"
    return False                       # UNKLAR -> nichts ist gültig


def level_status(intraday: pd.DataFrame, price: float, side: str) -> str:
    """Reine Fakten, keine Bewertung: War der Preis schon dort, und wie?"""
    if intraday.empty:
        return OFFEN
    if side == "high":
        wick, body = intraday["High"].max() > price, intraday["Close"].max() > price
    else:
        wick, body = intraday["Low"].min() < price, intraday["Close"].min() < price
    if body:
        return KOERPER_JENSEITS
    return ANGELAUFEN if wick else OFFEN


def watchlist(report, htf_trend: str, intraday: pd.DataFrame,
              as_of: pd.Timestamp, ranges: list | None = None) -> list[SweepPoint]:
    """
    Baut die Beobachtungsliste aus PDH/PDL/PWH/PWL und den Session Highs/Lows.
    report   = levels.LevelReport
    intraday = abgeschlossene Intraday-Kerzen (z. B. M15) für den Status
    ranges   = sessions.SessionRange-Liste (letzte abgeschlossene je Session)
    Sortierung: gültige + relevante Punkte zuerst, dann nach Abstand zum Preis.
    """
    raw = [
        ("PDH", report.levels["PDH"].price, "high", report.prev_day["end"], True),
        ("PDL", report.levels["PDL"].price, "low", report.prev_day["end"], True),
        ("PWH", report.levels["PWH"].price, "high", report.prev_week["end"], True),
        ("PWL", report.levels["PWL"].price, "low", report.prev_week["end"], True),
    ]
    for r in ranges or []:
        raw.append((f"{r.name} High", r.high, "high", r.end, r.relevant))
        raw.append((f"{r.name} Low", r.low, "low", r.end, r.relevant))

    points = []
    for name, price, side, since, relevant in raw:
        window = intraday[(intraday.index >= since) & (intraday.index < as_of)]
        points.append(SweepPoint(
            name=name,
            price=price,
            side=side,
            valid=is_valid_for(side, htf_trend),
            status=level_status(window, price, side),
            distance=price - report.last_price,
            since=since,
            relevant=relevant,
        ))
    return sorted(points, key=lambda p: (not p.valid, not p.relevant, abs(p.distance)))


# ---------------------------------------------------------------------------
# LQS-Muster für die AUTOMATISCHE H4-Prüfung (H4-Führung im Bias)
# ---------------------------------------------------------------------------
# Programmiert wird nur der Fall "Hoch-Sweep" (bearisher LQS). Für Tief-Sweeps
# spiegeln wir die Kerzen (alle Preise mal -1): aus einem Tief wird ein Hoch.
MUSTER_A, MUSTER_B = "Ablehnungskerze", "2-Kerzen-Umkehr"


def is_rejection_candle(o, h, l, c, level) -> bool:
    """(a) Docht über das Level, Schluss darunter, kleiner bearisher Körper, langer oberer Docht."""
    rng = h - l
    if rng <= 0 or h <= level or c > level:
        return False
    if c > o or (c == o and not config.LQS_ALLOW_DOJI):
        return False
    body, wick = abs(c - o), h - max(o, c)
    return (body <= config.LQS_MAX_BODY_RATIO * rng
            and wick >= config.LQS_MIN_WICK_RATIO * rng
            and wick >= config.LQS_WICK_TO_BODY * body)


def is_two_candle_reversal(c1, c2, level) -> bool:
    """(b) Bullisher Körper, danach mind. gleich großer bearisher Körper, Schluss unter dem Level."""
    o1, h1, _, k1 = c1
    o2, h2, _, k2 = c2
    return (k1 > o1 and max(h1, h2) > level and k2 < o2
            and abs(k2 - o2) >= abs(k1 - o1) and k2 <= level)


def lqs_pattern(candles: pd.DataFrame, i: int, level: float, side: str,
                last: int | None = None) -> tuple[str, int, int] | None:
    """
    Ist an Kerze i ein LQS am Level entstanden?
    side = "high" (Sweep über ein Hoch) oder "low" (Sweep unter ein Tief).
    last = letzte erlaubte Kerze für Muster (b) (z. B. die MSS-Kerze).
    Rückgabe: (Muster, erste Kerze, letzte Kerze des Musters) oder None.
    """
    last = len(candles) - 1 if last is None else last

    def row(k):
        o, h, l, c = (float(candles[x].iloc[k]) for x in ("Open", "High", "Low", "Close"))
        return (o, h, l, c) if side == "high" else (-o, -l, -h, -c)

    lv = level if side == "high" else -level
    cur = row(i)
    if is_rejection_candle(*cur, lv):
        return MUSTER_A, i, i
    if i > 0 and is_two_candle_reversal(row(i - 1), cur, lv):
        return MUSTER_B, i - 1, i
    if i + 1 <= last and is_two_candle_reversal(cur, row(i + 1), lv):
        return MUSTER_B, i, i + 1
    return None


def m15_checklist(htf_trend: str) -> list[str]:
    """Deine LQS-Kriterien zum Abhaken im M15 – passend zur Richtung."""
    if htf_trend == UNKLAR:
        return ["HTF-Trend unklar -> heute keinen Sweep suchen"]
    bear = htf_trend == BEARISH
    seite = ("über ein gültiges Hoch (PDH/PWH/Session High)" if bear
             else "unter ein gültiges Tief (PDL/PWL/Session Low)")
    unsere, gegen = ("bearish", "bullish") if bear else ("bullish", "bearish")
    docht = "oberer" if bear else "unterer"
    return [
        f"Preis sticht {seite} (Docht jenseits des Levels)",
        "Starke Ablehnung der anderen Seite – eins von beiden:",
        f"    a) kleiner {unsere}er Körper + langer {docht} Docht",
        f"    b) {gegen}er Körper, danach mind. gleich großer {unsere}er Körper",
        "Schluss wieder auf der richtigen Seite des Levels",
        f"Danach MSS {('nach unten' if bear else 'nach oben')} per Kerzenkörper",
        "FVG aus dieser Bewegung als möglicher Entry-Bereich",
    ]
