// Vitruvius preview inspector. Loaded only into the owned preview of an application project (never into an export).
// A person turns "select" mode on; hovering outlines the element under the pointer, a click selects it, Shift+click
// adds or removes one, Esc leaves the mode. Every change posts the whole selection to the host page (the frame
// parent) as {hoardDock: 1, type: 'dock/select', selection, mode}. Plain script: no build step, no dependencies.
(() => {
  'use strict';
  const MAX_TEXT = 200;
  const MAX_SELECTION = 24;
  const COMPUTED = ['display', 'width', 'height', 'color', 'backgroundColor', 'fontFamily', 'fontSize', 'fontWeight',
    'lineHeight', 'margin', 'padding', 'borderRadius', 'borderWidth', 'gap'];

  const compact = value => String(value || '').replace(/\s+/g, ' ').trim();
  const escapeCss = value => (globalThis.CSS && CSS.escape ? CSS.escape(value)
    : String(value).replace(/^\d|[^a-zA-Z0-9_\u00a0-\uffff-]/g, (char, at) => (at === 0 && /\d/.test(char) ? `\\3${char} ` : `\\${char}`)));
  const tagOf = element => String(element.tagName || '').toLowerCase();
  const attrOf = (element, name) => (element.getAttribute ? element.getAttribute(name) : null);

  function sameTagIndex(element) {
    const parent = element.parentElement;
    if (!parent) return {index: 1, total: 1};
    const same = [...parent.children].filter(sibling => tagOf(sibling) === tagOf(element));
    return {index: same.indexOf(element) + 1, total: same.length};
  }

  // Stable selector: data-vid, then id, then the shortest unique tag/nth-of-type path (stopping at an anchor).
  // `count(selector)` says how many elements the selector matches in the document.
  function selectorFor(element, count) {
    const anchor = node => {
      const vid = attrOf(node, 'data-vid');
      if (vid) { const selector = `[data-vid="${String(vid).replace(/["\\]/g, '\\$&')}"]`; if (count(selector) === 1) return selector; }
      const id = attrOf(node, 'id');
      if (id) { const selector = `#${escapeCss(id)}`; if (count(selector) === 1) return selector; }
      return null;
    };
    const own = anchor(element);
    if (own) return own;
    const parts = [];
    let node = element;
    let best = '';
    while (node && tagOf(node) && tagOf(node) !== 'html') {
      const {index, total} = sameTagIndex(node);
      const part = tagOf(node) === 'body' ? 'body' : (total > 1 ? `${tagOf(node)}:nth-of-type(${index})` : tagOf(node));
      parts.unshift(part);
      best = parts.join(' > ');
      if (count(best) === 1) return best;
      const parent = node.parentElement;
      const head = parent && parent !== node ? anchor(parent) : null;
      if (head) { best = `${head} > ${parts.join(' > ')}`; if (count(best) === 1) return best; }
      node = parent;
    }
    return best;
  }

  function describeElement(element, env) {
    const {count, rect, style, scroll} = env;
    const vsrcOwner = attrOf(element, 'data-vsrc') ? element : null;
    const generated = element.closest ? element.closest('[data-vgen]') : null;
    const vsrc = vsrcOwner ? attrOf(vsrcOwner, 'data-vsrc') : (generated ? attrOf(generated, 'data-vsrc') : null);
    const box = rect(element);
    const computed = {};
    const styles = style(element) || {};
    for (const key of COMPUTED) if (styles[key] !== undefined && styles[key] !== '') computed[key] = String(styles[key]).slice(0, 120);
    const classes = String(attrOf(element, 'class') || '').split(/\s+/).filter(Boolean).slice(0, 12);
    return {
      vsrc: vsrc || null,
      vgen: generated ? attrOf(generated, 'data-vgen') : null,
      selector: selectorFor(element, count),
      tag: tagOf(element),
      classes,
      text: compact(element.innerText ?? element.textContent).slice(0, MAX_TEXT),
      box: {x: Math.round(box.left + scroll.x), y: Math.round(box.top + scroll.y), w: Math.round(box.width), h: Math.round(box.height)},
      computed,
      same_vsrc_count: vsrc ? count(`[data-vsrc="${String(vsrc).replace(/["\\]/g, '\\$&')}"]`) : 0,
    };
  }

  const core = {selectorFor, describeElement, escapeCss, compact, COMPUTED, MAX_TEXT, MAX_SELECTION};
  if (globalThis.__VITRUVIUS_INSPECTOR_TEST__) { globalThis.VitruviusInspectorCore = core; return; }
  if (window.__vitruviusInspector) return;
  if (window === window.parent) return; // only meaningful inside the workbench frame

  // ---- browser side ------------------------------------------------------------------------------------------
  const reduced = () => window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const env = {
    count: selector => { try { return document.querySelectorAll(selector).length; } catch (_) { return 0; } },
    rect: element => element.getBoundingClientRect(),
    style: element => getComputedStyle(element),
    scroll: {get x() { return window.scrollX; }, get y() { return window.scrollY; }},
  };
  let hostOrigin = null;
  let mode = false;
  let selected = []; // elements, in the order they were chosen
  let hovered = null;
  let focusIndex = -1;
  const picked = new Map(); // element -> selector, so a page that re-renders can be followed
  let layer; let root; let frame = 0; let watcher = 0;

  const post = (type, fields = {}) => { if (hostOrigin !== null) window.parent.postMessage({hoardDock: 1, type, ...fields}, hostOrigin); };
  const pageId = () => location.pathname + location.search;
  const describe = element => { const item = describeElement(element, env); picked.set(element, item.selector); return item; };
  const report = () => post('dock/select', {mode, page: pageId(), selection: selected.map(describe)});
  const isOwn = element => !element || element === layer || (element.closest && element.closest('[data-vitruvius-inspector-layer]'));
  const candidates = () => [...document.body.querySelectorAll('*')].filter(element => !isOwn(element)
    && !['script', 'style', 'link', 'meta', 'head', 'noscript', 'template'].includes(tagOf(element))
    && element.getClientRects().length && getComputedStyle(element).visibility !== 'hidden');

  function ensureLayer() {
    if (layer) return;
    layer = document.createElement('div');
    layer.setAttribute('data-vitruvius-inspector-layer', '');
    layer.setAttribute('aria-hidden', 'true');
    layer.style.cssText = 'position:fixed;inset:0;pointer-events:none;z-index:2147483646;contain:layout style;';
    root = layer.attachShadow({mode: 'open'});
    root.innerHTML = `<style>
      .box{position:absolute;box-sizing:border-box;pointer-events:none}
      .margin{background:rgba(246,178,107,.35)} .pad{background:rgba(147,196,125,.40)} .content{background:rgba(111,168,220,.40)}
      .hover{outline:2px solid #1a73e8;outline-offset:-1px}
      .picked{outline:2px solid #e8441a;outline-offset:-1px;background:rgba(232,68,26,.08)}
      .tag{position:absolute;max-width:60vw;overflow:hidden;white-space:nowrap;text-overflow:ellipsis;font:600 11px/1.4 system-ui,sans-serif;
        background:#1a73e8;color:#fff;padding:1px 6px;border-radius:3px}
      .badge{position:absolute;min-width:18px;height:18px;border-radius:9px;background:#e8441a;color:#fff;font:700 11px/18px system-ui,sans-serif;text-align:center}
      .fade{transition:opacity .12s} @media (prefers-reduced-motion:reduce){.fade{transition:none}}
    </style><div id="stage"></div>`;
    document.documentElement.appendChild(layer);
  }

  const px = value => (parseFloat(value) || 0);
  function paint() {
    frame = 0;
    if (!layer) return;
    const stage = root.getElementById('stage');
    let html = '';
    if (mode && hovered && hovered.isConnected) {
      const r = hovered.getBoundingClientRect(); const s = getComputedStyle(hovered);
      const m = ['Top', 'Right', 'Bottom', 'Left'].map(side => px(s['margin' + side]));
      const p = ['Top', 'Right', 'Bottom', 'Left'].map(side => px(s['padding' + side]));
      const b = ['Top', 'Right', 'Bottom', 'Left'].map(side => px(s['border' + side + 'Width']));
      html += `<div class="box margin fade" style="left:${r.left - m[3]}px;top:${r.top - m[0]}px;width:${r.width + m[1] + m[3]}px;height:${r.height + m[0] + m[2]}px"></div>`;
      html += `<div class="box pad hover fade" style="left:${r.left}px;top:${r.top}px;width:${r.width}px;height:${r.height}px"></div>`;
      html += `<div class="box content" style="left:${r.left + b[3] + p[3]}px;top:${r.top + b[0] + p[0]}px;width:${Math.max(0, r.width - b[1] - b[3] - p[1] - p[3])}px;height:${Math.max(0, r.height - b[0] - b[2] - p[0] - p[2])}px"></div>`;
      const label = tagOf(hovered) + (hovered.classList && hovered.classList.length ? '.' + [...hovered.classList].slice(0, 3).join('.') : '');
      html += `<div class="tag" style="left:${Math.max(0, r.left)}px;top:${r.top > 22 ? r.top - 20 : r.top + 2}px">${label.replace(/[<>&]/g, '')}</div>`;
    }
    selected.forEach((element, index) => {
      const r = element.getBoundingClientRect();
      html += `<div class="box picked" style="left:${r.left}px;top:${r.top}px;width:${r.width}px;height:${r.height}px"></div>`;
      html += `<div class="badge" style="left:${Math.max(0, r.left - 6)}px;top:${Math.max(0, r.top - 9)}px">${index + 1}</div>`;
    });
    stage.innerHTML = html;
  }
  const schedule = () => { if (!frame) frame = requestAnimationFrame(paint); };
  // When the page replaces elements (a live refresh), selected ones that left the document are looked up again by
  // their selector, or dropped; the host is told only when the selection really changed.
  function follow() {
    watcher = 0;
    if (!selected.some(element => !element.isConnected)) return;
    const next = [];
    for (const element of selected) {
      let found = element;
      if (!element.isConnected) { try { found = document.querySelector(picked.get(element) || ''); } catch (_) { found = null; } }
      if (found && !next.includes(found)) next.push(found);
    }
    selected = next; schedule(); report();
  }
  new MutationObserver(() => { if (selected.length && !watcher) watcher = requestAnimationFrame(follow); }).observe(document.documentElement, {childList: true, subtree: true});

  function elementAt(event) {
    const hit = document.elementsFromPoint ? document.elementsFromPoint(event.clientX, event.clientY).find(element => !isOwn(element)) : event.target;
    return hit && hit !== document.documentElement ? hit : null;
  }

  function choose(element, additive) {
    if (!element) return;
    const at = selected.indexOf(element);
    if (additive) { if (at >= 0) selected.splice(at, 1); else if (selected.length < MAX_SELECTION) selected.push(element); }
    else selected = at >= 0 && selected.length === 1 ? [] : [element];
    schedule(); report();
  }

  const swallow = event => { event.preventDefault(); event.stopPropagation(); event.stopImmediatePropagation?.(); };
  function onMove(event) { if (!mode) return; const element = elementAt(event); if (element !== hovered) { hovered = element; focusIndex = -1; schedule(); } }
  function onClick(event) { if (!mode) return; swallow(event); choose(elementAt(event), event.shiftKey); }
  function onBlock(event) { if (mode) { event.preventDefault(); event.stopPropagation(); } }
  function onKey(event) {
    if (event.altKey && event.shiftKey && event.code === 'KeyS') { event.preventDefault(); setMode(!mode); return; }
    if (!mode) return;
    if (event.key === 'Escape') { swallow(event); setMode(false); return; }
    if (event.key === 'Tab') {
      swallow(event);
      const list = candidates(); if (!list.length) return;
      focusIndex = (focusIndex + (event.shiftKey ? -1 : 1) + list.length) % list.length;
      hovered = list[focusIndex]; hovered.scrollIntoView?.({block: 'nearest', behavior: reduced() ? 'auto' : 'smooth'}); schedule();
    } else if (event.key === 'Enter' && hovered) { swallow(event); choose(hovered, event.shiftKey); }
  }

  function setMode(on) {
    mode = Boolean(on);
    ensureLayer();
    if (!mode) hovered = null;
    document.documentElement.style.cursor = mode ? 'crosshair' : '';
    schedule(); report();
  }

  function restore(selectors) {
    const found = [];
    for (const selector of Array.isArray(selectors) ? selectors.slice(0, MAX_SELECTION) : []) {
      let element = null;
      try { element = document.querySelector(String(selector)); } catch (_) { /* a stale selector is skipped */ }
      if (element && !found.includes(element)) found.push(element);
    }
    selected = found; ensureLayer(); schedule(); report();
  }

  window.addEventListener('message', event => {
    if (event.source !== window.parent) return;
    const data = event.data;
    if (!data || data.hoardDock !== 1 || typeof data.type !== 'string' || !data.type.startsWith('inspect/')) return;
    hostOrigin = event.origin;
    if (data.type === 'inspect/hello') post('dock/inspector-ready', {mode, page: pageId(), selection: selected.map(describe)});
    else if (data.type === 'inspect/mode') setMode(data.on);
    else if (data.type === 'inspect/clear') { selected = []; schedule(); report(); }
    else if (data.type === 'inspect/remove') { const at = Number(data.index); if (Number.isInteger(at) && at >= 0 && at < selected.length) { selected.splice(at, 1); schedule(); report(); } }
    else if (data.type === 'inspect/restore') restore(data.selectors);
  });
  document.addEventListener('mousemove', onMove, true);
  document.addEventListener('click', onClick, true);
  for (const type of ['mousedown', 'mouseup', 'pointerdown', 'pointerup', 'submit', 'dblclick', 'auxclick', 'contextmenu']) document.addEventListener(type, onBlock, true);
  document.addEventListener('keydown', onKey, true);
  window.addEventListener('scroll', schedule, true);
  window.addEventListener('resize', schedule);
  window.__vitruviusInspector = {version: 1, core};
  try { const ancestor = (location.ancestorOrigins && location.ancestorOrigins[0]) || (document.referrer ? new URL(document.referrer).origin : null); if (ancestor) { hostOrigin = ancestor; post('dock/inspector-ready', {mode, page: pageId(), selection: []}); } } catch (_) { /* the host will say hello */ }
})();
