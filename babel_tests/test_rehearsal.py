"""Dependency upgrade rehearsal on two tiny local packages (no network, no touching the host environment)."""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from babels_hoard import rehearsal
from babels_hoard.api import create_app

from .agent_auth import agent_headers

V1 = {
    "rhpkg/__init__.py": (
        "from json import dumps as _dumps\n\n\n"
        "def fetch(url, timeout=10, retries=3):\n"
        "    \"\"\"Fetch a url.\"\"\"\n"
        "    return f'{url}|{timeout}|{retries}'\n\n\n"
        "def legacy_sum(items):\n    return sum(items)\n\n\n"
        "def render(data, indent=2):\n    return _dumps(data, indent=indent)\n"),
    "rhpkg/old_utils.py": "def slugify(text, sep='-'):\n    return sep.join(text.lower().split())\n",
}
V2 = {
    "rhpkg/__init__.py": (
        "from json import dumps as _dumps\n\n\n"
        "def fetch(url, timeout_s=10, retries=3):\n"
        "    \"\"\"Fetch a url.\"\"\"\n"
        "    return f'{url}|{timeout_s}|{retries}'\n\n\n"
        "def render(data, indent=4):\n    \"\"\"Render.\n\n    .. versionchanged:: 2.0 indentation is now four spaces.\n    \"\"\"\n"
        "    return _dumps(data, indent=indent)\n"),
    "rhpkg/text.py": "def slugify(text, sep='-'):\n    return sep.join(text.lower().split())\n",
}
APP = (
    "from rhpkg import fetch, render\n"
    "from rhpkg.old_utils import slugify\n\n\n"
    "def run():\n"
    "    a = fetch('http://x', timeout=5)\n"
    "    c = slugify('Hello World')\n"
    "    d = render({'a': 1})\n"
    "    e = render({'a': 1}, indent=2)\n"
    "    return a, c, d, e\n")
LEGACY = "from rhpkg import legacy_sum\n\n\ndef total(items):\n    return legacy_sum(items)\n"
TESTS = (
    "import app\n\n\n"
    "def test_fetch():\n    assert app.run()[0] == 'http://x|5|3'\n\n\n"
    "def test_slug():\n    assert app.run()[1] == 'hello-world'\n\n\n"
    "def test_sum():\n    import legacy\n    assert legacy.total([1]) == 1\n")


def write(root: Path, files: dict[str, str]) -> Path:
    for rel, text in files.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    return root


@pytest.fixture()
def world(tmp_path):
    old, new = write(tmp_path / "v1", V1), write(tmp_path / "v2", V2)
    project = write(tmp_path / "project", {"app.py": APP, "legacy.py": LEGACY, "test_app.py": TESTS})
    return project, old, new


def run(world, **kw):
    project, old, new = world
    return rehearsal.rehearse(str(project), "rhpkg", "2.0.0", old_version="1.0.0", old_path=str(old), new_path=str(new),
                              import_names=["rhpkg"], **kw)


def test_surface_diff_and_classification(world):
    result = run(world, run_tests=False)
    diff = result["api_diff"]
    removed = {r["symbol"]: r for r in diff["removed"]}
    assert "rhpkg.legacy_sum" in removed and "rhpkg.old_utils" in removed
    assert diff["changed"]["rhpkg.fetch"]["renamed_params"] == {"timeout": "timeout_s"}
    assert diff["changed"]["rhpkg.render"]["default_changed"]["indent"] == {"from": "2", "to": "4"}
    broken = {(b["line"], b["code"]) for b in result["uses"]["broken"] if b["file"] == "app.py"}
    assert any(b["symbol"] == "rhpkg.legacy_sum" and b["code"] == "removed_import" and b["file"] == "legacy.py"
               for b in result["uses"]["broken"])
    assert any(b["code"] == "unexpected_keyword" and b["line"] == 6 for b in result["uses"]["broken"])
    assert any(b["code"] == "moved_import" and b["moved_to"] == "rhpkg.text.slugify" for b in result["uses"]["broken"])
    # render() relying on the default is at risk (default + documented change); render(indent=2) is not
    risky = [r for r in result["uses"]["at_risk"] if r["symbol"] == "rhpkg.render"]
    by_line = {r["line"]: r for r in risky}
    assert set(by_line) == {8, 9}
    assert "default of 'indent'" in by_line[8]["reason"] and by_line[8]["evidence"]
    assert "default of" not in by_line[9]["reason"] and by_line[9]["evidence"]
    assert result["uses"]["ok_count"] >= 1
    assert result["summary"]["verdict"] == "breaking"
    assert result["isolation"]["mode"].startswith("pip --target")


