"""Equivara – Tkinter-Oberfläche.

Die GUI arbeitet immer über ein ``World``-Objekt (Solo = ein Land). Sie nutzt
die öffentlichen APIs von ``equivara_engine``, ``equivara_world``,
``equivara_views``, ``equivara_map``, ``equivara_export`` und
``equivara_store``; Dialoge liegen in ``equivara_dialogs``.
"""

import csv
import json
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import equivara_dialogs as dialogs
import equivara_store as store
from equivara_engine import (
    DEFAULT_INPUTS,
    INPUT_KEYS,
    INPUT_LABELS,
    INVEST_KEYS,
    MINISTRIES,
    MINISTRY_INPUT_KEYS,
    SCENARIOS,
    EquivaraEngine,
)
from equivara_export import export_canvas_png, export_html
from equivara_map import HexCountryMap, HexWorldMap
from equivara_views import CausalLoopView, CompareView, CurvesView, LeaderboardView, Tutorial
from equivara_widgets import (
    THEME,
    BudgetBar,
    HistoryTable,
    LineChart,
    MultiLineChart,
    StatCard,
    Tooltip,
    blend,
)
from equivara_world import COUNTRY_COLORS, MODES, ROLES, Country, World

C = THEME
SIDEBAR_BG = "#0a101c"
FIELD_BG = "#0f1729"
DEBOUNCE_MS = 150
FONT = "Segoe UI"
CYCLE_YEARS = 5


# ---------------------------------------------------------------------------
# Feld-Definitionen
# ---------------------------------------------------------------------------
UNITS = {
    "food_domestic": "NW", "food_export": "NW",
    "goods_domestic": "GW", "goods_export": "GW", "goods_investment": "GW",
    "energy_food": "EW", "energy_goods": "EW", "energy_export": "EW", "energy_carryover": "EW",
    "inv_food": "GW", "inv_env": "GW", "inv_goods": "GW", "inv_human": "GW",
    "inv_energy_prod": "GW", "inv_energy_eff": "GW",
    "foreign_aid": "GE", "new_loans": "GE", "repayments": "GE",
    "import_energy_money": "GE", "import_food_money": "GE", "import_goods_money": "GE",
    "inv_health": "GW", "inv_education": "GW", "inv_infrastructure": "GW", "inv_defense": "GW",
}

TOOLTIPS = {
    "food_domestic": "Nahrung, die die Bevölkerung in diesem Zyklus konsumiert.\nZiel: mind. 2 NW pro Kopf und Jahr.",
    "food_export": "Exportierte Nahrung. Bringt Devisen (GE) für Importe, Zinsen und Tilgung.",
    "goods_domestic": "Konsumgüter für die Bevölkerung. Verbraucht zusätzlich Energie (1/5 der Gütermenge).",
    "goods_export": "Exportierte Güter. Bringt Devisen (GE).",
    "goods_investment": "Güter, die als Investitionsbudget auf die Kapitalstöcke (und aktiven Ministerien) "
                        "verteilt werden.",
    "energy_food": "Energie für die Nahrungsproduktion. Unter 100 % Bedarf sinkt die Auslastung des Nahrungskapitals.",
    "energy_goods": "Energie für die Güterproduktion. Unter 100 % Bedarf sinkt die Auslastung des Güterkapitals.",
    "energy_export": "Exportierte Energie. Bringt Devisen (GE).",
    "energy_carryover": "Energie, die in den nächsten Zyklus übertragen wird.",
    "inv_food": "Erhöht das Nahrungskapital (wirkt verzögert).",
    "inv_env": "Umweltschutzkapital: senkt die Umweltbelastung.",
    "inv_goods": "Erhöht das Güterkapital (wirkt verzögert).",
    "inv_human": "Human Services: Bildung, Gesundheit – beeinflusst Produktivität und Demografie.",
    "inv_energy_prod": "Neue Energieproduktionskapazität (wirkt mit zwei Zyklen Verzögerung).",
    "inv_energy_eff": "Energieeffizienz: senkt den Energiebedarf.\nHöchstens Investition Nahrungs- + Güterkapital.",
    "foreign_aid": "Auslandshilfe in Geldeinheiten (GE).",
    "new_loans": "Neue Kredite. Limit: durchschnittliche Exporte minus Schulden.",
    "repayments": "Tilgung bestehender Schulden aus den verfügbaren Devisen.",
    "import_energy_money": "Devisen für Energieimporte (verfügbar im Folgezyklus).",
    "import_food_money": "Devisen für Nahrungsimporte (verfügbar im Folgezyklus).",
    "import_goods_money": "Devisen für Güterimporte (verfügbar im Folgezyklus).",
}
for _mk, _m in MINISTRIES.items():
    TOOLTIPS[_m["input_key"]] = f"Ministerium {_m['name']}: {_m['description']}\nZählt zum Investitionsbudget."

SECTIONS = [
    ("1  Konsum", "Wie viel Nahrung und Güter erhält die Bevölkerung?",
     ["food_domestic", "goods_domestic"]),
    ("2  Energie", "Verteile die verfügbare Energie auf Produktion und Reserve.",
     ["energy_food", "energy_goods", "energy_carryover"]),
    ("3  Handel & Finanzen", "Exporte bringen Devisen; daraus werden Tilgung, Zinsen und Importe bezahlt.",
     ["food_export", "goods_export", "energy_export", None,
      "foreign_aid", "new_loans", "repayments", None,
      "import_food_money", "import_goods_money", "import_energy_money"]),
    ("4  Investitionen", "Lege das Investitionsbudget fest und verteile es auf die Kapitalstöcke.",
     ["goods_investment", None] + list(INVEST_KEYS)),
    ("5  Ministerien", "Investitionen der aktiven Ministerien – sie zählen zum Investitionsbudget aus Abschnitt 4.",
     list(MINISTRY_INPUT_KEYS)),
]

# Prognose-Kennzahlen: (key, label, fmt, factor, good_when_up)
FORECAST_ROWS = [
    ("population", "Bevölkerung", "{:,.1f}", 1.0, True),
    ("food_pc", "Nahrung / Kopf", "{:,.2f}", 1.0, True),
    ("goods_pc", "Güter / Kopf", "{:,.2f}", 1.0, True),
    ("environment", "Umwelt %", "{:,.1f}", 100.0, True),
    ("debt", "Schulden", "{:,.0f}", 1.0, False),
    ("gdp", "GDP-Index", "{:,.1f}", 1.0, True),
    ("birth_rate", "Geburtenrate ‰", "{:,.1f}", 1.0, False),
    ("death_rate", "Sterberate ‰", "{:,.1f}", 1.0, False),
]

REPORT_ROWS = [
    ("population", "Bevölkerung", "{:,.1f}"),
    ("labor", "Arbeitskräfte", "{:,.1f}"),
    ("food_pc", "Nahrung / Kopf / Jahr", "{:,.2f}"),
    ("goods_pc", "Güter / Kopf / Jahr", "{:,.2f}"),
    ("human_pc", "Human Services / Kopf", "{:,.2f}"),
    ("birth_rate", "Geburtenrate (‰/Jahr)", "{:,.2f}"),
    ("death_rate", "Sterberate (‰/Jahr)", "{:,.2f}"),
    ("net_growth", "Nettowachstum (‰/Jahr)", "{:,.2f}"),
    ("food_production", "Nahrungsproduktion", "{:,.0f}"),
    ("goods_production", "Güterproduktion", "{:,.0f}"),
    ("energy_production", "Energieproduktion", "{:,.0f}"),
    ("food_available", "Nahrung verfügbar", "{:,.0f}"),
    ("goods_available", "Güter verfügbar", "{:,.0f}"),
    ("energy_available", "Energie verfügbar", "{:,.0f}"),
    ("food_cu", "Auslastung Nahrung", "{:.1%}"),
    ("goods_cu", "Auslastung Güter", "{:.1%}"),
    ("environment", "Umweltqualität", "{:.1%}"),
    ("export_money", "Exporterlöse", "{:,.0f}"),
    ("import_spending", "Importausgaben", "{:,.0f}"),
    ("annual_interest", "Zinssatz (%/Jahr)", "{:,.2f}"),
    ("interest_paid", "Zinsen bezahlt", "{:,.0f}"),
    ("unpaid_interest", "Zinsen kapitalisiert", "{:,.0f}"),
    ("cash_reserve", "Devisenreserve", "{:,.0f}"),
    ("imf_goods", "IMF-Rückzahlung (Güter)", "{:,.0f}"),
    ("debt", "Schulden", "{:,.0f}"),
    ("gdp", "GDP-Index", "{:,.1f}"),
    ("gdp_pc", "GDP / Kopf", "{:,.2f}"),
    ("cap_food", "Kapital Nahrung", "{:,.0f}"),
    ("cap_goods", "Kapital Güter", "{:,.0f}"),
    ("cap_human", "Kapital Human Services", "{:,.0f}"),
    ("cap_env", "Kapital Umweltschutz", "{:,.0f}"),
    ("cap_energy_prod", "Kapital Energieproduktion", "{:,.0f}"),
    ("cap_energy_eff", "Kapital Energieeffizienz", "{:,.0f}"),
]

# Ministerien: Berichtszeilen, Dashboard-Karten
MINISTRY_REPORT_ROWS = {
    "gesundheit": [("cap_health", "Kapital Gesundheit", "{:,.0f}"),
                   ("health_mult", "Sterberaten-Multiplikator", "{:,.3f}")],
    "bildung": [("cap_education", "Kapital Bildung", "{:,.0f}"),
                ("education_mult", "Bildungs-Produktivität", "{:,.3f}")],
    "infrastruktur": [("cap_infrastructure", "Kapital Infrastruktur", "{:,.0f}"),
                      ("infra_mult", "Logistik-Multiplikator", "{:,.3f}")],
    "verteidigung": [("cap_defense", "Kapital Verteidigung", "{:,.0f}"),
                     ("security", "Sicherheit", "{:.1%}")],
}
# (key, title, color, fmt, factor, good_when_up)
MINISTRY_CARDS = {
    "gesundheit": ("health_mult", "Gesundheit · Sterbe-Mult.", "red", "{:,.3f}", 1.0, False),
    "bildung": ("education_mult", "Bildung · Produktivität", "purple", "{:,.3f}", 1.0, True),
    "infrastruktur": ("infra_mult", "Infrastruktur · Logistik", "orange", "{:,.3f}", 1.0, True),
    "verteidigung": ("security", "Verteidigung · Sicherheit %", "blue", "{:,.0f}", 100.0, True),
}

MINISTRY_HINTS = {"gesundheit": "Sterberate ×{:.2f}", "bildung": "Produktivität ×{:.2f}",
                  "infrastruktur": "Logistik ×{:.2f}", "verteidigung": "Sicherheit {:.0f} %"}

CAPITAL_SERIES = [
    ("cap_food", "Nahrung", "orange"),
    ("cap_goods", "Güter", "blue"),
    ("cap_human", "Human Services", "purple"),
    ("cap_env", "Umweltschutz", "green"),
    ("cap_energy_prod", "Energieproduktion", "red"),
    ("cap_energy_eff", "Energieeffizienz", "cyan"),
]

# Dashboard-Diagramme: (key, title, color, factor, kwargs, reference)
CHARTS = [
    ("population", "Bevölkerung", "blue", 1.0, {}, None),
    ("food_pc", "Nahrung / Kopf", "orange", 1.0, {"fmt": "{:,.2f}", "ymin": 0}, 2.0),
    ("goods_pc", "Güter / Kopf", "purple", 1.0, {"fmt": "{:,.2f}", "ymin": 0}, None),
    ("environment", "Umwelt", "green", 100.0, {"unit": "%", "fmt": "{:,.1f}", "ymin": 0, "ymax": 100}, None),
    ("debt", "Schulden", "red", 1.0, {"ymin": 0}, None),
    ("gdp", "GDP-Index", "cyan", 1.0, {"fmt": "{:,.1f}"}, None),
]

SCORE_PART_NAMES = {"food": "Nahrung/Kopf", "goods": "Güter/Kopf", "environment": "Umwelt",
                    "debt": "Schulden", "population": "Bevölkerung", "services": "Ministerien"}

NAV = [("decisions", "Entscheidungen"), ("dashboard", "Dashboard"), ("world", "Welt"),
       ("report", "Bericht"), ("curves", "Kennlinien"), ("loops", "Wirkungsgefüge"),
       ("compare", "Vergleich"), ("leaderboard", "Bestenliste"), ("end", "Auswertung"),
       ("settings", "Einstellungen")]

GOODS_NAMES = {"food": "Nahrung", "goods": "Güter", "energy": "Energie"}


def _fmt_input(value):
    try:
        v = float(value)
    except (TypeError, ValueError):
        return "0"
    if abs(v - round(v)) < 1e-9:
        return str(int(round(v)))
    return f"{v:g}"


def _num(d, key, default=0.0):
    if not d:
        return default
    try:
        v = d.get(key, default)
        return default if v is None else float(v)
    except (TypeError, ValueError):
        return default


def solo_world(engine, name="Land 1"):
    """Verpackt eine einzelne Engine in eine Solo-Welt."""
    return World("solo", [Country(name=name, engine=engine, color=COUNTRY_COLORS[0])],
                 seed=getattr(engine, "seed", None))


