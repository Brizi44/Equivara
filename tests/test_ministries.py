"""Tests für Ministerien, Markt-Hook und einstellbares Ziel (CONTRACT3 §1 und §5)."""

import base64
import copy
import hashlib
import itertools
import json
import os
import sys
import time
import zlib

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from equivara_engine import (  # noqa: E402
    ALL_INPUT_KEYS, ALL_INPUT_LABELS, CURVE_INFO, DEFAULT_INPUTS, DEFAULT_MARKET, INPUT_KEYS, INPUT_LABELS,
    INVEST_KEYS, MINISTRIES, MINISTRY_INPUT_KEYS, SCENARIOS, EquivaraEngine,
)

ALL_ON = {k: True for k in MINISTRIES}
MINISTRY_RECORD_KEYS = {"cap_health", "cap_education", "cap_infrastructure", "cap_defense", "security",
                        "health_mult", "education_mult", "infra_mult", "exports", "imports"}
# Schlüssel, die nach der Erweiterung neu in den Ergebnis-Dicts sind (für den Bitvergleich ignoriert)
NEW_RECORD_KEYS = MINISTRY_RECORD_KEYS | {"infra_energy_mult", "defense_labor_share", "ministries"}

# Referenz-Fingerabdrücke, erzeugt mit dem Engine-Stand VOR Einführung der Ministerien:
# 12 Runden advise_inputs je Szenario; sha256 über alle Eingaben + komplette history (alte Schlüssel).
REFERENCE = {
    ("standard", False, 3): "c8d1e684dd0e7d1a937832df0905439ecd3c045ac2c88c11cf5d3235badddce9",
    ("standard", True, 7): "a48f54dd92c772ce130412749fdc16aa5a9c5bf7245ec78277395ce92b0d1d94",
    ("verschuldet", False, 3): "aba6da39d81d863c3e719594ce1bbe027ed184c05a2489260030238f96ee40ef",
    ("verschuldet", True, 7): "914ff9f185d8d67c445936f995c29f13eed0e11cfa9a68ff90b50424bb0db325",
    ("energiearm", False, 3): "79bb0214ab4b12ae7ac244300fdfbd288c9fd01da0580c8cae1561d3603d3ebb",
    ("energiearm", True, 7): "e5c26c65ff854057cd8cd4529930dc4854064a7a0ba09f0dad1ce12ec5d1996f",
    ("umweltkrise", False, 3): "d2c6e2ff6e9c7df6566e4afb06715c9d9e3d00fb1f4cda47d7f6107dc36bd1b4",
    ("umweltkrise", True, 7): "860fc7e9977610a4c499300f937ce763e35065a140549826f710c8695a7cc0f1",
    ("bevoelkerungsdruck", False, 3): "52e9ba8bcdab4755acc405f864947ee6b4bbde09f5eed934132d9ec6edb877ce",
    ("bevoelkerungsdruck", True, 7): "6b4f5e84898e53aeed9663777bd6454d9672a5c75b23ea918498ca595bc4be7f",
}
REFERENCE_SCORE = {("standard", False, 3): 96.49185, ("standard", True, 7): 97.526933}

