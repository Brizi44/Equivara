"""Equivara – Simulationsmodell (ohne GUI).

Modell inspiriert von STRATAGEM-1 (Meadows et al.), eigene Umsetzung.

- 5 Sektoren, 12 Zyklen à 5 Jahre = 60 Jahre, 200 Einwohner zu Beginn
- Kapitalstocks mit unterschiedlichen Lebensdauern
- Energieeffizienz senkt den Energiebedarf
- Energieproduktion hat abnehmende Grenzerträge
- Nahrung hängt von Landproduktivität, Kapital und Umwelt ab
- Güter hängen von Arbeitskraft, Güterkapital und Humankapital ab
- Geburtenrate hängt vom Güterkonsum + Humankapital ab
- Sterberate hängt vom Nahrungskonsum + Umwelt ab
- Importe wirken erst im nächsten Zyklus
- Schulden beeinflussen Importpreise und Zinssatz

Die Kennlinien aus dem Kurzhandbuch sind als lineare Interpolation hinterlegt.

Gegenüber der ursprünglichen Fassung (früher stratagem1_akkurater.py) umgesetzte
Modellkorrekturen sind im Code mit "KORREKTUR n" markiert:
 1. validate() prüft alles VOR jeder Mutation; abgelehnte Züge ändern nichts.
 2. Finanzlogik ohne Doppelbuchung der Zinsen, mit Devisenreserve.
 3. MFC/MGC vergleichen mit dem unmittelbar vorigen Zyklus.
 4. IMF-Rückzahlung wird von den verfügbaren Gütern abgezogen.
 5. Eingaberegeln + nicht blockierende Warnungen.
 6. suggest_inputs() liefert stets zulässige Eingaben.

Nur Standardbibliothek, keine tkinter-Abhängigkeit.
"""

from __future__ import annotations

import copy
import functools
import json
import math
import random
from dataclasses import dataclass

__all__ = [
    "INPUT_KEYS", "INPUT_LABELS", "INVEST_KEYS", "DEFAULT_INPUTS",
    "SCENARIOS", "EVENTS", "CURVE_INFO",
    "MINISTRIES", "MINISTRY_INPUT_KEYS", "ALL_INPUT_KEYS", "ALL_INPUT_LABELS", "DEFAULT_MARKET",
    "Issue", "EquivaraEngine", "clamp", "interp",
]


def clamp(value, low, high):
    return max(low, min(high, value))


def interp(x, points):
    """Lineare Interpolation einer Modell-Kennlinie."""
    if x <= points[0][0]:
        return points[0][1]
    if x >= points[-1][0]:
        return points[-1][1]
    for (x1, y1), (x2, y2) in zip(points, points[1:]):
        if x1 <= x <= x2:
            if x2 == x1:
                return y1
            f = (x - x1) / (x2 - x1)
            return y1 + f * (y2 - y1)
    return points[-1][1]


# =============================================================================
# Eingaben
# =============================================================================

INPUT_KEYS = [
    "food_domestic", "food_export", "goods_domestic", "goods_export", "goods_investment",
    "energy_food", "energy_goods", "energy_export", "energy_carryover",
    "inv_food", "inv_env", "inv_goods", "inv_human", "inv_energy_prod", "inv_energy_eff",
    "foreign_aid", "new_loans", "repayments",
    "import_energy_money", "import_food_money", "import_goods_money",
]

INPUT_LABELS = {
    "food_domestic": "Nahrung Bevölkerung",
    "food_export": "Nahrung Export",
    "goods_domestic": "Güter Bevölkerung",
    "goods_export": "Güter Export",
    "goods_investment": "Güter für Investitionen",
    "energy_food": "Energie → Nahrung",
    "energy_goods": "Energie → Güter",
    "energy_export": "Energie Export",
    "energy_carryover": "Energie Carry-over",
    "inv_food": "Investition Nahrungskapital",
    "inv_env": "Investition Umweltschutzkapital",
    "inv_goods": "Investition Güterkapital",
    "inv_human": "Investition Humankapital",
    "inv_energy_prod": "Investition Energieproduktion",
    "inv_energy_eff": "Investition Energieeffizienz",
    "foreign_aid": "Auslandshilfe",
    "new_loans": "Neue Kredite",
    "repayments": "Tilgung",
    "import_energy_money": "Importbudget Energie",
    "import_food_money": "Importbudget Nahrung",
    "import_goods_money": "Importbudget Güter",
}

INVEST_KEYS = ["inv_food", "inv_env", "inv_goods", "inv_human", "inv_energy_prod", "inv_energy_eff"]

IMPORT_KEYS = ["import_energy_money", "import_food_money", "import_goods_money"]

DEFAULT_INPUTS = {
    "food_domestic": 2000.0, "food_export": 1000.0,
    "goods_domestic": 2000.0, "goods_export": 0.0, "goods_investment": 1500.0,
    "energy_food": 8500.0, "energy_goods": 5000.0, "energy_export": 0.0, "energy_carryover": 600.0,
    "inv_food": 300.0, "inv_env": 200.0, "inv_goods": 300.0, "inv_human": 200.0,
    "inv_energy_prod": 300.0, "inv_energy_eff": 200.0,
    "foreign_aid": 0.0, "new_loans": 0.0, "repayments": 0.0,
    "import_energy_money": 0.0, "import_food_money": 0.0, "import_goods_money": 0.0,
}

TOL = 1e-7


# =============================================================================
# Ministerien (optional, Standard: alle aus)
# =============================================================================
#
# Die vier Ministerien sind EIGENE Erweiterungen von Equivara (nicht Teil des
# STRATAGEM-1-Kurzhandbuchs). Ihre Kennlinien sind plausible Näherungen, die so
# gewählt sind, dass ein "kleiner Startbestand" ungefähr neutral wirkt und
# volle Investitionen spürbar, aber nicht spielentscheidend helfen.
# Sind alle Ministerien aus, verhält sich das Modell bitgenau wie zuvor
# (alle neuen Wirkungen sind dann nicht nur 1.0, sondern werden gar nicht
# erst angewendet).

MINISTRIES = {
    "gesundheit": {
        "name": "Gesundheit",
        "description": "Kliniken und Gesundheitsdienste senken die Sterberate und mildern Epidemien.",
        "input_key": "inv_health", "capital_attr": "cap_health",
        "lifetime": 30, "delay_cycles": 1, "color_hint": "red",
    },
    "bildung": {
        "name": "Bildung",
        "description": "Schulen und Universitäten steigern verzögert die Güterproduktivität, senken die "
                       "Geburtenrate leicht und verstärken die Wirkung von Energieeffizienz.",
        "input_key": "inv_education", "capital_attr": "cap_education",
        "lifetime": 45, "delay_cycles": 2, "color_hint": "purple",
    },
    "infrastruktur": {
        "name": "Infrastruktur",
        "description": "Straßen, Netze und Logistik senken den Energiebedarf der Produktion; zu wenig "
                       "Infrastruktur bremst die Produktion, genug beschleunigt sie.",
        "input_key": "inv_infrastructure", "capital_attr": "cap_infrastructure",
        "lifetime": 40, "delay_cycles": 2, "color_hint": "orange",
    },
    "verteidigung": {
        "name": "Verteidigung",
        "description": "Sicherheit dämpft die Folgen negativer Ereignisse, bindet aber Arbeitskräfte.",
        "input_key": "inv_defense", "capital_attr": "cap_defense",
        "lifetime": 20, "delay_cycles": 1, "color_hint": "blue",
    },
}

MINISTRY_INPUT_KEYS = [m["input_key"] for m in MINISTRIES.values()]
ALL_INPUT_KEYS = INPUT_KEYS + MINISTRY_INPUT_KEYS
_MINISTRY_BY_INPUT = {m["input_key"]: key for key, m in MINISTRIES.items()}

MINISTRY_INPUT_LABELS = {
    "inv_health": "Investition Gesundheit",
    "inv_education": "Investition Bildung",
    "inv_infrastructure": "Investition Infrastruktur",
    "inv_defense": "Investition Verteidigung",
}


class _InputLabels(dict):
    """INPUT_LABELS: enthält per Zugriff ([], get, in) auch die Ministeriums-Schlüssel.

    Beim Iterieren (keys/items/set(...)) erscheinen weiterhin nur die 21
    Grundschlüssel – bestehender Code, der über INPUT_LABELS iteriert, bleibt
    unverändert. Vollständige Iteration: ALL_INPUT_LABELS.
    """

    def __missing__(self, key):
        return MINISTRY_INPUT_LABELS[key]

    def get(self, key, default=None):
        if dict.__contains__(self, key):
            return dict.__getitem__(self, key)
        return MINISTRY_INPUT_LABELS.get(key, default)

    def __contains__(self, key):
        return dict.__contains__(self, key) or key in MINISTRY_INPUT_LABELS


INPUT_LABELS = _InputLabels(INPUT_LABELS)
ALL_INPUT_LABELS = dict(INPUT_LABELS, **MINISTRY_INPUT_LABELS)

# Vorschlagswerte für Ministeriums-Investitionen (suggest_inputs ohne Vorgabe)
MINISTRY_DEFAULT_INPUTS = {k: 100.0 for k in MINISTRY_INPUT_KEYS}

# Startbestände bei aktivem Ministerium (Szenario "standard", 200 Einwohner).
# Gesundheit/Bildung/Verteidigung skalieren mit der Bevölkerung, Infrastruktur
# mit dem Produktionskapital (Nahrung + Güter): Verhältnis 0.3 = neutral.
MINISTRY_START = {"cap_health": 100.0, "cap_education": 100.0, "cap_defense": 50.0}
MINISTRY_INFRA_START_RATIO = 0.30
# Szenario-Faktor auf die Startbestände (verschuldete Länder starten ärmer).
MINISTRY_SCENARIO_FACTOR = {"standard": 1.0, "verschuldet": 0.7, "energiearm": 0.9,
                            "umweltkrise": 0.9, "bevoelkerungsdruck": 0.8}

DEFAULT_MARKET = {"export_price": {"food": 1.0, "goods": 1.0, "energy": 1.0},
                  "import_price": {"food": 1.1, "goods": 1.1, "energy": 1.0}}

class _Requirements(dict):
    """Ergebnis von requirements(): req["market"] / req.get("market") / "market" in req
    liefern die Marktpreise, beim Iterieren erscheinen weiterhin nur die bisherigen
    Schlüssel (Rückwärtskompatibilität)."""

    def __init__(self, data, **extra):
        super().__init__(data)
        self.extra = extra

    def __missing__(self, key):
        return self.extra[key]

    def get(self, key, default=None):
        if dict.__contains__(self, key):
            return dict.__getitem__(self, key)
        return self.extra.get(key, default)

    def __contains__(self, key):
        return dict.__contains__(self, key) or key in self.extra


_KEEP = object()   # Sentinel für reset(goal_cycles=...): bisherigen Wert behalten


# =============================================================================
# Szenarien und Ereignisse
# =============================================================================

SCENARIOS = {
    "standard": {
        "name": "Standard",
        "description": "Der klassische Startzustand: 200 Einwohner, moderate Schulden "
                       "und ausgeglichene Kapitalstöcke.",
        "overrides": {},
    },
    "verschuldet": {
        "name": "Verschuldet",
        "description": "Das Land startet mit hohen Auslandsschulden. Hohe Zinsen und teurere Importe "
                       "verlangen konsequenten Export und Tilgung.",
        "overrides": {
            "debt": 1600.0,
            "avg_exports_history": [1200.0, 1200.0, 1200.0],
        },
    },
    "energiearm": {
        "name": "Energiearm",
        "description": "Kaum Kraftwerke und geringe Energiereserven: Ohne Investitionen in Energieproduktion "
                       "oder Effizienz bleibt die Wirtschaft unter ihren Möglichkeiten.",
        "overrides": {
            "cap_energy_prod": 600.0,
            "energy_available": 10800.0,
            "last_energy_production": 9000.0,
            "cap_energy_eff": 60.0,
        },
    },
    "umweltkrise": {
        "name": "Umweltkrise",
        "description": "Die Umwelt ist stark geschädigt und die Ernten fallen geringer aus. Umweltschutz "
                       "zahlt sich langfristig aus, kostet aber zunächst Güter.",
        "overrides": {
            "environment": 0.50,
            "food_available": 3000.0,
            "last_food_production": 3000.0,
            "cap_env": 100.0,
        },
    },
    "bevoelkerungsdruck": {
        "name": "Bevölkerungsdruck",
        "description": "Eine größere, schnell wachsende Bevölkerung trifft auf knappe Güter. Nahrung und "
                       "Humankapital entscheiden über ein stabiles Wachstum.",
        "overrides": {
            "population": 250.0,
            "goods_pc": 1.7,
            "last_goods_pc": 1.7,
            "goods_pc_history": [1.7, 1.7, 1.7],
            "food_available": 3500.0,
            "cap_food": 860.0,
            "cap_human": 400.0,
        },
    },
}

