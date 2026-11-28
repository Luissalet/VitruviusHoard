import assert from "node:assert/strict";
import { afterEach, beforeEach, test } from "node:test";
import { recentProjectId, rememberProject } from "../src/canvas/recentProject.js";

const oldStorage = Object.getOwnPropertyDescriptor(globalThis, "localStorage");
const active = [{ id: "first" }, { id: "second" }];

beforeEach(() => {
  const items = new Map();
  Object.defineProperty(globalThis, "localStorage", {
    configurable: true,
    value: {
      getItem: (key) => items.get(key) ?? null,
      setItem: (key, value) => items.set(key, value),
      removeItem: (key) => items.delete(key),
    },
  });
});

afterEach(() => {
  if (oldStorage) Object.defineProperty(globalThis, "localStorage", oldStorage);
  else delete globalThis.localStorage;
});

test("resumes the latest remembered project when it is active", () => {
  assert.equal(recentProjectId(active), null);
  rememberProject("first");
  assert.equal(recentProjectId(active), "first");
  rememberProject("second");
  assert.equal(recentProjectId(active), "second");
});

test("only an active project can be resumed and the picker can be cleared", () => {
  rememberProject("second");
  assert.equal(recentProjectId([{ id: "first" }]), null);
  rememberProject(null);
  assert.equal(recentProjectId(active), null);
});

test("opening and clearing the picker tolerate unavailable storage", () => {
  Object.defineProperty(globalThis, "localStorage", {
    configurable: true,
    get: () => { throw new Error("Storage is unavailable"); },
  });
  assert.doesNotThrow(() => rememberProject("first"));
  assert.doesNotThrow(() => rememberProject(null));
  assert.equal(recentProjectId(active), null);
});
