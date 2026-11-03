"""Protocol specification: shared state, processes made of labelled atomic steps,
bounded crashes with restart, invariants and end conditions.

Spec (JSON)::

    {"name": "...",
     "vars": {"db": {}, "charged": 0},
     "processes": [
       {"name": "cliente", "count": 2, "locals": {"seen": null},
        "steps": [
          {"label": "check", "set": {"seen": "key in db"}},
          {"label": "charge", "when": "not seen", "set": {"charged": "charged + 1"}},
          {"label": "mark", "set": {"db": "put(db, key, 'ok')"}, "goto": "end"}],
        "crash": {"max": 1, "restart": "check"}}],
     "invariants": [{"name": "un solo cobro", "check": "charged <= 1"}],
     "at_end": [{"name": "cobrado", "check": "charged == 1"}]}

Inside a process, names resolve to its locals, then shared vars, then ``me``
(1-based copy number) and ``self`` (process name). Each step is atomic: all
``set`` expressions read the state *before* the step. A step without ``goto``
continues with the next step in the list; after the last one the process ends.
A step may instead list ``choose`` alternatives (each with when/set/goto): a
nondeterministic choice. Constants can be given in ``const``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .expr import Expr, SpecError, freeze

END = "end"
RESERVED = {"me", "self", "end"}


@dataclass
class Branch:
    when: Expr | None
    set: list[tuple[str, Expr]]
    goto: str


@dataclass
class Step:
    label: str
    branches: list[Branch]


@dataclass
class Proc:
    name: str
    base: str
    me: int
    locals: dict[str, Any]
    steps: dict[str, Step]
    order: list[str]
    crash_max: int = 0
    restart: str | None = None
    keep_locals: bool = False

    @property
    def first(self) -> str:
        return self.order[0] if self.order else END


@dataclass
class Prop:
    name: str
    check: Expr


@dataclass
class Spec:
    name: str
    shared: dict[str, Any]
    consts: dict[str, Any]
    procs: list[Proc]
    invariants: list[Prop]
    at_end: list[Prop]
    deadlock: bool = True
    max_states: int = 200_000
    raw: dict = field(default_factory=dict)

    @property
    def var_names(self) -> list[str]:
        return list(self.shared)


def _props(items, where) -> list[Prop]:
    out = []
    for i, p in enumerate(items or []):
        if isinstance(p, str):
            p = {"name": p, "check": p}
        if not isinstance(p, dict) or "check" not in p:
            raise SpecError(f"{where}[{i}] necesita 'check'")
        out.append(Prop(str(p.get("name") or p["check"]), Expr(p["check"])))
    return out


def load_spec(data: dict) -> Spec:
    if not isinstance(data, dict):
        raise SpecError("la especificación debe ser un objeto")
    shared = {str(k): freeze(v) for k, v in (data.get("vars") or {}).items()}
    consts = {str(k): freeze(v) for k, v in (data.get("const") or {}).items()}
    for k in list(shared) + list(consts):
        if k in RESERVED or not k.isidentifier():
            raise SpecError(f"nombre de variable no válido: {k!r}")
    if set(shared) & set(consts):
        raise SpecError(f"nombres repetidos entre vars y const: {sorted(set(shared) & set(consts))}")
    procs: list[Proc] = []
    for i, p in enumerate(data.get("processes") or []):
        base = str(p.get("name") or f"p{i + 1}")
        count = int(p.get("count", 1))
        if count < 1 or count > 8:
            raise SpecError(f"{base}: count debe estar entre 1 y 8")
        loc = {str(k): freeze(v) for k, v in (p.get("locals") or {}).items()}
        for k in loc:
            if k in RESERVED or not k.isidentifier():
                raise SpecError(f"{base}: nombre local no válido {k!r}")
            if k in shared or k in consts:
                raise SpecError(f"{base}: la local {k!r} tapa una variable compartida; usa otro nombre")
        raw_steps = p.get("steps") or []
        if not raw_steps:
            raise SpecError(f"{base}: sin pasos")
        labels = []
        for j, s in enumerate(raw_steps):
            lab = str(s.get("label") or f"s{j + 1}")
            if lab == END or lab in labels:
                raise SpecError(f"{base}: etiqueta repetida o reservada {lab!r}")
            labels.append(lab)
        steps: dict[str, Step] = {}
        writable = set(loc) | set(shared)
        readable = writable | set(consts) | {"me", "self"}
        for j, s in enumerate(raw_steps):
            lab = labels[j]
            default_next = labels[j + 1] if j + 1 < len(labels) else END
            alts = s.get("choose") or [s]
            branches = []
            for a in alts:
                when = Expr(a["when"]) if a.get("when") not in (None, "", True) else None
                sets = []
                for tgt, e in (a.get("set") or {}).items():
                    if tgt not in writable:
                        raise SpecError(f"{base}.{lab}: no se puede asignar {tgt!r} (no es local ni compartida)")
                    sets.append((tgt, Expr(str(e)) if not isinstance(e, Expr) else e))
                goto = str(a.get("goto") or (s.get("goto") if a is not s else None) or default_next)
                if goto != END and goto not in labels:
                    raise SpecError(f"{base}.{lab}: goto a etiqueta inexistente {goto!r}")
                for ex in ([when] if when else []) + [e for _, e in sets]:
                    unknown = ex.names - readable
                    if unknown:
                        raise SpecError(f"{base}.{lab}: nombres desconocidos {sorted(unknown)} en {ex.text!r}")
                branches.append(Branch(when, sets, goto))
            steps[lab] = Step(lab, branches)
        crash = p.get("crash") or {}
        cmax = int(crash.get("max", 0))
        restart = crash.get("restart") or (labels[0] if cmax else None)
        if cmax and restart not in labels:
            raise SpecError(f"{base}: restart a etiqueta inexistente {restart!r}")
        for n in range(1, count + 1):
            name = base if count == 1 else f"{base}{n}"
            procs.append(Proc(name, base, n, dict(loc), steps, labels, cmax, restart, bool(crash.get("keep_locals"))))
    if not procs:
        raise SpecError("no hay procesos")
    if len({p.name for p in procs}) != len(procs):
        raise SpecError("nombres de proceso repetidos")
    readable = set(shared) | set(consts)
    inv = _props(data.get("invariants"), "invariants")
    end = _props(data.get("at_end"), "at_end")
    for pr in inv + end:
        bad = pr.check.names - readable - {"ended", "crashes"}
        if bad:
            raise SpecError(f"propiedad {pr.name!r}: solo puede leer variables compartidas o constantes; desconocidas {sorted(bad)}")
    max_states = int(data.get("max_states", 200_000))
    if not 1 <= max_states <= 5_000_000:
        raise SpecError("max_states debe estar entre 1 y 5.000.000")
    return Spec(str(data.get("name") or "protocolo"), shared, consts, procs, inv, end,
                bool(data.get("deadlock", True)), max_states, raw=data)
