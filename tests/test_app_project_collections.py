import json
import runpy
import sqlite3
import urllib.error
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from vitruvius_hoard.agent_tools import call_tool
from vitruvius_hoard.app_projects import AppProjects
from vitruvius_hoard.app_runtime import ActionError, Collections, validate_spec


def synthetic_iban(suffix):
    bban = f"{suffix:014d}"
    return f"ZZ{98 - int(bban + '353500') % 97:02d}{bban}"


def transfer_spec():
    def ref(name, collection, required=True):
        return {"name": name, "type": "ref", "collection": collection, "required": required}

    def input_value(name):
        return {"input": name}

    source = input_value("source_account_id")
    destination = {"coalesce": [input_value("destination_account_id"), {"record": "own_destination", "field": "id"}]}
    contact = input_value("destination_contact_id")
    destination_iban = {"coalesce": [input_value("destination_iban"), {"record": "destination_contact", "field": "iban"}]}
    amount = input_value("amount_cents")
    debit = {"negate": amount}
    return {
        "format": "vitruvius-app/v2",
        "name": "Sample project",
        "collections": {
            "accounts": {
                "fields": [
                    {"name": "name", "type": "text"},
                    {"name": "iban", "type": "text", "format": "iban"},
                    {"name": "balance_cents", "type": "integer", "min": 0},
                ],
                "records": [
                    {"id": "daily", "name": "Daily", "iban": synthetic_iban(1), "balance_cents": 10000},
                    {"id": "reserve", "name": "Reserve", "iban": synthetic_iban(2), "balance_cents": 5000},
                ],
            },
            "contacts": {
                "fields": [{"name": "name", "type": "text"}, {"name": "iban", "type": "text", "format": "iban"}],
                "records": [
                    {"id": "supplier", "name": "Supplier", "iban": synthetic_iban(3)},
                    {"id": "own_alias", "name": "Own alias", "iban": synthetic_iban(2)},
                ],
            },
            "movements": {
                "fields": [
                    ref("account_id", "accounts"),
                    {"name": "amount_cents", "type": "integer"},
                    {"name": "concept", "type": "text"},
                    ref("destination_contact_id", "contacts", False),
                    {"name": "destination_iban", "type": "text", "format": "iban", "required": False},
                ],
            },
        },
        "actions": {
            "transfer": {
                "confirmable_by_voice": True,
                "input": [
                    ref("source_account_id", "accounts"),
                    ref("destination_account_id", "accounts", False),
                    ref("destination_contact_id", "contacts", False),
                    {"name": "destination_iban", "type": "text", "format": "iban", "required": False},
                    {"name": "amount_cents", "type": "integer", "min": 1},
                    {"name": "concept", "type": "text"},
                ],
                "exactly_one": ["destination_account_id", "destination_contact_id", "destination_iban"],
                "lookups": {
                    "destination_contact": {"collection": "contacts", "field": "id", "equals": contact},
                    "own_destination": {"collection": "accounts", "field": "iban", "equals": destination_iban},
                },
                "different": [source, destination],
                "effects": [
                    {"op": "adjust", "collection": "accounts", "id": source, "field": "balance_cents", "amount": debit},
                    {"op": "adjust", "collection": "accounts", "id": destination, "field": "balance_cents",
                     "amount": amount, "when": destination},
                    {"op": "create", "collection": "movements",
                     "values": {"account_id": source, "amount_cents": debit, "concept": input_value("concept"),
                                "destination_contact_id": contact, "destination_iban": destination_iban}},
                    {"op": "create", "collection": "movements", "when": destination,
                     "values": {"account_id": destination, "amount_cents": amount, "concept": input_value("concept")}},
                ],
            },
        },
    }


def transfer(**values):
    return {"source_account_id": "daily", "amount_cents": 1250, "concept": "Sample payment", **values}


