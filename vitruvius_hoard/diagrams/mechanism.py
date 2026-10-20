"""Authored part explanations and poses; no simulation or destructive geometry edits."""
from copy import deepcopy
from pydantic import BaseModel, ConfigDict, Field

from .spec import Diagram, RECT_KINDS


class Part(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=60)
    description: str = ""


class Pose(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    dx: float = 0
    dy: float = 0
    dz: float = 0


class State(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=60)
    title: str = Field(min_length=1)
    description: str = ""
    hidden: list[str] = Field(default_factory=list)
    poses: dict[str, Pose] = Field(default_factory=dict)
    focus_piece: str | None = None


class Mechanism(BaseModel):
    model_config = ConfigDict(extra="forbid")
    parts: list[Part] = Field(default_factory=list)
    states: list[State] = Field(default_factory=list)


def diagram_for(content, state_id=None):
    diagram = deepcopy(content["diagram"])
    if not state_id:
        return diagram
    if diagram["type"] != "isometric":
        raise ValueError("States apply to isometric diagrams.")
    state = next((s for s in content.get("mechanism", {}).get("states", []) if s["id"] == state_id), None)
    if state is None:
        raise ValueError("Unknown mechanism state.")
    for piece in diagram["pieces"]:
        pose = state.get("poses", {}).get(piece["id"], {})
        for key, axis in (("dx", "x"), ("dy", "y")):
            coordinate = axis if piece["kind"] in RECT_KINDS else "c" + axis
            piece["plan"][coordinate] += pose.get(key, 0)
        piece["z"] += pose.get("dz", 0)
        if state.get("focus_piece"):
            piece["lit"] = piece["id"] == state["focus_piece"]
    diagram["pieces"] = [p for p in diagram["pieces"] if p["id"] not in state.get("hidden", [])]
    # Enforce the same finite geometry and shape rules as the original renderer.
    return Diagram.model_validate(diagram).model_dump(by_alias=True)


def validate(content):
    if content["diagram"]["type"] != "isometric":
        if content.get("mechanism"):
            raise ValueError("Mechanism explanations and states require an isometric diagram.")
        return
    mechanism = Mechanism.model_validate(content.get("mechanism", {}))
    ids = {p["id"] for p in content["diagram"]["pieces"]}
    for collection in (mechanism.parts, mechanism.states):
        if len({item.id for item in collection}) != len(collection):
            raise ValueError("Mechanism identities must be unique within each collection.")
    if any(part.id not in ids for part in mechanism.parts):
        raise ValueError("An explanation references an unknown piece.")
    content["mechanism"] = mechanism.model_dump()
    for state in mechanism.states:
        referenced = set(state.hidden) | state.poses.keys() | ({state.focus_piece} if state.focus_piece else set())
        if referenced - ids:
            raise ValueError("A state references an unknown piece.")
        if set(state.hidden) >= ids:
            raise ValueError("A state must keep at least one visible piece.")
        if state.focus_piece in state.hidden:
            raise ValueError("The highlighted piece must be visible.")
        diagram_for(content, state.id)


def selected(row, state_id=None):
    if not state_id:
        return row
    from .documents import drawing
    return {**row, "rendering": drawing(row["content"], state_id)}
