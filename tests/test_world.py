import inspect
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import equivara_engine as eng_mod  # noqa: E402
import equivara_world as W  # noqa: E402
from equivara_engine import EquivaraEngine  # noqa: E402


def market(factor=1.0):
    m = json.loads(json.dumps(W.DEFAULT_MARKET))
    for g in W.GOODS:
        m["export_price"][g] *= factor
        m["import_price"][g] *= factor
    return m


# ---------------------------------------------------------------- Preisbildung

def test_oversupply_lowers_price():
    p = W.new_prices(market(), {"food": 8000, "goods": 0, "energy": 0},
                     {"food": 0, "goods": 0, "energy": 0}, 2)
    assert p["export_price"]["food"] < 1.0
    assert p["export_price"]["goods"] == pytest.approx(1.0)
    assert p["import_price"]["food"] == pytest.approx(1.1 * p["export_price"]["food"])


def test_scarcity_raises_price():
    p = W.new_prices(market(), {"food": 0, "goods": 0, "energy": 0},
                     {"food": 0, "goods": 9000, "energy": 0}, 2)
    assert p["export_price"]["goods"] > 1.0
    assert p["export_price"]["food"] == pytest.approx(1.0)


def test_price_bounds_and_damping():
    hi = market(1.0)
    lo = market(1.0)
    for _ in range(50):
        hi = W.new_prices(hi, {g: 0 for g in W.GOODS}, {g: 1e9 for g in W.GOODS}, 1)
        lo = W.new_prices(lo, {g: 1e9 for g in W.GOODS}, {g: 0 for g in W.GOODS}, 1)
    for g in W.GOODS:
        assert hi["export_price"][g] == pytest.approx(W.PRICE_MAX)
        assert lo["export_price"][g] == pytest.approx(W.PRICE_MIN)
    # Dämpfung: Nachfrage = 3x Puffer -> r = 4, Ziel 4**0.5 = 2.0, ein Schritt nur halber Weg.
    d = {g: 3 * W.ROW_BUFFER[g] for g in W.GOODS}
    one = W.new_prices(market(), {g: 0 for g in W.GOODS}, d, 1)
    assert one["export_price"]["food"] == pytest.approx(1.0 + W.DAMPING * (2.0 - 1.0))


def test_balanced_market_returns_to_normal():
    p = market(1.6)
    for _ in range(30):
        p = W.new_prices(p, {g: 500 for g in W.GOODS}, {g: 500 for g in W.GOODS}, 3)
    assert p["export_price"]["food"] == pytest.approx(1.0, abs=1e-3)


def test_flows_conserve_amounts():
    exports = [{"food": 1000}, {"food": 0}, {"food": 200}]
    imports = [{"food": 0}, {"food": 600}, {"food": 300}]
    flows = W._flow_list(exports, imports)
    out = {i: 0.0 for i in range(3)}
    inn = {i: 0.0 for i in range(3)}
    for f in flows:
        assert f["from"] != f["to"]
        if f["from"] is not None:
            out[f["from"]] += f["amount"]
        if f["to"] is not None:
            inn[f["to"]] += f["amount"]
    for i in range(3):
        assert out[i] == pytest.approx(exports[i]["food"])
        assert inn[i] == pytest.approx(imports[i]["food"])
    assert any(f["from"] == 0 and f["to"] == 1 for f in flows)


# ---------------------------------------------------------------- Modi

def test_solo_identical_to_engine():
    a = EquivaraEngine(seed=42)
    world = W.World("solo", [W.Country("A", EquivaraEngine(seed=42))])
    for _ in range(12):
        inp = a.suggest_inputs()
        ra = a.apply(inp)
        rb = world.submit(inp)
        assert json.dumps(ra, sort_keys=True, default=str) == json.dumps(rb, sort_keys=True, default=str)
    assert world.game_over()
    assert len(world.market_history) == 12
    assert world.current_prices() == W.DEFAULT_MARKET


def test_invalid_mode_and_country_count():
    with pytest.raises(ValueError):
        W.World("quatsch", [W.Country("A", EquivaraEngine(seed=1))])
    with pytest.raises(ValueError):
        W.World("solo", [W.Country("A", EquivaraEngine(seed=1)), W.Country("B", EquivaraEngine(seed=1))])


def test_turn_order_and_round_complete():
    w = W.World.create("wettbewerb", ["A", "B", "C"], seed=3)
    assert w.active == 0 and not w.round_complete()
    w.submit(w.current_country().engine.suggest_inputs())
    assert w.active == 1 and not w.round_complete()
    w.submit(w.current_country().engine.suggest_inputs())
    w.submit(w.current_country().engine.suggest_inputs())
    assert w.round_complete() and w.active == 0
    assert len(w.market_history) == 1
    assert w.current_prices() == W.DEFAULT_MARKET


