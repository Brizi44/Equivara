"""Equivara – Tkinter-Oberfläche.

Nutzt ausschließlich die öffentliche API von ``equivara_engine`` und die
Widgets aus ``equivara_widgets`` (siehe CONTRACT, Abschnitt 1 und 2).
"""

import csv
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from equivara_engine import (
    DEFAULT_INPUTS,
    INPUT_KEYS,
    INPUT_LABELS,
    INVEST_KEYS,
    EquivaraEngine,
)
from equivara_widgets import (
    THEME,
    BudgetBar,
    HistoryTable,
    LineChart,
    MultiLineChart,
    StatCard,
    Tooltip,
)

C = THEME
SIDEBAR_BG = "#0a101c"
FIELD_BG = "#0f1729"
DEBOUNCE_MS = 150
FONT = "Segoe UI"


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
}

TOOLTIPS = {
    "food_domestic": "Nahrung, die die Bevölkerung in diesem Zyklus konsumiert.\nZiel: mind. 2 NW pro Kopf und Jahr.",
    "food_export": "Exportierte Nahrung. Bringt Devisen (GE) für Importe, Zinsen und Tilgung.",
    "goods_domestic": "Konsumgüter für die Bevölkerung. Verbraucht zusätzlich Energie (1/5 der Gütermenge).",
    "goods_export": "Exportierte Güter. Bringt Devisen (GE).",
    "goods_investment": "Güter, die als Investitionsbudget auf die sechs Kapitalstöcke verteilt werden.",
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
        return float(d.get(key, default))
    except (TypeError, ValueError):
        return default


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
    """Tkinter-Frontend für die Equivara-Engine."""

    COLORS = C

    def __init__(self, root, engine=None):
        self.root = root
        self.root.title("Equivara  |  System Dynamics Simulation")
        self.root.geometry("1280x800")
        self.root.minsize(1100, 700)
        self.root.configure(bg=C["bg"])

        self.engine = engine or EquivaraEngine()
        self.vars = {}
        self.field_frames = {}
        self.field_msgs = {}
        self.spinboxes = {}
        self.views = {}
        self.current_view = None
        self._after_id = None
        self._suspend_trace = False
        self._preview = None
        self._issues = []
        self._parse_errors = {}
        self._can_apply = False

        self._configure_style()
        self._build_shell()
        self._build_decisions()
        self._build_dashboard()
        self._build_report()
        self._build_end()
        ScrollFrame.install_wheel(self.root)
        self._bind_keys()

        self._fill_inputs(self._initial_inputs())
        self._refresh_all()
        self._show_view("end" if self.engine.game_over else "decisions")

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
        style.configure("Side.TButton", background="#121b2e", foreground=C["text"], borderwidth=0,
                        padding=(10, 6), font=(FONT, 9, "bold"))
        style.map("Side.TButton", background=[("active", "#1c2a45")])
        style.configure("TSpinbox", fieldbackground=FIELD_BG, foreground=C["text"], insertcolor=C["text"],
                        bordercolor=FIELD_BG, lightcolor=FIELD_BG, darkcolor=FIELD_BG,
                        arrowcolor=C["muted"], background=C["panel2"], padding=4)
        style.map("TSpinbox", fieldbackground=[("disabled", "#141d31")], foreground=[("disabled", "#55647d")])
        style.configure("Vertical.TScrollbar", background=C["panel2"], troughcolor=C["bg"],
                        bordercolor=C["bg"], arrowcolor=C["muted"])

    # ------------------------------------------------------------------ shell
    def _build_shell(self):
        self.sidebar = tk.Frame(self.root, bg=SIDEBAR_BG, width=200)
        self.sidebar.pack(side=tk.LEFT, fill=tk.Y)
        self.sidebar.pack_propagate(False)

        brand = tk.Frame(self.sidebar, bg=SIDEBAR_BG)
        brand.pack(fill=tk.X, padx=20, pady=(22, 22))
        tk.Label(brand, text="EQUIVARA", bg=SIDEBAR_BG, fg=C["text"], font=(FONT, 19, "bold")).pack(anchor="w")
        tk.Label(brand, text="SYSTEM DYNAMICS SIMULATION", bg=SIDEBAR_BG, fg=C["blue"],
                 font=(FONT, 9, "bold")).pack(anchor="w", pady=(2, 0))

        self.nav_buttons = {}
        for key, label in [("decisions", "Entscheidungen"), ("dashboard", "Dashboard"),
                           ("report", "Bericht"), ("end", "Spielende")]:
            b = tk.Button(self.sidebar, text=label, anchor="w", relief="flat", bd=0,
                          bg=SIDEBAR_BG, fg=C["muted"], activebackground="#17243d",
                          activeforeground=C["text"], font=(FONT, 10, "bold"),
                          padx=20, pady=10, cursor="hand2", command=lambda k=key: self._show_view(k))
            b.pack(fill=tk.X, padx=8, pady=2)
            self.nav_buttons[key] = b

        tk.Frame(self.sidebar, bg=SIDEBAR_BG).pack(fill=tk.BOTH, expand=True)

        actions = tk.Frame(self.sidebar, bg=SIDEBAR_BG)
        actions.pack(fill=tk.X, padx=14, pady=(0, 10))
        for text, cmd, tip in [
            ("Speichern…", self.save_game, "Spielstand als JSON speichern (Strg+S)"),
            ("Laden…", self.load_game, "Spielstand aus JSON laden (Strg+O)"),
            ("Neues Spiel", self.new_game, "Alle Runden verwerfen und neu beginnen"),
        ]:
            b = ttk.Button(actions, text=text, style="Side.TButton", command=cmd)
            b.pack(fill=tk.X, pady=2)
            Tooltip(b, tip)

        tk.Label(self.sidebar, text="12 ZYKLEN  •  60 JAHRE", bg=SIDEBAR_BG, fg="#52617a",
                 font=(FONT, 8, "bold")).pack(anchor="w", padx=20, pady=(4, 4))
        tk.Label(self.sidebar, text="Enter  auswerten\nStrg+Z  rückgängig\nStrg+S / O  speichern / laden",
                 bg=SIDEBAR_BG, fg="#52617a", font=(FONT, 8), justify="left").pack(anchor="w", padx=20, pady=(0, 16))

        self.main = tk.Frame(self.root, bg=C["bg"])
        self.main.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.header = tk.Frame(self.main, bg=C["bg"], height=70)
        self.header.pack(fill=tk.X, padx=24, pady=(14, 6))
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
        self.cycle_label.pack(anchor="e", pady=(4, 6))
        self.year_label = tk.Label(right, text="", bg=C["bg"], fg=C["muted"], font=(FONT, 9))
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

    VIEW_TITLES = {
        "decisions": ("Entscheidungen", "Konsum, Energie, Handel und Investitionen für den nächsten Zyklus"),
        "dashboard": ("Dashboard", "Aktueller Zustand des Landes und Entwicklung"),
        "report": ("Bericht", "Alle Kennzahlen je Zyklus"),
        "end": ("Spiel beendet", "Endwerte und Bewertung nach 60 Jahren"),
    }

    def _show_view(self, key):
        if key not in self.views:
            return
        if key == "end" and not self.engine.game_over:
            self._status("Das Spielende ist nach Zyklus 12 verfügbar.")
            return
        for f in self.views.values():
            f.pack_forget()
        self.views[key].pack(fill=tk.BOTH, expand=True)
        title, sub = self.VIEW_TITLES[key]
        if self.engine.game_over:
            title = "Spiel beendet" if key in ("end", "decisions") else title
        self.page_title.config(text=title)
        self.page_subtitle.config(text=sub)
        for k, b in self.nav_buttons.items():
            b.config(bg="#17243d" if k == key else SIDEBAR_BG, fg=C["text"] if k == key else C["muted"])
        self.current_view = key
        if key == "dashboard":
            self._refresh_dashboard()
        elif key == "report":
            self._refresh_report()
        elif key == "end":
            self._refresh_end()

    def _status(self, text, color=None):
        self.status_bar.config(text=text, fg=color or C["muted"])

    # --------------------------------------------------------------- helpers
    def _panel(self, parent, title=None, subtitle=None, bg=None):
        bg = bg or C["panel"]
        f = tk.Frame(parent, bg=bg, highlightthickness=1, highlightbackground=C["border"])
        if title:
            tk.Label(f, text=title, bg=bg, fg=C["text"], font=(FONT, 12, "bold")).pack(anchor="w", padx=14, pady=(12, 0))
        if subtitle:
            tk.Label(f, text=subtitle, bg=bg, fg=C["muted"], font=(FONT, 9), justify="left",
                     wraplength=560).pack(anchor="w", padx=14, pady=(2, 6))
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
        tk.Label(grid, text=UNITS.get(key, ""), bg=bg, fg=C["muted"], font=(FONT, 8, "bold"),
                 width=3, anchor="w").grid(row=row, column=2, sticky="w", padx=(6, 4), pady=(5, 0))
        msg = tk.Label(grid, text="", bg=bg, fg=C["red"], font=(FONT, 8), anchor="w", justify="left",
                       wraplength=520)
        msg.grid(row=row + 1, column=0, columnspan=4, sticky="w", padx=(14, 8))
        msg.grid_remove()
        self.field_msgs[key] = msg
        tip = TOOLTIPS.get(key, "")
        Tooltip(lbl, tip)
        Tooltip(sp, tip)
        var.trace_add("write", self._on_var_change)
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
        inner = sf.inner

        legend = tk.Frame(inner, bg=C["panel2"], highlightthickness=1, highlightbackground=C["border"])
        legend.pack(fill=tk.X, pady=(0, 8))
        tk.Label(legend, text="Einheiten:  NW = Nahrungseinheiten   GW = Gütereinheiten   "
                              "EW = Energieeinheiten   GE = Geldeinheiten (Devisen)   •   Schrittweite 10",
                 bg=C["panel2"], fg=C["muted"], font=(FONT, 8, "bold"), wraplength=640,
                 justify="left").pack(anchor="w", padx=12, pady=6)

        self.hints = {}
        for title, subtitle, keys in SECTIONS:
            p = self._panel(inner, title, subtitle)
            p.pack(fill=tk.X, pady=(0, 10))
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
                row += 2
            if title.startswith("4"):
                bar_wrap = tk.Frame(p, bg=C["panel"])
                bar_wrap.pack(fill=tk.X, padx=14, pady=(0, 12))
                self.invest_bar_local = BudgetBar(bar_wrap, "Investitionsbudget", C["purple"], width=400)
                self.invest_bar_local.pack(fill=tk.X)
            if title.startswith("3"):
                self.finance_info = tk.Label(p, text="", bg=C["panel2"], fg=C["text"], font=("Consolas", 9),
                                             justify="left", anchor="w")
                self.finance_info.pack(fill=tk.X, padx=14, pady=(0, 12), ipadx=8, ipady=6)

        # ---- rechte Seite: Live-Panel (fixiert)
        live_sf = ScrollFrame(f, bg=C["bg"], width=318)
        live_sf.grid(row=0, column=1, sticky="nsew")
        live = live_sf.inner

        act = self._panel(live, "Zyklus abschließen")
        act.pack(fill=tk.X, pady=(0, 8))
        self.apply_btn = ttk.Button(act, text="Runde auswerten  ⏎", style="Accent.TButton",
                                    command=self.evaluate_round)
        self.apply_btn.pack(fill=tk.X, padx=14, pady=(8, 4))
        self.apply_reason = tk.Label(act, text="", bg=C["panel"], fg=C["red"], font=(FONT, 8),
                                     wraplength=290, justify="left", anchor="w")
        self.apply_reason.pack(fill=tk.X, padx=14)
        row = tk.Frame(act, bg=C["panel"])
        row.pack(fill=tk.X, padx=14, pady=(6, 12))
        self.suggest_btn = ttk.Button(row, text="Vorschlag übernehmen", command=self.apply_suggestion)
        self.suggest_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4))
        Tooltip(self.suggest_btn, "Skaliert die aktuellen Eingaben so, dass alle Budgets passen.")
        self.undo_btn = ttk.Button(row, text="Rückgängig", command=self.undo_round)
        self.undo_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(4, 0))
        Tooltip(self.undo_btn, "Letzte Runde rückgängig machen (Strg+Z)")

        bud = self._panel(live, "Budgets")
        bud.pack(fill=tk.X, pady=(0, 8))
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

        cards = tk.Frame(inner, bg=C["bg"])
        cards.pack(fill=tk.X, pady=(0, 10))
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
        lower.columnconfigure(0, weight=3)
        lower.columnconfigure(1, weight=2)
        self.capital_chart = MultiLineChart(lower, "Kapitalstöcke", height=240)
        self.capital_chart.grid(row=0, column=0, sticky="nsew", padx=(4, 4), pady=4)
        wp = self._panel(lower, "Systemwarnungen", "Aktueller Zustand laut Modell")
        wp.grid(row=0, column=1, sticky="nsew", padx=(4, 4), pady=4)
        self.dash_warn_box = tk.Frame(wp, bg=C["panel"])
        self.dash_warn_box.pack(fill=tk.BOTH, expand=True, padx=14, pady=(0, 12))
        btn = ttk.Button(wp, text="Zu den Entscheidungen →", style="Accent.TButton",
                         command=lambda: self._show_view("decisions"))
        btn.pack(fill=tk.X, padx=14, pady=(0, 14))
        self.dash_go_btn = btn

    # ---------------------------------------------------------------- report
    def _build_report(self):
        f = self._new_view("report")
        top = tk.Frame(f, bg=C["bg"])
        top.pack(fill=tk.X, pady=(0, 8))
        tk.Label(top, text="Spalten = Zyklen, Farbe = Veränderung zum Vorzyklus", bg=C["bg"], fg=C["muted"],
                 font=(FONT, 9)).pack(side=tk.LEFT)
        ttk.Button(top, text="Bericht als CSV exportieren", command=self.export_csv).pack(side=tk.RIGHT)
        self.history_table = HistoryTable(f, REPORT_ROWS)
        self.history_table.pack(fill=tk.BOTH, expand=True)

    # -------------------------------------------------------------- game end
    def _build_end(self):
        f = self._new_view("end")
        sf = ScrollFrame(f)
        sf.pack(fill=tk.BOTH, expand=True)
        inner = sf.inner

        top = tk.Frame(inner, bg=C["bg"])
        top.pack(fill=tk.X, pady=(0, 10))
        top.columnconfigure(0, weight=1)
        top.columnconfigure(1, weight=2)

        sp = self._panel(top, "Bewertung")
        sp.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        self.score_label = tk.Label(sp, text="—", bg=C["panel"], fg=C["blue"], font=(FONT, 40, "bold"))
        self.score_label.pack(anchor="w", padx=14)
        self.grade_label = tk.Label(sp, text="", bg=C["panel"], fg=C["text"], font=(FONT, 13, "bold"))
        self.grade_label.pack(anchor="w", padx=14)
        self.score_detail = tk.Label(sp, text="", bg=C["panel"], fg=C["muted"], font=("Consolas", 9),
                                     justify="left", anchor="w")
        self.score_detail.pack(anchor="w", padx=14, pady=(6, 14))

        ep = self._panel(top, "Endwerte nach 60 Jahren", "Vergleich mit dem Startzustand")
        ep.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        self.end_values = tk.Label(ep, text="", bg=C["panel"], fg=C["text"], font=("Consolas", 10),
                                   justify="left", anchor="w")
        self.end_values.pack(anchor="w", padx=14, pady=(0, 10))
        bar = tk.Frame(ep, bg=C["panel"])
        bar.pack(fill=tk.X, padx=14, pady=(0, 14))
        ttk.Button(bar, text="Neues Spiel", style="Accent.TButton", command=self.new_game).pack(side=tk.LEFT)
        ttk.Button(bar, text="Letzte Runde rückgängig", command=self.undo_round).pack(side=tk.LEFT, padx=8)
        ttk.Button(bar, text="Bericht als CSV exportieren", command=self.export_csv).pack(side=tk.LEFT)

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

    def _key_evaluate(self, event):
        if isinstance(event.widget, (tk.Button, ttk.Button)):
            return None  # Buttons behalten ihr eigenes Verhalten
        if self.current_view == "decisions":
            self.evaluate_round()
        return "break"

    # ---------------------------------------------------------------- inputs
    def _initial_inputs(self):
        e = self.engine
        if e.last_inputs and not e.game_over:
            return self._safe_suggest(e.last_inputs)
        if e.last_inputs:
            return dict(e.last_inputs)
        return self._safe_suggest(dict(DEFAULT_INPUTS))

    def _safe_suggest(self, base=None):
        try:
            return self.engine.suggest_inputs(base)
        except Exception:  # Engine-Fehler dürfen die GUI nicht sprengen
            return dict(base) if base else dict(DEFAULT_INPUTS)

    def _fill_inputs(self, values):
        """Füllt alle StringVars ohne für jedes Feld ein Live-Update auszulösen."""
        self._suspend_trace = True
        try:
            for k in INPUT_KEYS:
                if k in self.vars:
                    self.vars[k].set(_fmt_input((values or {}).get(k, 0)))
        finally:
            self._suspend_trace = False
        self._schedule_live(0)

    def read_inputs(self):
        """Liest alle Felder. Liefert (inputs, parse_errors); ungültige Felder werden als 0 übergeben."""
        inputs, errors = {}, {}
        for k in INPUT_KEYS:
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
            self._refresh_dashboard()

    def _mark_fields(self, issues, parse_errors):
        per_field = {}
        for k, msg in parse_errors.items():
            if k in self.vars:
                per_field.setdefault(k, []).append(("error", msg))
        for i in issues:
            if i.field in self.vars and i.field not in parse_errors:
                per_field.setdefault(i.field, []).append((i.severity, i.message))
        for k, wrap in self.field_frames.items():
            entries = per_field.get(k)
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
        pop = _num(e.history[-1] if e.history else {}, "population")
        if pop > 0:
            yrs = getattr(e, "CYCLE_YEARS", 5)
            h["food_domestic"].config(
                text=f"≈ {inputs.get('food_domestic', 0) / (pop * yrs):,.2f} NW/Kopf/Jahr (Ziel ≥ 2,0)")
        h["energy_carryover"].config(text="Reserve für den nächsten Zyklus")
        h["new_loans"].config(text=f"Kreditlimit: {_num(req, 'max_new_loan'):,.0f} GE")
        h["repayments"].config(text=f"Schulden: {_num(req, 'debt'):,.0f} GE")
        h["foreign_aid"].config(text=f"Reserve aus Vorzyklus: {_num(req, 'cash_reserve'):,.0f} GE")
        h["import_food_money"].config(text=f"Importpreis-Faktor: {_num(req, 'import_mult'):,.3f}")
        h["goods_investment"].config(text="Budget für die sechs Kapitalstöcke unten")
        h["inv_energy_eff"].config(
            text=f"max. {inputs.get('inv_food', 0) + inputs.get('inv_goods', 0):,.0f} GW (Nahrung + Güter)")
        try:
            money = e.budgets(inputs).get("money", {})
        except Exception:
            money = {}
        imf = _num(req, "imf_pending")
        self.finance_info.config(text=(
            f"Zinsen fällig     {_num(req, 'interest_due'):>10,.0f} GE   ({_num(req, 'annual_interest'):.2f} %/Jahr)\n"
            f"Kreditlimit       {_num(req, 'max_new_loan'):>10,.0f} GE   (Ø Exporte {_num(req, 'avg_exports'):,.0f})\n"
            f"Devisenreserve    {_num(req, 'cash_reserve'):>10,.0f} GE\n"
            f"Importbudget      {_num(money, 'available'):>10,.0f} GE   (verplant {_num(money, 'used'):,.0f})"
            + (f"\nIMF-Rückzahlung   {imf:>10,.0f}  (fällig)" if imf > 0 else "")
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

    def _fill_list(self, box, items, empty_text):
        for w in box.winfo_children():
            w.destroy()
        if not items:
            tk.Label(box, text=empty_text, bg=C["panel"], fg=C["green"], font=(FONT, 9), anchor="w",
                     justify="left", wraplength=290).pack(fill=tk.X, pady=2)
            return
        for color, text in items:
            tk.Label(box, text=text, bg=C["panel"], fg=color, font=(FONT, 9), anchor="w", justify="left",
                     wraplength=290).pack(fill=tk.X, pady=2)

    def _update_live_warnings(self, issues, parse_errors):
        items = []
        if self.engine.game_over:
            items.append((C["muted"], "Das Spiel ist beendet – keine weiteren Eingaben möglich."))
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
        if e.game_over:
            reason = "Spiel beendet – alle 12 Zyklen sind gespielt."
        elif parse_errors:
            reason = "Bitte zuerst ungültige Zahlen korrigieren (rot markiert)."
        elif errors:
            n = len(errors)
            reason = f"{n} Fehler verhindern die Auswertung: " + errors[0].message
        self._can_apply = not reason
        self.apply_btn.state(["!disabled"] if self._can_apply else ["disabled"])
        self.apply_reason.config(text=reason)
        self.undo_btn.state(["!disabled"] if self._can_undo() else ["disabled"])
        self.suggest_btn.state(["disabled"] if e.game_over else ["!disabled"])

    def _can_undo(self):
        try:
            return bool(self.engine.can_undo())
        except Exception:
            return False

    # ---------------------------------------------------------------- actions
    def evaluate_round(self):
        """Wertet den Zyklus mit den aktuellen Eingaben aus (Button / Enter)."""
        if self._after_id is not None:
            self.root.after_cancel(self._after_id)
        self._live_update()
        if not self._can_apply:
            self._status("Runde nicht ausgewertet: " + self.apply_reason.cget("text"), C["red"])
            return None
        inputs, _ = self.read_inputs()
        try:
            result = self.engine.apply(inputs)
        except ValueError as exc:
            self._status(f"Runde nicht ausgewertet: {exc}", C["red"])
            self._live_update()
            return None
        self._status(f"Zyklus {result.get('runde', '?')} ausgewertet (Jahr {result.get('jahr_start', '?')}–"
                     f"{result.get('jahr_end', '?')}).", C["green"])
        self._after_state_change(keep_inputs=True)
        if self.engine.game_over:
            self._show_view("end")
        return result

    def apply_suggestion(self):
        if self.engine.game_over:
            return
        inputs, _ = self.read_inputs()
        self._fill_inputs(self._safe_suggest(inputs))
        self._status("Vorschlag übernommen – alle Budgets passen.", C["blue"])

    def undo_round(self):
        if not self._can_undo():
            self._status("Nichts rückgängig zu machen.")
            return
        undone = dict(self.engine.last_inputs) if self.engine.last_inputs else None
        if not self.engine.undo():
            self._status("Rückgängig nicht möglich.", C["red"])
            return
        self._after_state_change(keep_inputs=False, values=undone)
        self._status("Letzte Runde rückgängig gemacht – Eingaben dieser Runde wiederhergestellt.", C["blue"])
        if self.current_view == "end":
            self._show_view("decisions")

    def new_game(self):
        if len(self.engine.history) > 1 and not messagebox.askyesno(
                "Neues Spiel", "Alle bisherigen Runden werden verworfen. Fortfahren?", parent=self.root):
            return
        self.engine.reset()
        self._after_state_change(keep_inputs=False)
        self._show_view("decisions")
        self._status("Neues Spiel gestartet.", C["blue"])

    def save_game(self):
        path = filedialog.asksaveasfilename(parent=self.root, title="Spielstand speichern",
                                            defaultextension=".json",
                                            filetypes=[("Equivara-Spielstand", "*.json"), ("Alle Dateien", "*.*")])
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(self.engine.to_json())
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
                engine = EquivaraEngine.from_json(fh.read())
        except Exception as exc:  # defekte Datei, falsches Format …
            messagebox.showerror("Laden fehlgeschlagen", f"Die Datei konnte nicht geladen werden:\n{exc}",
                                 parent=self.root)
            return
        self.engine = engine
        self._after_state_change(keep_inputs=False)
        self._show_view("end" if engine.game_over else "decisions")
        self._status(f"Geladen: {path}", C["green"])

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
        with open(path, "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.writer(fh, delimiter=";")
            w.writerow([labels.get(k, k) for k in keys])
            for row in hist:
                w.writerow([row.get(k, "") for k in keys])

    def _after_state_change(self, keep_inputs, values=None):
        """Nach apply/undo/reset/load: Eingaben (ggf.) neu füllen und alle Ansichten aktualisieren."""
        e = self.engine
        if not keep_inputs:
            if values:
                self._fill_inputs(values)
            elif e.last_inputs:
                self._fill_inputs(dict(e.last_inputs) if e.game_over else self._safe_suggest(e.last_inputs))
            else:
                self._fill_inputs(self._safe_suggest(dict(DEFAULT_INPUTS)))
        self._refresh_all()

    # --------------------------------------------------------------- refresh
    def _refresh_all(self):
        e = self.engine
        over = e.game_over
        cycles = getattr(e, "TOTAL_CYCLES", 12)
        yrs = getattr(e, "CYCLE_YEARS", 5)
        if over:
            self.cycle_label.config(text="SPIEL BEENDET", fg=C["orange"])
            self.year_label.config(text=f"Jahr 0–{cycles * yrs} abgeschlossen")
        else:
            cyc = min(e.runde, cycles)
            self.cycle_label.config(text=f"ZYKLUS {cyc} / {cycles}", fg=C["blue"])
            self.year_label.config(text=f"Jahr {(cyc - 1) * yrs}–{cyc * yrs}")
        for sp in self.spinboxes.values():
            sp.state(["disabled"] if over else ["!disabled"])
        self.nav_buttons["end"].config(state=tk.NORMAL if over else tk.DISABLED)
        self.dash_go_btn.config(text="Zum Spielende →" if over else "Zu den Entscheidungen →",
                                command=lambda: self._show_view("end" if self.engine.game_over else "decisions"))
        if self.current_view in self.VIEW_TITLES:
            title, _sub = self.VIEW_TITLES[self.current_view]
            if over and self.current_view in ("end", "decisions"):
                title = "Spiel beendet"
            self.page_title.config(text=title)
        self._live_update()
        if self.current_view != "dashboard":
            self._refresh_dashboard()
        self._refresh_report()
        if over:
            self._refresh_end()

    def _series(self, key, factor=1.0):
        hist = self.engine.history
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

    def _refresh_dashboard(self):
        hist = self.engine.history
        cur = hist[-1] if hist else {}
        prev = hist[-2] if len(hist) >= 2 else None
        pv = self._preview
        for key, (card, factor, good) in self.stat_cards.items():
            value = _num(cur, key) * factor
            previous = _num(prev, key) * factor if prev and key in prev else None
            preview = _num(pv, key) * factor if pv and key in pv else None
            card.set(value, previous=previous, preview=preview, good_when_up=good)
        for key, (ch, factor, ref) in self.charts.items():
            xs, ys = self._series(key, factor)
            ch.set_data(xs, ys, preview=self._preview_point(key, factor), reference=ref)
        self._set_capital(self.capital_chart)
        try:
            warns = list(self.engine.warnings())
        except Exception:
            warns = []
        self._fill_list(self.dash_warn_box, [(C["orange"], "⚠ " + w) for w in warns],
                        "✔ Keine Systemwarnungen.")

    def _set_capital(self, chart):
        xs = [float(r.get("jahr_end", 0)) for r in self.engine.history]
        series = [(label, C[color], [_num(r, key) for r in self.engine.history])
                  for key, label, color in CAPITAL_SERIES]
        chart.set_series(xs, series)

    def _refresh_report(self):
        self.history_table.set_history(self.engine.history)

    # --------------------------------------------------------------- scoring
    def compute_score(self):
        """Einfacher Score 0–100 aus Wohlstand (40), Umwelt (30) und Schulden (30)."""
        hist = self.engine.history
        if not hist:
            return 0.0, {}
        start, end = hist[0], hist[-1]
        food = max(0.0, min(1.0, _num(end, "food_pc") / 2.0)) * 20
        goods = max(0.0, min(1.0, _num(end, "goods_pc") / max(1e-9, _num(start, "goods_pc", 2.0) * 1.5))) * 20
        env = max(0.0, min(1.0, _num(end, "environment") / 0.8)) * 30
        start_debt = max(1.0, _num(start, "debt", 1000.0))
        debt = max(0.0, min(1.0, 1.0 - (_num(end, "debt") - start_debt) / (2 * start_debt))) * 30
        parts = {"Nahrung/Kopf": (food, 20), "Güter/Kopf": (goods, 20), "Umwelt": (env, 30), "Schulden": (debt, 30)}
        return food + goods + env + debt, parts

    def _refresh_end(self):
        hist = self.engine.history
        if not hist:
            return
        score, parts = self.compute_score()
        grade, color = ("Hervorragend", C["green"]) if score >= 80 else \
            ("Gut", C["cyan"]) if score >= 60 else \
            ("Durchwachsen", C["orange"]) if score >= 40 else ("Kritisch", C["red"])
        self.score_label.config(text=f"{score:.0f} / 100", fg=color)
        self.grade_label.config(text=grade, fg=color)
        self.score_detail.config(text="\n".join(f"{k:<14}{v:>5.1f} / {m}" for k, (v, m) in parts.items()))
        start, end = hist[0], hist[-1]
        lines = [f"{'':<18}{'Start':>11}{'Ende':>11}{'Δ':>11}"]
        for key, label, fmt, factor, _g in FORECAST_ROWS:
            s, en = _num(start, key) * factor, _num(end, key) * factor
            lines.append(f"{label:<18}{fmt.format(s):>11}{fmt.format(en):>11}{fmt.format(en - s):>11}")
        self.end_values.config(text="\n".join(lines))
        for key, (ch, factor, ref) in self.end_charts.items():
            xs, ys = self._series(key, factor)
            ch.set_data(xs, ys, reference=ref)
        self._set_capital(self.end_capital_chart)


def main():
    root = tk.Tk()
    EquivaraGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