# Ereignisse: höchstens eines je Zyklus. Wirkung siehe _simulate/_finance.
EVENTS = [
    {"key": "duerre", "name": "Dürre", "probability": 0.08,
     "description": "Eine Dürre senkt die Nahrungsproduktion dieses Zyklus um 25 %."},
    {"key": "gute_ernte", "name": "Gute Ernte", "probability": 0.08,
     "description": "Ideales Wetter steigert die Nahrungsproduktion dieses Zyklus um 15 %."},
    {"key": "oelpreisschock", "name": "Ölpreisschock", "probability": 0.06,
     "description": "Der Weltmarktpreis für Energie verdoppelt sich: Energieimporte kosten das Doppelte."},
    {"key": "rohstoffboom", "name": "Rohstoffboom", "probability": 0.06,
     "description": "Hohe Weltmarktpreise: Alle Exporterlöse dieses Zyklus steigen um 30 %."},
    {"key": "epidemie", "name": "Epidemie", "probability": 0.05,
     "description": "Eine Epidemie erhöht die Sterberate dieses Zyklus um 30 %."},
    {"key": "zinsschock", "name": "Zinsschock", "probability": 0.06,
     "description": "Die Weltmarktzinsen steigen: Der Zinssatz liegt diesen Zyklus 5 Prozentpunkte höher."},
]

_EVENTS_BY_KEY = {e["key"]: e for e in EVENTS}


@functools.lru_cache(maxsize=4096)
def _event_key_for(seed, runde):
    """Deterministisches Ereignis (Schlüssel oder None) für Seed und Zyklus."""
    roll = random.Random(f"{seed}-{runde}").random()
    acc = 0.0
    for ev in EVENTS:
        acc += ev["probability"]
        if roll < acc:
            return ev["key"]
    return None


CURVE_INFO = [
    # (Attribut, Abb., Titel, X-Beschriftung, Y-Beschriftung)
    ("BIRTH_RATE_CURVE", 1, "Normale Geburtenrate", "Güter pro Kopf (Ø 3 Zyklen)", "Geburten pro 1000/Jahr"),
    ("BIRTH_SERVICE_MULT_CURVE", 2, "Geburtenraten-Multiplikator", "Humankapital pro Kopf", "Multiplikator"),
    ("DEATH_RATE_CURVE", 3, "Normale Sterberate", "Nahrung pro Kopf", "Sterbefälle pro 1000/Jahr"),
    ("DEATH_ENV_MULT_CURVE", 4, "Sterberaten-Multiplikator", "Umweltqualität", "Multiplikator"),
    ("ENERGY_PRODUCTION_LOW_CURVE", 5, "Energieproduktion", "Energieproduktionskapital (Tsd.)",
     "Energie (Tsd. EW)"),
    ("ENERGY_EFFICIENCY_CURVE", 6, "Energieverbrauch", "Effizienzkapital / Produktionskapital",
     "Verbrauchsmultiplikator"),
    ("FOOD_CONSUMPTION_CHANGE_CURVE", 7, "Nahrung: Konsumänderung (MFC)", "Konsum / Vorzyklus",
     "Produktionsmultiplikator"),
    ("FOOD_CAPITAL_CURVE", 8, "Landproduktivität", "aktives Nahrungskapital / Fläche", "Multiplikator"),
    ("ENV_DEGRADATION_CURVE", 9, "Umweltdegradation", "Umweltbelastung (/ 20 000)", "% pro Jahr"),
    ("ENV_REGENERATION_CURVE", 10, "Umweltregeneration", "Umweltqualität", "Prozentpunkte pro Jahr"),
    ("GOODS_CONSUMPTION_CHANGE_CURVE", 11, "Güter: Konsumänderung (MGC)", "Konsum / Vorzyklus",
     "Produktionsmultiplikator"),
    ("GOODS_CAPITAL_CURVE", 12, "Arbeitsproduktivität", "aktives Güterkapital / Arbeitskraft", "Multiplikator"),
    ("HUMAN_SERVICE_CURVE", 13, "Humankapital-Wirkung", "Humankapital pro Kopf", "Multiplikator"),
    ("IMPORT_PRICE_MULT_CURVE", 14, "Importpreise", "Schulden / Ø Exporte", "Preismultiplikator"),
    ("INTEREST_RATE_CURVE", 15, "Zinssatz", "Schulden / Ø Exporte", "% pro Jahr"),
    # Ministerien (eigene Näherungen; nur in curve_positions(), wenn das Ministerium aktiv ist)
    ("HEALTH_DEATH_MULT_CURVE", 16, "Gesundheit: Sterberate", "Gesundheitskapital pro Kopf",
     "Sterberaten-Multiplikator"),
    ("EDUCATION_PRODUCTIVITY_CURVE", 17, "Bildung: Produktivität", "Bildungskapital pro Kopf",
     "Güterproduktivitäts-Multiplikator"),
    ("INFRA_ENERGY_CURVE", 18, "Infrastruktur: Energiebedarf", "Infrastruktur / Produktionskapital",
     "Energiebedarfs-Multiplikator"),
    ("INFRA_PRODUCTION_CURVE", 19, "Infrastruktur: Logistik", "Infrastruktur / Produktionskapital",
     "Produktions-Multiplikator"),
    ("DEFENSE_SECURITY_CURVE", 20, "Verteidigung: Sicherheit", "Verteidigungskapital pro Kopf",
     "Sicherheit (0–1)"),
]

# Kennlinie -> Ministerium (nur anzeigen, wenn aktiv)
_CURVE_MINISTRY = {"HEALTH_DEATH_MULT_CURVE": "gesundheit", "EDUCATION_PRODUCTIVITY_CURVE": "bildung",
                   "INFRA_ENERGY_CURVE": "infrastruktur", "INFRA_PRODUCTION_CURVE": "infrastruktur",
                   "DEFENSE_SECURITY_CURVE": "verteidigung"}

# Investitionsmixe des Beraters: Gewichte für
# (Nahrung, Umwelt, Güter, Human, Energieproduktion, Energieeffizienz)
_ADVISOR_MIXES = {
    "ausgewogen": (3, 2, 3, 2, 3, 2),
    "Nahrung": (6, 1, 2, 1, 2, 1),
    "Güter": (2, 1, 6, 2, 2, 1),
    "Humankapital": (2, 1, 2, 5, 1, 1),
    "Energie": (2, 1, 2, 1, 5, 2),
    "Umwelt": (2, 5, 2, 1, 1, 1),
    "Effizienz": (3, 1, 3, 1, 1, 4),
    "Nahrung+Güter": (5, 1, 5, 1, 2, 1),
    "Nahrung+Energie": (5, 1, 2, 1, 4, 1),
    "Nahrung+Umwelt": (5, 3, 2, 1, 1, 1),
}


@dataclass
class Issue:
    field: str | None   # Eingabeschlüssel oder None (global)
    message: str        # deutsch, mit Anzeigenamen
    severity: str       # "error" | "warning"


