// Tesela: shared data access and rendering for the summary, account, movements and contacts pages. Simulated data only.
// Data comes from the project's collections (cuentas, contactos, movimientos); money is stored in integer cents.

const NBSP = ' ';
/** Spanish euro format with thousands always grouped, from cents: 123456 → "1.234,56 €" */
export function euros(cents, {sign = false} = {}) {
  const n = Math.abs(Math.round(cents));
  const int = String(Math.floor(n / 100)).replace(/\B(?=(\d{3})+(?!\d))/g, '.');
  const prefix = cents < 0 ? '−' : (sign && cents > 0 ? '+' : '');
  return `${prefix}${int},${String(n % 100).padStart(2, '0')}${NBSP}€`;
}
export const groupIban = (iban) => String(iban || '').replace(/\s+/g, '').replace(/(.{4})/g, '$1 ').trim();
export const maskIban = (iban) => `${iban.slice(0, 4)} •••• ${iban.slice(-4)}`;
export const esc = (s) => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
const COLORS = ['var(--bar-1)', 'var(--bar-2)', 'var(--bar-3)', 'var(--bar-4)'];
const DATE = new Intl.DateTimeFormat('es-ES', {weekday: 'long', day: 'numeric', month: 'long'});
const dayLabel = (iso) => {
  const today = new Date(); today.setHours(12, 0, 0, 0);
  const d = new Date(iso + 'T12:00:00');
  const diff = Math.round((today - d) / 864e5);
  return diff === 0 ? 'Hoy' : diff === 1 ? 'Ayer' : DATE.format(d);
};

async function collection(name) {
  const response = await fetch(`/api/collections/${name}`);
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.error || `Respuesta ${response.status}`);
  return body.records || [];
}
/** Accounts (sorted, with a colour), contacts and movements (newest first). */
export async function loadBank() {
  const [cuentas, contactos, movimientos] = await Promise.all(['cuentas', 'contactos', 'movimientos'].map(collection));
  const accounts = cuentas.sort((a, b) => (a.orden || 0) - (b.orden || 0)).map((a, i) => ({...a, color: COLORS[i % COLORS.length]}));
  const moves = movimientos.sort((a, b) => (b.fecha || '').localeCompare(a.fecha || '') || String(b.id).localeCompare(String(a.id)));
  return {accounts, contacts: contactos, moves};
}

function renderTotal(accounts) {
  const el = document.getElementById('total-balance');
  if (!el) return;
  const total = accounts.reduce((s, a) => s + a.saldo_cent, 0);
  const [main, cents] = euros(total).split(',');
  el.innerHTML = `${esc(main)}<span class="cents">,${esc(cents)}</span>`;
  const meta = document.getElementById('total-meta');
  if (meta) meta.textContent = `En ${accounts.length} productos · incluye lo dispuesto de la tarjeta`;
  const positive = accounts.filter(a => a.saldo_cent > 0);
  const sum = positive.reduce((s, a) => s + a.saldo_cent, 0) || 1;
  const bar = document.getElementById('split-bar');
  const legend = document.getElementById('split-legend');
  if (bar) bar.innerHTML = positive.map(a => `<span style="flex:${a.saldo_cent / sum};background:${a.color}" title="${esc(a.nombre)}"></span>`).join('');
  if (legend) legend.innerHTML = positive.map(a => `<li><i style="background:${a.color}"></i>${esc(a.nombre)} · ${Math.round(a.saldo_cent / sum * 100)} %</li>`).join('');
}

function renderAccounts(accounts) {
  const list = document.getElementById('accounts');
  if (!list) return;
  if (!accounts.length) { list.innerHTML = '<li class="state"><strong>No tienes cuentas</strong>Cuando abras una aparecerá aquí.</li>'; return; }
  list.innerHTML = accounts.map(a => {
    const foot = a.limite_cent
      ? `<div class="limit" aria-hidden="true"><span style="width:${Math.min(100, Math.max(0, -a.saldo_cent) / a.limite_cent * 100)}%"></span></div>
         <div class="account-foot"><span>Dispuesto de ${euros(a.limite_cent)}</span><span class="mono">${esc(maskIban(a.iban))}</span></div>`
      : `<div class="account-foot"><span>Disponible</span><span class="mono">${esc(maskIban(a.iban))}</span></div>`;
    return `<li><a class="account" href="/cuentas/${encodeURIComponent(a.id)}" data-account="${esc(a.id)}">
      <div class="account-top"><div><div class="account-name">${esc(a.nombre)}</div><div class="account-type">${esc(a.tipo)}</div></div><span class="account-dot" style="background:${a.color}"></span></div>
      <div class="account-balance${a.saldo_cent < 0 ? ' negative' : ''}">${euros(a.saldo_cent)}</div>${foot}</a></li>`;
  }).join('');
}

