"""
equivara_map.py - Symbolische Hex-Karten fuer Equivara (tk.Canvas).

Oeffentliche API (Vertrag Runde 3, Abschnitt 3):
    HexCountryMap(parent, engine_getter, height=360, **kw).refresh()
    HexWorldMap(parent, world_getter, height=420, **kw).refresh()

Die Karten sind rein symbolisch: Die Landform ist deterministisch aus engine.seed,
die Feldtypen werden proportional zu Kapitalstoecken / Bevoelkerung verteilt.
Damit sich die Karte zwischen Zyklen stabil entwickelt, wird die Belegung aus der
gesamten engine.history nachgespielt: Felder wachsen vom Rand bestehender Cluster
bzw. schrumpfen am Rand, statt neu gewuerfelt zu werden.

Alle Zugriffe auf Engine/World laufen ueber getattr/hasattr, damit die Karte auch
mit aelteren Engine-Staenden (ohne Ministerien) oder ohne equivara_world funktioniert.
Nur tkinter / Standardbibliothek.
"""

from __future__ import annotations

import math
import random
import tkinter as tk
import tkinter.font as tkfont
from typing import Callable

from equivara_widgets import FONT_UI, THEME, _ChartBase, blend

__all__ = ["HexCountryMap", "HexWorldMap", "FIELD_TYPES"]

SQRT3 = math.sqrt(3.0)

# Nachbarn (axial, pointy-top) passend zu Kante i zwischen Ecke i und i+1
# (Ecke i liegt bei Winkel 60*i - 30 Grad, y nach unten).
_EDGE_NB = [(1, 0), (0, 1), (-1, 1), (-1, 0), (0, -1), (1, -1)]

SEA = "#081325"          # tiefes Meer
SEA_SHALLOW = "#0d1d35"  # Schelf an der Kueste
SEA_LINE = "#0e1a30"
COAST = "#5d7da6"

# --------------------------------------------------------------------------
# Feldtypen
# --------------------------------------------------------------------------
# key -> name, attr (Engine/History-Schluessel), value_label, per_cell (Einheiten je Feld),
#        accent (Symbolfarbe), ministry (Schluessel in engine.ministries oder None)
FIELD_TYPES: dict[str, dict] = {
    "stadt": {"name": "Stadt", "attr": "population", "value_label": "Bevölkerung",
              "per_cell": 30.0, "accent": "#d6e2f5", "fill": "#2a3754", "ministry": None},
    "acker": {"name": "Ackerland", "attr": "cap_food", "value_label": "Nahrungskapital",
              "per_cell": 100.0, "accent": "#e8c468", "fill": "#4a3e1d", "ministry": None},
    "industrie": {"name": "Industrie", "attr": "cap_goods", "value_label": "Güterkapital",
                  "per_cell": 50.0, "accent": "#b39dff", "fill": "#342d55", "ministry": None},
    "kraftwerk": {"name": "Kraftwerk", "attr": "cap_energy_prod", "value_label": "Energiekapital",
                  "per_cell": 120.0, "accent": "#ffcf4d", "fill": "#4d3a14", "ministry": None},
    "effizienz": {"name": "Effizienz/Solar", "attr": "cap_energy_eff", "value_label": "Effizienzkapital",
                  "per_cell": 45.0, "accent": "#3fd6e6", "fill": "#123f4c", "ministry": None},
    "umweltschutz": {"name": "Umweltschutz", "attr": "cap_env", "value_label": "Umweltschutzkapital",
                     "per_cell": 20.0, "accent": "#5fe0a4", "fill": "#123f33", "ministry": None},
    "klinik": {"name": "Klinik", "attr": "cap_health", "value_label": "Gesundheitskapital",
               "per_cell": 40.0, "accent": "#ff7b7b", "fill": "#4a1d26", "ministry": "gesundheit"},
    "schule": {"name": "Schule/Uni", "attr": "cap_education", "value_label": "Bildungskapital",
               "per_cell": 40.0, "accent": "#f28cd2", "fill": "#45203f", "ministry": "bildung"},
    "knoten": {"name": "Verkehrsknoten", "attr": "cap_infrastructure", "value_label": "Infrastrukturkapital",
               "per_cell": 60.0, "accent": "#ff9f43", "fill": "#4a2c14", "ministry": "infrastruktur"},
    "stuetzpunkt": {"name": "Stützpunkt", "attr": "cap_defense", "value_label": "Verteidigungskapital",
                    "per_cell": 40.0, "accent": "#7aa7ff", "fill": "#1c2c52", "ministry": "verteidigung"},
    "natur": {"name": "Natur/Wald", "attr": "environment", "value_label": "Umweltqualität",
              "per_cell": None, "accent": "#4fc27a", "fill": "#173d2a", "ministry": None},
}
# Reihenfolge beim Wachsen (wichtige Kerne zuerst) und in der Legende
_GROW_ORDER = ["stadt", "acker", "industrie", "kraftwerk", "effizienz", "umweltschutz",
               "klinik", "schule", "knoten", "stuetzpunkt"]
_LEGEND_ORDER = _GROW_ORDER + ["natur"]

# Nachbarschafts-Vorlieben beim Wachsen: _AFF[typ][nachbartyp]
_AFF: dict[str, dict[str, float]] = {
    "stadt": {"stadt": 1.0, "acker": 0.3, "industrie": 0.4},
    "acker": {"stadt": 0.9, "natur": 0.3, "umweltschutz": 0.2, "industrie": -0.4, "kraftwerk": -0.6},
    "industrie": {"stadt": 1.4, "kraftwerk": 1.0, "knoten": 0.6, "acker": -0.3},
    "kraftwerk": {"industrie": 1.2, "stadt": 0.2, "acker": -0.5},
    "effizienz": {"industrie": 0.8, "stadt": 0.8, "kraftwerk": 0.6},
    "umweltschutz": {"natur": 1.0, "acker": 0.3, "industrie": -0.8, "kraftwerk": -0.8},
    "klinik": {"stadt": 2.5, "schule": 0.6, "klinik": -1.5},
    "schule": {"stadt": 2.5, "klinik": 0.6, "schule": -1.0},
    "knoten": {"stadt": 1.5, "industrie": 1.0, "knoten": -2.0},
    "stuetzpunkt": {"stadt": 0.3, "stuetzpunkt": 0.4, "acker": -0.3},
}
_SAME_W = {"stadt": 3.5, "acker": 3.0, "industrie": 3.0, "kraftwerk": 2.5, "effizienz": 2.0,
           "umweltschutz": 3.0, "klinik": 0.0, "schule": 0.0, "knoten": 0.0, "stuetzpunkt": 1.5}

FLOW_COLORS = {"food": THEME["orange"], "goods": THEME["purple"], "energy": THEME["cyan"]}
FLOW_NAMES = {"food": "Nahrung", "goods": "Güter", "energy": "Energie"}


def _num(v, default=0.0) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return default
    if math.isnan(f) or math.isinf(f):
        return default
    return f


def _clamp(x, lo, hi):
    return lo if x < lo else hi if x > hi else x


def _fmt(v: float) -> str:
    if abs(v) >= 100:
        return f"{v:,.0f}".replace(",", ".")
    if abs(v) >= 10:
        return f"{v:,.1f}".replace(".", ",")
    return f"{v:,.2f}".replace(".", ",")


# --------------------------------------------------------------------------
# Hex-Geometrie
# --------------------------------------------------------------------------
def hex_center(q: int, r: int, size: float) -> tuple[float, float]:
    return size * SQRT3 * (q + r / 2.0), size * 1.5 * r


def hex_corners(cx: float, cy: float, size: float) -> list[float]:
    pts = []
    for i in range(6):
        a = math.radians(60 * i - 30)
        pts += [cx + size * math.cos(a), cy + size * math.sin(a)]
    return pts


def pixel_to_hex(x: float, y: float, size: float) -> tuple[int, int]:
    q = (SQRT3 / 3.0 * x - y / 3.0) / size
    r = (2.0 / 3.0 * y) / size
    s = -q - r
    rq, rr, rs = round(q), round(r), round(s)
    dq, dr, ds = abs(rq - q), abs(rr - r), abs(rs - s)
    if dq > dr and dq > ds:
        rq = -rr - rs
    elif dr > ds:
        rr = -rq - rs
    return int(rq), int(rr)


def hex_dist(a, b) -> int:
    dq = a[0] - b[0]
    dr = a[1] - b[1]
    return int((abs(dq) + abs(dr) + abs(dq + dr)) / 2)


