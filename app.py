"""
app.py – Kleine Web-Oberfläche für das Tool.

Start:   streamlit run app.py
Danach öffnet sich der Browser (sonst: http://localhost:8501).

Oben wählst du per Button die Ansicht:
  - Beide Signale        (Grundlage: Signal A, B wird zusätzlich angezeigt)
  - Signal A – Original Daily Bias
  - Signal B – H4-Retracement
POIs, Sweep-Punkte und Checkliste richten sich nach der gewählten Ansicht.
"""

import contextlib
import io

import pandas as pd
import streamlit as st

import config
import data
import main as tool
from structure import BEARISH, BULLISH

ANSICHTEN = {
    "Beide Signale": "beide",
    "Signal A – Original Daily Bias": "original",
    "Signal B – H4-Retracement": "retracement",
}

st.set_page_config(page_title="ICT Top-Down-Analyse", layout="wide")


@st.cache_data(ttl=600, show_spinner="Lade Kursdaten ...")
def lade(symbol: str) -> dict:
    """Daten nur alle 10 Minuten neu laden (yfinance ist langsam)."""
    return data.load_instrument(symbol)


def karte(spalte, signal, aktiv_als_grundlage: bool):
    with spalte:
        st.subheader(signal.name)
        if signal.direction == BULLISH:
            st.success(f"▲ {signal.text}")
        elif signal.direction == BEARISH:
            st.error(f"▼ {signal.text}")
        else:
            st.info(signal.text)
        for r in signal.reasons:
            st.markdown(f"- {r}")
        if signal.stats:
            st.caption(signal.stats)
        if aktiv_als_grundlage:
            st.caption("**Grundlage für POIs, Sweep-Punkte und Checkliste**")


INHALT = [
    ("signale", "Signale", "Signal A (Original Daily Bias) und Signal B (H4-Retracement)"),
    ("charts", "Charts Daily · H4 · M15", "Zonen, Sweep-Punkte, Premium/Discount, DOL"),
    ("h1-detail", "H1-Detailchart", "alle Highs/Lows als Linien, FVGs/OBs als Rechtecke"),
    ("checkliste", "Checkliste", "vor dem Trade abhaken"),
    ("positionsgroesse", "Positionsgröße", "Lots bei 1 % Risiko, CRV"),
    ("forward-test", "Forward-Test", "automatisches Protokoll um 15:30 + Auswertung"),
    ("meine-backtests", "Meine Backtests", "eigene Trades dokumentieren und auswerten"),
    ("komplette-analyse", "Komplette Analyse", "die ganze Textausgabe"),
]

# --- Seitenleiste ------------------------------------------------------------
with st.sidebar:
    st.header("Inhalt")
    st.markdown("\n".join(f"- [{titel}](#{anker})  \n  <small>{info}</small>"
                          for anker, titel, info in INHALT), unsafe_allow_html=True)
    st.divider()
    st.header("Einstellungen")
    symbol = st.selectbox("Instrument", list(config.INSTRUMENTS),
                          format_func=lambda s: f"{s} – {config.INSTRUMENTS[s]['name']}")
    zeitreise = st.checkbox("Zeitreise (früheren Zeitpunkt analysieren)")
    asof = None
    if zeitreise:
        tag = st.date_input("Datum")
        zeit = st.time_input("Uhrzeit (Berlin)", value=pd.Timestamp("15:30").time())
        asof = pd.Timestamp.combine(tag, zeit).tz_localize(config.TZ_BERLIN) \
            .tz_convert(config.TZ_NY)
    if st.button("Daten neu laden"):
        lade.clear()

# --- Hauptbereich --------------------------------------------------------------
st.title("ICT Top-Down-Analyse")
wahl = st.radio("Ansicht", list(ANSICHTEN), horizontal=True)
modus = ANSICHTEN[wahl]

try:
    tf = lade(symbol)
except RuntimeError as e:
    st.error(f"Keine Daten: {e}")
    st.stop()

if asof is not None:
    tf = data.cut_at(tf, asof)
    as_of = asof
else:
    as_of = pd.Timestamp.now(tz=config.TZ_NY)

puffer = io.StringIO()
with contextlib.redirect_stdout(puffer):
    a = tool.analyze_and_print(symbol, tf, as_of, modus)

be = as_of.tz_convert(config.TZ_BERLIN)
st.caption(f"Stand: {be:%d.%m.%Y %H:%M} Berlin  |  {as_of:%H:%M} New York  |  "
           f"Letzter Preis: {tool.fmt_price(a.report.last_price, config.INSTRUMENTS[symbol]['decimals'])}")

st.header("Signale", anchor="signale")
links, rechts = st.columns(2)
karte(links, a.signal_a, modus in ("beide", "original"))
karte(rechts, a.signal_b, modus == "retracement")

