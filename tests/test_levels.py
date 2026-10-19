"""
Tests für Schritt 1: Daten zusammensetzen und PDH/PDL/PWH/PWL.

Starten mit:   python -m pytest -v
"""

import os
import sys

import pandas as pd
import pytest

# Damit die Tests config.py, data.py usw. im Hauptordner finden
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config  # noqa: E402
import data  # noqa: E402
import levels  # noqa: E402
from tests.beispieldaten import make_sample_h1  # noqa: E402

TZ = config.TZ_NY
US100 = config.INSTRUMENTS["US100"]


def ny(s):
    return pd.Timestamp(s, tz=TZ)


@pytest.fixture
def tf():
    return data.build_timeframes(make_sample_h1(), US100)


# --- Kerzen-Zusammenbau -----------------------------------------------------
def test_tageskerze_beginnt_um_18_uhr_am_vortag(tf):
    tue = tf["D"].loc["2026-10-13"]
    assert tue["start"] == ny("2026-10-12 18:00")
    assert tue["end"] == ny("2026-10-13 17:00")
    # Montagabend 22:00 (High 120) muss in der DIENSTAG-Kerze stecken
    assert tue["High"] == 120
    assert tf["D"].loc["2026-10-12", "High"] == 101


def test_keine_wochenend_tageskerzen(tf):
    assert set(tf["D"].index.weekday) <= {0, 1, 2, 3, 4}


def test_h4_bloecke_sind_an_18_uhr_ausgerichtet(tf):
    assert set(tf["H4"].index.hour) <= {18, 22, 2, 6, 10, 14}
    # Erste H4-Kerze der Woche beginnt exakt So 18:00 NY und enthält 18–21 Uhr
    assert tf["H4"].index[0] == ny("2026-10-04 18:00")
    assert tf["H4"].iloc[0]["High"] == 130          # So 19:00 High 130
    # Der PDL (Di 10:00, Low 80) steckt in der 10:00-H4-Kerze
    assert tf["H4"].loc[ny("2026-10-13 10:00"), "Low"] == 80
    # Letzte H4-Kerze vor der Pause: 14:00 (enthält 14–16 Uhr)
    assert tf["H4"].index[-1] == ny("2026-10-16 14:00")


def test_wochenkerze_enthaelt_sonntagabend(tf):
    week = tf["W"].loc["2026-10-05"]
    assert week["High"] == 130      # So 04.10. 19:00
    assert week["Low"] == 70        # Fr 09.10. 16:00
    assert week["end"] == ny("2026-10-09 17:00")


# --- PDH / PDL / PWH / PWL --------------------------------------------------
def test_levels_am_mittwochmorgen(tf):
    rep = levels.compute_levels(tf, ny("2026-10-14 09:00"))
    L = rep.levels
    assert rep.prev_day.name == pd.Timestamp("2026-10-13")
    assert (L["PDH"].price, L["PDL"].price) == (120, 80)
    assert (L["PWH"].price, L["PWL"].price) == (130, 70)
    assert L["PDH"].formed_at == ny("2026-10-12 22:00")
    assert L["PDL"].formed_at == ny("2026-10-13 10:00")
    assert L["PWH"].formed_at == ny("2026-10-04 19:00")


def test_pdh_wurde_am_mittwoch_genommen(tf):
    rep = levels.compute_levels(tf, ny("2026-10-14 09:00"))
    assert rep.levels["PDH"].taken is True     # Mi 08:00 High 125 > 120
    assert rep.levels["PDL"].taken is False


def test_vor_dem_sweep_noch_unberuehrt(tf):
    rep = levels.compute_levels(tf, ny("2026-10-14 07:00"))
    assert rep.levels["PDH"].taken is False


def test_laufender_tag_zaehlt_nicht_als_vortag(tf):
    # Dienstag 16:00: Dienstag läuft noch -> Vortag ist Montag
    rep = levels.compute_levels(tf, ny("2026-10-13 16:00"))
    assert rep.prev_day.name == pd.Timestamp("2026-10-12")


def test_am_wochenende_ist_freitag_der_vortag(tf):
    rep = levels.compute_levels(tf, ny("2026-10-10 12:00"))   # Samstag
    assert rep.prev_day.name == pd.Timestamp("2026-10-09")
    assert rep.prev_week.name == pd.Timestamp("2026-10-05")
    assert rep.levels["PWL"].price == 70


def test_zeitreise_mit_cut_at(tf):
    cut = data.cut_at(tf, ny("2026-10-14 09:00"))
    assert cut["H1"].index[-1] == ny("2026-10-14 08:00")
    rep = levels.compute_levels(cut, ny("2026-10-14 09:00"))
    assert rep.levels["PDH"].price == 120


