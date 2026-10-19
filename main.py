"""
main.py – Startpunkt des Tools.

Beispiele:
    python main.py --symbol US100
    python main.py --symbol EURUSD
    python main.py --symbol US100 --asof "2026-10-15 09:30"     (Zeitreise, NY-Zeit)
    python main.py --symbol US100 --csv meine_daten.csv --csv-tz Europe/Berlin
"""

from __future__ import annotations

import argparse
from types import SimpleNamespace

import pandas as pd

import bias
import config
import data
import levels
import pois
import sessions
import signals
import structure
import sweeps


# ---------------------------------------------------------------------------
# Hilfsfunktionen für schöne Ausgabe
# ---------------------------------------------------------------------------
def fmt_price(x: float, decimals: int) -> str:
    """21480.25 -> '21.480,25' (deutsches Zahlenformat)."""
    s = f"{x:,.{decimals}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def fmt_time(ts: pd.Timestamp | None) -> str:
    """Zeigt einen Zeitpunkt in NY- und Berliner Zeit."""
    if ts is None:
        return "Zeitpunkt unbekannt"
    ny = ts.tz_convert(config.TZ_NY)
    be = ts.tz_convert(config.TZ_BERLIN)
    tag = levels.WOCHENTAGE[ny.weekday()]
    return f"{tag} {ny:%d.%m. %H:%M} NY  |  {be:%H:%M} Berlin"


def print_report(symbol: str, inst: dict, tf: dict, rep: levels.LevelReport) -> None:
    dec = inst["decimals"]
    line = "=" * 64
    print(line)
    print(f" {symbol} – {inst['name']}")
    print(f" Stand: {fmt_time(rep.as_of)}")
    print(f" Letzter Preis: {fmt_price(rep.last_price, dec)}")
    print(line)

    print("\n Geladene Daten:")
    for key in ("W", "D", "H4", "H1", "M15"):
        if key in tf and not tf[key].empty:
            df = tf[key]
            first = df["start"].iloc[0] if "start" in df else df.index[0]
            print(f"   {key:<4} {len(df):>6} Kerzen  ab {first:%d.%m.%Y}")

    pdr, pwr = rep.prev_day, rep.prev_week
    print(f"\n Vortag  ({rep.levels['PDH'].period}): "
          f"{fmt_time(pdr['start'])}  bis  {pdr['end']:%H:%M} NY")
    print(f"   O {fmt_price(pdr['Open'], dec)}  H {fmt_price(pdr['High'], dec)}  "
          f"L {fmt_price(pdr['Low'], dec)}  C {fmt_price(pdr['Close'], dec)}")
    print(f" Vorwoche ({rep.levels['PWH'].period}): "
          f"{pwr['start']:%d.%m.} – {pwr['end']:%d.%m.%Y}")
    print(f"   O {fmt_price(pwr['Open'], dec)}  H {fmt_price(pwr['High'], dec)}  "
          f"L {fmt_price(pwr['Low'], dec)}  C {fmt_price(pwr['Close'], dec)}")

    print("\n Level           Preis        gebildet am                        seitdem")
    print(" " + "-" * 82)
    for lv in rep.levels.values():
        status = "überschritten" if lv.taken else "unberührt"
        dist = rep.last_price - lv.price
        print(f"  {lv.name:<4} {fmt_price(lv.price, dec):>14}   {fmt_time(lv.formed_at):<36} "
              f"{status:<17} (Abstand {fmt_price(dist, dec)})")
    print()


def fmt_date(d: pd.Timestamp, weekly: bool = False) -> str:
    if weekly:
        iso = d.isocalendar()
        return f"KW {iso.week:>2}/{iso.year}"
    return f"{levels.WOCHENTAGE[d.weekday()]} {d:%d.%m.%Y}"


def fmt_when(t: pd.Timestamp, timeframe: str) -> str:
    """Datum passend zum Timeframe: KW, Tag oder Tag + Uhrzeit."""
    if timeframe == "Weekly":
        return fmt_date(t, weekly=True)
    if t.tzinfo is None:                     # Daily-Index (reines Datum)
        return fmt_date(t)
    return fmt_time(t)