def source_files(spec):
    return {
        "project.json": json.dumps(spec),
        "layout.html": "<!doctype html><html lang=\"en\"><title>{{name}}</title><main>{{content}}</main></html>",
        "pages/index.html": "<h1>{{name}}</h1>",
    }


def request(url, path, body=None, key=None):
    headers = {"Content-Type": "application/json"}
    if key is not None:
        headers["Idempotency-Key"] = key
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url + path, data=data, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as error:
        with error:
            return error.code, json.load(error)


def balances(store):
    return {row["id"]: row["balance_cents"] for row in store.list("accounts")}


def test_owned_preview_collection_routes_idempotency_and_atomic_undo(tmp_path):
    projects = AppProjects(tmp_path)
    try:
        project = projects.create("Sample project", "custom", files=source_files(transfer_spec()))
        assert "server.py" in project["files"]
        url = projects.preview(project["id"])["url"]
        assert request(url, "/api/collections/accounts?q=res")[1] == {
            "records": [{"id": "reserve", "name": "Reserve", "iban": synthetic_iban(2), "balance_cents": 5000}],
        }
        assert request(url, "/api/collections/missing")[0] == 404
        assert request(url, "/api/schema")[1]["actions"]["transfer"]["confirmable_by_voice"]
        values = transfer(destination_account_id="reserve")
        status, result = request(url, "/api/actions/transfer", values, key="same-confirmation")
        assert status == 200 and result["ok"] is True
        assert [change["operation"] for change in result["changes"]] == ["adjust", "adjust", "create", "create"]
        assert request(url, "/api/actions/transfer", values, key="same-confirmation") == (200, result)
        assert request(url, "/api/actions/transfer", {**values, "amount_cents": 110}, key="same-confirmation")[1]["code"] == "idempotency_conflict"
        assert request(url, "/api/collections/accounts/daily")[1]["balance_cents"] == 8750
        assert request(url, "/api/collections/accounts/reserve")[1]["balance_cents"] == 6250
        assert len(request(url, "/api/collections/movements")[1]["records"]) == 2

        undo = f"/api/action-receipts/{result['undo_token']}/undo"
        assert request(url, undo, {})[0] == 200
        assert request(url, undo, {})[1]["code"] == "undo_conflict"
        assert request(url, "/api/collections/accounts/daily")[1]["balance_cents"] == 10000
        assert request(url, "/api/collections/accounts/reserve")[1]["balance_cents"] == 5000
        assert request(url, "/api/collections/movements")[1] == {"records": []}
        assert request(url, "/api/actions/transfer", values, key="same-confirmation")[0] == 409
    finally:
        projects.close()


@pytest.mark.parametrize("destination", [
    {"destination_account_id": "reserve"},
    {"destination_contact_id": "own_alias"},
    {"destination_iban": synthetic_iban(2)[:4].lower() + " " + synthetic_iban(2)[4:]},
])
def test_own_destinations_credit_the_matching_account(tmp_path, destination):
    store = Collections(tmp_path / "data.db", validate_spec(transfer_spec()))
    result = store.perform("transfer", transfer(**destination))
    assert balances(store) == {"daily": 8750, "reserve": 6250}
    rows = store.list("movements")
    assert {(row["account_id"], row["amount_cents"]) for row in rows} == {("daily", -1250), ("reserve", 1250)}
    assert len(result["changes"]) == 4


@pytest.mark.parametrize("destination", [
    {"destination_contact_id": "supplier"},
    {"destination_iban": synthetic_iban(3)},
])
def test_external_destinations_only_debit(tmp_path, destination):
    store = Collections(tmp_path / "data.db", validate_spec(transfer_spec()))
    result = store.perform("transfer", transfer(**destination))
    assert balances(store) == {"daily": 8750, "reserve": 5000}
    row, = store.list("movements")
    assert row["account_id"] == "daily" and row["amount_cents"] == -1250
    assert row["destination_iban"] == synthetic_iban(3)
    if "destination_contact_id" in destination:
        assert row["destination_contact_id"] == "supplier"
    assert len(result["changes"]) == 2


