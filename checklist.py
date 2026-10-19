"""
checklist.py – Die Checkliste vor dem Trade als Datenstruktur.

Jeder Punkt ist entweder
  - automatisch (auto=True/False): das Tool weiß es selbst (Bias, Richtung, POI)
  - manuell (auto=None): das prüfst DU im M15 (Sweep, Ablehnung, MSS, FVG-Entry)
Die Web-Oberfläche macht daraus Häkchen-Kästchen.
"""

from __future__ import annotations

from dataclasses import dataclass

import bias
import structure


@dataclass
class Item:
    key: str
    label: str
    auto: bool | None          # True/False = vom Tool bestimmt, None = selbst abhaken
    detail: str = ""


def _fmt(a, x: float) -> str:
    import config
    dec = config.INSTRUMENTS[a.symbol]["decimals"] if hasattr(a, "symbol") else 2
    s = f"{x:,.{dec}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def items(a) -> list[Item]:
    """a = Ergebnis von main.analyze_and_print (mit a.effective, a.poi_view, a.points)."""
    b = a.effective
    klar = b.bias != bias.NEUTRAL
    price = a.report.last_price
    richtung = b.direction if klar else None
    bear = richtung == structure.BEARISH

    handelbar = [p for p in a.poi_view["A"] + a.poi_view["B"] if p.tradable]
    im_poi = next((p for p in handelbar if p.distance(price) == 0), None)
    if im_poi is not None:
        poi_detail = f"Preis ist in {im_poi.timeframe}-{im_poi.kind} (Stufe {im_poi.stufe})"
    elif handelbar:
        n = min(handelbar, key=lambda p: p.distance(price))
        poi_detail = (f"nächster: {n.timeframe}-{n.kind} {_fmt(a, n.bottom)}–{_fmt(a, n.top)} "
                      f"(Stufe {n.stufe})")
    else:
        poi_detail = "kein handelbarer POI in Bias-Richtung"

    gueltig = [p for p in a.points if p.valid and p.relevant][:4]
    sweep_detail = ", ".join(f"{p.name} {_fmt(a, p.price)}" for p in gueltig) or "keine"
    seite = "über ein gültiges Hoch" if bear else "unter ein gültiges Tief"
    unsere = "bearish" if bear else "bullish"
    gegen = "bullish" if bear else "bearish"
    docht = "oberer" if bear else "unterer"

    return [
        Item("bias", "Bias klar?", klar,
             "" if klar else "NEUTRAL – heute kein Trade"),
        Item("htf", f"Trade in HTF-Richtung? (nur {richtung}e Trades)" if klar
             else "Trade in HTF-Richtung?", klar),
        Item("poi", "Preis in einem handelbaren POI (Stufe A oder B)?", im_poi is not None,
             poi_detail),
        Item("sweep", f"Gültiger Sweep: Docht {seite}?", None, f"gültige Punkte: {sweep_detail}"),
        Item("lqs", "Starke Ablehnung?", None,
             f"a) kleiner {unsere}er Körper + langer {docht} Docht  ODER  "
             f"b) {gegen}er Körper, danach mind. gleich großer {unsere}er Körper"),
        Item("mss", f"M15-MSS {'nach unten' if bear else 'nach oben'} per Kerzenkörper?", None),
        Item("fvg", "Entry im M15-FVG aus dieser Bewegung?", None),
        Item("risk", f"Positionsgröße berechnet (max. {_risk_pct()} % Risiko)?", None),
    ]


def _risk_pct() -> str:
    import config
    return f"{config.RISK_PCT:g}"


def verdict(item_list: list[Item], manual_checked: dict[str, bool]) -> tuple[bool, str]:
    """(Setup komplett?, Text). manual_checked = {key: abgehakt} für die manuellen Punkte."""
    if not item_list[0].auto:
        return False, "Kein Bias – heute kein Trade."
    offen = [i.label for i in item_list
             if (i.auto is False) or (i.auto is None and not manual_checked.get(i.key))]
    if not offen:
        return True, "Alle Punkte erfüllt – Setup komplett. Die Entscheidung triffst du."
    return False, f"Noch offen ({len(offen)}): " + " · ".join(offen)