def print_structure(inst: dict, results: list[structure.TrendResult],
                    htf: structure.HTFResult, last_price: float) -> None:
    dec = inst["decimals"]
    an = [tf for tf, on in config.CANDLE_MSS.items() if on]
    print(f" Marktstruktur (Swing-Länge Daily {config.SWING_LENGTH} / "
          f"H4 {config.SWING_LENGTH_H4}, Bruch nur per Kerzenkörper"
          + (f", Kerzen-MSS: {', '.join(an)})" if an else ")"))
    print(" " + "-" * 82)
    for res in results:
        info = "   (nur Info)" if res.timeframe == "Weekly" else ""
        print(f"  {res.timeframe:<7} Trend: {res.trend.upper()}{info}")
        for kind, label in (("high", "Swing High"), ("low", "Swing Low ")):
            s = res.last_swing(kind)
            if s:
                print(f"           letztes {label}: {fmt_price(s.price, dec):>12}  "
                      f"({fmt_when(s.time, res.timeframe)})")
        for b in res.breaks[-3:]:
            pfeil = "nach oben " if b.direction == structure.BULLISH else "nach unten"
            if b.source == "kerze":
                was = ("Hoch der Low-Kerze" if b.direction == structure.BULLISH
                       else "Tief der High-Kerze")
                ziel = f"{was} vom {fmt_when(b.swing.time, res.timeframe)} " \
                       f"({fmt_price(b.level, dec)}) per Körper gebrochen"
            else:
                ziel = f"Swing {fmt_price(b.level, dec)} gebrochen"
            print(f"           {b.kind} {pfeil} {fmt_when(b.time, res.timeframe)}: {ziel}")
        print()

    leg = htf.leg
    if leg is not None:
        gesch = "Protected Low " if leg.direction == structure.BULLISH else "Protected High"
        ende = "Bein-Hoch     " if leg.direction == structure.BULLISH else "Bein-Tief     "
        print("  Daily-Bein (Dealing Range):")
        print(f"     {gesch}  {fmt_price(leg.protected, dec):>12}  ({fmt_when(leg.protected_time, 'Daily')})"
              + ("   VERLETZT" if leg.invalidated else ""))
        print(f"     {ende}  {fmt_price(leg.extreme, dec):>12}  ({fmt_when(leg.extreme_time, 'H4')})")
        print(f"     Equilibrium    {fmt_price(leg.equilibrium, dec):>12}  (50 %)")
        print(f"     Preis {fmt_price(last_price, dec)} liegt bei {leg.position(last_price):.0%} "
              f"der Range -> {leg.zone(last_price)}")
        print()

    kein = "   (kein Trade – Daily nicht eindeutig)" if htf.trend == structure.UNKLAR else ""
    print(f"  ==> HTF-Trend: {htf.trend.upper()}{kein}")
    print(f"      H4-Phase : {htf.h4_phase}")
    for r in htf.reasons_pro:
        print(f"      + {r}")
    for r in htf.reasons_contra:
        print(f"      - {r}")
    for r in htf.info:
        print(f"      i {r}")
    print()


def po3_levels(a, ranges, direction: str, as_of) -> list[tuple]:
    """
    Levels auf der Manipulations-Seite (bullish -> Tiefs, bearish -> Hochs):
    PDL/PDH und die relevanten Sessions seit Vortagsschluss, je mit "existiert ab".
    """
    bull = direction == structure.BULLISH
    pd_end = a.report.prev_day["end"]
    out = [("PDL", a.report.levels["PDL"].price, pd_end) if bull
           else ("PDH", a.report.levels["PDH"].price, pd_end)]
    for r in ranges:
        if r.relevant and r.end > pd_end:
            out.append((f"{r.name} Low", r.low, r.end) if bull
                       else (f"{r.name} High", r.high, r.end))
    return out


