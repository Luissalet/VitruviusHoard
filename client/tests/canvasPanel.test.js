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

test("the Dock context fits what the host keeps: focus and a short summary with selection and comments", () => {
  assert.deepEqual(canvasContext({}), { view: "canvas" });
  const context = canvasContext({
    project: { id: "p1", name: "Board" }, revision: "r2", mode: "select",
    selection: [{ selector: "main > h1", tag: "h1", vsrc: "pages/index.html:3:1", text: "Current records", same_vsrc_count: 3, html: "<h1>…</h1>" }],
    comments: [{ id: "c1", n: 1, status: "pending", note: "Bigger" }, { id: "c2", n: 2, status: "resolved", note: "Done" }],
  });
  assert.deepEqual(context.focus, { kind: "app_project", id: "p1", label: "Board" });
  assert.equal(context.summary, 'Board @r2 · mode select · selected 1: h1 "Current records" pages/index.html:3:1 x3 · open comments 1: #1 Bigger');
});

test("open comments keep their place when a long selection fills the summary", () => {
  const selection = Array.from({ length: 30 }, (_, n) => ({ tag: "p", text: "y".repeat(60), vsrc: `pages/records/index.html:${n + 10}:2` }));
  const comments = [{ n: 1, status: "pending", note: "Make the heading larger" }];
  const context = canvasContext({ project: { id: "p1", name: "Board" }, revision: "abcdef1234567890", mode: "select", selection, comments });
  assert.ok(context.summary.length <= 400, context.summary.length);
  assert.match(context.summary, /open comments 1: #1 Make the heading larger$/);
  assert.match(context.summary, /selected 30: p "y{30}" pages\/records\/index\.html:10:2; .*\+\d+ more/);
  const many = canvasContext({ project: { id: "p1", name: "Board" }, selection, comments: Array.from({ length: 9 }, (_, n) => ({ n, status: "pending", note: "z".repeat(90) })) });
  assert.ok(many.summary.length <= 400);
  assert.match(many.summary, /open comments 9: /);
});