import signals  # noqa: E402  (hier, damit die Seite oben schneller erscheint)
st.markdown(f"### ➜ {signals.verdict(a.signal_a, a.signal_b)}")

# --- Charts ---------------------------------------------------------------------
import chart  # noqa: E402

design = "light" if st.sidebar.toggle("Helles Chart-Design", value=False) else "dark"
figs = chart.build_all(a, symbol, design)
st.header("Charts Daily · H4 · M15", anchor="charts")
st.caption("Kerzen: hohl = steigend, gefüllt = fallend · Zonen: Daily = Blau, H4 = Orange, "
           "M15 = Aqua (FVG gepunktet, OB durchgezogen) · ✓ gültiger / ✗ ungültiger "
           "Sweep-Punkt · Legende anklicken zum Ein-/Ausblenden · Mausrad = Zoom")
h1_fig = figs.pop("H1", None)
tabs = st.tabs(list(figs) or ["Charts"])
for tab, (name, fig) in zip(tabs, figs.items()):
    with tab:
        st.plotly_chart(fig, config={"scrollZoom": True, "displaylogo": False},
                        key=f"chart_{name}")

# --- H1-Detailchart: alle Highs/Lows als Linien, FVGs/OBs als Rechtecke ----------
st.header("H1-Detailchart", anchor="h1-detail")
st.caption("Linien = Highs/Lows von Sessions (Asia, London, Pre, NY, PM), Vortag (PDH/PDL) und "
           "Vorwoche (PWH/PWL), jeweils ab der Kerze, an der sie entstanden sind · "
           "Rechtecke = Daily- und H4-FVGs (gepunktet) und Order Blocks (durchgezogen)")
if h1_fig is not None:
    st.plotly_chart(h1_fig, config={"scrollZoom": True, "displaylogo": False}, key="chart_H1")
else:
    st.info("Keine H1-Daten vorhanden (z. B. bei CSV mit Tageskerzen).")

# --- Checkliste + Positionsgröße ------------------------------------------------------
import checklist  # noqa: E402
import risk  # noqa: E402
from structure import BEARISH as _BEAR  # noqa: E402

dec = config.INSTRUMENTS[symbol]["decimals"]
links, rechts = st.columns(2)

with links:
    st.header("Checkliste vor dem Trade", anchor="checkliste")
    st.caption("Grau = vom Tool bestimmt · die übrigen prüfst du selbst im M15 und hakst sie ab")
    liste = checklist.items(a)
    # Häkchen gelten pro Instrument, Tag und Ansicht (am nächsten Tag wieder leer)
    tag = f"{symbol}_{as_of.tz_convert(config.TZ_BERLIN):%Y%m%d}_{modus}"
    erledigt = {}
    for item in liste:
        if item.auto is None:
            erledigt[item.key] = st.checkbox(item.label, key=f"chk_{tag}_{item.key}")
        else:
            st.checkbox(item.label, value=item.auto, disabled=True, key=f"auto_{tag}_{item.key}")
        if item.detail:
            st.caption(f"↳ {item.detail}")
    komplett, text = checklist.verdict(liste, erledigt)
    (st.success if komplett else st.warning)(text)

with rechts:
    st.header("Positionsgröße", anchor="positionsgroesse")
    b_eff = a.effective
    preis = float(a.report.last_price)
    # Vorschläge: Stop hinter dem nächsten gültigen Sweep-Punkt, Ziel = DOL
    bear = b_eff.direction == _BEAR
    import sweeps  # noqa: E402
    kandidaten = [p.price for p in a.points if p.valid and p.relevant
                  and p.status != sweeps.KOERPER_JENSEITS
                  and (p.price > preis if bear else p.price < preis)]
    stop_vorschlag = (min(kandidaten) if bear else max(kandidaten)) if kandidaten else \
        preis * (1.003 if bear else 0.997)
    ziel_vorschlag = b_eff.dol.price if b_eff.dol is not None else 0.0
    schritt = 10 ** -dec

    c1, c2 = st.columns(2)
    konto = c1.number_input("Kontogröße (€)", min_value=0.0,
                            value=float(config.ACCOUNT_SIZE_EUR), step=500.0)
    risiko = c2.number_input("Risiko (%)", min_value=0.05, max_value=5.0,
                             value=float(config.RISK_PCT), step=0.25)
    c3, c4, c5 = st.columns(3)
    einstieg = c3.number_input("Einstieg", value=preis, step=schritt, format=f"%.{dec}f")
    stop = c4.number_input("Stop-Loss", value=float(stop_vorschlag), step=schritt,
                           format=f"%.{dec}f")
    ziel = c5.number_input("Ziel (0 = keins)", value=float(ziel_vorschlag), step=schritt,
                           format=f"%.{dec}f")
    vpp_default = risk.value_per_point(symbol, einstieg)
    einheit = "Punkt" if config.INSTRUMENTS[symbol]["point"] >= 1 else "Pip"
    vpp = st.number_input(f"€ je {einheit} und 1 Lot (bei deinem Broker prüfen!)",
                          min_value=0.0001, value=float(round(vpp_default, 4)), step=0.1,
                          format="%.4f")
    st.caption("Vorschlag: Stop hinter dem nächsten gültigen Sweep-Punkt, Ziel = DOL – "
               "bitte an dein Setup anpassen.")
    try:
        r = risk.position_size(symbol, konto, risiko, einstieg, stop,
                               ziel if ziel > 0 else None, vpp)
        de = tool.fmt_price                       # deutsches Zahlenformat
        zeilen = [
            ("Richtung", r.direction),
            ("**Positionsgröße**", f"**{de(r.lots, 2)} Lot**"),
            ("Risiko", f"{de(r.actual_risk, 2)} € (geplant {de(r.risk_amount, 2)} €)"),
            ("Stop-Abstand", f"{de(r.stop_distance, 1)} {r.unit}"),
        ]
        if r.crv is not None:
            zeilen += [("CRV", f"1 : {de(r.crv, 1)}"),
                       ("möglicher Gewinn", f"{de(r.reward, 2)} €")]
        st.markdown("| | |\n|---|---|\n" + "\n".join(f"| {k} | {v} |" for k, v in zeilen))
        if r.warnung:
            st.warning(r.warnung)
    except ValueError as e:
        st.error(str(e))

