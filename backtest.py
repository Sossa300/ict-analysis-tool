"""
backtest.py – Prüft, ob der Bias des Tools sich nach 15:30 (Berlin) bestätigt.

Ablauf für jeden Handelstag der letzten Monate:
  1. "Zeitreise" auf 15:30 Berlin: Das Tool sieht nur Stundenkerzen, die bis
     dahin GESCHLOSSEN waren (also bis 15:00 Berlin). Kein Blick in die Zukunft.
  2. Daraus berechnet es den Bias wie gewohnt (Daily + H4-Führung).
  3. Danach wird die echte Preisbewegung von 15:30 bis Tagesschluss
     (17:00 New York = 23:00 Berlin) mit dem Bias verglichen.

Bewertung (nur Tage MIT Bias):
  Richtung  : Schluss in Bias-Richtung gegenüber 15:30?
  MFE > MAE : Lief der Preis weiter IN Bias-Richtung als dagegen?
  DOL       : Wurde das DOL-Ziel nach 15:30 erreicht?

Preis um 15:30: aus M15-Daten (gibt es bei yfinance nur ~60 Tage). Für ältere
Tage wird die H1-Kerze ab 15:00 als Näherung genommen (Spalte "genau" = nein).

Start:   python backtest.py                 (alle Instrumente, 3 Monate)
         python backtest.py --symbol US100 --monate 2
"""

from __future__ import annotations

import argparse
import os

import pandas as pd

import bias
import config
import data
import main as tool
import structure

OUT_DIR = "backtest_ergebnisse"


def _eval_window(m15, h1, t_ref, day_end):
    """Kerzen von 15:30 bis Tagesschluss. M15 wenn möglich (genau), sonst H1 (Näherung)."""
    if m15 is not None and not m15.empty and m15.index[0] <= t_ref:
        w = m15[(m15.index >= t_ref) & (m15.index < day_end)]
        if not w.empty:
            return w, True
    start = t_ref.floor("h")
    return h1[(h1.index >= start) & (h1.index < day_end)], False


def _criteria(a, price: float) -> dict:
    """
    Jedes Kriterium EINZELN als Richtungs-Vorhersage (bullish/bearish/None).
    So lässt sich später messen, welches Kriterium allein etwas taugt.
    """
    b, htf = a.bias, a.htf
    last = a.daily.last_break
    sig = b.pd_signal
    k = {
        "K_Daily_Trend": htf.trend if htf.trend != structure.UNKLAR else None,
        "K_Daily_Trend_BOS": htf.trend if last is not None and last.kind == "BOS"
        and htf.trend != structure.UNKLAR else None,
        "K_Daily_Trend_MSS": htf.trend if last is not None and last.kind == "MSS"
        and htf.trend != structure.UNKLAR else None,
        "K_Kerzen_MSS": last.direction if last is not None and last.source == "kerze" else None,
        "K_Weekly_Trend": a.weekly.trend if a.weekly.trend != structure.UNKLAR else None,
        "K_H4_Trend": a.h4.trend if a.h4 is not None and a.h4.trend != structure.UNKLAR else None,
        "K_Daily_und_H4_gleich": htf.trend if a.h4 is not None
        and a.h4.trend == htf.trend != structure.UNKLAR else None,
        "K_PD_Fortsetzung": sig.direction if sig and sig.kind == bias.PD_FORTSETZUNG else None,
        "K_PD_Reversal": sig.direction if sig and sig.kind == bias.PD_REVERSAL else None,
        # Premium -> bearish erwartet, Discount -> bullish erwartet (Daily-Bein)
        "K_Zone_Premium_Discount": None,
        "K_H4_Umkehr": b.h4_reversal.direction if b.h4_reversal else None,
    }
    if htf.leg is not None:
        k["K_Zone_Premium_Discount"] = (structure.BEARISH if htf.leg.zone(price) == "Premium"
                                        else structure.BULLISH)
    k["H4_Phase"] = htf.h4_phase
    return k


