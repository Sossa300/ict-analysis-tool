"""
data.py – Kursdaten laden und in die Timeframes M15 / H1 / H4 / Daily / Weekly
umwandeln.

Grundidee:
  1. Wir laden feine Intraday-Daten (H1 und M15) – entweder von yfinance
     oder aus einer CSV-Datei.
  2. Alle Zeitstempel werden nach New-York-Zeit umgerechnet.
  3. Daraus bauen wir H4-, Daily- und Weekly-Kerzen SELBST zusammen.
     Warum? Weil yfinance die Tagesgrenzen je nach Instrument unterschiedlich
     setzt. Wir wollen exakt die ICT-Tageskerze (z. B. 18:00–17:00 NY beim
     Nasdaq), damit PDH/PDL zu deinem Chart passen.

Jede Kerzen-Tabelle (DataFrame) hat die Spalten Open, High, Low, Close.
Daily und Weekly haben zusätzlich "start" und "end" (Beginn/Ende in NY-Zeit).
"""

from __future__ import annotations

import pandas as pd

import config

OHLC = ["Open", "High", "Low", "Close"]


# ---------------------------------------------------------------------------
# 1) Daten laden
# ---------------------------------------------------------------------------
def download_yfinance(yf_symbol: str, interval: str, period: str) -> pd.DataFrame:
    """Lädt Kerzen von Yahoo Finance und gibt sie in NY-Zeit zurück."""
    import yfinance as yf  # erst hier importieren, damit Tests ohne Internet laufen

    df = yf.Ticker(yf_symbol).history(interval=interval, period=period,
                                      auto_adjust=False)
    if df.empty:
        raise RuntimeError(
            f"yfinance hat keine Daten für '{yf_symbol}' ({interval}) geliefert. "
            "Internetverbindung prüfen oder später erneut versuchen."
        )
    df = df[OHLC].dropna()
    df.index = df.index.tz_convert(config.TZ_NY)
    df.index.name = "time"
    return df


# Mögliche Spaltennamen in CSV-Exporten (alles klein geschrieben)
_CSV_NAMES = {
    "time":  ["datum", "date", "time", "zeit", "datetime", "timestamp"],
    "Open":  ["open", "eröffnung", "eroeffnung", "o"],
    "High":  ["high", "hoch", "h"],
    "Low":   ["low", "tief", "l"],
    "Close": ["close", "schluss", "c"],
}


def _to_number(series: pd.Series) -> pd.Series:
    """Wandelt Text wie '21.480,25' (deutsch) oder '21480.25' in Zahlen um."""
    if pd.api.types.is_numeric_dtype(series):
        return series.astype(float)
    s = series.astype(str).str.strip()
    deutsch = s.str.contains(",")
    s = s.where(~deutsch, s.str.replace(".", "", regex=False)
                           .str.replace(",", ".", regex=False))
    return s.astype(float)


def load_csv(path: str, csv_tz: str = config.TZ_NY) -> pd.DataFrame:
    """
    Liest eine CSV mit den Spalten Datum, Open, High, Low, Close.

    - Trennzeichen (Komma oder Semikolon) wird automatisch erkannt.
    - Deutsche Zahlen (21.480,25) und Datumsformate (17.10.2026 14:00) gehen.
    - Unix-Zeitstempel (z. B. TradingView-Export "time") gehen auch.
    - csv_tz: In welcher Zeitzone stehen die Zeiten in der Datei?
      (Standard NY. Wenn dein Chart auf Berlin steht: "Europe/Berlin")
    """
    raw = pd.read_csv(path, sep=None, engine="python")
    lower = {c.lower().strip(): c for c in raw.columns}

    df = pd.DataFrame()
    for target, candidates in _CSV_NAMES.items():
        found = next((lower[c] for c in candidates if c in lower), None)
        if found is None:
            raise ValueError(f"Spalte für '{target}' nicht gefunden. "
                             f"Vorhandene Spalten: {list(raw.columns)}")
        df[target] = raw[found]

    # Zeitspalte umwandeln
    if pd.api.types.is_numeric_dtype(df["time"]):
        times = pd.to_datetime(df["time"], unit="s", utc=True)
    else:
        text = df["time"].astype(str).str.strip()
        # "2026-10-14 09:00" (ISO, Jahr zuerst) oder "14.10.2026 09:00" (deutsch)
        iso = text.str.match(r"^\d{4}-").all()
        times = pd.to_datetime(text, dayfirst=not iso, format="mixed")
        if times.dt.tz is None:
            times = times.dt.tz_localize(csv_tz, ambiguous="infer",
                                         nonexistent="shift_forward")
    df["time"] = times.dt.tz_convert(config.TZ_NY)

    for col in OHLC:
        df[col] = _to_number(df[col])

    df = df.set_index("time").sort_index()
    df = df[~df.index.duplicated(keep="last")]
    return df[OHLC].dropna()


