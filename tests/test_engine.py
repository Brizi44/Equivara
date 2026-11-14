import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from stratagem_engine import (  # noqa: E402
    DEFAULT_INPUTS, INPUT_KEYS, INPUT_LABELS, INVEST_KEYS, Issue, StratagemEngine,
)


def errors(issues):
    return [i for i in issues if i.severity == "error"]


@pytest.fixture
def eng():
    return StratagemEngine()


def test_constants():
    assert len(INPUT_KEYS) == 21
    assert set(INPUT_LABELS) == set(INPUT_KEYS)
    assert set(DEFAULT_INPUTS) == set(INPUT_KEYS)
    assert INVEST_KEYS == [k for k in INPUT_KEYS if k.startswith("inv_")]
    assert StratagemEngine.CYCLE_YEARS == 5 and StratagemEngine.TOTAL_CYCLES == 12


def test_defaults_valid(eng):
    assert errors(eng.validate(DEFAULT_INPUTS)) == []


def test_rejected_move_leaves_state_unchanged(eng):
    before = eng.to_json()
    bad = dict(DEFAULT_INPUTS, food_domestic=5000)  # Nahrung überbelegt
    issues = eng.validate(bad)
    assert errors(issues)
    assert all(isinstance(i, Issue) for i in issues)
    assert eng.to_json() == before
    with pytest.raises(ValueError):
        eng.apply(bad)
    assert eng.to_json() == before
    # Importbudget überschritten (Fehler erst in der Finanzrechnung)
    with pytest.raises(ValueError):
        eng.apply(dict(DEFAULT_INPUTS, import_food_money=600))
    assert eng.to_json() == before


@pytest.mark.parametrize("key,value", [
    ("food_export", -10), ("goods_export", 15), ("inv_energy_eff", 700),
    ("new_loans", 10), ("repayments", 2000), ("food_domestic", "abc"),
])
def test_invalid_inputs(eng, key, value):
    errs = errors(eng.validate(dict(DEFAULT_INPUTS, **{key: value})))
    assert errs
    assert any(e.field == key for e in errs)
    for e in errs:
        assert key not in e.message  # Anzeigenamen statt Schlüssel


def test_invest_sum_error(eng):
    errs = errors(eng.validate(dict(DEFAULT_INPUTS, inv_human=900)))
    assert errs


def test_interest_not_double_counted(eng):
    req = eng.requirements()
    assert req["interest_due"] == pytest.approx(500.0)
    budgets = eng.budgets(DEFAULT_INPUTS)
    assert budgets["money"]["available"] == pytest.approx(500.0)
    r = eng.apply(DEFAULT_INPUTS)
    assert r["debt"] == pytest.approx(1000.0)
    assert r["cash_reserve"] == pytest.approx(500.0)
    assert r["interest_paid"] == pytest.approx(500.0)
    assert r["unpaid_interest"] == pytest.approx(0.0)
    assert eng.requirements()["cash_reserve"] == pytest.approx(500.0)


def test_unpaid_interest_capitalised(eng):
    r = eng.apply(dict(DEFAULT_INPUTS, food_export=0, food_domestic=2000))
    assert r["interest_paid"] == pytest.approx(0.0)
    assert r["unpaid_interest"] == pytest.approx(500.0)
    assert r["debt"] == pytest.approx(1500.0)


def test_mfc_compares_with_previous_cycle(eng):
    # Zyklus 1: Konsum 2.0 -> 1.6 (Rückgang 20 %), Zyklus 2: Konsum bleibt 1.6.
    r1 = eng.apply(dict(DEFAULT_INPUTS, food_domestic=1600, food_export=1000))
    assert r1["food_mfc"] == pytest.approx(0.88)
    inp = eng.suggest_inputs()
    pop = eng.population
    inp["food_domestic"] = round(1.6 * pop * 5 / 10) * 10
    pc = inp["food_domestic"] / pop / 5
    inp["food_export"] = 0
    assert errors(eng.validate(inp)) == []
    r2 = eng.apply(inp)
    # Altcode hätte mit 2.0 (vorvoriger Zyklus) verglichen -> < 1.0
    expected_ratio = pc / r1["food_pc"]
    assert expected_ratio > 0.99
    assert r2["food_mfc"] == pytest.approx(min(1.0, 0.88 + (expected_ratio - 0.8) * 0.6), abs=1e-6)


def test_imf_deducts_goods():
    eng = StratagemEngine()
    eng.debt = 10000.0  # erzwingt IMF-Intervention
    inp = eng.suggest_inputs(DEFAULT_INPUTS)
    r = eng.apply(inp)
    assert r["imf"] > 0
    assert r["imf_goods"] == pytest.approx(r["imf"])
    assert r["imf_goods"] == pytest.approx(min(0.1 * r["goods_production"], r["debt"]))
    assert r["goods_available"] == pytest.approx(
        max(0.0, r["goods_production"] + r["goods_import"] - r["imf_goods"]))
    assert eng.requirements()["imf_pending"] == pytest.approx(r["imf"])
    debt_before = eng.debt
    r2 = eng.apply(eng.suggest_inputs())
    assert r2["imf_paid"] == pytest.approx(min(r["imf"], debt_before))


def test_preview_does_not_mutate(eng):
    before = eng.to_json()
    p = eng.preview(DEFAULT_INPUTS)
    assert p is not None
    assert eng.to_json() == before
    r = eng.apply(DEFAULT_INPUTS)
    assert p == r
    assert eng.preview(dict(DEFAULT_INPUTS, food_domestic=99990)) is None


