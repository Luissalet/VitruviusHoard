"""Protocol checker: semantics, shortest counterexamples, crashes, bounds, replay and validation."""
from __future__ import annotations

import pytest

from vitruvius_hoard.protocols import SpecError, counterexample_test, explore, load_spec, replay
from vitruvius_hoard.protocols.examples import EXAMPLES


def run(spec, **kw):
    return explore(load_spec(spec), **kw)


def test_state_counts_by_hand():
    one = {"vars": {"x": 0}, "processes": [{"name": "p", "steps": [{"set": {"x": "x + 1"}}, {"set": {"x": "x + 1"}}]}]}
    assert run(one)["states"] == 3
    two = {"vars": {"x": 0}, "processes": [{"name": "p", "count": 2, "steps": [{"set": {"x": "x + 1"}}]}],
           "at_end": [{"name": "dos", "check": "x == 2"}]}
    r = run(two)
    assert r["status"] == "holds" and r["states"] == 4 and r["terminal_states"] == 1


def test_double_charge_shortest_counterexample():
    r = run(EXAMPLES["pago-no-atomico"]())
    v = r["violation"]
    assert r["status"] == "violated" and v["kind"] == "invariant" and v["length"] == 4
    assert [s[:2] for s in v["schedule"]] == [["intento1", "comprobar"], ["intento1", "cobrar"], ["intento2", "comprobar"], ["intento2", "cobrar"]]
    assert v["trace"][-1]["changes"] == {"charges": [1, 2]}
    rep = replay(load_spec(EXAMPLES["pago-no-atomico"]()), v["schedule"])
    assert rep["status"] == "violated" and rep["at_step"] == 4


def test_atomic_claim_holds_with_crashes():
    r = run(EXAMPLES["pago-reserva-atomica"]())
    assert r["status"] == "holds" and r["exhaustive"] and r["violation"] is None
    assert any("Caídas" in a for a in r["assumptions"])


def test_crash_between_charge_and_mark_double_charges():
    spec = {"vars": {"done": False, "charges": 0},
            "processes": [{"name": "w", "steps": [
                {"label": "cobrar", "when": "not done", "set": {"charges": "charges + 1"}},
                {"label": "marcar", "set": {"done": "True"}}],
                "crash": {"max": 1, "restart": "cobrar"}}],
            "invariants": [{"name": "un cobro", "check": "charges <= 1"}]}
    v = run(spec)["violation"]
    assert [s[2] for s in v["schedule"]] == ["step", "crash", "step"]
    no_crash = dict(spec, processes=[dict(spec["processes"][0], crash={})])
    assert run(no_crash)["status"] == "holds"


def test_lost_update_and_deadlock():
    r = run(EXAMPLES["contador"]())
    assert r["violation"]["kind"] == "at_end" and r["violation"]["final_state"]["vars"] == {"counter": 1}
    d = run(EXAMPLES["cerrojos"]())["violation"]
    assert d["kind"] == "deadlock" and d["length"] == 2


def test_bounds_make_it_inconclusive():
    spec = {"vars": {"n": 0}, "processes": [{"name": "p", "steps": [{"label": "inc", "set": {"n": "n + 1"}, "goto": "inc"}]}],
            "max_states": 50}
    r = run(spec)
    assert r["status"] == "inconclusive" and not r["exhaustive"] and "50" in r["truncated"]


def test_choose_explores_every_branch():
    spec = {"vars": {"v": 0}, "processes": [{"name": "p", "steps": [{"label": "elige", "choose": [
        {"set": {"v": "1"}}, {"set": {"v": "2"}}, {"when": "False", "set": {"v": "3"}}]}]}],
        "invariants": [{"name": "nunca 2", "check": "v != 2"}]}
    v = run(spec)["violation"]
    assert v["trace"][0]["branch"] == 1