def print_sessions(inst: dict, ranges, run, po3, as_of, po3_moeglich: bool = False) -> None:
    dec = inst["decimals"]
    f = lambda x: fmt_price(x, dec)  # noqa: E731
    print(" Sessions (letzte abgeschlossene, Zeiten in Berlin)")
    print(" " + "-" * 82)
    # Zeitumstellung: NY normalerweise 6 h hinter Berlin
    diff = (as_of.tz_convert(config.TZ_BERLIN).utcoffset()
            - as_of.tz_convert(config.TZ_NY).utcoffset())
    if diff != pd.Timedelta(hours=6):
        print(f"  ACHTUNG Zeitumstellung: Berlin ist diese Woche nur {diff.seconds // 3600} h "
              "vor New York -> NY-Sessions beginnen 1 h früher (Berliner Zeit)!")
    for r in ranges:
        s, e = r.start.tz_convert(config.TZ_BERLIN), r.end.tz_convert(config.TZ_BERLIN)
        tag = levels.WOCHENTAGE[s.weekday()]
        hinweis = "" if r.relevant else "   (meist irrelevant)"
        if not r.genau and r.name == config.PO3_PREMARKET:
            hinweis += "   (nur H1-Daten: ungenau)"
        print(f"  {r.name:<14} {tag} {s:%H:%M}–{e:%H:%M}   High {f(r.high):>12}   "
              f"Low {f(r.low):>12}{hinweis}")
    if run is not None:
        print(f"  läuft gerade: {run.name} (bisher High {f(run.high)} / Low {f(run.low)})")
    if po3 is not None:
        print(f"\n  Power of 3 ({po3.direction}):")
        for line in po3.lines:
            print(f"    - {line}")
    elif po3_moeglich:
        print("\n  Power of 3: heute noch kein Midnight Open (Wochenende oder vor 06:00 Berlin)")
    print()


def print_sweeps(inst: dict, points: list[sweeps.SweepPoint], htf_trend: str,
                 status_tf: str) -> None:
    dec = inst["decimals"]
    print(" Sweep-Punkte (Beobachtungsliste – den Sweep bewertest DU im M15)")
    print(" " + "-" * 82)
    for p in points:
        if p.valid:
            urteil = "GÜLTIG  "
        else:
            urteil = "ungültig"
        extra = "" if p.relevant else "  (meist irrelevant)"
        print(f"  {urteil} {p.name:<18} {fmt_price(p.price, dec):>12}   "
              f"Abstand {fmt_price(p.distance, dec):>10}   {status_tf}: {p.status}{extra}")
    if htf_trend == structure.UNKLAR:
        print("  -> Kein Bias: KEIN Sweep-Punkt gültig (kein Trade)")
    else:
        seite = "Hochs" if htf_trend == structure.BEARISH else "Tiefs"
        print(f"  -> Bias {htf_trend}: nur Sweeps von {seite} sind gültig (harte Regel 2)")

    print("\n Checkliste im M15 (selbst prüfen):")
    for item in sweeps.m15_checklist(htf_trend):
        box = "    " if item.startswith("    ") else "  [ ] "
        print(f"{box}{item.strip() if box == '  [ ] ' else item}")
    print()


def bias_title(b: bias.BiasResult) -> str:
    if b.bias == bias.NEUTRAL:
        return bias.NEUTRAL
    zusatz = {"H4": " (H4-geführt)", "Retracement": " (H4-Retracement)"}.get(b.mode, "")
    return b.bias.upper() + zusatz


def print_bias(inst: dict, b: bias.BiasResult) -> None:
    dec = inst["decimals"]
    print(" Daily Bias")
    print(" " + "-" * 82)
    print(f"  ==> BIAS: {bias_title(b)}   (Konfidenz {b.confidence} %)")
    for r in b.info:
        print(f"      i {r}")
    if b.h4_reversal:
        rv = b.h4_reversal
        richtung = "oben" if rv.direction == structure.BULLISH else "unten"
        print(f"      H4-Umkehr: {rv.pattern} an {rv.level_name} {fmt_price(rv.level, dec)} "
              f"({fmt_time(rv.sweep_time)})")
        print(f"                 -> MSS nach {richtung} {fmt_time(rv.mss.time)}, "
              f"Sweep-Extrem {fmt_price(rv.sweep_extreme, dec)} hält"
              + (", BOS danach" if rv.bos_after else ""))
    if b.pd_signal:
        print(f"      Previous Day: {b.pd_signal.text}")
    for r in b.pro:
        print(f"      + {r}")
    for r in b.contra:
        print(f"      - {r}")
    if b.targets:
        print("      Liquiditätsziele in HTF-Richtung (nächstes = DOL):")
        for t in b.targets[:4]:
            print(f"        {fmt_price(t.price, dec):>12}  {t.name}")
    print()


