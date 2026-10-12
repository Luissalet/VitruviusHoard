import test from "node:test";
import assert from "node:assert/strict";
import {
  buildContext, changedFields, clipText, collectEditor, formSnapshot, isNoObjectId, resolveObjects,
} from "./src/copilot-core.js";

const rows = {
  render: { rnd_1: { id: "rnd_1", title: "Landing", url: "http://x.test/" }, rnd_2: { id: "rnd_2", url: "http://x.test/pricing" } },
  tokens: { ds_1: { id: "ds_1", name: "Blueprint", tokens: { color: {} } } },
  diagram: { dg_1: { id: "dg_1", type: "flowchart", title: "Order flow" } },
  reference: { ref_1: { id: "ref_1", url: "http://ref.test/", title: "" } },
  motion: { a1b2: { id: "a1b2", revision: 3, composition: { title: "Launch", scenes: [] } } },
};
const lookup = (table) => async (id) => {
  if (table[id]) return table[id];
  throw Object.assign(new Error(`Unknown '${id}'`), { status: 404 });
};
const makeApi = (calls = []) => {
  const wrap = (name, table) => async (id) => { calls.push([name, id]); return lookup(table)(id); };
  return {
    render: wrap("render", rows.render), tokensGet: wrap("tokensGet", rows.tokens), diagram: wrap("diagram", rows.diagram),
    reference: wrap("reference", rows.reference), motion: wrap("motion", rows.motion),
  };
};
const noForms = () => {};

test("isNoObjectId treats new/blank placeholders as no object", () => {
  for (const id of [undefined, null, "", " ", "new", "NEW", "undefined", "null"]) assert.equal(isNoObjectId(id), true);
  assert.equal(isNoObjectId("rnd_1"), false);
});

test("changedFields reports only differing keys, deeply, including cleared values", () => {
  assert.deepEqual(changedFields({ a: 1, b: [1, 2], c: "x" }, { a: 1, b: [1, 3], c: "" }), { b: [1, 3], c: "" });
  assert.deepEqual(changedFields(undefined, { a: 1 }), { a: 1 });
  assert.deepEqual(changedFields({ a: 1 }, { a: 1 }), {});
});

test("formSnapshot: edit forms carry object_id, create forms do not, long text is clipped", () => {
  const edit = formSnapshot("motion-form", { objectId: "a1b2", initial: { title: "A", fps: 24 }, current: { title: "B", fps: 24 } });
  assert.deepEqual(edit, { kind: "motion-form", object_id: "a1b2", dirty: true, fields: { title: "B" } });
  const draft = formSnapshot("design-system-draft", { initial: { name: "", mode: "both" }, current: { name: "Ink", mode: "both" } });
  assert.deepEqual(draft, { kind: "design-system-draft", dirty: true, fields: { name: "Ink" } });
  assert.equal("object_id" in formSnapshot("x-draft", { objectId: "new", initial: {}, current: {} }), false);
  assert.equal(formSnapshot("x", { objectId: "p", initial: { a: 1 }, current: { a: 1 } }).dirty, false);
  const big = formSnapshot("diagram-draft", { initial: { source: "" }, current: { source: "x".repeat(20000) } });
  assert.equal(big.dirty, true);
  assert.ok(big.fields.source.length < 8100 && big.fields.source.includes("more characters"));
  assert.equal(clipText("short"), "short");
  assert.equal(clipText(42), 42);
});

test("collectEditor prefers the last dirty answer and gathers object refs", () => {
  const { editor, refs } = collectEditor(({ provide, provideObjects }) => {
    provide({ kind: "design-system-draft", dirty: false, fields: {} });
    provide({ kind: "diagram-draft", dirty: true, fields: { source: "x" } });
    provide({ kind: "other", dirty: false, fields: {} });
    provideObjects([{ kind: "diagram", id: "dg_1" }]);
    provideObjects("nope");
    provide(null);
  });
  assert.equal(editor.kind, "diagram-draft");
  assert.deepEqual(refs, [{ kind: "diagram", id: "dg_1" }]);
  assert.equal(collectEditor(() => { throw new Error("boom"); }).editor, undefined);
});