# Echter Spielstand im alten Engine-Format (Version 2: Standard, Ereignisse an, Seed 5,
# eine Runde suggest_inputs), zlib + base64.
OLD_JSON_V2 = (
    "eNrtWEtypDgQvQpRaw8Bovj1uucMs3B0ECpQUYxBMOLTdjh8jTnN7PpikxISSED93O2IXrgW7eZlkqRSmS9Tet0da1bhbvfF2pF/"
    "+mLADP9BaF5Qsnuwdm2HOwKy1x0e8oQ8NzXr2uRUtF3NXgB/dB3HsZ0Ha/rr8r/f4NUUNwmhhOUvCTkeQVfIdbhhdQZ4sNclg6F5"
    "rFcqOUAtYEjDTn2FKWB7R2HtKWGkJWzg3gcSzsiBL1T5upN+4AEXJT6UXNVFwSQcClbTitBOuBSGCPkcHwBpwVP+BneuYz0BnLtq"
    "mEL7GNmBeEfImpSDNpqf9UAi/lGQ8tDluCJJPRAGgiMuW24+z5qkoBl5BiyKbRSGsYfCKAziaC/FYHDScGzXizwvQAjciAOPq/DA"
    "GR56rufaUbQPA3/0c1SRjjoasOHp+A93V5NBnlDa4xIc6QhswBhuYUpLIH0PDgXrTknVl0LV3vsTxsbUg20O7kmnyLmaTrqKSifP"
    "2UgnX0ungmqmjPRSyYX1hTj7CZMLQY4dbSQhf5aB4ZpFPb5+Jj3BJSN3IRbaN2e8qLjByTktRH0K36Ai1ec6GJKM5AxnWMpmvKxx"
    "ZgCM5NzaStMoliA2weRAgGeIJhtGVdqXJX98bkjakUztkKe2YxJo+zRJeMiqmpKXyY9VEU6GhCTtpziJ50WUBFYdU1NJK4fxWQ+i"
    "Zp+RIqcJLuZwnanjcfdHDVG2OrAuUt8QaUsYgcUaRrDK04XauqiNZaioitSfqIoXY1HN1Qb/nzZiRhp9zQIgNCtormFiqw59lpNu"
    "iRrZK7F2ZWGmExMwP/43PjEoegGoR2hhY3gAgJjWfDNkXVPSJTmrv3cn7kAsypOS7zzn6bxEyhtkmQhS4mGJdFRU+FjcHG3qpi9V"
    "aSAZU0Ya/MKrYLbJeiBq6VSbQi9hou55v6UZZhnvvT3la0vMpb89WL8Bx35UyxYc67rXurhJtEuehY10fppntTHgI3nWtUMU67/I"
    "pF039M4yr2d7IXDD9HMvDS03UPErhKhNWdFI+7uvhFl/kbKrMHvqGqC31jr++I9Zf/JFFsQCYsvqpgENqy3S0xclGGNCrKe67Qi1"
    "MtxaX0c9YvPEfhKEvatJKYy26alOn7iAAl9yyY9/lxII6AEfirLoJNcHbxtdA8FIZPubXSP0IxsFbuhGob9uHlPKXR3iBP1CI/ff"
    "00LQZgsxPnFPEzk7Bv7sAKgW6Rm//S9uOctva60HyiL2ke+7MYoCJwpEWXxAI1JF/s5WpDrzshkpXGtH/sV25Nuhg7woRAHspudF"
    "y96EXMHP7+xNkhDN3oSQHTmxv48d4IjY89HlRuXe3ai+ndmDEkOgLvOkUFmV24xqiaWBZ2pKaFzLa01pafyW1BWKBW16EblX1QZS"
    "zNiLLN1lP3ne6hvqfLIY8lWm+45OU1ldQbQL4S7SBZNtjdY2eEWsSzfiGIPmwkNZ+XQAddleXN8sH+mtOZFL2ciLWxLJHqYIup0x"
    "iCBnJZCjiGdIhoWuOk5o0PLAxzE1jKhX14W2LI232wpKVg+6UD0tIYogurqDstUGOLV/o2AM2OyTRM+QD/80M6P4iNTljCGUkXwU"
    "73lLlWHjRRnWx4WyCu0SV+GVZt5GQS0vDG68WHLuvlj6qJuA9cn/+rWSdm7fOinfeqdkHmdXJ9PlPc0tl0nmUXQNXzuQft4Wfd4W"
    "fd4Wfd4Wfd4W/Ya3Rb9uCHeX4/bVGXxK9uUE7q6G6xtGbsOtadSWhLAdyBuOLheGr/snr/Nz19Wpa2vm2py4tuet7WlLzFocB05p"
    "ZWze/gdf+V6f"
)


def errors(issues):
    return [i for i in issues if i.severity == "error"]


def fingerprint(eng):
    ins = []
    for _ in range(12):
        inp, _r = eng.advise_inputs()
        ins.append({k: inp[k] for k in sorted(inp)})
        eng.apply(inp)
    hist = [{k: r[k] for k in sorted(r) if k not in NEW_RECORD_KEYS} for r in eng.history]
    blob = json.dumps({"inputs": ins, "history": hist}, sort_keys=True, default=repr)
    return hashlib.sha256(blob.encode()).hexdigest()


def play(eng, n=12, mode="advise"):
    for _ in range(n):
        inp = eng.advise_inputs()[0] if mode == "advise" else eng.suggest_inputs()
        eng.apply(inp)
    return eng


def only(key):
    return {k: k == key for k in MINISTRIES}


def _find_seed_with_event(key):
    for seed in range(1, 5000):
        ev = EquivaraEngine(events_enabled=True, seed=seed).current_event()
        if ev and ev["key"] == key:
            return seed
    raise AssertionError(f"kein Seed mit Ereignis {key}")


# --------------------------------------------------------------- Struktur

