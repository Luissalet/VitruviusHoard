// Tesela transfer flow: data → confirm → receipt, through the project's atomic action `transferir`.
// Voice/assistant anchors: every field has data-voice-field; window.teselaTransfer exposes the same steps a person takes.
import {euros, groupIban, maskIban, loadBank, esc} from './bank.js';
import {mountTransferAssistant} from './transfer-assistant/assistant.js';

const form = document.getElementById('transfer-form');
const $ = (id) => document.getElementById(id);
let accounts = [];
let contacts = [];
let pending = null;
let voice = null;
const amountText = (cents) => euros(cents).replace(/\u00a0€$/, '');

/** Parses "1.234,56", "1234.56", "50" or "50,5" into integer cents; NaN when it is not an amount. */
export function parseCents(text) {
  let s = String(text ?? '').trim().replace(/\s|€/g, '');
  if (!s) return NaN;
  if (s.includes(',')) s = s.replace(/\./g, '').replace(',', '.');
  else if (/^\d{1,3}(\.\d{3})+$/.test(s)) s = s.replace(/\./g, '');
  if (!/^\d+(\.\d{1,2})?$/.test(s)) return NaN;
  return Math.round(Number(s) * 100);
}
/** ISO 13616 check: country, check digits and mod 97 (Spain: 24 characters). */
export function validIban(raw) {
  const s = String(raw ?? '').replace(/\s+/g, '').toUpperCase();
  if (!/^[A-Z]{2}\d{2}[A-Z0-9]{11,30}$/.test(s)) return false;
  if (s.startsWith('ES') && s.length !== 24) return false;
  let rest = 0;
  for (const ch of s.slice(4) + s.slice(0, 4)) {
    for (const d of /\d/.test(ch) ? ch : String(ch.charCodeAt(0) - 55)) rest = (rest * 10 + Number(d)) % 97;
  }
  return rest === 1;
}
/** Contacts whose name or alias contains every word given (accent-insensitive). Two matches mean the assistant must ask which. */
export function findContacts(text) {
  const norm = (s) => String(s).normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();
  const words = norm(text).split(/\s+/).filter(Boolean);
  return contacts.filter(c => words.every(w => norm(`${c.nombre} ${c.alias || ''}`).includes(w)));
}
const ERRORS = {insufficient_balance: 'Saldo insuficiente', ambiguous_reference: 'Hay más de una cuenta con ese IBAN', different_values: 'El origen y el destino son la misma cuenta',
  not_found: 'No se encuentra la cuenta o el contacto', conflict: 'La operación ya no se puede repetir'};

function fillSelects() {
  const chosen = $('origen').value;
  $('origen').innerHTML = accounts.map(a => `<option value="${esc(a.id)}">${esc(a.nombre)} · ${euros(a.disponible_cent)} disponibles</option>`).join('');
  if (chosen) $('origen').value = chosen;
  const contact = $('contacto').value;
  $('contacto').innerHTML = '<option value="">Elige un contacto</option>' + contacts.map(c => `<option value="${esc(c.id)}">${esc(c.nombre)}${c.nota ? ' · ' + esc(c.nota) : ''}</option>`).join('');
  if (contact) $('contacto').value = contact;
  syncDestino(); syncContactIban();
}
function syncDestino() {
  const from = $('origen').value;
  const current = $('destino').value;
  $('destino').innerHTML = accounts.filter(a => a.id !== from).map(a => `<option value="${esc(a.id)}">${esc(a.nombre)} · ${esc(maskIban(a.iban))}</option>`).join('');
  if ([...$('destino').options].some(o => o.value === current)) $('destino').value = current;
  const a = accounts.find(x => x.id === from);
  $('origen-hint').textContent = a ? `${a.tipo} · ${maskIban(a.iban)}` : '';
}
const mode = () => form.querySelector('input[name="modo"]:checked')?.value || 'contacto';
function syncMode() { for (const el of form.querySelectorAll('[data-when]')) el.hidden = el.dataset.when !== mode(); }
function syncContactIban() {
  const c = contacts.find(x => x.id === $('contacto').value);
  $('contacto-iban').textContent = c ? groupIban(c.iban) : '';
}

