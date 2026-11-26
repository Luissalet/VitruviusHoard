import test from "node:test";
import assert from "node:assert/strict";
import { canvasContext, isCanvasMessage, modeFromPage, modeMessages, supportedModes } from "../src/canvas/canvasPanel.js";

test("the toolbar offers only the modes the preview supports", () => {
  assert.deepEqual(supportedModes(undefined), ["navigate"]);
  assert.deepEqual(supportedModes({ selection: [] }), ["navigate", "select"]);
  assert.deepEqual(supportedModes({ selection: [], comment_mode: false }), ["navigate", "select", "comment"]);
  assert.deepEqual(supportedModes({ selection: [], comment_mode: false, capabilities: ["handles"] }), ["navigate", "select", "comment", "handles"]);
});

test("mode changes speak the inspector protocol and navigate leaves the current mode", () => {
  assert.deepEqual(modeMessages("select", "navigate"), [{ type: "inspect/mode", on: true }]);
  assert.deepEqual(modeMessages("comment", "select"), [{ type: "inspect/mode", on: true, kind: "comment" }]);
  assert.deepEqual(modeMessages("navigate", "select"), [{ type: "inspect/mode", on: false }]);
  assert.deepEqual(modeMessages("navigate", "comment"), [{ type: "inspect/mode", on: false, kind: "comment" }]);
  assert.deepEqual(modeMessages("navigate", "navigate"), []);
  assert.equal(modeFromPage({ mode: true }), "select");
  assert.equal(modeFromPage({ mode: false, comment_mode: true }), "comment");
  assert.equal(modeFromPage({}), "navigate");
});

test("only the visible preview frame, from its own origin, is heard", () => {
  const frame = {};
  const ok = { source: frame, origin: "http://127.0.0.1:5001", data: { hoardDock: 1, type: "dock/select", selection: [] } };
  assert.equal(isCanvasMessage(ok, frame, "http://127.0.0.1:5001"), true);
  assert.equal(isCanvasMessage({ ...ok, source: {} }, frame, "http://127.0.0.1:5001"), false);
  assert.equal(isCanvasMessage({ ...ok, origin: "http://127.0.0.1:5002" }, frame, "http://127.0.0.1:5001"), false);
  assert.equal(isCanvasMessage({ ...ok, data: { ...ok.data, type: "dock/call" } }, frame, "http://127.0.0.1:5001"), false);
  assert.equal(isCanvasMessage({ ...ok, data: { ...ok.data, hoardDock: 2 } }, frame, "http://127.0.0.1:5001"), false);
});

test("the Dock context carries the project, revision, selection and open comments in short form", () => {
  assert.deepEqual(canvasContext({}), { view: "canvas" });
  const context = canvasContext({
    project: { id: "p1", name: "Board" }, revision: "r2", mode: "select",
    selection: [{ selector: "main > h1", tag: "h1", vsrc: "pages/index.html:3:1", text: "x".repeat(120), same_vsrc_count: 3, html: "<h1>…</h1>" }],
    comments: [{ id: "c1", n: 1, status: "pending", note: "Bigger", element: { vsrc: "pages/index.html:5:3" } }, { id: "c2", n: 2, status: "resolved", note: "Done" }],
  });
  assert.equal(context.view, "canvas");
  assert.equal(context.focus.id, "p1");
  assert.equal(context.focus.revision, "r2");
  assert.deepEqual(context.focus.selection, [{ selector: "main > h1", tag: "h1", source: "pages/index.html:3:1", text: "x".repeat(80), affects: 3 }]);
  assert.deepEqual(context.focus.comments, [{ id: "c1", n: 1, status: "pending", note: "Bigger", source: "pages/index.html:5:3" }]);
  assert.equal(context.summary, "Board · 1 selected · 1 open comments");
});
