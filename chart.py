"""
chart.py – Interaktive Plotly-Charts für Daily, H4 und M15.

Was im Chart zu sehen ist:
  - Kerzen: HOHL = steigend, GEFÜLLT = fallend (eindeutig auch ohne Farbsehen)
  - POI-Zonen, Farbe = Timeframe:  Daily = Blau, H4 = Orange, M15 = Aqua
        FVG = gepunktete Kante, Order Block = durchgezogene Kante
        Beschriftung z. B. "D-FVG ▼"  oder  "H4-OB ▼ Stufe B 3/4"
  - Sweep-Punkte (PDH/PDL/PWH/PWL, im M15 auch Sessions):
        durchgezogen + "✓" = gültig (passt zum Bias), gepunktet + "✗" = ungültig
  - Sessions (M15): graue Hintergrund-Streifen mit Namen
  - Premium/Discount: dunkleres Band = Premium, helleres = Discount, EQ-Linie = 50 %
  - DOL: gestrichelte Linie "DOL ▶"
Alle Elemente haben Tooltips und lassen sich über die Legende ein-/ausblenden.

Die Farben wurden mit dem Farb-Validator (Farbsehschwäche-Simulation) geprüft:
nur drei Farbtöne, alle anderen Unterschiede über Linienart und Beschriftung.
"""

from __future__ import annotations

import os

import pandas as pd
import plotly.graph_objects as go

import bias
import config
import sessions
import sweeps
from structure import BULLISH

THEMES = {
    "dark": {"surface": "#1a1a19", "primary": "#f0efec", "secondary": "#c3c2b7",
             "muted": "#898781", "grid": "#2c2c2a", "axis": "#383835",
             "tint": "255,255,255",
             "tf": {"Daily": "#3987e5", "H4": "#d95926", "M15": "#199e70"}},
    "light": {"surface": "#fcfcfb", "primary": "#0b0b0b", "secondary": "#52514e",
              "muted": "#898781", "grid": "#e1e0d9", "axis": "#c3c2b7",
              "tint": "11,11,11",
              "tf": {"Daily": "#2a78d6", "H4": "#eb6834", "M15": "#1baf7a"}},
}
KURZ = {"Daily": "D", "H4": "H4", "M15": "M15"}
FENSTER = {"Daily": 100, "H4": 150, "H1": 120, "M15": 200}   # so viele Kerzen anzeigen


def _rgba(hex_color: str, alpha: float) -> str:
    h = hex_color.lstrip("#")
    return f"rgba({int(h[0:2], 16)},{int(h[2:4], 16)},{int(h[4:6], 16)},{alpha})"


def _bx(ts) -> pd.Timestamp:
    """Zeitpunkt -> x-Achse (Berliner Uhrzeit ohne Zeitzone; Tagesdaten bleiben Datum)."""
    ts = pd.Timestamp(ts)
    return ts.tz_convert(config.TZ_BERLIN).tz_localize(None) if ts.tzinfo else ts


class _Ctx:
    """Alles, was die Charts aus der Analyse brauchen."""

    def __init__(self, a, symbol: str, theme: str):
        self.a, self.symbol = a, symbol
        self.t = THEMES[theme]
        self.dec = config.INSTRUMENTS[symbol]["decimals"]
        self.d_all = a.tf["D"]

    def fmt(self, x: float) -> str:
        s = f"{x:,.{self.dec}f}"
        return s.replace(",", "X").replace(".", ",").replace("X", ".")

    def time_x(self, ts, tfname: str) -> pd.Timestamp:
        """
        Zeitpunkt auf die x-Achse des jeweiligen Charts umrechnen:
          - Tagesdatum (ohne Zeitzone) im H4/M15-Chart -> Beginn dieses Handelstages
          - Uhrzeit (mit Zeitzone) im Daily-Chart     -> nur das Datum
        """
        ts = pd.Timestamp(ts)
        if ts.tzinfo is None and tfname != "Daily" and ts in self.d_all.index:
            return _bx(self.d_all.loc[ts, "start"])
        if ts.tzinfo is not None and tfname == "Daily":
            return _bx(ts).normalize()
        return _bx(ts)

    def poi_x(self, p, tfname: str) -> pd.Timestamp:
        """Startzeit einer Zone auf der x-Achse des jeweiligen Charts."""
        return self.time_x(p.time, tfname)