/** Current form values, as an assistant would read them. importe is in cents. */
export function fields() {
  return {origen: $('origen').value, modo: mode(), contacto: $('contacto').value, beneficiario: $('beneficiario').value.trim(),
    iban: $('iban').value.replace(/\s+/g, '').toUpperCase(), destino: $('destino').value, importe_cent: parseCents($('importe').value), concepto: $('concepto').value.trim()};
}
/** Field name → message for everything missing or wrong. Empty object = ready to review. */
export function problems(v = fields()) {
  const out = {};
  const from = accounts.find(a => a.id === v.origen);
  if (!from) out.origen = 'Elige la cuenta de origen.';
  if (v.modo === 'contacto' && !v.contacto) out.contacto = 'Elige a quién envías el dinero.';
  if (v.modo === 'iban') {
    if (!v.beneficiario) out.beneficiario = 'Escribe el nombre del titular.';
    if (!v.iban) out.iban = 'Escribe el IBAN de destino.';
    else if (!validIban(v.iban)) out.iban = 'Este IBAN no es válido: revisa los dígitos.';
    else if (from && from.iban === v.iban) out.iban = 'Es el IBAN de la cuenta de origen.';
  }
  if (v.modo === 'propia' && (!v.destino || v.destino === v.origen)) out.destino = 'Elige otra de tus cuentas.';
  if (!Number.isFinite(v.importe_cent) || v.importe_cent <= 0) out.importe = 'Escribe un importe mayor que cero, por ejemplo 25,50.';
  else if (from && v.importe_cent > from.disponible_cent) out.importe = `Saldo insuficiente: en ${from.nombre} hay ${euros(from.disponible_cent)} disponibles.`;
  if (!v.concepto) out.concepto = 'Escribe un concepto.';
  return out;
}
function showProblems(list) {
  for (const name of ['contacto', 'beneficiario', 'iban', 'importe', 'concepto']) {
    const el = $(name + '-error'); if (el) el.textContent = list[name] || '';
    $(name)?.setAttribute('aria-invalid', list[name] ? 'true' : 'false');
  }
}
function step(name) {
  for (const pane of form.querySelectorAll('[data-pane]')) pane.hidden = pane.dataset.pane !== name;
  for (const li of form.querySelectorAll('[data-step]')) {
    if (li.dataset.step === name) li.setAttribute('aria-current', 'step'); else li.removeAttribute('aria-current');
  }
  form.dataset.step = name;
  document.dispatchEvent(new CustomEvent('tesela:transfer-step', {detail: {step: name, transfer: pending}}));
}
function recipient(v) {
  if (v.modo === 'contacto') { const c = contacts.find(x => x.id === v.contacto); return {nombre: c.nombre, iban: c.iban}; }
  if (v.modo === 'propia') { const a = accounts.find(x => x.id === v.destino); return {nombre: a.nombre, iban: a.iban, cuenta: a.id}; }
  const own = accounts.find(a => a.iban === v.iban);
  return {nombre: v.beneficiario, iban: v.iban, cuenta: own?.id};
}

