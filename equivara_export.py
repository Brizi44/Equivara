"""Equivara – Export von Spielberichten.

export_html()       erzeugt eine eigenständige, druckfreundliche HTML-Datei
                    (kein externes CSS/JS, inline-SVG-Diagramme). Im Browser
                    lässt sie sich über "Drucken → Als PDF speichern" in ein
                    PDF umwandeln (A4, beim Druck immer hell).
export_canvas_png() speichert den Bildschirmbereich eines tk.Canvas als PNG
                    (nur wenn Pillow installiert ist).

Nur Standardbibliothek; Pillow ist optional. Engine-Erweiterungen wie
score(), scenario, events_enabled oder history[i]["event"] werden genutzt,
wenn vorhanden, sonst gibt es sinnvolle Ersatzanzeigen.
"""

from __future__ import annotations

import html
import math
from datetime import datetime
from pathlib import Path

__all__ = ["export_html", "export_canvas_png"]


# =============================================================================
# Formatierung
# =============================================================================

_NBSP_THIN = " "   # schmales geschütztes Leerzeichen als Tausendertrenner
_MINUS = "−"


def _esc(value) -> str:
    return html.escape(str(value), quote=True)


def _num(x, dec: int = 0) -> str:
    """Deutsche Zahlendarstellung: 12 345,6 (schmales Leerzeichen, Dezimalkomma)."""
    if x is None:
        return "–"
    try:
        x = float(x)
    except (TypeError, ValueError):
        return "–"
    if math.isnan(x) or math.isinf(x):
        return "–"
    if abs(x) < 0.5 * 10 ** (-dec):
        x = 0.0
    s = f"{abs(x):,.{dec}f}".replace(",", _NBSP_THIN).replace(".", ",")
    return (_MINUS if x < 0 else "") + s


def _signed(x, dec: int = 0) -> str:
    if x is None:
        return "–"
    s = _num(x, dec)
    return "+" + s if float(x) > 0 and s.strip("0,") else s


# =============================================================================
# Kennzahlen
# =============================================================================

def _pct(v):
    return None if v is None else float(v) * 100.0


# (Schlüssel, Bezeichnung, Einheit, Dezimalstellen, Umrechnung)
_METRICS = {
    "population": ("Bevölkerung", "Einwohner", 0, None),
    "food_pc": ("Nahrung pro Kopf", "NW/Kopf/Jahr", 2, None),
    "goods_pc": ("Güter pro Kopf", "GW/Kopf/Jahr", 2, None),
    "environment": ("Umweltqualität", "%", 1, _pct),
    "debt": ("Schulden", "GW", 0, None),
    "gdp": ("GDP-Index", "Index (Start = 100)", 1, None),
}

# Diagramme im Bericht: (Schlüssel, Titel, y-Achse, Referenzlinie, y-Bereich fix)
_CHARTS = [
    ("population", "Bevölkerung", "Einwohner", None, None),
    ("food_pc", "Nahrung pro Kopf", "NW pro Kopf und Jahr", (2.0, "Ziel 2,0"), None),
    ("goods_pc", "Güter pro Kopf", "GW pro Kopf und Jahr", None, None),
    ("environment", "Umweltqualität", "Umweltqualität in %", None, (0.0, 100.0)),
    ("debt", "Schulden", "Schulden in GW", None, None),
    ("gdp", "GDP-Index", "Index (Start = 100)", None, None),
]

_CAPITALS = [
    ("cap_food", "Nahrungskapital"),
    ("cap_goods", "Güterkapital"),
    ("cap_human", "Humankapital"),
    ("cap_energy_prod", "Energieproduktion"),
    ("cap_energy_eff", "Energieeffizienz"),
    ("cap_env", "Umweltschutz"),
]

# Vollständige Verlaufstabelle: (Gruppe, [(Schlüssel, Bezeichnung, Dezimalstellen, Umrechnung)])
_TABLE = [
    ("Bevölkerung", [
        ("population", "Bevölkerung", 0, None),
        ("labor", "Arbeitskräfte", 0, None),
        ("birth_rate", "Geburtenrate (‰/Jahr)", 1, None),
        ("death_rate", "Sterberate (‰/Jahr)", 1, None),
        ("net_growth", "Nettowachstum (‰/Jahr)", 1, None),
    ]),
    ("Versorgung", [
        ("food_pc", "Nahrung/Kopf", 2, None),
        ("goods_pc", "Güter/Kopf", 2, None),
        ("human_pc", "Human Services/Kopf", 2, None),
    ]),
    ("Produktion", [
        ("food_production", "Nahrungsproduktion", 0, None),
        ("goods_production", "Güterproduktion", 0, None),
        ("energy_production", "Energieproduktion", 0, None),
        ("food_cu", "Auslastung Nahrung (%)", 0, _pct),
        ("goods_cu", "Auslastung Güter (%)", 0, _pct),
    ]),
    ("Bestände", [
        ("food_available", "Nahrung verfügbar", 0, None),
        ("goods_available", "Güter verfügbar", 0, None),
        ("energy_available", "Energie verfügbar", 0, None),
    ]),
    ("Umwelt", [
        ("environment", "Umweltqualität (%)", 1, _pct),
        ("env_load", "Umweltbelastung", 2, None),
    ]),
    ("Finanzen", [
        ("debt", "Schulden", 0, None),
        ("debt_export_ratio", "Schulden/Exporte", 2, None),
        ("annual_interest", "Zinssatz (%/Jahr)", 1, None),
        ("interest_paid", "Gezahlte Zinsen", 0, None),
        ("import_mult", "Importpreis-Faktor", 2, None),
        ("export_money", "Exporterlöse", 0, None),
        ("import_spending", "Importausgaben", 0, None),
        ("new_loans", "Neue Kredite", 0, None),
        ("repayments", "Tilgung", 0, None),
        ("imf_paid", "IMF-Rückzahlung", 0, None),
    ]),
    ("Kapitalstöcke", [(k, label, 0, None) for k, label in _CAPITALS]),
    ("Wirtschaft", [
        ("gdp", "GDP-Index", 1, None),
        ("gdp_pc", "GDP/Kopf-Index", 1, None),
    ]),
]

