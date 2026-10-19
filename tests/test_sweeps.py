"""
Tests für die Sweep-Beobachtungsliste.

Das Programm bewertet keine Sweeps – geprüft wird nur:
  - harte Regel 2 (welche Seite ist gültig?)
  - der reine Fakten-Status (offen / Docht / Körper jenseits)
"""

import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config  # noqa: E402
import data  # noqa: E402
import levels  # noqa: E402
import sweeps as sw  # noqa: E402
from structure import BEARISH, BULLISH, UNKLAR  # noqa: E402
from tests.beispieldaten import make_sample_h1  # noqa: E402


def ny(s):
    return pd.Timestamp(s, tz=config.TZ_NY)


def kerzen(*ohlc):
    idx = pd.date_range("2026-10-14 09:30", periods=len(ohlc), freq="15min",
                        tz=config.TZ_NY)
    return pd.DataFrame(list(ohlc), columns=["Open", "High", "Low", "Close"], index=idx)


# --- Harte Regel 2 ----------------------------------------------------------
def test_bearish_nur_hochs_gueltig():
    assert sw.is_valid_for("high", BEARISH) is True
    assert sw.is_valid_for("low", BEARISH) is False


def test_bullish_nur_tiefs_gueltig():
    assert sw.is_valid_for("low", BULLISH) is True
    assert sw.is_valid_for("high", BULLISH) is False


def test_unklar_nichts_gueltig():
    assert not sw.is_valid_for("high", UNKLAR)
    assert not sw.is_valid_for("low", UNKLAR)


# --- Status (nur Fakten) ----------------------------------------------------
def test_status_offen():
    assert sw.level_status(kerzen((98, 99, 97, 98.5)), 100, "high") == sw.OFFEN


def test_status_nur_docht():
    assert sw.level_status(kerzen((99, 101, 98, 99.5)), 100, "high") == sw.ANGELAUFEN


def test_status_koerper_jenseits():
    assert sw.level_status(kerzen((99, 101, 98, 100.5)), 100, "high") == sw.KOERPER_JENSEITS


def test_status_tief_gespiegelt():
    assert sw.level_status(kerzen((101, 102, 99, 100.5)), 100, "low") == sw.ANGELAUFEN
    assert sw.level_status(kerzen((101, 102, 99, 99.5)), 100, "low") == sw.KOERPER_JENSEITS


# --- Beobachtungsliste mit Beispieldaten ------------------------------------
def test_watchlist_bearish():
    tf = data.build_timeframes(make_sample_h1(), config.INSTRUMENTS["US100"])
    as_of = ny("2026-10-14 09:00")
    rep = levels.compute_levels(tf, as_of)
    pts = {p.name: p for p in sw.watchlist(rep, BEARISH, tf["H1"], as_of)}
    assert pts["PDH"].valid and pts["PWH"].valid
    assert not pts["PDL"].valid and not pts["PWL"].valid
    # Mi 08:00: High 125 über PDH 120, Close 100 -> nur Docht
    assert pts["PDH"].status == sw.ANGELAUFEN
    assert pts["PDL"].status == sw.OFFEN


def test_watchlist_gueltige_zuerst():
    tf = data.build_timeframes(make_sample_h1(), config.INSTRUMENTS["US100"])
    as_of = ny("2026-10-14 09:00")
    rep = levels.compute_levels(tf, as_of)
    pts = sw.watchlist(rep, BULLISH, tf["H1"], as_of)
    assert [p.valid for p in pts] == [True, True, False, False]
    assert {p.name for p in pts[:2]} == {"PDL", "PWL"}


def test_checkliste_passt_zur_richtung():
    bear = " ".join(sw.m15_checklist(BEARISH))
    assert "Hoch" in bear and "oberer Docht" in bear
    bull = " ".join(sw.m15_checklist(BULLISH))
    assert "Tief" in bull and "unterer Docht" in bull
    assert "keinen Sweep" in sw.m15_checklist(UNKLAR)[0]
