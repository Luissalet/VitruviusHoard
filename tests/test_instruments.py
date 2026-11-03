"""Instrument factory: spec -> app project with tests, standalone export that is actually run, explainer parity."""
import json
import threading
import urllib.request
import zipfile
from copy import deepcopy
from pathlib import Path

import pytest
from conftest import make_services

from vitruvius_hoard import instrument_runtime as rt
from vitruvius_hoard.agent_tools import TOOLS_BY_NAME, call_tool
from vitruvius_hoard.app_projects import AppProjects
from vitruvius_hoard.instruments import Instruments

PRICE = {
    "name": "Price with VAT", "kind": "calculator", "description": "Total price after discount and VAT.",
    "inputs": [
        {"name": "net", "label": "Net unit price", "type": "number", "unit": "EUR", "min": 0, "max": 100000},
        {"name": "qty", "label": "Quantity", "type": "integer", "min": 1, "max": 1000, "default": 1},
        {"name": "discount", "label": "Discount", "type": "number", "unit": "%", "min": 0, "max": 100, "default": 0},
        {"name": "vat_rate", "label": "VAT", "type": "number", "unit": "%", "min": 0, "max": 100, "default": 21},
        {"name": "invoice", "label": "Invoice", "type": "boolean", "default": False},
        {"name": "region", "label": "Region", "type": "choice", "choices": ["ES", "PT"], "default": "ES"},
    ],
    "operations": [{"name": "pct", "params": ["amount", "percent"], "formula": "amount * percent / 100"}],
    "steps": [{"name": "subtotal", "label": "Subtotal", "unit": "EUR", "formula": "net * qty"},
              {"name": "off", "label": "Discount amount", "unit": "EUR", "operation": "pct", "args": ["subtotal", "discount"]}],
    "outputs": [{"name": "taxable", "label": "Taxable base", "unit": "EUR", "formula": "subtotal - off"},
                {"name": "vat", "label": "VAT amount", "unit": "EUR", "formula": "pct(taxable, vat_rate)"},
                {"name": "total", "label": "Total", "unit": "EUR", "formula": "taxable + vat + (2.5 if invoice else 0)"}],
    "invariants": [{"name": "total never below the taxable base", "expression": "total >= taxable"}],
    "examples": [{"name": "plain", "inputs": {"net": 100}, "expected": {"taxable": 100, "vat": 21, "total": 121}},
                 {"name": "discounted bulk", "inputs": {"net": 50, "qty": 3, "discount": 10, "vat_rate": 10, "invoice": True},
                  "expected": {"taxable": 135, "vat": 13.5, "total": 151}}],
}


@pytest.fixture
def instruments(tmp_path):
    return Instruments(AppProjects(tmp_path))


def test_spec_generates_project_tests_and_source(instruments):
    made = instruments.create(PRICE)
    assert made["examples_ok"] is True and made["warnings"] == []
    got = instruments.get(made["id"], include_files=True)
    assert {"instrument.json", "server.py", "pages/index.html", "tests/test_instrument.py", "project.json", "README.md"} <= set(got["files"])
    tests = got["files"]["tests/test_instrument.py"]
    assert "test_example_1_plain" in tests and "test_example_2_discounted_bulk" in tests and "test_invalid_" in tests and "test_invariant_1_" in tests
    assert not any(line.startswith(("import vitruvius", "from vitruvius", "from .")) for line in got["files"]["server.py"].splitlines())  # nothing to import from the workbench
    assert instruments.projects.get(made["id"])["template"] == "instrument"
    row = instruments.list()[0]
    assert row["spec"]["name"] == "Price with VAT" and row["inputs"][0] == "net" and row["examples_ok"] is True