def run(symbol: str, monate: int, uhrzeit: str) -> pd.DataFrame:
    inst = config.INSTRUMENTS[symbol]
    print(f"[{symbol}] Lade Daten ...", flush=True)
    h1 = data.download_yfinance(inst["yf_symbol"], "1h", config.DOWNLOAD_PERIOD_H1)
    try:
        m15 = data.download_yfinance(inst["yf_symbol"], "15m", config.DOWNLOAD_PERIOD_M15)
        m15 = data.drop_weekend_bars(m15, inst["day_start_ny"])
    except RuntimeError:
        m15 = None
    tf_full = data.build_timeframes(h1, inst)          # nur H1-Basis: überall gleich
    h1c = tf_full["H1"]
    daily = tf_full["D"]

    ende = daily.index[-1]
    start = ende - pd.DateOffset(months=monate)
    hh, mm = (int(x) for x in uhrzeit.split(":"))
    rows = []

    for day in daily.index[(daily.index > start)]:
        if day.weekday() >= 5:
            continue
        t_ref = (pd.Timestamp(day.date()) + pd.Timedelta(hours=hh, minutes=mm)) \
            .tz_localize(config.TZ_BERLIN).tz_convert(config.TZ_NY)
        day_end = daily.loc[day, "end"]
        if not (daily.loc[day, "start"] < t_ref < day_end):
            continue
        cut_time = t_ref.floor("h")                    # nur bis dahin GESCHLOSSENE H1-Kerzen
        window, genau = _eval_window(m15, h1c, t_ref, day_end)
        if window.empty or day_end > pd.Timestamp.now(tz=config.TZ_NY):
            continue                                    # Feiertag / Tag noch nicht fertig

        try:
            a = tool.run_bias(data.cut_at(tf_full, cut_time), cut_time, inst)
        except (ValueError, IndexError) as e:          # z. B. zu wenig Daten am Anfang
            print(f"  {day:%d.%m.} übersprungen: {e}")
            continue
        b = a.bias

        ref = float(window["Open"].iloc[0])
        close = float(window["Close"].iloc[-1])
        hi, lo = float(window["High"].max()), float(window["Low"].min())
        row = {
            "Datum": day.date(), "Bias": b.bias if b.bias != bias.NEUTRAL else "neutral",
            "Modus": b.mode if b.bias != bias.NEUTRAL else "",
            "Konfidenz": b.confidence, "Preis_15_30": ref, "Schluss": close,
            "Bewegung": close - ref, "Hoch_danach": hi, "Tief_danach": lo,
            "genau": "ja" if genau else "nein (H1)",
        }
        row.update(_criteria(a, ref))
        if b.bias != bias.NEUTRAL:
            s = 1 if b.bias == structure.BULLISH else -1
            mfe = (hi - ref) if s == 1 else (ref - lo)
            mae = (ref - lo) if s == 1 else (hi - ref)
            dol = b.dol.price if b.dol else None
            dol_hit = None
            if dol is not None:
                dol_hit = hi >= dol if s == 1 else lo <= dol
            row.update({
                "in_Bias_Richtung": s * (close - ref),
                "Richtung_richtig": s * (close - ref) > 0,
                "MFE": mfe, "MAE": mae, "MFE_groesser_MAE": mfe > mae,
                "DOL": dol, "DOL_erreicht": dol_hit,
            })
        rows.append(row)
    return pd.DataFrame(rows)


def _pct(x: pd.Series) -> str:
    x = x.dropna()
    return f"{x.mean():.0%} ({int(x.sum())}/{len(x)})" if len(x) else "–"


