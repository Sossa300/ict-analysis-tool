"""
methoden_backtest.py – Vergleicht ALLE Bias-Methoden aus bias_methods.py.

Für jeden Handelstag (Standard: 24 Monate):
  - Entscheidung um 15:30 Berlin, nur mit H1-Kerzen, die bis dahin geschlossen waren
  - Bewertung A: Schluss bei Tagesende (17:00 NY) gegenüber 15:30
  - Bewertung B: Stand um 18:00 Berlin (NY-Vormittag) gegenüber 15:30

Gegen Zufallstreffer:
  - Jahr 1 (erste Hälfte) zum FINDEN, Jahr 2 (zweite Hälfte) zum BESTÄTIGEN.
    Eine Methode taugt nur, wenn sie in BEIDEN Hälften über dem Zufall liegt.
  - 95-%-Vertrauensbereich: Liegt er komplett über dem Zufallswert, ist der
    Vorteil statistisch gesichert. Bei ~25 Methoden ist trotzdem 1 "Glückstreffer"
    zu erwarten – deshalb zählt die Bestätigung in Jahr 2.

Start:  python methoden_backtest.py            (alle Instrumente, 24 Monate)
"""

from __future__ import annotations

import argparse
import os

import pandas as pd

import bias
import bias_methods as bm
import config
import data
import main as tool
import structure
from backtest import OUT_DIR, wilson

# Korreliertes Instrument für die SMT-Divergenz
SMT_PARTNER = {"US100": "ES=F", "EURUSD": "GBPUSD=X", "EURGBP": None}


def _window(m15, h1, start, end):
    if m15 is not None and not m15.empty and m15.index[0] <= start:
        w = m15[(m15.index >= start) & (m15.index < end)]
        if not w.empty:
            return w
    return h1[(h1.index >= start.floor("h")) & (h1.index < end)]


def _ctx(cut: dict, cut_time, symbol, a=None) -> bm.MethodContext | None:
    d_all, w_all = cut["D"], cut["W"]
    if d_all.empty or not (d_all["start"].iloc[-1] < cut_time < d_all["end"].iloc[-1]):
        return None                                  # kein laufender Handelstag
    h4_done = (a.h4_done if a is not None else
               structure.completed(cut["H4"], cut_time, pd.Timedelta(hours=4)))
    ctx = bm.MethodContext(
        h1=cut["H1"], d_done=structure.completed(d_all, cut_time),
        w_done=structure.completed(w_all, cut_time), day=d_all.iloc[-1],
        week=w_all.iloc[-1], h4_done=h4_done, now=cut_time,
        price=float(cut["H1"]["Close"].iloc[-1]), symbol=symbol)
    if a is not None:
        ctx.tool_bias = a.bias.bias if a.bias.bias != bias.NEUTRAL else None
        ctx.tool_daily_trend = a.htf.trend if a.htf.trend != structure.UNKLAR else None
        ctx.tool_h4_phase = a.htf.h4_phase
    return ctx


def run(symbol: str, monate: int, uhrzeit: str) -> pd.DataFrame:
    inst = config.INSTRUMENTS[symbol]
    print(f"[{symbol}] Lade Daten ...", flush=True)
    h1 = data.download_yfinance(inst["yf_symbol"], "1h", config.DOWNLOAD_PERIOD_H1)
    try:
        m15 = data.drop_weekend_bars(
            data.download_yfinance(inst["yf_symbol"], "15m", config.DOWNLOAD_PERIOD_M15),
            inst["day_start_ny"])
    except RuntimeError:
        m15 = None
    tf = data.build_timeframes(h1, inst)
    tf_other = None
    if SMT_PARTNER.get(symbol):
        try:
            h1o = data.download_yfinance(SMT_PARTNER[symbol], "1h", config.DOWNLOAD_PERIOD_H1)
            tf_other = data.build_timeframes(h1o, inst)
        except RuntimeError:
            tf_other = None

    daily = tf["D"]
    start = daily.index[-1] - pd.DateOffset(months=monate)
    hh, mm = (int(x) for x in uhrzeit.split(":"))
    rows = []
    days = [d for d in daily.index if d > start and d.weekday() < 5]
    for n, day in enumerate(days):
        berlin = pd.Timestamp(day.date())
        t_ref = (berlin + pd.Timedelta(hours=hh, minutes=mm)).tz_localize(
            config.TZ_BERLIN).tz_convert(config.TZ_NY)
        t_am = (berlin + pd.Timedelta(hours=18)).tz_localize(
            config.TZ_BERLIN).tz_convert(config.TZ_NY)
        day_end = daily.loc[day, "end"]
        if not (daily.loc[day, "start"] < t_ref < day_end) or \
                day_end > pd.Timestamp.now(tz=config.TZ_NY):
            continue
        cut_time = t_ref.floor("h")
        w_end = _window(m15, tf["H1"], t_ref, day_end)
        w_am = _window(m15, tf["H1"], t_ref, min(t_am, day_end))
        if w_end.empty or w_am.empty:
            continue

        cut = data.cut_at(tf, cut_time)
        try:
            a = tool.run_bias(cut, cut_time, inst)
        except (ValueError, IndexError):
            continue
        ctx = _ctx(cut, cut_time, symbol, a)
        if ctx is None:
            continue
        if tf_other is not None:
            ctx.smt_other = _ctx(data.cut_at(tf_other, cut_time), cut_time, symbol)

        ref = float(w_end["Open"].iloc[0])
        row = {"Symbol": symbol, "Datum": day.date(),
               "Bewegung_Tagesende": float(w_end["Close"].iloc[-1]) - ref,
               "Bewegung_18Uhr": float(w_am["Close"].iloc[-1]) - ref}
        row.update(bm.predict_all(ctx))
        rows.append(row)
        if n % 50 == 0:
            print(f"  {n}/{len(days)} Tage ...", flush=True)
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Auswertung
# ---------------------------------------------------------------------------
def score(df: pd.DataFrame, method: str, move_col: str) -> dict | None:
    pred = df[method]
    m = pred.notna() & (df[move_col] != 0)
    if m.sum() == 0:
        return None
    sub, p = df[m], pred[m]
    bull = p == bm.BULL
    hit = (bull & (sub[move_col] > 0)) | (~bull & (sub[move_col] < 0))
    up = sub["Symbol"].map(df.groupby("Symbol")[move_col].apply(lambda x: (x > 0).mean()))
    zufall = float(up.where(bull, 1 - up).mean())
    k, n = int(hit.sum()), len(sub)
    lo, hi = wilson(k, n)
    return {"n": n, "q": k / n, "lo": lo, "hi": hi, "z": zufall}


