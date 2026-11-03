"""Small bundled protocols (invented) to start from."""
from __future__ import annotations


def payment_check_then_charge() -> dict:
    """Two retries of one payment with an idempotency key, checked and marked in separate steps."""
    return {
        "name": "Cobro con clave de idempotencia (comprobar, cobrar y marcar por separado)",
        "vars": {"processed": [], "charges": 0},
        "const": {"key": "pedido-42"},
        "processes": [{
            "name": "intento", "count": 2, "locals": {"seen": False},
            "steps": [
                {"label": "comprobar", "set": {"seen": "key in processed"}},
                {"label": "cobrar", "choose": [
                    {"when": "seen", "goto": "end"},
                    {"when": "not seen", "set": {"charges": "charges + 1"}, "goto": "marcar"}]},
                {"label": "marcar", "set": {"processed": "append(processed, key)"}, "goto": "end"},
            ],
        }],
        "invariants": [{"name": "un solo cobro por clave", "check": "charges <= 1"}],
        "at_end": [{"name": "el pedido queda cobrado", "check": "charges == 1"}],
    }


def payment_atomic_claim() -> dict:
    """Fixed version: claiming the key is one atomic insert-if-absent; a crash after charging is retried."""
    return {
        "name": "Cobro con reserva atómica de la clave y caídas",
        "vars": {"claims": {}, "charges": 0},
        "const": {"key": "pedido-42"},
        "processes": [{
            "name": "intento", "count": 2, "locals": {"mine": False},
            "steps": [
                {"label": "reservar", "set": {
                    "mine": "key not in claims",
                    "claims": "claims if key in claims else put(claims, key, me)"}},
                {"label": "cobrar", "choose": [
                    {"when": "not mine", "goto": "end"},
                    {"when": "mine and claims[key] == me", "set": {"charges": "charges + 1"}, "goto": "confirmar"}]},
                {"label": "confirmar", "set": {"claims": "put(claims, key, 'hecho')"}, "goto": "end"},
            ],
            "crash": {"max": 1, "restart": "reservar"},
        }],
        "invariants": [{"name": "un solo cobro por clave", "check": "charges <= 1"}],
        "deadlock": True,
    }


def lost_update() -> dict:
    """Read-modify-write counter: two increments can lose one."""
    return {
        "name": "Contador con leer-modificar-escribir",
        "vars": {"counter": 0},
        "processes": [{
            "name": "hilo", "count": 2, "locals": {"tmp": 0},
            "steps": [{"label": "leer", "set": {"tmp": "counter"}},
                      {"label": "escribir", "set": {"counter": "tmp + 1"}}],
        }],
        "at_end": [{"name": "dos incrementos", "check": "counter == 2"}],
    }


def two_locks() -> dict:
    """Two workers take two locks in opposite order."""
    return {
        "name": "Dos cerrojos en orden opuesto",
        "vars": {"a": None, "b": None},
        "processes": [
            {"name": "x", "steps": [
                {"label": "coge_a", "when": "a == None", "set": {"a": "self"}},
                {"label": "coge_b", "when": "b == None", "set": {"b": "self"}},
                {"label": "suelta", "set": {"a": "None", "b": "None"}}]},
            {"name": "y", "steps": [
                {"label": "coge_b", "when": "b == None", "set": {"b": "self"}},
                {"label": "coge_a", "when": "a == None", "set": {"a": "self"}},
                {"label": "suelta", "set": {"a": "None", "b": "None"}}]},
        ],
    }


EXAMPLES = {
    "pago-no-atomico": payment_check_then_charge,
    "pago-reserva-atomica": payment_atomic_claim,
    "contador": lost_update,
    "cerrojos": two_locks,
}
