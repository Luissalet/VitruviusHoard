"""HTML page of a generated instrument: one static file whose form is built from instrument.json in the browser."""

PAGE = r'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{name}}</title>
<style>
*{box-sizing:border-box}body{margin:0;background:#f6f5f0;color:#1f2a2c;font:16px/1.6 system-ui,sans-serif}
header,main{max-width:1000px;margin:auto;padding:16px clamp(16px,4vw,40px)}header{display:flex;justify-content:space-between;flex-wrap:wrap;gap:12px;border-bottom:1px solid #c8cec9}
h1{font:clamp(28px,4vw,46px)/1.15 Georgia,serif;margin:14px 0}h2{font:22px/1.3 Georgia,serif;margin:24px 0 10px}a{color:#1f4e63}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,220px),1fr));gap:16px;margin:16px 0}.field{display:flex;flex-direction:column;gap:6px}label{font-weight:600}
input,select,button{font:inherit;min-height:44px;padding:6px 10px;border:1px solid #6d7b78;background:#fff;color:#1f2a2c}input[type=checkbox]{width:24px;height:24px;min-height:24px}
button{background:#1f4e63;color:#fff;border-color:#1f4e63;cursor:pointer}button.plain{background:#fff;color:#1f4e63}
.table-wrap{overflow-x:auto}table{width:100%;min-width:480px;border-collapse:collapse;background:#fff}th,td{text-align:left;padding:10px;border-bottom:1px solid #d5dad7;vertical-align:middle}
output{font-weight:700;font-variant-numeric:tabular-nums}.problem{background:#f9e3e0;color:#7a1f14;padding:10px 12px}.cols{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,300px),1fr));gap:24px}
fieldset{border:1px solid #c8cec9;padding:8px 16px;margin:0}legend{font-weight:700;padding:0 6px}.unit{color:#4a5a57}
a:focus-visible,button:focus-visible,input:focus-visible,select:focus-visible{outline:3px solid #1f4e63;outline-offset:2px}@media(prefers-reduced-motion:reduce){*{scroll-behavior:auto}}
</style></head><body>
<header><strong>{{name}}</strong><nav aria-label="Instrument"><a href="/">Instrument</a> <a href="/explain" id="explain-link" hidden>Worked example</a> <a href="/api/spec">Spec</a></nav></header>
<main><h1>{{name}}</h1><p id="description"></p><div id="app"></div><p id="status" role="status" aria-live="polite" class="problem" hidden></p></main>
<script type="application/json" id="spec">{{spec_json}}</script>
<script>
const spec = JSON.parse(document.getElementById('spec').textContent);
const app = document.getElementById('app'), status = document.getElementById('status');
document.getElementById('description').textContent = spec.description || '';
if ((spec.views || []).includes('explainer')) document.getElementById('explain-link').hidden = false;
const el = (tag, attrs = {}, ...kids) => { const n = document.createElement(tag); for (const [k, v] of Object.entries(attrs)) { if (k === 'text') n.textContent = v; else if (v !== false && v != null) n.setAttribute(k, v === true ? '' : v); } kids.forEach(k => n.append(k)); return n; };
const fmt = o => (typeof o.value === 'number' ? o.value.toLocaleString(undefined, {maximumFractionDigits: 10}) : String(o.value)) + (o.unit ? ' ' + o.unit : '');
function control(f, value, id) {
  const a = {id, name: f.name};
  if (f.type === 'choice') { const s = el('select', a); f.choices.forEach(c => s.append(el('option', {value: c, text: c, selected: c === value}))); return s; }
  if (f.type === 'boolean') return el('input', {...a, type: 'checkbox', checked: value === true});
  if (f.type === 'text') return el('input', {...a, type: 'text', value: value ?? ''});
  return el('input', {...a, type: 'number', inputmode: 'decimal', step: f.step ?? (f.type === 'integer' ? 1 : 'any'), min: f.min, max: f.max, value: value ?? ''});
}
function read(root, prefix) {
  const out = {};
  for (const f of spec.inputs) {
    const n = root.querySelector('#' + prefix + f.name); if (!n) continue;
    if (f.type === 'boolean') out[f.name] = n.checked;
    else if (n.value === '') continue;
    else out[f.name] = (f.type === 'number' || f.type === 'integer') ? Number(n.value) : n.value;
  }
  return out;
}
function fieldset(title, prefix, values) {
  const fs = el('fieldset', {}, el('legend', {text: title}));
  const grid = el('div', {class: 'grid'});
  for (const f of spec.inputs) {
    const label = el('label', {for: prefix + f.name, text: f.label + (f.unit ? ' (' + f.unit + ')' : '')});
    grid.append(el('div', {class: 'field'}, label, control(f, values[f.name] ?? f.default, prefix + f.name)));
  }
  fs.append(grid); return fs;
}
async function post(path, body) {
  const r = await fetch(path, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
  const j = await r.json(); if (!r.ok) throw new Error(j.error || 'Request failed'); return j;
}
const say = m => { status.hidden = !m; status.textContent = m || ''; };
function outputsList(result) {
  const dl = el('dl');
  result.outputs.forEach(o => dl.append(el('dt', {text: o.label}), el('dd', {}, el('output', {'data-name': o.name, text: fmt(o)}))));
  (result.invariants || []).filter(i => !i.holds).forEach(i => dl.append(el('dt', {text: 'Invariant violated'}), el('dd', {text: i.name})));
  return dl;
}
function debounce(fn) { let t; return () => { clearTimeout(t); t = setTimeout(fn, 150); }; }
const kind = spec.kind || 'calculator';
if (kind === 'calculator') {
  const form = el('form', {}, fieldset('Inputs', 'a-', {})), out = el('section', {'aria-live': 'polite'}, el('h2', {text: 'Results'}));
  app.append(form, out);
  const run = debounce(async () => { try { const r = await post('/api/compute', read(form, 'a-')); say(''); out.replaceChildren(el('h2', {text: 'Results'}), outputsList(r)); } catch (e) { say(e.message); } });
  form.addEventListener('input', run); form.addEventListener('submit', e => { e.preventDefault(); run(); }); run();
} else if (kind === 'comparator') {
  const cols = el('div', {class: 'cols'}), a = fieldset('Option A', 'a-', spec.rows[0] || {}), b = fieldset('Option B', 'b-', spec.rows[1] || {});
  const out = el('section', {'aria-live': 'polite'}, el('h2', {text: 'Comparison'}));
  cols.append(a, b); app.append(cols, out);
  const run = debounce(async () => {
    try {
      const [ra, rb] = await Promise.all([post('/api/compute', read(a, 'a-')), post('/api/compute', read(b, 'b-'))]); say('');
      const t = el('table', {}, el('thead', {}, el('tr', {}, ...['Output', 'A', 'B', 'B minus A'].map(h => el('th', {scope: 'col', text: h})))));
      const body = el('tbody');
      ra.outputs.forEach((o, i) => { const p = rb.outputs[i]; const d = typeof o.value === 'number' ? Math.round((p.value - o.value) * 1e10) / 1e10 : ''; body.append(el('tr', {}, el('th', {scope: 'row', text: o.label}), el('td', {text: fmt(o)}), el('td', {text: fmt(p)}), el('td', {text: String(d)}))); });
      t.append(body); out.replaceChildren(el('h2', {text: 'Comparison'}), el('div', {class: 'table-wrap'}, t));
    } catch (e) { say(e.message); }
  });
  cols.addEventListener('input', run); run();
} else {
  let rows = spec.rows.length ? spec.rows.map(r => ({...r})) : [Object.fromEntries(spec.inputs.filter(f => 'default' in f).map(f => [f.name, f.default]))];
  const editable = kind === 'editor', holder = el('div', {class: 'table-wrap'}), tools = el('p');
  app.append(holder, tools);
  async function draw() {
    let results = []; try { results = (await post('/api/table', {rows})).rows; say(''); } catch (e) { say(e.message); }
    const head = el('tr', {}, ...spec.inputs.map(f => el('th', {scope: 'col', text: f.label + (f.unit ? ' (' + f.unit + ')' : '')})), ...spec.outputs.map(o => el('th', {scope: 'col', text: o.label + (o.unit ? ' (' + o.unit + ')' : '')})), ...(editable ? [el('th', {scope: 'col', text: 'Row'})] : []));
    const body = el('tbody');
    rows.forEach((row, i) => {
      const tr = el('tr'); const res = results[i] || {};
      spec.inputs.forEach(f => { const td = el('td'); if (editable) { const c = control(f, row[f.name] ?? f.default, 'r' + i + '-' + f.name); c.setAttribute('aria-label', f.label + ' row ' + (i + 1)); c.addEventListener('change', () => { row[f.name] = f.type === 'boolean' ? c.checked : (f.type === 'number' || f.type === 'integer') ? (c.value === '' ? undefined : Number(c.value)) : c.value; draw(); }); td.append(c); } else td.textContent = String(row[f.name] ?? (res.inputs ? res.inputs[f.name] : '') ?? ''); tr.append(td); });
      spec.outputs.forEach((o, k) => tr.append(el('td', res.ok ? {} : {class: 'problem'}, res.ok ? el('output', {'data-name': o.name, text: fmt(res.outputs[k])}) : (k === 0 ? (res.error || '') : ''))));
      if (editable) { const rm = el('button', {type: 'button', class: 'plain', text: 'Remove', 'aria-label': 'Remove row ' + (i + 1)}); rm.addEventListener('click', () => { rows.splice(i, 1); draw(); }); tr.append(el('td', {}, rm)); }
      body.append(tr);
    });
    holder.replaceChildren(el('table', {}, el('thead', {}, head), body));
  }
  if (editable) {
    const add = el('button', {type: 'button', text: 'Add row'}); add.addEventListener('click', () => { rows.push(Object.fromEntries(spec.inputs.filter(f => 'default' in f).map(f => [f.name, f.default]))); draw(); });
    const save = el('button', {type: 'button', class: 'plain', text: 'Download rows as JSON'}); save.addEventListener('click', () => { const a = el('a', {href: URL.createObjectURL(new Blob([JSON.stringify(rows, null, 2)], {type: 'application/json'})), download: 'rows.json'}); a.click(); });
    tools.append(add, ' ', save);
  }
  draw();
}
</script></body></html>
'''
