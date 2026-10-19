"""
config.py – Alle einstellbaren Parameter an EINEM Ort.

Wenn du etwas anpassen willst (anderes Symbol, andere Session-Zeiten,
andere Swing-Länge), änderst du es hier – nicht im restlichen Code.
"""

# ---------------------------------------------------------------------------
# Zeitzonen
# ---------------------------------------------------------------------------
# Intern rechnen wir IMMER in New-York-Zeit (ICT-Standard).
# Für die Ausgabe zeigen wir zusätzlich Berliner Zeit an.
TZ_NY = "America/New_York"
TZ_BERLIN = "Europe/Berlin"

# ---------------------------------------------------------------------------
# Instrumente
# ---------------------------------------------------------------------------
# yf_symbol   : Kürzel bei Yahoo Finance (yfinance)
# day_start_ny: Uhrzeit (NY) am VORTAG, zu der ein neuer Handelstag beginnt.
# day_end_ny  : Uhrzeit (NY), zu der der Handelstag schließt.
#               - Nasdaq-Futures (CME): 18:00 bis 17:00 NY (1 h Pause dazwischen)
#               - Forex:                17:00 bis 17:00 NY
#               So sehen die Daily-Kerzen auch in TradingView & Co. aus.
#               Beispiel US100: Die "Dienstag"-Kerze läuft von
#               Montag 18:00 bis Dienstag 17:00 NY-Zeit.
# decimals    : Nachkommastellen für die Ausgabe
# Positionsgröße (risk.py):
#   point              : Größe von 1 Punkt bzw. 1 Pip im Kurs
#   lot_step           : kleinste Lot-Schrittweite bei deinem Broker
#   value_per_point_eur: € je Punkt und 1 Lot (nur US100 – BITTE an deinen
#                        Broker anpassen! Viele CFD-Broker: 1 Lot = 1 € je Punkt)
#   Forex wird automatisch berechnet: 10 USD bzw. GBP je Pip und Standard-Lot
INSTRUMENTS = {
    "US100": {
        "name": "Nasdaq 100 (E-mini Future)",
        "yf_symbol": "NQ=F",      # Alternative: "^NDX" (Kassa-Index, nur RTH)
        "day_start_ny": 18,
        "day_end_ny": 17,
        "decimals": 2,
        "point": 1.0,
        "lot_step": 0.01,
        "value_per_point_eur": 1.0,
    },
    "EURUSD": {
        "name": "EUR/USD",
        "yf_symbol": "EURUSD=X",
        "day_start_ny": 17,
        "day_end_ny": 17,
        "decimals": 5,
        "point": 0.0001,
        "lot_step": 0.01,
    },
    "EURGBP": {
        "name": "EUR/GBP",
        "yf_symbol": "EURGBP=X",
        "day_start_ny": 17,
        "day_end_ny": 17,
        "decimals": 5,
        "point": 0.0001,
        "lot_step": 0.01,
    },
}

# Standardwerte für den Positionsgrößen-Rechner
ACCOUNT_SIZE_EUR = 10_000
RISK_PCT = 1.0

# ---------------------------------------------------------------------------
# Datenmenge, die von yfinance geladen wird
# ---------------------------------------------------------------------------
# yfinance-Grenzen: 1h-Daten max. ~730 Tage, 15m-Daten max. 60 Tage.
DOWNLOAD_PERIOD_H1 = "730d"
DOWNLOAD_PERIOD_M15 = "60d"

# ---------------------------------------------------------------------------
# Marktstruktur (Schritt 2)
# ---------------------------------------------------------------------------
# Ein Swing High braucht mindestens so viele Kerzen links UND rechts,
# die ein niedrigeres Hoch haben (Fraktal). Gleiches gilt für Swing Lows.
# Achtung: Ein Swing ist erst bestätigt, wenn die Kerzen rechts davon
# geschlossen haben – bei 2 also zwei Kerzen später.
SWING_LENGTH = 2

# Bruch-Regel (fest, nicht einstellbar): Ein BOS oder MSS zählt nur, wenn
# der KERZENKÖRPER den Swing bricht (Schlusskurs jenseits des Swings).
# Ein Docht allein ist nie ein Bruch.

