"""--before / --kept: what a redesign must not lose."""

from __future__ import annotations

import pytest

from conftest import make_services
from vitruvius_hoard import kept

OLD = """<html><head><title>Brumario</title></head><body>
<h1>Libros cosidos a mano</h1><h2>Lo que salió del taller</h2>
<a href="/obra">Obra</a><a href="mailto:hola@brumario.example">Escribir</a>
<form action="/encargo"><label for="n">Nombre</label><input id="n" name="nombre"><input type="email" name="email"><button onclick="enviar()">Enviar</button></form>
<script>document.getElementById('menu').addEventListener('click', toggle)</script></body></html>"""
NEW_OK = OLD.replace("Libros cosidos a mano", "Libros cosidos a mano").replace("<a href=\"/obra\">Obra</a>", "<a href=\"/obra\">Ver la obra</a>")
NEW_BAD = """<html><head><title>Brumario</title></head><body><h1>Libros cosidos a mano</h1><a href="/obra">Obra</a>
<form action="/encargo"><input type="email" name="email"></form></body></html>"""


def test_snapshot_reads_links_fields_handlers_and_titles():
    s = kept.snapshot(OLD)
    assert {l["href"] for l in s["links"]} == {"/obra", "mailto:hola@brumario.example"}
    assert {f["key"] for f in s["fields"]} == {"nombre", "email"}
    assert {"#menu:click", "form:/encargo:submit"} <= {f"{h['target']}:{h['event']}" for h in s["handlers"]}
    assert any(h["event"] == "click" and h["target"] == "button" for h in s["handlers"])
    assert s["titles"]["title"] == "brumario" and "libros cosidos a mano" in s["titles"]["headings"]


def test_a_page_that_keeps_everything_passes_even_with_new_copy_around_it():
    out = kept.compare(kept.snapshot(OLD), NEW_OK)
    assert out["ok"] and out["total_missing"] == 0


def test_a_page_that_drops_something_fails_and_names_it():
    out = kept.compare(kept.snapshot(OLD), NEW_BAD)
    assert not out["ok"]
    assert {l["href"] for l in out["missing"]["links"]} == {"mailto:hola@brumario.example"}
    assert {f["key"] for f in out["missing"]["fields"]} == {"nombre"}
    assert out["missing_count"]["handlers"] == 2 and any(t["text"] == "lo que salió del taller" for t in out["missing"]["titles"])


def test_page_assay_before_then_kept_fails_a_redesign_that_lost_things(tmp_path):
    def runner(cmd, timeout):
        return 0, '{"works": true, "failed": 0, "cases": [{"id": "C001", "what": "open", "outcome": "passed"}]}', ""
    svc = make_services(tmp_path)
    svc.assay_runner = runner
    svc.start()
    try:
        saved = svc.assay_page(html=OLD, before=True, snapshot_only=True, label="before")
        kept_id = saved["kept"]["id"]
        assert saved["kept"]["counts"]["links"] == 2 and svc.kept_list()[0]["id"] == kept_id
        good = svc.assay_page(html=NEW_OK, kept=kept_id)
        assert good["kept"]["ok"] and good["works"] is True
        bad = svc.assay_page(html=NEW_BAD, kept=kept_id)
        assert bad["kept"]["ok"] is False and bad["works"] is False and bad["failed"] >= 1 and bad["failing"][-1]["id"] == "KEPT"
        both = svc.assay_page(html=OLD, before=True)
        assert both["kept_saved"]["id"] != kept_id
        with pytest.raises(LookupError):
            svc.assay_page(html=OLD, kept="nope")
    finally:
        svc.stop()