_SCORE_PARTS = [
    ("food", "Nahrung/Kopf"),
    ("goods", "Güter/Kopf"),
    ("environment", "Umwelt"),
    ("debt", "Schulden"),
    ("population", "Bevölkerung"),
]


def _value(rec: dict, key: str, conv=None):
    v = rec.get(key) if isinstance(rec, dict) else None
    if v is None or isinstance(v, bool):
        return None
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return conv(v) if conv else v


def _series(history: list[dict], key: str, conv=None) -> list[tuple[float, float]]:
    pts = []
    for i, rec in enumerate(history):
        v = _value(rec, key, conv)
        if v is not None:
            cycle = rec.get("runde", i) if isinstance(rec, dict) else i
            try:
                cycle = float(cycle)
            except (TypeError, ValueError):
                cycle = float(i)
            pts.append((cycle, v))
    return pts


# =============================================================================
# Engine-Zugriff (robust gegen fehlende Erweiterungen)
# =============================================================================

def _history(obj) -> list[dict]:
    """Akzeptiert eine Engine oder direkt eine history-Liste."""
    if isinstance(obj, list):
        return [r for r in obj if isinstance(r, dict)]
    hist = getattr(obj, "history", None)
    return [r for r in hist if isinstance(r, dict)] if isinstance(hist, list) else []


def _scenario_key(obj, history) -> str:
    key = getattr(obj, "scenario", None)
    if not key and history:
        key = history[0].get("scenario")
    return str(key or "standard")


def _scenario_name(key: str) -> str:
    try:
        import equivara_engine
        sc = getattr(equivara_engine, "SCENARIOS", {}) or {}
        entry = sc.get(key)
        if isinstance(entry, dict) and entry.get("name"):
            return str(entry["name"])
    except Exception:
        pass
    return "Standard" if key == "standard" else key


def _events_enabled(obj, history):
    val = getattr(obj, "events_enabled", None)
    if val is None:
        if any(isinstance(r.get("event"), dict) for r in history):
            return True
        return None
    return bool(val)


def _score(obj):
    fn = getattr(obj, "score", None)
    if not callable(fn):
        return None
    try:
        sc = fn()
    except Exception:
        return None
    return sc if isinstance(sc, dict) else None


def _upcoming_event(obj):
    fn = getattr(obj, "current_event", None)
    if not callable(fn) or getattr(obj, "game_over", False):
        return None
    try:
        ev = fn()
    except Exception:
        return None
    return ev if isinstance(ev, dict) else None


def _total_cycles(obj) -> int:
    try:
        return int(getattr(obj, "TOTAL_CYCLES", 12))
    except (TypeError, ValueError):
        return 12


# =============================================================================
# SVG-Liniendiagramm
# =============================================================================

def _nice_step(span: float, target: int) -> float:
    raw = span / max(1, target)
    mag = 10 ** math.floor(math.log10(raw))
    for m in (1, 2, 5, 10):
        if m * mag >= raw * (1 - 1e-9):
            return m * mag
    return 10 * mag


def _nice_ticks(lo: float, hi: float, target: int = 5) -> tuple[float, float, list[float], int]:
    """Achsenbereich und Ticks mit Schrittweiten 1/2/5 · 10^k.

    Gibt (min, max, ticks, dezimalstellen) zurück.
    """
    if hi < lo:
        lo, hi = hi, lo
    if hi - lo < 1e-12:
        pad = abs(hi) * 0.1 if hi else 1.0
        lo, hi = lo - pad, hi + pad
    step = _nice_step(hi - lo, target)
    t0 = math.floor(lo / step + 1e-9) * step
    t1 = math.ceil(hi / step - 1e-9) * step
    n = int(round((t1 - t0) / step))
    ticks = [round(t0 + i * step, 10) for i in range(n + 1)]
    t0, t1 = ticks[0], ticks[-1]
    dec = max(0, -int(math.floor(math.log10(step) + 1e-9)))
    return t0, t1, ticks, dec


_VB_W, _VB_H = 460, 250
_M_L, _M_R, _M_T, _M_B = 62, 14, 14, 44


