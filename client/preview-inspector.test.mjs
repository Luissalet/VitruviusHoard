import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import { chipText } from "./src/preview-selection.js";

// The inspector is a plain script for the preview page: load its pure core under a flag, with a tiny fake DOM.
const source = fs.readFileSync(new URL("../vitruvius_hoard/preview_scripts/preview-inspector.js", import.meta.url), "utf8");
const context = { __VITRUVIUS_INSPECTOR_TEST__: true };
context.globalThis = context;
vm.runInNewContext(source, context);
const { selectorFor, describeElement, reconcile, anchorOf, gate, escapeCss, formatHandleValue, formatOutlineLabel, outlineLabelPosition } = context.VitruviusInspectorCore;

test("handle feedback shows the nearest whole pixel", () => {
  assert.equal(formatHandleValue(390.4821), "390 px");
  assert.equal(formatHandleValue(390.6821), "391 px");
  assert.equal(formatHandleValue(-4.6821), "-5 px");
});

test("selection labels avoid the title above and fit below a full-width element", () => {
  const viewport = {width: 480, height: 360};
  const rect = {left: 0, right: 480, top: 100, bottom: 134};
  const headline = {left: 0, right: 350, top: 74, bottom: 99};
  const label = {width: 180, height: 20};
  assert.deepEqual({...outlineLabelPosition(rect, label, viewport, [headline])}, {x: 4, y: 137});
});

test("a label at the top can move sideways when a handle blocks the space below", () => {
  const viewport = {width: 480, height: 360};
  const rect = {left: 4, right: 79, top: 4, bottom: 24};
  const control = {...rect};
  const handle = {left: 10, right: 32, top: 20, bottom: 42};
  const label = {width: 120, height: 20};
  assert.deepEqual({...outlineLabelPosition(rect, label, viewport, [control, handle])}, {x: 82, y: 4});
});

test("a displaced label stays close to the outline and off visible content", () => {
  const viewport = {width: 320, height: 340};
  const rect = {left: 0, right: 320, top: 110, bottom: 135};
  const label = {width: 160, height: 20};
  const blocks = [
    {left: 0, right: 320, top: 85, bottom: 159},
    {left: 0, right: 320, top: 0, bottom: 32},
  ];
  assert.deepEqual({...outlineLabelPosition(rect, label, viewport, blocks)}, {x: 4, y: 162});
  assert.equal(outlineLabelPosition(rect, label, viewport, [{left: 0, right: 320, top: 0, bottom: 340}]), null);
  assert.equal(outlineLabelPosition(rect, label, {width: 320, height: 24}, []), null);
});


test("outline badges match selection cards in both languages and preserve their order", () => {
  const link = { tag: "a", selector: "#quick-transfer", text: "Nueva transferencia" };
  assert.equal(formatOutlineLabel(link, false), "Link · Nueva transferencia");
  assert.equal(formatOutlineLabel(link, true, 2), "2 · Enlace · Nueva transferencia");

  const items = [
    link,
    { tag: "a", role: "button", classes: ["boton"], text: "  Reservar\n para un grupo " },
    { tag: "section", selector: "#portada", label: "Portada", text: "Portada y detalles" },
    { tag: "img", label: "🙂".repeat(58) },
    { tag: "div", role: "constructor", selector: "#internal" },
    ...("a link button h1 h6 heading section region article main aside nav navigation header footer form input textarea textbox"
      + " select combobox checkbox radio switch img figure p ul ol list li listitem table tr td th").split(" ").map(tag => ({ tag })),
  ];
  for (const item of items) {
    for (const es of [true, false]) assert.equal(formatOutlineLabel(item, es), chipText(item, es), item.tag);
  }
});

