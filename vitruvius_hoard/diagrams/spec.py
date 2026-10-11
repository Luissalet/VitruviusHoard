"""What a diagram is made of, and the catalogue of types grouped by the question they answer.

The model supplies structure only (nodes, edges, groups, messages, events, tasks); layout, routing and colours are code. The
workflow is pattern first, type second: ``pick_type(intent)`` maps a request to a semantic pattern and its best type, and
``type_card(type)`` returns only that type's card (fields, rules, a minimal example) so a small model reads one card, not 44.
"""

from __future__ import annotations

import re
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

DiagramType = Literal["flowchart", "architecture", "state", "er", "swimlane", "sequence", "timeline", "gantt"]


class Field_(BaseModel):
    name: str = Field(..., max_length=60)
    type: str = Field("", max_length=40)
    key: Literal["", "pk", "fk"] = ""


class Node(BaseModel):
    id: str = Field(..., min_length=1, max_length=60)
    label: str = Field("", max_length=160)
    group: str = Field("", max_length=60, description="architecture: the box it sits in; swimlane: its lane.")
    shape: Literal["box", "round", "diamond", "pill", "cylinder"] = "box"
    fields: list[Field_] = Field(default_factory=list, max_length=30, description="er: the entity's columns.")

    @model_validator(mode="after")
    def _label(self):
        if not self.label:
            self.label = self.id
        return self


class Edge(BaseModel):
    source: str = Field(..., alias="from", min_length=1, max_length=60)
    target: str = Field(..., alias="to", min_length=1, max_length=60)
    label: str = Field("", max_length=80)
    style: Literal["solid", "dashed"] = "solid"
    cardinality: str = Field("", max_length=12, description="er: e.g. 1..n, 0..1 (drawn at the target end).")

    model_config = {"populate_by_name": True}


class Group(BaseModel):
    id: str = Field(..., min_length=1, max_length=60)
    label: str = Field("", max_length=80)


class Message(BaseModel):
    source: str = Field(..., alias="from", min_length=1, max_length=60)
    target: str = Field(..., alias="to", min_length=1, max_length=60)
    label: str = Field("", max_length=120)
    reply: bool = False

    model_config = {"populate_by_name": True}


class Event(BaseModel):
    when: str = Field(..., min_length=1, max_length=40)
    label: str = Field(..., min_length=1, max_length=120)


class Task(BaseModel):
    id: str = Field("", max_length=60)
    label: str = Field(..., min_length=1, max_length=80)
    start: float = Field(..., description="Day number or any unit; ISO dates are converted by the importer.")
    end: float
    lane: str = Field("", max_length=60)

    @model_validator(mode="after")
    def _order(self):
        if self.end < self.start:
            raise ValueError(f"task '{self.label}' ends before it starts")
        return self


class Diagram(BaseModel):
    type: DiagramType
    title: str = Field("", max_length=120)
    direction: Literal["TB", "LR"] = Field("TB", description="Graph types: top-to-bottom or left-to-right.")
    nodes: list[Node] = Field(default_factory=list, max_length=80)
    edges: list[Edge] = Field(default_factory=list, max_length=200)
    groups: list[Group] = Field(default_factory=list, max_length=20)
    participants: list[str] = Field(default_factory=list, max_length=12, description="sequence: column order.")
    messages: list[Message] = Field(default_factory=list, max_length=80)
    events: list[Event] = Field(default_factory=list, max_length=40)
    tasks: list[Task] = Field(default_factory=list, max_length=60)
    unit: str = Field("d", max_length=12, description="gantt: label of the time unit on the axis.")

    @field_validator("nodes")
    @classmethod
    def _unique(cls, nodes):
        seen = set()
        for n in nodes:
            if n.id in seen:
                raise ValueError(f"node id '{n.id}' appears twice")
            seen.add(n.id)
        return nodes

    @model_validator(mode="after")
    def _consistent(self):
        ids = {n.id for n in self.nodes}
        if self.type in GRAPH_TYPES:
            if not self.nodes:
                raise ValueError(f"a {self.type} needs nodes")
            missing = sorted(({e.source for e in self.edges} | {e.target for e in self.edges}) - ids)
            if missing:
                raise ValueError(f"edges point at unknown nodes: {', '.join(missing)}")
        if self.type == "sequence":
            if not self.messages:
                raise ValueError("a sequence needs messages")
            order = list(self.participants)
            for m in self.messages:
                for p in (m.source, m.target):
                    if p not in order:
                        order.append(p)
            self.participants = order
        if self.type == "timeline" and not self.events:
            raise ValueError("a timeline needs events")
        if self.type == "gantt" and not self.tasks:
            raise ValueError("a gantt needs tasks")
        return self


