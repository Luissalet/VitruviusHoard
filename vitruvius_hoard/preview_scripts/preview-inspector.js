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
      ...relationOf(element),
      anchor: anchorOf(element),
      same_vsrc_count: vsrc ? count(`[data-vsrc="${String(vsrc).replace(/["\\]/g, '\\$&')}"]`) : 0,
    };
  }

  const textOf = element => compact(element.innerText ?? element.textContent).slice(0, MAX_TEXT);
  // What the element itself declares as its identity: data-vid and id are strong (unique in a document), href and name tell
  // lookalike links and fields apart.
  function anchorOf(element) {
    const anchor = {};
    for (const [key, name] of [['vid', 'data-vid'], ['id', 'id'], ['href', 'href'], ['name', 'name']]) {
      const value = attrOf(element, name);
      if (value) anchor[key] = String(value).slice(0, 200);
    }
    return anchor;
  }
  const sameAnchor = (item, element) => Object.entries(item.anchor || {}).every(([key, value]) => key === 'vid' || key === 'id' || attrOf(element, key === 'vid' ? 'data-vid' : key) === value);
  // Where an element sits among its siblings: its parent (tag and source position) and its index there.
  function relationOf(element) {
    const parent = element.parentElement;
    const text = sibling => (sibling ? textOf(sibling).slice(0, 80) : null);
    return {parent: parent ? `${tagOf(parent)}|${attrOf(parent, 'data-vsrc') || ''}` : '', index: parent ? [...parent.children].indexOf(element) : 0,
      near: [text(element.previousElementSibling), text(element.nextElementSibling)]};
  }

  // The element a recorded description stands for, in this document or in another revision of it, or null when it is
  // no longer the same element: the tag and visible text must still match, and when several elements look alike the
  // source position and then the place among the siblings must single one out. A source position alone is never an
  // identity across revisions (editing the source reassigns positions). When no element carries the old text, an
  // element at the very same position and place is taken as the same element edited in place. Otherwise null: the
  // selection is reported as expired, never handed to a neighbour. `all(selector)` lists matching elements.
  function reconcile(item, all) {
    if (!item || typeof item !== 'object' || !item.tag) return null;
    // A data-vid or an id is the element's own name: the element that still has it is the same element, whatever its text or
    // position became; when nothing has it any more, the element is gone.
    const named = item.anchor && (item.anchor.vid ? ['data-vid', item.anchor.vid] : item.anchor.id ? ['id', item.anchor.id] : null);
    if (named) {
      let byName;
      try { byName = all(`[${named[0]}="${String(named[1]).replace(/["\\]/g, '\\$&')}"]`).filter(element => tagOf(element) === item.tag); } catch (_) { return null; }
      return byName.length === 1 ? byName[0] : null;
    }
    let alike;
    try { alike = all(String(item.tag)).filter(element => tagOf(element) === item.tag && textOf(element) === item.text && sameAnchor(item, element)); } catch (_) { return null; }
    let pick = alike;
    if (pick.length > 1 && item.vsrc) pick = pick.filter(element => attrOf(element, 'data-vsrc') === item.vsrc);
    if (pick.length > 1) pick = pick.filter(element => { const at = relationOf(element); return at.parent === item.parent && at.index === item.index; });
    if (pick.length === 1) return pick[0];
    if (alike.length > 0) return null; // several look alike and nothing singles one out
    if (item.own_vsrc && item.vsrc) {
      let here;
      try { here = all(`[data-vsrc="${String(item.vsrc).replace(/["\\]/g, '\\$&')}"]`).filter(element => tagOf(element) === item.tag && sameAnchor(item, element)); } catch (_) { return null; }
      // An edit keeps the place; text that used to belong to a neighbour means the content moved, not that this was edited.
      if (here.length === 1) { const at = relationOf(here[0]); if (at.parent === item.parent && at.index === item.index && !(item.near || []).includes(textOf(here[0]).slice(0, 80))) return here[0]; }
    }
    return null;
  }

  // Attributes that tell two look-alike elements apart (a link's address, an id): recorded with a comment and checked again.
  const IDENTITY_ATTRS = ['id', 'href', 'data-vid', 'name', 'src', 'for'];
  const MAX_PINS = 300; // the same limit per page as the server keeps (preview_comments.MAX_PER_PAGE)
  // A long attribute (an address of hundreds of characters) is kept as its start plus a hash of the whole, so two values that
  // differ only late are told apart and the stored value stays short. Recording and comparing both go through here.
  function compactAttr(value) {
    const text = String(value);
    if (text.length <= 200) return text;
    let hash = 0x811c9dc5;
    for (let i = 0; i < text.length; i++) { hash ^= text.charCodeAt(i); hash = Math.imul(hash, 0x01000193) >>> 0; }
    return `${text.slice(0, 160)}#${text.length}:${hash.toString(16)}`;
  }
  function identityAttrs(element) {
    const found = {};
    for (const name of IDENTITY_ATTRS) { const value = attrOf(element, name); if (value) found[name] = compactAttr(value); }
    return found;
  }
  // Where a pinned comment's element is now. A pin names the element by its tag, its visible text and the attributes above;
  // an explicit attribute that changed means another element, whatever the text says. On the revision the pin was made on a
  // unique source position is enough; on any other revision source positions mean other lines, so the tag, a non-empty
  // text (or an identity attribute) and, when several look alike, the place among the siblings must single one out.
  // Otherwise the pin has no anchor: it is never moved to a neighbour. `all(selector)` lists the matching elements.
  function locatePin(pin, all, pageRevision) {
    const lost = {state: 'lost', element: null};
    const attrs = pin.attrs && typeof pin.attrs === 'object' ? pin.attrs : {};
    const attrsOk = element => IDENTITY_ATTRS.every(name => !attrs[name] || compactAttr(attrOf(element, name)) === attrs[name]);
    const quote = value => String(value).replace(/["\\]/g, '\\$&');
    try {
      if (pin.revision && pin.revision === pageRevision && pin.own_vsrc && pin.vsrc) {
        const here = all(`[data-vsrc="${quote(pin.vsrc)}"]`).filter(element => tagOf(element) === pin.tag && attrsOk(element));
        if (here.length === 1) return {state: 'ok', element: here[0]};
      }
      if (!pin.text && !Object.keys(attrs).length) return lost;
      let pick = all(String(pin.tag)).filter(element => tagOf(element) === pin.tag && textOf(element) === (pin.text || '') && attrsOk(element));
      if (pick.length > 1 && pin.revision === pageRevision && pin.own_vsrc && pin.vsrc) pick = pick.filter(element => attrOf(element, 'data-vsrc') === pin.vsrc);
      if (pick.length > 1 && typeof pin.parent === 'string') pick = pick.filter(element => { const at = relationOf(element); return at.parent === pin.parent && at.index === pin.index; });
      return pick.length === 1 ? {state: 'ok', element: pick[0]} : lost;
    } catch (_) { return lost; }
  }

  // Who may talk to the inspector: only the frame's parent window, from the origin fixed at the start (the browser's
  // ancestor origin, or else the origin of the first hello). Returns the origin to keep, or null to ignore the message.
  function gate(known, event, parentWindow) {
    const data = event && event.data;
    if (!event || event.source !== parentWindow || !data || data.hoardDock !== 1 || typeof data.type !== 'string' || !data.type.startsWith('inspect/')) return null;
    if (known === null) return data.type === 'inspect/hello' ? event.origin : null;
    return event.origin === known ? known : null;
  }

  const core = {selectorFor, describeElement, reconcile, relationOf, anchorOf, textOf, locatePin, identityAttrs, compactAttr, gate, escapeCss, compact, COMPUTED, MAX_TEXT, MAX_SELECTION};
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
  let hostLanguage;
  let mode = false;
  let commenting = false;
  let pins = []; // comments pinned on this page: {id, n, status, selector, vsrc, own_vsrc, tag, text, revision}
  let draft = null; // the element a new comment is being written on
  let flash = ''; let flashTimer = 0; let anchorKey = '';
  let selected = []; // elements, in the order they were chosen
  let hovered = null;
  let focusIndex = -1;
  const picked = new Map(); // element -> what it was when chosen (tag, text, position, place), so another revision can be matched
  const clips = new WeakMap(); // element -> data URL of its clip, or false when none could be made
  let expired = []; // chosen elements that are no longer the same element on the revision now served
  let lastRevision, updatedTs = null;
  let cursorSheet;
  let layer; let root; let edits; let frame = 0; let watcher = 0;

  const post = (type, fields = {}) => { if (hostOrigin !== null) window.parent.postMessage({hoardDock: 1, type, ...fields}, hostOrigin); };
  const pageId = () => location.pathname + location.search;
  const sessionId = () => { const meta = document.querySelector('meta[name="vitruvius-preview-session"]'); return (meta && meta.content) || null; };
  const revision = () => { const meta = document.querySelector('meta[name="vitruvius-preview-revision"]'); return (meta && meta.content) || null; };
  const describe = element => {
    const item = {...describeElement(element, env), revision: revision()};
    if (!picked.has(element)) picked.set(element, item);
    const clip = clips.get(element);
    if (clip) item.clip = clip;
    else if (clip === undefined) wantClip(element);
    return item;
  };
  // Live cards first, then the expired ones: they stay in the list, flagged, until the person removes them.
  const active = () => mode || commenting;
  const snapshot = () => ({mode, comment_mode: commenting, page: pageId(), revision: revision(), selection: [...selected.map(describe), ...expired]});
  // A clip of the element (an SVG foreignObject drawn to a canvas), made once, off the report path; the list is reported again when it is ready.
  let clipTimer = 0;
  function wantClip(element) {
    clips.set(element, false);
    captureClip(element).then(clip => { if (clip) { clips.set(element, clip); if (!clipTimer) clipTimer = setTimeout(() => { clipTimer = 0; if (selected.includes(element)) report(); }, 60); } }, () => {});
  }
  const CLIP_STYLES = ['display', 'position', 'box-sizing', 'width', 'height', 'margin', 'padding', 'border', 'border-radius', 'color', 'background-color', 'background-image', 'font-family', 'font-size', 'font-weight',
    'font-style', 'line-height', 'letter-spacing', 'text-align', 'text-decoration', 'text-transform', 'white-space', 'flex', 'flex-direction', 'justify-content', 'align-items', 'gap', 'grid-template-columns',
    'overflow', 'opacity', 'list-style', 'vertical-align', 'border-collapse', 'min-width', 'max-width', 'object-fit'];
  // Pixels of an element the page has already loaded (an <img>, a <canvas>), or null when the browser will not give them
  // (a cross-origin image taints the canvas). A clip is an SVG image and cannot load anything itself, so every picture
  // in it travels inline, or is left out and named in the card.
  function pixelsOf(source, width, height) {
    try {
      const canvas = document.createElement('canvas');
      canvas.width = Math.max(1, Math.min(800, Math.round(width))); canvas.height = Math.max(1, Math.min(800, Math.round(height)));
      canvas.getContext('2d').drawImage(source, 0, 0, canvas.width, canvas.height);
      return canvas.toDataURL('image/png');
    } catch (_) { return null; }
  }
  function loadImage(url) {
    return new Promise(resolve => { const image = new Image(); image.onload = () => resolve(image); image.onerror = () => resolve(null); image.src = url; });
  }
  async function captureClip(element) {
    const r = element.getBoundingClientRect();
    if (!(r.width > 0 && r.height > 0)) return null;
    const scale = Math.min(1, 480 / r.width, 360 / r.height);
    const w = Math.max(1, Math.round(r.width * scale)); const h = Math.max(1, Math.round(r.height * scale));
    const clone = element.cloneNode(true);
    const originals = [element, ...element.querySelectorAll('*')].slice(0, 80);
    const copies = [clone, ...clone.querySelectorAll('*')];
    const omitted = [];
    let root = clone; // the element being clipped: it may itself be the picture, which is then swapped like any other
    const swap = (target, replacement) => { if (target === root) root = replacement; else target.replaceWith(replacement); };
    const leaveOut = (original, target, why) => {
      omitted.push(`${tagOf(original)} ${(original.currentSrc || original.getAttribute('src') || '').slice(0, 80)}: ${why}`.trim());
      const box = original.getBoundingClientRect();
      const hole = document.createElement('span');
      hole.setAttribute('style', `display:inline-block;width:${Math.round(box.width)}px;height:${Math.round(box.height)}px`);
      swap(target, hole);
    };
    for (let index = 0; index < originals.length; index++) {
      const original = originals[index]; const target = copies[index];
      if (!target || !target.setAttribute) continue;
      const computed = getComputedStyle(original);
      let style = CLIP_STYLES.map(name => `${name}:${computed.getPropertyValue(name)}`).join(';') + ';margin:0';
      target.removeAttribute('data-vsrc'); target.removeAttribute('data-vgen');
      const kind = tagOf(original);
      if (kind === 'img' || kind === 'canvas') {
        const box = original.getBoundingClientRect();
        const loaded = kind === 'canvas' || (original.complete && original.naturalWidth > 0);
        const data = loaded ? pixelsOf(original, kind === 'canvas' ? original.width : original.naturalWidth || box.width, kind === 'canvas' ? original.height : original.naturalHeight || box.height) : null;
        if (data) {
          const picture = document.createElement('img');
          picture.setAttribute('src', data); picture.setAttribute('alt', original.getAttribute('alt') || '');
          picture.setAttribute('style', style + `;width:${Math.round(box.width)}px;height:${Math.round(box.height)}px`);
          swap(target, picture);
          continue;
        }
        leaveOut(original, target, loaded ? 'not readable (another origin)' : 'not loaded');
        continue;
      }
      const background = computed.getPropertyValue('background-image');
      if (background && background !== 'none' && background.includes('url(')) {
        const url = (background.match(/url\(["']?([^"')]+)["']?\)/) || [])[1];
        const picture = url ? await loadImage(url) : null;
        const data = picture ? pixelsOf(picture, picture.naturalWidth || 1, picture.naturalHeight || 1) : null;
        if (data) style = style.replace(/background-image:[^;]*/, `background-image:url("${data}")`);
        else { style = style.replace(/background-image:[^;]*/, 'background-image:none'); omitted.push(`${kind} background ${String(url || '').slice(0, 80)}: not readable`); }
      }
      target.setAttribute('style', style);
    }
    copies.slice(80).forEach(extra => extra.remove());
    const markup = new XMLSerializer().serializeToString(root);
    const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${h}" viewBox="0 0 ${Math.ceil(r.width)} ${Math.ceil(r.height)}"><foreignObject x="0" y="0" width="${Math.ceil(r.width)}" height="${Math.ceil(r.height)}">${markup}</foreignObject></svg>`;
    const image = new Image();
    await new Promise((resolve, reject) => { image.onload = resolve; image.onerror = reject; image.src = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(svg); });
    const canvas = document.createElement('canvas'); canvas.width = w; canvas.height = h;
    const context = canvas.getContext('2d'); context.fillStyle = '#fff'; context.fillRect(0, 0, w, h); context.drawImage(image, 0, 0, w, h);
    let data = canvas.toDataURL('image/png');
    if (data.length > 150000) data = canvas.toDataURL('image/jpeg', 0.6);
    return data.length <= 150000 ? {mime: data.slice(5, data.indexOf(';')), w, h, bytes: Math.round(data.length * 0.75), omitted: omitted.slice(0, 8), data_url: data} : null;
  }
  // The App Dock context of the page (when the bridge is present) names the selection, so the agent's turn carries it.
  function publishContext(items) {
    const app = window.HoardApp;
    if (!app || typeof app.setContext !== 'function') return;
    const summary = items.length ? 'Selected on the preview: ' + items.map((item, index) => (item.expired ? '(expired) ' : '') + `${index + 1}. ${item.tag}${item.classes[0] ? '.' + item.classes[0] : ''} "${item.text.slice(0, 40)}"${item.vsrc ? ' (' + item.vsrc + ')' : ''}`).join('; ') : '';
    // The whole card travels in `view` (the clip as its description only: its pixels stay in the preview's report).
    const cards = items.map(({clip, ...card}) => ({...card, ...(clip ? {clip: {mime: clip.mime, w: clip.w, h: clip.h, bytes: clip.bytes, omitted: clip.omitted || []}} : {})}));
    try { app.setContext(() => ({summary: summary.slice(0, 400), ...(items[0] ? {focus: items[0].selector} : {}), view: {kind: 'preview-selection', revision: revision(), selection: cards}})); } catch (_) { /* the bridge must not break selection */ }
  }
  function report() {
    paintEdits();
    const message = snapshot();
    lastRevision = message.revision;
    updatedTs = message.selection.length ? Date.now() / 1000 : null;
    publishContext(message.selection);
    post('dock/select', message);
    scheduleElements();
  }
  const isOwn = element => !element || element === layer || (element.closest && element.closest('[data-vitruvius-inspector-layer]'));
  const candidates = () => [...document.body.querySelectorAll('*')].filter(element => !isOwn(element)
    && !['script', 'style', 'link', 'meta', 'head', 'noscript', 'template'].includes(tagOf(element))
    && element.getClientRects().length && getComputedStyle(element).visibility !== 'hidden');

  function ensureLayer() {
    if (layer) return;
    layer = document.createElement('vitruvius-inspector-layer');
    layer.setAttribute('data-vitruvius-inspector-layer', '');
    layer.setAttribute('style', LAYER_STYLE);
    root = layer.attachShadow({mode: 'open'});
    root.innerHTML = `<style>
      :host{--inspection-ink:#1a2740;--inspection-blue:#3559b7;--inspection-amber:#8a5315;--inspection-paper:#fff}
      .box{position:absolute;box-sizing:border-box;pointer-events:none;background:transparent;
        border:1px solid var(--edge);box-shadow:inset 0 0 0 1px #fff}
      .hover{--edge:#526580}
      .picked{--edge:var(--inspection-blue)}
      .draft{--edge:var(--inspection-amber);border-style:dashed}
      .tag{position:absolute;box-sizing:border-box;overflow:hidden;white-space:nowrap;text-overflow:ellipsis;
        color:var(--inspection-ink);background:var(--inspection-paper);border:1px solid var(--edge);border-radius:4px;
        font:600 12px/16px system-ui,sans-serif;padding:1px 5px;pointer-events:none}
      .tag.draft{border-style:solid}
      .pin{position:absolute;pointer-events:auto;cursor:pointer;min-width:22px;height:22px;padding:0 4px;box-sizing:border-box;
        border:1px solid var(--pin);border-radius:5px;background:var(--inspection-paper);color:var(--pin);
        font:700 12px/19px system-ui,sans-serif;box-shadow:0 1px 3px #131b2b40}
      .pin.s-pending{--pin:var(--inspection-amber)}
      .pin.s-seen{--pin:var(--inspection-blue);box-shadow:inset 0 0 0 1px var(--pin),0 1px 3px #131b2b40}
      .pin.s-answered{--pin:#69469a}
      .pin.s-resolved{--pin:#266249}
      .pin.s-dismissed{--pin:#545e70}
      .pin.flash,.pin:focus-visible{outline:2px solid var(--pin);outline-offset:2px}
    </style><div id="stage" aria-hidden="true"></div><div id="pins"></div>`;
    document.documentElement.appendChild(layer);
    edits = installCanvasEdits(root, post, schedule);
    edits?.setLanguage(hostLanguage);
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

  function installCanvasEdits(root, post, redraw) {
    const meta = document.querySelector('meta[name="vitruvius-preview-revision"]');
    if (!meta) return null;
    const style = document.createElement('style');
    style.textContent = [
      '.canvas-control{pointer-events:auto;box-sizing:border-box;font:600 13px/1.35 system-ui,sans-serif}',
      '.canvas-handle{position:absolute;z-index:1;width:22px;height:22px;padding:0;display:grid;place-items:center;',
      'border:0;background:none;color:var(--inspection-blue);transform:translate(-50%,-50%);touch-action:none}',
      '.canvas-handle::before{content:"";width:6px;height:6px;border:1px solid currentColor;background:var(--inspection-paper);',
      'border-radius:1px;box-shadow:0 0 0 1px #fff;box-sizing:content-box}',
      '.canvas-handle[data-kind=padding]::before{border-radius:50%;width:5px;height:5px}',
      '.canvas-handle[data-kind=margin]::before{transform:rotate(45deg);width:5px;height:5px}',
      '.canvas-handle:focus-visible,.canvas-action:focus-visible,.canvas-text:focus-visible{outline:2px solid var(--inspection-blue);outline-offset:2px}',
      '.canvas-handle:hover::before,.canvas-handle:focus-visible::before{background:currentColor}',
      '.canvas-tip,.canvas-panel,.canvas-text{position:absolute;z-index:2;border:1px solid #9cb1d5;',
      'border-radius:6px;background:#f7f9ff;color:#182946;box-shadow:0 3px 12px #18294626}',
      '.canvas-tip{padding:4px 8px;font:600 12px/1.3 system-ui,sans-serif;pointer-events:none;max-width:calc(100vw - 16px)}',
      '.canvas-panel{width:max-content;max-width:min(310px,calc(100vw - 16px));padding:10px;',
      'display:flex;gap:8px;align-items:center;flex-wrap:wrap}',
      '.canvas-panel[hidden],.canvas-tip[hidden],.canvas-handle[hidden],.canvas-text[hidden]{display:none}',
      '.canvas-panel-message{width:100%;overflow-wrap:anywhere}',
      '.canvas-guide{position:absolute;box-sizing:border-box;pointer-events:none;color:#20458f}',
      '.canvas-guide[data-axis=x]{border-left:1px dashed currentColor} .canvas-guide[data-axis=y]{border-top:1px dashed currentColor}',
      '.canvas-action{min-height:32px;padding:4px 9px;border:1px solid #9cb1d5;border-radius:4px;color:#182946;background:#fff;font:inherit}',
      '.canvas-action[data-apply]{color:#fff;background:#20458f;border-color:#20458f}',
      '.canvas-text{padding:4px 6px;resize:none;overflow:hidden;min-height:30px}',
    ].join('');
    root.append(style);

    const names = {
      en: {
        width: 'Width', height: 'Height', margin: 'Margin', padding: 'Padding',
        top: 'top', right: 'right', bottom: 'bottom', left: 'left',
        text: 'Edit text', apply: 'Apply', cancel: 'Cancel', saving: 'Saving…',
        saved: 'Revision saved', unchanged: 'No change', missing: 'Select the element in the current preview.',
        timeout: 'The edit could not be confirmed. Check the current revision.',
        count: count => count === 1 ? 'Affects 1 element' : 'Affects ' + count + ' elements',
        pageCount: count => (count === 1 ? 'Affects 1 element' : 'Affects ' + count + ' elements') + ' on this page.',
        shared: 'This stylesheet is shared. The change can also affect other pages.',
      },
      es: {
        width: 'Ancho', height: 'Alto', margin: 'Margen', padding: 'Relleno',
        top: 'superior', right: 'derecho', bottom: 'inferior', left: 'izquierdo',
        text: 'Editar texto', apply: 'Aplicar', cancel: 'Cancelar', saving: 'Guardando…',
        saved: 'Versión guardada', unchanged: 'Sin cambios', missing: 'Selecciona el elemento en la vista previa actual.',
        timeout: 'No se ha podido confirmar la edición. Comprueba la revisión actual.',
        count: count => count === 1 ? 'Afecta a 1 elemento' : 'Afecta a ' + count + ' elementos',
        pageCount: count => (count === 1 ? 'Afecta a 1 elemento' : 'Afecta a ' + count + ' elementos') + ' en esta página.',
        shared: 'La hoja de estilos es compartida. El cambio puede afectar también a otras páginas.',
      },
    };
    let lang = document.documentElement.lang.startsWith('es') ? 'es' : 'en';
    const copy = () => names[lang];
    const stage = document.createElement('div');
    stage.dataset.canvasEdits = '';
    root.append(stage);
    const button = (className) => {
      const node = document.createElement('button');
      node.type = 'button';
      node.className = 'canvas-control ' + className;
      return node;
    };
    const directions = { top: [0, 1], right: [1, 0], bottom: [0, 1], left: [1, 0] };
    const properties = ['width', 'height', ...['margin', 'padding'].flatMap(kind =>
      Object.keys(directions).map(side => kind + '-' + side))];
    const handles = properties.map(property => {
      const [kind, side] = property.split('-');
      const node = button('canvas-handle');
      node.hidden = true;
      node.dataset.property = property;
      node.dataset.kind = kind;
      node.style.cursor = kind === 'width' || side === 'left' || side === 'right' ? 'ew-resize' : 'ns-resize';
      stage.append(node);
      return node;
    });
    const tip = document.createElement('div');
    tip.className = 'canvas-tip';
    tip.role = 'status';
    tip.hidden = true;
    const panel = document.createElement('div');
    panel.className = 'canvas-control canvas-panel';
    panel.setAttribute('role', 'group');
    panel.hidden = true;
    const message = document.createElement('div');
    message.className = 'canvas-panel-message';
    message.role = 'status';
    const scope = document.createElement('div');
    const shared = document.createElement('div');
    message.append(scope, shared);
    const applyButton = button('canvas-action');
    applyButton.dataset.apply = '';
    const cancelButton = button('canvas-action');
    panel.append(message, applyButton, cancelButton);
    const input = document.createElement('textarea');
    input.rows = 1;
    input.wrap = 'off';
    input.className = 'canvas-control canvas-text';
    input.hidden = true;
    const guide = document.createElement('div');
    guide.className = 'canvas-guide';
    guide.hidden = true;
    guide.setAttribute('aria-hidden', 'true');
    stage.append(guide, tip, panel, input);

    let selected = null;
    let scale = [];
    let scaleKey = '';
    let gesture = null;
    let editor = null;
    let confirmation = null;
    let saving = false;
    let waitingFor = null;
    let tipTimer = 0;
    const pending = new Map();
    const labels = property => property.split('-').map(word => copy()[word]).join(' ');
    const trim = value => value.replace(/^[\t\n\f\r ]+|[\t\n\f\r ]+$/g, '');
    const textNodes = element => [...element.childNodes].filter(node => node.nodeType === Node.TEXT_NODE && trim(node.data));
    const source = element => element && !element.closest('[data-vgen]') && element.getAttribute('data-vsrc');
    const position = (node, x, y) => {
      node.style.left = Math.round(x) + 'px';
      node.style.top = Math.round(y) + 'px';
    };
    const bounded = (value, extent, padding) => Math.max(padding, Math.min(value, extent - padding));

    function anchor(node, rect) {
      const width = node.offsetWidth;
      const height = node.offsetHeight;
      const x = Math.max(8, Math.min(rect.left, innerWidth - width - 8));
      const y = rect.bottom + height + 8 <= innerHeight
        ? Math.max(8, rect.bottom + 4)
        : Math.max(8, rect.top - height - 4);
      position(node, x, y);
    }

    function announce(text, rect = selected?.getBoundingClientRect(), sticky = false) {
      clearTimeout(tipTimer);
      tip.hidden = !text;
      tip.textContent = text || '';
      if (text) {
        anchor(tip, rect || { left: 8, top: 8, bottom: 8 });
        if (!sticky) tipTimer = setTimeout(() => { tip.hidden = true; }, 3300);
      }
    }

    const rootFont = () => parseFloat(getComputedStyle(document.documentElement).fontSize) || 16;

    function argumentsFor(element, change) {
      return {
        vsrc: source(element), tag: tagOf(element), expected_revision: meta.content, change,
        path: location.pathname + location.search,
        root_font_px: rootFont(),
      };
    }

    function exchange(type, args) {
      const request = crypto.randomUUID();
      return new Promise((resolve, reject) => {
        const timer = setTimeout(() => {
          pending.delete(request);
          reject(new Error(copy().timeout));
        }, 7000);
        pending.set(request, data => {
          clearTimeout(timer);
          if (data.error) reject(new Error(data.error));
          else resolve(data.result);
        });
        post(type, { request, args });
      });
    }

    function request(args, operation, expectedCount) {
      return exchange(args.change.kind === 'style' ? 'dock/commit' : 'dock/text',
        { ...args, operation, expected_count: expectedCount });
    }

    function emitGesture(current, phase) {
      post('dock/gesture', {
        vsrc: source(current.element), revision: current.revision, path: current.path,
        property: current.property, value: current.value, phase,
      });
    }

    function restoreGesture(phase = 'cancel') {
      if (!gesture) return null;
      const current = gesture;
      gesture = null;
      guide.hidden = true;
      emitGesture(current, phase);
      const { element, property, originalStyle, appliedStyle, originalValue, originalPriority } = current;
      if (appliedStyle !== undefined && element.getAttribute('style') === appliedStyle) {
        if (originalStyle === null) element.removeAttribute('style');
        else element.setAttribute('style', originalStyle);
      } else if (appliedStyle !== undefined && element.style.getPropertyValue(property) === current.value + 'px') {
        if (originalValue) element.style.setProperty(property, originalValue, originalPriority);
        else element.style.removeProperty(property);
      }
      if (current.pointer !== null && current.handle.hasPointerCapture(current.pointer)) {
        current.handle.releasePointerCapture(current.pointer);
      }
      redraw();
      return current;
    }

    function closeEditor(focus = false) {
      if (!editor) return null;
      const current = editor;
      editor = null;
      input.hidden = true;
      if (focus) handles[0].focus({ preventScroll: true });
      return current;
    }

    function closePanel(focus = true) {
      if (!confirmation) return;
      const previous = confirmation.focus;
      confirmation = null;
      panel.hidden = true;
      if (focus && previous?.isConnected && !previous.hidden) previous.focus({ preventScroll: true });
    }

    async function save(args, handle) {
      if (saving || waitingFor) return;
      saving = true;
      announce(copy().saving, undefined, true);
      try {
        const plan = await request(args, 'plan');
        if (args.expected_revision !== meta.content) throw new Error(copy().missing);
        if (plan.confirmation_required || visibleCount(args, plan) > 1) {
          ask(args, plan, handle);
        } else {
          await apply(args, undefined, handle);
        }
      } catch (error) {
        announce(error.message);
      } finally {
        saving = false;
      }
    }

    function visibleCount(args, plan) {
      if (plan.target.kind === 'class') {
        try { return Math.max(plan.affects, document.querySelectorAll(plan.target.selector).length); } catch { return plan.affects; }
      }
      return Math.max(plan.affects, [...document.querySelectorAll('[data-vsrc]')].filter(node => source(node) === args.vsrc).length);
    }

    function ask(args, plan, focus) {
      announce('');
      confirmation = { args, count: plan.affects, focus };
      const count = visibleCount(args, plan);
      scope.textContent = plan.affects_scope === 'page' ? copy().pageCount(count) : copy().count(count);
      shared.textContent = plan.shared_stylesheet ? copy().shared : '';
      panel.setAttribute('aria-label', scope.textContent);
      applyButton.textContent = copy().apply;
      cancelButton.textContent = copy().cancel;
      panel.hidden = false;
      const rect = selected?.getBoundingClientRect() || { left: 8, top: 8, bottom: 8 };
      anchor(panel, rect);
      applyButton.focus({ preventScroll: true });
    }

    async function apply(args, count, focus) {
      const result = await request(args, 'apply', count);
      if (result.confirmation_required) {
        ask(args, result, focus);
        return;
      }
      if (result.changed) {
        // The host's revision stream owns rendering the new revision.
        if (meta.content === args.expected_revision) waitingFor = result.revision;
        announce(copy().saved);
      } else {
        announce(copy().unchanged);
      }
    }

    applyButton.addEventListener('click', async () => {
      if (!confirmation || saving) return;
      const { args, count, focus } = confirmation;
      closePanel();
      saving = true;
      announce(copy().saving, undefined, true);
      try {
        await apply(args, count, focus);
      } catch (error) {
        announce(error.message);
      } finally {
        saving = false;
      }
    });
    cancelButton.addEventListener('click', () => closePanel());
    panel.addEventListener('keydown', event => {
      if (event.key === 'Escape') { event.preventDefault(); closePanel(); }
    });

    function locateHandles(element) {
      const rect = element.getBoundingClientRect();
      if (rect.width === 0 || rect.height === 0 || rect.bottom < 0 || rect.top > innerHeight
        || rect.right < 0 || rect.left > innerWidth) return false;
      const computed = getComputedStyle(element);
      for (const handle of handles) {
        const { property, kind } = handle.dataset;
        const side = property.split('-')[1];
        let x = rect.left + rect.width / 2;
        let y = rect.top + rect.height / 2;
        if (kind === 'width') x = rect.right;
        else if (kind === 'height') y = rect.bottom;
        else {
          const horizontal = side === 'left' || side === 'right';
          const near = side === 'top' || side === 'left';
          const axis = horizontal ? rect.width : rect.height;
          const spacing = Math.abs(parseFloat(computed.getPropertyValue(property)) || 0);
          // Centre the visible padding marker in its band. With little or no padding,
          // place it beyond the element; a clipped handle can still pass double-clicks through.
          const gap = kind === 'padding'
            ? (spacing >= 12 && axis >= 24 ? -Math.min(axis / 2, spacing / 2, 26) : 28)
            : Math.max(12, Math.min(26, spacing));
          const fraction = kind === 'padding' ? .72 : .28;
          x = horizontal ? (near ? rect.left - gap : rect.right + gap) : rect.left + rect.width * fraction;
          y = horizontal ? rect.top + rect.height * fraction : (near ? rect.top - gap : rect.bottom + gap);
        }
        handle.hidden = false;
        position(handle, bounded(x, innerWidth, 11), bounded(y, innerHeight, 11));
        const label = labels(property);
        handle.setAttribute('aria-label', label);
        handle.title = label;
      }
      return true;
    }

    const observer = new ResizeObserver(redraw);
    function paint(element) {
      const next = source(element) && element.isConnected ? element : null;
      if (next !== selected) {
        observer.disconnect();
        restoreGesture();
        closeEditor();
        closePanel(false);
        selected = next;
        if (next) observer.observe(next);
      }
      if (waitingFor && waitingFor === meta.content) waitingFor = null;
      if (!next || !locateHandles(next)) {
        for (const handle of handles) handle.hidden = true;
        return;
      }
      if (confirmation) anchor(panel, next.getBoundingClientRect());
      const path = pageId();
      const rootFontPx = rootFont();
      const key = [meta.content, path, rootFontPx].join('|');
      if (key !== scaleKey) {
        scale = [];
        scaleKey = key;
        exchange('dock/edit-scale', { revision: meta.content, path, root_font_px: rootFontPx })
          .then(result => { if (scaleKey === key) scale = result.scale; }).catch(() => {});
      }
    }

    function begin(handle, element, pointer) {
      if (!element || !source(element) || saving || confirmation || editor || waitingFor) return null;
      restoreGesture();
      const { property } = handle.dataset;
      const computed = getComputedStyle(element).getPropertyValue(property);
      const size = (property === 'width' ? element.offsetWidth : element.offsetHeight) || 0;
      const base = parseFloat(computed);
      const start = Number.isFinite(base) ? base : property === 'width' || property === 'height' ? size : 0;
      gesture = {
        element, handle, pointer, property, start, value: start,
        revision: meta.content, path: location.pathname + location.search,
        originalStyle: element.getAttribute('style'),
        originalValue: element.style.getPropertyValue(property),
        originalPriority: element.style.getPropertyPriority(property),
      };
      emitGesture(gesture, 'start');
      return gesture;
    }

    function drawGuide(property, rect, pixels) {
      const [kind, side] = property.split('-');
      const horizontal = kind === 'width' || side === 'left' || side === 'right';
      const near = side === 'top' || side === 'left';
      const inset = kind === 'margin' ? -pixels : kind === 'padding' ? pixels : 0;
      const along = horizontal ? (near ? rect.left + inset : rect.right - inset)
        : (near ? rect.top + inset : rect.bottom - inset);
      guide.dataset.axis = horizontal ? 'x' : 'y';
      position(guide, horizontal ? along : rect.left, horizontal ? rect.top : along);
      guide.style.width = (horizontal ? 0 : rect.width) + 'px';
      guide.style.height = (horizontal ? rect.height : 0) + 'px';
      guide.hidden = false;
    }

    function feedback(current, pixels, snap) {
      const minimum = current.property.startsWith('margin-') ? -100000 : 0;
      const value = Math.min(100000, Math.max(minimum, pixels));
      const nearby = snap ? scale.filter(token => token.pixels >= minimum && Math.abs(token.pixels - value) <= 3)
        .reduce((best, token) => !best || Math.abs(token.pixels - value) < Math.abs(best.pixels - value) ? token : best, null) : null;
      current.value = nearby ? nearby.pixels : Math.round(value * 10000) / 10000;
      current.element.style.setProperty(current.property, current.value + 'px', 'important');
      current.appliedStyle = current.element.getAttribute('style');
      redraw();
      emitGesture(current, 'move');
      const rect = current.element.getBoundingClientRect();
      if (nearby) drawGuide(current.property, rect, current.value);
      else guide.hidden = true;
      const text = labels(current.property) + ' ' + current.value + ' px' + (nearby ? ' · ' + nearby.name : '');
      announce(text, rect, true);
    }

    function complete() {
      const current = restoreGesture('end');
      announce('');
      if (!current || current.start === current.value) return;
      if (current.revision !== meta.content || current.path !== location.pathname + location.search || !current.element.isConnected) {
        announce(copy().missing);
        return;
      }
      void save(argumentsFor(current.element, { kind: 'style', property: current.property, pixels: current.value }), current.handle);
    }

    for (const handle of handles) {
      handle.addEventListener('pointerdown', event => {
        if (event.button !== 0 || !begin(handle, selected, event.pointerId)) return;
        event.preventDefault();
        handle.focus({ preventScroll: true });
        handle.setPointerCapture(event.pointerId);
        gesture.x = event.clientX;
        gesture.y = event.clientY;
      });
      handle.addEventListener('pointermove', event => {
        if (gesture?.pointer !== event.pointerId) return;
        const [kind, side] = gesture.property.split('-');
        const [horizontal] = directions[side] || [kind === 'width' ? 1 : 0];
        const delta = horizontal ? event.clientX - gesture.x : event.clientY - gesture.y;
        const near = side === 'left' || side === 'top';
        const sign = (kind === 'margin' && near) || (kind === 'padding' && !near) ? -1 : 1;
        if (delta || gesture.appliedStyle !== undefined) feedback(gesture, gesture.start + delta * sign, !event.altKey);
      });
      handle.addEventListener('pointerup', event => { if (gesture?.pointer === event.pointerId) complete(); });
      const lost = event => {
        if (gesture?.pointer === event.pointerId) { restoreGesture(); announce(''); }
      };
      handle.addEventListener('pointercancel', lost);
      handle.addEventListener('lostpointercapture', lost);
      handle.addEventListener('keydown', event => {
        const horizontal = ['width', 'margin-left', 'margin-right', 'padding-left', 'padding-right'].includes(handle.dataset.property);
        const grow = horizontal ? 'ArrowRight' : 'ArrowDown';
        const shrink = horizontal ? 'ArrowLeft' : 'ArrowUp';
        if (event.key === grow || event.key === shrink) {
          event.preventDefault();
          const current = gesture?.handle === handle ? gesture : begin(handle, selected, null);
          if (current && current.pointer === null) feedback(current, current.value + (event.key === grow ? 1 : -1) * (event.shiftKey ? 10 : 1), false);
        } else if (gesture?.handle === handle && event.key === 'Enter') {
          event.preventDefault();
          complete();
        } else if (gesture?.handle === handle && event.key === 'Escape') {
          event.preventDefault();
          restoreGesture(); announce('');
        }
      });
      handle.addEventListener('blur', () => {
        if (gesture?.handle === handle && gesture.pointer === null) { restoreGesture(); announce(''); }
      });
    }

    async function editNode(node) {
      const element = node?.parentElement;
      if (!source(element) || saving || confirmation || waitingFor || editor) return false;
      const index = textNodes(element).indexOf(node);
      if (index < 0) return false;
      const original = trim(node.data);
      const args = argumentsFor(element, { kind: 'text', original, value: original, index });
      saving = true;
      try {
        await request(args, 'plan');
        if (!node.isConnected || args.expected_revision !== meta.content) throw new Error(copy().missing);
        const range = document.createRange();
        range.selectNodeContents(node);
        const rect = range.getBoundingClientRect();
        const computed = getComputedStyle(element);
        editor = { args, rect };
        input.value = original;
        input.setAttribute('aria-label', copy().text);
        input.style.fontSize = computed.fontSize;
        input.style.fontFamily = computed.fontFamily;
        input.style.fontWeight = computed.fontWeight;
        input.style.width = Math.min(innerWidth - 16, Math.max(rect.width + 16, 172)) + 'px';
        input.style.height = Math.max(30, (parseFloat(computed.fontSize) || 16) * 1.35 + 10) + 'px';
        input.hidden = false;
        sizeEditor();
        input.focus({ preventScroll: true });
        input.select();
      } catch (error) {
        announce(error.message, element.getBoundingClientRect());
      } finally {
        saving = false;
      }
      return true;
    }

    function sizeEditor() {
      if (!editor) return;
      const width = Math.min(innerWidth - 16, Math.max(input.offsetWidth, input.scrollWidth + 2));
      input.style.width = width + 'px';
      const { rect } = editor;
      position(input, Math.max(8, Math.min(rect.left, innerWidth - width - 8)),
        Math.max(0, Math.min(rect.top - 4, innerHeight - input.offsetHeight - 8)));
    }

    input.addEventListener('input', sizeEditor);
    input.addEventListener('keydown', event => {
      if (event.isComposing || !editor) return;
      if (event.key === 'Escape') { event.preventDefault(); closeEditor(true); }
      else if (event.key === 'Enter') {
        event.preventDefault();
        const { args } = closeEditor(true);
        const value = trim(input.value);
        if (value !== args.change.original) void save({ ...args, change: { ...args.change, value } }, handles[0]);
      }
    });
    input.addEventListener('blur', () => closeEditor());
    new MutationObserver(() => {
      const interrupted = gesture || editor || confirmation;
      restoreGesture(); closeEditor(); closePanel(false); waitingFor = null; redraw();
      if (interrupted) announce(copy().missing);
    }).observe(meta, { attributes: true, attributeFilter: ['content'] });

    function literalAt(event, throughHandle) {
      if (throughHandle) stage.style.visibility = 'hidden';
      try {
        const caret = document.caretPositionFromPoint?.(event.clientX, event.clientY);
        return caret?.offsetNode || document.caretRangeFromPoint?.(event.clientX, event.clientY)?.startContainer;
      } finally {
        if (throughHandle) stage.style.removeProperty('visibility');
      }
    }

    return {
      paint,
      hit: event => event.composedPath().includes(stage),
      hitHandle: event => event.composedPath().some(node => node.classList?.contains('canvas-handle')),
      editing: () => Boolean(gesture || editor || confirmation),
      cancel: () => { restoreGesture(); closeEditor(); closePanel(false); },
      focus: () => handles.find(handle => !handle.hidden)?.focus({ preventScroll: true }),
      doubleClick: (event, throughHandle) => {
        const node = literalAt(event, throughHandle);
        if (!node || node.nodeType !== Node.TEXT_NODE || !source(node.parentElement) || !trim(node.data)) return null;
        // Only edit the actual run of text the pointer hit, not the nearest line in a paragraph.
        const range = document.createRange();
        range.selectNodeContents(node);
        if (![...range.getClientRects()].some(rect => event.clientX >= rect.left && event.clientX <= rect.right
          && event.clientY >= rect.top && event.clientY <= rect.bottom)) return null;
        void editNode(node);
        return node.parentElement;
      },
      setLanguage: value => { if (value) { lang = value === 'es' ? 'es' : 'en'; redraw(); } },
      message: data => {
        if (data.type === 'inspect/canvas-edit-result' && pending.has(data.request)) {
          const callback = pending.get(data.request);
          pending.delete(data.request);
          callback(data);
        }
      },
    };
  }

  function paintEdits() {
    edits?.paint(mode && selected.length === 1 ? selected[0] : null);
  }

  function drawOutline(drawings, element, kind, number) {
    const r = element.getBoundingClientRect();
    if (!r.width || !r.height || r.right <= 0 || r.bottom <= 0 || r.left >= innerWidth || r.top >= innerHeight) return;

    const box = document.createElement('div');
    box.className = `box ${kind}`;
    box.setAttribute('aria-hidden', 'true');
    Object.assign(box.style, {left: r.left + 'px', top: r.top + 'px', width: r.width + 'px', height: r.height + 'px'});

    const name = compact(attrOf(element, 'aria-label'));
    const id = attrOf(element, 'id');
    const firstClass = element.classList?.[0];
    const label = name || (tagOf(element) + (id ? '#' + id : firstClass ? '.' + firstClass : ''));
    const tag = document.createElement('div');
    tag.className = `tag ${kind}`;
    tag.setAttribute('aria-hidden', 'true');
    tag.dir = 'auto';
    tag.textContent = number ? `${number} · ${label}` : label;
    const left = Math.max(4, Math.min(r.left, innerWidth - 112));
    const top = Math.max(4, Math.min(r.top >= 25 ? r.top - 23 : r.top + 4, innerHeight - 24));
    Object.assign(tag.style, {left: left + 'px', top: top + 'px', maxWidth: Math.min(220, innerWidth - left - 4) + 'px'});
    drawings.append(box, tag);
  }

  const commentLabels = {
    en: {comment: 'Comment', pending: 'pending', seen: 'seen', answered: 'answered', resolved: 'resolved', dismissed: 'dismissed'},
    es: {comment: 'Comentario', pending: 'pendiente', seen: 'visto', answered: 'respondido', resolved: 'resuelto', dismissed: 'descartado'},
  };
  function paint() {
    frame = 0;
    if (!layer) return;
    const stage = root.getElementById('stage');
    const pinLayer = root.getElementById('pins');
    const stalePins = new Map([...pinLayer.children].map(button => [button.dataset.pin, button]));
    const drawings = document.createDocumentFragment();
    if (active() && hovered?.isConnected && hovered !== draft && !selected.includes(hovered)) drawOutline(drawings, hovered, 'hover');
    selected.forEach((element, index) => {
      if (element !== draft && element.isConnected) drawOutline(drawings, element, 'picked', selected.length > 1 ? index + 1 : 0);
    });
    if (draft?.isConnected) drawOutline(drawings, draft, 'draft');

    const anchors = []; const slots = new Map(); const now = revision();
    const labels = hostLanguage === 'es' ? commentLabels.es : commentLabels.en;
    for (const pin of pins) {
      const found = locatePin(pin, all, now);
      if (found.state === 'lost') { anchors.push({id: pin.id, state: 'lost'}); continue; }
      const r = found.element.getBoundingClientRect();
      const slot = slots.get(found.element) || 0; slots.set(found.element, slot + 1);
      anchors.push({id: pin.id, state: 'ok', vsrc: attrOf(found.element, 'data-vsrc') || null,
        box: {x: Math.round(r.left + window.scrollX), y: Math.round(r.top + window.scrollY), w: Math.round(r.width), h: Math.round(r.height)}});
      if (!r.width && !r.height) continue;

      let button = stalePins.get(pin.id);
      if (button) {
        stalePins.delete(pin.id);
      } else {
        button = document.createElement('button');
        button.type = 'button';
        button.dataset.pin = pin.id;
        pinLayer.append(button);
      }
      button.className = `pin s-${pin.status}${flash === pin.id ? ' flash' : ''}`;
      button.style.left = Math.max(0, Math.min(r.right, innerWidth - 18) - 12 - slot * 26) + 'px';
      button.style.top = Math.max(0, r.top - 10) + 'px';
      button.setAttribute('aria-label', `${labels.comment} ${pin.n} · ${labels[pin.status]}`);
      const glyph = {resolved: '\u2713', answered: '?', dismissed: '\u00d7'}[pin.status] || '';
      button.textContent = `${pin.n}${glyph}`;
    }
    for (const button of stalePins.values()) button.remove();
    stage.replaceChildren(drawings);
    const key = JSON.stringify([now, anchors.map(a => [a.id, a.state, a.vsrc || ''])]);
    if (pins.length && key !== anchorKey) { anchorKey = key; post('dock/comment-anchors', {page: pageId(), revision: now, session: sessionId(), anchors}); }
    paintEdits();
  }
  const schedule = () => { if (!frame) frame = requestAnimationFrame(paint); };
  // After a change of the served revision, or when the page replaced a selected element, each chosen element is matched
  // again against what it was when chosen. One that is no longer the same element is kept in the list as expired.
  function settle() {
    const next = []; const lost = [];
    for (const element of selected) {
      const identity = picked.get(element);
      const found = identity ? reconcile(identity, all) : (element.isConnected ? element : null);
      if (found && !next.includes(found)) {
        next.push(found);
        if (found !== element || (identity && revision() !== identity.revision)) picked.set(found, {...describeElement(found, env), revision: revision()});
      } else if (identity) lost.push({...identity, expired: true});
    }
    selected = next; expired = [...expired, ...lost].slice(-MAX_SELECTION); schedule(); report();
  }
  const all = selector => [...document.querySelectorAll(selector)];
  const layerSelector = 'header,main,footer,nav,aside,section,article,h1,h2,h3,h4,h5,h6,p,ul,ol,table,form,label,button,a,input,select,textarea,img,svg,video,canvas,[role],[data-vsrc],[data-vgen]';
  const layerIds = new WeakMap();
  let nextLayerId = 0, listedElements = new Map(), listFrame = 0, listKey = '', listRequested = false;

  function publishElements() {
    listFrame = 0;
    const elements = [...document.body.querySelectorAll(layerSelector)].filter(element =>
      !isOwn(element) && element.getClientRects().length && getComputedStyle(element).visibility === 'visible'
      && !element.matches('input[type=hidden]'));
    const limit = 200;
    const rows = [], depths = new Map();
    listedElements = new Map();
    for (const element of elements.slice(0, limit)) {
      if (!layerIds.has(element)) layerIds.set(element, ++nextLayerId);
      const id = layerIds.get(element);
      let parent = element.parentElement;
      while (parent && !depths.has(parent)) parent = parent.parentElement;
      const depth = parent ? depths.get(parent) + 1 : 0;
      depths.set(element, depth);
      listedElements.set(id, element);
      const label = element.getAttribute('aria-label') || element.getAttribute('alt') ||
        element.getAttribute('placeholder') || element.getAttribute('title');
      const hasText = element.matches('a,button,p,label,h1,h2,h3,h4,h5,h6,[role="button"]') || !element.children.length;
      const text = label || (hasText && compact(element.textContent)) || element.id;
      rows.push({id, tag: tagOf(element), text: compact(text || '').slice(0, 96), depth,
        selected: selected.includes(element)});
    }
    const payload = {page: pageId(), revision: revision(), items: rows, total: elements.length};
    const key = JSON.stringify(payload);
    if (key !== listKey) { listKey = key; post('dock/elements', payload); }
  }

  function scheduleElements() {
    if (listRequested && !listFrame) listFrame = setTimeout(publishElements, 100);
  }
  // A layer the page removed is put back. A change of the served revision (a live refresh patches the page in place)
  // or a selected element that left the document settles the selection.
  new MutationObserver(() => {
    if (layer && !layer.isConnected) document.documentElement.appendChild(layer);
    if ((selected.length || pins.length || draft) && !watcher) watcher = requestAnimationFrame(() => {
      watcher = 0;
      if (draft && !draft.isConnected) draft = null;
      if (selected.length && (selected.some(element => !element.isConnected) || revision() !== lastRevision)) settle();
      if (pins.length || draft) schedule();
    });
  }).observe(document.documentElement, {childList: true, subtree: true, attributes: true, attributeFilter: ['content']});
  new MutationObserver(scheduleElements).observe(document.documentElement, {
    childList: true, characterData: true, subtree: true, attributes: true,
    attributeFilter: ['content', 'class', 'style', 'hidden', 'aria-label', 'alt', 'title', 'id', 'open'],
  });

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
  function updateHover(element) {
    if (element !== hovered) { hovered = element; focusIndex = -1; schedule(); }
  }
  function onMove(event) {
    if (!active()) return;
    updateHover((mode && edits?.hit(event)) || pinOf(event) ? null : elementAt(event));
  }
  const pinOf = event => { const path = event.composedPath ? event.composedPath() : []; const pin = path.find(node => node && node.dataset && node.dataset.pin); return pin ? pin.dataset.pin : null; };
  // The crop is the clip the selection already makes (captureClip); a page that cannot draw it gives none, and the comment is kept anyway.
  async function pickForComment(element) {
    draft = element; hovered = null; schedule();
    const item = {...describeElement(element, env), revision: revision()};
    let clip = null;
    try { clip = await captureClip(element); } catch (_) { clip = null; }
    if (draft === element) post('dock/comment-target', {page: pageId(), revision: item.revision, element: item, crop: clip ? clip.data_url : null, attrs: identityAttrs(element)});
  }
  function onClick(event) {
    const pin = pinOf(event);
    if (pin) { swallow(event); post('dock/comment-focus', {page: pageId(), revision: revision(), id: pin}); return; }
    if (!active() || (mode && edits?.hit(event))) return;
    swallow(event);
    if (commenting) { const target = elementAt(event); if (target) pickForComment(target); return; }
    if (event.detail <= 1) choose(elementAt(event), event.shiftKey);
  }
  function onBlock(event) {
    if (!active() || pinOf(event)) return;
    if (commenting) { event.preventDefault(); event.stopPropagation(); return; }
    const hitOverlay = edits?.hit(event);
    if (event.type === 'dblclick' && (!hitOverlay || edits.hitHandle(event))) {
      const element = edits?.doubleClick(event, hitOverlay);
      if (element) { selected = [element]; schedule(); report(); swallow(event); return; }
    }
    if (hitOverlay) return;
    event.preventDefault();
    event.stopPropagation();
  }
  function onKey(event) {
    if (event.altKey && event.shiftKey && event.code === 'KeyS') { event.preventDefault(); setMode(!mode); return; }
    if (event.altKey && event.shiftKey && event.code === 'KeyC') { event.preventDefault(); setMode(!commenting, 'comment'); return; }
    if (!active() || (mode && edits?.hit(event) && (event.key !== 'Escape' || edits.editing()))) return;
    if (mode && event.altKey && event.key === 'Enter' && selected.length === 1 && edits) {
      swallow(event); edits.focus(); return;
    }
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
    if (!mode) edits?.cancel();
    if (!commenting) draft = null;
    setCursor(active());
    schedule(); report();
  }

  // A new document (a reload, or the frame replaced after an edit of the layout) gets the selection back: every item is
  // matched against what it was when chosen, and one that no longer identifies an element is reported as expired.
  function restore(items) {
    const found = []; const lost = [];
    for (const item of Array.isArray(items) ? items.slice(0, MAX_SELECTION) : []) {
      if (!item || typeof item !== 'object') continue;
      const element = item.expired ? null : reconcile(item, all);
      if (element && !found.includes(element)) { found.push(element); picked.set(element, {...describeElement(element, env), revision: revision()}); }
      else if (!element) lost.push({tag: item.tag, text: item.text, selector: item.selector, vsrc: item.vsrc || null, own_vsrc: Boolean(item.own_vsrc), index: item.index, parent: item.parent, anchor: item.anchor && typeof item.anchor === 'object' ? item.anchor : {}, revision: item.revision || null, classes: Array.isArray(item.classes) ? item.classes : [], html: '', box: item.box || {x: 0, y: 0, w: 0, h: 0}, computed: {}, same_vsrc_count: 0, vgen: item.vgen || null, expired: true});
    }
    selected = found; expired = lost; ensureLayer(); schedule(); report();
  }

  window.addEventListener('message', event => {
    const accepted = gate(hostOrigin, event, window.parent);
    if (accepted === null) return;
    hostOrigin = accepted;
    const data = event.data;
    edits?.message(data);
    if (data.type === 'inspect/edits-config') {
      hostLanguage = data.lang;
      edits?.setLanguage(hostLanguage);
    } else if (data.type === 'inspect/hello') { const message = snapshot(); lastRevision = message.revision; publishContext(message.selection); post('dock/inspector-ready', message); }
    else if (data.type === 'inspect/read-selection' && typeof data.id === 'string') {
      if (selected.length && (revision() !== lastRevision || selected.some(element => !element.isConnected))) settle();
      const { selection, revision: servedRevision } = snapshot();
      post('dock/result', { id: data.id, ok: true, result: { selection, revision: servedRevision, updated_ts: updatedTs } });
    }
    else if (data.type === 'inspect/mode') setMode(data.on, data.kind === 'comment' ? 'comment' : 'select');
    else if (data.type === 'inspect/elements') {
      listRequested = true; listKey = ''; scheduleElements();
    } else if (data.type === 'inspect/element-select' && data.page === pageId() && data.revision === revision()) {
      const element = listedElements.get(data.id);
      if (element?.isConnected && element.getClientRects().length) {
        if (!mode) setMode(true);
        choose(element, data.additive === true);
        if (selected.includes(element)) element.scrollIntoView?.({block: 'nearest', behavior: reduced() ? 'auto' : 'smooth'});
      } else scheduleElements();
    } else if (data.type === 'inspect/pins') {
      const states = ['pending', 'seen', 'answered', 'resolved', 'dismissed']; const text = value => (typeof value === 'string' ? value : '');
      pins = (Array.isArray(data.pins) ? data.pins : []).slice(0, MAX_PINS).filter(pin => pin && typeof pin.id === 'string' && Number.isInteger(pin.n))
        .map(pin => ({id: pin.id, n: pin.n, status: states.includes(pin.status) ? pin.status : 'pending', selector: text(pin.selector), vsrc: text(pin.vsrc),
          own_vsrc: pin.own_vsrc === true, tag: text(pin.tag), text: text(pin.text), revision: text(pin.revision),
          attrs: pin.attrs && typeof pin.attrs === 'object' ? Object.fromEntries(IDENTITY_ATTRS.filter(name => typeof pin.attrs[name] === 'string').map(name => [name, pin.attrs[name]])) : {},
          parent: typeof pin.parent === 'string' ? pin.parent : undefined, index: Number.isInteger(pin.index) ? pin.index : 0}));
      ensureLayer(); anchorKey = ''; schedule();
    }
    else if (data.type === 'inspect/draft-clear') { draft = null; schedule(); }
    else if (data.type === 'inspect/pin-navigate' && typeof data.page === 'string' && data.page.startsWith('/')) {
      const target = new URL(data.page, location.origin);
      if (target.origin === location.origin && target.pathname + target.search !== pageId()) location.assign(target.href);
    } else if (data.type === 'inspect/pin-focus') {
      const pin = pins.find(entry => entry.id === data.id);
      const found = pin && locatePin(pin, all, revision());
      post('dock/comment-jump', {id: data.id, found: Boolean(found?.element)});
      if (found && found.element) { found.element.scrollIntoView?.({block: 'center', behavior: reduced() ? 'auto' : 'smooth'}); flash = pin.id; clearTimeout(flashTimer); flashTimer = setTimeout(() => { flash = ''; schedule(); }, 1600); schedule(); }
    }
    else if (data.type === 'inspect/clear') { selected = []; expired = []; schedule(); report(); }
    else if (data.type === 'inspect/dismiss') { const at = Number(data.index); if (Number.isInteger(at) && at >= 0 && at < expired.length) { expired.splice(at, 1); report(); } }
    else if (data.type === 'inspect/remove') { const at = Number(data.index); if (Number.isInteger(at) && at >= 0 && at < selected.length) { selected.splice(at, 1); schedule(); report(); } }
    else if (data.type === 'inspect/restore') restore(data.items);
  });
  document.addEventListener('mousemove', onMove, true);
  document.addEventListener('mouseout', event => { if (!event.relatedTarget) updateHover(null); }, true);
  window.addEventListener('blur', () => updateHover(null));
  document.addEventListener('click', onClick, true);
  for (const type of ['mousedown', 'mouseup', 'pointerdown', 'pointerup', 'submit', 'dblclick', 'auxclick', 'contextmenu']) document.addEventListener(type, onBlock, true);
  document.addEventListener('keydown', onKey, true);
  window.addEventListener('scroll', schedule, true);
  window.addEventListener('resize', () => { schedule(); scheduleElements(); });
  window.__vitruviusInspector = {version: 1, core};
  try { const ancestor = location.ancestorOrigins && location.ancestorOrigins[0]; if (ancestor) { hostOrigin = ancestor; post('dock/inspector-ready', snapshot()); } } catch (_) { /* the host will say hello */ }
})();
