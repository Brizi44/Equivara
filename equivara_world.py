"""Equivara – Welt: mehrere Länder, gemeinsamer Weltmarkt und Rollen.

Die Welt bündelt ein oder mehrere Länder (je eine eigene ``EquivaraEngine``)
und steuert die Zugreihenfolge (Hot-Seat). Je nach Modus gibt es einen fixen
Weltmarkt (bisheriges Verhalten) oder einen gemeinsamen Markt, auf dem sich
die Preise aus Angebot und Nachfrage aller Länder bilden.

Preisbildung im Modus "handel" (pro Gut: Nahrung, Güter, Energie)
------------------------------------------------------------------
1. Angebot  S = Summe der Exportmengen aller Länder in diesem Zyklus.
   Nachfrage D = Summe der Importmengen aller Länder (Importbudget / Preis).
2. Rest der Welt (RdW): Ein fiktiver Puffer B = ROW_BUFFER[gut] * Anzahl Länder
   steht auf BEIDEN Seiten des Marktes (er kauft und verkauft jeweils B
   Einheiten zum Normalpreis). Dadurch bewegen kleine Mengen die Preise kaum,
   und ein Markt ohne Händler (S = D = 0) bleibt beim Normalpreis.
3. Knappheitsverhältnis r = (D + B) / (S + B).
   r > 1 -> Knappheit, r < 1 -> Überangebot.
4. Zielfaktor f* = r ** ELASTICITY (ELASTICITY = 0.5, d.h. doppelte Knappheit
   -> ca. +41 % Preis). Der Zielfaktor bezieht sich auf den Normalpreis,
   eine dauerhafte Knappheit führt also zu einem stabilen höheren Preis und
   nicht zu einer endlosen Preisspirale.
5. Dämpfung: f_neu = f_alt + DAMPING * (f* - f_alt) mit DAMPING = 0.5 –
   der Preis bewegt sich pro Zyklus nur zur Hälfte auf das Ziel zu.
6. Grenzen: f_neu wird auf PRICE_MIN..PRICE_MAX (0.5 .. 2.0) begrenzt.
7. Exportpreis = Basis-Exportpreis * f, Importpreis = Basis-Importpreis * f
   (der Handelsaufschlag von 10 % bei Nahrung/Gütern bleibt erhalten).

Die neuen Preise gelten für den NÄCHSTEN Zyklus aller Länder und werden in
``engine.market`` jedes Landes geschrieben, damit Budgets, Prüfung, Vorschau
und Berater bereits mit den gültigen Preisen rechnen.

Handelssicherheit (optional): Ist bei einem Land das Ministerium
"verteidigung" aktiv, sinkt sein Importaufschlag (Importpreis - Exportpreis)
um bis zu SECURITY_DISCOUNT (25 %) * security. Ohne Ministerium keine Wirkung.

Mengenflüsse (``trade_flows``): Die gehandelte Menge eines Gutes ist
M = min(S, D). Jeder Exporteur liefert den Anteil M/S seiner Exporte an die
importierenden Länder (aufgeteilt nach deren Anteil an D); der Rest seiner
Exporte geht an den Weltmarkt (``to = None``). Jeder Importeur bezieht den
Anteil (1 - M/D) seiner Importe vom Weltmarkt (``from = None``). Lieferungen
eines Landes an sich selbst werden über den Weltmarkt umgebucht. In den
Modi ohne gemeinsamen Markt laufen alle Flüsse über den Weltmarkt.
"""

from __future__ import annotations

import copy
import inspect
import json
from dataclasses import dataclass, field

import equivara_engine as _eng
from equivara_engine import EquivaraEngine

try:  # THEME braucht tkinter nur zum Import; Fallback für Umgebungen ohne tk.
    from equivara_widgets import THEME as _THEME
except Exception:  # pragma: no cover
    _THEME = {"blue": "#4f8cff", "orange": "#f6ad55", "green": "#35c98a",
              "purple": "#9b7cff", "red": "#ef6a6a", "cyan": "#28c7d9"}