def neighbors(c):
    q, r = c
    return [(q + dq, r + dr) for dq, dr in _EDGE_NB]


# --------------------------------------------------------------------------
# Landform + Belegung (rein, ohne tk)
# --------------------------------------------------------------------------
class Landform:
    """Zusammenhaengende Hex-Insel, deterministisch aus seed."""

    def __init__(self, seed, n_cells: int | None = None, salt: str = "land"):
        rng = random.Random(f"equivara-map-{salt}-{seed}")
        n = n_cells if n_cells else rng.randint(54, 60)
        cells = {(0, 0)}
        # leichte Streckung in eine zufaellige Richtung -> keine Kreisscheibe
        ang = rng.uniform(0, math.pi)
        ax, ay = math.cos(ang), math.sin(ang)
        while len(cells) < n:
            frontier = {}
            for c in cells:
                for nb in neighbors(c):
                    if nb not in cells:
                        frontier[nb] = frontier.get(nb, 0) + 1
            items = sorted(frontier.items())
            weights = []
            for c, k in items:
                x, y = hex_center(c[0], c[1], 1.0)
                along = abs(x * ax + y * ay)
                across = abs(-x * ay + y * ax)
                w = (k ** 2.2) * (1.0 + 0.15 * along) / (1.0 + 0.35 * across)
                weights.append(w)
            pick = rng.choices([c for c, _ in items], weights=weights, k=1)[0]
            cells.add(pick)
        # Loecher (Binnenseen aus einem Feld) fuellen
        for _ in range(2):
            for c in list(cells):
                for nb in neighbors(c):
                    if nb not in cells and all(x in cells for x in neighbors(nb)):
                        cells.add(nb)
        self.cells: list[tuple[int, int]] = sorted(cells)
        self.cellset = set(self.cells)
        xs = [hex_center(q, r, 1.0) for q, r in self.cells]
        mx = sum(p[0] for p in xs) / len(xs)
        my = sum(p[1] for p in xs) / len(xs)
        self.centroid = (mx, my)
        self.center_dist = {c: math.hypot(p[0] - mx, p[1] - my) for c, p in zip(self.cells, xs)}
        self.coast = {c: sum(1 for nb in neighbors(c) if nb not in self.cellset) for c in self.cells}
        self.noise = {(c, t): rng.random() for c in self.cells for t in FIELD_TYPES}
        self.nb = {c: [x for x in neighbors(c) if x in self.cellset] for c in self.cells}

    def bbox(self, size: float = 1.0):
        pts = [hex_center(q, r, size) for q, r in self.cells]
        return (min(p[0] for p in pts) - size * SQRT3 / 2, min(p[1] for p in pts) - size,
                max(p[0] for p in pts) + size * SQRT3 / 2, max(p[1] for p in pts) + size)


def _ministry_active(engine, rec: dict, mkey: str, attr: str) -> bool:
    mins = getattr(engine, "ministries", None)
    if isinstance(mins, dict) and mkey in mins:
        return bool(mins.get(mkey))
    return _num(rec.get(attr, getattr(engine, attr, 0.0))) > 0


def record_values(engine, rec: dict, use_engine: bool = False) -> dict:
    """Werte je Feldtyp aus einem History-Record (Fallback: Engine-Attribute)."""
    out = {}
    for t, info in FIELD_TYPES.items():
        a = info["attr"]
        v = rec.get(a) if isinstance(rec, dict) else None
        if v is None and use_engine:
            v = getattr(engine, a, None)
        out[t] = _num(v, 0.0)
    return out


def target_counts(engine, rec: dict, n_cells: int, use_engine: bool = False) -> dict[str, int]:
    vals = record_values(engine, rec, use_engine)
    raw = {}
    for t in _GROW_ORDER:
        info = FIELD_TYPES[t]
        if info["ministry"] and not _ministry_active(engine, rec, info["ministry"], info["attr"]):
            raw[t] = 0.0
            continue
        raw[t] = max(0.0, vals[t]) / info["per_cell"]
    cap = n_cells * 0.86            # mind. ~14 % bleiben Natur
    total = sum(raw.values())
    scale = cap / total if total > cap else 1.0
    scaled = {t: v * scale for t, v in raw.items()}
    counts = {t: int(v) for t, v in scaled.items()}
    for t, v in scaled.items():        # kleine, aber vorhandene Bestaende: mind. 1 Feld
        if counts[t] == 0 and raw[t] >= 0.25:
            counts[t] = 1
    budget = int(round(min(total * scale, cap)))
    rest = sorted(_GROW_ORDER, key=lambda t: (-(scaled[t] - int(scaled[t])), _GROW_ORDER.index(t)))
    i = 0
    while sum(counts.values()) < budget and i < len(rest):
        t = rest[i]
        if scaled[t] - counts[t] > 0.0:
            counts[t] += 1
        i += 1
    while sum(counts.values()) > int(cap):
        t = max(counts, key=lambda k: counts[k])
        counts[t] -= 1
    return counts


def evolve(land: Landform, assign: dict, counts: dict[str, int]) -> dict:
    """Passt die Belegung inkrementell an counts an (Rand schrumpft/waechst)."""
    a = dict(assign)
    cur = {t: 0 for t in FIELD_TYPES}
    for t in a.values():
        cur[t] += 1

    def same_nb(c, t):
        return sum(1 for x in land.nb[c] if a[x] == t)

    # 1) Schrumpfen: Felder mit wenigen gleichartigen Nachbarn zuerst
    for t in _GROW_ORDER:
        while cur[t] > counts.get(t, 0):
            cand = [c for c in land.cells if a[c] == t]
            c = min(cand, key=lambda c: (same_nb(c, t), -land.center_dist[c] if t == "stadt" else 0,
                                         land.noise[(c, t)]))
            a[c] = "natur"
            cur[t] -= 1
            cur["natur"] += 1

    # 2) Wachsen: reihum je ein Feld, damit Cluster nebeneinander entstehen
    def score(c, t):
        s = _SAME_W.get(t, 1.0) * same_nb(c, t)
        aff = _AFF.get(t, {})
        for x in land.nb[c]:
            s += aff.get(a[x], 0.0)
        if t == "stadt":
            s -= 0.9 * land.center_dist[c]
        elif t in ("kraftwerk", "stuetzpunkt"):
            s += 0.6 * land.coast[c]
        elif t == "umweltschutz":
            s += 0.25 * land.center_dist[c]
        elif t == "acker":
            s -= 0.15 * abs(land.center_dist[c] - 2.5)
        return s + 1.2 * land.noise[(c, t)]

    while True:
        progressed = False
        for t in _GROW_ORDER:
            if cur[t] >= counts.get(t, 0):
                continue
            free = [c for c in land.cells if a[c] == "natur"]
            if not free:
                break
            c = max(free, key=lambda c: score(c, t))
            a[c] = t
            cur[t] += 1
            cur["natur"] -= 1
            progressed = True
        if not progressed:
            break
    return a


class _Replay:
    """Spielt die Belegung ueber die History nach (mit Praefix-Cache)."""

    def __init__(self):
        self.key = None
        self.counts: list[tuple] = []
        self.assigns: list[dict] = []

    def run(self, engine, land: Landform, salt: str = "") -> tuple[dict, dict]:
        hist = list(getattr(engine, "history", None) or [])
        if not hist:
            hist = [{}]
        key = (getattr(engine, "seed", None), len(land.cells), salt)
        if key != self.key:
            self.key, self.counts, self.assigns = key, [], []
        seq = []
        for i, rec in enumerate(hist):
            last = i == len(hist) - 1
            c = target_counts(engine, rec if isinstance(rec, dict) else {}, len(land.cells), use_engine=last)
            seq.append(tuple(sorted(c.items())))
        k = 0
        while k < len(seq) and k < len(self.counts) and seq[k] == self.counts[k]:
            k += 1
        self.counts = self.counts[:k]
        self.assigns = self.assigns[:k]
        prev = self.assigns[-1] if self.assigns else {c: "natur" for c in land.cells}
        for i in range(k, len(seq)):
            prev = evolve(land, prev, dict(seq[i]))
            self.counts.append(seq[i])
            self.assigns.append(prev)
        cur = self.assigns[-1]
        before = self.assigns[-2] if len(self.assigns) > 1 else cur
        return cur, before