# ---------------------------------------------------------------------------
# Bausteine
# ---------------------------------------------------------------------------
def _candles(fig, df, x, c):
    t = c.t
    fig.add_trace(go.Candlestick(
        x=x, open=df["Open"], high=df["High"], low=df["Low"], close=df["Close"],
        name="Kerzen", showlegend=False,
        increasing=dict(line=dict(color=t["secondary"], width=1), fillcolor=t["surface"]),
        decreasing=dict(line=dict(color=t["secondary"], width=1), fillcolor=t["secondary"]),
        hoverlabel=dict(bgcolor=t["surface"], font_color=t["primary"])))


def _hline(fig, x0, x1, y, name, group, color, dash, width, hover, show_legend):
    fig.add_trace(go.Scatter(
        x=[x0, x1], y=[y, y], mode="lines", name=group, legendgroup=group,
        showlegend=show_legend, line=dict(color=color, dash=dash, width=width),
        hovertext=hover, hoverinfo="text"))


def _zones(fig, pois, tfname, x_start, x_end, c, labels, show_all=False):
    """
    POI-Zonen (FVG und OB) als Rechtecke (mit Tooltip, ein-/ausblendbar).
    H4-POIs, die NICHT zählen, sind standardmäßig ausgeblendet (Legende: einblenden).
    show_all=True (H1-Detailchart): auch diese sichtbar und beschriftet.
    """
    seen = set()
    for p in pois:
        col = c.t["tf"][p.timeframe]
        x0 = max(c.poi_x(p, tfname), x_start)
        zaehlt = p.stufe is not None or p.timeframe == "M15"
        group = f"{p.timeframe}-POIs" + ("" if zaehlt else " (zählen nicht)")
        zaehlt = zaehlt or show_all          # ab hier: sichtbar + beschriftet?
        pfeil = "▲" if p.direction == BULLISH else "▼"
        stufe = ("Stufe A" if p.stufe == "A" else
                 f"Stufe B {p.n_checks}/4" if p.stufe == "B" else
                 f"zählt nicht {p.n_checks}/4" if p.checks else "")
        txt = f"{KURZ[p.timeframe]}-{p.kind} {pfeil} {stufe}".strip()
        hover = (f"<b>{p.timeframe}-{p.kind} {pfeil}</b><br>{c.fmt(p.bottom)} – {c.fmt(p.top)}"
                 f"<br>Mitigation: {p.mitigation}<br>{stufe}"
                 + ("<br>" + "<br>".join(f"{'✓' if v else '✗'} {k}" for k, v in p.checks.items())
                    if p.checks else "")
                 + ("<br><b>handelbar</b>" if p.tradable else "<br>nicht handelbar"))
        fig.add_trace(go.Scatter(
            x=[x0, x_end, x_end, x0, x0], y=[p.bottom, p.bottom, p.top, p.top, p.bottom],
            mode="lines", fill="toself", name=group, legendgroup=group,
            showlegend=group not in seen, visible=True if zaehlt else "legendonly",
            fillcolor=_rgba(col, 0.22 if p.tradable else 0.10),
            line=dict(color=col, width=2 if p.kind == "OB" else 1,
                      dash="solid" if p.kind == "OB" else "dot"),
            hovertext=hover, hoverinfo="text", hoveron="fills+points"))
        seen.add(group)
        if zaehlt:
            labels.append(dict(x=x0, y=p.top, text=txt))