def summary(symbol: str, df: pd.DataFrame, dec: int) -> str:
    f = lambda v: tool.fmt_price(v, dec)  # noqa: E731
    lines = [f"{symbol}: {len(df)} Handelstage, Bias um 15:30 Berlin, Bewertung bis Tagesschluss"]
    if df.empty:
        return lines[0]
    mit = df[df["Bias"] != "neutral"]
    lines.append(f"  Tage mit Bias: {len(mit)} (bullish {int((mit['Bias'] == 'bullish').sum())}, "
                 f"bearish {int((mit['Bias'] == 'bearish').sum())}), "
                 f"NEUTRAL/kein Trade: {len(df) - len(mit)}")
    if not mit.empty:
        lines.append(f"  Richtung richtig (Schluss): {_pct(mit['Richtung_richtig'])}")
        lines.append(f"  MFE > MAE                 : {_pct(mit['MFE_groesser_MAE'])}")
        lines.append(f"  DOL erreicht              : {_pct(mit['DOL_erreicht'].astype('float'))}")
        lines.append(f"  Ø Bewegung in Bias-Richtung: {f(mit['in_Bias_Richtung'].mean())}  "
                     f"(Ø MFE {f(mit['MFE'].mean())}, Ø MAE {f(mit['MAE'].mean())})")
        for name, part in (("Daily-Bias", mit[mit["Modus"] == "Daily"]),
                           ("H4-geführt", mit[mit["Modus"] == "H4"]),
                           ("Konfidenz >= 75", mit[mit["Konfidenz"] >= 75]),
                           ("Konfidenz < 75", mit[mit["Konfidenz"] < 75])):
            if not part.empty:
                lines.append(f"    {name:<16} {len(part):>3} Tage, Richtung richtig "
                             f"{_pct(part['Richtung_richtig'])}")
    neu = df[df["Bias"] == "neutral"]
    if not neu.empty:
        lines.append(f"  An NEUTRAL-Tagen: Ø Spanne nach 15:30 {f(neu['Bewegung'].abs().mean())} "
                     "(Schluss-Abstand, egal welche Richtung)")
    lines.append(f"  Vergleich: Anteil Tage mit Schluss über 15:30-Preis: "
                 f"{(df['Bewegung'] > 0).mean():.0%} (= Trefferquote von 'immer bullish')")
    lines.append(f"  Zeitpunkt genau (M15): {int((df['genau'] == 'ja').sum())} Tage, "
                 f"Näherung (H1 ab 15:00): {int((df['genau'] != 'ja').sum())} Tage")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Welche Kriterien bringen wirklich etwas?
