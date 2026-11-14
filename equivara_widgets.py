"""
equivara_widgets.py - Canvas-Diagramme und Widgets fuer die Equivara-Oberflaeche.

Nur tkinter / Standardbibliothek, keine Abhaengigkeit zur Engine.

Oeffentliche API (siehe Vertrag, Abschnitt 2):
    THEME, LineChart, MultiLineChart, BudgetBar, StatCard, Tooltip, HistoryTable
Zusaetzliche Hilfsfunktionen: fmt_value, nice_ticks, blend
"""

from __future__ import annotations

import math
import re
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk
from typing import Callable, Sequence

__all__ = [
    "THEME",
    "LineChart",
    "MultiLineChart",
    "BudgetBar",
    "StatCard",
    "Tooltip",
    "HistoryTable",
    "fmt_value",
    "nice_ticks",
    "blend",
]

THEME: dict[str, str] = {
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

FONT_UI = "Segoe UI"
FONT_MONO = "Consolas"


# --------------------------------------------------------------------------
# Hilfsfunktionen
# --------------------------------------------------------------------------
def _hex_to_rgb(c: str) -> tuple[int, int, int]:
    c = c.lstrip("#")
    if len(c) == 3:
        c = "".join(ch * 2 for ch in c)
    return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)


def blend(c1: str, c2: str, t: float) -> str:
    """Mischt Farbe c1 mit c2 (t=0 -> c1, t=1 -> c2). Erwartet #rrggbb."""
    try:
        r1, g1, b1 = _hex_to_rgb(c1)
        r2, g2, b2 = _hex_to_rgb(c2)
    except (ValueError, IndexError):
        return c1
    t = max(0.0, min(1.0, t))
    return "#%02x%02x%02x" % (
        round(r1 + (r2 - r1) * t),
        round(g1 + (g2 - g1) * t),
        round(b1 + (b2 - b1) * t),
    )


def _is_num(v) -> bool:
    if isinstance(v, bool):
        return False
    try:
        return math.isfinite(float(v))
    except (TypeError, ValueError):
        return False


def fmt_value(fmt: str, value) -> str:
    """Formatiert value mit fmt (z.B. "{:,.0f}"); faellt robust auf str() zurueck."""
    if value is None:
        return "–"
    try:
        return fmt.format(value)
    except (ValueError, TypeError, IndexError, KeyError):
        try:
            return fmt.format(float(value))
        except (ValueError, TypeError, IndexError, KeyError):
            return str(value)


def _fmt_signed(fmt: str, d: float) -> str:
    body = fmt_value(fmt, abs(d))
    if body == fmt_value(fmt, 0.0):
        return "±" + body
    return ("+" if d > 0 else "−") + body


def nice_ticks(lo: float, hi: float, max_ticks: int = 5) -> list[float]:
    """Liefert 'schoene' Achsenwerte (1/2/5-Raster), die [lo, hi] einschliessen.

    Robust bei lo == hi, vertauschten Grenzen und nicht-endlichen Werten.
    """
    max_ticks = max(2, int(max_ticks))
    if not (_is_num(lo) and _is_num(hi)):
        return [0.0, 0.5, 1.0]
    lo, hi = float(lo), float(hi)
    if hi < lo:
        lo, hi = hi, lo
    if hi - lo < 1e-12 * max(1.0, abs(lo), abs(hi)):
        d = abs(lo) * 0.1 if lo != 0 else 1.0
        new_lo = lo - d
        if lo >= 0 and new_lo < 0:
            new_lo = 0.0
        lo, hi = new_lo, hi + d
    raw = (hi - lo) / (max_ticks - 1)
    mag = 10.0 ** math.floor(math.log10(raw))
    for m in (0.1, 0.2, 0.5, 1, 2, 5, 10, 20, 50, 100):
        step = m * mag
        start = math.floor(lo / step + 1e-9) * step
        end = math.ceil(hi / step - 1e-9) * step
        n = int(round((end - start) / step)) + 1
        if n <= max_ticks:
            ticks = []
            for i in range(n):
                t = start + i * step
                t = round(t / step) * step
                ticks.append(round(t, 12) + 0.0)
            if len(ticks) < 2:
                ticks.append(ticks[0] + step)
            return ticks
    return [lo, hi]


def _step_decimals(step: float) -> int:
    if step <= 0 or not math.isfinite(step):
        return 0
    d = 0
    while d < 6 and abs(step * 10 ** d - round(step * 10 ** d)) > 1e-6:
        d += 1
    return d


def _tick_label(t: float, step: float) -> str:
    if abs(t) >= 1e6 and step >= 1e5:
        dec = _step_decimals(step / 1e6)
        return f"{t / 1e6:,.{dec}f} Mio"
    dec = _step_decimals(step)
    return f"{t:,.{dec}f}"


def _x_label(x: float) -> str:
    if abs(x - round(x)) < 1e-9:
        return str(int(round(x)))
    return f"{x:g}"


def _clean_pairs(xs: Sequence, ys: Sequence) -> list[tuple[float, float]]:
    out = []
    for x, y in zip(xs or [], ys or []):
        if _is_num(x) and _is_num(y):
            out.append((float(x), float(y)))
    return out


