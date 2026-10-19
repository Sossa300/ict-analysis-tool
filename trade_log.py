"""
trade_log.py – Deine eigenen Backtests dokumentieren.

Jeder Eintrag ist ein (Backtest-)Trade mit Einstieg, Stop, Ausstieg usw.
Das Ergebnis wird in R gerechnet:

    1 R = das Risiko des Trades (Abstand Einstieg -> Stop)
    Ergebnis in R = Gewinn bzw. Verlust ÷ Risiko
    Beispiel Long: Einstieg 100, Stop 95 (Risiko 5), Ausstieg 110 -> +2 R

Gespeichert wird in meine_backtests/backtests.csv (öffnet sich in Excel).
"""

from __future__ import annotations

import os

import pandas as pd

DIR = "meine_backtests"
FILE = os.path.join(DIR, "backtests.csv")

COLUMNS = ["Datum", "Uhrzeit", "Instrument", "Richtung", "Signal", "Sweep_Punkt", "POI",
           "LQS_Muster", "Checkliste_erfuellt", "Einstieg", "Stop", "Ziel", "Ausstieg",
           "R", "Ergebnis", "Notizen", "Screenshot"]

SIGNALE = ["Signal A (Original)", "Signal B (H4-Retracement)", "beide Signale", "eigenes Setup"]
POIS = ["Daily-FVG", "Daily-OB", "H4-FVG", "H4-OB", "M15-FVG", "kein POI"]
SWEEPS = ["PDH", "PDL", "PWH", "PWL", "Asia High", "Asia Low", "London High", "London Low",
          "NY Pre-Market High", "NY Pre-Market Low", "NY AM High", "NY AM Low",
          "NY PM High", "NY PM Low", "kein Sweep", "anderer"]
LQS = ["a) Ablehnungskerze", "b) 2-Kerzen-Umkehr", "keins"]
BE_GRENZE = 0.1          # |R| unter 0,1 gilt als Break-even


def compute_r(direction: str, entry: float, stop: float, exit_price: float) -> float:
    """Ergebnis in R. direction = 'Long' oder 'Short'."""
    risk = abs(entry - stop)
    if risk == 0:
        raise ValueError("Einstieg und Stop dürfen nicht gleich sein.")
    if direction == "Long" and stop > entry or direction == "Short" and stop < entry:
        raise ValueError("Stop liegt auf der falschen Seite des Einstiegs.")
    move = (exit_price - entry) if direction == "Long" else (entry - exit_price)
    return round(move / risk, 2)


def outcome(r: float) -> str:
    if abs(r) < BE_GRENZE:
        return "Break-even"
    return "Gewinn" if r > 0 else "Verlust"


NUMERIC = ["Einstieg", "Stop", "Ziel", "Ausstieg", "R"]


def _as_numbers(df: pd.DataFrame) -> pd.DataFrame:
    """Zahlenspalten sicher als Zahlen (auch '21.480,25' / '2,0' aus der CSV)."""
    df = df.copy()
    for c in NUMERIC:
        s = df[c].astype(str).str.strip()
        deutsch = s.str.contains(",", regex=False)
        s = s.where(~deutsch, s.str.replace(".", "", regex=False).str.replace(",", ".", regex=False))
        df[c] = pd.to_numeric(s.replace({"": None, "None": None, "nan": None}), errors="coerce")
    return df


def load(path: str = FILE) -> pd.DataFrame:
    if os.path.exists(path):
        df = pd.read_csv(path, sep=";", encoding="utf-8-sig", dtype=str)
        for c in COLUMNS:
            if c not in df.columns:
                df[c] = None
        return _as_numbers(df[COLUMNS])
    return pd.DataFrame(columns=COLUMNS)


def save(df: pd.DataFrame, path: str = FILE) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    _as_numbers(df[COLUMNS]).to_csv(path, sep=";", decimal=",", index=False,
                                    encoding="utf-8-sig")


def add(entry: dict, path: str = FILE) -> pd.DataFrame:
    """Fügt einen Trade hinzu (R und Ergebnis werden berechnet) und speichert."""
    e = dict(entry)
    e["R"] = compute_r(e["Richtung"], float(e["Einstieg"]), float(e["Stop"]),
                       float(e["Ausstieg"]))
    e["Ergebnis"] = outcome(e["R"])
    df = load(path)
    neu = pd.DataFrame([{c: e.get(c) for c in COLUMNS}])
    df = neu if df.empty else pd.concat([df, neu], ignore_index=True)
    save(df, path)
    return _as_numbers(df)


def recompute(df: pd.DataFrame) -> pd.DataFrame:
    """Nach dem Bearbeiten in der Tabelle: R und Ergebnis neu berechnen."""
    df = df.copy()
    rs, res = [], []
    for _, row in df.iterrows():
        try:
            r = compute_r(row["Richtung"], float(row["Einstieg"]), float(row["Stop"]),
                          float(row["Ausstieg"]))
            rs.append(r)
            res.append(outcome(r))
        except (ValueError, TypeError):
            rs.append(None)
            res.append("ungültig")
    df["R"], df["Ergebnis"] = rs, res
    return df


def stats(df: pd.DataFrame) -> dict:
    """Kennzahlen über alle gültigen Trades."""
    r = pd.to_numeric(df["R"], errors="coerce").dropna()
    if r.empty:
        return {"Trades": 0}
    wins, losses = r[r >= BE_GRENZE], r[r <= -BE_GRENZE]
    entscheidend = len(wins) + len(losses)
    return {
        "Trades": len(r),
        "Gewinner": len(wins), "Verlierer": len(losses), "Break-even": len(r) - entscheidend,
        "Trefferquote": (len(wins) / entscheidend) if entscheidend else None,
        "Ø R": float(r.mean()),
        "Summe R": float(r.sum()),
        "Ø Gewinn (R)": float(wins.mean()) if len(wins) else None,
        "Ø Verlust (R)": float(losses.mean()) if len(losses) else None,
        "Profitfaktor": (float(wins.sum() / -losses.sum()) if len(losses) and losses.sum() != 0
                         else None),
        "Max. Drawdown (R)": float((r.cumsum() - r.cumsum().cummax()).min()),
    }


def by_group(df: pd.DataFrame, column: str) -> pd.DataFrame:
    """Trefferquote und Ø R je Gruppe (z. B. je Signal oder POI-Typ)."""
    d = df.copy()
    d["R"] = pd.to_numeric(d["R"], errors="coerce")
    d = d.dropna(subset=["R"])
    if d.empty:
        return pd.DataFrame()
    g = d.groupby(column)["R"]
    out = pd.DataFrame({
        "Trades": g.size(),
        "Trefferquote": g.apply(lambda x: (x >= BE_GRENZE).sum() /
                                max(1, ((x >= BE_GRENZE) | (x <= -BE_GRENZE)).sum())),
        "Ø R": g.mean().round(2),
        "Summe R": g.sum().round(2),
    }).reset_index()
    out["Trefferquote"] = out["Trefferquote"].map(lambda v: f"{v:.0%}")
    return out.sort_values("Summe R", ascending=False)