def _svg_line_chart(series: list[tuple[str, int, list[tuple[float, float]]]], *,
                    y_label: str, x_label: str = "Zyklus (je 5 Jahre)",
                    reference: tuple[float, str] | None = None,
                    y_fixed: tuple[float, float] | None = None,
                    x_max: float | None = None, aria: str = "", dec: int = 1) -> str:
    """series: [(Name, Farbindex, [(x, y), ...]), ...]"""
    all_pts = [p for _, _, pts in series for p in pts]
    if not all_pts:
        return '<p class="empty">Keine Daten vorhanden.</p>'

    xs = [p[0] for p in all_pts]
    ys = [p[1] for p in all_pts]
    x_lo, x_hi = 0.0, max(max(xs), x_max or 0.0, 1.0)

    if y_fixed:
        y_lo, y_hi = y_fixed
        y_lo = min(y_lo, min(ys))
        y_hi = max(y_hi, max(ys))
    else:
        y_lo, y_hi = min(ys), max(ys)
        if reference:
            y_lo, y_hi = min(y_lo, reference[0]), max(y_hi, reference[0])
        # Nullpunkt einbeziehen, wenn die Werte nicht weit von 0 entfernt liegen.
        if y_lo > 0 and y_lo < 0.45 * y_hi:
            y_lo = 0.0
    y0, y1, yticks, ydec = _nice_ticks(y_lo, y_hi, 5)

    pw = _VB_W - _M_L - _M_R
    ph = _VB_H - _M_T - _M_B

    def sx(x):
        return _M_L + (x - x_lo) / (x_hi - x_lo) * pw

    def sy(y):
        return _M_T + (1 - (y - y0) / (y1 - y0)) * ph

    out = [f'<svg class="chart" viewBox="0 0 {_VB_W} {_VB_H}" role="img" '
           f'aria-label="{_esc(aria)}" preserveAspectRatio="xMidYMid meet">']

    # Gitter + y-Ticks
    for t in yticks:
        y = sy(t)
        out.append(f'<line class="grid" x1="{_M_L}" y1="{y:.1f}" x2="{_VB_W - _M_R}" y2="{y:.1f}"/>')
        out.append(f'<text class="tick" x="{_M_L - 7}" y="{y + 4:.1f}" text-anchor="end">'
                   f'{_num(t, ydec)}</text>')

    # x-Ticks (ganze Zyklen, bei vielen Zyklen ausgedünnt)
    xstep = 1 if x_hi <= 13 else _nice_step(x_hi, 8)
    xt = 0.0
    while xt <= x_hi + 1e-9:
        x = sx(xt)
        out.append(f'<line class="axis" x1="{x:.1f}" y1="{_M_T + ph}" x2="{x:.1f}" y2="{_M_T + ph + 4}"/>')
        out.append(f'<text class="tick" x="{x:.1f}" y="{_M_T + ph + 17}" text-anchor="middle">'
                   f'{_num(xt, 0)}</text>')
        xt += xstep

    # Achsen
    out.append(f'<line class="axis" x1="{_M_L}" y1="{_M_T + ph}" x2="{_VB_W - _M_R}" y2="{_M_T + ph}"/>')
    out.append(f'<line class="axis" x1="{_M_L}" y1="{_M_T}" x2="{_M_L}" y2="{_M_T + ph}"/>')
    out.append(f'<text class="axis-label" x="{_M_L + pw / 2:.1f}" y="{_VB_H - 6}" '
               f'text-anchor="middle">{_esc(x_label)}</text>')
    cy = _M_T + ph / 2
    out.append(f'<text class="axis-label" x="14" y="{cy:.1f}" text-anchor="middle" '
               f'transform="rotate(-90 14 {cy:.1f})">{_esc(y_label)}</text>')

    # Referenzlinie
    if reference and y0 <= reference[0] <= y1:
        y = sy(reference[0])
        out.append(f'<line class="ref" x1="{_M_L}" y1="{y:.1f}" x2="{_VB_W - _M_R}" y2="{y:.1f}"/>')
        out.append(f'<text class="ref-label" x="{_VB_W - _M_R - 4}" y="{y - 5:.1f}" '
                   f'text-anchor="end">{_esc(reference[1])}</text>')

    # Linien
    for name, color, pts in series:
        if not pts:
            continue
        cls = f"s{color % 6}"
        if len(pts) > 1:
            d = " ".join(f"{sx(x):.1f},{sy(y):.1f}" for x, y in pts)
            out.append(f'<polyline class="line {cls}" points="{d}"/>')
        r = 2.6 if len(pts) <= 14 else 0
        for x, y in pts:
            if r or (x, y) == pts[-1]:
                out.append(f'<circle class="dot {cls}" cx="{sx(x):.1f}" cy="{sy(y):.1f}" r="{r or 2.6}">'
                           f'<title>{_esc(name)} – Zyklus {_num(x, 0)}: {_num(y, dec)}</title></circle>')
    out.append("</svg>")
    return "".join(out)


def _legend(items: list[tuple[str, int]]) -> str:
    li = "".join(f'<li><span class="swatch s{c % 6}"></span>{_esc(n)}</li>' for n, c in items)
    return f'<ul class="legend">{li}</ul>'


