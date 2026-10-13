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
