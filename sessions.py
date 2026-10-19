"""
sessions.py – Session Highs/Lows und Power of 3.

Sessions (Zeiten in config.SESSIONS, jede in der Zeitzone ihres Marktes):
  Asia 00–06 Berlin, London 09–11 Berlin, NY Pre-Market 08:30–09:30 NY,
  NY AM 09:30–11:00 NY, NY PM 13–15 NY (meist irrelevant).

Für die Sweep-Punkte (harte Regel 3) nimmt das Tool von JEDER Session die
letzte bereits ABGESCHLOSSENE Ausgabe. Um 15:30 Berlin sind das z. B.
Asia, London und Pre-Market von heute sowie NY AM und NY PM von gestern.

Power of 3 (ICT):
  Akkumulation  = Asia-Range (ruhige Phase)
  Manipulation  = Fakeout GEGEN den Bias über/unter das Midnight Open
                  (bei bullish: Tief unter dem Open, oft Sweep eines Session-Tiefs)
  Distribution  = die eigentliche Bewegung in Bias-Richtung (ab NY AM)
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

import pandas as pd

import config
from structure import BEARISH, BULLISH


@dataclass
class SessionRange:
    name: str
    start: pd.Timestamp           # NY-Zeit
    end: pd.Timestamp             # NY-Zeit
    high: float
    low: float
    high_time: pd.Timestamp
    low_time: pd.Timestamp
    relevant: bool = True
    complete: bool = True         # False = Session läuft noch
    genau: bool = True            # False = aus H1 berechnet (Pre-Market dann ungenau)


def window(name: str, date: dt.date) -> tuple[pd.Timestamp, pd.Timestamp]:
    """Beginn und Ende einer Session an einem Kalendertag, umgerechnet in NY-Zeit."""
    cfg = config.SESSIONS[name]
    s = pd.Timestamp(f"{date} {cfg['start']}", tz=cfg["tz"])
    e = pd.Timestamp(f"{date} {cfg['end']}", tz=cfg["tz"])
    if e <= s:
        e += pd.Timedelta(days=1)
    return s.tz_convert(config.TZ_NY), e.tz_convert(config.TZ_NY)


def _range(candles: pd.DataFrame, name: str, s, e, as_of) -> SessionRange | None:
    w = candles[(candles.index >= s) & (candles.index < min(e, as_of))]
    if w.empty:
        return None
    spacing = candles.index.to_series().diff().median() if len(candles) > 1 else pd.Timedelta(0)
    return SessionRange(name, s, e, float(w["High"].max()), float(w["Low"].min()),
                        w["High"].idxmax(), w["Low"].idxmin(),
                        config.SESSIONS[name]["relevant"], complete=e <= as_of,
                        genau=spacing <= pd.Timedelta(minutes=15))


def latest_completed(candles: pd.DataFrame, as_of: pd.Timestamp, name: str,
                     max_days: int = 6) -> SessionRange | None:
    """Letzte bereits abgeschlossene Ausgabe der Session (vor as_of)."""
    day = as_of.tz_convert(config.TZ_BERLIN).date()
    for back in range(0, max_days + 1):
        s, e = window(name, day - dt.timedelta(days=back))
        if e <= as_of:
            r = _range(candles, name, s, e, as_of)
            if r is not None:
                return r
    return None


def running(candles: pd.DataFrame, as_of: pd.Timestamp) -> SessionRange | None:
    """Session, die gerade läuft (Hoch/Tief bis jetzt)."""
    day = as_of.tz_convert(config.TZ_BERLIN).date()
    for name in config.SESSIONS:
        for d in (day, day - dt.timedelta(days=1)):
            s, e = window(name, d)
            if s <= as_of < e:
                return _range(candles, name, s, e, as_of)
    return None


def session_ranges(candles: pd.DataFrame, as_of: pd.Timestamp) -> list[SessionRange]:
    """Pro Session die letzte abgeschlossene Ausgabe, zeitlich sortiert."""
    out = [r for name in config.SESSIONS
           if (r := latest_completed(candles, as_of, name)) is not None]
    return sorted(out, key=lambda r: r.start)


def session_of(t: pd.Timestamp) -> str:
    """In welcher Session liegt Zeitpunkt t? (sonst 'zwischen den Sessions')"""
    d = t.tz_convert(config.TZ_BERLIN).date()
    for name in config.SESSIONS:
        for day in (d, d - dt.timedelta(days=1)):
            s, e = window(name, day)
            if s <= t < e:
                return name
    return "zwischen den Sessions"


# ---------------------------------------------------------------------------
# Power of 3
# ---------------------------------------------------------------------------
@dataclass
class PO3:
    direction: str
    open_price: float
    manipulation: bool            # Fakeout gegen den Bias über/unter das Open?
    manip_extreme: float | None
    manip_time: pd.Timestamp | None
    manip_session: str | None
    swept: list[str] = field(default_factory=list)   # dabei gesweepte Levels
    premarket_fakeout: bool = False
    price_ok: bool = False        # Preis wieder auf der richtigen Seite des Opens?
    lines: list[str] = field(default_factory=list)


def _mirror(df: pd.DataFrame) -> pd.DataFrame:
    """Spiegelt Kerzen (Preise mal -1): so gilt die bullishe Logik auch für bearish."""
    return pd.DataFrame({"Open": -df["Open"], "High": -df["Low"],
                         "Low": -df["High"], "Close": -df["Close"]}, index=df.index)


def power_of_three(candles: pd.DataFrame, as_of: pd.Timestamp, direction: str,
                   levels: list[tuple[str, float]],
                   fmt=lambda x: f"{x:g}") -> PO3 | None:
    """
    candles  : abgeschlossene Intraday-Kerzen (M15, sonst H1)
    direction: Bias-Richtung (BULLISH/BEARISH)
    levels   : Liquiditäts-Levels auf der MANIPULATIONS-Seite als
               (Name, Preis, existiert_ab), z. B. bei bullish
               [("PDL", ..., Ende Vortag), ("Asia Low", ..., Ende Asia)]
               Gesweept zählt nur, was zum Zeitpunkt der Manipulation schon da war.
    """
    if direction not in (BULLISH, BEARISH):
        return None
    ny_date = as_of.tz_convert(config.TZ_NY).date()
    t_open = pd.Timestamp(f"{ny_date} {config.PO3_OPEN_NY}", tz=config.TZ_NY)
    bar = candles[candles.index == t_open]
    if bar.empty or t_open >= as_of:
        return None

    bull = direction == BULLISH
    s = 1 if bull else -1                       # zum Zurückspiegeln
    c = candles if bull else _mirror(candles)
    lv = [(n, s * p, ab) for n, p, ab in levels]
    opn = float(c.loc[t_open, "Open"])
    since = c[(c.index >= t_open) & (c.index < as_of)]
    unten, oben = ("unter", "über") if bull else ("über", "unter")
    res = PO3(direction, s * opn, False, None, None, None)

    # Manipulation: tiefster Punkt seit dem Open (gespiegelt bei bearish)
    m_low, m_time = float(since["Low"].min()), since["Low"].idxmin()
    if m_low < opn:
        res.manipulation = True
        res.manip_extreme, res.manip_time = s * m_low, m_time
        res.manip_session = session_of(m_time)
        res.swept = [n for n, p, ab in lv if ab <= m_time and m_low < p]

    # Pre-Market-Fakeout: neues Tages-Extrem im Pre-Market, Schluss wieder zurück
    pm_s, pm_e = window(config.PO3_PREMARKET, as_of.tz_convert(config.TZ_BERLIN).date())
    pm = c[(c.index >= pm_s) & (c.index < min(pm_e, as_of))]
    before = c[(c.index >= t_open) & (c.index < pm_s)]
    if not pm.empty and not before.empty:
        prev_low = float(before["Low"].min())
        if pm["Low"].min() < prev_low and pm["Close"].iloc[-1] > prev_low:
            res.premarket_fakeout = True

    price = float(since["Close"].iloc[-1])
    res.price_ok = price > opn

    # Text
    a = latest_completed(candles, as_of, "Asia")
    if a is not None:
        res.lines.append(f"Akkumulation: Asia-Range {fmt(a.low)} – {fmt(a.high)}")
    res.lines.append(f"Midnight Open (True Day Open): {fmt(res.open_price)}")
    if res.manipulation:
        sw = f", dabei gesweept: {', '.join(res.swept)}" if res.swept else ""
        res.lines.append(f"Manipulation: {'Tief' if bull else 'Hoch'} {fmt(res.manip_extreme)} "
                         f"{unten} dem Open ({res.manip_session}, "
                         f"{res.manip_time.tz_convert(config.TZ_BERLIN):%H:%M} Berlin){sw}")
    else:
        res.lines.append(f"Manipulation: noch kein Fakeout {unten} das Open")
    res.lines.append("Pre-Market-Fakeout (14:30–15:30): "
                     + ("JA – neues Tages-" + ("tief" if bull else "hoch")
                        + ", Schluss wieder zurück" if res.premarket_fakeout else "nein"))
    if res.manipulation and res.price_ok:
        res.lines.append(f"Distribution: Preis wieder {oben} dem Open -> "
                         f"{'bullishe' if bull else 'bearishe'} Expansion möglich")
    elif res.manipulation:
        res.lines.append(f"Distribution: Preis noch {unten} dem Open -> abwarten")
    else:
        res.lines.append("Distribution: ohne Manipulation kein klassisches Power-of-3-Muster")
    return res
