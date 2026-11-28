"""The Faustus copilot launcher every Hoard page can load: ``/api/copilot/launcher.js`` (see ``copilot.install_copilot``).

Plain browser JavaScript, no framework and no build: a floating «Faustus» button and a side panel with the shared
``<faustus-chat>`` element that Faustus serves (``/api/copilot/panel.js``). Every request of the panel goes through the
app's own relay (``/api/copilot/proxy``), so tokens never reach the page.

What the panel learns about the page (``contextProvider``): the app (``origin``), the view (path, title, first heading,
language), the text selected, and the objects open in the view, guessed from the route: pairs ``/<kind>/<id>`` where the
id looks like an id (digits, a ULID, a UUID); ``new`` is never an object. An app adds or overrides any of it by defining
``window.hoardCopilot = { context: async () => ({ project, active_objects, ... }), onTurnEnd() {...} }``; returning
``active_objects: []`` drops the guesses from the URL.

Where the button sits: bottom right by default; an app whose own controls live there moves it with the CSS variables
``--hoard-copilot-bottom`` / ``--hoard-copilot-right`` (or ``--hoard-copilot-left`` with
``<html data-hoard-copilot-position="left">``). The panel opens under the app's own top bar (a fixed or sticky bar, or a
``header``/``nav``/``role=banner`` starting in the first 64 px); ``--hoard-copilot-top`` on ``:root`` overrides it.
Escape closes the panel, except inside an app dialog.

Apps with strict defences work without exceptions of their own: the styles are a constructed stylesheet (allowed by
``style-src 'self'``), the requests to ``/api/copilot/info`` and ``/proxy`` carry ``X-Hoard-Request: 1`` and the page
cookies, and the launcher script itself needs no session (``COPILOT_PUBLIC_PATHS`` in ``copilot.py`` lists what a
session guard should let through).

Keys typed in the panel stay in the panel (the app's shortcuts never see them). The conversation is kept per data space
(localStorage, best effort; the route of each turn travels in the context) and, when the app's context names a project
(``project.external_project_id`` / ``id``), per project: switching project in the app shows that project's conversation
(or a fresh one) instead of mixing two projects in one thread. The launcher checks on every navigation, when the panel
opens, when the page dispatches ``hoard:copilot-context-changed`` and, last, right before each turn. When a turn ends
the page gets ``hoard:copilot-turn-end`` and ``onTurnEnd``.
"""

import json

FAUSTUS_BRAND = "#e06c75"
FAUSTUS_MARK_SVG = ('<svg viewBox="0 0 32 32" width="28" height="28" aria-hidden="true">'
    '<path fill="currentColor" d="M16 0.738L4.674 25.559L13.004 28.992L13.004 24.798L9.229 24.798L9.229 19.644L16 12.094L22.772 19.644L22.772 24.798L17.678 24.798L13.4 31.264L27.326 25.559Z"/>'
    '<g fill="currentColor" opacity="0.62">'
    '<path d="M5.993 5.022L0.839 13.292L6.233 18.985L9.049 13.172L4.555 11.434Z"/>'
    '<path d="M26.008 5.022L31.161 13.292L25.768 18.985L22.952 13.172L27.446 11.434Z"/>'
    '</g></svg>')

