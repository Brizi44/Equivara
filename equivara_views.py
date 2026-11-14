"""
equivara_views.py - Zusaetzliche Ansichten fuer die Equivara-Oberflaeche.

Nur tkinter / Standardbibliothek + Projektmodule.

Oeffentliche API (siehe CONTRACT2.md, Abschnitt 3):
    CurveChart, CurvesView, CausalLoopView, CompareView, LeaderboardView, Tutorial

Robust gegenueber fehlenden Engine-Erweiterungen: Fehlt ``engine.curve_positions()``,
werden die Kennlinien direkt aus den ``*_CURVE``-Klassenattributen gelesen und der
Arbeitspunkt aus dem Engine-Zustand berechnet. Fehlt ``equivara_store``, zeigt die
Bestenliste einen freundlichen Hinweis.
"""

from __future__ import annotations

import json
import math
import tkinter as tk
import tkinter.font as tkfont
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Callable

from equivara_widgets import (
    THEME,
    FONT_UI,
    MultiLineChart,
    Tooltip,
    _ChartBase,
    _scrollbar_styles,
    blend,
    fmt_value,
    nice_ticks,
)

try:  # Engine ist fuer die Ansichten optional (z.B. Vergleich von Dateien)
    import equivara_engine as _engine_mod
    from equivara_engine import EquivaraEngine
except Exception:  # pragma: no cover
    _engine_mod = None
    EquivaraEngine = None  # type: ignore

__all__ = [
    "CurveChart",
    "CurvesView",
    "CausalLoopView",
    "CompareView",
    "LeaderboardView",
    "Tutorial",
]

SERIES_COLORS = [THEME["blue"], THEME["orange"], THEME["green"], THEME["purple"],
                 THEME["cyan"], THEME["red"]]


# --------------------------------------------------------------------------
# Hilfsfunktionen
# --------------------------------------------------------------------------
def _num(v) -> float | None:
    if v is None or isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def _interp(points, x: float) -> float | None:
    """Stueckweise lineare Interpolation, ausserhalb des Bereichs konstant fortgesetzt."""
    pts = sorted((float(a), float(b)) for a, b in points)
    if not pts:
        return None
    if x <= pts[0][0]:
        return pts[0][1]
    if x >= pts[-1][0]:
        return pts[-1][1]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if x0 <= x <= x1:
            if x1 == x0:
                return y1
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return pts[-1][1]


def _smart(v) -> str:
    """Kompakte Zahl fuer Achsen/Tooltips."""
    v = _num(v)
    if v is None:
        return "–"
    a = abs(v)
    if a >= 1000:
        return f"{v:,.0f}".replace(",", ".")
    if a >= 100:
        return f"{v:.0f}"
    if a >= 10:
        return f"{v:.1f}"
    return f"{v:.2f}"


def _tick_txt(t: float, step: float) -> str:
    if step >= 1 and abs(t - round(t)) < 1e-9:
        return f"{t:,.0f}".replace(",", ".")
    dec = 0
    while dec < 4 and abs(step * 10 ** dec - round(step * 10 ** dec)) > 1e-6:
        dec += 1
    return f"{t:.{dec}f}"


def _bezier(p0, c, p1, t):
    u = 1 - t
    return (u * u * p0[0] + 2 * u * t * c[0] + t * t * p1[0],
            u * u * p0[1] + 2 * u * t * c[1] + t * t * p1[1])


def _bind_wheel(widget, canvas: tk.Canvas):
    """Mausrad scrollt canvas, solange der Zeiger ueber widget ist."""

    def on_wheel(e):
        try:
            if e.delta:
                canvas.yview_scroll(int(-e.delta / 120) or (-1 if e.delta > 0 else 1), "units")
            elif getattr(e, "num", None) == 4:
                canvas.yview_scroll(-3, "units")
            elif getattr(e, "num", None) == 5:
                canvas.yview_scroll(3, "units")
        except tk.TclError:
            pass

    def enter(_e):
        widget.bind_all("<MouseWheel>", on_wheel)
        widget.bind_all("<Button-4>", on_wheel)
        widget.bind_all("<Button-5>", on_wheel)

    def leave(_e):
        for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            try:
                widget.unbind_all(seq)
            except tk.TclError:
                pass

    widget.bind("<Enter>", enter, add="+")
    widget.bind("<Leave>", leave, add="+")


def _header(parent, title: str, subtitle: str = "", bg=None) -> tk.Frame:
    bg = bg or THEME["bg"]
    f = tk.Frame(parent, bg=bg)
    tk.Label(f, text=title, bg=bg, fg=THEME["text"], font=(FONT_UI, 15, "bold"),
             anchor="w").pack(anchor="w")
    if subtitle:
        tk.Label(f, text=subtitle, bg=bg, fg=THEME["muted"], font=(FONT_UI, 10),
                 anchor="w", justify="left").pack(anchor="w", pady=(2, 0))
    return f


def _button(parent, text, command, accent=False, **kw) -> tk.Button:
    c = THEME
    bg = c["blue"] if accent else c["panel2"]
    fg = c["white"] if accent else c["text"]
    b = tk.Button(parent, text=text, command=command, bg=bg, fg=fg,
                  activebackground=blend(bg, c["white"], 0.15), activeforeground=fg,
                  relief="flat", bd=0, padx=12, pady=6, font=(FONT_UI, 9, "bold" if accent else "normal"),
                  cursor="hand2", highlightthickness=1, highlightbackground=c["border"], **kw)
    return b


def _ttk_styles(widget) -> None:
    """Dunkle Stile fuer Combobox/Treeview/Radiobutton (wirken im 'clam'-Theme)."""
    c = THEME
    st = ttk.Style(widget)
    try:
        st.configure("Equivara.TCombobox", fieldbackground=c["panel2"], background=c["panel2"],
                     foreground=c["text"], arrowcolor=c["muted"], bordercolor=c["border"],
                     lightcolor=c["panel2"], darkcolor=c["panel2"], selectbackground=c["panel2"],
                     selectforeground=c["text"])
        st.map("Equivara.TCombobox", fieldbackground=[("readonly", c["panel2"])],
               foreground=[("readonly", c["text"])],
               selectbackground=[("readonly", c["panel2"])],
               selectforeground=[("readonly", c["text"])])
        widget.option_add("*TCombobox*Listbox.background", c["panel2"])
        widget.option_add("*TCombobox*Listbox.foreground", c["text"])
        widget.option_add("*TCombobox*Listbox.selectBackground", c["blue"])
        widget.option_add("*TCombobox*Listbox.selectForeground", c["white"])
        st.configure("Equivara.Treeview", background=c["panel"], fieldbackground=c["panel"],
                     foreground=c["text"], rowheight=28, bordercolor=c["border"],
                     lightcolor=c["panel"], darkcolor=c["panel"], font=(FONT_UI, 10))
        st.map("Equivara.Treeview", background=[("selected", blend(c["blue"], c["panel"], 0.45))],
               foreground=[("selected", c["white"])])
        st.configure("Equivara.Treeview.Heading", background=c["panel2"], foreground=c["muted"],
                     relief="flat", bordercolor=c["border"], lightcolor=c["panel2"],
                     darkcolor=c["panel2"], font=(FONT_UI, 9, "bold"), padding=(6, 6))
        st.map("Equivara.Treeview.Heading", background=[("active", c["border"])])
    except tk.TclError:
        pass


# --------------------------------------------------------------------------
# Kennlinien-Metadaten (Fallback, falls engine.curve_positions fehlt)
# --------------------------------------------------------------------------
_CURVE_META = [
    # key, Abb., Titel, x-Beschriftung, y-Beschriftung
    ("BIRTH_RATE_CURVE", 1, "Normale Geburtenrate", "Güter/Kopf (Ø 3 Zyklen)", "Geburten pro 1000/Jahr"),
    ("BIRTH_SERVICE_MULT_CURVE", 2, "Geburten-Multiplikator Human Services",
     "Human Services/Kopf", "Multiplikator"),
    ("DEATH_RATE_CURVE", 3, "Normale Sterberate", "Nahrung/Kopf (NW)", "Sterbefälle pro 1000/Jahr"),
    ("DEATH_ENV_MULT_CURVE", 4, "Sterbe-Multiplikator Umwelt", "Umweltqualität (0–1)", "Multiplikator"),
    ("ENERGY_PRODUCTION_LOW_CURVE", 5, "Energieproduktion", "Energiekapital (Tsd.)", "Energie (Tsd. EW)"),
    ("ENERGY_EFFICIENCY_CURVE", 6, "Energieverbrauch durch Effizienz",
     "Effizienz-/Produktionskapital", "Verbrauchsfaktor"),
    ("FOOD_CONSUMPTION_CHANGE_CURVE", 7, "Nahrungsproduktion bei Konsumänderung",
     "Konsum jetzt / vorher", "Multiplikator"),
    ("FOOD_CAPITAL_CURVE", 8, "Landproduktivität", "Aktives Nahrungskapital / Land", "Multiplikator"),
    ("ENV_DEGRADATION_CURVE", 9, "Umweltbelastung", "Belastung (relativ)", "Abbau % pro Jahr"),
    ("ENV_REGENERATION_CURVE", 10, "Umweltregeneration", "Umweltqualität (0–1)", "Regeneration %-Pkt./Jahr"),
    ("GOODS_CONSUMPTION_CHANGE_CURVE", 11, "Güterproduktion bei Konsumänderung",
     "Konsum jetzt / vorher", "Multiplikator"),
    ("GOODS_CAPITAL_CURVE", 12, "Arbeitsproduktivität", "Güterkapital / Arbeitskraft", "Multiplikator"),
    ("HUMAN_SERVICE_CURVE", 13, "Güterproduktion durch Human Services", "Human Services/Kopf",
     "Multiplikator"),
    ("IMPORT_PRICE_MULT_CURVE", 14, "Importpreise", "Schulden / Exporte", "Preis-Multiplikator"),
    ("INTEREST_RATE_CURVE", 15, "Zinssatz", "Schulden / Exporte", "Zins % pro Jahr"),
]


def _curve_color(key: str) -> str:
    c = THEME
    if key.startswith("BIRTH"):
        return c["blue"]
    if key.startswith("DEATH"):
        return c["red"]
    if key.startswith("ENERGY"):
        return c["orange"]
    if key.startswith("FOOD"):
        return c["cyan"]
    if key.startswith("ENV"):
        return c["green"]
    if key.startswith("GOODS") or key.startswith("HUMAN"):
        return c["purple"]
    return blend(c["red"], c["orange"], 0.5)


