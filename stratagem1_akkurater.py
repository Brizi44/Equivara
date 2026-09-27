import math
import tkinter as tk
from tkinter import messagebox, ttk


# =============================================================================
# STRATAGEM 1 - möglichst originalgetreues Modell
# Grundlage: STRATAGEM Version 4.0, Meadows et al.
#
# Wichtige Modellmerkmale:
# - 5 Sektoren
# - 12 Zyklen à 5 Jahre = 60 Jahre
# - 200 Einwohner zu Beginn
# - Kapitalstocks mit unterschiedlichen Lebensdauern
# - Energieeffizienz senkt den Energiebedarf
# - Energieproduktion hat abnehmende Grenzerträge
# - Nahrung hängt von Landproduktivität, Kapital und Umwelt ab
# - Güter hängen von Arbeitskraft, Güterkapital und Humankapital ab
# - Geburtenrate hängt vom Güterkonsum + Humankapital ab
# - Sterberate hängt vom Nahrungskonsum + Umwelt ab
# - Importe wirken erst im nächsten Zyklus
# - Schulden beeinflussen Importpreise und Zinssatz
#
# Die Kurven aus dem Kurzhandbuch sind als lineare Interpolation
# der dort abgebildeten Kennlinien hinterlegt. Dadurch ist das Modell
# wesentlich näher am ursprünglichen STRATAGEM als die vorherige
# vereinfachte Exponential-/Faktorlogik.
# =============================================================================


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


