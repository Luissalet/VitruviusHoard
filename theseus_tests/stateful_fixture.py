"""Recipe for the invented quotes service (fixtures/quotes): create, add/remove lines, discount, confirm, retry.

The oracles come from the service's documented rules (module docstring of quotes_v2.py), not from endpoint names:
integer-cent totals rounded half up after the discount, one charge per confirmed quote, and a retried confirmation
with the same Idempotency-Key answers with the same charge.
"""
import copy
from pathlib import Path

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "quotes"
EXPECTED_TOTAL = "(subtotal * (100 - pct) + 50) // 100"


def service(version):
    return str(FIXTURES / ("quotes_%s.py" % version))


def target(version):
    return {"argv": ["{python}", service(version), "--db", "{sandbox}/quotes.db", "--port", "{port}"],
            "ready": "/health", "ready_timeout_seconds": 20, "label": "quotes " + version}


def quotes_recipe(version="v1", **overrides):
    recipe = {
        "name": "quotes",
        "description": "Quote lifecycle: totals after edits and discount, single charge on confirmation and retries.",
        "target": target(version),
        "watch": {"sqlite": "quotes.db", "tables": ["quotes", "lines", "charges"]},
        "queries": {"charges": "SELECT COUNT(*) FROM charges", "stored_total": "SELECT COALESCE(SUM(total_cents), 0) FROM quotes"},
        "model": {"quote_id": None, "state": "none", "subtotal": 0, "pct": 0, "line_ids": [], "amounts": [],
                  "key": "", "charge_id": "", "charges": 0},
        "actions": [
            {"name": "create_quote", "pre": "quote_id == None",
             "params": {"customer": {"kind": "sampled_from", "values": ["Talleres Norte", "Hostal Brisa", "Imprenta Sol"]}},
             "request": {"method": "POST", "path": "/quotes", "body": {"customer": "{customer}"}},
             "expect_status": 201, "extract": {"new_id": "body['id']"},
             "update": {"quote_id": "new_id", "state": "'draft'"},
             "post": [{"name": "starts empty", "expr": "body['total_cents'] == 0"}]},
            {"name": "add_line", "pre": "state == 'draft'",
             "params": {"qty": {"kind": "integers", "min": 1, "max": 5}, "unit": {"kind": "integers", "min": 1, "max": 9999}},
             "request": {"method": "POST", "path": "/quotes/{quote_id}/lines",
                         "body": {"description": "item", "qty": "{qty}", "unit_cents": "{unit}"}},
             "expect_status": 201, "extract": {"line_id": "body['line_id']"},
             "update": {"line_ids": "line_ids + [line_id]", "amounts": "amounts + [qty * unit]", "subtotal": "subtotal + qty * unit"},
             "post": [{"name": "total after edit", "expr": "body['total_cents'] == " + EXPECTED_TOTAL,
                       "explain": "Total is the discounted subtotal in cents, rounded half up."}]},
            {"name": "remove_line", "pre": "state == 'draft' and len(line_ids) > 0", "pick": {"line": "line_ids"},
             "request": {"method": "DELETE", "path": "/quotes/{quote_id}/lines/{line}"},
             "expect_status": 200,
             "update": {"subtotal": "subtotal - amounts[line_index]",
                        "line_ids": "line_ids[:line_index] + line_ids[line_index + 1:]",
                        "amounts": "amounts[:line_index] + amounts[line_index + 1:]"},
             "post": [{"name": "total after edit", "expr": "body['total_cents'] == " + EXPECTED_TOTAL,
                       "explain": "Total is the discounted subtotal in cents, rounded half up."}]},
            {"name": "apply_discount", "pre": "state == 'draft'",
             "params": {"percent": {"kind": "integers", "min": 0, "max": 50}},
             "request": {"method": "POST", "path": "/quotes/{quote_id}/discount", "body": {"percent": "{percent}"}},
             "expect_status": 200, "update": {"pct": "percent"},
             "post": [{"name": "total after edit", "expr": "body['total_cents'] == " + EXPECTED_TOTAL}]},
            {"name": "confirm", "pre": "state == 'draft' and len(line_ids) > 0",
             "params": {"new_key": {"kind": "text", "min_len": 8, "max_len": 8, "alphabet": "abcdef0123456789"}},
             "request": {"method": "POST", "path": "/quotes/{quote_id}/confirm", "headers": {"Idempotency-Key": "{new_key}"}},
             "expect_status": 200, "extract": {"cid": "body['charge_id']"},
             "update": {"state": "'confirmed'", "key": "new_key", "charge_id": "cid", "charges": "charges + 1"},
             "post": [{"name": "charged the total", "expr": "body['amount_cents'] == " + EXPECTED_TOTAL}]},
            {"name": "retry_confirm", "pre": "state == 'confirmed'",
             "request": {"method": "POST", "path": "/quotes/{quote_id}/confirm", "headers": {"Idempotency-Key": "{key}"}},
             "expect_status": 200,
             "post": [{"name": "same charge on retry", "expr": "body['charge_id'] == charge_id",
                       "explain": "A retried confirmation with the same key answers with the stored charge."}]},
        ],
        "invariants": [
            {"name": "one charge per confirmation", "expr": "sql['charges'][0][0] == charges",
             "explain": "The charges table holds exactly one row per confirmed quote."},
            {"name": "stored total", "expr": "sql['stored_total'][0][0] == " + EXPECTED_TOTAL},
        ],
        "runs": 25, "max_length": 8, "seed": 5,
    }
    recipe.update(copy.deepcopy(overrides))
    return recipe