def build_pois(tf, d_done, daily, h4_done, h4, htf, b, today, intraday,
               price: float) -> dict:
    """Sucht und bewertet alle POIs. Rückgabe: dict mit Listen für die Ausgabe."""
    view = {"direction": b.direction, "A": [], "B": [], "against": 0, "m15": []}
    if b.direction == structure.UNKLAR:
        return view
    bias_ok = b.bias != bias.NEUTRAL

    daily_pois = (pois.find_fvgs(d_done, "Daily", extra=today)
                  + pois.find_order_blocks(d_done, daily.breaks, "Daily", extra=today))
    h4_pois = []
    if h4 is not None and h4_done is not None and not h4_done.empty:
        # Für die Mitigation zählen auch Kerzen nach der letzten fertigen H4-Kerze
        rest = None
        if intraday is not None:
            rest = intraday[intraday.index >= h4_done.index[-1] + pd.Timedelta(hours=4)]
        h4_pois = (pois.find_fvgs(h4_done, "H4", extra=rest)
                   + pois.find_order_blocks(h4_done, h4.breaks, "H4", extra=rest))
        h4_pois = [p for p in h4_pois if p.pos >= len(h4_done) - config.H4_POI_LOOKBACK]

    # Premium/Discount: Daily-Bein, bei H4-Führung das H4-Bein
    pois.grade_pois(daily_pois, h4_pois, b.direction, b.leg, h4_done,
                    h4.swings if h4 else [], bias_ok)
    view["A"] = pois.relevant(daily_pois, b.direction, price)
    view["B"] = pois.relevant(h4_pois, b.direction, price)
    view["against"] = sum(1 for p in daily_pois + h4_pois
                          if p.is_open and p.direction != b.direction)

    if "M15" in tf and not today.empty:
        m15_done = tf["M15"][tf["M15"].index < today.index[-1] + pd.Timedelta(minutes=15)]
        m15_fvgs = pois.find_fvgs(m15_done, "M15")
        view["m15"] = pois.m15_entry_hints(m15_fvgs, daily_pois + h4_pois,
                                           b.direction, today.index[0])
    return view


def poi_name(p: pois.POI) -> str:
    return f"{p.timeframe}-{p.kind}"


def print_pois(inst: dict, view: dict, price: float) -> None:
    dec = inst["decimals"]
    f = lambda x: fmt_price(x, dec)  # noqa: E731
    print(" POIs (Points of Interest)")
    print(" " + "-" * 82)
    if view["direction"] == structure.UNKLAR:
        print("  Kein klarer HTF-Trend -> keine POIs in Handelsrichtung.\n")
        return

    print(f"  Stufe A – Daily (Richtung {view['direction']}):")
    if not view["A"]:
        print("    keine offenen Daily-POIs in HTF-Richtung")
    for p in view["A"]:
        ort = "Preis IN der Zone" if p.distance(price) == 0 else f"Abstand {f(p.distance(price))}"
        tag = "handelbar" if p.tradable else "nicht handelbar (kein Bias)"
        print(f"    {poi_name(p):<10} {f(p.bottom)}–{f(p.top)}  {fmt_when(p.time, 'Daily')}  "
              f"Mitigation: {p.mitigation:<10} {p.zone or '':<8}  {ort}  -> {tag}")

    print(f"\n  Stufe B – H4 (zählt nur mit >= {config.H4_MIN_CONFIRMATIONS}/4 "
          "Bestätigungen, Richtung + Bereich ist Pflicht):")
    if not view["B"]:
        print("    keine offenen H4-POIs in HTF-Richtung")
    for p in view["B"]:
        ort = "Preis IN der Zone" if p.distance(price) == 0 else f"Abstand {f(p.distance(price))}"
        urteil = f"ZÄHLT (Stufe B, {p.n_checks}/4)" if p.stufe == "B" \
            else f"zählt nicht ({p.n_checks}/4)"
        print(f"    {poi_name(p):<10} {f(p.bottom)}–{f(p.top)}  {p.time:%d.%m. %H:%M} NY  "
              f"Mitigation: {p.mitigation}  {ort}  -> {urteil}")
        kurz = {pois.CHECK_ZONE: "Richtung+Bereich", pois.CHECK_DISP: "Displacement",
                pois.CHECK_SWEEP: "Sweep davor", pois.CHECK_DAILY: "Daily-Überschneidung"}
        print("        " + "  ".join(f"[{'x' if p.checks[c] else ' '}] {kurz[c]}"
                                     for c in pois.CHECKS))
    if view["against"]:
        print(f"\n  {view['against']} offene POIs GEGEN die HTF-Richtung ausgeblendet "
              "(harte Regel 1: nie handelbar)")

    if view["m15"]:
        print("\n  M15-Hinweis: heutige M15-FVGs innerhalb eines handelbaren HTF-POIs")
        print("  (möglicher Entry-Bereich – Sweep und MSS davor prüfst du selbst):")
        for m, host in view["m15"]:
            print(f"    M15-FVG {f(m.bottom)}–{f(m.top)}  {fmt_time(m.time)}  "
                  f"in {poi_name(host)} {f(host.bottom)}–{f(host.top)}")
    print()


