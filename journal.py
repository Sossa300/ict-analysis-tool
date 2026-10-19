"""
journal.py – Forward-Test-Protokoll.

Für jeden Handelstag ab dem Start-Datum wird festgehalten, was das Tool um
15:30 Berlin gesagt hat (Signal A und Signal B) – nur mit Kerzen, die bis
15:30 abgeschlossen waren. Nach Tagesschluss wird ausgewertet, ob es stimmte.

Automatisch: Jeder Aufruf (App oder "python journal.py") trägt fehlende Tage
nach und wertet fertige Tage aus. Weil nur Daten vor 15:30 benutzt werden, ist
das genau das, was live um 15:30 herausgekommen wäre.

Ehrlich bleiben:
  - Start = erster Handelstag NACH dem ersten Aufruf (keine Backtest-Tage).
  - Jeder Eintrag speichert die Regel-Version (Prüfsumme der Regel-Dateien).
    Werden Regeln geändert, sieht man das an einer neuen Version.

Start:  python journal.py              (aktualisieren + Bericht)
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import os

import pandas as pd

import bias
import config
import data
import main as tool
import signals
import structure
from backtest import wilson

DIR = "forward_test"
JOURNAL = os.path.join(DIR, "journal.csv")
START_FILE = os.path.join(DIR, "start.txt")
UHRZEIT_BERLIN = "15:30"
REGEL_DATEIEN = ["config.py", "structure.py", "bias.py", "signals.py", "pois.py",
                 "sessions.py", "levels.py", "data.py"]
SIGNALE = {"A": "Signal A (Original)", "B": "Signal B (H4-Retracement)"}


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------
def regel_version(base: str | None = None) -> str:
    """Kurze Prüfsumme der Dateien, die die Regeln bestimmen."""
    base = base or os.path.dirname(os.path.abspath(__file__))
    h = hashlib.sha1()
    for name in REGEL_DATEIEN:
        path = os.path.join(base, name)
        if os.path.exists(path):
            with open(path, "rb") as fh:
                h.update(fh.read())
    return h.hexdigest()[:8]


def start_date(directory: str = DIR, today: dt.date | None = None) -> dt.date:
    """Start-Datum lesen; beim allerersten Mal: nächster Handelstag nach heute."""
    path = os.path.join(directory, "start.txt")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            return dt.date.fromisoformat(fh.read().strip())
    today = today or pd.Timestamp.now(tz=config.TZ_BERLIN).date()
    start = (pd.Timestamp(today) + pd.offsets.BDay(1)).date()
    os.makedirs(directory, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(start.isoformat())
    return start


def decision_time(day: dt.date) -> pd.Timestamp:
    """15:30 Berlin am Tag 'day' als NY-Zeitstempel."""
    return pd.Timestamp(f"{day} {UHRZEIT_BERLIN}", tz=config.TZ_BERLIN).tz_convert(config.TZ_NY)


def _day_end(tf: dict, t_ref: pd.Timestamp) -> pd.Timestamp | None:
    """Ende des Handelstages, in den t_ref fällt."""
    d = tf["D"]
    row = d[(d["start"] <= t_ref) & (d["end"] > t_ref)]
    return row["end"].iloc[0] if not row.empty else None


def _dir(x) -> str:
    return x if x in (structure.BULLISH, structure.BEARISH) else "neutral"


def _num(v) -> float | None:
    """'29268,75' (aus der CSV) oder 29268.75 -> 29268.75; leer -> None."""
    if v is None or (isinstance(v, float) and pd.isna(v)) or str(v).strip() in ("", "nan"):
        return None
    return float(str(v).replace(",", "."))


# ---------------------------------------------------------------------------
# 1) Eintrag um 15:30
# ---------------------------------------------------------------------------
def snapshot(symbol: str, tf: dict, day: dt.date, version: str) -> dict | None:
    """Was hat das Tool am 'day' um 15:30 Berlin gesagt? None = kein Handelstag."""
    inst = config.INSTRUMENTS[symbol]
    t_ref = decision_time(day)
    if _day_end(tf, t_ref) is None:
        return None                                   # Wochenende/Feiertag
    cut = data.cut_at(tf, t_ref)
    try:
        a = tool.run_bias(cut, t_ref, inst)
    except (ValueError, IndexError):
        return None
    sa = signals.original_signal(a)
    sb = signals.retracement_signal(a)
    b_dol = signals.bias_for_mode(a, "retracement").dol if sb.active else None
    a_dol = a.bias.dol if a.bias.bias != bias.NEUTRAL else None
    return {
        "Datum": day.isoformat(), "Symbol": symbol, "Uhrzeit": UHRZEIT_BERLIN,
        "Regel_Version": version,
        "Preis_Entscheidung": round(a.report.last_price, inst["decimals"]),
        "A_Richtung": _dir(sa.direction), "A_Konfidenz": a.bias.confidence,
        "A_Modus": a.bias.mode if sa.active else "",
        "A_DOL": round(a_dol.price, inst["decimals"]) if a_dol else "",
        "B_Richtung": _dir(sb.direction),
        "B_DOL": round(b_dol.price, inst["decimals"]) if b_dol else "",
        "Urteil": signals.verdict(sa, sb),
        "Erfasst_am": pd.Timestamp.now(tz=config.TZ_BERLIN).strftime("%Y-%m-%d %H:%M"),
    }


# ---------------------------------------------------------------------------
# 2) Auswertung nach Tagesschluss
# ---------------------------------------------------------------------------
def evaluate(row: dict, tf: dict, now: pd.Timestamp | None = None) -> dict | None:
    """Bewertet einen Eintrag, sobald sein Handelstag vorbei ist (sonst None)."""
    now = now or pd.Timestamp.now(tz=config.TZ_NY)
    t_ref = decision_time(dt.date.fromisoformat(str(row["Datum"])))
    end = _day_end(tf, t_ref)
    if end is None or end > now:
        return None
    src = tf.get("M15")
    genau = src is not None and not src.empty and src.index[0] <= t_ref
    if not genau:
        src = tf["H1"]
    w = src[(src.index >= (t_ref if genau else t_ref.floor("h"))) & (src.index < end)]
    if w.empty:
        return None
    ref, close = float(w["Open"].iloc[0]), float(w["Close"].iloc[-1])
    hi, lo = float(w["High"].max()), float(w["Low"].min())
    out = {"Preis_1530": ref, "Schluss": close, "Hoch_danach": hi, "Tief_danach": lo,
           "Bewertung_genau": "ja" if genau else "nein (H1)"}
    for s in ("A", "B"):
        d = row[f"{s}_Richtung"]
        if d not in (structure.BULLISH, structure.BEARISH):
            out.update({f"{s}_Treffer": "", f"{s}_MFE_gr_MAE": "", f"{s}_DOL_erreicht": ""})
            continue
        bull = d == structure.BULLISH
        mfe = (hi - ref) if bull else (ref - lo)
        mae = (ref - lo) if bull else (hi - ref)
        dol = _num(row.get(f"{s}_DOL"))
        dol_hit = "" if dol is None else ((hi >= dol) if bull else (lo <= dol))
        out.update({f"{s}_Treffer": (close > ref) if bull else (close < ref),
                    f"{s}_MFE_gr_MAE": mfe > mae, f"{s}_DOL_erreicht": dol_hit})
    return out


# ---------------------------------------------------------------------------
# 3) Protokoll aktualisieren
# ---------------------------------------------------------------------------
def load_journal(path: str = JOURNAL) -> pd.DataFrame:
    if os.path.exists(path):
        return pd.read_csv(path, sep=";", decimal=",", encoding="utf-8-sig", dtype=str)
    return pd.DataFrame()


def save_journal(df: pd.DataFrame, path: str = JOURNAL) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    df.to_csv(path, sep=";", decimal=",", index=False, encoding="utf-8-sig")


def update(tf_map: dict[str, dict], directory: str = DIR,
           now: pd.Timestamp | None = None) -> pd.DataFrame:
    """
    tf_map: {Symbol: Timeframes} (z. B. aus data.load_instrument)
    Trägt fehlende Tage ab dem Start-Datum nach und wertet fertige Tage aus.
    """
    now = now or pd.Timestamp.now(tz=config.TZ_NY)
    path = os.path.join(directory, "journal.csv")
    df = load_journal(path)
    rows = df.to_dict("records") if not df.empty else []
    have = {(r["Datum"], r["Symbol"]) for r in rows}
    start = start_date(directory, now.tz_convert(config.TZ_BERLIN).date())
    version = regel_version()

    for symbol, tf in tf_map.items():
        day = start
        today = now.tz_convert(config.TZ_BERLIN).date()
        while day <= today:
            if day.weekday() < 5 and (day.isoformat(), symbol) not in have \
                    and decision_time(day) <= now:
                snap = snapshot(symbol, tf, day, version)
                if snap is not None:
                    rows.append(snap)
                    have.add((day.isoformat(), symbol))
            day += dt.timedelta(days=1)
        for r in rows:
            if r["Symbol"] == symbol and str(r.get("Bewertung_genau", "") or "") in ("", "nan"):
                ev = evaluate(r, tf, now)
                if ev:
                    r.update(ev)

    out = pd.DataFrame(rows)
    if not out.empty:
        out = out.sort_values(["Datum", "Symbol"]).reset_index(drop=True)
        save_journal(out, path)
    return out


# ---------------------------------------------------------------------------
# 4) Bericht
# ---------------------------------------------------------------------------
def _true(v) -> bool:
    return str(v).strip().lower() in ("true", "1", "ja")


def stats(df: pd.DataFrame) -> pd.DataFrame:
    """Trefferquoten je Signal (und je Instrument) für ausgewertete Tage."""
    zeilen = []
    if df.empty or "A_Treffer" not in df.columns:
        return pd.DataFrame(zeilen)
    for s, name in SIGNALE.items():
        for sym in ["alle"] + sorted(df["Symbol"].unique()):
            part = df if sym == "alle" else df[df["Symbol"] == sym]
            col = part[f"{s}_Treffer"].astype(str).str.strip().str.lower()
            part = part[col.isin(["true", "false"])]
            n = len(part)
            if n == 0:
                continue
            k = int(part[f"{s}_Treffer"].map(_true).sum())
            lo, hi = wilson(k, n)
            mfe = part[f"{s}_MFE_gr_MAE"].map(_true).mean()
            dol = part[f"{s}_DOL_erreicht"].astype(str).str.lower()
            dol = dol[dol.isin(["true", "false"])].map(_true)
            zeilen.append({"Signal": name, "Instrument": sym, "Tage": n,
                           "Treffer": f"{k / n:.0%}", "95%-Bereich": f"{lo:.0%}–{hi:.0%}",
                           "MFE>MAE": f"{mfe:.0%}",
                           "DOL erreicht": f"{dol.mean():.0%}" if len(dol) else "–"})
    return pd.DataFrame(zeilen)


def report(df: pd.DataFrame) -> str:
    if df.empty:
        return "Forward-Test: noch keine Einträge."
    st = stats(df)
    if "Bewertung_genau" in df.columns:
        n_offen = int(df["Bewertung_genau"].astype(str).isin(["", "nan", "None"]).sum())
    else:
        n_offen = len(df)
    lines = [f"Forward-Test seit {df['Datum'].min()} – {len(df)} Einträge, "
             f"{len(df) - n_offen} ausgewertet, {n_offen} warten auf Tagesschluss",
             f"Regel-Versionen: {', '.join(sorted(df['Regel_Version'].unique()))}"]
    if st.empty:
        lines.append("Noch keine ausgewerteten Tage mit Signal.")
    else:
        lines.append(st.to_string(index=False))
        if (st["Tage"] < 30).any():
            lines.append("Hinweis: unter ~30 Tagen sind die Quoten noch Zufall-anfällig "
                         "(siehe 95%-Bereich).")
    return "\n".join(lines)


def main() -> None:
    p = argparse.ArgumentParser(description="Forward-Test: aktualisieren und auswerten")
    p.add_argument("--symbol", choices=list(config.INSTRUMENTS), help="Standard: alle")
    args = p.parse_args()
    syms = [args.symbol] if args.symbol else list(config.INSTRUMENTS)
    tf_map = {}
    for s in syms:
        print(f"Lade Daten für {s} ...", flush=True)
        tf_map[s] = data.load_instrument(s)
    df = update(tf_map)
    print()
    print(report(df))
    print(f"\nProtokoll: {JOURNAL}")


if __name__ == "__main__":
    main()
