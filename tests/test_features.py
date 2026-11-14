import json
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import equivara_store as store  # noqa: E402
from equivara_engine import (  # noqa: E402
    DEFAULT_INPUTS, EVENTS, INPUT_KEYS, SCENARIOS, EquivaraEngine,
)


def errors(issues):
    return [i for i in issues if i.severity == "error"]


def play(eng, mode):
    for _ in range(EquivaraEngine.TOTAL_CYCLES):
        inp = eng.suggest_inputs() if mode == "suggest" else eng.advise_inputs()[0]
        assert errors(eng.validate(inp)) == [], [i.message for i in eng.validate(inp)]
        eng.apply(inp)
    assert eng.game_over
    return eng


# --------------------------------------------------------------- Szenarien

def test_scenarios_structure():
    assert list(SCENARIOS) == ["standard", "verschuldet", "energiearm", "umweltkrise", "bevoelkerungsdruck"]
    assert SCENARIOS["standard"]["overrides"] == {}
    for sc in SCENARIOS.values():
        assert sc["name"] and sc["description"]
        assert isinstance(sc["overrides"], dict)


def test_standard_scenario_unchanged():
    assert EquivaraEngine().history[0] == EquivaraEngine("standard").history[0]
    e = EquivaraEngine("verschuldet")
    assert e.debt == SCENARIOS["verschuldet"]["overrides"]["debt"]
    assert e.history[0]["debt"] == e.debt
    assert e.history[0]["scenario"] == "verschuldet"
    e.reset(scenario="standard")
    assert e.debt == 1000.0 and e.scenario == "standard"
    with pytest.raises(ValueError):
        EquivaraEngine("gibtsnicht")


@pytest.mark.parametrize("scenario", list(SCENARIOS))
@pytest.mark.parametrize("mode", ["suggest", "advise"])
def test_scenarios_playable(scenario, mode):
    eng = EquivaraEngine(scenario, events_enabled=True, seed=7)
    assert errors(eng.validate(eng.suggest_inputs())) == []
    play(eng, mode)
    assert len(eng.history) == 13
    assert 0.0 <= eng.score()["total"] <= 100.0


# --------------------------------------------------------------- Ereignisse

def test_events_structure():
    keys = {e["key"] for e in EVENTS}
    assert {"duerre", "gute_ernte", "oelpreisschock", "rohstoffboom", "epidemie", "zinsschock"} <= keys
    for e in EVENTS:
        assert set(e) >= {"key", "name", "description", "probability"}
        assert 0 < e["probability"] < 1


def test_events_none_when_disabled():
    eng = EquivaraEngine(events_enabled=False, seed=3)
    for _ in range(12):
        assert eng.current_event() is None
        r = eng.apply(eng.suggest_inputs())
        assert r["event"] is None
    assert eng.history[0]["event"] is None


def test_events_deterministic_per_seed():
    def seq(seed):
        eng = EquivaraEngine(events_enabled=True, seed=seed)
        out = []
        for _ in range(12):
            out.append((eng.current_event() or {}).get("key"))
            eng.apply(eng.suggest_inputs())
        assert eng.current_event() is None  # game over
        return out

    assert seq(42) == seq(42)
    all_keys = set()
    for s in range(60):
        all_keys.update(seq(s))
    assert {e["key"] for e in EVENTS} <= all_keys
    assert None in all_keys