# --- Forward-Test ----------------------------------------------------------------------
import journal  # noqa: E402

st.header("Forward-Test", anchor="forward-test")
st.caption(f"Jeder Handelstag wird so protokolliert, wie das Tool um {journal.UHRZEIT_BERLIN} "
           "Berlin entschieden hätte (nur Daten bis dahin), und nach Tagesschluss ausgewertet. "
           "Fehlende Tage werden beim Öffnen automatisch nachgetragen.")
heute = pd.Timestamp.now(tz=config.TZ_BERLIN).strftime("%Y-%m-%d")
merker = f"journal_{symbol}_{heute}"
if not st.session_state.get(merker):
    journal.update({symbol: lade(symbol)})                 # nur 1x pro Tag und Instrument
    st.session_state[merker] = True
if st.button("Alle Instrumente aktualisieren"):
    with st.spinner("Lade Daten und aktualisiere das Protokoll ..."):
        journal.update({s: lade(s) for s in config.INSTRUMENTS})
jdf = journal.load_journal()
st.caption(f"Start: {journal.start_date()} · Regel-Version jetzt: {journal.regel_version()}")
if jdf.empty:
    st.info("Noch keine Einträge – der erste kommt am Start-Tag um 15:30 Berlin.")
else:
    sdf = journal.stats(jdf)
    if sdf.empty:
        st.info(f"{len(jdf)} Einträge, noch keiner ausgewertet (wartet auf Tagesschluss).")
    else:
        st.dataframe(sdf, hide_index=True)
        if (sdf["Tage"] < 30).any():
            st.caption("Unter ~30 Tagen sind die Quoten noch stark vom Zufall abhängig "
                       "(siehe 95%-Bereich).")
    spalten = [c for c in ["Datum", "Symbol", "A_Richtung", "A_Konfidenz", "B_Richtung",
                           "Urteil", "A_Treffer", "B_Treffer", "Regel_Version"] if c in jdf]
    st.dataframe(jdf[spalten].tail(15).iloc[::-1], hide_index=True)

# --- Meine Backtests ---------------------------------------------------------------------
import trade_log  # noqa: E402

st.header("Meine Backtests", anchor="meine-backtests")
st.caption("Dokumentiere hier deine eigenen Backtest-Trades. Das Ergebnis wird in R "
           "gerechnet (1 R = Risiko Einstieg→Stop). Gespeichert in "
           f"`{trade_log.FILE}` (öffnet sich in Excel).")