def _figure(title: str, svg: str, legend: str = "", note: str = "") -> str:
    note_html = f'<p class="fig-note">{note}</p>' if note else ""
    return (f'<figure class="fig"><figcaption>{_esc(title)}</figcaption>'
            f'{legend}{svg}{note_html}</figure>')


# =============================================================================
# HTML-Bausteine
# =============================================================================

def _tiles(history: list[dict]) -> str:
    first, last = history[0], history[-1]
    out = []
    for key, (label, unit, dec, conv) in _METRICS.items():
        v1 = _value(last, key, conv)
        v0 = _value(first, key, conv)
        delta = ""
        if v1 is not None and v0 is not None and len(history) > 1:
            d = v1 - v0
            # Bei Schulden ist ein Anstieg schlecht, sonst gut.
            good = (d < 0) if key == "debt" else (d > 0)
            cls = "neutral" if abs(d) < 0.5 * 10 ** (-dec) else ("up" if good else "down")
            unit_short = " %-Pkt." if key == "environment" else ""
            delta = f'<span class="delta {cls}">{_signed(d, dec)}{unit_short} seit Start</span>'
        warn = ""
        if key == "food_pc" and v1 is not None and v1 < 2.0:
            warn = " warn"
        if key == "environment" and v1 is not None and v1 < 60:
            warn = " warn"
        out.append(f'<div class="tile{warn}"><div class="tile-label">{_esc(label)}</div>'
                   f'<div class="tile-value">{_num(v1, dec)}'
                   f'{" %" if key == "environment" else ""}</div>'
                   f'<div class="tile-unit">{_esc(unit if key != "environment" else "Umwelt")}</div>'
                   f'{delta}</div>')
    return f'<div class="tiles">{"".join(out)}</div>'


def _score_block(score: dict | None) -> str:
    if not score:
        return ('<div class="score score-missing"><p>Für diesen Spielstand ist keine '
                'Gesamtbewertung verfügbar.</p></div>')
    try:
        total = float(score.get("total", 0.0))
    except (TypeError, ValueError):
        total = 0.0
    grade = _esc(score.get("grade", "–"))
    comment = score.get("comment") or ""
    parts = score.get("parts") or {}
    rows = []
    known = [k for k, _ in _SCORE_PARTS]
    labels = dict(_SCORE_PARTS)
    for key in known + [k for k in parts if k not in known]:
        p = parts.get(key)
        if not isinstance(p, (list, tuple)) or len(p) < 2:
            continue
        try:
            pts, mx = float(p[0]), float(p[1])
        except (TypeError, ValueError):
            continue
        frac = max(0.0, min(1.0, pts / mx)) if mx > 0 else 0.0
        rows.append(f'<div class="part"><span class="part-label">{_esc(labels.get(key, key))}</span>'
                    f'<span class="bar"><span style="width:{frac * 100:.1f}%"></span></span>'
                    f'<span class="part-val">{_num(pts, 1)} / {_num(mx, 0)}</span></div>')
    return (f'<div class="score"><div class="score-main"><div class="grade">{grade}</div>'
            f'<div><div class="score-total">{_num(total, 1)}<small> / 100 Punkte</small></div>'
            f'<p class="score-comment">{_esc(comment)}</p></div></div>'
            f'<div class="parts">{"".join(rows)}</div></div>')


def _events_block(obj, history: list[dict], enabled) -> str:
    items = []
    for i, rec in enumerate(history[1:], start=1):
        ev = rec.get("event")
        if isinstance(ev, dict):
            cyc = rec.get("runde", i)
            items.append(f'<li><span class="ev-cycle">Zyklus {_esc(cyc)}</span>'
                         f'<strong>{_esc(ev.get("name", ev.get("key", "Ereignis")))}</strong>'
                         f'<span class="ev-desc">{_esc(ev.get("description", ""))}</span></li>')
    upcoming = _upcoming_event(obj)
    if upcoming:
        items.append(f'<li class="upcoming"><span class="ev-cycle">angekündigt für Zyklus '
                     f'{_esc(getattr(obj, "runde", "?"))}</span>'
                     f'<strong>{_esc(upcoming.get("name", upcoming.get("key", "Ereignis")))}</strong>'
                     f'<span class="ev-desc">{_esc(upcoming.get("description", ""))}</span></li>')
    if items:
        return f'<ul class="events">{"".join(items)}</ul>'
    if enabled is False:
        return '<p class="empty">Zufallsereignisse waren in diesem Spiel ausgeschaltet.</p>'
    if enabled is None:
        return '<p class="empty">Dieser Spielstand enthält keine Ereignisdaten.</p>'
    return '<p class="empty">In diesem Spiel ist kein Ereignis eingetreten.</p>'