LAUNCHER_JS = r"""
(() => {
  if (window.__hoardCopilotLauncher) return;
  window.__hoardCopilotLauncher = true;
  const ID_RE = /^(?:\d+|[0-9A-HJKMNP-TV-Z]{26}|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|[A-Za-z]+_[0-9A-Za-z]{8,}|[0-9a-f]{12,})$/;
  const SKIP = new Set(['new', 'edit', 'create', 'add', 'api', 'static', 'assets']);
  const store = {
    get(key) { try { return localStorage.getItem(key); } catch { return null; } },
    set(key, value) { try { value ? localStorage.setItem(key, value) : localStorage.removeItem(key); } catch { /* private mode */ } },
  };
  const lang = () => (document.documentElement.lang || navigator.language || 'en').slice(0, 2).toLowerCase();
  const routeOf = () => (location.hash && location.hash.length > 1 ? location.hash.slice(1) : location.pathname) || '/';

  function guessObjects(route) {
    const parts = route.split('?')[0].split('/').filter(Boolean).map(decodeURIComponent);
    const found = [];
    for (let i = 0; i < parts.length; i += 1) {
      const id = parts[i + 1];
      if (!id || SKIP.has(id.toLowerCase()) || !ID_RE.test(id)) continue;
      const kind = parts[i].replace(/s$/, '');
      if (!/^[A-Za-z][\w-]*$/.test(kind) || SKIP.has(kind)) continue;
      found.push({ kind, object_id: id });
      i += 1;
    }
    return found;
  }

  const TURN_WAIT_S = 600;
  // Apps that refuse state-changing requests without their anti-CSRF header (``X-Hoard-Request: 1``) accept the
  // relay like any other call of their own page; apps that do not check it ignore the header.
  const APP_HEADERS = { 'X-Hoard-Request': '1' };

  function relayFetch(input, init = {}, onTurn) {
    const request = new Request(input, init);
    return (async () => {
      const url = new URL(request.url);
      // Keep the upstream chat path stable when the workbench rewrites local API routes.
      const isChatTurn = url.pathname === ["", "api", "chat_stream"].join("/");
      const envelope = { path: url.pathname + url.search, method: request.method, headers: {} };
      for (const name of ['X-Faustus-Client-Version', 'X-Odysseus-Run-Id']) {
        const value = request.headers.get(name);
        if (value) envelope.headers[name] = value;
      }
      let bytes;
      if (request.method !== 'GET' && request.method !== 'HEAD') {
        bytes = new Uint8Array(await request.arrayBuffer());
        const type = request.headers.get('Content-Type') || '';
        if (type.startsWith('application/json')) {
          envelope.body = JSON.parse(new TextDecoder().decode(bytes) || 'null');
          // Someone typing in an app waits for the answer: a turn queued behind another agent on the shared model
          // lane keeps its place (the panel shows the queue) instead of failing at the endpoint's short default.
          if (isChatTurn && envelope.body && typeof envelope.body === 'object'
              && envelope.body.initial_response_timeout_s == null) envelope.body.initial_response_timeout_s = TURN_WAIT_S;
        }
        else {
          let binary = '';
          for (let i = 0; i < bytes.length; i += 0x8000) binary += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
          envelope.content_type = type;
          envelope.raw_body = btoa(binary);
        }
      }
      if (onTurn && request.method === 'POST' && isChatTurn) {
        if (envelope.body) onTurn(envelope.body);
        else if (envelope.content_type?.startsWith('multipart/form-data')) {
          try {
            const data = await new Response(bytes, {
              headers: {'Content-Type': envelope.content_type},
            }).formData();
            const body = {};
            for (const field of ['message', 'user_message', 'user_input', 'prompt', 'text', 'input']) {
              if (typeof data.get(field) === 'string') body[field] = data.get(field);
            }
            for (const field of ['context', 'hoard_context']) {
              if (typeof data.get(field) === 'string') {
                try { body[field] = JSON.parse(data.get(field)); } catch { /* the chat still handles its own payload */ }
              }
            }
            onTurn(body);
          } catch { /* an attachment must never prevent the native chat from sending */ }
        }
      }
      const response = await fetch('/api/copilot/proxy', { method: 'POST', headers: { 'Content-Type': 'application/json', ...APP_HEADERS },
        body: JSON.stringify(envelope), signal: request.signal, credentials: 'same-origin' });
      showDestination(response.headers.get('X-Hoard-Copilot-Destination'));
      return response;
    })();
  }

  const css = `
    .hoard-copilot-layer{position:fixed;inset:0;margin:0;padding:0;border:0;width:100vw;height:100dvh;
      max-width:none;max-height:none;background:transparent;overflow:visible;pointer-events:none}
    .hoard-copilot-layer::backdrop{background:transparent;pointer-events:none}
    .hoard-copilot-layer>.hoard-copilot-toggle,.hoard-copilot-layer>.hoard-copilot{pointer-events:auto}
    .hoard-copilot-toggle{position:fixed;right:var(--hoard-copilot-right,18px);bottom:var(--hoard-copilot-bottom,18px);z-index:2147483000;font:600 13px/1 system-ui,sans-serif;
      display:grid;place-items:center;width:48px;height:48px;padding:0;border-radius:50%;border:1px solid rgba(127,127,127,.45);background:#1f1b2e;color:__FAUSTUS_BRAND__;
      box-shadow:0 6px 18px rgba(0,0,0,.35);cursor:pointer}
    .hoard-copilot-toggle svg{pointer-events:none}
    .hoard-copilot-toggle:focus-visible{outline:2px solid __FAUSTUS_BRAND__;outline-offset:2px}
    html[data-hoard-copilot-position=left] .hoard-copilot-toggle{right:auto;left:var(--hoard-copilot-left,18px)}
    .hoard-copilot{position:fixed;top:var(--hoard-copilot-top,14px);right:14px;bottom:calc(var(--hoard-copilot-bottom,18px) + 48px);width:min(430px,calc(100vw - 28px));z-index:2147483001;
      display:flex;flex-direction:column;background:#17141f;color:#f4f1ff;border:1px solid rgba(127,127,127,.4);
      border-radius:12px;box-shadow:0 12px 40px rgba(0,0,0,.45);font:14px/1.4 system-ui,sans-serif}
    .hoard-copilot[data-inline]{position:static;width:100%;height:clamp(250px,46dvh,435px);min-width:0;z-index:auto;box-shadow:none}
    .hoard-copilot[data-inline]:not(:has(faustus-chat)){height:auto}
    .hoard-copilot-conversation-tools{display:none;padding:6px 12px;border-bottom:1px solid rgba(127,127,127,.25)}
    .hoard-copilot[data-inline] .hoard-copilot-conversation-tools{display:block}
    .hoard-copilot-conversation-tools p{margin:0}
    .hoard-copilot-conversation-tools form{display:flex;flex-wrap:wrap;align-items:end;gap:6px;margin-top:6px}
    .hoard-copilot-conversation-tools label{min-width:0;flex:1 1 10ch}
    .hoard-copilot-conversation-tools input{display:block;width:100%;box-sizing:border-box}
    .hoard-copilot-conversation-tools :is(input,button){font:inherit;color:inherit;background:#242132;border:1px solid #91879d;border-radius:4px;padding:3px 6px}    .hoard-copilot .hoard-copilot-loading{margin:12px}
    .hoard-copilot details summary{cursor:pointer}
    .hoard-copilot[hidden]{display:none}
    .hoard-copilot header{display:flex;justify-content:space-between;align-items:center;gap:10px;padding:10px 12px;
      border-bottom:1px solid rgba(127,127,127,.25)}
    .hoard-copilot header button{background:transparent;border:0;color:inherit;font-size:20px;line-height:1;cursor:pointer;padding:2px 6px}
    .hoard-copilot .hoard-copilot-body{flex:1;min-height:0;display:flex}
    .hoard-copilot faustus-chat{flex:1;min-height:0;border:0;border-radius:0 0 12px 12px}
    .hoard-copilot [role=alert]{margin:10px 12px;color:#ffb4a8}
.hoard-copilot .hoard-copilot-unavailable{display:flex;flex-direction:column;align-items:flex-start;gap:8px;color:inherit;line-height:1.45}
.hoard-copilot .hoard-copilot-unavailable p{margin:0}
.hoard-copilot .hoard-copilot-unavailable button{font:inherit;padding:6px 12px;border-radius:8px;border:1px solid currentColor;background:transparent;color:inherit;cursor:pointer}
.hoard-copilot .hoard-copilot-unavailable small{opacity:.65;overflow-wrap:anywhere}
    @media (max-width:600px){.hoard-copilot{top:var(--hoard-copilot-top,6px);right:6px;bottom:60px;width:calc(100vw - 12px)}}`;

  let conversationControls = null;
  let info = null;
  let aside = null;
  let panel = null;
  let currentKey = null;          // localStorage key of the conversation on screen: data space (+ the app's project)
  let busy = false;               // a turn is running: a project switch waits for its end
  let lastAsk = 0;                // when the panel last asked for the context (a send is starting)
  let refreshAfterTurn = false;   // the conversation changed under a send: show its history when the turn ends
  let layer = null;
  const modalOrder = [];

  function isModal(node) {
    if (!node || !node.isConnected || node.tagName !== 'DIALOG' || !node.open) return false;
    try { return node.matches(':modal'); } catch { return true; }
  }

  // A popover escapes clipping, but it must still be a DOM descendant of the
  // active modal to remain interactive. Move the host, never recreate its chat.
  function placeLayer(records = []) {
    if (!layer) return;
    for (const record of records) {
      if (record.type === 'attributes' && isModal(record.target)) {
        const index = modalOrder.indexOf(record.target);
        if (index >= 0) modalOrder.splice(index, 1);
        modalOrder.push(record.target);
      }
    }
    for (const node of document.querySelectorAll('dialog[open]')) {
      if (isModal(node) && !modalOrder.includes(node)) modalOrder.push(node);
    }
    for (let index = modalOrder.length - 1; index >= 0; index--) {
      if (!isModal(modalOrder[index])) modalOrder.splice(index, 1);
    }
    const parent = modalOrder[modalOrder.length - 1] || document.body;
    let focus = layer.contains(document.activeElement) ? document.activeElement : null;
    while (focus && focus.shadowRoot && focus.shadowRoot.activeElement) focus = focus.shadowRoot.activeElement;
    if (layer.parentNode !== parent) {
      if (typeof layer.hidePopover === 'function' && layer.matches(':popover-open')) layer.hidePopover();
      if (typeof parent.moveBefore === 'function') parent.moveBefore(layer, null);
      else parent.appendChild(layer);
    }
    if (typeof layer.showPopover === 'function' && !layer.matches(':popover-open')) layer.showPopover();
    if (focus && focus.isConnected && document.activeElement !== focus) focus.focus({ preventScroll: true });
  }

  function stopKeys(node) {
    for (const type of ['keydown', 'keyup', 'keypress']) node.addEventListener(type, (event) => {
      event.stopPropagation();
      if (type === 'keydown' && event.key === 'Escape' && modalOrder.length) event.preventDefault();
    });
  }

  async function appContext() {
    const route = routeOf();
    const selected = String(window.getSelection?.() || '').trim();
    const base = {
      origin: { app_id: info.app_id, app_name: info.app_name, data_space_id: info.data_space_id,
                surface: 'page', tool_server_id: info.tool_server_id },
      view: { route, title: document.title, heading: (document.querySelector('h1')?.textContent || '').trim().slice(0, 200),
              locale: lang() },
      active_objects: guessObjects(route),
      selection: selected ? { kind: 'text', text: selected.slice(0, 4000) } : null,
    };
    const hook = window.hoardCopilot && window.hoardCopilot.context;
    if (typeof hook !== 'function') return base;
    try {
      const extra = (await hook(base)) || {};
      const merged = { ...base, ...extra, origin: base.origin, view: { ...base.view, ...(extra.view || {}) } };
      if (merged.project == null) delete merged.project;   // a view without a project omits it
      return merged;
    } catch (error) {
      return { ...base, context_error: String(error && error.message || error) };
    }
  }

  function projectKey(ctx) {
    const project = ctx && ctx.project;
    if (!project || typeof project !== 'object') return '';
    const id = project.external_project_id ?? project.id ?? project.project_link_id ?? project.project_id ?? project.title;
    return id == null || id === '' ? '' : String(id).slice(0, 200);
  }

  function keyFor(ctx) {
    const project = projectKey(ctx);
    return 'hoard-copilot:' + info.data_space_id + (project ? ':project:' + project : '');
  }

  // A conversation saved against another Faustus (or deleted there) would leave the panel stuck on a 404: check it and
  // start fresh when it is gone. Network failures keep the saved id so a restart does not lose the thread.
  async function savedSession(key) {
    const saved = store.get(key);
    if (!saved) return null;
    let gone = false;
    try { gone = (await relayFetch(window.location.origin + '/api/hoard-copilot/conversations/' + encodeURIComponent(saved))).status === 404; }
    catch { gone = false; }
    if (gone) { store.set(key, null); return null; }
    return saved;
  }

  // What the panel sends with each turn. It asks right before picking the conversation, so a project change nothing
  // announced still sends this turn to that project's conversation (its history is shown when the turn ends).
  async function context() {
    lastAsk = Date.now();
    const ctx = await appContext();
    const key = keyFor(ctx);
    if (panel && key !== currentKey) {
      currentKey = key;
      panel.session = await savedSession(key);
      syncRename(panel);
      refreshAfterTurn = true;
    }
    return ctx;
  }

  function messageText(value) {
    if (typeof value === 'string') return value;
    const content = value?.content ?? value;
    if (typeof content === 'string') return content;
    if (Array.isArray(content)) {
      return content.filter(part => ['text', 'input_text', 'output_text'].includes(part?.type))
        .map(part => typeof part.text === 'string' ? part.text : '').filter(Boolean).join('\n');
    }
    return typeof value?.text === 'string' ? value.text : '';
  }

  function requestText(body) {
    const messages = Array.isArray(body?.messages) ? body.messages : Array.isArray(body?.input) ? body.input : [];
    const user = messages.findLast(message => message?.role === 'user');
    const candidates = [body?.message, body?.user_message, body?.user_input, user, body?.text,
      typeof body?.input === 'string' ? body.input : null, body?.prompt];
    return candidates.filter(value => !value?.role || value.role === 'user').map(messageText).find(text => text.trim()) || '';
  }

  let turnSequence = 0;
  const textEvents = new Set(['text', 'text_delta', 'assistant_delta', 'assistant_text', 'content_block_delta']);
  const textBoundaries = new Set(['tool_input', 'tool_start', 'tool_call', 'tool_use', 'tool_output', 'tool_result', 'text_end', 'message_stop']);

  function publishConversation(turn, role, text, speaker) {
    const part = role === 'user' ? 'request' : turn.part;
    window.dispatchEvent(new CustomEvent('hoard:copilot-conversation', {
      detail: { projectId: turn.projectId, id: 'copilot:' + turn.id + ':' + part, role, text, speaker },
    }));
  }

  function recordAssistantText(turn, event) {
    if (!turn || (event.role && event.role !== 'assistant')) return;
    if (textBoundaries.has(event.type)) {
      if (turn.text) { turn.part++; turn.text = ''; }
      return;
    }
    const full = event.type === 'assistant_message' || event.type === 'message' && event.message?.role === 'assistant';
    if (!full && !textEvents.has(event.type)) return;
    if (event.type === 'content_block_delta' && event.delta?.type !== 'text_delta') return;
    const delta = typeof event.delta === 'string' ? event.delta : event.delta?.text;
    const text = typeof delta === 'string' ? delta : messageText(event.message || event);
    if (!text) return;
    if (full) {
      if (turn.text && !text.startsWith(turn.text)) turn.part++;
      turn.text = text;
    } else if (event.type === 'assistant_text' && typeof delta !== 'string') {
      turn.text = text;
    } else {
      turn.text += text;
    }
    if (turn.text.trim()) publishConversation(turn, 'assistant', turn.text, event.actor?.name);
    if (full) { turn.part++; turn.text = ''; }
  }

  function showDestination(value) {
    if (!conversationControls || typeof value !== 'string') return;
    const es = lang() === 'es';
    const spark = /^spark:(\d+)$/.exec(value);
    const labels = {
      searching: es ? 'Buscando Faustus…' : 'Looking for Faustus…',
      pc: 'Faustus · PC',
      spark: 'Faustus · Spark',
      remote: es ? 'Faustus · Servidor remoto' : 'Faustus · Remote server',
      connection_lost: es ? 'Se ha perdido la conexión con Faustus.' : 'The connection to Faustus was lost.',
      unavailable: es ? 'Ningún Faustus responde.' : 'No Faustus server is responding.',
    };
    const label = spark ? 'Faustus · Spark ' + spark[1] : labels[value];
    if (typeof label !== 'string') return;
    conversationControls.destination.textContent = label;
    conversationControls.destination.hidden = false;
  }

  let discovery = 0;
  async function readInfo() {
    const request = ++discovery;
    showDestination('searching');
    let destination = 'unavailable';
    try {
      const response = await fetch('/api/copilot/info', { headers: APP_HEADERS, credentials: 'same-origin', cache: 'no-store' });
      if (!response.ok) {
        destination = response.headers.get('X-Hoard-Copilot-Destination') || 'unavailable';
        throw new Error((await response.text()) || ('HTTP ' + response.status));
      }
      const data = await response.json();
      destination = data.destination;
      return data;
    } finally {
      if (request === discovery) {
        if (destination) showDestination(destination);
        else conversationControls.destination.hidden = true;
      }
    }
  }

  function syncRename(element) {
    const controls = conversationControls;
    const session = element?.session || null;
    if (!controls || (controls.element === element && controls.session === session)) return;
    controls.element = element;
    controls.session = session;
    controls.rename.hidden = !session;
    controls.rename.open = false;
    controls.field.value = '';
    controls.notice.textContent = '';
  }

  function makeConversationControls() {
    const es = lang() === 'es';
    const root = document.createElement('div');
    root.className = 'hoard-copilot-conversation-tools';
    const destination = document.createElement('p');
    destination.setAttribute('role', 'status');
    destination.hidden = true;
    const rename = document.createElement('details');
    rename.hidden = true;
    const summary = document.createElement('summary');
    summary.textContent = es ? 'Renombrar conversación' : 'Rename conversation';
    const form = document.createElement('form');
    const label = document.createElement('label');
    label.textContent = es ? 'Nuevo nombre' : 'New name';
    const field = document.createElement('input');
    field.required = true;
    label.appendChild(field);
    const save = document.createElement('button');
    save.type = 'submit';
    save.textContent = es ? 'Guardar' : 'Save';
    const notice = document.createElement('p');
    notice.setAttribute('role', 'status');
    form.append(label, save);
    rename.append(summary, form);
    root.append(destination, rename, notice);

    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      if (save.disabled) return;
      const element = panel;
      const session = element?.session;
      const key = currentKey;
      const name = field.value.trim();
      if (!session || !name) {
        notice.textContent = es ? 'Escribe un nombre para la conversación.' : 'Enter a name for the conversation.';
        return;
      }
      save.disabled = true;
      notice.textContent = '';
      const stillCurrent = () => panel === element && currentKey === key && element.session === session;
      try {
        if (keyFor(await appContext()) !== key || !stillCurrent()) {
          schedule();
          return;
        }
        const encoded = encodeURIComponent(session);
        const response = await relayFetch(location.origin + '/api/session/' + encoded,
          { method: 'PATCH', body: new URLSearchParams({ name }) });
        if (!stillCurrent()) return;
        let unsupported = [405, 501].includes(response.status);
        if (response.status === 404) {
          const existing = await relayFetch(location.origin + '/api/hoard-copilot/conversations/' + encoded);
          unsupported = existing.ok;
        }
        if (!stillCurrent()) return;
        if (unsupported) {
          notice.textContent = es ? 'Este Faustus no permite renombrar conversaciones.' : 'This Faustus does not support renaming conversations.';
          return;
        }
        if (!response.ok) throw new Error('Rename failed');
        const result = await response.json();
        if (!stillCurrent()) return;
        if (result?.id !== session || result.name !== name) throw new Error('Rename not confirmed');
        rename.open = false;
        field.value = '';
        notice.textContent = es ? 'Nombre guardado.' : 'Name saved.';
        summary.focus();
        try { await element.refreshConversations?.(); } catch { /* the rename already persisted */ }
      } catch {
        if (stillCurrent()) notice.textContent = es ? 'No se pudo guardar el nombre. Vuelve a intentarlo.' : 'Could not save the name. Try again.';
      } finally {
        save.disabled = false;
      }
    });
    return { root, destination, rename, field, notice };
  }
  function buildPanel(sessionId) {
    const element = document.createElement('faustus-chat');
    element.server = window.location.origin;
    element.locale = lang();
    element.theme = 'dark';
    let requestProject = '';
    let turn;
    element.fetch = (input, init) => relayFetch(input, init, (body) => {
      const projectId = projectKey(body.context) || projectKey(body.hoard_context) || requestProject;
      const text = requestText(body);
      if (!projectId || !text) return;
      if (turn?.projectId === projectId && turn.request === text) return;
      turn = { projectId, request: text, id: ++turnSequence, part: 0, text: '' };
      publishConversation(turn, 'user', text);
    });
    element.onOpenSettings = () => window.open(info.settings_url, '_blank', 'noopener');
    element.contextProvider = async () => {
      const value = await context();
      requestProject = projectKey(value);
      return value;
    };
    if (sessionId) element.session = sessionId;
    element.addEventListener('faustus:session-change', (event) => {
      if (currentKey) store.set(currentKey, event.detail && event.detail.sessionId);
      if (panel === element) syncRename(element);
    });
    element.addEventListener('faustus:turn-start', () => { busy = true; });
    // A completed tool can already have saved changes while the model is still answering.
    // Keep the panel and turn mounted; hosts only reload their own saved views.
    element.addEventListener('faustus:event', (event) => {
      const detail = event.detail || {};
      recordAssistantText(turn, detail);
      if (detail.type !== 'tool_output') return;
      window.dispatchEvent(new CustomEvent('hoard:copilot-change', { detail }));
      try {
        const host = window.hoardCopilot;
        const refresh = host && (host.onChange || host.onTurnEnd);
        if (typeof refresh === 'function') Promise.resolve(refresh.call(host, detail)).catch(() => {});
      } catch { /* a host refresh must never interrupt the turn */ }
    });
    element.addEventListener('faustus:turn-end', (event) => {
      busy = false;
      turn = undefined;
      window.dispatchEvent(new CustomEvent('hoard:copilot-turn-end', { detail: event.detail || {} }));
      try { window.hoardCopilot && typeof window.hoardCopilot.onTurnEnd === 'function' && window.hoardCopilot.onTurnEnd(event.detail || {}); }
      catch { /* the app's refresh must never break the panel */ }
      if (refreshAfterTurn) {
        refreshAfterTurn = false;
        if (typeof element.loadHistory === 'function') element.loadHistory().catch(() => {});
      }
      schedule();   // a navigation during the turn waited for its end
    });
    return element;
  }

  async function mount(body, title) {
    info = await readInfo();
    if (aside?.hasAttribute('data-inline')) {
      const status = document.createElement('p');
      status.className = 'hoard-copilot-loading';
      status.setAttribute('role', 'status');
      status.textContent = lang() === 'es' ? 'Cargando conversación…' : 'Loading conversation…';
      body.replaceChildren(status);
    }
    title.textContent = 'Faustus · ' + (info.app_name || info.app_id);
    await import(info.panel_url);
    // One conversation per app data space (and per project when the app names one): the route of every turn travels
    // in the context, so moving around the app keeps the thread instead of scattering it over one chat per page.
    currentKey = keyFor(await appContext());
    panel = buildPanel(await savedSession(currentKey));
    body.replaceChildren(panel);
    syncRename(panel);
    if (typeof panel.loadHistory === 'function') await panel.loadHistory();
  }

  // A different project in the app is a different conversation: put that one (or a fresh one) on screen. Never in the
  // middle of a turn or of a send that is asking for its context.
  async function checkProject() {
    if (!panel || !info || !aside || aside.hidden || busy || Date.now() - lastAsk < 3000) return;
    const key = keyFor(await appContext());
    if (key === currentKey || busy || Date.now() - lastAsk < 3000) return;
    currentKey = key;
    const next = buildPanel(await savedSession(key));
    panel.replaceWith(next);
    panel = next;
    syncRename(panel);
    if (typeof next.loadHistory === 'function') await next.loadHistory();
  }

  let checkTimer = 0;
  function schedule() {
    clearTimeout(checkTimer);
    checkTimer = setTimeout(() => { checkProject().catch(() => {}); }, 250);
  }

  // A strict content security policy (``style-src 'self'``) blocks a <style> element but not a constructed sheet, so
  // the launcher adopts one when the browser can and falls back to <style> otherwise.
  function addStyles() {
    try {
      const sheet = new CSSStyleSheet();
      sheet.replaceSync(css);
      document.adoptedStyleSheets = [...document.adoptedStyleSheets, sheet];
      return;
    } catch { /* older browser: a <style> element */ }
    const style = document.createElement('style');
    style.textContent = css;
    document.head.appendChild(style);
  }

  // The panel opens under the app's own top bar instead of covering its buttons: the lowest bar across the panel's
  // width (fixed or sticky at the top edge, or a header/nav/banner starting in the first 64 px) sets
  // ``--hoard-copilot-top``.
  // An app that sets ``--hoard-copilot-top`` itself keeps its value.
  function fitBelowHeader() {
    if (aside?.hasAttribute('data-inline')) return;
    if (!aside) return;
    aside.style.removeProperty('--hoard-copilot-top');
    if (getComputedStyle(document.documentElement).getPropertyValue('--hoard-copilot-top').trim()) return;
    const width = window.innerWidth;
    const height = window.innerHeight;
    const panelLeft = Math.max(0, width - Math.min(430, width - 28) - 14);
    let bottom = 0;
    for (const x of [width - 24, width - 120, (width + panelLeft) / 2, panelLeft + 24]) {
      for (const y of [4, 24, 48, 72]) {
        for (const node of document.elementsFromPoint(Math.max(0, x), y)) {
          if (layer && layer.contains(node)) continue;
          if (node === document.documentElement || node === document.body) break;
          const bar = barOf(node, height);
          if (bar) bottom = Math.max(bottom, bar.getBoundingClientRect().bottom);
          break;
        }
      }
    }
    if (bottom > 0 && bottom < height * 0.4) aside.style.setProperty('--hoard-copilot-top', Math.ceil(bottom + 8) + 'px');
  }

  function barOf(node, height) {
    for (let el = node; el && el !== document.body && el !== document.documentElement; el = el.parentElement) {
      const rect = el.getBoundingClientRect();
      if (rect.height > height * 0.4 || rect.bottom <= 0) continue;
      const position = getComputedStyle(el).position;
      if (rect.top <= 2 && (position === 'fixed' || position === 'sticky')) return el;
      // A page header a little below the top edge (padding, a margin) still holds the app's main buttons.
      if (rect.top <= 64 && (/^(HEADER|NAV)$/.test(el.tagName) || el.getAttribute('role') === 'banner')) return el;
    }
    return null;
  }

  // Faustus down or unreachable: the app keeps working; the panel says so in plain words and offers to try again
  // (the draft lives in Faustus and comes back with the conversation).
  function unavailable(body, title, error) {
    const es = lang() === 'es';
    const box = document.createElement('div');
    box.setAttribute('role', 'alert');
    box.className = 'hoard-copilot-unavailable';
    const text = document.createElement('p');
    text.textContent = es
      ? 'Ningún Faustus responde ahora mismo. La aplicación sigue funcionando y tu borrador se conserva; vuelve a intentarlo cuando Faustus esté en marcha.'
      : 'No Faustus server is responding right now. The app keeps working and your draft is kept; try again once Faustus is running.';
    const retry = document.createElement('button');
    retry.type = 'button';
    retry.textContent = es ? 'Reintentar' : 'Try again';
    retry.addEventListener('click', () => { attach(body, title); });
    const detail = document.createElement('small');
    detail.textContent = String(error && error.message || error || '');
    box.append(text, retry);
    if (aside?.hasAttribute('data-inline')) {
      const disclosure = document.createElement('details');
      const label = document.createElement('summary');
      label.textContent = es ? 'Detalles técnicos' : 'Technical details';
      disclosure.append(label, detail);
      box.appendChild(disclosure);
    } else box.appendChild(detail);
    body.replaceChildren(box);
  }

  function attach(body, title) {
    if (aside?.hasAttribute('data-inline')) body.replaceChildren();
    mounting = mount(body, title).catch((error) => { panel = null; syncRename(null); conversationControls.destination.hidden = true; unavailable(body, title, error); }).finally(() => { mounting = null; });
    return mounting;
  }

  let mounting = null;
  let mountTarget = null;
  let returnFocus = null;

  function placeAside(container) {
    const inline = container instanceof HTMLElement && container.isConnected;
    const destination = inline ? container : layer;
    const previous = aside.hasAttribute('data-inline') ? aside.parentElement : null;
    aside.toggleAttribute('data-inline', inline);
    if (aside.parentElement !== destination) {
      if (previous) window.dispatchEvent(new CustomEvent('hoard:copilot-visibility', {
        detail: { container: previous, visible: false },
      }));
      if (aside.isConnected && typeof destination.moveBefore === 'function') destination.moveBefore(aside, null);
      else destination.appendChild(aside);
    }
  }

  function setVisible(toggle, visible) {
    aside.hidden = !visible;
    toggle.setAttribute('aria-expanded', String(visible));
    if (aside.hasAttribute('data-inline')) {
      window.dispatchEvent(new CustomEvent('hoard:copilot-visibility', {
        detail: { container: aside.parentElement, visible },
      }));
    }
  }

  function open(toggle, container, trigger) {
    returnFocus = trigger || toggle;
    if (aside) {
      placeAside(container); setVisible(toggle, true); fitBelowHeader();
      if (!panel && !mounting && mountTarget) attach(mountTarget.body, mountTarget.title);
      else {
        if (panel && aside.hasAttribute('data-inline')) {
          readInfo().then(({ settings_url }) => { if (info) info.settings_url = settings_url; }).catch(() => {});
        }
        schedule();
      }
      return;
    }
    aside = document.createElement('aside');
    aside.className = 'hoard-copilot';
    aside.setAttribute('aria-label', 'Faustus');
    aside.tabIndex = -1;
    const header = document.createElement('header');
    const title = document.createElement('strong');
    title.textContent = 'Faustus';
    const close = document.createElement('button');
    close.type = 'button';
    close.textContent = '×';
    close.setAttribute('aria-label', lang() === 'es' ? 'Cerrar Faustus' : 'Close Faustus');
    close.addEventListener('click', () => {
      setVisible(toggle, false);
      (returnFocus?.getClientRects().length ? returnFocus : toggle).focus();
    });
    header.append(title, close);
    const body = document.createElement('div');
    body.className = 'hoard-copilot-body';
    conversationControls = makeConversationControls();
    aside.append(header, conversationControls.root, body);
    stopKeys(aside);
    // Escape closes the panel (inside an app dialog it stays for the dialog; the chat may claim it first).
    aside.addEventListener('keydown', (event) => {
      if (event.key === 'Escape' && !modalOrder.length && !event.defaultPrevented) close.click();
    });
    placeAside(container);
    setVisible(toggle, true);
    fitBelowHeader();
    window.addEventListener('resize', () => { if (aside && !aside.hidden) fitBelowHeader(); });
    mountTarget = { body, title };
    attach(body, title);
  }

  function start() {
    if (document.querySelector('.hoard-copilot-toggle, faustus-chat')) return;
    addStyles();
    layer = document.createElement('div');
    layer.className = 'hoard-copilot-layer';
    if (typeof layer.showPopover === 'function') layer.setAttribute('popover', 'manual');
    document.body.appendChild(layer);
    const toggle = document.createElement('button');
    toggle.type = 'button';
    toggle.className = 'hoard-copilot-toggle';
    toggle.innerHTML = __FAUSTUS_MARK_SVG__;
    toggle.setAttribute('aria-label', 'Faustus');
    toggle.title = 'Faustus';
    toggle.setAttribute('aria-expanded', 'false');
    toggle.addEventListener('click', () => {
      const slot = document.querySelector('[data-hoard-copilot-inline-slot]');
      if (aside && !aside.hidden && aside.getClientRects().length) setVisible(toggle, false);
      else open(toggle, slot?.getClientRects().length ? slot : null);
    });
    layer.appendChild(toggle);
    const modalObserver = new MutationObserver(placeLayer);
    modalObserver.observe(document.body, { childList: true, subtree: true, attributes: true, attributeFilter: ['open'] });
    placeLayer();
    window.addEventListener('hoard:copilot-open', (event) => open(toggle, event.detail?.container, event.detail?.trigger));
    window.addEventListener('hoard:copilot-release', (event) => {
      if (!aside || aside.parentElement !== event.detail?.container) return;
      setVisible(toggle, false);
      placeAside(null);
    });
    for (const name of ['pushState', 'replaceState']) {
      const original = history[name];
      if (typeof original !== 'function') continue;
      history[name] = function (...args) { const out = original.apply(this, args); schedule(); return out; };
    }
    window.addEventListener('popstate', schedule);
    window.addEventListener('hashchange', schedule);
    window.addEventListener('hoard:copilot-context-changed', schedule);
  }

  window.hoardCopilotGuessObjects = guessObjects;
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start, { once: true });
  else start();
})();
""".replace('__FAUSTUS_MARK_SVG__', json.dumps(FAUSTUS_MARK_SVG)).replace('__FAUSTUS_BRAND__', FAUSTUS_BRAND)
