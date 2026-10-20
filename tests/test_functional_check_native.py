from __future__ import annotations

import importlib.util
from pathlib import Path

from vitruvius_hoard import assay
from vitruvius_hoard.agent_tools import TOOLS_BY_NAME


def test_worker_command_is_owned_when_external_package_is_absent(tmp_path, monkeypatch):
    original = importlib.util.find_spec
    monkeypatch.setattr(assay.importlib.util, "find_spec", lambda name: None if name == "assay" else original(name))
    monkeypatch.setattr(assay.proc, "which", lambda name: (_ for _ in ()).throw(AssertionError("external CLI search")))
    assert assay.available()
    command = assay._command(tmp_path, "index.html")
    assert Path(command[1]).name == "worker.py"
    assert "functional_check" in command[1] and "assay.cli" not in " ".join(command)


def test_own_tool_preserves_the_historical_input_contract():
    assert TOOLS_BY_NAME["page_check"].input_model == TOOLS_BY_NAME["page_assay"].input_model
    assert TOOLS_BY_NAME["page_check"].run == TOOLS_BY_NAME["page_assay"].run


def test_owned_checker_measures_working_and_broken_controls(tmp_path):
    working = '''<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Counter</title></head><body>
<h1>Counter</h1><output id="value">0</output><button id="inc" onclick="document.querySelector('#value').textContent=Number(document.querySelector('#value').textContent)+1">Increase</button>
</body></html>'''
    criteria = [{"id": "expected-counter", "what": "The requested counter increases after its button", "acts": [{"click": "#inc"}], "expect": {"want": "1"}, "control": "#inc"}]
    good = assay.run(tmp_path / "good", html=working, criteria=criteria)
    assert "error" not in good, good
    assert good["planned"] > 1 and any(row["kind"] == "button" for row in good["surface"])
    assert good["works"] is True, good
    broken = working.replace("onclick=\"document.querySelector('#value').textContent=Number(document.querySelector('#value').textContent)+1\"", "")
    bad = assay.run(tmp_path / "bad", html=broken, criteria=criteria)
    assert "error" not in bad, bad
    assert bad["works"] is False and bad["failed"] >= 1 and bad["failing"], bad


def test_explicit_browser_states_measure_focus_hover_mobile_and_motion(tmp_path):
    html = '''<!doctype html><html lang="es"><head><meta charset="utf-8"><title>Estados</title>
<style>body{margin:0}#nav .help{display:none}#nav:hover .help{display:block}
#wide{display:none;width:800px} .motion{animation:pulse 1s infinite}
@keyframes pulse{to{opacity:.5}} button:focus-visible{outline:3px solid blue}
</style></head><body><h1>Comprobar estados</h1>
<nav id="nav"><button id="menu">Menú</button><span class="help">Opciones de ayuda</span></nav>
<button id="open" tabindex="-1" onclick="document.querySelector('dialog').showModal()">Abrir diálogo</button>
<button id="expand" onclick="document.querySelector('#wide').style.display='block'">Mostrar panel</button>
<div id="wide">Panel abierto</div><div class="motion">Movimiento del ejemplo</div>
<dialog><p>Diálogo abierto</p><button onclick="this.closest('dialog').close()">Cerrar</button></dialog>
</body></html>'''
    desktop = {"viewport": {"width": 1440, "height": 1000}}
    mobile = {"viewport": {"width": 390, "height": 844}}
    criteria = [
        {"id": "keyboard", "what": "Tab reaches the dialog opener", "acts": [{"focus": "#menu"}, {"press": "Tab"}], "expect": {"focused": "#open"}, "environment": desktop},
        {"id": "hover", "what": "Hover keeps its visible help", "acts": [{"hover": "#nav"}], "expect": {"want": "Opciones de ayuda", "no_overflow": True}, "environment": mobile},
        {"id": "mobile-panel", "what": "Open panel fits mobile", "acts": [{"click": "#expand"}], "expect": {"no_overflow": True}, "environment": mobile},
        {"id": "reduced", "what": "Reduced motion stops the animation", "acts": [], "expect": {"no_motion": True}, "environment": {**mobile, "reduced_motion": "reduce"}},
        {"id": "dialog", "what": "The dialog opens", "acts": [{"click": "#open"}], "expect": {"want": "Diálogo abierto", "no_overflow": True}, "environment": desktop},
    ]
    bad = assay.run(tmp_path / "bad-states", html=html, criteria=criteria)
    assert "error" not in bad, bad
    failures = {row["what"] for row in bad["failing"]}
    assert {criteria[index]["what"] for index in (0, 2, 3)} <= failures, bad
    assert criteria[1]["what"] not in failures and criteria[4]["what"] not in failures, bad
    fixed = html.replace('tabindex="-1"', '').replace('width:800px', 'width:800px;max-width:100%')
    fixed = fixed.replace('</style>', '@media(prefers-reduced-motion:reduce){.motion{animation:none}}</style>')
    good = assay.run(tmp_path / "good-states", html=fixed, criteria=criteria)
    assert "error" not in good, good
    assert not {row["what"] for row in good["failing"]}.intersection(row["what"] for row in criteria), good
    for row in good["cases_sample"]:
        if row["what"] in {case["what"] for case in criteria}:
            assert row["outcome"] == "passed", row
            assert row["environment"]["viewport"]["width"] in (390, 1440)
            assert '"dom_ready_ms"' in row["measured"] and '"observed_layout_shift_sum"' in row["measured"]
