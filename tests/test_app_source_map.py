import re

import pytest

from vitruvius_hoard.app_source_map import (
    edit_source, is_direct_text_edit, render_template, source_count, source_position, text_edit_proofs,
)


def test_text_edit_proof_rejects_deletion_even_when_the_next_heading_takes_the_source_position():
    first = "<h2>Watering</h2>\n"
    before = f"<section>{first}<h2>Inventory</h2></section>"
    edited = before.replace("Watering", "Water &amp; tools")
    deleted = before.replace(first, "")
    assert is_direct_text_edit(before, edited, 1, 10, "h2")
    assert is_direct_text_edit(edited, before, 1, 10, "h2")
    assert not is_direct_text_edit(before, deleted, 1, 10, "h2")
    assert not is_direct_text_edit(before, edited.replace("Inventory", "Stock"), 1, 10, "h2")
    generated = before.replace("Watering", "{{name}}")
    assert not is_direct_text_edit(before, generated, 1, 10, "h2")


def test_older_pins_follow_verified_text_edits_across_unchanged_source_and_shifted_lines():
    filename = "pages/index.html"
    middle = "<section><h2>Watering</h2></section><section><h2>Current records</h2></section>"
    pinned = middle.replace("Current records", "Saved shifts")
    shown = middle.replace("Watering", "Watering\nthis week")
    removed = shown.replace("<h2>Current records</h2>", "")
    sources = {"pinned": pinned, "middle": middle, "same": middle, "shown": shown, "removed": removed}
    neighbors = {"pinned": ["middle"], "middle": ["pinned", "same"], "same": ["middle", "shown"],
                 "shown": ["same", "removed"], "removed": ["shown"]}
    edits = {frozenset(("pinned", "middle")): (1, 46, "h2"), frozenset(("same", "shown")): (1, 10, "h2"),
             frozenset(("shown", "removed")): (2, 34, "h2")}

    pins = [entry for entry in text_edit_proofs(filename, "shown", neighbors, edits, sources.get)
            if entry[0] == "pinned"]
    assert set(pins) == {
        ("pinned", f"{filename}:1:10", "h2", f"{filename}:1:10", f"section|{filename}:1:1", f"section|{filename}:1:1"),
        ("pinned", f"{filename}:1:46", "h2", f"{filename}:2:34", f"section|{filename}:1:37", f"section|{filename}:2:25"),
    }
    assert text_edit_proofs(filename, "removed", neighbors, edits, sources.get) == []


def test_preview_annotations_preserve_positions_and_raw_markup(tmp_path):
    file = tmp_path / "pages" / "nested" / "[id].html"
    file.parent.mkdir(parents=True)
    source = (
        "\ufeff<!--<aside>ignored</aside>--><![unknown]>\r\n"
        "<section CLASS='lead' data-note=plain>é🗺<img src=map.png/><br />\r\n"
        "<script>const text = '<fake attr=\"value\">';</script>"
        "<style>p::before{content:'<fake>'}</style><textarea><fake></textarea>"
        "<p data-value='>'>No closing tag\r\n"
        "<a href='unfinished"
    )
    file.write_bytes(source.encode("utf-8"))
    rendered = render_template(tmp_path, file, {})
    line = source.splitlines()[1]
    assert rendered.startswith("\ufeff<!--<aside>ignored</aside>--><![unknown]>\r\n")
    assert "<section data-vsrc=\"pages/nested/[id].html:2:1\" CLASS='lead' data-note=plain>" in rendered
    assert f'<img data-vsrc="pages/nested/[id].html:2:{line.index("<img") + 1}" src=map.png/>' in rendered
    assert f'<br data-vsrc="pages/nested/[id].html:2:{line.index("<br") + 1}" />' in rendered
    assert "const text = '<fake attr=\"value\">';" in rendered
    assert "p::before{content:'<fake>'}" in rendered
    assert "<fake></textarea>" in rendered
    assert "<a href='unfinished" in rendered
    assert re.sub(r' data-vsrc="[^"]*"', "", rendered) == source
    assert file.read_bytes() == source.encode("utf-8")


def test_generated_fragment_roots_keep_their_context_and_share_the_marker_position(tmp_path):
    file = tmp_path / "layout.html"
    source = '<main><div class="wrap">{{table}}</div><!-- {{table}} --><p title="{{query}}">{{name}}</p>{{form}}</main>'
    file.write_bytes(source.encode())
    values = {"table": "<table><tr><td>data</td></tr></table><p>Empty</p>",
              "name": "Project", "query": "Search", "form": "<form><button>Add record</button></form>"}
    rendered = render_template(tmp_path, file, values)
    table = f"layout.html:1:{source.index('{{table}}') + 1}"
    form = f"layout.html:1:{source.index('{{form}}') + 1}"
    assert f'<table data-vsrc="{table}" data-vgen="table"><tr><td>data</td></tr></table>' in rendered
    assert f'<p data-vsrc="{table}" data-vgen="table">Empty</p></div>' in rendered
    assert f'<form data-vsrc="{form}" data-vgen="form"><button>Add record</button></form>' in rendered
    assert "<!-- <table><tr><td>data</td></tr></table><p>Empty</p> -->" in rendered
    assert 'title="Search">Project</p>' in rendered
    assert source_count(rendered, table) == 2
    assert source_count(rendered, form) == 1
    assert source_count(f'<script>let x="<span data-vsrc={table}>"</script><!-- data-vsrc="{table}" -->', table) == 0