def test_undo_last_submit():
    w = W.World.create("handel", ["A", "B"], seed=5)
    assert not w.can_undo()
    w.submit(w.current_country().engine.suggest_inputs())
    w.submit(w.current_country().engine.suggest_inputs())
    assert len(w.market_history) == 1
    prices = w.current_prices()
    assert w.can_undo() and w.undo()
    assert w.active == 1 and len(w.market_history) == 0
    assert w.current_prices() == W.DEFAULT_MARKET
    assert not w.can_undo()
    w.submit(w.current_country().engine.suggest_inputs())
    assert w.current_prices() == prices


def test_handel_three_countries_twelve_cycles_with_advisor():
    w = W.World.create("handel", ["A", "B", "C"], seed=11)
    while not w.game_over():
        inp, _ = w.current_country().engine.advise_inputs()
        w.submit(inp)
    assert len(w.market_history) == 12
    for h in w.market_history:
        for g in W.GOODS:
            assert W.PRICE_MIN - 1e-9 <= h["prices"]["export_price"][g] <= W.PRICE_MAX + 1e-9
        for f in h["flows"]:
            assert f["good"] in W.GOODS and f["amount"] > 0
    ranking = w.ranking()
    assert len(ranking) == 3
    assert ranking == sorted(ranking, key=lambda t: t[1], reverse=True)
    if hasattr(w.countries[0].engine, "market"):
        assert w.countries[0].engine.market == w.current_prices() or w.game_over()


# ---------------------------------------------------------------- Rollen

def test_roles_cover_all_fields_exactly_once():
    seen = []
    for role in W.ROLES.values():
        seen.extend(role["fields"])
    assert sorted(seen) == sorted(W.ALL_INPUT_KEYS)
    assert len(seen) == len(set(seen))
    assert "goods_investment" in W.ROLES["praesidium"]["fields"]
    for key in W.ROLES:
        for k in ("name", "description", "fields", "requires_ministry"):
            assert k in W.ROLES[key]


def test_roles_for_and_order():
    e = EquivaraEngine(seed=1)
    roles = W.roles_for(e)
    assert "gesundheit" not in roles and "praesidium" in roles
    w = W.World("rollen", [W.Country("A", e)])
    order = w.role_order()
    assert order[-1] == "praesidium"
    assert set(order) == set(roles)
    if "ministries" in inspect.signature(EquivaraEngine).parameters:
        e2 = EquivaraEngine(seed=1, ministries={"gesundheit": True})
        assert "gesundheit" in W.roles_for(e2)
        assert "bildung" not in W.roles_for(e2)
    w2 = W.World("wettbewerb", [W.Country("A", EquivaraEngine(seed=1)),
                                W.Country("B", EquivaraEngine(seed=1), roles={"umwelt": "Eva"})])
    assert w2.role_order() == []
    w2.submit(w2.current_country().engine.suggest_inputs())
    assert w2.role_order() == ["umwelt", "praesidium"]


# ---------------------------------------------------------------- JSON

def test_json_roundtrip():
    w = W.World.create("handel", ["A", "B"], seed=9, roles=[{}, {"umwelt": "Eva"}])
    for _ in range(3):
        w.submit(w.current_country().engine.suggest_inputs())
    w2 = W.World.from_json(w.to_json())
    assert w2.mode == "handel" and w2.active == w.active
    assert [c.name for c in w2.countries] == ["A", "B"]
    assert w2.countries[1].roles == {"umwelt": "Eva"}
    assert w2.market_history == json.loads(json.dumps(w.market_history))
    assert w2.current_prices() == w.current_prices()
    r1 = w.submit(w.current_country().engine.suggest_inputs())
    r2 = w2.submit(w2.current_country().engine.suggest_inputs())
    assert r1["population"] == pytest.approx(r2["population"])


def test_load_legacy_formats():
    a, b = EquivaraEngine(seed=2), EquivaraEngine(seed=2)
    a.apply(a.suggest_inputs())
    multi = json.dumps({"players": [{"name": "A", "engine": a.to_json()},
                                    {"name": "B", "engine": b.to_json()}], "active": 1})
    w = W.World.from_json(multi)
    assert w.mode == "wettbewerb" and w.active == 1
    single = W.World.from_json(a.to_json())
    assert single.mode == "solo" and len(single.countries[0].engine.history) == 2


# ---------------------------------------------------------------- Ziel / Weiterspielen

def test_goal_and_continue_play():
    w = W.World.create("wettbewerb", ["A", "B"], seed=4, goal_cycles=3)
    assert w.goal_cycles == 3
    for _ in range(6):
        w.submit(w.current_country().engine.suggest_inputs())
    assert w.game_over() and w.goal_reached()
    goal_rank = w.ranking()
    w.continue_play()
    assert not w.game_over() and w.goal_reached()
    for _ in range(4):
        w.submit(w.current_country().engine.suggest_inputs())
    assert all(len(c.engine.history) == 6 for c in w.countries)
    assert len(w.ranking()) == len(goal_rank) == 2