def test_constants_and_structure():
    assert list(MINISTRIES) == ["gesundheit", "bildung", "infrastruktur", "verteidigung"]
    assert MINISTRY_INPUT_KEYS == ["inv_health", "inv_education", "inv_infrastructure", "inv_defense"]
    assert ALL_INPUT_KEYS == INPUT_KEYS + MINISTRY_INPUT_KEYS and len(INPUT_KEYS) == 21
    colors = {"gesundheit": "red", "bildung": "purple", "infrastruktur": "orange", "verteidigung": "blue"}
    caps = {"gesundheit": "cap_health", "bildung": "cap_education", "infrastruktur": "cap_infrastructure",
            "verteidigung": "cap_defense"}
    for key, m in MINISTRIES.items():
        assert set(m) >= {"name", "description", "input_key", "capital_attr", "lifetime", "delay_cycles",
                          "color_hint"}
        assert m["color_hint"] == colors[key] and m["capital_attr"] == caps[key]
        assert m["delay_cycles"] >= 1 and m["lifetime"] > 0
    for k in MINISTRY_INPUT_KEYS:
        assert k in INPUT_LABELS and INPUT_LABELS[k] and INPUT_LABELS.get(k) == ALL_INPUT_LABELS[k]
    assert set(ALL_INPUT_LABELS) == set(ALL_INPUT_KEYS)
    assert DEFAULT_MARKET == {"export_price": {"food": 1.0, "goods": 1.0, "energy": 1.0},
                              "import_price": {"food": 1.1, "goods": 1.1, "energy": 1.0}}
    for key in ("HEALTH_DEATH_MULT_CURVE", "EDUCATION_PRODUCTIVITY_CURVE", "INFRA_ENERGY_CURVE",
                "INFRA_PRODUCTION_CURVE", "DEFENSE_SECURITY_CURVE"):
        assert key in [c[0] for c in CURVE_INFO]


def test_default_engine_has_ministries_off():
    eng = EquivaraEngine(seed=1)
    assert eng.ministries == {k: False for k in MINISTRIES}
    assert eng.active_input_keys() == INPUT_KEYS
    assert eng.active_invest_keys() == INVEST_KEYS
    assert eng.market == DEFAULT_MARKET
    assert len(eng.curve_positions()) == 15
    with pytest.raises(ValueError):
        EquivaraEngine(ministries={"marine": True})


def test_active_keys_and_reset_keeps_ministries():
    eng = EquivaraEngine(seed=1, ministries={"bildung": True, "verteidigung": True})
    assert eng.active_input_keys() == INPUT_KEYS + ["inv_education", "inv_defense"]
    assert eng.active_invest_keys() == INVEST_KEYS + ["inv_education", "inv_defense"]
    eng.reset(scenario="verschuldet")
    assert eng.ministries["bildung"] and eng.ministries["verteidigung"] and not eng.ministries["gesundheit"]
    eng.reset(ministries={})
    assert not any(eng.ministries.values())
    assert eng.cap_education == 0.0


def test_records_always_have_ministry_keys():
    for mins in ({}, ALL_ON):
        eng = EquivaraEngine(seed=3, ministries=mins)
        eng.apply(eng.suggest_inputs())
        assert set(eng.history[0]) == set(eng.history[1])
        for rec in eng.history:
            assert MINISTRY_RECORD_KEYS <= set(rec)
            assert set(rec["exports"]) == set(rec["imports"]) == {"food", "goods", "energy"}
    off = EquivaraEngine(seed=3)
    off.apply(off.suggest_inputs())
    rec = off.history[-1]
    assert (rec["cap_health"], rec["cap_education"], rec["cap_infrastructure"], rec["cap_defense"]) == (0, 0, 0, 0)
    assert rec["security"] == 0.0
    assert rec["health_mult"] == rec["education_mult"] == rec["infra_mult"] == 1.0


def test_start_values_per_scenario():
    std = EquivaraEngine(seed=1, ministries=ALL_ON)
    for scen in SCENARIOS:
        eng = EquivaraEngine(scen, seed=1, ministries=ALL_ON)
        for m in MINISTRIES.values():
            assert getattr(eng, m["capital_attr"]) > 0
        # Infrastruktur startet nahe neutral (Logistik-Multiplikator 0.9 .. 1.0)
        assert 0.9 <= eng.infra_production_multiplier() <= 1.0
    assert EquivaraEngine("verschuldet", seed=1, ministries=ALL_ON).cap_health < std.cap_health
    assert std.infra_production_multiplier() == pytest.approx(1.0)


# --------------------------------------------------------------- Bitgenau