INPUT_KEYS = list(_eng.INPUT_KEYS)
ALL_INPUT_KEYS = list(getattr(_eng, "ALL_INPUT_KEYS", INPUT_KEYS + [
    "inv_health", "inv_education", "inv_infrastructure", "inv_defense"]))

COUNTRY_COLORS = [_THEME[k] for k in ("blue", "orange", "green", "purple", "red", "cyan")]

GOODS = ("food", "goods", "energy")
DEFAULT_MARKET = {"export_price": {"food": 1.0, "goods": 1.0, "energy": 1.0},
                  "import_price": {"food": 1.1, "goods": 1.1, "energy": 1.0}}

# Parameter der Preisbildung (siehe Moduldoku).
ROW_BUFFER = {"food": 1500.0, "goods": 1500.0, "energy": 2500.0}
ELASTICITY = 0.5
DAMPING = 0.5
PRICE_MIN = 0.5
PRICE_MAX = 2.0
SECURITY_DISCOUNT = 0.25

MODES = {
    "solo": {"name": "Solo",
             "description": "Ein Land, fester Weltmarkt – das klassische Equivara."},
    "wettbewerb": {"name": "Wettbewerb",
                   "description": "Mehrere Länder spielen nacheinander dasselbe Szenario ohne "
                                  "gegenseitige Beeinflussung; am Ende zählt die Rangliste."},
    "handel": {"name": "Handel",
               "description": "Mehrere Länder teilen einen Weltmarkt: Exporte bilden das Angebot, "
                              "Importe die Nachfrage. Knappheit verteuert ein Gut, Überangebot "
                              "macht es billiger."},
    "rollen": {"name": "Rollen",
               "description": "Ein Land, mehrere Personen: jede Rolle (Ministerium) entscheidet über "
                              "ihre Felder, das Präsidium gibt die Runde frei."},
}

# Jedes Feld aus ALL_INPUT_KEYS gehört genau einer Rolle.
ROLES = {
    "praesidium": {
        "name": "Präsidium",
        "description": "Legt das Investitionsbudget fest, sieht alle Entscheidungen und gibt die Runde frei.",
        "fields": ["goods_investment"],
        "requires_ministry": None,
    },
    "landwirtschaft": {
        "name": "Landwirtschaft",
        "description": "Nahrungsverteilung, Energie für die Landwirtschaft und Nahrungskapital.",
        "fields": ["food_domestic", "food_export", "energy_food", "inv_food"],
        "requires_ministry": None,
    },
    "industrie_energie": {
        "name": "Industrie & Energie",
        "description": "Güterkapital, Energieproduktion und -effizienz, Energieverteilung.",
        "fields": ["energy_goods", "energy_export", "energy_carryover",
                   "inv_goods", "inv_energy_prod", "inv_energy_eff"],
        "requires_ministry": None,
    },
    "umwelt": {
        "name": "Umwelt",
        "description": "Investitionen in Umweltschutzkapital.",
        "fields": ["inv_env"],
        "requires_ministry": None,
    },
    "finanzen_handel": {
        "name": "Finanzen & Handel",
        "description": "Güterexporte, Kredite, Tilgung, Auslandshilfe und Importbudgets.",
        "fields": ["goods_export", "foreign_aid", "new_loans", "repayments",
                   "import_energy_money", "import_food_money", "import_goods_money"],
        "requires_ministry": None,
    },
    "soziales": {
        "name": "Soziales",
        "description": "Güterversorgung der Bevölkerung und Humankapital.",
        "fields": ["goods_domestic", "inv_human"],
        "requires_ministry": None,
    },
    "gesundheit": {
        "name": "Gesundheit",
        "description": "Investitionen in das Gesundheitswesen.",
        "fields": ["inv_health"],
        "requires_ministry": "gesundheit",
    },
    "bildung": {
        "name": "Bildung",
        "description": "Investitionen in Schulen und Hochschulen.",
        "fields": ["inv_education"],
        "requires_ministry": "bildung",
    },
    "infrastruktur": {
        "name": "Infrastruktur",
        "description": "Investitionen in Verkehr und Logistik.",
        "fields": ["inv_infrastructure"],
        "requires_ministry": "infrastruktur",
    },
    "verteidigung": {
        "name": "Verteidigung",
        "description": "Investitionen in Sicherheit und Verteidigung.",
        "fields": ["inv_defense"],
        "requires_ministry": "verteidigung",
    },
}


