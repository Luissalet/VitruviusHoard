import { partitionLegacyHistory } from "../src/canvas/canvasPanel.js";
import test from "node:test";
import assert from "node:assert/strict";
import { canvasContext, canvasHistoryEntries, isCanvasMessage, modeFromPage, modeMessages, previewPick, supportedModes } from "../src/canvas/canvasPanel.js";

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

test("a guarded click keeps its coordinates inside the preview and preserves Shift", () => {
  const frame = {
    clientLeft: 1, clientTop: 1, clientWidth: 398, clientHeight: 298, offsetWidth: 400, offsetHeight: 300,
    getBoundingClientRect: () => ({ left: 40, top: 60, width: 800, height: 600 }),
  };
  assert.deepEqual(previewPick(frame, { clientX: 80, clientY: 100, shiftKey: true }),
    { type: "inspect/pick", x: 19, y: 19, additive: true });
  assert.equal(previewPick(frame, { clientX: 40, clientY: 100 }), null, "iframe border");
  assert.equal(previewPick(frame, { clientX: 840, clientY: 100 }), null, "outside iframe");
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

test("history groups only earlier unattributed snapshots and preserves their order", () => {
  const current = { revision: "r5", action: "legacy" };
  const authoredSave = { revision: "r4", action: "legacy", author: { kind: "person" } };
  const edit = { revision: "r3", action: "edit", id: "edit-1" };
  const earlier = [{ revision: "r2", action: "legacy" }, { revision: "r1" }];
  const entries = [current, authoredSave, edit, ...earlier];
  assert.deepEqual(partitionLegacyHistory(entries, "r5"), {
    recordedEntries: [current, authoredSave, edit],
    previous: earlier,
  });
  assert.deepEqual(partitionLegacyHistory(entries, "missing"), { recordedEntries: entries, previous: [] });
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

test("expired elements are never counted as selected and carry no source position", () => {
  const project = { id: "p1", name: "Board" };
  const heading = { selector: "main > h2", tag: "h2", text: "Current records", vsrc: "pages/index.html:1:167" };
  const gone = canvasContext({ project, revision: "newrev", mode: "select", selection: [{ ...heading, expired: true }] });
  assert.equal(gone.summary, 'Board @newrev · mode select · selected 0 · expired 1, not in this revision: h2 "Current records"');
  assert.doesNotMatch(gone.summary, /selected 1|pages\/index\.html/);
  const mixed = canvasContext({ project, revision: "newrev", selection: [{ tag: "p", text: "Kept", vsrc: "pages/index.html:4:3" }, { ...heading, expired: true }] });
  assert.equal(mixed.summary, 'Board @newrev · selected 1: p "Kept" pages/index.html:4:3 · expired 1, not in this revision: h2 "Current records"');
  const restored = canvasContext({ project, revision: "newrev", selection: [heading] });
  assert.equal(restored.summary, 'Board @newrev · selected 1: h2 "Current records" pages/index.html:1:167');
});
test("history gives a rollback its own step number and keeps the restored revision", () => {
  const revisions = ["first", "next", "edited"];
  const history = [
    { id: "edit2", revision: "next", action: "edit" },
    { id: "edit3", revision: "edited", action: "edit" },
    { id: "undo", revision: "next", action: "undo" },
  ];
  assert.deepEqual(canvasHistoryEntries({ revisions, history }).map(({ step, revision }) => [step, revision]),
    [[4, "next"], [3, "edited"], [2, "next"], [1, "first"]]);
  assert.deepEqual(canvasHistoryEntries({ revisions }).map(({ step }) => step), [3, 2, 1]);
  assert.deepEqual(canvasHistoryEntries({ revisions, history: null }), canvasHistoryEntries({ revisions }));
});

test("restoring the prior snapshot marks the reverted edit and offers one redo", () => {
  const revision = ["first", "edited"];
  const create = { id: "create", revision: "first", action: "create" };
  const edit = { id: "edit", revision: "edited", previous_revision: "first", action: "edit" };
  const undo = { id: "undo", revision: "first", previous_revision: "edited", action: "undo" };
  const history = [create, edit, undo];
  const [latest, previous] = canvasHistoryEntries({ revisions: revision, history });
  assert.equal(previous.undone, true);
  assert.equal(latest.redoRevision, "edited");

  const redo = { id: "redo", revision: "edited", previous_revision: "first", action: "undo" };
  const restored = canvasHistoryEntries({ revisions: revision, history: [...history, redo] });
  assert.equal(restored[0].action, "redo");
  assert.equal(restored[0].redoRevision, undefined);
  assert.equal(restored.find((step) => step.id === "edit").undone, undefined);

  const revertedAgain = { ...undo, id: "undo-again" };
  const repeated = canvasHistoryEntries({ revisions: revision, history: [...history, redo, revertedAgain] });
  assert.equal(repeated[0].action, "undo");
  assert.equal(repeated[0].redoRevision, "edited");
});

test("undoing one step leaves later edits active and a new edit closes the immediate redo", () => {
  const revisions = ["first", "after-text", "after-style", "style-only", "new-text"];
  const history = [
    { id: "text", revision: "after-text", previous_revision: "first", action: "edit" },
    { id: "style", revision: "after-style", previous_revision: "after-text", action: "edit" },
    { id: "undo", revision: "style-only", previous_revision: "after-style", action: "undo-change", reverted_change: "text" },
  ];
  const rows = canvasHistoryEntries({ revisions, history });
  assert.equal(rows[0].redoRevision, "after-style");
  assert.equal(rows.find((step) => step.id === "text").undone, true);
  assert.equal(rows.find((step) => step.id === "style").undone, undefined);

  const redo = { id: "redo", revision: "after-style", previous_revision: "style-only", action: "undo" };
  const redone = canvasHistoryEntries({ revisions, history: [...history, redo] });
  assert.equal(redone[0].action, "redo");
  assert.equal(redone.find((step) => step.id === "text").undone, undefined);

  const newEdit = { id: "new", revision: "new-text", previous_revision: "style-only", action: "edit" };
  const newer = canvasHistoryEntries({ revisions, history: [...history, newEdit] });
  assert.equal(newer[0].redoRevision, undefined);
  assert.equal(newer.find((step) => step.id === "text").undone, true);
});