export function renderMoves(target, moves, accounts, {limit = 0, showAccount = true, empty = null} = {}) {
  const shown = limit ? moves.slice(0, limit) : moves;
  if (!shown.length) {
    target.innerHTML = empty || '<div class="state"><strong>Aún no hay movimientos</strong>Cuando entre o salga dinero aparecerá aquí.</div>';
    return;
  }
  const byId = Object.fromEntries(accounts.map(a => [a.id, a]));
  let html = '<ul class="moves">', day = '';
  for (const m of shown) {
    if (m.fecha !== day) { day = m.fecha; html += `<li class="day">${esc(dayLabel(day))}</li>`; }
    const incoming = m.importe_cent > 0;
    const acc = byId[m.cuenta];
    html += `<li class="move" data-move="${esc(m.id)}"><span class="cat" data-in="${incoming ? 1 : 0}" aria-hidden="true">${esc((m.categoria || m.concepto || '?').slice(0, 2))}</span>
      <div class="move-text"><div class="move-title">${esc(m.concepto)}</div><div class="move-sub">${esc(m.contraparte || '')}${m.categoria ? ' · ' + esc(m.categoria) : ''}</div></div>
      <div class="move-amt${incoming ? ' in' : ''}">${euros(m.importe_cent, {sign: true})}${showAccount && acc ? `<span class="move-acc">${esc(acc.nombre)}</span>` : ''}</div></li>`;
  }
  target.innerHTML = html + '</ul>';
}

export function renderError(target, error, retry) {
  target.innerHTML = `<div class="state error" role="alert"><strong>No se han podido cargar los datos</strong>${esc(error.message)}. <button class="btn" type="button" data-retry>Reintentar</button></div>`;
  target.querySelector('[data-retry]')?.addEventListener('click', retry);
}
const loading = '<div class="state"><div class="skeleton" style="width:60%;margin:0 auto 12px"></div><div class="skeleton" style="width:40%;margin:0 auto"></div></div>';

async function summary() {
  const movesEl = document.getElementById('recent-moves');
  if (!movesEl) return;
  movesEl.innerHTML = loading;
  try {
    const {accounts, moves} = await loadBank();
    renderTotal(accounts);
    renderAccounts(accounts);
    renderMoves(movesEl, moves, accounts, {limit: Number(movesEl.dataset.limit) || 0});
  } catch (error) {
    renderError(movesEl, error, summary);
    const meta = document.getElementById('total-meta');
    if (meta) meta.textContent = 'No se han podido calcular los saldos.';
    const total = document.getElementById('total-balance');
    if (total) total.textContent = '—';
  }
}

function searchable(input, list, draw) {
  input?.addEventListener('input', draw);
  draw();
}

async function accountPage() {
  const root = document.querySelector('[data-account-page]');
  if (!root) return;
  const list = document.getElementById('acc-moves');
  list.innerHTML = loading;
  try {
    const {accounts, moves} = await loadBank();
    const acc = accounts.find(a => a.id === root.getAttribute('data-account-page'));
    if (!acc) {
      root.innerHTML = `<a class="back" href="/">← Resumen</a><div class="state error" role="alert"><strong>Esta cuenta no existe</strong>Vuelve al resumen para ver tus cuentas.</div>`;
      list.closest('section')?.remove();
      return;
    }
    document.title = `${acc.nombre} · Tesela`;
    document.getElementById('acc-name').textContent = acc.nombre;
    document.getElementById('acc-type').textContent = acc.limite_cent ? `${acc.tipo} · ${euros(acc.disponible_cent)} disponibles` : acc.tipo;
    document.getElementById('acc-iban').textContent = groupIban(acc.iban);
    document.getElementById('acc-transfer').href = `/transferir?origen=${encodeURIComponent(acc.id)}`;
    const bal = document.getElementById('acc-balance');
    const [main, cents] = euros(acc.saldo_cent).split(',');
    bal.innerHTML = `${esc(main)}<span class="cents">,${esc(cents)}</span>`;
    bal.classList.toggle('negative', acc.saldo_cent < 0);
    document.getElementById('copy-iban').addEventListener('click', async (e) => {
      try { await navigator.clipboard.writeText(acc.iban); e.target.textContent = 'IBAN copiado'; } catch (err) { e.target.textContent = 'No se ha podido copiar'; }
    });
    const mine = moves.filter(m => m.cuenta === acc.id);
    const search = document.getElementById('acc-search');
    searchable(search, list, () => {
      const q = search.value.trim().toLowerCase();
      const shown = q ? mine.filter(m => `${m.concepto} ${m.contraparte} ${m.categoria}`.toLowerCase().includes(q)) : mine;
      renderMoves(list, shown, accounts, {showAccount: false,
        empty: q ? `<div class="state"><strong>Sin resultados</strong>Ningún movimiento coincide con «${esc(search.value.trim())}».</div>` : null});
    });
  } catch (error) { renderError(list, error, accountPage); }
}