@pytest.mark.parametrize("values", [
    {},
    {"destination_account_id": "daily"},
    {"destination_account_id": "absent"},
    {"destination_iban": synthetic_iban(1)},
    {"destination_iban": "ZZ0012345678901234"},
    {"destination_account_id": "reserve", "destination_contact_id": "supplier"},
    {"destination_account_id": "reserve", "amount_cents": 0},
    {"destination_account_id": "reserve", "amount_cents": True},
    {"destination_account_id": "reserve", "amount_cents": 1250.0},
    {"destination_account_id": "reserve", "amount_cents": 2**53},
    {"destination_account_id": "reserve", "concept": ""},
])
def test_invalid_transfer_writes_nothing(tmp_path, values):
    store = Collections(tmp_path / "data.db", validate_spec(transfer_spec()))
    with pytest.raises(ValueError):
        store.perform("transfer", transfer(**values))
    assert balances(store) == {"daily": 10000, "reserve": 5000}
    assert store.list("movements") == []


def test_sql_failure_on_last_effect_rolls_back_balances_receipt_and_movements(tmp_path):
    store = Collections(tmp_path / "data.db", validate_spec(transfer_spec()))
    with store.connection() as conn:
        conn.execute("""CREATE TRIGGER fail_last_effect BEFORE INSERT ON app_collection_records
            WHEN NEW.collection = 'movements' AND json_extract(NEW.body, '$.amount_cents') > 0
            BEGIN SELECT RAISE(ABORT, 'abort after debit, credit and first movement'); END""")
    values = transfer(destination_account_id="reserve")
    with pytest.raises(sqlite3.IntegrityError, match="after debit, credit and first movement"):
        store.perform("transfer", values, "failed-confirmation")
    assert balances(store) == {"daily": 10000, "reserve": 5000}
    assert store.list("movements") == []
    with store.connection() as conn:
        assert conn.execute("SELECT count(*) FROM app_action_receipts").fetchone() == (0,)
        conn.execute("DROP TRIGGER fail_last_effect")
    assert store.perform("transfer", values, "failed-confirmation")["ok"]


def test_concurrent_transfers_cannot_overspend(tmp_path):
    store = Collections(tmp_path / "data.db", validate_spec(transfer_spec()))
    ready = Barrier(2, timeout=5)

    def send(index):
        ready.wait()
        try:
            store.perform("transfer", transfer(destination_account_id="reserve", amount_cents=7000), str(index))
            return "ok"
        except ActionError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(send, range(2))) == ["insufficient_balance", "ok"]
    assert balances(store) == {"daily": 3000, "reserve": 12000}
    assert len(store.list("movements")) == 2


def test_undo_with_later_adjustment_is_atomic_and_supports_reverse_order(tmp_path):
    store = Collections(tmp_path / "data.db", validate_spec(transfer_spec()))
    first = store.perform("transfer", transfer(destination_account_id="reserve"))
    later = store.perform("transfer", transfer(destination_contact_id="supplier"))
    with pytest.raises(ActionError, match="later action") as error:
        store.undo(first["undo_token"])
    assert error.value.code == "undo_conflict"
    assert balances(store) == {"daily": 7500, "reserve": 6250}
    assert len(store.list("movements")) == 3
    store.undo(later["undo_token"])
    store.undo(first["undo_token"])
    assert balances(store) == {"daily": 10000, "reserve": 5000}
    assert store.list("movements") == []