@pytest.mark.parametrize("spec,msg", [
    ({"processes": []}, "no hay procesos"),
    ({"vars": {"x": 0}, "processes": [{"steps": [{"set": {"y": "1"}}]}]}, "no se puede asignar"),
    ({"vars": {"x": 0}, "processes": [{"steps": [{"set": {"x": "zz + 1"}}]}]}, "desconocidos"),
    ({"vars": {"x": 0}, "processes": [{"steps": [{"goto": "nowhere"}]}]}, "inexistente"),
    ({"vars": {"x": 0}, "processes": [{"locals": {"x": 1}, "steps": [{}]}]}, "tapa"),
    ({"vars": {"x": 0}, "processes": [{"steps": [{"set": {"x": "__import__('os')"}}]}]}, "no permitida"),
    ({"vars": {"x": 0}, "processes": [{"steps": [{"set": {"x": "x.real"}}]}]}, "no permitida"),
    ({"vars": {"x": 0.5}, "processes": [{"steps": [{}]}]}, "no soportado"),
    ({"vars": {"x": 0}, "processes": [{"locals": {"t": 0}, "steps": [{}]}], "invariants": ["t == 0"]}, "solo puede leer"),
])
def test_validation(spec, msg):
    with pytest.raises(SpecError, match=msg):
        load_spec(spec)


def test_replay_rejects_impossible_step():
    with pytest.raises(SpecError, match="no puede ejecutar"):
        replay(load_spec(EXAMPLES["cerrojos"]()), [["x", "suelta"]])


def test_skeleton_is_valid_python():
    spec = load_spec(EXAMPLES["pago-no-atomico"]())
    code = counterexample_test(spec, explore(spec)["violation"])
    compile(code, "skeleton", "exec")
    assert "('intento2', 'cobrar', 'step', 1)" in code


# --- agent tool -------------------------------------------------------------

def test_agent_tool_actions():
    from vitruvius_hoard.agent_tools import ProtocolArgs, TOOLS, run_protocol_check
    assert "protocol_check" in {t.name for t in TOOLS}
    ex = run_protocol_check(None, ProtocolArgs(action="examples"))["examples"]
    assert {"pago-no-atomico", "pago-reserva-atomica", "contador", "cerrojos"} <= {e["id"] for e in ex}
    spec = run_protocol_check(None, ProtocolArgs(action="example", example="pago-no-atomico"))["spec"]
    r = run_protocol_check(None, ProtocolArgs(action="check", spec=spec))
    assert r["status"] == "violated"
    rep = run_protocol_check(None, ProtocolArgs(action="replay", spec=spec, schedule=r["violation"]["schedule"]))
    assert rep["status"] == "violated"
    code = run_protocol_check(None, ProtocolArgs(action="test", spec=spec))["code"]
    assert "def test_" in code
    with pytest.raises(ValueError, match="no hay contraejemplo"):
        run_protocol_check(None, ProtocolArgs(action="test", spec=run_protocol_check(None, ProtocolArgs(action="example", example="pago-reserva-atomica"))["spec"]))
    with pytest.raises(ValueError, match="no se puede asignar"):
        run_protocol_check(None, ProtocolArgs(action="check", spec={"vars": {"x": 0}, "processes": [{"steps": [{"set": {"y": "1"}}]}]}))


def test_http_routes(client):
    r = client.get("/api/protocols/examples")
    assert r.status_code == 200 and r.json()["examples"]
    spec = client.get("/api/protocols/examples/contador").json()["spec"]
    out = client.post("/api/protocols/check", json={"spec": spec}).json()
    assert out["violation"]["kind"] == "at_end"
    assert client.post("/api/protocols/replay", json={"spec": spec, "schedule": out["violation"]["schedule"]}).json()["status"] == "violated"
    t = client.post("/api/protocols/test.py", json={"spec": spec})
    assert t.status_code == 200 and "attachment" in t.headers["content-disposition"]
    assert client.post("/api/protocols/check", json={"spec": {"processes": []}}).status_code == 400
    assert client.get("/api/protocols/examples/nada").status_code == 400