def bar_spacing(df: pd.DataFrame) -> pd.Timedelta:
    """Typischer Abstand zwischen zwei Kerzen (z. B. 15 min, 1 h, 1 Tag)."""
    if len(df) < 2:
        return pd.Timedelta(0)
    return df.index.to_series().diff().median()


# ---------------------------------------------------------------------------
# 2) Kerzen zusammensetzen (Resampling)
# ---------------------------------------------------------------------------
def _shifted_wall_clock(index: pd.DatetimeIndex, day_start: int) -> pd.DatetimeIndex:
    """
    Trick für die Tagesgrenze: Wir verschieben die NY-Uhrzeit so, dass der
    Handelstag um 00:00 beginnt. Beim Nasdaq (Start 18:00) addieren wir 6 h:
    Montag 18:00 NY -> "Dienstag 00:00" -> gehört zur Dienstag-Kerze.
    """
    wall = index.tz_convert(config.TZ_NY).tz_localize(None)
    return wall + pd.Timedelta(hours=24 - day_start)


def drop_weekend_bars(intraday: pd.DataFrame, day_start: int) -> pd.DataFrame:
    """
    Entfernt Kerzen, die zu keinem Handelstag Mo–Fr gehören.
    Beispiel: Yahoo liefert bei Forex am Freitag ab 17:00 NY noch Kerzen
    nach Handelsschluss. Ohne diesen Filter entstünde eine falsche
    "Samstag"-Tageskerze, die PDH/PDL und die Wochenkerze verfälscht.
    """
    trading_date = _shifted_wall_clock(intraday.index, day_start)
    return intraday[trading_date.weekday < 5]


def _aggregate(df: pd.DataFrame, keys) -> pd.DataFrame:
    """Fasst Kerzen gruppenweise zusammen: erstes Open, max High, min Low, letztes Close."""
    g = df.groupby(keys)
    return pd.DataFrame({
        "Open": g["Open"].first(),
        "High": g["High"].max(),
        "Low": g["Low"].min(),
        "Close": g["Close"].last(),
    })


def make_h4(intraday: pd.DataFrame, day_start: int) -> pd.DataFrame:
    """
    Baut H4-Kerzen aus H1 (oder feiner). Die H4-Blöcke beginnen am
    Tagesanfang, also beim Nasdaq 18, 22, 02, 06, 10, 14 Uhr NY.
    """
    bucket = _shifted_wall_clock(intraday.index, day_start).floor("4h")
    out = _aggregate(intraday, bucket)
    # Als Zeitstempel nehmen wir den echten Beginn der ersten Kerze im Block
    first_time = intraday.index.to_series().groupby(bucket).min()
    out.index = pd.DatetimeIndex(first_time.loc[out.index], name="time")
    return out


def make_m15(intraday: pd.DataFrame) -> pd.DataFrame:
    """Fasst feinere Daten (z. B. M1/M5) zu M15 zusammen."""
    wall = intraday.index.tz_localize(None).floor("15min")
    out = _aggregate(intraday, wall)
    first_time = intraday.index.to_series().groupby(wall).min()
    out.index = pd.DatetimeIndex(first_time.loc[out.index], name="time")
    return out


def _add_day_bounds(daily: pd.DataFrame, day_start: int, day_end: int) -> pd.DataFrame:
    """Ergänzt Beginn/Ende jeder Tageskerze in NY-Zeit."""
    dates = daily.index
    start = (dates - pd.Timedelta(days=1) + pd.Timedelta(hours=day_start))
    end = dates + pd.Timedelta(hours=day_end)
    daily = daily.copy()
    daily["start"] = start.tz_localize(config.TZ_NY)
    daily["end"] = end.tz_localize(config.TZ_NY)
    return daily


def make_daily(intraday: pd.DataFrame, day_start: int, day_end: int) -> pd.DataFrame:
    """Baut Daily-Kerzen. Index = Handelsdatum (z. B. 2026-10-14 = Dienstag-Kerze)."""
    trading_date = _shifted_wall_clock(intraday.index, day_start).floor("D")
    daily = _aggregate(intraday, trading_date)
    daily.index = pd.DatetimeIndex(daily.index, name="date")
    return _add_day_bounds(daily, day_start, day_end)


def daily_from_daily_csv(df: pd.DataFrame, day_start: int, day_end: int) -> pd.DataFrame:
    """Wenn die CSV schon Tageskerzen enthält, nehmen wir das Datum direkt."""
    daily = df.copy()
    daily.index = pd.DatetimeIndex(daily.index.tz_localize(None).normalize(), name="date")
    daily = daily[~daily.index.duplicated(keep="last")]
    return _add_day_bounds(daily, day_start, day_end)