/** Moves to the confirmation step when everything is valid; returns the problems otherwise. */
export function review({focus = true, via = 'formulario'} = {}) {
  const v = fields();
  const list = problems(v);
  showProblems(list);
  if (Object.keys(list).length) return {ok: false, problems: list};
  const from = accounts.find(a => a.id === v.origen);
  pending = Object.freeze({...v, origen_nombre: from.nombre, origen_iban: from.iban, para: Object.freeze(recipient(v)), key: crypto.randomUUID(), via, huella: fingerprint(v)});
  $('transfer-summary').innerHTML = `
    <div><dt>Desde</dt><dd>${esc(from.nombre)}<span class="mono">${esc(maskIban(from.iban))}</span></dd></div>
    <div><dt>Para</dt><dd>${esc(pending.para.nombre)}<span class="mono">${esc(groupIban(pending.para.iban))}</span></dd></div>
    <div class="big"><dt>Importe</dt><dd>${euros(v.importe_cent)}</dd></div>
    <div><dt>Concepto</dt><dd>${esc(v.concepto)}</dd></div>
    <div><dt>Saldo después</dt><dd>${euros(from.saldo_cent - v.importe_cent)}</dd></div>
    <div><dt>Llega</dt><dd>${pending.para.cuenta ? 'Al momento, entre tus cuentas' : 'Hoy, transferencia inmediata'}</dd></div>`;
  if (via === 'voz') $('transfer-summary').insertAdjacentHTML('afterbegin', '<p class="read-note">Datos leídos por el asistente. Revísalos antes de confirmar.</p>');
  $('transfer-error').textContent = '';
  form.dataset.via = via;
  step('confirmar');
  if (focus) $('transfer-confirm').focus();
  return {ok: true, transfer: pending};
}

async function post(url, body, key) {
  const headers = {'Content-Type': 'application/json'};
  if (key) headers['Idempotency-Key'] = key;
  const response = await fetch(url, {method: 'POST', headers, body: JSON.stringify(body ?? {})});
  const answer = await response.json().catch(() => ({}));
  if (!response.ok) throw Object.assign(new Error(ERRORS[answer.code] || answer.error || `Respuesta ${response.status}`), {code: answer.code});
  return answer;
}

/** Sends the reviewed transfer with one call to the atomic action and shows the receipt. The same review retried keeps one charge. */
export async function confirm() {
  if (!pending) return {ok: false, problems: {transferencia: 'Revisa la transferencia antes de confirmarla.'}};
  // The confirmation runs exactly the reviewed draft. Only when the assistant read that same draft does it go
  // through the assistant, so a spoken and a clicked confirmation share one execution and one key.
  if (pending.via === 'voz' && voice?.matches(pending)) { await voice.api.submit('confirmo'); return {ok: form.dataset.step === 'justificante', via: 'voz'}; }
  try { return {ok: true, ...(await send(pending, pending.key))}; } catch (error) { return {ok: false, problems: {transferencia: error.message}, code: error.code}; }
}

/** The action input for a set of form values (without the date): exactly what a confirmation sends. */
function actionInput(v) {
  const input = {origen: v.origen, importe_cent: v.importe_cent, concepto: v.concepto};
  if (v.modo === 'contacto') input.contacto = v.contacto;
  else if (v.modo === 'propia') input.destino = v.destino;
  else { input.iban = v.iban; input.beneficiario = v.beneficiario; }
  return input;
}
const fingerprint = (v) => JSON.stringify(Object.entries(actionInput(v)).sort(([a], [b]) => a.localeCompare(b)));

/** Drops the reviewed draft: a confirmation needs a new review after any edit. */
function expire() {
  pending = null;
  form.dataset.via = 'formulario';
}

