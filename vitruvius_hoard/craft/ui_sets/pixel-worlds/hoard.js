// Hoard: a hold-to-delete button with a dragon asleep in it.
// Hover and one eye opens. Hold and he breathes in, then the fire crosses the button: that is the fill.
// Let go early and he swallows it. Hold to the end and the card it sits on is scorched.
// Everything is painted in code at 192 x 40, lit, and crushed to a fixed palette every frame. No assets, no network.
//
// One file, no dependencies. Load it with a script tag and put <hoard-button></hoard-button> where the button goes.
// Give it a heading and it draws the parchment card round itself as well. It fires "hoard:delete" once, when the hold completes.
(() => {
'use strict';
function mulberry(seed) { let a = seed >>> 0; return () => { a = (a + 0x6D2B79F5) >>> 0; let t = a; t = Math.imul(t ^ (t >>> 15), t | 1); t ^= t + Math.imul(t ^ (t >>> 7), t | 61); return ((t ^ (t >>> 14)) >>> 0) / 4294967296; }; }
function hash(x, y) { let h = (x * 374761393 + y * 668265263) | 0; h = (h ^ (h >>> 13)) * 1274126177 | 0; return ((h ^ (h >>> 16)) >>> 0) / 4294967296; }
function vnoise(x, y) { const xi = Math.floor(x), yi = Math.floor(y), fx = x - xi, fy = y - yi, sx = fx * fx * (3 - 2 * fx), sy = fy * fy * (3 - 2 * fy), l = (a, b, t) => a + (b - a) * t; return l(l(hash(xi, yi), hash(xi + 1, yi), sx), l(hash(xi, yi + 1), hash(xi + 1, yi + 1), sx), sy); }
const fbm = (x, y) => 0.55 * vnoise(x, y) + 0.3 * vnoise(x * 2.1, y * 2.1 + 7) + 0.15 * vnoise(x * 4.3, y * 4.3 + 19);
const clamp = (v, a, b) => (v < a ? a : v > b ? b : v), mix = (a, b, t) => a + (b - a) * t, smooth = (a, b, v) => { const t = clamp((v - a) / (b - a), 0, 1); return t * t * (3 - 2 * t); };

const W = 192, H = 40, HOLD = 1.7;   // the button's scene in art pixels, and how long you have to hold, in seconds
const PAL = [
  '#04050a', '#090b15', '#101322', '#181c32',
  '#1a2444', '#243560', '#32497c', '#46639a', '#6584b8', '#8eaad2', '#bccbe6', '#e4ecf6',
  '#221d38', '#332a52', '#473a6c', '#62528a',
  '#0b2024', '#113236', '#194848', '#24645c', '#348270', '#4fa488', '#7cc8a4', '#b4e8c4',
  '#2c4226', '#4c6a34', '#7c9448',
  '#24160c', '#3e260e', '#5e3b0f', '#855714', '#ae7a1c', '#d4a02c', '#f0ca4a', '#fbe88a', '#fffbd4',
  '#4a1010', '#7c1e12', '#b03a16', '#e0641e', '#f89a38',
  '#3c3430', '#6a5c50', '#9c8a70', '#cdb992', '#eedfb8',
  '#2c2e3e', '#474a5e', '#6c7088', '#9a9eb4',
  '#6a1626', '#a02a3a', '#c84a56', '#e0cfa0',
];
const mk = (w, h) => Object.assign(document.createElement('canvas'), { width: w, height: h });
const soft = mk(W, H), sctx = soft.getContext('2d', { willReadFrequently: true });
let g = sctx;
const POOL = [];
function scratch() { const c = POOL.pop() || mk(W, H), x = c.getContext('2d'); x.setTransform(1, 0, 0, 1, 0, 0); x.globalAlpha = 1; x.globalCompositeOperation = 'source-over'; x.filter = 'none'; x.clearRect(0, 0, W, H); return c; }
const release = (...cs) => { for (const c of cs) if (c) POOL.push(c); };
function layer(draw) { const L = scratch(), prev = g; g = L.getContext('2d'); g.save(); draw(); g.restore(); g = prev; return L; }
const rc = (x, y, w, h, c) => { g.fillStyle = c; g.fillRect(x, y, w, h); };
function glow(x, y, r, rgb, a) { const gr = g.createRadialGradient(x, y, 0, x, y, r); gr.addColorStop(0, `rgba(${rgb},${a})`); gr.addColorStop(1, `rgba(${rgb},0)`); g.fillStyle = gr; g.fillRect(x - r, y - r, r * 2, r * 2); }
const lin = (x0, y0, x1, y1, ...st) => { const gr = g.createLinearGradient(x0, y0, x1, y1); st.forEach((c, i) => gr.addColorStop(i / (st.length - 1), c)); return gr; };
const rad = (x, y, r, ...st) => { const gr = g.createRadialGradient(x, y, 0.5, x, y, r); st.forEach((c, i) => gr.addColorStop(i / (st.length - 1), c)); return gr; };
const ell = (x, y, rx, ry, c, a0 = 0, a1 = 7, rot = 0) => { g.fillStyle = c; g.beginPath(); g.ellipse(x, y, rx, ry, rot, a0, a1); g.fill(); };
const fillP = (c, fn) => { g.fillStyle = c; g.beginPath(); fn(g); g.fill(); };
const strokeP = (c, w, fn) => { g.strokeStyle = c; g.lineWidth = w; g.lineCap = 'round'; g.lineJoin = 'round'; g.beginPath(); fn(g); g.stroke(); };
const poly = (pts, c) => fillP(c, (k) => pts.forEach(([x, y], i) => (i ? k.lineTo(x, y) : k.moveTo(x, y))));

// ───────── light ─────────
// Every layer is multiplied by the same map: a cold ambient plus whatever is giving light in this frame.
function lit(L, S) {
  const k = L.getContext('2d'), M = scratch(), m = M.getContext('2d');
  m.fillStyle = S.amb; m.fillRect(0, 0, W, H); m.globalCompositeOperation = 'lighter';
  for (const [x, y, r, rgb, a] of S.lights) {
    const s = Math.min(1, a), gr = m.createRadialGradient(x, y, 2, x, y, r); gr.addColorStop(0, `rgba(${rgb},${s})`); gr.addColorStop(0.42, `rgba(${rgb},${s * 0.5})`); gr.addColorStop(1, `rgba(${rgb},0)`);
    m.fillStyle = gr; m.fillRect(0, 0, W, H);
  }
  m.globalCompositeOperation = 'destination-in'; m.drawImage(L, 0, 0);
  k.globalCompositeOperation = 'multiply'; k.drawImage(M, 0, 0); k.globalCompositeOperation = 'source-over'; release(M);
  return L;
}
function rim(L, dx, dy, x, y, r, rgb, a, occ) {
  if (a <= 0) return;
  const k = L.getContext('2d'), R = scratch(), q = R.getContext('2d');
  q.drawImage(L, 0, 0); q.globalCompositeOperation = 'source-in';
  const gr = q.createRadialGradient(x, y, 2, x, y, r); gr.addColorStop(0, `rgba(${rgb},${a})`); gr.addColorStop(0.5, `rgba(${rgb},${a * 0.6})`); gr.addColorStop(1, `rgba(${rgb},0)`);
  q.fillStyle = gr; q.fillRect(0, 0, W, H); q.globalCompositeOperation = 'destination-out'; q.drawImage(L, dx, dy); if (occ) q.drawImage(occ, 0, 0);
  k.globalCompositeOperation = 'source-atop'; k.drawImage(R, 0, 0); k.globalCompositeOperation = 'source-over'; release(R);
}

// ───────── the dragon ─────────
let HS = 0.86;
const SC = '#3a8c78', DK = '#1b4c4e', LT = '#6cbc9a', BONE = '#ece2c6', BELLY = '#d8c690', MEM = '#5a4884';
const bez = (p, t) => { const u = 1 - t; return [0, 1].map((i) => u * u * u * p[0][i] + 3 * u * u * t * p[1][i] + 3 * u * t * t * p[2][i] + t * t * t * p[3][i]); };
function path(p, n = 44) {
  const pts = []; for (let i = 0; i <= n; i++) pts.push(bez(p, i / n));
  return pts.map((q, i) => { const a = pts[Math.max(0, i - 1)], b = pts[Math.min(n, i + 1)], dx = b[0] - a[0], dy = b[1] - a[1], l = Math.hypot(dx, dy) || 1; return { x: q[0], y: q[1], nx: -dy / l, ny: dx / l, t: i / n }; });
}
function tube(P, r, col) {
  fillP(col, (k) => { P.forEach((p, i) => { const R = r(p.t); i ? k.lineTo(p.x - p.nx * R, p.y - p.ny * R) : k.moveTo(p.x - p.nx * R, p.y - p.ny * R); }); for (let i = P.length - 1; i >= 0; i--) { const p = P[i], R = r(p.t); k.lineTo(p.x + p.nx * R, p.y + p.ny * R); } });
  const a = P[0], b = P[P.length - 1]; ell(a.x, a.y, r(0), r(0), col); ell(b.x, b.y, r(1), r(1), col);
}
function plates(P, r, each, step = 3) {
  for (let i = step; i + step < P.length; i += step) {
    const a = P[i], b = P[i + step - 0.0 | 0], Ra = r(a.t), Rb = r(b.t), back = 0.86;
    const bx = mix(a.x, b.x, back), by = mix(a.y, b.y, back), bnx = mix(a.nx, b.nx, back), bny = mix(a.ny, b.ny, back), Rm = mix(Ra, Rb, back);
    each([[a.x + a.nx * Ra * 0.34, a.y + a.ny * Ra * 0.34], [a.x + a.nx * Ra * 1.0, a.y + a.ny * Ra * 1.0], [bx + bnx * Rm * 1.0, by + bny * Rm * 1.0], [bx + bnx * Rm * 0.34, by + bny * Rm * 0.34]], (a.t + b.t) / 2);
  }
}
function scales(clip, x0, y0, x1, y1) {
  g.save(); clip(); g.clip();
  for (let y = y0, j = 0; y < y1; y += 4.2, j++) for (let x = x0 + (j & 1) * 3; x < x1; x += 6) { strokeP('rgba(8,30,36,.34)', 0.9, (k) => k.arc(x, y, 3, 0.15, Math.PI - 0.15)); strokeP('rgba(190,240,214,.13)', 0.7, (k) => k.arc(x, y - 1.2, 3, Math.PI + 0.5, Math.PI * 2 - 0.5)); }
  g.restore();
}
function horn(x0, y0, x1, y1, w, c) { const mx = (x0 + x1) / 2, my = (y0 + y1) / 2 - 5; fillP(c, (k) => { k.moveTo(x0 + 1.5, y0 - w / 2); k.quadraticCurveTo(mx, my - w / 3, x1, y1); k.quadraticCurveTo(mx, my + w / 2, x0 - 1.5, y0 + w / 2); k.closePath(); }); }
const headXf = (o) => { g.translate(o.hb[0], o.hb[1]); g.rotate(o.ang); g.scale(HS, HS); };
const headPt = (o, x, y) => { const c = Math.cos(o.ang), s = Math.sin(o.ang); return [o.hb[0] + (x * c - y * s) * HS, o.hb[1] + (x * s + y * c) * HS]; };
function head(o) {
  g.save(); headXf(o);
  horn(-1, -6, -27, -11, 3.4, '#b4a886');
  poly([[3, -1], [-14, -4], [-2, 4]], '#56a88c'); poly([[3, 3], [-13, 6], [0, 10]], '#4a9c84'); poly([[4, 8], [-8, 14], [5, 12]], '#3a8c78');
  // inside of the mouth, then the lower jaw on its hinge
  if (o.jaw > 0.02 && !o.fire) fillP('#3a0c10', (k) => { k.moveTo(9, 5); k.lineTo(49, 3); k.lineTo(9 + 40 * Math.cos(o.jaw), 5 + 40 * Math.sin(o.jaw) + 2); k.closePath(); });
  g.save(); g.translate(9, 5); g.rotate(o.jaw); g.translate(-9, -5);
  for (const x of [25, 31, 37, 42.5, 46]) poly([[x - 1.2, 5], [x, 1.4], [x + 1.2, 5]], BONE);
  fillP(lin(0, 4, 0, 14, '#34806e', DK), (k) => { k.moveTo(1, 3); k.lineTo(47, 4.6); k.quadraticCurveTo(51, 7, 46, 9.6); k.lineTo(21, 12.6); k.quadraticCurveTo(7, 15, -5, 9); k.closePath(); });
  strokeP(BELLY, 1.7, (k) => { k.moveTo(9, 12.6); k.lineTo(44, 9.2); });
  poly([[28, 11.4], [26, 16.5], [32, 11]], '#56a88c'); poly([[36, 10.4], [35, 14.5], [39.5, 10]], '#56a88c');
  g.restore();
  // skull and snout
  fillP(lin(0, -13, 0, 7, LT, SC, DK), (k) => { k.moveTo(-8, -7); k.quadraticCurveTo(4, -14.5, 16, -11.5); k.lineTo(25, -8.5); k.quadraticCurveTo(35, -4.6, 44, -5.6); k.quadraticCurveTo(48, -9.4, 51.5, -5.6); k.quadraticCurveTo(55.5, -1.4, 52, 2.8); k.lineTo(30, 4.4); k.quadraticCurveTo(18, 5.6, 10, 6.2); k.quadraticCurveTo(0, 10.5, -8, 9.5); k.closePath(); });
  scales(() => { g.beginPath(); g.rect(-8, -13, 30, 22); }, -8, -11, 22, 9);
  for (const x of [24, 30, 36, 42]) poly([[x - 1.2, 3.8], [x, 7.2], [x + 1.2, 3.8]], BONE);
  poly([[45.4, 3], [47, 9], [48.8, 2.8]], BONE); poly([[49.6, 2.8], [50.8, 7], [52.2, 2.4]], BONE);
  strokeP('rgba(8,26,32,.55)', 0.9, (k) => { k.moveTo(11, 6); k.quadraticCurveTo(30, 4.4, 52, 2.8); });
  ell(48.4, -4.6, 1.5, 1, '#081c20', 0, 7, -0.3);
  for (const x of [28, 33, 38]) poly([[x - 1.6, -6.6 + (x - 28) * 0.16], [x - 0.4, -10 + (x - 28) * 0.26], [x + 1.6, -6 + (x - 28) * 0.16]], '#8fd4b4');
  // brow, eye, horn
  ell(19, -4.6, 4.4, 2.8, o.eye > 0.05 ? '#0a2428' : '#1c5450');
  if (o.eye <= 0.05) strokeP('#06181c', 1.2, (k) => { k.moveTo(15, -4.4); k.quadraticCurveTo(19, -2.8, 23.6, -4.8); });
  poly([[8, -12.4], [27.5, -8.6], [24.5, -6], [12, -7.4]], '#2a6f62');
  horn(6, -11.5, -25, -25, 4.6, BONE); strokeP('rgba(120,104,70,.6)', 0.8, (k) => { k.moveTo(1, -12.6); k.lineTo(0, -15.6); k.moveTo(-6, -15.4); k.lineTo(-7.4, -18.6); k.moveTo(-13, -18.6); k.lineTo(-14.2, -21.4); });
  g.restore();
}
function face(o) {
  g.save(); headXf(o);
  if (o.eye > 0.05) { ell(19.2, -4.7, 3.5, 2.2 * o.eye, '#f6b62c'); ell(19.2, -4.7, 2.2, 1.5 * o.eye, '#ffe37a'); rc(18.7, -4.7 - 2 * o.eye, 1.1, 4 * o.eye, '#160804'); if (o.lid) fillP('#2a6f62', (k) => { k.moveTo(14.4, -8.4); k.lineTo(24.4, -8); k.lineTo(24.2, -5.2 - (1 - o.lid) * 1.6); k.lineTo(14.6, -5.4 - (1 - o.lid) * 1.6); }); }
  if (o.glow > 0.55) { const a = smooth(0.55, 1, o.glow); ell(48.4, -4.6, 1.5, 1, `rgba(255,170,60,${a})`, 0, 7, -0.3); if (o.jaw > 0.02 && !o.fire) fillP(`rgba(255,150,40,${0.85 * a})`, (k) => { k.moveTo(12, 5.4); k.lineTo(46, 4); k.lineTo(12 + 34 * Math.cos(o.jaw), 6 + 34 * Math.sin(o.jaw) + 1); k.closePath(); }); }
  g.restore();
  if (o.eye > 0.05) { const [ex, ey] = headPt(o, 19.2, -4.7); g.save(); g.globalCompositeOperation = 'lighter'; glow(ex, ey, 9, '255,170,40', 0.34 * o.eye); g.restore(); }
}

// ───────── lettering, in the same pixels as the art ─────────
const FONT = {   // 5 x 7, caps only
  A: '.###. #...# #...# ##### #...# #...# #...#', B: '####. #...# #...# ####. #...# #...# ####.', C: '.###. #...# #.... #.... #.... #...# .###.', D: '####. #...# #...# #...# #...# #...# ####.',
  E: '##### #.... #.... ####. #.... #.... #####', F: '##### #.... #.... ####. #.... #.... #....', G: '.###. #...# #.... #.### #...# #...# .###.', H: '#...# #...# #...# ##### #...# #...# #...#',
  I: '### .#. .#. .#. .#. .#. ###', J: '..### ...#. ...#. ...#. ...#. #..#. .##..', K: '#...# #..#. #.#.. ##... #.#.. #..#. #...#', L: '#.... #.... #.... #.... #.... #.... #####',
  M: '#...# ##.## #.#.# #.#.# #...# #...# #...#', N: '#...# ##..# #.#.# #..## #...# #...# #...#', O: '.###. #...# #...# #...# #...# #...# .###.', P: '####. #...# #...# ####. #.... #.... #....',
  Q: '.###. #...# #...# #...# #.#.# #..#. .##.#', R: '####. #...# #...# ####. #.#.. #..#. #...#', S: '.#### #.... #.... .###. ....# ....# ####.', T: '##### ..#.. ..#.. ..#.. ..#.. ..#.. ..#..',
  U: '#...# #...# #...# #...# #...# #...# .###.', V: '#...# #...# #...# #...# #...# .#.#. ..#..', W: '#...# #...# #...# #.#.# #.#.# ##.## #...#', X: '#...# #...# .#.#. ..#.. .#.#. #...# #...#',
  Y: '#...# #...# .#.#. ..#.. ..#.. ..#.. ..#..', Z: '##### ....# ...#. ..#.. .#... #.... #####', 0: '.###. #...# #..## #.#.# ##..# #...# .###.', 1: '.#. ##. .#. .#. .#. .#. ###',
  2: '.###. #...# ....# ...#. ..#.. .#... #####', 3: '####. ....# ....# .###. ....# ....# ####.', 4: '...#. ..##. .#.#. #..#. ##### ...#. ...#.', 5: '##### #.... ####. ....# ....# #...# .###.',
  6: '.###. #.... #.... ####. #...# #...# .###.', 7: '##### ....# ...#. ..#.. ..#.. ..#.. ..#..', 8: '.###. #...# #...# .###. #...# #...# .###.', 9: '.###. #...# #...# .#### ....# ....# .###.',
  '.': '. . . . . . #', "'": '# # . . . . .', '"': '#.# #.# ... ... ... ... ...', '-': '.... .... .... #### .... .... ....',
  '?': '.###. #...# ....# ...#. ..#.. ..... ..#..', '!': '# # # # # . #', ' ': '... ... ... ... ... ... ...',
};
for (const k in FONT) FONT[k] = FONT[k].split(' ');
const glyphs = (str) => [...str.toUpperCase().replace(/[“”]/g, '"').replace(/’/g, "'")].map((ch) => FONT[ch] || FONT[' ']);
function ptext(str, x, y, c, bold) { for (const gl of glyphs(str)) { for (let r = 0; r < 7; r++) for (let q = 0; q < gl[r].length; q++) if (gl[r][q] === '#') rc(x + q, y + r, bold ? 2 : 1, 1, c); x += gl[0].length + (bold ? 2 : 1); } }
const ptextW = (str, bold) => glyphs(str).reduce((a, gl) => a + gl[0].length + (bold ? 2 : 1), -1);
function ptext2(str, x, y, splitX, cA, cB, w, h) {
  g.save(); g.beginPath(); g.rect(0, 0, splitX, h); g.clip(); ptext(str, x, y, cA, 1); g.restore();
  g.save(); g.beginPath(); g.rect(splitX, 0, w, h); g.clip(); ptext(str, x, y, cB, 1); g.restore();
}

// ───────── crush: every pixel to the nearest palette colour, with a 4 x 4 ordered dither ─────────
const B4 = [0, 8, 2, 10, 12, 4, 14, 6, 3, 11, 1, 9, 15, 7, 13, 5], SPREAD = 10;
const RGB = PAL.map((h) => [parseInt(h.slice(1, 3), 16), parseInt(h.slice(3, 5), 16), parseInt(h.slice(5, 7), 16)]);
const u32 = (h) => (255 << 24) | (parseInt(h.slice(5, 7), 16) << 16) | (parseInt(h.slice(3, 5), 16) << 8) | parseInt(h.slice(1, 3), 16);
const PAL32 = new Uint32Array(PAL.map(u32)), LUT = new Uint8Array(32768);
for (let r = 0; r < 32; r++) for (let gg = 0; gg < 32; gg++) for (let b = 0; b < 32; b++) {
  let best = 0, bd = 1e9; const R = r * 8 + 4, G = gg * 8 + 4, Bv = b * 8 + 4;
  for (let q = 0; q < RGB.length; q++) { const c = RGB[q], e = 2 * (R - c[0]) ** 2 + 4 * (G - c[1]) ** 2 + 3 * (Bv - c[2]) ** 2; if (e < bd) { bd = e; best = q; } }
  LUT[(r << 10) | (gg << 5) | b] = best;
}
const art = mk(W, H), actx = art.getContext('2d'), artImg = actx.createImageData(W, H), art32 = new Uint32Array(artImg.data.buffer);
function crush() {
  const d = sctx.getImageData(0, 0, W, H).data;
  for (let y = 0, i = 0, j = 0; y < H; y++) for (let x = 0; x < W; x++, i += 4, j++) {
    const nz = ((B4[(y & 3) * 4 + (x & 3)] + 0.5) / 16 - 0.5) * SPREAD;
    let r = d[i] + nz, gg = d[i + 1] + nz, b = d[i + 2] + nz;
    r = r < 0 ? 0 : r > 255 ? 255 : r; gg = gg < 0 ? 0 : gg > 255 ? 255 : gg; b = b < 0 ? 0 : b > 255 ? 255 : b;
    art32[j] = PAL32[LUT[((r >> 3) << 10) | ((gg >> 3) << 5) | (b >> 3)]];
  }
  actx.putImageData(artImg, 0, 0);
}

// ───────── the scene inside the button ─────────
const COIN = ['#b8851e', '#dcaa30', '#94641a', '#f0ca4a', '#c8962a'];
let CAVE, COINS;
function bake() {   // the things that never change, painted once in their own colours
  CAVE = mk(W, H); COINS = mk(W, H);
  const prev = g; g = CAVE.getContext('2d');
  g.fillStyle = lin(0, 0, 0, H, '#6a6890', '#7a78a2', '#55537a'); g.fillRect(0, 0, W, H);
  for (let y = 0; y < H; y += 2) for (let x = 0; x < W; x += 2) { const v = (fbm(x * 0.02 + 3, y * 0.09) - 0.5) * 0.6 + (fbm(x * 0.1 + 40, y * 0.2) - 0.5) * 0.4; rc(x, y, 2, 2, v > 0 ? `rgba(196,196,236,${v * 0.5})` : `rgba(10,8,24,${-v * 0.95})`); }
  let rnd = mulberry(6); for (let i = 0; i < 7; i++) strokeP('rgba(12,10,26,.4)', 1, (k) => { let x = rnd() * W, y = 4 + rnd() * 26; k.moveTo(x, y); for (let j = 0; j < 4; j++) { x += 8 + rnd() * 18; y += (rnd() - 0.42) * 5; k.lineTo(x, y); } });
  g.fillStyle = lin(0, 35, 0, H, '#5a5878', '#3c3a54'); g.fillRect(0, 35, W, 5); rc(0, 35, W, 1, 'rgba(210,210,245,.3)');
  g = COINS.getContext('2d');
  const CP = new Path2D('M -2 42 L -2 35 Q 16 31 40 35 Q 56 36 68 42 Z'); g.fillStyle = '#94641a'; g.fill(CP); rnd = mulberry(5);
  for (let i = 0; i < 150; i++) { const x = rnd() * 72 - 2, y = 31 + rnd() * 10; if (!g.isPointInPath(CP, x, y)) continue; const rx = 1.5 + rnd(); ell(x, y, rx, rx * 0.46, COIN[i % 5]); rc(x - rx * 0.5, y - 0.9, rx, 0.6, 'rgba(255,246,190,.55)'); }
  g = prev;
}
const FLAME = [[1, '#e0641e', '#b03a16'], [0.74, '#f89a38', '#e0641e'], [0.5, '#fbe88a', '#f89a38'], [0.24, '#fffbd4', '#fbe88a']];
function stream(mx, my, fx, time, a) {   // the fire is the fill: out of the mouth, opening to the full height, with a ragged front that keeps moving
  const L = fx - mx; if (L <= 0) return;
  g.save(); g.globalAlpha = a;
  // licks running ahead of the front, so it arrives ragged
  if (L > 26) for (let ti = 0; ti < 2; ti++) for (let j = 0; j < 8; j++) {
    const y = 3 + j * 4.9 + (vnoise(time * 3 + j, 5 + ti) - 0.5) * 5, reach = 3 + 13 * vnoise(time * 6 + j * 1.7, 11 + ti) - ti * 3, x0 = fx - 18, x1 = fx - 3 + reach, wd = 3.6 - ti;
    fillP(FLAME[ti][2 - ti], (k) => { k.moveTo(x0, y - wd); k.quadraticCurveTo(x0 + (x1 - x0) * 0.6, y - wd * 0.9, x1, y + (vnoise(time * 4, j) - 0.5) * 3); k.quadraticCurveTo(x0 + (x1 - x0) * 0.6, y + wd * 0.9, x0, y + wd); });
  }
  FLAME.forEach(([wk, c0, c1], ti) => {
    const len = L * (1 - ti * 0.07), n = 56, flow = time * (7 + ti * 2);
    const cy = (x) => mix(my, 20.5, smooth(0, 44, x)) + (vnoise(x * 0.06 - flow * 0.5, 30 + ti) - 0.5) * 3 * smooth(10, 60, x);
    const half = (x, sd) => Math.max(0.6, (2.4 + 25 * smooth(0, 50, x)) * wk * Math.pow(Math.max(0, 1 - Math.pow(x / len, 9)), 0.5) + (vnoise(x * 0.22 + ti * 5 - flow, sd) - 0.5) * 7 * wk * smooth(4, 30, x));
    fillP(lin(mx, 0, mx + len, 0, c0, c0, c1), (k) => { for (let i = 0; i <= n; i++) { const x = (len * i) / n; i ? k.lineTo(mx + x, cy(x) - half(x, 2)) : k.moveTo(mx, my - 1.5); } for (let i = n; i >= 0; i--) { const x = (len * i) / n; k.lineTo(mx + x, cy(x) + half(x, 9)); } });
  });
  for (let i = 0; i < 18; i++) { const ph = (time * (1.4 + hash(i, 70)) + hash(i, 71)) % 1; rc(fx - 6 + ph * 22, 3 + hash(i, 72) * 34 + Math.sin(ph * 6 + i) * 2, 1, 1, i % 2 ? '#fbe88a' : '#e0641e'); }
  g.restore();
}
const SMOKE = '126,132,160';
function wisp(x, y, rise, seed, a, time) { g.save(); g.filter = 'blur(1.4px)'; for (let i = 0; i < 8; i++) { const t = (i / 8 + time * 0.2) % 1; ell(x + (hash(i, seed) - 0.5) * (4 + t * 14) + t * 7, y - t * rise, 2 + t * 5, 1.6 + t * 4, `rgba(${SMOKE},${a * Math.sin(Math.PI * t)})`); } g.restore(); }
// One frame of the button, from the state. Returns where the front of the fire is.
function scene(s) {
  const time = s.time, inh = smooth(0, 0.14, s.h), open = smooth(0.13, 0.2, s.h), shut = s.done ? smooth(0.12, 0.6, s.ta) : 0;
  const fa = s.done ? 1 - smooth(0.08, 0.55, s.ta) : 1, p = clamp((s.h - 0.16) / 0.84, 0, 1), burning = p > 0 && fa > 0;
  const soot = s.done ? smooth(0.1, 0.7, s.ta) : 0, fl = 0.86 + 0.14 * vnoise(time * 9, 4);
  const o = {
    hb: [20 - 5 * inh * (1 - open) + 1.5 * open * (1 - shut), 24], ang: (-0.1 * inh - 0.06 * open) * (1 - shut) + (burning ? (vnoise(time * 26, 1) - 0.5) * 0.035 * fa : 0),
    jaw: (0.08 * inh + 0.36 * open) * (1 - shut), eye: s.eye * (1 - s.blink), lid: s.lid, glow: inh * (1 - shut), fire: burning,
  };
  const [mx, my] = headPt(o, 30, 8), fx = mx + (W + 14 - mx) * p;
  const S = { amb: 'rgb(74,80,130)', lights: [[W - 16, -14, 130, '140,176,255', 0.5]] };
  if (burning) S.lights.push([fx, 20, 46 + 60 * p, '255,160,70', fa * fl], [mx + 6, my, 50, '255,196,120', 0.9 * fa * fl]);
  if (o.glow > 0) S.lights.push([8, 32, 50, '255,150,56', o.glow * (0.9 + 0.1 * fl)]);
  if (soot > 0) S.lights.push([104, 42, 96, '255,110,40', 0.4 * soot * (1 - 0.7 * smooth(3, 10, s.ta)) * (0.8 + 0.2 * vnoise(time * 5, 8))]);
  g = sctx; g.setTransform(1, 0, 0, 1, 0, 0); g.clearRect(0, 0, W, H);
  const BG = lit(layer(() => { g.drawImage(CAVE, 0, 0); if (soot > 0) { g.globalAlpha = soot; g.fillStyle = lin(50, 0, W, 0, 'rgba(4,3,8,0)', 'rgba(4,3,8,.72)', 'rgba(4,3,8,.8)'); g.fillRect(50, 0, W - 50, H); } }), S);
  g.drawImage(BG, 0, 0);
  if (burning) stream(mx, my, fx, time, fa);
  const NP = path([[-14, 42], [-2, 40], [6, 27], o.hb], 18), nr = (t) => mix(10, 7.2, t);
  const HD = layer(() => { tube(NP, nr, lin(0, 12, 0, 40, '#4a9c84', SC, DK)); plates(NP, nr, (q) => poly(q, BELLY)); head(o); });
  lit(HD, S); rim(HD, -1.2, 1.2, W, -10, 190, '170,204,255', 0.9); rim(HD, 0, 1.1, 40, -20, 90, '130,160,240', 0.5);
  if (burning) rim(HD, -1, -1.3, mx + 20, my + 4, 60, '255,214,140', fa);
  g.drawImage(HD, 0, 0);
  const CN = lit(layer(() => g.drawImage(COINS, 0, 0)), S); g.drawImage(CN, 0, 0);
  release(BG, HD, CN);
  if (o.glow > 0) plates(NP, nr, (q) => poly(q, `rgba(255,${Math.round(150 + 80 * o.glow)},90,${o.glow})`));
  face(o);
  if (burning) { g.save(); g.globalCompositeOperation = 'lighter'; glow(fx - 10, 20, 50, '255,120,36', 0.3 * fa * fl); g.restore(); }
  const [nx, ny] = headPt(o, 51, -6);
  if (s.ring >= 0) {   // the one he blows when you let go
    const q = s.ring / 1.5, a = 0.85 * (1 - q) ** 1.5;
    g.save(); g.filter = 'blur(0.5px)'; strokeP(`rgba(190,204,236,${a})`, 1.8, (k) => k.ellipse(nx + 7 + q * 9, ny - 6 - q * 7, 3 + q * 2.4, 4.6 + q * 3, 0.25, 0, 7)); g.restore();
  }
  if (!s.done && s.h === 0 && s.eye < 0.05) {   // asleep: a breath out of the nostril every few seconds
    const ph = (time % 4.6) / 1.9;
    if (ph < 1) { g.save(); g.filter = 'blur(1.1px)'; ell(nx + 2 + ph * 6, ny - 1 - ph * 9, 1.6 + ph * 3, 1.3 + ph * 2.4, `rgba(${SMOKE},${0.4 * Math.sin(Math.PI * ph)})`); g.restore(); }
  }
  if (soot > 0) {   // what is left: embers that wink out, and smoke that thins
    const n = Math.round(mix(28, 8, smooth(3, 10, s.ta)));
    for (let i = 0; i < n; i++) { const tw = hash(i, (time * 5) | 0); if (tw < 0.4) continue; const up = (time * (0.04 + hash(i, 44) * 0.07) + hash(i, 45)) % 1; rc(64 + hash(i, 41) * 112, 35 - up * 27 * hash(i, 43), 1, 1, tw > 0.78 ? '#fbe88a' : '#f89a38'); }
    const a = 0.24 * soot * (1 - 0.8 * smooth(4, 11, s.ta)); wisp(96, 31, 26, 3, a, time); wisp(142, 33, 28, 9, a, time + 2.2);
  }
  return fx;
}

// ───────── the button: an ink capsule with stepped ends and a hard shadow, around the scene ─────────
const INK = '#26221c', CW = W + 4, CH = H + 4, SH = 4, cap = mk(CW, CH + SH), cctx = cap.getContext('2d');
const SPAN = [0, 2].map((inset) => Array.from({ length: CH }, (_, y) => { if (y < inset || y >= CH - inset) return null; const r = CH / 2, rr = r - inset, dy = y + 0.5 - r, dx = Math.sqrt(Math.max(0, rr * rr - dy * dy)), x0 = Math.round(r - dx); return [x0, Math.round(CW - r + dx) - x0]; }));
function capsule(down, col) {
  const oy = down ? SH : 0; cctx.clearRect(0, 0, CW, CH + SH); cctx.fillStyle = col;
  for (let y = 0; y < CH; y++) { const a = SPAN[0][y]; cctx.fillRect(a[0], y + oy, a[1], 1); if (!down) cctx.fillRect(a[0], y + SH, a[1], 1); }
  for (let y = 2; y < CH - 2; y++) { const a = SPAN[1][y]; if (a && a[1] > 0) cctx.drawImage(art, a[0] - 2, y - 2, a[1], 1, a[0], y + oy, a[1], 1); }
}

// ───────── the card: the page you are about to burn ─────────
// No noise and no soft edges: flat tones, a checker where two tones meet, stepped corners, a nicked edge.
const PCH = { base: '#ecdcb0', lite: '#f8eecb', shade: '#dfcc9c', dark: '#c9b281', line: '#4a3a22' };
function seal(cx, cy) {   // wax with two tails of ribbon and three claw marks pressed into it
  for (let i = 0; i < 11; i++) { const e = i > 8; rc(cx - 5 - (i > 5 ? 1 : 0), cy + 5 + i, e ? 1 : 4, 1, '#6a1626'); if (e) rc(cx - 2 - 1, cy + 5 + i, 1, 1, '#6a1626'); rc(cx + 1 + (i > 5 ? 1 : 0), cy + 5 + i, e ? 1 : 4, 1, '#8c2232'); if (e) rc(cx + 5, cy + 5 + i, 1, 1, '#8c2232'); }
  for (let dy = -9; dy <= 9; dy++) for (let dx = -9; dx <= 9; dx++) {
    const r = Math.hypot(dx, dy), R = 7.7 + 0.9 * Math.cos(Math.atan2(dy, dx) * 8); if (r > R) continue;
    rc(cx + dx, cy + dy, 1, 1, r > R - 1.3 ? '#6a1626' : r > 4.7 ? '#a02a3a' : r > 3.7 ? '#6a1626' : '#b83a4a');
  }
  for (const k of [-2, 0, 2]) for (let j = 0; j < 4; j++) rc(cx + k + 1 - ((j + 1) >> 1), cy - 2 + j, 1, 1, '#6a1626');
  rc(cx - 5, cy - 4, 1, 2, '#e07a84'); rc(cx - 4, cy - 5, 2, 1, '#e07a84');
}
function layoutCard(root, q, btn) {   // paint the parchment to the card's own size, and work out how the burn will spread from the button
  const A = (v) => Math.round(v / 1.5), w = A(root.offsetWidth), h = A(root.offsetHeight);
  const tear = Math.round(w * 0.43);
  const T = (x) => (hash((x / 9) | 0, 1) > 0.62 ? 1 : 0), Bm = (x) => (x >= tear && x < tear + 5 ? [1, 2, 3, 2, 1][x - tear] : hash((x / 8) | 0, 2) > 0.62 ? 1 : 0);
  const Lf = (y) => (hash((y / 7) | 0, 3) > 0.66 ? 1 : 0), Rt = (y) => (hash((y / 6) | 0, 4) > 0.66 ? 1 : 0), cor = (y) => [5, 3, 2, 1, 1][Math.min(y, h - 1 - y)] || 0;
  const inside = (x, y) => y >= 0 && y < h && x >= cor(y) + Lf(y) && x < w - cor(y) - Rt(y) && y >= T(x) && y < h - Bm(x);
  const near = (x, y, k) => !inside(x - k, y) || !inside(x + k, y) || !inside(x, y - k) || !inside(x, y + k);
  const c = mk(w, h + 6), prev = g, mask = new Uint8Array(w * (h + 6)), dn = new Float32Array(w * (h + 6));
  const bx = A(btn.offsetLeft + btn.offsetWidth / 2), by = A(btn.offsetTop + btn.offsetHeight / 2), R = Math.min(176, w * 0.5);
  const top = A(btn.offsetTop), under = A(q.offsetTop + q.offsetHeight) <= top;   // on a narrow card the button sits under the words, and the burn must not climb over them
  g = c.getContext('2d', { willReadFrequently: true });
  for (let y = 0; y < h + 6; y++) for (let x = 0; x < w; x++) {
    if (!inside(x, y)) { for (let k = 1; k <= 6; k++) if (inside(x, y - k)) { rc(x, y, 1, 1, INK); break; } continue; }
    if (near(x, y, 1)) { mask[y * w + x] = 1; rc(x, y, 1, 1, PCH.line); continue; }
    mask[y * w + x] = 2; dn[y * w + x] = Math.hypot(x - bx, (y - by) * 1.3) / (R * (0.66 + 0.6 * fbm(x * 0.05, y * 0.05 + 50))) + (under ? Math.max(0, top - 1 - y) * 0.075 : 0);
    const v = fbm(x * 0.016 + 11, y * 0.036 + 5), ck = (x + y) & 1;
    let t = v < 0.41 ? 'shade' : v < 0.45 ? (ck ? 'shade' : 'base') : v < 0.56 ? 'base' : v < 0.6 ? (ck ? 'lite' : 'base') : 'lite';
    if (!inside(x, y - 2) || !inside(x - 2, y)) t = 'lite';
    else if (!inside(x, y + 2) || !inside(x + 2, y)) t = 'dark';
    else { let d = 3; while (d < 9 && !near(x, y, d)) d++; if (d < 9 && (B4[(y & 3) * 4 + (x & 3)] + 0.5) / 16 < (1 - (d - 2) / 7) * 0.62) t = t === 'shade' ? 'dark' : 'shade'; }
    rc(x, y, 1, 1, PCH[t]);
  }
  for (const [fx, fy] of [[0.31, 0.72], [0.52, 0.2], [0.58, 0.8], [0.12, 0.86]]) { const x = Math.round(w * fx), y = Math.round(h * fy); rc(x, y, 2, 1, PCH.dark); rc(x + 1, y + 1, 1, 1, PCH.dark); }
  const qx = A(q.offsetLeft), qy = A(q.offsetTop), tx = qx + A(parseFloat(getComputedStyle(q).paddingLeft));
  seal(qx + 14, qy + 11);
  const base = g.getImageData(0, 0, w, h + 6); g = prev;
  return { c, w, h, mask, dn, tx, qy, base };
}
const CHAR = [u32('#14100e'), u32('#2a1a10'), u32('#4a4038')], HOT = [u32('#e0641e'), u32('#f89a38'), u32('#fbe88a')], COOL = [u32('#8c2412'), u32('#5a1410')], SINGE = [u32('#5e3b0f'), u32('#8a6230'), u32('#b89a64')];
function paintCard(card, s, title, sub) {
  const { c, w, h, mask, dn } = card, k = c.getContext('2d'), prev = g;
  k.putImageData(card.base, 0, 0); g = k; ptext(title, card.tx, card.qy + 4, INK, 1); ptext(sub, card.tx, card.qy + 17, '#7a6644'); g = prev;
  if (!s.done) return;
  // scorched outward from the button: char, a live edge that cools, then a singed band in a 4 x 4 pattern
  const grow = Math.max(0.02, 1 - (1 - clamp(s.ta / 1.2, 0, 1)) ** 3), cool = smooth(2.5, 9, s.ta), fb = (s.time * 7) | 0;
  const im = k.getImageData(0, 0, w, h), d32 = new Uint32Array(im.data.buffer);
  for (let y = 0, i = 0; y < h; y++) for (let x = 0; x < w; x++, i++) {
    if (mask[i] !== 2) continue; const d = dn[i] / grow; if (d >= 1) continue;
    if (d < 0.6) d32[i] = hash(x, y) > 0.95 ? CHAR[2] : d < 0.44 ? CHAR[0] : d < 0.5 ? CHAR[(x + y) & 1] : CHAR[1];
    else if (d < 0.66) { const q = hash(x + fb * 13, y - fb * 7); d32[i] = q < cool * 0.9 ? COOL[d < 0.63 ? 0 : 1] : d >= 0.63 ? COOL[0] : q > 0.92 ? HOT[2] : q > 0.5 ? HOT[0] : HOT[1]; }
    else { const t = (1 - d) / 0.34; if ((B4[(y & 3) * 4 + (x & 3)] + 0.5) / 16 < t * 1.15) d32[i] = SINGE[t > 0.66 ? 0 : t > 0.33 ? 1 : 2]; }
  }
  k.putImageData(im, 0, 0);
}

// ───────── the element ─────────
const SHEET = `
:host{display:inline-block;position:relative;vertical-align:middle;font:15px/1.45 -apple-system,"Helvetica Neue","Segoe UI",sans-serif}
:host([heading]){display:block}
canvas{display:block;position:absolute;left:0;top:0;image-rendering:pixelated;pointer-events:none}
.card{position:relative;display:flex;align-items:center;gap:12px}
:host([heading]) .card{padding:16px 18px;margin-bottom:9px}
:host(:not([heading])) .q,:host(:not([heading])) .skin{display:none}
:host(:not([heading])) button{margin-bottom:6px}
.card.narrow{flex-wrap:wrap;justify-content:flex-end}.card.narrow .q{flex-basis:100%}
.q{flex:1;min-width:0;padding-left:46px}.q b{display:block;font-size:16px}.q span{font-size:13px}
.q,button{color:transparent;user-select:none;-webkit-user-select:none}
button{position:relative;flex:none;width:294px;height:66px;margin:0;padding:0;border:0;background:none;font:inherit;cursor:pointer;outline:none;touch-action:none;-webkit-touch-callout:none;-webkit-tap-highlight-color:transparent}
button:disabled{cursor:default}`;
// every button on the page is painted from one loop, with the same scratch canvases
const LIVE = new Set(); let ticking = false, last = 0, baked = false;
// A first frame can be stamped before wake() ran, so the step is kept from going negative: time must not run backwards.
function loop(now) { if (!LIVE.size || HoardButton.paused) { ticking = false; return; } const dt = Math.max(0, Math.min(0.05, (now - last) / 1000)); last = now; for (const el of LIVE) el.advance(dt); requestAnimationFrame(loop); }
function wake() { if (!ticking && LIVE.size && !HoardButton.paused) { ticking = true; last = performance.now(); requestAnimationFrame(loop); } }
class HoardButton extends HTMLElement {
  static get observedAttributes() { return ['label', 'done-label', 'heading', 'warning', 'done-heading', 'done-warning']; }
  constructor() {
    super();
    // The words stay in the page for layout and for screen readers. Everything you see is drawn in art pixels.
    const root = this.attachShadow({ mode: 'open', delegatesFocus: true });
    root.innerHTML = `<style>${SHEET}</style><div class="card"><canvas class="skin" aria-hidden="true"></canvas><div class="q" aria-live="polite"><b></b><span></span></div><button type="button"><canvas aria-hidden="true"></canvas><span></span></button></div>`;
    const $ = (q) => root.querySelector(q);
    this._card = $('.card'); this._skin = $('.skin'); this._q = $('.q'); this._t = $('.q b'); this._w = $('.q span'); this._btn = $('button'); this._face = $('button canvas'); this._l = $('button span');
    this._face.width = CW * 3; this._face.height = (CH + SH) * 3; this._face.style.width = CW * 1.5 + 'px'; this._face.style.height = (CH + SH) * 1.5 + 'px';
    this._s = { time: 0, h: 0, eye: 0, lid: 0, blink: 0, nextBlink: 3, ring: -1, sulk: 0, done: false, ta: 0, said: false };
    this.input = { hover: false, down: false, focus: false };   // what the pointer and keys are doing; a script can set these too
    this._wasDown = false; this._dirty = true; this._frame = 0; this._paper = null;
    const b = this._btn, inp = this.input;
    b.addEventListener('pointerenter', () => { inp.hover = true; });
    b.addEventListener('pointerleave', () => { inp.hover = false; });
    b.addEventListener('pointerdown', (e) => { if (e.button !== 0 || this._s.done) return; inp.down = true; b.setPointerCapture(e.pointerId); });
    for (const ev of ['pointerup', 'pointercancel', 'lostpointercapture']) b.addEventListener(ev, () => { inp.down = false; });
    b.addEventListener('keydown', (e) => { if ((e.key === ' ' || e.key === 'Enter') && !this._s.done) { e.preventDefault(); if (!e.repeat) inp.down = true; } });
    b.addEventListener('keyup', (e) => { if (e.key === ' ' || e.key === 'Enter') inp.down = false; });
    b.addEventListener('focus', () => { inp.focus = b.matches(':focus-visible'); });
    b.addEventListener('blur', () => { inp.focus = false; inp.down = false; });
    b.addEventListener('contextmenu', (e) => e.preventDefault());
    this._ro = new ResizeObserver(() => this._fit(false));
  }
  connectedCallback() { if (!baked) { bake(); baked = true; } this._words(); this._ro.observe(this); LIVE.add(this); this._fit(true); this._render(); wake(); }
  disconnectedCallback() { LIVE.delete(this); this._ro.disconnect(); }
  attributeChangedCallback() { if (this.isConnected) { this._words(); this._fit(true); } }
  _words() {   // what it says now, from the attributes
    const d = this._s.said, a = (n, v) => this.getAttribute(n) ?? v;
    this._t.textContent = d ? a('done-heading', 'Deleted') : a('heading', ''); this._w.textContent = d ? a('done-warning', '') : a('warning', '');
    this._l.textContent = d ? a('done-label', 'Deleted') : a('label', 'Hold to delete'); this._btn.disabled = d; this._dirty = true;
  }
  _fit(force) {   // paint the parchment to the card's own size, whenever that changes
    if (!this.hasAttribute('heading')) { this._paper = null; return; }
    this._card.classList.toggle('narrow', this.offsetWidth < 490);
    const w = Math.round(this._card.offsetWidth / 1.5), h = Math.round(this._card.offsetHeight / 1.5); if (w < 40 || h < 20 || (!force && this._paper && w === this._paper.w && h === this._paper.h)) return;
    const p = (this._paper = layoutCard(this._card, this._q, this._btn)), k = this._skin;
    k.width = p.w * 3; k.height = (p.h + 6) * 3; k.style.width = p.w * 1.5 + 'px'; k.style.height = (p.h + 6) * 1.5 + 'px'; this._dirty = true;
  }
  reset() { Object.assign(this._s, { h: 0, ring: -1, sulk: 0, done: false, ta: 0, said: false }); this._words(); }   // put it back
  get held() { return this._s.h; }          // 0 to 1, how far through the hold
  get deleted() { return this._s.done; }    // true once it has fired
  advance(dt) {
    const s = this._s, inp = this.input;
    s.time += dt;
    if (!s.done) {
      if (inp.down) s.h = Math.min(1, s.h + dt / (parseFloat(this.getAttribute('hold')) || HOLD));
      else {
        if (this._wasDown && s.h > 0.05) { s.ring = 0; s.sulk = 2.4; }   // let go early: one smoke ring, and he keeps an eye on you for a while
        s.h = Math.max(0, s.h - dt / 0.4);
      }
      if (s.h >= 1) { s.done = true; s.ta = 0; this.dispatchEvent(new CustomEvent('hoard:delete', { bubbles: true, composed: true })); }
    } else s.ta += dt;
    this._wasDown = inp.down;
    if (s.ring >= 0) { s.ring += dt; if (s.ring > 1.5) s.ring = -1; }
    s.sulk = Math.max(0, s.sulk - dt);
    const busy = inp.down || s.h > 0, awake = s.done ? s.ta < 1.6 : inp.hover || inp.focus || busy || s.sulk > 0;
    s.eye += clamp((awake ? 1 : 0) - s.eye, -dt / 0.2, dt / 0.09);
    s.lid += clamp((s.done ? 0.5 : busy ? 0.4 : s.sulk > 0 ? 0.55 : 0) - s.lid, -dt / 0.25, dt / 0.15);
    s.nextBlink -= dt; if (s.nextBlink < 0) s.nextBlink = 2.6 + hash(this._frame, 9) * 3;
    s.blink = !busy && s.nextBlink < 0.13 ? 1 : 0;
    if (s.done && !s.said && s.ta > 0.45) { s.said = true; this._words(); }   // the words change once, and the page says so
    this._render();
  }
  _render() {
    const s = this._s, inp = this.input, frame = ++this._frame;
    const fx = scene(s); crush();
    // the label, in the art: pale on the cave, ink where the fire has been
    const label = this._l.textContent, lx = 82 + Math.round((W - 92 - ptextW(label, 1)) / 2), firing = s.h > 0.16 && !(s.done && s.ta > 0.3), split = firing ? Math.round(fx - 7) : 0;
    g = actx;
    if (s.said) ptext(label, lx, 17, '#8088a4', 1);
    else { g.save(); g.beginPath(); g.rect(split, 0, W, H); g.clip(); ptext(label, lx + 1, 18, '#090b15', 1); g.restore(); ptext2(label, lx, 17, split, INK, '#e4ecf6', W, H); }
    g = sctx;
    capsule((inp.down && !s.done) || s.said, s.said ? '#6a5642' : inp.focus && !inp.hover && !s.done ? '#f0ca4a' : INK);
    const v = this._face.getContext('2d'); v.imageSmoothingEnabled = false; v.clearRect(0, 0, this._face.width, this._face.height); v.drawImage(cap, 0, 0, this._face.width, this._face.height);
    // the card only needs repainting when its words change or while it is burning and cooling
    const p = this._paper;
    if (p && (this._dirty || (s.done && s.ta < 10 && (s.ta < 1.4 || frame % 5 === 0)))) {
      this._dirty = false; paintCard(p, s, this._t.textContent, this._w.textContent);
      const k = this._skin.getContext('2d'); k.imageSmoothingEnabled = false; k.clearRect(0, 0, this._skin.width, this._skin.height); k.drawImage(p.c, 0, 0, this._skin.width, this._skin.height);
    }
    const jolt = s.done && s.ta < 0.16 && !matchMedia('(prefers-reduced-motion: reduce)').matches;
    this._card.style.transform = jolt ? `translate(${frame % 2 ? 1.5 : -1.5}px, 3px)` : '';
  }
}
HoardButton.paused = false;   // set true to stop the clock and step it yourself with el.advance(seconds)
customElements.define('hoard-button', HoardButton);
})();