def make_weekly(daily: pd.DataFrame) -> pd.DataFrame:
    """
    Baut Weekly-Kerzen aus den Daily-Kerzen.
    Index = Montag der Woche. Die Woche beginnt mit der Montag-Kerze
    (also Sonntagabend) und endet mit dem Schluss der Freitag-Kerze.
    """
    monday = daily.index - pd.to_timedelta(daily.index.weekday, unit="D")
    weekly = _aggregate(daily, monday)
    g = daily.groupby(monday)
    weekly["start"] = g["start"].min()
    # Die Woche ist erst fertig, wenn die Freitag-Kerze geschlossen hat
    # (auch wenn z. B. ein Feiertag in der Woche fehlt).
    day_end = int(daily["end"].iloc[0].hour)
    friday_close = weekly.index + pd.Timedelta(days=4, hours=day_end)
    weekly["end"] = friday_close.tz_localize(config.TZ_NY)
    weekly.index = pd.DatetimeIndex(weekly.index, name="week")
    return weekly


# ---------------------------------------------------------------------------
# 3) Alles zusammen: ein Aufruf liefert alle Timeframes
# ---------------------------------------------------------------------------
def build_timeframes(base: pd.DataFrame, instrument: dict,
                     m15: pd.DataFrame | None = None) -> dict[str, pd.DataFrame]:
    """
    base : Intraday-Daten (H1 oder feiner) ODER Daily-Daten
    m15  : optionale separate M15-Daten (yfinance liefert M15 nur 60 Tage)

    Rückgabe: {"M15": ..., "H1": ..., "H4": ..., "D": ..., "W": ...}
              (Einträge fehlen, wenn die Daten dafür zu grob sind)
    """
    start, end = instrument["day_start_ny"], instrument["day_end_ny"]
    spacing = bar_spacing(base)
    tf: dict[str, pd.DataFrame] = {}

    if spacing >= pd.Timedelta(hours=20):          # Tagesdaten
        tf["D"] = daily_from_daily_csv(base, start, end)
    else:                                           # Intraday-Daten
        base = drop_weekend_bars(base, start)
        if m15 is not None:
            m15 = drop_weekend_bars(m15, start)
        if spacing <= pd.Timedelta(hours=1):
            tf["H1"] = base
        tf["H4"] = make_h4(base, start)
        tf["D"] = make_daily(base, start, end)
        if m15 is None and spacing <= pd.Timedelta(minutes=15):
            m15 = make_m15(base)

    if m15 is not None:
        tf["M15"] = m15
    tf["W"] = make_weekly(tf["D"])
    return tf


def load_instrument(symbol: str, csv_path: str | None = None,
                    csv_tz: str = config.TZ_NY) -> dict[str, pd.DataFrame]:
    """Lädt ein Instrument aus config.INSTRUMENTS – per yfinance oder CSV."""
    if symbol not in config.INSTRUMENTS:
        raise KeyError(f"Unbekanntes Symbol '{symbol}'. "
                       f"Verfügbar: {', '.join(config.INSTRUMENTS)}")
    inst = config.INSTRUMENTS[symbol]

    if csv_path:
        return build_timeframes(load_csv(csv_path, csv_tz), inst)

    h1 = download_yfinance(inst["yf_symbol"], "1h", config.DOWNLOAD_PERIOD_H1)
    try:
        m15 = download_yfinance(inst["yf_symbol"], "15m", config.DOWNLOAD_PERIOD_M15)
    except RuntimeError:
        m15 = None
    return build_timeframes(h1, inst, m15)


def cut_at(tf: dict[str, pd.DataFrame], as_of: pd.Timestamp) -> dict[str, pd.DataFrame]:
    """
    Schneidet alle Daten auf einen Zeitpunkt ab ("Zeitreise").
    Damit kannst du prüfen: Was hätte das Tool am Tag X um Uhrzeit Y gesagt?
    Intraday-Kerzen werden nur behalten, wenn sie bis as_of ABGESCHLOSSEN waren
    (um 15:30 also keine H1-Kerze 15:00–16:00 – die enthielte 30 Minuten Zukunft).
    Daily/Weekly werden aus den gekürzten Intraday-Daten neu berechnet.
    """
    base_key = "H1" if "H1" in tf else ("M15" if "M15" in tf else None)
    out = {}
    for k, v in tf.items():
        if k in ("M15", "H1", "H4") and not v.empty:
            out[k] = v[v.index + bar_spacing(v) <= as_of]
        elif k in ("M15", "H1", "H4"):
            out[k] = v
    if base_key is None:   # nur Tagesdaten vorhanden
        out["D"] = tf["D"][tf["D"]["start"] < as_of]
        out["W"] = make_weekly(out["D"])
        return out
    # H4, Daily und Weekly neu bauen, damit die laufende Kerze nur Daten
    # bis as_of enthält (sonst würde sie in die Zukunft "schauen")
    d_old = tf["D"]
    day_start = int(d_old["start"].iloc[0].hour)
    day_end = int(d_old["end"].iloc[0].hour)
    out["H4"] = make_h4(out[base_key], day_start)
    out["D"] = make_daily(out[base_key], day_start, day_end)
    out["W"] = make_weekly(out["D"])
    return out