/** Calls the atomic action once for a reviewed transfer and shows the receipt; throws with the action's code. */
async function send(t, key) {
  if (!t || t !== pending || fingerprint(t) !== t.huella || fingerprint(fields()) !== t.huella) {
    expire();
    throw Object.assign(new Error('Los datos han cambiado desde la revisión: revisa la transferencia de nuevo'), {code: 'draft_changed'});
  }
  const button = $('transfer-confirm');
  button.disabled = true; button.textContent = 'Enviando…';
  const input = {...actionInput(t), fecha: new Date().toLocaleDateString('sv-SE')};
  try {
    const result = await post('/api/actions/transferir', input, key);
    const ref = 'TSL-' + input.fecha.replace(/-/g, '') + '-' + String(result.undo_token || t.key).replace(/[^a-z0-9]/gi, '').slice(-6).toUpperCase();
    const now = new Intl.DateTimeFormat('es-ES', {dateStyle: 'long', timeStyle: 'short'}).format(new Date());
    $('transfer-receipt').innerHTML = `<div class="receipt-ok" aria-hidden="true">✓</div><h2>Transferencia enviada</h2>
      <p class="receipt-amount">${euros(t.importe_cent)}</p>
      <dl class="summary">
        <div><dt>Para</dt><dd>${esc(t.para.nombre)}<span class="mono">${esc(groupIban(t.para.iban))}</span></dd></div>
        <div><dt>Desde</dt><dd>${esc(t.origen_nombre)}<span class="mono">${esc(groupIban(t.origen_iban))}</span></dd></div>
        <div><dt>Concepto</dt><dd>${esc(t.concepto)}</dd></div>
        <div><dt>Fecha</dt><dd>${esc(now)}</dd></div>
        <div><dt>Referencia</dt><dd class="mono" id="receipt-ref">${esc(ref)}</dd></div>
      </dl><p class="hint">Justificante de una operación simulada: no se ha movido dinero real.</p>
      <p class="error-text" id="undo-status" role="status"></p>`;
    const undo = $('transfer-undo');
    undo.hidden = !result.undo_token;
    undo.dataset.token = result.undo_token || '';
    const done = {...t, referencia: ref, undo_token: result.undo_token};
    pending = null;
    step('justificante');
    $('transfer-receipt').focus();
    await refresh();
    document.dispatchEvent(new CustomEvent('tesela:transfer-done', {detail: done}));
    return {transfer: done, receipt: result};
  } catch (error) {
    $('transfer-error').textContent = `No se ha enviado: ${error.message}.`;
    if (error.code === 'insufficient_balance') await refresh();
    throw error;
  } finally {
    button.disabled = false; button.textContent = 'Confirmar y enviar';
  }
}

/** Reverses the last sent transfer through its receipt (refused when newer movements depend on it). */
export async function undoLast() {
  const undo = $('transfer-undo');
  const token = undo.dataset.token;
  if (!token) return {ok: false};
  undo.disabled = true;
  try {
    await post(`/api/action-receipts/${encodeURIComponent(token)}/undo`);
    $('undo-status').textContent = 'Transferencia anulada: el dinero ha vuelto a la cuenta de origen.';
    $('undo-status').classList.add('ok');
    undo.hidden = true;
    await refresh();
    return {ok: true};
  } catch (error) {
    $('undo-status').textContent = `No se ha podido anular: ${error.message}.`;
    return {ok: false, code: error.code};
  } finally { undo.disabled = false; }
}

/** Sets any of origen, modo, contacto, beneficiario, iban, destino, importe (text or cents via importe_cent), concepto. Returns what is still missing. */
export function set(values = {}) {
  expire();
  if (form.dataset.step !== 'datos') step('datos');
  if (values.origen) { $('origen').value = values.origen; syncDestino(); }
  const m = values.modo || (values.contacto ? 'contacto' : values.iban || values.beneficiario ? 'iban' : values.destino ? 'propia' : null);
  if (m) { const r = form.querySelector(`input[name="modo"][value="${m}"]`); if (r) r.checked = true; syncMode(); }
  if (values.contacto) { $('contacto').value = values.contacto; syncContactIban(); }
  if (values.destino) $('destino').value = values.destino;
  for (const name of ['beneficiario', 'iban', 'concepto']) if (values[name] != null) $(name).value = values[name];
  if (values.importe_cent != null) $('importe').value = amountText(values.importe_cent);
  else if (values.importe != null) $('importe').value = values.importe;
  return problems();
}
export function reset() { form.reset(); pending = null; syncMode(); syncDestino(); syncContactIban(); showProblems({}); step('datos'); }