def _history_table(history: list[dict]) -> str:
    head = ['<th class="rowhead" scope="col">Kennzahl</th>']
    for i, rec in enumerate(history):
        cyc = rec.get("runde", i)
        year = rec.get("jahr_end", i * 5)
        label = "Start" if i == 0 else f"Z{_esc(cyc)}"
        head.append(f'<th scope="col">{label}<small>Jahr {_esc(year)}</small></th>')
    body = []
    ncols = len(history) + 1
    for group, rows in _TABLE:
        body.append(f'<tr class="group"><th colspan="{ncols}" scope="rowgroup">{_esc(group)}</th></tr>')
        for key, label, dec, conv in rows:
            cells = "".join(f"<td>{_num(_value(rec, key, conv), dec)}</td>" for rec in history)
            body.append(f'<tr><th scope="row" class="rowhead">{_esc(label)}</th>{cells}</tr>')
    return (f'<div class="table-wrap"><table class="history"><thead><tr>{"".join(head)}</tr></thead>'
            f'<tbody>{"".join(body)}</tbody></table></div>')


# =============================================================================
# CSS
# =============================================================================

_CSS = """
:root {
  color-scheme: light dark;
  --bg: #f6f7f9; --paper: #ffffff; --text: #1d2330; --muted: #5d6676; --line: #dfe3ea;
  --grid: #e9ecf1; --axis: #8a93a3; --accent: #2457c5; --good: #18794e; --bad: #c0392b;
  --warn-bg: #fff4e5; --bar-bg: #e7eaf0; --ref: #c0392b;
  --s0: #2563eb; --s1: #e8590c; --s2: #0f8a5f; --s3: #c2255c; --s4: #7048e8; --s5: #a07800;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #12151b; --paper: #1b1f27; --text: #e6e9ef; --muted: #9aa3b2; --line: #2d333e;
    --grid: #262b35; --axis: #6f7888; --accent: #7aa2ff; --good: #4cc38a; --bad: #ff7b6b;
    --warn-bg: #3a2a14; --bar-bg: #2a303b; --ref: #ff7b6b;
    --s0: #6ea0ff; --s1: #ff9a52; --s2: #3fcf8e; --s3: #f06595; --s4: #a18bff; --s5: #e0b93a;
  }
}
* { box-sizing: border-box; }
html { -webkit-text-size-adjust: 100%; }
body {
  margin: 0; background: var(--bg); color: var(--text);
  font: 15px/1.55 "Segoe UI", system-ui, -apple-system, "Helvetica Neue", Arial, sans-serif;
  font-variant-numeric: tabular-nums;
}
main { max-width: 1060px; margin: 0 auto; padding: 32px 20px 56px; }
h1 { font-size: 1.9rem; line-height: 1.2; margin: 0 0 6px; letter-spacing: -0.01em; }
h2 { font-size: 1.45rem; margin: 0 0 4px; letter-spacing: -0.01em; }
h3 { font-size: 1.05rem; margin: 28px 0 10px; color: var(--muted); text-transform: uppercase;
     letter-spacing: 0.06em; font-weight: 600; }
p { margin: 0 0 8px; }
.report-head { border-bottom: 2px solid var(--text); padding-bottom: 14px; margin-bottom: 26px; }
.meta { display: flex; flex-wrap: wrap; gap: 6px 22px; color: var(--muted); margin: 8px 0 0;
        padding: 0; list-style: none; }
.meta strong { color: var(--text); font-weight: 600; }
.hint { font-size: 0.85rem; color: var(--muted); margin-top: 10px; }
section.block { background: var(--paper); border: 1px solid var(--line); border-radius: 10px;
                padding: 22px 24px; margin: 0 0 24px; }
.player-head { display: flex; flex-wrap: wrap; align-items: baseline; justify-content: space-between;
               gap: 4px 18px; }
.player-head .sub { color: var(--muted); }
.tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 10px; }
.tile { border: 1px solid var(--line); border-radius: 8px; padding: 10px 12px; break-inside: avoid; }
.tile.warn { background: var(--warn-bg); }
.tile-label { font-size: 0.8rem; color: var(--muted); font-weight: 600; }
.tile-value { font-size: 1.5rem; font-weight: 650; line-height: 1.25; }
.tile-unit { font-size: 0.75rem; color: var(--muted); }
.delta { display: block; font-size: 0.8rem; margin-top: 2px; }
.delta.up { color: var(--good); } .delta.down { color: var(--bad); } .delta.neutral { color: var(--muted); }
.score { display: grid; grid-template-columns: minmax(220px, 1fr) minmax(260px, 1.3fr); gap: 14px 28px;
         align-items: center; margin: 16px 0 4px; break-inside: avoid; }
.score-missing { display: block; color: var(--muted); }
.score-main { display: flex; gap: 16px; align-items: center; }
.grade { width: 64px; height: 64px; border-radius: 50%; display: grid; place-items: center;
         font-size: 2rem; font-weight: 700; background: var(--accent); color: var(--paper); flex: none; }
.score-total { font-size: 1.6rem; font-weight: 650; }
.score-total small { font-size: 0.85rem; color: var(--muted); font-weight: 400; }
.score-comment { color: var(--muted); margin: 2px 0 0; }
.part { display: grid; grid-template-columns: 110px 1fr 76px; gap: 10px; align-items: center;
        font-size: 0.85rem; margin: 3px 0; }
.bar { height: 8px; background: var(--bar-bg); border-radius: 4px; overflow: hidden; }
.bar span { display: block; height: 100%; background: var(--accent); }
.part-val { text-align: right; color: var(--muted); }
.charts { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 18px; }
.fig { margin: 0; border: 1px solid var(--line); border-radius: 8px; padding: 12px 12px 6px;
       break-inside: avoid; page-break-inside: avoid; }
.fig figcaption { font-weight: 600; margin-bottom: 4px; }
.fig-note { font-size: 0.8rem; color: var(--muted); margin: 2px 0 4px; }
svg.chart { display: block; width: 100%; height: auto; overflow: visible;
            font-family: inherit; font-variant-numeric: tabular-nums; }
svg .grid { stroke: var(--grid); stroke-width: 1; }
svg .axis { stroke: var(--axis); stroke-width: 1; }
svg .tick { fill: var(--muted); font-size: 11.5px; }
svg .axis-label { fill: var(--text); font-size: 12px; font-weight: 600; }
svg .ref { stroke: var(--ref); stroke-width: 1.4; stroke-dasharray: 5 4; }
svg .ref-label { fill: var(--ref); font-size: 11.5px; font-weight: 600; }
svg .line { fill: none; stroke-width: 2.2; stroke-linejoin: round; stroke-linecap: round; }
svg .dot { stroke: var(--paper); stroke-width: 1; }
.s0 { stroke: var(--s0); } .s1 { stroke: var(--s1); } .s2 { stroke: var(--s2); }
.s3 { stroke: var(--s3); } .s4 { stroke: var(--s4); } .s5 { stroke: var(--s5); }
circle.s0, .swatch.s0 { fill: var(--s0); background: var(--s0); }
circle.s1, .swatch.s1 { fill: var(--s1); background: var(--s1); }
circle.s2, .swatch.s2 { fill: var(--s2); background: var(--s2); }
circle.s3, .swatch.s3 { fill: var(--s3); background: var(--s3); }
circle.s4, .swatch.s4 { fill: var(--s4); background: var(--s4); }
circle.s5, .swatch.s5 { fill: var(--s5); background: var(--s5); }
.legend { display: flex; flex-wrap: wrap; gap: 4px 16px; list-style: none; padding: 0; margin: 0 0 6px;
          font-size: 0.82rem; color: var(--muted); }
.legend li { display: flex; align-items: center; gap: 6px; }
.swatch { width: 14px; height: 4px; border-radius: 2px; display: inline-block; }
.events { list-style: none; padding: 0; margin: 0; }
.events li { display: grid; grid-template-columns: 170px 1fr; gap: 0 14px; padding: 7px 0;
             border-bottom: 1px solid var(--line); break-inside: avoid; }
.events li:last-child { border-bottom: 0; }
.events .ev-cycle { color: var(--muted); grid-row: span 2; }
.events .ev-desc { color: var(--muted); font-size: 0.9rem; }
.events li.upcoming strong::after { content: " (bevorstehend)"; font-weight: 400; color: var(--muted); }
.empty { color: var(--muted); font-style: italic; }
.table-wrap { overflow-x: auto; border: 1px solid var(--line); border-radius: 8px; }
table.history { border-collapse: collapse; width: 100%; font-size: 0.8rem; }
table.history th, table.history td { padding: 4px 7px; text-align: right; white-space: nowrap;
                                     border-bottom: 1px solid var(--grid); }
table.history thead th { position: sticky; top: 0; background: var(--paper); font-weight: 600;
                         border-bottom: 1px solid var(--axis); vertical-align: bottom; }
table.history thead th small { display: block; font-weight: 400; color: var(--muted); font-size: 0.72rem; }
table.history .rowhead { text-align: left; font-weight: 500; position: sticky; left: 0;
                         background: var(--paper); }
table.history tr.group th { text-align: left; background: var(--bar-bg); font-weight: 650;
                            text-transform: uppercase; letter-spacing: 0.05em; font-size: 0.72rem; }
table.history tbody tr:not(.group):hover td, table.history tbody tr:not(.group):hover th { background: var(--grid); }
footer { color: var(--muted); font-size: 0.8rem; text-align: center; margin-top: 30px; }
@media (max-width: 720px) {
  .charts { grid-template-columns: 1fr; }
  .score { grid-template-columns: 1fr; }
  .events li { grid-template-columns: 1fr; }
  .events .ev-cycle { grid-row: auto; }
  section.block { padding: 16px; }
}

@page { size: A4 portrait; margin: 14mm 12mm 16mm; }
@media print {
  :root {
    color-scheme: light;
    --bg: #ffffff; --paper: #ffffff; --text: #111111; --muted: #4a4f59; --line: #c9ced6;
    --grid: #e3e6eb; --axis: #6b7280; --accent: #1f4fb8; --good: #126b42; --bad: #b02a1e;
    --warn-bg: #fff4e5; --bar-bg: #e7eaf0; --ref: #b02a1e;
    --s0: #1f5fd6; --s1: #d9480f; --s2: #0b7a52; --s3: #b01e55; --s4: #5f3dc4; --s5: #8a6a00;
  }
  * { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
  body { font-size: 9.5pt; line-height: 1.4; background: #fff; }
  main { max-width: none; padding: 0; }
  h1 { font-size: 18pt; } h2 { font-size: 14pt; } h3 { font-size: 9.5pt; margin: 14pt 0 6pt; }
  h2, h3 { break-after: avoid; page-break-after: avoid; }
  .hint { display: none; }
  section.block { border: 0; padding: 0; margin: 0; border-radius: 0; }
  section.player + section.player, section.compare + section.player, section.table-block { break-before: page; page-break-before: always; }
  .charts { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8pt; }
  .fig, .tile, .score, .events li, .tiles, table.history tr { break-inside: avoid; page-break-inside: avoid; }
  .fig { padding: 6pt 6pt 2pt; }
  .tiles { grid-template-columns: repeat(6, 1fr); gap: 6pt; }
  .tile { padding: 5pt 6pt; } .tile-value { font-size: 13pt; }
  .table-wrap { overflow: visible; border: 0; }
  table.history { font-size: 6.6pt; }
  table.history th, table.history td { padding: 1.6pt 3pt; }
  table.history thead { display: table-header-group; }
  table.history thead th, table.history .rowhead { position: static; }
  footer { margin-top: 12pt; }
}
"""


