// Vitruvius preview inspector. Loaded only into the owned preview of an application project (never into an export).
// A person turns "select" mode on; hovering outlines the element under the pointer, a click selects it, Shift+click
// adds or removes one, Esc leaves the mode. Every change posts the whole selection to the host page (the frame
// parent) as {hoardDock: 1, type: 'dock/select', selection, mode}. Plain script: no build step, no dependencies.
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

  // Who may talk to the inspector: only the frame's parent window, from the origin fixed at the start (the browser's
  // ancestor origin, or else the origin of the first hello). Returns the origin to keep, or null to ignore the message.
  function gate(known, event, parentWindow) {
    const data = event && event.data;
    if (!event || event.source !== parentWindow || !data || data.hoardDock !== 1 || typeof data.type !== 'string' || !data.type.startsWith('inspect/')) return null;
    if (known === null) return data.type === 'inspect/hello' ? event.origin : null;
    return event.origin === known ? known : null;
  }

  const core = {selectorFor, describeElement, reconcile, relationOf, anchorOf, textOf, gate, escapeCss, compact, COMPUTED, MAX_TEXT, MAX_SELECTION};
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
  let selected = []; // elements, in the order they were chosen
  let hovered = null;
  let focusIndex = -1;
  const picked = new Map(); // element -> what it was when chosen (tag, text, position, place), so another revision can be matched
  const clips = new WeakMap(); // element -> data URL of its clip, or false when none could be made
  let expired = []; // chosen elements that are no longer the same element on the revision now served
  let lastRevision;
  let cursorSheet;
  let layer; let root; let frame = 0; let watcher = 0;

  const post = (type, fields = {}) => { if (hostOrigin !== null) window.parent.postMessage({hoardDock: 1, type, ...fields}, hostOrigin); };
  const pageId = () => location.pathname + location.search;
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
  const snapshot = () => ({mode, page: pageId(), revision: revision(), selection: [...selected.map(describe), ...expired]});
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
    const leaveOut = (original, target, why) => {
      omitted.push(`${tagOf(original)} ${(original.currentSrc || original.getAttribute('src') || '').slice(0, 80)}: ${why}`.trim());
      const box = original.getBoundingClientRect();
      const hole = document.createElement('span');
      hole.setAttribute('style', `display:inline-block;width:${Math.round(box.width)}px;height:${Math.round(box.height)}px`);
      if (target !== clone) target.replaceWith(hole);
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
          if (target !== clone) target.replaceWith(picture);
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
    const markup = new XMLSerializer().serializeToString(clone);
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
  // A layer the page removed is put back. A change of the served revision (a live refresh patches the page in place)
  // or a selected element that left the document settles the selection.
  new MutationObserver(() => {
    if (layer && !layer.isConnected) document.documentElement.appendChild(layer);
    if (selected.length && !watcher) watcher = requestAnimationFrame(() => {
      watcher = 0;
      if (selected.some(element => !element.isConnected) || revision() !== lastRevision) settle();
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
    setCursor(mode);
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
    if (data.type === 'inspect/hello') { const message = snapshot(); lastRevision = message.revision; publishContext(message.selection); post('dock/inspector-ready', message); }
    else if (data.type === 'inspect/mode') setMode(data.on);
    else if (data.type === 'inspect/clear') { selected = []; expired = []; schedule(); report(); }
    else if (data.type === 'inspect/dismiss') { const at = Number(data.index); if (Number.isInteger(at) && at >= 0 && at < expired.length) { expired.splice(at, 1); report(); } }
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