def _place_labels(fig, labels, y_span, c):
    """Zonen-Beschriftungen setzen; liegen zwei zu nah beieinander, werden sie zusammengefasst."""
    placed: list[dict] = []
    for lab in sorted(labels, key=lambda l: l["y"]):
        near = next((p for p in placed if abs(p["y"] - lab["y"]) < y_span * 0.035), None)
        if near is not None:
            near["text"] += " · " + lab["text"]
        else:
            placed.append(dict(lab))
    for lab in placed:
        fig.add_annotation(x=lab["x"], y=lab["y"], text=lab["text"], showarrow=False,
                           xanchor="left", yanchor="bottom", xshift=2,
                           font=dict(size=10, color=c.t["secondary"]),
                           bgcolor=_rgba(c.t["surface"], 0.7))


def _levels(fig, points, x_start, x_end, c, y_lo, y_hi, mode, right, origins=None):
    """
    mode: "pdpw"           -> nur PDH/PDL/PWH/PWL (Daily, H4)
          "valid_sessions" -> plus gültige Session-Levels (M15)
          "all"            -> alle Highs/Lows inkl. ungültiger (H1-Detailchart)
    origins: {Name: Zeitpunkt} -> Linie beginnt dort, wo das Hoch/Tief entstand
    """
    seen = set()
    for p in points:
        is_session = p.name not in ("PDH", "PDL", "PWH", "PWL")
        if is_session and (mode == "pdpw" or (mode == "valid_sessions" and not p.valid)):
            continue
        if not (y_lo <= p.price <= y_hi):
            continue
        x0 = x_start
        if origins and origins.get(p.name) is not None:
            x0 = min(max(_bx(origins[p.name]), x_start), x_end)
        group = "Sweep-Punkte gültig" if p.valid else "Sweep-Punkte ungültig"
        gebrochen = p.status == sweeps.KOERPER_JENSEITS
        color = c.t["primary"] if p.valid and not gebrochen else c.t["muted"]
        dash = "solid" if p.valid else "dot"
        icon = "✓" if p.valid else "✗"
        extra = " (gebr.)" if gebrochen else ("" if p.relevant else " (irrel.)")
        hover = f"{icon} {p.name} {c.fmt(p.price)}<br>Status: {p.status}"
        _hline(fig, x0, x_end, p.price, p.name, group, color, dash, 1.5 if p.valid else 1,
               hover, group not in seen)
        seen.add(group)
        right.append((p.price, f"{icon} {p.name} {c.fmt(p.price)}{extra}", color))


def _ohne_preis(text: str) -> str:
    """'✓ London High 30.201,00 (gebr.)' -> '✓ London High'  ·  'DOL ▶ 29.648,00' -> 'DOL ▶'"""
    teile = text.split(" (")[0].split(" ")
    return " ".join(t for t in teile if not any(ch.isdigit() for ch in t))


def _right_labels(fig, right, x_end, y_span, c):
    """
    Beschriftungen rechts IM Chart (im freien Bereich nach der letzten Kerze),
    damit die Preisachse ganz am Fensterrand sitzen kann.
    Zu nahe Labels werden zusammengefasst.
    """
    right.sort(key=lambda r: r[0])
    merged = []                          # (Preis, [Texte], Farbe)
    for price, text, color in right:
        if merged and abs(price - merged[-1][0]) < y_span * 0.025:
            merged[-1][1].append(text)
        else:
            merged.append((price, [text], color))
    for price, texts, color in merged:
        # weitere Levels auf fast gleichem Preis nur mit Namen (Preis steht im Tooltip)
        rest = [_ohne_preis(x) for x in texts[1:]]
        text = texts[0] + "".join(f" · {r}" for r in rest[:1]) + \
            (f" (+{len(rest) - 1})" if len(rest) > 1 else "")
        fig.add_annotation(x=x_end, y=price, text=text, showarrow=False, xanchor="right",
                           yanchor="bottom", xshift=-4, font=dict(size=11, color=c.t["secondary"]),
                           bgcolor=_rgba(c.t["surface"], 0.75))