test("resolveObjects reads each kind through its real client call and builds titles", async () => {
  const calls = [];
  const out = await resolveObjects([
    { kind: "render", id: "rnd_1" }, { kind: "render", id: "rnd_2" }, { kind: "design-system", id: "ds_1" },
    { kind: "diagram", id: "dg_1" }, { kind: "reference", id: "ref_1" }, { kind: "motion", id: "a1b2" },
  ], makeApi(calls));
  assert.deepEqual(out.map((o) => [o.kind, o.object_id, o.title]), [
    ["render", "rnd_1", "Landing"], ["render", "rnd_2", "http://x.test/pricing"], ["design-system", "ds_1", "Blueprint"],
    ["diagram", "dg_1", "Order flow"], ["reference", "ref_1", "http://ref.test/"], ["motion", "a1b2", "Launch"],
  ]);
  assert.deepEqual(out.map((o) => o.url), ["#/critique", "#/critique", "#/tokens", "#/diagrams", "#/gallery", "#/motion"]);
  assert.deepEqual(calls.map((c) => c[0]), ["render", "render", "tokensGet", "diagram", "reference", "motion"]);
});

test("new, unknown kinds, duplicates and ids that do not resolve are dropped without throwing", async () => {
  const calls = [];
  const api = makeApi(calls);
  const out = await resolveObjects([
    { kind: "design-system", id: "new" }, { kind: "design-system", id: "gone" }, { kind: "ghost", id: "x" },
    null, { kind: "render", id: "rnd_1" }, { kind: "render", id: "rnd_1" },
  ], api);
  assert.deepEqual(out.map((o) => o.object_id), ["rnd_1"]);
  assert.deepEqual(calls, [["tokensGet", "gone"], ["render", "rnd_1"]]);
  // a backend that answers with another object, nothing, or a string is not an object either
  const odd = { render: async () => ({ id: "other" }), tokensGet: async () => null, diagram: async () => "text" };
  assert.deepEqual(await resolveObjects([{ kind: "render", id: "r" }, { kind: "design-system", id: "d" }, { kind: "diagram", id: "g" }], odd), []);
  assert.deepEqual(await resolveObjects(undefined, api), []);
});

test("buildContext: views name objects, the dirty form is the editor, no project is invented", async () => {
  const ctx = await buildContext({ api: makeApi(), ask: ({ provide, provideObjects }) => {
    provideObjects([{ kind: "design-system", id: "ds_1" }]);
    provide({ kind: "design-system-draft", dirty: true, fields: { name: "Ink" } });
  } });
  assert.equal("project" in ctx, false);
  assert.deepEqual(ctx.active_objects, [{ kind: "design-system", object_id: "ds_1", title: "Blueprint", url: "#/tokens" }]);
  assert.deepEqual(ctx.editor, { kind: "design-system-draft", dirty: true, fields: { name: "Ink" } });
});

test("create forms are reported with no object and no API call", async () => {
  const calls = [];
  const ctx = await buildContext({ api: makeApi(calls), ask: ({ provide }) => {
    provide(formSnapshot("motion-draft", { initial: { title: "Nuevo proyecto" }, current: { title: "Teaser" } }));
  } });
  assert.deepEqual(ctx, { active_objects: [], editor: { kind: "motion-draft", dirty: true, fields: { title: "Teaser" } } });
  assert.deepEqual(calls, []);
});

test("a failing form or a rejecting API leaves context resolved", async () => {
  const down = { render: () => Promise.reject(new Error("down")) };
  const ctx = await buildContext({ api: down, ask: ({ provideObjects }) => { provideObjects([{ kind: "render", id: "rnd_1" }]); throw new Error("form"); } });
  assert.deepEqual(ctx, { active_objects: [] });
  assert.deepEqual(await buildContext({ api: {}, ask: noForms }), { active_objects: [] });
  assert.deepEqual(await buildContext({ api: {}, ask: undefined }), { active_objects: [] });
});

test("window.hoardCopilot: context() never rejects and onTurnEnd fires the refresh event", async () => {
  const target = new EventTarget();
  const hits = [];
  globalThis.window = Object.assign(target, { location: { hash: "#/tokens", origin: "http://x.test" } });
  globalThis.fetch = async () => { throw new Error("offline"); };
  await import("./src/hoard-copilot.js");
  const hc = globalThis.window.hoardCopilot;
  assert.equal(typeof hc.context, "function");
  target.addEventListener("hoard:copilot-context-request", (e) => {
    e.detail.provide({ kind: "design-system-draft", dirty: true, fields: { name: "N" } });
    e.detail.provideObjects([{ kind: "design-system", id: "ds_1" }]);   // backend unreachable: dropped, context still resolves
  });
  assert.deepEqual(await hc.context(), { active_objects: [], editor: { kind: "design-system-draft", dirty: true, fields: { name: "N" } } });
  target.addEventListener("vitruvius:copilot-updated", () => hits.push(1));
  hc.onTurnEnd();
  assert.equal(hits.length, 1);
});