# ---------------------------------------------------------------------------
# Scrollbarer Bereich mit Mausrad
# ---------------------------------------------------------------------------
class ScrollFrame(tk.Frame):
    """Vertikal scrollbarer Container; ``self.inner`` nimmt den Inhalt auf."""

    registry = {}

    def __init__(self, parent, bg=None, width=None, **kw):
        bg = bg or C["bg"]
        super().__init__(parent, bg=bg, **kw)
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0, width=width or 400)
        self.vsb = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = tk.Frame(self.canvas, bg=bg)
        self._win = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.configure(yscrollcommand=self.vsb.set)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self.inner.bind("<Configure>", self._on_inner)
        self.canvas.bind("<Configure>", self._on_canvas)
        ScrollFrame.registry[str(self.canvas)] = self

    def _on_inner(self, _e=None):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas(self, e):
        self.canvas.itemconfigure(self._win, width=e.width)

    def scroll(self, units):
        first, last = self.canvas.yview()
        if first <= 0 and last >= 1:
            return
        self.canvas.yview_scroll(units, "units")

    @classmethod
    def install_wheel(cls, root):
        def find(widget):
            w = widget
            while w is not None:
                sf = cls.registry.get(str(w))
                if sf is not None:
                    return sf
                w = getattr(w, "master", None)
            return None

        def on_wheel(event):
            try:
                w = root.winfo_containing(event.x_root, event.y_root)
            except (KeyError, tk.TclError):
                return
            sf = find(w) if w is not None else None
            if sf is None:
                return
            if getattr(event, "num", None) == 4:
                sf.scroll(-3)
            elif getattr(event, "num", None) == 5:
                sf.scroll(3)
            elif event.delta:
                sf.scroll(int(-event.delta / 120 * 3) or (-1 if event.delta > 0 else 1))

        root.bind_all("<MouseWheel>", on_wheel, add="+")
        root.bind_all("<Button-4>", on_wheel, add="+")
        root.bind_all("<Button-5>", on_wheel, add="+")


