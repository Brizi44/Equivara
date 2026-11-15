"""Equivara – Dialoge und Hilfsansichten der Oberfläche.

Enthält:
- ``GOAL_OPTIONS`` und Helfer zum Lesen der gespeicherten Einstellungen,
- ``NewGameDialog`` / ``ask_new_game``: Neues Spiel (Modus, Länder, Rollen,
  Szenario, Ereignisse, Seed, Ziel, Ministerien),
- ``SettingsView``: Einstellungen (Ministerien, Standard-Ziel, Ereignisse,
  Tutorial erneut zeigen),
- ``NamesDialog`` / ``ask_names``: Namen für die Bestenliste,
- ``HandoverOverlay``: Vollbild-Zwischenbildschirm beim Hot-Seat-Wechsel.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from equivara_engine import MINISTRIES, SCENARIOS
from equivara_widgets import THEME, blend

try:
    from equivara_world import MODES, ROLES
except Exception:  # pragma: no cover - Welt-Modul fehlt
    MODES = {"solo": {"name": "Solo", "description": ""}}
    ROLES = {}

C = THEME
FONT = "Segoe UI"

# (Anzeigetext, Zyklen) – None = endlos
GOAL_OPTIONS = [
    ("20 Jahre", 4), ("40 Jahre", 8), ("60 Jahre", 12), ("80 Jahre", 16),
    ("100 Jahre", 20), ("150 Jahre", 30), ("200 Jahre", 40), ("Endlos", None),
]
DEFAULT_GOAL = 12
MAX_COUNTRIES = 4


def goal_label(cycles) -> str:
    for text, c in GOAL_OPTIONS:
        if c == cycles:
            return text
    return "Endlos" if cycles is None else f"{int(cycles) * 5} Jahre"


def goal_from_label(text: str):
    for t, c in GOAL_OPTIONS:
        if t == text:
            return c
    return DEFAULT_GOAL


def settings_ministries(settings: dict) -> dict:
    raw = (settings or {}).get("ministries")
    raw = raw if isinstance(raw, dict) else {}
    return {k: bool(raw.get(k, False)) for k in MINISTRIES}


def settings_goal(settings: dict):
    s = settings or {}
    if "goal_cycles" not in s:
        return DEFAULT_GOAL
    g = s.get("goal_cycles")
    if g is None:
        return None
    try:
        g = int(g)
    except (TypeError, ValueError):
        return DEFAULT_GOAL
    return g if g >= 1 else DEFAULT_GOAL


def settings_events(settings: dict) -> bool:
    return bool((settings or {}).get("events_default", False))


def settings_scenario(settings: dict) -> str:
    sc = (settings or {}).get("scenario_default", "standard")
    return sc if sc in SCENARIOS else "standard"


# ---------------------------------------------------------------------------
# kleine Bausteine
# ---------------------------------------------------------------------------
def _label(parent, text, bg=None, fg=None, size=9, bold=False, **kw):
    return tk.Label(parent, text=text, bg=bg or C["panel"], fg=fg or C["text"],
                    font=(FONT, size, "bold" if bold else "normal"), anchor="w", justify="left", **kw)


def _section(parent, title, bg=None):
    bg = bg or C["panel"]
    f = tk.Frame(parent, bg=bg, highlightthickness=1, highlightbackground=C["border"])
    tk.Label(f, text=title, bg=bg, fg=C["text"], font=(FONT, 11, "bold"), anchor="w").pack(
        fill="x", padx=12, pady=(10, 4))
    return f


def _check(parent, text, var, command=None, bg=None):
    bg = bg or C["panel"]
    return tk.Checkbutton(parent, text=text, variable=var, command=command, bg=bg, fg=C["text"],
                          selectcolor=C["panel2"], activebackground=bg, activeforeground=C["white"],
                          font=(FONT, 10), anchor="w", highlightthickness=0, bd=0, cursor="hand2")


def _radio(parent, text, var, value, command=None, bg=None):
    bg = bg or C["panel"]
    return tk.Radiobutton(parent, text=text, variable=var, value=value, command=command, bg=bg,
                          fg=C["text"], selectcolor=C["panel2"], activebackground=bg,
                          activeforeground=C["white"], font=(FONT, 10), anchor="w",
                          highlightthickness=0, bd=0, cursor="hand2")


def _entry(parent, var, width=18, size=10):
    return tk.Entry(parent, textvariable=var, width=width, bg="#0f1729", fg=C["text"],
                    insertbackground=C["text"], relief="flat", highlightthickness=1,
                    highlightbackground=C["border"], highlightcolor=C["blue"], font=(FONT, size),
                    disabledbackground="#141d31", disabledforeground="#55647d")


def configure_styles(widget) -> None:
    """Dunkle ttk-Stile für Combobox (wird von GUI und Dialogen genutzt)."""
    st = ttk.Style(widget)
    try:
        st.configure("Eq.TCombobox", fieldbackground=C["panel2"], background=C["panel2"],
                     foreground=C["text"], arrowcolor=C["muted"], bordercolor=C["border"],
                     lightcolor=C["panel2"], darkcolor=C["panel2"], selectbackground=C["panel2"],
                     selectforeground=C["text"], padding=4)
        st.map("Eq.TCombobox", fieldbackground=[("readonly", C["panel2"])],
               foreground=[("readonly", C["text"])],
               selectbackground=[("readonly", C["panel2"])],
               selectforeground=[("readonly", C["text"])])
        widget.option_add("*TCombobox*Listbox.background", C["panel2"])
        widget.option_add("*TCombobox*Listbox.foreground", C["text"])
        widget.option_add("*TCombobox*Listbox.selectBackground", C["blue"])
        widget.option_add("*TCombobox*Listbox.selectForeground", C["white"])
    except tk.TclError:
        pass


def _center_on(win, parent):
    try:
        win.update_idletasks()
        pw, ph = parent.winfo_width(), parent.winfo_height()
        px, py = parent.winfo_rootx(), parent.winfo_rooty()
        w, h = win.winfo_reqwidth(), win.winfo_reqheight()
        sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
        x = max(0, min(px + (pw - w) // 2, sw - w))
        y = max(0, min(py + (ph - h) // 2, sh - h - 40))
        win.geometry(f"+{x}+{y}")
    except tk.TclError:
        pass


# ---------------------------------------------------------------------------
# Neues Spiel
# ---------------------------------------------------------------------------
class NewGameDialog(tk.Toplevel):
    """Dialog „Neues Spiel“. Ergebnis in ``self.result`` (dict) oder None (abgebrochen).

    result = {"mode", "names": [..], "roles": [{rolle: person}, ..], "scenario", "events",
              "seed": int | None, "ministries": {..}, "goal_cycles": int | None}
    """

    def __init__(self, parent, settings: dict | None = None, modal: bool = True):
        super().__init__(parent, bg=C["bg"])
        self.withdraw()
        self.title("Neues Spiel – Equivara")
        self.resizable(False, False)
        self.result = None
        settings = settings or {}
        configure_styles(self)

        self.mode = tk.StringVar(value="solo")
        self.count = tk.IntVar(value=1)
        self.names = [tk.StringVar(value=f"Land {i + 1}") for i in range(MAX_COUNTRIES)]
        self.scenario = tk.StringVar(value=SCENARIOS[settings_scenario(settings)]["name"])
        self.events = tk.BooleanVar(value=settings_events(settings))
        self.seed = tk.StringVar(value="")
        self.goal = tk.StringVar(value=goal_label(settings_goal(settings)))
        mins = settings_ministries(settings)
        self.ministries = {k: tk.BooleanVar(value=mins[k]) for k in MINISTRIES}
        self.use_roles = tk.BooleanVar(value=False)
        self.role_vars: dict[tuple[str, int], tk.StringVar] = {}

        outer = tk.Frame(self, bg=C["bg"])
        outer.pack(fill="both", expand=True, padx=16, pady=14)
        tk.Label(outer, text="Neues Spiel", bg=C["bg"], fg=C["text"], font=(FONT, 17, "bold"),
                 anchor="w").pack(fill="x")
        tk.Label(outer, text="Wähle Spielmodus, Länder und Startbedingungen.", bg=C["bg"], fg=C["muted"],
                 font=(FONT, 10), anchor="w").pack(fill="x", pady=(0, 10))

        cols = tk.Frame(outer, bg=C["bg"])
        cols.pack(fill="both", expand=True)
        left = tk.Frame(cols, bg=C["bg"])
        left.pack(side="left", fill="both", expand=True, padx=(0, 8))
        right = tk.Frame(cols, bg=C["bg"])
        right.pack(side="left", fill="both", expand=True, padx=(8, 0))

        # -- Modus
        sec = _section(left, "Spielmodus")
        sec.pack(fill="x", pady=(0, 8))
        mrow = tk.Frame(sec, bg=C["panel"])
        mrow.pack(fill="x", padx=12)
        for key, m in MODES.items():
            _radio(mrow, m["name"], self.mode, key, command=self._on_mode).pack(side="left", padx=(0, 12))
        self.mode_desc = _label(sec, "", fg=C["muted"], size=8, wraplength=360)
        self.mode_desc.pack(fill="x", padx=12, pady=(4, 10))

        # -- Länder
        sec = _section(left, "Länder")
        sec.pack(fill="x", pady=(0, 8))
        row = tk.Frame(sec, bg=C["panel"])
        row.pack(fill="x", padx=12)
        _label(row, "Anzahl Länder").pack(side="left")
        self.count_spin = ttk.Spinbox(row, from_=1, to=MAX_COUNTRIES, textvariable=self.count, width=4,
                                      command=self._on_count, state="readonly")
        self.count_spin.pack(side="left", padx=8)
        self.count_hint = _label(row, "", fg=C["muted"], size=8)
        self.count_hint.pack(side="left")
        self.name_rows = []
        names_box = tk.Frame(sec, bg=C["panel"])
        names_box.pack(fill="x", padx=12, pady=(6, 10))
        for i in range(MAX_COUNTRIES):
            r = tk.Frame(names_box, bg=C["panel"])
            _label(r, f"Land {i + 1}", width=8).pack(side="left")
            _entry(r, self.names[i], width=26).pack(side="left", padx=(4, 0))
            self.name_rows.append(r)

        # -- Ziel
        sec = _section(left, "Ziel")
        sec.pack(fill="x", pady=(0, 8))
        row = tk.Frame(sec, bg=C["panel"])
        row.pack(fill="x", padx=12, pady=(0, 10))
        _label(row, "Spieldauer").pack(side="left")
        ttk.Combobox(row, textvariable=self.goal, values=[t for t, _ in GOAL_OPTIONS], state="readonly",
                     width=12, style="Eq.TCombobox").pack(side="left", padx=8)
        _label(row, "Nach dem Ziel kann weitergespielt werden.", fg=C["muted"], size=8).pack(side="left")

        # -- Szenario
        sec = _section(right, "Szenario")
        sec.pack(fill="x", pady=(0, 8))
        sc_names = [s["name"] for s in SCENARIOS.values()]
        cb = ttk.Combobox(sec, textvariable=self.scenario, values=sc_names, state="readonly", width=28,
                          style="Eq.TCombobox")
        cb.pack(anchor="w", padx=12)
        cb.bind("<<ComboboxSelected>>", lambda e: self._on_scenario())
        self.sc_desc = _label(sec, "", fg=C["muted"], wraplength=360)
        self.sc_desc.pack(fill="x", padx=12, pady=(4, 6))
        row = tk.Frame(sec, bg=C["panel"])
        row.pack(fill="x", padx=12, pady=(0, 10))
        _check(row, "Zufallsereignisse", self.events).pack(side="left")
        _label(row, "   Seed (optional)").pack(side="left")
        _entry(row, self.seed, width=12).pack(side="left", padx=(6, 0))

        # -- Ministerien
        sec = _section(left, "Ministerien")
        sec.pack(fill="x", pady=(0, 8))
        _label(sec, "Zusätzliche Staatsaufgaben mit eigenem Investitionsfeld. Alle aus = klassisches Modell.",
               fg=C["muted"], size=8, wraplength=360).pack(fill="x", padx=12)
        grid = tk.Frame(sec, bg=C["panel"])
        grid.pack(fill="x", padx=12, pady=(4, 10))
        for i, (key, m) in enumerate(MINISTRIES.items()):
            _check(grid, m["name"], self.ministries[key], command=self._rebuild_roles).grid(
                row=i // 2, column=i % 2, sticky="w", padx=(0, 18))

        # -- Rollen
        self.roles_sec = _section(right, "Rollen (optional)")
        self.roles_sec.pack(fill="x", pady=(0, 8))
        self.roles_check = _check(self.roles_sec, "Personen den Rollen zuordnen",
                                  self.use_roles, command=self._rebuild_roles)
        self.roles_check.pack(fill="x", padx=12)
        self.roles_info = _label(self.roles_sec, "", fg=C["muted"], size=8, wraplength=380)
        self.roles_info.pack(fill="x", padx=12, pady=(2, 4))
        self.roles_grid = tk.Frame(self.roles_sec, bg=C["panel"])
        self.roles_grid.pack(fill="x", padx=12, pady=(0, 10))

        # -- Buttons
        self.error = tk.Label(outer, text="", bg=C["bg"], fg=C["red"], font=(FONT, 9), anchor="w")
        self.error.pack(fill="x")
        btns = tk.Frame(outer, bg=C["bg"])
        btns.pack(fill="x", pady=(6, 0))
        ttk.Button(btns, text="Spiel starten", style="Accent.TButton", command=self.ok).pack(side="right")
        ttk.Button(btns, text="Abbrechen", command=self.cancel).pack(side="right", padx=8)

        self.bind("<Escape>", lambda e: self.cancel())
        self.bind("<Return>", lambda e: self.ok())
        self.protocol("WM_DELETE_WINDOW", self.cancel)
        self._on_mode()
        self._on_scenario()
        self.deiconify()
        _center_on(self, parent)
        if modal:
            try:
                self.transient(parent)
                self.grab_set()
            except tk.TclError:
                pass

    # -- Reaktionen -----------------------------------------------------
    def _scenario_key(self):
        name = self.scenario.get()
        for k, s in SCENARIOS.items():
            if s["name"] == name:
                return k
        return "standard"

    def _on_scenario(self):
        self.sc_desc.config(text=SCENARIOS[self._scenario_key()]["description"])

    def _on_mode(self):
        mode = self.mode.get()
        self.mode_desc.config(text=MODES.get(mode, {}).get("description", ""))
        if mode in ("solo", "rollen"):
            self.count.set(1)
            self.count_spin.state(["disabled"])
            self.count_hint.config(text="(dieser Modus hat genau ein Land)")
        else:
            if self.count.get() < 2:
                self.count.set(2)
            self.count_spin.state(["!disabled", "readonly"])
            self.count_hint.config(text="(Hot-Seat: Länder spielen nacheinander)")
        if mode == "rollen":
            self.use_roles.set(True)
        self._on_count()

    def _on_count(self):
        try:
            n = max(1, min(MAX_COUNTRIES, int(self.count.get())))
        except (tk.TclError, ValueError):
            n = 1
        for i, r in enumerate(self.name_rows):
            if i < n:
                r.pack(fill="x", pady=2)
            else:
                r.pack_forget()
        self._rebuild_roles()

    def _available_roles(self):
        out = []
        for key, role in ROLES.items():
            req = role.get("requires_ministry")
            if req is None or self.ministries.get(req, tk.BooleanVar(value=False)).get():
                out.append(key)
        return out

    def _rebuild_roles(self):
        for w in self.roles_grid.winfo_children():
            w.destroy()
        mode = self.mode.get()
        if mode == "rollen":
            self.roles_check.config(state="disabled")
        else:
            self.roles_check.config(state="normal")
        if not self.use_roles.get():
            self.roles_info.config(text="Aus: eine Person steuert jeweils alle Felder eines Landes.")
            return
        self.roles_info.config(text="Je Rolle eine Person (Hot-Seat). Leere Rollen übernimmt das Präsidium; "
                                    "ohne Namen fragt der Modus „Rollen“ alle Rollen ab.")
        n = max(1, int(self.count.get() or 1))
        roles = self._available_roles()
        _label(self.roles_grid, "Rolle", fg=C["muted"], size=8, bold=True).grid(row=0, column=0, sticky="w")
        for j in range(n):
            nm = self.names[j].get().strip() or f"Land {j + 1}"
            _label(self.roles_grid, nm, fg=C["muted"], size=8, bold=True).grid(row=0, column=1 + j, sticky="w",
                                                                              padx=4)
        per_row = 1
        for i, rk in enumerate(roles):
            r, block = divmod(i, per_row)
            base_col = block * (n + 1)
            _label(self.roles_grid, ROLES[rk]["name"], size=8, width=16).grid(row=1 + r, column=base_col,
                                                                              sticky="w", pady=0)
            for j in range(n):
                key = (rk, j)
                if key not in self.role_vars:
                    self.role_vars[key] = tk.StringVar(value="")
                _entry(self.roles_grid, self.role_vars[key], width=max(8, 22 - 4 * n), size=9).grid(
                    row=1 + r, column=base_col + 1 + j, sticky="w", padx=3, pady=1)

    # -- Ergebnis -------------------------------------------------------
    def values(self) -> dict | None:
        """Liest und prüft die Eingaben. Bei Fehlern: Meldung + None."""
        mode = self.mode.get()
        try:
            n = int(self.count.get())
        except (tk.TclError, ValueError):
            n = 1
        n = 1 if mode in ("solo", "rollen") else max(1, min(MAX_COUNTRIES, n))
        names = [(self.names[i].get().strip() or f"Land {i + 1}") for i in range(n)]
        if len(set(n_.lower() for n_ in names)) != len(names):
            self.error.config(text="Bitte jedem Land einen eigenen Namen geben.")
            return None
        seed_txt = self.seed.get().strip()
        seed = None
        if seed_txt:
            try:
                seed = int(seed_txt)
            except ValueError:
                self.error.config(text="Der Seed muss eine ganze Zahl sein (oder leer bleiben).")
                return None
        roles = []
        avail = self._available_roles()
        for j in range(n):
            d = {}
            if self.use_roles.get():
                for rk in avail:
                    v = self.role_vars.get((rk, j))
                    if v is not None and v.get().strip():
                        d[rk] = v.get().strip()
            roles.append(d)
        self.error.config(text="")
        return {
            "mode": mode, "names": names, "roles": roles,
            "scenario": self._scenario_key(), "events": bool(self.events.get()), "seed": seed,
            "ministries": {k: bool(v.get()) for k, v in self.ministries.items()},
            "goal_cycles": goal_from_label(self.goal.get()),
        }

    def ok(self):
        vals = self.values()
        if vals is None:
            return
        self.result = vals
        self._close()

    def cancel(self):
        self.result = None
        self._close()

    def _close(self):
        try:
            self.grab_release()
        except tk.TclError:
            pass
        self.destroy()


def ask_new_game(parent, settings: dict | None = None) -> dict | None:
    dlg = NewGameDialog(parent, settings)
    parent.wait_window(dlg)
    return dlg.result


# ---------------------------------------------------------------------------
# Namen für die Bestenliste
# ---------------------------------------------------------------------------
class NamesDialog(tk.Toplevel):
    def __init__(self, parent, defaults: list[str], info: str = "", modal: bool = True):
        super().__init__(parent, bg=C["bg"])
        self.withdraw()
        self.title("Bestenliste – Equivara")
        self.resizable(False, False)
        self.result = None
        box = tk.Frame(self, bg=C["panel"], highlightthickness=1, highlightbackground=C["border"])
        box.pack(fill="both", expand=True, padx=14, pady=14)
        tk.Label(box, text="🏆  In die Bestenliste eintragen", bg=C["panel"], fg=C["text"],
                 font=(FONT, 13, "bold"), anchor="w").pack(fill="x", padx=14, pady=(12, 2))
        if info:
            _label(box, info, fg=C["muted"], wraplength=380).pack(fill="x", padx=14)
        self.vars = []
        grid = tk.Frame(box, bg=C["panel"])
        grid.pack(fill="x", padx=14, pady=10)
        first = None
        for i, d in enumerate(defaults):
            _label(grid, d if len(defaults) > 1 else "Dein Name", width=14).grid(row=i, column=0, sticky="w",
                                                                                pady=2)
            v = tk.StringVar(value=d if len(defaults) > 1 else "")
            e = _entry(grid, v, width=26)
            e.grid(row=i, column=1, sticky="w", padx=(6, 0), pady=2)
            first = first or e
            self.vars.append(v)
        btns = tk.Frame(box, bg=C["panel"])
        btns.pack(fill="x", padx=14, pady=(0, 12))
        ttk.Button(btns, text="Eintragen", style="Accent.TButton", command=self.ok).pack(side="right")
        ttk.Button(btns, text="Nicht eintragen", command=self.cancel).pack(side="right", padx=8)
        self.bind("<Return>", lambda e: self.ok())
        self.bind("<Escape>", lambda e: self.cancel())
        self.protocol("WM_DELETE_WINDOW", self.cancel)
        self.deiconify()
        _center_on(self, parent)
        if first is not None:
            first.focus_set()
        if modal:
            try:
                self.transient(parent)
                self.grab_set()
            except tk.TclError:
                pass

    def ok(self):
        self.result = [v.get().strip() or "Unbenannt" for v in self.vars]
        self._close()

    def cancel(self):
        self.result = None
        self._close()

    def _close(self):
        try:
            self.grab_release()
        except tk.TclError:
            pass
        self.destroy()


def ask_names(parent, defaults: list[str], info: str = "") -> list[str] | None:
    dlg = NamesDialog(parent, defaults, info)
    parent.wait_window(dlg)
    return dlg.result


# ---------------------------------------------------------------------------
# Einstellungen
# ---------------------------------------------------------------------------
class SettingsView(tk.Frame):
    """Einstellungen; Änderungen werden sofort über ``save`` gespeichert."""

    def __init__(self, parent, load, save, on_tutorial=None, current_info=None, **kw):
        kw.setdefault("bg", C["bg"])
        super().__init__(parent, **kw)
        self._load = load
        self._save = save
        self._current_info = current_info
        self._busy = False
        configure_styles(self)

        self.min_vars = {k: tk.BooleanVar(value=False) for k in MINISTRIES}
        self.goal = tk.StringVar(value=goal_label(DEFAULT_GOAL))
        self.events = tk.BooleanVar(value=False)
        self.scenario = tk.StringVar(value=SCENARIOS["standard"]["name"])

        note = tk.Frame(self, bg=blend(C["orange"], C["bg"], 0.82), highlightthickness=1,
                        highlightbackground=blend(C["orange"], C["bg"], 0.5))
        note.pack(fill="x", pady=(0, 10))
        tk.Label(note, text="ⓘ  Änderungen werden sofort gespeichert und gelten ab dem nächsten neuen Spiel.",
                 bg=note["bg"], fg=C["orange"], font=(FONT, 10, "bold"), anchor="w").pack(fill="x", padx=12,
                                                                                         pady=8)
        cols = tk.Frame(self, bg=C["bg"])
        cols.pack(fill="both", expand=True)
        cols.columnconfigure(0, weight=3, uniform="s")
        cols.columnconfigure(1, weight=2, uniform="s")

        sec = _section(cols, "Ministerien")
        sec.grid(row=0, column=0, rowspan=2, sticky="nsew", padx=(0, 6))
        _label(sec, "Zusätzliche Staatsaufgaben mit eigenem Investitionsfeld, Kapitalstock, Kennlinie und "
                    "Dashboard-Karte. Alle aus = klassisches Modell.", fg=C["muted"], wraplength=520).pack(
            fill="x", padx=12, pady=(0, 6))
        for key, m in MINISTRIES.items():
            row = tk.Frame(sec, bg=C["panel"])
            row.pack(fill="x", padx=12, pady=4)
            _check(row, m["name"], self.min_vars[key], command=self._changed).pack(anchor="w")
            _label(row, m["description"], fg=C["muted"], size=8, wraplength=500).pack(fill="x", padx=(24, 0))
        tk.Frame(sec, bg=C["panel"], height=8).pack()

        sec = _section(cols, "Standard für neue Spiele")
        sec.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        row = tk.Frame(sec, bg=C["panel"])
        row.pack(fill="x", padx=12, pady=4)
        _label(row, "Ziel", width=10).pack(side="left")
        cb = ttk.Combobox(row, textvariable=self.goal, values=[t for t, _ in GOAL_OPTIONS], state="readonly",
                          width=14, style="Eq.TCombobox")
        cb.pack(side="left")
        cb.bind("<<ComboboxSelected>>", lambda e: self._changed())
        row = tk.Frame(sec, bg=C["panel"])
        row.pack(fill="x", padx=12, pady=4)
        _label(row, "Szenario", width=10).pack(side="left")
        cb = ttk.Combobox(row, textvariable=self.scenario, values=[s["name"] for s in SCENARIOS.values()],
                          state="readonly", width=20, style="Eq.TCombobox")
        cb.pack(side="left")
        cb.bind("<<ComboboxSelected>>", lambda e: self._changed())
        _check(sec, "Zufallsereignisse standardmäßig an", self.events, command=self._changed).pack(
            fill="x", padx=12, pady=(4, 12))

        sec = _section(cols, "Hilfe")
        sec.grid(row=1, column=1, sticky="nsew", padx=(6, 0), pady=(10, 0))
        _label(sec, "Die geführte Tour erklärt die wichtigsten Bereiche der Oberfläche.", fg=C["muted"],
               wraplength=360).pack(fill="x", padx=12)
        self.tutorial_btn = ttk.Button(sec, text="Tutorial erneut zeigen", command=on_tutorial or (lambda: None))
        self.tutorial_btn.pack(anchor="w", padx=12, pady=(8, 12))

        self.current = _label(self, "", bg=C["bg"], fg=C["muted"], wraplength=900)
        self.current.pack(fill="x", pady=(10, 0))
        self.saved = _label(self, "", bg=C["bg"], fg=C["green"])
        self.saved.pack(fill="x", pady=(2, 0))
        self.refresh()

    def refresh(self):
        s = self._load() or {}
        self._busy = True
        try:
            mins = settings_ministries(s)
            for k, v in self.min_vars.items():
                v.set(mins[k])
            self.goal.set(goal_label(settings_goal(s)))
            self.events.set(settings_events(s))
            self.scenario.set(SCENARIOS[settings_scenario(s)]["name"])
        finally:
            self._busy = False
        if self._current_info:
            try:
                self.current.config(text=self._current_info())
            except Exception:
                self.current.config(text="")
        self.saved.config(text="")

    def values(self) -> dict:
        sc = "standard"
        for k, v in SCENARIOS.items():
            if v["name"] == self.scenario.get():
                sc = k
        return {"ministries": {k: bool(v.get()) for k, v in self.min_vars.items()},
                "goal_cycles": goal_from_label(self.goal.get()),
                "events_default": bool(self.events.get()),
                "scenario_default": sc}

    def _changed(self):
        if self._busy:
            return
        s = dict(self._load() or {})
        s.update(self.values())
        try:
            self._save(s)
            self.saved.config(text="✔ Gespeichert – gilt ab dem nächsten neuen Spiel.", fg=C["green"])
        except Exception as exc:  # noqa: BLE001
            self.saved.config(text=f"Speichern fehlgeschlagen: {exc}", fg=C["red"])


# ---------------------------------------------------------------------------
# Hot-Seat-Zwischenbildschirm
# ---------------------------------------------------------------------------
class HandoverOverlay(tk.Frame):
    """Deckt das ganze Fenster ab, bis die nächste Person bestätigt."""

    def __init__(self, root, **kw):
        super().__init__(root, bg=C["bg"], **kw)
        self._on_continue = None
        self.visible = False
        box = tk.Frame(self, bg=C["panel"], highlightthickness=1, highlightbackground=C["border"])
        box.place(relx=0.5, rely=0.45, anchor="center")
        self.box = box
        self.top = tk.Label(box, text="ÜBERGABE", bg=C["panel"], fg=C["muted"], font=(FONT, 10, "bold"))
        self.top.pack(padx=60, pady=(28, 4))
        tk.Label(box, text="Jetzt am Zug:", bg=C["panel"], fg=C["text"], font=(FONT, 14)).pack(padx=60)
        self.name = tk.Label(box, text="", bg=C["panel"], fg=C["blue"], font=(FONT, 30, "bold"))
        self.name.pack(padx=60, pady=(2, 2))
        self.detail = tk.Label(box, text="", bg=C["panel"], fg=C["muted"], font=(FONT, 11), justify="center",
                               wraplength=560)
        self.detail.pack(padx=60, pady=(0, 6))
        self.hint = tk.Label(box, text="Die Eingaben der vorherigen Person sind verborgen, bis du bestätigst.",
                             bg=C["panel"], fg=blend(C["muted"], C["panel"], 0.3), font=(FONT, 9))
        self.hint.pack(padx=60, pady=(0, 14))
        self.button = ttk.Button(box, text="Ich bin bereit  →", style="Accent.TButton", command=self.confirm)
        self.button.pack(pady=(0, 10))
        self.back = tk.Label(box, text="", bg=C["panel"], fg=C["muted"], font=(FONT, 9, "underline"),
                             cursor="hand2")
        self.back.pack(pady=(0, 22))
        self.back.bind("<Button-1>", lambda e: self._on_back() if self._on_back else None)
        self._on_back = None

    def show(self, name: str, color: str | None = None, detail: str = "", on_continue=None,
             top: str = "ÜBERGABE", back_text: str = "", on_back=None):
        self._on_continue = on_continue
        self._on_back = on_back
        self.back.config(text=back_text if on_back else "")
        self.top.config(text=top)
        self.name.config(text=name, fg=color or C["blue"])
        self.box.config(highlightbackground=color or C["border"])
        self.detail.config(text=detail)
        self.place(x=0, y=0, relwidth=1, relheight=1)
        self.lift()
        self.visible = True
        try:
            self.button.focus_set()
        except tk.TclError:
            pass

    def confirm(self):
        if not self.visible:
            return
        self.visible = False
        self.place_forget()
        cb, self._on_continue = self._on_continue, None
        if cb:
            cb()

    def hide(self):
        self.visible = False
        self._on_continue = None
        self.place_forget()