def _future(x_last: pd.Timestamp, step: pd.Timedelta, n: int, daily: bool) -> pd.Timestamp:
    """Zeitpunkt n Kerzen nach der letzten – Wochenenden übersprungen (wie die x-Achse)."""
    if daily:
        return pd.bdate_range(x_last + pd.Timedelta(days=1), periods=n)[-1]
    t, count = x_last, 0
    while count < n:
        t += step
        if t.weekday() < 5:
            count += 1
    return t


def _premium_discount(fig, leg, x0, x_end, c):
    t = c.t
    eq = leg.equilibrium
    for lo, hi, name, alpha in ((eq, leg.high, "Premium", 0.07), (leg.low, eq, "Discount", 0.03)):
        fig.add_shape(type="rect", x0=x0, x1=x_end, y0=lo, y1=hi, layer="below",
                      line_width=0, fillcolor=f"rgba({t['tint']},{alpha})")
        fig.add_annotation(x=x0, y=hi if name == "Premium" else lo, text=name,
                           showarrow=False, xanchor="left",
                           yanchor="top" if name == "Premium" else "bottom",
                           font=dict(size=11, color=t["muted"]))
    _hline(fig, x0, x_end, eq, "EQ", "Premium/Discount", t["muted"], "dash", 1,
           f"Equilibrium (50 %) {c.fmt(eq)}<br>Range {c.fmt(leg.low)} – {c.fmt(leg.high)}",
           True)


def _sessions(fig, x_vals, c, schmal: bool = False):
    """
    Graue Streifen für jede Session im sichtbaren Bereich (M15 und H1).
    schmal=True (H1): kurze Namen, Pre-Market und NY PM ohne Beschriftung.
    """
    t = c.t
    first, last = x_vals.min(), x_vals.max()
    days = pd.date_range(first.normalize() - pd.Timedelta(days=1), last.normalize(), freq="D")
    for d in days:
        for name, cfg in config.SESSIONS.items():
            s, e = sessions.window(name, d.date())
            s, e = _bx(s), _bx(e)
            if e < first or s > last:
                continue
            alpha = 0.06 if cfg["relevant"] else 0.025
            if schmal:
                kurz = {"Asia": "As", "London": "Ldn", "NY AM": "NY"}.get(name, "")
            else:
                kurz = {"NY Pre-Market": "Pre", "NY AM": "NY", "NY PM": "(PM)"}.get(name, name)
            fig.add_vrect(x0=max(s, first), x1=min(e, last), layer="below", line_width=0,
                          fillcolor=f"rgba({t['tint']},{alpha})",
                          annotation_text=kurz,
                          annotation_position="top left",
                          annotation_font=dict(size=10, color=t["muted"]))