def test_event_identical_in_preview_and_apply():
    found = set()
    for seed in range(200):
        eng = EquivaraEngine(events_enabled=True, seed=seed)
        ev = eng.current_event()
        if ev is None or ev["key"] in found:
            continue
        found.add(ev["key"])
        inp = dict(DEFAULT_INPUTS)
        p = eng.preview(inp)
        r = eng.apply(inp)
        assert p == r
        assert r["event"] == ev
        assert eng.history[1]["event"] == ev
        plain = EquivaraEngine(seed=seed).apply(inp)
        assert plain["event"] is None
        # Ereignis wirkt tatsächlich
        k = ev["key"]
        if k == "duerre":
            assert r["food_production"] == pytest.approx(plain["food_production"] * 0.75)
        elif k == "gute_ernte":
            assert r["food_production"] == pytest.approx(plain["food_production"] * 1.15)
        elif k == "epidemie":
            assert r["death_rate"] == pytest.approx(plain["death_rate"] * 1.3)
        elif k == "zinsschock":
            assert r["annual_interest"] == pytest.approx(plain["annual_interest"] + 5.0)
        elif k == "rohstoffboom":
            assert r["export_money"] == pytest.approx(plain["export_money"] * 1.3)
        if len(found) == len(EVENTS):
            break
    assert {"duerre", "gute_ernte", "epidemie", "zinsschock", "rohstoffboom"} <= found


def test_oil_shock_doubles_energy_import_price():
    seed = next(s for s in range(1000)
                if (EquivaraEngine(events_enabled=True, seed=s).current_event() or {}).get("key")
                == "oelpreisschock")
    inp = dict(DEFAULT_INPUTS, import_energy_money=400)
    r = EquivaraEngine(events_enabled=True, seed=seed).apply(inp)
    plain = EquivaraEngine(seed=seed).apply(inp)
    assert r["energy_import"] == pytest.approx(plain["energy_import"] / 2.0)


def test_reset_keeps_or_sets_seed():
    eng = EquivaraEngine(events_enabled=True)
    assert isinstance(eng.seed, int)
    s = eng.seed
    eng.reset()
    assert eng.seed == s and eng.events_enabled
    eng.reset(seed=5, events_enabled=False)
    assert eng.seed == 5 and not eng.events_enabled


# --------------------------------------------------------------- Score

def test_score_range_and_structure():
    eng = EquivaraEngine()
    for _ in range(12):
        sc = eng.score()
        assert 0.0 <= sc["total"] <= 100.0
        assert sc["grade"] in list("ABCDEF")
        assert set(sc["parts"]) == {"food", "goods", "environment", "debt", "population"}
        assert sum(m for _, m in sc["parts"].values()) == 100
        for pts, mx in sc["parts"].values():
            assert 0.0 <= pts <= mx
        assert sc["total"] == pytest.approx(sum(p for p, _ in sc["parts"].values()))
        assert isinstance(sc["comment"], str) and sc["comment"]
        eng.apply(eng.suggest_inputs())


# --------------------------------------------------------------- Berater

def test_advise_better_than_suggest():
    s = play(EquivaraEngine("standard", events_enabled=False, seed=1), "suggest")
    a = play(EquivaraEngine("standard", events_enabled=False, seed=1), "advise")
    assert a.score()["total"] > s.score()["total"] + 5
    assert a.history[-1]["food_pc"] >= 1.5


def test_advise_fast_and_valid():
    eng = EquivaraEngine("standard", events_enabled=True, seed=11)
    for _ in range(12):
        t = time.perf_counter()
        inp, reasons = eng.advise_inputs()
        assert time.perf_counter() - t < 1.0
        assert set(inp) == set(INPUT_KEYS)
        assert all(v >= 0 and v % 10 == 0 for v in inp.values())
        assert errors(eng.validate(inp)) == []
        assert reasons and all(isinstance(r, str) for r in reasons)
        eng.apply(inp)
    inp, reasons = eng.advise_inputs()
    assert all(v == 0 for v in inp.values()) and reasons


def test_advise_does_not_mutate():
    eng = EquivaraEngine(events_enabled=True, seed=2)
    eng.apply(eng.suggest_inputs())
    before = eng.to_json()
    eng.advise_inputs()
    assert eng.to_json() == before


# --------------------------------------------------------------- Kennlinien