async function refresh() {
  try { ({accounts, contacts} = await loadBank()); $('transfer-load-error').hidden = true; }
  catch (error) { $('transfer-load-error').hidden = false; $('transfer-load-error').textContent = `No se han podido cargar tus cuentas: ${error.message}.`; }
  fillSelects();
}

// ---------- Voice assistant (shared transfer panel) ----------
// The panel owns the dialogue; this page gives it its accounts and contacts, its atomic action, and shows every
// understood field filling in the form, the missing ones marked, and the confirmation step with the data read.
const SLOT_FIELDS = {source: 'origen', recipient: 'contacto', iban: 'iban', amountCents: 'importe', concept: 'concepto'};

function markMissing(state) {
  const {slots} = state;
  const started = Object.keys(slots).length > 0 && !['complete', 'cancelled'].includes(state.phase);
  const r = slots.recipient;
  const has = {source: slots.source != null, recipient: Boolean(r), iban: Boolean(r?.iban || r?.id), amountCents: slots.amountCents != null, concept: Boolean(slots.concept)};
  for (const [slot, id] of Object.entries(SLOT_FIELDS)) {
    const field = $(id).closest('.field');
    if (started && !has[slot]) field.dataset.missing = $(id).value ? 'sin-confirmar' : 'falta';
    else delete field.dataset.missing;
  }
}

/** True when the assistant's draft and a set of form values describe the same transfer. */
function sameDraft(d, v) {
  if (!d || !d.recipient) return false;
  const to = d.recipient.id ? v.modo === 'contacto' && v.contacto === d.recipient.id
    : v.modo === 'iban' && v.iban === String(d.recipient.iban || '').replace(/\s+/g, '').toUpperCase() && v.beneficiario === String(d.recipient.name || '').trim();
  return to && v.origen === d.source && v.importe_cent === d.amountCents && v.concepto === String(d.concept || '').trim();
}

