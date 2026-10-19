"""
Tests für journal.py (Forward-Test-Protokoll) – mit Beispieldaten und
einem festen "jetzt", damit die Tests immer gleich laufen.
"""

import datetime as dt
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config  # noqa: E402
import data  # noqa: E402
import journal  # noqa: E402
from tests.beispieldaten import make_sample_h1  # noqa: E402

NY, BE = config.TZ_NY, config.TZ_BERLIN


def _tf():
    return data.build_timeframes(make_sample_h1(), config.INSTRUMENTS["US100"])


def _mit_start(tmp_path, start="2026-10-12"):
    d = tmp_path / "ft"
    d.mkdir()
    (d / "start.txt").write_text(start, encoding="utf-8")
    return str(d)


def test_entscheidungszeit_1530_berlin():
    assert journal.decision_time(dt.date(2026, 10, 14)) == pd.Timestamp("2026-10-14 09:30", tz=NY)
    # Zeitumstellungswoche: 15:30 Berlin = 10:30 NY
    assert journal.decision_time(dt.date(2026, 10, 27)) == pd.Timestamp("2026-10-27 10:30", tz=NY)


def test_start_ist_naechster_handelstag(tmp_path):
    # Erster Aufruf am Samstag 17.10. -> Start Montag 19.10.
    d = str(tmp_path / "neu")
    assert journal.start_date(d, dt.date(2026, 10, 17)) == dt.date(2026, 10, 19)
    # Danach bleibt der Start fest
    assert journal.start_date(d, dt.date(2026, 11, 30)) == dt.date(2026, 10, 19)


def test_regel_version_ist_stabil():
    assert journal.regel_version() == journal.regel_version()
    assert len(journal.regel_version()) == 8


def test_snapshot_nur_mit_daten_vor_1530():
    tf = _tf()
    snap = journal.snapshot("US100", tf, dt.date(2026, 10, 14), "test")
    # Mi 08:00 NY (14:00 Berlin) hatte High 125 – liegt VOR 15:30 und ist bekannt.
    # Letzter Preis = Schluss der letzten Kerze, die bis 09:30 NY fertig war.
    assert snap["Datum"] == "2026-10-14" and snap["Symbol"] == "US100"
    assert snap["A_Richtung"] in ("bullish", "bearish", "neutral")
    assert snap["B_Richtung"] in ("bullish", "bearish", "neutral")


def test_wochenende_kein_eintrag():
    assert journal.snapshot("US100", _tf(), dt.date(2026, 10, 10), "test") is None


def test_update_traegt_nach_und_wertet_aus(tmp_path):
    d = _mit_start(tmp_path)
    jetzt = pd.Timestamp("2026-10-16 23:30", tz=BE).tz_convert(NY)
    df = journal.update({"US100": _tf()}, directory=d, now=jetzt)
    assert list(df["Datum"]) == ["2026-10-12", "2026-10-13", "2026-10-14",
                                 "2026-10-15", "2026-10-16"]
    assert df["Bewertung_genau"].notna().all()           # alle Tage fertig -> ausgewertet
    assert os.path.exists(os.path.join(d, "journal.csv"))

    # Zweiter Aufruf: keine doppelten Einträge
    df2 = journal.update({"US100": _tf()}, directory=d, now=jetzt)
    assert len(df2) == 5


def test_laufender_tag_wartet_auf_schluss(tmp_path):
    d = _mit_start(tmp_path, "2026-10-16")
    jetzt = pd.Timestamp("2026-10-16 16:00", tz=BE).tz_convert(NY)   # nach 15:30, vor Schluss
    df = journal.update({"US100": _tf()}, directory=d, now=jetzt)
    assert len(df) == 1
    assert "Bewertung_genau" not in df.columns or df["Bewertung_genau"].isna().all()


def test_auswertung_treffer():
    tf = _tf()
    row = {"Datum": "2026-10-14", "A_Richtung": "bullish", "A_DOL": "125,5",
           "B_Richtung": "neutral", "B_DOL": ""}
    ev = journal.evaluate(row, tf, pd.Timestamp("2026-10-15 12:00", tz=NY))
    assert ev is not None
    assert ev["B_Treffer"] == ""                           # kein Signal -> nichts zu bewerten
    assert ev["A_DOL_erreicht"] in (True, False)


def test_bericht():
    df = pd.DataFrame({
        "Datum": ["2026-10-19", "2026-10-20", "2026-10-21"], "Symbol": ["US100"] * 3,
        "Regel_Version": ["abc"] * 3, "Bewertung_genau": ["ja", "ja", ""],
        "A_Treffer": ["True", "False", ""], "A_MFE_gr_MAE": ["True", "True", ""],
        "A_DOL_erreicht": ["False", "", ""],
        "B_Treffer": ["True", "", ""], "B_MFE_gr_MAE": ["True", "", ""],
        "B_DOL_erreicht": ["", "", ""],
    })
    st = journal.stats(df)
    a = st[(st["Signal"].str.startswith("Signal A")) & (st["Instrument"] == "alle")].iloc[0]
    assert a["Tage"] == 2 and a["Treffer"] == "50%"
    txt = journal.report(df)
    assert "2 ausgewertet" in txt and "1 warten" in txt