# --------------------------------------------------------------------------
# Symbole (Canvas-Formen)
# --------------------------------------------------------------------------
def _poly(cv, cx, cy, s, pts, **kw):
    flat = []
    for x, y in pts:
        flat += [cx + x * s, cy + y * s]
    return cv.create_polygon(flat, **kw)


def _tree(cv, x, y, k, col, trunk, tags):
    cv.create_line(x, y + 0.25 * k, x, y + 0.75 * k, fill=trunk, width=max(1, k * 0.18), tags=tags)
    cv.create_polygon(x, y - k, x - 0.62 * k, y + 0.38 * k, x + 0.62 * k, y + 0.38 * k,
                      fill=col, outline="", tags=tags)
    cv.create_polygon(x, y - 1.35 * k, x - 0.45 * k, y - 0.25 * k, x + 0.45 * k, y - 0.25 * k,
                      fill=blend(col, "#ffffff", 0.12), outline="", tags=tags)


def draw_symbol(cv, t: str, cx: float, cy: float, s: float, col: str, bg: str,
                env: float = 0.7, tags=("sym",), variant: float = 0.0):
    """Zeichnet das Symbol fuer Feldtyp t im Hex mit Radius s."""
    if s < 5:
        return
    lw = max(1.0, s * 0.09)
    if t == "natur":
        dead = _clamp((0.62 - env) / 0.3, 0.0, 1.0)
        col_t = blend(col, "#9b7a45", dead * 0.8)
        trunk = blend("#5b4630", bg, 0.2)
        k = s * 0.34
        spots = [(-0.32, 0.12), (0.30, 0.18), (0.0, -0.22)]
        if variant > 0.5:
            spots = [(-0.30, -0.10), (0.28, -0.05), (0.02, 0.30)]
        n = 3 if dead < 0.55 else 2
        for dx, dy in sorted(spots[:n], key=lambda p: p[1]):
            _tree(cv, cx + dx * s, cy + dy * s, k, col_t, trunk, tags)
    elif t == "acker":
        for i, off in enumerate((-0.32, 0.0, 0.32)):
            cv.create_line(cx - 0.52 * s, cy + off * s + 0.16 * s, cx + 0.52 * s, cy + off * s - 0.16 * s,
                           fill=col if i != 1 else blend(col, bg, 0.25), width=lw * 1.15,
                           capstyle="round", tags=tags)
    elif t == "industrie":
        _poly(cv, cx, cy, s, [(-0.55, 0.42), (-0.55, -0.05), (-0.3, -0.25), (-0.3, -0.05), (-0.05, -0.25),
                              (-0.05, -0.05), (0.22, -0.25), (0.22, -0.55), (0.40, -0.55), (0.40, -0.05),
                              (0.55, -0.05), (0.55, 0.42)], fill=col, outline="", tags=tags)
        if s >= 11:
            for wx in (-0.42, -0.17, 0.08):
                cv.create_rectangle(cx + wx * s, cy + 0.08 * s, cx + (wx + 0.12) * s, cy + 0.2 * s,
                                    fill=bg, outline="", tags=tags)
    elif t == "kraftwerk":
        _poly(cv, cx, cy, s, [(0.12, -0.62), (-0.34, 0.08), (-0.04, 0.08), (-0.14, 0.62), (0.34, -0.12),
                              (0.04, -0.12)], fill=col, outline="", tags=tags)
    elif t == "effizienz":
        r = 0.2 * s
        cv.create_oval(cx - r, cy - r, cx + r, cy + r, fill=col, outline="", tags=tags)
        for i in range(8):
            ang = math.radians(i * 45 + 22.5)
            cv.create_line(cx + math.cos(ang) * 0.32 * s, cy + math.sin(ang) * 0.32 * s,
                           cx + math.cos(ang) * 0.5 * s, cy + math.sin(ang) * 0.5 * s,
                           fill=col, width=lw, capstyle="round", tags=tags)
    elif t == "stadt":
        base = cy + 0.42 * s
        blds = [(-0.50, -0.20, -0.08), (-0.16, 0.14, -0.55), (0.20, 0.48, -0.30)]
        for i, (x0, x1, top) in enumerate(blds):
            shade = blend(col, bg, 0.18 * (i % 2))
            cv.create_rectangle(cx + x0 * s, cy + top * s, cx + x1 * s, base, fill=shade, outline="",
                                tags=tags)
            if s >= 12:
                for wy in (top + 0.12, top + 0.30, top + 0.48):
                    if wy > 0.32:
                        continue
                    cv.create_rectangle(cx + (x0 + 0.08) * s, cy + wy * s, cx + (x1 - 0.08) * s,
                                        cy + (wy + 0.06) * s, fill=blend("#ffd479", bg, 0.25), outline="",
                                        tags=tags)
    elif t == "umweltschutz":
        _poly(cv, cx, cy, s, [(0.0, -0.55), (0.40, -0.12), (0.30, 0.25), (0.0, 0.45), (-0.30, 0.25),
                              (-0.40, -0.12)], fill=col, outline="", smooth=True, tags=tags)
        cv.create_line(cx, cy - 0.35 * s, cx, cy + 0.6 * s, fill=bg, width=max(1, lw * 0.8), tags=tags)
        cv.create_line(cx, cy + 0.0 * s, cx + 0.2 * s, cy - 0.18 * s, fill=bg, width=max(1, lw * 0.6),
                       tags=tags)
        cv.create_line(cx, cy + 0.2 * s, cx - 0.2 * s, cy + 0.02 * s, fill=bg, width=max(1, lw * 0.6),
                       tags=tags)
    elif t == "klinik":
        r = 0.48 * s
        cv.create_oval(cx - r, cy - r, cx + r, cy + r, fill=blend(col, "#ffffff", 0.75), outline="",
                       tags=tags)
        a, b = 0.12 * s, 0.32 * s
        cv.create_rectangle(cx - a, cy - b, cx + a, cy + b, fill=col, outline="", tags=tags)
        cv.create_rectangle(cx - b, cy - a, cx + b, cy + a, fill=col, outline="", tags=tags)
    elif t == "schule":
        _poly(cv, cx, cy, s, [(-0.30, 0.0), (0.30, 0.0), (0.30, 0.30), (0.0, 0.40), (-0.30, 0.30)],
              fill=blend(col, bg, 0.3), outline="", tags=tags)
        _poly(cv, cx, cy, s, [(0.0, -0.42), (0.6, -0.12), (0.0, 0.16), (-0.6, -0.12)], fill=col, outline="",
              tags=tags)
        cv.create_line(cx + 0.48 * s, cy - 0.08 * s, cx + 0.48 * s, cy + 0.34 * s, fill=col, width=lw,
                       tags=tags)
    elif t == "knoten":
        r = 0.30 * s
        for ang in (90, 210, 330):
            a_ = math.radians(ang)
            cv.create_line(cx + math.cos(a_) * r, cy + math.sin(a_) * r, cx + math.cos(a_) * 0.62 * s,
                           cy + math.sin(a_) * 0.62 * s, fill=col, width=lw * 1.4, tags=tags)
        cv.create_oval(cx - r, cy - r, cx + r, cy + r, outline=col, width=lw * 1.4, tags=tags)
        cv.create_oval(cx - 0.09 * s, cy - 0.09 * s, cx + 0.09 * s, cy + 0.09 * s, fill=col, outline="",
                       tags=tags)
    elif t == "stuetzpunkt":
        pts = []
        for i in range(10):
            rr = 0.52 if i % 2 == 0 else 0.22
            ang = math.radians(-90 + i * 36)
            pts.append((math.cos(ang) * rr, math.sin(ang) * rr + 0.04))
        _poly(cv, cx, cy, s, pts, fill=col, outline="", tags=tags)