def test_exported_bundle_runs_standalone_and_reproduces_the_examples(instruments, tmp_path):
    made = instruments.create(PRICE)
    report = instruments.check(made["id"], inputs={"net": 19.99, "qty": 7, "discount": 15, "vat_rate": 10, "invoice": False, "region": "PT"})
    assert report["ok"] and report["tests"]["ok"] and report["tests"]["ran"] >= 12
    assert [e["ok"] for e in report["examples"]] == [True, True] and report["page_ok"]
    assert [e["ok"] for e in report["explainer"]] == [True, True, True] and report["explainer"][0]["numbers_compared"] == 5
    assert report["explainer_matches_outputs"] and report["examples_ok"]
    with zipfile.ZipFile(report["export"]["path"]) as bundle:
        assert "server.py" in bundle.namelist() and "vitruvius-export.json" in bundle.namelist()


def test_an_example_the_formulas_do_not_satisfy_is_reported(instruments):
    wrong = deepcopy(PRICE)
    wrong["examples"][1]["expected"]["total"] = 150
    made = instruments.create(wrong)
    assert made["examples_ok"] is False
    assert "1 of 2 spec examples" in made["warnings"][0] and "total expected 150 got 151" in made["warnings"][0]
    report = instruments.check(made["id"])
    assert not report["ok"] and not report["tests"]["ok"] and "test_example_2" in report["tests"]["output"]
    assert report["examples"][1]["mismatches"] == [{"output": "total", "expected": 150, "got": 151}]
    assert report["examples"][0]["ok"]


def test_spec_without_examples_warns_that_nothing_is_proved(instruments):
    bare = deepcopy(PRICE)
    bare["examples"] = []
    made = instruments.create(bare)
    assert "no examples" in made["warnings"][0] and made["examples_ok"] is None
    assert "no examples" in instruments.check(made["id"])["warning"]


def test_regenerating_after_a_spec_change_keeps_history(instruments):
    made = instruments.create(PRICE)
    changed = deepcopy(PRICE)
    changed["outputs"][2]["formula"] = "taxable + vat"
    changed["examples"][1]["expected"]["total"] = 148.5
    again = instruments.update(made["id"], changed)
    assert again["current_revision"] != made["current_revision"] and made["current_revision"] in again["revisions"]
    assert again["examples_ok"] and instruments.check(made["id"])["ok"]
    old = instruments.compute(made["id"], {"net": 50, "qty": 3, "discount": 10, "vat_rate": 10, "invoice": True}, revision=made["current_revision"])
    new = instruments.compute(made["id"], {"net": 50, "qty": 3, "discount": 10, "vat_rate": 10, "invoice": True})
    assert old["outputs"][2]["value"] == 151 and new["outputs"][2]["value"] == 148.5
    back = instruments.update(made["id"], PRICE)
    assert back["current_revision"] == made["current_revision"] and back["examples_ok"]  # same source, same revision id
    with pytest.raises(LookupError):
        instruments.get("0" * 16)


def test_input_validation_is_typed_and_ranged():
    spec = rt.validate_instrument_spec(PRICE)
    for bad, field in [({"net": -1}, "net"), ({"net": "abc"}, "net"), ({"net": 1, "qty": 1.5}, "qty"), ({"net": 1, "qty": 0}, "qty"), ({"net": 1, "discount": 101}, "discount"),
                       ({"net": 1, "region": "FR"}, "region"), ({"net": 1, "invoice": "yes"}, "invoice"), ({}, "net"), ({"net": 1, "ghost": 1}, "ghost"), ({"net": True}, "net")]:
        with pytest.raises(rt.InputError) as error:
            rt.compute(spec, bad)
        assert field in [e["field"] for e in error.value.errors], bad
    assert rt.compute(spec, {"net": 10})["outputs"][2]["value"] == 12.1


def test_units_conversion_and_division_guard():
    spec = rt.validate_instrument_spec({"name": "Density", "inputs": [
        {"name": "mass", "type": "number", "unit": "g", "to_base": 0.001, "min": 0}, {"name": "side", "type": "number", "unit": "cm", "to_base": 0.01, "min": 0}],
        "outputs": [{"name": "density", "unit": "kg/m3", "formula": "mass / (side * side * side)", "decimals": 1}],
        "examples": [{"name": "water", "inputs": {"mass": 1000, "side": 10}, "expected": {"density": 1000}}]})
    assert rt.check_examples(spec)[0]["ok"]
    with pytest.raises(ValueError, match="Division by zero"):
        rt.compute(spec, {"mass": 1, "side": 0})