def test_undo_preserves_later_references_and_rolls_back_any_partial_inverse(tmp_path):
    spec = transfer_spec()
    spec["actions"]["add_contact"] = {
        "input": [],
        "effects": [{"op": "create", "collection": "contacts", "values": {"name": "New", "iban": synthetic_iban(4)}}],
    }
    store = Collections(tmp_path / "data.db", validate_spec(spec))
    added = store.perform("add_contact", {})
    contact_id = added["changes"][0]["record"]["id"]
    payment = store.perform("transfer", transfer(destination_contact_id=contact_id))
    with pytest.raises(ActionError, match="later record refers"):
        store.undo(added["undo_token"])
    assert store.get("contacts", contact_id)["name"] == "New"
    assert store.list("movements")[0]["destination_contact_id"] == contact_id
    store.undo(payment["undo_token"])
    store.undo(added["undo_token"])
    assert {row["id"] for row in store.list("contacts")} == {"supplier", "own_alias"}


def test_collection_seeds_are_transactional_and_loaded_once(tmp_path):
    spec = transfer_spec()
    schema = spec["collections"]["movements"]
    schema["records"] = [{"id": "starting", "account_id": "absent", "amount_cents": -5, "concept": "Initial"}]
    path = tmp_path / "data.db"
    with pytest.raises(ActionError, match="not found"):
        Collections(path, validate_spec(spec))
    schema["records"][0]["account_id"] = "daily"
    store = Collections(path, validate_spec(spec))
    assert store.get("movements", "starting")["amount_cents"] == -5
    spec["collections"]["accounts"]["records"][0]["balance_cents"] = 1
    store = Collections(path, validate_spec(spec))
    assert store.get("accounts", "daily")["balance_cents"] == 10000


@pytest.mark.parametrize("invalid_effect", [
    {"op": "exec", "collection": "accounts", "code": "print('no')"},
    {"op": "adjust", "collection": "accounts", "id": {"input": "wrong"}, "field": "balance_cents", "amount": 1},
    {"op": "create", "collection": "movements", "values": {"account_id": "daily"}},
])
def test_project_schema_rejects_undeclared_operations_and_fields(invalid_effect):
    spec = transfer_spec()
    spec["actions"]["transfer"]["effects"].append(invalid_effect)
    with pytest.raises(ValueError):
        validate_spec(spec)


def test_agent_tool_native_rest_and_standalone_export(services, client, tmp_path):
    project = call_tool(services, "app_project_create", {
        "name": "Sample project", "template": "custom", "files": source_files(transfer_spec()),
    })
    id = project["id"]
    path = f"/api/app-projects/{id}/call"
    try:
        schema = call_tool(services, "app_project_call", {"id": id, "operation": "schema"})
        assert schema == transfer_spec()
        funds = client.post(path, json={"operation": "list", "collection": "accounts"})
        assert funds.status_code == 200 and len(funds.json()["records"]) == 2
        invalid = client.post(path, json={"operation": "invoke", "action": "transfer",
                                         "data": transfer(destination_account_id="reserve", amount_cents=11000)})
        assert invalid.status_code == 409 and invalid.json()["code"] == "insufficient_balance"

        result = call_tool(services, "app_project_call", {"id": id, "operation": "invoke", "action": "transfer",
                                                        "data": transfer(destination_account_id="reserve")})
        bundle = services.app_projects.export(id, include_data=True)
        extracted = tmp_path / "standalone"
        with zipfile.ZipFile(bundle["path"]) as archive:
            assert archive.read("server.py").decode() == project["files"]["server.py"]
            archive.extractall(extracted)
        runtime = runpy.run_path(str(extracted / "server.py"))
        with runtime["make_server"](extracted, extracted / "data" / "app.db") as listener:
            assert listener.server_port > 0
        copied = runtime["Collections"](extracted / "data" / "app.db", runtime["validate_spec"](schema))
        assert balances(copied) == {"daily": 8750, "reserve": 6250}
        assert len(copied.list("movements")) == 2
        assert call_tool(services, **{"name": result["undo"]["tool"], "arguments": result["undo"]["arguments"]})["ok"]
    finally:
        services.app_projects.stop(id)