GRAPH_TYPES = ("flowchart", "architecture", "state", "er", "swimlane")

#: pattern -> (question it answers, types in order of preference, trigger words EN/ES)
PATTERNS: dict[str, tuple[str, list[str], list[str]]] = {
    "process": ("How does something get done, step by step, with decisions?", ["flowchart", "swimlane"],
                ["process", "flow", "steps", "decision", "workflow", "proceso", "flujo", "pasos", "decisión", "algoritmo"]),
    "structure": ("What are the parts of a system and how do they connect?", ["architecture", "flowchart"],
                  ["architecture", "system", "components", "services", "infra", "arquitectura", "sistema", "componentes", "servicios", "módulos"]),
    "interaction": ("Who talks to whom, in what order?", ["sequence"],
                    ["sequence", "request", "api call", "handshake", "protocol", "secuencia", "petición", "llamada", "protocolo", "mensajes"]),
    "lifecycle": ("Which states can a thing be in and what moves it between them?", ["state"],
                  ["state", "status", "lifecycle", "transition", "estado", "ciclo de vida", "transición"]),
    "data": ("What entities exist and how do they relate?", ["er"],
             ["entity", "schema", "tables", "database", "relation", "entidad", "esquema", "tablas", "base de datos", "relación", "modelo de datos"]),
    "responsibility": ("Who does each step?", ["swimlane"],
                       ["swimlane", "who does", "roles", "departments", "handoff", "carriles", "quién hace", "responsables", "departamentos"]),
    "chronology": ("What happened when?", ["timeline"],
                   ["timeline", "history", "milestones", "dates", "cronología", "historia", "hitos", "fechas", "línea de tiempo"]),
    "schedule": ("What runs when, for how long, in parallel?", ["gantt"],
                 ["gantt", "schedule", "plan", "roadmap", "sprint", "calendario", "planificación", "hoja de ruta", "duración"]),
}