def test_wilson_vertrauensbereich():
    import backtest
    lo, hi = backtest.wilson(50, 100)
    assert round(lo, 2) == 0.40 and round(hi, 2) == 0.60
    lo, hi = backtest.wilson(0, 0)
    assert (lo, hi) == (0.0, 1.0)


def test_zeitreise_nur_abgeschlossene_kerzen(tf):
    # Um 07:30 ist die H1-Kerze 07:00–08:00 noch NICHT fertig -> darf nicht drin sein
    cut = data.cut_at(tf, ny("2026-10-14 07:30"))
    assert cut["H1"].index[-1] == ny("2026-10-14 06:00")


def test_zeitreise_ohne_blick_in_die_zukunft(tf):
    # Die H4-Kerze 06:00–10:00 darf um 07:30 nur die Stunden 06:00 und 07:00
    # enthalten – NICHT das High 125 von 08:00.
    cut = data.cut_at(tf, ny("2026-10-14 07:30"))
    assert cut["H4"].loc[ny("2026-10-14 06:00"), "High"] == 101
    assert cut["D"]["High"].iloc[-1] == 101


def test_forex_kerzen_nach_freitagsschluss_werden_ignoriert():
    # Forex-Woche: So 17:00 bis Fr 17:00, plus "Geisterkerzen" Fr 17:00–18:00
    idx = pd.date_range("2026-10-11 17:00", "2026-10-16 18:00", freq="1h", tz=TZ)
    h1 = pd.DataFrame({"Open": 1.10, "High": 1.11, "Low": 1.09, "Close": 1.10}, index=idx)
    h1.loc[ny("2026-10-16 17:00"), ["High", "Close"]] = [1.50, 1.50]   # Geisterkerze
    tf = data.build_timeframes(h1, config.INSTRUMENTS["EURUSD"])
    assert set(tf["D"].index.weekday) <= {0, 1, 2, 3, 4}
    assert tf["W"].iloc[-1]["High"] == pytest.approx(1.11)
    assert tf["W"].iloc[-1]["Close"] == pytest.approx(1.10)


# --- Zeitumstellung (USA: 01.11.2026) ---------------------------------------
def test_zeitumstellung_ohne_fehler():
    h1 = make_sample_h1("2026-10-25 18:00", "2026-11-06 16:00")
    tf = data.build_timeframes(h1, US100)
    assert set(tf["D"].index.weekday) <= {0, 1, 2, 3, 4}
    # Jede Tageskerze beginnt um 18:00 NY – vor und nach der Umstellung
    assert set(tf["D"]["start"].dt.hour) == {18}
    # 23 Stundenkerzen pro Handelstag (18:00 bis 16:00)
    counts = h1.groupby(data._shifted_wall_clock(h1.index, 18).floor("D")).size()
    assert set(counts) == {23}


# --- CSV-Import -------------------------------------------------------------
def test_csv_deutsches_format_und_berlin_zeit(tmp_path):
    p = tmp_path / "export.csv"
    p.write_text(
        "Datum;Open;High;Low;Close\n"
        "14.10.2026 15:00;21.400,00;21.480,25;21.390,50;21.450,00\n"
        "14.10.2026 16:00;21.450,00;21.460,00;21.420,00;21.430,00\n",
        encoding="utf-8",
    )
    df = data.load_csv(str(p), csv_tz="Europe/Berlin")
    # 15:00 Berlin (Sommerzeit) = 09:00 New York
    assert df.index[0] == ny("2026-10-14 09:00")
    assert df["High"].iloc[0] == pytest.approx(21480.25)


def test_csv_iso_datum_wird_nicht_vertauscht(tmp_path):
    p = tmp_path / "iso.csv"
    make_sample_h1().to_csv(p, index_label="Datum", date_format="%Y-%m-%d %H:%M")
    tf = data.build_timeframes(data.load_csv(str(p)), US100)
    rep = levels.compute_levels(tf, ny("2026-10-14 09:00"))
    assert (rep.levels["PDH"].price, rep.levels["PDL"].price) == (120, 80)
    assert (rep.levels["PWH"].price, rep.levels["PWL"].price) == (130, 70)


def test_csv_tradingview_unix_zeit(tmp_path):
    p = tmp_path / "tv.csv"
    t = int(ny("2026-10-14 09:00").timestamp())
    p.write_text(f"time,open,high,low,close\n{t},1.1,1.2,1.0,1.15\n", encoding="utf-8")
    df = data.load_csv(str(p))
    assert df.index[0] == ny("2026-10-14 09:00")
    assert df["Close"].iloc[0] == pytest.approx(1.15)