# --------------------------------------------------------------------------
# Basis fuer Diagramme
# --------------------------------------------------------------------------
class _ChartBase(tk.Canvas):
    PAD_L = 12
    PAD_R = 16
    PAD_B = 24

    def __init__(self, parent, title: str, height: int, fmt: str, unit: str = "", **kw):
        kw.setdefault("bg", THEME["panel"])
        kw.setdefault("highlightthickness", 1)
        kw.setdefault("highlightbackground", THEME["border"])
        kw.setdefault("bd", 0)
        kw.setdefault("width", 360)
        super().__init__(parent, height=height, **kw)
        self.title = title
        self.fmt = fmt or "{:,.0f}"
        self.unit = unit or ""
        self._bgc = kw["bg"]
        self._f_title = tkfont.Font(self, family=FONT_UI, size=10, weight="bold")
        self._f_value = tkfont.Font(self, family=FONT_UI, size=12, weight="bold")
        self._f_small = tkfont.Font(self, family=FONT_UI, size=8)
        self._f_small_b = tkfont.Font(self, family=FONT_UI, size=8, weight="bold")
        self._f_axis = tkfont.Font(self, family=FONT_MONO, size=8)
        self._f_tip = tkfont.Font(self, family=FONT_UI, size=9)
        self._f_tip_b = tkfont.Font(self, family=FONT_UI, size=9, weight="bold")
        self._after_id = None
        self._layout = None
        self.bind("<Configure>", self._schedule_redraw, add="+")
        self.bind("<Motion>", self._on_motion, add="+")
        self.bind("<Leave>", lambda e: self.delete("hover"), add="+")

    # -- Lebenszyklus --------------------------------------------------
    def _schedule_redraw(self, _event=None):
        if self._after_id is not None:
            try:
                self.after_cancel(self._after_id)
            except tk.TclError:
                pass
        self._after_id = self.after(40, self._redraw_now)

    def _redraw_now(self):
        self._after_id = None
        try:
            self.redraw()
        except tk.TclError:
            pass

    def destroy(self):
        if self._after_id is not None:
            try:
                self.after_cancel(self._after_id)
            except tk.TclError:
                pass
            self._after_id = None
        super().destroy()

    def _size(self) -> tuple[int, int]:
        w = self.winfo_width()
        h = self.winfo_height()
        if w <= 1:
            w = int(float(self.cget("width")))
        if h <= 1:
            h = int(float(self.cget("height")))
        return max(w, 80), max(h, 60)

    def redraw(self):  # pragma: no cover - in Unterklassen
        raise NotImplementedError

    # -- Achsen --------------------------------------------------------
    def _axes(self, w, h, top, xs_all, ys_all, ymin=None, ymax=None, extra_y=()):
        """Berechnet Skalen, zeichnet Raster + Achsenbeschriftung. Gibt Layout-Dict zurueck."""
        vals = [y for y in list(ys_all) + list(extra_y) if _is_num(y)]
        lo = min(vals) if vals else 0.0
        hi = max(vals) if vals else 1.0
        fixed_lo = ymin is not None and _is_num(ymin)
        fixed_hi = ymax is not None and _is_num(ymax)
        if fixed_lo:
            lo = min(lo, float(ymin))
        if fixed_hi:
            hi = max(hi, float(ymax))

        plot_h_est = max(20, h - top - self.PAD_B)
        max_ticks = max(3, min(5, plot_h_est // 24 + 1))
        ticks = nice_ticks(lo, hi, max_ticks)
        step = ticks[1] - ticks[0] if len(ticks) > 1 else 1.0
        y0 = float(ymin) if fixed_lo and float(ymin) <= min(vals or [float(ymin)]) else ticks[0]
        y1 = float(ymax) if fixed_hi and float(ymax) >= max(vals or [float(ymax)]) else ticks[-1]
        if y1 - y0 <= 0:
            y0, y1 = ticks[0], ticks[-1]
        ticks = [t for t in ticks if y0 - 1e-9 <= t <= y1 + 1e-9]

        labels = [_tick_label(t, step) for t in ticks]
        lab_w = max([self._f_axis.measure(s) for s in labels] or [10])
        left = self.PAD_L + lab_w + 8
        right = w - self.PAD_R
        bottom = h - self.PAD_B
        if right - left < 20:
            right = left + 20
        if bottom - top < 10:
            bottom = top + 10

        xs = sorted(set(x for x in xs_all if _is_num(x)))
        if xs:
            x0, x1 = xs[0], xs[-1]
        else:
            x0, x1 = 0.0, 1.0
        if x1 - x0 <= 0:
            x0, x1 = x0 - 1, x1 + 1
        inner = 10  # Abstand der Punkte vom Rand

        def px(x):
            return left + inner + (x - x0) / (x1 - x0) * (right - left - 2 * inner)

        def py(y):
            return bottom - (y - y0) / (y1 - y0) * (bottom - top)

        grid = blend(THEME["border"], self._bgc, 0.35)
        for t, s in zip(ticks, labels):
            yy = py(t)
            self.create_line(left, yy, right, yy, fill=grid)
            self.create_text(left - 8, yy, text=s, anchor="e", fill=THEME["muted"], font=self._f_axis)
        self.create_line(left, bottom, right, bottom, fill=THEME["border"])

        # X-Achse (Jahre)
        plot_w = right - left
        if xs:
            max_lbl = max(2, int(plot_w // 44))
            if len(xs) <= max_lbl:
                xt = xs
            else:
                cand = nice_ticks(xs[0], xs[-1], max(2, min(8, int(plot_w // 50))))
                xt = [x for x in cand if xs[0] - 1e-9 <= x <= xs[-1] + 1e-9]
            for x in xt:
                xx = px(x)
                self.create_line(xx, bottom, xx, bottom + 3, fill=THEME["border"])
                self.create_text(xx, bottom + 5, text=_x_label(x), anchor="n",
                                 fill=THEME["muted"], font=self._f_axis)

        return {"left": left, "right": right, "top": top, "bottom": bottom,
                "px": px, "py": py, "y0": y0, "y1": y1}

    def _empty(self, w, h, top):
        self.create_text(w / 2, (top + h) / 2, text="Noch keine Daten",
                         fill=THEME["muted"], font=self._f_tip)

    # -- Tooltip im Canvas --------------------------------------------
    def _draw_tip(self, ax, ay, lines):
        """lines: list[(text, color, bold, swatch_color|None)]"""
        pad = 8
        lh = 17
        widths = []
        for text, _c, bold, sw in lines:
            f = self._f_tip_b if bold else self._f_tip
            widths.append(f.measure(text) + (14 if sw else 0))
        bw = max(widths or [40]) + 2 * pad
        bh = len(lines) * lh + 2 * pad - 2
        w, h = self._size()
        x = ax + 12
        if x + bw > w - 4:
            x = ax - 12 - bw
        x = max(4, x)
        y = ay - bh / 2
        y = max(4, min(y, h - bh - 4))
        self.create_rectangle(x, y, x + bw, y + bh, fill=THEME["panel2"],
                              outline=THEME["border"], tags="hover")
        for i, (text, color, bold, sw) in enumerate(lines):
            ty = y + pad + i * lh + lh / 2 - 1
            tx = x + pad
            if sw:
                self.create_rectangle(tx, ty - 4, tx + 8, ty + 4, fill=sw, outline="", tags="hover")
                tx += 14
            self.create_text(tx, ty, text=text, anchor="w", fill=color,
                             font=self._f_tip_b if bold else self._f_tip, tags="hover")

    def _on_motion(self, event):
        self.delete("hover")
        L = self._layout
        if not L or not L.get("hover_xs"):
            return
        if not (L["left"] - 12 <= event.x <= L["right"] + 12 and L["top"] - 20 <= event.y <= L["bottom"] + 6):
            return
        hx = L["hover_xs"]
        best = min(hx, key=lambda x: abs(L["px"](x) - event.x))
        self._draw_hover(best)

    def _draw_hover(self, x):  # pragma: no cover - in Unterklassen
        pass


# --------------------------------------------------------------------------
# LineChart
# --------------------------------------------------------------------------
class LineChart(_ChartBase):
    """Liniendiagramm einer Kennzahl ueber die Jahre mit optionalem Prognosepunkt
    und optionaler Referenzlinie.

    Zusatz (optional, nicht im Vertrag): good_when_up=True/False faerbt das Delta im
    Kopf gruen/rot; Standard None = neutral.
    """

    def __init__(self, parent, title: str, color: str, unit: str = "", fmt: str = "{:,.0f}",
                 ymin: float | None = None, ymax: float | None = None, height: int = 170,
                 good_when_up: bool | None = None, **kw):
        super().__init__(parent, title, height, fmt, unit, **kw)
        self.color = color
        self.ymin = ymin
        self.ymax = ymax
        self.good_when_up = good_when_up
        self._pts: list[tuple[float, float]] = []
        self._preview: tuple[float, float] | None = None
        self._reference: float | None = None
        self.redraw()

    def set_data(self, xs: list[float], ys: list[float],
                 preview: tuple[float, float] | None = None,
                 reference: float | None = None) -> None:
        self._pts = _clean_pairs(xs, ys)
        self._preview = None
        if preview is not None:
            try:
                px_, py_ = preview
                if _is_num(px_) and _is_num(py_):
                    self._preview = (float(px_), float(py_))
            except (TypeError, ValueError):
                self._preview = None
        self._reference = float(reference) if _is_num(reference) else None
        self.redraw()

    def _vtxt(self, v):
        s = fmt_value(self.fmt, v)
        return f"{s} {self.unit}" if self.unit else s

    def redraw(self):
        self.delete("all")
        self._layout = None
        w, h = self._size()
        c = THEME
        pts, prev, ref = self._pts, self._preview, self._reference

        # Kopf
        self.create_text(12, 15, text=self.title, anchor="w", fill=c["text"], font=self._f_title)
        if pts:
            last = pts[-1][1]
            self.create_text(w - 12, 15, text=self._vtxt(last), anchor="e",
                             fill=self.color, font=self._f_value)
            if len(pts) >= 2:
                d = last - pts[-2][1]
                arrow = "▲" if d > 0 else ("▼" if d < 0 else "■")
                if d == 0 or self.good_when_up is None:
                    dc = c["muted"]
                else:
                    dc = c["green"] if (d > 0) == self.good_when_up else c["red"]
                self.create_text(w - 12, 34, text=f"{arrow} {_fmt_signed(self.fmt, d)}",
                                 anchor="e", fill=dc, font=self._f_small_b)
        if prev is not None:
            self.create_line(12, 34, 26, 34, fill=self.color, width=2, dash=(3, 2))
            self.create_text(31, 34, text=f"Prognose: {self._vtxt(prev[1])}", anchor="w",
                             fill=c["muted"], font=self._f_small)
        elif ref is not None:
            self.create_line(12, 34, 26, 34, fill=c["muted"], dash=(1, 3))
            self.create_text(31, 34, text=f"Referenz: {self._vtxt(ref)}", anchor="w",
                             fill=c["muted"], font=self._f_small)

        top = 52
        if not pts and prev is None:
            self._empty(w, h, top - 10)
            return

        all_x = [p[0] for p in pts] + ([prev[0]] if prev else [])
        all_y = [p[1] for p in pts] + ([prev[1]] if prev else [])
        extra = [ref] if ref is not None else []
        L = self._axes(w, h, top, all_x, all_y, self.ymin, self.ymax, extra)
        px, py = L["px"], L["py"]

        # Referenzlinie (gepunktet)
        if ref is not None and L["y0"] <= ref <= L["y1"]:
            ry = py(ref)
            self.create_line(L["left"], ry, L["right"], ry, fill=blend(c["muted"], self._bgc, 0.15),
                             dash=(1, 3))
            self.create_text(L["left"] + 4, ry - 2, text=fmt_value(self.fmt, ref), anchor="sw",
                             fill=c["muted"], font=self._f_axis)

        coords = [(px(x), py(y)) for x, y in pts]
        # Flaeche unter der Linie (weich, ohne Transparenz)
        if len(coords) >= 2:
            base = L["bottom"]
            poly = [coords[0][0], base]
            for xx, yy in coords:
                poly += [xx, yy]
            poly += [coords[-1][0], base]
            self.create_polygon(poly, fill=blend(self.color, self._bgc, 0.85), outline="")
            flat = [v for xy in coords for v in xy]
            self.create_line(flat, fill=self.color, width=2, capstyle="round", joinstyle="round")

        # Prognose gestrichelt
        if prev is not None:
            pxp, pyp = px(prev[0]), py(prev[1])
            if coords:
                self.create_line(coords[-1][0], coords[-1][1], pxp, pyp, fill=self.color,
                                 width=2, dash=(4, 3))
            self.create_oval(pxp - 4, pyp - 4, pxp + 4, pyp + 4, outline=self.color,
                             width=2, fill=self._bgc)

        n = len(coords)
        for i, (xx, yy) in enumerate(coords):
            r = 4 if i == n - 1 else (2.5 if n <= 30 else 0)
            if r:
                self.create_oval(xx - r, yy - r, xx + r, yy + r, fill=self.color,
                                 outline=self._bgc, width=1)

        L["hover_xs"] = sorted(set(all_x))
        self._layout = L

    def _draw_hover(self, x):
        L = self._layout
        px, py = L["px"], L["py"]
        xx = px(x)
        self.create_line(xx, L["top"], xx, L["bottom"], fill=blend(THEME["muted"], self._bgc, 0.4),
                         tags="hover")
        lines = [(f"Jahr {_x_label(x)}", THEME["muted"], False, None)]
        yy = None
        for x_, y_ in self._pts:
            if x_ == x:
                yy = py(y_)
                lines.append((self._vtxt(y_), THEME["text"], True, None))
                self.create_oval(xx - 5, yy - 5, xx + 5, yy + 5, outline=self.color, width=2,
                                 fill=self._bgc, tags="hover")
        if self._preview is not None and self._preview[0] == x:
            pyy = py(self._preview[1])
            yy = pyy if yy is None else yy
            lines.append((f"Prognose: {self._vtxt(self._preview[1])}", self.color, False, None))
            self.create_oval(xx - 5, pyy - 5, xx + 5, pyy + 5, outline=self.color, width=2,
                             fill=self._bgc, tags="hover")
        if len(lines) > 1:
            self._draw_tip(xx, yy if yy is not None else (L["top"] + L["bottom"]) / 2, lines)


# --------------------------------------------------------------------------
# MultiLineChart
# --------------------------------------------------------------------------
class MultiLineChart(_ChartBase):
    """Mehrere Serien auf einer gemeinsamen Achse, mit Legende im Kopf."""

    def __init__(self, parent, title: str, height: int = 220, fmt="{:,.0f}", **kw):
        super().__init__(parent, title, height, fmt, "", **kw)
        self._xs: list[float] = []
        self._series: list[tuple[str, str, list[tuple[float, float]]]] = []
        self.redraw()

    def set_series(self, xs: list[float], series: list[tuple[str, str, list[float]]]) -> None:
        self._xs = [float(x) for x in (xs or []) if _is_num(x)]
        out = []
        for item in series or []:
            try:
                label, color, ys = item
            except (TypeError, ValueError):
                continue
            out.append((str(label), color, _clean_pairs(xs, ys)))
        self._series = out
        self.redraw()

    def redraw(self):
        self.delete("all")
        self._layout = None
        w, h = self._size()
        c = THEME
        self.create_text(12, 15, text=self.title, anchor="w", fill=c["text"], font=self._f_title)

        # Legende (umbrechend)
        lx, ly = 12, 35
        for label, color, _pts in self._series:
            iw = 14 + self._f_small.measure(label) + 14
            if lx + iw > w - 10 and lx > 12:
                lx = 12
                ly += 16
            self.create_rectangle(lx, ly - 4, lx + 9, ly + 4, fill=color, outline="")
            self.create_text(lx + 14, ly, text=label, anchor="w", fill=c["muted"], font=self._f_small)
            lx += iw
        top = ly + 18

        has = any(pts for _l, _c, pts in self._series)
        if not has:
            self._empty(w, h, top - 10)
            return

        all_x = [x for _l, _c, pts in self._series for x, _y in pts]
        all_y = [y for _l, _c, pts in self._series for _x, y in pts]
        L = self._axes(w, h, top, all_x, all_y)
        px, py = L["px"], L["py"]
        for _label, color, pts in self._series:
            coords = [(px(x), py(y)) for x, y in pts]
            if len(coords) >= 2:
                flat = [v for xy in coords for v in xy]
                self.create_line(flat, fill=color, width=2, capstyle="round", joinstyle="round")
            if coords:
                xx, yy = coords[-1]
                self.create_oval(xx - 3.5, yy - 3.5, xx + 3.5, yy + 3.5, fill=color, outline=self._bgc)
        L["hover_xs"] = sorted(set(all_x))
        self._layout = L

    def _draw_hover(self, x):
        L = self._layout
        px, py = L["px"], L["py"]
        xx = px(x)
        self.create_line(xx, L["top"], xx, L["bottom"], fill=blend(THEME["muted"], self._bgc, 0.4),
                         tags="hover")
        lines = [(f"Jahr {_x_label(x)}", THEME["muted"], False, None)]
        ys_px = []
        for label, color, pts in self._series:
            for x_, y_ in pts:
                if x_ == x:
                    yy = py(y_)
                    ys_px.append(yy)
                    self.create_oval(xx - 4, yy - 4, xx + 4, yy + 4, outline=color, width=2,
                                     fill=self._bgc, tags="hover")
                    lines.append((f"{label}: {fmt_value(self.fmt, y_)}", THEME["text"], False, color))
                    break
        if len(lines) > 1:
            ay = sum(ys_px) / len(ys_px) if ys_px else (L["top"] + L["bottom"]) / 2
            self._draw_tip(xx, ay, lines)


# --------------------------------------------------------------------------
# BudgetBar
# --------------------------------------------------------------------------
class BudgetBar(tk.Frame):
    """Kompakte Budgetanzeige (~34 px): 'Label   verplant / verfuegbar   frei: X' + Balken."""

    HEIGHT = 34

    def __init__(self, parent, label: str, color: str, **kw):
        bg = kw.pop("bg", kw.pop("background", THEME["panel"]))
        kw.setdefault("height", self.HEIGHT)
        kw.setdefault("width", 320)
        super().__init__(parent, bg=bg, **kw)
        self.pack_propagate(False)
        self.grid_propagate(False)
        self.label = label
        self.color = color
        self._bgc = bg
        self.available = 0.0
        self.used = 0.0
        self._f_lbl = tkfont.Font(self, family=FONT_UI, size=9, weight="bold")
        self._f_num = tkfont.Font(self, family=FONT_MONO, size=9)
        self._f_free = tkfont.Font(self, family=FONT_UI, size=8, weight="bold")
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0, height=self.HEIGHT)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda e: self._draw(), add="+")
        self._draw()

    def set(self, available: float, used: float) -> None:
        self.available = float(available) if _is_num(available) else 0.0
        self.used = float(used) if _is_num(used) else 0.0
        self._draw()

    @property
    def ratio(self) -> float:
        if self.available <= 0:
            return math.inf if self.used > 0 else 0.0
        return self.used / self.available

    def _draw(self):
        cv = self.canvas
        cv.delete("all")
        c = THEME
        w = cv.winfo_width()
        if w <= 1:
            w = int(float(self.cget("width")))
        a, u = self.available, self.used
        ratio = self.ratio
        free = a - u
        over = ratio > 1.0 + 1e-9

        if over:
            accent = c["red"]
        elif ratio >= 0.95 and a > 0:
            accent = c["green"]
        else:
            accent = self.color

        ty = 9
        cv.create_text(0, ty, text=self.label, anchor="w", fill=c["text"], font=self._f_lbl)
        if over:
            free_txt = f"über: {abs(free):,.0f}"
            free_col = c["red"]
        else:
            free_txt = f"frei: {free:,.0f}"
            free_col = c["green"] if ratio >= 0.95 and a > 0 else c["muted"]
        cv.create_text(w, ty, text=free_txt, anchor="e", fill=free_col, font=self._f_free)
        fw = self._f_free.measure(free_txt)
        nums = f"{u:,.0f} / {a:,.0f}"
        cv.create_text(w - fw - 14, ty, text=nums, anchor="e",
                       fill=c["red"] if over else c["text"], font=self._f_num)

        # Balken
        y0, y1 = 21, 28
        trough = blend(c["bg"], self._bgc, 0.3)
        cv.create_rectangle(0, y0, w, y1, fill=trough, outline=blend(c["border"], self._bgc, 0.3))
        if over:
            frac_ok = (a / u) if (u > 0 and a > 0) else 0.0
            split = w * frac_ok
            if split > 0:
                cv.create_rectangle(0, y0, split, y1, fill=blend(c["red"], self._bgc, 0.45), outline="")
            cv.create_rectangle(split, y0, w, y1, fill=c["red"], outline="")
            if split > 0:
                cv.create_line(split, y0 - 3, split, y1 + 3, fill=c["white"], width=2)
        elif a > 0 and u > 0:
            cv.create_rectangle(0, y0, max(2, w * min(1.0, ratio)), y1, fill=accent, outline="")

    # Bequemlichkeit
    def configure_label(self, label: str):
        self.label = label
        self._draw()


# --------------------------------------------------------------------------
# StatCard
# --------------------------------------------------------------------------
class StatCard(tk.Frame):
    """Kennzahlkarte: Titel, grosser Wert, Delta zum Vorwert, optional Prognose."""

    def __init__(self, parent, title: str, color: str, fmt: str = "{:,.0f}", **kw):
        bg = kw.pop("bg", kw.pop("background", THEME["panel"]))
        kw.setdefault("highlightthickness", 1)
        kw.setdefault("highlightbackground", THEME["border"])
        super().__init__(parent, bg=bg, **kw)
        self.title = title
        self.color = color
        self.fmt = fmt
        self._bgc = bg
        self.lbl_title = tk.Label(self, text=title.upper(), bg=bg, fg=THEME["muted"],
                                  font=(FONT_UI, 8, "bold"), anchor="w")
        self.lbl_title.pack(fill="x", padx=14, pady=(11, 1))
        self.lbl_value = tk.Label(self, text="–", bg=bg, fg=color, font=(FONT_UI, 18, "bold"), anchor="w")
        self.lbl_value.pack(fill="x", padx=14)
        self.lbl_delta = tk.Label(self, text="", bg=bg, fg=THEME["muted"], font=(FONT_UI, 9, "bold"), anchor="w")
        self.lbl_delta.pack(fill="x", padx=14)
        self.lbl_preview = tk.Label(self, text="", bg=bg, fg=THEME["muted"], font=(FONT_UI, 8), anchor="w")
        self.lbl_preview.pack(fill="x", padx=14, pady=(0, 10))

    @staticmethod
    def _delta_parts(fmt, d, good_when_up):
        body = _fmt_signed(fmt, d)
        if body.startswith("±"):
            return f"■ {body}", THEME["muted"]
        arrow = "▲" if d > 0 else "▼"
        good = (d > 0) == bool(good_when_up)
        return f"{arrow} {body}", THEME["green"] if good else THEME["red"]

    def set(self, value: float, previous: float | None = None, preview: float | None = None,
            good_when_up: bool = True):
        self.lbl_value.config(text=fmt_value(self.fmt, value))
        if previous is not None and _is_num(previous) and _is_num(value):
            txt, col = self._delta_parts(self.fmt, float(value) - float(previous), good_when_up)
            self.lbl_delta.config(text=txt, fg=col)
        else:
            self.lbl_delta.config(text="", fg=THEME["muted"])
        if preview is not None and _is_num(preview):
            txt = f"Prognose: {fmt_value(self.fmt, preview)}"
            col = THEME["muted"]
            if _is_num(value):
                dtxt, dcol = self._delta_parts(self.fmt, float(preview) - float(value), good_when_up)
                txt += f"  ({dtxt})"
                col = blend(dcol, THEME["muted"], 0.35)
            self.lbl_preview.config(text=txt, fg=col)
        else:
            self.lbl_preview.config(text="")


# --------------------------------------------------------------------------
# Tooltip
# --------------------------------------------------------------------------
class Tooltip:
    """Hover-Tooltip im dunklen Theme. text darf ein String oder eine Funktion sein."""

    DELAY_MS = 450

    def __init__(self, widget, text: str | Callable[[], str]):
        self.widget = widget
        self.text = text
        self._tip: tk.Toplevel | None = None
        self._after_id = None
        widget.bind("<Enter>", self._on_enter, add="+")
        widget.bind("<Leave>", self._on_leave, add="+")
        widget.bind("<ButtonPress>", self._on_leave, add="+")
        widget.bind("<Destroy>", self._on_leave, add="+")

    def _resolve(self) -> str:
        try:
            t = self.text() if callable(self.text) else self.text
        except Exception:  # Tooltip-Text darf die UI nie crashen
            return ""
        return "" if t is None else str(t)

    def _on_enter(self, _e=None):
        self._cancel()
        try:
            self._after_id = self.widget.after(self.DELAY_MS, self.show)
        except tk.TclError:
            self._after_id = None

    def _on_leave(self, _e=None):
        self._cancel()
        self.hide()

    def _cancel(self):
        if self._after_id is not None:
            try:
                self.widget.after_cancel(self._after_id)
            except tk.TclError:
                pass
            self._after_id = None

    def show(self):
        self._after_id = None
        text = self._resolve()
        if not text:
            return
        self.hide()
        try:
            x = self.widget.winfo_rootx() + 12
            y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
            tip = tk.Toplevel(self.widget)
        except tk.TclError:
            return
        tip.wm_overrideredirect(True)
        try:
            tip.attributes("-topmost", True)
        except tk.TclError:
            pass
        tip.configure(bg=THEME["border"])
        lbl = tk.Label(tip, text=text, justify="left", bg=THEME["panel2"], fg=THEME["text"],
                       font=(FONT_UI, 9), padx=10, pady=6, wraplength=340)
        lbl.pack(padx=1, pady=1)
        tip.update_idletasks()
        sw = tip.winfo_screenwidth()
        sh = tip.winfo_screenheight()
        tw, th = tip.winfo_reqwidth(), tip.winfo_reqheight()
        if x + tw > sw - 4:
            x = max(4, sw - tw - 4)
        if y + th > sh - 4:
            y = max(4, self.widget.winfo_rooty() - th - 6)
        tip.wm_geometry(f"+{x}+{y}")
        self._tip = tip

    def hide(self):
        if self._tip is not None:
            try:
                self._tip.destroy()
            except tk.TclError:
                pass
            self._tip = None


# --------------------------------------------------------------------------
# HistoryTable
# --------------------------------------------------------------------------
def _scrollbar_styles(widget) -> tuple[str, str]:
    """Dunkle ttk-Scrollbar-Stile (wirken im 'clam'-Theme; sonst Standardoptik)."""
    c = THEME
    style = ttk.Style(widget)
    names = ("Equivara.Vertical.TScrollbar", "Equivara.Horizontal.TScrollbar")
    for n in names:
        try:
            style.configure(n, background=c["panel2"], troughcolor=c["bg"], bordercolor=c["bg"],
                            lightcolor=c["panel2"], darkcolor=c["panel2"], arrowcolor=c["muted"],
                            gripcount=0)
            style.map(n, background=[("active", c["border"])])
        except tk.TclError:
            return "Vertical.TScrollbar", "Horizontal.TScrollbar"
    return names


class HistoryTable(tk.Frame):
    """Bericht: Zeilen = Kennzahlen, Spalten = Zyklen. Erste Spalte und Kopfzeile fixiert,
    horizontal (und vertikal) scrollbar. Zellen leicht gruen/rot je nach Veraenderung
    zur Vorspalte."""

    ROW_H = 26
    HEAD_H = 32
    MIN_COL_W = 92

    def __init__(self, parent, rows: list[tuple[str, str, str]], **kw):
        bg = kw.pop("bg", kw.pop("background", THEME["panel"]))
        super().__init__(parent, bg=bg, **kw)
        self.rows = [tuple(r) for r in rows]
        self._bgc = bg
        self._history: list[dict] = []
        self._f_lbl = tkfont.Font(self, family=FONT_UI, size=9)
        self._f_head = tkfont.Font(self, family=FONT_UI, size=9, weight="bold")
        self._f_cell = tkfont.Font(self, family=FONT_MONO, size=9)

        label_w = max([self._f_lbl.measure(r[1]) for r in self.rows] + [self._f_head.measure("Kennzahl")]) + 28
        body_h = max(self.ROW_H, len(self.rows) * self.ROW_H)
        self._label_w = label_w
        mk = dict(bg=bg, highlightthickness=0, bd=0)
        self.corner = tk.Canvas(self, width=label_w, height=self.HEAD_H, **mk)
        self.colhead = tk.Canvas(self, height=self.HEAD_H, width=400, **mk)
        self.rowlab = tk.Canvas(self, width=label_w, height=body_h, **mk)
        self.body = tk.Canvas(self, height=body_h, width=400, **mk)
        vstyle, hstyle = _scrollbar_styles(self)
        self.vsb = ttk.Scrollbar(self, orient="vertical", command=self._yview, style=vstyle)
        self.hsb = ttk.Scrollbar(self, orient="horizontal", command=self._xview, style=hstyle)
        self.body.configure(xscrollcommand=self.hsb.set, yscrollcommand=self.vsb.set,
                            xscrollincrement=24, yscrollincrement=self.ROW_H)
        self.colhead.configure(xscrollincrement=24)
        self.rowlab.configure(yscrollincrement=self.ROW_H)

        self.corner.grid(row=0, column=0, sticky="nsew")
        self.colhead.grid(row=0, column=1, sticky="nsew")
        self.rowlab.grid(row=1, column=0, sticky="nsew")
        self.body.grid(row=1, column=1, sticky="nsew")
        self.vsb.grid(row=1, column=2, sticky="ns")
        self.hsb.grid(row=2, column=1, sticky="ew")
        self.columnconfigure(1, weight=1)
        self.rowconfigure(1, weight=1)

        for cv in (self.body, self.rowlab):
            cv.bind("<MouseWheel>", self._on_wheel_v)
            cv.bind("<Shift-MouseWheel>", self._on_wheel_h)
            cv.bind("<Button-4>", lambda e: self._scroll_v(-1))
            cv.bind("<Button-5>", lambda e: self._scroll_v(1))
        self.colhead.bind("<MouseWheel>", self._on_wheel_h)
        self.colhead.bind("<Button-4>", lambda e: self._scroll_h(-3))
        self.colhead.bind("<Button-5>", lambda e: self._scroll_h(3))
        self._render()

    # -- Scrollen ------------------------------------------------------
    def _xview(self, *args):
        self.body.xview(*args)
        self.colhead.xview(*args)

    def _yview(self, *args):
        self.body.yview(*args)
        self.rowlab.yview(*args)

    def _scroll_v(self, units):
        self._yview("scroll", units, "units")
        return "break"

    def _scroll_h(self, units):
        self._xview("scroll", units, "units")
        return "break"

    def _on_wheel_v(self, e):
        return self._scroll_v(-1 if e.delta > 0 else 1)

    def _on_wheel_h(self, e):
        return self._scroll_h(-3 if e.delta > 0 else 3)

    # -- Daten ---------------------------------------------------------
    def set_history(self, history: list[dict]) -> None:
        self._history = [h for h in (history or []) if isinstance(h, dict)]
        self._render()
        # zur neuesten Spalte scrollen
        self.after_idle(lambda: self._safe(lambda: self._xview("moveto", 1.0)))

    @staticmethod
    def _safe(fn):
        try:
            fn()
        except tk.TclError:
            pass

    def _render(self):
        c = THEME
        bg = self._bgc
        for cv in (self.corner, self.colhead, self.rowlab, self.body):
            cv.delete("all")
        hist = self._history
        nrows = len(self.rows)
        rh, hh = self.ROW_H, self.HEAD_H
        body_h = max(rh, nrows * rh)
        zebra = (bg, blend(bg, c["panel2"], 0.55))
        line_c = blend(c["border"], bg, 0.35)

        # Ecke
        self.corner.create_rectangle(0, 0, self._label_w, hh, fill=c["panel2"], outline="")
        self.corner.create_text(12, hh / 2, text="Kennzahl", anchor="w", fill=c["muted"], font=self._f_head)
        self.corner.create_line(self._label_w - 1, 0, self._label_w - 1, hh, fill=c["border"])
        self.corner.create_line(0, hh - 1, self._label_w, hh - 1, fill=c["border"])

        # Zeilenbeschriftung
        for i, row in enumerate(self.rows):
            y = i * rh
            self.rowlab.create_rectangle(0, y, self._label_w, y + rh, fill=zebra[i % 2], outline="")
            self.rowlab.create_text(12, y + rh / 2, text=row[1], anchor="w", fill=c["text"], font=self._f_lbl)
        self.rowlab.create_line(self._label_w - 1, 0, self._label_w - 1, body_h, fill=c["border"])
        self.rowlab.configure(scrollregion=(0, 0, self._label_w, body_h))

        if not hist:
            self.colhead.create_rectangle(0, 0, 4000, hh, fill=c["panel2"], outline="")
            self.body.create_text(16, min(body_h, 4 * rh) / 2, text="Noch keine Daten", anchor="w",
                                  fill=c["muted"], font=self._f_lbl)
            self.colhead.configure(scrollregion=(0, 0, 1, hh))
            self.body.configure(scrollregion=(0, 0, 1, body_h))
            return

        # Zellentexte vorbereiten + Spaltenbreite messen
        heads = []
        for h in hist:
            je = h.get("jahr_end", h.get("runde", ""))
            heads.append(f"Jahr {_x_label(je) if _is_num(je) else je}")
        cells = []
        col_w = max([self._f_head.measure(s) for s in heads] + [self.MIN_COL_W - 24])
        for key, _label, fmt in self.rows:
            row_cells = []
            for h in hist:
                v = h.get(key)
                txt = "–" if v is None else (fmt_value(fmt, v) if _is_num(v) else str(v))
                row_cells.append((v, txt))
                col_w = max(col_w, self._f_cell.measure(txt))
            cells.append(row_cells)
        col_w = max(self.MIN_COL_W, col_w + 24)
        total_w = col_w * len(hist)

        # Kopfzeile
        last = len(hist) - 1
        for j, s in enumerate(heads):
            x = j * col_w
            fill = blend(c["blue"], c["panel2"], 0.7) if j == last else c["panel2"]
            self.colhead.create_rectangle(x, 0, x + col_w, hh, fill=fill, outline="")
            self.colhead.create_text(x + col_w - 12, hh / 2, text=s, anchor="e",
                                     fill=c["white"] if j == last else c["muted"], font=self._f_head)
            if j:
                self.colhead.create_line(x, 6, x, hh - 6, fill=line_c)
        self.colhead.create_line(0, hh - 1, total_w, hh - 1, fill=c["border"])

        # Zellen
        green, red = c["green"], c["red"]
        for i, row_cells in enumerate(cells):
            y = i * rh
            base = zebra[i % 2]
            prev_v = None
            for j, (v, txt) in enumerate(row_cells):
                x = j * col_w
                fill = base
                fg = c["text"]
                if j > 0 and _is_num(v) and _is_num(prev_v):
                    cur, old = float(v), float(prev_v)
                    diff = cur - old
                    tol = 1e-9 * max(1.0, abs(old))
                    if abs(diff) > tol:
                        rel = abs(diff) / max(abs(old), 1e-9)
                        strength = 0.16 if rel < 0.10 else 0.26
                        fill = blend(base, green if diff > 0 else red, strength)
                if v is None:
                    fg = c["muted"]
                self.body.create_rectangle(x, y, x + col_w, y + rh, fill=fill, outline="")
                self.body.create_text(x + col_w - 12, y + rh / 2, text=txt, anchor="e",
                                      fill=fg, font=self._f_cell)
                if j:
                    self.body.create_line(x, y, x, y + rh, fill=line_c)
                prev_v = v
        self.colhead.configure(scrollregion=(0, 0, total_w, hh))
        self.body.configure(scrollregion=(0, 0, total_w, body_h))


# --------------------------------------------------------------------------
# Demo
# --------------------------------------------------------------------------
def _demo(root: tk.Tk) -> dict:
    """Baut ein Demofenster mit allen Widgets auf und gibt die Widgets zurueck."""
    c = THEME
    root.title("equivara_widgets – Demo")
    root.configure(bg=c["bg"])
    root.geometry("1280x800")

    style = ttk.Style(root)
    if "clam" in style.theme_names():
        style.theme_use("clam")
    style.configure("Vertical.TScrollbar", background=c["panel2"], troughcolor=c["bg"],
                    bordercolor=c["bg"], arrowcolor=c["muted"])
    style.configure("Horizontal.TScrollbar", background=c["panel2"], troughcolor=c["bg"],
                    bordercolor=c["bg"], arrowcolor=c["muted"])

    years = [0, 5, 10, 15, 20, 25, 30]
    pop = [100.0, 108.2, 117.5, 126.0, 133.4, 139.1, 146.9]
    food = [2.10, 2.05, 1.98, 2.02, 1.91, 1.95, 2.08]
    debt = [500, 620, 700, 690, 640, 580, 600]
    env = [80, 78, 74, 71, 70, 69, 70]

    out: dict = {}
    top = tk.Frame(root, bg=c["bg"])
    top.pack(fill="x", padx=16, pady=(16, 8))
    cards = [("Bevölkerung", c["blue"], "{:,.1f}", pop[-1], pop[-2], 151.2, True),
             ("Nahrung/Kopf", c["green"], "{:,.2f}", food[-1], food[-2], 2.01, True),
             ("Schulden", c["red"], "{:,.0f}", debt[-1], debt[-2], 640, False),
             ("Umwelt %", c["cyan"], "{:,.0f}", env[-1], env[-2], None, True)]
    for i, (t, col, f, v, p, pv, g) in enumerate(cards):
        sc = StatCard(top, t, col, fmt=f)
        sc.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 10, 0))
        top.columnconfigure(i, weight=1)
        sc.set(v, p, pv, good_when_up=g)
        Tooltip(sc, f"{t}: aktueller Wert mit Veränderung zum Vorzyklus")
        out.setdefault("cards", []).append(sc)

    mid = tk.Frame(root, bg=c["bg"])
    mid.pack(fill="both", expand=True, padx=16)
    ch1 = LineChart(mid, "Bevölkerung", c["blue"], unit="Mio", fmt="{:,.1f}", good_when_up=True)
    ch1.set_data(years, pop, preview=(35, 151.2))
    ch2 = LineChart(mid, "Nahrung/Kopf", c["green"], fmt="{:,.2f}")
    ch2.set_data(years, food, preview=(35, 2.01), reference=2.0)
    ch3 = LineChart(mid, "Umwelt %", c["cyan"], unit="%", ymin=0, ymax=100)
    ch3.set_data(years, env)
    ch4 = LineChart(mid, "Schulden (1 Punkt)", c["red"])
    ch4.set_data([0], [500], preview=(5, 620))
    ch5 = LineChart(mid, "Konstant", c["orange"])
    ch5.set_data(years, [42] * len(years))
    ch6 = LineChart(mid, "Leer", c["purple"])
    ch6.set_data([], [])
    for i, ch in enumerate((ch1, ch2, ch3, ch4, ch5, ch6)):
        ch.grid(row=i // 3, column=i % 3, sticky="nsew", padx=(0 if i % 3 == 0 else 10, 0), pady=(0, 10))
    for i in range(3):
        mid.columnconfigure(i, weight=1)
    multi = MultiLineChart(mid, "Kapitalstöcke")
    multi.set_series(years, [("Nahrung", c["green"], [100, 110, 118, 125, 131, 140, 150]),
                             ("Güter", c["blue"], [200, 215, 236, 250, 262, 270, 290]),
                             ("Energie", c["orange"], [150, 152, 160, 171, 180, 182, 190]),
                             ("Umwelt", c["cyan"], [80, 85, 90, 95, 98, 100, 104])])
    multi.grid(row=0, column=3, rowspan=2, sticky="nsew", padx=(10, 0), pady=(0, 10))
    mid.columnconfigure(3, weight=1)
    out["charts"] = [ch1, ch2, ch3, ch4, ch5, ch6, multi]

    bottom = tk.Frame(root, bg=c["bg"])
    bottom.pack(fill="both", padx=16, pady=(0, 16))
    bars = tk.Frame(bottom, bg=c["panel"], highlightthickness=1, highlightbackground=c["border"])
    bars.pack(side="left", fill="y", padx=(0, 10))
    out["bars"] = []
    for lbl, col, a, u in (("Nahrung", c["green"], 300, 240), ("Güter", c["blue"], 500, 490),
                           ("Energie", c["orange"], 200, 260), ("Devisen", c["cyan"], 0, 0),
                           ("Investitionen", c["purple"], 120, 60)):
        b = BudgetBar(bars, lbl, col, width=340)
        b.pack(fill="x", padx=12, pady=(6, 0))
        b.set(a, u)
        out["bars"].append(b)

    rows = [("population", "Bevölkerung", "{:,.1f}"), ("food_pc", "Nahrung/Kopf", "{:,.2f}"),
            ("debt", "Schulden", "{:,.0f}"), ("environment", "Umwelt %", "{:,.0f}"),
            ("missing", "Fehlt", "{:,.0f}")]
    table = HistoryTable(bottom, rows)
    table.pack(side="left", fill="both", expand=True)
    hist = [{"runde": i, "jahr_end": y, "population": p, "food_pc": f, "debt": d, "environment": e}
            for i, (y, p, f, d, e) in enumerate(zip(years, pop, food, debt, env))]
    table.set_history(hist)
    out["table"] = table
    return out


if __name__ == "__main__":
    _root = tk.Tk()
    _demo(_root)
    _root.mainloop()