@pytest.mark.parametrize("formula", ["__import__('os').system('x')", "(1).__class__", "net ** 2", "9 ** 9 ** 9", "open('f')", "net.real", "[net]", "lambda: 1", "pow(net, 999)"])
def test_hostile_or_unsupported_formulas(formula):
    spec = {"name": "X", "inputs": [{"name": "net", "type": "number", "default": 2}], "outputs": [{"name": "y", "formula": formula}]}
    try:
        validated = rt.validate_instrument_spec(spec)
    except ValueError:
        return
    with pytest.raises(ValueError):  # pow with a huge exponent passes syntax but is refused when computed
        rt.compute(validated, {"net": 2})


@pytest.mark.parametrize("change,message", [
    (lambda s: s["inputs"].append({"name": "net", "type": "number"}), "clashes"),
    (lambda s: s["outputs"][0].update(formula="missing + 1"), "unknown name 'missing'"),
    (lambda s: s["outputs"][0].update(formula="taxable + 1"), "unknown name 'taxable'"),
    (lambda s: s["examples"][0]["expected"].update(ghost=1), "unknown outputs"),
    (lambda s: s.update(kind="dashboard"), "kind must be"),
    (lambda s: s["inputs"][0].update(min=5, max=1), "min above max"),
    (lambda s: s["inputs"][5].update(choices=[]), "choices"),
    (lambda s: s["inputs"][1].update(default=5000), "Default of"),
    (lambda s: s["steps"][1].update(args=["subtotal"]), "must pass 2 args"),
    (lambda s: s["outputs"][0].update(decimals=40), "decimals"),
    (lambda s: s["inputs"][0].update(name="1bad"), "identifier"),
    (lambda s: s.update(unknown_key=1), "Unknown spec keys"),
])
def test_invalid_specs_are_refused_with_a_reason(change, message):
    spec = deepcopy(PRICE)
    change(spec)
    with pytest.raises(ValueError, match=message):
        rt.validate_instrument_spec(spec)


def test_explainer_shows_states_and_invariants_from_the_same_computation(instruments):
    made = instruments.create(PRICE)
    values = {"net": 50, "qty": 3, "discount": 10, "vat_rate": 10, "invoice": True}
    explained = instruments.explain(made["id"], values)
    computed = instruments.compute(made["id"], values)
    shown = {row["name"]: row for row in explained["shown"]}
    assert [row["kind"] for row in explained["shown"]].count("step") == 2
    for row in computed["steps"] + computed["outputs"]:
        assert shown[row["name"]]["value"] == row["value"] and shown[row["name"]]["formula"] == row["formula"]
    assert shown["off"]["formula"] == "pct(subtotal, discount)" and explained["invariants"] == [
        {"name": "total never below the taxable base", "expression": "total >= taxable", "holds": True}]
    assert explained["html_path"].startswith("/explain?net=50")
    page = rt.explain_html(rt.validate_instrument_spec(PRICE), values)
    assert 'data-name="total" data-kind="output" data-value="151"' in page and 'type="range"' in page and "Holds: total never below" in page
    assert instruments.explain(made["id"])["inputs"]["net"] == 100  # starts from the first example


def test_explainer_parity_check_detects_a_page_that_disagrees(instruments):
    spec = rt.validate_instrument_spec(PRICE)
    values = {"net": 100}

    def honest(path, body=None):
        if path.startswith("/explain"):
            return rt.explain_html(spec, values).encode()
        return json.dumps(rt.compute(spec, body)).encode()

    def forged(path, body=None):
        data = honest(path, body)
        return data.replace(b'data-name="total" data-kind="output" data-value="121"', b'data-name="total" data-kind="output" data-value="120"') if path.startswith("/explain") else data
    assert instruments._explainer_parity(spec, "x", values, honest)["ok"]
    bad = instruments._explainer_parity(spec, "x", values, forged)
    assert not bad["ok"] and bad["mismatches"] == [{"quantity": "total", "explainer": 120, "exported_instrument": 121}]