# ---------------------------------------------------------------------------
# Ein Chart
# ---------------------------------------------------------------------------
def build_chart(a, symbol: str, tfname: str, theme: str = "dark") -> go.Figure | None:
    """
    a      : Ergebnis von main.analyze_and_print (mit a.tf, a.poi_view, a.points ...)
    tfname : "Daily", "H4", "M15" oder "H1" (Detailchart mit allen Highs/Lows)
    """
    c = _Ctx(a, symbol, theme)
    t = c.t
    key = {"Daily": "D", "H4": "H4", "H1": "H1", "M15": "M15"}[tfname]
    if key not in a.tf or a.tf[key].empty:
        if tfname == "M15" and "H1" in a.tf:
            key = "H1"                                    # Ersatz, wenn keine M15-Daten
        else:
            return None
    df = a.tf[key].iloc[-FENSTER[tfname]:]
    x = pd.Index([_bx(i) for i in df.index])
    x_start = x[0]
    step = (x[-1] - x[-2]) if len(x) > 1 else pd.Timedelta(hours=1)
    # Freier Bereich rechts der letzten Kerze für die Beschriftungen;
    # die Preisachse sitzt dadurch ganz am rechten Fensterrand.
    pad = 0.30 if tfname == "H1" else 0.22          # H1 hat die meisten Beschriftungen
    x_end = _future(x[-1], step, max(8, int(len(x) * pad)), tfname == "Daily")
    intraday = tfname in ("H1", "M15")

    fig = go.Figure()
    _candles(fig, df, x, c)
    y_lo, y_hi = float(df["Low"].min()), float(df["High"].max())
    span = y_hi - y_lo
    y_lo_v, y_hi_v = y_lo - span * 0.08, y_hi + span * 0.08

    b = a.effective
    if intraday:
        _sessions(fig, x, c, schmal=tfname == "H1")
    # Premium/Discount (Daily + H4): Band ab dem Protected Low/High
    if tfname in ("Daily", "H4") and b.leg is not None:
        px0 = c.time_x(b.leg.protected_time, tfname)
        _premium_discount(fig, b.leg, max(px0, x_start), x_end, c)

    # POI-Zonen: Daily-Chart nur Daily-POIs, H4/H1 zusätzlich H4, M15 alle + M15-Hinweise
    view = a.poi_view
    pois_here = list(view["A"])
    if tfname in ("H4", "H1", "M15"):
        pois_here += list(view["B"])
    if tfname == "M15":
        pois_here += [m for m, _ in view["m15"]]
    pois_here = [p for p in pois_here if p.bottom <= y_hi_v and p.top >= y_lo_v]
    labels: list[dict] = []
    _zones(fig, pois_here, tfname, x_start, x_end, c, labels, show_all=tfname == "H1")
    _place_labels(fig, labels, y_hi_v - y_lo_v, c)

    # Highs/Lows (Sweep-Punkte): im H1/M15 beginnt jede Linie an ihrer Entstehung
    right: list[tuple] = []
    mode = {"H1": "all", "M15": "valid_sessions"}.get(tfname, "pdpw")
    _levels(fig, a.points, x_start, x_end, c, y_lo_v, y_hi_v, mode, right,
            _origins(a) if intraday else None)

    # DOL
    if b.dol is not None and b.bias != bias.NEUTRAL:
        _hline(fig, x_start, x_end, b.dol.price, "DOL", "DOL (Ziel)", t["primary"], "dash", 2,
               f"Draw on Liquidity: {b.dol.name} {c.fmt(b.dol.price)}", True)
        right.append((b.dol.price, f"DOL ▶ {c.fmt(b.dol.price)}", t["primary"]))
        y_lo_v, y_hi_v = min(y_lo_v, b.dol.price), max(y_hi_v, b.dol.price)

    # aktueller Preis
    price = a.report.last_price
    _hline(fig, x_start, x_end, price, "Preis", "Preis", t["muted"], "solid", 1,
           f"Letzter Preis {c.fmt(price)}", False)
    right.append((price, f"● Preis {c.fmt(price)}", t["muted"]))
    _right_labels(fig, right, x_end, y_hi_v - y_lo_v, c)

    # Layout
    titel_bias = (bias.NEUTRAL if b.bias == bias.NEUTRAL
                  else b.bias.upper() + {"H4": " (H4-geführt)",
                                         "Retracement": " (Signal B)"}.get(b.mode, ""))
    stand = _bx(a.as_of)
    breaks = [dict(bounds=["sat", "mon"])]
    ersatz = " (H1-Ersatz)" if key == "H1" and tfname == "M15" else ""
    detail = " Detail (alle Highs/Lows)" if tfname == "H1" else ""
    fig.update_layout(
        title=dict(text=f"{symbol} – {tfname}{detail}{ersatz}"
                        f"   |   Bias: {titel_bias}   |   Stand {stand:%d.%m.%Y %H:%M} Berlin",
                   font=dict(size=15, color=t["primary"]), x=0.01),
        paper_bgcolor=t["surface"], plot_bgcolor=t["surface"],
        font=dict(family='system-ui, -apple-system, "Segoe UI", sans-serif',
                  color=t["secondary"], size=12),
        separators=",.", height=680, margin=dict(l=10, r=10, t=50, b=90),
        hovermode="closest", dragmode="pan",
        legend=dict(orientation="h", y=-0.08, x=0, yanchor="top",
                    font=dict(color=t["secondary"]), bgcolor="rgba(0,0,0,0)"),
        xaxis=dict(rangeslider=dict(visible=False), rangebreaks=breaks, gridcolor=t["grid"],
                   linecolor=t["axis"], tickfont=dict(color=t["muted"]),
                   tickformat="%d.%m. %H:%M" if intraday else "%d.%m.",
                   range=[x_start, x_end]),
        yaxis=dict(side="right", gridcolor=t["grid"], linecolor=t["axis"],
                   tickfont=dict(color=t["muted"]), range=[y_lo_v, y_hi_v],
                   tickformat=f",.{c.dec}f"),
    )
    return fig