# ---------------------------------------------------------------------------
def wilson(hits: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95-%-Vertrauensbereich für eine Trefferquote (Wilson-Methode)."""
    if n == 0:
        return 0.0, 1.0
    p = hits / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / denom
    return center - half, center + half


def _eval_pred(df: pd.DataFrame, pred: pd.Series) -> dict | None:
    """Bewertet eine Richtungs-Vorhersage (bullish/bearish) gegen die Bewegung nach 15:30."""
    m = pred.notna() & (df["Bewegung"] != 0)
    if m.sum() == 0:
        return None
    sub, p = df[m], pred[m]
    bull = p == structure.BULLISH
    hit = (bull & (sub["Bewegung"] > 0)) | (~bull & (sub["Bewegung"] < 0))
    # Zufall: Wie oft hätte man mit dieser Mischung aus bullish/bearish rein
    # zufällig recht? (berücksichtigt, dass es mehr Auf- oder Abwärtstage gibt)
    up = sub["Symbol"].map(df.groupby("Symbol")["Bewegung"].apply(lambda x: (x > 0).mean()))
    zufall = float((up.where(bull, 1 - up)).mean())
    mfe = (sub["Hoch_danach"] - sub["Preis_15_30"]).where(bull, sub["Preis_15_30"] - sub["Tief_danach"])
    mae = (sub["Preis_15_30"] - sub["Tief_danach"]).where(bull, sub["Hoch_danach"] - sub["Preis_15_30"])
    n, k = len(sub), int(hit.sum())
    lo, hi = wilson(k, n)
    if lo > zufall:
        urteil = "BESSER als Zufall"
    elif hi < zufall:
        urteil = "SCHLECHTER als Zufall"
    else:
        urteil = "nicht unterscheidbar"
    return {"n": n, "quote": k / n, "lo": lo, "hi": hi, "zufall": zufall,
            "mfe_mae": float((mfe > mae).mean()), "urteil": urteil}


def kriterien_report(df: pd.DataFrame, titel: str) -> str:
    rows = []
    for col in [c for c in df.columns if c.startswith("K_")]:
        r = _eval_pred(df, df[col])
        if r:
            rows.append((col[2:].replace("_", " "), r))
    bias_pred = df["Bias"].where(df["Bias"] != "neutral")
    for name, mask in (("FINALER BIAS (alle)", df["Bias"] != "neutral"),
                       ("Bias Konfidenz >= 75", (df["Bias"] != "neutral") & (df["Konfidenz"] >= 75)),
                       ("Bias Konfidenz 55-74", (df["Bias"] != "neutral") & (df["Konfidenz"] < 75)),
                       ("Bias H4-geführt", df["Modus"] == "H4")):
        r = _eval_pred(df, bias_pred.where(mask))
        if r:
            rows.append((name, r))
    for phase in sorted(df["H4_Phase"].dropna().unique()):
        r = _eval_pred(df, df["K_Daily_Trend"].where(df["H4_Phase"] == phase))
        if r:
            rows.append((f"Daily-Trend bei '{phase}'", r))

    out = [titel, "-" * 104,
           f"{'Kriterium':<34}{'Tage':>6}{'Treffer':>9}{'95%-Bereich':>15}{'Zufall':>8}"
           f"{'MFE>MAE':>9}   Urteil"]
    for name, r in rows:
        bereich = f"{r['lo']:.0%}–{r['hi']:.0%}"
        out.append(f"{name:<34}{r['n']:>6}{r['quote']:>9.0%}{bereich:>15}"
                   f"{r['zufall']:>8.0%}{r['mfe_mae']:>9.0%}   {r['urteil']}")
    return "\n".join(out)


def main() -> None:
    p = argparse.ArgumentParser(description="Backtest: Bias um 15:30 vs. Preisbewegung danach")
    p.add_argument("--symbol", choices=list(config.INSTRUMENTS), help="Standard: alle")
    p.add_argument("--monate", type=int, default=3)
    p.add_argument("--uhrzeit", default="15:30", help="Berliner Zeit, Standard 15:30")
    args = p.parse_args()

    os.makedirs(OUT_DIR, exist_ok=True)
    texte, alle = [], []
    for sym in ([args.symbol] if args.symbol else list(config.INSTRUMENTS)):
        df = run(sym, args.monate, args.uhrzeit)
        df.insert(0, "Symbol", sym)
        df.to_csv(os.path.join(OUT_DIR, f"backtest_{sym}.csv"), index=False,
                  sep=";", decimal=",", encoding="utf-8-sig")
        texte.append(summary(sym, df, config.INSTRUMENTS[sym]["decimals"]))
        texte.append(kriterien_report(df, f"Kriterien einzeln – {sym}"))
        print(texte[-2] + "\n\n" + texte[-1] + "\n", flush=True)
        alle.append(df)
    if len(alle) > 1:
        gesamt = pd.concat(alle, ignore_index=True)
        texte.append(kriterien_report(gesamt, "Kriterien einzeln – ALLE Instrumente zusammen"))
        print(texte[-1] + "\n")
    with open(os.path.join(OUT_DIR, "zusammenfassung.txt"), "w", encoding="utf-8") as fh:
        fh.write("\n\n".join(texte) + "\n")
    print(f"Ergebnisse gespeichert in {OUT_DIR}/")


if __name__ == "__main__":
    main()