def test_undo_restores_exactly(eng):
    assert not eng.can_undo()
    assert eng.undo() is False
    s0 = eng.to_json()
    eng.apply(DEFAULT_INPUTS)
    s1 = eng.to_json()
    eng.apply(eng.suggest_inputs())
    assert eng.can_undo()
    assert eng.undo() is True
    assert eng.to_json() == s1
    assert eng.undo() is True
    assert eng.to_json() == s0
    assert not eng.can_undo()


def test_json_roundtrip(eng):
    eng.apply(DEFAULT_INPUTS)
    eng.apply(eng.suggest_inputs())
    s = eng.to_json()
    json.loads(s)
    clone = StratagemEngine.from_json(s)
    assert clone.to_json() == s
    assert clone.history == eng.history
    assert clone.runde == eng.runde
    assert clone.can_undo()
    clone.undo()
    eng.undo()
    assert clone.to_json() == eng.to_json()
    # Gleiche Fortsetzung
    inp = eng.suggest_inputs()
    assert clone.apply(inp) == eng.apply(inp)


def test_full_game_with_suggest_inputs(eng):
    for n in range(1, 13):
        inp = eng.suggest_inputs()
        assert set(inp) == set(INPUT_KEYS)
        assert all(v >= 0 and v % 10 == 0 for v in inp.values())
        assert errors(eng.validate(inp)) == [], [i.message for i in eng.validate(inp)]
        r = eng.apply(inp)
        assert r["runde"] == n
        assert r["jahr_end"] == 5 * n
        assert len(eng.history) == n + 1
        assert eng.game_over == (n == 12)
        assert isinstance(eng.warnings(), list)
    assert eng.game_over
    assert eng.runde == 13
    assert errors(eng.validate(DEFAULT_INPUTS))
    with pytest.raises(ValueError):
        eng.apply(DEFAULT_INPUTS)
    assert eng.preview(DEFAULT_INPUTS) is None


def test_suggest_inputs_scales_down():
    eng = StratagemEngine()
    eng.food_available = 1234.0
    eng.goods_available = 777.0
    eng.energy_available = 3333.0
    eng.debt = 5000.0
    base = dict(DEFAULT_INPUTS, new_loans=500, repayments=900, import_food_money=400)
    inp = eng.suggest_inputs(base)
    assert errors(eng.validate(inp)) == []
    assert all(v % 10 == 0 for v in inp.values())


def test_budgets_never_raise(eng):
    for inp in [{}, None, {"food_domestic": "x"}, {"goods_domestic": None, "inv_food": float("nan")}]:
        b = eng.budgets(inp)
        for key in ("food", "goods", "energy", "money", "invest"):
            assert set(b[key]) == {"available", "used"}
    b = eng.budgets(DEFAULT_INPUTS)
    assert b["food"]["used"] == 3000
    assert b["goods"]["used"] == 3500
    assert b["energy"]["used"] == pytest.approx(8500 + 5000 + 600 + 400)
    assert b["invest"] == {"available": 1500, "used": 1500}
    assert eng.validate({})  # fehlende Werte -> Fehler, aber keine Exception


def test_requirements_keys(eng):
    req = eng.requirements()
    assert set(req) == {
        "energy_food_full", "energy_goods_full", "energy_population_per_goods", "interest_due",
        "annual_interest", "import_mult", "avg_exports", "debt", "max_new_loan", "cash_reserve",
        "imf_pending",
    }
    assert req["energy_food_full"] == pytest.approx(10000.0)
    assert req["energy_goods_full"] == pytest.approx(6000.0)
    assert req["max_new_loan"] == pytest.approx(0.0)


def test_history_start_and_length(eng):
    assert len(eng.history) == 1
    h0 = eng.history[0]
    for k in ["population", "labor", "food_pc", "goods_pc", "human_pc", "environment", "debt", "gdp",
              "gdp_pc", "food_available", "goods_available", "energy_available", "food_production",
              "goods_production", "energy_production", "birth_rate", "death_rate", "net_growth",
              "cap_energy_prod", "cap_energy_eff", "cap_food", "cap_goods", "cap_human", "cap_env",
              "cash_reserve"]:
        assert k in h0
    assert h0["runde"] == 0 and h0["jahr_end"] == 0
    r = eng.apply(DEFAULT_INPUTS)
    assert len(eng.history) == 2
    assert eng.history[1] == r
    assert eng.last_inputs == {k: float(v) for k, v in DEFAULT_INPUTS.items()}
    for k in ["interest_paid", "unpaid_interest", "cash_reserve", "imf_goods", "net_growth"]:
        assert k in r
    assert set(eng.history[0]) == set(r)
    eng.undo()
    assert len(eng.history) == 1


def test_warnings_present(eng):
    w = [i for i in eng.validate(dict(DEFAULT_INPUTS, inv_human=0)) if i.severity == "warning"]
    assert any("Investitionsbudget" in i.message for i in w)
    w = [i for i in eng.validate(dict(DEFAULT_INPUTS, food_domestic=1000, food_export=0))
         if i.severity == "warning"]
    assert any(i.field == "food_domestic" for i in w)
    # Energie für Nahrung < 100 % (8500 < 10000)
    w = [i for i in eng.validate(DEFAULT_INPUTS) if i.severity == "warning"]
    assert any(i.field == "energy_food" for i in w)


def test_reset(eng):
    s0 = eng.to_json()
    eng.apply(DEFAULT_INPUTS)
    eng.reset()
    assert eng.to_json() == s0