# --------------------------------------------------------------------------
# Gemeinsame Basis
# --------------------------------------------------------------------------
class _HexBase(_ChartBase):
    def __init__(self, parent, title: str, height: int, **kw):
        kw.setdefault("bg", SEA)
        kw.setdefault("width", 520)
        super().__init__(parent, title, height, "{:,.0f}", **kw)
        self._f_name = tkfont.Font(self, family=FONT_UI, size=10, weight="bold")
        self._f_leg = tkfont.Font(self, family=FONT_UI, size=8)
        self._f_sub = tkfont.Font(self, family=FONT_UI, size=9)
        self._hover_cb = None

    def _hex_poly(self, cx, cy, size, **kw):
        return self.create_polygon(hex_corners(cx, cy, size), **kw)

    def _sea(self, w, h, size, ox, oy, land_cells=(), shallow=()):
        """Dezentes Hex-Raster im Meer und Schelf um Kuesten."""
        if size < 4:
            return
        r0 = int(-oy / (1.5 * size)) - 2
        r1 = int((h - oy) / (1.5 * size)) + 2
        for r in range(r0, r1 + 1):
            qa = int((-ox) / (SQRT3 * size) - r / 2.0) - 2
            qb = int((w - ox) / (SQRT3 * size) - r / 2.0) + 2
            for q in range(qa, qb + 1):
                if (q, r) in land_cells:
                    continue
                x, y = hex_center(q, r, size)
                x += ox
                y += oy
                if (q, r) in shallow:
                    self._hex_poly(x, y, size, fill=SEA_SHALLOW, outline=SEA, width=1)
                else:
                    self._hex_poly(x, y, size * 0.97, fill="", outline=SEA_LINE, width=1)

    def _coast(self, cells: set, size, ox, oy, color, width):
        for (q, r) in cells:
            x, y = hex_center(q, r, size)
            pts = hex_corners(x + ox, y + oy, size)
            for i, (dq, dr) in enumerate(_EDGE_NB):
                if (q + dq, r + dr) not in cells:
                    j = (i + 1) % 6
                    self.create_line(pts[2 * i], pts[2 * i + 1], pts[2 * j], pts[2 * j + 1],
                                     fill=color, width=width, capstyle="round")

    def _header(self, w, title, sub):
        """Kopfzeile auf eigenem Band (wird am Ende von redraw nach oben geholt)."""
        tags = ("header",)
        self.create_rectangle(0, 0, w, 34, fill=blend(SEA, THEME["panel"], 0.75), outline="", tags=tags)
        self.create_line(0, 34, w, 34, fill=THEME["border"], tags=tags)
        self.create_text(14, 17, text=title, anchor="w", fill=THEME["text"], font=self._f_title, tags=tags)
        if sub:
            tw = self._f_title.measure(title)
            self.create_text(14 + tw + 12, 17, text=sub, anchor="w", fill=THEME["muted"], font=self._f_sub,
                             tags=tags)

    def _empty_msg(self, w, h, text):
        self.create_text(w / 2, h / 2, text=text, fill=THEME["muted"], font=self._f_tip)

    def refresh(self) -> None:
        self._schedule_redraw()
        try:
            self.redraw()
        except tk.TclError:
            pass