@pytest.mark.parametrize("scen,ev,seed", list(REFERENCE))
def test_ministries_off_bit_identical_to_reference(scen, ev, seed):
    eng = EquivaraEngine(scen, events_enabled=ev, seed=seed)
    assert fingerprint(eng) == REFERENCE[(scen, ev, seed)]
    if (scen, ev, seed) in REFERENCE_SCORE:
        assert round(eng.score()["total"], 6) == REFERENCE_SCORE[(scen, ev, seed)]


def test_explicit_all_off_equals_reference():
    eng = EquivaraEngine("standard", events_enabled=True, seed=7, ministries={k: False for k in MINISTRIES})
    assert fingerprint(eng) == REFERENCE[("standard", True, 7)]


# --------------------------------------------------------------- Eingaben / Budget

def test_missing_ministry_keys_count_as_zero():
    eng = EquivaraEngine(seed=1, ministries=ALL_ON)
    assert errors(eng.validate(DEFAULT_INPUTS)) == []
    assert eng.budgets(DEFAULT_INPUTS)["invest"]["used"] == sum(DEFAULT_INPUTS[k] for k in INVEST_KEYS)


def test_values_for_inactive_ministries_are_errors():
    eng = EquivaraEngine(seed=1, ministries=only("gesundheit"))
    inp = dict(DEFAULT_INPUTS, inv_food=200.0, inv_defense=100.0)
    errs = errors(eng.validate(inp))
    assert any(e.field == "inv_defense" and "Verteidigung" in e.message for e in errs)
    assert eng.preview(inp) is None
    before = eng.to_json()
    with pytest.raises(ValueError):
        eng.apply(inp)
    assert eng.to_json() == before
    ok = dict(DEFAULT_INPUTS, inv_food=200.0, inv_health=100.0, inv_defense=0.0)
    assert errors(eng.validate(ok)) == []
    plain = EquivaraEngine(seed=1)
    errs = errors(plain.validate(dict(DEFAULT_INPUTS, inv_food=200.0, inv_education=100.0)))
    assert [e.field for e in errs] == ["inv_education"]


def test_ministry_value_rules():
    eng = EquivaraEngine(seed=1, ministries=only("bildung"))
    for bad in (-10.0, 15.0, "abc"):
        errs = errors(eng.validate(dict(DEFAULT_INPUTS, inv_food=200.0, inv_education=bad)))
        assert any(e.field == "inv_education" for e in errs), bad
    assert errors(eng.validate(dict(DEFAULT_INPUTS, inv_education=""))) == []
    assert errors(eng.validate(dict(DEFAULT_INPUTS, inv_education=None))) == []


def test_budget_counts_ministries():
    eng = EquivaraEngine(seed=1, ministries=ALL_ON)
    # Grundinvestitionen 1500 -> 1300, dazu 200 für Ministerien
    inp = dict(DEFAULT_INPUTS, inv_food=200.0, inv_goods=200.0, inv_health=100.0, inv_education=100.0)
    b = eng.budgets(inp)["invest"]
    assert b["used"] == 1500.0 and b["available"] == 1500.0
    assert errors(eng.validate(inp)) == []
    over = dict(inp, inv_defense=100.0)
    assert eng.budgets(over)["invest"]["used"] == 1600.0
    assert any("Investitionen" in e.message for e in errors(eng.validate(over)))
    # inaktive Ministerien zählen nicht zum Budget
    part = EquivaraEngine(seed=1, ministries=only("gesundheit"))
    assert part.budgets(inp)["invest"]["used"] == 1400.0


def test_suggest_inputs_with_ministries():
    for mins in (ALL_ON, only("infrastruktur")):
        eng = EquivaraEngine(seed=2, ministries=mins)
        for _ in range(3):
            inp = eng.suggest_inputs()
            assert set(inp) == set(eng.active_input_keys())
            assert errors(eng.validate(inp)) == []
            assert all(inp[k] > 0 for k in eng.active_invest_keys()[len(INVEST_KEYS):])
            eng.apply(inp)


# --------------------------------------------------------------- Wirkungen einzeln

def _two(key, seed=4, **kw):
    """Gleiche Startlage einmal ohne, einmal mit Ministerium `key`."""
    return (EquivaraEngine("standard", seed=seed, **kw),
            EquivaraEngine("standard", seed=seed, ministries=only(key), **kw))


def test_health_lowers_death_rate():
    off, on = _two("gesundheit")
    on.cap_health = 600.0   # 3 pro Kopf
    assert on.health_multiplier() < 0.8
    assert on.death_rate() < off.death_rate()
    r_off, r_on = off.preview(DEFAULT_INPUTS), on.preview(DEFAULT_INPUTS)
    assert r_on["death_rate"] < r_off["death_rate"]
    assert r_on["health_mult"] < 1.0 and r_off["health_mult"] == 1.0
    assert r_on["population"] > r_off["population"]
    pts = EquivaraEngine.HEALTH_DEATH_MULT_CURVE
    assert pts[0][1] == 1.0 and 0.65 <= pts[-1][1] <= 0.75


