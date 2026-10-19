"""
risk.py – Positionsgrößen-Rechner (Standard: 1 % Risiko pro Trade).

Formel:
    Risiko in €        = Kontogröße × Risiko-%
    Stop-Abstand       = |Einstieg − Stop|            (in Punkten bzw. Pips)
    Verlust je 1 Lot   = Stop-Abstand × Wert je Punkt/Pip (in €)
    Positionsgröße     = Risiko in € ÷ Verlust je 1 Lot   (abgerundet auf Lot-Schritte)

Wert je Punkt/Pip:
    US100 : hängt vom Broker ab (CFD oft 1 € je Punkt und Lot) -> config.py
    Forex : 1 Standard-Lot = 100.000 Einheiten -> 10 Einheiten der Kursw. je Pip;
            in Euro umgerechnet: 10 ÷ Kurs (EUR/USD: 10 USD, EUR/GBP: 10 GBP je Pip)
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import config


@dataclass
class PositionResult:
    lots: float                 # Positionsgröße (abgerundet)
    risk_amount: float          # geplantes Risiko in €
    actual_risk: float          # tatsächliches Risiko mit abgerundeter Größe
    stop_distance: float        # Stop-Abstand in Punkten/Pips
    unit: str                   # "Punkte" oder "Pips"
    value_per_point: float      # € je Punkt/Pip und Lot
    direction: str              # "Long" oder "Short"
    crv: float | None = None    # Chance-Risiko-Verhältnis (falls Ziel angegeben)
    reward: float | None = None # möglicher Gewinn in € (falls Ziel angegeben)
    warnung: str | None = None


def value_per_point(symbol: str, price: float) -> float:
    """€ je Punkt (US100) bzw. Pip (Forex) für 1 Lot."""
    inst = config.INSTRUMENTS[symbol]
    if "value_per_point_eur" in inst:
        return float(inst["value_per_point_eur"])
    # Forex: 10 Einheiten der Kurswährung je Pip und Standard-Lot -> in EUR
    return 10.0 / price


def position_size(symbol: str, account: float, risk_pct: float, entry: float, stop: float,
                  target: float | None = None, vpp: float | None = None) -> PositionResult:
    """
    symbol   : Instrument aus config.INSTRUMENTS
    account  : Kontogröße in €
    risk_pct : Risiko in Prozent (z. B. 1.0)
    vpp      : € je Punkt/Pip und Lot (None = aus config bzw. Kurs berechnen)
    """
    if account <= 0 or risk_pct <= 0:
        raise ValueError("Kontogröße und Risiko müssen größer als 0 sein.")
    if entry == stop:
        raise ValueError("Einstieg und Stop dürfen nicht gleich sein.")
    inst = config.INSTRUMENTS[symbol]
    point = inst["point"]
    unit = "Punkte" if point >= 1 else "Pips"
    vpp = value_per_point(symbol, entry) if vpp is None else vpp

    direction = "Long" if entry > stop else "Short"
    risk_amount = account * risk_pct / 100
    stop_distance = abs(entry - stop) / point
    loss_per_lot = stop_distance * vpp
    step = inst["lot_step"]
    lots = math.floor(risk_amount / loss_per_lot / step + 1e-9) * step
    lots = round(lots, 6)

    res = PositionResult(lots, risk_amount, lots * loss_per_lot, stop_distance, unit,
                         vpp, direction)
    if lots == 0:
        res.warnung = (f"Stop zu weit für {risk_pct:g} % Risiko: schon {step:g} Lot "
                       f"würde {step * loss_per_lot:.2f} € riskieren.")
    if target is not None:
        richtig = target > entry if direction == "Long" else target < entry
        if not richtig:
            res.warnung = "Ziel liegt auf der falschen Seite des Einstiegs."
        else:
            reward_dist = abs(target - entry) / point
            res.crv = reward_dist / stop_distance
            res.reward = lots * reward_dist * vpp
    return res