# ---------------------------------------------------------------------------
# Hauptfenster
# ---------------------------------------------------------------------------
class EquivaraGUI:
    """Tkinter-Frontend für Equivara (Solo, Wettbewerb, Handel, Rollen)."""

    COLORS = C

    VIEW_TITLES = {
        "decisions": ("Entscheidungen", "Konsum, Energie, Handel und Investitionen für den nächsten Zyklus"),
        "dashboard": ("Dashboard", "Aktueller Zustand des Landes und Entwicklung"),
        "world": ("Welt", "Alle Länder, Weltmarkt und Handelsflüsse"),
        "report": ("Bericht", "Alle Kennzahlen je Zyklus"),
        "curves": ("Kennlinien", "Der Punkt zeigt, wo dein Land gerade auf der Kurve steht."),
        "loops": ("Wirkungsgefüge", "Wie die Größen deines Landes zusammenhängen – dicke Pfeile wirken gerade stark."),
        "compare": ("Vergleich", "Mehrere Länder oder Spielstände nebeneinander"),
        "leaderboard": ("Bestenliste", "Die besten Länder aller bisherigen Spiele"),
        "end": ("Auswertung", "Bewertung und Endwerte"),
        "settings": ("Einstellungen", "Standardwerte für neue Spiele"),
    }

    def __init__(self, root, engine=None, world=None, settings_path=None, leaderboard_path=None,
                 show_tutorial=None):
        self.root = root
        self.root.title("Equivara  |  System Dynamics Simulation")
        self.root.geometry("1280x800")
        self.root.minsize(1100, 700)
        self.root.configure(bg=C["bg"])

        self.settings_path = settings_path
        self.leaderboard_path = leaderboard_path
        self.settings = self._load_settings()

        if world is not None:
            self.world = world
        elif engine is not None:
            self.world = solo_world(engine)
        else:
            self.world = self._world_from_settings()

        self.vars = {}
        self.field_frames = {}
        self.field_msgs = {}
        self.field_labels = {}
        self.field_rows = {}
        self.spinboxes = {}
        self.hints = {}
        self.views = {}
        self.current_view = None
        self._after_id = None
        self._suspend_trace = False
        self._preview = None
        self._issues = []
        self._parse_errors = {}
        self._can_apply = False
        self._role_idx = 0
        self._advice = None
        self._lb_done = set()
        self._layout_key = None
        self._end_idx = 0
        self._compare_auto = []
        self._goal_prompted = False
        self.tutorial = None

        self._configure_style()
        self._build_shell()
        self._build_decisions()
        self._build_dashboard()
        self._build_world()
        self._build_report()
        self._build_analysis_views()
        self._build_end()
        self._build_settings()
        self.overlay = dialogs.HandoverOverlay(self.root)
        ScrollFrame.install_wheel(self.root)
        self._bind_keys()

        self._sync_layout()
        self._fill_inputs(self._initial_inputs())
        self._show_view("end" if self.world.game_over() else "decisions")
        self._refresh_all()
        self._maybe_handover()

        if show_tutorial is None:
            show_tutorial = not self.settings.get("tutorial_done", False)
        if show_tutorial:
            self.root.after(700, self.start_tutorial)

    # ------------------------------------------------------------- engine/world
    @property
    def engine(self):
        """Engine des Landes, das gerade am Zug ist."""
        return self.world.current_country().engine

    @engine.setter
    def engine(self, eng):
        self.world = solo_world(eng)
        self._role_idx = 0

    @property
    def country(self):
        return self.world.current_country()

    @property
    def multi(self):
        return len(self.world.countries) > 1

    # -------------------------------------------------------------- settings
    def _load_settings(self):
        try:
            return dict(store.load_settings(self.settings_path) or {})
        except Exception:
            return {}

    def _save_settings(self, settings):
        self.settings = dict(settings)
        store.save_settings(self.settings, self.settings_path)

    def _world_from_settings(self):
        s = self.settings
        return World.create("solo", ["Land 1"], scenario=dialogs.settings_scenario(s),
                            events_enabled=dialogs.settings_events(s),
                            ministries=dialogs.settings_ministries(s),
                            goal_cycles=dialogs.settings_goal(s))

    # ------------------------------------------------------------------ style
    def _configure_style(self):
        style = ttk.Style(self.root)
        if "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure("TFrame", background=C["bg"])
        style.configure("TButton", background=C["panel2"], foreground=C["text"], borderwidth=0,
                        padding=(12, 7), font=(FONT, 10, "bold"))
        style.map("TButton", background=[("active", "#233453"), ("disabled", "#141d31")],
                  foreground=[("disabled", "#55647d")])
        style.configure("Accent.TButton", background=C["blue"], foreground=C["white"], borderwidth=0,
                        padding=(16, 10), font=(FONT, 11, "bold"))
        style.map("Accent.TButton", background=[("active", "#6b9fff"), ("disabled", "#26375a")],
                  foreground=[("disabled", "#7f8da6")])
        style.configure("Advisor.TButton", background="#1d3a33", foreground=C["green"], borderwidth=0,
                        padding=(12, 7), font=(FONT, 10, "bold"))
        style.map("Advisor.TButton", background=[("active", "#24493f"), ("disabled", "#141d31")],
                  foreground=[("disabled", "#55647d")])
        style.configure("Side.TButton", background="#121b2e", foreground=C["text"], borderwidth=0,
                        padding=(8, 5), font=(FONT, 9, "bold"))
        style.map("Side.TButton", background=[("active", "#1c2a45")])
        style.configure("TSpinbox", fieldbackground=FIELD_BG, foreground=C["text"], insertcolor=C["text"],
                        bordercolor=FIELD_BG, lightcolor=FIELD_BG, darkcolor=FIELD_BG,
                        arrowcolor=C["muted"], background=C["panel2"], padding=4)
        style.map("TSpinbox", fieldbackground=[("disabled", "#141d31")], foreground=[("disabled", "#55647d")])
        style.configure("Vertical.TScrollbar", background=C["panel2"], troughcolor=C["bg"],
                        bordercolor=C["bg"], arrowcolor=C["muted"])
        dialogs.configure_styles(self.root)

    # ------------------------------------------------------------------ shell
    def _build_shell(self):
        self.sidebar = tk.Frame(self.root, bg=SIDEBAR_BG, width=200)
        self.sidebar.pack(side=tk.LEFT, fill=tk.Y)
        self.sidebar.pack_propagate(False)

        brand = tk.Frame(self.sidebar, bg=SIDEBAR_BG)
        brand.pack(fill=tk.X, padx=(20, 8), pady=(18, 14))
        tk.Label(brand, text="EQUIVARA", bg=SIDEBAR_BG, fg=C["text"], font=(FONT, 19, "bold")).pack(anchor="w")
        tk.Label(brand, text="SYSTEM DYNAMICS SIMULATION", bg=SIDEBAR_BG, fg=C["blue"],
                 font=(FONT, 7, "bold")).pack(anchor="w", pady=(2, 0))

        self.nav_frame = tk.Frame(self.sidebar, bg=SIDEBAR_BG)
        self.nav_frame.pack(fill=tk.X)
        self.nav_buttons = {}
        for key, label in NAV:
            b = tk.Button(self.nav_frame, text=label, anchor="w", relief="flat", bd=0,
                          bg=SIDEBAR_BG, fg=C["muted"], activebackground="#17243d",
                          activeforeground=C["text"], font=(FONT, 10, "bold"), disabledforeground="#3c4a63",
                          padx=20, pady=6, cursor="hand2", command=lambda k=key: self._show_view(k))
            b.pack(fill=tk.X, padx=8, pady=1)
            self.nav_buttons[key] = b

        tk.Frame(self.sidebar, bg=SIDEBAR_BG).pack(fill=tk.BOTH, expand=True)

        actions = tk.Frame(self.sidebar, bg=SIDEBAR_BG)
        actions.pack(fill=tk.X, padx=12, pady=(0, 6))
        actions.columnconfigure(0, weight=1, uniform="act")
        actions.columnconfigure(1, weight=1, uniform="act")
        self.action_buttons = {}
        layout = [
            ("new", "Neues Spiel…", self.new_game, "Neues Spiel mit Modus, Ländern und Szenario starten", 0, 0, 2),
            ("save", "Speichern…", self.save_game, "Spielstand als JSON speichern (Strg+S)", 1, 0, 1),
            ("load", "Laden…", self.load_game, "Spielstand aus JSON laden (Strg+O)", 1, 1, 1),
            ("html", "Bericht (HTML/PDF)…", self.export_report,
             "Druckbaren HTML-Bericht aller Länder erzeugen (im Browser als PDF speichern)", 2, 0, 2),
            ("png", "Als PNG…", self.export_png, "Aktuelle Ansicht als PNG-Bild speichern (benötigt Pillow)",
             3, 0, 1),
            ("help", "Hilfe", self.start_tutorial, "Geführte Tour durch die Oberfläche (F1)", 3, 1, 1),
        ]
        for key, text, cmd, tip, r, c, span in layout:
            b = ttk.Button(actions, text=text, style="Side.TButton", command=cmd)
            b.grid(row=r, column=c, columnspan=span, sticky="ew", padx=2, pady=2)
            Tooltip(b, tip)
            self.action_buttons[key] = b

        self.side_info = tk.Label(self.sidebar, text="", bg=SIDEBAR_BG, fg="#52617a",
                                  font=(FONT, 8, "bold"), justify="left", wraplength=176)
        self.side_info.pack(anchor="w", padx=20, pady=(4, 2))
        tk.Label(self.sidebar, text="Enter  auswerten\nStrg+Z  rückgängig\nStrg+S / O  speichern / laden",
                 bg=SIDEBAR_BG, fg="#52617a", font=(FONT, 8), justify="left").pack(anchor="w", padx=20,
                                                                                   pady=(0, 10))

        self.main = tk.Frame(self.root, bg=C["bg"])
        self.main.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.header = tk.Frame(self.main, bg=C["bg"], height=66)
        self.header.pack(fill=tk.X, padx=24, pady=(12, 4))
        self.header.pack_propagate(False)
        left = tk.Frame(self.header, bg=C["bg"])
        left.pack(side=tk.LEFT, fill=tk.Y)
        self.page_title = tk.Label(left, text="", bg=C["bg"], fg=C["text"], font=(FONT, 20, "bold"))
        self.page_title.pack(anchor="w")
        self.page_subtitle = tk.Label(left, text="", bg=C["bg"], fg=C["muted"], font=(FONT, 10))
        self.page_subtitle.pack(anchor="w")
        right = tk.Frame(self.header, bg=C["bg"])
        right.pack(side=tk.RIGHT, fill=tk.Y)
        self.cycle_label = tk.Label(right, text="", bg="#16243c", fg=C["blue"],
                                    font=("Consolas", 10, "bold"), padx=14, pady=6)
        self.cycle_label.pack(anchor="e", pady=(4, 4))
        self.year_label = tk.Label(right, text="", bg=C["bg"], fg=C["muted"], font=(FONT, 9, "bold"))
        self.year_label.pack(anchor="e")

        self.status_bar = tk.Label(self.main, text="", bg=C["bg"], fg=C["muted"], anchor="w",
                                   font=(FONT, 9), padx=24)
        self.status_bar.pack(side=tk.BOTTOM, fill=tk.X, pady=(0, 6))

        self.content = tk.Frame(self.main, bg=C["bg"])
        self.content.pack(fill=tk.BOTH, expand=True, padx=24, pady=(0, 6))

    def _new_view(self, key):
        frame = tk.Frame(self.content, bg=C["bg"])
        self.views[key] = frame
        return frame

    def _end_available(self):
        return any(c.engine.cycles_played >= 1 for c in self.world.countries)

    def _show_view(self, key):
        if key not in self.views:
            return
        if key == "end" and not self._end_available():
            self._status("Die Auswertung ist nach dem ersten Zyklus verfügbar.")
            return
        if key == "world" and not self.multi:
            self._status("Die Weltansicht gibt es nur mit mehreren Ländern.")
            return
        for f in self.views.values():
            f.pack_forget()
        self.views[key].pack(fill=tk.BOTH, expand=True)
        self.current_view = key
        self._update_title()
        for k, b in self.nav_buttons.items():
            b.config(bg="#17243d" if k == key else SIDEBAR_BG, fg=C["text"] if k == key else C["muted"])
        self._refresh_view(key)

    def _update_title(self):
        key = self.current_view
        if key not in self.VIEW_TITLES:
            return
        title, sub = self.VIEW_TITLES[key]
        over = self.world.game_over()
        if key == "end":
            if over:
                title, sub = "Ziel erreicht", f"Auswertung nach {self._goal_years_text()} – du kannst weiterspielen"
            elif self.engine.goal_reached:
                sub = "Bewertung des aktuellen Stands (Ziel bereits erreicht)"
        elif key == "decisions" and over:
            title = "Ziel erreicht"
            sub = "Weiterspielen oder neues Spiel – siehe Auswertung"
        if key in ("decisions", "dashboard", "report", "curves", "loops") and self.multi:
            sub = f"{self.country.name}: {sub}"
        self.page_title.config(text=title)
        self.page_subtitle.config(text=sub)

    def _goal_years_text(self):
        g = self.engine.goal_years
        return "endlos" if g is None else f"{g} Jahren"

    def _status(self, text, color=None):
        self.status_bar.config(text=text, fg=color or C["muted"])

    # --------------------------------------------------------------- helpers
    def _panel(self, parent, title=None, subtitle=None, bg=None, wrap=560):
        bg = bg or C["panel"]
        f = tk.Frame(parent, bg=bg, highlightthickness=1, highlightbackground=C["border"])
        if title:
            tk.Label(f, text=title, bg=bg, fg=C["text"], font=(FONT, 12, "bold")).pack(anchor="w", padx=14, pady=(12, 0))
        if subtitle:
            tk.Label(f, text=subtitle, bg=bg, fg=C["muted"], font=(FONT, 9), justify="left",
                     wraplength=wrap).pack(anchor="w", padx=14, pady=(2, 6))
        return f

    @staticmethod
    def _collapse(container):
        """Leerer Container schrumpft in Tk nicht von selbst – Höhe zurücksetzen."""
        try:
            if not container.pack_slaves():
                container.configure(height=1)
        except tk.TclError:
            pass

    def _banner(self, parent, color):
        bg = blend(color, C["bg"], 0.84)
        f = tk.Frame(parent, bg=bg, highlightthickness=1, highlightbackground=blend(color, C["bg"], 0.45))
        title = tk.Label(f, text="", bg=bg, fg=color, font=(FONT, 10, "bold"), anchor="w", justify="left")
        title.pack(fill=tk.X, padx=12, pady=(7, 0))
        text = tk.Label(f, text="", bg=bg, fg=C["text"], font=(FONT, 9), anchor="w", justify="left",
                        wraplength=700)
        text.pack(fill=tk.X, padx=12, pady=(0, 7))
        f.bind("<Configure>", lambda e: text.config(wraplength=max(200, e.width - 30)), add="+")
        f.title_lbl, f.text_lbl = title, text
        return f

    def _field(self, grid, key, row):
        """Erzeugt Label + Spinbox (rot umrahmbar) + Einheit + Hinweisspalte + Meldungszeile."""
        bg = C["panel"]
        lbl = tk.Label(grid, text=INPUT_LABELS.get(key, key), bg=bg, fg=C["text"], font=(FONT, 9), anchor="w")
        lbl.grid(row=row, column=0, sticky="w", padx=(14, 8), pady=(5, 0))
        var = tk.StringVar(value="0")
        self.vars[key] = var
        wrap = tk.Frame(grid, bg=bg, highlightthickness=2, highlightbackground=bg, highlightcolor=bg)
        wrap.grid(row=row, column=1, sticky="e", pady=(5, 0))
        sp = ttk.Spinbox(wrap, from_=0, to=1_000_000, increment=10, textvariable=var, width=11,
                         justify="right", format="%.0f")
        sp.pack()
        self.spinboxes[key] = sp
        self.field_frames[key] = wrap
        self.field_labels[key] = lbl
        unit = tk.Label(grid, text=UNITS.get(key, ""), bg=bg, fg=C["muted"], font=(FONT, 8, "bold"),
                        width=3, anchor="w")
        unit.grid(row=row, column=2, sticky="w", padx=(6, 4), pady=(5, 0))
        msg = tk.Label(grid, text="", bg=bg, fg=C["red"], font=(FONT, 8), anchor="w", justify="left",
                       wraplength=520)
        msg.grid(row=row + 1, column=0, columnspan=4, sticky="w", padx=(14, 8))
        msg.grid_remove()
        self.field_msgs[key] = msg
        tip = TOOLTIPS.get(key, "")
        Tooltip(lbl, tip)
        Tooltip(sp, tip)
        var.trace_add("write", self._on_var_change)
        self.field_rows[key] = [lbl, wrap, unit]
        return lbl

    def _hint(self, grid, row, color=None):
        h = tk.Label(grid, text="", bg=C["panel"], fg=color or C["muted"], font=(FONT, 8), anchor="w",
                     justify="left", wraplength=230)
        h.grid(row=row, column=3, sticky="w", padx=(6, 14), pady=(5, 0))
        return h

    # ------------------------------------------------------------- decisions
    def _build_decisions(self):
        f = self._new_view("decisions")
        f.columnconfigure(0, weight=1)
        f.columnconfigure(1, weight=0, minsize=330)
        f.rowconfigure(0, weight=1)

        # ---- linke Seite: Entscheidungs-Flow (scrollbar)
        sf = ScrollFrame(f)
        sf.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        self.decisions_scroll = sf
        inner = sf.inner

        self.dec_banners = tk.Frame(inner, bg=C["bg"])
        self.dec_banners.pack(fill=tk.X)
        self.dec_event_banner = self._banner(self.dec_banners, C["orange"])
        self.role_banner = self._banner(self.dec_banners, C["cyan"])

        legend = tk.Frame(inner, bg=C["panel2"], highlightthickness=1, highlightbackground=C["border"])
        legend.pack(fill=tk.X, pady=(0, 8))
        tk.Label(legend, text="Einheiten:  NW = Nahrungseinheiten   GW = Gütereinheiten   "
                              "EW = Energieeinheiten   GE = Geldeinheiten (Devisen)   •   Schrittweite 10",
                 bg=C["panel2"], fg=C["muted"], font=(FONT, 8, "bold"), wraplength=640,
                 justify="left").pack(anchor="w", padx=12, pady=6)

        self.section_panels = []
        for title, subtitle, keys in SECTIONS:
            p = self._panel(inner, title, subtitle)
            p.pack(fill=tk.X, pady=(0, 10))
            self.section_panels.append(p)
            grid = tk.Frame(p, bg=C["panel"])
            grid.pack(fill=tk.X, pady=(0, 10))
            grid.columnconfigure(0, weight=1)
            grid.columnconfigure(3, minsize=200)
            row = 0
            for key in keys:
                if key is None:
                    tk.Frame(grid, bg=C["border"], height=1).grid(row=row, column=0, columnspan=4,
                                                                  sticky="ew", padx=14, pady=6)
                    row += 1
                    continue
                self._field(grid, key, row)
                self.hints[key] = self._hint(grid, row)
                self.field_rows[key].append(self.hints[key])
                row += 2
            if title.startswith("4"):
                bar_wrap = tk.Frame(p, bg=C["panel"])
                bar_wrap.pack(fill=tk.X, padx=14, pady=(0, 12))
                self.invest_bar_local = BudgetBar(bar_wrap, "Investitionsbudget", C["purple"], width=400)
                self.invest_bar_local.pack(fill=tk.X)
            if title.startswith("5"):
                bar_wrap = tk.Frame(p, bg=C["panel"])
                bar_wrap.pack(fill=tk.X, padx=14, pady=(0, 12))
                self.invest_bar_min = BudgetBar(bar_wrap, "Investitionsbudget (gesamt)", C["purple"], width=400)
                self.invest_bar_min.pack(fill=tk.X)
            if title.startswith("3"):
                self.finance_info = tk.Label(p, text="", bg=C["panel2"], fg=C["text"], font=("Consolas", 9),
                                             justify="left", anchor="w")
                self.finance_info.pack(fill=tk.X, padx=14, pady=(0, 12), ipadx=8, ipady=6)
        self.ministry_panel = self.section_panels[4]

        # ---- rechte Seite: Live-Panel (fixiert)
        live_sf = ScrollFrame(f, bg=C["bg"], width=318)
        live_sf.grid(row=0, column=1, sticky="nsew")
        live = live_sf.inner
        self.live_scroll = live_sf

        act = self._panel(live, "Zyklus abschließen")
        act.pack(fill=tk.X, pady=(0, 8))
        self.act_panel = act
        self.apply_btn = ttk.Button(act, text="Runde auswerten  ⏎", style="Accent.TButton",
                                    command=self.evaluate_round)
        self.apply_btn.pack(fill=tk.X, padx=14, pady=(8, 4))
        self.apply_reason = tk.Label(act, text="", bg=C["panel"], fg=C["red"], font=(FONT, 8),
                                     wraplength=290, justify="left", anchor="w")
        self.apply_reason.pack(fill=tk.X, padx=14)
        row = tk.Frame(act, bg=C["panel"])
        row.pack(fill=tk.X, padx=14, pady=(6, 4))
        self.suggest_btn = ttk.Button(row, text="Vorschlag", command=self.apply_suggestion)
        self.suggest_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4))
        Tooltip(self.suggest_btn, "Vorschlag übernehmen: skaliert die aktuellen Eingaben so, dass alle Budgets passen.")
        self.undo_btn = ttk.Button(row, text="Rückgängig", command=self.undo_round)
        self.undo_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(4, 0))
        Tooltip(self.undo_btn, "Letzten Zug rückgängig machen (Strg+Z)")
        self.advisor_btn = ttk.Button(act, text="💡  Berater fragen", style="Advisor.TButton",
                                      command=self.ask_advisor)
        self.advisor_btn.pack(fill=tk.X, padx=14, pady=(2, 12))
        Tooltip(self.advisor_btn, "Der Berater rechnet viele zulässige Varianten durch, übernimmt die beste "
                                  "und erklärt seine Wahl.")

        self.advice_panel = tk.Frame(live, bg="#0f2420", highlightthickness=1, highlightbackground="#24493f")
        head = tk.Frame(self.advice_panel, bg="#0f2420")
        head.pack(fill=tk.X, padx=12, pady=(8, 2))
        tk.Label(head, text="💡 Empfehlung des Beraters", bg="#0f2420", fg=C["green"],
                 font=(FONT, 10, "bold")).pack(side=tk.LEFT)
        close = tk.Label(head, text="✕", bg="#0f2420", fg=C["muted"], font=(FONT, 10, "bold"), cursor="hand2")
        close.pack(side=tk.RIGHT)
        close.bind("<Button-1>", lambda e: self._clear_advice())
        self.advice_box = tk.Frame(self.advice_panel, bg="#0f2420")
        self.advice_box.pack(fill=tk.X, padx=12, pady=(0, 10))

        bud = self._panel(live, "Budgets")
        bud.pack(fill=tk.X, pady=(0, 8))
        self.budget_panel = bud
        self.budget_bars = {}
        for key, label, color in [("food", "Nahrung (NW)", C["orange"]), ("goods", "Güter (GW)", C["purple"]),
                                  ("energy", "Energie (EW)", C["cyan"]), ("money", "Devisen (GE)", C["green"]),
                                  ("invest", "Investitionen (GW)", C["blue"])]:
            b = BudgetBar(bud, label, color, width=280)
            b.pack(fill=tk.X, padx=14, pady=(4, 2))
            self.budget_bars[key] = b
        tk.Frame(bud, bg=C["panel"], height=8).pack()

        prog = self._panel(live, "Prognose nächster Zyklus")
        prog.pack(fill=tk.X, pady=(0, 8))
        pg = tk.Frame(prog, bg=C["panel"])
        pg.pack(fill=tk.X, padx=14, pady=(4, 12))
        pg.columnconfigure(0, weight=1)
        for col, txt in enumerate(["", "Jetzt", "Prognose", "Δ"]):
            tk.Label(pg, text=txt, bg=C["panel"], fg=C["muted"], font=(FONT, 8, "bold"),
                     anchor="e").grid(row=0, column=col, sticky="ew", padx=2)
        self.forecast_labels = {}
        for i, (key, label, _fmt, _f, _g) in enumerate(FORECAST_ROWS, start=1):
            tk.Label(pg, text=label, bg=C["panel"], fg=C["text"], font=(FONT, 9), anchor="w").grid(
                row=i, column=0, sticky="w", pady=1)
            labs = []
            for col in (1, 2, 3):
                l = tk.Label(pg, text="—", bg=C["panel"], fg=C["text"] if col != 1 else C["muted"],
                             font=("Consolas", 9), anchor="e", width=8)
                l.grid(row=i, column=col, sticky="e", padx=2, pady=1)
                labs.append(l)
            self.forecast_labels[key] = labs

        warn = self._panel(live, "Hinweise & Warnungen")
        warn.pack(fill=tk.X, pady=(0, 8))
        self.live_warn_box = tk.Frame(warn, bg=C["panel"])
        self.live_warn_box.pack(fill=tk.X, padx=14, pady=(4, 12))

    # ------------------------------------------------------------- dashboard
    def _build_dashboard(self):
        f = self._new_view("dashboard")
        sf = ScrollFrame(f)
        sf.pack(fill=tk.BOTH, expand=True)
        inner = sf.inner
        self.dashboard_scroll = sf

        self.dash_banners = tk.Frame(inner, bg=C["bg"])
        self.dash_banners.pack(fill=tk.X)
        self.dash_event_banner = self._banner(self.dash_banners, C["orange"])

        cards = tk.Frame(inner, bg=C["bg"])
        cards.pack(fill=tk.X, pady=(0, 8))
        self.stat_cards = {}
        card_defs = [
            ("population", "Bevölkerung", "blue", "{:,.1f}", 1.0, True),
            ("food_pc", "Nahrung / Kopf", "orange", "{:,.2f}", 1.0, True),
            ("goods_pc", "Güter / Kopf", "purple", "{:,.2f}", 1.0, True),
            ("environment", "Umwelt %", "green", "{:,.1f}", 100.0, True),
            ("debt", "Schulden", "red", "{:,.0f}", 1.0, False),
            ("gdp", "GDP-Index", "cyan", "{:,.1f}", 1.0, True),
        ]
        for i, (key, title, color, fmt, factor, good) in enumerate(card_defs):
            cards.columnconfigure(i, weight=1, uniform="cards")
            card = StatCard(cards, title, C[color], fmt=fmt)
            card.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 4, 0 if i == len(card_defs) - 1 else 4))
            self.stat_cards[key] = (card, factor, good)
        self.min_cards_frame = tk.Frame(inner, bg=C["bg"])
        self.min_cards_frame.pack(fill=tk.X, pady=(0, 8))
        self.min_cards = {}

        mid = tk.Frame(inner, bg=C["bg"])
        mid.pack(fill=tk.X, pady=(0, 4))
        self.dash_mid = mid
        mid.columnconfigure(0, weight=3, uniform="mid")
        mid.columnconfigure(1, weight=2, uniform="mid")
        self.country_map = HexCountryMap(mid, lambda: self.engine, height=360)
        self.country_map.grid(row=0, column=0, sticky="nsew", padx=(4, 4), pady=4)
        wp = self._panel(mid, "Systemwarnungen", "Aktueller Zustand laut Modell")
        wp.grid(row=0, column=1, sticky="nsew", padx=(4, 4), pady=4)
        self.dash_warn_box = tk.Frame(wp, bg=C["panel"])
        self.dash_warn_box.pack(fill=tk.BOTH, expand=True, padx=14, pady=(0, 12))
        btn = ttk.Button(wp, text="Zu den Entscheidungen →", style="Accent.TButton",
                         command=lambda: self._show_view("decisions"))
        btn.pack(fill=tk.X, padx=14, pady=(0, 14))
        self.dash_go_btn = btn

        grid = tk.Frame(inner, bg=C["bg"])
        grid.pack(fill=tk.X)
        self.charts = {}
        for i, (key, title, color, factor, kw, ref) in enumerate(CHARTS):
            grid.columnconfigure(i % 3, weight=1, uniform="charts")
            ch = LineChart(grid, title, C[color], height=170, **kw)
            ch.grid(row=i // 3, column=i % 3, sticky="nsew", padx=4, pady=4)
            self.charts[key] = (ch, factor, ref)

        lower = tk.Frame(inner, bg=C["bg"])
        lower.pack(fill=tk.X, pady=(6, 0))
        self.dash_lower = lower
        lower.columnconfigure(0, weight=3)
        lower.columnconfigure(1, weight=2)
        self.capital_chart = MultiLineChart(lower, "Kapitalstöcke", height=240)
        self.capital_chart.grid(row=0, column=0, sticky="nsew", padx=(4, 4), pady=4)
        self.ministry_chart = MultiLineChart(lower, "Ministerien – Kapital", height=240)
        self.ministry_chart.grid(row=0, column=1, sticky="nsew", padx=(4, 4), pady=4)

    def _rebuild_ministry_cards(self):
        for w in self.min_cards_frame.winfo_children():
            w.destroy()
        self.min_cards = {}
        active = self.engine.active_ministries()
        if not active:
            self.min_cards_frame.pack_forget()
            return
        self.min_cards_frame.pack(fill=tk.X, pady=(0, 8), before=self.dash_mid)
        n = len(active)
        for i, mk in enumerate(active):
            key, title, color, fmt, factor, good = MINISTRY_CARDS[mk]
            self.min_cards_frame.columnconfigure(i, weight=1, uniform="mcards")
            card = StatCard(self.min_cards_frame, title, C[color], fmt=fmt)
            card.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 4, 0 if i == n - 1 else 4))
            self.min_cards[key] = (card, factor, good)
        for i in range(n, 4):
            self.min_cards_frame.columnconfigure(i, weight=0, uniform="")

    # ---------------------------------------------------------------- world
    def _build_world(self):
        f = self._new_view("world")
        sf = ScrollFrame(f)
        sf.pack(fill=tk.BOTH, expand=True)
        inner = sf.inner
        self.world_map = HexWorldMap(inner, lambda: self.world, height=400)
        self.world_map.pack(fill=tk.X, padx=4, pady=(0, 4))
        row = tk.Frame(inner, bg=C["bg"])
        row.pack(fill=tk.X)
        row.columnconfigure(0, weight=3, uniform="w")
        row.columnconfigure(1, weight=2, uniform="w")
        self.price_chart = MultiLineChart(row, "Marktpreise (Exportpreis je Einheit)", height=250, fmt="{:,.2f}")
        self.price_chart.grid(row=0, column=0, sticky="nsew", padx=4, pady=4)
        rp = self._panel(row, "Rangliste", "Nach Score (beim Ziel: Stand bei Zielerreichen)", wrap=380)
        rp.grid(row=0, column=1, sticky="nsew", padx=4, pady=4)
        self.ranking_box = tk.Frame(rp, bg=C["panel"])
        self.ranking_box.pack(fill=tk.X, padx=14, pady=(0, 12))
        tp = self._panel(inner, "Weltmarkt im letzten Zyklus")
        tp.pack(fill=tk.X, padx=4, pady=4)
        self.market_info = tk.Label(tp, text="", bg=C["panel"], fg=C["text"], font=("Consolas", 9),
                                    justify="left", anchor="w")
        self.market_info.pack(fill=tk.X, padx=14, pady=(4, 12))

    # ---------------------------------------------------------------- report
    def _build_report(self):
        f = self._new_view("report")
        top = tk.Frame(f, bg=C["bg"])
        top.pack(fill=tk.X, pady=(0, 8))
        tk.Label(top, text="Spalten = Zyklen (horizontal scrollen), Farbe = Veränderung zum Vorzyklus",
                 bg=C["bg"], fg=C["muted"], font=(FONT, 9)).pack(side=tk.LEFT)
        ttk.Button(top, text="Bericht als CSV exportieren", command=self.export_csv).pack(side=tk.RIGHT)
        self.report_frame = f
        self._report_rows_key = None
        self.history_table = None
        self._rebuild_report_table()

    def _report_rows(self):
        rows = list(REPORT_ROWS)
        for mk in self.engine.active_ministries():
            rows += MINISTRY_REPORT_ROWS[mk]
        return rows

    def _rebuild_report_table(self):
        rows = self._report_rows()
        key = tuple(r[0] for r in rows)
        if key == self._report_rows_key and self.history_table is not None:
            return
        if self.history_table is not None:
            self.history_table.destroy()
        self.history_table = HistoryTable(self.report_frame, rows)
        self.history_table.pack(fill=tk.BOTH, expand=True)
        self._report_rows_key = key

    # ------------------------------------------------------- analysis views
    def _strip_header(self, view, nested=False):
        """Die Views haben eine eigene Überschrift – die Seitenüberschrift reicht."""
        try:
            first = view.winfo_children()[0]
            if nested:
                first = first.winfo_children()[0]
            first.pack_forget()
        except (IndexError, tk.TclError):
            pass

    def _build_analysis_views(self):
        f = self._new_view("curves")
        self.curves_view = CurvesView(f, lambda: self.engine)
        self.curves_view.pack(fill=tk.BOTH, expand=True)
        self._strip_header(self.curves_view)

        f = self._new_view("loops")
        self.loops_view = CausalLoopView(f, lambda: self.engine)
        self.loops_view.pack(fill=tk.BOTH, expand=True)
        self._strip_header(self.loops_view)

        f = self._new_view("compare")
        self.compare_view = CompareView(f)
        self.compare_view.pack(fill=tk.BOTH, expand=True)
        self._strip_header(self.compare_view)

        f = self._new_view("leaderboard")
        self.leaderboard_view = LeaderboardView(f, path=self.leaderboard_path)
        self.leaderboard_view.pack(fill=tk.BOTH, expand=True)
        self._strip_header(self.leaderboard_view, nested=True)

    # -------------------------------------------------------------- game end
    def _build_end(self):
        f = self._new_view("end")
        sf = ScrollFrame(f)
        sf.pack(fill=tk.BOTH, expand=True)
        inner = sf.inner
        self.end_scroll = sf

        self.goal_wrap = tk.Frame(inner, bg=C["bg"])
        self.goal_wrap.pack(fill=tk.X)
        self.goal_banner = tk.Frame(self.goal_wrap, bg=blend(C["green"], C["bg"], 0.84), highlightthickness=1,
                                    highlightbackground=blend(C["green"], C["bg"], 0.45))
        gb = self.goal_banner
        self.goal_title = tk.Label(gb, text="", bg=gb["bg"], fg=C["green"], font=(FONT, 15, "bold"), anchor="w")
        self.goal_title.pack(fill=tk.X, padx=16, pady=(12, 0))
        self.goal_text = tk.Label(gb, text="", bg=gb["bg"], fg=C["text"], font=(FONT, 10), anchor="w",
                                  justify="left", wraplength=880)
        self.goal_text.pack(fill=tk.X, padx=16, pady=(2, 8))
        bar = tk.Frame(gb, bg=gb["bg"])
        bar.pack(fill=tk.X, padx=16, pady=(0, 14))
        self.continue_btn = ttk.Button(bar, text="Weiterspielen  →", style="Accent.TButton",
                                       command=self.continue_game)
        self.continue_btn.pack(side=tk.LEFT)
        ttk.Button(bar, text="Neues Spiel…", command=self.new_game).pack(side=tk.LEFT, padx=8)
        self.lb_btn = ttk.Button(bar, text="🏆 In Bestenliste eintragen…", command=self.prompt_leaderboard)
        self.lb_btn.pack(side=tk.LEFT)
        ttk.Button(bar, text="Bericht (HTML/PDF)…", command=self.export_report).pack(side=tk.LEFT, padx=8)
        self.goal_banner.pack(fill=tk.X, pady=(0, 10))

        self.end_select = tk.Frame(inner, bg=C["bg"])
        self.end_select.pack(fill=tk.X)

        top = tk.Frame(inner, bg=C["bg"])
        top.pack(fill=tk.X, pady=(0, 10))
        self.end_top = top
        top.columnconfigure(0, weight=2, uniform="end")
        top.columnconfigure(1, weight=3, uniform="end")
        top.columnconfigure(2, weight=0)

        sp = self._panel(top, "Bewertung")
        sp.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        self.score_label = tk.Label(sp, text="—", bg=C["panel"], fg=C["blue"], font=(FONT, 36, "bold"))
        self.score_label.pack(anchor="w", padx=14)
        self.grade_label = tk.Label(sp, text="", bg=C["panel"], fg=C["text"], font=(FONT, 12, "bold"),
                                    anchor="w", justify="left", wraplength=320)
        self.grade_label.pack(anchor="w", padx=14, fill=tk.X)
        self.grade_label.bind("<Configure>", lambda e: self.grade_label.config(wraplength=max(120, e.width - 6)))
        self.score_detail = tk.Label(sp, text="", bg=C["panel"], fg=C["muted"], font=("Consolas", 9),
                                     justify="left", anchor="w")
        self.score_detail.pack(anchor="w", padx=14, pady=(6, 14))

        ep = self._panel(top, "Endwerte", "Vergleich mit dem Startzustand")
        ep.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        self.end_values_title = ep.winfo_children()[0]
        self.end_values = tk.Label(ep, text="", bg=C["panel"], fg=C["text"], font=("Consolas", 10),
                                   justify="left", anchor="w")
        self.end_values.pack(anchor="w", padx=14, pady=(0, 10))
        bar = tk.Frame(ep, bg=C["panel"])
        bar.pack(fill=tk.X, padx=14, pady=(0, 14))
        ttk.Button(bar, text="Letzte Runde rückgängig", command=self.undo_round).pack(side=tk.LEFT)
        ttk.Button(bar, text="Bericht als CSV", command=self.export_csv).pack(side=tk.LEFT, padx=8)

        self.end_rank_panel = self._panel(top, "Rangliste", wrap=260)
        self.end_rank_box = tk.Frame(self.end_rank_panel, bg=C["panel"])
        self.end_rank_box.pack(fill=tk.X, padx=14, pady=(0, 12))

        grid = tk.Frame(inner, bg=C["bg"])
        grid.pack(fill=tk.X)
        self.end_charts = {}
        for i, key in enumerate(["population", "food_pc", "environment", "debt"]):
            _k, title, color, factor, kw, ref = next(c for c in CHARTS if c[0] == key)
            grid.columnconfigure(i % 2, weight=1, uniform="end")
            ch = LineChart(grid, title, C[color], height=180, **kw)
            ch.grid(row=i // 2, column=i % 2, sticky="nsew", padx=4, pady=4)
            self.end_charts[key] = (ch, factor, ref)
        self.end_capital_chart = MultiLineChart(inner, "Kapitalstöcke", height=230)
        self.end_capital_chart.pack(fill=tk.X, padx=4, pady=4)

    # -------------------------------------------------------------- settings
    def _build_settings(self):
        f = self._new_view("settings")
        self.settings_view = dialogs.SettingsView(
            f, load=lambda: self.settings, save=self._save_settings, on_tutorial=self.restart_tutorial,
            current_info=self._current_game_info)
        self.settings_view.pack(fill=tk.BOTH, expand=True)

    def _current_game_info(self):
        e = self.engine
        mins = ", ".join(MINISTRIES[k]["name"] for k in e.active_ministries()) or "keine"
        return (f"Aktuelles Spiel: Modus {MODES[self.world.mode]['name']}, {len(self.world.countries)} Land/Länder, "
                f"Szenario {SCENARIOS[e.scenario]['name']}, Ziel {dialogs.goal_label(e.goal_cycles)}, "
                f"Ereignisse {'an' if e.events_enabled else 'aus'}, Ministerien: {mins}.")

    # ------------------------------------------------------------- keybinds
    def _bind_keys(self):
        self.root.bind("<Return>", lambda e: self._key_evaluate(e))
        self.root.bind("<KP_Enter>", lambda e: self._key_evaluate(e))
        for seq in ("<Control-z>", "<Control-Z>"):
            self.root.bind(seq, lambda e: (self.undo_round(), "break")[1])
        for seq in ("<Control-s>", "<Control-S>"):
            self.root.bind(seq, lambda e: (self.save_game(), "break")[1])
        for seq in ("<Control-o>", "<Control-O>"):
            self.root.bind(seq, lambda e: (self.load_game(), "break")[1])
        self.root.bind("<F1>", lambda e: self.start_tutorial())

    def _key_evaluate(self, event):
        if self.overlay.visible:
            self.overlay.confirm()
            return "break"
        if isinstance(event.widget, (tk.Button, ttk.Button)):
            return None  # Buttons behalten ihr eigenes Verhalten
        if self.current_view == "decisions":
            self.evaluate_round()
        return "break"

    # ------------------------------------------------------------ layout sync
    def _sync_layout(self):
        """Passt Ministeriums-Felder, Weltnavigation, Bericht und Karten an die aktuelle Partie an."""
        e = self.engine
        active = e.active_ministries()
        key = (tuple(active), len(self.world.countries))
        if key == self._layout_key:
            return
        self._layout_key = key
        active_keys = {MINISTRIES[k]["input_key"] for k in active}
        for k in MINISTRY_INPUT_KEYS:
            for w in self.field_rows.get(k, []):
                if k in active_keys:
                    w.grid()
                else:
                    w.grid_remove()
            if k not in active_keys:
                self.field_msgs[k].grid_remove()
        if active:
            self.ministry_panel.pack(fill=tk.X, pady=(0, 10), after=self.section_panels[3])
        else:
            self.ministry_panel.pack_forget()
        self._rebuild_ministry_cards()
        if active:
            self.ministry_chart.grid()
            self.dash_lower.columnconfigure(1, weight=2)
        else:
            self.ministry_chart.grid_remove()
            self.dash_lower.columnconfigure(1, weight=0)
        self._rebuild_report_table()
        if self.multi:
            self.nav_buttons["world"].pack(fill=tk.X, padx=8, pady=1, before=self.nav_buttons["report"])
        else:
            self.nav_buttons["world"].pack_forget()
            if self.current_view == "world":
                self._show_view("dashboard")

    # ---------------------------------------------------------------- roles
    def role_order(self):
        try:
            return list(self.world.role_order())
        except Exception:
            return []

    def current_role(self):
        order = self.role_order()
        if not order or self.engine.game_over:
            return None
        return order[min(self._role_idx, len(order) - 1)]

    def role_person(self, role):
        name = ROLES.get(role, {}).get("name", role)
        person = (self.country.roles or {}).get(role)
        return person, name

    def editable_keys(self):
        e = self.engine
        if e.game_over:
            return set()
        role = self.current_role()
        if role is None:
            return set(e.active_input_keys())
        try:
            return set(self.world.role_fields(role))
        except Exception:
            return set(e.active_input_keys())

    # ---------------------------------------------------------------- inputs
    def _initial_inputs(self):
        e = self.engine
        if e.last_inputs and not e.game_over:
            return self._safe_suggest(e.last_inputs)
        if e.last_inputs:
            return dict(e.last_inputs)
        return self._safe_suggest(None)

    def _safe_suggest(self, base=None):
        try:
            return self.engine.suggest_inputs(base)
        except Exception:  # Engine-Fehler dürfen die GUI nicht sprengen
            return dict(base) if base else dict(DEFAULT_INPUTS)

    def _fill_inputs(self, values, only=None):
        """Füllt StringVars (optional nur ``only``) ohne für jedes Feld ein Live-Update auszulösen."""
        self._suspend_trace = True
        try:
            for k, var in self.vars.items():
                if only is not None and k not in only:
                    continue
                var.set(_fmt_input((values or {}).get(k, 0)))
        finally:
            self._suspend_trace = False
        self._schedule_live(0)

    def _active_keys(self):
        try:
            return list(self.engine.active_input_keys())
        except Exception:
            return list(INPUT_KEYS)

    def read_inputs(self):
        """Liest alle aktiven Felder. Liefert (inputs, parse_errors); ungültige Felder werden als 0 übergeben."""
        inputs, errors = {}, {}
        for k in self._active_keys():
            if k not in self.vars:
                continue
            raw = self.vars[k].get().strip().replace("'", "").replace("’", "").replace(" ", "")
            raw = raw.replace(",", ".") if raw.count(",") == 1 and "." not in raw else raw.replace(",", "")
            if raw == "":
                errors[k] = f"{INPUT_LABELS.get(k, k)}: bitte einen Wert eingeben."
                inputs[k] = 0.0
                continue
            try:
                inputs[k] = float(raw)
            except ValueError:
                errors[k] = f"{INPUT_LABELS.get(k, k)}: „{self.vars[k].get()}“ ist keine gültige Zahl."
                inputs[k] = 0.0
        return inputs, errors

    def _on_var_change(self, *_):
        if not self._suspend_trace:
            self._schedule_live(DEBOUNCE_MS)

    def _schedule_live(self, delay):
        if self._after_id is not None:
            try:
                self.root.after_cancel(self._after_id)
            except tk.TclError:
                pass
        self._after_id = self.root.after(delay, self._live_update)

    # ------------------------------------------------------------ live update
    def _live_update(self):
        self._after_id = None
        e = self.engine
        inputs, parse_errors = self.read_inputs()
        self._parse_errors = parse_errors

        try:
            budgets = e.budgets(inputs)
        except Exception:
            budgets = {}
        for key, bar in self.budget_bars.items():
            b = budgets.get(key, {})
            bar.set(_num(b, "available"), _num(b, "used"))
        ib = budgets.get("invest", {})
        self.invest_bar_local.set(_num(ib, "available"), _num(ib, "used"))
        self.invest_bar_min.set(_num(ib, "available"), _num(ib, "used"))

        issues = []
        if not e.game_over:
            try:
                issues = list(e.validate(inputs))
            except Exception as exc:
                issues = []
                parse_errors = dict(parse_errors)
                parse_errors["__engine__"] = f"Interner Fehler bei der Prüfung: {exc}"
        self._issues = issues

        errors = [i for i in issues if i.severity == "error"]
        has_errors = bool(errors) or bool(parse_errors)

        self._preview = None
        if not e.game_over and not has_errors:
            try:
                self._preview = e.preview(inputs)
            except Exception:
                self._preview = None

        self._mark_fields(issues, parse_errors)
        self._update_hints(inputs)
        self._update_forecast()
        self._update_live_warnings(issues, parse_errors)
        self._update_apply_state(errors, parse_errors)
        if self.current_view == "dashboard":
            self._refresh_dashboard(full=False)

    def _mark_fields(self, issues, parse_errors):
        per_field = {}
        for k, msg in parse_errors.items():
            if k in self.vars:
                per_field.setdefault(k, []).append(("error", msg))
        for i in issues:
            if i.field in self.vars and i.field not in parse_errors:
                per_field.setdefault(i.field, []).append((i.severity, i.message))
        active = set(self._active_keys())
        for k, wrap in self.field_frames.items():
            entries = per_field.get(k) if k in active else None
            msg = self.field_msgs[k]
            if not entries:
                wrap.config(highlightbackground=C["panel"], highlightcolor=C["panel"])
                msg.config(text="")
                msg.grid_remove()
                continue
            is_err = any(sev == "error" for sev, _ in entries)
            color = C["red"] if is_err else C["orange"]
            wrap.config(highlightbackground=color, highlightcolor=color)
            msg.config(text="\n".join(("✖ " if sev == "error" else "⚠ ") + m for sev, m in entries), fg=color)
            msg.grid()

    def _update_hints(self, inputs):
        e = self.engine
        try:
            req = e.requirements()
        except Exception:
            req = {}
        h = self.hints
        ef = _num(req, "energy_food_full")
        eg = _num(req, "energy_goods_full")
        h["energy_food"].config(text=f"Für 100 % Auslastung nötig: {ef:,.0f} EW",
                                fg=C["orange"] if inputs.get("energy_food", 0) < ef - 1e-6 else C["muted"])
        h["energy_goods"].config(text=f"Für 100 % Auslastung nötig: {eg:,.0f} EW",
                                 fg=C["orange"] if inputs.get("energy_goods", 0) < eg - 1e-6 else C["muted"])
        per_goods = _num(req, "energy_population_per_goods", 0.2)
        h["goods_domestic"].config(text=f"Bevölkerungsenergie: {inputs.get('goods_domestic', 0) * per_goods:,.0f} EW")
        cur = e.history[-1] if e.history else {}
        pop = _num(cur, "population")
        if pop > 0:
            yrs = getattr(e, "CYCLE_YEARS", 5)
            h["food_domestic"].config(
                text=f"≈ {inputs.get('food_domestic', 0) / (pop * yrs):,.2f} NW/Kopf/Jahr (Ziel ≥ 2,0)")
        h["energy_carryover"].config(text="Reserve für den nächsten Zyklus")
        h["new_loans"].config(text=f"Kreditlimit: {_num(req, 'max_new_loan'):,.0f} GE")
        h["repayments"].config(text=f"Schulden: {_num(req, 'debt'):,.0f} GE")
        h["foreign_aid"].config(text=f"Reserve aus Vorzyklus: {_num(req, 'cash_reserve'):,.0f} GE")
        h["import_food_money"].config(text=f"Importpreis-Faktor: {_num(req, 'import_mult'):,.3f}")
        mins = e.active_ministries()
        h["goods_investment"].config(text="Budget für Kapitalstöcke" + (" und Ministerien" if mins else " unten"))
        h["inv_energy_eff"].config(
            text=f"max. {inputs.get('inv_food', 0) + inputs.get('inv_goods', 0):,.0f} GW (Nahrung + Güter)")
        for mk in mins:
            m = MINISTRIES[mk]
            cap = _num(cur, m["capital_attr"])
            card = MINISTRY_CARDS[mk]
            val = _num(cur, card[0], 0.0) * card[4]
            h[m["input_key"]].config(text=f"Bestand {cap:,.0f} · {MINISTRY_HINTS[mk].format(val)}")
        try:
            money = e.budgets(inputs).get("money", {})
        except Exception:
            money = {}
        imf = _num(req, "imf_pending")
        market = req.get("market") if hasattr(req, "get") else None
        price_line = ""
        if isinstance(market, dict) and self.world.mode == "handel":
            ex = market.get("export_price", {})
            im = market.get("import_price", {})
            price_line = ("\nMarktpreise Ex/Im  " + "  ".join(
                f"{GOODS_NAMES[g][:4]} {_num(ex, g, 1):.2f}/{_num(im, g, 1):.2f}" for g in ("food", "goods", "energy")))
        self.finance_info.config(text=(
            f"Zinsen fällig     {_num(req, 'interest_due'):>10,.0f} GE   ({_num(req, 'annual_interest'):.2f} %/Jahr)\n"
            f"Kreditlimit       {_num(req, 'max_new_loan'):>10,.0f} GE   (Ø Exporte {_num(req, 'avg_exports'):,.0f})\n"
            f"Devisenreserve    {_num(req, 'cash_reserve'):>10,.0f} GE\n"
            f"Importbudget      {_num(money, 'available'):>10,.0f} GE   (verplant {_num(money, 'used'):,.0f})"
            + (f"\nIMF-Rückzahlung   {imf:>10,.0f}  (fällig)" if imf > 0 else "")
            + price_line
        ))

    def _current_state(self):
        h = self.engine.history
        return h[-1] if h else {}

    def _update_forecast(self):
        cur = self._current_state()
        pv = self._preview
        for key, _label, fmt, factor, good in FORECAST_ROWS:
            l_cur, l_pv, l_d = self.forecast_labels[key]
            c = _num(cur, key, None) if key in cur else None
            l_cur.config(text=fmt.format(c * factor) if c is not None else "—")
            if pv and key in pv and pv[key] is not None:
                p = float(pv[key])
                l_pv.config(text=fmt.format(p * factor))
                if c is not None:
                    d = (p - c) * factor
                    if abs(d) < 1e-9:
                        l_d.config(text="±0", fg=C["muted"])
                    else:
                        better = (d > 0) == good
                        l_d.config(text=("▲ +" if d > 0 else "▼ ") + fmt.format(d).lstrip("+"),
                                   fg=C["green"] if better else C["red"])
                else:
                    l_d.config(text="", fg=C["muted"])
            else:
                l_pv.config(text="—")
                l_d.config(text="", fg=C["muted"])

    def _fill_list(self, box, items, empty_text, bg=None, wrap=290):
        bg = bg or C["panel"]
        for w in box.winfo_children():
            w.destroy()
        if not items:
            tk.Label(box, text=empty_text, bg=bg, fg=C["green"], font=(FONT, 9), anchor="w",
                     justify="left", wraplength=wrap).pack(fill=tk.X, pady=2)
            return
        for color, text in items:
            tk.Label(box, text=text, bg=bg, fg=color, font=(FONT, 9), anchor="w", justify="left",
                     wraplength=wrap).pack(fill=tk.X, pady=2)

    def _update_live_warnings(self, issues, parse_errors):
        items = []
        if self.engine.game_over:
            items.append((C["muted"], "Ziel erreicht – „Weiterspielen“ in der Auswertung erlaubt weitere Zyklen."))
        if parse_errors:
            items.append((C["red"], f"✖ {len(parse_errors)} Feld(er) enthalten keine gültige Zahl."))
        for i in issues:
            if i.field is None or i.field not in self.vars:
                items.append((C["red"] if i.severity == "error" else C["orange"],
                              ("✖ " if i.severity == "error" else "⚠ ") + i.message))
        for i in issues:
            if i.field in self.vars and i.severity == "warning":
                items.append((C["orange"], "⚠ " + i.message))
        self._fill_list(self.live_warn_box, items, "✔ Alle Eingaben sind zulässig.")

    def _update_apply_state(self, errors, parse_errors):
        e = self.engine
        reason = ""
        role = self.current_role()
        role_step = role is not None and role != "praesidium"
        editable = self.editable_keys()
        if e.game_over:
            reason = "Ziel erreicht – in der Auswertung „Weiterspielen“ wählen, um fortzufahren."
        elif role_step:
            own_parse = [k for k in parse_errors if k in editable]
            if own_parse:
                reason = "Bitte zuerst ungültige Zahlen in deinen Feldern korrigieren."
        elif parse_errors:
            reason = "Bitte zuerst ungültige Zahlen korrigieren (rot markiert)."
        elif errors:
            n = len(errors)
            reason = f"{n} Fehler verhindern die Auswertung: " + errors[0].message
        self._can_apply = not reason
        if role_step:
            self.apply_btn.config(text="Rolle abschließen  →")
        else:
            self.apply_btn.config(text="Runde freigeben  ⏎" if role == "praesidium" else "Runde auswerten  ⏎")
        self.apply_btn.state(["!disabled"] if self._can_apply else ["disabled"])
        note_color = C["red"]
        if role_step and not reason and (errors or parse_errors):
            reason = (f"Hinweis: {len(errors) + len(parse_errors)} Fehler im Gesamtplan – das Präsidium muss sie "
                      "vor der Freigabe beheben.")
            note_color = C["orange"]
        self.apply_reason.config(text=reason, fg=note_color)
        self.undo_btn.state(["!disabled"] if self._can_undo() else ["disabled"])
        self.suggest_btn.state(["disabled"] if e.game_over else ["!disabled"])
        self.advisor_btn.state(["disabled"] if e.game_over else ["!disabled"])

    def _can_undo(self):
        try:
            if self.world.can_undo():
                return True
            return len(self.world.countries) == 1 and bool(self.engine.can_undo())
        except Exception:
            return False

    def _apply_field_locks(self):
        editable = self.editable_keys()
        role = self.current_role()
        for k, sp in self.spinboxes.items():
            ok = k in editable
            sp.state(["!disabled"] if ok else ["disabled"])
            self.field_labels[k].config(fg=C["text"] if ok or role is None else "#5d6b84")
        if role is not None:
            person, rname = self.role_person(role)
            who = f"{person} – {rname}" if person else rname
            if role == "praesidium":
                text = ("Das Präsidium sieht alle Entscheidungen, darf jedes Feld anpassen und gibt die Runde "
                        "mit „Runde freigeben“ frei.")
            else:
                labels = ", ".join(INPUT_LABELS.get(k, k) for k in self.world.role_fields(role))
                text = (f"Deine Felder: {labels}. Andere Felder sind gesperrt (sichtbar). "
                        f"Danach „Rolle abschließen →“.")
            order = self.role_order()
            step = f"Rolle {min(self._role_idx, len(order) - 1) + 1} von {len(order)}"
            self.role_banner.title_lbl.config(text=f"👤  {who}  ·  {step}  ·  {self.country.name}")
            self.role_banner.text_lbl.config(text=text)
            self.role_banner.pack(fill=tk.X, pady=(0, 8))
        else:
            self.role_banner.pack_forget()
        self._collapse(self.dec_banners)

    # ---------------------------------------------------------------- actions
    def evaluate_round(self):
        """Wertet den Zyklus aus (Button / Enter); im Rollenmodus schließt es die aktuelle Rolle ab."""
        if self.overlay.visible:
            return None
        if self._after_id is not None:
            self.root.after_cancel(self._after_id)
        self._live_update()
        if not self._can_apply:
            self._status("Nicht möglich: " + self.apply_reason.cget("text"), C["red"])
            return None
        role = self.current_role()
        if role is not None and role != "praesidium":
            return self.complete_role()
        inputs, _ = self.read_inputs()
        prev = self.world.active
        country = self.country
        try:
            result = self.world.submit(inputs)
        except ValueError as exc:
            self._status(f"Runde nicht ausgewertet: {exc}", C["red"])
            self._live_update()
            return None
        self._role_idx = 0
        self._clear_advice(refresh=False)
        name = f"{country.name}: " if self.multi else ""
        self._status(f"{name}Zyklus {result.get('runde', '?')} ausgewertet (Jahr {result.get('jahr_start', '?')}–"
                     f"{result.get('jahr_end', '?')}).", C["green"])
        switched = self.world.active != prev
        if switched or self.role_order():
            self._fill_inputs(self._initial_inputs())
        self._after_state_change(keep_inputs=True)
        if self.world.game_over():
            self._on_goal_reached()
        else:
            self._maybe_handover()
        return result

    def complete_role(self):
        role = self.current_role()
        if role is None:
            return None
        person, rname = self.role_person(role)
        self._role_idx += 1
        self._clear_advice(refresh=False)
        self._status(f"Rolle {rname} abgeschlossen.", C["blue"])
        self._apply_field_locks()
        self._live_update()
        self._maybe_handover()
        return role

    def _maybe_handover(self):
        """Zeigt den Zwischenbildschirm, wenn mehrere Länder oder Rollen im Spiel sind."""
        if self.world.game_over():
            self.overlay.hide()
            return
        role = self.current_role()
        if not self.multi and role is None:
            self.overlay.hide()
            return
        c = self.country
        e = c.engine
        detail = [f"{c.name} · Zyklus {e.runde} · Jahr {(e.runde - 1) * CYCLE_YEARS}–{e.runde * CYCLE_YEARS}"]
        if role is not None:
            person, rname = self.role_person(role)
            name = person or rname
            detail.insert(0, f"Rolle: {rname}" + (f" ({ROLES[role]['description']})" if role in ROLES else ""))
        else:
            name = c.name
        if self.multi:
            done = sum(1 for x in self.world.countries if x.engine.runde > e.runde)
            detail.append(f"{done} von {len(self.world.countries)} Ländern haben diesen Zyklus bereits gespielt.")
        ev = e.current_event()
        if ev:
            detail.append(f"⚡ Ereignis im kommenden Zyklus: {ev['name']}")
        can_back = self._can_undo() and (self.multi or self._role_idx == 0)
        self.overlay.show(name, c.color, "\n".join(detail), on_continue=self._after_handover,
                          top=f"ÜBERGABE · {MODES[self.world.mode]['name'].upper()}",
                          back_text="← Letzten Zug zurücknehmen (Strg+Z)",
                          on_back=self.undo_round if can_back else None)

    def _after_handover(self):
        if self.current_view not in ("decisions", "dashboard"):
            self._show_view("decisions")
        self.root.focus_set()

    def apply_suggestion(self):
        if self.engine.game_over:
            return
        inputs, _ = self.read_inputs()
        editable = self.editable_keys()
        self._fill_inputs(self._safe_suggest(inputs), only=editable)
        if self.current_role() not in (None, "praesidium"):
            self._status("Vorschlag für deine Felder übernommen.", C["blue"])
        else:
            self._status("Vorschlag übernommen – alle Budgets passen.", C["blue"])

    def ask_advisor(self):
        """Berater: übernimmt die beste Variante und zeigt die Begründungen unter dem Button."""
        if self.engine.game_over:
            return None
        try:
            self.root.config(cursor="watch")
            self.root.update_idletasks()
            inputs, reasons = self.engine.advise_inputs()
        except Exception as exc:
            self._status(f"Berater nicht verfügbar: {exc}", C["red"])
            return None
        finally:
            try:
                self.root.config(cursor="")
            except tk.TclError:
                pass
        editable = self.editable_keys()
        partial = editable != set(self._active_keys())
        self._fill_inputs(inputs, only=editable)
        reasons = list(reasons or [])
        if partial:
            reasons.insert(0, "Nur deine Felder wurden übernommen – die übrigen entscheiden die anderen Rollen.")
        self._advice = reasons
        self._show_advice()
        self._status("Berater-Empfehlung übernommen – Begründung im Panel rechts.", C["green"])
        return inputs, reasons

    def _show_advice(self):
        for w in self.advice_box.winfo_children():
            w.destroy()
        if not self._advice:
            self.advice_panel.pack_forget()
            return
        for r in self._advice:
            tk.Label(self.advice_box, text="• " + r, bg="#0f2420", fg=C["text"], font=(FONT, 9), anchor="w",
                     justify="left", wraplength=280).pack(fill=tk.X, pady=1)
        self.advice_panel.pack(fill=tk.X, pady=(0, 8), after=self.act_panel)

    def _clear_advice(self, refresh=True):
        self._advice = None
        self._show_advice()

    def undo_round(self):
        if not self._can_undo():
            self._status("Nichts rückgängig zu machen.")
            return
        prev = self.world.active
        if self.world.can_undo():
            idx = self.world._last_submit["index"] if getattr(self.world, "_last_submit", None) else prev
            eng = self.world.countries[idx].engine
            undone = dict(eng.last_inputs) if eng.last_inputs else None
            ok = self.world.undo()
        else:
            eng = self.engine
            undone = dict(eng.last_inputs) if eng.last_inputs else None
            ok = eng.undo()
            if ok:
                del self.world.market_history[max(0, len(eng.history) - 1):]
                self.world.active = 0
        if not ok:
            self._status("Rückgängig nicht möglich.", C["red"])
            return
        self.overlay.hide()
        self._role_idx = 0
        self._clear_advice(refresh=False)
        self._goal_prompted = self.world.game_over()
        self._after_state_change(keep_inputs=False, values=undone)
        self._status("Letzter Zug rückgängig gemacht – Eingaben wiederhergestellt.", C["blue"])
        if self.current_view == "end" and not self.world.game_over():
            self._show_view("decisions")
        if self.world.active != prev or self.role_order():
            self._maybe_handover()

    def continue_game(self):
        """Nach Erreichen des Ziels weiterspielen."""
        if not self.world.game_over():
            self._show_view("decisions")
            return
        self.world.continue_play()
        self._role_idx = 0
        self._after_state_change(keep_inputs=False)
        self._show_view("decisions")
        self._status("Weiter geht's – es gibt kein weiteres Ziel, die Auswertung bleibt erreichbar.", C["green"])
        self._maybe_handover()

    def new_game(self):
        if any(c.engine.cycles_played > 0 for c in self.world.countries) and not messagebox.askyesno(
                "Neues Spiel", "Das laufende Spiel wird verworfen. Fortfahren?", parent=self.root):
            return None
        cfg = dialogs.ask_new_game(self.root, self.settings)
        if not cfg:
            return None
        return self.start_new_game(cfg)

    def start_new_game(self, cfg):
        """Startet eine neue Partie aus einer Konfiguration (Ergebnis des Neues-Spiel-Dialogs)."""
        cfg = dict(cfg or {})
        mode = cfg.get("mode", "solo")
        names = list(cfg.get("names") or ["Land 1"])
        if mode in ("solo", "rollen"):
            names = names[:1]
        try:
            world = World.create(mode, names, scenario=cfg.get("scenario", "standard"),
                                 events_enabled=bool(cfg.get("events", False)), seed=cfg.get("seed"),
                                 ministries=cfg.get("ministries") or dialogs.settings_ministries(self.settings),
                                 roles=cfg.get("roles"),
                                 goal_cycles=cfg.get("goal_cycles", dialogs.settings_goal(self.settings)))
        except Exception as exc:
            messagebox.showerror("Neues Spiel", f"Das Spiel konnte nicht gestartet werden:\n{exc}", parent=self.root)
            return None
        self._set_world(world)
        self._status(f"Neues Spiel gestartet: {MODES[mode]['name']}, {len(names)} Land/Länder, "
                     f"Ziel {dialogs.goal_label(self.engine.goal_cycles)}.", C["blue"])
        return world

    def _set_world(self, world, gui_state=None):
        self.overlay.hide()
        self.world = world
        gui_state = gui_state or {}
        self._role_idx = int(gui_state.get("role_idx", 0) or 0)
        self._lb_done = set(gui_state.get("leaderboard_done", []) or [])
        self._goal_prompted = self.world.game_over()
        self._end_idx = 0
        self._clear_advice(refresh=False)
        self._sync_layout()
        self._fill_inputs(self._initial_inputs())
        self._refresh_all()
        self._show_view("end" if self.world.game_over() else "decisions")
        self._maybe_handover()

    # --------------------------------------------------------------- goal
    def _on_goal_reached(self):
        self._end_idx = 0
        self._show_view("end")
        if not self._goal_prompted:
            self._goal_prompted = True
            self.root.after(150, self.prompt_leaderboard)

    def _lb_eligible(self, eng):
        return bool(eng.goal_reached) or (eng.goal_cycles is None and eng.cycles_played >= 1)

    def leaderboard_entry(self, name, eng):
        """Bestenlisten-Eintrag; nach dem Ziel zählt der Stand beim Zielerreichen."""
        entry = store.entry_from_engine(name, eng)
        snap = getattr(eng, "goal_snapshot", None)
        if isinstance(snap, dict):
            sc = snap.get("score") or {}
            if "total" in sc:
                entry["score"] = round(float(sc["total"]), 2)
                entry["grade"] = sc.get("grade", entry["grade"])
            for k in ("population", "environment", "debt", "food_pc"):
                if snap.get(k) is not None:
                    entry[k] = float(snap[k])
            entry["goal_years"] = snap.get("goal_years")
            entry["years"] = snap.get("jahr_end")
        else:
            entry["goal_years"] = eng.goal_years
            entry["years"] = _num(eng.history[-1] if eng.history else {}, "jahr_end", 0)
        entry["mode"] = self.world.mode
        entry["ministries"] = eng.active_ministries()
        return entry

    def add_to_leaderboard(self, names_by_index):
        added = 0
        for idx, name in names_by_index.items():
            eng = self.world.countries[idx].engine
            store.add_entry(self.leaderboard_entry(name, eng), self.leaderboard_path)
            self._lb_done.add(idx)
            added += 1
        try:
            self.leaderboard_view.refresh()
        except Exception:
            pass
        self._refresh_end()
        return added

    def prompt_leaderboard(self):
        pending = [i for i, c in enumerate(self.world.countries)
                   if i not in self._lb_done and self._lb_eligible(c.engine)]
        if not pending:
            self._status("Keine offenen Bestenlisten-Einträge (bereits eingetragen oder Ziel noch nicht erreicht).")
            return 0
        defaults = [self.world.countries[i].name for i in pending]
        eng = self.world.countries[pending[0]].engine
        info = (f"Ziel {dialogs.goal_label(eng.goal_cycles)} · Szenario {SCENARIOS[eng.scenario]['name']}. "
                f"Gewertet wird der Stand beim Erreichen des Ziels.")
        names = dialogs.ask_names(self.root, defaults, info)
        if not names:
            self._status("Nicht in die Bestenliste eingetragen.")
            return 0
        n = self.add_to_leaderboard(dict(zip(pending, names)))
        self._status(f"{n} Eintrag/Einträge in die Bestenliste aufgenommen.", C["green"])
        return n

    # ------------------------------------------------------------- save/load
    def world_json(self):
        data = json.loads(self.world.to_json())
        # Kompatibel zur Vergleichsansicht und älteren Versionen: zusätzlich "players".
        data["players"] = [{"name": c.name, "engine": c.engine.to_json()} for c in self.world.countries]
        data["gui"] = {"leaderboard_done": sorted(self._lb_done), "role_idx": self._role_idx}
        return json.dumps(data, ensure_ascii=False)

    def load_world_json(self, text):
        world = World.from_json(text)
        try:
            gui = json.loads(text).get("gui") or {}
        except Exception:
            gui = {}
        self._set_world(world, gui)
        return world

    def save_game(self):
        if self.overlay.visible:
            return
        path = filedialog.asksaveasfilename(parent=self.root, title="Spielstand speichern",
                                            defaultextension=".json",
                                            filetypes=[("Equivara-Spielstand", "*.json"), ("Alle Dateien", "*.*")])
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(self.world_json())
        except OSError as exc:
            messagebox.showerror("Speichern fehlgeschlagen", str(exc), parent=self.root)
            return
        self._status(f"Gespeichert: {path}", C["green"])

    def load_game(self):
        path = filedialog.askopenfilename(parent=self.root, title="Spielstand laden",
                                          filetypes=[("Equivara-Spielstand", "*.json"), ("Alle Dateien", "*.*")])
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as fh:
                text = fh.read()
            self.load_world_json(text)
        except Exception as exc:  # defekte Datei, falsches Format …
            messagebox.showerror("Laden fehlgeschlagen", f"Die Datei konnte nicht geladen werden:\n{exc}",
                                 parent=self.root)
            return
        self._status(f"Geladen: {path}", C["green"])

    # --------------------------------------------------------------- export
    def export_csv(self):
        hist = self.engine.history
        if not hist:
            return
        path = filedialog.asksaveasfilename(parent=self.root, title="Bericht als CSV exportieren",
                                            defaultextension=".csv",
                                            filetypes=[("CSV", "*.csv"), ("Alle Dateien", "*.*")])
        if not path:
            return
        try:
            self.write_csv(path)
        except OSError as exc:
            messagebox.showerror("Export fehlgeschlagen", str(exc), parent=self.root)
            return
        self._status(f"Bericht exportiert: {path}", C["green"])

    def write_csv(self, path):
        """Schreibt die gesamte Historie (eine Zeile pro Zyklus) als CSV (Semikolon-getrennt)."""
        hist = self.engine.history
        keys = []
        for row in hist:
            for k, v in row.items():
                if k not in keys and isinstance(v, (int, float, bool)):
                    keys.append(k)
        labels = {k: lbl for k, lbl, _ in REPORT_ROWS}
        for rows in MINISTRY_REPORT_ROWS.values():
            labels.update({k: lbl for k, lbl, _ in rows})
        with open(path, "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.writer(fh, delimiter=";")
            w.writerow([labels.get(k, k) for k in keys])
            for row in hist:
                w.writerow([row.get(k, "") for k in keys])

    def write_report(self, path):
        runs = [(c.name, c.engine) for c in self.world.countries]
        export_html(path, runs, title=f"Equivara Bericht – {MODES[self.world.mode]['name']}")

    def export_report(self):
        path = filedialog.asksaveasfilename(parent=self.root, title="Bericht (HTML/PDF) exportieren",
                                            defaultextension=".html",
                                            filetypes=[("HTML-Bericht", "*.html"), ("Alle Dateien", "*.*")])
        if not path:
            return
        try:
            self.write_report(path)
        except Exception as exc:
            messagebox.showerror("Export fehlgeschlagen", str(exc), parent=self.root)
            return
        self._status(f"Bericht gespeichert: {path} – im Browser öffnen und als PDF drucken.", C["green"])

    def export_png(self):
        path = filedialog.asksaveasfilename(parent=self.root, title="Ansicht als PNG speichern",
                                            defaultextension=".png",
                                            filetypes=[("PNG-Bild", "*.png"), ("Alle Dateien", "*.*")])
        if not path:
            return
        if export_canvas_png(self.content, path):
            self._status(f"Bild gespeichert: {path}", C["green"])
        else:
            messagebox.showinfo("PNG-Export", "Der PNG-Export benötigt das Paket Pillow (pip install pillow).",
                                parent=self.root)

    # -------------------------------------------------------------- tutorial
    def _tutorial_steps(self):
        sv = self._show_view
        return [
            {"title": "Willkommen bei Equivara", "target": lambda: None, "before": lambda: sv("decisions"),
             "text": "Du lenkst ein Land über mehrere Jahrzehnte. Jeder Zyklus umfasst 5 Jahre. Ziel: "
                     "Versorgung sichern, Umwelt schützen und Schulden im Griff behalten."},
            {"title": "Navigation", "target": lambda: self.nav_frame, "before": None,
             "text": "Hier wechselst du zwischen Entscheidungen, Dashboard, Bericht und Analysen. "
                     "„Welt“ erscheint, wenn mehrere Länder spielen."},
            {"title": "Deine Entscheidungen", "target": lambda: self.section_panels[0], "before": None,
             "text": "Verteile Nahrung, Güter, Energie, Devisen und Investitionen. Fehler werden direkt am "
                     "Feld angezeigt, Tooltips erklären jedes Feld."},
            {"title": "Live-Budgets und Prognose", "target": lambda: self.budget_panel, "before": None,
             "text": "Die Balken zeigen, wie viel von jedem Budget verplant ist. Darunter siehst du die "
                     "Prognose für den nächsten Zyklus."},
            {"title": "Der Berater", "target": lambda: self.advisor_btn, "before": None,
             "text": "Unsicher? Der Berater rechnet viele Varianten durch, übernimmt die beste und erklärt "
                     "seine Begründung im Panel darunter."},
            {"title": "Runde auswerten", "target": lambda: self.apply_btn, "before": None,
             "text": "Mit diesem Button (oder Enter) wird der Zyklus berechnet. Strg+Z macht ihn rückgängig."},
            {"title": "Dashboard und Land-Karte", "target": lambda: self.country_map,
             "before": lambda: sv("dashboard"),
             "text": "Kennzahlen, Diagramme und eine Karte deines Landes: Felder wachsen mit den Kapitalstöcken, "
                     "die Natur färbt sich mit der Umweltqualität."},
            {"title": "Einstellungen", "target": lambda: self.nav_buttons["settings"],
             "before": lambda: sv("decisions"),
             "text": "Hier schaltest du Ministerien an, wählst das Standard-Ziel und kannst diese Tour erneut "
                     "starten. Neues Spiel startest du unten links."},
        ]

    def start_tutorial(self):
        if self.tutorial is not None and getattr(self.tutorial, "active", False):
            return
        if self.overlay.visible:
            self.overlay.confirm()
        self.tutorial = Tutorial(self.root, self._tutorial_steps(), on_finish=self._tutorial_done)
        self.tutorial.start()

    def restart_tutorial(self):
        self.start_tutorial()

    def _tutorial_done(self):
        s = dict(self.settings)
        s["tutorial_done"] = True
        try:
            self._save_settings(s)
        except Exception:
            pass

    # --------------------------------------------------------------- refresh
    def _after_state_change(self, keep_inputs, values=None):
        """Nach apply/undo/reset/load: Eingaben (ggf.) neu füllen und alle Ansichten aktualisieren."""
        e = self.engine
        self._sync_layout()
        if not keep_inputs:
            if values:
                self._fill_inputs(values)
            else:
                self._fill_inputs(self._initial_inputs())
        self._refresh_all()

    def _cycle_texts(self):
        e = self.engine
        if self.world.game_over():
            g = e.goal_years
            return "ZIEL ERREICHT", f"Jahr 0–{g if g is not None else e.cycles_played * CYCLE_YEARS} · Weiterspielen möglich"
        cyc = e.runde
        years = f"Jahr {(cyc - 1) * CYCLE_YEARS}–{cyc * CYCLE_YEARS}"
        if e.goal_cycles is None:
            text = f"Zyklus {cyc} · {years} (endlos)"
        elif e.goal_reached:
            text = f"Zyklus {cyc} · {years} (Ziel erreicht)"
        else:
            text = f"Zyklus {cyc} / {e.goal_cycles} · {years}"
        return text, None

    def _refresh_header(self):
        text, alt = self._cycle_texts()
        over = self.world.game_over()
        self.cycle_label.config(text=text, fg=C["orange"] if over else C["blue"])
        c = self.country
        parts = [f"● {c.name}"]
        if self.multi:
            parts.append(MODES[self.world.mode]["name"] + ("" if over else " · am Zug"))
        elif self.world.mode != "solo":
            parts.append(MODES[self.world.mode]["name"])
        role = self.current_role()
        if role is not None:
            person, rname = self.role_person(role)
            parts.append(f"Rolle {rname}" + (f" ({person})" if person else ""))
        if alt:
            parts.append(alt)
        self.year_label.config(text="  ·  ".join(parts), fg=c.color)
        e = self.engine
        self.side_info.config(text=f"{SCENARIOS[e.scenario]['name'].upper()}  •  ZIEL "
                                   f"{dialogs.goal_label(e.goal_cycles).upper()}"
                                   + ("  •  EREIGNISSE" if e.events_enabled else ""))

    def _refresh_event_banners(self):
        try:
            ev = self.engine.current_event()
        except Exception:
            ev = None
        for banner in (self.dec_event_banner, self.dash_event_banner):
            if ev:
                banner.title_lbl.config(text=f"⚡  Ereignis im kommenden Zyklus: {ev.get('name', '')}")
                banner.text_lbl.config(text=ev.get("description", "") + "  Der Berater und die Prognose "
                                                                      "berücksichtigen es bereits.")
                banner.pack(fill=tk.X, pady=(0, 8))
            else:
                banner.pack_forget()
        self._collapse(self.dec_banners)
        self._collapse(self.dash_banners)

    def _refresh_all(self):
        over = self.world.game_over()
        self._refresh_header()
        self._refresh_event_banners()
        self._apply_field_locks()
        self.nav_buttons["end"].config(state=tk.NORMAL if self._end_available() else tk.DISABLED)
        self.nav_buttons["end"].config(text="Ziel erreicht ★" if over else "Auswertung")
        self.dash_go_btn.config(text="Zur Auswertung →" if over else "Zu den Entscheidungen →",
                                command=lambda: self._show_view("end" if self.world.game_over() else "decisions"))
        self._update_title()
        self._live_update()
        if self.current_view:
            self._refresh_view(self.current_view)

    def _refresh_view(self, key):
        try:
            if key == "dashboard":
                self._refresh_dashboard()
            elif key == "report":
                self._refresh_report()
            elif key == "end":
                self._refresh_end()
            elif key == "world":
                self._refresh_world()
            elif key == "curves":
                self.curves_view.refresh()
            elif key == "loops":
                self.loops_view.refresh()
            elif key == "compare":
                self._refresh_compare()
            elif key == "leaderboard":
                self.leaderboard_view.refresh()
            elif key == "settings":
                self.settings_view.refresh()
        except tk.TclError:
            pass

    def _series(self, key, factor=1.0, engine=None):
        hist = (engine or self.engine).history
        xs, ys = [], []
        for row in hist:
            if key in row and row[key] is not None:
                xs.append(float(row.get("jahr_end", 0)))
                ys.append(float(row[key]) * factor)
        return xs, ys

    def _preview_point(self, key, factor):
        pv = self._preview
        if not pv or key not in pv:
            return None
        return (float(pv.get("jahr_end", 0)), float(pv[key]) * factor)

    def _refresh_dashboard(self, full=True):
        hist = self.engine.history
        cur = hist[-1] if hist else {}
        prev = hist[-2] if len(hist) >= 2 else None
        pv = self._preview
        for cards in (self.stat_cards, self.min_cards):
            for key, (card, factor, good) in cards.items():
                value = _num(cur, key) * factor
                previous = _num(prev, key) * factor if prev and key in prev else None
                preview = _num(pv, key) * factor if pv and key in pv else None
                card.set(value, previous=previous, preview=preview, good_when_up=good)
        for key, (ch, factor, ref) in self.charts.items():
            xs, ys = self._series(key, factor)
            ch.set_data(xs, ys, preview=self._preview_point(key, factor), reference=ref)
        if not full:
            return
        self._set_capital(self.capital_chart)
        active = self.engine.active_ministries()
        if active:
            xs = [float(r.get("jahr_end", 0)) for r in hist]
            series = [(MINISTRIES[k]["name"], C[MINISTRIES[k]["color_hint"]],
                       [_num(r, MINISTRIES[k]["capital_attr"]) for r in hist]) for k in active]
            self.ministry_chart.set_series(xs, series)
        try:
            self.country_map.refresh()
        except Exception:
            pass
        try:
            warns = list(self.engine.warnings())
        except Exception:
            warns = []
        self._fill_list(self.dash_warn_box, [(C["orange"], "⚠ " + w) for w in warns],
                        "✔ Keine Systemwarnungen.", wrap=360)

    def _set_capital(self, chart, engine=None):
        hist = (engine or self.engine).history
        xs = [float(r.get("jahr_end", 0)) for r in hist]
        series = [(label, C[color], [_num(r, key) for r in hist]) for key, label, color in CAPITAL_SERIES]
        chart.set_series(xs, series)

    def _refresh_report(self):
        self._rebuild_report_table()
        self.history_table.set_history(self.engine.history)

    def _refresh_compare(self):
        auto = [(c.name, c.engine.history) for c in self.world.countries]
        auto_names = {n for n, _ in self._compare_auto}
        others = [(n, h) for n, h in self.compare_view.runs if n not in auto_names]
        self._compare_auto = auto
        self.compare_view.set_runs(auto + others)

    # -------------------------------------------------------------- ranking
    def _ranking_rows(self):
        rows = []
        by_name = {c.name: (i, c) for i, c in enumerate(self.world.countries)}
        try:
            ranking = self.world.ranking()
        except Exception:
            ranking = [(c.name, 0.0) for c in self.world.countries]
        for name, score in ranking:
            i, c = by_name.get(name, (None, None))
            if c is None:
                continue
            try:
                grade = c.engine.score().get("grade", "")
            except Exception:
                grade = ""
            rows.append((i, c, score, grade))
        return rows

    def _fill_ranking(self, box, wrap=360, compact=False):
        for w in box.winfo_children():
            w.destroy()
        medals = {0: "🥇", 1: "🥈", 2: "🥉"}
        for pos, (i, c, score, grade) in enumerate(self._ranking_rows()):
            row = tk.Frame(box, bg=C["panel"])
            row.pack(fill=tk.X, pady=2)
            active = (i == self.world.active and not self.world.game_over())
            tk.Label(row, text=medals.get(pos, f"{pos + 1}."), bg=C["panel"], fg=C["text"], font=(FONT, 11),
                     width=3, anchor="w").pack(side=tk.LEFT)
            tk.Label(row, text="●", bg=C["panel"], fg=c.color, font=(FONT, 12)).pack(side=tk.LEFT)
            tk.Label(row, text=c.name + ("  (am Zug)" if active else ""), bg=C["panel"], fg=C["text"],
                     font=(FONT, 10, "bold"), anchor="w").pack(side=tk.LEFT, padx=(4, 0))
            last = c.engine.history[-1] if c.engine.history else {}
            tk.Label(row, text=f"{score:5.1f}  {grade}", bg=C["panel"], fg=C["cyan"], font=("Consolas", 10, "bold"),
                     anchor="e").pack(side=tk.RIGHT)
            if not compact:
                tk.Label(row, text=f"Bev. {_num(last, 'population'):,.0f} · Z{c.engine.cycles_played}",
                         bg=C["panel"], fg=C["muted"], font=(FONT, 8), anchor="e").pack(side=tk.RIGHT, padx=8)

    def _refresh_world(self):
        try:
            self.world_map.refresh()
        except Exception:
            pass
        mh = list(self.world.market_history)
        xs = [i * CYCLE_YEARS for i in range(len(mh) + 1)]
        series = []
        for g, color in (("food", "orange"), ("goods", "purple"), ("energy", "cyan")):
            ys = [_num(h.get("prices", {}).get("export_price", {}), g, 1.0) for h in mh]
            ys.append(_num(self.world.market.get("export_price", {}), g, 1.0))
            series.append((GOODS_NAMES[g], C[color], ys))
        self.price_chart.set_series(xs, series)
        self._fill_ranking(self.ranking_box)
        if mh:
            last = mh[-1]
            lines = [f"{'':<10}{'Angebot':>10}{'Nachfrage':>11}{'Preis':>8}{'→ neu':>8}"]
            for g in ("food", "goods", "energy"):
                lines.append(f"{GOODS_NAMES[g]:<10}{_num(last.get('supply'), g):>10,.0f}"
                             f"{_num(last.get('demand'), g):>11,.0f}"
                             f"{_num(last.get('prices', {}).get('export_price'), g, 1):>8.2f}"
                             f"{_num(last.get('next_prices', {}).get('export_price'), g, 1):>8.2f}")
            note = ("Gemeinsamer Markt: Knappheit verteuert, Überangebot verbilligt (Grenzen 0,5–2,0)."
                    if self.world.mode == "handel" else "Fester Weltmarkt – die Länder beeinflussen sich nicht.")
            lines.append("")
            lines.append(f"Zyklus {last.get('cycle', len(mh))} · {note}")
            self.market_info.config(text="\n".join(lines))
        else:
            self.market_info.config(text="Noch kein Zyklus abgeschlossen – sobald alle Länder gespielt haben, "
                                         "erscheinen hier Angebot, Nachfrage und Preise.")

    # --------------------------------------------------------------- scoring
    def compute_score(self, engine=None):
        """Score 0–100 aus engine.score(); liefert (total, {Anzeigename: (punkte, max)})."""
        eng = engine or self.engine
        try:
            sc = eng.score()
        except Exception:
            return 0.0, {}
        parts = {SCORE_PART_NAMES.get(k, k): (float(p), float(m)) for k, (p, m) in sc.get("parts", {}).items()}
        return float(sc.get("total", 0.0)), parts

    def _end_engine(self):
        idx = min(max(0, self._end_idx), len(self.world.countries) - 1)
        return self.world.countries[idx]

    def _rebuild_end_select(self):
        for w in self.end_select.winfo_children():
            w.destroy()
        if not self.multi:
            return
        tk.Label(self.end_select, text="Auswertung für:", bg=C["bg"], fg=C["muted"], font=(FONT, 10)).pack(
            side=tk.LEFT, padx=(0, 8), pady=(0, 8))
        for i, c in enumerate(self.world.countries):
            sel = i == self._end_idx
            b = tk.Button(self.end_select, text=f"● {c.name}", relief="flat", bd=0, cursor="hand2",
                          bg="#17243d" if sel else C["panel"], fg=c.color, activebackground="#1c2a45",
                          activeforeground=c.color, font=(FONT, 10, "bold"), padx=12, pady=4,
                          command=lambda k=i: self._select_end(k))
            b.pack(side=tk.LEFT, padx=2, pady=(0, 8))

    def _select_end(self, idx):
        self._end_idx = idx
        self._refresh_end()

    def _refresh_end(self):
        country = self._end_engine()
        eng = country.engine
        hist = eng.history
        over = self.world.game_over()
        if over:
            self.goal_title.config(text=f"🎯  Ziel erreicht: {self._goal_years_text().replace('Jahren', 'Jahre')} gespielt")
            self.goal_text.config(text="Hier ist deine Auswertung. Trage dich in die Bestenliste ein, spiele mit "
                                       "„Weiterspielen“ ohne Grenze weiter oder starte ein neues Spiel. "
                                       "Die Auswertung bleibt über die Navigation erreichbar.")
            self.continue_btn.pack(side=tk.LEFT, before=self.continue_btn.master.winfo_children()[1])
            self.goal_banner.pack(fill=tk.X, pady=(0, 10))
        elif eng.goal_reached:
            self.goal_title.config(text=f"★  Ziel ({dialogs.goal_label(eng.goal_cycles)}) erreicht – du spielst weiter")
            self.goal_text.config(text="Die Bestenliste wertet den Stand beim Erreichen des Ziels. Unten siehst "
                                       "du die Bewertung des aktuellen Stands.")
            self.continue_btn.pack_forget()
            self.goal_banner.pack(fill=tk.X, pady=(0, 10))
        elif eng.goal_cycles is None and eng.cycles_played >= 1:
            self.goal_title.config(text="∞  Endlos-Spiel – Zwischenstand")
            self.goal_text.config(text="Ohne Ziel gibt es kein Spielende. Du kannst den aktuellen Stand jederzeit "
                                       "in die Bestenliste eintragen.")
            self.continue_btn.pack_forget()
            self.goal_banner.pack(fill=tk.X, pady=(0, 10))
        else:
            self.goal_banner.pack_forget()
        pending = [i for i, c in enumerate(self.world.countries)
                   if i not in self._lb_done and self._lb_eligible(c.engine)]
        self.lb_btn.state(["!disabled"] if pending else ["disabled"])
        self.lb_btn.config(text="🏆 In Bestenliste eintragen…" if pending else "✔ In Bestenliste eingetragen")
        self._rebuild_end_select()
        if self.multi:
            self.end_rank_panel.grid(row=0, column=2, sticky="nsew", padx=(12, 0))
            self.end_top.columnconfigure(2, weight=2, uniform="end")
            self._fill_ranking(self.end_rank_box, wrap=260, compact=True)
        else:
            self.end_rank_panel.grid_remove()
            self.end_top.columnconfigure(2, weight=0, uniform="")
        if not hist:
            return
        try:
            sc = eng.score()
        except Exception:
            sc = {"total": 0.0, "grade": "–", "parts": {}, "comment": ""}
        score = float(sc.get("total", 0.0))
        color = C["green"] if score >= 70 else C["cyan"] if score >= 55 else C["orange"] if score >= 40 else C["red"]
        self.score_label.config(text=f"{score:.0f} / 100", fg=color)
        grade_txt = f"Note {sc.get('grade', '–')} – {sc.get('comment', '')}"
        if "goal_score" in sc:
            grade_txt += f"\nBeim Erreichen des Ziels: {sc['goal_score']:.0f} / 100"
        self.grade_label.config(text=grade_txt, fg=color)
        self.score_detail.config(text="\n".join(f"{SCORE_PART_NAMES.get(k, k):<14}{p:>5.1f} / {m:.0f}"
                                                for k, (p, m) in sc.get("parts", {}).items()))
        start, end = hist[0], hist[-1]
        self.end_values_title.config(text=f"Werte nach {int(_num(end, 'jahr_end'))} Jahren"
                                          + (f" – {country.name}" if self.multi else ""))
        lines = [f"{'':<18}{'Start':>11}{'Jetzt':>11}{'Δ':>11}"]
        for key, label, fmt, factor, _g in FORECAST_ROWS:
            s, en = _num(start, key) * factor, _num(end, key) * factor
            lines.append(f"{label:<18}{fmt.format(s):>11}{fmt.format(en):>11}{fmt.format(en - s):>11}")
        self.end_values.config(text="\n".join(lines))
        for key, (ch, factor, ref) in self.end_charts.items():
            xs, ys = self._series(key, factor, engine=eng)
            ch.set_data(xs, ys, reference=ref)
        self._set_capital(self.end_capital_chart, engine=eng)


def main():
    root = tk.Tk()
    EquivaraGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