def print_summary(symbol: str, inst: dict, b: bias.BiasResult,
                  points: list[sweeps.SweepPoint], view: dict, price: float,
                  sa: signals.Signal | None = None, sb: signals.Signal | None = None) -> None:
    dec = inst["decimals"]
    print("=" * 64)
    print(" ZUSAMMENFASSUNG")
    print("=" * 64)
    if sa and sb:
        print(f" {sa.name}: {sa.text}")
        print(f" {sb.name}: {sb.text}")
        print(f" -> {signals.verdict(sa, sb)}")
    if b.mode == "Retracement":
        print(f" {symbol} – Grundlage Signal B: {bias_title(b)}.")
    else:
        print(f" {symbol} – Bias: {bias_title(b)} (Konfidenz {b.confidence} %).")
    gruende = [r.rsplit(" (", 1)[0] for r in b.pro if not r.startswith("DOL:")]
    if gruende:
        print(" Gründe dafür: " + "; ".join(gruende) + ".")
    if b.contra:
        print(" Dagegen: " + "; ".join(r.rsplit(" (", 1)[0] for r in b.contra) + ".")
    if b.bias != bias.NEUTRAL and b.dol:
        print(f" DOL: {b.dol.name} bei {fmt_price(b.dol.price, dec)}.")
    gueltig = [p for p in points if p.valid and p.relevant
               and p.status != sweeps.KOERPER_JENSEITS][:5]
    if gueltig:
        print(" Gültige Sweep-Punkte (noch offen/angelaufen): " + ", ".join(
            f"{p.name} {fmt_price(p.price, dec)}" for p in gueltig) + ".")
    f = lambda x: fmt_price(x, dec)  # noqa: E731
    handelbar = [p for p in view["A"] + view["B"] if p.tradable]
    if handelbar:
        teile = []
        for p in sorted(handelbar, key=lambda p: p.distance(price))[:3]:
            extra = "Stufe A" if p.stufe == "A" else f"Stufe B, {p.n_checks}/4 Bestätigungen"
            teile.append(f"{poi_name(p)} {f(p.bottom)}–{f(p.top)} ({extra})")
        print(" POIs: " + ", ".join(teile) + ".")
    else:
        print(" POIs: keine handelbaren POIs in HTF-Richtung.")

    klar = b.bias != bias.NEUTRAL
    im_poi = next((p for p in handelbar if p.distance(price) == 0), None)

    def box(ok):
        return "[x]" if ok else "[ ]"
    print("\n Checkliste vor dem Trade:")
    print(f"  {box(klar)} Bias klar?" + ("" if klar else "  -> NEIN: heute kein Trade"))
    wer = {"H4": "H4-geführt", "Retracement": "Signal B"}.get(b.mode, "Daily")
    print(f"  {box(klar)} Trade in HTF-Richtung? ({wer}: nur {b.direction}e Trades erlaubt)"
          if klar else "  [ ] Trade in HTF-Richtung?")
    print("  [ ] Gültiger Sweep? (selbst im M15 prüfen, siehe Checkliste oben)")
    if im_poi:
        print(f"  [x] POI-Stufe? Preis ist in {poi_name(im_poi)} (Stufe {im_poi.stufe})")
    elif handelbar:
        nxt = min(handelbar, key=lambda p: p.distance(price))
        print(f"  [ ] POI-Stufe? Preis noch in keinem POI – nächster: {poi_name(nxt)} "
              f"{f(nxt.bottom)}–{f(nxt.top)} (Stufe {nxt.stufe})")
    else:
        print("  [ ] POI-Stufe? kein handelbarer POI")
    print("  [ ] M15-Bestätigung? (MSS per Körper + FVG)")
    print("\n Hinweis: Entscheidungshilfe, kein Signal. Die Entscheidung triffst du.")
    print()