def test_curve_positions():
    eng = EquivaraEngine()
    for step in range(2):
        cps = eng.curve_positions()
        assert len(cps) == 15
        assert [c["figure"] for c in cps] == list(range(1, 16))
        assert len({c["key"] for c in cps}) == 15
        for c in cps:
            assert set(c) == {"key", "figure", "title", "x_label", "y_label", "points", "x", "y"}
            assert c["points"] == [tuple(map(float, p)) for p in getattr(EquivaraEngine, c["key"])]
            assert c["x"] is None or isinstance(c["x"], float)
            if c["x"] is not None:
                assert c["points"][0][0] <= c["x"] <= c["points"][-1][0]
                assert c["y"] is not None
        eng.apply(eng.suggest_inputs())
    death = next(c for c in eng.curve_positions() if c["key"] == "DEATH_RATE_CURVE")
    assert death["x"] == pytest.approx(min(5.0, eng.food_pc))


# --------------------------------------------------------------- JSON

def test_json_contains_new_fields_and_roundtrip():
    eng = EquivaraEngine("energiearm", events_enabled=True, seed=99)
    eng.apply(eng.suggest_inputs())
    s = eng.to_json()
    state = json.loads(s)["state"]
    assert state["scenario"] == "energiearm" and state["events_enabled"] is True and state["seed"] == 99
    clone = EquivaraEngine.from_json(s)
    assert (clone.scenario, clone.events_enabled, clone.seed) == ("energiearm", True, 99)
    assert clone.current_event() == eng.current_event()
    assert clone.to_json() == s


def test_old_json_without_new_fields_loads():
    eng = EquivaraEngine(seed=1)
    eng.apply(DEFAULT_INPUTS)
    data = json.loads(eng.to_json())
    data["version"] = 1
    for st in [data["state"]] + data["undo"]:
        for k in ("scenario", "events_enabled", "seed"):
            st.pop(k, None)
        for rec in st["history"]:
            rec.pop("event", None)
            rec.pop("scenario", None)
    old = EquivaraEngine.from_json(json.dumps(data))
    assert old.scenario == "standard"
    assert old.events_enabled is False
    assert isinstance(old.seed, int)
    assert old.current_event() is None
    assert 0 <= old.score()["total"] <= 100
    old.apply(old.suggest_inputs())
    old.advise_inputs()
    assert old.undo() and old.undo()
    assert old.scenario == "standard"


# --------------------------------------------------------------- Store

def test_leaderboard_store(tmp_path):
    path = tmp_path / "sub" / "leaderboard.json"
    assert store.load_leaderboard(path) == []
    path.parent.mkdir()
    path.write_text("{kaputt", encoding="utf-8")
    assert store.load_leaderboard(path) == []
    path.unlink()

    eng = play(EquivaraEngine(seed=1), "suggest")
    entry = store.entry_from_engine("Anna", eng)
    assert set(entry) == {"name", "scenario", "events", "score", "grade", "population", "environment",
                          "debt", "food_pc", "date"}
    assert entry["name"] == "Anna" and entry["scenario"] == "standard" and entry["events"] is False
    assert entry["score"] == pytest.approx(eng.score()["total"], abs=0.01)

    lst = store.add_entry(entry, path)
    assert len(lst) == 1
    lst = store.add_entry(dict(entry, name="Ben", score=99.0), path)
    assert [e["name"] for e in lst] == ["Ben", "Anna"]
    assert store.load_leaderboard(path) == lst
    for i in range(120):
        lst = store.add_entry(dict(entry, name=f"P{i}", score=float(i % 50)), path)
    assert len(lst) == store.MAX_ENTRIES == 100
    scores = [e["score"] for e in store.load_leaderboard(path)]
    assert scores == sorted(scores, reverse=True)
    assert not [p for p in path.parent.iterdir() if p.name.endswith(".tmp")]


def test_settings_store(tmp_path):
    path = tmp_path / "settings.json"
    assert store.load_settings(path) == {}
    store.save_settings({"tutorial_done": True}, path)
    assert store.load_settings(path) == {"tutorial_done": True}
    path.write_text("[1, 2]", encoding="utf-8")
    assert store.load_settings(path) == {}
    assert store.DEFAULT_DIR.name == ".equivara"