with st.form("neuer_trade", clear_on_submit=True):
    st.markdown("**Neuen Trade eintragen**")
    f1, f2, f3, f4 = st.columns(4)
    t_datum = f1.date_input("Datum", value=be.date())
    t_zeit = f2.time_input("Uhrzeit (Berlin)", value=pd.Timestamp("15:30").time())
    t_inst = f3.selectbox("Instrument", list(config.INSTRUMENTS),
                          index=list(config.INSTRUMENTS).index(symbol))
    t_richtung = f4.radio("Richtung", ["Long", "Short"], horizontal=True,
                          index=1 if a.effective.direction == BEARISH else 0)
    g1, g2, g3, g4 = st.columns(4)
    t_signal = g1.selectbox("Signal", trade_log.SIGNALE)
    t_sweep = g2.selectbox("Sweep-Punkt", trade_log.SWEEPS)
    t_poi = g3.selectbox("POI", trade_log.POIS)
    t_lqs = g4.selectbox("LQS-Muster", trade_log.LQS)
    h1, h2, h3, h4 = st.columns(4)
    fmt_n = f"%.{dec}f"
    t_ein = h1.number_input("Einstieg", value=0.0, step=10 ** -dec, format=fmt_n)
    t_stop = h2.number_input("Stop", value=0.0, step=10 ** -dec, format=fmt_n)
    t_ziel = h3.number_input("Ziel (optional)", value=0.0, step=10 ** -dec, format=fmt_n)
    t_aus = h4.number_input("Ausstieg", value=0.0, step=10 ** -dec, format=fmt_n)
    t_check = st.checkbox("Checkliste war vollständig erfüllt")
    t_notiz = st.text_area("Notizen", placeholder="Was lief gut / schlecht? Warum Einstieg?")
    t_bild = st.text_input("Screenshot (Link oder Dateipfad, optional)")
    if st.form_submit_button("Trade speichern"):
        try:
            trade_log.add({
                "Datum": t_datum.isoformat(), "Uhrzeit": t_zeit.strftime("%H:%M"),
                "Instrument": t_inst, "Richtung": t_richtung, "Signal": t_signal,
                "Sweep_Punkt": t_sweep, "POI": t_poi, "LQS_Muster": t_lqs,
                "Checkliste_erfuellt": "ja" if t_check else "nein",
                "Einstieg": t_ein, "Stop": t_stop, "Ziel": t_ziel or None,
                "Ausstieg": t_aus, "Notizen": t_notiz, "Screenshot": t_bild})
            st.success("Trade gespeichert.")
        except ValueError as e:
            st.error(f"Nicht gespeichert: {e}")

tdf = trade_log.load()
if tdf.empty:
    st.info("Noch keine eigenen Backtests eingetragen.")
else:
    kz = trade_log.stats(tdf)
    def _q(v, fmt):  # noqa: E306
        return "–" if v is None else fmt(v)
    zeilen = [("Trades", kz["Trades"]),
              ("Gewinner / Verlierer / BE", f"{kz['Gewinner']} / {kz['Verlierer']} / "
                                            f"{kz['Break-even']}"),
              ("Trefferquote", _q(kz["Trefferquote"], lambda v: f"{v:.0%}")),
              ("Ø R je Trade (Erwartungswert)", tool.fmt_price(kz["Ø R"], 2)),
              ("Summe R", tool.fmt_price(kz["Summe R"], 2)),
              ("Ø Gewinn / Ø Verlust (R)",
               f"{_q(kz['Ø Gewinn (R)'], lambda v: tool.fmt_price(v, 2))} / "
               f"{_q(kz['Ø Verlust (R)'], lambda v: tool.fmt_price(v, 2))}"),
              ("Profitfaktor", _q(kz["Profitfaktor"], lambda v: tool.fmt_price(v, 2))),
              ("Max. Drawdown (R)", tool.fmt_price(kz["Max. Drawdown (R)"], 2))]
    k1, k2 = st.columns([1, 2])
    with k1:
        st.markdown("| Kennzahl | Wert |\n|---|---|\n"
                    + "\n".join(f"| {k} | {v} |" for k, v in zeilen))
    with k2:
        st.plotly_chart(chart.equity_curve(tdf, design), key="equity",
                        config={"displaylogo": False})
    gruppen = st.tabs(["nach Signal", "nach POI", "nach Sweep-Punkt", "nach Instrument",
                       "Checkliste erfüllt?"])
    for tab, spalte in zip(gruppen, ["Signal", "POI", "Sweep_Punkt", "Instrument",
                                     "Checkliste_erfuellt"]):
        with tab:
            st.dataframe(trade_log.by_group(tdf, spalte), hide_index=True)

    st.markdown("**Alle Einträge** – direkt in der Tabelle bearbeiten oder Zeilen löschen "
                "(Zeile markieren → Papierkorb), dann speichern. R wird neu berechnet.")
    bearbeitet = st.data_editor(tdf, num_rows="dynamic", hide_index=True, key="trades_edit",
                                disabled=["R", "Ergebnis"])
    if st.button("Änderungen speichern"):
        trade_log.save(trade_log.recompute(bearbeitet))
        st.success("Gespeichert.")
        st.rerun()

st.header("Komplette Analyse", anchor="komplette-analyse")
with st.expander("Textausgabe (Level, Struktur, POIs, Sweep-Punkte, Checkliste)",
                 expanded=False):
    st.code(puffer.getvalue(), language=None)

st.caption("Entscheidungshilfe, kein Signal. Die Entscheidung triffst du.")