# =============================================================================
# Öffentliche API
# =============================================================================

def export_html(path, runs, title: str = "Equivara Bericht") -> None:
    """Schreibt einen eigenständigen HTML-Bericht für einen oder mehrere Spieler.

    runs: Liste von (Name, EquivaraEngine). Statt einer Engine wird auch
    direkt eine history-Liste (list[dict]) akzeptiert.
    """
    path = Path(path)
    prepared = []
    for idx, (name, obj) in enumerate(runs or []):
        hist = _history(obj)
        if not hist:
            continue
        prepared.append({
            "name": str(name) if str(name).strip() else f"Spieler {idx + 1}",
            "obj": obj,
            "history": hist,
            "color": len(prepared) % 6,
            "scenario": _scenario_key(obj, hist),
            "events": _events_enabled(obj, hist),
            "seed": getattr(obj, "seed", None),
            "score": _score(obj),
            "cycles": _total_cycles(obj),
        })

    now = datetime.now()
    date_str = now.strftime("%d.%m.%Y, %H:%M Uhr")

    def events_text(v):
        return "an" if v is True else ("aus" if v is False else "unbekannt")

    scen = sorted({p["scenario"] for p in prepared})
    evs = {p["events"] for p in prepared}
    meta = [f"<li>Erstellt: <strong>{_esc(date_str)}</strong></li>"]
    if prepared:
        scen_txt = (_scenario_name(scen[0]) if len(scen) == 1
                    else "verschieden (siehe Spieler)")
        ev_txt = events_text(next(iter(evs))) if len(evs) == 1 else "verschieden (siehe Spieler)"
        meta.append(f"<li>Szenario: <strong>{_esc(scen_txt)}</strong></li>")
        meta.append(f"<li>Zufallsereignisse: <strong>{_esc(ev_txt)}</strong></li>")
        meta.append(f"<li>Spieler: "
                    f"<strong>{_esc(', '.join(p['name'] for p in prepared))}</strong></li>")

    parts = [
        "<!DOCTYPE html>",
        '<html lang="de"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f"<title>{_esc(title)}</title>",
        f"<style>{_CSS}</style></head><body><main>",
        f'<header class="report-head"><h1>{_esc(title)}</h1><ul class="meta">{"".join(meta)}</ul>',
        '<p class="hint">Tipp: Über „Drucken“ → „Als PDF speichern“ lässt sich dieser Bericht '
        'als PDF ablegen (A4, helle Darstellung).</p></header>',
    ]

    if not prepared:
        parts.append('<section class="block"><p class="empty">Keine Spieldaten vorhanden.</p></section>')

    multi = len(prepared) > 1
    x_max = max([p["cycles"] for p in prepared] + [0])

    # --- Gemeinsamer Vergleich bei mehreren Spielern --------------------------
    if multi:
        legend = _legend([(p["name"], p["color"]) for p in prepared])
        figs = []
        for key, ctitle, ylab, ref, fixed in _CHARTS:
            conv = _METRICS[key][3]
            series = [(p["name"], p["color"], _series(p["history"], key, conv)) for p in prepared]
            svg = _svg_line_chart(series, y_label=ylab, reference=ref, y_fixed=fixed, x_max=x_max,
                                  aria=f"{ctitle} – alle Spieler", dec=_METRICS[key][2])
            figs.append(_figure(ctitle, svg, legend))
        rows = []
        for p in prepared:
            last = p["history"][-1]
            sc = p["score"]
            cells = "".join(f"<td>{_num(_value(last, k, _METRICS[k][3]), _METRICS[k][2])}</td>"
                            for k in _METRICS)
            sc_cell = (f"{_num(sc.get('total'), 1)} ({_esc(sc.get('grade', '–'))})" if sc else "–")
            rows.append(f'<tr><th scope="row" class="rowhead"><span class="swatch s{p["color"]}"></span> '
                        f'{_esc(p["name"])}</th><td>{sc_cell}</td>{cells}</tr>')
        head = "".join(f"<th scope=\"col\">{_esc(lbl)}</th>" for lbl, *_ in _METRICS.values())
        parts.append(
            '<section class="block compare"><h2>Vergleich aller Spieler</h2>'
            '<h3>Endstand</h3><div class="table-wrap"><table class="history">'
            f'<thead><tr><th class="rowhead" scope="col">Spieler</th><th scope="col">Score</th>{head}</tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table></div>'
            f'<h3>Verläufe</h3><div class="charts">{"".join(figs)}</div></section>')

    # --- Je Spieler ------------------------------------------------------------
    for p in prepared:
        hist, name = p["history"], p["name"]
        played = max(0, len(hist) - 1)
        status = "Spiel beendet" if getattr(p["obj"], "game_over", False) or played >= p["cycles"] \
            else "Spiel läuft"
        sub = [f"{played} von {p['cycles']} Zyklen gespielt · {status}"]
        sub.append(f"Szenario {_scenario_name(p['scenario'])}")
        sub.append(f"Ereignisse {events_text(p['events'])}")
        if p["seed"] is not None:
            sub.append(f"Seed {p['seed']}")

        figs = []
        if not multi:
            for key, ctitle, ylab, ref, fixed in _CHARTS:
                conv = _METRICS[key][3]
                series = [(name, p["color"], _series(hist, key, conv))]
                svg = _svg_line_chart(series, y_label=ylab, reference=ref, y_fixed=fixed, x_max=x_max,
                                      aria=f"{ctitle} – {name}", dec=_METRICS[key][2])
                figs.append(_figure(ctitle, svg))
        cap_series = [(label, i, _series(hist, key)) for i, (key, label) in enumerate(_CAPITALS)]
        cap_svg = _svg_line_chart(cap_series, y_label="Kapitalstock", x_max=x_max,
                                  aria=f"Kapitalstöcke – {name}", dec=0)
        cap_fig = _figure("Kapitalstöcke", cap_svg, _legend([(lbl, i) for i, (_, lbl) in enumerate(_CAPITALS)]))

        parts.append(
            f'<section class="block player"><div class="player-head"><h2>{_esc(name)}</h2>'
            f'<span class="sub">{_esc(" · ".join(sub))}</span></div>'
            f'{_score_block(p["score"])}'
            f'<h3>Endwerte</h3>{_tiles(hist)}'
            + (f'<h3>Verläufe</h3><div class="charts">{"".join(figs)}{cap_fig}</div>' if figs
               else f'<h3>Kapitalstöcke</h3><div class="charts">{cap_fig}</div>')
            + f'<h3>Ereignisse</h3>{_events_block(p["obj"], hist, p["events"])}'
            '</section>')

    # --- Verlaufstabellen -------------------------------------------------------
    for p in prepared:
        parts.append(f'<section class="block table-block"><h2>Verlaufstabelle – {_esc(p["name"])}</h2>'
                     f'<h3>Alle Kennzahlen je Zyklus</h3>{_history_table(p["history"])}</section>')

    parts.append(f'<footer>Equivara · Modell inspiriert von STRATAGEM-1 (Meadows et al.) · '
                 f'Bericht erstellt am {_esc(date_str)}</footer></main></body></html>')

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text("\n".join(parts), encoding="utf-8")
    tmp.replace(path)


