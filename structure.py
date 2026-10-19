"""
structure.py – Marktstruktur: Swing Highs/Lows, BOS, MSS und Trend.

Begriffe (allgemein gängige ICT-Definitionen):

  Swing High : Kerze, deren Hoch höher ist als die Hochs der n Kerzen links
               und rechts davon (Fraktal, n = config.SWING_LENGTH).
  Swing Low  : entsprechend das tiefste Tief mit n Kerzen links und rechts.

  Bruch      : Zählt NUR, wenn der Kerzenkörper den Swing bricht, also der
               Schlusskurs jenseits des Swings liegt. Ein Docht allein reicht nie.

  BOS (Break of Structure)
             : Der Preis bricht einen Swing IN Trendrichtung.
               Bullish: Schluss über dem letzten Swing High im Aufwärtstrend.
               -> Trend wird bestätigt / fortgesetzt.
  MSS (Market Structure Shift)
             : Der Preis bricht einen Swing GEGEN den bisherigen Trend.
               Beispiel: Im Abwärtstrend schließt eine Kerze über dem
               letzten Swing High -> Trend dreht auf bullish.

Wichtig – kein Blick in die Zukunft:
  Ein Swing ist erst bestätigt, wenn die n Kerzen rechts davon geschlossen
  haben. Erst AB DANN kann er gebrochen werden. So erkennt das Tool nur,
  was du live im Chart auch hättest sehen können.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

import config

BULLISH, BEARISH, UNKLAR = "bullish", "bearish", "unklar"


@dataclass
class Swing:
    kind: str                     # "high" oder "low"
    pos: int                      # Position (Zeilennummer) der Swing-Kerze
    time: pd.Timestamp            # Index-Wert der Swing-Kerze
    price: float
    confirmed_pos: int            # ab dieser Kerze ist der Swing bestätigt


@dataclass
class StructureBreak:
    kind: str                     # "BOS" oder "MSS"
    direction: str                # BULLISH oder BEARISH (neue Richtung)
    pos: int                      # Kerze, die gebrochen hat
    time: pd.Timestamp
    level: float                  # Preis des gebrochenen Swings
    swing: Swing                  # welcher Swing wurde gebrochen?
    source: str = "swing"         # "swing" oder "kerze" (Kerzen-MSS, s. find_breaks)


@dataclass
class TrendResult:
    timeframe: str
    trend: str                                    # BULLISH / BEARISH / UNKLAR
    swings: list[Swing] = field(default_factory=list)
    breaks: list[StructureBreak] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)

    @property
    def last_break(self) -> StructureBreak | None:
        return self.breaks[-1] if self.breaks else None

    def last_swing(self, kind: str) -> Swing | None:
        """Letzter bestätigter Swing High ("high") bzw. Swing Low ("low")."""
        found = [s for s in self.swings if s.kind == kind]
        return found[-1] if found else None


# ---------------------------------------------------------------------------
# 1) Swings finden
# ---------------------------------------------------------------------------
def find_swings(candles: pd.DataFrame, n: int = config.SWING_LENGTH) -> list[Swing]:
    """
    Findet alle Swing Highs und Lows.

    Regel bei gleich hohen Hochs (Equal Highs): Die Kerze muss links
    STRENG höher sein (>) und rechts mindestens gleich hoch (>=).
    So wird bei zwei gleichen Hochs nur das erste als Swing gezählt.
    """
    highs = candles["High"].to_numpy()
    lows = candles["Low"].to_numpy()
    swings: list[Swing] = []

    # Die ersten und letzten n Kerzen können kein Swing sein,
    # weil links bzw. rechts nicht genug Kerzen vorhanden sind.
    for i in range(n, len(candles) - n):
        left_h, right_h = highs[i - n:i], highs[i + 1:i + n + 1]
        left_l, right_l = lows[i - n:i], lows[i + 1:i + n + 1]

        if highs[i] > left_h.max() and highs[i] >= right_h.max():
            swings.append(Swing("high", i, candles.index[i], float(highs[i]), i + n))
        if lows[i] < left_l.min() and lows[i] <= right_l.min():
            swings.append(Swing("low", i, candles.index[i], float(lows[i]), i + n))

    return swings


# ---------------------------------------------------------------------------
# 2) BOS / MSS erkennen
# ---------------------------------------------------------------------------
def find_breaks(candles: pd.DataFrame, swings: list[Swing],
                candle_mss: bool = False) -> list[StructureBreak]:
    """
    Geht Kerze für Kerze durch den Chart (wie live) und prüft:
    Schließt der KERZENKÖRPER über dem letzten aktiven Swing High bzw.
    unter dem letzten aktiven Swing Low?

    Feste Regel (BOS und MSS): Nur der Körper zählt, also der Schlusskurs.
    Ein Docht allein über/unter dem Swing ist KEIN Bruch – das ist höchstens
    ein Sweep (Liquidität geholt), siehe sweeps.py.

    "Aktiv" heißt: bestätigt und noch nicht gebrochen. Kommt ein neuer
    Swing High dazu, ersetzt er den alten (es zählt immer der jüngste).

    candle_mss = True schaltet die Kerzen-MSS-Regel zu:
      Im Abwärtstrend merkt sich das Tool die Kerze mit dem tiefsten Tief des
      laufenden Beins ("Low-Kerze"). Schließt eine spätere Kerze per Körper
      ÜBER dem Hoch dieser Low-Kerze -> MSS nach oben.
      Im Aufwärtstrend spiegelverkehrt: Schluss UNTER dem Tief der Kerze mit
      dem höchsten Hoch ("High-Kerze") -> MSS nach unten.
      Diese Regel erzeugt nur MSS (Trendwechsel), keinen BOS.
    """
    close = candles["Close"].to_numpy()
    high = candles["High"].to_numpy()
    low = candles["Low"].to_numpy()

    by_confirm = sorted(swings, key=lambda s: s.confirmed_pos)
    k = 0                                  # nächster noch nicht aktivierter Swing
    active_high: Swing | None = None
    active_low: Swing | None = None
    trend: str | None = None
    ext = None                             # Extrem-Kerze des laufenden Beins
    breaks: list[StructureBreak] = []

    def add(kind, direction, j, level, swing, source="swing"):
        breaks.append(StructureBreak(kind, direction, j, candles.index[j],
                                     level, swing, source))

    for j in range(len(candles)):
        # Swings aktivieren, die VOR dieser Kerze bestätigt wurden
        while k < len(by_confirm) and by_confirm[k].confirmed_pos < j:
            s = by_confirm[k]
            if s.kind == "high":
                active_high = s
            else:
                active_low = s
            k += 1

        if active_high is not None and close[j] > active_high.price:
            add("MSS" if trend == BEARISH else "BOS", BULLISH, j,
                active_high.price, active_high)
            trend, active_high, ext = BULLISH, None, j
        elif active_low is not None and close[j] < active_low.price:
            add("MSS" if trend == BULLISH else "BOS", BEARISH, j,
                active_low.price, active_low)
            trend, active_low, ext = BEARISH, None, j
        elif candle_mss and ext is not None and ext < j:
            # Kerzen-MSS: Körper schließt jenseits der Extrem-Kerze des Beins
            if trend == BEARISH and close[j] > high[ext]:
                kerze = Swing("high", ext, candles.index[ext], float(high[ext]), ext)
                add("MSS", BULLISH, j, float(high[ext]), kerze, "kerze")
                trend, ext = BULLISH, j
            elif trend == BULLISH and close[j] < low[ext]:
                kerze = Swing("low", ext, candles.index[ext], float(low[ext]), ext)
                add("MSS", BEARISH, j, float(low[ext]), kerze, "kerze")
                trend, ext = BEARISH, j

        # Extrem-Kerze des laufenden Beins nachführen
        if ext is not None:
            if trend == BEARISH and low[j] < low[ext]:
                ext = j
            elif trend == BULLISH and high[j] > high[ext]:
                ext = j

    return breaks


# ---------------------------------------------------------------------------
# 3) Trend eines Timeframes
# ---------------------------------------------------------------------------
def analyze(candles: pd.DataFrame, timeframe: str,
            n: int = config.SWING_LENGTH, candle_mss: bool = False) -> TrendResult:
    """
    Bestimmt den Trend eines Timeframes aus dem LETZTEN Strukturbruch.
    Bitte nur abgeschlossene Kerzen übergeben (siehe completed()).
    candle_mss: Kerzen-MSS-Regel zuschalten (siehe find_breaks).
    """
    swings = find_swings(candles, n)
    breaks = find_breaks(candles, swings, candle_mss)
    res = TrendResult(timeframe, UNKLAR, swings, breaks)

    if not breaks:
        res.reasons.append(f"{timeframe}: noch kein Strukturbruch erkennbar")
        return res

    last = breaks[-1]
    res.trend = last.direction
    richtung = "nach oben" if last.direction == BULLISH else "nach unten"
    res.reasons.append(f"{timeframe}: letzter Bruch = {last.kind} {richtung}")

    # Zusatzinfo: Wurde ein MSS schon durch einen BOS bestätigt?
    if last.kind == "MSS":
        res.reasons.append(f"{timeframe}: Trendwechsel ganz frisch – noch kein "
                           "BOS in neuer Richtung (schwächer)")
    else:
        streak = 0
        for b in reversed(breaks):
            if b.direction != last.direction:
                break
            streak += 1
        res.reasons.append(f"{timeframe}: {streak} Bruch/Brüche in Folge {richtung}")
    return res


def completed(candles: pd.DataFrame, as_of: pd.Timestamp,
              bar: pd.Timedelta | None = None) -> pd.DataFrame:
    """
    Nur Kerzen, die zum Zeitpunkt as_of schon geschlossen haben.
    Daily/Weekly haben eine "end"-Spalte. Bei Intraday (z. B. H4) gibst du
    die Kerzenlänge mit: completed(h4, as_of, pd.Timedelta(hours=4)).
    """
    if "end" in candles.columns:
        return candles[candles["end"] <= as_of]
    if bar is not None:
        return candles[candles.index + bar <= as_of]
    return candles


# ---------------------------------------------------------------------------
# 4) Daily-Bein (Dealing Range) und geschützter Swing
# ---------------------------------------------------------------------------
@dataclass
class DailyLeg:
    """
    Das aktuelle Daily-Bein in Trendrichtung.

    Bullish-Beispiel:
      protected   = tiefster Punkt zwischen dem gebrochenen Swing High und
                    der Bruch-Kerze. Von hier startete die Bewegung, die
                    Struktur gebrochen hat ("Protected Low"). Solange der
                    Preis nicht darunter schließt, ist der Daily-Trend intakt.
      extreme     = höchster Punkt seit dem Bruch (Ende des Beins)
      equilibrium = 50 % dazwischen. Darunter = Discount, darüber = Premium.
    """
    direction: str
    protected: float
    protected_time: pd.Timestamp
    extreme: float
    extreme_time: pd.Timestamp
    retrace_extreme: float | None   # tiefster (bullish) Punkt NACH dem Extrem
    invalidated: bool               # Schlusskurs jenseits des geschützten Swings?

    @property
    def low(self) -> float:
        return min(self.protected, self.extreme)

    @property
    def high(self) -> float:
        return max(self.protected, self.extreme)

    @property
    def equilibrium(self) -> float:
        return (self.low + self.high) / 2

    def position(self, price: float) -> float:
        """Lage des Preises in der Range: 0 % = Low, 100 % = High."""
        span = self.high - self.low
        return (price - self.low) / span if span else 0.5

    def zone(self, price: float) -> str:
        return "Discount" if self.position(price) < 0.5 else "Premium"

    def retrace_depth(self) -> float | None:
        """Wie weit ist der Preis seit dem Extrem zurückgelaufen? (0–100 %+)"""
        if self.retrace_extreme is None:
            return None
        span = self.high - self.low
        return abs(self.extreme - self.retrace_extreme) / span if span else 0.0


def daily_leg(daily: pd.DataFrame, res: TrendResult,
              fine: pd.DataFrame | None = None) -> DailyLeg | None:
    """
    Bestimmt das aktuelle Daily-Bein aus dem letzten Daily-Strukturbruch.

    daily : abgeschlossene Daily-Kerzen (dieselben, die in analyze() steckten)
    fine  : feinere Kerzen (z. B. H4, inkl. laufender Kerze) für genaue
            Extrem- und Retracement-Punkte. Ohne fine werden Daily-Kerzen benutzt.
    """
    last = res.last_break
    if last is None:
        return None
    bull = last.direction == BULLISH

    # 1) Geschützter Swing: Extrem zwischen gebrochenem Swing und Bruch-Kerze
    seg = daily.iloc[last.swing.pos:last.pos + 1]
    if bull:
        protected, p_time = float(seg["Low"].min()), seg["Low"].idxmin()
    else:
        protected, p_time = float(seg["High"].max()), seg["High"].idxmax()

    # 2) Ab dem Bruch-Tag: Extrem des Beins und Retracement danach
    if fine is not None and not fine.empty and "start" in daily.columns:
        after = fine[fine.index >= daily.iloc[last.pos]["start"]]
    else:
        after = daily.iloc[last.pos:]
    if after.empty:
        after = daily.iloc[last.pos:]

    if bull:
        extreme, e_time = float(after["High"].max()), after["High"].idxmax()
        later = after[after.index > e_time]
        retrace = float(later["Low"].min()) if not later.empty else None
    else:
        extreme, e_time = float(after["Low"].min()), after["Low"].idxmin()
        later = after[after.index > e_time]
        retrace = float(later["High"].max()) if not later.empty else None

    # 3) Wurde der geschützte Swing per Schlusskurs verletzt?
    closes_after = daily["Close"].iloc[last.pos + 1:]
    invalid = bool((closes_after < protected).any() if bull
                   else (closes_after > protected).any())

    return DailyLeg(last.direction, protected, p_time, extreme, e_time,
                    retrace, invalid)


# ---------------------------------------------------------------------------
# 5) HTF-Trend: Daily entscheidet, H4 zeigt die Phase
# ---------------------------------------------------------------------------
# Mögliche H4-Phasen
H4_MIT_DAILY = "H4 läuft mit Daily"
H4_RETRACE = "H4-Retracement"
H4_RETRACE_ENDE = "H4-Retracement beendet"
H4_UNKLAR = "H4 unklar"


@dataclass
class HTFResult:
    trend: str                      # BULLISH / BEARISH / UNKLAR (= Daily-Richtung)
    h4_phase: str                   # eine der H4_...-Konstanten
    leg: DailyLeg | None
    zone: str | None                # "Premium" / "Discount" (aktueller Preis)
    reasons_pro: list[str] = field(default_factory=list)
    reasons_contra: list[str] = field(default_factory=list)
    info: list[str] = field(default_factory=list)


def htf_trend(daily_res: TrendResult, daily: pd.DataFrame,
              h4_res: TrendResult | None, last_price: float,
              fine: pd.DataFrame | None = None,
              weekly_res: TrendResult | None = None,
              h4_candles: pd.DataFrame | None = None) -> HTFResult:
    """
    HTF-Trend nach dem Prinzip "Daily gibt die Richtung vor, H4 zeigt,
    wo wir im Daily-Bein stehen":

      - Der Daily-Trend IST die Handelsrichtung.
        Daily unklar oder geschützter Swing verletzt -> UNKLAR (kein Trade).
      - H4 in Daily-Richtung   -> Bestätigung.
      - H4 GEGEN Daily-Richtung -> kein Widerspruch, sondern ein Retracement
        (Rücklauf) innerhalb des Daily-Beins – solange der geschützte Daily-
        Swing hält. Ideal: Retracement läuft in den Daily-Discount (bullish)
        bzw. Daily-Premium (bearish).
      - H4-MSS zurück in Daily-Richtung nach einem Retracement
        -> "Retracement beendet": Daily und H4 laufen wieder zusammen.
      - Weekly wird nur als Information angezeigt.
    """
    leg = daily_leg(daily, daily_res, fine) if daily_res.trend != UNKLAR else None
    out = HTFResult(UNKLAR, H4_UNKLAR, leg, None)

    if weekly_res is not None:
        out.info.append(f"Weekly (nur Info): {weekly_res.trend}")

    # --- Daily ----------------------------------------------------------------
    if daily_res.trend == UNKLAR or leg is None:
        out.reasons_contra.append("Daily: kein klarer Trend -> kein Trade")
        return out
    d = daily_res.trend
    richtung = "nach oben" if d == BULLISH else "nach unten"
    last = daily_res.last_break
    out.reasons_pro.append(f"Daily: letzter Bruch = {last.kind} {richtung}")
    if last.kind == "MSS":
        out.reasons_contra.append("Daily: Trendwechsel frisch (MSS), noch kein BOS")

    gesch = "Protected Low" if d == BULLISH else "Protected High"
    if leg.invalidated:
        out.reasons_contra.append(f"Daily: {gesch} per Schlusskurs verletzt "
                                  "-> Struktur nicht mehr sauber, kein Trade")
        return out
    out.reasons_pro.append(f"Daily: {gesch} hält")
    out.trend = d

    out.zone = leg.zone(last_price)
    gute_zone = "Discount" if d == BULLISH else "Premium"
    if out.zone == gute_zone:
        out.reasons_pro.append(f"Preis im Daily-{out.zone} (richtiger Bereich für {d})")
    else:
        out.reasons_contra.append(f"Preis im Daily-{out.zone} – für {d} lieber "
                                  f"auf Rücklauf in den {gute_zone} warten")

    # --- H4 -------------------------------------------------------------------
    if h4_res is None or h4_res.trend == UNKLAR:
        out.h4_phase = H4_UNKLAR
        out.info.append("H4: kein klarer Strukturbruch")
        return out

    depth = leg.retrace_depth()
    tiefe = f"{depth:.0%}" if depth is not None else "–"
    h4_last = h4_res.last_break

    if h4_res.trend == d:
        if h4_last.kind == "MSS":
            out.h4_phase = H4_RETRACE_ENDE
            # Tiefe des beendeten Retracements: extremster Gegenpreis zwischen
            # dem H4-Bruch gegen den Daily und dem H4-MSS zurück.
            if h4_candles is not None and len(h4_res.breaks) >= 2:
                seg = h4_candles.iloc[h4_res.breaks[-2].pos:h4_last.pos + 1]
                peak = float(seg["High"].max() if d == BEARISH else seg["Low"].min())
                span = leg.high - leg.low
                depth = abs(leg.extreme - peak) / span if span else None
                tiefe = f"{depth:.0%}" if depth is not None else "–"
            out.reasons_pro.append(f"H4: MSS zurück in Daily-Richtung – Retracement "
                                   f"beendet (reichte bis {tiefe} des Daily-Beins)")
            if depth is not None and depth < 0.5:
                out.reasons_contra.append(f"H4: Retracement blieb im "
                                          f"{'Premium' if d == BULLISH else 'Discount'} "
                                          "(unter 50 %) – Daily-Bereich nicht erreicht")
        else:
            out.h4_phase = H4_MIT_DAILY
            out.reasons_pro.append("H4: läuft mit dem Daily (BOS in Daily-Richtung)")
    else:
        out.h4_phase = H4_RETRACE
        out.info.append(f"H4: {h4_last.kind} gegen Daily = Retracement im Daily-Bein, "
                        f"kein Trendwechsel, solange {gesch} hält")
        if out.zone == gute_zone:
            out.reasons_pro.append(f"H4-Retracement hat den Daily-{gute_zone} "
                                   f"erreicht (Tiefe {tiefe}) – auf H4/M15-MSS "
                                   "zurück in Daily-Richtung warten")
        else:
            out.reasons_contra.append(f"H4-Retracement läuft noch, Daily-{gute_zone} "
                                      f"noch nicht erreicht (Tiefe {tiefe}) – abwarten")
    return out