# ---------------------------------------------------------------------------
# Programmstart
# ---------------------------------------------------------------------------
def print_signals(sa: signals.Signal, sb: signals.Signal, modus: str) -> None:
    print(" SIGNALE")
    print(" " + "-" * 82)
    for s, kenn in ((sa, "original"), (sb, "retracement")):
        aktiv = "  <== Grundlage für POIs/Sweeps/Checkliste" if (
            modus == kenn or (modus == "beide" and kenn == "original")) else ""
        print(f"  {s.name}: {s.text}{aktiv}")
        for r in s.reasons:
            print(f"      - {r}")
        if s.stats:
            print(f"      ({s.stats})")
    print(f"  ==> {signals.verdict(sa, sb)}")
    print(f"      Modus: {modus}  (umschalten mit --modus original | retracement | beide)")
    print()


def load_and_cut(symbol: str, csv: str | None = None, csv_tz: str = config.TZ_NY,
                 asof: str | None = None) -> tuple[dict, pd.Timestamp]:
    """Lädt die Daten und bestimmt den Analyse-Zeitpunkt (ggf. Zeitreise)."""
    tf = data.load_instrument(symbol, csv, csv_tz)
    if asof:
        as_of = pd.Timestamp(asof).tz_localize(config.TZ_NY)
        tf = data.cut_at(tf, as_of)
    elif csv:
        # Bei CSV: "jetzt" = Ende der letzten Kerze in der Datei
        base = next(tf[k] for k in ("M15", "H1", "H4") if k in tf) if "H4" in tf else None
        if base is not None:
            as_of = base.index[-1] + data.bar_spacing(base)
        else:
            as_of = tf["D"]["end"].iloc[-1]
    else:
        as_of = pd.Timestamp.now(tz=config.TZ_NY)
    return tf, as_of


def analyze_and_print(symbol: str, tf: dict, as_of: pd.Timestamp,
                      modus: str = "beide") -> SimpleNamespace:
    """Komplette Analyse mit Textausgabe. Gibt die Ergebnisse zurück (für app.py)."""
    inst = config.INSTRUMENTS[symbol]
    a = run_bias(tf, as_of, inst)
    print_report(symbol, inst, tf, a.report)
    print_structure(inst, [r for r in (a.weekly, a.daily, a.h4) if r], a.htf,
                    a.report.last_price)
    print_bias(inst, a.bias)

    # Die zwei Signale: A = Original Daily Bias, B = H4-Retracement
    sa, sb = signals.original_signal(a, symbol), signals.retracement_signal(a, symbol)
    print_signals(sa, sb, modus)
    b = signals.bias_for_mode(a, modus)   # danach richten sich POIs/Sweeps/Checkliste

    # Modul 2: POIs (Daily = Stufe A, H4 = Stufe B mit Bestätigungen)
    poi_view = build_pois(tf, a.d_done, a.daily, a.h4_done, a.h4, a.htf, b, a.today,
                          a.intraday, a.report.last_price)
    print_pois(inst, poi_view, a.report.last_price)

    # Sessions (Highs/Lows) + Power of 3
    sweep_dir = b.bias if b.bias != bias.NEUTRAL else structure.UNKLAR
    ranges, points = [], []
    if a.intraday is not None and not a.intraday.empty:
        ranges = sessions.session_ranges(a.intraday, as_of)
        po3 = None
        if sweep_dir != structure.UNKLAR:
            po3 = sessions.power_of_three(a.intraday, as_of, sweep_dir,
                                          po3_levels(a, ranges, sweep_dir, as_of),
                                          lambda x: fmt_price(x, inst["decimals"]))
        print_sessions(inst, ranges, sessions.running(a.intraday, as_of), po3, as_of,
                       po3_moeglich=sweep_dir != structure.UNKLAR)

        # Sweep-Punkte: gültig nur in BIAS-Richtung (bei NEUTRAL ist nichts gültig)
        points = sweeps.watchlist(a.report, sweep_dir, a.intraday, as_of, ranges)
        print_sweeps(inst, points, sweep_dir, a.status_tf)

    print_summary(symbol, inst, b, points, poi_view, a.report.last_price, sa, sb)
    # für Charts und Web-Oberfläche merken
    a.signal_a, a.signal_b, a.effective = sa, sb, b
    a.tf, a.as_of, a.poi_view, a.points, a.ranges = tf, as_of, poi_view, points, ranges
    a.symbol = symbol
    return a


