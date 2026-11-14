"""STRATAGEM 1 – Simulationsmodell (ohne GUI).

Grundlage: STRATAGEM Version 4.0, Meadows et al.

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

Gegenüber der ursprünglichen Fassung (stratagem1_akkurater.py) umgesetzte
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
import json
import math
from dataclasses import dataclass

__all__ = [
    "INPUT_KEYS", "INPUT_LABELS", "INVEST_KEYS", "DEFAULT_INPUTS",
    "Issue", "StratagemEngine", "clamp", "interp",
]


def clamp(value, low, high):
    return max(low, min(high, value))


def interp(x, points):
    """Lineare Interpolation einer STRATAGEM-Kennlinie."""
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
    """Liefert (werte, ungültige_schlüssel). Fehlende/ungültige Werte = 0."""
    inputs = inputs or {}
    values, bad = {}, []
    for k in INPUT_KEYS:
        v = _parse_number(inputs.get(k)) if isinstance(inputs, dict) else None
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

class StratagemEngine:
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

    def __init__(self):
        self._undo = []
        self.reset()

    # -------------------------------------------------------------------------
    # Zustand
    # -------------------------------------------------------------------------

    def reset(self) -> None:
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
        self.last_inputs = None
        self._undo = []
        self.history = [self._initial_record()]

    def _state(self) -> dict:
        return copy.deepcopy({k: v for k, v in vars(self).items() if k != "_undo"})

    def _restore(self, state: dict) -> None:
        undo = getattr(self, "_undo", [])
        self.__dict__.clear()
        self.__dict__.update(copy.deepcopy(state))
        self._undo = undo

    # -------------------------------------------------------------------------
    # Hilfsfunktionen des Modells
    # -------------------------------------------------------------------------

    @property
    def labor_force(self):
        return 0.25 * self.population

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
        return interp(self.cap_energy_eff / production_capital, self.ENERGY_EFFICIENCY_CURVE)

    def normal_birth_rate(self, average_goods_pc):
        return interp(clamp(average_goods_pc, 0.0, 15.0), self.BIRTH_RATE_CURVE)

    def birth_service_multiplier(self):
        return interp(clamp(self.human_services_pc, 0.0, 20.0), self.BIRTH_SERVICE_MULT_CURVE)

    def normal_death_rate(self, food_pc):
        return interp(clamp(food_pc, 0.0, 5.0), self.DEATH_RATE_CURVE)

    def death_environment_multiplier(self):
        return interp(clamp(self.environment, 0.0, 1.0), self.DEATH_ENV_MULT_CURVE)

    def birth_rate(self):
        return self.normal_birth_rate(sum(self.goods_pc_history) / 3.0) * self.birth_service_multiplier()

    def death_rate(self):
        return self.normal_death_rate(self.food_pc) * self.death_environment_multiplier()

    def energy_production(self):
        return interp(self.cap_energy_prod / 1000.0, self.ENERGY_PRODUCTION_LOW_CURVE) * 1000.0

    def expected_food_production(self, food_mfc=None, food_mfp=None):
        if food_mfc is None:
            food_mfc = 1.0
        if food_mfp is None:
            food_mfp = interp(self.active_food_capital / self.LAND_AREA, self.FOOD_CAPITAL_CURVE)
        return 6250.0 * food_mfc * food_mfp * self.environment

    def expected_goods_production(self, goods_mgc=None):
        if goods_mgc is None:
            goods_mgc = 1.0
        mgp = interp(self.active_goods_capital / max(1.0, self.labor_force), self.GOODS_CAPITAL_CURVE)
        mhs = interp(self.human_services_pc, self.HUMAN_SERVICE_CURVE)
        return 5.775 * self.labor_force * goods_mgc * mgp * mhs

    def full_energy_requirements(self):
        eff = self.energy_efficiency_multiplier()
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
        interest_due = debt * annual_interest / 100.0 * self.CYCLE_YEARS
        max_new_loan = max(0.0, avg_exports - debt)
        export_money = v["energy_export"] + v["food_export"] + v["goods_export"]
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
            v = {k: 0.0 for k in INPUT_KEYS}
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
                       "used": sum(v[k] for k in INVEST_KEYS)},
        }

    def requirements(self) -> dict:
        food_req, goods_req, _ = self.full_energy_requirements()
        fin = self._finance({k: 0.0 for k in INPUT_KEYS})
        return {
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
        }

    def validate(self, inputs: dict) -> list[Issue]:
        """KORREKTUR 1/5: reine Prüfung, verändert nichts am Zustand."""
        issues: list[Issue] = []

        def err(field, msg):
            issues.append(Issue(field, msg, "error"))

        def warn(field, msg):
            issues.append(Issue(field, msg, "warning"))

        if self.game_over:
            err(None, "Das Spiel ist beendet – alle 12 Zyklen (60 Jahre) sind gespielt.")
            return issues

        v, bad = _coerce(inputs)
        for k in bad:
            err(k, f"{INPUT_LABELS[k]}: ungültige oder fehlende Zahl.")
        for k in INPUT_KEYS:
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
        inv_sum = sum(v[k] for k in INVEST_KEYS)
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
        self.last_inputs = dict(v)
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
        zeros = {k: 0.0 for k in INPUT_KEYS}
        if self.game_over:
            return zeros
        if base is None:
            base = self.last_inputs if self.last_inputs is not None else DEFAULT_INPUTS
        v, _ = _coerce(base)
        v = {k: _floor10(max(0.0, x)) for k, x in v.items()}

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
        scale(INVEST_KEYS, v["goods_investment"])
        v["inv_energy_eff"] = min(v["inv_energy_eff"], v["inv_food"] + v["inv_goods"])
        rest = _floor10(v["goods_investment"] - sum(v[k] for k in INVEST_KEYS))
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
    # Hauptsimulation (nur auf validierten Eingaben aufrufen)
    # -------------------------------------------------------------------------

    def _simulate(self, x: dict) -> dict:
        # Finanzrechnung zuerst – reine Funktion des Anfangszustands.
        fin = self._finance(x)

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

        goods_mgp = interp(active_goods_for_output / max(1.0, self.labor_force), self.GOODS_CAPITAL_CURVE)
        goods_mhs = interp(self.human_services_pc, self.HUMAN_SERVICE_CURVE)
        expected_goods = 5.775 * self.labor_force * goods_mgc * goods_mgp * goods_mhs
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
        normal_death = self.normal_death_rate(current_food_pc)
        death_mult = self.death_environment_multiplier()
        actual_death = normal_death * death_mult
        annual_growth = (actual_birth - actual_death) / 1000.0
        self.population = max(1.0, self.population * math.exp(annual_growth * self.CYCLE_YEARS))

        # --- Außenhandel / Schulden (KORREKTUR 2) -----------------------------
        imf_paid_this_cycle = fin["imf_paid"]
        self.imf_pending = 0.0
        import_mult = fin["import_mult"]
        energy_import_units = x["import_energy_money"] / max(0.0001, 1.0 * import_mult)
        food_import_units = x["import_food_money"] / max(0.0001, 1.1 * import_mult)
        goods_import_units = x["import_goods_money"] / max(0.0001, 1.1 * import_mult)
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
        if cycle_finished >= self.TOTAL_CYCLES:
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
        }

    # -------------------------------------------------------------------------
    # Speichern / Laden
    # -------------------------------------------------------------------------

    def to_json(self) -> str:
        return json.dumps({"format": "stratagem-engine", "version": 1,
                           "state": self._state(), "undo": self._undo},
                          ensure_ascii=False, sort_keys=True)

    @classmethod
    def from_json(cls, s: str) -> "StratagemEngine":
        data = json.loads(s)
        if not isinstance(data, dict) or "state" not in data:
            raise ValueError("Ungültige STRATAGEM-Spielstanddatei.")
        eng = cls()
        eng._restore(data["state"])
        eng._undo = list(data.get("undo", []))
        return eng