def _fallback_x(engine, key: str) -> float | None:
    """Arbeitspunkt (x) aus dem Engine-Zustand – nur genutzt, wenn curve_positions fehlt."""
    h = engine.history[-1] if getattr(engine, "history", None) else {}
    g = lambda name, default=None: getattr(engine, name, default)  # noqa: E731
    try:
        if key == "BIRTH_RATE_CURVE":
            hist = g("goods_pc_history") or [g("goods_pc", 0.0)]
            return sum(hist) / len(hist)
        if key in ("BIRTH_SERVICE_MULT_CURVE", "HUMAN_SERVICE_CURVE"):
            return float(g("human_services_pc"))
        if key == "DEATH_RATE_CURVE":
            return float(g("food_pc"))
        if key in ("DEATH_ENV_MULT_CURVE", "ENV_REGENERATION_CURVE"):
            return float(g("environment"))
        if key == "ENERGY_PRODUCTION_LOW_CURVE":
            return float(g("cap_energy_prod")) / 1000.0
        if key == "ENERGY_EFFICIENCY_CURVE":
            prod = float(g("cap_food", 0.0)) + float(g("cap_goods", 0.0))
            return float(g("cap_energy_eff", 0.0)) / prod if prod > 0 else None
        if key == "FOOD_CONSUMPTION_CHANGE_CURVE":
            return float(g("food_pc")) / max(0.001, float(g("last_food_pc")))
        if key == "GOODS_CONSUMPTION_CHANGE_CURVE":
            return float(g("goods_pc")) / max(0.001, float(g("last_goods_pc")))
        if key == "FOOD_CAPITAL_CURVE":
            return float(g("active_food_capital")) / float(g("LAND_AREA", 1000.0))
        if key == "GOODS_CAPITAL_CURVE":
            return float(g("active_goods_capital")) / max(1.0, float(g("labor_force")))
        if key == "ENV_DEGRADATION_CURVE":
            load = _num(h.get("env_load"))
            return None if load is None else _clamp(load / 20000.0, 0.0, 1.0)
        if key in ("IMPORT_PRICE_MULT_CURVE", "INTEREST_RATE_CURVE"):
            r = _num(h.get("debt_export_ratio"))
            return None if r is None else _clamp(r, 0.0, 5.0)
    except (TypeError, ValueError, AttributeError, ZeroDivisionError):
        return None
    return None


def _fallback_positions(engine) -> list[dict]:
    out = []
    for key, fig, title, xl, yl in _CURVE_META:
        pts = getattr(engine, key, None) or getattr(type(engine), key, None)
        if not pts:
            continue
        pts = [(float(a), float(b)) for a, b in pts]
        x = _fallback_x(engine, key)
        y = None
        if x is not None:
            x = _clamp(x, pts[0][0], pts[-1][0])
            y = _interp(pts, x)
        out.append({"key": key, "figure": fig, "title": title, "x_label": xl, "y_label": yl,
                    "points": pts, "x": x, "y": y})
    return out


def _curve_positions(engine) -> list[dict]:
    if engine is None:
        return []
    fn = getattr(engine, "curve_positions", None)
    if callable(fn):
        try:
            res = fn()
            if res:
                return list(res)
        except Exception:  # Engine in Arbeit – auf Fallback ausweichen
            pass
    return _fallback_positions(engine)