function node(tagName, attrs = {}, children = [], text = "") {
  const element = { tagName: tagName.toUpperCase(), attrs, children, parentElement: null, textContent: text, getAttribute: (name) => (name in attrs ? attrs[name] : null) };
  element.closest = (selector) => { for (let n = element; n; n = n.parentElement) if (selector === "[data-vgen]" ? n.attrs["data-vgen"] !== undefined : false) return n; return null; };
  children.forEach((child) => { child.parentElement = element; });
  const sibling = (offset) => ({ get() { const list = element.parentElement ? element.parentElement.children : []; return list[list.indexOf(element) + offset] || null; } });
  Object.defineProperty(element, "previousElementSibling", sibling(-1));
  Object.defineProperty(element, "nextElementSibling", sibling(1));
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

test("descriptions add a person-facing label without changing source identity", () => {
  const title = node("h1", { id: "titulo" }, [], "Portada");
  const section = node("section", { id: "portada", "aria-labelledby": "titulo", "data-vsrc": "pages/index.html:3:1" }, [title], "VISITAS Portada Más texto");
  section.ownerDocument = { getElementById: (id) => id === "titulo" ? title : null };
  const link = node("a", { id: "reserva", role: "button" }, [], "Reservar para un grupo");
  const body = node("body", {}, [section, link]);
  const env = { count: counter(body), rect: () => ({}), style: () => ({}), scroll: { x: 0, y: 0 } };
  const selection = describeElement(section, env);
  assert.equal(selection.label, "Portada");
  assert.equal(selection.text, "VISITAS Portada Más texto");
  assert.equal(selection.selector, "#portada");
  assert.equal(selection.vsrc, "pages/index.html:3:1");
  assert.equal(describeElement(link, env).role, "button");
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

// A page that re-renders its list: rows are [vsrc, text] in document order.
function listPage(rows) {
  const items = rows.map(([vsrc, text]) => node("li", vsrc ? { "data-vsrc": vsrc } : {}, [], text));
  const body = node("body", {}, [node("ul", {}, items)]);
  const html = node("html", {}, [node("head"), body]);
  return { html, items, all: (selector) => walk(html).filter((candidate) => matches(candidate, selector)) };
}
const matches = (element, selector) => { const parts = selector.split(" > "); let current = element; for (let i = parts.length - 1; i >= 0; i--) { if (!current || !seg(current, parts[i])) return false; current = current.parentElement; } return true; };
const identityOf = (list, at) => { const env = { count: counter(list.html), rect: () => ({ left: 0, top: 0, width: 1, height: 1 }), style: () => ({}), scroll: { x: 0, y: 0 } }; return JSON.parse(JSON.stringify(describeElement(list.items[at], env))); };

test("an element follows its own text through a reorder, and its source position alone never decides", () => {
  const before = listPage([["pages/index.html:2:5", "First revised row"], ["pages/index.html:3:5", "Second stable row"]]);
  const chosen = identityOf(before, 0);
  // the source rows were swapped: the positions now belong to the other text
  const after = listPage([["pages/index.html:2:5", "Second stable row"], ["pages/index.html:3:5", "First revised row"]]);
  assert.equal(reconcile(chosen, after.all), after.items[1], "the chip goes with the text, not with the position");
  // the same list in the same order keeps the element
  assert.equal(reconcile(chosen, listPage([["pages/index.html:2:5", "First revised row"], ["pages/index.html:3:5", "Second stable row"]]).all).textContent, "First revised row");
});

test("an element edited in place is the same element; one that is gone expires", () => {
  const before = listPage([["pages/index.html:2:5", "Old text"], ["pages/index.html:3:5", "Other"]]);
  const chosen = identityOf(before, 0);
  const edited = listPage([["pages/index.html:2:5", "New text"], ["pages/index.html:3:5", "Other"]]);
  assert.equal(reconcile(chosen, edited.all), edited.items[0], "nothing else carries the old text and the place is the same");
  const rewritten = listPage([["pages/index.html:2:5", "Other"], ["pages/index.html:3:5", "Another one"]]);
  assert.equal(reconcile(chosen, rewritten.all), null, "the position now holds something else");
  const removed = listPage([["pages/index.html:3:5", "Other"]]);
  assert.equal(reconcile(chosen, removed.all), null);
  assert.equal(reconcile(null, edited.all), null);
});

test("lookalikes are told apart by source position, then by place; otherwise the selection expires", () => {
  const before = listPage([["pages/index.html:2:5", "Same"], ["pages/index.html:3:5", "Same"], ["pages/index.html:4:5", "Same"]]);
  const second = identityOf(before, 1);
  const kept = listPage([["pages/index.html:2:5", "Same"], ["pages/index.html:3:5", "Same"], ["pages/index.html:4:5", "Same"]]);
  assert.equal(reconcile(second, kept.all), kept.items[1]);
  const same = [["pages/index.html:3:5", "Same"], ["pages/index.html:3:5", "Same"]];
  const twins = listPage(same);
  assert.equal(reconcile({ ...second, index: 1 }, twins.all), twins.items[1], "same position: the place among siblings decides");
  assert.equal(reconcile({ ...second, index: 5 }, twins.all), null, "nothing singles one out");
  const bare = listPage([[null, "Same"], [null, "Same"]]);
  assert.equal(reconcile({ tag: "li", text: "Same", vsrc: null, own_vsrc: false, parent: "ul|", index: 0 }, bare.all), bare.items[0]);
});

// Two rows with the same text and different ids, swapped in the source: the id is the element's own name.
test("an id or data-vid keeps the element through a swap of lookalikes; href tells lookalike links apart", () => {
  const rows = (order) => {
    const items = order.map((id) => node("li", { id, "data-vsrc": "pages/index.html:7:3" }, [], "Available"));
    const html = node("html", {}, [node("head"), node("body", {}, [node("ul", {}, items)])]);
    return { items, all: (selector) => walk(html).filter((candidate) => { const m = selector.match(/^\[id="(.*)"\]$/); return m ? candidate.attrs.id === m[1] : matches(candidate, selector); }) };
  };
  const before = rows(["qa-duplicate-first", "qa-duplicate-second"]);
  const env = { count: () => 1, rect: () => ({ left: 0, top: 0, width: 1, height: 1 }), style: () => ({}), scroll: { x: 0, y: 0 } };
  const chosen = JSON.parse(JSON.stringify(describeElement(before.items[0], env)));
  assert.deepEqual(chosen.anchor, { id: "qa-duplicate-first" });
  const after = rows(["qa-duplicate-second", "qa-duplicate-first"]);
  assert.equal(reconcile(chosen, after.all), after.items[1], "the element named qa-duplicate-first, wherever it is now");
  assert.equal(reconcile(chosen, rows(["qa-duplicate-second"]).all), null, "its name is gone: expired, not a lookalike");
  const link = (href) => node("a", { href }, [], "Open");
  const page2 = (hrefs) => { const items = hrefs.map(link); const html = node("html", {}, [node("head"), node("body", {}, items)]); return { items, all: (selector) => walk(html).filter((c) => matches(c, selector)) }; };
  const links = page2(["/a", "/b"]);
  const picked = JSON.parse(JSON.stringify(describeElement(links.items[1], env)));
  assert.deepEqual(picked.anchor, { href: "/b" });
  const swapped = page2(["/b", "/a"]);
  assert.equal(reconcile(picked, swapped.all), swapped.items[0], "same text, told apart by href");
  assert.deepEqual(JSON.parse(JSON.stringify(anchorOf(node("div", { "data-vid": "v1", id: "x" })))), { vid: "v1", id: "x" });
});

test("the inspector listens only to its parent, from an origin fixed once", () => {
  const parent = {};
  const message = (type, origin, source = parent) => ({ source, origin, data: { hoardDock: 1, type } });
  // nothing is known yet: only a hello from the parent fixes the origin
  assert.equal(gate(null, message("inspect/mode", "http://a.test"), parent), null);
  assert.equal(gate(null, message("inspect/hello", "http://a.test", {}), parent), null, "not the parent window");
  assert.equal(gate(null, message("inspect/hello", "http://a.test"), parent), "http://a.test");
  // once fixed (by the browser or by the first hello) another origin is ignored, even from the parent window
  assert.equal(gate("http://a.test", message("inspect/mode", "http://a.test"), parent), "http://a.test");
  assert.equal(gate("http://a.test", message("inspect/hello", "http://evil.test"), parent), null);
  assert.equal(gate("http://a.test", { source: parent, origin: "http://a.test", data: { hoardDock: 1, type: "dock/ready" } }, parent), null, "not an inspect/ message");
});

test("a pinned comment keeps its identity: attributes first, then source position or tag and text, never a look-alike", () => {
  const { locatePin } = context.VitruviusInspectorCore;
  const el = (tag, attrs, text, parent = null) => { const e = node(tag, attrs, [], text); if (parent) { parent.children.push(e); e.parentElement = parent; } return e; };
  const lookup = (table) => (selector) => { if (!(selector in table)) throw new Error("bad selector"); return table[selector]; };
  const vs = (v) => `[data-vsrc="${v}"]`;
  const pin = { selector: vs("pages/index.html:2:10"), vsrc: "pages/index.html:2:10", own_vsrc: true, tag: "a", text: "Details", revision: "r1", attrs: { id: "details-archive", href: "/records?view=archive" } };
  const archive = el("a", { "data-vsrc": "pages/index.html:2:10", id: "details-archive", href: "/records?view=archive" }, "Details");
  const current = el("a", { "data-vsrc": "pages/index.html:2:10", id: "details-current", href: "/records?view=current" }, "Details");
  // same revision: the unique source position with the same attributes
  assert.equal(locatePin(pin, lookup({ [vs("pages/index.html:2:10")]: [archive] }), "r1").element, archive);
  // the link was replaced by another with the same text and another id and address: no anchor, in any revision
  const sameRevision = locatePin(pin, lookup({ [vs("pages/index.html:2:10")]: [current], a: [current] }), "r1");
  assert.equal(sameRevision.state, "lost"); assert.equal(sameRevision.element, null);
  assert.equal(locatePin(pin, lookup({ a: [current] }), "r2").state, "lost");
  // another revision, the same link moved: found by tag, text and attributes
  const moved = el("a", { "data-vsrc": "pages/index.html:9:3", id: "details-archive", href: "/records?view=archive" }, "Details");
  assert.equal(locatePin(pin, lookup({ a: [current, moved] }), "r2").element, moved);
  // without attributes: tag and text decide on another revision; a changed text or an ambiguous one is no anchor
  const plain = { selector: "h1", vsrc: "pages/index.html:1:1", own_vsrc: true, tag: "h1", text: "Original heading", revision: "r1" };
  const heading = el("h1", { "data-vsrc": "pages/index.html:7:10" }, "Different heading");
  assert.equal(locatePin(plain, lookup({ h1: [heading] }), "r2").state, "lost");
  const same = el("h1", { "data-vsrc": "pages/index.html:3:3" }, "Original heading");
  assert.equal(locatePin(plain, lookup({ h1: [heading, same] }), "r2").element, same);
  assert.equal(locatePin(plain, lookup({ h1: [same, el("h1", {}, "Original heading")] }), "r2").state, "lost");
  assert.equal(locatePin({ ...plain, text: "" }, lookup({ h1: [same] }), "r2").state, "lost");
  // a repeated element is told apart by its place among the siblings
  const list = node("ul", { "data-vsrc": "pages/index.html:3:1" }, [], "");
  const first = el("li", {}, "Row", list); const second = el("li", {}, "Row", list);
  const rowPin = { selector: "li", tag: "li", text: "Row", revision: "r1", own_vsrc: false, parent: "ul|pages/index.html:3:1", index: 1 };
  assert.equal(locatePin(rowPin, lookup({ li: [first, second] }), "r2").element, second);
});

test("a pin follows its stable ID across text and line changes within its source file", () => {
  const { locatePin } = context.VitruviusInspectorCore;
  const button = (attrs, text) => node("button", attrs, [], text);
  const original = { selector: "#preparar", tag: "button", text: "Preparar visita", revision: "r1",
    attrs: { id: "preparar" }, vsrc: "pages/index.html:6:1", own_vsrc: true };
  const edited = button({ id: "preparar", "data-vsrc": "pages/index.html:9:1" }, "Confirmar visita");
  const neighbour = button({ id: "cancelar", "data-vsrc": "pages/index.html:6:1" }, original.text);
  const foreignFile = button({ id: "preparar", "data-vsrc": "pages/otra.html:6:1" }, original.text);
  const wrongTag = node("a", { id: "preparar", "data-vsrc": original.vsrc }, [], original.text);
  assert.equal(locatePin(original, () => [neighbour, edited], "r2").element, edited);
  assert.equal(locatePin(original, () => [neighbour], "r2").state, "lost");
  assert.equal(locatePin(original, () => [foreignFile, wrongTag], "r2").state, "lost");
  assert.equal(locatePin(original, () => [edited, button(edited.attrs, "Duplicado")], "r2").state, "lost");
  const generated = button({ "data-vid": "booking-confirm" }, "Confirmar reserva");
  node("section", { "data-vgen": "form", "data-vsrc": "pages/index.html:12:1" }, [generated]);
  const pin = { ...original, attrs: { "data-vid": "booking-confirm" }, own_vsrc: false };
  assert.equal(locatePin(pin, () => [generated], "r2").element, generated);
});

test("an unnamed comment follows a verified text edit and cannot move to the next heading after deletion", () => {
  const { locatePin } = context.VitruviusInspectorCore;
  const vsrc = "pages/index.html:1:189";
  const section = "pages/index.html:1:180";
  const pin = {
    selector: `[data-vsrc="${vsrc}"]`, tag: "h2", text: "Turnos apuntados", revision: "edited",
    vsrc, own_vsrc: true, parent: `section|${section}`, index: 0,
  };
  const heading = (text, source = vsrc, attrs = {}) => node("h2", { "data-vsrc": source, ...attrs }, [], text);
  const inSection = (children, source = section) => node("section", { "data-vsrc": source }, children);
  const proof = [["edited", vsrc, "h2"]];
  const find = (target, root, revision = "original", textEdits = proof) =>
    locatePin(target, (selector) => walk(root).filter((element) => seg(element, selector)), revision, textEdits);
  const restored = heading("Current records");
  assert.equal(find(pin, inSection([restored])).element, restored);
  const redone = heading(pin.text);
  assert.equal(find(pin, inSection([redone]), "edited").element, redone);

  const following = heading("Inventory");
  assert.equal(find(pin, inSection([following]), "deleted", []).state, "lost", "the following heading reused the source and slot");
  assert.equal(find(pin, inSection([following]), "deleted", [["unrelated", vsrc, "h2"]]).state, "lost", "proof from another revision");
  assert.equal(find(pin, inSection([])).state, "lost", "deleted heading");
  assert.equal(find(pin, inSection([heading("Other heading", "pages/index.html:1:220")])).state, "lost", "different source");
  assert.equal(find(pin, inSection([restored], "pages/index.html:1:150")).state, "lost", "different parent");
  assert.equal(find(pin, inSection([node("p"), restored])).state, "lost", "different sibling slot");
  assert.equal(find(pin, inSection([restored, heading("Duplicate")])).state, "lost", "duplicate source");
  assert.equal(find({ ...pin, selector: "h2:nth-of-type(1)" }, inSection([restored])).state, "lost", "source was not unique when pinned");
  assert.equal(find({ ...pin, own_vsrc: false }, inSection([restored])).state, "lost", "inherited source");
  assert.equal(find(pin, inSection([heading("New heading", vsrc, { id: "replacement" })])).state, "lost", "different declared identity");
});

test("the identity attributes of an element are the ones that tell look-alikes apart", () => {
  const { identityAttrs } = context.VitruviusInspectorCore;
  const found = identityAttrs(node("a", { id: "x", href: "/y", class: "btn", "data-vsrc": "p:1:1" }, [], "T"));
  assert.equal(found.id, "x"); assert.equal(found.href, "/y"); assert.equal(found.class, undefined); assert.equal(found["data-vsrc"], undefined);
});

test("a very long address keeps its pin, and an address that differs only late is another link", () => {
  const { locatePin, identityAttrs, compactAttr } = context.VitruviusInspectorCore;
  const base = "/records?view=archive&" + "filter=".padEnd(300, "x");
  const link = (href) => node("a", { id: "long", href }, [], "Details");
  const original = link(base + "&tail=1");
  assert.equal(base.length + 7 > 300, true);
  const recorded = identityAttrs(original);
  assert.equal(recorded.href.length < 220, true, "the stored value stays short");
  assert.equal(compactAttr("short"), "short");
  const pin = { selector: "#long", tag: "a", text: "Details", revision: "r1", own_vsrc: false, attrs: recorded };
  const lookup = (table) => (selector) => { if (!(selector in table)) throw new Error("bad selector"); return table[selector]; };
  assert.equal(locatePin(pin, lookup({ a: [original] }), "r1").element, original, "the intact link is found again");
  const later = link(base + "&tail=2");
  assert.equal(locatePin(pin, lookup({ a: [later] }), "r1").state, "lost", "a link that differs only after character 300 is not the same");
});