class StratagemEngine:
    CYCLE_YEARS = 5
    TOTAL_CYCLES = 12

    # Lebensdauern der Kapitalstocks in Jahren.
    LIFETIME_ENERGY_PROD = 25
    LIFETIME_ENERGY_EFF = 25
    LIFETIME_FOOD = 25
    LIFETIME_GOODS = 25
    LIFETIME_HUMAN = 45
    LIFETIME_ENV = 30

    # Normale Energieanforderungen pro Kapitaleinheit und Zyklus.
    ENERGY_PER_FOOD_CAP = 12.5
    ENERGY_PER_GOODS_CAP = 20.0

    # Produktionskonstanten aus dem Handbuch.
    LAND_AREA = 1000.0
    LAND_PRODUCTIVITY_NORMAL = 1.25
    GOODS_PRODUCTIVITY_NORMAL = 1.155

    # -------------------------------------------------------------------------
    # Kennlinien aus den Abbildungen des STRATAGEM-Kurzhandbuchs.
    # Die Originalsoftware verwendet glatte Kennlinien; hier werden die
    # veröffentlichten Kurvenpunkte mit linearer Interpolation angenähert.
    # -------------------------------------------------------------------------

    # Abb. 1: normale Geburtenrate [pro 1000/Jahr]
    BIRTH_RATE_CURVE = [
        (0.0, 30.0),
        (3.0, 27.0),
        (6.0, 23.0),
        (9.0, 17.0),
        (12.0, 12.0),
        (15.0, 10.0),
    ]

    # Abb. 2: Geburtenraten-Multiplikator aus Humankapital/Kopf
    BIRTH_SERVICE_MULT_CURVE = [
        (0.0, 1.00),
        (2.5, 1.50),
        (4.0, 1.45),
        (8.0, 1.35),
        (12.0, 1.20),
        (16.0, 1.00),
        (20.0, 1.00),
    ]

    # Abb. 3: normale Sterberate [pro 1000/Jahr]
    DEATH_RATE_CURVE = [
        (0.0, 60.0),
        (1.0, 30.0),
        (2.0, 20.0),
        (3.0, 15.0),
        (4.0, 12.0),
        (5.0, 10.0),
    ]

    # Abb. 4: Sterberaten-Multiplikator aus Umweltqualität
    DEATH_ENV_MULT_CURVE = [
        (0.0, 1.75),
        (0.20, 1.50),
        (0.40, 1.30),
        (0.60, 1.10),
        (0.75, 1.00),
        (1.00, 1.00),
    ]

    # Abb. 5: Energieproduktion pro Zyklus als Funktion des
    # Energieproduktionskapitals. x ist in Tausender-Kapitaleinheiten,
    # y in Tausender-Energieeinheiten.
    ENERGY_PRODUCTION_LOW_CURVE = [
        (0.0, 0.0),
        (0.8, 12.0),
        (1.0, 15.0),
        (2.0, 20.0),
        (4.0, 25.0),
        (6.0, 29.0),
        (8.0, 33.0),
        (10.0, 35.0),
    ]

    # Abb. 6: Energieverbrauchsmultiplikator aus Effizienzkapital /
    # gesamtem Produktionskapital.
    ENERGY_EFFICIENCY_CURVE = [
        (0.0, 1.00),
        (0.10, 0.78),
        (0.20, 0.70),
        (0.40, 0.50),
        (0.60, 0.42),
        (0.80, 0.35),
        (1.00, 0.30),
    ]

    # Abb. 7: Nahrungsproduktions-Multiplikator aus Veränderung
    # des Pro-Kopf-Nahrungskonsums.
    FOOD_CONSUMPTION_CHANGE_CURVE = [
        (0.0, 0.40),
        (0.40, 0.64),
        (0.80, 0.88),
        (1.00, 1.00),
        (2.00, 1.00),
    ]

    # Abb. 8: Landproduktivitäts-Multiplikator aus aktivem
    # Nahrungskapital / verfügbarer landwirtschaftlicher Fläche.
    FOOD_CAPITAL_CURVE = [
        (0.0, 0.0),
        (0.8, 0.8),
        (1.0, 1.0),
        (2.0, 2.0),
        (3.0, 3.0),
        (4.0, 3.8),
        (6.0, 4.5),
        (10.0, 5.0),
    ]

    # Abb. 9: jährliche Umweltdegradation in Prozent.
    ENV_DEGRADATION_CURVE = [
        (0.0, 0.0),
        (0.10, 2.0),
        (0.20, 4.0),
        (0.40, 7.0),
        (0.60, 9.0),
        (0.80, 9.7),
        (1.00, 10.0),
    ]

    # Abb. 10: jährliche Regeneration in Prozentpunkten.
    ENV_REGENERATION_CURVE = [
        (0.0, 0.0),
        (0.10, 0.2),
        (0.20, 1.8),
        (0.40, 4.2),
        (0.50, 5.0),
        (0.60, 4.5),
        (0.80, 2.0),
        (0.90, 0.3),
        (1.00, 0.0),
    ]

    # Abb. 11: Güterproduktions-Multiplikator aus Änderung des
    # Pro-Kopf-Güterkonsums.
    GOODS_CONSUMPTION_CHANGE_CURVE = [
        (0.0, 0.40),
        (0.40, 0.64),
        (0.80, 0.88),
        (1.00, 1.00),
        (2.00, 1.00),
    ]

    # Abb. 12: Arbeitsproduktivitäts-Multiplikator aus aktivem
    # Güterkapital / Arbeitskraft.
    GOODS_CAPITAL_CURVE = [
        (0.0, 0.0),
        (4.0, 5.0),
        (8.0, 9.5),
        (16.0, 13.5),
        (24.0, 16.0),
        (32.0, 18.0),
        (40.0, 20.0),
    ]

    # Abb. 13: Güterproduktions-Multiplikator aus Humankapital/Kopf.
    HUMAN_SERVICE_CURVE = [
        (0.0, 1.0),
        (2.0, 2.0),
        (4.0, 3.0),
        (8.0, 3.8),
        (12.0, 4.3),
        (16.0, 4.65),
        (20.0, 5.0),
    ]

    # Abb. 14: Multiplikator der Importpreise.
    IMPORT_PRICE_MULT_CURVE = [
        (0.0, 1.00),
        (2.0, 1.00),
        (3.0, 1.33),
        (4.0, 1.67),
        (5.0, 2.00),
    ]

    # Abb. 15: Zinssatz pro Jahr in Prozent.
    INTEREST_RATE_CURVE = [
        (0.0, 10.0),
        (1.0, 10.0),
        (2.0, 15.0),
        (3.0, 16.8),
        (4.0, 18.4),
        (5.0, 20.0),
    ]

    def __init__(self):
        self.reset()

    def reset(self):
        self.runde = 1

        # Bevölkerung: STRATAGEM startet mit 200 Personen.
        self.population = 200.0

        # Pro-Kopf-Konsum startet bei 2 Einheiten/Jahr.
        self.food_pc = 2.0
        self.goods_pc = 2.0

        # Ausgangs-Humankapital: 2.25 pro Person -> 450.
        self.cap_human = 450.0

        # Ausgangskapitalstocks aus dem veröffentlichten Beispiel.
        self.cap_energy_prod = 800.0
        self.cap_energy_eff = 0.0
        self.cap_food = 800.0
        self.cap_goods = 300.0
        self.cap_env = 0.0

        # Baustellen / verzögerte Investitionen.
        self.under_energy_prod = [0.0, 0.0]
        self.under_energy_eff = [0.0]
        self.under_food = [0.0]
        self.under_goods = [0.0]
        self.under_human = [0.0]
        self.under_env = [0.0]

        # Anfangsbestände gemäß Beispiel im Kurzhandbuch:
        # Food: 3300, Goods: 3500, Energy: 12000 + 1500 Import + 1000 Carry-over.
        self.food_available = 3300.0
        self.goods_available = 3500.0
        self.energy_available = 14500.0

        # Ausgangsschulden: Standardfall mit 1000 Einheiten.
        self.debt = 1000.0
        # IMF repayment triggered in cycle t is due at the start of t+1.
        self.imf_pending = 0.0

        self.environment = 0.69

        self.last_food_pc = 2.0
        self.last_goods_pc = 2.0

        # Für den 3-Zyklen-Mittelwert der Güterkonsumption.
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

    # -------------------------------------------------------------------------
    # Hilfsfunktionen
    # -------------------------------------------------------------------------

    @property
    def labor_force(self):
        # STRATAGEM: Arbeitskraft = 25 % der Bevölkerung.
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

        ratio = self.cap_energy_eff / production_capital
        return interp(ratio, self.ENERGY_EFFICIENCY_CURVE)

    def normal_birth_rate(self, average_goods_pc):
        return interp(clamp(average_goods_pc, 0.0, 15.0),
                      self.BIRTH_RATE_CURVE)

    def birth_service_multiplier(self):
        return interp(clamp(self.human_services_pc, 0.0, 20.0),
                      self.BIRTH_SERVICE_MULT_CURVE)

    def normal_death_rate(self, food_pc):
        return interp(clamp(food_pc, 0.0, 5.0),
                      self.DEATH_RATE_CURVE)

    def death_environment_multiplier(self):
        return interp(clamp(self.environment, 0.0, 1.0),
                      self.DEATH_ENV_MULT_CURVE)

    def birth_rate(self):
        return self.normal_birth_rate(sum(self.goods_pc_history) / 3.0) * \
            self.birth_service_multiplier()

    def death_rate(self):
        return self.normal_death_rate(self.food_pc) * \
            self.death_environment_multiplier()

    def energy_production(self):
        # Low-output-Variante der veröffentlichten Startkonfiguration.
        x = self.cap_energy_prod / 1000.0
        return interp(x, self.ENERGY_PRODUCTION_LOW_CURVE) * 1000.0

    def expected_food_production(self, food_mfc=None, food_mfp=None):
        if food_mfc is None:
            food_mfc = 1.0
        if food_mfp is None:
            active_ratio = self.active_food_capital / self.LAND_AREA
            food_mfp = interp(active_ratio, self.FOOD_CAPITAL_CURVE)

        # AL * ALPN * 5 = 6250
        return 6250.0 * food_mfc * food_mfp * self.environment

    def expected_goods_production(self, goods_mgc=None):
        if goods_mgc is None:
            goods_mgc = 1.0

        mgp = interp(
            self.active_goods_capital / max(1.0, self.labor_force),
            self.GOODS_CAPITAL_CURVE,
        )
        mhs = interp(
            self.human_services_pc,
            self.HUMAN_SERVICE_CURVE,
        )

        # LPN * 5 = 5.775
        return 5.775 * self.labor_force * goods_mgc * mgp * mhs

    def full_energy_requirements(self):
        eff = self.energy_efficiency_multiplier()
        food_req = self.cap_food * self.ENERGY_PER_FOOD_CAP * eff
        goods_req = self.cap_goods * self.ENERGY_PER_GOODS_CAP * eff
        pop_req = self.goods_pc * self.population * 0.2 / 1.0

        return food_req, goods_req, pop_req

    def current_finance_conditions(self):
        avg_exports = sum(self.avg_exports_history) / \
            len(self.avg_exports_history)

        ratio = self.debt / max(1.0, avg_exports)

        import_mult = interp(
            clamp(ratio, 0.0, 5.0),
            self.IMPORT_PRICE_MULT_CURVE,
        )
        annual_interest = interp(
            clamp(ratio, 0.0, 5.0),
            self.INTEREST_RATE_CURVE,
        )

        return avg_exports, ratio, import_mult, annual_interest

    # -------------------------------------------------------------------------
    # Hauptsimulation
    # -------------------------------------------------------------------------

    def berechne_runde(self, inputs):
        if self.game_over:
            raise ValueError("Das STRATAGEM-Spiel ist bereits beendet.")

        # ---------------------------------------------------------------------
        # Eingaben
        # ---------------------------------------------------------------------
        food_domestic = inputs["food_domestic"]
        food_export = inputs["food_export"]

        goods_domestic = inputs["goods_domestic"]
        goods_export = inputs["goods_export"]
        goods_investment = inputs["goods_investment"]

        energy_food = inputs["energy_food"]
        energy_goods = inputs["energy_goods"]
        energy_export = inputs["energy_export"]
        energy_carryover = inputs["energy_carryover"]

        inv_food = inputs["inv_food"]
        inv_env = inputs["inv_env"]
        inv_goods = inputs["inv_goods"]
        inv_human = inputs["inv_human"]
        inv_energy_prod = inputs["inv_energy_prod"]
        inv_energy_eff = inputs["inv_energy_eff"]

        foreign_aid = inputs["foreign_aid"]
        new_loans = inputs["new_loans"]
        repayments = inputs["repayments"]

        import_energy_money = inputs["import_energy_money"]
        import_food_money = inputs["import_food_money"]
        import_goods_money = inputs["import_goods_money"]

        tol = 1e-7

        values = [
            food_domestic, food_export, goods_domestic, goods_export,
            goods_investment, energy_food, energy_goods, energy_export,
            energy_carryover, inv_food, inv_env, inv_goods, inv_human,
            inv_energy_prod, inv_energy_eff, foreign_aid, new_loans,
            repayments, import_energy_money, import_food_money,
            import_goods_money
        ]

        if any(v < -tol for v in values):
            raise ValueError("Negative Eingaben sind im Originalspiel nicht vorgesehen.")

        # STRATAGEM Input-Sheet: Eingaben als Vielfache von 10.
        for v in values:
            if abs(v / 10.0 - round(v / 10.0)) > 1e-6:
                raise ValueError(
                    "Im STRATAGEM-Eingabebogen sollen alle Werte "
                    "Vielfache von 10 sein."
                )

        # ---------------------------------------------------------------------
        # 1. Bestandsallokation
        # ---------------------------------------------------------------------
        if food_domestic + food_export > self.food_available + tol:
            raise ValueError(
                f"Nahrung überbelegt: verfügbar {self.food_available:.1f}, "
                f"zugeteilt {food_domestic + food_export:.1f}."
            )

        if goods_domestic + goods_export + goods_investment > \
                self.goods_available + tol:
            raise ValueError(
                f"Güter überbelegt: verfügbar {self.goods_available:.1f}, "
                f"zugeteilt {goods_domestic + goods_export + goods_investment:.1f}."
            )

        # Energie für die Bevölkerung ist KEINE freie Entscheidung:
        # 1 Energieeinheit je 5 Gütereinheiten für die Bevölkerung.
        energy_population = goods_domestic / 5.0

        if energy_food + energy_goods + energy_export + energy_carryover + \
                energy_population > self.energy_available + tol:
            raise ValueError(
                f"Energie überbelegt: verfügbar {self.energy_available:.1f}, "
                f"benötigt {energy_food + energy_goods + energy_export + energy_carryover + energy_population:.1f}."
            )

        # Maximal 110 % Kapazitätsauslastung.
        food_full_energy, goods_full_energy, _ = self.full_energy_requirements()
        food_cu = clamp(
            energy_food / max(1.0, food_full_energy),
            0.0,
            1.10,
        )
        goods_cu = clamp(
            energy_goods / max(1.0, goods_full_energy),
            0.0,
            1.10,
        )

        # ---------------------------------------------------------------------
        # 2. Konsum des AKTUELLEN Zyklus
        # ---------------------------------------------------------------------
        # Das Handbuch sagt ausdrücklich, dass die zu Zyklusbeginn getroffene
        # Allokation von Nahrung und Gütern die Bevölkerungsentwicklung und
        # die MFC/MGC-Produktionsmultiplikatoren dieses Zyklus bestimmt.
        current_food_pc = food_domestic / max(1.0, self.population) / 5.0
        current_goods_pc = goods_domestic / max(1.0, self.population) / 5.0

        # Produktionsrückgang bei einer Änderung gegenüber dem letzten Zyklus.
        food_mfc = interp(
            clamp(current_food_pc / max(0.001, self.last_food_pc), 0.0, 2.0),
            self.FOOD_CONSUMPTION_CHANGE_CURVE,
        )

        goods_mgc = interp(
            clamp(current_goods_pc / max(0.001, self.last_goods_pc), 0.0, 2.0),
            self.GOODS_CONSUMPTION_CHANGE_CURVE,
        )

        active_food_for_output = self.cap_food * food_cu
        active_goods_for_output = self.cap_goods * goods_cu

        food_mfp = interp(
            active_food_for_output / self.LAND_AREA,
            self.FOOD_CAPITAL_CURVE,
        )

        expected_food = self.expected_food_production(
            food_mfc=food_mfc,
            food_mfp=food_mfp,
        )
        produced_food = max(0.0, expected_food * food_cu)

        goods_mgp = interp(
            active_goods_for_output / max(1.0, self.labor_force),
            self.GOODS_CAPITAL_CURVE,
        )
        goods_mhs = interp(
            self.human_services_pc,
            self.HUMAN_SERVICE_CURVE,
        )

        expected_goods = (
            5.775
            * self.labor_force
            * goods_mgc
            * goods_mgp
            * goods_mhs
        )
        produced_goods = max(0.0, expected_goods * goods_cu)

        produced_energy = self.energy_production()

        # ---------------------------------------------------------------------
        # 3. Umwelt
        # ---------------------------------------------------------------------
        # Z = aktive Nahrungsproduktion + aktive Güterproduktion
        #     + Energieproduktionskapital.
        z = (
            active_food_for_output
            + active_goods_for_output
            + self.cap_energy_prod
        )

        # Je 1 Einheit Umweltschutzkapital kompensiert 3 Einheiten
        # produktiven Kapitals.
        environmental_load = max(0.0, z - 3.0 * self.cap_env)
        env_curve_x = environmental_load / 20000.0

        annual_degradation = interp(
            clamp(env_curve_x, 0.0, 1.0),
            self.ENV_DEGRADATION_CURVE,
        )

        annual_regeneration = interp(
            clamp(self.environment, 0.0, 1.0),
            self.ENV_REGENERATION_CURVE,
        )

        environment_before = self.environment
        self.environment = clamp(
            self.environment
            + self.CYCLE_YEARS * (
                annual_regeneration / 100.0
                - annual_degradation / 100.0
            ),
            0.05,
            0.95,
        )

        # ---------------------------------------------------------------------
        # 4. Demografie
        # ---------------------------------------------------------------------
        avg_goods_pc = (self.goods_pc_history[-2] + self.goods_pc_history[-1] + current_goods_pc) / 3.0

        normal_birth = self.normal_birth_rate(avg_goods_pc)
        birth_mult = self.birth_service_multiplier()
        actual_birth = normal_birth * birth_mult

        normal_death = self.normal_death_rate(current_food_pc)
        death_mult = self.death_environment_multiplier()
        actual_death = normal_death * death_mult

        annual_growth = (actual_birth - actual_death) / 1000.0

        old_population = self.population

        # Näherung an die kontinuierliche Fünfjahresentwicklung.
        self.population *= math.exp(
            annual_growth * self.CYCLE_YEARS
        )

        self.population = max(1.0, self.population)

        # ---------------------------------------------------------------------
        # 5. Außenhandel / Schulden
        # ---------------------------------------------------------------------
        # IMF intervention triggered in the previous cycle is paid now.
        imf_paid_this_cycle = min(self.imf_pending, self.debt)
        self.debt -= imf_paid_this_cycle
        self.imf_pending = 0.0

        avg_exports, debt_export_ratio, import_mult, annual_interest = \
            self.current_finance_conditions()

        interest_for_cycle = self.debt * annual_interest / 100.0 * \
            self.CYCLE_YEARS

        # Exportpreis laut Handbuch = 1.0.
        export_money = (
            energy_export
            + food_export
            + goods_export
        )

        # Importpreise: Energie 1.0, Nahrung/Güter 1.1,
        # multipliziert mit dem Terms-of-Trade-Multiplikator.
        energy_import_units = (
            import_energy_money
            / max(0.0001, 1.0 * import_mult)
        )
        food_import_units = (
            import_food_money
            / max(0.0001, 1.1 * import_mult)
        )
        goods_import_units = (
            import_goods_money
            / max(0.0001, 1.1 * import_mult)
        )

        import_spending = (
            import_energy_money
            + import_food_money
            + import_goods_money
        )

        # Finanzfluss:
        # Exporte + Hilfe + neue Kredite - Zinsen - Tilgung = Importbudget.
        available_for_imports = (
            export_money
            + foreign_aid
            + new_loans
            - interest_for_cycle
            - repayments
        )

        if available_for_imports < -tol:
            raise ValueError(
                f"Finanzierung reicht nicht aus. Nach Zinsen/Tilgung "
                f"stehen {available_for_imports:.1f} für Importe zur Verfügung."
            )

        if import_spending > available_for_imports + tol:
            raise ValueError(
                f"Importbudget überschritten: verfügbar {available_for_imports:.1f}, "
                f"für Importe benötigt {import_spending:.1f}."
            )

        # Neue Kredite sind nur zulässig, solange die aktuelle Schuld nicht
        # über dem 3-Zyklen-Durchschnitt der Exporte liegt.
        max_new_loan = max(
            0.0,
            avg_exports - self.debt
        )
        if new_loans > max_new_loan + tol:
            raise ValueError(
                f"Zu hoher neuer Kredit. Bei durchschnittlichen Exporten "
                f"von {avg_exports:.1f} und Schulden von {self.debt:.1f} "
                f"sind höchstens {max_new_loan:.1f} neue Kredite zulässig."
            )

        # Tilgung darf die aktuelle Schuld nicht negativ machen.
        repayments = min(repayments, self.debt + interest_for_cycle + new_loans)

        # Schuld nach Zinsen, neuen Krediten und Tilgung.
        new_debt = (
            self.debt
            + interest_for_cycle
            + new_loans
            - repayments
        )

        # IMF intervention is triggered by the END-OF-CYCLE debt condition.
        # The manual specifies that 10% of total goods production is used
        # for repayment at the START of the next cycle.
        gdp_current = produced_food + produced_goods
        imf_repayment = 0.0
        if new_debt > 0.5 * max(1.0, gdp_current):
            imf_repayment = 0.10 * produced_goods
            self.imf_pending = imf_repayment

        self.debt = new_debt

        # ---------------------------------------------------------------------
        # 6. Kapitalstock-Verfall und Investitionsverzögerungen
        # ---------------------------------------------------------------------
        # Produktion wird zuerst mit dem alten Kapital berechnet.
        # Danach erfolgt der Verschleiß. Investitionen kommen zeitversetzt.
        old_cap = {
            "energy_prod": self.cap_energy_prod,
            "energy_eff": self.cap_energy_eff,
            "food": self.cap_food,
            "goods": self.cap_goods,
            "human": self.cap_human,
            "env": self.cap_env,
        }

        # 25 Jahre / 5 Jahre = 20 % pro Zyklus.
        self.cap_energy_prod *= 1.0 - 1.0 / 5.0
        self.cap_energy_eff *= 1.0 - 1.0 / 5.0
        self.cap_food *= 1.0 - 1.0 / 5.0
        self.cap_goods *= 1.0 - 1.0 / 5.0

        # Human Services: 45 Jahre -> 1/9 pro Zyklus.
        self.cap_human *= 1.0 - 1.0 / 9.0

        # Umweltkapital: 30 Jahre -> 1/6 pro Zyklus.
        self.cap_env *= 1.0 - 1.0 / 6.0

        # Baustellen abarbeiten.
        # Energieproduktion benötigt laut STRATAGEM zwei Zyklen bis zur
        # zusätzlichen Energieproduktion.
        energy_prod_ready = self.under_energy_prod.pop(0)
        self.under_energy_prod.append(inv_energy_prod)

        energy_eff_ready = self.under_energy_eff.pop(0)
        self.under_energy_eff.append(inv_energy_eff)

        food_ready = self.under_food.pop(0)
        self.under_food.append(inv_food)

        goods_ready = self.under_goods.pop(0)
        self.under_goods.append(inv_goods)

        human_ready = self.under_human.pop(0)
        self.under_human.append(inv_human)

        env_ready = self.under_env.pop(0)
        self.under_env.append(inv_env)

        self.cap_energy_prod += energy_prod_ready
        self.cap_energy_eff += energy_eff_ready
        self.cap_food += food_ready
        self.cap_goods += goods_ready
        self.cap_human += human_ready
        self.cap_env += env_ready

        # ---------------------------------------------------------------------
        # 7. Verfügbare Bestände für den nächsten Zyklus
        # ---------------------------------------------------------------------
        # Importe werden erst im nächsten Zyklus verfügbar.
        self.food_available = produced_food + food_import_units
        self.goods_available = produced_goods + goods_import_units

        # Energie: Produktion + Import + expliziter Carry-over.
        self.energy_available = (
            produced_energy
            + energy_import_units
            + energy_carryover
        )

        # ---------------------------------------------------------------------
        # 8. Export-/Zins-Historie
        # ---------------------------------------------------------------------
        total_export_units = (
            energy_export
            + food_export
            + goods_export
        )

        self.avg_exports_history.append(total_export_units)
        self.avg_exports_history = self.avg_exports_history[-3:]

        self.total_exports += total_export_units
        self.total_imports += (
            energy_import_units
            + food_import_units
            + goods_import_units
        )
        self.total_interest_paid += interest_for_cycle

        # ---------------------------------------------------------------------
        # 9. Zustände für den nächsten Zyklus
        # ---------------------------------------------------------------------
        self.last_food_pc = self.food_pc
        self.last_goods_pc = self.goods_pc

        # Konsum pro Kopf dieses Zyklus.
        self.food_pc = current_food_pc
        self.goods_pc = current_goods_pc

        self.goods_pc_history.append(self.goods_pc)
        self.goods_pc_history = self.goods_pc_history[-3:]

        self.food_pc_history.append(self.food_pc)
        self.food_pc_history = self.food_pc_history[-3:]

        self.last_food_production = produced_food
        self.last_goods_production = produced_goods
        self.last_energy_production = produced_energy

        self.last_food_cu = food_cu
        self.last_goods_cu = goods_cu

        # GDP-Index: Ausgangs-GDP = 100.
        initial_output = 3300.0 + 3000.0
        self.gdp_index = (
            (produced_food + produced_goods)
            / initial_output
            * 100.0
        )
        self.gdp_pc_index = (
            self.gdp_index
            * 200.0
            / max(1.0, self.population)
        )

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
            "energy_eff_mult": self.energy_efficiency_multiplier(),

            "expected_food": expected_food,
            "expected_goods": expected_goods,

            "environment": self.environment,
            "environment_before": environment_before,
            "env_load": environmental_load,
            "env_degradation": annual_degradation,
            "env_regeneration": annual_regeneration,

            "debt": self.debt,
            "interest": interest_for_cycle,
            "annual_interest": annual_interest,
            "avg_exports": avg_exports,
            "debt_export_ratio": debt_export_ratio,
            "import_mult": import_mult,
            "imf": imf_repayment,
            "imf_paid": imf_paid_this_cycle,
            "imf_pending": self.imf_pending,

            "energy_import": energy_import_units,
            "food_import": food_import_units,
            "goods_import": goods_import_units,

            "export_money": export_money,
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



