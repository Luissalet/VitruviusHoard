"""Editable transfer assistant assets and preview voice relay."""

from hashlib import sha256
from html import escape
from html.parser import HTMLParser
from importlib.resources import files
import json

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError


ASSET_ROOT = "assets/transfer-assistant/"
ENTRY = ASSET_ROOT + "assistant.js"
ASSETS = ("assistant.js", "dialogue.js", "voice.js", "reply_audio.js", "microphone.js", "assistant.css")
FORM_ROOT = "assets/voice-assistant/"
FORM_ENTRY = FORM_ROOT + "form.js"
FORM_ASSETS = ("form.js", "form.css", "microphone.js", "reply_audio.js")


def assistant_assets():
    """Return the sources in the shape accepted by the application project tools."""
    package = files(__package__)
    return {
        "files": {ASSET_ROOT + name: package.joinpath(name).read_text(encoding="utf-8") for name in ASSETS},
        "mount": '<section data-transfer-assistant></section>',
        "stylesheet": f'<link rel="stylesheet" href="/{ASSET_ROOT}assistant.css">',
        "script": f'<script type="module" src="/{ENTRY}"></script>',
    }


class _BodyEnd(HTMLParser):
    position = None

    def handle_endtag(self, tag):
        if tag == "body" and self.position is None:
            self.position = self.getpos()


def form_assistant_files(page, source, form_selector, schema, allow_submit):
    properties = schema.get("properties")
    if (schema.get("type") != "object" or not isinstance(properties, dict) or not 1 <= len(properties) <= 32
            or any(not name or len(name) > 128 or not isinstance(spec, dict) for name, spec in properties.items())):
        raise ValueError("Voice schema needs 1–32 named field definitions in object.properties")
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as error:
        raise ValueError(f"Invalid voice schema: {error.message}") from error
    if any(name not in properties for name in schema.get("required", [])):
        raise ValueError("Every required voice field must have a field definition")
    config = json.dumps({"formSelector": form_selector, "schema": schema, "allowSubmit": allow_submit}, ensure_ascii=False)
    if len(config.encode("utf-8")) > 12_000:
        raise ValueError("Voice schema exceeds 12,000 UTF-8 bytes")
    key = sha256(f"{page}\0{form_selector}".encode()).hexdigest()[:20]
    start = f"<!-- vitruvius:voice:{key} -->"
    end = f"<!-- /vitruvius:voice:{key} -->"
    settings = escape(config, quote=True).replace("{", "&#123;").replace("}", "&#125;")
    block = (f'{start}<link rel="stylesheet" href="/{FORM_ROOT}form.css">'
             f'<span hidden data-voice-assistant="{settings}"></span>'
             f'<script type="module" src="/{FORM_ENTRY}"></script>{end}')
    before, marker, after = source.partition(start)
    if marker:
        _, closing, tail = after.partition(end)
        if not closing:
            raise ValueError("Voice assistant mount marker is incomplete")
        updated = before + block + tail
    else:
        parser = _BodyEnd()
        parser.feed(source)
        parser.close()
        index = len(source)
        if parser.position is not None:
            row, column = parser.position
            index = sum(len(line) + 1 for line in source.split("\n")[:row - 1]) + column
        updated = source[:index] + block + source[index:]
    package = files(__package__)
    assets = {FORM_ROOT + name: package.joinpath(name).read_text(encoding="utf-8")
              for name in FORM_ASSETS}
    return {**assets, page: updated}