CARDS: dict[str, dict] = {
    "flowchart": {"pattern": "process", "use": "Steps and decisions in order. Up to ~25 nodes; split bigger flows.",
                  "fields": "nodes[{id,label,shape: box|round|diamond|pill}], edges[{from,to,label}], direction TB|LR",
                  "rules": ["One start (pill) and clear ends.", "Decisions are diamonds with labelled exits (yes/no).",
                            "Labels are verbs: 'Validate order', not 'Validation'."],
                  "example": {"type": "flowchart", "nodes": [{"id": "a", "label": "Start", "shape": "pill"},
                              {"id": "b", "label": "Valid?", "shape": "diamond"}, {"id": "c", "label": "Save"}],
                              "edges": [{"from": "a", "to": "b"}, {"from": "b", "to": "c", "label": "yes"}]}},
    "architecture": {"pattern": "structure", "use": "Components grouped by boundary (client, backend, data), with the calls between them.",
                     "fields": "groups[{id,label}], nodes[{id,label,group,shape: box|cylinder}], edges[{from,to,label}]",
                     "rules": ["Group by trust or deployment boundary.", "Stores are cylinders.", "Edge labels say what travels (HTTP, SQL, events)."],
                     "example": {"type": "architecture", "groups": [{"id": "be", "label": "Backend"}],
                                 "nodes": [{"id": "ui", "label": "Web app"}, {"id": "api", "label": "API", "group": "be"},
                                           {"id": "db", "label": "Postgres", "group": "be", "shape": "cylinder"}],
                                 "edges": [{"from": "ui", "to": "api", "label": "HTTPS"}, {"from": "api", "to": "db", "label": "SQL"}]}},
    "state": {"pattern": "lifecycle", "use": "States and the events that move between them.",
              "fields": "nodes[{id,label,shape: round}], edges[{from,to,label: event}]",
              "rules": ["States are nouns or adjectives; edges are events.", "Mark the initial state with a pill named 'start'."],
              "example": {"type": "state", "nodes": [{"id": "draft", "shape": "round"}, {"id": "sent", "shape": "round"}],
                          "edges": [{"from": "draft", "to": "sent", "label": "submit"}]}},
    "er": {"pattern": "data", "use": "Entities with their key columns and relations.",
           "fields": "nodes[{id,label,fields[{name,type,key: pk|fk}]}], edges[{from,to,label,cardinality}]",
           "rules": ["Only the columns that explain the relation.", "Cardinality at the target end (1, 0..1, 1..n, 0..n)."],
           "example": {"type": "er", "nodes": [{"id": "user", "fields": [{"name": "id", "key": "pk"}]},
                                               {"id": "order", "fields": [{"name": "id", "key": "pk"}, {"name": "user_id", "key": "fk"}]}],
                       "edges": [{"from": "user", "to": "order", "label": "places", "cardinality": "0..n"}]}},
    "swimlane": {"pattern": "responsibility", "use": "A process where each step belongs to a role; lanes are groups.",
                 "fields": "groups[{id,label}] (lanes, top to bottom), nodes[{id,label,group}], edges[{from,to,label}]",
                 "rules": ["Every node has a lane.", "Hand-offs between lanes are the interesting edges: label them."],
                 "example": {"type": "swimlane", "groups": [{"id": "c", "label": "Customer"}, {"id": "s", "label": "Shop"}],
                             "nodes": [{"id": "o", "label": "Order", "group": "c"}, {"id": "p", "label": "Pack", "group": "s"}],
                             "edges": [{"from": "o", "to": "p"}]}},
    "sequence": {"pattern": "interaction", "use": "Messages between participants over time (top to bottom).",
                 "fields": "participants[...] (optional order), messages[{from,to,label,reply}]",
                 "rules": ["Replies are dashed (reply: true).", "One message per line; keep labels short."],
                 "example": {"type": "sequence", "messages": [{"from": "Browser", "to": "API", "label": "POST /login"},
                                                               {"from": "API", "to": "Browser", "label": "200 + cookie", "reply": True}]}},
    "timeline": {"pattern": "chronology", "use": "Dated events on one axis, in order.",
                 "fields": "events[{when,label}]",
                 "rules": ["Keep 'when' short (2026, Q3, 12 Oct).", "Up to ~12 events reads well."],
                 "example": {"type": "timeline", "events": [{"when": "2024", "label": "Prototype"}, {"when": "2025", "label": "Launch"}]}},
    "gantt": {"pattern": "schedule", "use": "Tasks as bars over time, optionally grouped in lanes.",
              "fields": "tasks[{label,start,end,lane}] (numbers: day offsets), unit",
              "rules": ["start/end are numbers on one axis (days from the start).", "Lanes group tasks by team or phase."],
              "example": {"type": "gantt", "unit": "d", "tasks": [{"label": "Design", "start": 0, "end": 5, "lane": "UX"},
                                                                   {"label": "Build", "start": 4, "end": 14, "lane": "Dev"}]}},
}


def _words(text: str) -> str:
    return " " + re.sub(r"[^\wáéíóúñü.]+", " ", (text or "").lower()) + " "


def pick_type(intent: str) -> dict:
    """The pattern and type a request points at, with the runners-up; ties keep the catalogue order."""
    text = _words(intent)
    scores = []
    for pid, (question, types, words) in PATTERNS.items():
        # a phrase ("who does", "base de datos") is more specific than a single word, so it weighs double
        hit = sum((2 if " " in w else 1) for w in words if f" {w} " in text or (len(w) > 5 and w in text))
        hit += sum(2 for t in types if f" {t} " in text)
        scores.append((hit, pid))
    scores.sort(key=lambda s: -s[0])
    best = scores[0][1] if scores[0][0] > 0 else "process"
    question, types, _ = PATTERNS[best]
    return {"pattern": best, "question": question, "type": types[0], "alternatives": types[1:],
            "other_patterns": [p for s, p in scores[1:4] if s > 0], "matched": scores[0][0] > 0}


def type_card(kind: str) -> dict:
    if kind not in CARDS:
        raise LookupError(f"Unknown diagram type '{kind}'. Known: {', '.join(CARDS)}.")
    return {"type": kind, **CARDS[kind]}


def catalogue() -> dict:
    return {"patterns": {p: {"question": q, "types": t} for p, (q, t, _) in PATTERNS.items()},
            "types": {k: v["use"] for k, v in CARDS.items()}}
