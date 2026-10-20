import test from "node:test";
import assert from "node:assert/strict";
import { clone, mergeDraft } from "./model.js";

const source = () => ({ diagram: { title: "Original", nodes: [{ id: "a", label: "A" }, { id: "b", label: "B" }] }, view: { nodes: {}, edges: {} } });

test("initial geometry merges independent fields without relaxing identity conflicts", () => {
  const base = source(), wanted = clone(base), current = clone(base);
  wanted.view.nodes.a = { width: 240 }; current.view.nodes.a = { x: 300 };
  assert.deepEqual(mergeDraft(base, wanted, current).view.nodes.a, { x: 300, width: 240 });
  current.view.nodes.a = { width: 400 };
  assert.throws(() => mergeDraft(base, wanted, current), /width/);
  wanted.diagram.nodes.push({ id: "new", label: "Local" });
  current.diagram.nodes.push({ id: "new", details: "Remote" });
  assert.throws(() => mergeDraft(base.diagram, wanted.diagram, current.diagram), /new/);
});

test("rebased undo and redo preserve an independent remote label", () => {
  const base = source(), local = clone(base), fresh = clone(base);
  local.diagram.title = "Local"; fresh.diagram.nodes[1].label = "Remote B";
  const draft = mergeDraft(base, local, fresh);
  const undo = mergeDraft(base, base, fresh);
  assert.equal(undo.diagram.title, "Original");
  assert.equal(undo.diagram.nodes[1].label, "Remote B");
  const redo = clone(draft);
  assert.equal(redo.diagram.title, "Local");
  assert.equal(redo.diagram.nodes[1].label, "Remote B");
});
