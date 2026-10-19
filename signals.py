"""
signals.py – Die zwei Signale des Tools nebeneinander.

  Signal A – Original Daily Bias
      Unser ursprünglicher Bias: Daily-Struktur, Previous-Day-Logik,
      Premium/Discount, DOL, H4-Führung (siehe bias.py).

  Signal B – H4-Retracement
      Aktiv, wenn der Daily-Trend klar ist UND der H4 gerade dagegen läuft
      (Retracement im Daily-Bein, Protected Low/High hält).
      Richtung = Daily-Trend. Im 2-Jahres-Backtest war das die einzige
      Situation mit einem Vorteil (v. a. US100).

Der Modus bestimmt, nach welchem Signal sich POIs, Sweep-Punkte und
Checkliste richten:  "original", "retracement" oder "beide" (= nach A,
B wird zusätzlich angezeigt).
"""

from __future__ import annotations

import copy
import os
from dataclasses import dataclass, field

import pandas as pd

import bias
import structure

MODI = ("beide", "original", "retracement")
RETRACE_COLUMN = "Tool: Trend bei H4-Retracement"
ORIGINAL_COLUMN = "Tool: finaler Bias"
BACKTEST_DIR = "backtest_ergebnisse"


@dataclass
class Signal:
    name: str
    direction: str | None          # BULLISH / BEARISH / None (kein Signal)
    text: str                      # kurze Zusammenfassung
    reasons: list[str] = field(default_factory=list)
    stats: str = ""                # Trefferquote aus dem Backtest (falls vorhanden)

    @property
    def active(self) -> bool:
        return self.direction is not None


def history_stats(symbol: str, column: str, base_dir: str = BACKTEST_DIR) -> str:
    """Liest die Trefferquote eines Signals aus dem gespeicherten Methoden-Backtest."""
    path = os.path.join(base_dir, f"methoden_{symbol}.csv")
    if not os.path.exists(path):
        return "noch kein Backtest (python methoden_backtest.py)"
    try:
        df = pd.read_csv(path, sep=";", decimal=",", encoding="utf-8-sig")
    except (OSError, ValueError):
        return "Backtest-Datei nicht lesbar"
    if column not in df.columns:
        return "Signal nicht im Backtest enthalten"
    m = df[column].notna() & (df["Bewegung_Tagesende"] != 0)
    sub = df[m]
    if sub.empty:
        return "im Backtest nie aufgetreten"
    bull = sub[column] == structure.BULLISH
    hit = (bull & (sub["Bewegung_Tagesende"] > 0)) | (~bull & (sub["Bewegung_Tagesende"] < 0))
    return (f"Backtest {symbol}: {hit.mean():.0%} Treffer bei {len(sub)} Tagen "
            f"(Richtung 15:30 bis Tagesschluss)")


def original_signal(a, symbol: str | None = None) -> Signal:
    b = a.bias
    d = b.bias if b.bias != bias.NEUTRAL else None
    titel = "NEUTRAL – kein Trade" if d is None else (
        d.upper() + (" (H4-geführt)" if b.mode == "H4" else ""))
    s = Signal("Signal A – Original Daily Bias", d,
               f"{titel}, Konfidenz {b.confidence} %",
               [r.rsplit(" (", 1)[0] for r in b.pro[:4]])
    if symbol:
        s.stats = history_stats(symbol, ORIGINAL_COLUMN)
    return s


def retracement_signal(a, symbol: str | None = None) -> Signal:
    htf = a.htf
    active = htf.trend != structure.UNKLAR and htf.h4_phase == structure.H4_RETRACE
    name = "Signal B – H4-Retracement"
    if not active:
        warum = ("Daily-Trend unklar" if htf.trend == structure.UNKLAR
                 else f"H4-Phase: {htf.h4_phase} (kein Retracement gegen den Daily)")
        s = Signal(name, None, f"nicht aktiv – {warum}")
    else:
        leg = htf.leg
        gesch = "Protected Low" if htf.trend == structure.BULLISH else "Protected High"
        gute = "Discount" if htf.trend == structure.BULLISH else "Premium"
        tiefe = leg.retrace_depth() if leg else None
        reasons = [f"Daily-Trend {htf.trend} ({a.daily.last_break.kind}), {gesch} hält",
                   f"H4 läuft gegen den Daily ({a.h4.last_break.kind}) = Retracement"]
        if tiefe is not None:
            reasons.append(f"Retracement-Tiefe {tiefe:.0%} des Daily-Beins, "
                           f"Preis im {htf.zone or '?'}"
                           + ("" if htf.zone == gute else f" (ideal: {gute})"))
        reasons.append("Einstieg erst nach MSS zurück in Daily-Richtung (H4/M15)")
        s = Signal(name, htf.trend, f"{htf.trend.upper()} – Rücklauf im Daily-Trend", reasons)
    if symbol:
        s.stats = history_stats(symbol, RETRACE_COLUMN)
    return s


def bias_for_mode(a, modus: str) -> bias.BiasResult:
    """
    Liefert den BiasResult, nach dem sich POIs, Sweeps und Checkliste richten.
    "original"/"beide": unverändert. "retracement": Richtung aus Signal B
    (oder NEUTRAL, wenn B nicht aktiv ist).
    """
    if modus not in MODI:
        raise ValueError(f"Unbekannter Modus '{modus}', erlaubt: {', '.join(MODI)}")
    if modus != "retracement":
        return a.bias
    sig = retracement_signal(a)
    b = copy.copy(a.bias)
    b.pro, b.contra, b.info = list(sig.reasons), [], []
    b.mode, b.leg, b.h4_reversal = "Retracement", a.htf.leg, None
    if sig.active:
        b.bias, b.direction = sig.direction, sig.direction
        b.targets = bias.find_targets(sig.direction, a.report.last_price, a.report,
                                      a.d_done, a.daily, a.today)
    else:
        b.bias, b.direction = bias.NEUTRAL, a.htf.trend
        b.contra = [sig.text]
    return b


def verdict(sa: Signal, sb: Signal) -> str:
    """Kurzurteil, wenn beide Signale angezeigt werden."""
    if sa.active and sb.active:
        if sa.direction == sb.direction:
            return f"BEIDE Signale {sa.direction.upper()} – stärkste Lage"
        return "Signale widersprechen sich – kein Trade"
    if sa.active:
        return f"Nur Signal A ({sa.direction}) aktiv"
    if sb.active:
        return f"Nur Signal B ({sb.direction}) aktiv"
    return "Kein Signal aktiv – kein Trade"
