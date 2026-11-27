import test from "node:test";
import assert from "node:assert/strict";
import { conversationEntry, groupCanvasActivity, recordCanvasActivity } from "../src/canvas/canvasConversation.js";

const action = (id, kind, state = "active") => ({ id, kind, state, projectId: "project-one" });
const say = (id, role, text) => conversationEntry({ id, role, text }, "project-one");

test("the request retains punctuation, spacing and line breaks", () => {
  const text = "  Monta la portada.\nPrograma y horarios.";
  assert.equal(say("request", "user", text).text, text);
  assert.equal(say("blank", "user", " \n "), null);
  assert.equal(say("other", "reasoning", "Omit this internal event."), null);
  assert.equal(conversationEntry({ id: "request", role: "user", text }, ""), null);
});

test("completing a click keeps the four interactions between request and narration", () => {
  const request = say("request", "user", "Monta la portada con el programa.");
  const first = say("first", "assistant", "Monto la portada como un libro.");
  const second = say("second", "assistant", "Cambio la tipografía de titulares.");
  const actions = [action("1", "click"), action("2", "click"), action("3", "click"), action("4", "scroll")];
  const entries = [request, ...actions, first, second].reduce(recordCanvasActivity, []);
  const groups = groupCanvasActivity(recordCanvasActivity(entries, action("2", "click", "done")));
  assert.deepEqual(groups.map((entry) => entry.id), ["request", "interactions:1", "first", "second"]);
  assert.deepEqual(groups[1].steps.map((step) => step.id), ["1", "2", "3", "4"]);
  assert.equal(groups[1].steps[1].state, "done");
});

test("narration separates interaction groups and text updates keep the original slot", () => {
  const start = say("line", "assistant", "Organizo");
  const entries = [action("1", "navigate"), start, action("2", "scroll"), action("3", "edit")];
  const updated = say("line", "assistant", "Organizo el programa.");
  const groups = groupCanvasActivity(recordCanvasActivity(entries, updated));
  assert.deepEqual(groups.map((item) => item.kind), ["interactions", "speech", "interactions", "edit"]);
  assert.equal(groups[1].text, updated.text);
});

test("a long run retains the latest request and bounds the activity list", () => {
  const request = say("request", "user", "Conserva este encargo.");
  const actions = Array.from({ length: 150 }, (_, i) => action("action-" + i, "click"));
  const entries = actions.reduce(recordCanvasActivity, [request]);
  assert.equal(entries.length, 120);
  assert.equal(entries[0], request);
  assert.equal(entries.at(-1), actions.at(-1));
});
