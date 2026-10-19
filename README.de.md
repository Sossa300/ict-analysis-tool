# ICT Top-Down-Analyse-Tool

Entscheidungshilfe für ICT-Top-Down-Analysen (Daily → H4 → M15). Kein Signalgeber – die
Entscheidung triffst du.

## Inhalt
1. [Schnellstart](#1-schnellstart)
2. [Die Web-Oberfläche](#2-die-web-oberfläche)
3. [Die Werkzeuge (Dateien)](#3-die-werkzeuge-dateien)
   - [Daten & Level](#daten--level)
   - [Analyse: Struktur, Bias, POIs, Sessions](#analyse-struktur-bias-pois-sessions)
   - [Signale & Ausgabe](#signale--ausgabe)
   - [Trading-Hilfen](#trading-hilfen)
   - [Tests, Backtests, Protokolle](#tests-backtests-protokolle)
4. [Wo liegen meine Ergebnisse?](#4-wo-liegen-meine-ergebnisse)
5. [Die festen Regeln](#5-die-festen-regeln)
6. [Zeiten: Tagesgrenzen & Sessions](#6-zeiten-tagesgrenzen--sessions)

---

## 1. Schnellstart

In einem Terminal im Projektordner:

```
pip install -r requirements.txt
streamlit run app.py                    (Web-Oberfläche, empfohlen)
python main.py --symbol US100           (Textausgabe im Terminal)
python main.py --symbol US100 --chart   (+ Charts als HTML in charts/)
python journal.py                       (Forward-Test aktualisieren + Bericht)
python -m pytest -v                     (alle Tests)
```

Weitere Optionen für `main.py`:
- `--modus beide | original | retracement` – Grundlage für POIs/Sweeps/Checkliste
- `--asof "2026-10-14 09:30"` – Zeitreise (NY-Zeit): Was hätte das Tool da gesagt?
- `--csv datei.csv --csv-tz Europe/Berlin` – eigene Daten statt yfinance
- `--hell` – Charts im hellen Design

## 2. Die Web-Oberfläche

`streamlit run app.py` – in der Seitenleiste steht ein **Inhaltsverzeichnis** mit Links zu jedem Bereich:

| Bereich | Was du dort siehst |
|---|---|
| **Signale** | Signal A (Original Daily Bias) und Signal B (H4-Retracement), umschaltbar per Button |
| **Charts Daily · H4 · M15** | Zonen, Sweep-Punkte ✓/✗, Premium/Discount, DOL, Sessions |
| **H1-Detailchart** | alle Session-/Tages-/Wochen-Highs/Lows als Linien ab Entstehung, FVGs/OBs als Rechtecke |
| **Checkliste** | vor dem Trade abhaken (Tool-Punkte automatisch, M15-Punkte selbst) |
| **Positionsgröße** | Lots bei 1 % Risiko, Stop-Abstand, CRV |
| **Forward-Test** | automatisches Protokoll um 15:30 Berlin + Auswertung |
| **Meine Backtests** | eigene Trades eintragen, Statistik (Trefferquote, Ø R, Profitfaktor), R-Kurve |
| **Komplette Analyse** | die ganze Textausgabe |

## 3. Die Werkzeuge (Dateien)

### Daten & Level
| Datei | Aufgabe |
|---|---|
| `config.py` | **Alle Einstellungen**: Instrumente, Tagesgrenzen, Sessions, Swing-Länge, Kerzen-MSS, H4-Führung, POI-Grenzwerte, Bias-Punkte, Positionsgröße |
| `data.py` | Daten laden (yfinance oder CSV), H4/Daily/Weekly in NY-Zeit bauen, Zeitreise ohne Blick in die Zukunft |
| `levels.py` | PDH, PDL, PWH, PWL (+ wann gebildet, schon genommen?) |

### Analyse: Struktur, Bias, POIs, Sessions
| Datei | Aufgabe |
|---|---|
| `structure.py` | Swings, BOS/MSS (nur per Kerzenkörper), Kerzen-MSS im Daily, Daily-Bein (Protected Low/High, Equilibrium), HTF-Trend = Daily + H4-Phase |
| `bias.py` | Daily Bias: Previous-Day-Logik, Premium/Discount, DOL, Konfidenz mit Gründen, NEUTRAL bei Widerspruch, H4-Führung bei unklarem Daily |
| `pois.py` | FVGs und Order Blocks mit Displacement und Mitigation; Stufe A (Daily), Stufe B (H4, 4 Bestätigungen) |
| `sessions.py` | Session Highs/Lows und Power of 3 mit Pre-Market-Fakeout |
| `sweeps.py` | Sweep-Punkte als Beobachtungsliste (gültig/ungültig) + LQS-Muster für die H4-Prüfung |

### Signale & Ausgabe
| Datei | Aufgabe |
|---|---|
| `signals.py` | Signal A (Original) und Signal B (H4-Retracement), Modus-Wechsel |
| `main.py` | Startpunkt im Terminal, Textausgabe in NY- und Berliner Zeit |
| `chart.py` | Plotly-Charts (Daily, H4, M15, H1-Detail) und R-Kurve deiner Backtests |
| `app.py` | Web-Oberfläche |

### Trading-Hilfen
| Datei | Aufgabe |
|---|---|
| `checklist.py` | Checkliste vor dem Trade |
| `risk.py` | Positionsgrößen-Rechner. **€ je Punkt beim US100 in `config.py` an deinen Broker anpassen!** |
| `trade_log.py` | Eigene Backtests dokumentieren, Ergebnis in R, Statistik |

### Tests, Backtests, Protokolle
| Datei | Aufgabe |
|---|---|
| `backtest.py` | Bias um 15:30 vs. Preisbewegung bis Tagesschluss, Kriterien einzeln geprüft |
| `bias_methods.py` / `methoden_backtest.py` | 27 Bias-Methoden aus dem Internet, 2-Jahres-Vergleich (Jahr 1 finden, Jahr 2 bestätigen) |
| `journal.py` | Forward-Test ab dem Start-Datum, mit Regel-Version |
| `tests/` | automatische Tests mit Beispieldaten (`python -m pytest -v`) |

## 4. Wo liegen meine Ergebnisse?

| Ordner / Datei | Inhalt |
|---|---|
| `meine_backtests/backtests.csv` | deine eingetragenen Backtest-Trades |
| `forward_test/journal.csv` | Forward-Test-Protokoll (Start-Datum in `forward_test/start.txt`) |
| `backtest_ergebnisse/` | automatische Backtests und das Methoden-Ranking |
| `charts/` | gespeicherte HTML-Charts |
| `beispiele/` | Beispiel-Analysen als Text |

Alle CSV-Dateien nutzen `;` und deutsches Komma – sie öffnen sich direkt in Excel.

## 5. Die festen Regeln

1. Trade-Richtung **nur in HTF-Richtung** (Daily gibt die Richtung vor; H4 gegen Daily = Retracement).
2. Sweeps **nur passend zum Bias**: bearish → nur Hochs, bullish → nur Tiefs.
3. Sweep-Punkte: PDH/PDL, PWH/PWL, Session Highs/Lows.
4. Ein BOS/MSS zählt **nur per Kerzenkörper** – ein Docht allein nie.
5. Widersprechen sich die Kriterien: **NEUTRAL – kein Trade**.

## 6. Zeiten: Tagesgrenzen & Sessions

- **Tageskerze** US100 (NQ=F): 18:00–17:00 NY · Forex: 17:00–17:00 NY
- **Sessions** (Berliner Zeit): Asia 00–06 · London 09–11 · Pre-Market 14:30–15:30 · NY AM 15:30–17:00 · NY PM 19–21 (meist irrelevant)
- Intern wird in NY-Zeit gerechnet. In den Wochen der Zeitumstellung beginnen die NY-Sessions 1 h früher (Berliner Zeit) – das Tool zeigt dann einen Hinweis.