def export_canvas_png(canvas, path) -> bool:
    """Speichert den sichtbaren Bildschirmbereich des Canvas als PNG.

    Benötigt Pillow (PIL.ImageGrab). Gibt False zurück, wenn Pillow fehlt
    oder die Aufnahme fehlschlägt.
    """
    try:
        from PIL import ImageGrab
    except ImportError:
        return False
    try:
        canvas.update_idletasks()
        canvas.update()
        x, y = canvas.winfo_rootx(), canvas.winfo_rooty()
        w, h = canvas.winfo_width(), canvas.winfo_height()
        if w <= 1 or h <= 1:
            return False
        try:
            img = ImageGrab.grab(bbox=(x, y, x + w, y + h), all_screens=True)
        except TypeError:   # ältere Pillow-Versionen ohne all_screens
            img = ImageGrab.grab(bbox=(x, y, x + w, y + h))
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        img.save(str(path), "PNG")
        return True
    except Exception:
        return False


# =============================================================================
# Demo
# =============================================================================

if __name__ == "__main__":
    import sys
    import tempfile

    from equivara_engine import EquivaraEngine

    def make_engine(**kw):
        try:
            return EquivaraEngine(**kw)
        except TypeError:   # Engine ohne Szenario-/Ereignis-Unterstützung
            return EquivaraEngine()

    engines = [("Anna", make_engine()),
               ("Ben", make_engine(scenario="verschuldet", events_enabled=True, seed=7))]
    for _, eng in engines:
        for _ in range(EquivaraEngine.TOTAL_CYCLES):
            if eng.game_over:
                break
            eng.apply(eng.suggest_inputs())

    out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(tempfile.mkdtemp(prefix="equivara_"))
    target = out_dir / "equivara_bericht.html"
    export_html(target, engines)
    print(f"Bericht geschrieben: {target}")