import tkinter as tk
from tkinter import messagebox, ttk

class StratagemGUI:
    """Modernes, übersichtliches Tkinter-Frontend für die STRATAGEM-Engine."""

    COLORS = {
        "bg": "#0b1220",
        "panel": "#111a2e",
        "panel2": "#17223a",
        "border": "#263653",
        "text": "#e7edf7",
        "muted": "#91a0b8",
        "blue": "#4f8cff",
        "cyan": "#28c7d9",
        "green": "#35c98a",
        "orange": "#f6ad55",
        "red": "#ef6a6a",
        "purple": "#9b7cff",
        "white": "#ffffff",
    }

    def __init__(self, root):
        self.root = root
        self.root.title("STRATAGEM 1  |  System Dynamics Simulation")
        self.root.geometry("1440x900")
        self.root.minsize(1180, 760)
        self.root.configure(bg=self.COLORS["bg"])

        self.engine = StratagemEngine()
        self.vars = {}
        self.graph_data = {"population": [], "debt": [], "environment": []}
        self.current_view = "dashboard"

        self._configure_style()
        self._build_shell()
        self._build_dashboard()
        self._build_inputs()
        self._build_investments()
        self._build_report()
        self._show_view("dashboard")
        self._update_all()

        self.root.bind("<Configure>", self._on_resize)

    # ------------------------------------------------------------------ style
    def _configure_style(self):
        style = ttk.Style(self.root)
        if "clam" in style.theme_names():
            style.theme_use("clam")

        c = self.COLORS
        style.configure("TFrame", background=c["bg"])
        style.configure("Panel.TFrame", background=c["panel"])
        style.configure("TLabel", background=c["bg"], foreground=c["text"], font=("Segoe UI", 10))
        style.configure("Muted.TLabel", background=c["panel"], foreground=c["muted"], font=("Segoe UI", 9))
        style.configure("Title.TLabel", background=c["bg"], foreground=c["text"], font=("Segoe UI", 20, "bold"))
        style.configure("Subtitle.TLabel", background=c["bg"], foreground=c["muted"], font=("Segoe UI", 10))
        style.configure("Card.TFrame", background=c["panel"], relief="flat")
        style.configure("CardTitle.TLabel", background=c["panel"], foreground=c["muted"], font=("Segoe UI", 9, "bold"))
        style.configure("CardValue.TLabel", background=c["panel"], foreground=c["text"], font=("Segoe UI", 18, "bold"))
        style.configure("Section.TLabel", background=c["panel2"], foreground=c["text"], font=("Segoe UI", 11, "bold"))
        style.configure("TNotebook", background=c["bg"], borderwidth=0)
        style.configure("TNotebook.Tab", background=c["panel2"], foreground=c["muted"], padding=(14, 8), font=("Segoe UI", 10, "bold"))
        style.map("TNotebook.Tab", background=[("selected", c["blue"])], foreground=[("selected", c["white"])])
        style.configure("TButton", background=c["panel2"], foreground=c["text"], borderwidth=0, padding=(12, 8), font=("Segoe UI", 10, "bold"))
        style.map("TButton", background=[("active", "#233453")])
        style.configure("Accent.TButton", background=c["blue"], foreground=c["white"], borderwidth=0, padding=(16, 10), font=("Segoe UI", 10, "bold"))
        style.map("Accent.TButton", background=[("active", "#6b9fff")])
        style.configure("Danger.TButton", background="#7f2d36", foreground=c["white"], borderwidth=0, padding=(12, 8), font=("Segoe UI", 10, "bold"))
        style.configure("TEntry", fieldbackground="#0f1729", foreground=c["text"], insertcolor=c["text"], bordercolor=c["border"], padding=6)
        style.configure("TSpinbox", fieldbackground="#0f1729", foreground=c["text"], insertcolor=c["text"], bordercolor=c["border"], padding=5)
        style.configure("Horizontal.TProgressbar", background=c["blue"], troughcolor="#0d1525", borderwidth=0, thickness=7)

    # ------------------------------------------------------------------ shell
    def _build_shell(self):
        self.sidebar = tk.Frame(self.root, bg="#0a101c", width=230)
        self.sidebar.pack(side=tk.LEFT, fill=tk.Y)
        self.sidebar.pack_propagate(False)

        brand = tk.Frame(self.sidebar, bg="#0a101c")
        brand.pack(fill=tk.X, padx=22, pady=(24, 25))
        tk.Label(brand, text="STRATAGEM", bg="#0a101c", fg=self.COLORS["text"], font=("Segoe UI", 21, "bold")).pack(anchor="w")
        tk.Label(brand, text="SYSTEM DYNAMICS  •  1", bg="#0a101c", fg=self.COLORS["blue"], font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(2, 0))

        self.nav_buttons = {}
        for key, label in [
            ("dashboard", "Dashboard"),
            ("inputs", "Sektoren & Ressourcen"),
            ("invest", "Investitionsplanung"),
            ("report", "Rundenbericht"),
        ]:
            b = tk.Button(
                self.sidebar, text=label, anchor="w", relief="flat", bd=0,
                bg="#0a101c", fg=self.COLORS["muted"], activebackground="#17243d",
                activeforeground=self.COLORS["text"], font=("Segoe UI", 10, "bold"),
                padx=22, pady=11, cursor="hand2", command=lambda k=key: self._show_view(k)
            )
            b.pack(fill=tk.X, padx=10, pady=2)
            self.nav_buttons[key] = b

        tk.Frame(self.sidebar, bg="#0a101c").pack(fill=tk.BOTH, expand=True)
        tk.Label(self.sidebar, text="12 ZYKLEN  •  60 JAHRE", bg="#0a101c", fg="#52617a", font=("Segoe UI", 8, "bold")).pack(anchor="w", padx=22, pady=(0, 6))
        tk.Label(self.sidebar, text="Meadows et al.", bg="#0a101c", fg="#52617a", font=("Segoe UI", 8)).pack(anchor="w", padx=22, pady=(0, 20))

        self.main = tk.Frame(self.root, bg=self.COLORS["bg"])
        self.main.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.header = tk.Frame(self.main, bg=self.COLORS["bg"], height=82)
        self.header.pack(fill=tk.X, padx=30, pady=(20, 0))
        self.header.pack_propagate(False)

        left = tk.Frame(self.header, bg=self.COLORS["bg"])
        left.pack(side=tk.LEFT, fill=tk.Y)
        self.page_title = tk.Label(left, text="Dashboard", bg=self.COLORS["bg"], fg=self.COLORS["text"], font=("Segoe UI", 22, "bold"))
        self.page_title.pack(anchor="w")
        self.page_subtitle = tk.Label(left, text="Aktueller Zustand des Landes", bg=self.COLORS["bg"], fg=self.COLORS["muted"], font=("Segoe UI", 10))
        self.page_subtitle.pack(anchor="w", pady=(1, 0))

        right = tk.Frame(self.header, bg=self.COLORS["bg"])
        right.pack(side=tk.RIGHT, fill=tk.Y)
        self.cycle_label = tk.Label(right, text="ZYKLUS 1 / 12", bg="#16243c", fg=self.COLORS["blue"], font=("Consolas", 10, "bold"), padx=14, pady=7)
        self.cycle_label.pack(anchor="e", pady=(4, 7))
        self.year_label = tk.Label(right, text="Jahr 0–5", bg=self.COLORS["bg"], fg=self.COLORS["muted"], font=("Segoe UI", 9))
        self.year_label.pack(anchor="e")

        self.content = tk.Frame(self.main, bg=self.COLORS["bg"])
        self.content.pack(fill=tk.BOTH, expand=True, padx=30, pady=(0, 25))

        self.views = {}

    def _new_view(self, key):
        frame = tk.Frame(self.content, bg=self.COLORS["bg"])
        self.views[key] = frame
        return frame

    def _show_view(self, key):
        if key not in self.views:
            return
        for f in self.views.values():
            f.pack_forget()
        self.views[key].pack(fill=tk.BOTH, expand=True)
        titles = {
            "dashboard": ("Dashboard", "Aktueller Zustand des Landes"),
            "inputs": ("Sektoren & Ressourcen", "Verteile Nahrung, Güter, Energie und Handel"),
            "invest": ("Investitionsplanung", "Verteile das Investitionsbudget auf die sechs Kapitalstöcke"),
            "report": ("Rundenbericht", "Detaillierte Modellresultate und Entwicklung"),
        }
        self.page_title.config(text=titles[key][0])
        self.page_subtitle.config(text=titles[key][1])
        for k, b in self.nav_buttons.items():
            if k == key:
                b.config(bg="#17243d", fg=self.COLORS["text"])
            else:
                b.config(bg="#0a101c", fg=self.COLORS["muted"])
        self.current_view = key

    # --------------------------------------------------------------- helpers
    def _card(self, parent, title, value="—", accent=None):
        f = tk.Frame(parent, bg=self.COLORS["panel"], highlightthickness=1, highlightbackground=self.COLORS["border"])
        tk.Label(f, text=title.upper(), bg=self.COLORS["panel"], fg=self.COLORS["muted"], font=("Segoe UI", 8, "bold")).pack(anchor="w", padx=14, pady=(12, 3))
        v = tk.Label(f, text=value, bg=self.COLORS["panel"], fg=accent or self.COLORS["text"], font=("Segoe UI", 18, "bold"))
        v.pack(anchor="w", padx=14, pady=(0, 12))
        return f, v

    def _section(self, parent, title, subtitle=None):
        f = tk.Frame(parent, bg=self.COLORS["panel"], highlightthickness=1, highlightbackground=self.COLORS["border"])
        tk.Label(f, text=title, bg=self.COLORS["panel"], fg=self.COLORS["text"], font=("Segoe UI", 12, "bold")).grid(row=0, column=0, sticky="w", padx=16, pady=(14, 2))
        if subtitle:
            tk.Label(f, text=subtitle, bg=self.COLORS["panel"], fg=self.COLORS["muted"], font=("Segoe UI", 9)).grid(row=1, column=0, sticky="w", padx=16, pady=(0, 10))
        f.grid_columnconfigure(0, weight=1)
        return f

    def _entry(self, parent, key, label, default, row, unit=""):
        tk.Label(parent, text=label, bg=self.COLORS["panel"], fg=self.COLORS["text"], font=("Segoe UI", 9)).grid(row=row, column=0, sticky="w", padx=(16, 8), pady=7)
        var = tk.StringVar(value=str(default))
        self.vars[key] = var
        e = ttk.Entry(parent, textvariable=var, width=13, justify="right")
        e.grid(row=row, column=1, sticky="e", padx=(4, 4), pady=7)
        if unit:
            tk.Label(parent, text=unit, bg=self.COLORS["panel"], fg=self.COLORS["muted"], font=("Segoe UI", 8)).grid(row=row, column=2, sticky="w", padx=(0, 16))
        return e

    def _spin(self, parent, key, label, default, row, unit="", from_=0, to=100000):
        tk.Label(parent, text=label, bg=self.COLORS["panel"], fg=self.COLORS["text"], font=("Segoe UI", 9)).grid(row=row, column=0, sticky="w", padx=(16, 8), pady=7)
        var = tk.StringVar(value=str(default))
        self.vars[key] = var
        sp = ttk.Spinbox(parent, from_=from_, to=to, increment=25, textvariable=var, width=13, justify="right")
        sp.grid(row=row, column=1, sticky="e", padx=4, pady=7)
        if unit:
            tk.Label(parent, text=unit, bg=self.COLORS["panel"], fg=self.COLORS["muted"], font=("Segoe UI", 8)).grid(row=row, column=2, sticky="w", padx=(0, 16))
        return sp

    # ------------------------------------------------------------- dashboard
    def _build_dashboard(self):
        f = self._new_view("dashboard")
        cards = tk.Frame(f, bg=self.COLORS["bg"])
        cards.pack(fill=tk.X, pady=(0, 16))
        for i in range(5):
            cards.columnconfigure(i, weight=1)
        self.card_population, self.val_population = self._card(cards, "Bevölkerung", accent=self.COLORS["blue"])
        self.card_food, self.val_food = self._card(cards, "Nahrung", accent=self.COLORS["orange"])
        self.card_goods, self.val_goods = self._card(cards, "Güter", accent=self.COLORS["purple"])
        self.card_energy, self.val_energy = self._card(cards, "Energie", accent=self.COLORS["cyan"])
        self.card_env, self.val_env = self._card(cards, "Umwelt", accent=self.COLORS["green"])
        for i, card in enumerate([self.card_population, self.card_food, self.card_goods, self.card_energy, self.card_env]):
            card.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 6, 0 if i == 4 else 6))

        lower = tk.Frame(f, bg=self.COLORS["bg"])
        lower.pack(fill=tk.BOTH, expand=True)
        lower.columnconfigure(0, weight=3)
        lower.columnconfigure(1, weight=1)
        lower.rowconfigure(0, weight=1)

        graph = self._section(lower, "Entwicklung", "Historischer Verlauf der drei wichtigsten Systemindikatoren")
        graph.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        graph.rowconfigure(2, weight=1)
        graph.columnconfigure(0, weight=1)
        self.graph_canvas = tk.Canvas(graph, bg=self.COLORS["panel"], highlightthickness=0)
        self.graph_canvas.grid(row=2, column=0, sticky="nsew", padx=12, pady=(4, 12))

        side = self._section(lower, "Systemstatus", "Modellwerte am Ende des letzten Zyklus")
        side.grid(row=0, column=1, sticky="nsew")
        side.rowconfigure(2, weight=1)
        side.columnconfigure(0, weight=1)
        self.status_text = tk.Label(side, text="", justify="left", anchor="nw", bg=self.COLORS["panel"], fg=self.COLORS["text"], font=("Consolas", 10), padx=16, pady=8)
        self.status_text.grid(row=2, column=0, sticky="nsew")

        action = tk.Frame(side, bg=self.COLORS["panel"])
        action.grid(row=3, column=0, sticky="ew", padx=14, pady=(0, 14))
        ttk.Button(action, text="Runde auswerten", style="Accent.TButton", command=self.next_round).grid(sticky="ew")

    # --------------------------------------------------------------- inputs
    def _build_inputs(self):
        f = self._new_view("inputs")
        canvas = tk.Canvas(f, bg=self.COLORS["bg"], highlightthickness=0)
        scroll = ttk.Scrollbar(f, orient="vertical", command=canvas.yview)
        inner = tk.Frame(canvas, bg=self.COLORS["bg"])
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=scroll.set)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)

        inner.columnconfigure(0, weight=1)
        inner.columnconfigure(1, weight=1)

        a = self._section(inner, "01  Bevölkerung & Konsum", "Bestimme den realen Konsum und die verfügbaren Investitionsgüter.")
        a.grid(row=0, column=0, sticky="new", padx=(0, 7), pady=(0, 10))
        self._entry(a, "food_domestic", "Nahrung Bevölkerung", 2000, 0, "NW")
        self._entry(a, "goods_domestic", "Güter Bevölkerung", 2000, 1, "GW")
        self._entry(a, "goods_investment", "Güter für Investitionen", 1500, 2, "GW")
        tk.Label(a, text="Die Bevölkerungsenergie wird automatisch mit 1/5 der Gütermenge berechnet.", bg=self.COLORS["panel"], fg=self.COLORS["muted"], font=("Segoe UI", 8), wraplength=420, justify="left").grid(row=3, column=0, columnspan=3, sticky="w", padx=16, pady=(3, 14))

        b = self._section(inner, "02  Energie", "Verteile die verfügbare Energie auf Produktion und Reserve.")
        b.grid(row=1, column=0, sticky="new", padx=(0, 7), pady=10)
        self._entry(b, "energy_food", "Energie → Nahrung", 8500, 0, "EW")
        self._entry(b, "energy_goods", "Energie → Güter", 5000, 1, "EW")
        self._entry(b, "energy_carryover", "Carry-over", 600, 2, "EW")

        c = self._section(inner, "03  Internationaler Handel", "Exporte, Importe, Hilfe und Verschuldung.")
        c.grid(row=0, column=1, sticky="new", padx=(7, 0), pady=(0, 10))
        self._entry(c, "food_export", "Nahrung Export", 1000, 0, "NW")
        self._entry(c, "goods_export", "Güter Export", 0, 1, "GW")
        self._entry(c, "energy_export", "Energie Export", 0, 2, "EW")
        tk.Frame(c, bg=self.COLORS["border"], height=1).grid(row=3, column=0, columnspan=3, sticky="ew", padx=16, pady=8)
        self._entry(c, "import_food_money", "Importbudget Nahrung", 0, 4, "Geldeinheiten")
        self._entry(c, "import_goods_money", "Importbudget Güter", 0, 5, "Geldeinheiten")
        self._entry(c, "import_energy_money", "Importbudget Energie", 0, 6, "Geldeinheiten")
        self._entry(c, "foreign_aid", "Auslandshilfe", 0, 7, "Geldeinheiten")
        self._entry(c, "new_loans", "Neue Kredite", 0, 8, "Geldeinheiten")
        self._entry(c, "repayments", "Tilgung", 0, 9, "Geldeinheiten")

        hint = self._section(inner, "Hinweise zur Eingabe", "STRATAGEM-Entscheidungen werden vor jeder Runde automatisch geprüft.")
        hint.grid(row=1, column=1, sticky="new", padx=(7, 0), pady=10)
        hint.columnconfigure(0, weight=1)
        tk.Label(hint, text="• Werte müssen Vielfache von 10 sein\n• Keine negativen Mengen\n• Ressourcen dürfen nicht überbelegt werden\n• Investitionen werden über das Investitions-Board verteilt\n• Importe stehen erst im folgenden Zyklus zur Verfügung", bg=self.COLORS["panel"], fg=self.COLORS["muted"], justify="left", anchor="nw", font=("Segoe UI", 9), wraplength=360).grid(row=2, column=0, sticky="ew", padx=16, pady=(6, 16))

        bar = tk.Frame(f, bg=self.COLORS["bg"])
        bar.pack(fill=tk.X, pady=(10, 0))
        ttk.Button(bar, text="Investitionsplanung →", style="Accent.TButton", command=lambda: self._show_view("invest")).pack(side=tk.RIGHT)

    # ------------------------------------------------------------- investments
    def _build_investments(self):
        f = self._new_view("invest")
        top = tk.Frame(f, bg=self.COLORS["bg"])
        top.pack(fill=tk.X, pady=(0, 12))
        self.budget_label = tk.Label(top, text="Budget: 1'500", bg=self.COLORS["bg"], fg=self.COLORS["text"], font=("Segoe UI", 16, "bold"))
        self.budget_label.pack(side=tk.LEFT)
        self.remaining_label = tk.Label(top, text="Frei: 0", bg=self.COLORS["bg"], fg=self.COLORS["green"], font=("Consolas", 12, "bold"))
        self.remaining_label.pack(side=tk.RIGHT)

        grid = tk.Frame(f, bg=self.COLORS["bg"])
        grid.pack(fill=tk.BOTH, expand=True)
        for i in range(3):
            grid.columnconfigure(i, weight=1)
        for i in range(2):
            grid.rowconfigure(i, weight=1)

        self.invest_widgets = []
        defs = [
            ("inv_food", "Nahrungskapital", "Produktivität der Landwirtschaft", self.COLORS["orange"], 300),
            ("inv_env", "Umweltschutz", "Reduziert Umweltbelastung", self.COLORS["green"], 200),
            ("inv_goods", "Güterkapital", "Produktive Güterkapazität", self.COLORS["blue"], 300),
            ("inv_human", "Human Services", "Produktivität & Demografie", self.COLORS["purple"], 200),
            ("inv_energy_prod", "Energieproduktion", "Neue Energieproduktionskapazität", self.COLORS["red"], 300),
            ("inv_energy_eff", "Energieeffizienz", "Senkt Energiebedarf", self.COLORS["cyan"], 200),
        ]
        for i, (key, title, desc, color, default) in enumerate(defs):
            card = tk.Frame(grid, bg=self.COLORS["panel"], highlightthickness=1, highlightbackground=self.COLORS["border"])
            card.grid(row=i // 3, column=i % 3, sticky="nsew", padx=5, pady=5)
            tk.Frame(card, bg=color, height=4).pack(fill=tk.X)
            tk.Label(card, text=title, bg=self.COLORS["panel"], fg=self.COLORS["text"], font=("Segoe UI", 12, "bold")).pack(anchor="w", padx=15, pady=(13, 2))
            tk.Label(card, text=desc, bg=self.COLORS["panel"], fg=self.COLORS["muted"], font=("Segoe UI", 8), wraplength=250, justify="left").pack(anchor="w", padx=15)
            var = tk.StringVar(value=str(default))
            self.vars[key] = var
            spin = ttk.Spinbox(card, from_=0, to=100000, increment=25, textvariable=var, width=12, justify="right", command=self._update_investment_budget)
            spin.pack(anchor="w", padx=15, pady=(12, 15))
            spin.bind("<KeyRelease>", lambda e: self._update_investment_budget())
            self.invest_widgets.append(spin)

        bottom = tk.Frame(f, bg=self.COLORS["panel"], highlightthickness=1, highlightbackground=self.COLORS["border"])
        bottom.pack(fill=tk.X, pady=(12, 0))
        self.invest_hint = tk.Label(bottom, text="", bg=self.COLORS["panel"], fg=self.COLORS["muted"], font=("Segoe UI", 9), justify="left")
        self.invest_hint.pack(side=tk.LEFT, padx=16, pady=13)
        ttk.Button(bottom, text="Runde auswerten", style="Accent.TButton", command=self.next_round).pack(side=tk.RIGHT, padx=12, pady=9)

    def _update_investment_budget(self):
        try:
            budget = float(self.vars.get("goods_investment", tk.StringVar(value="0")).get())
            keys = ["inv_food", "inv_env", "inv_goods", "inv_human", "inv_energy_prod", "inv_energy_eff"]
            used = sum(float(self.vars[k].get()) for k in keys)
            remaining = budget - used
            self.budget_label.config(text=f"Budget: {budget:,.0f}")
            self.remaining_label.config(text=f"Frei: {remaining:,.0f}", fg=self.COLORS["green"] if remaining >= 0 else self.COLORS["red"])
            if "inv_energy_eff" in self.vars:
                eff = float(self.vars["inv_energy_eff"].get())
                food = float(self.vars["inv_food"].get())
                goods = float(self.vars["inv_goods"].get())
                if eff > food + goods:
                    self.invest_hint.config(text="Warnung: Energieeffizienz-Investition überschreitet Nahrung + Güterkapital.", fg=self.COLORS["red"])
                elif remaining < 0:
                    self.invest_hint.config(text="Warnung: Investitionsbudget überschritten.", fg=self.COLORS["red"])
                else:
                    self.invest_hint.config(text="Alle Investitionen werden vor dem nächsten Zyklus geprüft. Energieproduktionskapital wirkt verzögert.", fg=self.COLORS["muted"])
        except (ValueError, KeyError):
            self.remaining_label.config(text="Frei: —", fg=self.COLORS["muted"])

    # ---------------------------------------------------------------- report
    def _build_report(self):
        f = self._new_view("report")
        top = tk.Frame(f, bg=self.COLORS["bg"])
        top.pack(fill=tk.X, pady=(0, 8))
        ttk.Button(top, text="Bericht leeren", command=lambda: self.log.delete("1.0", tk.END)).pack(side=tk.RIGHT)
        box = tk.Frame(f, bg=self.COLORS["panel"], highlightthickness=1, highlightbackground=self.COLORS["border"])
        box.pack(fill=tk.BOTH, expand=True)
        self.log = tk.Text(box, bg="#0d1525", fg="#cbd5e1", insertbackground="#ffffff", selectbackground="#284a80", font=("Consolas", 10), relief="flat", wrap="none", padx=18, pady=16)
        sy = ttk.Scrollbar(box, orient="vertical", command=self.log.yview)
        sx = ttk.Scrollbar(box, orient="horizontal", command=self.log.xview)
        self.log.configure(yscrollcommand=sy.set, xscrollcommand=sx.set)
        self.log.grid(row=0, column=0, sticky="nsew")
        sy.grid(row=0, column=1, sticky="ns")
        sx.grid(row=1, column=0, sticky="ew")
        box.rowconfigure(0, weight=1)
        box.columnconfigure(0, weight=1)
        self._write_initial_report()

    # -------------------------------------------------------------- simulation
    def _read_float(self, key):
        try:
            return float(self.vars[key].get().replace("'", "").replace(",", "."))
        except (ValueError, KeyError):
            raise ValueError(f"Ungültige Eingabe bei '{key}'.")

    def read_inputs(self):
        keys = [
            "food_domestic", "food_export", "goods_domestic", "goods_export", "goods_investment",
            "energy_food", "energy_goods", "energy_export", "energy_carryover",
            "inv_food", "inv_env", "inv_goods", "inv_human", "inv_energy_prod", "inv_energy_eff",
            "foreign_aid", "new_loans", "repayments", "import_energy_money", "import_food_money", "import_goods_money"
        ]
        return {k: self._read_float(k) for k in keys}

    def _validate_inputs(self, x):
        for key, value in x.items():
            if value < -1e-9:
                raise ValueError(f"'{key}' darf nicht negativ sein.")
            if abs(value / 10.0 - round(value / 10.0)) > 1e-7:
                raise ValueError(f"'{key}' muss ein Vielfaches von 10 sein.")

        total_inv = sum(x[k] for k in ["inv_food", "inv_env", "inv_goods", "inv_human", "inv_energy_prod", "inv_energy_eff"])
        if total_inv > x["goods_investment"] + 1e-7:
            raise ValueError(f"Investitionen übersteigen das Budget um {total_inv - x['goods_investment']:.0f}.")
        if x["inv_energy_eff"] > x["inv_food"] + x["inv_goods"] + 1e-7:
            raise ValueError("Energieeffizienz-Investition darf höchstens Nahrungskapital + Güterkapital betragen.")

    def next_round(self):
        if self.engine.game_over:
            messagebox.showinfo("STRATAGEM", "Die 12 Zyklen / 60 Jahre sind abgeschlossen.")
            return
        try:
            x = self.read_inputs()
            self._validate_inputs(x)
            result = self.engine.berechne_runde(x)
        except ValueError as exc:
            messagebox.showerror("Entscheidung nicht zulässig", str(exc))
            return
        self.graph_data["population"].append(result["population"])
        self.graph_data["debt"].append(result["debt"])
        self.graph_data["environment"].append(result["environment"])
        self.log.insert(tk.END, self._format_report(result))
        self.log.see(tk.END)
        self._update_all()
        self._show_view("dashboard")
        if result["game_over"]:
            messagebox.showinfo("STRATAGEM abgeschlossen", "60 Jahre / 12 Zyklen sind abgeschlossen.")

    def reset_game(self):
        if not messagebox.askyesno("Simulation zurücksetzen", "Alle bisherigen Runden werden gelöscht. Fortfahren?"):
            return
        self.engine.reset()
        self.graph_data = {"population": [], "debt": [], "environment": []}
        defaults = {
            "food_domestic": 2000, "food_export": 1000, "goods_domestic": 2000, "goods_export": 0, "goods_investment": 1500,
            "energy_food": 8500, "energy_goods": 5000, "energy_export": 0, "energy_carryover": 600,
            "inv_food": 300, "inv_env": 200, "inv_goods": 300, "inv_human": 200, "inv_energy_prod": 300, "inv_energy_eff": 200,
            "foreign_aid": 0, "new_loans": 0, "repayments": 0, "import_energy_money": 0, "import_food_money": 0, "import_goods_money": 0,
        }
        for k, v in defaults.items():
            if k in self.vars:
                self.vars[k].set(str(v))
        self._write_initial_report()
        self._update_all()
        self._show_view("dashboard")

    # -------------------------------------------------------------- dashboard
    def _update_all(self):
        e = self.engine
        cycle = min(e.runde, 12)
        self.cycle_label.config(text=f"ZYKLUS {cycle} / 12")
        self.year_label.config(text=f"Jahr {(cycle - 1) * 5}–{min(cycle * 5, 60)}")
        self.val_population.config(text=f"{e.population:,.1f}")
        self.val_food.config(text=f"{e.food_available:,.0f}")
        self.val_goods.config(text=f"{e.goods_available:,.0f}")
        self.val_energy.config(text=f"{e.energy_available:,.0f}")
        self.val_env.config(text=f"{e.environment * 100:.1f}%")
        self.status_text.config(text=(
            f"BEVÖLKERUNG\n  {e.population:,.1f}\n\n"
            f"ARBEITSKRÄFTE\n  {e.labor_force:,.1f}\n\n"
            f"SCHULDEN\n  {e.debt:,.1f}\n\n"
            f"GDP-INDEX\n  {e.gdp_index:,.1f}\n\n"
            f"UMWELT\n  {e.environment * 100:.1f}%"
        ))
        self._update_investment_budget()
        self.draw_graph()

    def draw_graph(self):
        if not hasattr(self, "graph_canvas"):
            return
        gc = self.graph_canvas
        gc.delete("all")
        gc.update_idletasks()
        w = max(500, gc.winfo_width())
        h = max(300, gc.winfo_height())
        left, top, right, bottom = 48, 24, w - 24, h - 38
        gc.create_rectangle(left, top, right, bottom, outline=self.COLORS["border"], fill="#0e1728")
        for i in range(5):
            y = top + i * (bottom - top) / 4
            gc.create_line(left, y, right, y, fill="#1c2940")
        if not self.graph_data["population"]:
            gc.create_text((left + right) / 2, (top + bottom) / 2, text="Noch keine Runden simuliert", fill=self.COLORS["muted"], font=("Segoe UI", 11))
            return

        series = [
            (self.graph_data["population"], self.COLORS["blue"], "Bevölkerung"),
            (self.graph_data["debt"], self.COLORS["red"], "Schulden"),
            ([v * 100 for v in self.graph_data["environment"]], self.COLORS["green"], "Umwelt %"),
        ]
        for values, color, label in series:
            if not values:
                continue
            vmax = max(values) or 1
            vmin = min(values)
            # Separate normalization makes all three trends readable.
            points = []
            for i, value in enumerate(values):
                x = left + (i / max(1, len(values) - 1)) * (right - left)
                y = bottom - ((value - vmin) / max(1e-9, vmax - vmin)) * (bottom - top - 10) - 5
                points.append((x, y))
            if len(points) > 1:
                gc.create_line(*[coord for p in points for coord in p], fill=color, width=2, smooth=True)
            for x, y in points:
                gc.create_oval(x - 3, y - 3, x + 3, y + 3, fill=color, outline=color)
            lx = right - 105
            ly = top + 18 + series.index((values, color, label)) * 20
            gc.create_line(lx, ly, lx + 18, ly, fill=color, width=3)
            gc.create_text(lx + 24, ly, text=label, anchor="w", fill=self.COLORS["muted"], font=("Segoe UI", 8, "bold"))

        for i in range(len(self.graph_data["population"])):
            x = left + (i / max(1, len(self.graph_data["population"]) - 1)) * (right - left)
            gc.create_text(x, bottom + 16, text=str((i + 1) * 5), fill="#61718a", font=("Consolas", 8))

    def _on_resize(self, event):
        if event.widget is self.root:
            self.root.after_idle(self.draw_graph)

    # -------------------------------------------------------------- reporting
    def _write_initial_report(self):
        if not hasattr(self, "log"):
            return
        e = self.engine
        self.log.delete("1.0", tk.END)
        self.log.insert(tk.END, f"""
================================================================================
 STRATAGEM 1  |  AUSGANGSZUSTAND
================================================================================
 Zyklus 0 / Jahr 0

 BEVÖLKERUNG                 {e.population:,.1f}
 ARBEITSKRÄFTE               {e.labor_force:,.1f}
 NAHRUNG / KOPF              {e.food_pc:.2f}
 GÜTER / KOPF                {e.goods_pc:.2f}
 HUMAN SERVICES / KOPF       {e.human_services_pc:.2f}

 BESTÄNDE
 Nahrung                     {e.food_available:,.1f}
 Güter                       {e.goods_available:,.1f}
 Energie                     {e.energy_available:,.1f}

 KAPITALSTOCKS
 Energieproduktion           {e.cap_energy_prod:,.1f}
 Energieeffizienz            {e.cap_energy_eff:,.1f}
 Nahrung                     {e.cap_food:,.1f}
 Güter                       {e.cap_goods:,.1f}
 Human Services              {e.cap_human:,.1f}
 Umweltschutz                {e.cap_env:,.1f}
 Umweltqualität              {e.environment * 100:.1f}%

 SCHULDEN                    {e.debt:,.1f}

Hinweis: Investitionen werden gemäß den eingebauten Verzögerungen erst
in späteren Zyklen wirksam. Die Originalkurven sind hier als interpolierte
Kennlinien des veröffentlichten STRATAGEM-Modells implementiert.
================================================================================
""")

    def _format_report(self, r):
        return f"""
================================================================================
 STRATAGEM 1  |  RUNDENBERICHT {r['runde']:02d}   |   JAHR {r['jahr_start']:02d}–{r['jahr_end']:02d}
================================================================================

 DEMOGRAFIE
 Bevölkerung                 {r['population']:,.2f}
 Arbeitskräfte               {r['labor']:,.2f}
 Nahrung / Kopf / Jahr       {r['food_pc']:,.2f}
 Güter / Kopf / Jahr         {r['goods_pc']:,.2f}
 Geburtenrate                {r['birth_rate']:,.2f} / 1000 / Jahr
 Sterberate                  {r['death_rate']:,.2f} / 1000 / Jahr

 PRODUKTION
 Energieproduktion           {r['energy_production']:,.2f}
 Nahrungproduktion           {r['food_production']:,.2f}
 Güterproduktion             {r['goods_production']:,.2f}
 Energie-Auslastung Nahrung  {r['food_cu'] * 100:,.1f}%
 Energie-Auslastung Güter    {r['goods_cu'] * 100:,.1f}%

 UMWELT
 Umweltqualität              {r['environment'] * 100:,.2f}%
 Belastung                   {r['env_load']:,.2f}
 Degradation / Jahr          {r['env_degradation']:,.2f}%
 Regeneration / Jahr         {r['env_regeneration']:,.2f}%

 FINANZEN
 Exporterlöse                {r['export_money']:,.2f}
 Importausgaben              {r['import_spending']:,.2f}
 Importpreis-Multiplikator   {r['import_mult']:,.3f}
 Zinssatz                    {r['annual_interest']:,.2f}% / Jahr
 Zinsen                      {r['interest']:,.2f}
 Schulden                    {r['debt']:,.2f}
 IMF-Rückzahlung             {r['imf']:,.2f}

 KAPITALSTOCKS NACH DEM ZYKLUS
 Energieproduktion           {r['cap_energy_prod']:,.2f}
 Energieeffizienz            {r['cap_energy_eff']:,.2f}
 Nahrung                     {r['cap_food']:,.2f}
 Güter                       {r['cap_goods']:,.2f}
 Human Services              {r['cap_human']:,.2f}
 Umweltschutz                {r['cap_env']:,.2f}
================================================================================
"""


if __name__ == "__main__":
    root = tk.Tk()
    app = StratagemGUI(root)
    root.mainloop()
