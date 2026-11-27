import json
from types import SimpleNamespace

from vitruvius_hoard.agent_tools import call_tool
from vitruvius_hoard.app_projects import AppProjects, starter_files


def test_static_page_can_be_created_by_the_agent(tmp_path):
    projects = AppProjects(tmp_path, host_port=9)
    services = SimpleNamespace(app_projects=projects)
    templates = call_tool(services, "app_templates", {})["templates"]
    assert any(template["id"] == "static-page" and template["name_es"] == "Página estática" for template in templates)

    project = call_tool(services, "app_project_create", {
        "name": "Guía", "template": "static-page", "lang": "es", "description_es": "Información práctica.",
        "include_files": True,
    })
    files = project["files"]
    assert files.keys() == {
        "project.json", "server.py", "layout.html", "pages/index.html", "assets/style.css", "Dockerfile", "LICENSE", "README.md",
    }
    spec = json.loads(files["project.json"])
    assert spec["fields"] == [] and spec["description"] == "Información práctica."
    assert 'lang="es"' in files["layout.html"] and "/records" not in files["layout.html"]
    assert "{{description}}" in files["pages/index.html"]
    assert project["undo"]["tool"] == "app_project_undo"


def test_existing_default_still_includes_the_records_interface():
    files = starter_files("Work board")
    assert "pages/records/index.html" in files and "assets/client.js" in files
