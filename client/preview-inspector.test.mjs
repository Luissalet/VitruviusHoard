import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

// The inspector is a plain script for the preview page: load its pure core under a flag, with a tiny fake DOM.
const source = fs.readFileSync(new URL("../vitruvius_hoard/preview_scripts/preview-inspector.js", import.meta.url), "utf8");
const context = { __VITRUVIUS_INSPECTOR_TEST__: true };
context.globalThis = context;
vm.runInNewContext(source, context);
const { selectorFor, describeElement, resolveElement, escapeCss } = context.VitruviusInspectorCore;

function node(tagName, attrs = {}, children = [], text = "") {
  const element = { tagName: tagName.toUpperCase(), attrs, children, parentElement: null, textContent: text, getAttribute: (name) => (name in attrs ? attrs[name] : null) };
  element.closest = (selector) => { for (let n = element; n; n = n.parentElement) if (selector === "[data-vgen]" ? n.attrs["data-vgen"] !== undefined : false) return n; return null; };
  children.forEach((child) => { child.parentElement = element; });
  return element;
}
const walk = (root) => [root, ...root.children.flatMap(walk)];
const same = (a, b) => a.tagName === b.tagName;
function seg(element, part) {
  if (part.startsWith("#")) return element.attrs.id === part.slice(1);
  const vid = part.match(/^\[data-vid="(.*)"\]$/); if (vid) return element.attrs["data-vid"] === vid[1];
  const vsrc = part.match(/^\[data-vsrc="(.*)"\]$/); if (vsrc) return element.attrs["data-vsrc"] === vsrc[1];
  const m = part.match(/^([a-z0-9]+)(?::nth-of-type\((\d+)\))?$/);
  if (!m || element.tagName.toLowerCase() !== m[1]) return false;
  if (!m[2]) return true;
  return element.parentElement.children.filter((s) => same(s, element)).indexOf(element) + 1 === Number(m[2]);
}
// Evaluates the only selector grammar the inspector emits: `a > b > c`, where the first part may be an anchor.
function counter(root) {
  return (selector) => walk(root).filter((candidate) => {
    const parts = selector.split(" > ");
    let current = candidate;
    for (let i = parts.length - 1; i >= 0; i--) { if (!current || !seg(current, parts[i])) return false; current = current.parentElement; }
    return true;
  }).length;
}

function page() {
  const items = [node("li", {}, [], "One"), node("li", { "data-vsrc": "pages/index.html:7:5" }, [], "Two"), node("li", {}, [], "Three")];
  const list = node("ul", { class: "menu" }, items);
  const heading = node("h1", { id: "top", "data-vsrc": "pages/index.html:1:1" }, [], "Title");
  const generated = node("div", { "data-vgen": "table", "data-vsrc": "pages/index.html:9:1" }, [node("table", {}, [node("tr", {}, [node("td", {}, [], "cell")])])]);
  const body = node("body", {}, [heading, list, generated, node("p", { "data-vid": "intro" }, [], "Hi")]);
  const html = node("html", {}, [node("head"), body]);
  return { html, body, heading, list, items, generated };
}

test("selector prefers data-vid, then id, then the shortest unique path", () => {
  const { html, heading, items, body } = page();
  const count = counter(html);
  assert.equal(selectorFor(body.children[3], count), '[data-vid="intro"]');
  assert.equal(selectorFor(heading, count), "#top");
  assert.equal(selectorFor(items[1], count), '[data-vsrc="pages/index.html:7:5"]'); // a unique source position is an anchor
  assert.equal(selectorFor(items[2], count), "li:nth-of-type(3)");
  for (const element of walk(body)) assert.equal(count(selectorFor(element, count)), 1, "unique for " + element.tagName);
});

test("selector falls back to a path anchored at body when nothing shorter is unique", () => {
  const { html, generated } = page();
  const td = generated.children[0].children[0].children[0];
  const selector = selectorFor(td, counter(html));
  assert.equal(counter(html)(selector), 1);
  assert.ok(selector.split(" > ").length <= 5);
});