def _ministry_active(engine, key) -> bool:
    ministries = getattr(engine, "ministries", None)
    return isinstance(ministries, dict) and bool(ministries.get(key))


def roles_for(engine) -> list[str]:
    """Verfügbare Rollen; Ministeriumsrollen nur, wenn das Ministerium aktiv ist."""
    out = []
    for key, role in ROLES.items():
        req = role["requires_ministry"]
        if req is None or _ministry_active(engine, req):
            out.append(key)
    return out


def role_of_field(field_key: str) -> str | None:
    for key, role in ROLES.items():
        if field_key in role["fields"]:
            return key
    return None


_KEEP = object()   # Sentinel: Ziel der Engines unverändert lassen


def _set_goal(engine, goal_cycles) -> None:
    """Ziel (Anzahl Zyklen, None = endlos) an eine Engine durchreichen."""
    engine.goal_cycles = None if goal_cycles is None else int(goal_cycles)
    if not getattr(engine, "continued", False):
        played = len(getattr(engine, "history", [None])) - 1
        engine.game_over = goal_cycles is not None and played >= int(goal_cycles)


def _goal_reached(engine) -> bool:
    if hasattr(engine, "goal_reached"):
        return bool(engine.goal_reached)
    goal = getattr(engine, "goal_cycles", getattr(engine, "TOTAL_CYCLES", 12))
    return goal is not None and len(engine.history) - 1 >= goal


@dataclass
class Country:
    name: str
    engine: EquivaraEngine
    color: str = COUNTRY_COLORS[0]
    roles: dict[str, str] = field(default_factory=dict)   # Rolle -> Personenname


def _flow_list(exports: list[dict], imports: list[dict]) -> list[dict]:
    """Mengenflüsse eines Zyklus aus Export-/Importmengen je Land (siehe Moduldoku)."""
    flows = []
    for good in GOODS:
        ex = [max(0.0, e.get(good, 0.0)) for e in exports]
        im = [max(0.0, i.get(good, 0.0)) for i in imports]
        supply, demand = sum(ex), sum(im)
        matched = min(supply, demand)
        pair = {}
        to_world = {i: 0.0 for i in range(len(ex))}
        from_world = {j: 0.0 for j in range(len(im))}
        for i, e in enumerate(ex):
            if e <= 0:
                continue
            traded = e * matched / supply if supply > 0 else 0.0
            to_world[i] += e - traded
            for j, d in enumerate(im):
                if d <= 0 or demand <= 0:
                    continue
                amount = traded * d / demand
                if i == j:   # an sich selbst -> über den Weltmarkt umbuchen
                    to_world[i] += amount
                    from_world[j] += amount
                else:
                    pair[(i, j)] = pair.get((i, j), 0.0) + amount
        for j, d in enumerate(im):
            if d > 0 and demand > 0:
                from_world[j] += d * (1.0 - matched / demand)
        for (i, j), amount in pair.items():
            if amount > 1e-6:
                flows.append({"from": i, "to": j, "good": good, "amount": amount})
        for i, amount in to_world.items():
            if amount > 1e-6:
                flows.append({"from": i, "to": None, "good": good, "amount": amount})
        for j, amount in from_world.items():
            if amount > 1e-6:
                flows.append({"from": None, "to": j, "good": good, "amount": amount})
    return flows


