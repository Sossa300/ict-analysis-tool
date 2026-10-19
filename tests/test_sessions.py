"""
Tests für sessions.py: Session-Zeiten, Session Highs/Lows, Power of 3.
"""

import datetime as dt
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config  # noqa: E402
import sessions  # noqa: E402
import sweeps  # noqa: E402
from structure import BEARISH, BULLISH  # noqa: E402

NY, BE = config.TZ_NY, config.TZ_BERLIN


def ny(s):
    return pd.Timestamp(s, tz=NY)


def m15(start, end, base=100.0):
    """Ruhige M15-Kerzen: Open=Close=base, High base+0.5, Low base-0.5."""
    idx = pd.date_range(start, end, freq="15min", tz=NY, inclusive="left")
    return pd.DataFrame({"Open": base, "High": base + 0.5, "Low": base - 0.5,
                         "Close": base}, index=idx)


# --- Zeiten -----------------------------------------------------------------------
def test_session_zeiten_sommer():
    # 14.10.2026: Berlin MESZ (UTC+2), NY EDT (UTC-4) -> 6 h Unterschied
    d = dt.date(2026, 10, 14)
    s, e = sessions.window("Asia", d)
    assert (s, e) == (ny("2026-10-13 18:00"), ny("2026-10-14 00:00"))   # 00–06 Berlin
    s, e = sessions.window("London", d)
    assert (s, e) == (ny("2026-10-14 03:00"), ny("2026-10-14 05:00"))   # 09–11 Berlin
    s, e = sessions.window("NY AM", d)
    assert s.tz_convert(BE).strftime("%H:%M") == "15:30"


def test_zeitumstellungswoche_ny_am_um_1430_berlin():
    # 27.10.2026: Berlin schon Winterzeit, NY noch Sommerzeit -> nur 5 h Unterschied
    s, _ = sessions.window("NY AM", dt.date(2026, 10, 27))
    assert s == ny("2026-10-27 09:30")
    assert s.tz_convert(BE).strftime("%H:%M") == "14:30"
    # London bleibt bei 09:00 Berlin
    s, _ = sessions.window("London", dt.date(2026, 10, 27))
    assert s.tz_convert(BE).strftime("%H:%M") == "09:00"


# --- Highs/Lows -----------------------------------------------------------------------
def _tag():
    """Kerzen von Di 18:00 NY bis Mi 10:00 NY mit markierten Extremen."""
    df = m15("2026-10-13 18:00", "2026-10-14 10:00")
    df.loc[ny("2026-10-13 21:00"), "High"] = 103      # Asia High
    df.loc[ny("2026-10-13 22:00"), "Low"] = 98        # Asia Low
    df.loc[ny("2026-10-14 04:00"), "High"] = 104      # London High
    df.loc[ny("2026-10-14 08:45"), "Low"] = 97        # Pre-Market Low
    return df


def test_session_highs_lows():
    as_of = ny("2026-10-14 09:45")                     # 15:45 Berlin
    r = {x.name: x for x in sessions.session_ranges(_tag(), as_of)}
    assert (r["Asia"].high, r["Asia"].low) == (103, 98)
    assert r["London"].high == 104
    assert r["NY Pre-Market"].low == 97
    assert "NY AM" not in r                            # läuft noch, nicht abgeschlossen
    assert sessions.running(_tag(), as_of).name == "NY AM"


def test_ny_pm_ist_als_irrelevant_markiert():
    df = m15("2026-10-13 12:00", "2026-10-13 16:00")
    r = sessions.latest_completed(df, ny("2026-10-13 16:00"), "NY PM")
    assert r is not None and r.relevant is False


def test_session_punkte_in_watchlist():
    from types import SimpleNamespace
    import levels
    lv = {k: levels.Level(k, p, None, "", False)
          for k, p in (("PDH", 110), ("PDL", 90), ("PWH", 120), ("PWL", 80))}
    rep = SimpleNamespace(levels=lv, last_price=100.0,
                          prev_day={"end": ny("2026-10-13 17:00")},
                          prev_week={"end": ny("2026-10-09 17:00")})
    as_of = ny("2026-10-14 09:45")
    rng = sessions.session_ranges(_tag(), as_of)
    pts = {p.name: p for p in sweeps.watchlist(rep, BEARISH, _tag(), as_of, rng)}
    assert pts["London High"].valid and not pts["London Low"].valid    # harte Regel 2
    assert pts["London High"].price == 104


# --- Power of 3 -------------------------------------------------------------------------
def test_po3_bullish_mit_pre_market_fakeout():
    df = _tag()
    # Midnight Open 100; Pre-Market fällt auf 97 (neues Tagestief), schließt bei 100,2
    df.loc[ny("2026-10-14 09:15"), "Close"] = 100.2
    df.loc[ny("2026-10-14 09:30"), "Close"] = 100.4
    lv = [("PDL", 99.0, ny("2026-10-13 17:00")), ("Asia Low", 98.0, ny("2026-10-14 00:00"))]
    p = sessions.power_of_three(df, ny("2026-10-14 09:45"), BULLISH, lv)
    assert p.manipulation and p.manip_extreme == 97
    assert p.manip_session == "NY Pre-Market"
    assert set(p.swept) == {"PDL", "Asia Low"}
    assert p.premarket_fakeout is True
    assert p.price_ok is True


def test_po3_level_aus_der_zukunft_zaehlt_nicht():
    df = _tag()
    # "London Low" existiert erst ab 05:00 NY – die Manipulation um 08:45 darf es nehmen,
    # ein Level ab 09:00 NY aber nicht
    lv = [("Spaeter", 99.0, ny("2026-10-14 09:00"))]
    p = sessions.power_of_three(df, ny("2026-10-14 09:45"), BULLISH, lv)
    assert p.swept == []


def test_po3_bearish_gespiegelt():
    df = m15("2026-10-13 18:00", "2026-10-14 10:00")
    df.loc[ny("2026-10-14 08:45"), "High"] = 103      # Fakeout nach oben im Pre-Market
    df.loc[ny("2026-10-14 09:30"), "Close"] = 99.5    # wieder unter dem Open (100)
    p = sessions.power_of_three(df, ny("2026-10-14 09:45"), BEARISH, [])
    assert p.manipulation and p.manip_extreme == 103
    assert p.premarket_fakeout and p.price_ok


def test_po3_ohne_manipulation():
    df = m15("2026-10-13 18:00", "2026-10-14 10:00")
    df["Low"] = 100.0                                  # nie unter dem Open
    p = sessions.power_of_three(df, ny("2026-10-14 09:45"), BULLISH, [])
    assert not p.manipulation and not p.premarket_fakeout