# --------------------------------------------------------------------------
# HexCountryMap
# --------------------------------------------------------------------------
class HexCountryMap(_HexBase):
    """Symbolische Land-Karte eines Landes (Feldtypen ~ Kapitalstoecke)."""

    FLASH_STEPS = 10
    FLASH_MS = 140

    def __init__(self, parent, engine_getter: Callable[[], object], height: int = 360,
                 highlight_changes: bool = True, **kw):
        super().__init__(parent, "Land-Karte", height, **kw)
        self.engine_getter = engine_getter
        self.highlight_changes = highlight_changes
        self._land: Landform | None = None
        self._land_seed = object()
        self._replay = _Replay()
        self._geo = None
        self._seen_len = None
        self._flash_id = None
        self._flash_step = 0
        self.assign: dict = {}
        self.before: dict = {}
        self.changed: set = set()
        self.redraw()

    def destroy(self):
        self._stop_flash()
        super().destroy()

    def _engine(self):
        try:
            return self.engine_getter() if self.engine_getter else None
        except Exception:  # noqa: BLE001 - Karte darf die GUI nie stoeren
            return None

    def _compute(self, eng):
        seed = getattr(eng, "seed", 0)
        if self._land is None or self._land_seed != seed:
            self._land = Landform(seed)
            self._land_seed = seed
        self.assign, self.before = self._replay.run(eng, self._land)
        self.changed = {c for c in self._land.cells if self.assign.get(c) != self.before.get(c)}

    def counts(self) -> dict[str, int]:
        out = {t: 0 for t in FIELD_TYPES}
        for t in self.assign.values():
            out[t] += 1
        return out

    # -- Zeichnen --------------------------------------------------------
    def redraw(self):
        self.delete("all")
        w, h = self._size()
        eng = self._engine()
        if eng is None:
            self._header(w, self.title, "")
            self._empty_msg(w, h, "Noch kein Spiel")
            self._geo = None
            return
        self._compute(eng)
        land = self._land
        hist = getattr(eng, "history", None) or [{}]
        rec = hist[-1] if isinstance(hist[-1], dict) else {}
        env = _num(rec.get("environment", getattr(eng, "environment", 0.7)), 0.7)
        year = rec.get("jahr_end", None)
        sub = f"Jahr {int(_num(year))}" if year is not None else ""
        sub += ("  ·  " if sub else "") + f"Umwelt {env * 100:.0f} %"
        self._header(w, self.title, sub)

        # Layout: Legende rechts (breit) oder unten (schmal)
        counts = self.counts()
        leg_items = [t for t in _LEGEND_ORDER if counts.get(t, 0) > 0 or t == "natur"]
        top = 44
        side = w >= 560
        leg_w = 178 if side else 0
        rows_bottom = 0
        if not side:
            per_row = max(1, int((w - 24) // 124))
            rows_bottom = math.ceil(len(leg_items) / per_row)
        avail_w = w - 24 - leg_w
        avail_h = h - top - 12 - rows_bottom * 20
        x0, y0, x1, y1 = land.bbox(1.0)
        size = max(4.0, min(avail_w / (x1 - x0 + 1.2), avail_h / (y1 - y0 + 1.0)))
        ox = 12 + (avail_w - (x1 - x0) * size) / 2 - x0 * size
        oy = top + (avail_h - (y1 - y0) * size) / 2 - y0 * size
        self._geo = (size, ox, oy)

        shallow = set()
        for c in land.cells:
            for nb in neighbors(c):
                if nb not in land.cellset:
                    shallow.add(nb)
        self._sea(w, h, size, ox, oy, land.cellset, shallow)

        natur_fill = blend(blend("#1b4a30", "#4a3a20", _clamp((0.8 - env) / 0.5, 0, 1)), SEA, 0.05)
        natur_sym = blend("#4fc27a", "#a08050", _clamp((0.75 - env) / 0.45, 0, 1) * 0.6)
        smog = _clamp((0.62 - env) / 0.30, 0.0, 1.0)

        centers = {}
        for c in land.cells:
            x, y = hex_center(c[0], c[1], size)
            centers[c] = (x + ox, y + oy)

        # Felder
        for c in land.cells:
            t = self.assign.get(c, "natur")
            info = FIELD_TYPES[t]
            fill = natur_fill if t == "natur" else info["fill"]
            fill = blend(fill, "#ffffff", 0.025 * (land.noise[(c, "natur")] - 0.5))
            cx, cy = centers[c]
            self._hex_poly(cx, cy, size, fill=fill, outline=blend(fill, SEA, 0.55), width=1,
                           tags=("cell",))
            # leichte Innenkante oben -> Relief
            pts = hex_corners(cx, cy, size * 0.9)
            self.create_line(pts[6], pts[7], pts[8], pts[9], pts[10], pts[11], pts[0], pts[1],
                             fill=blend(fill, "#ffffff", 0.07), width=1)

        # Strassen (Infrastruktur aktiv): MST ueber Staedte + Verkehrsknoten
        if counts.get("knoten", 0) > 0:
            nodes = [c for c in land.cells if self.assign[c] in ("stadt", "knoten")]
            for a_, b_ in _mst(nodes):
                ax, ay = centers[a_]
                bx, by = centers[b_]
                self.create_line(ax, ay, bx, by, fill="#1a1410", width=max(2, size * 0.22), capstyle="round")
                self.create_line(ax, ay, bx, by, fill=blend(FIELD_TYPES["knoten"]["accent"], "#000000", 0.25),
                                 width=max(1, size * 0.08), dash=(4, 3) if size > 10 else None,
                                 capstyle="round")

        # Symbole
        for c in land.cells:
            t = self.assign.get(c, "natur")
            info = FIELD_TYPES[t]
            cx, cy = centers[c]
            col = natur_sym if t == "natur" else info["accent"]
            bg = natur_fill if t == "natur" else info["fill"]
            draw_symbol(self, t, cx, cy, size, col, bg, env=env, variant=land.noise[(c, "stadt")])

        # Smog-Schraffur ueber Industrie/Kraftwerk (und Nachbarschaft bei starker Belastung)
        if smog > 0.05:
            stip = "gray25" if smog < 0.5 else "gray50"
            smog_col = blend("#8d8f86", "#b6ad8f", smog)
            dirty = {c for c in land.cells if self.assign[c] in ("industrie", "kraftwerk")}
            for c in dirty:
                cx, cy = centers[c]
                self._hex_poly(cx, cy, size * 0.98, fill=smog_col, outline="", stipple=stip)
            if smog >= 0.5:
                halo = {nb for c in dirty for nb in land.nb[c]} - dirty
                for c in halo:
                    cx, cy = centers[c]
                    self._hex_poly(cx, cy, size * 0.98, fill=smog_col, outline="", stipple="gray12")

        # Kueste
        self._coast(land.cellset, size, ox, oy, blend(COAST, SEA, 0.55), max(3, size * 0.22))
        self._coast(land.cellset, size, ox, oy, COAST, max(1, size * 0.07))

        # Hervorhebung geaenderter Felder
        self.delete("flash")
        if self.highlight_changes and self.changed and self._flash_step > 0:
            self._draw_flash()

        # Legende
        self._legend(w, h, leg_items, counts, side, leg_w, top, env, natur_fill, natur_sym)

        self.tag_raise("header")
        self._layout = {"cells": centers}
        hist_len = len(hist)
        if self._seen_len is not None and hist_len != self._seen_len and self.changed and self.highlight_changes:
            self._start_flash()
        self._seen_len = hist_len

    def _legend(self, w, h, items, counts, side, leg_w, top, env, natur_fill, natur_sym):
        s = 8.0
        if side:
            x = w - leg_w + 4
            y = top + 4
            self.create_rectangle(x - 6, y - 6, w - 10, y + len(items) * 21 + 22, fill=THEME["panel"],
                                  outline=THEME["border"])
            self.create_text(x + 2, y + 2, text="LEGENDE", anchor="nw", fill=THEME["muted"],
                             font=self._f_small_b)
            self.create_text(w - 18, y + 2, text="Felder", anchor="ne", fill=THEME["muted"], font=self._f_small)
            y += 24
            for t in items:
                self._legend_item(x + 10, y, s, t, counts.get(t, 0), natur_fill, natur_sym, env,
                                  right=w - 18)
                y += 21
        else:
            per_row = max(1, int((w - 24) // 124))
            y = h - 12 - math.ceil(len(items) / per_row) * 20 + 10
            for i, t in enumerate(items):
                col_i = i % per_row
                row = i // per_row
                self._legend_item(18 + col_i * 124, y + row * 20, s, t, counts.get(t, 0), natur_fill,
                                  natur_sym, env, right=None)

    def _legend_item(self, x, y, s, t, n, natur_fill, natur_sym, env, right=None):
        info = FIELD_TYPES[t]
        fill = natur_fill if t == "natur" else info["fill"]
        col = natur_sym if t == "natur" else info["accent"]
        self._hex_poly(x, y, s + 1.5, fill=fill, outline=blend(col, fill, 0.5))
        draw_symbol(self, t, x, y, s + 1.5, col, fill, env=env, tags=("leg",))
        self.create_text(x + 16, y, text=info["name"], anchor="w", fill=THEME["text"], font=self._f_leg)
        if right is not None:
            self.create_text(right, y, text=str(n), anchor="e", fill=THEME["muted"], font=self._f_axis)

    # -- Hervorhebung ------------------------------------------------------
    def _start_flash(self):
        self._stop_flash()
        self._flash_step = self.FLASH_STEPS
        self._draw_flash()
        self._flash_id = self.after(self.FLASH_MS, self._flash_tick)

    def _stop_flash(self):
        if self._flash_id is not None:
            try:
                self.after_cancel(self._flash_id)
            except tk.TclError:
                pass
            self._flash_id = None

    def _flash_tick(self):
        self._flash_id = None
        self._flash_step -= 1
        try:
            self._draw_flash()
        except tk.TclError:
            return
        if self._flash_step > 0:
            self._flash_id = self.after(self.FLASH_MS, self._flash_tick)

    def _draw_flash(self):
        self.delete("flash")
        if not self._geo or self._flash_step <= 0 or not self._land:
            return
        size, ox, oy = self._geo
        t = self._flash_step / self.FLASH_STEPS
        col = blend("#3a4a66", "#ffffff", t)
        for c in self.changed:
            x, y = hex_center(c[0], c[1], size)
            self._hex_poly(x + ox, y + oy, size * 0.86, fill="", outline=col, width=max(2, size * 0.12),
                           tags=("flash",))
        self.tag_raise("hover")

    # -- Hover -------------------------------------------------------------
    def _on_motion(self, event):
        self.delete("hover")
        if not self._geo or not self._land:
            return
        size, ox, oy = self._geo
        c = pixel_to_hex(event.x - ox, event.y - oy, size)
        if c not in self._land.cellset:
            return
        eng = self._engine()
        if eng is None:
            return
        t = self.assign.get(c, "natur")
        info = FIELD_TYPES[t]
        hist = getattr(eng, "history", None) or [{}]
        rec = hist[-1] if isinstance(hist[-1], dict) else {}
        vals = record_values(eng, rec, use_engine=True)
        n = self.counts().get(t, 0)
        x, y = hex_center(c[0], c[1], size)
        x += ox
        y += oy
        self._hex_poly(x, y, size, fill="", outline=THEME["white"], width=2, tags=("hover",))
        lines = [(info["name"], THEME["text"], True, info["accent"])]
        v = vals.get(t, 0.0)
        if t == "natur":
            lines.append((f"{info['value_label']}: {v * 100:.0f} %", THEME["muted"], False, None))
            load = _num(rec.get("env_load"), -1)
            if load >= 0:
                lines.append((f"Umweltbelastung: {_fmt(load)}", THEME["muted"], False, None))
        else:
            lines.append((f"{info['value_label']}: {_fmt(v)}", THEME["muted"], False, None))
            per = v / n if n else 0
            lines.append((f"{n} Felder  ·  ≈ {_fmt(per)} je Feld", THEME["muted"], False, None))
        if t == "stuetzpunkt":
            sec = rec.get("security", getattr(eng, "security", None))
            if callable(sec):
                try:
                    sec = sec()
                except Exception:  # noqa: BLE001
                    sec = None
            if sec is not None:
                lines.append((f"Sicherheit: {_num(sec) * 100:.0f} %", THEME["muted"], False, None))
        if t in ("industrie", "kraftwerk"):
            env = vals.get("natur", 0.7)
            if env < 0.62:
                lines.append(("Smog: hohe Umweltbelastung", THEME["orange"], False, None))
        if c in self.changed:
            old = FIELD_TYPES[self.before.get(c, "natur")]["name"]
            lines.append((f"Neu in diesem Zyklus (vorher {old})", THEME["cyan"], False, None))
        self._draw_tip(x + size * 0.6, y, lines)


def _mst(nodes):
    """Prim-MST (Pixelabstand) ueber Hex-Koordinaten."""
    if len(nodes) < 2:
        return []
    pts = {c: hex_center(c[0], c[1], 1.0) for c in nodes}
    inside = {nodes[0]}
    edges = []
    rest = set(nodes[1:])
    while rest:
        best = None
        for a in inside:
            for b in rest:
                d = math.dist(pts[a], pts[b])
                if best is None or d < best[0] or (d == best[0] and (a, b) < best[1:]):
                    best = (d, a, b)
        _, a, b = best
        edges.append((a, b))
        inside.add(b)
        rest.discard(b)
    return edges


# --------------------------------------------------------------------------
# HexWorldMap
# --------------------------------------------------------------------------
class HexWorldMap(_HexBase):
    """Weltkarte: Laender als Hex-Cluster um eine zentrale Boerse, Handelsfluesse als Pfeile."""

    def __init__(self, parent, world_getter: Callable[[], object], height: int = 420, **kw):
        super().__init__(parent, "Weltkarte", height, **kw)
        self.world_getter = world_getter
        self._lands: dict = {}
        self._replays: dict = {}
        self._hit = None
        self._f_badge = tkfont.Font(self, family=FONT_UI, size=7, weight="bold")
        self.redraw()

    def _world(self):
        try:
            return self.world_getter() if self.world_getter else None
        except Exception:  # noqa: BLE001
            return None

    @staticmethod
    def _countries(world) -> list:
        cs = getattr(world, "countries", None)
        if cs is None:
            cs = getattr(world, "players", None)
        return list(cs or [])

    @staticmethod
    def _cattr(c, name, default=None):
        if isinstance(c, dict):
            return c.get(name, default)
        return getattr(c, name, default)

    def _land_for(self, i, eng):
        pop = _num(getattr(eng, "population", 200.0), 200.0)
        n = int(_clamp(round(pop / 9.0), 14, 46))
        key = (i, getattr(eng, "seed", 0), n)
        if key not in self._lands:
            self._lands[key] = Landform(getattr(eng, "seed", 0), n_cells=n, salt=f"world{i}")
        return self._lands[key]

    def _score(self, eng):
        try:
            sc = eng.score()
            return _num(sc.get("total")), sc.get("grade", "")
        except Exception:  # noqa: BLE001
            return None, ""

    def redraw(self):
        self.delete("all")
        w, h = self._size()
        world = self._world()
        countries = self._countries(world) if world is not None else []
        self._hit = None
        if not countries:
            self._header(w, self.title, "")
            self._empty_msg(w, h, "Keine Welt geladen")
            return
        active = int(_num(getattr(world, "active", 0), 0))
        mode = getattr(world, "mode", "")
        cyc = None
        e0 = self._cattr(countries[0], "engine")
        if e0 is not None:
            cyc = getattr(e0, "runde", None)
        sub = []
        if cyc is not None:
            sub.append(f"Zyklus {int(_num(cyc))}")
        if mode:
            sub.append(f"Modus {str(mode).capitalize()}")
        self._header(w, self.title, "  ·  ".join(sub))

        top = 36
        bottom_leg = 26
        cx_m = w / 2
        cy_m = top + (h - top - bottom_leg) / 2
        n = len(countries)
        rx = (w / 2) * 0.62
        ry = ((h - top - bottom_leg) / 2) * 0.60
        if n == 1:
            angles = [180]
        elif n == 2:
            angles = [180, 0]
        elif n == 3:
            angles = [210, 330, 90]
        else:
            angles = [225, 315, 45, 135] + [i * 360 / n for i in range(4, n)]
        pos = []
        for i in range(n):
            a = math.radians(angles[i % len(angles)])
            pos.append((cx_m + rx * math.cos(a), cy_m + ry * math.sin(a)))

        lands, engines = [], []
        for i, c in enumerate(countries):
            eng = self._cattr(c, "engine")
            engines.append(eng)
            lands.append(self._land_for(i, eng) if eng is not None else Landform(i, n_cells=14, salt="x"))
        # Hexgroesse: groesstes Land passt in die Zelle
        cell_w = (w / (2 if n <= 2 else 2)) * 0.62
        cell_h = (h - top - bottom_leg) / (1 if n <= 2 else 2) * 0.62
        ext = []
        for L in lands:
            x0, y0, x1, y1 = L.bbox(1.0)
            ext.append((x1 - x0, y1 - y0))
        size = min(min(cell_w / e[0], cell_h / e[1]) for e in ext)
        size = _clamp(size, 5.0, 22.0)

        # Meer-Raster (Basis-Ursprung auf Mitte)
        self._sea(w, h, size, cx_m, cy_m)

        # Geometrie aller Laender
        geo = []
        for i, L in enumerate(lands):
            px, py = pos[i]
            mx, my = L.centroid
            ox = px - mx * size
            oy = py - my * size
            # auf das Meeresraster schnappen
            q, r = pixel_to_hex(ox - cx_m, oy - cy_m, size)
            sx, sy = hex_center(q, r, size)
            ox, oy = cx_m + sx, cy_m + sy
            cells = {c: (hex_center(c[0], c[1], size)[0] + ox, hex_center(c[0], c[1], size)[1] + oy)
                     for c in L.cells}
            xs = [p[0] for p in cells.values()]
            ys = [p[1] for p in cells.values()]
            cxx, cyy = sum(xs) / len(xs), sum(ys) / len(ys)
            rad = max(math.hypot(x - cxx, y - cyy) for x, y in zip(xs, ys)) + size * 0.6
            geo.append({"ox": ox, "oy": oy, "cells": cells, "c": (cxx, cyy), "r": rad,
                        "top": min(ys) - size, "bot": max(ys) + size})

        # Weltmarkt
        m_r = _clamp(size * 3.6, 44, 64)
        flows = []
        try:
            if hasattr(world, "trade_flows"):
                flows = list(world.trade_flows() or [])
        except Exception:  # noqa: BLE001
            flows = []
        self._draw_flows(flows, geo, (cx_m, cy_m), m_r)

        # Laender
        hit_cells = []
        for i, (c, L, eng, g) in enumerate(zip(countries, lands, engines, geo)):
            color = self._cattr(c, "color") or [THEME["blue"], THEME["green"], THEME["orange"],
                                                THEME["purple"]][i % 4]
            is_active = (i == active) and n > 1
            assign = {}
            if eng is not None:
                rp = self._replays.setdefault(i, _Replay())
                try:
                    assign, _ = rp.run(eng, L, salt=f"w{i}")
                except Exception:  # noqa: BLE001
                    assign = {}
            env = _num(getattr(eng, "environment", 0.7), 0.7) if eng is not None else 0.7
            if is_active:
                self._coast(L.cellset, size, g["ox"], g["oy"], blend(color, SEA, 0.55), max(6, size * 0.55))
            shade_cache = {}
            for cell, (x, y) in g["cells"].items():
                t = assign.get(cell, "natur")
                if t == "natur":
                    fill = blend(blend(color, "#2f6b45", 0.45), SEA, 0.42 + 0.15 * (1 - env))
                elif t == "stadt":
                    fill = blend(color, "#ffffff", 0.18)
                else:
                    fill = shade_cache.setdefault(t, blend(color, FIELD_TYPES[t]["fill"], 0.45))
                self._hex_poly(x, y, size, fill=fill, outline=blend(fill, SEA, 0.5), width=1)
                if t == "stadt" and size >= 7:
                    rr = size * 0.22
                    self.create_oval(x - rr, y - rr, x + rr, y + rr, fill="#ffffff", outline="")
                elif t != "natur" and size >= 12:
                    draw_symbol(self, t, x, y, size * 0.75, blend(FIELD_TYPES[t]["accent"], "#ffffff", 0.2),
                                fill, env=env)
                hit_cells.append((x, y, i))
            self._coast(L.cellset, size, g["ox"], g["oy"],
                        THEME["white"] if is_active else blend(color, "#ffffff", 0.35),
                        max(1.5, size * (0.16 if is_active else 0.09)))
            # Beschriftung
            name = str(self._cattr(c, "name", f"Land {i + 1}"))
            sc, grade = self._score(eng) if eng is not None else (None, "")
            above = g["c"][1] < cy_m
            ly = g["top"] - 8 if above else g["bot"] + 8
            anchor = "s" if above else "n"
            label_y2 = ly - 15 if above else ly + 16
            self._label(g["c"][0], ly, name, color, anchor, bold=True)
            pop = _num(getattr(eng, "population", 0)) if eng is not None else 0
            info = f"Score {sc:.0f} {grade}  ·  {pop:.0f} Einw." if sc is not None else f"{pop:.0f} Einw."
            self.create_text(g["c"][0], label_y2, text=info, anchor=anchor, fill=THEME["muted"],
                             font=self._f_small)
            if is_active:
                tw = self._f_badge.measure("AM ZUG") + 12
                nw = self._f_name.measure(name) + 14
                bx = g["c"][0] + nw / 2 + 6 + tw / 2
                th = self._f_name.metrics("linespace")
                by = ly - th / 2 if above else ly + th / 2
                self.create_rectangle(bx - tw / 2, by - 8, bx + tw / 2, by + 8, fill=THEME["white"],
                                      outline="")
                self.create_text(bx, by, text="AM ZUG", fill=SEA, font=self._f_badge)

        self._draw_market(world, engines, (cx_m, cy_m), m_r)
        self._world_legend(w, h)
        self.tag_raise("header")
        self._layout = {"hit": hit_cells, "size": size, "market": (cx_m, cy_m, m_r),
                        "countries": countries, "engines": engines, "flows": flows}

    def _label(self, x, y, text, color, anchor, bold=False):
        f = self._f_name if bold else self._f_small
        tw = f.measure(text)
        th = f.metrics("linespace")
        y0 = y - th if anchor == "s" else y
        self.create_rectangle(x - tw / 2 - 7, y0 - 1, x + tw / 2 + 7, y0 + th + 1,
                              fill=blend(color, SEA, 0.78), outline=blend(color, SEA, 0.35))
        self.create_text(x, y0 + th / 2, text=text, fill=blend(color, "#ffffff", 0.45), font=f)

    def _prices(self, world, engines):
        pr = None
        try:
            if hasattr(world, "current_prices"):
                pr = world.current_prices()
        except Exception:  # noqa: BLE001
            pr = None
        if not pr:
            for e in engines:
                m = getattr(e, "market", None)
                if isinstance(m, dict):
                    pr = m
                    break
        return pr if isinstance(pr, dict) else None

    def _draw_market(self, world, engines, center, r):
        cx, cy = center
        # Leuchtring
        for k, t in ((1.45, 0.86), (1.25, 0.72)):
            self._hex_poly(cx, cy, r * k, fill=blend("#d9b65a", SEA, t), outline="")
        self._hex_poly(cx, cy, r, fill=THEME["panel2"], outline="#d9b65a", width=2)
        self._hex_poly(cx, cy, r * 0.92, fill="", outline=blend("#d9b65a", THEME["panel2"], 0.7), width=1)
        pr = self._prices(world, engines)
        rows = []
        if pr and isinstance(pr.get("export_price"), dict):
            ep = pr["export_price"]
            rows = [(g, _num(ep[g], 1.0)) for g in ("food", "goods", "energy") if g in ep]
        if not rows:
            self.create_text(cx, cy - r * 0.18, text="⇄", fill="#f0d27a",
                             font=(FONT_UI, int(_clamp(r * 0.42, 11, 20)), "bold"))
            self.create_text(cx, cy + r * 0.22, text="Weltmarkt", fill=THEME["text"], font=self._f_small_b)
            return
        self.create_text(cx, cy - r * 0.50, text="⇄ Weltmarkt", fill="#f0d27a", font=self._f_small_b)
        lh = _clamp(r * 0.26, 12, 15)
        y = cy - r * 0.50 + lh * 1.3
        for g, v in rows:
            col = FLOW_COLORS[g]
            arrow = "▲" if v > 1.02 else "▼" if v < 0.98 else "■"
            acol = THEME["green"] if v > 1.02 else THEME["red"] if v < 0.98 else THEME["muted"]
            self.create_oval(cx - r * 0.84, y - 3, cx - r * 0.84 + 6, y + 3, fill=col, outline="")
            self.create_text(cx - r * 0.84 + 10, y, text=FLOW_NAMES[g], anchor="w", fill=THEME["text"],
                             font=self._f_leg)
            self.create_text(cx + r * 0.80, y, text=f"{v:.2f}".replace(".", ",") + " " + arrow, anchor="e",
                             fill=acol if arrow != "■" else THEME["muted"], font=self._f_axis)
            y += lh

    def _draw_flows(self, flows, geo, mcenter, m_r):
        clean = []
        for f in flows:
            if not isinstance(f, dict):
                continue
            amt = _num(f.get("amount"), 0.0)
            good = f.get("good", "goods")
            if amt <= 0:
                continue
            clean.append((f.get("from"), f.get("to"), good, amt))
        if not clean:
            return
        mx = max(a for *_, a in clean)
        gidx = {"food": -1, "goods": 0, "energy": 1}

        def anchor(idx):
            if idx is None or not isinstance(idx, int) or not (0 <= idx < len(geo)):
                return mcenter, m_r * 1.05
            return geo[idx]["c"], geo[idx]["r"] * 0.85

        placed = []
        for src, dst, good, amt in sorted(clean, key=lambda x: -x[3]):
            (ax, ay), ra = anchor(src)
            (bx, by), rb = anchor(dst)
            d = math.hypot(bx - ax, by - ay)
            if d < 1:
                continue
            ux, uy = (bx - ax) / d, (by - ay) / d
            px, py = -uy, ux
            off = gidx.get(good, 0) * 0.20 + 0.12
            sa = ax + ux * ra + px * ra * gidx.get(good, 0) * 0.25
            sb = ay + uy * ra + py * ra * gidx.get(good, 0) * 0.25
            ea = bx - ux * rb + px * rb * gidx.get(good, 0) * 0.25
            eb = by - uy * rb + py * rb * gidx.get(good, 0) * 0.25
            dd = math.hypot(ea - sa, eb - sb)
            mxp = (sa + ea) / 2 + px * dd * off
            myp = (sb + eb) / 2 + py * dd * off
            width = 1.5 + 7.0 * math.sqrt(amt / mx)
            col = FLOW_COLORS.get(good, THEME["muted"])
            self.create_line(sa, sb, mxp, myp, ea, eb, smooth=True, splinesteps=30,
                             fill=blend(col, SEA, 0.7), width=width + 4, capstyle="round")
            self.create_line(sa, sb, mxp, myp, ea, eb, smooth=True, splinesteps=30, fill=col, width=width,
                             arrow="last", arrowshape=(width * 2.2 + 6, width * 2.2 + 6, width * 1.1 + 3),
                             capstyle="round", tags=("flow",))
            if width >= 4:
                lx = (sa + ea) / 4 + mxp / 2
                ly = (sb + eb) / 4 + myp / 2
                txt = _fmt(amt)
                tw = self._f_axis.measure(txt) + 8
                for _ in range(6):
                    if not any(abs(lx - px_) < (tw + pw) / 2 + 2 and abs(ly - py_) < 16 for px_, py_, pw in placed):
                        break
                    ly += 16
                placed.append((lx, ly, tw))
                self.create_rectangle(lx - tw / 2, ly - 7, lx + tw / 2, ly + 7, fill=SEA, outline=col)
                self.create_text(lx, ly, text=txt, fill=col, font=self._f_axis)

    def _world_legend(self, w, h):
        x = 16
        y = h - 14
        self.create_text(x, y, text="Handel:", anchor="w", fill=THEME["muted"], font=self._f_small_b)
        x += self._f_small_b.measure("Handel:") + 10
        for g in ("food", "goods", "energy"):
            col = FLOW_COLORS[g]
            self.create_line(x, y, x + 22, y, fill=col, width=3, arrow="last", arrowshape=(7, 7, 4))
            self.create_text(x + 28, y, text=FLOW_NAMES[g], anchor="w", fill=THEME["text"], font=self._f_leg)
            x += 36 + self._f_leg.measure(FLOW_NAMES[g]) + 10
        self.create_text(x + 4, y, text="Pfeildicke ~ Menge", anchor="w", fill=THEME["muted"], font=self._f_leg)

    # -- Hover -------------------------------------------------------------
    def _on_motion(self, event):
        self.delete("hover")
        L = self._layout
        if not L:
            return
        cx, cy, mr = L["market"]
        if math.hypot(event.x - cx, event.y - cy) <= mr:
            self._tip_market(event.x, event.y)
            return
        size = L["size"]
        best = None
        for x, y, i in L["hit"]:
            d = math.hypot(event.x - x, event.y - y)
            if d <= size * 0.95 and (best is None or d < best[0]):
                best = (d, i)
        if best is None:
            return
        i = best[1]
        c = L["countries"][i]
        eng = L["engines"][i]
        color = self._cattr(c, "color") or THEME["blue"]
        name = str(self._cattr(c, "name", f"Land {i + 1}"))
        lines = [(name, THEME["text"], True, color)]
        if eng is not None:
            sc, grade = self._score(eng)
            if sc is not None:
                lines.append((f"Score: {sc:.0f} ({grade})", THEME["text"], False, None))
            lines.append((f"Bevölkerung: {_fmt(_num(getattr(eng, 'population', 0)))}", THEME["muted"], False,
                          None))
            lines.append((f"Nahrung/Kopf: {_fmt(_num(getattr(eng, 'food_pc', 0)))}   "
                          f"Güter/Kopf: {_fmt(_num(getattr(eng, 'goods_pc', 0)))}", THEME["muted"], False, None))
            lines.append((f"Umwelt: {_num(getattr(eng, 'environment', 0)) * 100:.0f} %   "
                          f"Schulden: {_fmt(_num(getattr(eng, 'debt', 0)))}", THEME["muted"], False, None))
        out = {}
        inn = {}
        for f in L["flows"]:
            if not isinstance(f, dict):
                continue
            g = f.get("good")
            if f.get("from") == i:
                out[g] = out.get(g, 0.0) + _num(f.get("amount"))
            if f.get("to") == i:
                inn[g] = inn.get(g, 0.0) + _num(f.get("amount"))
        for lbl, dct in (("Export", out), ("Import", inn)):
            if dct:
                txt = ", ".join(f"{FLOW_NAMES.get(g, g)} {_fmt(v)}" for g, v in dct.items())
                lines.append((f"{lbl}: {txt}", THEME["muted"], False, None))
        self._draw_tip(event.x, event.y, lines)

    def _tip_market(self, x, y):
        world = self._world()
        pr = self._prices(world, self._layout.get("engines", []))
        lines = [("Weltmarkt", THEME["text"], True, "#d9b65a")]
        if pr:
            ep = pr.get("export_price", {}) or {}
            ip = pr.get("import_price", {}) or {}
            for g in ("food", "goods", "energy"):
                if g in ep or g in ip:
                    lines.append((f"{FLOW_NAMES[g]}: Export {_num(ep.get(g), 1):.2f} · Import "
                                  f"{_num(ip.get(g), 1):.2f}".replace(".", ","), FLOW_COLORS[g], False, None))
        else:
            lines.append(("Preise fix (kein gemeinsamer Markt)", THEME["muted"], False, None))
        mh = getattr(world, "market_history", None)
        if mh and isinstance(mh[-1], dict):
            sup = mh[-1].get("supply") or {}
            dem = mh[-1].get("demand") or {}
            for g in ("food", "goods", "energy"):
                if g in sup or g in dem:
                    lines.append((f"{FLOW_NAMES[g]}: Angebot {_fmt(_num(sup.get(g)))} · Nachfrage "
                                  f"{_fmt(_num(dem.get(g)))}", THEME["muted"], False, None))
        self._draw_tip(x, y, lines)


# --------------------------------------------------------------------------
# Demo
# --------------------------------------------------------------------------
class _DemoCountry:
    def __init__(self, name, engine, color):
        self.name = name
        self.engine = engine
        self.color = color
        self.roles = {}


class _DemoWorld:
    """Minimaler World-Ersatz, falls equivara_world (noch) fehlt."""

    def __init__(self, countries):
        self.mode = "handel"
        self.countries = countries
        self.active = 0
        self.market_history = []
        self._flows = []
        self._prices = {"export_price": {"food": 1.0, "goods": 1.0, "energy": 1.0},
                        "import_price": {"food": 1.1, "goods": 1.1, "energy": 1.0}}

    def current_prices(self):
        return self._prices

    def trade_flows(self):
        return self._flows

    def play_round(self, advise=True):
        flows = []
        sup = {"food": 0.0, "goods": 0.0, "energy": 0.0}
        for i, c in enumerate(self.countries):
            e = c.engine
            inp = e.advise_inputs()[0] if advise else e.suggest_inputs()
            r = e.apply(inp)
            for g, k in (("food", "food_import"), ("goods", "goods_import"), ("energy", "energy_import")):
                amt = _num(r.get(k))
                if amt > 0:
                    flows.append({"from": None, "to": i, "good": g, "amount": amt})
            ex = r.get("exports") if isinstance(r.get("exports"), dict) else None
            if ex:
                for g, amt in ex.items():
                    if _num(amt) > 0:
                        flows.append({"from": i, "to": None, "good": g, "amount": _num(amt)})
                        sup[g] += _num(amt)
            else:
                amt = _num(r.get("export_money"))
                if amt > 0:
                    flows.append({"from": i, "to": None, "good": "goods", "amount": amt})
        # ein direkter Laenderfluss fuer die Optik
        if len(self.countries) >= 2:
            flows.append({"from": 0, "to": 1, "good": "food", "amount": 120.0})
        self._flows = flows
        self._prices = {"export_price": {"food": 1.08, "goods": 0.93, "energy": 1.0},
                        "import_price": {"food": 1.18, "goods": 1.02, "energy": 1.05}}
        self.market_history.append({"prices": self._prices, "supply": sup, "demand": {}, "flows": flows})
        self.active = (self.active + 1) % len(self.countries)


def _shot(widget, path):
    from PIL import ImageGrab  # optional
    widget.update()
    x, y = widget.winfo_rootx(), widget.winfo_rooty()
    w, h = widget.winfo_width(), widget.winfo_height()
    ImageGrab.grab(bbox=(x, y, x + w, y + h)).save(path)
    return path


def _demo(outdir: str | None = None):
    """Demo: Land-Karte in mehreren Zyklen + Weltkarte. Mit outdir: Screenshots, kein mainloop."""
    import os

    from equivara_engine import EquivaraEngine

    def mk(seed, scenario="standard"):
        kw = {}
        try:
            names = getattr(__import__("equivara_engine"), "MINISTRIES", None)
            if names:
                kw["ministries"] = {k: True for k in names}
        except Exception:  # noqa: BLE001
            pass
        try:
            return EquivaraEngine(scenario=scenario, seed=seed, **kw)
        except TypeError:
            return EquivaraEngine(scenario=scenario, seed=seed)

    root = tk.Tk()
    root.title("equivara_map – Demo")
    root.configure(bg=THEME["bg"])
    root.geometry("1360x860+20+20")
    eng = mk(7)
    state = {"eng": eng}
    left = tk.Frame(root, bg=THEME["bg"])
    left.pack(side="left", fill="both", expand=True, padx=(12, 6), pady=12)
    cmap = HexCountryMap(left, lambda: state["eng"], height=400)
    cmap.pack(fill="both", expand=True)
    small = HexCountryMap(left, lambda: state["eng"], height=300, width=420)
    small.pack(anchor="w", pady=(10, 0))

    world = None
    try:
        import equivara_world as ew  # type: ignore
        cols = [THEME["blue"], THEME["green"], THEME["orange"]]
        cs = [ew.Country(name=n, engine=mk(s), color=col)
              for n, s, col in (("Nordland", 11, cols[0]), ("Südmark", 23, cols[1]), ("Ostria", 5, cols[2]))]
        world = ew.World("handel", cs, seed=1)
    except Exception:  # noqa: BLE001
        world = _DemoWorld([_DemoCountry("Nordland", mk(11), THEME["blue"]),
                            _DemoCountry("Südmark", mk(23, "bevoelkerungsdruck"), THEME["green"]),
                            _DemoCountry("Ostria", mk(5, "umweltkrise"), THEME["orange"])])
    wmap = HexWorldMap(root, lambda: world, height=600, width=640)
    wmap.pack(side="left", fill="both", expand=True, padx=(6, 12), pady=12)

    def world_round():
        if isinstance(world, _DemoWorld):
            world.play_round()
        else:
            for _ in range(len(world.countries)):
                e = world.current_country().engine
                world.submit(e.advise_inputs()[0])

    def advance(k):
        for i in range(k):
            e = state["eng"]
            inp = e.advise_inputs()[0] if i % 2 == 0 else e.suggest_inputs()
            e.apply(inp)
        cmap.refresh()
        small.refresh()

    if outdir:
        os.makedirs(outdir, exist_ok=True)
        root.update()
        cmap.refresh(); small.refresh(); wmap.refresh()
        root.update()
        paths = [_shot(cmap, os.path.join(outdir, "map_country_c0.png"))]
        advance(3)
        root.update()
        paths.append(_shot(cmap, os.path.join(outdir, "map_country_c3_flash.png")))
        advance(5)
        root.after(1600)
        root.update()
        paths.append(_shot(cmap, os.path.join(outdir, "map_country_c8.png")))
        paths.append(_shot(small, os.path.join(outdir, "map_country_small.png")))
        # Umweltkrise -> Smog
        state["eng"] = mk(3, "umweltkrise")
        e = state["eng"]
        for _ in range(4):
            e.apply(e.suggest_inputs())
        # Umweltkatastrophe fuer die Demo simulieren (nur Anzeige)
        e.environment = 0.36
        if e.history:
            e.history[-1]["environment"] = 0.36
        cmap.refresh(); small.refresh()
        root.after(1600)
        root.update()
        paths.append(_shot(cmap, os.path.join(outdir, "map_country_smog.png")))
        world_round(); world_round()
        wmap.refresh()
        root.update()
        paths.append(_shot(wmap, os.path.join(outdir, "map_world.png")))
        root.destroy()
        return paths

    bar = tk.Frame(root, bg=THEME["bg"])
    tk.Button(bar, text="+1 Zyklus", command=lambda: advance(1)).pack(side="left")
    tk.Button(bar, text="Welt-Runde", command=lambda: (world_round(), wmap.refresh())).pack(side="left")
    bar.place(x=14, y=4)
    root.mainloop()
    return []


if __name__ == "__main__":
    import sys

    out = sys.argv[1] if len(sys.argv) > 1 else None
    for p in _demo(out):
        print(p)
