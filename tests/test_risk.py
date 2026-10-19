"""
Tests für risk.py (Positionsgröße) und checklist.py.
"""

import contextlib
import io
import os
import sys

import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import checklist  # noqa: E402
import config  # noqa: E402
import data  # noqa: E402
import main as tool  # noqa: E402
import risk  # noqa: E402
from tests.beispieldaten import make_sample_h1  # noqa: E402


# --- Positionsgröße ---------------------------------------------------------------
def test_us100_ein_prozent():
    # 10.000 € Konto, 1 % = 100 €. Stop 50 Punkte, 1 € je Punkt -> 2 Lot
    r = risk.position_size("US100", 10_000, 1.0, 21_000, 21_050, vpp=1.0)
    assert r.direction == "Short"
    assert r.stop_distance == 50 and r.lots == 2.0
    assert r.actual_risk == pytest.approx(100)


def test_abrunden_nie_mehr_risiko():
    # 100 € / (30 Punkte × 1 €) = 3,333 -> 3,33 Lot (abgerundet, nie mehr als 1 %)
    r = risk.position_size("US100", 10_000, 1.0, 21_000, 20_970, vpp=1.0)
    assert r.lots == pytest.approx(3.33)
    assert r.actual_risk <= r.risk_amount


def test_forex_pipwert_und_crv():
    # EUR/USD 1,10000: 10 USD je Pip = 9,0909 € je Pip und Lot
    assert risk.value_per_point("EURUSD", 1.1) == pytest.approx(9.0909, rel=1e-4)
    # Stop 20 Pips: 100 € / (20 × 9,0909) = 0,55 Lot; Ziel 60 Pips -> CRV 3
    r = risk.position_size("EURUSD", 10_000, 1.0, 1.10000, 1.09800, target=1.10600)
    assert r.direction == "Long" and r.unit == "Pips"
    assert r.stop_distance == pytest.approx(20)
    assert r.lots == pytest.approx(0.55)
    assert r.crv == pytest.approx(3.0)


def test_ziel_auf_falscher_seite():
    r = risk.position_size("US100", 10_000, 1.0, 21_000, 21_050, target=21_100, vpp=1.0)
    assert r.crv is None and "falschen Seite" in r.warnung


def test_stop_zu_weit():
    r = risk.position_size("US100", 1_000, 0.5, 21_000, 22_000, vpp=1.0)
    assert r.lots == 0 and "zu weit" in r.warnung


def test_ungueltige_eingaben():
    with pytest.raises(ValueError):
        risk.position_size("US100", 10_000, 1.0, 21_000, 21_000)


# --- Checkliste --------------------------------------------------------------------
def _analyse():
    tf = data.build_timeframes(make_sample_h1(), config.INSTRUMENTS["US100"])
    as_of = pd.Timestamp("2026-10-14 09:00", tz=config.TZ_NY)
    with contextlib.redirect_stdout(io.StringIO()):
        return tool.analyze_and_print("US100", data.cut_at(tf, as_of), as_of, "beide")


def test_checkliste_aufbau():
    liste = checklist.items(_analyse())
    keys = [i.key for i in liste]
    assert keys == ["bias", "htf", "poi", "sweep", "lqs", "mss", "fvg", "risk"]
    auto = {i.key for i in liste if i.auto is not None}
    assert auto == {"bias", "htf", "poi"}          # der Rest wird selbst abgehakt


def test_urteil_checkliste():
    I = checklist.Item
    liste = [I("bias", "Bias", True), I("htf", "HTF", True), I("poi", "POI", True),
             I("sweep", "Sweep", None), I("mss", "MSS", None)]
    ok, text = checklist.verdict(liste, {"sweep": True, "mss": True})
    assert ok and "komplett" in text
    ok, text = checklist.verdict(liste, {"sweep": True})
    assert not ok and "MSS" in text
    ok, text = checklist.verdict([I("bias", "Bias", False)] + liste[1:], {})
    assert not ok and "kein Trade" in text