# Kerzen-MSS: Zusätzlich zählt als MSS, wenn ein Körper über dem HOCH der
# Kerze schließt, die das letzte Low gemacht hat (bzw. unter dem TIEF der
# Kerze, die das letzte High gemacht hat). Beispiel EUR/USD: Die Kerze vom
# 14.10. machte das Low, der 15.10. schloss über ihrem Hoch -> MSS nach oben.
# Pro Timeframe ein-/ausschaltbar:
CANDLE_MSS = {
    "Daily": True,
    "H4": False,      # auf H4 würde das sehr oft auslösen
    "Weekly": False,
}

# HTF-Trend: Der DAILY gibt die Richtung vor. Der H4 zeigt, in welcher Phase
# des Daily-Beins wir sind (läuft mit / Retracement / Retracement beendet).
# Ein H4 gegen den Daily ist KEIN Widerspruch, sondern ein Rücklauf – solange
# das Protected Low (bullish) bzw. Protected High (bearish) des Daily hält.
# Der Weekly wird nur als Information angezeigt.
# Swing-Länge für den H4 (darf vom Daily abweichen):
SWING_LENGTH_H4 = 2

# ---------------------------------------------------------------------------
# Liquidity Sweep (LQS)
# ---------------------------------------------------------------------------
# Das Programm BEWERTET Sweeps nicht – das machst du selbst im M15.
# Es zeigt nur die Sweep-Punkte (gültig/ungültig nach harter Regel 2) und
# eine Checkliste mit deinen LQS-Kriterien:
#   a) kleiner Körper in unsere Richtung + langer Docht in Gegenrichtung
#   b) Körper gegen uns, danach mind. gleich großer Körper in unsere Richtung
#
# Mit welchem Timeframe wird geprüft, ob ein Level schon erreicht wurde?
STATUS_TIMEFRAME = "M15"    # (Ersatz: H1, falls keine M15-Daten vorliegen)

# ---------------------------------------------------------------------------
# Daily Bias (Schritt 3)
# ---------------------------------------------------------------------------
# Die Konfidenz startet bei 50 % und wird durch die Kriterien erhöht oder
# gesenkt (Punkte = Prozentpunkte). So ist jede Zahl nachvollziehbar.
BIAS_START = 50
BIAS_POINTS = {
    "daily_bos": +10,            # Daily-Trend durch BOS bestätigt
    "daily_mss_frisch": -5,      # Trendwechsel ganz frisch (nur MSS)
    "h4_mit_daily": +10,         # H4 läuft mit dem Daily
    "h4_retrace_ende_tief": +15, # H4-MSS zurück nach Retracement >= 50 %
    "h4_retrace_ende_flach": +5, # H4-MSS zurück, Retracement < 50 %
    "h4_retrace_offen": -10,     # H4 läuft noch gegen Daily, Zone nicht erreicht
    "pd_passt": +15,             # Previous-Day-Signal in Bias-Richtung
    "pd_inside": -10,            # Inside Day -> wenig Information
    "pd_outside": -5,            # beide Seiten gesweept, in Range geschlossen
    "zone_passt": +10,           # Preis im richtigen Bereich (Premium/Discount)
    "zone_falsch": -10,
    "dol_vorhanden": +10,        # klares Liquiditätsziel in Bias-Richtung
    "dol_fehlt": -15,
}
# Unter dieser Konfidenz gibt es KEINEN Bias -> "NEUTRAL – kein Trade"
BIAS_MIN_CONFIDENCE = 55

# ---------------------------------------------------------------------------
# H4-Führung: Daily unklar -> H4 darf den Bias bestimmen
# ---------------------------------------------------------------------------
# Greift NUR, wenn der Daily allein keinen Bias liefert (Trend unklar oder
# Widerspruch). Dann braucht der H4: Liquidity Sweep (nach den LQS-Kriterien
# unten) + danach MSS per Körper, frisch und nicht wieder verletzt.
H4_LEAD = True
H4_LEAD_MAX_AGE = 18          # MSS höchstens 18 H4-Kerzen alt (~3 Handelstage)
H4_LEAD_SWEEP_WINDOW = 10     # Sweep höchstens 10 H4-Kerzen vor dem MSS
# Darf der H4 GEGEN einen klaren Daily-Trend führen?
#   False (Standard): Nein. Der H4 führt nur, wenn der Daily-Trend unklar ist
#                     oder der H4 in Daily-Richtung zeigt. Ein H4 gegen den
#                     Daily ist ein Retracement (Beispiel US100 Fr 16.10.).
#   True            : Ja, wenn zusätzlich das Previous-Day-Signal in H4-Richtung zeigt.
H4_LEAD_AGAINST_DAILY = False
BIAS_POINTS.update({
    "h4_lqs": +10,            # H4-Liquidity-Sweep erkannt
    "h4_mss": +10,            # H4-MSS nach dem Sweep
    "h4_bos_danach": +5,      # H4-BOS nach dem MSS bestätigt die Richtung
    "h4_gefuehrt": -10,       # Abschlag: Daily hat noch nicht bestätigt
    "gegen_daily": -10,       # Abschlag: gegen den (noch) laufenden Daily-Trend
    "pd_gegen": -15,          # Previous-Day-Signal gegen die H4-Richtung
})