def test_choice_counterexample_replays_the_same_branch_and_exports_it():
    spec = load_spec({"vars": {"v": 0}, "processes": [{"name": "p", "steps": [
        {"label": "pick", "choose": [{"set": {"v": "1"}}, {"set": {"v": "2"}}]}]}],
        "invariants": [{"name": "not_two", "check": "v != 2"}]})
    violation = explore(spec)["violation"]
    assert violation["schedule"] == [["p", "pick", "step", 1]]
    repeated = replay(spec, violation["schedule"])
    assert repeated["status"] == "violated" and repeated["kind"] == "invariant"
    assert repeated["state"] == violation["final_state"]
    assert repeated["steps"][0]["branch"] == 1
    namespace = {}
    exec(counterexample_test(spec, violation), namespace)
    assert namespace["SCHEDULE"] == [("p", "pick", "step", 1)]
    seen = []
    namespace["run_step"] = lambda *args: seen.append(args)
    namespace["check_property"] = lambda: True
    namespace["test_not_two"]()
    assert seen == [("p", "pick", "step", 1)]
    with pytest.raises(SpecError, match="rama"):
        replay(spec, [["p", "pick", "step", 99]])


@pytest.mark.parametrize("extra,kind", [
    ({"invariants": ["x == 1"]}, "invariant"),
    ({"invariants": ["x == 1"], "processes": [{"name": "p", "steps": [{"set": {"x": "1 // 0"}}]}]}, "invariant"),
    ({"processes": [{"name": "p", "steps": [{"when": "False"}]}]}, "deadlock"),
])
def test_replay_checks_the_initial_state_even_with_an_empty_schedule(extra, kind):
    raw = {"vars": {"x": 0}, "processes": [{"name": "p", "steps": [{}]}], **extra}
    spec = load_spec(raw)
    assert explore(spec)["violation"]["length"] == 0
    repeated = replay(spec, [])
    assert repeated["status"] == "violated" and repeated["kind"] == kind
    assert repeated["at_step"] == 0
    from vitruvius_hoard.agent_tools import ProtocolArgs, run_protocol_check
    assert run_protocol_check(None, ProtocolArgs(action="replay", spec=raw, schedule=[]))["at_step"] == 0


def test_replay_checks_terminal_properties():
    spec = load_spec({"vars": {"x": 0}, "processes": [{"name": "p", "steps": [
        {"label": "finish", "set": {"x": "1"}}]}], "at_end": ["x == 2"]})
    violation = explore(spec)["violation"]
    repeated = replay(spec, violation["schedule"])
    assert repeated["status"] == "violated" and repeated["kind"] == "at_end"
    assert repeated["at_step"] == 1 and repeated["state"] == violation["final_state"]


def test_bfs_checks_all_property_kinds_at_the_same_depth():
    raw = {"vars": {"x": 0}, "processes": [{"name": "p", "steps": [
        {"label": "pick", "choose": [{"goto": "later"}, {"set": {"x": "1"}, "goto": "end"}]},
        {"label": "later", "set": {"x": "3"}}]}], "invariants": ["x != 3"], "at_end": ["x == 2"]}
    spec = load_spec(raw)
    violation = explore(spec)["violation"]
    assert violation["kind"] == "at_end" and violation["length"] == 1
    assert replay(spec, violation["schedule"])["kind"] == "at_end"
    # A state admitted at the bound is still checked; an omitted state cannot prove holds.
    bounded = load_spec({**raw, "max_states": 3})
    assert explore(bounded)["violation"]["length"] == 1


def test_dictionary_and_sequence_are_distinct_hashed_states():
    from vitruvius_hoard.protocols.expr import Expr, freeze
    assert Expr("{} == []").eval({}) is False
    assert Expr("{} != []").eval({}) is True
    assert Expr("[] == {}").eval({}) is False
    assert Expr("{} == {}").eval({}) is True
    assert len({freeze({}), freeze([])}) == 2
    assert len({freeze({"x": 1}), freeze([["x", 1]])}) == 2
    spec = load_spec({"vars": {"v": []}, "processes": [{"name": "p", "steps": [
        {"label": "pick", "choose": [{"set": {"v": "[]"}}, {"set": {"v": "{}"}}]}]}],
        "invariants": ["v != {}"]})
    violation = explore(spec)["violation"]
    assert violation["length"] == 1 and violation["trace"][0]["branch"] == 1
    assert violation["trace"][0]["changes"] == {"v": [[], {}]}