def test_health_mitigates_epidemic():
    seed = _find_seed_with_event("epidemie")
    hit = EquivaraEngine(events_enabled=True, seed=seed, ministries=only("gesundheit"))
    calm = EquivaraEngine(events_enabled=False, seed=seed, ministries=only("gesundheit"))
    hit.cap_health = calm.cap_health = 600.0
    plain_hit = EquivaraEngine(events_enabled=True, seed=seed)
    plain_calm = EquivaraEngine(events_enabled=False, seed=seed)
    f_health = hit.preview(DEFAULT_INPUTS)["death_rate"] / calm.preview(DEFAULT_INPUTS)["death_rate"]
    f_plain = plain_hit.preview(DEFAULT_INPUTS)["death_rate"] / plain_calm.preview(DEFAULT_INPUTS)["death_rate"]
    assert f_plain == pytest.approx(1.3)
    assert 1.0 < f_health < f_plain


def test_education_raises_goods_productivity_and_lowers_births():
    off, on = _two("bildung")
    assert on.preview(DEFAULT_INPUTS)["goods_production"] == pytest.approx(
        off.preview(DEFAULT_INPUTS)["goods_production"] * on.education_multiplier())
    on.cap_education = 800.0   # 4 pro Kopf
    assert on.education_multiplier() > 1.3
    r_off, r_on = off.preview(DEFAULT_INPUTS), on.preview(DEFAULT_INPUTS)
    assert r_on["goods_production"] > r_off["goods_production"] * 1.3
    assert r_on["birth_rate"] < r_off["birth_rate"]
    pts = EquivaraEngine.EDUCATION_PRODUCTIVITY_CURVE
    assert pts[0][1] == 1.0 and 1.35 <= pts[-1][1] <= 1.45


def test_education_effect_is_delayed():
    eng = EquivaraEngine(seed=4, ministries=only("bildung"))
    assert MINISTRIES["bildung"]["delay_cycles"] == 2
    cap0 = eng.cap_education
    keep = 1 - 5 / MINISTRIES["bildung"]["lifetime"]
    eng.apply(dict(DEFAULT_INPUTS, inv_food=200.0, inv_education=100.0))
    assert eng.cap_education == pytest.approx(cap0 * keep)
    eng.apply(eng.suggest_inputs(dict(DEFAULT_INPUTS, inv_education=0.0)))
    assert eng.cap_education == pytest.approx(cap0 * keep ** 2)
    eng.apply(eng.suggest_inputs(dict(DEFAULT_INPUTS, inv_education=0.0)))
    assert eng.cap_education == pytest.approx(cap0 * keep ** 3 + 100.0)


def test_education_bonus_on_energy_efficiency():
    off, on = _two("bildung")
    off.cap_energy_eff = on.cap_energy_eff = 300.0
    on.cap_education = 800.0
    assert on.energy_efficiency_multiplier() < off.energy_efficiency_multiplier()


def test_infrastructure_energy_and_logistics():
    off, on = _two("infrastruktur")
    assert off.infra_production_multiplier() == 1.0 and off.infra_energy_multiplier() == 1.0
    r_off = off.preview(DEFAULT_INPUTS)
    on.cap_infrastructure = 0.0
    assert on.infra_production_multiplier() == pytest.approx(0.9)
    assert on.preview(DEFAULT_INPUTS)["food_production"] < r_off["food_production"]
    on.cap_infrastructure = 1100.0   # Verhältnis 1.0 zu Nahrungs- + Güterkapital
    assert on.infra_production_multiplier() == pytest.approx(1.1)
    assert on.infra_energy_multiplier() == pytest.approx(0.8)
    f_on, g_on, _ = on.full_energy_requirements()
    f_off, g_off, _ = off.full_energy_requirements()
    assert f_on == pytest.approx(0.8 * f_off) and g_on == pytest.approx(0.8 * g_off)
    r_high = on.preview(DEFAULT_INPUTS)
    assert r_high["food_production"] > r_off["food_production"]
    assert r_high["infra_mult"] == pytest.approx(1.1)