def ranking(df: pd.DataFrame, move_col: str, titel: str) -> str:
    df = df.sort_values("Datum")
    mitte = df["Datum"].iloc[len(df) // 2]
    j1, j2 = df[df["Datum"] < mitte], df[df["Datum"] >= mitte]
    res = []
    for name, (_, gruppe) in bm.METHODS.items():
        g, a, b = score(df, name, move_col), score(j1, name, move_col), score(j2, name, move_col)
        if g is None or a is None or b is None:
            continue
        vorteil_1, vorteil_2 = a["q"] - a["z"], b["q"] - b["z"]
        if g["lo"] > g["z"] and vorteil_1 > 0 and vorteil_2 > 0:
            urteil = "GESICHERT besser"
        elif vorteil_1 > 0.02 and vorteil_2 > 0.02:
            urteil = "in beiden Jahren besser (nicht gesichert)"
        elif g["hi"] < g["z"]:
            urteil = "gesichert SCHLECHTER (Umkehrung prüfen)"
        else:
            urteil = "kein Vorteil"
        res.append((name, gruppe, g, a, b, urteil))
    res.sort(key=lambda r: r[2]["q"] - r[2]["z"], reverse=True)

    out = [titel, f"(Jahr 1: bis {mitte}, Jahr 2: ab {mitte})", "-" * 122,
           f"{'Methode':<32}{'Gruppe':<10}{'Tage':>6}{'Treffer':>8}{'95%-Bereich':>13}"
           f"{'Zufall':>7}{'Vorteil':>8}{'Jahr1':>7}{'Jahr2':>7}   Urteil"]
    for name, gruppe, g, a, b, urteil in res:
        out.append(f"{name:<32}{gruppe:<10}{g['n']:>6}{g['q']:>8.0%}"
                   f"{g['lo']:>7.0%}–{g['hi']:<5.0%}{g['z']:>7.0%}{g['q'] - g['z']:>+8.1%}"
                   f"{a['q'] - a['z']:>+7.1%}{b['q'] - b['z']:>+7.1%}   {urteil}")
    return "\n".join(out)


def main() -> None:
    p = argparse.ArgumentParser(description="Alle Bias-Methoden im Vergleich")
    p.add_argument("--symbol", choices=list(config.INSTRUMENTS))
    p.add_argument("--monate", type=int, default=24)
    p.add_argument("--uhrzeit", default="15:30")
    args = p.parse_args()

    os.makedirs(OUT_DIR, exist_ok=True)
    frames = []
    for sym in ([args.symbol] if args.symbol else list(config.INSTRUMENTS)):
        df = run(sym, args.monate, args.uhrzeit)
        df.to_csv(os.path.join(OUT_DIR, f"methoden_{sym}.csv"), index=False,
                  sep=";", decimal=",", encoding="utf-8-sig")
        frames.append(df)
    alle = pd.concat(frames, ignore_index=True)

    texte = []
    for col, label in (("Bewegung_Tagesende", "bis Tagesschluss (17:00 NY)"),
                       ("Bewegung_18Uhr", "bis 18:00 Berlin (NY-Vormittag)")):
        texte.append(ranking(alle, col, f"ALLE Instrumente – Bewertung {label}"))
        for sym in alle["Symbol"].unique():
            texte.append(ranking(alle[alle["Symbol"] == sym], col, f"{sym} – Bewertung {label}"))
    text = "\n\n".join(texte)
    print(text)
    with open(os.path.join(OUT_DIR, "methoden_ranking.txt"), "w", encoding="utf-8") as fh:
        fh.write(text + "\n")
    print(f"\nGespeichert: {OUT_DIR}/methoden_ranking.txt und methoden_*.csv")


if __name__ == "__main__":
    main()
