"""Breadth-first exploration of every interleaving of a bounded protocol.

BFS gives the *shortest* counterexample. Results are honest about scope:
``holds`` only means every reachable state within the declared bounds was
checked, under the spec's assumptions (atomic steps, bounded crashes).
"""
from __future__ import annotations

import time
from collections import deque
from typing import Any, Iterator

from .expr import SpecError, thaw
from .model import END, Proc, Spec

# state = (shared tuple, ((pc, locals tuple, crashes), ...))


def initial(spec: Spec):
    shared = tuple(spec.shared.values())
    procs = tuple((p.first, tuple(p.locals.values()), 0) for p in spec.procs)
    return shared, procs


def _env(spec: Spec, state, i: int | None) -> dict[str, Any]:
    shared, procs = state
    env = dict(spec.consts)
    env.update(zip(spec.var_names, shared))
    if i is not None:
        p = spec.procs[i]
        env.update(zip(p.locals.keys(), procs[i][1]))
        env["me"] = p.me
        env["self"] = p.name
    return env


def _global_env(spec: Spec, state) -> dict[str, Any]:
    env = _env(spec, state, None)
    env["ended"] = sum(1 for pc, _, _ in state[1] if pc == END)
    env["crashes"] = sum(c for _, _, c in state[1])
    return env


def successors(spec: Spec, state) -> Iterator[tuple[dict, Any]]:
    """(action, next_state) for every enabled transition, in a fixed order."""
    shared, procs = state
    for i, p in enumerate(spec.procs):
        pc, loc, crashes = procs[i]
        if pc == END:
            continue
        env = _env(spec, state, i)
        step = p.steps[pc]
        for b, br in enumerate(step.branches):
            if br.when is not None and not br.when.eval(env):
                continue
            new_vals = [(t, e.eval(env)) for t, e in br.set]
            sh = dict(zip(spec.var_names, shared))
            lo = dict(zip(p.locals.keys(), loc))
            for t, v in new_vals:
                if t in lo:
                    lo[t] = v
                else:
                    sh[t] = v
            nprocs = list(procs)
            nprocs[i] = (br.goto, tuple(lo.values()), crashes)
            action = {"process": p.name, "label": pc, "branch": b if len(step.branches) > 1 else None, "kind": "step"}
            yield action, (tuple(sh.values()), tuple(nprocs))
        if p.crash_max and crashes < p.crash_max:
            nprocs = list(procs)
            new_loc = loc if p.keep_locals else tuple(p.locals.values())
            nprocs[i] = (p.restart, new_loc, crashes + 1)
            yield {"process": p.name, "label": pc, "branch": None, "kind": "crash"}, (shared, tuple(nprocs))


def _describe(spec: Spec, state) -> dict:
    shared, procs = state
    return {"vars": {k: thaw(v) for k, v in zip(spec.var_names, shared)},
            "processes": {p.name: {"at": procs[i][0], "locals": {k: thaw(v) for k, v in zip(p.locals, procs[i][1])},
                                   "crashes": procs[i][2]} for i, p in enumerate(spec.procs)}}


def _trace(spec: Spec, parents: dict, state) -> list[dict]:
    path = []
    while parents[state] is not None:
        prev, action = parents[state]
        path.append((prev, action, state))
        state = prev
    path.reverse()
    out = []
    for prev, action, nxt in path:
        before, after = dict(zip(spec.var_names, prev[0])), dict(zip(spec.var_names, nxt[0]))
        changes = {k: [thaw(before[k]), thaw(after[k])] for k in spec.var_names if before[k] != after[k]}
        i = next(j for j, p in enumerate(spec.procs) if p.name == action["process"])
        p = spec.procs[i]
        lb, la = dict(zip(p.locals, prev[1][i][1])), dict(zip(p.locals, nxt[1][i][1]))
        local_changes = {k: [thaw(lb[k]), thaw(la[k])] for k in p.locals if lb[k] != la[k]}
        out.append({**action, "goto": nxt[1][i][0], "changes": changes, "local_changes": local_changes})
    return out


def _inspect_state(spec: Spec, state):
    """Use the same property semantics for exploration and replay."""
    env = _global_env(spec, state)
    for inv in spec.invariants:
        if not inv.check.eval(env):
            return ("invariant", inv.name), []
    nexts = list(successors(spec, state))
    if all(pc == END for pc, _, _ in state[1]):
        for prop in spec.at_end:
            if not prop.check.eval(env):
                return ("at_end", prop.name), nexts
    elif spec.deadlock and not any(a["kind"] == "step" for a, _ in nexts):
        stuck = [p.name for i, p in enumerate(spec.procs) if state[1][i][0] != END]
        return ("deadlock", "bloqueo: " + ", ".join(stuck) + " no pueden avanzar"), nexts
    return None, nexts


