"""Current assets for assistants already embedded in a project."""

from importlib.resources import files

from . import ENTRY, FORM_ASSETS, FORM_ENTRY, FORM_ROOT, assistant_assets


def embedded_assistant_assets(source):
    """Select bundles by their installed entry points and preserve project-owned sources."""
    entries = {}
    if ENTRY in source:
        entries.update(assistant_assets()["files"])
    if FORM_ENTRY in source:
        package = files(__package__)
        if not package.joinpath("form.js").is_file():
            raise ValueError("The current product does not provide the form voice assistant")
        entries.update({FORM_ROOT + name: package.joinpath(name).read_text(encoding="utf-8") for name in FORM_ASSETS})
    if not entries:
        raise ValueError("The project has no embedded voice assistant to refresh")
    return entries