def _parse_number(value):
    """Wandelt einen Eingabewert in float um; None bei ungültigem Wert."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        v = float(value)
    else:
        s = str(value).strip().replace("'", "").replace(" ", "").replace(",", ".")
        if s == "":
            return None
        try:
            v = float(s)
        except ValueError:
            return None
    if math.isnan(v) or math.isinf(v):
        return None
    return v


def _coerce(inputs):
    """Liefert (werte, ungültige_schlüssel). Fehlende/ungültige Werte = 0.

    Ministeriums-Schlüssel dürfen fehlen (oder leer sein) und gelten dann als 0;
    nur ein vorhandener, ungültiger Wert ist ein Fehler.
    """
    inputs = inputs or {}
    is_dict = isinstance(inputs, dict)
    values, bad = {}, []
    for k in INPUT_KEYS:
        v = _parse_number(inputs.get(k)) if is_dict else None
        if v is None:
            bad.append(k)
            v = 0.0
        values[k] = v
    for k in MINISTRY_INPUT_KEYS:
        raw = inputs.get(k) if is_dict else None
        if raw is None or (isinstance(raw, str) and raw.strip() == ""):
            values[k] = 0.0
            continue
        v = _parse_number(raw)
        if v is None:
            bad.append(k)
            v = 0.0
        values[k] = v
    return values, bad


def _floor10(x):
    """Abwärts auf ein Vielfaches von 10 runden (nie negativ)."""
    if x <= 0:
        return 0.0
    return float(math.floor(x / 10.0 + 1e-9) * 10)


def _fmt(x):
    return f"{x:,.0f}".replace(",", "'")


# =============================================================================
# Engine
# =============================================================================

class EquivaraEngine:
    CYCLE_YEARS = 5
    TOTAL_CYCLES = 12

    LIFETIME_ENERGY_PROD = 25
    LIFETIME_ENERGY_EFF = 25
    LIFETIME_FOOD = 25
    LIFETIME_GOODS = 25
    LIFETIME_HUMAN = 45
    LIFETIME_ENV = 30

    ENERGY_PER_FOOD_CAP = 12.5
    ENERGY_PER_GOODS_CAP = 20.0
    ENERGY_POPULATION_PER_GOODS = 0.2

    LAND_AREA = 1000.0
    LAND_PRODUCTIVITY_NORMAL = 1.25
    GOODS_PRODUCTIVITY_NORMAL = 1.155

    INITIAL_OUTPUT = 3300.0 + 3000.0

    # Abb. 1: normale Geburtenrate [pro 1000/Jahr]
    BIRTH_RATE_CURVE = [(0.0, 30.0), (3.0, 27.0), (6.0, 23.0), (9.0, 17.0), (12.0, 12.0), (15.0, 10.0)]
    # Abb. 2: Geburtenraten-Multiplikator aus Humankapital/Kopf
    BIRTH_SERVICE_MULT_CURVE = [(0.0, 1.00), (2.5, 1.50), (4.0, 1.45), (8.0, 1.35), (12.0, 1.20),
                                (16.0, 1.00), (20.0, 1.00)]
    # Abb. 3: normale Sterberate [pro 1000/Jahr]
    DEATH_RATE_CURVE = [(0.0, 60.0), (1.0, 30.0), (2.0, 20.0), (3.0, 15.0), (4.0, 12.0), (5.0, 10.0)]
    # Abb. 4: Sterberaten-Multiplikator aus Umweltqualität
    DEATH_ENV_MULT_CURVE = [(0.0, 1.75), (0.20, 1.50), (0.40, 1.30), (0.60, 1.10), (0.75, 1.00), (1.00, 1.00)]
    # Abb. 5: Energieproduktion (Tsd. EW) aus Energieproduktionskapital (Tsd.)
    ENERGY_PRODUCTION_LOW_CURVE = [(0.0, 0.0), (0.8, 12.0), (1.0, 15.0), (2.0, 20.0), (4.0, 25.0),
                                   (6.0, 29.0), (8.0, 33.0), (10.0, 35.0)]
    # Abb. 6: Energieverbrauchsmultiplikator aus Effizienzkapital / Produktionskapital
    ENERGY_EFFICIENCY_CURVE = [(0.0, 1.00), (0.10, 0.78), (0.20, 0.70), (0.40, 0.50), (0.60, 0.42),
                               (0.80, 0.35), (1.00, 0.30)]
    # Abb. 7: Nahrungsproduktions-Multiplikator aus Konsumänderung
    FOOD_CONSUMPTION_CHANGE_CURVE = [(0.0, 0.40), (0.40, 0.64), (0.80, 0.88), (1.00, 1.00), (2.00, 1.00)]
    # Abb. 8: Landproduktivitäts-Multiplikator
    FOOD_CAPITAL_CURVE = [(0.0, 0.0), (0.8, 0.8), (1.0, 1.0), (2.0, 2.0), (3.0, 3.0), (4.0, 3.8),
                          (6.0, 4.5), (10.0, 5.0)]
    # Abb. 9: jährliche Umweltdegradation in Prozent
    ENV_DEGRADATION_CURVE = [(0.0, 0.0), (0.10, 2.0), (0.20, 4.0), (0.40, 7.0), (0.60, 9.0),
                             (0.80, 9.7), (1.00, 10.0)]
    # Abb. 10: jährliche Regeneration in Prozentpunkten
    ENV_REGENERATION_CURVE = [(0.0, 0.0), (0.10, 0.2), (0.20, 1.8), (0.40, 4.2), (0.50, 5.0),
                              (0.60, 4.5), (0.80, 2.0), (0.90, 0.3), (1.00, 0.0)]
    # Abb. 11: Güterproduktions-Multiplikator aus Konsumänderung
    GOODS_CONSUMPTION_CHANGE_CURVE = [(0.0, 0.40), (0.40, 0.64), (0.80, 0.88), (1.00, 1.00), (2.00, 1.00)]
    # Abb. 12: Arbeitsproduktivitäts-Multiplikator aus Güterkapital / Arbeitskraft
    GOODS_CAPITAL_CURVE = [(0.0, 0.0), (4.0, 5.0), (8.0, 9.5), (16.0, 13.5), (24.0, 16.0),
                           (32.0, 18.0), (40.0, 20.0)]
    # Abb. 13: Güterproduktions-Multiplikator aus Humankapital/Kopf
    HUMAN_SERVICE_CURVE = [(0.0, 1.0), (2.0, 2.0), (4.0, 3.0), (8.0, 3.8), (12.0, 4.3),
                           (16.0, 4.65), (20.0, 5.0)]
    # Abb. 14: Multiplikator der Importpreise
    IMPORT_PRICE_MULT_CURVE = [(0.0, 1.00), (2.0, 1.00), (3.0, 1.33), (4.0, 1.67), (5.0, 2.00)]
    # Abb. 15: Zinssatz pro Jahr in Prozent
    INTEREST_RATE_CURVE = [(0.0, 10.0), (1.0, 10.0), (2.0, 15.0), (3.0, 16.8), (4.0, 18.4), (5.0, 20.0)]

    # --- Ministerien: eigene Näherungen (nicht aus dem Kurzhandbuch) ---------
    # Abb. 16: Sterberaten-Multiplikator aus Gesundheitskapital pro Kopf.
    #   Startbestand 0.5/Kopf -> 0.95; sättigt bei ~4/Kopf auf 0.70.
    HEALTH_DEATH_MULT_CURVE = [(0.0, 1.00), (0.5, 0.95), (1.0, 0.88), (2.0, 0.79), (3.0, 0.73),
                               (4.0, 0.70), (6.0, 0.70)]
    # Abb. 17: Güterproduktivitäts-Multiplikator aus Bildungskapital pro Kopf
    #   (Bildungskapital wird erst nach 2 Zyklen wirksam). Sättigt bei 1.40.
    EDUCATION_PRODUCTIVITY_CURVE = [(0.0, 1.00), (0.5, 1.05), (1.0, 1.12), (2.0, 1.24), (3.0, 1.32),
                                    (4.0, 1.37), (6.0, 1.40)]
    # Abb. 18: Energiebedarfs-Multiplikator aus Infrastruktur / (Nahrungs- + Güterkapital).
    INFRA_ENERGY_CURVE = [(0.0, 1.00), (0.2, 0.97), (0.4, 0.92), (0.6, 0.86), (0.8, 0.82), (1.0, 0.80)]
    # Abb. 19: Logistik-Multiplikator der Produktion (gleiche X-Achse). 0.3 = neutral,
    #   zu wenig Infrastruktur -> bis 0.90, genug -> bis 1.10.
    INFRA_PRODUCTION_CURVE = [(0.0, 0.90), (0.15, 0.95), (0.3, 1.00), (0.5, 1.05), (0.8, 1.10), (1.0, 1.10)]
    # Abb. 20: Sicherheit 0..1 aus Verteidigungskapital pro Kopf.
    DEFENSE_SECURITY_CURVE = [(0.0, 0.0), (0.25, 0.30), (0.5, 0.55), (1.0, 0.80), (1.5, 0.92), (2.0, 1.00)]
    # Bildung senkt die Geburtenrate um bis zu 10 % (linear im Bildungseffekt)
    # und verstärkt die Einsparung durch Energieeffizienz um bis zu 25 %.
    EDUCATION_BIRTH_REDUCTION = 0.10
    EDUCATION_EFFICIENCY_BONUS = 0.25
    # Verteidigung bindet Arbeitskräfte: Anteil = 0.05 * Kapital pro Kopf, max. 10 %.
    DEFENSE_LABOR_PER_CAPITAL = 0.05
    DEFENSE_LABOR_MAX = 0.10

    def __init__(self, scenario: str = "standard", events_enabled: bool = False, seed: int | None = None,
                 ministries: dict | None = None, goal_cycles: int | None = 12):
        self._undo = []
        self.scenario = "standard"
        self.events_enabled = False
        self.seed = None
        self.ministries = {k: False for k in MINISTRIES}
        self.goal_cycles = 12
        self.reset(scenario=scenario, events_enabled=events_enabled, seed=seed, ministries=ministries,
                   goal_cycles=goal_cycles)

    # -------------------------------------------------------------------------
    # Zustand
    # -------------------------------------------------------------------------

    @staticmethod
    def _random_seed() -> int:
        return random.SystemRandom().randrange(1, 1_000_000_000)

    @staticmethod
    def _normalize_ministries(ministries) -> dict:
        out = {k: False for k in MINISTRIES}
        for k, val in dict(ministries or {}).items():
            if k not in MINISTRIES:
                raise ValueError(f"Unbekanntes Ministerium: {k!r}")
            out[k] = bool(val)
        return out

    @staticmethod
    def _normalize_goal(goal_cycles):
        if goal_cycles is None:
            return None
        g = int(goal_cycles)
        if g < 1:
            raise ValueError("Das Ziel muss mindestens 1 Zyklus betragen.")
        return g

    def reset(self, scenario: str | None = None, events_enabled: bool | None = None,
              seed: int | None = None, ministries: dict | None = None, goal_cycles=_KEEP) -> None:
        """Startzustand herstellen.

        None = bisherigen Wert behalten (bei goal_cycles: Argument weglassen;
        goal_cycles=None bedeutet "endlos"). Gibt es noch keinen Seed, wird ein
        zufälliger erzeugt und gespeichert.
        """
        if ministries is None:
            ministries = getattr(self, "ministries", None)
        ministries = self._normalize_ministries(ministries)
        if goal_cycles is _KEEP:
            goal_cycles = getattr(self, "goal_cycles", 12)
        goal_cycles = self._normalize_goal(goal_cycles)
        if scenario is None:
            scenario = getattr(self, "scenario", "standard") or "standard"
        if scenario not in SCENARIOS:
            raise ValueError(f"Unbekanntes Szenario: {scenario!r}")
        if events_enabled is None:
            events_enabled = bool(getattr(self, "events_enabled", False))
        if seed is None:
            seed = getattr(self, "seed", None)
            if seed is None:
                seed = self._random_seed()
        self.scenario = scenario
        self.events_enabled = bool(events_enabled)
        self.seed = int(seed)
        self._reset_state()
        self.ministries = ministries
        self.goal_cycles = goal_cycles
        for attr, value in SCENARIOS[scenario]["overrides"].items():
            setattr(self, attr, copy.deepcopy(value))
        self._init_ministry_capital()
        self.history = [self._initial_record()]

    def _init_ministry_capital(self) -> None:
        """Startbestände der Ministerien (0 wenn inaktiv), nach den Szenario-Overrides."""
        factor = MINISTRY_SCENARIO_FACTOR.get(self.scenario, 1.0)
        pop_factor = self.population / 200.0
        for key, m in MINISTRIES.items():
            attr = m["capital_attr"]
            if not self.ministries.get(key):
                value = 0.0
            elif attr == "cap_infrastructure":
                value = round(MINISTRY_INFRA_START_RATIO * (self.cap_food + self.cap_goods) * factor, 1)
            else:
                value = round(MINISTRY_START[attr] * pop_factor * factor, 1)
            setattr(self, attr, float(value))
            setattr(self, "under_" + attr[4:], [0.0] * m["delay_cycles"])

    # -------------------------------------------------------------------------
    # Ministerien / Ziel – öffentliche Hilfen
    # -------------------------------------------------------------------------

    def is_active(self, ministry: str) -> bool:
        return bool(self.ministries.get(ministry, False))

    def any_ministry(self) -> bool:
        return any(self.ministries.values())

    def active_ministries(self) -> list[str]:
        return [k for k in MINISTRIES if self.ministries.get(k)]

    def active_invest_keys(self) -> list[str]:
        return INVEST_KEYS + [MINISTRIES[k]["input_key"] for k in self.active_ministries()]

    def active_input_keys(self) -> list[str]:
        return INPUT_KEYS + [MINISTRIES[k]["input_key"] for k in self.active_ministries()]

    @property
    def cycles_played(self) -> int:
        return self.runde - 1

    @property
    def goal_years(self) -> int | None:
        return None if self.goal_cycles is None else self.goal_cycles * self.CYCLE_YEARS

    @property
    def goal_reached(self) -> bool:
        return self.goal_cycles is not None and self.cycles_played >= self.goal_cycles

    def continue_play(self) -> None:
        """Nach Erreichen des Ziels weiterspielen (ohne Obergrenze)."""
        self.continued = True
        self.game_over = False

    def _take_goal_snapshot(self) -> None:
        end = self.history[-1] if self.history else self._initial_record()
        sc = self.score()
        sc.pop("goal_score", None)
        snap = {"score": sc, "runde": end.get("runde"), "jahr_end": end.get("jahr_end"),
                "goal_cycles": self.goal_cycles, "goal_years": self.goal_years}
        for k in ("population", "food_pc", "goods_pc", "environment", "debt", "gdp", "gdp_pc"):
            snap[k] = end.get(k)
        self.goal_snapshot = snap

    def _reset_state(self) -> None:
        self.runde = 1
        self.population = 200.0
        self.food_pc = 2.0
        self.goods_pc = 2.0
        self.cap_human = 450.0
        self.cap_energy_prod = 800.0
        self.cap_energy_eff = 0.0
        self.cap_food = 800.0
        self.cap_goods = 300.0
        self.cap_env = 0.0

        self.under_energy_prod = [0.0, 0.0]
        self.under_energy_eff = [0.0]
        self.under_food = [0.0]
        self.under_goods = [0.0]
        self.under_human = [0.0]
        self.under_env = [0.0]

        # Food: 3300, Goods: 3500, Energy: 12000 + 1500 Import + 1000 Carry-over.
        self.food_available = 3300.0
        self.goods_available = 3500.0
        self.energy_available = 14500.0

        self.debt = 1000.0
        # IMF-Rückzahlung, ausgelöst in Zyklus t, fällig zu Beginn von t+1.
        self.imf_pending = 0.0
        # KORREKTUR 2: Devisenreserve (nicht ausgegebenes Importbudget).
        self.cash_reserve = 0.0

        self.environment = 0.69

        self.last_food_pc = 2.0
        self.last_goods_pc = 2.0
        self.goods_pc_history = [2.0, 2.0, 2.0]
        self.food_pc_history = [2.0]

        self.last_food_production = 3300.0
        self.last_goods_production = 3000.0
        self.last_energy_production = 12000.0
        self.last_food_cu = 1.0
        self.last_goods_cu = 1.0

        self.avg_exports_history = [1000.0, 1000.0, 1000.0]

        self.gdp_index = 100.0
        self.gdp_pc_index = 100.0

        self.total_interest_paid = 0.0
        self.total_exports = 0.0
        self.total_imports = 0.0

        self.game_over = False
        self.continued = False
        self.goal_snapshot = None
        self.last_inputs = None
        self._undo = []
        self.history = []

        # Weltmarktpreise (Markt-Hook, von equivara_world gesetzt)
        self.market = copy.deepcopy(DEFAULT_MARKET)

    def _state(self) -> dict:
        return copy.deepcopy({k: v for k, v in vars(self).items() if k != "_undo"})

    def _restore(self, state: dict) -> None:
        undo = getattr(self, "_undo", [])
        keep = {"scenario": getattr(self, "scenario", "standard"),
                "events_enabled": getattr(self, "events_enabled", False),
                "seed": getattr(self, "seed", None)}
        self.__dict__.clear()
        self.__dict__.update(copy.deepcopy(state))
        self._undo = undo
        # Ältere Spielstände ohne Szenario/Ereignis-Felder -> Standard.
        if getattr(self, "scenario", None) not in SCENARIOS:
            self.scenario = keep["scenario"] if keep["scenario"] in SCENARIOS else "standard"
        if "events_enabled" not in state:
            self.events_enabled = bool(keep["events_enabled"])
        if getattr(self, "seed", None) is None:
            self.seed = keep["seed"] if keep["seed"] is not None else self._random_seed()
        # Ältere Spielstände ohne Ministerien/Markt/Ziel -> alles aus, Standardmarkt, Ziel 12.
        try:
            self.ministries = self._normalize_ministries(state.get("ministries"))
        except (ValueError, TypeError, AttributeError):
            self.ministries = {k: False for k in MINISTRIES}
        for m in MINISTRIES.values():
            attr = m["capital_attr"]
            if not isinstance(state.get(attr), (int, float)):
                setattr(self, attr, 0.0)
            under = "under_" + attr[4:]
            if not isinstance(state.get(under), list) or len(state[under]) != m["delay_cycles"]:
                setattr(self, under, [0.0] * m["delay_cycles"])
        market = copy.deepcopy(DEFAULT_MARKET)
        if isinstance(state.get("market"), dict):
            for side in market:
                for good in market[side]:
                    try:
                        market[side][good] = float(state["market"][side][good])
                    except (KeyError, TypeError, ValueError):
                        pass
        self.market = market
        if "goal_cycles" not in state:
            self.goal_cycles = 12
        self.continued = bool(state.get("continued", False))
        snap = state.get("goal_snapshot")
        self.goal_snapshot = copy.deepcopy(snap) if isinstance(snap, dict) else None

    def _light_clone(self) -> "EquivaraEngine":
        """Schnelle Kopie ohne Verlauf/Undo (für Berater-Simulationen)."""
        clone = object.__new__(type(self))
        clone.__dict__ = copy.deepcopy({k: v for k, v in vars(self).items()
                                        if k not in ("_undo", "history", "last_inputs")})
        clone._undo = []
        clone.history = []
        clone.last_inputs = None
        return clone

    # -------------------------------------------------------------------------
    # Ereignisse
    # -------------------------------------------------------------------------

    def current_event(self) -> dict | None:
        """Ereignis des kommenden Zyklus (self.runde); vorab bekannt."""
        if not self.events_enabled or self.game_over:
            return None
        key = _event_key_for(self.seed, self.runde)
        return dict(_EVENTS_BY_KEY[key]) if key else None

    def _event_key(self):
        if not getattr(self, "events_enabled", False) or self.game_over:
            return None
        return _event_key_for(self.seed, self.runde)

    # -------------------------------------------------------------------------
    # Hilfsfunktionen des Modells
    # -------------------------------------------------------------------------

    @property
    def labor_force(self):
        if self.ministries.get("verteidigung"):
            return 0.25 * self.population * (1.0 - self.defense_labor_share())
        return 0.25 * self.population

    # --- Ministeriums-Wirkungen (inaktiv: neutral, werden dann nicht angewendet) ---

    def _per_capita(self, attr):
        return getattr(self, attr, 0.0) / max(1.0, self.population)

    def _infra_ratio(self):
        prod = self.cap_food + self.cap_goods
        return self.cap_infrastructure / prod if prod > 0 else 0.0

    def health_multiplier(self):
        """Sterberaten-Multiplikator (1.0 .. 0.7)."""
        if not self.ministries.get("gesundheit"):
            return 1.0
        return interp(self._per_capita("cap_health"), self.HEALTH_DEATH_MULT_CURVE)

    def education_multiplier(self):
        """Güterproduktivitäts-Multiplikator (1.0 .. 1.4)."""
        if not self.ministries.get("bildung"):
            return 1.0
        return interp(self._per_capita("cap_education"), self.EDUCATION_PRODUCTIVITY_CURVE)

    def _education_level(self):
        """Bildungseffekt normiert auf 0..1."""
        top = self.EDUCATION_PRODUCTIVITY_CURVE[-1][1] - 1.0
        return clamp((self.education_multiplier() - 1.0) / top, 0.0, 1.0)

    def education_birth_multiplier(self):
        return 1.0 - self.EDUCATION_BIRTH_REDUCTION * self._education_level()

    def infra_energy_multiplier(self):
        """Energiebedarfs-Multiplikator (1.0 .. 0.8)."""
        if not self.ministries.get("infrastruktur"):
            return 1.0
        return interp(self._infra_ratio(), self.INFRA_ENERGY_CURVE)

    def infra_production_multiplier(self):
        """Logistik-Multiplikator der Produktion (0.9 .. 1.1; inaktiv exakt 1.0)."""
        if not self.ministries.get("infrastruktur"):
            return 1.0
        return interp(self._infra_ratio(), self.INFRA_PRODUCTION_CURVE)

    def security(self):
        """Sicherheit 0..1 aus Verteidigungskapital pro Kopf."""
        if not self.ministries.get("verteidigung"):
            return 0.0
        return interp(self._per_capita("cap_defense"), self.DEFENSE_SECURITY_CURVE)

    def defense_labor_share(self):
        if not self.ministries.get("verteidigung"):
            return 0.0
        return min(self.DEFENSE_LABOR_MAX, self.DEFENSE_LABOR_PER_CAPITAL * self._per_capita("cap_defense"))

    def _event_damping(self, health=False):
        """Faktor auf die Stärke negativer Ereignisse (1.0 = ungedämpft).

        Verteidigung: * (1 - 0.5 * security). Gesundheit (nur Epidemie):
        * (1 - 0.5 * Gesundheitseffekt), Gesundheitseffekt = (1 - health_mult) / 0.3.
        """
        f = 1.0 - 0.5 * self.security()
        if health and self.ministries.get("gesundheit"):
            f *= 1.0 - 0.5 * clamp((1.0 - self.health_multiplier()) / 0.3, 0.0, 1.0)
        return f

    @property
    def human_services_pc(self):
        return self.cap_human / max(1.0, self.population)

    @property
    def active_food_capital(self):
        return self.cap_food * self.last_food_cu

    @property
    def active_goods_capital(self):
        return self.cap_goods * self.last_goods_cu

    def energy_efficiency_multiplier(self):
        production_capital = self.cap_food + self.cap_goods
        if production_capital <= 0:
            return 1.0
        m = interp(self.cap_energy_eff / production_capital, self.ENERGY_EFFICIENCY_CURVE)
        if self.ministries.get("bildung"):
            # Bildung verstärkt die Einsparung durch Effizienz (bis +25 %).
            saving = (1.0 - m) * (1.0 + self.EDUCATION_EFFICIENCY_BONUS * self._education_level())
            m = clamp(1.0 - saving, 0.2, 1.0)
        return m

    def normal_birth_rate(self, average_goods_pc):
        return interp(clamp(average_goods_pc, 0.0, 15.0), self.BIRTH_RATE_CURVE)

    def birth_service_multiplier(self):
        return interp(clamp(self.human_services_pc, 0.0, 20.0), self.BIRTH_SERVICE_MULT_CURVE)

    def normal_death_rate(self, food_pc):
        return interp(clamp(food_pc, 0.0, 5.0), self.DEATH_RATE_CURVE)

    def death_environment_multiplier(self):
        return interp(clamp(self.environment, 0.0, 1.0), self.DEATH_ENV_MULT_CURVE)

    def birth_rate(self):
        rate = self.normal_birth_rate(sum(self.goods_pc_history) / 3.0) * self.birth_service_multiplier()
        if self.ministries.get("bildung"):
            rate *= self.education_birth_multiplier()
        return rate

    def death_rate(self):
        rate = self.normal_death_rate(self.food_pc) * self.death_environment_multiplier()
        if self.ministries.get("gesundheit"):
            rate *= self.health_multiplier()
        return rate

    def energy_production(self):
        return interp(self.cap_energy_prod / 1000.0, self.ENERGY_PRODUCTION_LOW_CURVE) * 1000.0

    def expected_food_production(self, food_mfc=None, food_mfp=None):
        if food_mfc is None:
            food_mfc = 1.0
        if food_mfp is None:
            food_mfp = interp(self.active_food_capital / self.LAND_AREA, self.FOOD_CAPITAL_CURVE)
        value = 6250.0 * food_mfc * food_mfp * self.environment
        if self.ministries.get("infrastruktur"):
            value *= self.infra_production_multiplier()
        return value

    def expected_goods_production(self, goods_mgc=None, goods_mgp=None):
        if goods_mgc is None:
            goods_mgc = 1.0
        if goods_mgp is None:
            goods_mgp = interp(self.active_goods_capital / max(1.0, self.labor_force), self.GOODS_CAPITAL_CURVE)
        mhs = interp(self.human_services_pc, self.HUMAN_SERVICE_CURVE)
        value = 5.775 * self.labor_force * goods_mgc * goods_mgp * mhs
        if self.ministries.get("bildung"):
            value *= self.education_multiplier()
        if self.ministries.get("infrastruktur"):
            value *= self.infra_production_multiplier()
        return value

    def full_energy_requirements(self):
        eff = self.energy_efficiency_multiplier()
        if self.ministries.get("infrastruktur"):
            eff *= self.infra_energy_multiplier()
        food_req = self.cap_food * self.ENERGY_PER_FOOD_CAP * eff
        goods_req = self.cap_goods * self.ENERGY_PER_GOODS_CAP * eff
        pop_req = self.goods_pc * self.population * self.ENERGY_POPULATION_PER_GOODS
        return food_req, goods_req, pop_req

    def current_finance_conditions(self, debt=None):
        if debt is None:
            debt = self.debt
        avg_exports = sum(self.avg_exports_history) / len(self.avg_exports_history)
        ratio = debt / max(1.0, avg_exports)
        import_mult = interp(clamp(ratio, 0.0, 5.0), self.IMPORT_PRICE_MULT_CURVE)
        annual_interest = interp(clamp(ratio, 0.0, 5.0), self.INTEREST_RATE_CURVE)
        return avg_exports, ratio, import_mult, annual_interest

    def _price(self, side: str, good: str) -> float:
        """Weltmarktpreis aus self.market (Fallback: DEFAULT_MARKET)."""
        try:
            return float(self.market[side][good])
        except (AttributeError, KeyError, TypeError, ValueError):
            return DEFAULT_MARKET[side][good]

    def _finance(self, v: dict) -> dict:
        """KORREKTUR 2: Finanzrechnung des Zyklus, ohne Zustand zu verändern.

        cash_in = Reserve + Exporte + Hilfe + neue Kredite
        interest_paid = min(Zinsen, cash_in - Tilgung), Rest wird kapitalisiert
        Importbudget = cash_in - Tilgung - interest_paid
        """
        # IMF-Zahlung aus dem Vorzyklus wird zu Beginn dieses Zyklus fällig.
        imf_paid = min(self.imf_pending, self.debt)
        debt = self.debt - imf_paid
        avg_exports, ratio, import_mult, annual_interest = self.current_finance_conditions(debt)
        event = self._event_key()
        if event == "zinsschock":
            if self.ministries.get("verteidigung"):
                annual_interest += 5.0 * self._event_damping()
            else:
                annual_interest += 5.0
        interest_due = debt * annual_interest / 100.0 * self.CYCLE_YEARS
        max_new_loan = max(0.0, avg_exports - debt)
        # Markt-Hook: Exporterlös = Menge * Exportpreis (Default 1.0 -> bisheriges Verhalten).
        export_money = (v["energy_export"] * self._price("export_price", "energy")
                        + v["food_export"] * self._price("export_price", "food")
                        + v["goods_export"] * self._price("export_price", "goods"))
        if event == "rohstoffboom":
            export_money *= 1.3
        cash_in = self.cash_reserve + export_money + v["foreign_aid"] + v["new_loans"]
        repay = v["repayments"]
        after_repay = max(0.0, cash_in - repay)
        interest_paid = min(interest_due, after_repay)
        unpaid_interest = interest_due - interest_paid
        import_budget = max(0.0, cash_in - repay - interest_paid)
        imports = sum(v[k] for k in IMPORT_KEYS)
        return {
            "imf_paid": imf_paid,
            "debt_start": debt,
            "avg_exports": avg_exports,
            "debt_export_ratio": ratio,
            "import_mult": import_mult,
            "annual_interest": annual_interest,
            "interest_due": interest_due,
            "max_new_loan": max_new_loan,
            "export_money": export_money,
            "cash_in": cash_in,
            "interest_paid": interest_paid,
            "unpaid_interest": unpaid_interest,
            "import_budget": import_budget,
            "imports": imports,
            "max_repayment": min(cash_in, debt + v["new_loans"]),
        }

    # -------------------------------------------------------------------------
    # Öffentliche API: Abfragen
    # -------------------------------------------------------------------------

    def budgets(self, inputs: dict) -> dict:
        try:
            v, _ = _coerce(inputs)
        except Exception:
            v = {k: 0.0 for k in ALL_INPUT_KEYS}
        fin = self._finance(v)
        return {
            "food": {"available": self.food_available,
                     "used": v["food_domestic"] + v["food_export"]},
            "goods": {"available": self.goods_available,
                      "used": v["goods_domestic"] + v["goods_export"] + v["goods_investment"]},
            "energy": {"available": self.energy_available,
                       "used": v["energy_food"] + v["energy_goods"] + v["energy_export"]
                       + v["energy_carryover"] + v["goods_domestic"] / 5.0},
            "money": {"available": fin["import_budget"], "used": fin["imports"]},
            "invest": {"available": v["goods_investment"],
                       "used": sum(v[k] for k in self.active_invest_keys())},
        }

    def requirements(self) -> dict:
        food_req, goods_req, _ = self.full_energy_requirements()
        fin = self._finance({k: 0.0 for k in INPUT_KEYS})
        return _Requirements({
            "energy_food_full": food_req,
            "energy_goods_full": goods_req,
            "energy_population_per_goods": self.ENERGY_POPULATION_PER_GOODS,
            "interest_due": fin["interest_due"],
            "annual_interest": fin["annual_interest"],
            "import_mult": fin["import_mult"],
            "avg_exports": fin["avg_exports"],
            "debt": self.debt,
            "max_new_loan": fin["max_new_loan"],
            "cash_reserve": self.cash_reserve,
            "imf_pending": self.imf_pending,
        }, market=copy.deepcopy(self.market))

    def validate(self, inputs: dict) -> list[Issue]:
        """KORREKTUR 1/5: reine Prüfung, verändert nichts am Zustand."""
        issues: list[Issue] = []

        def err(field, msg):
            issues.append(Issue(field, msg, "error"))

        def warn(field, msg):
            issues.append(Issue(field, msg, "warning"))

        if self.game_over:
            if self.goal_cycles is not None:
                err(None, f"Das Spiel ist beendet – das Ziel von {self.goal_cycles} Zyklen "
                          f"({self.goal_years} Jahre) ist erreicht.")
            else:
                err(None, "Das Spiel ist beendet.")
            return issues

        v, bad = _coerce(inputs)
        for k in bad:
            err(k, f"{INPUT_LABELS[k]}: ungültige oder fehlende Zahl.")
        for k in MINISTRY_INPUT_KEYS:
            mk = _MINISTRY_BY_INPUT[k]
            if k not in bad and not self.ministries.get(mk) and abs(v[k]) > TOL:
                err(k, f"{INPUT_LABELS[k]}: Das Ministerium {MINISTRIES[mk]['name']} ist in diesem Spiel "
                       f"nicht aktiv – der Wert muss 0 sein.")
        for k in self.active_input_keys():
            if k in bad:
                continue
            x = v[k]
            if x < -TOL:
                err(k, f"{INPUT_LABELS[k]} darf nicht negativ sein.")
            elif abs(x / 10.0 - round(x / 10.0)) > 1e-6:
                err(k, f"{INPUT_LABELS[k]} muss ein Vielfaches von 10 sein.")

        # Ressourcen
        food_used = v["food_domestic"] + v["food_export"]
        if food_used > self.food_available + TOL:
            err(None, f"Nahrung überbelegt: verfügbar {_fmt(self.food_available)}, "
                      f"zugeteilt {_fmt(food_used)} NW.")
        goods_used = v["goods_domestic"] + v["goods_export"] + v["goods_investment"]
        if goods_used > self.goods_available + TOL:
            err(None, f"Güter überbelegt: verfügbar {_fmt(self.goods_available)}, "
                      f"zugeteilt {_fmt(goods_used)} GW.")
        energy_pop = v["goods_domestic"] / 5.0
        energy_used = (v["energy_food"] + v["energy_goods"] + v["energy_export"]
                       + v["energy_carryover"] + energy_pop)
        if energy_used > self.energy_available + TOL:
            err(None, f"Energie überbelegt: verfügbar {_fmt(self.energy_available)}, benötigt "
                      f"{_fmt(energy_used)} EW (inkl. {_fmt(energy_pop)} EW Bevölkerungsenergie).")

        # Investitionen
        inv_sum = sum(v[k] for k in self.active_invest_keys())
        if inv_sum > v["goods_investment"] + TOL:
            err(None, f"Investitionen ({_fmt(inv_sum)}) übersteigen "
                      f"{INPUT_LABELS['goods_investment']} ({_fmt(v['goods_investment'])}) "
                      f"um {_fmt(inv_sum - v['goods_investment'])}.")
        if v["inv_energy_eff"] > v["inv_food"] + v["inv_goods"] + TOL:
            err("inv_energy_eff", f"{INPUT_LABELS['inv_energy_eff']} darf höchstens "
                                  f"{INPUT_LABELS['inv_food']} + {INPUT_LABELS['inv_goods']} "
                                  f"({_fmt(v['inv_food'] + v['inv_goods'])}) betragen.")

        # Finanzen (KORREKTUR 2)
        fin = self._finance(v)
        if v["new_loans"] > fin["max_new_loan"] + TOL:
            err("new_loans", f"{INPUT_LABELS['new_loans']} zu hoch: bei durchschnittlichen Exporten von "
                             f"{_fmt(fin['avg_exports'])} und Schulden von {_fmt(fin['debt_start'])} "
                             f"sind höchstens {_fmt(fin['max_new_loan'])} zulässig.")
        if v["repayments"] > fin["cash_in"] + TOL:
            err("repayments", f"{INPUT_LABELS['repayments']} ({_fmt(v['repayments'])}) übersteigt die "
                              f"verfügbaren Devisen ({_fmt(fin['cash_in'])}).")
        elif v["repayments"] > fin["debt_start"] + v["new_loans"] + TOL:
            err("repayments", f"{INPUT_LABELS['repayments']} ({_fmt(v['repayments'])}) übersteigt "
                              f"Schulden + neue Kredite ({_fmt(fin['debt_start'] + v['new_loans'])}).")
        if fin["imports"] > fin["import_budget"] + TOL:
            err(None, f"Importbudget überschritten: verfügbar {_fmt(fin['import_budget'])}, "
                      f"für Importe eingeplant {_fmt(fin['imports'])}.")

        # Warnungen (blockieren nicht)
        food_req, goods_req, _ = self.full_energy_requirements()
        if food_req > 0 and v["energy_food"] < food_req - TOL:
            warn("energy_food", f"{INPUT_LABELS['energy_food']} deckt nur "
                                f"{v['energy_food'] / food_req * 100:.0f} % des Bedarfs für volle "
                                f"Auslastung ({_fmt(food_req)} EW).")
        if goods_req > 0 and v["energy_goods"] < goods_req - TOL:
            warn("energy_goods", f"{INPUT_LABELS['energy_goods']} deckt nur "
                                 f"{v['energy_goods'] / goods_req * 100:.0f} % des Bedarfs für volle "
                                 f"Auslastung ({_fmt(goods_req)} EW).")
        pop = max(1.0, self.population)
        cur_food_pc = v["food_domestic"] / pop / 5.0
        cur_goods_pc = v["goods_domestic"] / pop / 5.0
        food_ratio = cur_food_pc / max(0.001, self.food_pc)
        goods_ratio = cur_goods_pc / max(0.001, self.goods_pc)
        if food_ratio < 0.8:
            warn("food_domestic", f"Nahrungskonsum pro Kopf sinkt um {(1 - food_ratio) * 100:.0f} % "
                                  f"– Produktionseinbruch in der Landwirtschaft (MFC).")
        elif cur_food_pc < self.food_pc - 1e-9:
            warn("food_domestic", f"Nahrung pro Kopf sinkt von {self.food_pc:.2f} auf {cur_food_pc:.2f}.")
        if goods_ratio < 0.8:
            warn("goods_domestic", f"Güterkonsum pro Kopf sinkt um {(1 - goods_ratio) * 100:.0f} % "
                                   f"– Produktionseinbruch in der Güterproduktion (MGC).")
        if inv_sum < v["goods_investment"] - TOL:
            warn(None, f"Investitionsbudget nicht voll verteilt: {_fmt(v['goods_investment'] - inv_sum)} GW "
                       f"bleiben ungenutzt.")
        if v["new_loans"] > 0 and v["new_loans"] >= 0.9 * fin["max_new_loan"] - TOL:
            warn("new_loans", f"Neue Kredite nahe am Kreditlimit ({_fmt(fin['max_new_loan'])}).")
        return issues

    def warnings(self) -> list[str]:
        """Systemwarnungen zum aktuellen Zustand."""
        out = []
        if self.game_over:
            out.append("Das Spiel ist beendet.")
        if self.food_pc < 2.0 - 1e-9:
            out.append(f"Nahrung pro Kopf ({self.food_pc:.2f}) liegt unter 2,0 – erhöhte Sterberate.")
        if self.food_available / max(1.0, self.population) / 5.0 < 2.0:
            out.append("Verfügbare Nahrung reicht nicht für 2,0 NW pro Kopf und Jahr.")
        if self.environment < 0.4:
            out.append(f"Umweltqualität kritisch ({self.environment * 100:.0f} %).")
        elif self.environment < 0.6:
            out.append(f"Umweltqualität sinkt ({self.environment * 100:.0f} %) – Sterberate steigt.")
        fin = self._finance({k: 0.0 for k in INPUT_KEYS})
        if fin["debt_export_ratio"] > 2.0:
            out.append(f"Schulden betragen das {fin['debt_export_ratio']:.1f}-fache der Exporte – "
                       f"höhere Zinsen ({fin['annual_interest']:.1f} %) und Importpreise.")
        if self.imf_pending > 0:
            out.append(f"IMF-Intervention: {_fmt(self.imf_pending)} GW wurden für die Schuldentilgung "
                       f"einbehalten.")
        net = self.birth_rate() - self.death_rate()
        if net < 0:
            out.append(f"Bevölkerung schrumpft ({net:+.1f} pro 1000/Jahr).")
        food_req, goods_req, pop_req = self.full_energy_requirements()
        if self.energy_available < food_req + goods_req + pop_req:
            out.append(f"Energie ({_fmt(self.energy_available)}) reicht nicht für volle Auslastung "
                       f"(Bedarf {_fmt(food_req + goods_req + pop_req)} EW).")
        if self.ministries.get("gesundheit") and self._per_capita("cap_health") < 0.3:
            out.append("Gesundheitswesen unterversorgt – kaum Schutz vor Sterblichkeit und Epidemien.")
        if self.ministries.get("bildung") and self._per_capita("cap_education") < 0.3:
            out.append("Bildungssystem unterfinanziert – die Produktivität profitiert kaum von Bildung.")
        if self.ministries.get("infrastruktur") and self.infra_production_multiplier() < 1.0 - 1e-9:
            out.append(f"Infrastruktur reicht nicht für das Produktionskapital – Logistik bremst die "
                       f"Produktion ({(1 - self.infra_production_multiplier()) * 100:.0f} % Verlust).")
        if self.ministries.get("verteidigung"):
            if self.security() < 0.25:
                out.append(f"Sicherheit niedrig ({self.security() * 100:.0f} %) – negative Ereignisse "
                           f"treffen das Land fast ungebremst.")
            if self.defense_labor_share() >= self.DEFENSE_LABOR_MAX - 1e-9:
                out.append("Die Streitkräfte binden 10 % der Arbeitskräfte (Maximum).")
        return out

    # -------------------------------------------------------------------------
    # Öffentliche API: Züge
    # -------------------------------------------------------------------------

    def preview(self, inputs: dict) -> dict | None:
        if any(i.severity == "error" for i in self.validate(inputs)):
            return None
        clone = copy.deepcopy(self)
        v, _ = _coerce(inputs)
        return clone._simulate(v)

    def apply(self, inputs: dict) -> dict:
        errors = [i for i in self.validate(inputs) if i.severity == "error"]
        if errors:
            raise ValueError("\n".join(i.message for i in errors))
        v, _ = _coerce(inputs)
        snapshot = self._state()
        result = self._simulate(v)
        self._undo.append(snapshot)
        self.history.append(copy.deepcopy(result))
        self.last_inputs = {k: v[k] for k in self.active_input_keys()}
        if self.goal_snapshot is None and self.goal_reached:
            self._take_goal_snapshot()
        return result

    def berechne_runde(self, inputs):
        """Kompatibilität zum Altcode."""
        return self.apply(inputs)

    def can_undo(self) -> bool:
        return bool(self._undo)

    def undo(self) -> bool:
        if not self._undo:
            return False
        self._restore(self._undo.pop())
        return True

    def suggest_inputs(self, base: dict | None = None) -> dict:
        """KORREKTUR 6: zulässige Eingaben passend zu den aktuellen Beständen.

        Nahrung, Güter und Energie werden proportional auf die verfügbaren
        Bestände skaliert (auf- oder abwärts), Investitionen auf das
        Investitionsbudget. Kredite/Tilgung werden auf ihre Grenzen begrenzt,
        Importe nur abwärts auf das Importbudget skaliert. Alles wird abwärts
        auf Vielfache von 10 gerundet.
        """
        keys = self.active_input_keys()
        inv_keys = self.active_invest_keys()
        zeros = {k: 0.0 for k in keys}
        if self.game_over:
            return zeros
        if base is None:
            base = self.last_inputs if self.last_inputs is not None else DEFAULT_INPUTS
        base = dict(base) if isinstance(base, dict) else {}
        for k in inv_keys[len(INVEST_KEYS):]:
            # Aktive Ministerien ohne Vorgabe bekommen einen kleinen Startbetrag.
            if base.get(k) is None:
                base[k] = MINISTRY_DEFAULT_INPUTS[k]
        v, _ = _coerce(base)
        v = {k: _floor10(max(0.0, v[k])) for k in keys}

        def scale(keys, target):
            total = sum(v[k] for k in keys)
            if total <= 0:
                for k in keys:
                    v[k] = 0.0
                return
            f = max(0.0, target) / total
            for k in keys:
                v[k] = _floor10(v[k] * f)

        # Nahrung
        scale(["food_domestic", "food_export"], self.food_available)
        rest = _floor10(self.food_available - v["food_domestic"] - v["food_export"])
        if v["food_domestic"] + v["food_export"] > 0:
            v["food_domestic"] += rest

        # Güter
        g_keys = ["goods_domestic", "goods_export", "goods_investment"]
        scale(g_keys, self.goods_available)
        rest = _floor10(self.goods_available - sum(v[k] for k in g_keys))
        if sum(v[k] for k in g_keys) > 0:
            v["goods_investment"] += rest

        # Energie (Bevölkerungsenergie = goods_domestic / 5 ist fix)
        if v["goods_domestic"] / 5.0 > self.energy_available:
            v["goods_domestic"] = _floor10(self.energy_available * 5.0)
        e_keys = ["energy_food", "energy_goods", "energy_export", "energy_carryover"]
        e_avail = self.energy_available - v["goods_domestic"] / 5.0
        scale(e_keys, e_avail)
        rest = _floor10(e_avail - sum(v[k] for k in e_keys))
        v["energy_carryover"] += rest

        # Investitionen
        scale(inv_keys, v["goods_investment"])
        v["inv_energy_eff"] = min(v["inv_energy_eff"], v["inv_food"] + v["inv_goods"])
        rest = _floor10(v["goods_investment"] - sum(v[k] for k in inv_keys))
        others = [k for k in INVEST_KEYS if k != "inv_energy_eff"]
        biggest = max(others, key=lambda k: v[k])
        if rest > 0 and v[biggest] > 0:
            v[biggest] += rest

        # Finanzen
        fin = self._finance(v)
        v["new_loans"] = min(v["new_loans"], _floor10(fin["max_new_loan"]))
        fin = self._finance(v)
        v["repayments"] = min(v["repayments"], _floor10(fin["max_repayment"]))
        fin = self._finance(v)
        if fin["imports"] > fin["import_budget"]:
            scale(IMPORT_KEYS, fin["import_budget"])

        if not any(i.severity == "error" for i in self.validate(v)):
            return v
        # Rückfallebene: Finanzentscheidungen neutralisieren, dann alles 0.
        for k in ["new_loans", "repayments"] + IMPORT_KEYS:
            v[k] = 0.0
        if not any(i.severity == "error" for i in self.validate(v)):
            return v
        return zeros

    # -------------------------------------------------------------------------
    # Bewertung
    # -------------------------------------------------------------------------

    # Gewichte des Scores (Summe 100):
    #  food        30  Nahrung/Kopf: linear, volle Punkte ab 2,0 NW/Kopf
    #  goods       20  Güter/Kopf: linear, volle Punkte ab 1,5 x Startwert
    #  environment 20  Umweltqualität: linear, volle Punkte ab 80 %
    #  debt        15  Schulden: volle Punkte, solange sie nicht über den Startwert
    #                  (mind. 500) steigen; 0 Punkte bei Verdreifachung
    #  population  15  Bevölkerungsstabilität: je zur Hälfte Größe (nicht unter
    #                  Startbevölkerung) und Wachstum (|netto| <= 5 pro 1000/Jahr
    #                  volle Punkte, 0 Punkte ab 25)
    SCORE_WEIGHTS = {"food": 30, "goods": 20, "environment": 20, "debt": 15, "population": 15}
    #  services    10  nur wenn Ministerien aktiv sind (die übrigen Gewichte werden
    #                  dann mit 0.9 skaliert, die Summe bleibt 100)
    SCORE_SERVICES_WEIGHT = 10

    @classmethod
    def _score_parts(cls, end: dict, start: dict, ministries: dict | None = None) -> dict:
        w = cls.SCORE_WEIGHTS

        def g(d, k, default=0.0):
            try:
                return float(d.get(k, default))
            except (TypeError, ValueError):
                return default

        food = w["food"] * clamp(g(end, "food_pc") / 2.0, 0.0, 1.0)
        goods_ref = max(0.5, g(start, "goods_pc", 2.0)) * 1.5
        goods = w["goods"] * clamp(g(end, "goods_pc") / goods_ref, 0.0, 1.0)
        env = w["environment"] * clamp(g(end, "environment") / 0.8, 0.0, 1.0)
        start_debt = max(500.0, g(start, "debt", 1000.0))
        debt = w["debt"] * clamp(1.0 - (g(end, "debt") - start_debt) / (2.0 * start_debt), 0.0, 1.0)
        size = clamp(g(end, "population") / max(1.0, g(start, "population", 200.0)), 0.0, 1.0)
        stab = clamp(1.0 - max(0.0, abs(g(end, "net_growth")) - 5.0) / 20.0, 0.0, 1.0)
        pop = w["population"] * (0.5 * size + 0.5 * stab)
        parts = {"food": (food, w["food"]), "goods": (goods, w["goods"]),
                 "environment": (env, w["environment"]), "debt": (debt, w["debt"]),
                 "population": (pop, w["population"])}
        active = [k for k in MINISTRIES if (ministries or {}).get(k)]
        if not active:
            return parts
        # Mit aktiven Ministerien: bisherige Teile * 0.9, dazu "services" (max. 10)
        # = mittlerer Ausbaugrad der aktiven Ministerien (je 0..1):
        #   Gesundheit (1 - health_mult) / 0.25, Bildung (education_mult - 1) / 0.3,
        #   Infrastruktur (infra_mult - 0.9) / 0.15, Verteidigung security / 0.8.
        f = 1.0 - cls.SCORE_SERVICES_WEIGHT / 100.0
        parts = {k: (p * f, m * f) for k, (p, m) in parts.items()}
        levels = {
            "gesundheit": (1.0 - g(end, "health_mult", 1.0)) / 0.25,
            "bildung": (g(end, "education_mult", 1.0) - 1.0) / 0.3,
            "infrastruktur": (g(end, "infra_mult", 1.0) - 0.9) / 0.15,
            "verteidigung": g(end, "security", 0.0) / 0.8,
        }
        level = sum(clamp(levels[k], 0.0, 1.0) for k in active) / len(active)
        ws = cls.SCORE_SERVICES_WEIGHT
        parts["services"] = (ws * level, ws)
        return parts

    def score(self) -> dict:
        """Score 0..100 des aktuellen Zustands (siehe SCORE_WEIGHTS)."""
        start = self.history[0] if self.history else self._initial_record()
        end = self.history[-1] if self.history else start
        parts = self._score_parts(end, start, self.ministries)
        total = clamp(sum(p for p, _ in parts.values()), 0.0, 100.0)
        if total >= 85:
            grade = "A"
        elif total >= 70:
            grade = "B"
        elif total >= 55:
            grade = "C"
        elif total >= 40:
            grade = "D"
        elif total >= 25:
            grade = "E"
        else:
            grade = "F"
        names = {"food": "Nahrungsversorgung", "goods": "Güterversorgung", "environment": "Umweltqualität",
                 "debt": "Verschuldung", "population": "Bevölkerungsstabilität",
                 "services": "Staatsaufgaben (Ministerien)"}
        weakest = min(parts, key=lambda k: parts[k][0] / parts[k][1])
        strongest = max(parts, key=lambda k: parts[k][0] / parts[k][1])
        lead = {"A": "Hervorragend regiert.", "B": "Gut regiert.", "C": "Solide, mit Schwächen.",
                "D": "Durchwachsen.", "E": "Das Land steckt in Schwierigkeiten.",
                "F": "Kritischer Zustand."}[grade]
        if parts[weakest][0] >= parts[weakest][1] - 1e-9:
            comment = f"{lead} Alle Bereiche erreichen die volle Punktzahl."
        else:
            comment = (f"{lead} Stärke: {names[strongest]}. "
                       f"Größtes Verbesserungspotenzial: {names[weakest]}.")
        out = {"total": total, "grade": grade, "parts": parts, "comment": comment}
        snap = getattr(self, "goal_snapshot", None)
        if snap and self.cycles_played > (snap.get("runde") or 0):
            # Über das Ziel hinaus gespielt: Score im Moment des Zielerreichens.
            try:
                out["goal_score"] = float(snap["score"]["total"])
            except (KeyError, TypeError, ValueError):
                pass
        return out

    # -------------------------------------------------------------------------
    # Berater
    # -------------------------------------------------------------------------

    _ADVISOR_HORIZON = 8   # Vorausschau in Zyklen (stationäre Strategie)

    _ADVISOR_DIMS = [
        ("fc", [2.0, 2.2, 2.5, 3.0, 1.8]),             # Nahrung pro Kopf (Ziel)
        ("gf", [1.0, 1.1, 1.25, 1.5, 0.9, 0.75]),       # Güterkonsum relativ zum Vorzyklus
        ("gx", [0.0, 0.15, 0.3]),                      # Anteil Güterüberschuss für Export
        ("ef", [1.0, 1.1, 0.85]),                      # Energie relativ zum Bedarf
        ("em", ["carry", "export", "split"]),          # Energie-Rest
        ("mix", list(_ADVISOR_MIXES)),                 # Investitionsmix
        ("fin", ["reserve", "repay", "food", "goods", "energy", "repay_food", "loan_food"]),
    ]

    def _advisor_dims(self) -> list:
        """Suchdimensionen; mit aktiven Ministerien zusätzlich Anteil + Schwerpunkt."""
        active = self.active_ministries()
        if not active:
            return self._ADVISOR_DIMS
        dims = list(self._ADVISOR_DIMS)
        dims.append(("ms", [0.15, 0.08, 0.25, 0.35, 0.0]))     # Anteil Ministerien am Investitionsbudget
        if len(active) > 1:
            dims.append(("mf", ["gleich"] + active))           # Schwerpunkt-Ministerium
        return dims

    def _advisor_inputs(self, p: dict) -> dict:
        """Baut Eingaben aus Beraterparametern für den aktuellen Zustand."""
        v = {k: 0.0 for k in self.active_input_keys()}
        pop = max(1.0, self.population)
        food_av = self.food_available
        v["food_domestic"] = _floor10(min(food_av, p["fc"] * pop * 5.0))
        v["food_export"] = _floor10(food_av - v["food_domestic"])

        g_av, e_av = self.goods_available, self.energy_available
        gd = _floor10(min(0.85 * g_av, p["gf"] * max(self.goods_pc, 0.3) * pop * 5.0, e_av * 5.0))
        rest = g_av - gd
        v["goods_domestic"] = gd
        v["goods_export"] = _floor10(rest * p["gx"])
        v["goods_investment"] = _floor10(rest - v["goods_export"])

        e_rest = e_av - gd / 5.0
        food_req, goods_req, _ = self.full_energy_requirements()
        need_f, need_g = food_req * p["ef"], goods_req * p["ef"]
        if need_f + need_g > e_rest > 0:
            f = e_rest / (need_f + need_g)
            need_f, need_g = need_f * f, need_g * f
        v["energy_food"] = _floor10(min(need_f, e_rest))
        v["energy_goods"] = _floor10(min(need_g, e_rest - v["energy_food"]))
        r = _floor10(e_rest - v["energy_food"] - v["energy_goods"])
        if p["em"] == "export":
            v["energy_export"] = r
        elif p["em"] == "split":
            v["energy_export"] = _floor10(r / 2.0)
            v["energy_carryover"] = _floor10(r - v["energy_export"])
        else:
            v["energy_carryover"] = r

        gi = v["goods_investment"]
        active = self.active_ministries()
        if active:
            # Anteil des Investitionsbudgets für die Ministerien; Schwerpunkt "mf"
            # bekommt dreifaches Gewicht.
            m_budget = _floor10(gi * p.get("ms", 0.0))
            mw = {k: (3.0 if p.get("mf") == k else 1.0) for k in active}
            mws = sum(mw.values())
            for k in active:
                v[MINISTRIES[k]["input_key"]] = _floor10(m_budget * mw[k] / mws)
            gi = gi - sum(v[MINISTRIES[k]["input_key"]] for k in active)
        weights = _ADVISOR_MIXES[p["mix"]]
        wsum = float(sum(weights))
        for k, w in zip(INVEST_KEYS, weights):
            v[k] = _floor10(gi * w / wsum)
        v["inv_energy_eff"] = min(v["inv_energy_eff"], v["inv_food"] + v["inv_goods"])
        rest = _floor10(gi - sum(v[k] for k in INVEST_KEYS))
        if rest > 0:
            others = [k for k in INVEST_KEYS if k != "inv_energy_eff"]
            v[max(others, key=lambda k: v[k])] += rest

        fin_mode = p["fin"]
        if fin_mode == "loan_food":
            fin = self._finance(v)
            v["new_loans"] = _floor10(fin["max_new_loan"])
        fin = self._finance(v)
        budget = _floor10(fin["import_budget"])
        if fin_mode == "repay":
            v["repayments"] = _floor10(min(budget, fin["debt_start"]))
        elif fin_mode == "repay_food":
            v["repayments"] = _floor10(min(budget / 2.0, fin["debt_start"]))
            v["import_food_money"] = _floor10(budget - v["repayments"])
        elif fin_mode in ("food", "loan_food"):
            v["import_food_money"] = budget
        elif fin_mode == "goods":
            v["import_goods_money"] = budget
        elif fin_mode == "energy":
            v["import_energy_money"] = budget
        return v

    def _advisor_value(self, res: dict, start: dict) -> float:
        """Bewertung eines (simulierten) Zustands: Score + zukünftige Kapazität."""
        value = sum(p for p, _ in self._score_parts(res, start, self.ministries).values())
        # Schuldenspirale zusätzlich bestrafen (der Score-Anteil ist bei 0 gedeckelt).
        value -= 8.0 * math.log1p(max(0.0, self.current_finance_conditions()[1] - 1.5))
        if not self.game_over:
            pop = max(1.0, self.population)
            value += 20.0 * clamp(self.food_available / (pop * 5.0 * 2.0), 0.0, 1.25)
            value += 8.0 * clamp(self.goods_available / (pop * 5.0) / 4.0, 0.0, 1.25)
            food_req, goods_req, pop_req = self.full_energy_requirements()
            value += 4.0 * clamp(self.energy_available / max(1.0, food_req + goods_req + pop_req), 0.0, 1.0)
        return value

    def _advisor_rollout(self, p: dict, first: dict, start: dict, horizon: int) -> float:
        eng = self._light_clone()
        res = eng._simulate(first)
        eng.events_enabled = False   # nur das kommende Ereignis ist bekannt
        for _ in range(horizon):
            if eng.game_over:
                break
            inp = eng._advisor_inputs(p)
            if any(i.severity == "error" for i in eng.validate(inp)):
                inp = eng.suggest_inputs(inp)
            res = eng._simulate(inp)
        return eng._advisor_value(res, start)

    def advise_inputs(self) -> tuple[dict, list[str]]:
        """Berater: sucht per Simulation die beste von vielen zulässigen Varianten.

        Die Kandidaten werden über Parameter (Nahrung/Kopf, Güterkonsum,
        Güterexport, Energieeinsatz, Energierest, Investitionsmix, Finanzen)
        erzeugt; jede Variante wird über einige Zyklen vorausgerechnet
        (Koordinatensuche) und nach Score + zukünftiger Kapazität bewertet.
        """
        zeros = {k: 0.0 for k in self.active_input_keys()}
        if self.game_over:
            return zeros, ["Das Spiel ist beendet – keine Eingaben mehr nötig."]
        start = self.history[0] if self.history else self._initial_record()
        horizon = self._ADVISOR_HORIZON
        dims = self._advisor_dims()
        cache = {}

        def evaluate(p):
            key = tuple(sorted(p.items()))
            if key in cache:
                return cache[key]
            inp = self._advisor_inputs(p)
            if any(i.severity == "error" for i in self.validate(inp)):
                val = None
            else:
                val = self._advisor_rollout(p, inp, start, horizon)
            cache[key] = val
            return val

        best = {name: opts[0] for name, opts in dims}
        best["mix"] = "ausgewogen"
        best_val = evaluate(best)
        if best_val is None:
            best_val = -math.inf
        for _ in range(3):
            improved = False
            for name, opts in dims:
                for o in opts:
                    if o == best[name]:
                        continue
                    q = dict(best, **{name: o})
                    val = evaluate(q)
                    if val is not None and val > best_val + 1e-9:
                        best, best_val, improved = q, val, True
            if not improved:
                break

        if best_val == -math.inf:
            inp = self.suggest_inputs()
            return inp, ["Keine bessere Variante gefunden – Standardvorschlag übernommen."]
        inp = self._advisor_inputs(best)
        return inp, self._advisor_reasons(inp, best)

    def _advisor_reasons(self, v: dict, p: dict) -> list[str]:
        pop = max(1.0, self.population)
        out = []
        ev = self.current_event()
        if ev:
            out.append(f"Ereignis „{ev['name']}“ im kommenden Zyklus berücksichtigt: {ev['description']}")
        out.append(f"Nahrung: {_fmt(v['food_domestic'])} NW für die Bevölkerung "
                   f"({v['food_domestic'] / pop / 5:.2f} NW/Kopf, Ziel ≥ 2,0); "
                   f"{_fmt(v['food_export'])} NW Überschuss werden exportiert.")
        out.append(f"Güter: {_fmt(v['goods_domestic'])} GW Konsum ({v['goods_domestic'] / pop / 5:.2f} GW/Kopf, "
                   f"Vorzyklus {self.goods_pc:.2f}), {_fmt(v['goods_investment'])} GW Investitionen"
                   + (f", {_fmt(v['goods_export'])} GW Export." if v["goods_export"] > 0 else "."))
        food_req, goods_req, _ = self.full_energy_requirements()
        rest = []
        if v["energy_export"] > 0:
            rest.append(f"{_fmt(v['energy_export'])} EW Export")
        if v["energy_carryover"] > 0:
            rest.append(f"{_fmt(v['energy_carryover'])} EW Carry-over")
        out.append(f"Energie: Nahrung {v['energy_food'] / max(1.0, food_req) * 100:.0f} %, "
                   f"Güter {v['energy_goods'] / max(1.0, goods_req) * 100:.0f} % des Bedarfs"
                   + (f"; Rest: {', '.join(rest)}." if rest else "."))
        out.append(f"Investitionen: Schwerpunkt „{p['mix']}“ – "
                   + ", ".join(f"{INPUT_LABELS[k].replace('Investition ', '')} {_fmt(v[k])}"
                               for k in INVEST_KEYS if v[k] > 0) + ".")
        active = self.active_ministries()
        if active:
            parts = [f"{MINISTRIES[k]['name']} {_fmt(v.get(MINISTRIES[k]['input_key'], 0.0))}" for k in active]
            focus = p.get("mf")
            focus_txt = (f", Schwerpunkt {MINISTRIES[focus]['name']}" if focus in MINISTRIES else "")
            out.append(f"Ministerien: {p.get('ms', 0.0) * 100:.0f} % des Investitionsbudgets{focus_txt} – "
                       + ", ".join(parts) + ".")
        fin_text = {
            "reserve": "Devisen bleiben als Reserve für den nächsten Zyklus.",
            "repay": f"Freie Devisen tilgen Schulden ({_fmt(v['repayments'])}).",
            "food": f"Freie Devisen für Nahrungsimporte ({_fmt(v['import_food_money'])}).",
            "goods": f"Freie Devisen für Güterimporte ({_fmt(v['import_goods_money'])}).",
            "energy": f"Freie Devisen für Energieimporte ({_fmt(v['import_energy_money'])}).",
            "repay_food": f"Devisen je zur Hälfte für Tilgung ({_fmt(v['repayments'])}) und "
                          f"Nahrungsimporte ({_fmt(v['import_food_money'])}).",
            "loan_food": f"Neuer Kredit ({_fmt(v['new_loans'])}) finanziert Nahrungsimporte "
                         f"({_fmt(v['import_food_money'])}).",
        }[p["fin"]]
        out.append(f"Finanzen: {fin_text}")
        res = self.preview(v)
        if res is not None:
            out.append(f"Prognose: Bevölkerung {res['population']:.0f}, Nahrung/Kopf {res['food_pc']:.2f}, "
                       f"Güter/Kopf {res['goods_pc']:.2f}, Umwelt {res['environment'] * 100:.0f} %, "
                       f"Schulden {_fmt(res['debt'])}.")
        return out

    # -------------------------------------------------------------------------
    # Kennlinien
    # -------------------------------------------------------------------------

    def curve_positions(self) -> list[dict]:
        """Alle 15 Kennlinien (+ die der aktiven Ministerien) mit aktuellem Arbeitspunkt (x, y)."""
        prod_cap = self.cap_food + self.cap_goods
        ratio = self.current_finance_conditions()[1]
        load = max(0.0, self.active_food_capital + self.active_goods_capital + self.cap_energy_prod
                   - 3.0 * self.cap_env)
        xs = {
            "BIRTH_RATE_CURVE": sum(self.goods_pc_history) / len(self.goods_pc_history),
            "BIRTH_SERVICE_MULT_CURVE": self.human_services_pc,
            "DEATH_RATE_CURVE": self.food_pc,
            "DEATH_ENV_MULT_CURVE": self.environment,
            "ENERGY_PRODUCTION_LOW_CURVE": self.cap_energy_prod / 1000.0,
            "ENERGY_EFFICIENCY_CURVE": (self.cap_energy_eff / prod_cap) if prod_cap > 0 else None,
            "FOOD_CONSUMPTION_CHANGE_CURVE": self.food_pc / self.last_food_pc if self.last_food_pc > 0 else None,
            "FOOD_CAPITAL_CURVE": self.active_food_capital / self.LAND_AREA,
            "ENV_DEGRADATION_CURVE": load / 20000.0,
            "ENV_REGENERATION_CURVE": self.environment,
            "GOODS_CONSUMPTION_CHANGE_CURVE":
                self.goods_pc / self.last_goods_pc if self.last_goods_pc > 0 else None,
            "GOODS_CAPITAL_CURVE": self.active_goods_capital / max(1.0, self.labor_force),
            "HUMAN_SERVICE_CURVE": self.human_services_pc,
            "IMPORT_PRICE_MULT_CURVE": ratio,
            "INTEREST_RATE_CURVE": ratio,
            "HEALTH_DEATH_MULT_CURVE": self._per_capita("cap_health"),
            "EDUCATION_PRODUCTIVITY_CURVE": self._per_capita("cap_education"),
            "INFRA_ENERGY_CURVE": self._infra_ratio(),
            "INFRA_PRODUCTION_CURVE": self._infra_ratio(),
            "DEFENSE_SECURITY_CURVE": self._per_capita("cap_defense"),
        }
        out = []
        for key, fig, title, x_label, y_label in CURVE_INFO:
            if key in _CURVE_MINISTRY and not self.ministries.get(_CURVE_MINISTRY[key]):
                continue
            points = [(float(a), float(b)) for a, b in getattr(self, key)]
            x = xs.get(key)
            y = None
            if x is not None and math.isfinite(x):
                x = clamp(float(x), points[0][0], points[-1][0])
                y = interp(x, points)
            else:
                x = None
            out.append({"key": key, "figure": fig, "title": title, "x_label": x_label,
                        "y_label": y_label, "points": points, "x": x, "y": y})
        return out

    # -------------------------------------------------------------------------
    # Hauptsimulation (nur auf validierten Eingaben aufrufen)
    # -------------------------------------------------------------------------

    def _simulate(self, x: dict) -> dict:
        # Finanzrechnung zuerst – reine Funktion des Anfangszustands.
        fin = self._finance(x)
        event_key = self._event_key()
        event = dict(_EVENTS_BY_KEY[event_key]) if event_key else None
        any_min = self.any_ministry()
        # Ministeriums-Wirkungen zu Zyklusbeginn (inaktiv: neutral, nicht angewendet)
        health_mult = self.health_multiplier()
        education_mult = self.education_multiplier()
        infra_mult = self.infra_production_multiplier()
        infra_energy_mult = self.infra_energy_multiplier()
        security = self.security()
        damping = self._event_damping() if any_min else 1.0
        damping_health = self._event_damping(health=True) if any_min else 1.0

        food_domestic = x["food_domestic"]
        goods_domestic = x["goods_domestic"]

        food_full_energy, goods_full_energy, _ = self.full_energy_requirements()
        food_cu = clamp(x["energy_food"] / max(1.0, food_full_energy), 0.0, 1.10)
        goods_cu = clamp(x["energy_goods"] / max(1.0, goods_full_energy), 0.0, 1.10)

        # --- Konsum des aktuellen Zyklus --------------------------------------
        current_food_pc = food_domestic / max(1.0, self.population) / 5.0
        current_goods_pc = goods_domestic / max(1.0, self.population) / 5.0

        # KORREKTUR 3: Vergleich mit dem Konsum des UNMITTELBAR vorigen Zyklus
        # (self.food_pc / self.goods_pc), nicht mit dem vorvorigen.
        food_mfc = interp(clamp(current_food_pc / max(0.001, self.food_pc), 0.0, 2.0),
                          self.FOOD_CONSUMPTION_CHANGE_CURVE)
        goods_mgc = interp(clamp(current_goods_pc / max(0.001, self.goods_pc), 0.0, 2.0),
                           self.GOODS_CONSUMPTION_CHANGE_CURVE)

        active_food_for_output = self.cap_food * food_cu
        active_goods_for_output = self.cap_goods * goods_cu

        food_mfp = interp(active_food_for_output / self.LAND_AREA, self.FOOD_CAPITAL_CURVE)
        expected_food = self.expected_food_production(food_mfc=food_mfc, food_mfp=food_mfp)
        produced_food = max(0.0, expected_food * food_cu)
        if event_key == "duerre":
            if damping != 1.0:
                produced_food *= 1.0 - 0.25 * damping
            else:
                produced_food *= 0.75
        elif event_key == "gute_ernte":
            produced_food *= 1.15

        goods_mgp = interp(active_goods_for_output / max(1.0, self.labor_force), self.GOODS_CAPITAL_CURVE)
        goods_mhs = interp(self.human_services_pc, self.HUMAN_SERVICE_CURVE)
        expected_goods = self.expected_goods_production(goods_mgc=goods_mgc, goods_mgp=goods_mgp)
        produced_goods = max(0.0, expected_goods * goods_cu)

        produced_energy = self.energy_production()

        # --- Umwelt -----------------------------------------------------------
        z = active_food_for_output + active_goods_for_output + self.cap_energy_prod
        environmental_load = max(0.0, z - 3.0 * self.cap_env)
        annual_degradation = interp(clamp(environmental_load / 20000.0, 0.0, 1.0), self.ENV_DEGRADATION_CURVE)
        annual_regeneration = interp(clamp(self.environment, 0.0, 1.0), self.ENV_REGENERATION_CURVE)
        environment_before = self.environment
        self.environment = clamp(
            self.environment + self.CYCLE_YEARS * (annual_regeneration / 100.0 - annual_degradation / 100.0),
            0.05, 0.95)

        # --- Demografie -------------------------------------------------------
        avg_goods_pc = (self.goods_pc_history[-2] + self.goods_pc_history[-1] + current_goods_pc) / 3.0
        normal_birth = self.normal_birth_rate(avg_goods_pc)
        birth_mult = self.birth_service_multiplier()
        actual_birth = normal_birth * birth_mult
        if self.ministries.get("bildung"):
            actual_birth *= self.education_birth_multiplier()
        normal_death = self.normal_death_rate(current_food_pc)
        death_mult = self.death_environment_multiplier()
        actual_death = normal_death * death_mult
        if self.ministries.get("gesundheit"):
            actual_death *= health_mult
        if event_key == "epidemie":
            if damping_health != 1.0:
                actual_death *= 1.0 + 0.3 * damping_health
            else:
                actual_death *= 1.3
        annual_growth = (actual_birth - actual_death) / 1000.0
        self.population = max(1.0, self.population * math.exp(annual_growth * self.CYCLE_YEARS))

        # --- Außenhandel / Schulden (KORREKTUR 2) -----------------------------
        imf_paid_this_cycle = fin["imf_paid"]
        self.imf_pending = 0.0
        import_mult = fin["import_mult"]
        # Markt-Hook: Import-Einheiten = Geld / (Importpreis * import_mult);
        # Ölpreisschock wirkt multiplikativ zusätzlich (gedämpft durch Verteidigung).
        energy_price = self._price("import_price", "energy")
        if event_key == "oelpreisschock":
            energy_price *= (1.0 + damping) if damping != 1.0 else 2.0
        energy_import_units = x["import_energy_money"] / max(0.0001, energy_price * import_mult)
        food_import_units = x["import_food_money"] / max(0.0001, self._price("import_price", "food") * import_mult)
        goods_import_units = x["import_goods_money"] / max(0.0001,
                                                          self._price("import_price", "goods") * import_mult)
        import_spending = fin["imports"]

        # Zinsen werden genau einmal behandelt: bezahlt aus cash_in oder
        # kapitalisiert (unpaid_interest), nie beides.
        new_debt = max(0.0, fin["debt_start"] + fin["unpaid_interest"] + x["new_loans"] - x["repayments"])
        self.cash_reserve = max(0.0, fin["import_budget"] - import_spending)

        # IMF wird durch die Schuld am Zyklusende ausgelöst: 10 % der
        # Güterproduktion werden zu Beginn des nächsten Zyklus zur Tilgung genutzt.
        gdp_current = produced_food + produced_goods
        imf_repayment = 0.0
        if new_debt > 0.5 * max(1.0, gdp_current):
            imf_repayment = min(0.10 * produced_goods, new_debt)
            self.imf_pending = imf_repayment
        self.debt = new_debt

        # --- Kapitalverfall und Investitionsverzögerungen ---------------------
        self.cap_energy_prod *= 1.0 - 1.0 / 5.0
        self.cap_energy_eff *= 1.0 - 1.0 / 5.0
        self.cap_food *= 1.0 - 1.0 / 5.0
        self.cap_goods *= 1.0 - 1.0 / 5.0
        self.cap_human *= 1.0 - 1.0 / 9.0
        self.cap_env *= 1.0 - 1.0 / 6.0

        for attr, cap, key in [
            ("under_energy_prod", "cap_energy_prod", "inv_energy_prod"),
            ("under_energy_eff", "cap_energy_eff", "inv_energy_eff"),
            ("under_food", "cap_food", "inv_food"),
            ("under_goods", "cap_goods", "inv_goods"),
            ("under_human", "cap_human", "inv_human"),
            ("under_env", "cap_env", "inv_env"),
        ]:
            queue = getattr(self, attr)
            ready = queue.pop(0)
            queue.append(x[key])
            setattr(self, cap, getattr(self, cap) + ready)
        # Ministerien: Verschleiß (CYCLE_YEARS / Lebensdauer) + Bau-Verzögerung
        for mkey in self.active_ministries():
            m = MINISTRIES[mkey]
            cap = m["capital_attr"]
            queue = getattr(self, "under_" + cap[4:])
            setattr(self, cap, getattr(self, cap) * (1.0 - self.CYCLE_YEARS / m["lifetime"]))
            ready = queue.pop(0)
            queue.append(float(x.get(m["input_key"], 0.0)))
            setattr(self, cap, getattr(self, cap) + ready)

        # --- Bestände für den nächsten Zyklus ---------------------------------
        self.food_available = produced_food + food_import_units
        # KORREKTUR 4: die IMF-Rückzahlung (Güter) steht nicht mehr zur Verfügung.
        imf_goods = imf_repayment
        self.goods_available = max(0.0, produced_goods + goods_import_units - imf_goods)
        self.energy_available = produced_energy + energy_import_units + x["energy_carryover"]

        # --- Export-/Zins-Historie --------------------------------------------
        total_export_units = fin["export_money"]
        self.avg_exports_history.append(total_export_units)
        self.avg_exports_history = self.avg_exports_history[-3:]
        self.total_exports += total_export_units
        self.total_imports += energy_import_units + food_import_units + goods_import_units
        self.total_interest_paid += fin["interest_paid"]

        # --- Zustände für den nächsten Zyklus ---------------------------------
        self.last_food_pc = self.food_pc
        self.last_goods_pc = self.goods_pc
        self.food_pc = current_food_pc
        self.goods_pc = current_goods_pc
        self.goods_pc_history = (self.goods_pc_history + [self.goods_pc])[-3:]
        self.food_pc_history = (self.food_pc_history + [self.food_pc])[-3:]
        self.last_food_production = produced_food
        self.last_goods_production = produced_goods
        self.last_energy_production = produced_energy
        self.last_food_cu = food_cu
        self.last_goods_cu = goods_cu

        self.gdp_index = (produced_food + produced_goods) / self.INITIAL_OUTPUT * 100.0
        self.gdp_pc_index = self.gdp_index * 200.0 / max(1.0, self.population)

        cycle_finished = self.runde
        self.runde += 1
        if (self.goal_cycles is not None and cycle_finished >= self.goal_cycles
                and not getattr(self, "continued", False)):
            self.game_over = True

        return {
            "runde": cycle_finished,
            "jahr_start": (cycle_finished - 1) * 5,
            "jahr_end": cycle_finished * 5,

            "population": self.population,
            "labor": self.labor_force,
            "food_pc": self.food_pc,
            "goods_pc": self.goods_pc,
            "human_pc": self.human_services_pc,

            "birth_rate": actual_birth,
            "death_rate": actual_death,
            "net_growth": actual_birth - actual_death,
            "normal_birth": normal_birth,
            "normal_death": normal_death,
            "birth_mult": birth_mult,
            "death_mult": death_mult,

            "food_available": self.food_available,
            "goods_available": self.goods_available,
            "energy_available": self.energy_available,

            "food_production": produced_food,
            "goods_production": produced_goods,
            "energy_production": produced_energy,

            "food_cu": food_cu,
            "goods_cu": goods_cu,
            "food_mfc": food_mfc,
            "goods_mgc": goods_mgc,
            "energy_eff_mult": self.energy_efficiency_multiplier(),

            "expected_food": expected_food,
            "expected_goods": expected_goods,

            "environment": self.environment,
            "environment_before": environment_before,
            "env_load": environmental_load,
            "env_degradation": annual_degradation,
            "env_regeneration": annual_regeneration,

            "debt": self.debt,
            "interest": fin["interest_due"],
            "interest_paid": fin["interest_paid"],
            "unpaid_interest": fin["unpaid_interest"],
            "annual_interest": fin["annual_interest"],
            "avg_exports": fin["avg_exports"],
            "debt_export_ratio": fin["debt_export_ratio"],
            "import_mult": import_mult,
            "imf": imf_repayment,
            "imf_goods": imf_goods,
            "imf_paid": imf_paid_this_cycle,
            "imf_pending": self.imf_pending,
            "cash_in": fin["cash_in"],
            "import_budget": fin["import_budget"],
            "cash_reserve": self.cash_reserve,
            "new_loans": x["new_loans"],
            "repayments": x["repayments"],
            "foreign_aid": x["foreign_aid"],

            "energy_import": energy_import_units,
            "food_import": food_import_units,
            "goods_import": goods_import_units,

            "export_money": fin["export_money"],
            "import_spending": import_spending,

            "cap_energy_prod": self.cap_energy_prod,
            "cap_energy_eff": self.cap_energy_eff,
            "cap_food": self.cap_food,
            "cap_goods": self.cap_goods,
            "cap_human": self.cap_human,
            "cap_env": self.cap_env,

            "gdp": self.gdp_index,
            "gdp_pc": self.gdp_pc_index,

            "game_over": self.game_over,
            "event": event,
            "scenario": self.scenario,

            **self._ministry_record(health_mult, education_mult, infra_mult, security, infra_energy_mult),
            "exports": {"food": x["food_export"], "goods": x["goods_export"], "energy": x["energy_export"]},
            "imports": {"food": food_import_units, "goods": goods_import_units, "energy": energy_import_units},
        }

    def _ministry_record(self, health_mult, education_mult, infra_mult, security, infra_energy_mult):
        """Ministeriums-Kennzahlen (immer vorhanden; inaktiv 0 bzw. 1.0)."""
        return {
            "cap_health": self.cap_health, "cap_education": self.cap_education,
            "cap_infrastructure": self.cap_infrastructure, "cap_defense": self.cap_defense,
            "security": security, "health_mult": health_mult, "education_mult": education_mult,
            "infra_mult": infra_mult, "infra_energy_mult": infra_energy_mult,
            "defense_labor_share": self.defense_labor_share(),
        }

    def _initial_record(self) -> dict:
        """history[0]: Startzustand (runde 0)."""
        birth = self.birth_rate()
        death = self.death_rate()
        return {
            "runde": 0, "jahr_start": 0, "jahr_end": 0,
            "population": self.population, "labor": self.labor_force,
            "food_pc": self.food_pc, "goods_pc": self.goods_pc, "human_pc": self.human_services_pc,
            "birth_rate": birth, "death_rate": death, "net_growth": birth - death,
            "normal_birth": self.normal_birth_rate(sum(self.goods_pc_history) / 3.0),
            "normal_death": self.normal_death_rate(self.food_pc),
            "birth_mult": self.birth_service_multiplier(), "death_mult": self.death_environment_multiplier(),
            "food_available": self.food_available, "goods_available": self.goods_available,
            "energy_available": self.energy_available,
            "food_production": self.last_food_production, "goods_production": self.last_goods_production,
            "energy_production": self.last_energy_production,
            "food_cu": self.last_food_cu, "goods_cu": self.last_goods_cu,
            "food_mfc": 1.0, "goods_mgc": 1.0,
            "energy_eff_mult": self.energy_efficiency_multiplier(),
            "expected_food": self.last_food_production, "expected_goods": self.last_goods_production,
            "environment": self.environment, "environment_before": self.environment,
            "env_load": 0.0, "env_degradation": 0.0, "env_regeneration": 0.0,
            "debt": self.debt, "interest": 0.0, "interest_paid": 0.0, "unpaid_interest": 0.0,
            "annual_interest": self.current_finance_conditions()[3],
            "avg_exports": self.current_finance_conditions()[0],
            "debt_export_ratio": self.current_finance_conditions()[1],
            "import_mult": self.current_finance_conditions()[2],
            "imf": 0.0, "imf_goods": 0.0, "imf_paid": 0.0, "imf_pending": self.imf_pending,
            "cash_in": 0.0, "import_budget": 0.0, "cash_reserve": self.cash_reserve,
            "new_loans": 0.0, "repayments": 0.0, "foreign_aid": 0.0,
            "energy_import": 0.0, "food_import": 0.0, "goods_import": 0.0,
            "export_money": 0.0, "import_spending": 0.0,
            "cap_energy_prod": self.cap_energy_prod, "cap_energy_eff": self.cap_energy_eff,
            "cap_food": self.cap_food, "cap_goods": self.cap_goods,
            "cap_human": self.cap_human, "cap_env": self.cap_env,
            "gdp": self.gdp_index, "gdp_pc": self.gdp_pc_index,
            "game_over": False,
            "event": None,
            "scenario": self.scenario,
            **self._ministry_record(self.health_multiplier(), self.education_multiplier(),
                                    self.infra_production_multiplier(), self.security(),
                                    self.infra_energy_multiplier()),
            "exports": {"food": 0.0, "goods": 0.0, "energy": 0.0},
            "imports": {"food": 0.0, "goods": 0.0, "energy": 0.0},
        }

    # -------------------------------------------------------------------------
    # Speichern / Laden
    # -------------------------------------------------------------------------

    def to_json(self) -> str:
        return json.dumps({"format": "equivara-engine", "version": 3,
                           "state": self._state(), "undo": self._undo},
                          ensure_ascii=False, sort_keys=True)

    @classmethod
    def from_json(cls, s: str) -> "EquivaraEngine":
        data = json.loads(s)
        if not isinstance(data, dict) or "state" not in data:
            raise ValueError("Ungültige Equivara-Spielstanddatei.")
        eng = cls()
        eng._restore(data["state"])
        eng._undo = list(data.get("undo", []))
        return eng