def test_literal_replacement_preserves_bom_crlf_nesting_and_entities():
    source = "\ufeff<!--keep-->\r\n<section>é🗺<H2>\r\n  Café &amp; té <em>hoy</em></H2></section>\r\n"
    line = source.splitlines()[1]
    position = line.index("<H2>") + 1
    same = edit_source(source, 2, position, "H2", {"kind": "text", "value": "Café & té"})
    assert same == source
    changed = edit_source(source, 2, position, "h2", {"kind": "text", "value": "<Niño> {{name}} & té"})
    assert changed == source.replace("Café &amp; té", "&lt;Niño&gt; &#123;&#123;name}} &amp; té")
    assert edit_source("<textarea>á &lt;b&gt;</textarea>", 1, 1, "textarea",
                       {"kind": "text", "value": "literal <b>"}) == "<textarea>literal &lt;b&gt;</textarea>"


@pytest.mark.parametrize(("source", "change", "expected"), [
    ("<img alt='Old' class=compact />", {"kind": "attribute", "name": "alt", "value": "It's visible"},
     "<img alt='It&#x27;s visible' class=compact />"),
    ("<button DATA-KEY = unquoted checked>", {"kind": "attribute", "name": "data-key", "value": "x=y"},
     '<button DATA-KEY = "x=y" checked>'),
    ("<input checked   name=q>", {"kind": "attribute", "name": "checked", "value": None}, "<input   name=q>"),
    ("<br/>", {"kind": "attribute", "name": "id", "value": "separator"}, '<br id="separator"/>'),
    ("<img alt=old>", {"kind": "attribute", "name": "alt", "value": "new"}, "<img alt=new>"),
    ("<div class='hero wide' title=x>", {"kind": "class", "operation": "remove", "value": "wide"}, "<div class='hero' title=x>"),
    ("<div class=hero title=x>", {"kind": "class", "operation": "add", "value": "wide"}, '<div class="hero wide" title=x>'),
    ("<div class=hero title=x>", {"kind": "class", "operation": "add", "value": "hero"}, "<div class=hero title=x>"),
    ("<div title=x>", {"kind": "class", "operation": "remove", "value": "hero"}, "<div title=x>"),
    ("<path fill='black'/>", {"kind": "class", "operation": "add", "value": "hero"}, '<path class="hero" fill=\'black\'/>'),
])
def test_attribute_and_class_edits_change_only_the_target_span(source, change, expected):
    tag = re.match(r"<(\w+)", source)[1]
    assert edit_source(source, 1, 1, tag, change) == expected


@pytest.mark.parametrize(("source", "column", "tag", "change", "error"), [
    ("<div>{{table}}</div>", 6, "table", {"kind": "attribute", "name": "id", "value": "x"}, r"\{\{table\}\}"),
    ("<h1>Hello {{name}}</h1>", 1, "h1", {"kind": "text", "value": "x"}, r"\{\{name\}\}"),
    ("<input value={{query}}>", 1, "input", {"kind": "attribute", "name": "value", "value": None}, r"\{\{query\}\}"),
    ("<h1>Old</h1>", 1, "h2", {"kind": "text", "value": "x"}, "expected HTML tag"),
    ("<!--<h1>Old</h1>-->", 5, "h1", {"kind": "text", "value": "x"}, "expected HTML tag"),
    ("<!-- comment -->\n<h1>Old</h1>", 18, "h1", {"kind": "text", "value": "x"}, "expected HTML tag"),
    ("<p>First <em>child</em> second</p>", 1, "p", {"kind": "text", "value": "x"}, "single direct literal"),
    ("<script>let x = 1</script>", 1, "script", {"kind": "text", "value": "x"}, "script or style"),
    ("<style>strong{color:red}</style>", 1, "style", {"kind": "text", "value": "x"}, "script or style"),
    ("<input value==bad>", 1, "input", {"kind": "attribute", "name": "value", "value": "x"}, "ambiguous attribute"),
    ("<button id=x ID=y>", 1, "button", {"kind": "attribute", "name": "id", "value": "z"}, "repeats this attribute"),
    ("<button>", 1, "button", {"kind": "attribute", "name": "data-vsrc", "value": "z"}, "reserved"),
])
def test_ambiguous_stale_and_generated_changes_are_rejected(source, column, tag, change, error):
    with pytest.raises(ValueError, match=error):
        edit_source(source, 1, column, tag, change)


@pytest.mark.parametrize("value", ["pages/../layout.html:1:1", "/layout.html:1:1", "server.py:1:1",
                                  "pages\\index.html:1:1", "pages//index.html:1:1", "layout.html:0:1"])
def test_source_positions_are_limited_to_rendered_templates(value):
    with pytest.raises(ValueError, match="source position"):
        source_position(value)


def test_source_position_accepts_nested_unicode_path():
    assert source_position("pages/área/[id].html:4:6") == ("pages/área/[id].html", 4, 6)