def main() -> None:
    parser = argparse.ArgumentParser(description="ICT Top-Down-Analyse")
    parser.add_argument("--symbol", default="US100", choices=list(config.INSTRUMENTS),
                        help="Instrument aus config.py")
    parser.add_argument("--csv", help="CSV-Datei statt yfinance (Datum, Open, High, Low, Close)")
    parser.add_argument("--csv-tz", default=config.TZ_NY,
                        help="Zeitzone der Zeiten in der CSV (Standard: America/New_York)")
    parser.add_argument("--asof", help='Analyse-Zeitpunkt in NY-Zeit, z. B. "2026-10-15 09:30"')
    parser.add_argument("--modus", default="beide", choices=signals.MODI,
                        help="Grundlage für POIs/Sweeps/Checkliste: original, retracement "
                             "oder beide (= original, B wird zusätzlich angezeigt)")
    parser.add_argument("--chart", action="store_true",
                        help="interaktive Charts (Daily/H4/M15) als HTML in charts/ speichern")
    parser.add_argument("--hell", action="store_true", help="Charts im hellen Design")
    args = parser.parse_args()

    inst = config.INSTRUMENTS[args.symbol]
    print(f"Lade Daten für {args.symbol} ({'CSV: ' + args.csv if args.csv else inst['yf_symbol']}) ...")
    tf, as_of = load_and_cut(args.symbol, args.csv, args.csv_tz, args.asof)
    a = analyze_and_print(args.symbol, tf, as_of, args.modus)

    if args.chart:
        import chart   # erst hier laden: Plotly wird nur für Charts gebraucht
        figs = chart.build_all(a, args.symbol, "light" if args.hell else "dark")
        for path in chart.write_html(figs, args.symbol):
            print(f"Chart gespeichert: {path}")


def run_bias(tf: dict, as_of: pd.Timestamp, inst: dict) -> SimpleNamespace:
    """
    Schritte 1–3 ohne Ausgabe: Level, Marktstruktur, Daily Bias.
    Wird von main() und vom Backtest (backtest.py) benutzt.
    """
    # Schritt 1: PDH / PDL / PWH / PWL
    report = levels.compute_levels(tf, as_of)

    # Schritt 2: Marktstruktur (nur geschlossene Kerzen!)
    #   Daily = Richtung, H4 = Phase im Daily-Bein, Weekly = nur Info
    d_done = structure.completed(tf["D"], as_of)
    w_done = structure.completed(tf["W"], as_of)
    cm = config.CANDLE_MSS
    weekly = structure.analyze(w_done, "Weekly", candle_mss=cm.get("Weekly", False))
    daily = structure.analyze(d_done, "Daily", candle_mss=cm.get("Daily", False))
    h4, h4_done = None, None
    if "H4" in tf:
        h4_done = structure.completed(tf["H4"], as_of, pd.Timedelta(hours=4))
        h4 = structure.analyze(h4_done, "H4", n=config.SWING_LENGTH_H4,
                               candle_mss=cm.get("H4", False))
    htf = structure.htf_trend(daily, d_done, h4, report.last_price,
                              fine=tf.get("H4"), weekly_res=weekly,
                              h4_candles=h4_done)

    # Schritt 3: Daily Bias
    status_tf = config.STATUS_TIMEFRAME if config.STATUS_TIMEFRAME in tf else "H1"
    intraday = None
    if status_tf in tf and not tf[status_tf].empty:
        intraday = structure.completed(tf[status_tf], as_of, data.bar_spacing(tf[status_tf]))
    # "today" = Intraday-Kerzen nach der letzten abgeschlossenen Tageskerze
    if intraday is not None and not d_done.empty:
        today = intraday[intraday.index >= d_done["end"].iloc[-1]]
    else:
        today = pd.DataFrame(columns=["Open", "High", "Low", "Close"])
    fmt = lambda x: fmt_price(x, inst["decimals"])  # noqa: E731
    # H4-Umkehr (Sweep + MSS) – wird nur benutzt, wenn der Daily allein unklar ist
    h4_rev = None
    if h4 is not None and h4_done is not None and not h4_done.empty:
        h4_rev = bias.find_h4_reversal(h4_done, h4, d_done, w_done)
    b = bias.compute_bias(htf, daily, d_done, report, today, fmt,
                          h4_rev=h4_rev, h4_candles=h4_done, h4_res=h4)
    return SimpleNamespace(report=report, d_done=d_done, weekly=weekly, daily=daily,
                           h4=h4, h4_done=h4_done, htf=htf, bias=b, today=today,
                           intraday=intraday, status_tf=status_tf)


if __name__ == "__main__":
    main()