def serve(instruments, id, tmp_path):
    root = tmp_path / "served"
    for name, text in instruments.get(id, include_files=True)["files"].items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text, encoding="utf-8")
    server = rt.make_server(root)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_port}"


def post(url, body):
    request = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.loads(response.read())


def test_viewer_comparator_and_editor_kinds_serve_their_pages(instruments, tmp_path):
    rows = [{"net": 10}, {"net": 20, "qty": 2}]
    for kind in ("viewer", "comparator", "editor"):
        spec = {**deepcopy(PRICE), "kind": kind, "name": f"Price {kind}", "rows": rows}
        made = instruments.create(spec)
        server, base = serve(instruments, made["id"], tmp_path / kind)
        try:
            page = urllib.request.urlopen(base + "/", timeout=10).read().decode()
            assert f'"kind": "{kind}"' in page and f"Price {kind}</h1>" in page and "<\\/script" not in page
            table = post(base + "/api/table", {"rows": rows + [{"net": -5}]})["rows"]
            assert [r["ok"] for r in table] == [True, True, False] and table[1]["outputs"][2]["value"] == 48.4
            bad = urllib.request.Request(base + "/api/compute", data=b'{"net": "x"}', headers={"Content-Type": "application/json"}, method="POST")
            with pytest.raises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(bad)
            assert error.value.code == 400 and json.loads(error.value.read())["errors"][0]["field"] == "net"
        finally:
            server.shutdown()
            server.server_close()
    with pytest.raises(ValueError, match="needs rows"):
        instruments.create({**deepcopy(PRICE), "kind": "viewer", "rows": []})


def test_tools_and_rest_follow_the_same_path(tmp_path):
    svc = make_services(tmp_path)
    assert {n for n in TOOLS_BY_NAME if n.startswith("instrument_")} == {f"instrument_{x}" for x in ("create", "list", "get", "update", "compute", "explain", "check", "export")}
    made = call_tool(svc, "instrument_create", {"spec": PRICE})
    id = made["id"]
    assert call_tool(svc, "instrument_list", {})["instruments"][0]["id"] == id
    assert call_tool(svc, "instrument_compute", {"id": id, "inputs": {"net": 100}})["outputs"][2]["value"] == 121
    assert call_tool(svc, "instrument_explain", {"id": id, "inputs": {"net": 100}})["shown"][-1]["name"] == "total"
    assert call_tool(svc, "instrument_check", {"id": id})["ok"]
    exported = call_tool(svc, "instrument_export", {"id": id})
    assert exported["check"]["ok"] and Path(exported["path"]).is_file()
    with pytest.raises(ValueError):
        call_tool(svc, "instrument_create", {"spec": {"name": "x", "inputs": [], "outputs": []}})
    svc.stop()


def test_rest_routes(client):
    r = client.post("/api/instruments", json={"spec": PRICE})
    assert r.status_code == 201 and r.json()["examples_ok"]
    id = r.json()["id"]
    assert client.get("/api/instruments").json()["instruments"][0]["id"] == id
    assert client.post(f"/api/instruments/{id}/compute", json={"inputs": {"net": 100}}).json()["outputs"][0]["value"] == 100
    assert client.post(f"/api/instruments/{id}/compute", json={"inputs": {"net": -1}}).status_code == 400
    assert client.post(f"/api/instruments/{id}/explain", json={}).json()["shown"]
    changed = deepcopy(PRICE)
    changed["description"] = "Changed"
    assert client.put(f"/api/instruments/{id}", json={"spec": changed}).json()["spec"]["description"] == "Changed"
    assert client.post(f"/api/instruments/{id}/check", json={}).json()["ok"]
    exported = client.post(f"/api/instruments/{id}/export", json={"run_check": False}).json()
    assert exported["download_url"].startswith(f"/api/app-projects/{id}/exports/")
    assert client.get(exported["download_url"]).status_code == 200
    assert client.get("/api/instruments/" + "0" * 16).status_code == 404
