"""The personal banking example: its project validates and its declared transfer is atomic."""
import json
from pathlib import Path

import pytest

from vitruvius_hoard.app_runtime import ActionError, Collections, validate_spec

EXAMPLE = Path(__file__).resolve().parents[1] / "docs" / "examples" / "app-projects" / "personal-banking"


@pytest.fixture
def store(tmp_path):
    spec = json.loads((EXAMPLE / "project.json").read_text(encoding="utf-8"))
    return Collections(tmp_path / "app.db", validate_spec(spec))


def accounts(store):
    return {row["id"]: row for row in store.list("cuentas")}


def transfer(**values):
    return {"origen": "cuenta-diaria", "importe_cent": 5000, "concepto": "Regalo", "fecha": "2026-11-26", **values}


def mod97(iban):
    digits = "".join(str(int(ch, 36)) for ch in iban[4:] + iban[:4])
    return int(digits) % 97 == 1


def test_example_declares_pages_and_valid_seed_data(store):
    pages = sorted(path.relative_to(EXAMPLE / "pages").as_posix() for path in (EXAMPLE / "pages").rglob("*.html"))
    assert pages == ["contactos.html", "cuentas/[id].html", "index.html", "movimientos.html", "transferir.html"]
    rows = accounts(store)
    contacts = store.list("contactos")
    assert all(mod97(row["iban"]) for row in [*rows.values(), *contacts])
    assert sum(1 for c in contacts if c["nombre"].startswith("María ")) == 2
    assert sum(row["saldo_cent"] for row in rows.values()) == 1556801
    assert all(row["disponible_cent"] == row["saldo_cent"] + row["limite_cent"] for row in rows.values())


def test_transfer_to_contact_debits_and_records_one_movement(store):
    before = len(store.list("movimientos"))
    result = store.perform("transferir", transfer(contacto="maria-ortega"))
    assert result["ok"] and result["undo_token"]
    assert accounts(store)["cuenta-diaria"]["saldo_cent"] == 238417 - 5000
    moves = store.list("movimientos")
    assert len(moves) == before + 1
    assert any(m["contraparte"] == "María Ortega Ruiz" and m["importe_cent"] == -5000 for m in moves)


@pytest.mark.parametrize("destination", [{"destino": "cuenta-ahorro"}, {"iban": "ES89 2471 0310 1700 0731 2046", "beneficiario": "Ahorro"}])
def test_transfer_between_own_accounts_credits_the_destination(store, destination):
    store.perform("transferir", transfer(**destination))
    rows = accounts(store)
    assert rows["cuenta-diaria"]["saldo_cent"] == 238417 - 5000
    assert rows["cuenta-ahorro"]["saldo_cent"] == 1265000 + 5000


def test_insufficient_funds_and_card_credit(store):
    before = (accounts(store), len(store.list("movimientos")))
    with pytest.raises(ActionError) as error:
        store.perform("transferir", transfer(contacto="maria-lozano", importe_cent=238418))
    assert error.value.code == "insufficient_balance"
    assert (accounts(store), len(store.list("movimientos"))) == before
    store.perform("transferir", transfer(origen="tarjeta", contacto="andres-molina", importe_cent=6000))
    card = accounts(store)["tarjeta"]
    assert (card["saldo_cent"], card["disponible_cent"]) == (-37248, 112752)


@pytest.mark.parametrize("values", [{"contacto": "maria-ortega", "destino": "cuenta-ahorro"}, {"destino": "cuenta-diaria"}, {}])
def test_ambiguous_or_same_destination_writes_nothing(store, values):
    before = (accounts(store), len(store.list("movimientos")))
    with pytest.raises((ActionError, ValueError)):
        store.perform("transferir", transfer(**values))
    assert (accounts(store), len(store.list("movimientos"))) == before


def test_undo_restores_the_balances(store):
    result = store.perform("transferir", transfer(destino="cuenta-compartida"))
    store.undo(result["undo_token"])
    rows = accounts(store)
    assert (rows["cuenta-diaria"]["saldo_cent"], rows["cuenta-compartida"]["saldo_cent"]) == (238417, 84632)


def test_transfer_page_gives_the_assistant_its_place():
    page = (EXAMPLE / "pages" / "transferir.html").read_text(encoding="utf-8")
    layout = (EXAMPLE / "layout.html").read_text(encoding="utf-8")
    for slot in ("source", "recipient", "iban", "amountCents", "concept"):
        assert f'data-transfer-slot="{slot}"' in page
    assert "data-transfer-scope" in page and 'data-transfer-assistant="manual"' in page
    assert 'id="voice-fab"' in layout and "/assets/transfer-assistant/assistant.css" in layout
    script = (EXAMPLE / "assets" / "transfer.js").read_text(encoding="utf-8")
    assert "from './transfer-assistant/assistant.js'" in script and "'/api/actions/transferir'" in script
