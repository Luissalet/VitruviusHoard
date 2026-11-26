"""Editable transfer assistant assets and preview voice relay."""

from importlib.resources import files


ASSET_ROOT = "assets/transfer-assistant/"
ENTRY = ASSET_ROOT + "assistant.js"
ASSETS = ("assistant.js", "dialogue.js", "voice.js", "microphone.js", "assistant.css")


def assistant_assets():
    """Return the sources in the shape accepted by the application project tools."""
    package = files(__package__)
    return {
        "files": {ASSET_ROOT + name: package.joinpath(name).read_text(encoding="utf-8") for name in ASSETS},
        "mount": '<section data-transfer-assistant></section>',
        "stylesheet": f'<link rel="stylesheet" href="/{ASSET_ROOT}assistant.css">',
        "script": f'<script type="module" src="/{ENTRY}"></script>',
    }
