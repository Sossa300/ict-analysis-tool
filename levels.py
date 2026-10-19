"""
levels.py – Wichtige Preis-Level berechnen: PDH, PDL, PWH, PWL.

  PDH / PDL = Previous Day High / Low   (Hoch/Tief der letzten FERTIGEN Tageskerze)
  PWH / PWL = Previous Week High / Low  (Hoch/Tief der letzten FERTIGEN Wochenkerze)

"Fertig" heißt: Die Kerze hat zum Zeitpunkt as_of bereits geschlossen.
Läuft gerade Dienstag, ist der Vortag Montag. Am Samstag ist der Vortag Freitag.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass
class Level:
    name: str                       # z. B. "PDH"
    price: float                    # Preis des Levels
    formed_at: pd.Timestamp | None  # wann das Hoch/Tief entstand (NY-Zeit)
    period: str                     # z. B. "Mo 13.10.2026" oder "KW 41/2026"
    taken: bool                     # wurde das Level danach schon überschritten?


@dataclass
class LevelReport:
    as_of: pd.Timestamp
    last_price: float
    prev_day: pd.Series             # die Vortageskerze (Open/High/Low/Close/start/end)
    prev_week: pd.Series            # die Vorwochenkerze
    levels: dict[str, Level]        # "PDH", "PDL", "PWH", "PWL"


WOCHENTAGE = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]


def last_completed(candles: pd.DataFrame, as_of: pd.Timestamp) -> pd.Series:
    """Gibt die letzte Kerze zurück, deren Ende <= as_of liegt."""
    done = candles[candles["end"] <= as_of]
    if done.empty:
        raise ValueError("Zu wenig Daten: Es gibt noch keine abgeschlossene Kerze.")
    return done.iloc[-1]


def _finest_intraday(tf: dict[str, pd.DataFrame], since: pd.Timestamp) -> pd.DataFrame | None:
    """Sucht die feinste Intraday-Tabelle, die ab 'since' Daten hat."""
    for key in ("M15", "H1", "H4"):
        df = tf.get(key)
        if df is not None and not df.empty and df.index[0] <= since:
            return df
    return None


def _formed_at(intraday: pd.DataFrame | None, start, end, price: float,
               column: str) -> pd.Timestamp | None:
    """Zeitpunkt der Intraday-Kerze, die das Hoch/Tief gebildet hat."""
    if intraday is None:
        return None
    window = intraday[(intraday.index >= start) & (intraday.index < end)]
    hit = window[window[column] == price]
    return hit.index[0] if not hit.empty else None


def _taken_after(intraday: pd.DataFrame | None, daily: pd.DataFrame, after,
                 as_of, price: float, side: str) -> bool:
    """
    Wurde das Level nach 'after' (bis as_of) schon einmal überschritten?
    side = "high" -> wurde darüber gehandelt?   side = "low" -> darunter?
    """
    src = intraday if intraday is not None else daily.set_index("start")
    window = src[(src.index >= after) & (src.index < as_of)]
    if window.empty:
        return False
    if side == "high":
        return bool(window["High"].max() > price)
    return bool(window["Low"].min() < price)


def compute_levels(tf: dict[str, pd.DataFrame], as_of: pd.Timestamp) -> LevelReport:
    """Berechnet PDH/PDL/PWH/PWL zum Zeitpunkt as_of (NY-Zeit)."""
    daily, weekly = tf["D"], tf["W"]

    pd_row = last_completed(daily, as_of)
    pw_row = last_completed(weekly, as_of)

    day_label = f"{WOCHENTAGE[pd_row.name.weekday()]} {pd_row.name:%d.%m.%Y}"
    iso = pw_row.name.isocalendar()
    week_label = f"KW {iso.week}/{iso.year}"

    intra_d = _finest_intraday(tf, pd_row["start"])
    intra_w = _finest_intraday(tf, pw_row["start"])

    levels = {}
    for name, row, intra, col, side, label in [
        ("PDH", pd_row, intra_d, "High", "high", day_label),
        ("PDL", pd_row, intra_d, "Low",  "low",  day_label),
        ("PWH", pw_row, intra_w, "High", "high", week_label),
        ("PWL", pw_row, intra_w, "Low",  "low",  week_label),
    ]:
        price = float(row[col])
        levels[name] = Level(
            name=name,
            price=price,
            formed_at=_formed_at(intra, row["start"], row["end"], price, col),
            period=label,
            taken=_taken_after(intra, daily, row["end"], as_of, price, side),
        )

    # Letzter bekannter Preis = Close der letzten Kerze vor as_of
    intraday = next((tf[k] for k in ("M15", "H1", "H4") if k in tf), None)
    if intraday is not None:
        last_price = float(intraday[intraday.index < as_of]["Close"].iloc[-1])
    else:
        last_price = float(daily[daily["start"] < as_of]["Close"].iloc[-1])

    return LevelReport(as_of=as_of, last_price=last_price,
                       prev_day=pd_row, prev_week=pw_row, levels=levels)
