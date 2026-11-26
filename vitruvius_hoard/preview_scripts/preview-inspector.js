// Vitruvius preview inspector. Loaded only into the owned preview of an application project (never into an export).
// A person turns "select" mode on; hovering outlines the element under the pointer, a click selects it, Shift+click
// adds or removes one, Esc leaves the mode. Every change posts the whole selection to the host page (the frame
// parent) as {hoardDock: 1, type: 'dock/select', selection, mode}. A second mode, comment, picks one element for a note
// ('dock/comment-target', with the served revision and a crop of the element) and paints the pins the host sends
// ('inspect/pins') on the elements they were made on, reporting which of them it still finds ('dock/comment-anchors').
// Plain script: no build step, no dependencies.
(() => {
  'use strict';
  const MAX_TEXT = 200;
  const MAX_SELECTION = 24;
  const MAX_HTML = 1200;
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
      const vsrc = attrOf(node, 'data-vsrc');
      if (vsrc) { const selector = `[data-vsrc="${String(vsrc).replace(/["\\]/g, '\\$&')}"]`; if (count(selector) === 1) return selector; }
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
      own_vsrc: Boolean(vsrcOwner),
      html: String(element.outerHTML || '').slice(0, MAX_HTML),
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

  // The element a recorded description stands for, or null when it cannot be told apart any more. A unique data-vsrc
  // is an identity; otherwise the tag and visible text must still match, so a reordered page never hands the
  // selection to a neighbour. `all(selector)` lists the matching elements of the document.
  function resolveElement(item, all) {
    if (!item || typeof item !== 'object') return null;
    const same = element => tagOf(element) === item.tag && compact(element.innerText ?? element.textContent).slice(0, MAX_TEXT) === item.text;
    let found = [];
    try {
      if (item.own_vsrc && item.vsrc) {
        found = all(`[data-vsrc="${String(item.vsrc).replace(/["\\]/g, '\\$&')}"]`).filter(element => tagOf(element) === item.tag);
        if (found.length > 1) found = found.filter(same);
      } else if (item.selector) found = all(String(item.selector)).filter(same);
    } catch (_) { return null; }
    return found.length === 1 ? found[0] : null;
  }

  // Where a pinned comment's element is now. On the revision the pin was made on, the recorded identity decides (a unique
  // data-vsrc, else selector with the same tag and text). On any other revision source positions mean other lines, so
  // only an element with the same tag and the same non-empty text, found by the selector or alone on the page, is the
  // same element; anything else is a pin without anchor, never moved to a neighbour. `all(selector)` lists matches.
  function locatePin(pin, all, pageRevision) {
    const lost = {state: 'lost', element: null};
    const text = element => compact(element.innerText ?? element.textContent).slice(0, MAX_TEXT);
    const same = element => tagOf(element) === pin.tag && text(element) === (pin.text || '');
    if (!pin.revision || pin.revision === pageRevision) {
      const element = resolveElement({own_vsrc: pin.own_vsrc, vsrc: pin.vsrc, selector: pin.selector, tag: pin.tag, text: pin.text || ''}, all);
      return element ? {state: 'ok', element} : lost;
    }
    if (!pin.text) return lost;
    let found = [];
    try { found = pin.selector ? all(String(pin.selector)).filter(same) : []; } catch (_) { found = []; }
    if (found.length !== 1) { try { found = all(pin.tag).filter(same); } catch (_) { found = []; } }
    return found.length === 1 ? {state: 'ok', element: found[0]} : lost;
  }

  // Who may talk to the inspector: only the frame's parent window, from the origin fixed at the start (the browser's
  // ancestor origin, or else the origin of the first hello). Returns the origin to keep, or null to ignore the message.
  function gate(known, event, parentWindow) {
    const data = event && event.data;
    if (!event || event.source !== parentWindow || !data || data.hoardDock !== 1 || typeof data.type !== 'string' || !data.type.startsWith('inspect/')) return null;
    if (known === null) return data.type === 'inspect/hello' ? event.origin : null;
    return event.origin === known ? known : null;
  }

  const core = {selectorFor, describeElement, resolveElement, locatePin, gate, escapeCss, compact, COMPUTED, MAX_TEXT, MAX_SELECTION};
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
  let hostOrigin = null; // the origin of the page that frames this one: fixed by the browser, or by the first hello
  let mode = false;
  let commenting = false;
  let pins = []; // comments pinned on this page: {id, n, status, selector, vsrc, own_vsrc, tag, text, revision}
  let draft = null; // the element a new comment is being written on
  let flash = ''; let flashTimer = 0; let anchorKey = '';
  let selected = []; // elements, in the order they were chosen
  let hovered = null;
  let focusIndex = -1;
  const picked = new Map(); // element -> its last description, so a page that re-renders can be followed
  let lastRevision;
  let cursorSheet;
  let layer; let root; let frame = 0; let watcher = 0;

  const post = (type, fields = {}) => { if (hostOrigin !== null) window.parent.postMessage({hoardDock: 1, type, ...fields}, hostOrigin); };
  const pageId = () => location.pathname + location.search;
  const revision = () => { const meta = document.querySelector('meta[name="vitruvius-preview-revision"]'); return (meta && meta.content) || null; };
  const describe = element => { const item = {...describeElement(element, env), revision: revision()}; picked.set(element, item); return item; };
  const active = () => mode || commenting;
  const snapshot = () => ({mode, comment_mode: commenting, page: pageId(), revision: revision(), selection: selected.map(describe)});
  // The App Dock context of the page (when the bridge is present) names the selection, so the agent's turn carries it.
  function publishContext(items) {
    const app = window.HoardApp;
    if (!app || typeof app.setContext !== 'function') return;
    const summary = items.length ? 'Selected on the preview: ' + items.map((item, index) => `${index + 1}. ${item.tag}${item.classes[0] ? '.' + item.classes[0] : ''} "${item.text.slice(0, 40)}"${item.vsrc ? ' (' + item.vsrc + ')' : ''}`).join('; ') : '';
    try { app.setContext(() => ({summary: summary.slice(0, 400), ...(items[0] ? {focus: items[0].selector} : {})})); } catch (_) { /* the bridge must not break selection */ }
  }
  const report = () => { const message = snapshot(); lastRevision = message.revision; publishContext(message.selection); post('dock/select', message); };
  const isOwn = element => !element || element === layer || (element.closest && element.closest('[data-vitruvius-inspector-layer]'));
  const candidates = () => [...document.body.querySelectorAll('*')].filter(element => !isOwn(element)
    && !['script', 'style', 'link', 'meta', 'head', 'noscript', 'template'].includes(tagOf(element))
    && element.getClientRects().length && getComputedStyle(element).visibility !== 'hidden');

  function ensureLayer() {
    if (layer) return;
    layer = document.createElement('vitruvius-inspector-layer');
    layer.setAttribute('data-vitruvius-inspector-layer', '');
    layer.setAttribute('aria-hidden', 'true');
    layer.setAttribute('style', LAYER_STYLE);
    root = layer.attachShadow({mode: 'open'});
    root.innerHTML = `<style>
      .box{position:absolute;box-sizing:border-box;pointer-events:none}
      .margin{background:rgba(246,178,107,.35)} .pad{background:rgba(147,196,125,.40)} .content{background:rgba(111,168,220,.40)}
      .hover{outline:2px solid #1a73e8;outline-offset:-1px}
      .picked{outline:2px solid #e8441a;outline-offset:-1px;background:rgba(232,68,26,.08)}
      .tag{position:absolute;max-width:60vw;overflow:hidden;white-space:nowrap;text-overflow:ellipsis;font:600 11px/1.4 system-ui,sans-serif;
        background:#1a73e8;color:#fff;padding:1px 6px;border-radius:3px}
      .badge{position:absolute;min-width:18px;height:18px;border-radius:9px;background:#e8441a;color:#fff;font:700 11px/18px system-ui,sans-serif;text-align:center}
      .pin{position:absolute;pointer-events:auto;cursor:pointer;min-width:20px;height:20px;padding:0 5px;box-sizing:border-box;border:2px solid #fff;border-radius:10px;
        font:700 11px/16px system-ui,sans-serif;color:#fff;text-align:center;box-shadow:0 1px 3px rgba(0,0,0,.45)}
      .pin.s-pending{background:#b45309}.pin.s-seen{background:#1a73e8;box-shadow:0 0 0 2px #1a73e8,0 1px 3px rgba(0,0,0,.45)}
      .pin.s-answered{background:#7b3fc4}.pin.s-resolved{background:#2e7d32}.pin.s-dismissed{background:#6b7280}
      .pin.flash{outline:3px solid #111;outline-offset:2px}
      .draft{outline:2px dashed #b45309;outline-offset:-1px;background:rgba(180,83,9,.10)}
      .fade{transition:opacity .12s} @media (prefers-reduced-motion:reduce){.fade{transition:none}}
    </style><div id="stage"></div>`;
    document.documentElement.appendChild(layer);
    // Project CSS must not hide or move the layer: inline !important wins over any stylesheet rule, and the layer is
    // put back (or its style restored) if the page removes or rewrites it.
    new MutationObserver(() => { if (layer.getAttribute('style') !== LAYER_STYLE) layer.setAttribute('style', LAYER_STYLE); }).observe(layer, {attributes: true, attributeFilter: ['style', 'class', 'hidden']});
  }
  const LAYER_STYLE = ['all:initial', 'display:block', 'position:fixed', 'inset:0', 'width:auto', 'height:auto', 'margin:0', 'padding:0', 'border:0', 'transform:none', 'opacity:1', 'visibility:visible',
    'overflow:visible', 'pointer-events:none', 'z-index:2147483647', 'contain:layout style'].map(rule => rule + '!important').join(';');
  // The crosshair is an adopted stylesheet: the page's own inline styles are never touched.
  function setCursor(on) {
    try {
      if (!cursorSheet) { cursorSheet = new CSSStyleSheet(); cursorSheet.replaceSync('html,html *{cursor:crosshair!important}'); }
      const others = document.adoptedStyleSheets.filter(sheet => sheet !== cursorSheet);
      document.adoptedStyleSheets = on ? [...others, cursorSheet] : others;
    } catch (_) { /* a browser without adopted stylesheets keeps its normal cursor */ }
  }

  const px = value => (parseFloat(value) || 0);
  function paint() {
    frame = 0;
    if (!layer) return;
    const stage = root.getElementById('stage');
    let html = '';
    if (active() && hovered && hovered.isConnected) {
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
    if (draft && draft.isConnected) {
      const r = draft.getBoundingClientRect();
      html += `<div class="box draft" style="left:${r.left}px;top:${r.top}px;width:${r.width}px;height:${r.height}px"></div>`;
    }
    const anchors = []; const slots = new Map(); const now = revision();
    for (const pin of pins) {
      const found = locatePin(pin, all, now);
      if (found.state === 'lost') { anchors.push({id: pin.id, state: 'lost'}); continue; }
      const r = found.element.getBoundingClientRect();
      const slot = slots.get(found.element) || 0; slots.set(found.element, slot + 1);
      anchors.push({id: pin.id, state: 'ok', vsrc: attrOf(found.element, 'data-vsrc') || null,
        box: {x: Math.round(r.left + window.scrollX), y: Math.round(r.top + window.scrollY), w: Math.round(r.width), h: Math.round(r.height)}});
      if (!r.width && !r.height) continue;
      const glyph = {resolved: '\u2713', answered: '?', dismissed: '\u00d7'}[pin.status] || '';
      html += `<button type="button" class="pin s-${pin.status}${flash === pin.id ? ' flash' : ''}" data-pin="${pin.id}" style="left:${Math.max(0, r.right - 12 - slot * 24)}px;top:${Math.max(0, r.top - 10)}px" aria-label="${pin.n} ${pin.status}">${pin.n}${glyph}</button>`;
    }
    stage.innerHTML = html;
    const key = JSON.stringify([now, anchors.map(a => [a.id, a.state, a.vsrc || ''])]);
    if (pins.length && key !== anchorKey) { anchorKey = key; post('dock/comment-anchors', {page: pageId(), revision: now, anchors}); }
  }
  const schedule = () => { if (!frame) frame = requestAnimationFrame(paint); };
  // When the page replaces elements (a live refresh), selected ones that left the document are looked up again by
  // their selector, or dropped; the host is told only when the selection really changed.
  function follow() {
    if (!selected.some(element => !element.isConnected)) return;
    const next = [];
    for (const element of selected) {
      const found = element.isConnected ? element : resolveElement(picked.get(element), all);
      if (found && !next.includes(found)) next.push(found);
    }
    selected = next; schedule(); report();
  }
  const all = selector => [...document.querySelectorAll(selector)];
  // A change of the served revision (a live refresh patches the page in place) is reported again with the new one;
  // a layer the page removed is put back.
  new MutationObserver(() => {
    if (layer && !layer.isConnected) document.documentElement.appendChild(layer);
    if ((selected.length || pins.length || draft) && !watcher) watcher = requestAnimationFrame(() => {
      watcher = 0;
      if (draft && !draft.isConnected) draft = null;
      if (selected.some(element => !element.isConnected)) follow();
      else if (selected.length && revision() !== lastRevision) report();
      if (pins.length || draft) schedule();
    });
  }).observe(document.documentElement, {childList: true, subtree: true, attributes: true, attributeFilter: ['content']});

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
  function onMove(event) { if (!active()) return; const element = elementAt(event); if (element !== hovered) { hovered = element; focusIndex = -1; schedule(); } }
  const pinOf = event => { const path = event.composedPath ? event.composedPath() : []; const pin = path.find(node => node && node.dataset && node.dataset.pin); return pin ? pin.dataset.pin : null; };
  // A crop of the element as it looks now: its computed styles inlined into a copy, drawn through an SVG image. A
  // page that taints the canvas, or an element too big or too busy, gives no crop (null); the comment is kept anyway.
  async function cropOf(element) {
    try {
      const rect = element.getBoundingClientRect();
      const width = Math.ceil(rect.width); const height = Math.ceil(rect.height);
      const sources = [element, ...element.querySelectorAll('*')];
      if (width < 2 || height < 2 || width > 1600 || height > 1200 || sources.length > 300) return null;
      const copy = element.cloneNode(true);
      const copies = [copy, ...copy.querySelectorAll('*')];
      sources.forEach((source, index) => {
        const target = copies[index]; const styles = getComputedStyle(source);
        target.setAttribute('style', [...styles].map(name => `${name}:${styles.getPropertyValue(name)}`).join(';'));
        for (const attribute of [...target.attributes]) if (/^on/i.test(attribute.name)) target.removeAttribute(attribute.name);
      });
      copy.style.margin = '0'; copy.style.position = 'static'; copy.querySelectorAll('script').forEach(node => node.remove());
      const markup = new XMLSerializer().serializeToString(copy);
      const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}"><foreignObject width="100%" height="100%">${markup}</foreignObject></svg>`;
      const image = new Image();
      await new Promise((resolve, reject) => { image.onload = resolve; image.onerror = reject; image.src = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(svg); });
      const scale = Math.min(1, 480 / width, 320 / height);
      const canvas = document.createElement('canvas'); canvas.width = Math.max(1, Math.round(width * scale)); canvas.height = Math.max(1, Math.round(height * scale));
      canvas.getContext('2d').drawImage(image, 0, 0, canvas.width, canvas.height);
      const url = canvas.toDataURL('image/png');
      return url.length < 380000 ? url : null;
    } catch (_) { return null; }
  }
  async function pickForComment(element) {
    draft = element; hovered = null; schedule();
    const item = {...describeElement(element, env), revision: revision()};
    const crop = await cropOf(element);
    if (draft === element) post('dock/comment-target', {page: pageId(), revision: item.revision, element: item, crop});
  }
  function onClick(event) {
    const pin = pinOf(event);
    if (pin) { swallow(event); post('dock/comment-focus', {page: pageId(), revision: revision(), id: pin}); return; }
    if (!active()) return;
    swallow(event);
    const element = elementAt(event);
    if (commenting) { if (element) pickForComment(element); return; }
    choose(element, event.shiftKey);
  }
  function onBlock(event) { if (active() && !pinOf(event)) { event.preventDefault(); event.stopPropagation(); } }
  function onKey(event) {
    if (event.altKey && event.shiftKey && event.code === 'KeyS') { event.preventDefault(); setMode(!mode); return; }
    if (event.altKey && event.shiftKey && event.code === 'KeyC') { event.preventDefault(); setMode(!commenting, 'comment'); return; }
    if (!active()) return;
    if (event.key === 'Escape') { swallow(event); setMode(false, commenting ? 'comment' : 'select'); return; }
    if (event.key === 'Tab') {
      swallow(event);
      const list = candidates(); if (!list.length) return;
      focusIndex = (focusIndex + (event.shiftKey ? -1 : 1) + list.length) % list.length;
      hovered = list[focusIndex]; hovered.scrollIntoView?.({block: 'nearest', behavior: reduced() ? 'auto' : 'smooth'}); schedule();
    } else if (event.key === 'Enter' && hovered) { swallow(event); if (commenting) pickForComment(hovered); else choose(hovered, event.shiftKey); }
  }

  // Select and Comment exclude each other: turning one on turns the other off.
  function setMode(on, kind = 'select') {
    if (kind === 'comment') { commenting = Boolean(on); if (commenting) mode = false; } else { mode = Boolean(on); if (mode) commenting = false; }
    ensureLayer();
    if (!active()) hovered = null;
    if (!commenting) draft = null;
    setCursor(active());
    schedule(); report();
  }

  function restore(items) {
    const found = [];
    for (const item of Array.isArray(items) ? items.slice(0, MAX_SELECTION) : []) {
      const element = resolveElement(item, all); // an element that cannot be told apart is dropped, never guessed
      if (element) { picked.set(element, item); if (!found.includes(element)) found.push(element); }
    }
    selected = found; ensureLayer(); schedule(); report();
  }

  window.addEventListener('message', event => {
    const accepted = gate(hostOrigin, event, window.parent);
    if (accepted === null) return;
    hostOrigin = accepted;
    const data = event.data;
    if (data.type === 'inspect/hello') { const message = snapshot(); lastRevision = message.revision; publishContext(message.selection); post('dock/inspector-ready', message); }
    else if (data.type === 'inspect/mode') setMode(data.on, data.kind === 'comment' ? 'comment' : 'select');
    else if (data.type === 'inspect/pins') {
      const states = ['pending', 'seen', 'answered', 'resolved', 'dismissed']; const text = value => (typeof value === 'string' ? value : '');
      pins = (Array.isArray(data.pins) ? data.pins : []).slice(0, 300).filter(pin => pin && typeof pin.id === 'string' && Number.isInteger(pin.n))
        .map(pin => ({id: pin.id, n: pin.n, status: states.includes(pin.status) ? pin.status : 'pending', selector: text(pin.selector), vsrc: text(pin.vsrc),
          own_vsrc: pin.own_vsrc === true, tag: text(pin.tag), text: text(pin.text), revision: text(pin.revision)}));
      ensureLayer(); anchorKey = ''; schedule();
    }
    else if (data.type === 'inspect/draft-clear') { draft = null; schedule(); }
    else if (data.type === 'inspect/pin-focus') {
      const pin = pins.find(entry => entry.id === data.id);
      const found = pin && locatePin(pin, all, revision());
      if (found && found.element) { found.element.scrollIntoView?.({block: 'center', behavior: reduced() ? 'auto' : 'smooth'}); flash = pin.id; clearTimeout(flashTimer); flashTimer = setTimeout(() => { flash = ''; schedule(); }, 1600); schedule(); }
    }
    else if (data.type === 'inspect/clear') { selected = []; schedule(); report(); }
    else if (data.type === 'inspect/remove') { const at = Number(data.index); if (Number.isInteger(at) && at >= 0 && at < selected.length) { selected.splice(at, 1); schedule(); report(); } }
    else if (data.type === 'inspect/restore') restore(data.items);
  });
  document.addEventListener('mousemove', onMove, true);
  document.addEventListener('click', onClick, true);
  for (const type of ['mousedown', 'mouseup', 'pointerdown', 'pointerup', 'submit', 'dblclick', 'auxclick', 'contextmenu']) document.addEventListener(type, onBlock, true);
  document.addEventListener('keydown', onKey, true);
  window.addEventListener('scroll', schedule, true);
  window.addEventListener('resize', schedule);
  window.__vitruviusInspector = {version: 1, core};
  try { const ancestor = location.ancestorOrigins && location.ancestorOrigins[0]; if (ancestor) { hostOrigin = ancestor; post('dock/inspector-ready', snapshot()); } } catch (_) { /* the host will say hello */ }
})();
