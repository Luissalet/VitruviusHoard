from pathlib import Path

import pytest

from babel_tests.faustus_manifest import check_repo

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize("folder,plugin_id", [(".", "vitruvius"), ("compatibility/babel", "babel"), ("compatibility/theseus", "theseus")])
def test_manifest_passes_faustus_checks(folder, plugin_id):
    data = check_repo(REPO_ROOT / folder)
    assert data["id"] == plugin_id
    assert data["mcp"]["transport"] == "stdio"