def test_mechanical_edits_and_manual_items(world):
    project = world[0]
    result = run(world, run_tests=False)
    edits = {e["kind"]: e for e in result["plan"]["mechanical_edits"]}
    kw = edits["renamed_keyword"]
    assert (kw["file"], kw["line"], kw["old"], kw["new"]) == ("app.py", 6, "timeout", "timeout_s")
    assert APP.splitlines()[5][kw["col"]:kw["end_col"]] == "timeout"
    mv = edits["moved_import"]
    assert (mv["file"], mv["line"], mv["new"]) == ("app.py", 2, "from rhpkg.text import slugify")
    manual = result["plan"]["manual"]
    assert any("legacy_sum" in m["action"] and m["file"] == "legacy.py" for m in manual)
    assert "-    a = fetch('http://x', timeout=5)" in result["plan"]["diff"]
    assert "+    a = fetch('http://x', timeout_s=5)" in result["plan"]["diff"]
    # the user's project is never edited
    assert (project / "app.py").read_text(encoding="utf-8") == APP


def test_before_after_tests_on_throwaway_copies(world):
    project = world[0]
    result = run(world, run_tests=True, test_timeout=60)
    tests = result["tests"]
    assert tests["before"]["exit_code"] == 0 and tests["before"]["failed"] == []
    # in the new version app.py cannot even be imported (moved module): a collection error on the whole file
    assert tests["after"]["exit_code"] != 0 and "test_app.py" in tests["regressions"]
    assert result["summary"]["verdict"] == "breaking"
    # the mechanical edits repair fetch() and the moved import; only the removed function is left
    assert tests["after_edits"]["failed"] == ["test_app.py::test_sum"]
    assert tests["regressions_after_edits"] == ["test_app.py::test_sum"]
    assert tests["partly_fixed_by_edits"] == ["test_app.py"]
    assert (project / "app.py").read_text(encoding="utf-8") == APP
    assert not list(project.glob("**/__pycache__"))
    assert "timeout_s" not in (project / "app.py").read_text(encoding="utf-8")


def test_javascript_is_refused(world):
    with pytest.raises(rehearsal.RehearsalError, match="unsupported_language"):
        rehearsal.rehearse(str(world[0]), "x", "1", language="typescript")


def test_pip_installs_into_isolated_folder_and_leaves_host_alone(tmp_path):
    """The real install path: a local source tree installed with pip --target (offline)."""
    pytest.importorskip("setuptools")
    def package(version, body):
        root = tmp_path / f"src{version}"
        write(root, {"pyproject.toml": f'[build-system]\nrequires=["setuptools"]\nbuild-backend="setuptools.build_meta"\n'
                                       f'[project]\nname="pipdemo"\nversion="{version}"\n[tool.setuptools]\npackages=["pipdemo"]\n',
                     "pipdemo/__init__.py": body})
        return root
    old_src = package("1.0", "def go(a, b=1):\n    return a\n")
    new_src = package("2.0", "def go(a, *, mode=1):\n    return a\n")
    project = write(tmp_path / "proj", {"main.py": "import pipdemo\npipdemo.go(1, 2)\n"})
    extra = ["--no-index", "--no-build-isolation"]
    result = rehearsal.rehearse(str(project), "pipdemo", "2.0", old_version="1.0", old_requirement=str(old_src), requirement=str(new_src), pip_args=extra,
                                run_tests=False, pip_timeout=120)
    assert "pip --target" in result["isolation"]["new"]
    assert result["import_names"] == ["pipdemo"]
    assert result["new_version"] == "2.0"
    import importlib.util
    assert importlib.util.find_spec("pipdemo") is None
    assert result["api_diff"]["changed"]["pipdemo.go"]["removed_params"] == ["b"]
    assert any(b["code"] == "too_many_positional" for b in result["uses"]["broken"])


def test_agent_endpoint(world, tmp_path):
    project, old, new = world
    app = create_app(tmp_path / "data", None, port=18814)
    with TestClient(app, base_url="http://127.0.0.1:18814", headers=agent_headers(app)) as c:
        r = c.post("/api/agent/api_upgrade_rehearsal", json={
            "project_path": str(project), "package": "rhpkg", "target_version": "2.0.0", "old_version": "1.0.0",
            "old_path": str(old), "new_path": str(new), "import_names": ["rhpkg"], "run_tests": False})
        assert r.status_code == 200, r.text
        assert r.json()["summary"]["broken"] >= 3
        bad = c.post("/api/agent/api_upgrade_rehearsal", json={
            "project_path": str(project), "package": "x", "target_version": "1", "language": "typescript"})
        assert bad.status_code == 400 and bad.json()["error"] == "unsupported_language"