test("description carries source position, generated marker, trimmed text, page box and styles", () => {
  const { html, items, generated } = page();
  const count = counter(html);
  const env = { count, rect: () => ({ left: 10, top: 20, width: 100.4, height: 30 }), style: () => ({ color: "red", fontSize: "16px", gap: "" }), scroll: { x: 0, y: 300 } };
  items[1].innerText = "  Two \n  words ";
  const picked = JSON.parse(JSON.stringify(describeElement(items[1], env))); // plain objects: the script ran in another realm
  assert.equal(picked.vsrc, "pages/index.html:7:5");
  assert.equal(picked.vgen, null);
  assert.equal(picked.text, "Two words");
  assert.deepEqual(picked.box, { x: 10, y: 320, w: 100, h: 30 });
  assert.deepEqual(picked.computed, { color: "red", fontSize: "16px" });
  assert.equal(picked.same_vsrc_count, 1);
  const inside = describeElement(generated.children[0].children[0].children[0], env);
  assert.equal(inside.vgen, "table");
  assert.equal(inside.vsrc, "pages/index.html:9:1");
  items[0].textContent = "x".repeat(500);
  assert.equal(describeElement(items[0], env).text.length, 200);
  assert.equal(describeElement(items[0], env).vsrc, null);
});

test("escapeCss protects ids that are not plain identifiers", () => {
  assert.equal(escapeCss("a b"), "a\\ b");
  assert.equal(escapeCss("1x"), "\\31 x");
});

test("the served description carries the element HTML and says whether the source position is its own", () => {
  const { html, items, generated } = page();
  const env = { count: counter(html), rect: () => ({ left: 0, top: 0, width: 1, height: 1 }), style: () => ({}), scroll: { x: 0, y: 0 } };
  items[1].outerHTML = '<li data-vsrc="pages/index.html:7:5">Two</li>'.padEnd(3000, " ");
  const own = JSON.parse(JSON.stringify(describeElement(items[1], env)));
  assert.equal(own.own_vsrc, true);
  assert.equal(own.html.length, 1200);
  assert.equal(JSON.parse(JSON.stringify(describeElement(generated.children[0], env))).own_vsrc, false);
});

// A page that re-renders its list in another order must not hand the selection to a neighbour.
function listPage(order) {
  const rows = { a: ["pages/index.html:2:5", "First"], b: ["pages/index.html:3:5", "Second"], c: ["pages/index.html:4:5", "Second"] };
  const items = order.map((key) => node("li", { "data-vsrc": rows[key][0] }, [], rows[key][1]));
  const body = node("body", {}, [node("ul", {}, items)]);
  const html = node("html", {}, [node("head"), body]);
  return { html, items, all: (selector) => walk(html).filter((candidate) => matches(candidate, selector)) };
}
const matches = (element, selector) => { const parts = selector.split(" > "); let current = element; for (let i = parts.length - 1; i >= 0; i--) { if (!current || !seg(current, parts[i])) return false; current = current.parentElement; } return true; };

test("a unique source position follows its element through a reorder; a lookalike never takes its place", () => {
  const identity = { tag: "li", text: "First", vsrc: "pages/index.html:2:5", own_vsrc: true, selector: "li:nth-of-type(1)" };
  const after = listPage(["b", "a"]); // same elements, reversed
  const found = resolveElement(identity, after.all);
  assert.equal(found.textContent, "First");
  assert.equal(found, after.items[1]);
});

test("without a source position the tag and text must still match, and ambiguity drops the selection", () => {
  const page2 = listPage(["a", "b", "c"]);
  const positional = { tag: "li", text: "First", selector: "li:nth-of-type(1)", own_vsrc: false };
  assert.equal(resolveElement(positional, page2.all).textContent, "First");
  const reordered = listPage(["b", "a", "c"]);
  assert.equal(resolveElement(positional, reordered.all), null, "the first li is now another element");
  const repeated = { tag: "li", text: "Second", vsrc: "pages/index.html:3:5", own_vsrc: true, selector: "li:nth-of-type(2)" };
  assert.equal(resolveElement(repeated, listPage(["a", "b", "c"]).all).textContent, "Second");
  const twins = { tag: "li", text: "Second", selector: "li", own_vsrc: false };
  assert.equal(resolveElement(twins, listPage(["a", "b", "c"]).all), null, "two lookalikes are ambiguous");
  assert.equal(resolveElement(null, page2.all), null);
});