# LQS-Kriterien für die AUTOMATISCHE H4-Prüfung (dein M15 prüfst du weiter selbst):
#   a) Ablehnungskerze: kleiner Körper in unsere Richtung + langer Docht dagegen
#   b) 2-Kerzen-Umkehr: Körper gegen uns, danach mind. gleich großer Körper für uns
LQS_MAX_BODY_RATIO = 0.35     # (a) Körper höchstens 35 % der Kerze
LQS_MIN_WICK_RATIO = 0.50     # (a) Ablehnungsdocht mindestens 50 % der Kerze
LQS_WICK_TO_BODY = 2.0        # (a) und mindestens 2x so lang wie der Körper
LQS_ALLOW_DOJI = True         # (a) Doji (Open = Close) als kleinen Körper erlauben
# Wie viele Daily-Kerzen zurück nach unberührten Swings / offenen FVGs suchen?
DOL_LOOKBACK_DAYS = 120

# ---------------------------------------------------------------------------
# POIs (Modul 2)
# ---------------------------------------------------------------------------
# Displacement = impulsive Kerze. Beide Bedingungen müssen erfüllt sein:
DISP_BODY_RATIO = 0.6       # Körper mind. 60 % der Kerzenlänge (wenig Docht)
DISP_RANGE_MULT = 1.5       # Kerzenlänge mind. 1,5x so groß wie der Durchschnitt
DISP_AVG_PERIOD = 14        # ... der letzten 14 Kerzen

# Order Block: letzte gegenläufige Kerze vor der Displacement-Kerze.
# So viele Kerzen vor dem Displacement wird nach ihr gesucht:
OB_LOOKBACK = 5

# H4-POI (Stufe B) zählt nur mit genug Bestätigungen (von 4 möglichen):
#   1. Bias-Richtung + richtiger Bereich (Discount bullish / Premium bearish) – PFLICHT
#   2. durch Displacement entstanden
#   3. vor der Entstehung wurde Liquidität gesweept (ein H4-Swing genommen)
#   4. überschneidet sich mit einem Daily-POI
H4_MIN_CONFIRMATIONS = 3
H4_SWEEP_LOOKBACK = 6       # so viele H4-Kerzen vor dem POI wird nach dem Sweep gesucht
H4_POI_LOOKBACK = 300       # nur H4-POIs aus den letzten 300 H4-Kerzen (~ 2 Monate)
MAX_POIS_SHOWN = 5          # pro Stufe höchstens so viele anzeigen (die nächsten)

# ---------------------------------------------------------------------------
# Sessions (harte Regel 3: Session Highs/Lows sind Sweep-Punkte)
# ---------------------------------------------------------------------------
# Jede Session hat die Zeitzone ihres Marktes. So stimmen die Zeiten auch in
# den Wochen, in denen Europa und die USA zu verschiedenen Terminen auf
# Sommer-/Winterzeit umstellen (dann beginnt z. B. NY AM um 14:30 Berlin).
#   start/end : "HH:MM" in der angegebenen Zeitzone (tz)
#   relevant  : False = wird angezeigt, aber als "meist irrelevant" markiert
SESSIONS = {
    "Asia":          {"start": "00:00", "end": "06:00", "tz": TZ_BERLIN, "relevant": True},
    "London":        {"start": "09:00", "end": "11:00", "tz": TZ_BERLIN, "relevant": True},
    "NY Pre-Market": {"start": "08:30", "end": "09:30", "tz": TZ_NY, "relevant": True},
    "NY AM":         {"start": "09:30", "end": "11:00", "tz": TZ_NY, "relevant": True},
    "NY PM":         {"start": "13:00", "end": "15:00", "tz": TZ_NY, "relevant": False},
}

# Power of 3: Referenz-Open ("True Day Open") = Midnight Open in NY-Zeit
PO3_OPEN_NY = "00:00"
# Session, in der der Pre-Market-Fakeout gesucht wird
PO3_PREMARKET = "NY Pre-Market"