def test_defense_security_binds_labor_and_damps_events():
    off, on = _two("verteidigung")
    on.cap_defense = 400.0   # 2 pro Kopf
    assert on.security() == pytest.approx(1.0)
    assert on.labor_force == pytest.approx(off.labor_force * 0.9)
    on.cap_defense = 10000.0
    assert on.defense_labor_share() == pytest.approx(0.1)   # gedeckelt
    assert off.security() == 0.0 and off.labor_force == 50.0
    # Dürre gedämpft: Wirkung * (1 - 0.5 * security)
    seed = _find_seed_with_event("duerre")
    hit = EquivaraEngine(events_enabled=True, seed=seed, ministries=only("verteidigung"))
    calm = EquivaraEngine(events_enabled=False, seed=seed, ministries=only("verteidigung"))
    hit.cap_defense = calm.cap_defense = 400.0
    ratio = hit.preview(DEFAULT_INPUTS)["food_production"] / calm.preview(DEFAULT_INPUTS)["food_production"]
    assert ratio == pytest.approx(1 - 0.25 * 0.5)
    plain_hit = EquivaraEngine(events_enabled=True, seed=seed)
    plain_calm = EquivaraEngine(events_enabled=False, seed=seed)
    assert (plain_hit.preview(DEFAULT_INPUTS)["food_production"]
            / plain_calm.preview(DEFAULT_INPUTS)["food_production"]) == pytest.approx(0.75)


def test_defense_damps_interest_shock():
    seed = _find_seed_with_event("zinsschock")
    plain = EquivaraEngine(events_enabled=True, seed=seed)
    on = EquivaraEngine(events_enabled=True, seed=seed, ministries=only("verteidigung"))
    on.cap_defense = 400.0
    base = EquivaraEngine(events_enabled=False, seed=seed).requirements()["annual_interest"]
    assert plain.requirements()["annual_interest"] == pytest.approx(base + 5.0)
    assert on.requirements()["annual_interest"] == pytest.approx(base + 2.5)


def test_capital_decays_with_lifetime_and_delay():
    eng = EquivaraEngine(seed=1, ministries=ALL_ON)
    before = {m["capital_attr"]: getattr(eng, m["capital_attr"]) for m in MINISTRIES.values()}
    eng.apply(dict(DEFAULT_INPUTS, inv_food=200.0, inv_health=100.0))
    for m in MINISTRIES.values():
        attr = m["capital_attr"]
        assert getattr(eng, attr) == pytest.approx(before[attr] * (1 - 5 / m["lifetime"]))
    assert eng.under_health == [100.0]


def test_curve_positions_only_active():
    eng = EquivaraEngine(seed=1, ministries=only("infrastruktur"))
    keys = [c["key"] for c in eng.curve_positions()]
    assert len(keys) == 17 and "INFRA_ENERGY_CURVE" in keys and "HEALTH_DEATH_MULT_CURVE" not in keys
    cps = EquivaraEngine(seed=1, ministries=ALL_ON).curve_positions()
    assert len(cps) == 20
    for c in cps:
        assert c["x"] is not None and c["y"] is not None
        assert c["points"] == [tuple(map(float, p)) for p in getattr(EquivaraEngine, c["key"])]


def test_warnings_mention_ministries():
    eng = EquivaraEngine(seed=1, ministries=ALL_ON)
    eng.cap_health = eng.cap_education = eng.cap_defense = eng.cap_infrastructure = 0.0
    text = " ".join(eng.warnings())
    for word in ("Gesundheit", "Bildung", "Infrastruktur", "Sicherheit"):
        assert word in text


def test_score_with_ministries():
    eng = EquivaraEngine(seed=1, ministries=ALL_ON)
    sc = eng.score()
    assert "services" in sc["parts"]
    assert sum(m for _, m in sc["parts"].values()) == pytest.approx(100)
    for pts, mx in sc["parts"].values():
        assert 0.0 <= pts <= mx + 1e-9
    assert set(EquivaraEngine(seed=1).score()["parts"]) == {"food", "goods", "environment", "debt", "population"}


# --------------------------------------------------------------- Kombinationen / Berater

COMBOS = [dict(zip(MINISTRIES, bits)) for bits in itertools.product([False, True], repeat=4)]


@pytest.mark.parametrize("combo", COMBOS, ids=lambda c: "-".join(k[:3] for k, v in c.items() if v) or "aus")
def test_all_combinations_all_scenarios_playable(combo):
    for i, scen in enumerate(SCENARIOS):
        eng = EquivaraEngine(scen, events_enabled=bool(i % 2), seed=20 + i, ministries=combo)
        for _ in range(12):
            t = time.perf_counter()
            inp, reasons = eng.advise_inputs()
            # Großzügig, da die Messung unter Testlast schwankt; die harte 1-s-Grenze
            # prüft der eigene Laufzeittest.
            assert time.perf_counter() - t < 2.0
            assert set(inp) == set(eng.active_input_keys())
            assert all(v >= 0 and v % 10 == 0 for v in inp.values())
            assert errors(eng.validate(inp)) == [] and reasons
            eng.apply(inp)
        assert eng.game_over and len(eng.history) == 13
        assert 0 <= eng.score()["total"] <= 100