def _origins(a) -> dict:
    """Wo ist jedes High/Low entstanden? {Name: Zeitpunkt} – für Linien ab Entstehung."""
    out = {n: lv.formed_at for n, lv in a.report.levels.items()}
    for r in getattr(a, "ranges", []) or []:
        out[f"{r.name} High"] = r.high_time
        out[f"{r.name} Low"] = r.low_time
    return out


def build_all(a, symbol: str, theme: str = "dark") -> dict[str, go.Figure]:
    """Daily, H4, M15 (Tabs) und H1 (Detailchart darunter)."""
    out = {}
    for tfname in ("Daily", "H4", "M15", "H1"):
        fig = build_chart(a, symbol, tfname, theme)
        if fig is not None:
            out[tfname] = fig
    return out


def equity_curve(trades: pd.DataFrame, theme: str = "dark") -> go.Figure:
    """Kumulierte R-Kurve deiner Backtests (eine Linie, Tooltip je Trade)."""
    t = THEMES[theme]
    d = trades.copy()
    d["R"] = pd.to_numeric(d["R"], errors="coerce")
    d = d.dropna(subset=["R"]).sort_values(["Datum", "Uhrzeit"]).reset_index(drop=True)
    d["Kumuliert"] = d["R"].cumsum()
    nr = list(range(1, len(d) + 1))
    hover = [f"Trade {i}: {r.Datum} {r.Instrument} {r.Richtung}<br>"
             f"Ergebnis {r.R:+.2f} R · Summe {r.Kumuliert:+.2f} R".replace(".", ",")
             for i, r in zip(nr, d.itertuples())]
    fig = go.Figure(go.Scatter(
        x=nr, y=d["Kumuliert"], mode="lines+markers", name="Summe R",
        line=dict(color=t["tf"]["Daily"], width=2), marker=dict(size=8),
        hovertext=hover, hoverinfo="text", showlegend=False))
    fig.add_hline(y=0, line=dict(color=t["axis"], width=1))
    fig.update_layout(
        title=dict(text="Summe R über alle Trades", font=dict(size=14, color=t["primary"]),
                   x=0.01),
        paper_bgcolor=t["surface"], plot_bgcolor=t["surface"], height=300,
        margin=dict(l=10, r=10, t=40, b=30), separators=",.",
        font=dict(family='system-ui, -apple-system, "Segoe UI", sans-serif',
                  color=t["secondary"], size=12),
        xaxis=dict(title="Trade Nr.", gridcolor=t["grid"], tickfont=dict(color=t["muted"]),
                   dtick=1 if len(d) <= 20 else None),
        yaxis=dict(title="R", side="right", gridcolor=t["grid"],
                   tickfont=dict(color=t["muted"]), zeroline=False))
    return fig


def write_html(figs: dict[str, go.Figure], symbol: str, out_dir: str = "charts") -> list[str]:
    """Speichert jeden Chart als eigene HTML-Datei (zum Öffnen im Browser)."""
    os.makedirs(out_dir, exist_ok=True)
    paths = []
    for tfname, fig in figs.items():
        path = os.path.join(out_dir, f"{symbol}_{tfname}.html")
        fig.write_html(path, include_plotlyjs="cdn", full_html=True,
                       config={"scrollZoom": True, "displaylogo": False})
        paths.append(path)
    return paths