def explore(spec: Spec, *, time_limit: float = 60.0) -> dict:
    t0 = time.monotonic()
    start = initial(spec)
    parents: dict[Any, Any] = {start: None}
    depth = {start: 0}
    queue = deque([start])
    transitions = 0
    terminal = 0
    status, violation = "holds", None

    def violated(kind, name, state):
        tr = _trace(spec, parents, state)
        schedule = [[a["process"], a["label"], a["kind"]] + ([a["branch"]] if a["branch"] is not None else []) for a in tr]
        return {"kind": kind, "property": name, "trace": tr, "schedule": schedule,
                "final_state": _describe(spec, state), "length": len(tr)}
    truncated = None
    while queue and violation is None:
        if time.monotonic() - t0 > time_limit:
            truncated = f"tiempo agotado ({time_limit:.0f} s)"
            break
        state = queue.popleft()
        failure, nexts = _inspect_state(spec, state)
        if failure:
            violation = violated(*failure, state)
            break
        if all(pc == END for pc, _, _ in state[1]):
            terminal += 1
        for action, nxt in nexts:
            transitions += 1
            if nxt in parents:
                continue
            if len(parents) >= spec.max_states:
                truncated = f"límite de {spec.max_states} estados"
                continue
            parents[nxt] = (state, action)
            depth[nxt] = depth[state] + 1
            queue.append(nxt)
    if violation:
        status = "violated"
    elif truncated:
        status = "inconclusive"
    return {
        "status": status,
        "spec": spec.name,
        "states": len(parents),
        "transitions": transitions,
        "terminal_states": terminal,
        "max_depth": max(depth.values()),
        "seconds": round(time.monotonic() - t0, 3),
        "exhaustive": status == "holds",
        "truncated": truncated,
        "violation": violation,
        "assumptions": assumptions(spec),
    }


def assumptions(spec: Spec) -> list[str]:
    out = ["Cada paso es atómico: lo que ocurre dentro de un paso no se intercala con otros procesos.",
           "Los procesos se intercalan paso a paso en cualquier orden posible.",
           "La conclusión vale para este modelo, no para el código: si el modelo no refleja el sistema, la prueba no lo cubre."]
    crashing = [p for p in spec.procs if p.crash_max]
    if crashing:
        out.append("Caídas: " + ", ".join(f"{p.name} hasta {p.crash_max} (reinicia en {p.restart!r}, "
                                          f"{'conserva' if p.keep_locals else 'pierde'} sus variables locales; lo compartido persiste)"
                                          for p in crashing) + ".")
    else:
        out.append("Sin caídas ni reintentos.")
    return out


def replay(spec: Spec, schedule: list) -> dict:
    """Run [[process, label, kind?, branch?], ...], including endpoint properties.

    Legacy entries without a branch keep their first-enabled-branch behaviour.
    New counterexamples always include the branch of a nondeterministic step.
    """
    state = initial(spec)
    steps = []

    def result_if_broken(at_step):
        failure, _ = _inspect_state(spec, state)
        if failure:
            kind, prop = failure
            return {"status": "violated", "at_step": at_step, "kind": kind,
                    "property": prop, "steps": steps, "state": _describe(spec, state)}
        return None

    broken = result_if_broken(0)
    if broken:
        return broken
    for n, item in enumerate(schedule):
        proc, label = item[0], item[1]
        kind = item[2] if len(item) > 2 else "step"
        options = [(a, s) for a, s in successors(spec, state) if a["process"] == proc and a["label"] == label and a["kind"] == kind]
        if not options:
            raise SpecError(f"paso {n + 1}: {proc} no puede ejecutar {label!r} ({kind}) en ese estado")
        if len(item) > 3 and item[3] is not None:
            options = [o for o in options if o[0]["branch"] == item[3]]
            if not options:
                raise SpecError(f"paso {n + 1}: rama {item[3]!r} no habilitada para {proc}.{label}")
        action = options[0][0]
        state = options[0][1]
        steps.append({**action, "broken": []})
        broken = result_if_broken(n + 1)
        if broken:
            steps[-1]["broken"] = [broken["property"]]
            return broken
    return {"status": "completed", "steps": steps, "state": _describe(spec, state)}


def counterexample_test(spec: Spec, violation: dict) -> str:
    """pytest file that replays a counterexample's order against the real system (hooks to fill in)."""
    import re as _re
    slug = _re.sub(r"[^a-z0-9]+", "_", violation["property"].lower()).strip("_")[:40] or "propiedad"
    lines = [
        f'"""Contraejemplo de «{spec.name}»: incumple «{violation["property"]}» ({violation["kind"]}).',
        "",
        "Orden exacto encontrado por el comprobador de protocolos de Vitruvius. Conecta cada paso con la",
        "llamada real del servicio en run_step y la comprobación de la propiedad en check_property.",
        '"""',
        "",
        "SCHEDULE = [",
    ]
    for action in violation["schedule"]:
        lines.append(f"    {tuple(action)!r},")
    lines += [
        "]",
        "",
        "",
        "def run_step(process, label, kind, branch=None):",
        '    """Ejecuta el paso real; branch es el índice desde cero de la elección y kind="crash" simula su caída."""',
        '    raise NotImplementedError(f"conecta {process}.{label} ({kind}) con el servicio")',
        "",
        "",
        "def check_property():",
        f'    """Devuelve True si se cumple «{violation["property"]}» en el sistema real."""',
        '    raise NotImplementedError("lee el estado real y comprueba la propiedad")',
        "",
        "",
        f"def test_{slug}():",
        "    for action in SCHEDULE:",
        "        run_step(*action)",
        "    assert check_property()",
        "",
    ]
    return "\n".join(lines)