def test_advisor_invests_in_active_ministries():
    eng = EquivaraEngine(seed=5, ministries=ALL_ON)
    totals = {k: 0.0 for k in MINISTRY_INPUT_KEYS}
    for _ in range(6):
        inp, reasons = eng.advise_inputs()
        for k in totals:
            totals[k] += inp[k]
        assert any(r.startswith("Ministerien") for r in reasons)
        eng.apply(inp)
    assert all(v > 0 for v in totals.values()), totals
    inp, _ = EquivaraEngine(seed=5, ministries=only("gesundheit")).advise_inputs()
    assert "inv_defense" not in inp and "inv_health" in inp


def test_advise_does_not_mutate_with_ministries():
    eng = EquivaraEngine(events_enabled=True, seed=2, ministries=ALL_ON)
    eng.apply(eng.suggest_inputs())
    before = eng.to_json()
    eng.advise_inputs()
    assert eng.to_json() == before


# --------------------------------------------------------------- Markt-Hook

def test_market_default_and_requirements():
    req = EquivaraEngine(seed=1).requirements()
    assert req["market"] == DEFAULT_MARKET and "market" in req and req.get("market") == DEFAULT_MARKET


def test_market_prices_change_revenue_and_imports():
    inp = dict(DEFAULT_INPUTS, energy_carryover=100.0, energy_export=500.0)
    base = EquivaraEngine(seed=1)
    r0 = base.preview(inp)
    assert r0["exports"] == {"food": 1000.0, "goods": 0.0, "energy": 500.0}
    assert r0["export_money"] == 1500.0
    hi = EquivaraEngine(seed=1)
    hi.market["export_price"]["food"] = 1.5
    hi.market["export_price"]["energy"] = 0.5
    r1 = hi.preview(inp)
    assert r1["export_money"] == pytest.approx(1000 * 1.5 + 500 * 0.5)
    assert r1["exports"] == r0["exports"]                     # Mengen unverändert
    assert hi.budgets(inp)["money"]["available"] > base.budgets(inp)["money"]["available"]
    # Importe: Einheiten = Geld / (Importpreis * import_mult)
    imp = dict(inp, import_food_money=500.0)
    assert errors(base.validate(imp)) == []
    q0 = base.preview(imp)["imports"]["food"]
    assert q0 == pytest.approx(500.0 / (1.1 * base.requirements()["import_mult"]))
    cheap = EquivaraEngine(seed=1)
    cheap.market["import_price"]["food"] = 0.55
    q1 = cheap.preview(imp)["imports"]["food"]
    assert q1 == pytest.approx(2 * q0)
    assert cheap.preview(imp)["food_available"] > base.preview(imp)["food_available"]


def test_market_and_oil_shock_multiply():
    seed = _find_seed_with_event("oelpreisschock")
    eng = EquivaraEngine(events_enabled=True, seed=seed)
    eng.market["import_price"]["energy"] = 1.5
    eng.cash_reserve = 400.0
    r = eng.preview(dict(DEFAULT_INPUTS, import_energy_money=300.0))
    assert r["imports"]["energy"] == pytest.approx(300.0 / (1.5 * 2.0 * r["import_mult"]))


def test_market_saved_in_json():
    eng = EquivaraEngine(seed=1)
    eng.market["export_price"]["goods"] = 1.7
    clone = EquivaraEngine.from_json(eng.to_json())
    assert clone.market["export_price"]["goods"] == 1.7


# --------------------------------------------------------------- JSON

def test_json_roundtrip_with_ministries():
    eng = EquivaraEngine("umweltkrise", events_enabled=True, seed=9,
                         ministries={"gesundheit": True, "infrastruktur": True})
    play(eng, 3, "suggest")
    s = eng.to_json()
    assert json.loads(s)["state"]["ministries"] == eng.ministries
    clone = EquivaraEngine.from_json(s)
    assert clone.ministries == eng.ministries
    assert clone.to_json() == s
    assert clone.cap_health == eng.cap_health and clone.under_infrastructure == eng.under_infrastructure
    assert clone.advise_inputs()[0] == eng.advise_inputs()[0]
    assert clone.undo() and clone.ministries == eng.ministries