# --------------------------------------------------------------------------
# CurveChart
# --------------------------------------------------------------------------
class CurveChart(_ChartBase):
    """Eine Kennlinie (Tabellenfunktion) mit beschrifteten Achsen und Arbeitspunkt."""

    PAD_R = 14
    PAD_B = 38

    def __init__(self, parent, title: str, x_label: str, y_label: str, color: str,
                 height: int = 190, **kw):
        kw.setdefault("width", 300)
        super().__init__(parent, title, height, "{:.2f}", "", **kw)
        self.x_label = x_label or ""
        self.y_label = y_label or ""
        self.color = color
        self._f_label = tkfont.Font(self, family=FONT_UI, size=8)
        self._points: list[tuple[float, float]] = []
        self._x: float | None = None
        self._y: float | None = None
        self.redraw()

    def set_curve(self, points: list[tuple[float, float]], x: float | None = None,
                  y: float | None = None) -> None:
        pts = []
        for p in points or []:
            try:
                a, b = _num(p[0]), _num(p[1])
            except (TypeError, IndexError):
                continue
            if a is not None and b is not None:
                pts.append((a, b))
        self._points = sorted(pts)
        self._x = _num(x)
        self._y = _num(y)
        if self._x is not None and self._y is None and self._points:
            self._y = _interp(self._points, self._x)
        self.redraw()

    # -- Zeichnen -------------------------------------------------------
    def redraw(self):
        self.delete("all")
        self._layout = None
        w, h = self._size()
        c = THEME
        title = self.title
        maxw = w - 24
        if self._f_title.measure(title) > maxw:
            while len(title) > 4 and self._f_title.measure(title + "…") > maxw:
                title = title[:-1]
            title += "…"
        self.create_text(12, 14, text=title, anchor="w", fill=c["text"], font=self._f_title)
        if self._x is not None and self._y is not None:
            self.create_oval(12, 28, 20, 36, fill=self.color, outline="")
            self.create_text(25, 32, text=f"Arbeitspunkt  x = {_smart(self._x)}   →   y = {_smart(self._y)}",
                             anchor="w", fill=self.color, font=self._f_small_b)
        else:
            self.create_text(12, 32, text="Arbeitspunkt noch nicht bestimmbar", anchor="w",
                             fill=c["muted"], font=self._f_small)
        top = 48
        if len(self._points) < 2:
            self._empty(w, h, top)
            return

        xs = [p[0] for p in self._points]
        ys = [p[1] for p in self._points]
        if self._x is not None:
            xs.append(self._x)
        if self._y is not None:
            ys.append(self._y)
        lo, hi = min(ys), max(ys)
        if lo >= 0 and lo <= 0.35 * hi:
            lo = 0.0
        plot_h = max(20, h - top - self.PAD_B)
        yt = nice_ticks(lo, hi, max(3, min(5, plot_h // 26 + 1)))
        ystep = yt[1] - yt[0] if len(yt) > 1 else 1.0
        y0, y1 = yt[0], yt[-1]
        ylabels = [_tick_txt(t, ystep) for t in yt]
        lab_w = max(self._f_axis.measure(s) for s in ylabels)
        left = 20 + lab_w + 6
        right = w - self.PAD_R
        bottom = h - self.PAD_B
        if right - left < 30:
            right = left + 30

        x_lo, x_hi = min(xs), max(xs)
        if x_hi - x_lo <= 0:
            x_hi = x_lo + 1
        xt = nice_ticks(x_lo, x_hi, max(3, min(7, int((right - left) // 46))))
        xt = [t for t in xt if x_lo - 1e-9 <= t <= x_hi + 1e-9] or [x_lo, x_hi]
        xstep = xt[1] - xt[0] if len(xt) > 1 else 1.0

        def px(x):
            return left + (x - x_lo) / (x_hi - x_lo) * (right - left)

        def py(y):
            return bottom - (y - y0) / ((y1 - y0) or 1.0) * (bottom - top)

        grid = blend(c["border"], self._bgc, 0.4)
        for t, s in zip(yt, ylabels):
            yy = py(t)
            self.create_line(left, yy, right, yy, fill=grid)
            self.create_text(left - 6, yy, text=s, anchor="e", fill=c["muted"], font=self._f_axis)
        for t in xt:
            xx = px(t)
            self.create_line(xx, top, xx, bottom, fill=blend(grid, self._bgc, 0.45))
            self.create_line(xx, bottom, xx, bottom + 3, fill=c["border"])
            self.create_text(xx, bottom + 4, text=_tick_txt(t, xstep), anchor="n",
                             fill=c["muted"], font=self._f_axis)
        self.create_line(left, bottom, right, bottom, fill=c["border"])
        self.create_line(left, top, left, bottom, fill=c["border"])
        # Achsentitel
        self.create_text((left + right) / 2, h - 6, text=self.x_label, anchor="s",
                         fill=c["muted"], font=self._f_label)
        try:
            self.create_text(9, (top + bottom) / 2, text=self.y_label, angle=90,
                             fill=c["muted"], font=self._f_label)
        except tk.TclError:  # sehr alte Tk-Versionen ohne angle
            pass

        coords = [(px(x), py(y)) for x, y in self._points]
        poly = [coords[0][0], bottom] + [v for xy in coords for v in xy] + [coords[-1][0], bottom]
        self.create_polygon(poly, fill=blend(self.color, self._bgc, 0.86), outline="")
        self.create_line([v for xy in coords for v in xy], fill=self.color, width=2,
                         capstyle="round", joinstyle="round")
        for xx, yy in coords:
            self.create_oval(xx - 2, yy - 2, xx + 2, yy + 2, fill=blend(self.color, self._bgc, 0.3),
                             outline="")

        if self._x is not None and self._y is not None:
            ax, ay = px(self._x), py(self._y)
            guide = blend(self.color, self._bgc, 0.35)
            self.create_line(ax, ay, ax, bottom, fill=guide, dash=(3, 3))
            self.create_line(left, ay, ax, ay, fill=guide, dash=(3, 3))
            self.create_oval(ax - 11, ay - 11, ax + 11, ay + 11, outline="",
                             fill=blend(self.color, self._bgc, 0.72))
            self.create_oval(ax - 6.5, ay - 6.5, ax + 6.5, ay + 6.5, fill=self.color,
                             outline=c["white"], width=2)

        self._layout = {"left": left, "right": right, "top": top, "bottom": bottom,
                        "px": px, "py": py, "x_lo": x_lo, "x_hi": x_hi}

    def _on_motion(self, event):
        self.delete("hover")
        L = self._layout
        if not L or not (L["left"] - 4 <= event.x <= L["right"] + 4
                         and L["top"] - 6 <= event.y <= L["bottom"] + 6):
            return
        frac = _clamp((event.x - L["left"]) / max(1, L["right"] - L["left"]), 0.0, 1.0)
        x = L["x_lo"] + frac * (L["x_hi"] - L["x_lo"])
        y = _interp(self._points, x)
        if y is None:
            return
        xx, yy = L["px"](x), L["py"](y)
        self.create_line(xx, L["top"], xx, L["bottom"], fill=blend(THEME["muted"], self._bgc, 0.45),
                         tags="hover")
        self.create_oval(xx - 4.5, yy - 4.5, xx + 4.5, yy + 4.5, outline=self.color, width=2,
                         fill=self._bgc, tags="hover")
        lines = [(f"{self.x_label}: {_smart(x)}", THEME["muted"], False, None),
                 (f"{self.y_label}: {_smart(y)}", THEME["text"], True, self.color)]
        self._draw_tip(xx, yy, lines)


# --------------------------------------------------------------------------
# CurvesView
# --------------------------------------------------------------------------
class CurvesView(tk.Frame):
    """Scrollbares Raster (3 Spalten) aller Kennlinien mit aktuellem Arbeitspunkt."""

    COLUMNS = 3

    def __init__(self, parent, engine_getter: Callable[[], object], **kw):
        kw.setdefault("bg", THEME["bg"])
        super().__init__(parent, **kw)
        self.engine_getter = engine_getter
        self._charts: dict[str, CurveChart] = {}
        bg = self["bg"]

        head = _header(self, "Kennlinien",
                       "Der Punkt zeigt, wo dein Land gerade auf der Kurve steht.", bg=bg)
        head.pack(fill="x", padx=16, pady=(14, 2))
        tk.Label(self, text="Die 15 Tabellenfunktionen des Modells. Fahre mit der Maus über eine Kurve, "
                            "um Werte abzulesen.", bg=bg, fg=blend(THEME["muted"], bg, 0.25),
                 font=(FONT_UI, 9), anchor="w").pack(fill="x", padx=16, pady=(0, 8))

        body = tk.Frame(self, bg=bg)
        body.pack(fill="both", expand=True, padx=(12, 4), pady=(0, 10))
        self._canvas = tk.Canvas(body, bg=bg, highlightthickness=0, bd=0)
        vs, _hs = _scrollbar_styles(self)
        self._sb = ttk.Scrollbar(body, orient="vertical", command=self._canvas.yview, style=vs)
        self._canvas.configure(yscrollcommand=self._sb.set)
        self._sb.pack(side="right", fill="y")
        self._canvas.pack(side="left", fill="both", expand=True)
        self._grid = tk.Frame(self._canvas, bg=bg)
        self._win = self._canvas.create_window(0, 0, window=self._grid, anchor="nw")
        self._grid.bind("<Configure>", lambda e: self._canvas.configure(
            scrollregion=self._canvas.bbox("all")))
        self._canvas.bind("<Configure>", lambda e: self._canvas.itemconfigure(self._win, width=e.width))
        for i in range(self.COLUMNS):
            self._grid.columnconfigure(i, weight=1, uniform="curves")
        self._empty = tk.Label(self._grid, text="Keine Kennlinien verfügbar.", bg=bg,
                               fg=THEME["muted"], font=(FONT_UI, 11))
        _bind_wheel(self._canvas, self._canvas)
        _bind_wheel(self._grid, self._canvas)
        self.refresh()

    def _engine(self):
        try:
            return self.engine_getter() if self.engine_getter else None
        except Exception:
            return None

    def refresh(self) -> None:
        positions = _curve_positions(self._engine())
        keys = [p.get("key", str(i)) for i, p in enumerate(positions)]
        if keys != list(self._charts):
            for ch in self._charts.values():
                ch.destroy()
            self._charts.clear()
            for i, p in enumerate(positions):
                key = keys[i]
                fig = p.get("figure")
                title = f"Abb. {fig} · {p.get('title', key)}" if fig else str(p.get("title", key))
                ch = CurveChart(self._grid, title, p.get("x_label", "x"), p.get("y_label", "y"),
                                _curve_color(key), height=210, bg=THEME["panel"])
                ch.grid(row=i // self.COLUMNS, column=i % self.COLUMNS, sticky="nsew", padx=5, pady=5)
                _bind_wheel(ch, self._canvas)
                self._charts[key] = ch
        if not positions:
            self._empty.grid(row=0, column=0, columnspan=self.COLUMNS, pady=40)
        else:
            self._empty.grid_forget()
        for key, p in zip(keys, positions):
            self._charts[key].set_curve(p.get("points") or [], p.get("x"), p.get("y"))


# --------------------------------------------------------------------------
# CausalLoopView – Wirkungsgefuege
# --------------------------------------------------------------------------
# Knoten: key -> (Name, rel. x, rel. y, Hebel?, Erklaerung)
_CLD_NODES = {
    "hs": ("Human Services", 0.075, 0.11, True,
           "Bildung, Gesundheit, soziale Dienste pro Kopf. Steigert die Güterproduktion und senkt "
           "langfristig die Geburtenrate. Wächst durch Investitionen, verdünnt sich bei Bevölkerungswachstum."),
    "goods": ("Güter/Kopf", 0.33, 0.11, False,
              "Konsumgüter pro Kopf und Jahr. Wohlstand senkt die Geburtenrate (demografischer Übergang)."),
    "capg": ("Güterkapital", 0.62, 0.11, True,
             "Fabriken und Maschinen. Mehr Kapital pro Arbeitskraft erhöht die Güterproduktion – "
             "belastet aber die Umwelt."),
    "exp": ("Exporte", 0.91, 0.11, False,
            "Exporterlöse (Ø der letzten Zyklen). Sie bestimmen, wie viel Schulden tragbar sind."),
    "birth": ("Geburtenrate", 0.13, 0.36, False,
              "Geburten pro 1000 Einwohner und Jahr. Hängt von Güter/Kopf und Human Services ab."),
    "pop": ("Bevölkerung", 0.385, 0.52, False,
            "Einwohnerzahl. Wächst, solange die Geburtenrate über der Sterberate liegt."),
    "energy": ("Energie", 0.585, 0.44, True,
               "Verfügbare Energie. Ohne genug Energie laufen Nahrungs- und Güterkapital nicht voll."),
    "debt": ("Schulden", 0.91, 0.38, True,
             "Auslandsschulden. Ein hohes Verhältnis Schulden/Exporte verteuert Zinsen und Importe."),
    "impp": ("Importpreise", 0.91, 0.68, False,
             "Multiplikator auf Importpreise (und Zinssatz). Steigt ab Schulden > 2× Exporte."),
    "death": ("Sterberate", 0.13, 0.70, False,
              "Sterbefälle pro 1000 Einwohner und Jahr. Steigt stark bei Nahrung/Kopf < 2 und schlechter Umwelt."),
    "env": ("Umwelt", 0.70, 0.76, True,
            "Umweltqualität (0–100 %). Produktion belastet sie, Regeneration erholt sie – am besten um 50 %, "
            "darunter kippt die Erholung."),
    "food": ("Nahrung/Kopf", 0.33, 0.92, False,
             "Nahrung pro Kopf und Jahr (NW). Unter 2,0 steigt die Sterberate deutlich."),
    "capf": ("Nahrungskapital", 0.60, 0.92, True,
             "Landwirtschaftliche Ausstattung. Mehr Kapital pro Fläche erhöht die Nahrungsproduktion."),
}

# Kanten: (von, nach, Polaritaet, Kruemmung, Erklaerung)
_CLD_EDGES = [
    ("birth", "pop", "+", 0.22, "Mehr Geburten → mehr Menschen."),
    ("pop", "birth", "+", 0.22, "Mehr Menschen → mehr Geburten (absolut)."),
    ("death", "pop", "−", 0.22, "Mehr Sterbefälle → weniger Menschen."),
    ("pop", "death", "+", 0.22, "Mehr Menschen → mehr Sterbefälle (absolut)."),
    ("pop", "goods", "−", 0.0, "Mehr Menschen teilen sich die Güter → weniger Güter/Kopf."),
    ("pop", "food", "−", 0.0, "Mehr Menschen teilen sich die Nahrung → weniger Nahrung/Kopf."),
    ("pop", "hs", "−", 0.08, "Mehr Menschen → Human Services pro Kopf verdünnen sich."),
    ("goods", "birth", "−", -0.08, "Wohlstand senkt die Geburtenrate (Abb. 1)."),
    ("hs", "birth", "−", -0.15, "Bildung & Gesundheit senken langfristig die Geburtenrate (Abb. 2)."),
    ("hs", "goods", "+", 0.0, "Human Services steigern die Güterproduktion (Abb. 13)."),
    ("food", "death", "−", 0.1, "Mehr Nahrung/Kopf → niedrigere Sterberate (Abb. 3)."),
    ("env", "death", "−", 0.06, "Bessere Umwelt → niedrigere Sterberate (Abb. 4)."),
    ("capg", "goods", "+", 0.34, "Mehr Güterkapital → mehr Güterproduktion (Abb. 12)."),
    ("goods", "capg", "+", 0.34, "Güterproduktion finanziert Investitionen in Kapital."),
    ("capf", "food", "+", 0.0, "Mehr Nahrungskapital → mehr Nahrung (Abb. 8)."),
    ("energy", "goods", "+", 0.0, "Energie treibt die Güterproduktion an."),
    ("energy", "food", "+", -0.05, "Energie treibt die Nahrungsproduktion an."),
    ("energy", "env", "−", 0.0, "Energieproduktion belastet die Umwelt."),
    ("capg", "env", "−", -0.18, "Industrie belastet die Umwelt (Abb. 9)."),
    ("capf", "env", "−", 0.12, "Intensive Landwirtschaft belastet die Umwelt (Abb. 9)."),
    ("capg", "exp", "+", 0.0, "Mehr Produktionskapazität → mehr exportierbare Güter."),
    ("exp", "debt", "−", 0.0, "Höhere Exporterlöse → Schulden wiegen relativ weniger, Tilgung möglich."),
    ("debt", "impp", "+", 0.25, "Schulden/Exporte > 2 → höhere Zinsen und Importpreise (Abb. 14/15)."),
    ("impp", "debt", "+", 0.25, "Teure Zinsen & Importe → mehr neue Kredite nötig."),
    ("impp", "energy", "−", 0.0, "Teurere Importe → weniger importierte Energie."),
]

# Schleifen: (id, Name, Typ R/B, rel. x, rel. y, Kanten, Erklaerung)
_CLD_LOOPS = [
    ("R1", "Bevölkerungswachstum", "R", 0.255, 0.44, [("pop", "birth"), ("birth", "pop")],
     "Mehr Menschen bekommen mehr Kinder – exponentielles Wachstum."),
    ("B1", "Sterblichkeit", "B", 0.255, 0.615, [("pop", "death"), ("death", "pop")],
     "Mehr Menschen → mehr Sterbefälle; bremst das Wachstum."),
    ("R2", "Armutsfalle", "R", 0.255, 0.255, [("pop", "goods"), ("goods", "birth"), ("birth", "pop")],
     "Wachstum senkt Güter/Kopf, Armut hält die Geburtenrate hoch – noch mehr Wachstum."),
    ("B2", "Hunger (Malthus)", "B", 0.265, 0.80, [("pop", "food"), ("food", "death"), ("death", "pop")],
     "Wachstum senkt Nahrung/Kopf, Hunger erhöht die Sterberate und begrenzt die Bevölkerung."),
    ("R3", "Kapitalbildung", "R", 0.475, 0.11, [("capg", "goods"), ("goods", "capg")],
     "Güterproduktion wird investiert und erhöht die Kapazität – Wachstumsmotor."),
    ("B3", "Umwelt & Regeneration", "B", 0.80, 0.90, [("env", "env"), ("capg", "env"), ("capf", "env"),
                                                     ("energy", "env"), ("env", "death")],
     "Die Natur erholt sich selbst, am stärksten bei ~50 %. Fällt die Umwelt darunter, sinkt auch "
     "die Erholung – Belastung durch Kapital und Energie wird gefährlich."),
    ("R4", "Schuldenspirale", "R", 0.91, 0.53, [("debt", "impp"), ("impp", "debt")],
     "Hohe Schulden verteuern Zinsen und Importe, was noch mehr Kredite erzwingt."),
]


class CausalLoopView(tk.Frame):
    """Wirkungsgefuege (Causal-Loop-Diagramm) mit Hervorhebung nach aktuellem Zustand."""

    INFO_W = 300

    def __init__(self, parent, engine_getter, **kw):
        kw.setdefault("bg", THEME["bg"])
        super().__init__(parent, **kw)
        self.engine_getter = engine_getter
        bg = self["bg"]
        c = THEME
        self._state: dict = {}
        self._warnings: list[str] = []
        self._selected: str | None = None
        self._hover: str | None = None
        self._after = None
        self._node_rects: dict[str, tuple[float, float, float, float]] = {}

        head = _header(self, "Wirkungsgefüge",
                       "Wie die Größen deines Landes zusammenhängen. Dicke, farbige Pfeile wirken "
                       "gerade besonders stark. Klicke auf einen Knoten für Details.", bg=bg)
        head.pack(fill="x", padx=16, pady=(14, 8))

        body = tk.Frame(self, bg=bg)
        body.pack(fill="both", expand=True, padx=16, pady=(0, 12))
        side = tk.Frame(body, bg=c["panel"], width=self.INFO_W, highlightthickness=1,
                        highlightbackground=c["border"])
        side.pack(side="right", fill="y", padx=(10, 0))
        side.pack_propagate(False)
        self.canvas = tk.Canvas(body, bg=c["panel"], highlightthickness=1,
                                highlightbackground=c["border"], bd=0, width=760, height=520)
        self.canvas.pack(side="left", fill="both", expand=True)

        # Info-Panel
        pad = dict(padx=14)
        self._info_title = tk.Label(side, text="", bg=c["panel"], fg=c["text"],
                                    font=(FONT_UI, 12, "bold"), anchor="w", justify="left")
        self._info_title.pack(fill="x", pady=(12, 0), **pad)
        self._info_value = tk.Label(side, text="", bg=c["panel"], fg=c["cyan"],
                                    font=(FONT_UI, 11, "bold"), anchor="w", justify="left")
        self._info_value.pack(fill="x", **pad)
        self._info_text = tk.Label(side, text="", bg=c["panel"], fg=c["muted"], font=(FONT_UI, 9),
                                   anchor="w", justify="left", wraplength=self.INFO_W - 30)
        self._info_text.pack(fill="x", pady=(4, 8), **pad)
        tk.Frame(side, bg=c["border"], height=1).pack(fill="x", padx=10, pady=4)
        tk.Label(side, text="RÜCKKOPPLUNGSSCHLEIFEN", bg=c["panel"], fg=c["muted"],
                 font=(FONT_UI, 8, "bold"), anchor="w").pack(fill="x", pady=(4, 2), **pad)
        self._loop_frame = tk.Frame(side, bg=c["panel"])
        self._loop_frame.pack(fill="x", **pad)
        tk.Frame(side, bg=c["border"], height=1).pack(fill="x", padx=10, pady=8)
        tk.Label(side, text="SYSTEMWARNUNGEN", bg=c["panel"], fg=c["muted"],
                 font=(FONT_UI, 8, "bold"), anchor="w").pack(fill="x", pady=(0, 2), **pad)
        self._warn_lbl = tk.Label(side, text="", bg=c["panel"], fg=c["orange"], font=(FONT_UI, 9),
                                  anchor="nw", justify="left", wraplength=self.INFO_W - 30)
        self._warn_lbl.pack(fill="x", **pad)

        self._f_node = tkfont.Font(self, family=FONT_UI, size=10, weight="bold")
        self._f_node_s = tkfont.Font(self, family=FONT_UI, size=9, weight="bold")
        self._f_val = tkfont.Font(self, family=FONT_UI, size=8)
        self._f_pol = tkfont.Font(self, family=FONT_UI, size=9, weight="bold")
        self._f_loop = tkfont.Font(self, family=FONT_UI, size=9, weight="bold")
        self._f_leg = tkfont.Font(self, family=FONT_UI, size=8)

        self.canvas.bind("<Configure>", self._schedule, add="+")
        self.canvas.bind("<Button-1>", self._on_click_bg, add="+")
        self.refresh()

    # -- Daten ------------------------------------------------------------
    def _engine(self):
        try:
            return self.engine_getter() if self.engine_getter else None
        except Exception:
            return None

    def refresh(self) -> None:
        eng = self._engine()
        rec = {}
        if eng is not None and getattr(eng, "history", None):
            rec = dict(eng.history[-1])
            prev = eng.history[-2] if len(eng.history) >= 2 else None
            rec["_prev_gdp"] = prev.get("gdp") if prev else None
        warns = []
        if eng is not None and hasattr(eng, "warnings"):
            try:
                warns = list(eng.warnings())
            except Exception:
                warns = []
        self._state = rec
        self._warnings = warns
        self._strengths = self._compute_strengths()
        self._fill_side()
        self._redraw()

    def _v(self, key, default=None):
        return _num(self._state.get(key, default)) if self._state else None

    def _compute_strengths(self) -> dict[str, float]:
        """Aktivitaet der Schleifen 0..1 aus history[-1]."""
        s = {k[0]: 0.0 for k in _CLD_LOOPS}
        if not self._state:
            return s
        food = self._v("food_pc")
        goods = self._v("goods_pc")
        env = self._v("environment")
        ratio = self._v("debt_export_ratio")
        net = self._v("net_growth")
        death = self._v("death_rate")
        gdp, pgdp = self._v("gdp"), _num(self._state.get("_prev_gdp"))
        if net is not None:
            s["R1"] = _clamp(net / 20.0, 0.0, 1.0)
        if death is not None:
            s["B1"] = _clamp((death - 10.0) / 25.0, 0.0, 1.0)
        if goods is not None:
            s["R2"] = _clamp((2.5 - goods) / 1.5, 0.0, 1.0) * (1.0 if (net or 0) > 0 else 0.5)
        if food is not None:
            s["B2"] = _clamp((2.0 - food) / 0.6, 0.0, 1.0) if food < 2.0 else 0.0
        if gdp is not None and pgdp:
            s["R3"] = _clamp((gdp - pgdp) / max(1.0, pgdp) * 5.0, 0.0, 1.0)
        if env is not None:
            s["B3"] = _clamp((0.6 - env) / 0.3, 0.0, 1.0) if env < 0.6 else 0.0
        if ratio is not None:
            s["R4"] = _clamp((ratio - 2.0) / 1.5, 0.0, 1.0) if ratio > 2.0 else 0.0
        return s

    def _node_value(self, key) -> tuple[str, str]:
        """(Wert-Text, Status 'ok'|'warn'|'bad'|'none')."""
        if not self._state:
            return "–", "none"
        v = self._v
        st = "ok"
        if key == "pop":
            n = v("net_growth")
            st = "warn" if (n is not None and n < 0) else "ok"
            return f"{_smart(v('population'))}  ({(n or 0):+.1f} ‰)", st
        if key == "food":
            f = v("food_pc") or 0.0
            st = "bad" if f < 1.8 else ("warn" if f < 2.0 else "ok")
            return f"{f:.2f} NW", st
        if key == "goods":
            g = v("goods_pc") or 0.0
            st = "warn" if g < 1.5 else "ok"
            return f"{g:.2f} GW", st
        if key == "birth":
            return f"{_smart(v('birth_rate'))} ‰/Jahr", "ok"
        if key == "death":
            d = v("death_rate") or 0.0
            st = "bad" if d > 25 else ("warn" if d > 16 else "ok")
            return f"{_smart(d)} ‰/Jahr", st
        if key == "env":
            e = v("environment") or 0.0
            st = "bad" if e < 0.4 else ("warn" if e < 0.6 else "ok")
            return f"{e * 100:.0f} %", st
        if key == "capf":
            return f"{_smart(v('cap_food'))}", "ok"
        if key == "capg":
            return f"{_smart(v('cap_goods'))}", "ok"
        if key == "energy":
            fcu, gcu = v("food_cu"), v("goods_cu")
            low = min(x for x in (fcu, gcu, 1.0) if x is not None)
            st = "bad" if low < 0.8 else ("warn" if low < 0.97 else "ok")
            return f"{_smart(v('energy_available'))} EW · {low * 100:.0f} %", st
        if key == "hs":
            return f"{_smart(v('human_pc'))} /Kopf", "ok"
        if key == "debt":
            r = v("debt_export_ratio") or 0.0
            st = "bad" if r > 3 else ("warn" if r > 2 else "ok")
            return f"{_smart(v('debt'))} GE · {r:.1f}×", st
        if key == "impp":
            m = v("import_mult") or 1.0
            st = "warn" if m > 1.0001 else "ok"
            return f"×{m:.2f} · Zins {_smart(v('annual_interest'))} %", st
        if key == "exp":
            e = v("export_money")
            if not e:
                e = v("avg_exports")
            return f"{_smart(e)} GE", "ok"
        return "–", "none"

    # -- Seitenpanel ---------------------------------------------------------
    def _fill_side(self):
        c = THEME
        for wdg in self._loop_frame.winfo_children():
            wdg.destroy()
        for lid, name, typ, _x, _y, _edges, text in _CLD_LOOPS:
            s = self._strengths.get(lid, 0.0)
            col = c["orange"] if typ == "R" else c["cyan"]
            row = tk.Frame(self._loop_frame, bg=c["panel"], cursor="hand2")
            row.pack(fill="x", pady=1)
            badge = tk.Label(row, text=lid, bg=blend(col, c["panel"], 0.75 - 0.55 * s),
                             fg=c["white"] if s > 0.3 else col, font=(FONT_UI, 8, "bold"), width=3)
            badge.pack(side="left")
            level = "stark" if s > 0.66 else ("mittel" if s > 0.33 else ("schwach" if s > 0.05 else "ruhig"))
            tk.Label(row, text=name, bg=c["panel"], fg=c["text"], font=(FONT_UI, 9),
                     anchor="w").pack(side="left", padx=(6, 0))
            tk.Label(row, text=level, bg=c["panel"],
                     fg=(c["red"] if s > 0.66 else (col if s > 0.05 else c["muted"])),
                     font=(FONT_UI, 8), anchor="e").pack(side="right")
            for wdg in (row, badge) + tuple(row.winfo_children()):
                wdg.bind("<Button-1>", lambda e, l=lid: self._select_loop(l), add="+")
        if self._warnings:
            self._warn_lbl.configure(text="\n".join("• " + w for w in self._warnings), fg=c["orange"])
        else:
            self._warn_lbl.configure(text="Keine Warnungen – das System ist im Gleichgewicht.",
                                     fg=c["green"])
        self._show_info(self._selected)

    def _show_info(self, key: str | None):
        c = THEME
        if key and key.startswith("loop:"):
            lid = key[5:]
            for l_id, name, typ, _x, _y, edges, text in _CLD_LOOPS:
                if l_id == lid:
                    s = self._strengths.get(lid, 0.0)
                    kind = "verstärkend (R)" if typ == "R" else "ausgleichend (B)"
                    self._info_title.configure(text=f"{lid} · {name}")
                    self._info_value.configure(text=f"{kind} · Aktivität {s * 100:.0f} %",
                                               fg=c["orange"] if typ == "R" else c["cyan"])
                    self._info_text.configure(text=text)
                    return
        if key and key in _CLD_NODES:
            name, _x, _y, lever, text = _CLD_NODES[key]
            val, st = self._node_value(key)
            col = {"ok": c["green"], "warn": c["orange"], "bad": c["red"]}.get(st, c["muted"])
            ins = [f"{_CLD_NODES[a][0]} ({p})" for a, b, p, _k, _t in _CLD_EDGES if b == key and a != key]
            outs = [f"{_CLD_NODES[b][0]} ({p})" for a, b, p, _k, _t in _CLD_EDGES if a == key and b != key]
            extra = ""
            if ins:
                extra += "\n\nBeeinflusst von: " + ", ".join(ins)
            if outs:
                extra += "\nWirkt auf: " + ", ".join(outs)
            if lever:
                extra += "\n\n◆ Direkt über Investitionen bzw. Entscheidungen steuerbar."
            self._info_title.configure(text=name)
            self._info_value.configure(text="Aktuell: " + val, fg=col)
            self._info_text.configure(text=text + extra)
            return
        self._info_title.configure(text="Wirkungsgefüge")
        self._info_value.configure(text="Knoten anklicken für Details", fg=c["cyan"])
        self._info_text.configure(
            text="Pfeile zeigen Ursache → Wirkung. „+“: beide Größen bewegen sich gleichgerichtet, "
                 "„−“: entgegengesetzt. Schleifen mit R verstärken Veränderungen, Schleifen mit B "
                 "gleichen sie aus. Hervorgehoben ist, was in deinem Land gerade dominiert.")

    def _select_loop(self, lid):
        self._selected = "loop:" + lid
        self._show_info(self._selected)
        self._redraw()

    # -- Interaktion ----------------------------------------------------------
    def _on_click_bg(self, event):
        hit = self.canvas.find_overlapping(event.x - 1, event.y - 1, event.x + 1, event.y + 1)
        for item in hit:
            for t in self.canvas.gettags(item):
                if t.startswith("node:") or t.startswith("loop:"):
                    return
        self._selected = None
        self._show_info(None)
        self._redraw()

    def _bind_item(self, tag, key):
        cv = self.canvas
        cv.tag_bind(tag, "<Enter>", lambda e: self._set_hover(key))
        cv.tag_bind(tag, "<Leave>", lambda e: self._set_hover(None))
        cv.tag_bind(tag, "<Button-1>", lambda e: self._click(key))

    def _set_hover(self, key):
        if key == self._hover:
            return
        self._hover = key
        self.canvas.configure(cursor="hand2" if key else "")
        self._show_info(key or self._selected)
        self._redraw()

    def _click(self, key):
        self._selected = None if self._selected == key else key
        self._show_info(self._selected or self._hover)
        self._redraw()

    def _schedule(self, _e=None):
        if self._after is not None:
            try:
                self.after_cancel(self._after)
            except tk.TclError:
                pass
        self._after = self.after(30, self._redraw)

    def destroy(self):
        if self._after is not None:
            try:
                self.after_cancel(self._after)
            except tk.TclError:
                pass
        super().destroy()

    # -- Zeichnen ---------------------------------------------------------------
    def _edge_style(self, a, b):
        """(Breite, Farbe, aktiv) einer Kante."""
        c = THEME
        best, col = 0.0, None
        for lid, _n, typ, _x, _y, edges, _t in _CLD_LOOPS:
            if (a, b) in edges:
                s = self._strengths.get(lid, 0.0)
                if s > best:
                    best, col = s, (c["orange"] if typ == "R" else c["cyan"])
        if (a in ("energy",) and b in ("food", "goods")) and self._state:
            fcu = self._v("food_cu") if b == "food" else self._v("goods_cu")
            if fcu is not None and fcu < 0.97:
                sh = _clamp((1.0 - fcu) / 0.3, 0.3, 1.0)
                if sh > best:
                    best, col = sh, c["red"]
        if (a, b) == ("impp", "energy") and (self._v("import_mult") or 1.0) > 1.0001:
            best, col = max(best, 0.5), col or c["orange"]
        if best > 0.75 and col not in (None, c["red"]):
            col = blend(col, c["white"], 0.2)
        return best, col

    def _redraw(self):
        self._after = None
        cv = self.canvas
        cv.delete("all")
        c = THEME
        w = max(cv.winfo_width(), int(float(cv.cget("width"))) if cv.winfo_width() <= 1 else 0, 300)
        h = max(cv.winfo_height(), int(float(cv.cget("height"))) if cv.winfo_height() <= 1 else 0, 260)
        panel = c["panel"]
        compact = w < 640
        f_node = self._f_node_s if compact else self._f_node
        legend_h = 30
        mx, my_top, my_bot = 70 if not compact else 50, 34, 30 + legend_h

        def pos(fx, fy):
            return mx + fx * (w - 2 * mx), my_top + fy * (h - my_top - my_bot)

        focus = self._hover or self._selected
        focus_loop = None
        focus_node = None
        if focus and focus.startswith("loop:"):
            focus_loop = focus[5:]
        elif focus:
            focus_node = focus
        loop_edges = set()
        if focus_loop:
            for lid, _n, _t, _x, _y, edges, _tx in _CLD_LOOPS:
                if lid == focus_loop:
                    loop_edges = set(edges)

        # Knotengroessen
        rects = {}
        for key, (name, fx, fy, lever, _t) in _CLD_NODES.items():
            x, y = pos(fx, fy)
            val, _st = self._node_value(key)
            tw = max(f_node.measure(name) + 44, self._f_val.measure(val) + 24)
            hh = 21 if compact else 23
            rects[key] = (x - tw / 2, y - hh, x + tw / 2, y + hh)
        self._node_rects = rects

        def inside(pt, r, pad):
            return r[0] - pad <= pt[0] <= r[2] + pad and r[1] - pad <= pt[1] <= r[3] + pad

        # Kanten
        for a, b, pol, bend, why in _CLD_EDGES:
            ra, rb = rects[a], rects[b]
            p0 = ((ra[0] + ra[2]) / 2, (ra[1] + ra[3]) / 2)
            p1 = ((rb[0] + rb[2]) / 2, (rb[1] + rb[3]) / 2)
            dx, dy = p1[0] - p0[0], p1[1] - p0[1]
            dist = math.hypot(dx, dy) or 1.0
            ctrl = ((p0[0] + p1[0]) / 2 - dy / dist * bend * dist,
                    (p0[1] + p1[1]) / 2 + dx / dist * bend * dist)
            pts = [_bezier(p0, ctrl, p1, i / 48) for i in range(49)]
            i0 = next((i for i, p in enumerate(pts) if not inside(p, ra, 4)), 0)
            i1 = next((i for i in range(48, -1, -1) if not inside(pts[i], rb, 6)), 48)
            seg = pts[i0:i1 + 1]
            if len(seg) < 2:
                continue
            s, col = self._edge_style(a, b)
            dim = False
            if focus_node and focus_node not in (a, b):
                dim = True
            if focus_loop and (a, b) not in loop_edges:
                dim = True
            if focus_loop and (a, b) in loop_edges:
                s = max(s, 0.6)
                col = col or (c["orange"] if focus_loop.startswith("R") else c["cyan"])
            base = blend(c["muted"], panel, 0.45)
            if col and s > 0.05:
                color = blend(base, col, 0.35 + 0.65 * s)
                width = 1.6 + 3.0 * s
            else:
                color = base
                width = 1.5
            if focus_node and focus_node in (a, b) and not (col and s > 0.05):
                color = blend(base, c["text"], 0.6)
                width = 2.0
            if dim:
                color = blend(color, panel, 0.72)
            flat = [v for p in seg for v in p]
            tag = f"edge:{a}:{b}"
            cv.create_line(flat, fill=color, width=width, arrow="last", smooth=True,
                           arrowshape=(9 + width, 11 + width, 4 + width / 2), capstyle="round",
                           tags=(tag,))
            # Polaritaet
            mid = seg[len(seg) // 2]
            r = 8
            pcol = c["green"] if pol == "+" else c["red"]
            if dim:
                pcol = blend(pcol, panel, 0.7)
            cv.create_oval(mid[0] - r, mid[1] - r, mid[0] + r, mid[1] + r, fill=panel,
                           outline=blend(pcol, panel, 0.35), width=1.2, tags=(tag,))
            cv.create_text(mid[0], mid[1] - 0.5, text=pol, fill=pcol, font=self._f_pol, tags=(tag,))
            Tooltip_text = f"{_CLD_NODES[a][0]} → {_CLD_NODES[b][0]} ({pol}): {why}"
            cv.tag_bind(tag, "<Enter>", lambda e, t=Tooltip_text: self._edge_hint(t))
            cv.tag_bind(tag, "<Leave>", lambda e: self._edge_hint(None))

        # Selbstschleife Umwelt (Regeneration)
        re_ = rects["env"]
        cx, cy = re_[2] + 2, re_[1] + 4
        s_env, col_env = self._edge_style("env", "env")
        base = blend(c["muted"], panel, 0.45)
        ecol = blend(base, col_env, 0.35 + 0.65 * s_env) if col_env and s_env > 0.05 else base
        if (focus_node and focus_node != "env") or (focus_loop and focus_loop != "B3"):
            ecol = blend(ecol, panel, 0.72)
        R = 16
        arc = [(cx + R * math.cos(math.radians(a)), cy - R * math.sin(math.radians(a)))
               for a in range(200, -110, -12)]
        cv.create_line([v for p in arc for v in p], fill=ecol, width=1.6 + 3 * s_env, smooth=True,
                       arrow="last", arrowshape=(9, 11, 4), tags=("edge:env:env",))
        cv.create_text(cx + R + 12, cy - 8, text="+", fill=c["green"], font=self._f_pol)
        cv.tag_bind("edge:env:env", "<Enter>", lambda e: self._edge_hint(
            "Umwelt → Umwelt (+): Regeneration hängt von der Umweltqualität selbst ab (Abb. 10). "
            "Unter ~50 % schwächt sich die Erholung ab."))
        cv.tag_bind("edge:env:env", "<Leave>", lambda e: self._edge_hint(None))

        # Schleifen-Marker
        for lid, name, typ, fx, fy, _edges, _t in _CLD_LOOPS:
            x, y = pos(fx, fy)
            s = self._strengths.get(lid, 0.0)
            col = c["orange"] if typ == "R" else c["cyan"]
            if s > 0.75:
                col = blend(col, c["white"], 0.2)
            active = s > 0.05 or focus_loop == lid
            tag = f"loop:{lid}"
            rr = 15 if not compact else 13
            dimmed = (focus_loop and focus_loop != lid) or (focus_node is not None)
            ring = col if active else blend(col, panel, 0.5)
            fill = blend(col, panel, 0.78 - 0.5 * s) if active else panel
            if dimmed:
                ring, fill = blend(ring, panel, 0.6), blend(fill, panel, 0.6)
            if s > 0.33 and not dimmed:
                cv.create_oval(x - rr - 5, y - rr - 5, x + rr + 5, y + rr + 5, outline="",
                               fill=blend(col, panel, 0.86), tags=(tag,))
            # kreisfoermiger Pfeil (Umlaufsinn)
            arc = [(x + (rr + 0.5) * math.cos(math.radians(a)), y - (rr + 0.5) * math.sin(math.radians(a)))
                   for a in range(110, 110 - 300, -15)]
            cv.create_oval(x - rr, y - rr, x + rr, y + rr, fill=fill, outline="", tags=(tag,))
            cv.create_line([v for p in arc for v in p], fill=ring, width=2, smooth=True, arrow="last",
                           arrowshape=(6, 7, 3), tags=(tag,))
            cv.create_text(x, y, text=lid, fill=c["white"] if (active and not dimmed) else ring,
                           font=self._f_loop, tags=(tag,))
            self._bind_item(tag, "loop:" + lid)

        # Knoten
        for key, (name, fx, fy, lever, _t) in _CLD_NODES.items():
            x0, y0, x1, y1 = rects[key]
            val, st = self._node_value(key)
            stc = {"ok": c["green"], "warn": c["orange"], "bad": c["red"]}.get(st, c["border"])
            tag = f"node:{key}"
            dim = (focus_node and focus_node != key and not any(
                (a == focus_node and b == key) or (b == focus_node and a == key) for a, b, *_ in _CLD_EDGES))
            if focus_loop:
                dim = not any(key in e for e in loop_edges)
            sel = key in (self._selected, self._hover)
            fill = c["panel2"] if not dim else blend(c["panel2"], panel, 0.6)
            outline = c["blue"] if sel else (blend(stc, c["panel2"], 0.25) if st in ("warn", "bad")
                                             else c["border"])
            if dim:
                outline = blend(outline, panel, 0.6)
            self._round_rect(x0, y0, x1, y1, 9, fill=fill, outline=outline,
                             width=2.2 if (sel or st in ("warn", "bad")) else 1.2, tags=(tag,))
            # Statuspunkt
            cv.create_oval(x0 + 8, y0 + 9, x0 + 14, y0 + 15, fill=stc if not dim else blend(stc, panel, 0.6),
                           outline="", tags=(tag,))
            tcol = c["text"] if not dim else blend(c["text"], panel, 0.6)
            cv.create_text((x0 + x1) / 2, y0 + 12, text=name, fill=tcol, font=f_node, tags=(tag,))
            cv.create_text((x0 + x1) / 2, y1 - 11, text=val,
                           fill=(stc if st in ("warn", "bad") else c["muted"]) if not dim
                           else blend(c["muted"], panel, 0.6), font=self._f_val, tags=(tag,))
            if lever:
                cv.create_text(x1 - 8, y0 + 11, text="◆", fill=blend(c["purple"], panel, 0.1 if not dim else 0.6),
                               font=self._f_val, tags=(tag,))
            self._bind_item(tag, key)

        # Legende
        ly = h - 18
        lx = 14
        items = [("+", c["green"], "gleichgerichtet"), ("−", c["red"], "entgegengerichtet")]
        for sym, col, txt in items:
            cv.create_oval(lx, ly - 8, lx + 16, ly + 8, outline=blend(col, panel, 0.35), fill=panel)
            cv.create_text(lx + 8, ly - 0.5, text=sym, fill=col, font=self._f_pol)
            cv.create_text(lx + 22, ly, text=txt, anchor="w", fill=c["muted"], font=self._f_leg)
            lx += 30 + self._f_leg.measure(txt) + 10
        for lid, col, txt in (("R", c["orange"], "verstärkende Schleife"),
                              ("B", c["cyan"], "ausgleichende Schleife")):
            cv.create_oval(lx, ly - 8, lx + 16, ly + 8, fill=blend(col, panel, 0.5), outline=col)
            cv.create_text(lx + 8, ly, text=lid, fill=c["white"], font=self._f_leg)
            cv.create_text(lx + 22, ly, text=txt, anchor="w", fill=c["muted"], font=self._f_leg)
            lx += 30 + self._f_leg.measure(txt) + 10
        if lx + 260 < w:
            cv.create_line(lx, ly, lx + 22, ly, fill=c["orange"], width=4, arrow="last")
            cv.create_text(lx + 28, ly, text="wirkt gerade stark", anchor="w", fill=c["muted"],
                           font=self._f_leg)
            lx += 40 + self._f_leg.measure("wirkt gerade stark") + 10
            cv.create_text(lx, ly, text="◆ steuerbar", anchor="w", fill=c["purple"], font=self._f_leg)
        cv.create_line(10, h - legend_h - 6, w - 10, h - legend_h - 6, fill=blend(c["border"], panel, 0.3))
        # Hinweiszeile fuer Kanten
        self._hint_id = cv.create_text(14, 16, text="", anchor="w", fill=c["text"], font=self._f_leg)
        if not self._state:
            cv.create_text(w / 2, 16, text="Noch kein Spielzustand – Werte erscheinen nach Spielstart.",
                           fill=c["muted"], font=self._f_leg)

    def _edge_hint(self, text):
        try:
            self.canvas.itemconfigure(self._hint_id, text=text or "")
        except (tk.TclError, AttributeError):
            pass

    def _round_rect(self, x0, y0, x1, y1, r, **kw):
        pts = [x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r, x1, y1 - r, x1, y1, x1 - r, y1,
               x0 + r, y1, x0, y1, x0, y1 - r, x0, y0 + r, x0, y0]
        return self.canvas.create_polygon(pts, smooth=True, **kw)


# --------------------------------------------------------------------------
# CompareView
# --------------------------------------------------------------------------
_COMPARE_METRICS = [
    # key, Anzeigename, Format, Faktor
    ("population", "Bevölkerung", "{:,.1f}", 1.0),
    ("food_pc", "Nahrung/Kopf", "{:.2f}", 1.0),
    ("goods_pc", "Güter/Kopf", "{:.2f}", 1.0),
    ("environment", "Umwelt %", "{:.0f}", 100.0),
    ("debt", "Schulden", "{:,.0f}", 1.0),
    ("gdp", "GDP-Index", "{:.1f}", 1.0),
]


class CompareView(tk.Frame):
    """Vergleich mehrerer Spielverlaeufe (max. 6) in einem Diagramm + Endwert-Tabelle."""

    MAX_RUNS = 6

    def __init__(self, parent, **kw):
        kw.setdefault("bg", THEME["bg"])
        super().__init__(parent, **kw)
        c = THEME
        bg = self["bg"]
        _ttk_styles(self)
        self.runs: list[tuple[str, list[dict]]] = []
        self._metric = tk.StringVar(value=_COMPARE_METRICS[0][1])

        head = _header(self, "Vergleich",
                       "Mehrere Spielstände nebeneinander – wer hat sein Land am besten entwickelt?", bg=bg)
        head.pack(fill="x", padx=16, pady=(14, 8))

        body = tk.Frame(self, bg=bg)
        body.pack(fill="both", expand=True, padx=16, pady=(0, 12))
        left = tk.Frame(body, bg=c["panel"], highlightthickness=1, highlightbackground=c["border"],
                        width=250)
        left.pack(side="left", fill="y", padx=(0, 10))
        left.pack_propagate(False)
        right = tk.Frame(body, bg=bg)
        right.pack(side="left", fill="both", expand=True)

        sec = dict(bg=c["panel"], fg=c["muted"], font=(FONT_UI, 8, "bold"), anchor="w")
        tk.Label(left, text="SPIELSTÄNDE", **sec).pack(fill="x", padx=12, pady=(12, 4))
        self._add_btn = _button(left, "Spielstand hinzufügen…", self._add_from_file, accent=True)
        self._add_btn.pack(fill="x", padx=12)
        self._list = tk.Listbox(left, bg=c["panel2"], fg=c["text"], selectbackground=c["blue"],
                                selectforeground=c["white"], relief="flat", bd=0, highlightthickness=1,
                                highlightbackground=c["border"], highlightcolor=c["blue"],
                                font=(FONT_UI, 10), activestyle="none", height=6, exportselection=False)
        self._list.pack(fill="x", padx=12, pady=(8, 4))
        bt = tk.Frame(left, bg=c["panel"])
        bt.pack(fill="x", padx=12)
        _button(bt, "Entfernen", self._remove_selected).pack(side="left", fill="x", expand=True)
        _button(bt, "Alle entfernen", self._remove_all).pack(side="left", fill="x", expand=True, padx=(6, 0))
        self._count = tk.Label(left, text="", bg=c["panel"], fg=c["muted"], font=(FONT_UI, 8), anchor="w")
        self._count.pack(fill="x", padx=12, pady=(4, 0))

        tk.Frame(left, bg=c["border"], height=1).pack(fill="x", padx=10, pady=10)
        tk.Label(left, text="KENNZAHL", **sec).pack(fill="x", padx=12, pady=(0, 4))
        for _k, label, _f, _m in _COMPARE_METRICS:
            rb = tk.Radiobutton(left, text=label, value=label, variable=self._metric,
                                command=self._render, bg=c["panel"], fg=c["text"],
                                selectcolor=c["panel2"], activebackground=c["panel"],
                                activeforeground=c["white"], font=(FONT_UI, 10), anchor="w",
                                highlightthickness=0, bd=0, indicatoron=True, cursor="hand2")
            rb.pack(fill="x", padx=12, pady=1)

        self._chart = MultiLineChart(right, "Bevölkerung", height=330, bg=c["panel"])
        self._chart.pack(fill="both", expand=True)
        tbl_wrap = tk.Frame(right, bg=c["panel"], highlightthickness=1, highlightbackground=c["border"])
        tbl_wrap.pack(fill="x", pady=(10, 0))
        tk.Label(tbl_wrap, text="ENDWERTE", bg=c["panel"], fg=c["muted"], font=(FONT_UI, 8, "bold"),
                 anchor="w").pack(fill="x", padx=12, pady=(8, 2))
        self._table = tk.Frame(tbl_wrap, bg=c["panel"])
        self._table.pack(fill="x", padx=12, pady=(0, 10))
        self._render()

    # -- API ----------------------------------------------------------------
    def set_runs(self, runs: list[tuple[str, list[dict]]]) -> None:
        self.runs = []
        for name, hist in list(runs or [])[: self.MAX_RUNS]:
            self.runs.append((str(name), list(hist or [])))
        self._render()

    def add_run(self, name: str, history: list[dict]) -> bool:
        """Zusatz: fuegt einen Verlauf hinzu (False, wenn bereits 6 vorhanden)."""
        if len(self.runs) >= self.MAX_RUNS:
            return False
        names = {n for n, _h in self.runs}
        base, i = str(name), 2
        while name in names:
            name = f"{base} ({i})"
            i += 1
        self.runs.append((str(name), list(history or [])))
        self._render()
        return True

    # -- Datei laden ---------------------------------------------------------
    def _add_from_file(self):
        if len(self.runs) >= self.MAX_RUNS:
            messagebox.showinfo("Vergleich", f"Es können höchstens {self.MAX_RUNS} Spielstände "
                                             "verglichen werden.", parent=self)
            return
        path = filedialog.askopenfilename(parent=self, title="Spielstand hinzufügen",
                                          filetypes=[("Equivara-Spielstand", "*.json"),
                                                     ("Alle Dateien", "*.*")])
        if not path:
            return
        try:
            loaded = self.load_file(path)
        except Exception as exc:  # noqa: BLE001 - Nutzer soll Grund sehen
            messagebox.showerror("Vergleich", f"Datei konnte nicht geladen werden:\n{exc}", parent=self)
            return
        skipped = 0
        for name, hist in loaded:
            if not self.add_run(name, hist):
                skipped += 1
        if skipped:
            messagebox.showinfo("Vergleich", f"{skipped} Spieler wurden nicht hinzugefügt "
                                             f"(maximal {self.MAX_RUNS}).", parent=self)

    @staticmethod
    def load_file(path) -> list[tuple[str, list[dict]]]:
        """Liest Einzel-Engine-JSON oder Mehrspieler-JSON {"players":[{"name","engine"}]}."""
        if EquivaraEngine is None:
            raise RuntimeError("equivara_engine nicht verfügbar.")
        text = Path(path).read_text(encoding="utf-8")
        data = json.loads(text)
        stem = Path(path).stem
        if isinstance(data, dict) and isinstance(data.get("players"), list):
            out = []
            for i, p in enumerate(data["players"]):
                eng_json = p.get("engine")
                if isinstance(eng_json, dict):
                    eng_json = json.dumps(eng_json)
                eng = EquivaraEngine.from_json(eng_json)
                out.append((str(p.get("name") or f"{stem} – Spieler {i + 1}"), eng.history))
            if not out:
                raise ValueError("Die Datei enthält keine Spieler.")
            return out
        eng = EquivaraEngine.from_json(text)
        return [(stem, eng.history)]

    def _remove_selected(self):
        sel = list(self._list.curselection())
        if not sel:
            return
        for i in sorted(sel, reverse=True):
            if 0 <= i < len(self.runs):
                del self.runs[i]
        self._render()

    def _remove_all(self):
        self.runs = []
        self._render()

    # -- Darstellung -----------------------------------------------------------
    def _metric_def(self):
        lbl = self._metric.get()
        for m in _COMPARE_METRICS:
            if m[1] == lbl:
                return m
        return _COMPARE_METRICS[0]

    def _render(self):
        c = THEME
        key, label, fmt, factor = self._metric_def()
        self._list.delete(0, "end")
        for i, (name, hist) in enumerate(self.runs):
            n = max(0, len(hist) - 1)
            self._list.insert("end", f"  {name}  ·  {n} Zyklen")
            self._list.itemconfigure(i, foreground=SERIES_COLORS[i % len(SERIES_COLORS)])
        self._count.configure(text=f"{len(self.runs)} von {self.MAX_RUNS} Plätzen belegt")
        self._add_btn.configure(state="normal" if len(self.runs) < self.MAX_RUNS else "disabled")

        years = sorted({_num(r.get("jahr_end")) for _n, h in self.runs for r in h
                        if _num(r.get("jahr_end")) is not None})
        series = []
        for i, (name, hist) in enumerate(self.runs):
            by_year = {}
            for r in hist:
                y, v = _num(r.get("jahr_end")), _num(r.get(key))
                if y is not None and v is not None:
                    by_year[y] = v * factor
            series.append((name, SERIES_COLORS[i % len(SERIES_COLORS)], [by_year.get(y) for y in years]))
        self._chart.title = f"{label} – Verlauf"
        self._chart.fmt = fmt
        self._chart.set_series(years, series)

        for wdg in self._table.winfo_children():
            wdg.destroy()
        if not self.runs:
            tk.Label(self._table, text="Noch keine Spielstände. Füge über „Spielstand hinzufügen…“ "
                                       "gespeicherte Spiele hinzu.", bg=c["panel"], fg=c["muted"],
                     font=(FONT_UI, 10), anchor="w").grid(row=0, column=0, sticky="w", pady=6)
            return
        cols = ["Spieler", "Jahr"] + [m[1] for m in _COMPARE_METRICS]
        for j, t in enumerate(cols):
            bold = t == label
            tk.Label(self._table, text=t, bg=c["panel"], fg=c["text"] if bold else c["muted"],
                     font=(FONT_UI, 9, "bold"), anchor="e" if j else "w").grid(
                row=0, column=j, sticky="ew", padx=6, pady=(0, 4))
            self._table.columnconfigure(j, weight=1 if j else 2)
        # Bester Wert je Kennzahl (hoeher besser ausser Schulden)
        finals = []
        for name, hist in self.runs:
            last = hist[-1] if hist else {}
            finals.append(last)
        best = {}
        for k, _l, _f, fac in _COMPARE_METRICS:
            vals = [_num(f.get(k)) for f in finals]
            vals = [v for v in vals if v is not None]
            if len(vals) >= 2:
                best[k] = min(vals) if k == "debt" else max(vals)
        for i, ((name, hist), last) in enumerate(zip(self.runs, finals), start=1):
            col = SERIES_COLORS[(i - 1) % len(SERIES_COLORS)]
            cell = tk.Frame(self._table, bg=c["panel"])
            cell.grid(row=i, column=0, sticky="w", padx=6, pady=2)
            tk.Frame(cell, bg=col, width=10, height=10).pack(side="left", padx=(0, 6))
            tk.Label(cell, text=name, bg=c["panel"], fg=c["text"], font=(FONT_UI, 10)).pack(side="left")
            tk.Label(self._table, text=str(int(_num(last.get("jahr_end")) or 0)), bg=c["panel"],
                     fg=c["muted"], font=(FONT_UI, 10), anchor="e").grid(row=i, column=1, sticky="ew", padx=6)
            for j, (k, l_, f_, fac) in enumerate(_COMPARE_METRICS, start=2):
                v = _num(last.get(k))
                txt = fmt_value(f_, v * fac) if v is not None else "–"
                is_best = k in best and v is not None and abs(v - best[k]) < 1e-12
                fg = c["green"] if is_best else (c["text"] if l_ == label else c["muted"])
                tk.Label(self._table, text=("★ " if is_best else "") + txt, bg=c["panel"], fg=fg,
                         font=(FONT_UI, 10, "bold" if l_ == label else "normal"), anchor="e").grid(
                    row=i, column=j, sticky="ew", padx=6)


# --------------------------------------------------------------------------
# LeaderboardView
# --------------------------------------------------------------------------
def _scenario_names() -> dict[str, str]:
    sc = getattr(_engine_mod, "SCENARIOS", None) if _engine_mod else None
    out = {}
    if isinstance(sc, dict):
        for k, v in sc.items():
            out[k] = (v.get("name") if isinstance(v, dict) else None) or str(k)
    return out


class LeaderboardView(tk.Frame):
    """Bestenliste aus equivara_store.load_leaderboard() mit Szenario-Filter."""

    COLUMNS = [
        ("rank", "Rang", 54, "center"),
        ("name", "Name", 170, "w"),
        ("scenario", "Szenario", 150, "w"),
        ("events", "Ereignisse", 86, "center"),
        ("score", "Score", 70, "e"),
        ("grade", "Note", 56, "center"),
        ("population", "Bevölkerung", 100, "e"),
        ("environment", "Umwelt %", 84, "e"),
        ("debt", "Schulden", 90, "e"),
        ("date", "Datum", 130, "center"),
    ]
    ALL = "Alle Szenarien"

    def __init__(self, parent, path: Path | str | None = None, **kw):
        kw.setdefault("bg", THEME["bg"])
        super().__init__(parent, **kw)
        c = THEME
        bg = self["bg"]
        _ttk_styles(self)
        self.path = Path(path) if path else None
        self.entries: list[dict] = []
        self._filter = tk.StringVar(value=self.ALL)

        top = tk.Frame(self, bg=bg)
        top.pack(fill="x", padx=16, pady=(14, 8))
        _header(top, "Bestenliste", "Die besten Länder aller bisherigen Spiele.", bg=bg).pack(
            side="left", anchor="w")
        ctl = tk.Frame(top, bg=bg)
        ctl.pack(side="right", anchor="s")
        tk.Label(ctl, text="Szenario:", bg=bg, fg=c["muted"], font=(FONT_UI, 9)).pack(side="left", padx=(0, 6))
        self._combo = ttk.Combobox(ctl, textvariable=self._filter, state="readonly", width=24,
                                   style="Equivara.TCombobox", values=[self.ALL])
        self._combo.pack(side="left")
        self._combo.bind("<<ComboboxSelected>>", lambda e: self._render())
        _button(ctl, "Aktualisieren", self.refresh).pack(side="left", padx=(8, 0))

        self._body = tk.Frame(self, bg=c["panel"], highlightthickness=1, highlightbackground=c["border"])
        self._body.pack(fill="both", expand=True, padx=16, pady=(0, 12))
        vs, _h = _scrollbar_styles(self)
        self._tree = ttk.Treeview(self._body, columns=[k for k, *_ in self.COLUMNS], show="headings",
                                  style="Equivara.Treeview", selectmode="browse")
        for key, title, width, anchor in self.COLUMNS:
            self._tree.heading(key, text=title, anchor=anchor if anchor != "e" else "e")
            self._tree.column(key, width=width, anchor=anchor, stretch=key in ("name", "scenario"))
        self._sb = ttk.Scrollbar(self._body, orient="vertical", command=self._tree.yview, style=vs)
        self._tree.configure(yscrollcommand=self._sb.set)
        self._tree.tag_configure("gold", foreground="#f5c451")
        self._tree.tag_configure("silver", foreground="#c9d3e3")
        self._tree.tag_configure("bronze", foreground="#d99a6c")
        self._tree.tag_configure("odd", background=blend(c["panel"], c["panel2"], 0.6))
        self._empty = tk.Frame(self._body, bg=c["panel"])
        tk.Label(self._empty, text="🏆", bg=c["panel"], fg=c["orange"], font=(FONT_UI, 30)).pack(pady=(40, 4))
        self._empty_title = tk.Label(self._empty, text="Noch keine Einträge", bg=c["panel"], fg=c["text"],
                                     font=(FONT_UI, 13, "bold"))
        self._empty_title.pack()
        self._empty_text = tk.Label(self._empty, text="Spiele ein Land über alle 12 Zyklen – am Ende "
                                                      "kannst du dich hier verewigen.",
                                    bg=c["panel"], fg=c["muted"], font=(FONT_UI, 10))
        self._empty_text.pack(pady=(4, 40))
        self.refresh()

    def refresh(self) -> None:
        self._store_ok = True
        try:
            import equivara_store  # noqa: WPS433 - optional
        except Exception:
            equivara_store = None
            self._store_ok = False
        entries = []
        if equivara_store is not None and hasattr(equivara_store, "load_leaderboard"):
            try:
                entries = list(equivara_store.load_leaderboard(self.path) if self.path
                               else equivara_store.load_leaderboard())
            except Exception:
                entries = []
        elif equivara_store is not None:
            self._store_ok = False
        self.entries = sorted([e for e in entries if isinstance(e, dict)],
                              key=lambda e: -(_num(e.get("score")) or 0.0))
        names = _scenario_names()
        present = []
        for e in self.entries:
            sc = str(e.get("scenario") or "standard")
            if sc not in present:
                present.append(sc)
        ordered = [k for k in names if k in present] + [k for k in present if k not in names]
        self._sc_map = {names.get(k, k): k for k in ordered}
        values = [self.ALL] + list(self._sc_map)
        self._combo.configure(values=values)
        if self._filter.get() not in values:
            self._filter.set(self.ALL)
        self._render()

    @staticmethod
    def _fmt_date(s) -> str:
        if not s:
            return "–"
        try:
            return datetime.fromisoformat(str(s)).strftime("%d.%m.%Y %H:%M")
        except ValueError:
            return str(s)[:16]

    def _render(self):
        self._tree.delete(*self._tree.get_children())
        f = self._filter.get()
        sc_key = self._sc_map.get(f) if f != self.ALL else None
        rows = [e for e in self.entries if sc_key is None or str(e.get("scenario") or "standard") == sc_key]
        names = _scenario_names()
        if not rows:
            self._tree.pack_forget()
            self._sb.pack_forget()
            if not self._store_ok:
                self._empty_title.configure(text="Bestenliste noch nicht verfügbar")
                self._empty_text.configure(text="Das Speichermodul (equivara_store) fehlt.")
            elif self.entries:
                self._empty_title.configure(text="Keine Einträge für dieses Szenario")
                self._empty_text.configure(text="Wähle ein anderes Szenario oder spiele dieses als Erste/r!")
            else:
                self._empty_title.configure(text="Noch keine Einträge")
                self._empty_text.configure(text="Spiele ein Land über alle 12 Zyklen – am Ende kannst du "
                                                "dich hier verewigen.")
            self._empty.pack(fill="both", expand=True)
            return
        self._empty.pack_forget()
        self._sb.pack(side="right", fill="y")
        self._tree.pack(side="left", fill="both", expand=True)
        for i, e in enumerate(rows, start=1):
            env = _num(e.get("environment"))
            if env is not None and env <= 1.0:
                env *= 100.0
            medal = {1: "🥇 1", 2: "🥈 2", 3: "🥉 3"}.get(i, str(i))
            vals = [
                medal,
                str(e.get("name") or "–"),
                names.get(str(e.get("scenario") or "standard"), str(e.get("scenario") or "standard")),
                "an" if e.get("events") else "aus",
                fmt_value("{:.1f}", _num(e.get("score"))),
                str(e.get("grade") or "–"),
                fmt_value("{:,.1f}", _num(e.get("population"))),
                fmt_value("{:.0f}", env),
                fmt_value("{:,.0f}", _num(e.get("debt"))),
                self._fmt_date(e.get("date")),
            ]
            tags = []
            if i <= 3:
                tags.append(("gold", "silver", "bronze")[i - 1])
            if i % 2 == 0:
                tags.append("odd")
            self._tree.insert("", "end", values=vals, tags=tags)


# --------------------------------------------------------------------------
# Tutorial
# --------------------------------------------------------------------------
class Tutorial:
    """Gefuehrte Tour: Sprechblase neben einem Ziel-Widget mit Rahmen-Hervorhebung.

    step = {"title", "text", "target": Callable[[], tk.Widget | None], "before": Callable | None}
    on_finish wird aufgerufen, wenn die Tour beendet (Fertig) oder uebersprungen wird.
    """

    BUBBLE_W = 330
    BORDER = 3

    def __init__(self, root, steps: list[dict], on_finish: Callable[[], None] | None = None):
        self.root = root
        self.steps = list(steps or [])
        self.on_finish = on_finish
        self.index = 0
        self._bubble: tk.Toplevel | None = None
        self._frames: list[tk.Toplevel] = []
        self._after = None
        self._bind_id = None
        self.active = False

    # -- API ---------------------------------------------------------------
    def start(self) -> None:
        if not self.steps:
            self._finish()
            return
        self.active = True
        self.index = 0
        try:
            self._bind_id = self.root.bind("<Configure>", lambda e: self._schedule_place(), add="+")
        except tk.TclError:
            self._bind_id = None
        self._show()

    def close(self) -> None:
        """Schliesst die Tour ohne on_finish aufzurufen."""
        self.active = False
        if self._after is not None:
            try:
                self.root.after_cancel(self._after)
            except tk.TclError:
                pass
            self._after = None
        if self._bind_id is not None:
            try:
                self.root.unbind("<Configure>", self._bind_id)
            except tk.TclError:
                pass
            self._bind_id = None
        for t in self._frames:
            try:
                t.destroy()
            except tk.TclError:
                pass
        self._frames = []
        if self._bubble is not None:
            try:
                self._bubble.destroy()
            except tk.TclError:
                pass
            self._bubble = None

    def next(self):
        if self.index >= len(self.steps) - 1:
            self._finish()
        else:
            self.index += 1
            self._show()

    def back(self):
        if self.index > 0:
            self.index -= 1
            self._show()

    def skip(self):
        self._finish()

    # -- intern --------------------------------------------------------------
    def _finish(self):
        self.close()
        if self.on_finish:
            try:
                self.on_finish()
            except Exception:
                pass

    def _target(self):
        step = self.steps[self.index]
        fn = step.get("target")
        try:
            w = fn() if callable(fn) else fn
            if w is not None and w.winfo_exists() and w.winfo_ismapped():
                return w
        except Exception:
            pass
        return None

    def _show(self):
        step = self.steps[self.index]
        before = step.get("before")
        if callable(before):
            try:
                before()
            except Exception:
                pass
        self._build_bubble(step)
        try:
            self.root.update_idletasks()
        except tk.TclError:
            return
        self._place()
        # Windows uebernimmt die Position eines frisch erzeugten overrideredirect-Fensters
        # erst nach dem ersten Mapping zuverlaessig -> kurz darauf erneut positionieren.
        self._schedule_place()

    def _build_bubble(self, step):
        c = THEME
        if self._bubble is None:
            b = tk.Toplevel(self.root)
            b.wm_overrideredirect(True)
            try:
                b.transient(self.root)
                b.attributes("-topmost", True)
            except tk.TclError:
                pass
            b.configure(bg=c["blue"])
            b.bind("<Escape>", lambda e: self.skip())
            b.bind("<Right>", lambda e: self.next())
            b.bind("<Return>", lambda e: self.next())
            b.bind("<Left>", lambda e: self.back())
            self._bubble = b
            self._frames = []
            for _ in range(4):
                fr = tk.Toplevel(self.root)
                fr.wm_overrideredirect(True)
                try:
                    fr.transient(self.root)
                    fr.attributes("-topmost", True)
                except tk.TclError:
                    pass
                fr.configure(bg=c["orange"])
                self._frames.append(fr)
        b = self._bubble
        for wdg in b.winfo_children():
            wdg.destroy()
        inner = tk.Frame(b, bg=c["panel2"])
        inner.pack(padx=2, pady=2, fill="both")
        top = tk.Frame(inner, bg=c["panel2"])
        top.pack(fill="x", padx=16, pady=(12, 0))
        tk.Label(top, text=f"Schritt {self.index + 1} von {len(self.steps)}", bg=c["panel2"],
                 fg=c["cyan"], font=(FONT_UI, 8, "bold")).pack(side="left")
        dots = tk.Frame(top, bg=c["panel2"])
        dots.pack(side="right")
        for i in range(len(self.steps)):
            tk.Frame(dots, bg=c["blue"] if i == self.index else c["border"], width=7, height=7).pack(
                side="left", padx=2)
        tk.Label(inner, text=str(step.get("title", "")), bg=c["panel2"], fg=c["text"],
                 font=(FONT_UI, 12, "bold"), anchor="w", justify="left",
                 wraplength=self.BUBBLE_W - 32).pack(fill="x", padx=16, pady=(6, 2))
        tk.Label(inner, text=str(step.get("text", "")), bg=c["panel2"], fg=c["muted"],
                 font=(FONT_UI, 10), anchor="w", justify="left",
                 wraplength=self.BUBBLE_W - 32).pack(fill="x", padx=16, pady=(0, 12))
        btns = tk.Frame(inner, bg=c["panel2"])
        btns.pack(fill="x", padx=12, pady=(0, 12))
        skip = tk.Label(btns, text="Überspringen", bg=c["panel2"], fg=c["muted"], font=(FONT_UI, 9, "underline"),
                        cursor="hand2")
        skip.pack(side="left", padx=4)
        skip.bind("<Button-1>", lambda e: self.skip())
        last = self.index >= len(self.steps) - 1
        _button(btns, "Fertig" if last else "Weiter →", self.next, accent=True).pack(side="right")
        back = _button(btns, "← Zurück", self.back)
        back.pack(side="right", padx=(0, 6))
        if self.index == 0:
            back.configure(state="disabled")
        try:
            b.focus_force()
        except tk.TclError:
            pass

    def _schedule_place(self):
        if not self.active:
            return
        if self._after is not None:
            try:
                self.root.after_cancel(self._after)
            except tk.TclError:
                pass
        self._after = self.root.after(50, self._place)

    def _place(self):
        self._after = None
        if not self.active or self._bubble is None:
            return
        try:
            self._place_inner()
        except tk.TclError:
            pass

    def _place_inner(self):
        b = self._bubble
        b.update_idletasks()
        bw, bh = max(self.BUBBLE_W, b.winfo_reqwidth()), b.winfo_reqheight()
        sw, sh = b.winfo_screenwidth(), b.winfo_screenheight()
        tgt = self._target()
        bd = self.BORDER
        if tgt is None:
            for fr in self._frames:
                fr.withdraw()
            rx, ry = self.root.winfo_rootx(), self.root.winfo_rooty()
            rw, rh = self.root.winfo_width(), self.root.winfo_height()
            x, y = rx + (rw - bw) // 2, ry + (rh - bh) // 2
        else:
            tx, ty = tgt.winfo_rootx(), tgt.winfo_rooty()
            tw, th = tgt.winfo_width(), tgt.winfo_height()
            geo = [(tx - bd - 2, ty - bd - 2, tw + 2 * bd + 4, bd),
                   (tx - bd - 2, ty + th + 2, tw + 2 * bd + 4, bd),
                   (tx - bd - 2, ty - 2, bd, th + 4),
                   (tx + tw + 2, ty - 2, bd, th + 4)]
            for fr, (gx, gy, gw, gh) in zip(self._frames, geo):
                fr.deiconify()
                fr.wm_geometry(f"{max(1, gw)}x{max(1, gh)}+{gx}+{gy}")
                fr.lift()
            gap = 14
            if tx + tw + gap + bw <= sw - 8:
                x, y = tx + tw + gap, ty
            elif tx - gap - bw >= 8:
                x, y = tx - gap - bw, ty
            elif ty + th + gap + bh <= sh - 8:
                x, y = tx, ty + th + gap
            else:
                x, y = tx, ty - gap - bh
            # Wenn das Ziel sehr gross ist, Blase innen oben rechts platzieren
            if tw > sw * 0.6 and th > sh * 0.5:
                x, y = tx + tw - bw - 20, ty + 20
        x = int(max(8, min(x, sw - bw - 8)))
        y = int(max(8, min(y, sh - bh - 8)))
        b.wm_geometry(f"{bw}x{bh}+{x}+{y}")
        b.deiconify()
        b.lift()


# --------------------------------------------------------------------------
# Demo
# --------------------------------------------------------------------------
def _demo_engines(rounds: int = 5):
    """Erzeugt zwei Beispiel-Engines (unterschiedliche Strategien)."""
    if EquivaraEngine is None:
        return []
    out = []
    for name, use_advisor in (("Vorschlag", False), ("Berater", True)):
        eng = EquivaraEngine()
        for _ in range(rounds):
            if eng.game_over:
                break
            if use_advisor and hasattr(eng, "advise_inputs"):
                try:
                    inp, _why = eng.advise_inputs()
                except Exception:
                    inp = eng.suggest_inputs()
            else:
                inp = eng.suggest_inputs()
                if use_advisor:  # ohne Berater: mehr Umwelt-/Human-Investitionen probieren
                    inp = dict(inp)
                    move = min(inp.get("inv_goods", 0.0), 40.0)
                    inp["inv_goods"] = inp.get("inv_goods", 0.0) - move
                    inp["inv_env"] = inp.get("inv_env", 0.0) + move
            try:
                eng.apply(inp)
            except ValueError:
                eng.apply(eng.suggest_inputs())
        out.append((name, eng))
    return out


def _demo(root: tk.Tk, leaderboard_path: Path | None = None) -> dict:
    root.title("Equivara – Ansichten (Demo)")
    root.configure(bg=THEME["bg"])
    root.geometry("1280x800")
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass
    c = THEME
    style.configure("Equivara.TNotebook", background=c["bg"], borderwidth=0)
    style.configure("Equivara.TNotebook.Tab", background=c["panel"], foreground=c["muted"],
                    padding=(14, 6), borderwidth=0, font=(FONT_UI, 10))
    style.map("Equivara.TNotebook.Tab", background=[("selected", c["panel2"])],
              foreground=[("selected", c["text"])])
    engines = _demo_engines(5)
    eng = engines[0][1] if engines else None
    nb = ttk.Notebook(root, style="Equivara.TNotebook")
    nb.pack(fill="both", expand=True)
    curves = CurvesView(nb, lambda: eng)
    loops = CausalLoopView(nb, lambda: eng)
    compare = CompareView(nb)
    compare.set_runs([(n, e.history) for n, e in engines])
    board = LeaderboardView(nb, path=leaderboard_path)
    nb.add(curves, text="Kennlinien")
    nb.add(loops, text="Wirkungsgefüge")
    nb.add(compare, text="Vergleich")
    nb.add(board, text="Bestenliste")
    return {"notebook": nb, "curves": curves, "loops": loops, "compare": compare, "board": board,
            "engines": engines}


if __name__ == "__main__":
    import sys
    import tempfile

    lb_path = None
    try:  # Beispiel-Bestenliste in tmp-Datei (beruehrt nicht die echte Bestenliste)
        import equivara_store

        lb_path = Path(tempfile.mkdtemp(prefix="equivara_demo_")) / "leaderboard.json"
        for i, (nm, sc, sco, gr) in enumerate([("Anna", "standard", 81.5, "B"), ("Ben", "verschuldet", 64.2, "C"),
                                               ("Cem", "standard", 92.0, "A"), ("Dora", "umweltkrise", 48.9, "D")]):
            equivara_store.add_entry({"name": nm, "scenario": sc, "events": i % 2 == 0, "score": sco,
                                       "grade": gr, "population": 240 + 10 * i, "environment": 0.6 - 0.05 * i,
                                       "debt": 800 + 300 * i, "food_pc": 2.1,
                                       "date": datetime.now().isoformat(timespec="seconds")}, lb_path)
    except Exception:
        lb_path = None

    root = tk.Tk()
    parts = _demo(root, lb_path)
    if "--tutorial" in sys.argv:
        nb = parts["notebook"]
        steps = [
            {"title": "Kennlinien", "text": "Hier siehst du alle Tabellenfunktionen des Modells.",
             "target": lambda: parts["curves"], "before": lambda: nb.select(0)},
            {"title": "Wirkungsgefüge", "text": "Klicke auf Knoten, um Zusammenhänge zu verstehen.",
             "target": lambda: parts["loops"].canvas, "before": lambda: nb.select(1)},
            {"title": "Vergleich", "text": "Lade Spielstände und vergleiche sie.",
             "target": lambda: parts["compare"]._add_btn, "before": lambda: nb.select(2)},
        ]
        root.after(400, lambda: Tutorial(root, steps, on_finish=lambda: print("Tutorial fertig")).start())
    root.mainloop()
