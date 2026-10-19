"""
bias.py – Daily Bias nach allgemeinen ICT-Kriterien.

Bausteine:
  1. HTF-Trend (Daily + H4-Phase, aus structure.py)  -> gibt die Richtung vor
  2. Previous-Day-Logik: Was hat die Vortageskerze mit dem Tag davor gemacht?
  3. Premium/Discount im aktuellen Daily-Bein
  4. Draw on Liquidity (DOL): nächstes unberührtes Ziel in Bias-Richtung

Harte Regel 1: Der Bias kann NIE gegen den HTF-Trend zeigen.
  - HTF unklar                         -> NEUTRAL
  - Previous-Day-Signal gegen HTF      -> Widerspruch -> NEUTRAL
  - Konfidenz unter BIAS_MIN_CONFIDENCE -> NEUTRAL (zu schwach)
Lieber kein Trade als ein erzwungener Bias.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import pandas as pd

import config
import levels
import pois
import structure
import sweeps
from structure import (BEARISH, BULLISH, UNKLAR, HTFResult, StructureBreak,
                       TrendResult)

NEUTRAL = "NEUTRAL – kein Trade"

# Previous-Day-Signale
PD_FORTSETZUNG = "Fortsetzung"
PD_REVERSAL = "Reversal"
PD_INSIDE = "Inside Day"
PD_OUTSIDE = "Outside Day"
PD_KEIN = "kein klares Signal"


@dataclass
class PDSignal:
    kind: str                     # eine der PD_...-Konstanten
    direction: str | None         # BULLISH / BEARISH / None (neutral)
    text: str


@dataclass
class Target:
    name: str                     # z. B. "PDL", "Swing Low", "Daily-FVG"
    price: float
    time: pd.Timestamp | None = None


@dataclass
class H4Reversal:
    """Ein klarer H4-Trendwechsel: Liquidity Sweep + danach MSS."""
    direction: str                # BULLISH (Tief gesweept) / BEARISH (Hoch gesweept)
    level_name: str               # welches Level wurde gesweept (PDL, PWL, H4-Swing ...)
    level: float
    pattern: str                  # sweeps.MUSTER_A / MUSTER_B
    sweep_time: pd.Timestamp
    sweep_extreme: float          # Docht-Spitze des Sweeps (muss halten)
    mss: StructureBreak
    bos_after: bool               # gab es danach schon einen H4-BOS?


@dataclass
class BiasResult:
    bias: str                     # BULLISH / BEARISH / NEUTRAL
    confidence: int               # 0–100
    direction: str                # Richtung, auf die sich alles bezieht
    pro: list[str] = field(default_factory=list)
    contra: list[str] = field(default_factory=list)
    pd_signal: PDSignal | None = None
    targets: list[Target] = field(default_factory=list)
    mode: str = "Daily"           # "Daily" oder "H4" (H4-geführt)
    neutral_reason: str | None = None   # "htf_unklar" / "widerspruch" / "schwach"
    leg: object | None = None     # Dealing Range, die für Premium/Discount gilt
    h4_reversal: H4Reversal | None = None
    info: list[str] = field(default_factory=list)

    @property
    def dol(self) -> Target | None:
        return self.targets[0] if self.targets else None


def _fmt_default(x: float) -> str:
    return f"{x:g}"


def _day(d: pd.Timestamp) -> str:
    return f"{levels.WOCHENTAGE[d.weekday()]} {d:%d.%m.}"


# ---------------------------------------------------------------------------
# 1) Previous-Day-Logik
# ---------------------------------------------------------------------------
def previous_day_signal(daily_done: pd.DataFrame,
                        fmt: Callable[[float], str] = _fmt_default) -> PDSignal:
    """
    Vergleicht die letzte abgeschlossene Tageskerze (Vortag) mit der Kerze
    davor (Vor-Vortag). Aus Sicht des Vortags ist das Hoch vom Vor-Vortag
    "sein PDH".

      Schluss über dem PDH           -> bullishe Fortsetzung
      Schluss unter dem PDL          -> bearishe Fortsetzung
      PDH gesweept, Schluss in Range -> mögliches bearishes Reversal
      PDL gesweept, Schluss in Range -> mögliches bullishes Reversal
      beide gesweept, in Range       -> Outside Day (unklar)
      keins von beiden               -> Inside Day (Bias schwach)
    """
    if len(daily_done) < 2:
        return PDSignal(PD_KEIN, None, "zu wenig Tageskerzen")
    pd_, pd1 = daily_done.iloc[-1], daily_done.iloc[-2]
    t, t1 = _day(daily_done.index[-1]), _day(daily_done.index[-2])
    hi1, lo1 = pd1["High"], pd1["Low"]

    if pd_["Close"] > hi1:
        return PDSignal(PD_FORTSETZUNG, BULLISH,
                        f"Vortag ({t}) schloss über dem Hoch vom {t1} ({fmt(hi1)}) "
                        "-> bullishe Fortsetzung Richtung Buy-Side Liquidity")
    if pd_["Close"] < lo1:
        return PDSignal(PD_FORTSETZUNG, BEARISH,
                        f"Vortag ({t}) schloss unter dem Tief vom {t1} ({fmt(lo1)}) "
                        "-> bearishe Fortsetzung Richtung Sell-Side Liquidity")

    swept_h, swept_l = pd_["High"] > hi1, pd_["Low"] < lo1
    if swept_h and swept_l:
        return PDSignal(PD_OUTSIDE, None,
                        f"Vortag ({t}) hat Hoch UND Tief vom {t1} gesweept und in "
                        "der Range geschlossen -> Outside Day, kein klares Signal")
    if swept_h:
        return PDSignal(PD_REVERSAL, BEARISH,
                        f"Vortag ({t}) hat das Hoch vom {t1} ({fmt(hi1)}) gesweept "
                        "und darunter geschlossen -> mögliches bearishes Reversal")
    if swept_l:
        return PDSignal(PD_REVERSAL, BULLISH,
                        f"Vortag ({t}) hat das Tief vom {t1} ({fmt(lo1)}) gesweept "
                        "und darüber geschlossen -> mögliches bullishes Reversal")
    return PDSignal(PD_INSIDE, None,
                    f"Vortag ({t}) war ein Inside Day innerhalb vom {t1} "
                    "-> Bias schwach")


# ---------------------------------------------------------------------------
# 2) Draw on Liquidity
# ---------------------------------------------------------------------------
def _reached_since(price: float, side: str, later: pd.DataFrame) -> bool:
    """Wurde 'price' in den Kerzen 'later' schon erreicht (Docht reicht)?"""
    if later.empty:
        return False
    if side == "high":
        return bool(later["High"].max() > price)
    return bool(later["Low"].min() < price)


def find_targets(direction: str, last_price: float, report: levels.LevelReport,
                 daily_done: pd.DataFrame, daily_res: TrendResult,
                 today: pd.DataFrame) -> list[Target]:
    """
    Sammelt unberührte Liquiditätsziele in Bias-Richtung, sortiert nach Abstand.

    bullish -> Ziele ÜBER dem Preis: PDH, PWH, unberührte Swing Highs,
               offene bearishe Daily-FVGs (Ziel = Unterkante)
    bearish -> Ziele UNTER dem Preis: PDL, PWL, unberührte Swing Lows,
               offene bullishe Daily-FVGs (Ziel = Oberkante)
    today   = Intraday-Kerzen nach der letzten abgeschlossenen Tageskerze
    """
    bull = direction == BULLISH
    side = "high" if bull else "low"
    beyond = (lambda p: p > last_price) if bull else (lambda p: p < last_price)
    targets: list[Target] = []

    # PDH/PWH bzw. PDL/PWL – nur wenn noch nicht genommen
    for name in (("PDH", "PWH") if bull else ("PDL", "PWL")):
        lv = report.levels[name]
        if not lv.taken and beyond(lv.price):
            targets.append(Target(name, lv.price, lv.formed_at))

    # Unberührte Daily-Swings
    start = max(0, len(daily_done) - config.DOL_LOOKBACK_DAYS)
    for s in daily_res.swings:
        if s.kind != side or s.pos < start or not beyond(s.price):
            continue
        later = pd.concat([daily_done.iloc[s.pos + 1:][["High", "Low"]],
                           today[["High", "Low"]]])
        if not _reached_since(s.price, side, later):
            label = "Swing High" if bull else "Swing Low"
            targets.append(Target(f"{label} {_day(s.time)}", s.price, s.time))

    # Offene Daily-FVGs auf der Zielseite
    want = BEARISH if bull else BULLISH
    for f in pois.find_fvgs(daily_done.iloc[start:]):
        if f.direction != want or not f.is_open:
            continue
        edge = f.bottom if bull else f.top           # erste Kante, die erreicht wird
        if beyond(edge) and not _reached_since(edge, side, today):
            targets.append(Target(f"Daily-FVG {_day(f.time)}", edge, f.time))

    # Doppelte Preise zusammenfassen (z. B. PDH = PWH)
    merged: dict[float, Target] = {}
    for t in targets:
        if t.price in merged:
            merged[t.price].name += f" / {t.name}"
        else:
            merged[t.price] = t
    return sorted(merged.values(), key=lambda t: abs(t.price - last_price))


# ---------------------------------------------------------------------------
# 3) H4-Umkehr finden: Liquidity Sweep + danach MSS
# ---------------------------------------------------------------------------
def _liquidity_levels(i: int, side: str, h4: pd.DataFrame, h4_res: TrendResult,
                      daily_all: pd.DataFrame | None,
                      weekly_all: pd.DataFrame | None) -> list[tuple[str, float]]:
    """
    Welche Liquiditäts-Levels hat H4-Kerze i mit dem Docht genommen?
    side = "low" (für bullishe Umkehr) oder "high" (für bearishe Umkehr).
    Reihenfolge = Wichtigkeit: PWL/PWH, PDL/PDH, dann unberührte H4-Swings.
    """
    t = h4.index[i]
    wick = h4["Low"].iloc[i] if side == "low" else h4["High"].iloc[i]
    col = "Low" if side == "low" else "High"
    taken = (lambda p: wick < p) if side == "low" else (lambda p: wick > p)
    out: list[tuple[str, float]] = []

    for name, df in (("PWL" if side == "low" else "PWH", weekly_all),
                     ("PDL" if side == "low" else "PDH", daily_all)):
        if df is None or df.empty:
            continue
        done = df[df["end"] <= t]
        if not done.empty and taken(float(done[col].iloc[-1])):
            out.append((name, float(done[col].iloc[-1])))

    kind = "low" if side == "low" else "high"
    for s in reversed(h4_res.swings):
        if s.kind != kind or s.confirmed_pos >= i or not taken(s.price):
            continue
        between = h4.iloc[s.pos + 1:i]
        schon_weg = (not between.empty and
                     (between["Low"].min() < s.price if side == "low"
                      else between["High"].max() > s.price))
        if not schon_weg:
            out.append((f"H4-Swing {'Low' if side == 'low' else 'High'} "
                        f"{s.time:%d.%m. %H:%M}", s.price))
    return out


def find_h4_reversal(h4: pd.DataFrame, h4_res: TrendResult,
                     daily_all: pd.DataFrame | None = None,
                     weekly_all: pd.DataFrame | None = None) -> H4Reversal | None:
    """
    Sucht einen KLAREN H4-Trendwechsel:
      1. Der H4-Trend hat zuletzt per MSS gedreht (danach kein Bruch dagegen).
      2. Der MSS ist frisch (höchstens H4_LEAD_MAX_AGE Kerzen alt).
      3. Höchstens H4_LEAD_SWEEP_WINDOW Kerzen davor gab es einen Liquidity
         Sweep nach deinen LQS-Kriterien (Ablehnungskerze / 2-Kerzen-Umkehr)
         an PWL/PDL/H4-Swing Low (bullish) bzw. PWH/PDH/H4-Swing High (bearish).
      4. Seit dem Sweep hat KEIN Schlusskurs das Sweep-Extrem verletzt.
    h4 = abgeschlossene H4-Kerzen (dieselben wie in h4_res)
    """
    d = h4_res.trend
    if d == UNKLAR or not h4_res.breaks:
        return None

    # 1) Letzter Richtungswechsel: erster Bruch nach dem letzten Gegen-Bruch
    br = h4_res.breaks
    k = len(br) - 1
    while k > 0 and br[k - 1].direction == d:
        k -= 1
    mss = br[k]
    if mss.kind != "MSS":
        return None
    # 2) frisch?
    if mss.pos < len(h4) - config.H4_LEAD_MAX_AGE:
        return None

    # 3) Sweep davor suchen (von der MSS-Kerze rückwärts)
    side = "low" if d == BULLISH else "high"
    for i in range(mss.pos, max(mss.pos - config.H4_LEAD_SWEEP_WINDOW, 0) - 1, -1):
        for name, lv in _liquidity_levels(i, side, h4, h4_res, daily_all, weekly_all):
            found = sweeps.lqs_pattern(h4, i, lv, side, last=mss.pos)
            if found is None:
                continue
            pattern, a, e = found
            seg = h4.iloc[a:e + 1]          # alle Kerzen des Musters
            extreme = float(seg["Low"].min() if side == "low" else seg["High"].max())
            # 4) Sweep-Extrem hält per Schlusskurs?
            after = h4["Close"].iloc[e + 1:]
            verletzt = (after < extreme).any() if side == "low" else (after > extreme).any()
            if verletzt:
                return None
            bos_after = any(b.kind == "BOS" for b in br[k + 1:])
            return H4Reversal(d, name, lv, pattern, h4.index[i], extreme, mss, bos_after)
    return None


# ---------------------------------------------------------------------------
# 4) Alles zusammen: der Daily Bias (mit H4-Führung, wenn der Daily unklar ist)
# ---------------------------------------------------------------------------
def _score_zone_and_dol(res: BiasResult, plus, d: str, leg, label: str,
                        report: levels.LevelReport, daily_done, daily_res,
                        today, fmt) -> None:
    """Premium/Discount und Draw on Liquidity – gleich für Daily und H4-Führung."""
    richtung = "nach unten" if d == BEARISH else "nach oben"
    if leg is not None:
        zone = leg.zone(report.last_price)
        pct = leg.position(report.last_price)
        gut = "Premium" if d == BEARISH else "Discount"
        if zone == gut:
            plus("zone_passt", f"Preis im {label}-{zone} ({pct:.0%} der Range)")
        else:
            plus("zone_falsch", f"Preis im {label}-{zone} ({pct:.0%} der Range), "
                                f"für {d} besser im {gut}")
    res.targets = find_targets(d, report.last_price, report, daily_done, daily_res, today)
    if res.dol:
        plus("dol_vorhanden", f"DOL: {res.dol.name} bei {fmt(res.dol.price)}")
    else:
        plus("dol_fehlt", f"kein unberührtes Liquiditätsziel {richtung} gefunden")


def _finish(res: BiasResult, score: int) -> BiasResult:
    res.confidence = int(max(0, min(100, score)))
    if res.confidence >= config.BIAS_MIN_CONFIDENCE:
        res.bias = res.direction
    else:
        res.neutral_reason = "schwach"
        res.contra.append(f"Konfidenz unter {config.BIAS_MIN_CONFIDENCE} % -> zu schwach")
    return res


def compute_bias(htf: HTFResult, daily_res: TrendResult, daily_done: pd.DataFrame,
                 report: levels.LevelReport, today: pd.DataFrame,
                 fmt: Callable[[float], str] = _fmt_default,
                 h4_rev: H4Reversal | None = None,
                 h4_candles: pd.DataFrame | None = None,
                 h4_res: TrendResult | None = None) -> BiasResult:
    """
    1. Daily-Bias wie gewohnt.
    2. Ist er NEUTRAL, weil der Daily unklar ist oder sich widerspricht, und
       zeigt der H4 einen klaren Trendwechsel (h4_rev), darf der H4 führen.
    """
    res = _daily_bias(htf, daily_res, daily_done, report, today, fmt)
    if res.bias != NEUTRAL or res.neutral_reason not in ("htf_unklar", "widerspruch"):
        return res
    if not config.H4_LEAD:
        return res
    if h4_rev is None:
        res.info.append("H4 geprüft: kein klarer H4-Trendwechsel (Sweep + MSS) -> bleibt NEUTRAL")
        return res

    lead = _h4_led_bias(htf, daily_res, daily_done, report, today, fmt,
                        h4_rev, h4_candles, h4_res, res)
    return lead if lead is not None else res


def _h4_led_bias(htf, daily_res, daily_done, report, today, fmt,
                 rev: H4Reversal, h4_candles, h4_res, daily_result: BiasResult):
    P = config.BIAS_POINTS
    d = rev.direction
    sig = daily_result.pd_signal

    # Sicherung: Gegen einen klaren Daily-Trend nur, wenn auch der Previous Day
    # in H4-Richtung zeigt – sonst ist der H4 nur ein Retracement.
    gegen_daily = htf.trend not in (UNKLAR, d)
    if gegen_daily and not (config.H4_LEAD_AGAINST_DAILY and sig and sig.direction == d):
        daily_result.info.append(
            f"H4 dreht {d}, aber gegen den Daily-Trend ({htf.trend}) ohne passendes "
            "Previous-Day-Signal -> nur Retracement, bleibt NEUTRAL")
        return None

    res = BiasResult(NEUTRAL, 0, d, pd_signal=sig, mode="H4", h4_reversal=rev)
    grund = "Trend unklar" if daily_result.neutral_reason == "htf_unklar" else "Widerspruch"
    res.info.append(f"Daily allein: NEUTRAL ({grund}) -> H4-Umkehr gefunden, H4 wird geprüft")
    score = config.BIAS_START

    def plus(key: str, text: str):
        nonlocal score
        score += P[key]
        (res.pro if P[key] > 0 else res.contra).append(f"{text} ({P[key]:+d})")

    richtung = "nach unten" if d == BEARISH else "nach oben"
    plus("h4_lqs", f"H4-LQS ({rev.pattern}) an {rev.level_name} {fmt(rev.level)}, "
                   f"Spitze {fmt(rev.sweep_extreme)}")
    plus("h4_mss", f"danach H4-MSS {richtung} per Körper")
    if rev.bos_after:
        plus("h4_bos_danach", f"H4-BOS {richtung} bestätigt")
    plus("h4_gefuehrt", "H4-geführt: Daily hat den Wechsel noch nicht bestätigt")
    if gegen_daily:
        plus("gegen_daily", f"noch gegen den Daily-Trend ({htf.trend})")

    if sig and sig.direction == d:
        plus("pd_passt", sig.text)
    elif sig and sig.direction is not None:
        plus("pd_gegen", sig.text)
    elif sig and sig.kind == PD_INSIDE:
        plus("pd_inside", sig.text)
    elif sig and sig.kind == PD_OUTSIDE:
        plus("pd_outside", sig.text)

    # Premium/Discount im H4-Bein (vom Sweep bis zum Hoch/Tief danach)
    leg = None
    if h4_candles is not None and h4_res is not None:
        leg = structure.daily_leg(h4_candles, h4_res)
        if leg is not None and leg.invalidated:
            leg = None
    res.leg = leg
    _score_zone_and_dol(res, plus, d, leg, "H4", report, daily_done, daily_res, today, fmt)
    res = _finish(res, score)
    res.info.append(f"-> H4 übernimmt die Führung: {d}" if res.bias != NEUTRAL
                    else "-> H4-Signal reicht nicht (Konfidenz zu niedrig), bleibt NEUTRAL")
    return res


def _daily_bias(htf: HTFResult, daily_res: TrendResult, daily_done: pd.DataFrame,
                report: levels.LevelReport, today: pd.DataFrame,
                fmt: Callable[[float], str]) -> BiasResult:
    P = config.BIAS_POINTS
    d = htf.trend
    res = BiasResult(NEUTRAL, 0, d, leg=htf.leg)
    score = config.BIAS_START

    def plus(key: str, text: str):
        nonlocal score
        score += P[key]
        (res.pro if P[key] > 0 else res.contra).append(f"{text} ({P[key]:+d})")

    # --- Harte Regel 1: ohne klaren HTF-Trend kein Bias ----------------------
    res.pd_signal = previous_day_signal(daily_done, fmt)
    if d == UNKLAR:
        res.neutral_reason = "htf_unklar"
        res.contra.append("HTF-Trend (Daily) unklar oder Struktur verletzt")
        res.contra += htf.reasons_contra
        return res
    richtung = "nach unten" if d == BEARISH else "nach oben"

    # --- Daily-Struktur -------------------------------------------------------
    last = daily_res.last_break
    if last.kind == "BOS":
        plus("daily_bos", f"Daily BOS {richtung}, Trend bestätigt")
    else:
        res.pro.append(f"Daily MSS {richtung}")
        plus("daily_mss_frisch", "Trendwechsel frisch, noch kein Daily-BOS")

    # --- H4-Phase -------------------------------------------------------------
    if htf.h4_phase == structure.H4_MIT_DAILY:
        plus("h4_mit_daily", "H4 läuft mit dem Daily")
    elif htf.h4_phase == structure.H4_RETRACE_ENDE:
        tief = not any("nicht erreicht" in r for r in htf.reasons_contra)
        if tief:
            plus("h4_retrace_ende_tief", "H4-MSS zurück in Daily-Richtung nach tiefem Retracement")
        else:
            plus("h4_retrace_ende_flach", "H4-MSS zurück in Daily-Richtung, Retracement aber flach")
    elif htf.h4_phase == structure.H4_RETRACE:
        if htf.zone == ("Premium" if d == BEARISH else "Discount"):
            res.pro.append("H4-Retracement im richtigen Daily-Bereich – auf M15-Bestätigung warten")
        else:
            plus("h4_retrace_offen", "H4-Retracement läuft noch, Daily-Bereich nicht erreicht")

    # --- Previous Day ---------------------------------------------------------
    sig = res.pd_signal
    if sig.direction is not None and sig.direction != d:
        res.contra.append(f"WIDERSPRUCH: {sig.text}, Daily-Trend ist aber {d}")
        res.confidence = 0
        res.neutral_reason = "widerspruch"
        return res                               # -> NEUTRAL (H4 darf evtl. führen)
    if sig.direction == d:
        plus("pd_passt", sig.text)
    elif sig.kind == PD_INSIDE:
        plus("pd_inside", sig.text)
    elif sig.kind == PD_OUTSIDE:
        plus("pd_outside", sig.text)

    # --- Premium / Discount + Draw on Liquidity ------------------------------
    _score_zone_and_dol(res, plus, d, htf.leg, "Daily", report, daily_done,
                        daily_res, today, fmt)
    return _finish(res, score)