def test_old_json_loads_with_ministries_off():
    old_s = zlib.decompress(base64.b64decode("".join(OLD_JSON_V2))).decode()
    data = json.loads(old_s)
    assert data["version"] == 2 and "ministries" not in data["state"]
    old = EquivaraEngine.from_json(old_s)
    assert old.ministries == {k: False for k in MINISTRIES}
    assert old.market == DEFAULT_MARKET
    assert old.goal_cycles == 12 and old.continued is False and old.goal_snapshot is None
    assert old.cap_health == 0.0 and old.under_education == [0.0, 0.0]
    assert old.active_input_keys() == INPUT_KEYS
    play(old, 11)
    assert old.game_over and old.undo()
    old2 = EquivaraEngine.from_json(old_s)
    assert old2.undo()   # alter Undo-Snapshot ohne neue Felder
    assert old2.ministries == {k: False for k in MINISTRIES} and old2.runde == 1
    old2.apply(old2.suggest_inputs())


# --------------------------------------------------------------- Ziel / Weiterspielen

def test_goal_default_12():
    eng = EquivaraEngine(seed=1)
    assert eng.goal_cycles == 12 and eng.goal_years == 60 and not eng.goal_reached
    play(eng, 12, "suggest")
    assert eng.game_over and eng.goal_reached and eng.goal_snapshot is not None


@pytest.mark.parametrize("goal", [4, 20])
def test_goal_cycles(goal):
    eng = EquivaraEngine(seed=2, goal_cycles=goal)
    assert eng.goal_years == goal * 5
    for i in range(goal):
        assert not eng.game_over and not eng.goal_reached
        eng.apply(eng.advise_inputs()[0])
        assert eng.history[-1]["jahr_start"] == i * 5 and eng.history[-1]["jahr_end"] == (i + 1) * 5
    assert eng.game_over and eng.goal_reached
    assert eng.history[-1]["game_over"] is True
    snap = eng.goal_snapshot
    assert snap["runde"] == goal and snap["jahr_end"] == goal * 5 and snap["goal_years"] == goal * 5
    assert snap["score"]["total"] == pytest.approx(eng.score()["total"])
    assert "goal_score" not in eng.score()
    assert errors(eng.validate(DEFAULT_INPUTS))   # beendet
    assert all(v == 0 for v in eng.advise_inputs()[0].values())


def test_goal_endless():
    eng = EquivaraEngine(seed=3, goal_cycles=None)
    assert eng.goal_cycles is None and eng.goal_years is None
    play(eng, 15)
    assert not eng.game_over and not eng.goal_reached and eng.goal_snapshot is None
    assert eng.history[-1]["jahr_start"] == 70 and eng.history[-1]["jahr_end"] == 75


def test_continue_play_after_goal():
    eng = EquivaraEngine(events_enabled=True, seed=4, goal_cycles=4, ministries=only("bildung"))
    play(eng, 4)
    assert eng.game_over
    snap = copy.deepcopy(eng.goal_snapshot)
    eng.continue_play()
    assert eng.continued and not eng.game_over and eng.goal_reached
    play(eng, 16)                          # 20 Zyklen insgesamt
    assert not eng.game_over and eng.goal_reached and eng.runde == 21
    assert eng.history[-1]["jahr_start"] == 95 and eng.history[-1]["jahr_end"] == 100
    assert eng.goal_snapshot == snap       # Schnappschuss bleibt beim Zielzeitpunkt
    assert eng.score()["goal_score"] == pytest.approx(snap["score"]["total"])
    s = eng.to_json()
    clone = EquivaraEngine.from_json(s)
    assert clone.continued and clone.goal_cycles == 4 and clone.goal_snapshot["runde"] == 4
    assert clone.to_json() == s
    assert errors(clone.validate(clone.suggest_inputs())) == []


def test_reset_goal_sentinel():
    eng = EquivaraEngine(seed=1, goal_cycles=8)
    eng.reset()
    assert eng.goal_cycles == 8
    eng.reset(goal_cycles=None)
    assert eng.goal_cycles is None
    eng.reset(scenario="energiearm")
    assert eng.goal_cycles is None
    eng.reset(goal_cycles=20)
    assert eng.goal_cycles == 20 and not eng.continued and eng.goal_snapshot is None
    with pytest.raises(ValueError):
        EquivaraEngine(goal_cycles=0)


def test_undo_after_goal():
    eng = EquivaraEngine(seed=1, goal_cycles=2)
    play(eng, 2, "suggest")
    assert eng.game_over and eng.goal_snapshot
    assert eng.undo()
    assert not eng.game_over and eng.goal_snapshot is None