async function movesPage() {
  const list = document.getElementById('all-moves');
  if (!list) return;
  list.innerHTML = loading;
  try {
    const {accounts, moves} = await loadBank();
    const filter = document.getElementById('moves-account');
    filter.innerHTML = '<option value="">Todas las cuentas</option>' + accounts.map(a => `<option value="${esc(a.id)}">${esc(a.nombre)}</option>`).join('');
    const search = document.getElementById('moves-search');
    const draw = () => {
      const q = search.value.trim().toLowerCase();
      const shown = moves.filter(m => (!filter.value || m.cuenta === filter.value) && (!q || `${m.concepto} ${m.contraparte} ${m.categoria}`.toLowerCase().includes(q)));
      renderMoves(list, shown, accounts, {empty: `<div class="state"><strong>Sin resultados</strong>Prueba con otro texto o con todas las cuentas.</div>`});
    };
    filter.addEventListener('change', draw);
    searchable(search, list, draw);
  } catch (error) { renderError(list, error, movesPage); }
}

async function contactsPage() {
  const list = document.getElementById('contacts');
  if (!list) return;
  list.innerHTML = `<li>${loading}</li>`;
  try {
    const {contacts} = await loadBank();
    const initials = (n) => n.split(/\s+/).slice(0, 2).map(w => w[0]).join('');
    const search = document.getElementById('contact-search');
    searchable(search, list, () => {
      const q = (search.value || '').trim().toLowerCase().replace(/\s+/g, '');
      const shown = contacts.filter(c => !q || `${c.nombre}${c.alias || ''}`.toLowerCase().replace(/\s+/g, '').includes(q) || c.iban.toLowerCase().includes(q));
      list.innerHTML = shown.length ? shown.map(c => `<li class="contact" data-contact="${esc(c.id)}"><span class="avatar" aria-hidden="true">${esc(initials(c.nombre))}</span>
        <div class="contact-main"><div class="contact-name">${esc(c.nombre)}</div><div class="contact-note">${esc(c.nota || '')}</div><div class="mono contact-iban">${esc(groupIban(c.iban))}</div></div>
        <a class="btn" href="/transferir?contacto=${encodeURIComponent(c.id)}" aria-label="Enviar dinero a ${esc(c.nombre)}">Enviar</a></li>`).join('')
        : `<li class="state"><strong>Ningún contacto coincide</strong>Puedes enviar dinero a cualquier IBAN desde <a href="/transferir?modo=iban">Transferir</a>.</li>`;
    });
  } catch (error) { renderError(list, error, contactsPage); }
}

function navAndTheme() {
  const here = location.pathname.replace(/\/+$/, '') || '/';
  for (const a of document.querySelectorAll('[data-nav]')) {
    const nav = a.getAttribute('data-nav');
    if (nav === here || (nav !== '/' && here.startsWith(nav)) || (nav === '/' && here.startsWith('/cuentas'))) a.setAttribute('aria-current', 'page');
  }
  document.getElementById('theme-toggle')?.addEventListener('click', () => {
    const root = document.documentElement;
    const dark = root.dataset.theme === 'dark' || (root.dataset.theme === 'auto' && matchMedia('(prefers-color-scheme: dark)').matches);
    root.dataset.theme = dark ? 'light' : 'dark';
    try { localStorage.setItem('tesela-theme', root.dataset.theme); } catch (e) { /* private mode */ }
  });
}

navAndTheme();
summary();
accountPage();
movesPage();
contactsPage();