function mountVoice() {
  const root = document.getElementById('voz-asistente');
  if (!root) return null;
  let last = '';
  let draft = null;
  let scheduleReview = () => {};
  const api = mountTransferAssistant(root, {
    language: 'es',
    loadContext: async () => {
      const [bank, schema] = await Promise.all([loadBank(), fetch('/api/schema').then(r => r.json())]);
      ({accounts, contacts} = bank);
      fillSelects();
      return {
        accounts: accounts.map(a => ({id: a.id, name: a.nombre, iban: a.iban, balanceCents: a.disponible_cent, aliases: [a.nombre.replace(/^cuenta\s+/i, ''), a.tipo]})),
        contacts: contacts.map(c => ({id: c.id, name: c.nombre, iban: c.iban, aliases: c.alias ? [c.alias] : []})),
        allowConfirm: schema.actions?.transferir?.confirmable_by_voice === true,
      };
    },
    execute: async (draft, key) => {
      if (!pending || pending.via !== 'voz' || form.dataset.step !== 'confirmar' || !sameDraft(draft, pending)) {
        expire();
        if (sameDraft(draft, fields())) scheduleReview();
        throw Object.assign(new Error('Revisa la transferencia en el formulario antes de confirmarla'), {code: 'draft_changed'});
      }
      return (await send(pending, key)).receipt;
    },
    onDraft: (state) => {
      const r = state.slots.recipient;
      const before = draft?.recipient;
      draft = state.slots;
      // Follow the recipient only when the assistant changes it: a later turn (such as the confirmation) must not undo
      // a mode the person chose in the form.
      const who = (x) => x ? (x.id || `${x.iban}|${x.name || ''}`) : '';
      const changedRecipient = r && who(r) !== who(before);
      const wanted = r ? (r.id ? 'contacto' : 'iban') : null;
      if (changedRecipient && mode() !== wanted) { form.querySelector(`input[name="modo"][value="${wanted}"]`).checked = true; syncMode(); }
      if (changedRecipient && wanted === 'iban') $('beneficiario').value = r.name || '';
      markMissing(state);
      if (state.phase === 'ready' && root.dataset.transferPhase === 'ready' && !(pending && sameDraft(state.slots, pending))) scheduleReview();
      if (!['ready', 'executing'].includes(state.phase) && form.dataset.step === 'confirmar' && form.dataset.via === 'voz') { expire(); step('datos'); }
    },
  });
  // When the panel reaches its review, or corrects a draft it already reviewed, the form shows the same data in its
  // confirmation step once the fields have filled.
  let showing = 0;
  scheduleReview = () => {
    const run = ++showing;
    let tries = 0;
    const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
    const show = () => {
      if (run !== showing || root.dataset.transferPhase !== 'ready') return;
      // Wait while a field is still marked as just changed, so the last fill is seen before the summary replaces it.
      if (form.querySelector('[data-transfer-changed]') && ++tries < 40) { setTimeout(show, 80); return; }
      if (!sameDraft(draft, fields()) || !review({focus: false, via: 'voz'}).ok) { if (++tries < 40) setTimeout(show, 80); return; }
      if (matchMedia('(max-width: 900px)').matches) document.dispatchEvent(new CustomEvent('tesela:voice-sheet', {detail: {open: false}}));
      requestAnimationFrame(() => $('transfer-confirm').scrollIntoView({block: 'end', behavior: reduce ? 'auto' : 'smooth'}));
    };
    setTimeout(show, reduce ? 300 : 700);
  };
  new MutationObserver(() => {
    const phase = root.dataset.transferPhase;
    if (phase === last) return;
    last = phase;
    if (phase === 'ready') scheduleReview();
  }).observe(root, {attributes: true, attributeFilter: ['data-transfer-phase']});
  // A field the assistant changes scrolls into the visible part of the page (above the sheet on a phone).
  new MutationObserver((records) => {
    for (const rec of records) if (rec.target.hasAttribute('data-transfer-changed')) rec.target.scrollIntoView({block: 'nearest', behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth'});
  }).observe(form, {attributes: true, subtree: true, attributeFilter: ['data-transfer-changed']});
  return {api, ready: () => root.dataset.transferPhase === 'ready', matches: (t) => root.dataset.transferPhase === 'ready' && sameDraft(draft, t)};
}

if (form) {
  syncMode();
  form.addEventListener('change', (e) => {
    if (e.target.name === 'modo') syncMode();
    if (e.target.id === 'origen') syncDestino();
    if (e.target.id === 'contacto') syncContactIban();
  });
  form.addEventListener('submit', (e) => { e.preventDefault(); review(); });
  $('importe').addEventListener('blur', () => {
    const cents = parseCents($('importe').value);
    if (Number.isFinite(cents) && cents > 0) $('importe').value = amountText(cents);
  });
  $('transfer-back').addEventListener('click', () => { expire(); step('datos'); $('importe').focus(); });
  for (const type of ['input', 'change']) form.addEventListener(type, (e) => { if (e.target.closest('[data-pane="datos"]')) expire(); });
  $('transfer-confirm').addEventListener('click', confirm);
  $('transfer-undo').addEventListener('click', undoLast);
  $('receipt-print').addEventListener('click', () => print());
  await refresh();
  const q = new URLSearchParams(location.search);
  const pre = Object.fromEntries(['origen', 'modo', 'contacto', 'beneficiario', 'iban', 'destino', 'importe', 'concepto'].filter(k => q.get(k)).map(k => [k, q.get(k)]));
  if (Object.keys(pre).length) set(pre);
  voice = mountVoice();
  window.teselaTransfer = {fields, problems, set, review, confirm, undo: undoLast, reset, findContacts, validIban, parseCents,
    accounts: () => accounts, contacts: () => contacts, assistant: voice?.api};
  document.dispatchEvent(new CustomEvent('tesela:transfer-ready'));
}
