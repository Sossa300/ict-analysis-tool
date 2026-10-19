"""
Künstliche Beispieldaten mit BEKANNTEN Hochs und Tiefs.

Weil wir die Extremwerte selbst platzieren, wissen wir genau, was das Tool
erkennen muss. So lässt sich prüfen, ob PDH/PDL/PWH/PWL stimmen.

Aufbau (US100-Handelszeiten, NY-Zeit, H1-Kerzen):
  - Normale Kerzen: Open 100, High 101, Low 99, Close 100
  - Woche ab Mo 05.10.2026:
      * So 04.10. 19:00  High 130   -> PWH (gehört schon zur Woche!)
      * Fr 09.10. 16:00  Low   70   -> PWL
  - Dienstag-Kerze 13.10.2026 (läuft Mo 18:00 bis Di 17:00):
      * Mo 12.10. 22:00  High 120   -> PDH (Montagabend zählt zu Dienstag!)
      * Di 13.10. 10:00  Low   80   -> PDL
  - Mi 14.10. 08:00  High 125       -> nimmt den PDH (Sweep/Break)

Aufruf "python tests/beispieldaten.py" schreibt die Daten zusätzlich als
CSV, damit du main.py damit ausprobieren kannst.
"""

import os
import sys

import pandas as pd

TZ = "America/New_York"


def is_cme_open(ts: pd.Timestamp) -> bool:
    """Nasdaq-Futures: So 18:00 bis Fr 17:00, täglich Pause 17:00–18:00."""
    wd, h = ts.weekday(), ts.hour
    if h == 17:
        return False
    if wd == 5:                      # Samstag
        return False
    if wd == 6 and h < 18:           # Sonntag vor 18:00
        return False
    if wd == 4 and h >= 17:          # Freitag ab 17:00
        return False
    return True


def make_sample_h1(start="2026-10-04 18:00", end="2026-10-16 16:00") -> pd.DataFrame:
    idx = pd.date_range(start, end, freq="1h", tz=TZ)
    idx = idx[[is_cme_open(t) for t in idx]]
    df = pd.DataFrame({"Open": 100.0, "High": 101.0, "Low": 99.0, "Close": 100.0},
                      index=idx)
    df.index.name = "time"

    def put(when, high=None, low=None):
        t = pd.Timestamp(when, tz=TZ)
        if t not in df.index:        # liegt außerhalb des gewählten Zeitraums
            return
        if high is not None:
            df.loc[t, "High"] = high
        if low is not None:
            df.loc[t, "Low"] = low

    put("2026-10-04 19:00", high=130)   # PWH
    put("2026-10-09 16:00", low=70)     # PWL
    put("2026-10-12 22:00", high=120)   # PDH der Dienstag-Kerze
    put("2026-10-13 10:00", low=80)     # PDL der Dienstag-Kerze
    put("2026-10-14 08:00", high=125)   # bricht den PDH am Mittwoch
    return df


if __name__ == "__main__":
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "beispiel_us100_h1.csv")
    df = make_sample_h1()
    csv = df.copy()
    csv.index = csv.index.strftime("%Y-%m-%d %H:%M")
    csv.index.name = "Datum"
    csv.to_csv(out)
    print(f"Beispieldaten geschrieben: {out}", file=sys.stderr)