def new_prices(old: dict, supply: dict, demand: dict, n_countries: int) -> dict:
    """Neue Marktpreise aus Angebot/Nachfrage (siehe Moduldoku, Schritte 2–7)."""
    out = copy.deepcopy(DEFAULT_MARKET)
    for good in GOODS:
        base_ex = DEFAULT_MARKET["export_price"][good]
        base_im = DEFAULT_MARKET["import_price"][good]
        old_factor = old["export_price"][good] / base_ex
        buffer = ROW_BUFFER[good] * max(1, n_countries)
        ratio = (demand.get(good, 0.0) + buffer) / (supply.get(good, 0.0) + buffer)
        target = ratio ** ELASTICITY
        factor = old_factor + DAMPING * (target - old_factor)
        factor = min(PRICE_MAX, max(PRICE_MIN, factor))
        out["export_price"][good] = base_ex * factor
        out["import_price"][good] = base_im * factor
    return out


def _trade_of(record: dict | None, engine=None) -> tuple[dict, dict]:
    """Export-/Importmengen aus einem Ergebnis-Dict (mit Fallback ohne Markt-Hook)."""
    record = record or {}
    exports = record.get("exports")
    imports = record.get("imports")
    if not isinstance(exports, dict):
        last = getattr(engine, "last_inputs", None) or {}
        exports = {"food": float(last.get("food_export", 0.0)),
                   "goods": float(last.get("goods_export", 0.0)),
                   "energy": float(last.get("energy_export", 0.0))}
    if not isinstance(imports, dict):
        imports = {"food": float(record.get("food_import", 0.0)),
                   "goods": float(record.get("goods_import", 0.0)),
                   "energy": float(record.get("energy_import", 0.0))}
    return ({g: float(exports.get(g, 0.0)) for g in GOODS},
            {g: float(imports.get(g, 0.0)) for g in GOODS})


