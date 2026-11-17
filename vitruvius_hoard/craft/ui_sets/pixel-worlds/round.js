// Round: a loading bar that is the bar of a tavern. Seven regulars empty their cups in turn as the task loads.
// At 100% the empties go up together and come down hard.
// Everything is painted in code, smooth, at 476 x 160, lit per character, then crushed to 49 colours every frame. No assets, no network.
//
// One file, no dependencies. Load it with a script tag and put <round-bar></round-bar> where the loading bar goes.
// Give it value="0.4" or call el.set(0.4) with the task's progress, 0 to 1. Left alone it plays a demo load on a loop.
// It fires "round:done" once each time real progress reaches 1.
(() => {
'use strict';
if (customElements.get('round-bar')) return;   // loaded twice: the first one stands

function mulberry(seed) { let a = seed >>> 0; return () => { a = (a + 0x6D2B79F5) >>> 0; let t = a; t = Math.imul(t ^ (t >>> 15), t | 1); t ^= t + Math.imul(t ^ (t >>> 7), t | 61); return ((t ^ (t >>> 14)) >>> 0) / 4294967296; }; }
let rnd = mulberry(5);
function hash(x, y) { let h = (x * 374761393 + y * 668265263) | 0; h = (h ^ (h >>> 13)) * 1274126177 | 0; return ((h ^ (h >>> 16)) >>> 0) / 4294967296; }
function vnoise(x, y) { const xi = Math.floor(x), yi = Math.floor(y), fx = x - xi, fy = y - yi, sx = fx * fx * (3 - 2 * fx), sy = fy * fy * (3 - 2 * fy), l = (a, b, t) => a + (b - a) * t; return l(l(hash(xi, yi), hash(xi + 1, yi), sx), l(hash(xi, yi + 1), hash(xi + 1, yi + 1), sx), sy); }
const fbm = (x, y) => 0.55 * vnoise(x, y) + 0.3 * vnoise(x * 2.1, y * 2.1 + 7) + 0.15 * vnoise(x * 4.3, y * 4.3 + 19);


// The grim cut: same bar, same mechanic, lit only by the hearth, three candle stubs and the moon.
const W = 476, H = 160, CT = 124;
const PAL = [
  '#07060b', '#0e0c14', '#16131e', '#201b28', '#2b2533', '#383040',
  '#1c1210', '#2c1a15', '#40241a', '#58301f', '#754026', '#96552e', '#b9713a', '#d99448', '#f0bb62', '#fbe09a', '#fff6d0',
  '#3a1414', '#5c1c18', '#8a2a1c', '#b8431f', '#e0692a',
  '#4a2e28', '#6e4438', '#946050', '#b98470', '#d8ac94',
  '#10182a', '#1a2740', '#27395a', '#3a5078', '#55709a', '#7e97b8', '#aebfd4', '#dfe7f0',
  '#141c18', '#1f2c24', '#2e4034', '#44584a', '#647a66',
  '#2a2238', '#40345a', '#5c4a7a',
  '#4a4a52', '#6c6c76', '#96969e', '#c4c4c8',
  '#3aa890', '#8fe6c8',
];
const soft = document.createElement('canvas'); soft.width = W; soft.height = H;
let g = soft.getContext('2d', { willReadFrequently: true });
const POOL = [];
function scratch() { const c = POOL.pop() || Object.assign(document.createElement('canvas'), { width: W, height: H }); const x = c.getContext('2d', { willReadFrequently: true }); x.setTransform(1, 0, 0, 1, 0, 0); x.globalAlpha = 1; x.globalCompositeOperation = 'source-over'; x.filter = 'none'; x.clearRect(0, 0, W, H); return c; }
const release = (...cs) => { for (const c of cs) if (c) POOL.push(c); };
const rc = (x, y, w, h, c) => { g.fillStyle = c; g.fillRect(x, y, w, h); };
function glow(x, y, r, rgb, a) { const gr = g.createRadialGradient(x, y, 0, x, y, r); gr.addColorStop(0, `rgba(${rgb},${a})`); gr.addColorStop(1, `rgba(${rgb},0)`); g.fillStyle = gr; g.fillRect(x - r, y - r, r * 2, r * 2); }
const lin = (x0, y0, x1, y1, ...st) => { const gr = g.createLinearGradient(x0, y0, x1, y1); st.forEach((c, i) => gr.addColorStop(i / (st.length - 1), c)); return gr; };
const rad = (x, y, r, ...st) => { const gr = g.createRadialGradient(x, y, 0.5, x, y, r); st.forEach((c, i) => gr.addColorStop(i / (st.length - 1), c)); return gr; };
const ell = (x, y, rx, ry, c, a0 = 0, a1 = 7, rot = 0) => { g.fillStyle = c; g.beginPath(); g.ellipse(x, y, rx, ry, rot, a0, a1); g.fill(); };
const fillP = (c, fn) => { g.fillStyle = c; g.beginPath(); fn(g); g.fill(); };
const strokeP = (c, w, fn) => { g.strokeStyle = c; g.lineWidth = w; g.lineCap = 'round'; g.lineJoin = 'round'; g.beginPath(); fn(g); g.stroke(); };
const poly = (pts, c) => fillP(c, (k) => pts.forEach(([x, y], i) => (i ? k.lineTo(x, y) : k.moveTo(x, y))));
function layer(draw) { const L = scratch(), prev = g; g = L.getContext('2d'); g.save(); draw(); g.restore(); g = prev; return L; }

// Lighting. Each figure is painted in its own colours, then multiplied by a light map:
// a cold dark ambient, plus the things in the room that actually give light.
const HX = 372, CANDLES = [90, 200, 341];
const AMBIENT = 'rgb(66,60,98)';
const LIGHTS = [
  ...CANDLES.map((x) => [x, CT - 6, 104, '255,186,110', 1]),
  [HX + 52, CT - 12, 215, '255,128,48', 0.8, 'hearth'],
  [166, 58, 130, '96,136,255', 0.42],                      // the moon, through the lancets
];
function light(L, c, arm) {
  const x0 = Math.max(0, Math.floor(c.cx - 80)), bw = Math.min(W - x0, 160), k = L.getContext('2d');
  const M = scratch(), m = M.getContext('2d');
  m.fillStyle = AMBIENT; m.fillRect(x0, 0, bw, H);
  m.globalCompositeOperation = 'lighter';
  for (const [lx, ly, r, rgb, a, tag] of LIGHTS) {
    const s = a * (tag === 'hearth' ? (c.hearth ?? 1) : (c.lit ?? 1)); if (s <= 0 || Math.abs(lx - c.cx) > r + 80) continue;
    const gr = m.createRadialGradient(lx, ly, 2, lx, ly, r); gr.addColorStop(0, `rgba(${rgb},${s})`); gr.addColorStop(0.46, `rgba(${rgb},${s * 0.5})`); gr.addColorStop(1, `rgba(${rgb},0)`);
    m.fillStyle = gr; m.fillRect(x0, 0, bw, H);
  }
  const up = m.createLinearGradient(0, CT - 46, 0, CT + 4); up.addColorStop(0, 'rgba(255,160,84,0)'); up.addColorStop(1, `rgba(255,160,84,${c.backlit ? 0.02 : 0.3})`);   // bounce off the bar
  m.fillStyle = up; m.fillRect(x0, 0, bw, H);
  m.globalCompositeOperation = 'destination-in'; m.drawImage(L, x0, 0, bw, H, x0, 0, bw, H);
  k.globalCompositeOperation = 'multiply'; k.drawImage(M, x0, 0, bw, H, x0, 0, bw, H); release(M);
  // rims: fire on the edges that face the hearth, moon on the ones that don't
  k.globalCompositeOperation = 'source-atop';
  const band = (dx, dy, col) => { const R = scratch(), r = R.getContext('2d'); r.drawImage(L, x0, 0, bw, H, x0, 0, bw, H); r.globalCompositeOperation = 'source-in'; r.fillStyle = col; r.fillRect(x0, 0, bw, H); r.globalCompositeOperation = 'destination-out'; r.drawImage(L, x0, 0, bw, H, x0 + dx, dy, bw, H); k.drawImage(R, x0, 0, bw, H, x0, 0, bw, H); release(R); };
  const warm = 0.22 + 0.78 * Math.pow(c.cx / W, 1.3);
  if (c.backlit) { band(-1.3, 0.3, 'rgba(255,196,110,1)'); band(1.3, 0.3, 'rgba(255,170,80,1)'); band(0, 1.5, 'rgba(255,224,150,.95)'); }
  else { band(-2.3, 0.7, `rgba(255,150,64,${0.95 * warm})`); if (!arm) band(2, 0.9, `rgba(130,170,240,${0.8 * (1 - warm * 0.6)})`); }
  k.globalCompositeOperation = 'source-over';
}


// ───────── the room ─────────
function flame(x, y, s) { glow(x, y - 2 * s, 9 * s, '255,170,70', 0.6); fillP('#f0bb62', (k) => { k.moveTo(x - 1.4 * s, y); k.quadraticCurveTo(x - 2 * s, y - 3 * s, x, y - 6 * s); k.quadraticCurveTo(x + 2 * s, y - 3 * s, x + 1.4 * s, y); }); ell(x, y - 1.6 * s, 0.8 * s, 1.6 * s, '#fff6d0'); }
const hearthPath = (k) => { k.moveTo(HX + 16, CT); k.lineTo(HX + 16, 88); k.quadraticCurveTo(HX + 52, 54, HX + 88, 88); k.lineTo(HX + 88, CT); };
function room() {
  g.fillStyle = lin(0, 0, 0, CT, '#050409', '#0e0b13', '#17111a'); g.fillRect(0, 0, W, H);
  // rough stone
  for (let y = 30; y < CT; y += 12) for (let x = ((y / 12 | 0) % 2 ? -9 : 4); x < W; x += 24 + (hash(x, y) * 10 | 0)) { const w = 22 + hash(y, x) * 9; rc(x, y, w, 11, `rgba(${hash(x, y + 3) < 0.5 ? '56,46,60' : '34,28,40'},.45)`); rc(x, y, w, 1, 'rgba(120,104,120,.16)'); }
  // lancet window: the citadel, small and far away
  const wx = 132, wy = 34, ww = 30, wh = 62;
  for (const ox of [0, 38]) {
    fillP('#030306', (k) => { k.moveTo(wx + ox - 4, wy + wh + 3); k.lineTo(wx + ox - 4, wy + 16); k.quadraticCurveTo(wx + ox + ww / 2, wy - 26, wx + ox + ww + 4, wy + 16); k.lineTo(wx + ox + ww + 4, wy + wh + 3); });
    g.save(); g.beginPath(); g.moveTo(wx + ox, wy + wh); g.lineTo(wx + ox, wy + 17); g.quadraticCurveTo(wx + ox + ww / 2, wy - 18, wx + ox + ww, wy + 17); g.lineTo(wx + ox + ww, wy + wh); g.clip();
    g.fillStyle = lin(0, wy - 6, 0, wy + wh, '#070a1c', '#13204e', '#2c3a78'); g.fillRect(wx + ox, wy - 12, ww, wh + 12);
    for (let i = 0; i < 26; i++) rc(wx + ox + rnd() * ww, wy - 6 + rnd() * 40, 1, 1, `rgba(220,232,255,${0.3 + rnd() * 0.6})`);
    for (let x = wx + ox; x < wx + ox + ww; x++) { const y = wy + 2 + 5 * Math.sin(x * 0.09) + 2 * Math.sin(x * 0.23), i = 0.4 + 0.6 * vnoise(x * 0.14, 2); g.fillStyle = lin(0, y, 0, y + 20, 'rgba(70,200,170,0)', `rgba(70,200,170,${0.5 * i})`, 'rgba(110,60,170,0)'); g.fillRect(x, y, 1, 20); }
    if (ox) { const mx = wx + ox + 14, my = wy + 26; glow(mx, my, 26, '170,198,240', 0.5); ell(mx, my, 9, 9, rad(mx - 3, my - 3, 10, '#ffffff', '#dfe7f0', '#9db6dc')); for (const [dx, w, h] of [[-8, 2, 9], [7, 2, 11], [-4, 2, 15], [3, 2, 17], [0, 3, 22]]) { rc(mx + dx - w / 2, my + 12 - h, w, h, '#070a18'); poly([[mx + dx - w / 2 - 1, my + 12 - h], [mx + dx + w / 2 + 1, my + 12 - h], [mx + dx, my + 12 - h - w * 2.4]], '#070a18'); } fillP('#0c1226', (k) => { k.moveTo(mx - 15, my + 12); k.lineTo(mx + 15, my + 12); k.lineTo(mx + 3, my + 24); k.lineTo(mx - 6, my + 22); }); }
    for (let x = wx + ox; x < wx + ox + ww; x++) rc(x, wy + wh - 10 - 7 * fbm((x + ox) * 0.06, 4), 1, 30, '#101a3c');
    for (let y = wy - 10; y < wy + wh; y += 9) rc(wx + ox, y, ww, 1, 'rgba(3,3,6,.9)'); rc(wx + ox + ww / 2 - 0.5, wy - 14, 1, wh + 14, 'rgba(3,3,6,.9)');
    g.restore();
  }
  rc(wx - 8, wy + wh + 2, 84, 4, '#1a1418'); rc(wx - 8, wy + wh + 2, 84, 1, 'rgba(120,150,210,.4)');
  glow(wx + 34, wy + 40, 80, '60,90,180', 0.2);
  // posts, a low beam, and the dark above it
  for (const x of [0, 118, 222, 356, W]) { g.fillStyle = lin(x - 6, 0, x + 6, 0, '#2a1a18', '#0e0a0e'); g.fillRect(x - 6, 0, 12, CT); rc(x - 6, 0, 1, CT, 'rgba(120,80,60,.3)'); }
  g.fillStyle = lin(0, 16, 0, 30, '#2c1b18', '#0e0a0e'); g.fillRect(0, 16, W, 14); rc(0, 16, W, 1, 'rgba(140,90,60,.3)'); rc(0, 30, W, 2, 'rgba(0,0,0,.7)');
  rc(0, 0, W, 16, '#040306');
  // chains, a hook, a cold iron ring with two guttering stubs
  for (const [x, len] of [[92, 22], [250, 15], [318, 30]]) { for (let y = 30; y < 30 + len; y += 3) rc(x, y, 1, 2, '#4a4a52'); strokeP('#6c6c76', 1.2, (k) => k.arc(x + 0.5, 32 + len, 3, 0.3, 3.8)); }
  ell(284, 44, 22, 4.6, '#050409'); ell(284, 43, 22, 4.2, lin(262, 0, 306, 0, '#16131e', '#4a4a52', '#16131e')); ell(284, 42.5, 17, 2.6, '#050409');
  strokeP('#050409', 1, (k) => { k.moveTo(284, 18); k.lineTo(265, 42); k.moveTo(284, 18); k.lineTo(303, 42); });
  for (const dx of [-17, 14]) { rc(284 + dx - 1, 37, 2.4, 5, '#b98470'); flame(284 + dx, 37, 0.6); }
  for (const [x, len, col] of [[30, 16, '#2e4034'], [40, 12, '#44584a'], [196, 14, '#2e4034'], [206, 10, '#1f2c24'], [404, 9, '#2e4034']]) { rc(x, 30, 1, 4, '#2c1a15'); fillP(col, (k) => { k.moveTo(x - 3.4, 34); k.lineTo(x + 4.4, 34); k.lineTo(x + 2, 34 + len); k.lineTo(x - 2, 34 + len - 3); }); }
  // shelves: jars, bottles, a skull
  for (const y of [60, 86]) {
    g.fillStyle = lin(0, y, 0, y + 4, '#40241a', '#16100f'); g.fillRect(8, y, 100, 4); rc(8, y, 100, 1, 'rgba(160,100,60,.3)');
    for (let x = 12; x < 102; x += 9 + (hash(x, y) * 4 | 0)) { const h = 8 + hash(x, y + 1) * 11, w = 4 + (hash(y, x) * 3 | 0), col = ['#1f2c24', '#3a1414', '#1a2740', '#40241a', '#2a2238'][(x + y) % 5]; g.fillStyle = lin(x, 0, x + w, 0, col, '#07060b'); g.fillRect(x, y - h, w, h); rc(x + w / 2 - 1, y - h - 3, 2, 3, col); rc(x + 1, y - h + 2, 1, h - 5, 'rgba(180,200,230,.28)'); }
  }
  ell(88, 80, 5.5, 5, '#c4c4c8'); rc(84.5, 82, 7, 4, '#96969e'); ell(86, 80, 1.5, 1.7, '#07060b'); ell(90, 80, 1.5, 1.7, '#07060b');
  // the hearth: the only real light in the room
  const hx = 372, hy = 52;
  g.fillStyle = lin(hx, 0, hx + 104, 0, '#201b28', '#383040', '#16131e'); g.fillRect(hx, hy, 104, CT - hy);
  for (let y = hy; y < CT; y += 11) for (let x = hx + ((y / 11 | 0) % 2 ? 0 : 9); x < hx + 104; x += 18) { rc(x, y, 17, 10, `rgba(${hash(x, y) < 0.5 ? '84,70,84' : '44,36,50'},.5)`); rc(x, y, 17, 1, 'rgba(230,150,90,.22)'); rc(x, y + 10, 18, 1, 'rgba(0,0,0,.7)'); }
  fillP('#040306', hearthPath); strokeP('rgba(255,150,70,.42)', 1.4, hearthPath); strokeP('rgba(5,4,9,.8)', 1, (k) => { k.moveTo(hx + 14.5, CT); k.lineTo(hx + 14.5, hy + 35); k.quadraticCurveTo(hx + 52, hy, hx + 89.5, hy + 35); k.lineTo(hx + 89.5, CT); });
  g.fillStyle = lin(0, hy - 8, 0, hy, '#40241a', '#16100f'); g.fillRect(hx - 6, hy - 8, 116, 8); rc(hx - 6, hy - 8, 116, 1, 'rgba(230,140,70,.5)');
  // a horned skull over the mantel
  const sx = hx + 52, sy = hy - 24;
  for (const s of [-1, 1]) fillP(lin(sx, 0, sx + s * 26, 0, '#b98470', '#4a2e28'), (k) => { k.moveTo(sx + s * 6, sy - 3); k.bezierCurveTo(sx + s * 18, sy - 4, sx + s * 27, sy - 12, sx + s * 25, sy - 22); k.bezierCurveTo(sx + s * 22, sy - 12, sx + s * 15, sy - 8, sx + s * 6, sy + 1); });
  fillP(lin(sx - 8, 0, sx + 8, 0, '#96969e', '#d8ac94', '#6e4438'), (k) => { k.moveTo(sx - 8, sy - 6); k.quadraticCurveTo(sx, sy - 11, sx + 8, sy - 6); k.lineTo(sx + 5, sy + 6); k.lineTo(sx + 3, sy + 14); k.lineTo(sx - 3, sy + 14); k.lineTo(sx - 5, sy + 6); });
  ell(sx - 3.6, sy - 1, 2.2, 2.6, '#07060b'); ell(sx + 3.6, sy - 1, 2.2, 2.6, '#07060b'); rc(sx - 1, sy + 6, 2, 4, '#07060b');
  // a torn banner
  fillP(lin(322, 0, 346, 0, '#3a1414', '#5c1c18', '#1c1210'), (k) => { k.moveTo(322, 30); k.lineTo(346, 30); k.lineTo(346, 80); k.lineTo(341, 72); k.lineTo(337, 84); k.lineTo(332, 70); k.lineTo(327, 82); k.lineTo(322, 74); });
  strokeP('rgba(216,172,148,.55)', 1.2, (k) => { k.moveTo(334, 40); k.lineTo(334, 60); k.moveTo(328, 46); k.lineTo(340, 46); k.arc(334, 52, 5, 0, 7); });
  // moonlight through the lancets
  g.save(); g.globalCompositeOperation = 'lighter';
  for (const ox of [0, 38]) fillP(lin(0, wy, 0, CT, 'rgba(70,100,190,.2)', 'rgba(70,100,190,0)'), (k) => { k.moveTo(wx + ox, wy); k.lineTo(wx + ox + ww, wy); k.lineTo(wx + ox + ww + 90, CT); k.lineTo(wx + ox + 40, CT); });
  g.restore();
  g.fillStyle = 'rgba(5,4,9,.34)'; g.fillRect(0, 0, W, CT);
}
function counterBase() {
  g.fillStyle = lin(0, CT, 0, CT + 9, '#b9713a', '#754026', '#40241a'); g.fillRect(0, CT, W, 9);
  for (let i = 0; i < 90; i++) rc(rnd() * W, CT + 1 + rnd() * 7, 6 + rnd() * 30, 1, `rgba(${rnd() < 0.4 ? '250,200,130' : '20,10,8'},.24)`);
  for (const [x, w] of [[52, 9], [150, 6], [262, 11], [388, 7]]) strokeP('rgba(10,6,6,.6)', 0.8, (k) => { k.moveTo(x, CT + 2); k.lineTo(x + w, CT + 6); });
  g.fillStyle = lin(0, 0, W, 0, 'rgba(5,4,9,.5)', 'rgba(5,4,9,.2)', 'rgba(5,4,9,0)'); g.fillRect(0, CT, W, 9);
  rc(0, CT, W, 1.1, 'rgba(255,214,150,.6)'); rc(0, CT + 9, W, 2, '#07060b');
  g.save(); g.beginPath(); g.rect(0, CT, W, 11); g.clip();   // light pools on the wood, and stays on the wood
  for (const x of CANDLES) glow(x, CT + 5, 46, '255,180,90', 0.6); glow(HX + 52, CT + 3, 80, '255,150,60', 0.5); g.restore();
  g.fillStyle = lin(0, CT + 11, 0, H, '#40241a', '#1c1210', '#07060b'); g.fillRect(0, CT + 11, W, H - CT - 11);
  for (let x = 6; x < W; x += 68) { g.fillStyle = 'rgba(5,4,9,.6)'; g.fillRect(x, CT + 13, 56, 11); rc(x, CT + 23, 56, 1, 'rgba(150,85,46,.3)'); }
  // the rail: an iron channel that fills with ember light. this is the actual progress bar
  rc(20, CT + 27, W - 40, 5, '#07060b'); rc(20, CT + 32, W - 40, 1, 'rgba(150,150,158,.3)'); rc(20, CT + 26, W - 40, 1, 'rgba(0,0,0,.6)');
}
function candle(x) {   // stands at the near edge of the bar, in front of everyone
  const b = CT + 7.6;
  ell(x, b, 7, 1.9, '#07060b'); ell(x, b - 0.7, 6.4, 1.6, lin(x - 6, 0, x + 6, 0, '#6c6c76', '#383040', '#16131e'));
  g.fillStyle = lin(0, b - 12, 0, b, '#fbe09a', '#d8ac94', '#946050'); g.fillRect(x - 3, b - 11.5, 6, 11);
  g.fillStyle = lin(x - 3, 0, x + 3, 0, 'rgba(255,246,208,.35)', 'rgba(0,0,0,0)', 'rgba(40,20,16,.5)'); g.fillRect(x - 3, b - 11.5, 6, 11);
  rc(x - 3.9, b - 9, 1.7, 5.4, '#d8ac94'); ell(x - 3.1, b - 3.6, 1.1, 1.1, '#d8ac94'); rc(x + 2.1, b - 10.6, 1.5, 3.6, '#b98470'); ell(x + 0.6, b - 1.2, 3.6, 1, '#b98470');
  ell(x, b - 11.5, 3, 1, '#fff6d0'); rc(x - 0.4, b - 13.6, 0.9, 2.4, '#07060b');
}
// ───────── seven drinkers, seven cups. each is drawn standing on 0,0 with its handle on the outer side ─────────
const froth = (w, y) => {
  for (let i = 0, n = Math.ceil(w / 2.7); i < n; i++) ell(-w / 2 + (i + 0.5) * w / n, y - 0.5 - (i % 2) * 1, 2.4 + (i % 3) * 0.35, 2, '#fbe09a');
  ell(-w * 0.16, y - 2.3, w * 0.2, 0.9, '#fff6d0');
  fillP('#fbe09a', (k) => { k.moveTo(-w / 2 - 0.5, y + 1.4); k.quadraticCurveTo(-w / 2 - 2, y + 5.5, -w / 2 - 0.5, y + 8.5); k.lineTo(-w / 2 + 1, y + 7.5); k.lineTo(-w / 2 + 0.9, y + 1.4); });
};
const hollow = (w, y) => { ell(0, y, w / 2, 2.2, '#07060b'); ell(0, y + 0.5, w / 2 - 1.3, 1.4, '#2c1a15'); rc(-w / 2 + 0.4, y - 0.2, 3, 1, '#d99448'); };
const VESSEL = {
  tankard: { lip: [-5, -18], grip: [12.8, -9], draw(full) {   // oak staves, two iron hoops
    strokeP('#1c1210', 3.4, (k) => k.arc(8.5, -9, 5.2, -1.25, 1.25)); strokeP('#754026', 1, (k) => k.arc(8.5, -9, 5.6, -1.1, 0.3));
    for (let i = 0; i < 5; i++) { g.fillStyle = lin(-7.5 + i * 3, 0, -4.5 + i * 3, 0, i < 2 ? '#b9713a' : '#96552e', i < 3 ? '#754026' : '#40241a'); g.fillRect(-7.5 + i * 3, -18, 3, 18); }
    for (const yy of [-15, -5]) { g.fillStyle = lin(-7.5, 0, 7.5, 0, '#96969e', '#4a4a52', '#16131e'); g.fillRect(-7.9, yy, 15.8, 2.6); rc(-5, yy + 0.8, 1, 1, '#c4c4c8'); rc(1, yy + 0.8, 1, 1, '#c4c4c8'); }
    rc(-7.5, -1, 15, 1, '#1c1210');
    full ? froth(15, -18) : hollow(15, -18);
  } },
  beaker: { lip: [-4, -18], grip: [1, -7.5], draw(full) {   // elven silver, no handle, a waist
    fillP(lin(-5.5, 0, 5.5, 0, '#dfe7f0', '#7e97b8', '#1a2740'), (k) => { k.moveTo(-3.6, 0); k.lineTo(-2.8, -6); k.quadraticCurveTo(-3, -12, -5.4, -18); k.lineTo(5.4, -18); k.quadraticCurveTo(3, -12, 2.8, -6); k.lineTo(3.6, 0); });
    g.fillStyle = lin(-4, 0, 4, 0, '#aebfd4', '#27395a'); g.fillRect(-4.2, -1.4, 8.4, 1.6);
    strokeP('rgba(16,24,42,.75)', 0.7, (k) => { k.moveTo(-4, -13.4); k.quadraticCurveTo(0, -12, 4, -13.4); k.moveTo(-2.9, -7); k.quadraticCurveTo(0, -6, 2.9, -7); });
    for (const x of [-2, 0.4, 2.6]) strokeP('rgba(16,24,42,.5)', 0.6, (k) => { k.moveTo(x, -12); k.lineTo(x * 0.8, -7.6); });
    rc(-3.9, -16.4, 1, 8, 'rgba(255,255,255,.55)');
    ell(0, -18, 5.4, 1.6, full ? '#d99448' : '#07060b'); if (full) ell(-1.2, -18.2, 2.6, 0.7, '#fbe09a'); else ell(0, -17.6, 4, 1, '#1a2740');
  } },
  clay: { lip: [-4.5, -13.6], grip: [10.6, -6.8], draw(full) {   // a squat fired mug with a thumbprint in it
    strokeP('#2c1a15', 3, (k) => k.arc(8, -6.8, 3.8, -1.35, 1.35)); strokeP('#96552e', 0.9, (k) => k.arc(8, -6.8, 4.2, -1.2, 0.2));
    fillP(lin(-9, 0, 9, 0, '#d99448', '#96552e', '#40241a'), (k) => { k.moveTo(-5.6, 0); k.bezierCurveTo(-10, -3, -9.4, -10.4, -6.4, -13.4); k.lineTo(6.4, -13.4); k.bezierCurveTo(9.4, -10.4, 10, -3, 5.6, 0); });
    strokeP('rgba(28,18,16,.55)', 0.9, (k) => { k.moveTo(-8.6, -8.6); k.quadraticCurveTo(0, -7, 8.6, -8.6); k.moveTo(-8.4, -4); k.quadraticCurveTo(0, -2.4, 8.4, -4); });
    g.fillStyle = lin(-6.6, 0, 6.6, 0, '#f0bb62', '#b9713a', '#58301f'); g.fillRect(-6.8, -14.6, 13.6, 1.8); ell(-3.4, -6.4, 1.5, 1.9, 'rgba(28,18,16,.3)');
    full ? froth(12.6, -14.6) : hollow(12.6, -14.4);
  } },
  stein: { lip: [-4.5, -21], grip: [12.4, -10.5], draw(full) {   // tall pewter, lid thrown back, one rune that still works
    strokeP('#0e0c14', 3.2, (k) => k.arc(7.6, -10.5, 5.4, -1.25, 1.25)); strokeP('#96969e', 0.9, (k) => k.arc(7.6, -10.5, 5.8, -1.1, 0.3));
    fillP(lin(-7, 0, 7, 0, '#c4c4c8', '#6c6c76', '#201b28'), (k) => { k.moveTo(-7, 0); k.lineTo(-6, -21); k.lineTo(6, -21); k.lineTo(7, 0); });
    for (const y of [-19.4, -11.6, -2.6]) { rc(-7, y, 14, 1.8, 'rgba(14,12,20,.55)'); rc(-7, y, 14, 0.6, 'rgba(223,231,240,.5)'); }
    strokeP('#3aa890', 0.9, (k) => { k.moveTo(-1.6, -9.4); k.lineTo(-1.6, -5); k.moveTo(-1.6, -9.4); k.lineTo(1.6, -7.6); k.lineTo(-1.6, -6.4); }); glow(0, -7.4, 5, '58,168,144', 0.55);
    rc(-5.6, -18, 1.1, 14, 'rgba(255,255,255,.4)');
    fillP(lin(6, -28, 10, -20, '#c4c4c8', '#383040'), (k) => { k.moveTo(5.4, -21); k.lineTo(7.6, -29); k.quadraticCurveTo(10.6, -28.4, 10, -24.6); k.lineTo(7.4, -20.4); }); ell(8.6, -29, 1.3, 1.3, '#96969e');
    full ? froth(12, -21) : hollow(12, -21);
  } },
  horn: { lip: [-3.4, -24.6], grip: [1.6, -11], draw(full) {   // an aurochs horn in iron, stood on its point
    fillP(lin(-4, -24, -4, 1, '#2c1a15', '#58301f', '#96552e', '#fbe09a'), (k) => { k.moveTo(-4.6, -23.6); k.bezierCurveTo(-4.6, -14, -5.6, -6, -6.6, 0.4); k.bezierCurveTo(-1, -1, 7.8, -8, 8.8, -23.6); });
    rc(-3.6, -21, 1.3, 12, 'rgba(255,220,170,.4)');
    for (const [y, a] of [[-16, 0.5], [-9, 0.44]]) strokeP(`rgba(14,10,10,${a})`, 0.9, (k) => { k.moveTo(-5, y); k.quadraticCurveTo(1, y + 2.4, 7.6 + y * 0.12, y + 0.6); });
    g.fillStyle = lin(-6, 0, 9, 0, '#c4c4c8', '#6c6c76', '#201b28'); g.fillRect(-5.6, -25.4, 15.2, 3.2); for (const x of [-3, 2, 7]) ell(x, -23.8, 0.8, 0.8, '#dfe7f0');
    fillP(lin(-7, -6, -3, 0, '#96969e', '#201b28'), (k) => { k.moveTo(-5.9, -5.6); k.lineTo(-6.8, 0.6); k.lineTo(-3.4, -1.2); k.lineTo(-2.2, -4.4); });
    g.save(); g.translate(2, 0); full ? froth(13, -25.4) : hollow(13, -25.2); g.restore();
  } },
  goblet: { lip: [-5, -18], grip: [0.4, -5.6], draw(full) {   // black steel and a red stone. wine, not ale
    ell(0, -0.4, 6, 1.7, '#07060b'); ell(0, -1, 5.4, 1.4, lin(-5, 0, 5, 0, '#7e97b8', '#2b2533', '#07060b'));
    g.fillStyle = lin(-1.4, 0, 1.4, 0, '#7e97b8', '#16131e'); g.fillRect(-1.4, -9.4, 2.8, 8.4); ell(0, -5.4, 2.5, 1.5, lin(-2.5, 0, 2.5, 0, '#aebfd4', '#27395a'));
    fillP(lin(-7, 0, 7, 0, '#7e97b8', '#2b2533', '#07060b'), (k) => { k.moveTo(-6.8, -18); k.bezierCurveTo(-6.8, -11.6, -3, -9, 0, -9); k.bezierCurveTo(3, -9, 6.8, -11.6, 6.8, -18); });
    strokeP('rgba(174,191,212,.55)', 0.7, (k) => { k.moveTo(-6.2, -15.4); k.quadraticCurveTo(0, -13.6, 6.2, -15.4); }); rc(-5.4, -17, 1, 5, 'rgba(223,231,240,.5)');
    ell(0, -13, 1.5, 1.5, '#b8431f'); rc(-0.6, -13.8, 0.9, 0.9, '#f0bb62');
    ell(0, -18, 6.8, 1.8, full ? '#5c1c18' : '#07060b'); if (full) ell(-1.6, -18.2, 3, 0.8, '#b8431f'); else ell(0, -17.6, 5, 1.1, '#201b28');
    rc(-6.8, -18.6, 13.6, 0.9, 'rgba(174,191,212,.7)');
  } },
  tin: { lip: [-4.5, -12.6], grip: [10, -6.6], draw(full) {   // a soldier's cup, dented, older than he admits
    strokeP('#16131e', 2.8, (k) => { k.moveTo(6, -10.4); k.quadraticCurveTo(12.4, -10.4, 11.6, -5.6); k.quadraticCurveTo(11, -2.4, 6, -3); }); strokeP('#96969e', 0.9, (k) => { k.moveTo(6.4, -10.8); k.quadraticCurveTo(12.6, -10.6, 12, -6); });
    fillP(lin(-7, 0, 7, 0, '#c4c4c8', '#6c6c76', '#201b28'), (k) => { k.moveTo(-6, 0); k.lineTo(-6.8, -12.4); k.lineTo(6.8, -12.4); k.lineTo(6, 0); });
    ell(-2.4, -5.4, 2.3, 2.9, 'rgba(14,12,20,.38)'); ell(-1.8, -6, 1.2, 1.6, 'rgba(223,231,240,.3)'); for (const [x, y] of [[3, -3], [4.2, -8], [-4.6, -2]]) rc(x, y, 1.2, 1, 'rgba(117,64,38,.7)');
    rc(-7, -13.2, 14, 1.5, '#dfe7f0'); rc(-6.2, -1, 12.4, 1, 'rgba(14,12,20,.6)');
    full ? froth(13, -13.2) : hollow(13, -13);
  } },
};
function vessel(kind, x, y, side, rot, full, s = 1) { g.save(); g.translate(x, y); g.scale(side * s, s); g.rotate(rot); VESSEL[kind].draw(full); g.restore(); }
const rot2 = ([x, y], a) => [x * Math.cos(a) - y * Math.sin(a), x * Math.sin(a) + y * Math.cos(a)], mix = (a, b, t) => a + (b - a) * t;
const tone = (hex, k) => `rgb(${[1, 3, 5].map((i) => Math.min(255, Math.round(parseInt(hex.slice(i, i + 2), 16) * k)))})`;
function round(ax, ay, ra, bx, by, rb, hex) {   // the same capsule, lit from above and from the hearth side
  let a = Math.atan2(by - ay, bx - ax), nx = -Math.sin(a), ny = Math.cos(a); if (nx * 0.35 - ny * 0.94 < 0) { nx = -nx; ny = -ny; }
  const mx = (ax + bx) / 2, my = (ay + by) / 2, r = Math.max(ra, rb);
  limb(ax, ay, ra, bx, by, rb, lin(mx + nx * r, my + ny * r, mx - nx * r, my - ny * r, tone(hex, 1.4), hex, tone(hex, 0.62), tone(hex, 0.4)));
}
function limb(ax, ay, ra, bx, by, rb, col) {   // a tapered capsule: thick at one joint, thinner at the next
  const a = Math.atan2(by - ay, bx - ax), nx = -Math.sin(a), ny = Math.cos(a), q = Math.PI / 2;
  fillP(col, (k) => { k.moveTo(ax + nx * ra, ay + ny * ra); k.lineTo(bx + nx * rb, by + ny * rb); k.arc(bx, by, rb, a + q, a - q, true); k.lineTo(ax - nx * ra, ay - ny * ra); k.arc(ax, ay, ra, a - q, a + q, true); });
}
// ───────── faces that give nothing away ─────────
function socket(ex, ey, s, pose, glint, glowRgb) {
  for (const sd of [-1, 1]) {
    const x = sd * ex;
    ell(x, ey, 3.4 * s, 2.3 * s, 'rgba(8,5,10,.62)');
    if (pose.shut) strokeP('#07060b', s, (k) => { k.moveTo(x - 2 * s, ey + 0.3 * s); k.lineTo(x + 2 * s, ey + 0.6 * s); });
    else { ell(x, ey + 0.3, 1.8 * s, 1 * s, '#07060b'); rc(x - 0.1 * s, ey - 0.3 * s, 1.1 * s, 0.9 * s, glint); if (glowRgb) glow(x, ey, 4.5 * s, glowRgb, 0.6); }
  }
}
function scowl(ex, ey, s, col, w = 2.3) { for (const sd of [-1, 1]) strokeP(col, w * s, (k) => { k.moveTo(sd * (ex + 3.8 * s), ey - 1.8 * s); k.quadraticCurveTo(sd * ex, ey - 1.4 * s, sd * (ex - 3 * s), ey + 1 * s); }); }
function grim(y, w) { strokeP('rgba(24,8,10,.9)', 1.1, (k) => { k.moveTo(-w, y + 0.7); k.quadraticCurveTo(0, y - 0.5, w, y + 0.7); }); }
// where the cup is: on the bar, at the mouth, or held up. everything else follows the cup
function hold(c, st) {
  const V = VESSEL[c.cup], sd = c.side, s = c.cupS, rx = c.cx + sd * c.rest, ry = CT + 3;
  if (st.toast > 0) { const t = st.toast; return { x: mix(rx, c.cx + sd * c.high[0], t), y: mix(ry, c.high[1], t), rot: 0.16 * Math.min(1, t) }; }
  const a = st.lift, ru = -(0.7 + 0.5 * st.tip), [lx, ly] = rot2(V.lip, ru), arc = Math.sin(a * Math.PI);
  const ux = c.cx + sd * (c.mouth[0] - s * lx), uy = c.hy + c.mouth[1] - s * ly - 1.5 * st.tip;
  return { x: mix(rx, ux, a) + sd * 4 * arc, y: mix(ry, uy, a) - 3 * arc + st.bob - st.hop, rot: ru * smooth(0.4, 1, a) };
}
function make(o) {
  const c = { side: 1, cupS: 1, rest: 16, ...o };
  c.high = c.high || [c.sw * 0.72 + 7, c.hy + 7];
  const headXf = (st) => { g.translate(c.cx, c.ny + st.bow * 1.6 + st.bob * 0.7 + st.dip - 1.6 * st.tip); g.rotate(-c.side * (0.17 * st.lift + 0.1 * st.tip - 0.05 * st.bow) - c.side * 0.07 * Math.min(1, st.toast)); g.translate(0, -(c.ny - c.hy)); };
  c.body = (st) => { c.torso(st); g.save(); headXf(st); c.head(st); g.restore(); };
  c.spark = (st) => { if (c.sparkT) c.sparkT(st); if (c.sparkH) { g.save(); headXf(st); c.sparkH(st); g.restore(); } };
  c.arm = (st) => {
    g.beginPath(); g.rect(0, 0, W, CT + 7); g.clip();   // the bar hides whatever is below its top
    const sd = c.side, P = hold(c, st), w = c.armW, S = [c.cx + sd * c.sw * 0.8, c.sy + 4];
    const [gx, gy] = rot2(VESSEL[c.cup].grip, P.rot), Hd = [P.x + sd * c.cupS * gx, P.y + c.cupS * gy];
    // the elbow rests on the bar, and swings out and up around the shoulder as the cup rises
    const ex = c.sw * 0.2 + 5, ey = CT + 3 - S[1], a0 = Math.atan2(ey, ex), l0 = Math.hypot(ex, ey), A = Math.max(13, l0);
    const t = st.toast > 0 ? Math.min(1, st.toast) : st.lift, tg = st.toast > 0 ? [-0.5, 0.6] : [0.36, 0.52];
    const ea = mix(a0, tg[0], t), el = mix(l0, A * tg[1], t), E = [S[0] + sd * Math.cos(ea) * el, Math.min(CT + 3, S[1] + Math.sin(ea) * el)];
    const fx = Hd[0] - E[0], fy = Hd[1] - E[1], ux = E[0] - S[0], uy = E[1] - S[1], rS = w * 0.56, rE = w * 0.46, rH = w * 0.36;
    limb(S[0], S[1], rS + 1, E[0], E[1], rE + 1, c.sleeve[1]); round(S[0], S[1], rS, E[0], E[1], rE, c.sleeve[0]);
    for (const q of [0.62, 0.8]) strokeP('rgba(5,4,9,.3)', 0.9, (k) => { k.moveTo(S[0] + ux * q - uy * 0.16, S[1] + uy * q + ux * 0.16); k.quadraticCurveTo(S[0] + ux * (q + 0.07), S[1] + uy * (q + 0.07), S[0] + ux * q + uy * 0.16, S[1] + uy * q - ux * 0.16); });
    if (c.shoulder) c.shoulder();
    limb(E[0], E[1], rE + 1, Hd[0], Hd[1], rH + 1, c.sleeve[1]); round(E[0], E[1], rE, Hd[0], Hd[1], rH, c.fore || c.sleeve[0]);
    if (c.cuff) { round(E[0] + fx * 0.6, E[1] + fy * 0.6, rE * 0.52 + rH * 0.48 + 0.9, E[0] + fx * 0.9, E[1] + fy * 0.9, rH + 1.1, c.cuff); strokeP('rgba(5,4,9,.5)', 0.8, (k) => { k.moveTo(E[0] + fx * 0.6 - fy * 0.14, E[1] + fy * 0.6 + fx * 0.14); k.lineTo(E[0] + fx * 0.6 + fy * 0.14, E[1] + fy * 0.6 - fx * 0.14); }); }
    vessel(c.cup, P.x, P.y, sd, P.rot, st.full, c.cupS);
    const h = c.hand;
    g.save(); g.translate(Hd[0], Hd[1]); g.scale(sd, 1); g.rotate(P.rot);
    ell(0.4, 0, h + 0.9, h * 0.92 + 0.9, 'rgba(5,4,9,.75)'); ell(0.4, 0, h, h * 0.92, rad(-1, -1.6, h * 1.8, c.glove[0], c.glove[1]));
    for (const i of [-0.5, 0, 0.5]) strokeP('rgba(5,4,9,.55)', 0.8, (k) => { k.moveTo(-h * 0.55, i * h); k.lineTo(h * 0.8, i * h + 0.5); });
    ell(-h * 0.3, -h * 0.82, h * 0.5, h * 0.34, c.glove[0]);
    g.restore();
    if (st.lift > 0.9 && st.tip > 0.12 && st.tip < 0.97) for (let j = 0; j < 2; j++) { const ph = (st.time * 2.1 + j * 0.5 + c.cx * 0.01) % 1; ell(c.cx + sd * (c.mouth[0] + 3 + j * 2.4), c.hy + c.mouth[1] + 5 + ph * 13, 0.8, 1.3, `rgba(251,224,154,${0.95 - ph * 0.6})`); }
  };
  return c;
}
const STEEL = ['#c4c4c8', '#6c6c76', '#2b2533'], IRON = ['#6c6c76', '#383040', '#0e0c14'];
function plate(x, y, rx, ry, m = STEEL) { ell(x, y, rx, ry, lin(x - rx, y - ry, x + rx, y + ry, m[0], m[1], m[2])); strokeP('rgba(5,4,9,.55)', 0.9, (k) => k.ellipse(x, y, rx, ry, 0, 0.2, 2.9)); }
function ironhelm(cx) {   // a dwarf who has not taken the helmet off in years
  const B = ['#d99448', '#96552e', '#40241a'];
  const c = make({ cx, hy: 85, ny: 98, hr: 13.5, sw: 33, sy: 102, mouth: [0, 9], armW: 12.5, hand: 5.6, sleeve: ['#6c6c76', '#16131e'], cuff: '#96552e', glove: ['#58301f', '#1c1210'], cup: 'tankard', cupS: 1.12, rest: 16 });
  const pauld = (s) => { plate(cx + s * 27, 104.5, 12.5, 8.8, IRON); plate(cx + s * 28, 100.5, 11, 7); plate(cx + s * 29, 97, 8.6, 5); fillP(lin(0, 82, 0, 96, '#c4c4c8', '#383040'), (k) => { k.moveTo(cx + s * 26, 95); k.lineTo(cx + s * 34, 82); k.lineTo(cx + s * 34.5, 96); }); };
  c.shoulder = () => pauld(c.side);
  c.sparkH = (pose) => { if (!pose.shut) for (const s of [-1, 1]) { rc(s * 5.2 - 1.2, -3.8, 2.6, 1.6, '#fbe09a'); glow(s * 5.2, -3, 5.5, '255,170,80', 0.7); } };
  c.torso = () => {
    for (let i = -8; i <= 8; i++) { ell(cx + i * 4.4, 99 + Math.abs(i) * 0.9, 5.4, 7, i % 2 ? '#2c1a15' : '#40241a'); strokeP('rgba(5,4,9,.5)', 0.8, (k) => { k.moveTo(cx + i * 4.4, 96); k.lineTo(cx + i * 4.4 + 1, 106); }); }
    fillP(lin(cx - 30, 0, cx + 30, 0, IRON[1], IRON[0], IRON[2]), (k) => { k.moveTo(cx - 33, CT + 2); k.lineTo(cx - 32, 110); k.quadraticCurveTo(cx - 28, 100, cx - 14, 99); k.lineTo(cx + 14, 99); k.quadraticCurveTo(cx + 28, 100, cx + 32, 110); k.lineTo(cx + 33, CT + 2); });
    for (let y = 108; y < CT; y += 5) for (let x = cx - 26 + ((y / 5 | 0) % 2) * 3; x < cx + 28; x += 6) strokeP('rgba(5,4,9,.45)', 0.8, (k) => k.arc(x, y, 3, 0.2, 2.9));
    for (const s of [-1, 1]) pauld(s);
  };
  c.head = (pose) => {
    ell(0, 0, 13, 12.4, rad(-3, -2, 17, '#d8ac94', '#946050', '#4a2e28'));
    fillP(lin(0, 0, 0, 42, B[0], B[1], B[2]), (k) => { k.moveTo(-13.6, -2); k.bezierCurveTo(-19, 10, -16, 28, -8, 36); k.quadraticCurveTo(0, 43, 8, 36); k.bezierCurveTo(16, 28, 19, 10, 13.6, -2); k.quadraticCurveTo(9, 3.6, 4.4, 5); k.lineTo(-4.4, 5); k.quadraticCurveTo(-9, 3.6, -13.6, -2); });
    for (let i = -6; i <= 6; i++) strokeP('rgba(5,4,9,.4)', 0.8, (k) => { k.moveTo(i * 2, 10); k.quadraticCurveTo(i * 2.8, 24, i * 1.5, 37 - Math.abs(i) * 1.7); });
    for (const s of [-1, 1]) { for (let j = 0; j < 5; j++) ell(s * 6.6, 17 + j * 4, 2.8, 2.6, j % 2 ? B[0] : B[1]); rc(s * 6.6 - 3.2, 35.5, 6.4, 2.8, '#6c6c76'); rc(s * 6.6 - 3.2, 35.5, 6.4, 0.9, '#dfe7f0'); }
    for (const s of [-1, 1]) fillP(lin(0, 3, 0, 14, B[0], B[1]), (k) => { k.moveTo(0, 4.6); k.bezierCurveTo(s * 5, 3, s * 11, 6.4, s * 12.6, 15); k.bezierCurveTo(s * 9, 11.4, s * 4, 10, 0, 9); });
    ell(0, 2.6, 4, 3.5, rad(-1, 1.6, 5, '#b98470', '#6e4438'));
    // the helm: dome, brow, cheek plates, nasal. the eyes are two points of light in the slit
    for (const s of [-1, 1]) fillP(lin(s * 6, 0, s * 15, 0, STEEL[1], STEEL[2]), (k) => { k.moveTo(s * 7, -6); k.lineTo(s * 15, -6); k.lineTo(s * 15.4, 5); k.quadraticCurveTo(s * 13, 10, s * 9.4, 9); k.lineTo(s * 8.4, 0); });
    rc(-13, -5.4, 26, 5.6, 'rgba(5,4,9,.92)');
    ell(0, -6.5, 15, 13, lin(-15, 0, 15, 0, STEEL[0], STEEL[1], STEEL[2]), Math.PI, 0); rc(-15.2, -8.2, 30.4, 3.6, '#754026'); rc(-15.2, -8.2, 30.4, 1.2, '#f0bb62');
    for (let x = -12; x <= 12; x += 6) ell(x, -6.4, 1.1, 1.1, '#c4c4c8'); g.fillStyle = lin(-2, 0, 2, 0, '#96969e', '#2b2533'); g.fillRect(-2, -8, 4, 10.6);
    rc(-1, -19.4, 2, 12, '#383040'); rc(-1, -19.4, 0.8, 12, '#c4c4c8');
    for (const s of [-1, 1]) { fillP(lin(s * 12, 0, s * 25, 0, '#4a4a52', '#16131e'), (k) => { k.moveTo(s * 13.4, -11); k.bezierCurveTo(s * 22, -10, s * 27, -15, s * 26, -25); k.bezierCurveTo(s * 23, -19, s * 19, -17, s * 12.6, -17); }); rc(s * 13 - 1.8, -18, 3.6, 7.4, '#6c6c76'); }
    if (!pose.shut) for (const s of [-1, 1]) { rc(s * 5.2 - 1, -3.6, 2.2, 1.3, '#f0bb62'); glow(s * 5.2, -3, 4.5, '255,170,80', 0.55); }
    if (pose.foam) for (const [x, y, r] of [[-5, 8, 2.2], [-1, 7.2, 2.4], [4, 7.8, 2.2]]) ell(x, y, r, r * 0.75, '#fbe09a');
  };
  return c;
}
function berserker(cx) {   // the other kind of dwarf
  const B = ['#b8431f', '#5c1c18', '#1c1210'], SK = ['#d8ac94', '#946050', '#4a2e28'];
  const c = make({ cx, hy: 86, ny: 99, hr: 13.5, sw: 32, sy: 102, mouth: [0, 9], armW: 12.5, hand: 5.6, sleeve: [SK[1], SK[2]], cuff: '#40241a', glove: [SK[1], SK[2]], cup: 'horn', cupS: 1.05, rest: 18 });
  c.sparkH = (pose) => { if (!pose.shut) for (const s of [-1, 1]) rc(s * 5.2 - 0.4, -3.2, 1.5, 1.1, '#dfe7f0'); };
  c.torso = () => {
    fillP(lin(cx - 32, 0, cx + 32, 0, SK[2], SK[1], SK[2]), (k) => { k.moveTo(cx - 33, CT + 2); k.lineTo(cx - 32, 108); k.quadraticCurveTo(cx - 29, 98, cx - 14, 98); k.lineTo(cx + 14, 98); k.quadraticCurveTo(cx + 29, 98, cx + 32, 108); k.lineTo(cx + 33, CT + 2); });
    ell(cx - 24, 105, 11.5, 9.5, rad(cx - 27, 101, 14, SK[0], SK[1], SK[2])); strokeP('#1a2740', 1.3, (k) => { k.moveTo(cx - 32, 102); k.quadraticCurveTo(cx - 25, 98, cx - 17, 104); k.moveTo(cx - 30, 107); k.quadraticCurveTo(cx - 24, 104, cx - 18, 109); });
    strokeP('rgba(92,28,24,.8)', 1, (k) => { k.moveTo(cx - 29, 110); k.lineTo(cx - 21, 114); });
    for (let i = 0; i <= 9; i++) { const x = cx + 4 + i * 3.4, y = 99 + i * 1.5; ell(x, y, 6, 7.4, i % 2 ? '#2c1a15' : '#40241a'); strokeP('rgba(5,4,9,.5)', 0.8, (k) => { k.moveTo(x - 1, y - 4); k.lineTo(x + 1, y + 6); }); }
    strokeP('#16131e', 3.4, (k) => { k.moveTo(cx - 20, 99); k.lineTo(cx + 12, CT); }); for (const t of [0.25, 0.5, 0.75]) ell(cx - 20 + 32 * t, 99 + 25 * t, 1.3, 1.3, '#96969e');
  };
  c.head = (pose) => {
    fillP(lin(0, -30, 0, -6, '#e0692a', '#8a2a1c'), (k) => { k.moveTo(-4.4, -8); k.lineTo(-5.4, -19); k.lineTo(-2.6, -15.6); k.lineTo(-1.6, -25); k.lineTo(0.6, -17); k.lineTo(2.6, -23.4); k.lineTo(3.6, -15); k.lineTo(6, -18.6); k.lineTo(4.6, -8); });
    ell(0, 0, 13, 12.6, rad(-2, -1, 17, SK[0], SK[1], SK[2]));
    for (const s of [-1, 1]) { ell(s * 13, 1, 2.8, 3.8, SK[1]); strokeP('#96969e', 1.2, (k) => k.arc(s * 13.6, 6.6, 2, 0, 7)); }
    for (let i = 0; i < 26; i++) rc(-11 + hash(i, 1) * 22, -11 + hash(i, 2) * 7, 1, 1, 'rgba(40,20,18,.35)');
    strokeP('#1a2740', 1.4, (k) => { k.moveTo(-10.4, -6.6); k.lineTo(-7, 1); k.lineTo(-10, 5); k.moveTo(-6.4, -8.4); k.lineTo(-4.6, -5.6); });
    socket(5.2, -2.8, 1.05, pose, '#d8ac94'); if (!pose.shut) { ell(5.2, -2.5, 1.9, 1.1, '#aebfd4'); }
    scowl(5.2, -6, 1, B[2], 2.6); strokeP('rgba(200,150,130,.85)', 1.1, (k) => { k.moveTo(3, -10.4); k.lineTo(7.4, 3); });
    fillP(lin(0, 0, 0, 42, B[0], B[1], B[2]), (k) => { k.moveTo(-13.6, -2); k.bezierCurveTo(-19, 8, -17, 22, -11, 39); k.lineTo(-3, 22); k.lineTo(0, 27); k.lineTo(3, 22); k.lineTo(11, 39); k.bezierCurveTo(17, 22, 19, 8, 13.6, -2); k.quadraticCurveTo(9, 3.6, 4.4, 5); k.lineTo(-4.4, 5); k.quadraticCurveTo(-9, 3.6, -13.6, -2); });
    for (let i = -6; i <= 6; i++) if (i) strokeP('rgba(5,4,9,.4)', 0.8, (k) => { k.moveTo(i * 2, 9); k.quadraticCurveTo(i * 2.9, 20, i * 1.9, 36 - (7 - Math.abs(i)) * 2); });
    for (const s of [-1, 1]) { rc(s * 9 - 2.8, 30, 5.6, 2.4, '#6c6c76'); fillP(lin(0, 3, 0, 15, B[0], B[1]), (k) => { k.moveTo(0, 4.6); k.bezierCurveTo(s * 5, 3, s * 11, 6.4, s * 12.6, 16); k.bezierCurveTo(s * 9, 11.4, s * 4, 10, 0, 9); }); }
    ell(0, 2.4, 4.2, 3.6, rad(-1, 1.4, 5, '#d8ac94', '#946050')); strokeP('rgba(92,28,24,.8)', 1, (k) => { k.moveTo(-3, 0.6); k.lineTo(3.4, 3.4); });
    if (pose.foam) for (const [x, y, r] of [[-5, 8, 2.2], [-1, 7.2, 2.4], [4, 7.8, 2.2]]) ell(x, y, r, r * 0.75, '#fbe09a');
  };
  return c;
}
function ranger(cx) {   // an elf who keeps the hood up indoors
  const SK = ['#d8ac94', '#946050', '#4a2e28'], CL = ['#44584a', '#1f2c24', '#0e0c14'];
  const c = make({ cx, hy: 59, ny: 72, hr: 10.5, sw: 24, sy: 82, mouth: [0, 6.4], armW: 8.2, hand: 4.2, sleeve: [CL[0], CL[2]], cuff: '#40241a', glove: ['#58301f', '#1c1210'], cup: 'beaker', cupS: 1.05, rest: 15 });
  c.sparkH = (pose) => { if (!pose.shut) for (const s of [-1, 1]) { rc(s * 3.8 - 1, -2, 2.1, 1.2, '#8fe6c8'); glow(s * 3.8, -1.5, 4.6, '143,230,200', 0.7); } };
  c.torso = () => {
    for (const [dx, dy] of [[17, 0], [21, 3], [25, 1]]) { strokeP('#40241a', 1, (k) => { k.moveTo(cx + dx - 6, 78); k.lineTo(cx + dx, 44 + dy); }); fillP('#aebfd4', (k) => { k.moveTo(cx + dx, 44 + dy); k.lineTo(cx + dx + 3, 51 + dy); k.lineTo(cx + dx - 1.4, 53 + dy); }); }
    fillP(lin(cx - 26, 0, cx + 26, 0, CL[1], CL[0], CL[2]), (k) => { k.moveTo(cx - 27, CT + 2); k.bezierCurveTo(cx - 28, 100, cx - 26, 84, cx - 9, 76); k.lineTo(cx + 9, 76); k.bezierCurveTo(cx + 26, 84, cx + 28, 100, cx + 27, CT + 2); });
    for (const x of [-18, -10, 9, 17]) strokeP('rgba(5,4,9,.42)', 1.1, (k) => { k.moveTo(cx + x * 0.7, 86); k.quadraticCurveTo(cx + x * 1.1, 104, cx + x, CT); });
    for (let i = -5; i <= 5; i++) { ell(cx + i * 4, 80 + Math.abs(i) * 1.5, 4.6, 5.4, i % 2 ? '#2b2533' : '#383040'); strokeP('rgba(5,4,9,.5)', 0.7, (k) => { k.moveTo(cx + i * 4, 77 + Math.abs(i) * 1.5); k.lineTo(cx + i * 4 + 1, 85 + Math.abs(i) * 1.5); }); }
    strokeP('#2c1a15', 3, (k) => { k.moveTo(cx + 17, 84); k.lineTo(cx - 12, CT); }); fillP('#96969e', (k) => { k.moveTo(cx, 95); k.lineTo(cx + 3.4, 99); k.lineTo(cx, 104); k.lineTo(cx - 3.4, 99); });
    for (const s of [-1, 1]) fillP(lin(0, 70, 0, CT, '#dfe7f0', '#55709a'), (k) => { k.moveTo(cx + s * 6, 68); k.bezierCurveTo(cx + s * 10, 84, cx + s * 7, 100, cx + s * 9.6, 118); k.lineTo(cx + s * 6, 118); k.bezierCurveTo(cx + s * 4.4, 100, cx + s * 6.6, 86, cx + s * 4, 70); });
  };
  c.head = (pose) => {
    fillP(lin(-14, 0, 14, 0, CL[1], CL[0], CL[2]), (k) => { k.moveTo(-13.6, 12); k.bezierCurveTo(-17, -4, -9, -18, 2.4, -19.6); k.bezierCurveTo(11, -17, 17, -4, 13.6, 12); k.quadraticCurveTo(0, 17, -13.6, 12); });
    fillP('#07060b', (k) => { k.moveTo(-9.6, 9); k.bezierCurveTo(-12, -3, -6, -13, 1, -14); k.bezierCurveTo(8, -13, 12, -3, 9.6, 9); k.quadraticCurveTo(0, 14, -9.6, 9); });
    fillP(rad(-1, 4, 13, SK[0], SK[1], SK[2]), (k) => { k.moveTo(-7.6, -2.4); k.bezierCurveTo(-7.8, 5, -3.4, 10.6, 0, 12); k.bezierCurveTo(3.4, 10.6, 7.8, 5, 7.6, -2.4); k.bezierCurveTo(7.6, -11, -7.6, -11, -7.6, -2.4); });
    for (const s of [-1, 1]) fillP('rgba(8,5,10,.42)', (k) => { k.moveTo(s * 7.4, 0); k.lineTo(s * 3.4, 5.4); k.lineTo(s * 5.6, 9); });
    strokeP('rgba(60,30,30,.7)', 0.8, (k) => { k.moveTo(0.4, -1); k.lineTo(1, 3.4); k.lineTo(-0.8, 3.8); }); grim(6.6, 2.4); strokeP('rgba(216,172,148,.6)', 0.8, (k) => { k.moveTo(-5.4, 2); k.lineTo(-3, 7.4); });
    g.fillStyle = lin(0, -12, 0, 4.5, 'rgba(5,4,9,.97)', 'rgba(5,4,9,.86)', 'rgba(5,4,9,0)'); g.fillRect(-10, -13, 20, 18);
    if (!pose.shut) for (const s of [-1, 1]) { rc(s * 3.8 - 1, -2, 2.1, 1.2, '#8fe6c8'); glow(s * 3.8, -1.5, 4.4, '143,230,200', 0.6); }
    strokeP(CL[0], 1.2, (k) => { k.moveTo(-10.6, 9.4); k.bezierCurveTo(-13, -3, -6.4, -14, 1, -15); }); strokeP('rgba(255,160,80,.5)', 1, (k) => { k.moveTo(10.6, 9.4); k.bezierCurveTo(13, -3, 8, -13, 1.4, -15); });
  };
  return c;
}
function knight(cx) {   // and one in black plate, who has been a long way from home
  const SK = ['#dfe7f0', '#aebfd4', '#55709a'], AR = ['#55709a', '#201b28', '#07060b'];
  const c = make({ cx, hy: 58, ny: 71, hr: 10.5, sw: 25, sy: 81, mouth: [0, 6.4], armW: 9.5, hand: 4.4, sleeve: ['#383040', '#07060b'], cuff: '#55709a', glove: ['#4a4a52', '#0e0c14'], cup: 'goblet', cupS: 1.08, rest: 15 });
  const pauld = (s) => { for (const [ox, oy, w, h] of [[20, 88, 13, 9], [21.5, 83, 11.5, 7], [22, 78.6, 9, 5]]) { fillP(lin(cx + s * (ox - w), oy - h, cx + s * (ox + w), oy + h, AR[0], AR[1], AR[2]), (k) => { k.moveTo(cx + s * (ox - w), oy + h * 0.6); k.quadraticCurveTo(cx + s * ox, oy - h * 1.5, cx + s * (ox + w), oy + h * 0.2); k.lineTo(cx + s * (ox + w + 3), oy + h); k.quadraticCurveTo(cx + s * ox, oy + h * 0.2, cx + s * (ox - w), oy + h * 0.6); }); }
    fillP(lin(0, 62, 0, 78, '#7e97b8', AR[2]), (k) => { k.moveTo(cx + s * 20, 76); k.lineTo(cx + s * 29, 61); k.lineTo(cx + s * 27, 78); }); };
  c.shoulder = () => pauld(c.side);
  c.sparkT = () => { ell(cx, 86, 2.4, 2.4, '#b8431f'); rc(cx - 1, 85, 1.2, 1.2, '#f0bb62'); glow(cx, 86, 6, '224,105,42', 0.5); };
  c.sparkH = (pose) => { if (!pose.shut) for (const s of [-1, 1]) rc(s * 3.9 - 0.2, -1.6, 1.3, 1, '#dfe7f0'); };
  c.torso = () => {
    fillP(lin(cx - 20, 0, cx + 20, 0, '#07060b', '#201b28', '#07060b'), (k) => { k.moveTo(cx - 13, 46); k.bezierCurveTo(cx - 22, 70, cx - 20, 100, cx - 24, CT + 2); k.lineTo(cx + 24, CT + 2); k.bezierCurveTo(cx + 20, 100, cx + 22, 70, cx + 13, 46); });
    fillP(lin(cx - 22, 0, cx + 22, 0, AR[1], '#383040', AR[2]), (k) => { k.moveTo(cx - 23, CT + 2); k.lineTo(cx - 22, 90); k.quadraticCurveTo(cx - 20, 80, cx - 8, 77); k.lineTo(cx + 8, 77); k.quadraticCurveTo(cx + 20, 80, cx + 22, 90); k.lineTo(cx + 23, CT + 2); });
    strokeP('rgba(126,151,184,.6)', 1, (k) => { k.moveTo(cx - 12, 84); k.quadraticCurveTo(cx, 96, cx + 12, 84); k.moveTo(cx, 92); k.lineTo(cx, CT); k.moveTo(cx - 15, 104); k.quadraticCurveTo(cx, 112, cx + 15, 104); });
    for (const s of [-1, 1]) { fillP(lin(0, 62, 0, 82, '#383040', AR[2]), (k) => { k.moveTo(cx + s * 3, 80); k.lineTo(cx + s * 6, 64); k.lineTo(cx + s * 10.6, 78); }); strokeP('rgba(126,151,184,.7)', 0.8, (k) => { k.moveTo(cx + s * 6, 64); k.lineTo(cx + s * 10.6, 78); });
      pauld(s); }
    ell(cx, 86, 2.4, 2.4, '#8a2a1c'); rc(cx - 1, 85, 1, 1, '#e0692a');
  };
  c.head = (pose) => {
    for (const s of [-1, 1]) fillP(lin(s * 7, 0, s * 18, 0, SK[1], SK[2]), (k) => { k.moveTo(s * 7.4, -2); k.quadraticCurveTo(s * 14, -2.6, s * 18.6, -6.4); k.quadraticCurveTo(s * 13, 2, s * 7.8, 4.4); });
    fillP(rad(-2, -2, 15, SK[0], SK[1], SK[2]), (k) => { k.moveTo(-8.4, -3); k.bezierCurveTo(-8.6, 5, -3.6, 11, 0, 13); k.bezierCurveTo(3.6, 11, 8.6, 5, 8.4, -3); k.bezierCurveTo(8.4, -13.5, -8.4, -13.5, -8.4, -3); });
    for (const s of [-1, 1]) fillP('rgba(20,24,50,.5)', (k) => { k.moveTo(s * 8, -1); k.lineTo(s * 3.2, 5.6); k.lineTo(s * 5.8, 10); });
    socket(3.9, -1.2, 0.95, pose, '#dfe7f0'); scowl(3.9, -3.9, 0.82, '#07060b', 1.5);
    strokeP('rgba(40,50,90,.6)', 0.8, (k) => { k.moveTo(0.4, -0.6); k.lineTo(1, 3.6); k.lineTo(-0.8, 4); }); grim(6.8, 2.5); strokeP('rgba(138,42,28,.8)', 0.9, (k) => { k.moveTo(-6, -7); k.lineTo(-2.4, 3.4); });
    fillP(lin(-10, 0, 10, 0, '#07060b', '#2b2533', '#07060b'), (k) => { k.moveTo(-9.6, 0); k.bezierCurveTo(-11.4, -15.5, 11.4, -15.5, 9.6, 0); k.quadraticCurveTo(7, -7, 0, -5.4); k.quadraticCurveTo(-7, -7, -9.6, 0); });
    for (const s of [-1, 1]) fillP(lin(0, -8, 0, 46, '#201b28', '#07060b'), (k) => { k.moveTo(s * 7.4, -8); k.bezierCurveTo(s * 12.4, -2, s * 9.4, 16, s * 13, 46); k.lineTo(s * 8, 46); k.bezierCurveTo(s * 6.8, 22, s * 9.4, 4, s * 6.4, -6); });
    strokeP('#4a4a52', 1.5, (k) => { k.moveTo(-9.4, -6.4); k.quadraticCurveTo(0, -3.4, 9.4, -6.4); }); fillP('#6c6c76', (k) => { k.moveTo(-1.5, -5.6); k.lineTo(0, -11.6); k.lineTo(1.5, -5.6); });
  };
  return c;
}
function greybeard(cx) {   // the wizard, tired, with a pipe
  const RB = ['#3a5078', '#1a2740', '#07060b'];
  const c = make({ cx, hy: 70, ny: 83, hr: 11, sw: 28, sy: 90, mouth: [0, 7], armW: 10.5, hand: 4.8, sleeve: [RB[0], RB[2]], cuff: '#1a2740', glove: ['#b98470', '#6e4438'], cup: 'stein', rest: 14 });
  c.sparkT = () => { glow(cx - 32, 25, 17, '58,168,144', 0.7); fillP('#3aa890', (k) => { k.moveTo(cx - 32, 17); k.lineTo(cx - 28, 25); k.lineTo(cx - 32, 32); k.lineTo(cx - 36, 25); }); fillP('#8fe6c8', (k) => { k.moveTo(cx - 32, 17); k.lineTo(cx - 30, 25); k.lineTo(cx - 32, 32); }); };
  c.sparkH = (pose) => { if (!pose.shut) for (const s of [-1, 1]) { rc(s * 4.3 - 0.9, -2, 1.9, 1.1, '#f0bb62'); glow(s * 4.3, -1.6, 3.6, '240,187,98', 0.55); } if (!pose.busy) { ell(15.4, 5.6, 2.6, 1.1, '#e0692a'); rc(14.6, 5, 1.4, 0.9, '#fbe09a'); glow(15.4, 5, 8, '255,130,50', 0.8); } };
  c.torso = () => {
    strokeP('#2c1a15', 3.2, (k) => { k.moveTo(cx - 36, CT); k.lineTo(cx - 32, 30); }); strokeP('#754026', 1, (k) => { k.moveTo(cx - 36.7, CT); k.lineTo(cx - 32.7, 30); });
    glow(cx - 32, 25, 15, '58,168,144', 0.6); fillP('#3aa890', (k) => { k.moveTo(cx - 32, 17); k.lineTo(cx - 28, 25); k.lineTo(cx - 32, 32); k.lineTo(cx - 36, 25); }); fillP('#8fe6c8', (k) => { k.moveTo(cx - 32, 17); k.lineTo(cx - 30, 25); k.lineTo(cx - 32, 32); });
    fillP(lin(cx - 30, 0, cx + 30, 0, RB[1], RB[0], RB[2]), (k) => { k.moveTo(cx - 31, CT + 2); k.bezierCurveTo(cx - 32, 104, cx - 28, 90, cx - 11, 85); k.lineTo(cx + 11, 85); k.bezierCurveTo(cx + 28, 90, cx + 32, 104, cx + 31, CT + 2); });
    fillP(lin(0, 84, 0, 108, '#3a5078', '#10182a'), (k) => { k.moveTo(cx - 29, 100); k.quadraticCurveTo(cx - 25, 88, cx - 11, 84.4); k.lineTo(cx + 11, 84.4); k.quadraticCurveTo(cx + 25, 88, cx + 29, 100); for (let i = 7; i >= -7; i--) k.lineTo(cx + i * 4, 104 + (i % 2 ? 4.4 : 0) + (7 - Math.abs(i)) * 0.6); });
    for (const x of [-20, -9, 8, 19]) strokeP('rgba(5,4,9,.42)', 1.1, (k) => { k.moveTo(cx + x * 0.8, 92); k.quadraticCurveTo(cx + x * 1.1, 108, cx + x, CT); });
    rc(cx + 12, 92, 5, 5, '#27395a'); strokeP('rgba(174,191,212,.6)', 0.7, (k) => { k.moveTo(cx + 12, 92); k.lineTo(cx + 17, 97); k.moveTo(cx + 17, 92); k.lineTo(cx + 12, 97); });
  };
  c.head = (pose) => {
    ell(0, 0, 10.4, 11, rad(-2, 3, 15, '#d8ac94', '#946050', '#4a2e28'));
    fillP(lin(0, 2, 0, 56, '#c4c4c8', '#96969e', '#4a4a52', '#201b28'), (k) => { k.moveTo(-10.6, 0); k.bezierCurveTo(-15, 14, -13, 34, -7, 48); k.quadraticCurveTo(0, 58, 5, 48); k.bezierCurveTo(13, 34, 15, 14, 10.6, 0); k.quadraticCurveTo(7, 5, 3.4, 6); k.lineTo(-3.4, 6); k.quadraticCurveTo(-7, 5, -10.6, 0); });
    for (let i = -5; i <= 5; i++) strokeP('rgba(5,4,9,.38)', 0.8, (k) => { k.moveTo(i * 1.8, 12); k.bezierCurveTo(i * 2.8, 24, i * 1.2, 36, i * 1.5, 50 - Math.abs(i) * 2.4); });
    for (const s of [-1, 1]) fillP('#c4c4c8', (k) => { k.moveTo(0, 5); k.bezierCurveTo(s * 4, 3.4, s * 10, 6.5, s * 12.6, 14); k.bezierCurveTo(s * 8, 11, s * 4, 10, 0, 8.6); });
    fillP(rad(0, 2, 7, '#d8ac94', '#946050'), (k) => { k.moveTo(-1.6, -3); k.quadraticCurveTo(-3.6, 4, -2.8, 6); k.quadraticCurveTo(0.6, 8.6, 3.2, 5.4); k.quadraticCurveTo(3.4, 2, 1.4, -3); });
    for (const s of [-1, 1]) for (const [x, y, r] of [[2.6, -5, 1.8], [5.2, -5.8, 2.1], [8, -5, 1.7]]) ell(s * x, y, r, r * 0.8, '#96969e');
    // brim shadow swallows the eyes; what is left are two warm points
    g.fillStyle = lin(0, -8, 0, 3.6, 'rgba(5,4,9,.96)', 'rgba(5,4,9,.8)', 'rgba(5,4,9,0)'); g.fillRect(-11, -9, 22, 13);
    if (!pose.shut) for (const s of [-1, 1]) { rc(s * 4.3 - 0.9, -2, 1.9, 1.1, '#f0bb62'); glow(s * 4.3, -1.6, 3.4, '240,187,98', 0.5); }
    if (!pose.busy) { strokeP('#1c1210', 1.6, (k) => { k.moveTo(2.4, 8.6); k.quadraticCurveTo(9, 11, 14, 8.6); }); fillP('#40241a', (k) => { k.moveTo(12.4, 5.4); k.lineTo(18.4, 5.4); k.lineTo(17.4, 11); k.lineTo(13.4, 11); }); ell(15.4, 5.6, 2.6, 1.1, '#e0692a'); glow(15.4, 5, 7, '255,130,50', 0.75); }
    if (pose.foam) for (const [x, y, r] of [[-4, 7.4, 2], [0, 6.8, 2.2]]) ell(x, y, r, r * 0.75, '#fbe09a');
    // the hat: wide, patched, folded over on itself
    fillP(lin(-15, 0, 16, 0, '#27395a', '#3a5078', '#10182a'), (k) => { k.moveTo(-14, -8); k.bezierCurveTo(-10, -26, -5, -40, 4, -47); k.bezierCurveTo(11, -49, 19, -44, 23.4, -35); k.bezierCurveTo(17, -40, 12.4, -38, 11.4, -32.6); k.bezierCurveTo(11.4, -24, 12.6, -17, 14, -8); });
    strokeP('rgba(5,4,9,.5)', 1.1, (k) => { k.moveTo(11.4, -32.6); k.quadraticCurveTo(5.4, -35, 3, -31); k.moveTo(-8, -22); k.quadraticCurveTo(-2, -24.6, 7, -21); });
    rc(-7, -19, 6, 6, '#1a2740'); strokeP('rgba(174,191,212,.6)', 0.7, (k) => { k.moveTo(-7, -19); k.lineTo(-7, -13); k.lineTo(-1, -13); k.moveTo(-7, -16); k.lineTo(-5, -16); });
    rc(-14, -12.6, 28, 4.6, '#1c1210'); rc(-14, -12.6, 28, 1, '#58301f');
    ell(0, -6.6, 31, 6.4, lin(-31, 0, 31, 0, '#10182a', '#27395a', '#07060b')); ell(0, -7.8, 30.4, 4.4, lin(-31, 0, 31, 0, '#1a2740', '#3a5078', '#10182a'), Math.PI, 0); ell(0, -5.6, 17, 2.8, 'rgba(5,4,9,.7)');
    for (const x of [-27, 22]) fillP('#07060b', (k) => { k.moveTo(x, -4.4); k.lineTo(x + 3, -1); k.lineTo(x + 5.4, -4.6); });
  };
  return c;
}
function burglar(cx, patch) {   // hobbits: one hooded, one older and missing an eye
  const SK = ['#d8ac94', '#946050', '#4a2e28'], CL = patch ? ['#5c1c18', '#3a1414', '#0e0c14'] : ['#58301f', '#2c1a15', '#0e0c14'];
  const c = make({ cx, hy: 98, ny: 110, hr: 11.5, sw: 20, sy: 114, mouth: [0, 6.6], armW: 8.4, hand: 4.2, sleeve: [CL[0], CL[2]], cuff: '#1c1210', glove: [SK[1], SK[2]], cup: patch ? 'tin' : 'clay', cupS: patch ? 1.12 : 1.06, rest: 16, ...(patch ? { hearth: 0.03, lit: 0.12, backlit: true } : { side: -1 }) });
  c.sparkH = (pose) => { if (pose.shut) return; if (patch) { rc(4.2, -1.7, 1.6, 1.2, '#fbe09a'); glow(4.8, -1.2, 3.4, '255,200,120', 0.6); } else for (const s of [-1, 1]) { rc(s * 4.5 - 0.9, -1.6, 2, 1.1, '#f0bb62'); glow(s * 4.5, -1.2, 3.2, '240,187,98', 0.45); } };
  c.torso = () => {
    fillP(lin(cx - 22, 0, cx + 22, 0, CL[1], CL[0], CL[2]), (k) => { k.moveTo(cx - 23, CT + 2); k.bezierCurveTo(cx - 24, 118, cx - 20, 111, cx - 8, 109); k.lineTo(cx + 8, 109); k.bezierCurveTo(cx + 20, 111, cx + 24, 118, cx + 23, CT + 2); });
    if (patch) { for (let i = -4; i <= 4; i++) ell(cx + i * 3.6, 110.5 + Math.abs(i) * 0.5, 4, 4.4, i % 2 ? '#8a2a1c' : '#5c1c18'); strokeP('rgba(5,4,9,.5)', 0.8, (k) => { k.moveTo(cx - 13, 112); k.quadraticCurveTo(cx, 117, cx + 13, 112); }); }
    else { strokeP('rgba(5,4,9,.45)', 1, (k) => { k.moveTo(cx - 10, 114); k.lineTo(cx - 12, CT); k.moveTo(cx + 10, 114); k.lineTo(cx + 12, CT); }); ell(cx, 113, 2.2, 2.2, '#96969e'); }
  };
  c.head = (pose) => {
    if (!patch) fillP(lin(-16, 0, 16, 0, CL[1], CL[0], CL[2]), (k) => { k.moveTo(-15, 12); k.bezierCurveTo(-19, -4, -11, -18, 1, -19); k.bezierCurveTo(12, -18, 19, -4, 15, 12); k.quadraticCurveTo(0, 17, -15, 12); });
    else for (const s of [-1, 1]) for (const [x, y, r] of [[10.4, -3, 4], [11.6, 2, 3.4], [8.6, -7.4, 3.2]]) ell(s * x, y, r, r, '#6c6c76');
    for (const s of [-1, 1]) fillP(SK[1], (k) => { k.moveTo(s * 10, -2); k.quadraticCurveTo(s * 15.4, -5, s * 13.8, 3); k.quadraticCurveTo(s * 12, 4.6, s * 10.4, 3); });
    ell(0, 0.6, 11.4, 11, rad(-2, 2, 15.5, SK[0], SK[1], SK[2]));
    socket(4.5, -1.2, 1.05, pose, '#f0bb62'); scowl(4.5, -4.4, 0.95, patch ? '#6c6c76' : '#2c1a15', 2);
    ell(0, 3, 2.4, 2, '#946050'); grim(7.2, 3); for (let i = 0; i < 22; i++) rc(-7 + hash(i, 5) * 14, 4.6 + hash(i, 6) * 5.6, 0.9, 0.9, 'rgba(28,18,16,.45)');
    if (patch) { ell(-4.5, -1.2, 3.8, 3.2, '#07060b'); strokeP('#07060b', 1.2, (k) => { k.moveTo(-12, -6.4); k.lineTo(11, 1); }); strokeP('rgba(216,172,148,.6)', 0.9, (k) => { k.moveTo(3, -9.6); k.lineTo(6.6, 3.4); }); ell(-2, -8.6, 5, 2, 'rgba(216,172,148,.3)'); }
    else { for (const [x, y, r] of [[-5.4, -7.6, 3.4], [-1, -9, 3.6], [4, -8.4, 3.4], [7.6, -6, 2.6]]) ell(x, y, r, r, '#2c1a15'); g.fillStyle = lin(0, -12, 0, 2.6, 'rgba(5,4,9,.95)', 'rgba(5,4,9,.7)', 'rgba(5,4,9,0)'); g.fillRect(-12, -13, 24, 16); if (!pose.shut) for (const s of [-1, 1]) rc(s * 4.5 - 0.9, -1.6, 2, 1.1, '#f0bb62'); strokeP(CL[0], 1.2, (k) => { k.moveTo(-12, 9.6); k.bezierCurveTo(-15, -3, -8, -14.6, 1, -15.4); }); }
  };
  return c;
}
const CREW = [ironhelm(40), ranger(102), burglar(166, false), greybeard(230), berserker(294), knight(358), burglar(422, true)];

// ───────── baked layers: everything that never changes is painted once ─────────
const clamp = (v, a, b) => (v < a ? a : v > b ? b : v), smooth = (a, b, v) => { const t = clamp((v - a) / (b - a), 0, 1); return t * t * (3 - 2 * t); };
const ORDER = [1, 5, 3, 0, 4, 2, 6], N = CREW.length;
let ROOM, COUNTER, CANDLE, HAZE;
function bake() {
  rnd = mulberry(5);
  ROOM = layer(() => room());
  COUNTER = layer(() => counterBase());
  CANDLE = layer(() => { for (const x of CANDLES) candle(x); });
  HAZE = layer(() => {
    g.save(); g.filter = 'blur(5px)'; for (let i = 0; i < 12; i++) ell(rnd() * W, 34 + rnd() * 62, 50 + rnd() * 80, 3 + rnd() * 5, 'rgba(150,140,160,.06)'); g.restore();
    const v = g.createRadialGradient(W * 0.5, 84, 170, W * 0.5, 84, 360); v.addColorStop(0, 'rgba(4,3,7,0)'); v.addColorStop(1, 'rgba(4,3,7,.62)'); g.fillStyle = v; g.fillRect(0, 0, W, H);
  });
}
function shadowOf(L, blur, c) {
  const S = scratch(), s = S.getContext('2d'), x0 = Math.max(0, Math.floor(c.cx - 96)), bw = Math.min(W - x0, 192);
  s.filter = `blur(${blur}px)`; s.drawImage(L, x0, 0, bw, H, x0, 0, bw, H); s.filter = 'none'; s.globalCompositeOperation = 'source-in'; s.fillStyle = '#07040c'; s.fillRect(x0, 0, bw, H);
  return S;
}
const cache = new Map();
function piece(i, kind, st) {
  const key = st.key ? i + kind + st.key + (kind === 'b' && st.shut ? 'z' : '') : null;
  if (key && cache.has(key)) return cache.get(key);
  const c = CREW[i], L = layer(() => (kind === 'b' ? c.body(st) : c.arm(st)));
  light(L, c, kind === 'a');
  const out = { L, S: shadowOf(L, kind === 'b' ? 7 : 2.5, c), temp: !key };
  if (kind === 'b') { const prev = g; g = L.getContext('2d'); g.save(); c.spark(st); g.restore(); g = prev; }
  if (key) cache.set(key, out);
  return out;
}
// What each drinker is doing, from nothing but the progress number.
// A drinker owns one seventh of the bar, and starts reaching a little before the one beside them has put theirs down.
const T_UP = 0.3, T_SLAM = 1.9;   // seconds after 100%: the empties go up, hang there, and come down hard
function stateFor(i, p, tt, time) {
  const st = { lift: 0, tip: 0, bow: 0, bob: 0, hop: 0, dip: 0, toast: 0, hit: -1, full: true, shut: false, foam: false, busy: false, key: 'wait', time };
  if (p >= 1) {
    st.full = false; st.foam = true; st.bow = 1; st.key = 'done';
    const up = smooth(0, 0.42, tt - T_UP - i * 0.07), e = tt - T_SLAM - i * 0.05;
    if (up > 0 && e < 0.11) {
      const wind = Math.sin(clamp((e + 0.24) / 0.24, 0, 1) * Math.PI / 2) * 0.12, dn = clamp(e / 0.11, 0, 1);   // a breath in, then down
      st.toast = Math.max(0.0001, (up + wind) * (1 - dn * dn)); st.bow = 1 - up; st.key = up >= 1 && e <= -0.24 ? 'up' : '';
    } else if (e >= 0.11 && e < 0.4) {
      const k = e - 0.11; st.hit = k; st.hop = k < 0.14 ? Math.sin(k / 0.14 * Math.PI) * 1.6 : 0; st.dip = 2 * Math.max(0, 1 - k / 0.22); st.shut = k < 0.16; st.key = '';
    } else if (e >= 0.4) st.hit = e - 0.11;
  } else {
    const lead = i ? 0.22 : 0, u = (p * N - i + lead) / (1 + lead);
    if (u >= 1) { st.bow = 1; st.full = false; st.foam = true; st.key = 'done'; }
    else if (u > 0) {
      const dr = clamp((u - 0.8) / 0.13, 0, 1), land = clamp((u - 0.93) / 0.07, 0, 1);
      st.lift = smooth(0.08, 0.34, u) * (1 - dr * dr); st.tip = smooth(0.34, 0.76, u); st.full = u < 0.7;
      st.dip = Math.sin(clamp(u / 0.12, 0, 1) * Math.PI) * 1.2 + Math.sin(land * Math.PI) * 1.4;   // a look down at it first; a nod when it lands
      st.hop = Math.sin(land * Math.PI) * 1.3; st.bow = smooth(0.84, 1, u);
      st.shut = u > 0.24 && u < 0.86; st.busy = st.lift > 0.45; st.foam = u > 0.78;
      st.bob = st.lift > 0.97 ? Math.sin(time * 12) * 0.8 : 0;   // swallowing runs on the clock, so a stalled bar is a long drink
      st.key = '';
    }
  }
  if (st.key && (time * (0.19 + hash(i, 40) * 0.12) + hash(i, 41)) % 1 < 0.03) st.shut = true;   // everyone blinks
  return st;
}
function fire(time) {
  const f = 0.82 + 0.18 * (0.6 * vnoise(time * 7, 3) + 0.4 * vnoise(time * 17, 9));
  g.save(); g.beginPath(); hearthPath(g); g.clip();
  g.fillStyle = rad(HX + 52, CT + 8, 96, `rgba(255,190,100,${f})`, `rgba(226,100,36,${0.9 * f})`, 'rgba(138,36,20,.8)', 'rgba(58,16,14,.6)', 'rgba(8,5,8,0)'); g.fillRect(HX, 50, 104, CT - 50);
  for (let y = 62; y < CT; y += 9) rc(HX + 16, y, 72, 1, 'rgba(8,5,8,.22)');
  // a couple of dozen thin tongues, red ones behind and tall, pale ones in front and low
  const TIER = [['rgba(184,67,31,0)', '#b8431f', '#e0692a', '#f0bb62'], ['rgba(224,105,42,0)', '#e0692a', '#f0bb62', '#fbe09a'], ['rgba(240,187,98,0)', '#f0bb62', '#fbe09a', '#fff6d0']];
  for (let j = 0; j < 22; j++) {
    const tier = j < 10 ? 0 : j < 17 ? 1 : 2, q = hash(j, 21), dx = (hash(j, 22) - 0.5) * (64 - tier * 14), h0 = (52 - tier * 13) * (1 - 0.5 * (dx / 34) ** 2) * (0.6 + 0.4 * q);
    const fh = h0 * (0.6 + 0.62 * vnoise(time * (3.6 + tier + q) + j * 9.1, j)), x = HX + 52 + dx + (vnoise(time * 2.4 + j * 4, 7) - 0.5) * 7, sway = (vnoise(time * 2.3 + j * 1.7, 3) - 0.5) * fh * 0.6, wd = fh * 0.1 + 2.4;
    g.fillStyle = lin(0, CT - fh, 0, CT, ...TIER[tier]);
    g.beginPath(); g.moveTo(x - wd, CT + 1); g.bezierCurveTo(x - wd * 1.3, CT - fh * 0.4, x - wd * 0.15 + sway * 0.4, CT - fh * 0.64, x + sway, CT - fh); g.bezierCurveTo(x + wd * 0.45 + sway * 0.5, CT - fh * 0.66, x + wd * 1.3, CT - fh * 0.36, x + wd, CT + 1); g.fill();
  }
  for (let i = 0; i < 22; i++) { const ph = (time * (0.25 + hash(i, 1) * 0.3) + hash(i, 2)) % 1; rc(HX + 30 + hash(i, 3) * 44 + Math.sin(ph * 7 + i) * 4, CT - 22 - ph * 50, 1, 1, ph < 0.5 ? '#fbe09a' : '#e0692a'); }
  g.restore();
  glow(HX + 52, CT - 12, 100, '255,110,30', 0.22 * f);   // what spills onto the stone around it
  return f;
}
function rail(p, tt) {
  if (p <= 0) return;
  const w = (W - 40) * Math.min(1, p);
  g.fillStyle = lin(20, 0, 20 + w, 0, '#8a2a1c', '#e0692a', '#fbe09a'); g.fillRect(20, CT + 27, w, 5); rc(20, CT + 27, w, 1, 'rgba(255,246,208,.7)'); glow(20 + w, CT + 29, 16, '255,200,120', 0.95);
  const e = tt - T_SLAM - 0.42;   // the last cup lands and the whole rail takes
  if (p >= 1 && e > 0) {
    const k = Math.exp(-e * 2.2);
    g.save(); g.globalCompositeOperation = 'lighter'; g.fillStyle = `rgba(255,220,150,${0.8 * k})`; g.fillRect(20, CT + 26, W - 40, 7);
    g.fillStyle = lin(0, CT + 10, 0, CT + 34, 'rgba(255,150,60,0)', `rgba(255,150,60,${0.4 * k})`); g.fillRect(20, CT + 10, W - 40, 24); g.restore();
    for (let j = 0; j < 30; j++) { const ph = e * (0.7 + hash(j, 31) * 0.8) - hash(j, 32) * 0.3; if (ph > 0 && ph < 1) rc(24 + hash(j, 33) * (W - 48) + Math.sin(ph * 6 + j) * 2, CT + 27 - ph * (9 + hash(j, 34) * 15), 1, 1, ph < 0.5 ? '#fbe09a' : '#e0692a'); }
  }
}
// ───────── crush, with a lookup table so it runs every frame ─────────
const B4 = [0, 8, 2, 10, 12, 4, 14, 6, 3, 11, 1, 9, 15, 7, 13, 5], SPREAD = 10;
const RGB = PAL.map((h) => [parseInt(h.slice(1, 3), 16), parseInt(h.slice(3, 5), 16), parseInt(h.slice(5, 7), 16)]);
const PAL32 = new Uint32Array(RGB.map((c) => (255 << 24) | (c[2] << 16) | (c[1] << 8) | c[0]));
const LUT = new Uint8Array(32768);
for (let r = 0; r < 32; r++) for (let gg = 0; gg < 32; gg++) for (let b = 0; b < 32; b++) {
  let best = 0, bd = 1e9; const R = r * 8 + 4, G = gg * 8 + 4, Bv = b * 8 + 4;
  for (let q = 0; q < RGB.length; q++) { const c = RGB[q], e = 2 * (R - c[0]) ** 2 + 4 * (G - c[1]) ** 2 + 3 * (Bv - c[2]) ** 2; if (e < bd) { bd = e; best = q; } }
  LUT[(r << 10) | (gg << 5) | b] = best;
}
const sctx = soft.getContext('2d');
const outC = document.createElement('canvas'); outC.width = W; outC.height = H; const octx = outC.getContext('2d');
const outImg = octx.createImageData(W, H), out32 = new Uint32Array(outImg.data.buffer);
function crush() {
  const d = sctx.getImageData(0, 0, W, H).data;
  for (let y = 0, i = 0, j = 0; y < H; y++) for (let x = 0; x < W; x++, i += 4, j++) {
    const nz = ((B4[(y & 3) * 4 + (x & 3)] + 0.5) / 16 - 0.5) * SPREAD;
    let r = d[i] + nz, gg = d[i + 1] + nz, b = d[i + 2] + nz;
    r = r < 0 ? 0 : r > 255 ? 255 : r; gg = gg < 0 ? 0 : gg > 255 ? 255 : gg; b = b < 0 ? 0 : b > 255 ? 255 : b;
    out32[j] = PAL32[LUT[((r >> 3) << 10) | ((gg >> 3) << 5) | (b >> 3)]];
  }
  octx.putImageData(outImg, 0, 0);
}
const FONT = {
  A: ['.#.', '#.#', '###', '#.#', '#.#'], B: ['##.', '#.#', '##.', '#.#', '##.'], C: ['.##', '#..', '#..', '#..', '.##'], D: ['##.', '#.#', '#.#', '#.#', '##.'],
  E: ['###', '#..', '##.', '#..', '###'], F: ['###', '#..', '##.', '#..', '#..'], G: ['.##', '#..', '#.#', '#.#', '.##'], H: ['#.#', '#.#', '###', '#.#', '#.#'],
  I: ['###', '.#.', '.#.', '.#.', '###'], J: ['..#', '..#', '..#', '#.#', '.#.'], K: ['#.#', '#.#', '##.', '#.#', '#.#'], L: ['#..', '#..', '#..', '#..', '###'],
  M: ['#...#', '##.##', '#.#.#', '#...#', '#...#'], N: ['#..#', '##.#', '#.##', '#..#', '#..#'], O: ['.#.', '#.#', '#.#', '#.#', '.#.'], P: ['##.', '#.#', '##.', '#..', '#..'],
  Q: ['.#.', '#.#', '#.#', '.#.', '..#'], R: ['##.', '#.#', '##.', '#.#', '#.#'], S: ['.##', '#..', '.#.', '..#', '##.'], T: ['###', '.#.', '.#.', '.#.', '.#.'],
  U: ['#.#', '#.#', '#.#', '#.#', '###'], V: ['#.#', '#.#', '#.#', '#.#', '.#.'], W: ['#...#', '#...#', '#.#.#', '##.##', '#...#'], X: ['#.#', '#.#', '.#.', '#.#', '#.#'],
  Y: ['#.#', '#.#', '.#.', '.#.', '.#.'], Z: ['###', '..#', '.#.', '#..', '###'],
  0: ['###', '#.#', '#.#', '#.#', '###'], 1: ['.#.', '##.', '.#.', '.#.', '###'], 2: ['###', '..#', '###', '#..', '###'], 3: ['###', '..#', '###', '..#', '###'],
  4: ['#.#', '#.#', '###', '..#', '..#'], 5: ['###', '#..', '###', '..#', '###'], 6: ['###', '#..', '###', '#.#', '###'], 7: ['###', '..#', '..#', '..#', '..#'],
  8: ['###', '#.#', '###', '#.#', '###'], 9: ['###', '#.#', '###', '..#', '###'], '%': ['#.#', '..#', '.#.', '#..', '#.#'], '.': ['.', '.', '.', '.', '#'], '!': ['#', '#', '#', '.', '#'], ' ': ['..', '..', '..', '..', '..'],
};
function text(str, x, y, c, s = 1) {
  for (const ch of str) { const gl = FONT[ch]; for (let r = 0; r < 5; r++) for (let q = 0; q < gl[r].length; q++) if (gl[r][q] === '#') (g.fillStyle = c, g.fillRect(x + q * s, y + r * s, s, s)); x += (gl[0].length + 1) * s; }
  return x;
}
const textW = (str, s = 1) => [...str].reduce((a, ch) => a + (FONT[ch][0].length + 1) * s, -s);

// ───────── the demo load: a simulated task with one stall, then the empties come down ─────────
const KEYS = [[0, 0], [0.9, 0], [4.9, 0.44], [7.0, 0.636], [8.3, 0.636], [12.6, 1]];
const T_DONE = KEYS[KEYS.length - 1][0], DUR = 16.8;
function progressAt(t) {
  for (let k = 1; k < KEYS.length; k++) if (t <= KEYS[k][0]) { const [ta, pa] = KEYS[k - 1], [tb, pb] = KEYS[k]; return pa + (pb - pa) * (t - ta) / (tb - ta); }
  return 1;
}
// One frame of the bar, painted into outC at art size. It is the same for every bar on the page: nothing in here belongs to one element.
// time: seconds, for everything that runs on the clock. p: progress 0..1. tt: seconds since p reached 1
// Returns 1 on the frames where a cup has just hit the bar, and the picture is shown one art pixel lower.
function draw(time, p, tt) {
  g = sctx; g.globalAlpha = 1; g.drawImage(ROOM, 0, 0);
  const f = fire(time), sts = CREW.map((_, i) => stateFor(i, p, tt, time));
  for (const i of ORDER) { const { L, S, temp } = piece(i, 'b', sts[i]); g.globalAlpha = 0.7; g.drawImage(S, -9, 4); g.globalAlpha = 1; g.drawImage(L, 0, 0); if (temp) release(L, S); }
  g.drawImage(COUNTER, 0, 0); rail(p, tt);
  for (const i of ORDER) { const { L, S, temp } = piece(i, 'a', sts[i]); g.globalAlpha = 0.6; g.drawImage(S, -3, 3); g.globalAlpha = 1; g.drawImage(L, 0, 0); if (temp) release(L, S); }
  let rattle = 0, thud = 9;
  sts.forEach((st, i) => {   // what a cup does to the bar when it comes down
    if (st.hit < 0) return; thud = Math.min(thud, st.hit); if (st.hit < 0.034) rattle = 1;
    if (st.hit < 0.36) { const c = CREW[i], k = st.hit / 0.36, x = c.cx + c.side * c.rest; for (const d of [-1, 1]) ell(x + d * (8 + k * 13), CT + 2.6 - k * 2.6, 2 + k * 5, 1 + k * 1.6, `rgba(216,172,148,${0.44 * (1 - k)})`); }
  });
  g.drawImage(CANDLE, 0, 0);
  const gut = 1 - 0.62 * Math.exp(-thud * 4.5);   // the candles duck
  for (const x of CANDLES) flame(x, CT - 5.4, (0.95 + 0.22 * vnoise(time * 6 + x, 1)) * gut);
  g.save(); g.globalCompositeOperation = 'lighter';
  for (const x of CANDLES) glow(x, CT - 10, 36, '120,60,20', (0.22 + 0.1 * vnoise(time * 6 + x, 1)) * gut); glow(HX + 52, 104, 120, '130,50,12', 0.16 * f);
  g.restore();
  const wz = CREW[3];
  if (!sts[3].busy) for (let j = 0; j < 6; j++) { const ph = (time * 0.22 + j / 6) % 1; glow(wz.cx + 17 + Math.sin(ph * 5 + j) * 4 + ph * 7, wz.hy + 3 - ph * 48, (3 + ph * 8) * 1.7, '170,170,190', 0.24 * (1 - ph)); }
  g.drawImage(HAZE, 0, 0);
  for (let i = 0; i < 40; i++) { const x = 140 + hash(i, 11) * 130 + Math.sin(time * 0.3 + i) * 5, y = 40 + ((hash(i, 12) * 76 - time * (1 + hash(i, 13) * 2)) % 76 + 76) % 76; rc(x, y, 1, 1, `rgba(170,190,240,${0.1 + hash(i, 14) * 0.3})`); }
  crush();
  g = octx;
  const done = p >= 1, label = done ? 'DONE' : 'LOADING ' + Math.floor(p * 100) + '%', tw = textW(label, 2), x = Math.round(W / 2 - tw / 2), flash = done && tt > T_SLAM + 0.42 && tt < T_SLAM + 0.75;
  text(label, x + 1, CT + 14, '#07060b', 2); text(label, x, CT + 13, flash ? '#fff6d0' : done ? '#fbe09a' : '#b98470', 2);
  return rattle;
}

// ───────── the element ─────────
const SHEET = ':host{display:block}:host([hidden]){display:none}canvas{display:block;max-width:100%;height:auto;image-rendering:pixelated}';
const SCALES = [4, 3, 2.5, 2, 1.5, 1];   // canvas pixels per art pixel: the largest that fits is used
// every bar on the page is painted from one loop, with the same baked layers, pose cache and scratch canvases
const LIVE = new Set(); let ticking = false, last = 0, baked = false, paused = false;
function loop(now) { if (!LIVE.size || paused) { ticking = false; return; } const dt = Math.max(0, (now - last) / 1000); last = now; for (const el of LIVE) el._step(dt, Math.min(0.1, dt)); requestAnimationFrame(loop); }
function wake() { if (!ticking && LIVE.size && !paused) { ticking = true; last = performance.now(); requestAnimationFrame(loop); } }
addEventListener('resize', () => { for (const el of LIVE) el._fit(); });   // a zoom changes the pixel ratio without always changing the element's width
class RoundBar extends HTMLElement {
  static get observedAttributes() { return ['value', 'label']; }
  static get paused() { return paused; }
  static set paused(v) { paused = !!v; wake(); }   // true stops the clock, so you can step a bar yourself with el.advance(seconds)
  constructor() {
    super();
    const root = this.attachShadow({ mode: 'open' });
    root.innerHTML = `<style>${SHEET}</style><canvas part="bar" role="progressbar" aria-label="Loading" aria-valuemin="0" aria-valuemax="100" aria-valuenow="0" style="cursor:pointer"></canvas>`;
    this._cv = root.querySelector('canvas'); this._vctx = this._cv.getContext('2d');
    // What belongs to this bar. target: the value it was last given, or null while it plays the demo. shown: the progress it is showing.
    // time: its own clock, in seconds. demo: how far into the demo load it is. doneAt: its clock when shown reached 1. full: whether it has said so.
    this._s = { target: null, shown: 0, time: 0, demo: 0, doneAt: null, full: false };
    this._k = 0; this._w = 0; this._dpr = 0; this._pc = 0;
    this._cv.addEventListener('click', () => { if (this._s.target === null) this.demo(); });   // a click replays the demo; it never touches a real load
    this._ro = new ResizeObserver((e) => this._fit(e[e.length - 1].contentRect.width));
  }
  connectedCallback() { if (!baked) { bake(); baked = true; } LIVE.add(this); this._ro.observe(this); this._fit(this.clientWidth); wake(); }
  disconnectedCallback() { LIVE.delete(this); this._ro.disconnect(); }
  attributeChangedCallback(name, was, v) {
    if (name === 'label') this._cv.setAttribute('aria-label', v || 'Loading');
    else if (v === null) this.demo(); else this.set(v);
  }
  _fit(w) {   // the largest scale whose canvas fits this element's width in device pixels, shown at one canvas pixel per device pixel
    if (w !== undefined) this._w = w;
    const dpr = window.devicePixelRatio || 1, k = SCALES.find((s) => W * s <= Math.round(this._w * dpr)) || 1, cv = this._cv;
    if (k === this._k && dpr === this._dpr) return;
    this._k = k; this._dpr = dpr; cv.width = W * k; cv.height = H * k; cv.style.width = W * k / dpr + 'px'; this._vctx.imageSmoothingEnabled = false;
    this._paint();
  }
  // set(0.37): the task's progress, 0 to 1, as often as you like. The bar eases toward it, so a jump from 10% to 60% still gives each drinker a turn.
  // set(0.37, true) goes straight there instead. At 1 that is the settled end, with the cups already down.
  set(v, jump) {
    const s = this._s; s.target = clamp(+v || 0, 0, 1); this._cv.style.cursor = '';
    if (jump) { s.shown = s.target; s.doneAt = s.target < 1 ? null : s.time - 9; this._paint(); }
  }
  demo() { Object.assign(this._s, { target: null, shown: 0, demo: 0, doneAt: null }); this._cv.style.cursor = 'pointer'; }   // play the demo load from the start, on a loop
  get value() { const s = this._s; return s.target === null ? null : s.shown; }   // the progress it is showing, or null while it plays the demo
  set value(v) { if (v === null || v === undefined) this.demo(); else this.set(v); }
  get demoLength() { return DUR; }   // seconds in one demo load
  advance(seconds) { const dt = Math.max(0, +seconds || 0); this._step(dt, dt); }   // move this bar's clock on and paint it
  _step(dt, ease) {
    const s = this._s; s.time += dt;
    if (s.target === null) s.demo += dt;
    else {   // eased toward the reported value
      const d = s.target - s.shown, r = Math.max(0.25, Math.abs(d) * 2) * ease; s.shown += clamp(d, -r, r);
      if (s.shown < 1) s.doneAt = null; else if (s.doneAt === null) s.doneAt = s.time;
    }
    this._paint();
  }
  _paint() {
    const s = this._s, cv = this._cv, v = this._vctx; let time, p, tt;
    if (s.target === null) { time = s.demo % (DUR + 1); p = progressAt(time); tt = time - T_DONE; }
    else { time = s.time; p = s.shown; tt = s.doneAt === null ? -1 : s.time - s.doneAt; }
    if (this._k) {   // it has a canvas to paint once it has been on a page
      const rattle = draw(time, p, tt), k = cv.width / W;
      if (rattle) { v.fillStyle = '#040306'; v.fillRect(0, 0, cv.width, k); v.drawImage(outC, 0, 0, W, H - 1, 0, k, cv.width, cv.height - k); }
      else v.drawImage(outC, 0, 0, cv.width, cv.height);
    }
    const pc = Math.round(p * 100); if (pc !== this._pc) { this._pc = pc; cv.setAttribute('aria-valuenow', pc); }
    const full = s.target !== null && p >= 1, say = full && !s.full; s.full = full;   // the demo is not a real load, so it does not say it is done
    if (say) this.dispatchEvent(new CustomEvent('round:done', { bubbles: true, composed: true }));
  }
}
customElements.define('round-bar', RoundBar);
})();