class World:
    """Eine Partie mit einem oder mehreren Ländern."""

    def __init__(self, mode: str, countries: list[Country], seed: int | None = None,
                 goal_cycles=_KEEP):
        if mode not in MODES:
            raise ValueError(f"Unbekannter Modus: {mode!r}")
        if not countries:
            raise ValueError("Mindestens ein Land wird benötigt.")
        if mode in ("solo", "rollen") and len(countries) != 1:
            raise ValueError(f"Modus {MODES[mode]['name']!r} erlaubt genau ein Land.")
        self.mode = mode
        self.countries = list(countries)
        self.seed = seed
        if goal_cycles is not _KEEP:
            if goal_cycles is not None and int(goal_cycles) < 1:
                raise ValueError("Ziel muss mindestens 1 Zyklus sein (oder None = endlos).")
            for c in self.countries:
                _set_goal(c.engine, goal_cycles)
        self.active = 0
        self.market = copy.deepcopy(DEFAULT_MARKET)
        self.market_history: list[dict] = []
        self._last_submit = None   # Undo-Info für den zuletzt eingereichten Zug
        self._sync_market()
        self.active = self._next_active(-1)

    # ------------------------------------------------------------------
    # Erzeugung
    # ------------------------------------------------------------------

    @classmethod
    def create(cls, mode: str, names: list[str], scenario: str = "standard",
               events_enabled: bool = False, seed: int | None = None,
               ministries: dict | None = None,
               roles: list[dict[str, str]] | None = None,
               goal_cycles=_KEEP) -> "World":
        """Bequemer Konstruktor: alle Länder mit gleichem Szenario und gleichem Seed
        (gleiche Ereignisse -> fairer Vergleich)."""
        countries = []
        shared_seed = seed
        for i, name in enumerate(names):
            kwargs = {"scenario": scenario, "events_enabled": events_enabled, "seed": shared_seed}
            params = inspect.signature(EquivaraEngine).parameters
            if ministries is not None and "ministries" in params:
                kwargs["ministries"] = dict(ministries)
            if goal_cycles is not _KEEP and "goal_cycles" in params:
                kwargs["goal_cycles"] = goal_cycles
            eng = EquivaraEngine(**kwargs)
            shared_seed = eng.seed
            countries.append(Country(name=name, engine=eng,
                                     color=COUNTRY_COLORS[i % len(COUNTRY_COLORS)],
                                     roles=dict(roles[i]) if roles and i < len(roles) else {}))
        return cls(mode, countries, seed=shared_seed, goal_cycles=goal_cycles)

    # ------------------------------------------------------------------
    # Abfragen
    # ------------------------------------------------------------------

    @property
    def shared_market(self) -> bool:
        return self.mode == "handel"

    def current_country(self) -> Country:
        return self.countries[self.active]

    def current_prices(self) -> dict:
        """Preise des laufenden Zyklus (gleiche Struktur wie engine.market)."""
        return copy.deepcopy(self.market)

    def _cycle_len(self, c: Country) -> int:
        return len(c.engine.history)

    def _submitted(self) -> set[int]:
        """Länder, die im laufenden Zyklus schon eingereicht haben."""
        lens = [self._cycle_len(c) for c in self.countries]
        low = min(lens)
        return {i for i, n in enumerate(lens) if n > low}

    def round_complete(self) -> bool:
        """True, wenn alle Länder den zuletzt begonnenen Zyklus gespielt haben."""
        lens = [self._cycle_len(c) for c in self.countries]
        return len(set(lens)) == 1 and lens[0] > 1

    @property
    def goal_cycles(self) -> int | None:
        eng = self.countries[0].engine
        return getattr(eng, "goal_cycles", getattr(eng, "TOTAL_CYCLES", 12))

    def goal_reached(self) -> bool:
        return all(_goal_reached(c.engine) for c in self.countries)

    def game_over(self) -> bool:
        """Alle Länder am Ziel und (noch) nicht fortgesetzt."""
        return all(c.engine.game_over for c in self.countries)

    def continue_play(self) -> None:
        """Nach Erreichen des Ziels für alle Länder weiterspielen."""
        for c in self.countries:
            if hasattr(c.engine, "continue_play"):
                c.engine.continue_play()
            else:   # Fallback für Engines ohne Ziel-API
                c.engine.game_over = False
                c.engine.continued = True
        self._last_submit = None
        self._sync_market()
        self.active = self._next_active(-1)

    def cycle(self) -> int:
        """Nummer des laufenden Zyklus (1-basiert)."""
        return min(c.engine.runde for c in self.countries)

    def trade_flows(self) -> list[dict]:
        return copy.deepcopy(self.market_history[-1]["flows"]) if self.market_history else []

    def ranking(self) -> list[tuple[str, float]]:
        out = []
        for c in self.countries:
            # Am Ziel (nicht fortgesetzt): Stand beim Zielerreichen; danach aktueller Score.
            snap = getattr(c.engine, "goal_snapshot", None)
            total = None
            if isinstance(snap, dict) and not getattr(c.engine, "continued", False):
                sc = snap.get("score", snap)
                if isinstance(sc, dict) and "total" in sc:
                    total = float(sc["total"])
                elif isinstance(snap.get("total"), (int, float)):
                    total = float(snap["total"])
            if total is None:
                try:
                    total = float(c.engine.score()["total"])
                except Exception:
                    total = 0.0
            out.append((c.name, total))
        return sorted(out, key=lambda t: t[1], reverse=True)

    def role_order(self) -> list[str]:
        """Reihenfolge der Rollen-Eingaben für das aktive Land (Präsidium zuletzt).

        Mit Rollen-Zuordnung: nur zugeordnete Rollen (Felder nicht zugeordneter
        Rollen bearbeitet das Präsidium). Modus "rollen" ohne Zuordnung: alle
        verfügbaren Rollen. Sonst leer (eine Person steuert alles)."""
        c = self.current_country()
        available = roles_for(c.engine)
        if c.roles:
            order = [r for r in available if r in c.roles and r != "praesidium"]
        elif self.mode == "rollen":
            order = [r for r in available if r != "praesidium"]
        else:
            return []
        return order + ["praesidium"]

    def role_fields(self, role: str) -> list[str]:
        """Editierbare Felder einer Rolle im aktiven Land (Präsidium: alle aktiven)."""
        c = self.current_country()
        active = list(getattr(c.engine, "active_input_keys", lambda: INPUT_KEYS)())
        if role == "praesidium":
            return active
        return [k for k in ROLES[role]["fields"] if k in active]

    # ------------------------------------------------------------------
    # Markt
    # ------------------------------------------------------------------

    def _country_market(self, c: Country) -> dict:
        m = copy.deepcopy(self.market)
        if self.shared_market and _ministry_active(c.engine, "verteidigung"):
            sec = getattr(c.engine, "security", 0.0)
            security = float((sec() if callable(sec) else sec) or 0.0)
            security = min(1.0, max(0.0, security))
            for g in GOODS:
                ex, im = m["export_price"][g], m["import_price"][g]
                if im > ex:
                    m["import_price"][g] = ex + (im - ex) * (1.0 - SECURITY_DISCOUNT * security)
        return m

    def _sync_market(self) -> None:
        """Preise in alle Engines schreiben (nur bei gemeinsamem Markt)."""
        if not self.shared_market:
            return
        for c in self.countries:
            if not c.engine.game_over or not hasattr(c.engine, "market"):  # Endstand nicht anfassen
                c.engine.market = self._country_market(c)

    def _resolve_cycle(self) -> None:
        exports, imports = [], []
        for c in self.countries:
            ex, im = _trade_of(c.engine.history[-1] if len(c.engine.history) > 1 else None, c.engine)
            exports.append(ex)
            imports.append(im)
        supply = {g: sum(e[g] for e in exports) for g in GOODS}
        demand = {g: sum(i[g] for i in imports) for g in GOODS}
        if self.shared_market:
            flows = _flow_list(exports, imports)
            nxt = new_prices(self.market, supply, demand, len(self.countries))
        else:
            # Kein gemeinsamer Markt: alles läuft über den (festen) Weltmarkt.
            flows = _flow_list(exports, [{} for _ in imports]) + \
                    _flow_list([{} for _ in exports], imports)
            nxt = copy.deepcopy(self.market)
        self.market_history.append({
            "cycle": len(self.market_history) + 1,
            "prices": copy.deepcopy(self.market),
            "next_prices": copy.deepcopy(nxt),
            "supply": supply, "demand": demand,
            "exports": exports, "imports": imports,
            "flows": flows,
        })
        self.market = nxt
        self._sync_market()

    # ------------------------------------------------------------------
    # Züge
    # ------------------------------------------------------------------

    def _next_active(self, after: int) -> int:
        n = len(self.countries)
        done = self._submitted()
        for step in range(1, n + 1):
            i = (after + step) % n
            if i not in done and not self.countries[i].engine.game_over:
                return i
        return 0

    def submit(self, inputs: dict) -> dict:
        idx = self.active
        c = self.countries[idx]
        if self.shared_market:
            c.engine.market = self._country_market(c)
        snapshot = {"index": idx,
                    "market": copy.deepcopy(self.market),
                    "history_len": len(self.market_history)}
        result = c.engine.apply(inputs)     # wirft ValueError bei ungültigen Eingaben
        if not hasattr(c.engine, "goal_reached") and not getattr(c.engine, "continued", False):
            # Fallback für Engines ohne Ziel-API: Ziel selbst prüfen.
            goal = getattr(c.engine, "goal_cycles", None)
            if goal is not None and len(c.engine.history) - 1 >= goal:
                c.engine.game_over = True
        self._last_submit = snapshot
        if self.round_complete():
            self._resolve_cycle()
            self.active = self._next_active(-1)
        else:
            self.active = self._next_active(idx)
        return result

    def can_undo(self) -> bool:
        return self._last_submit is not None and \
            self.countries[self._last_submit["index"]].engine.can_undo()

    def undo(self) -> bool:
        """Nimmt den zuletzt eingereichten Zug zurück (inkl. Marktauflösung)."""
        if not self.can_undo():
            return False
        snap = self._last_submit
        self._last_submit = None
        c = self.countries[snap["index"]]
        c.engine.undo()
        del self.market_history[snap["history_len"]:]
        self.market = snap["market"]
        self._sync_market()
        self.active = snap["index"]
        return True

    # ------------------------------------------------------------------
    # Speichern / Laden
    # ------------------------------------------------------------------

    def to_json(self) -> str:
        return json.dumps({
            "format": "equivara-world", "version": 1,
            "mode": self.mode, "seed": self.seed, "active": self.active,
            "market": self.market, "market_history": self.market_history,
            "countries": [{"name": c.name, "color": c.color, "roles": c.roles,
                           "engine": c.engine.to_json()} for c in self.countries],
        }, ensure_ascii=False)

    @classmethod
    def from_json(cls, s: str) -> "World":
        """Lädt Welt-JSON, GUI-Mehrspieler-JSON {"players": [...], "active": i}
        oder einen Einzel-Engine-Spielstand."""
        data = json.loads(s)
        if not isinstance(data, dict):
            raise ValueError("Ungültige Equivara-Spielstanddatei.")

        def engine_of(raw):
            return EquivaraEngine.from_json(raw if isinstance(raw, str) else json.dumps(raw))

        if data.get("format") == "equivara-world":
            countries = [Country(name=str(cd.get("name", f"Land {i + 1}")),
                                 engine=engine_of(cd["engine"]),
                                 color=cd.get("color") or COUNTRY_COLORS[i % len(COUNTRY_COLORS)],
                                 roles=dict(cd.get("roles") or {}))
                         for i, cd in enumerate(data["countries"])]
            world = cls(data.get("mode", "solo"), countries, seed=data.get("seed"))
            world.market = data.get("market") or copy.deepcopy(DEFAULT_MARKET)
            world.market_history = list(data.get("market_history") or [])
            world._sync_market()
        elif "players" in data:
            players = data["players"]
            countries = [Country(name=str(p.get("name", f"Land {i + 1}")),
                                 engine=engine_of(p["engine"]),
                                 color=COUNTRY_COLORS[i % len(COUNTRY_COLORS)])
                         for i, p in enumerate(players)]
            world = cls("solo" if len(countries) == 1 else "wettbewerb", countries,
                        seed=countries[0].engine.seed)
        elif "state" in data:
            eng = engine_of(s)
            world = cls("solo", [Country(name="Land 1", engine=eng, color=COUNTRY_COLORS[0])],
                        seed=eng.seed)
        else:
            raise ValueError("Unbekanntes Spielstandformat.")
        active = data.get("active")
        if isinstance(active, int) and 0 <= active < len(world.countries) \
                and active not in world._submitted() and not world.countries[active].engine.game_over:
            world.active = active
        return world


if __name__ == "__main__":   # Demo: 3 Länder handeln 12 Zyklen mit dem Berater
    w = World.create("handel", ["Nordland", "Ostmark", "Südhafen"], seed=7)
    while not w.game_over():
        inp, _ = w.current_country().engine.advise_inputs()
        w.submit(inp)
    for h in w.market_history:
        p = h["prices"]["export_price"]
        print(f"Zyklus {h['cycle']:2d}: " + "  ".join(f"{g}={p[g]:.3f}" for g in GOODS)
              + "  | Angebot " + ", ".join(f"{g}={h['supply'][g]:.0f}" for g in GOODS)
              + "  Nachfrage " + ", ".join(f"{g}={h['demand'][g]:.0f}" for g in GOODS))
    print(w.ranking())
