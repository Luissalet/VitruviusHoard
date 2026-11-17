// Sage: thinking states for an agent.
// A status chip with a wizard at his desk in it. Whatever the agent is doing, he is doing:
// stroking his beard, scrying, reading, stirring, writing, holding out a quill for you to sign, nodding off over the finished job, or sitting in the soot.
// Everything is painted in code at 200 x 44, lit by whatever is giving light in that state, and crushed to a fixed palette every frame.
//
// One file, no dependencies. Load it with a script tag and put <sage-status state="thinking"></sage-status> where the status goes.
// el.set(state, label, detail) changes it. States: thinking, searching, reading, running, writing, waiting, done, failed.
(() => {
'use strict';
function mulberry(seed) { let a = seed >>> 0; return () => { a = (a + 0x6D2B79F5) >>> 0; let t = a; t = Math.imul(t ^ (t >>> 15), t | 1); t ^= t + Math.imul(t ^ (t >>> 7), t | 61); return ((t ^ (t >>> 14)) >>> 0) / 4294967296; }; }
function hash(x, y) { let h = (x * 374761393 + y * 668265263) | 0; h = (h ^ (h >>> 13)) * 1274126177 | 0; return ((h ^ (h >>> 16)) >>> 0) / 4294967296; }
function vnoise(x, y) { const xi = Math.floor(x), yi = Math.floor(y), fx = x - xi, fy = y - yi, sx = fx * fx * (3 - 2 * fx), sy = fy * fy * (3 - 2 * fy), l = (a, b, t) => a + (b - a) * t; return l(l(hash(xi, yi), hash(xi + 1, yi), sx), l(hash(xi, yi + 1), hash(xi + 1, yi + 1), sx), sy); }
const fbm = (x, y) => 0.55 * vnoise(x, y) + 0.3 * vnoise(x * 2.1, y * 2.1 + 7) + 0.15 * vnoise(x * 4.3, y * 4.3 + 19);
const clamp = (v, a, b) => (v < a ? a : v > b ? b : v), mix = (a, b, t) => a + (b - a) * t, smooth = (a, b, v) => { const t = clamp((v - a) / (b - a), 0, 1); return t * t * (3 - 2 * t); };

const W = 200, H = 44, DESK = 37;   // the chip's scene in art pixels, and the top of the desk
const PAL = [
  '#04050a', '#090b15', '#101322', '#181c32',
  '#1a2444', '#243560', '#32497c', '#46639a', '#6584b8', '#8eaad2', '#bccbe6', '#e4ecf6',
  '#221d38', '#332a52', '#473a6c', '#62528a', '#8474b4',
  '#0b2024', '#113236', '#194848', '#24645c', '#348270', '#4fa488', '#7cc8a4', '#b4e8c4',
  '#1c6c7c', '#3cb4c8', '#7ce0e0', '#c8f8f4',
  '#2c4226', '#4c6a34', '#4ca838', '#8ce04a', '#d0f48c',
  '#24160c', '#3e260e', '#5e3b0f', '#855714', '#ae7a1c', '#d4a02c', '#f0ca4a', '#fbe88a', '#fffbd4',
  '#4a1010', '#7c1e12', '#b03a16', '#e0641e', '#f89a38',
  '#3c3430', '#6a5c50', '#9c8a70', '#cdb992', '#eedfb8',
  '#8a5c44', '#c08a68', '#f0c49c',
  '#2c2e3e', '#474a5e', '#6c7088', '#9a9eb4',
  '#6a1626', '#a02a3a', '#c84a56',
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
function limb(ax, ay, ra, bx, by, rb, col) {   // a tapered capsule: thick at one joint, thinner at the next
  const a = Math.atan2(by - ay, bx - ax), nx = -Math.sin(a), ny = Math.cos(a), q = Math.PI / 2;
  fillP(col, (k) => { k.moveTo(ax + nx * ra, ay + ny * ra); k.lineTo(bx + nx * rb, by + ny * rb); k.arc(bx, by, rb, a + q, a - q, true); k.lineTo(ax - nx * ra, ay - ny * ra); k.arc(ax, ay, ra, a - q, a + q, true); });
}
const R = Math.round;

// ───────── light ─────────
// Every layer is multiplied by the same map: a cold ambient plus whatever is giving light in this state.
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
Object.assign(FONT, { ':': '. . # . # . .'.split(' '), '/': '..# ..# .#. .#. .#. #.. #..'.split(' '), '_': '.... .... .... .... .... .... ####'.split(' '), ',': '.. .. .. .. .. .# #.'.split(' '), '%': '#..# ...# ..#. ..#. .#.. #... #..#'.split(' ') });

// ───────── crush: every pixel to the nearest palette colour, with a 4 x 4 ordered dither ─────────
const B4 = [0, 8, 2, 10, 12, 4, 14, 6, 3, 11, 1, 9, 15, 7, 13, 5], SPREAD = 9;
const RGB = PAL.map((h) => [parseInt(h.slice(1, 3), 16), parseInt(h.slice(3, 5), 16), parseInt(h.slice(5, 7), 16)]);
const u32 = (h) => (255 << 24) | (parseInt(h.slice(5, 7), 16) << 16) | (parseInt(h.slice(3, 5), 16) << 8) | parseInt(h.slice(1, 3), 16);
const PAL32 = new Uint32Array(PAL.map(u32)), LUT = new Uint8Array(32768);
for (let r = 0; r < 32; r++) for (let gg = 0; gg < 32; gg++) for (let b = 0; b < 32; b++) {
  let best = 0, bd = 1e9; const Rr = r * 8 + 4, G = gg * 8 + 4, Bv = b * 8 + 4;
  for (let q = 0; q < RGB.length; q++) { const c = RGB[q], e = 2 * (Rr - c[0]) ** 2 + 4 * (G - c[1]) ** 2 + 3 * (Bv - c[2]) ** 2; if (e < bd) { bd = e; best = q; } }
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

// ───────── the study: a stone wall, a long desk, a candle ─────────
let ROOM, DESKL;
function bake() {
  ROOM = mk(W, H); DESKL = mk(W, H);
  const prev = g; g = ROOM.getContext('2d');
  g.fillStyle = lin(0, 0, 0, H, '#74729a', '#6a6890', '#55537a'); g.fillRect(0, 0, W, H);
  for (let y = 0; y < H; y += 2) for (let x = 0; x < W; x += 2) { const v = (fbm(x * 0.03 + 3, y * 0.07) - 0.5) * 0.5 + (fbm(x * 0.13 + 40, y * 0.2) - 0.5) * 0.3; rc(x, y, 2, 2, v > 0 ? `rgba(196,196,236,${v * 0.5})` : `rgba(10,8,24,${-v * 0.9})`); }
  for (let y = 5, j = 0; y < DESK; y += 9, j++) { rc(0, y, W, 1, 'rgba(12,10,26,.34)'); rc(0, y + 1, W, 1, 'rgba(200,200,240,.1)'); for (let x = (j & 1) * 11 + 6; x < W; x += 22) rc(x, y - 8, 1, 8, 'rgba(12,10,26,.26)'); }
  g = DESKL.getContext('2d');
  g.fillStyle = lin(0, DESK, 0, H, '#b07c40', '#7a4c22', '#5a3414'); g.fillRect(0, DESK, W, H - DESK);
  rc(0, DESK, W, 1, '#d8a860'); rc(0, DESK + 2, W, 1, 'rgba(40,20,6,.55)');
  for (let x = 13; x < W; x += 31) rc(x, DESK + 3, 1, H - DESK - 3, 'rgba(40,20,6,.4)');
  // the candle, in a brass dish, on the far side of whatever he is working at
  rc(69, DESK - 1, 9, 2, '#c8962a'); rc(70, DESK - 2, 7, 1, '#f0ca4a'); rc(72, DESK - 9, 4, 8, '#f2ead0'); rc(75, DESK - 9, 1, 8, '#cdb992'); rc(72, DESK - 6, 1, 3, '#fffbd4'); rc(73.5, DESK - 11, 1, 2, '#24160c');
  g = prev;
}

// ───────── the wizard: side on, facing his work. Bent hat, big nose, a beard down to the desk ─────────
const ROBE = '#4058ae', ROBE_D = '#22306c', ROBE_L = '#6480d2', HAT = '#3a52a2', HAT_D = '#202e68', GOLD = '#d4a02c';
const BEARD = '#e8ecf4', BEARD_D = '#a4acc4', SKIN = '#ecbe98', SKIN_D = '#b98466', SOOT = '#2a2a34', ASH = '#55555f';
const NECK = [24, 24], SHO = [21, 27.5];
// where a point on his head ends up once the head has moved and tipped
const hp = (p, x, y) => { const a = p.tilt || 0, c = Math.cos(a), s = Math.sin(a), dx = x - NECK[0], dy = y - NECK[1]; return [NECK[0] + R(p.head[0]) + dx * c - dy * s, NECK[1] + R(p.head[1]) + dx * s + dy * c]; };
function hat(p) {
  g.save(); g.translate(28, 12); g.rotate(p.hat || 0); g.translate(-28, -12);
  fillP(p.soot ? '#1e2850' : lin(14, 0, 38, 0, HAT_D, HAT, '#5670c6'), (k) => { k.moveTo(20.6, 11.8); k.quadraticCurveTo(20.8, 5.4, 17.2, 3.8); k.lineTo(11.2, 6.2); k.quadraticCurveTo(17.4, 0, 26, 1.2); k.quadraticCurveTo(33.6, 3.4, 37, 11.4); k.closePath(); });
  strokeP('rgba(8,12,40,.55)', 0.9, (k) => { k.moveTo(20.8, 6.4); k.quadraticCurveTo(23, 4.2, 27, 4.6); });
  if (!p.soot) { rc(29, 6, 1, 1, '#fbe88a'); rc(32, 8, 1, 1, '#fbe88a'); rc(25, 8, 1, 1, '#f0ca4a'); }
  strokeP(p.soot ? '#5e3b0f' : GOLD, 1.5, (k) => { k.moveTo(21, 10.6); k.quadraticCurveTo(29, 8.9, 36.6, 10.3); });
  fillP(p.soot ? '#182044' : lin(17, 0, 42, 0, HAT_D, HAT_D, HAT), (k) => { k.moveTo(16.6, 12.2); k.quadraticCurveTo(29, 9.8, 41.8, 11.4); k.quadraticCurveTo(42.8, 12.8, 40.8, 13.6); k.quadraticCurveTo(29, 12.6, 18, 14.6); k.quadraticCurveTo(15.6, 13.8, 16.6, 12.2); });
  g.restore();
}
function head(p) {
  const so = p.soot;
  g.save(); g.translate(NECK[0] + R(p.head[0]), NECK[1] + R(p.head[1])); g.rotate(p.tilt || 0); g.translate(-NECK[0], -NECK[1]);
  fillP(so ? '#44444e' : BEARD_D, (k) => { k.moveTo(21.4, 12.6); k.quadraticCurveTo(16.4, 17, 17.2, 25.4); k.lineTo(22.4, 26.4); k.quadraticCurveTo(21.6, 19, 24, 14); k.closePath(); });   // hair down the back of his neck
  ell(28.6, 17, 5, 5.6, so ? SOOT : lin(24, 0, 34, 0, SKIN_D, SKIN, SKIN));
  fillP(so ? '#34343e' : SKIN, (k) => { k.moveTo(32.6, 14.6); k.quadraticCurveTo(37.8, 16.4, 38.2, 18.8); k.quadraticCurveTo(36, 20.2, 33, 19.6); k.closePath(); });   // the nose
  if (!so) { rc(35.6, 19, 2, 0.8, SKIN_D); rc(31, 18.4, 2, 1.4, '#e0a488'); }
  fillP(so ? lin(0, 18, 0, 38, ASH, '#33333c') : lin(25, 0, 38, 0, BEARD_D, BEARD, '#ffffff'), (k) => { k.moveTo(24.4, 17.4); k.lineTo(32.6, 20.2); k.quadraticCurveTo(36.8, 21, 37.4, 24.6); k.quadraticCurveTo(38, 30, 34.6, 34.6); k.quadraticCurveTo(33.2, 37, 31.4, 38.6); k.quadraticCurveTo(28.2, 35, 26.2, 30); k.quadraticCurveTo(23.8, 24, 24.4, 17.4); });
  strokeP(so ? 'rgba(10,10,14,.5)' : 'rgba(96,106,140,.55)', 0.8, (k) => { k.moveTo(28.6, 22.6); k.quadraticCurveTo(29.6, 29, 31.2, 35.4); k.moveTo(32.8, 23.6); k.quadraticCurveTo(34.6, 28, 33.6, 33); k.moveTo(26.2, 21); k.quadraticCurveTo(26.4, 26, 28, 31); });
  fillP(so ? ASH : '#ffffff', (k) => { k.moveTo(32.4, 19.6); k.quadraticCurveTo(36.6, 19.4, 38, 23.8); k.quadraticCurveTo(34.8, 23, 31.8, 21.8); k.closePath(); });   // moustache
  fillP(so ? '#6a6a76' : '#ffffff', (k) => { k.moveTo(30.2, 13.2); k.lineTo(35.6, 13.9); k.lineTo(35, 15.4); k.lineTo(30.2, 14.9); });   // one large eyebrow
  hat(p);
  g.restore();
}
function headFront(p) {   // the same head, turned to face you
  g.save(); g.translate(R(p.head[0]), R(p.head[1]));
  fillP(BEARD_D, (k) => { k.moveTo(20, 12.6); k.quadraticCurveTo(17.4, 18, 18.6, 26); k.lineTo(33.4, 26); k.quadraticCurveTo(34.6, 18, 32, 12.6); k.closePath(); });   // hair either side
  ell(26, 17, 5.2, 5.4, lin(20, 0, 32, 0, SKIN_D, SKIN, SKIN));
  fillP(lin(19, 0, 33, 0, BEARD_D, BEARD, '#ffffff'), (k) => { k.moveTo(20.4, 18); k.lineTo(31.6, 18); k.quadraticCurveTo(33.4, 26, 29.4, 33.6); k.quadraticCurveTo(27.6, 37, 26, 38.6); k.quadraticCurveTo(24.4, 37, 22.6, 33.6); k.quadraticCurveTo(18.6, 26, 20.4, 18); });
  strokeP('rgba(96,106,140,.55)', 0.8, (k) => { k.moveTo(24, 24); k.quadraticCurveTo(24.4, 30, 25.6, 35.6); k.moveTo(28.4, 24); k.quadraticCurveTo(28, 30, 26.8, 34); });
  fillP('#ffffff', (k) => { k.moveTo(26, 19.6); k.quadraticCurveTo(22.6, 19.6, 20.6, 23.4); k.quadraticCurveTo(24, 23, 26, 21.4); k.quadraticCurveTo(28, 23, 31.4, 23.4); k.quadraticCurveTo(29.4, 19.6, 26, 19.6); });   // moustache
  ell(26, 18.6, 1.7, 2.1, SKIN); rc(25, 20, 2.4, 0.8, SKIN_D);   // the nose, head on
  poly([[21.6, 13.4], [25, 14.2], [25, 15.4], [21.6, 14.8]], '#ffffff'); poly([[30.4, 13.4], [27, 14.2], [27, 15.4], [30.4, 14.8]], '#ffffff');
  fillP(lin(14, 0, 34, 0, HAT_D, HAT, '#5670c6'), (k) => { k.moveTo(19.2, 11.8); k.quadraticCurveTo(20.6, 4.6, 17.4, 3.2); k.lineTo(11.8, 5.6); k.quadraticCurveTo(18.4, -0.4, 26, 1.4); k.quadraticCurveTo(31.6, 4.6, 32.8, 11.6); k.closePath(); });
  strokeP('rgba(8,12,40,.55)', 0.9, (k) => { k.moveTo(20.6, 5.8); k.quadraticCurveTo(23, 4, 26.6, 4.4); });
  rc(27, 6, 1, 1, '#fbe88a'); rc(30, 8, 1, 1, '#fbe88a'); rc(23, 8, 1, 1, '#f0ca4a');
  strokeP(GOLD, 1.5, (k) => { k.moveTo(19.4, 10.6); k.quadraticCurveTo(26, 9.2, 32.6, 10.6); });
  ell(26, 12.4, 12.4, 2.3, lin(14, 0, 38, 0, HAT_D, HAT, HAT_D));
  g.restore();
}
function body(p) {
  strokeP('#6a4a26', 1.7, (k) => { k.moveTo(6.6, DESK + 2); k.lineTo(9.8, 7); }); poly([[10, 1.4], [12.8, 4.6], [10.4, 8], [7.8, 4.8]], '#3cb4c8'); rc(8, 7.4, 4, 1.4, '#ae7a1c');   // the staff, propped against the wall
  if (p.far) { const [fe, fh] = reach([27, 27.5], p.far, 11, 15); limb(27, 27.5, 3.4, fe[0], fe[1], 3, ROBE_D); limb(fe[0], fe[1], 3, fh[0], fh[1], 2.6, ROBE_D); ell(R(fh[0]) + 1.6, R(fh[1]), 2.2, 1.9, p.soot ? '#3a3a44' : SKIN_D); }
  fillP(lin(11, 0, 35, 0, ROBE_D, ROBE, ROBE_L), (k) => { k.moveTo(10.6, DESK + 2); k.quadraticCurveTo(10.4, 28, 16.6, 25); k.quadraticCurveTo(22, 22.6, 28.4, 24.6); k.quadraticCurveTo(33.6, 30, 34.6, DESK + 2); k.closePath(); });
  if (p.front) headFront(p); else head(p);
}
// The arm has two bones of fixed length, so however far he reaches it stays an arm. The elbow hangs below the line from shoulder to hand.
function reach(S, T, U = 11, F = 14) {
  let dx = T[0] - S[0], dy = T[1] - S[1], d = Math.hypot(dx, dy) || 1; const m = U + F - 0.4, lo = Math.abs(U - F) + 0.4, k = d > m ? m / d : d < lo ? lo / d : 1; dx *= k; dy *= k; d *= k;
  const e = Math.atan2(dy, dx) + Math.acos(clamp((U * U + d * d - F * F) / (2 * U * d), -1, 1));
  return [[S[0] + U * Math.cos(e), Math.min(DESK + 1, S[1] + U * Math.sin(e))], [S[0] + dx, S[1] + dy]];
}
function nearArm(p) {
  const S = [SHO[0] + R(p.head[0] * 0.6), SHO[1]], [E, H0] = reach(S, p.hand), hd = H0.map(R), a = Math.atan2(hd[1] - E[1], hd[0] - E[0]), nx = -Math.sin(a), ny = Math.cos(a), wx = hd[0] - Math.cos(a) * 2.4, wy = hd[1] - Math.sin(a) * 2.4;
  if (p.held) p.held(hd);
  if (p.book) p.book();
  limb(S[0], S[1], 4.2, E[0], E[1], 3.8, ROBE);
  // the forearm, in a sleeve that hangs open at the wrist
  fillP(lin(E[0], E[1] - 4, E[0], E[1] + 6, ROBE_L, ROBE, ROBE_D), (k) => { k.moveTo(E[0] - nx * 3.8, E[1] - ny * 3.8); k.lineTo(wx - nx * 3, wy - ny * 3); k.lineTo(wx + nx * 3, wy + ny * 3); k.lineTo(wx - 2.4 + nx * 2, Math.min(DESK + 1, wy + 7)); k.lineTo(E[0] + nx * 3.8, E[1] + ny * 3.8); k.closePath(); });
  ell(E[0], E[1], 3.8, 3.8, ROBE); strokeP(GOLD, 1.1, (k) => { k.moveTo(wx - nx * 3, wy - ny * 3); k.lineTo(wx + nx * 3, wy + ny * 3); });
  ell(hd[0], hd[1], 2.4, 2, p.soot ? '#4a4038' : SKIN); rc(hd[0] + Math.cos(a) * 1.6 - 0.5, hd[1] + Math.sin(a) * 1.6 - 1.4, 1.6, 1.2, p.soot ? '#4a4038' : SKIN);
}
// what is drawn after the light, so it stays readable: the eye
function features(p, blink) {
  if (p.front) { const dx = R(p.head[0]), dy = R(p.head[1]); for (const x of [23, 28]) { if (blink) rc(x + dx, 16 + dy, 2, 1, '#8a5c44'); else { rc(x + dx, 15 + dy, 2, 2, '#ffffff'); rc(x + dx + (x < 26 ? 1 : 0), 15 + dy, 1, 2, '#090b15'); } } return; }
  const [x, y] = hp(p, 32.2, 16.2).map(R), e = blink ? 'shut' : p.eyes;
  if (e === 'wide') { rc(x - 1, y - 1, 3, 2, '#ffffff'); rc(x + 1, y - 1, 1, 2, '#090b15'); }
  else if (e === 'shut') rc(x - 1, y, 3, 1, p.soot ? '#9a9eb4' : '#8a5c44');
  else rc(x, y - 1, 1, 2, '#24160c');
}
const REST = { head: [0, 0], tilt: 0, eyes: 'dot', hand: [37, DESK - 2] };

// ───────── small things that give light ─────────
const SMOKE = '126,132,160';
function flame(x, y, t, s = 1) { const f = vnoise(t * 9, 3), h = (5 + f * 2) * s, sw = (vnoise(t * 5, 7) - 0.5) * 2 * s; g.save(); g.globalCompositeOperation = 'lighter'; glow(x, y - 2, 9 * s, '255,170,70', 0.5); g.restore(); fillP('#f89a38', (k) => { k.moveTo(x - 1.6 * s, y); k.quadraticCurveTo(x - 2 * s, y - h * 0.5, x + sw, y - h); k.quadraticCurveTo(x + 2 * s, y - h * 0.5, x + 1.6 * s, y); }); ell(x, y - 1.4 * s, 0.9 * s, 1.6 * s, '#fffbd4'); }
function wisp(x, y, rise, seed, a, t, rgb = SMOKE) { g.save(); g.filter = 'blur(1.2px)'; for (let i = 0; i < 7; i++) { const q = (i / 7 + t * 0.22) % 1; ell(x + (hash(i, seed) - 0.5) * (3 + q * 10) + q * 4, y - q * rise, 1.6 + q * 4, 1.4 + q * 3.2, `rgba(${rgb},${a * Math.sin(Math.PI * q)})`); } g.restore(); }
const CANDLE = [73.5, DESK - 12], PX = 50;   // the flame, and the middle of the stretch of desk he works at
const BOOK = 55;
// where he is on the page: which of eight lines, how far along it, and how far through turning the page
const READ = (t) => { const c = t % 3.2, n = c / 0.31; return c < 2.48 ? { ln: Math.floor(n), w: n % 1, q: 0 } : { ln: 8, w: 0, q: (c - 2.48) / 0.72 }; };
function quill(x, y, a) { g.save(); g.translate(x, y); g.rotate(a); strokeP('#e4ecf6', 1.2, (k) => { k.moveTo(-3, 0); k.lineTo(11, 0); }); poly([[3, 0], [12, -3], [11, 0.8]], '#bccbe6'); poly([[4, 0], [11, 2.4], [11, 0]], '#8eaad2'); g.restore(); }
function cauldron(tipped) { g.save(); g.translate(PX + 2, DESK - 5); if (tipped) g.rotate(0.5); if (!tipped) { rc(-8, 4, 2, 2, '#2c2e3e'); rc(6, 4, 2, 2, '#2c2e3e'); } ell(0, 0, 10, 6, lin(-10, 0, 10, 0, '#181c32', '#2c2e3e', '#474a5e')); if (tipped) { ell(9, -1, 2.4, 5.6, '#101322'); strokeP('#090b15', 1, (k) => { k.moveTo(-6, -4); k.lineTo(-3, 0); k.lineTo(-5, 3); }); } else { ell(0, -5, 9.2, 2.6, '#6c7088'); ell(0, -5, 7.8, 1.8, '#4ca838'); } g.restore(); }

// ───────── the states ─────────
// Each one says what he is doing with his head and his hands, what is on the desk, what glows, and what light that throws.
const STATES = {
  thinking: {
    label: 'Thinking', busy: true,
    pose: (t) => { const ph = (t % 2.4) / 2.4, d = ph < 0.6 ? ph / 0.6 : 1 - smooth(0.6, 1, ph); return { ...REST, head: [0, -1], tilt: -0.07, eyes: ph < 0.6 ? 'shut' : 'dot', hand: [35.5 - d * 1.5, 25 + d * 7] }; },   // stroking his beard
    fx: (t) => {   // three motes going round until they meet, which is the idea
      const c = (t % 3.8) / 3.8, rr = c > 0.82 ? 1 - smooth(0.82, 0.92, c) : smooth(0, 0.12, c), cx = PX + 6, cy = 15;
      for (let i = 0; i < 3; i++) for (let k = 5; k >= 0; k--) { const a = t * 3.4 + i * 2.094 - k * 0.2, x = R(cx + Math.cos(a) * 11 * rr), y = R(cy + Math.sin(a) * 5.5 * rr); if (k) rc(x, y, 1, 1, k === 1 ? '#fbe88a' : k < 4 ? '#d4a02c' : '#855714'); else { rc(x - 1, y, 3, 1, '#fffbd4'); rc(x, y - 1, 1, 3, '#fffbd4'); } }
      if (c > 0.9) { const s = c < 0.95 ? 1 : 2; rc(cx - s - 1, cy, s * 2 + 3, 1, '#fffbd4'); rc(cx, cy - s - 1, 1, s * 2 + 3, '#fffbd4'); g.save(); g.globalCompositeOperation = 'lighter'; glow(cx, cy, 12, '255,220,120', 0.5); g.restore(); }
    },
    lights: (t) => [[PX + 6, 15, 40, '255,210,120', (t % 3.8) / 3.8 > 0.9 ? 0.75 : 0.26]],
  },
  searching: {
    label: 'Searching', busy: true,
    pose: (t) => { const w = Math.sin(t * 2.6) > 0 ? 1 : 0; return { ...REST, head: [2, 1], tilt: 0.14, eyes: 'wide', hand: [PX - 8 + w, DESK - 6], far: [PX + 1 - w, DESK - 19] }; },
    props: () => { rc(PX - 5, DESK - 2, 10, 2, '#ae7a1c'); rc(PX - 3, DESK - 4, 6, 2, '#855714'); ell(PX, DESK - 10, 7.4, 7.4, rad(PX - 2, DESK - 12, 8, '#7ce0e0', '#3cb4c8', '#1c6c7c')); },
    fx: (t) => {
      const cy = DESK - 10; g.save(); g.globalCompositeOperation = 'lighter'; glow(PX, cy, 15, '80,220,230', 0.34 + 0.1 * Math.sin(t * 4)); g.restore();
      for (let i = 0; i < 3; i++) strokeP('rgba(200,255,250,.75)', 1, (k) => k.arc(PX, cy, 2.2 + i * 1.7, t * (2.4 - i * 0.5) + i * 2, t * (2.4 - i * 0.5) + i * 2 + 1.5));
      for (let i = 0; i < 5; i++) if (hash(i, (t * 7) | 0) > 0.55) rc(R(PX - 4 + hash(i, 5 + ((t * 2) | 0)) * 8), R(cy - 4 + hash(i, 9 + ((t * 2) | 0)) * 8), 1, 1, '#c8f8f4');
      rc(PX - 4, cy - 5, 2, 1, '#ffffff'); rc(PX - 5, cy - 4, 1, 2, '#ffffff');
    },
    lights: (t) => [[PX, DESK - 10, 72, '90,230,235', 0.9 + 0.1 * Math.sin(t * 4)]],
    dim: 0.45,
  },
  reading: {   // a big book on a stand. A point of light runs along each line, and at the end of the page he flicks a finger and it turns itself
    label: 'Reading', busy: true,
    pose: (t) => { const c = READ(t), fl = c.q > 0 ? Math.sin(Math.PI * Math.min(1, c.q * 2.4)) : 0; return { ...REST, head: [1, c.ln > 3 ? 1 : 0], tilt: 0.1 + 0.02 * (c.ln % 4), eyes: 'dot', hand: [40 - 3 * fl, 28 - 6 * fl] }; },
    props: (t) => {
      const c = READ(t), B = BOOK, top = DESK - 15;
      poly([[B - 4, DESK + 1], [B + 4, DESK + 1], [B + 2, DESK - 4], [B - 2, DESK - 4]], '#5e3b0f'); rc(B - 7, DESK, 14, 2, '#855714');   // the stand
      poly([[B - 15, DESK - 1], [B + 15, DESK - 1], [B + 14, top - 1], [B - 14, top - 1]], '#7c1e12'); rc(B - 15, DESK - 2, 30, 1, '#4a1010');
      poly([[B - 13, DESK - 3], [B, DESK - 2], [B, top + 2], [B - 12, top]], '#f6f0dc'); poly([[B, DESK - 2], [B + 13, DESK - 3], [B + 12, top], [B, top + 2]], '#ffffff');
      for (let i = 0; i < 4; i++) for (const sd of [0, 1]) { const n = sd * 4 + i, x = sd ? B + 2 : B - 11, y = top + 3 + i * 2.6 + (sd ? -0.4 : 0.4); rc(x, y, 9, 1, c.q > 0 || n > c.ln ? 'rgba(50,34,20,.45)' : 'rgba(50,34,20,.9)'); }
      rc(B - 0.5, top + 2, 1, 11, '#6a5c50');
      if (c.q > 0) { const ex = B + 13 * Math.cos(Math.PI * c.q), ey = top - 6 * Math.sin(Math.PI * c.q); poly([[B, DESK - 2], [B, top + 2], [ex, ey], [ex, ey + 12]], c.q < 0.5 ? '#f6f0dc' : '#ffffff'); strokeP('rgba(50,34,20,.55)', 0.8, (k) => { k.moveTo(ex, ey); k.lineTo(ex, ey + 12); }); }
    },
    fx: (t) => {
      const c = READ(t), B = BOOK, top = DESK - 15;
      if (c.q <= 0) { const sd = c.ln > 3 ? 1 : 0, x = R((sd ? B + 2 : B - 11) + 9 * c.w), y = R(top + 3 + (c.ln % 4) * 2.6); rc(x, y, 2, 1, '#fffbd4'); rc(x - 2, y, 2, 1, '#f0ca4a'); g.save(); g.globalCompositeOperation = 'lighter'; glow(x, y, 5, '255,210,120', 0.5); g.restore(); }
      else for (let i = 0; i < 5; i++) { const a = Math.PI * Math.max(0, c.q - i * 0.07); rc(R(B + 15 * Math.cos(a)), R(top - 1 - 8 * Math.sin(a) + i * 2), 1, 1, i % 2 ? '#fbe88a' : '#fffbd4'); }   // what the flick leaves in the air
    },
    lights: () => [],
  },
  running: {
    label: 'Running', busy: true,
    pose: (t) => ({ ...REST, head: [1, 0], tilt: 0.12, eyes: 'dot', hand: [42 + 2 * Math.cos(t * 5), DESK - 18 + Math.sin(t * 5)], held: (hd) => strokeP('#ae7a1c', 1.5, (k) => { k.moveTo(hd[0] - 1, hd[1] - 2); k.lineTo(PX + 2 + 3 * Math.cos(t * 5), DESK - 9); }) }),
    props: () => cauldron(false),
    fx: (t) => {
      const cx = PX + 2; ell(cx, DESK - 10, 7.4, 1.5, '#8ce04a'); ell(cx - 2 + 2 * Math.cos(t * 5), DESK - 10, 3, 0.8, '#d0f48c');
      g.save(); g.globalCompositeOperation = 'lighter'; glow(cx, DESK - 11, 16, '120,255,70', 0.3); g.restore();
      for (let i = 0; i < 7; i++) { const ph = (t * (0.5 + hash(i, 1) * 0.5) + hash(i, 2)) % 1, x = R(cx - 6 + hash(i, 3) * 12 + Math.sin(ph * 5 + i) * 1.5), y = R(DESK - 11 - ph * 12); if (ph < 0.82) { rc(x, y, 2, 2, '#8ce04a'); rc(x, y, 1, 1, '#d0f48c'); } else { rc(x - 1, y, 1, 1, '#d0f48c'); rc(x + 2, y, 1, 1, '#d0f48c'); rc(x, y - 1, 1, 1, '#d0f48c'); } }
      wisp(cx + 1, DESK - 13, 16, 4, 0.2, t, '150,220,130');
    },
    lights: (t) => [[PX + 2, DESK - 11, 66, '150,255,90', 0.86 + 0.14 * vnoise(t * 6, 2)]],
    dim: 0.45,
  },
  writing: {
    label: 'Writing', busy: true,
    pose: (t) => { const ph = (t % 1.5) / 1.5, w = ph < 0.8 ? ph / 0.8 : 1 - smooth(0.8, 1, ph), jig = ph < 0.8 && (t * 16) % 1 < 0.5 ? 1 : 0; return { ...REST, head: [2, 1], tilt: 0.2, eyes: 'dot', hand: [38 + 10 * w, DESK - 5 - jig], held: (hd) => quill(hd[0] + 1, hd[1] + 1, -1.15) }; },
    props: (t) => {
      const ph = (t % 1.5) / 1.5, w = Math.min(1, ph / 0.8), n = Math.floor(t / 1.5) % 3, B = PX - 1;
      poly([[B - 14, DESK + 2], [B + 16, DESK + 2], [B + 14, DESK - 6], [B - 12, DESK - 6]], '#f6f0dc'); rc(B - 14, DESK + 1, 30, 1, '#9c8a70');
      limb(B - 14, DESK, 2.4, B - 13, DESK - 6, 2.4, '#cdb992'); limb(B + 16, DESK, 2.4, B + 15, DESK - 6, 2.4, '#cdb992');
      for (let i = 0; i < 3; i++) { const len = i < n ? 13 : i === n ? 2 + 11 * w : 0; if (len > 0) rc(B - 9, DESK - 5 + i * 2.2, len, 1, 'rgba(40,26,14,.85)'); }
    },
    lights: () => [],
  },
  waiting: {   // he has stopped, turned to face you, and is waving. The page is ready and the quill is on it
    label: 'Needs you', color: '#f0ca4a',
    pose: (t) => { const w = Math.sin(t * 7) > 0 ? 1 : -1, up = t % 2.4 < 1.5; return { ...REST, front: true, head: [0, 0], eyes: 'wide', hand: up ? [40 + 2 * w, 16] : [38, 22] }; },
    props: () => {
      const B = PX + 4; poly([[B - 13, DESK + 2], [B + 15, DESK + 2], [B + 13, DESK - 6], [B - 11, DESK - 6]], '#f6f0dc'); rc(B - 13, DESK + 1, 28, 1, '#9c8a70');
      rc(B - 8, DESK - 5, 16, 1, 'rgba(40,26,14,.7)'); rc(B - 8, DESK - 3, 11, 1, 'rgba(40,26,14,.7)'); for (let x = B - 4; x < B + 11; x += 2) rc(x, DESK, 1, 1, '#a02a3a');
      rc(B - 9, DESK - 1, 1, 1, '#a02a3a'); rc(B - 8, DESK, 1, 1, '#a02a3a'); rc(B - 7, DESK - 1, 1, 1, '#a02a3a'); rc(B - 9, DESK + 1, 1, 1, '#a02a3a'); rc(B - 7, DESK + 1, 1, 1, '#a02a3a');
      quill(B + 2, DESK - 4, -0.3);
    },
    fx: (t) => {   // the mark over an innkeeper's head when he has something for you
      const b = [0, -1, -2, -1][Math.floor(t * 6) % 4], x = 49, y = 4 + b;
      rc(x + 1, y, 9, 13, INK); rc(x, y + 1, 11, 11, INK); rc(x + 1, y + 1, 9, 11, '#fffbd4'); rc(x + 2, y + 13, 3, 1, INK); rc(x + 1, y + 14, 2, 1, INK); rc(x + 2, y + 12, 2, 1, '#fffbd4');
      rc(x + 4, y + 3, 3, 5, '#e0641e'); rc(x + 4, y + 9, 3, 2, '#e0641e');
    },
    lights: () => [],
  },
  done: {
    label: 'Done', color: '#7cc8a4', candle: false,
    pose: (t) => ({ ...REST, head: [1, 2 + (Math.sin(t * 1.3) > 0 ? 1 : 0)], tilt: 0.34, hat: 0.16, eyes: 'shut', hand: [34, DESK - 4] }),   // nodded off, hat over his eyes
    props: () => { const B = PX + 2; limb(B - 6, DESK - 3, 2.6, B + 10, DESK - 3, 2.6, lin(0, DESK - 6, 0, DESK, '#fffbd4', '#cdb992')); ell(B + 2, DESK - 3, 2.6, 2.6, '#a02a3a'); rc(B + 1, DESK - 4, 1, 1, '#c84a56'); rc(B + 1, DESK - 1, 1, 2, '#6a1626'); rc(B + 3, DESK - 1, 1, 2, '#6a1626'); },
    fx: (t) => {
      for (let i = 0; i < 2; i++) { const ph = (t * 0.45 + i * 0.5) % 1, x = R(44 + ph * 9 + Math.sin(ph * 6) * 1.5), y = R(18 - ph * 14), s = i ? 1 : 0, c = ph > 0.75 ? '#46639a' : '#bccbe6'; rc(x, y, 3 + s, 1, c); rc(x + 2 + s, y + 1, 1, 1, c); rc(x + 1, y + 2, 1 + s, 1, c); rc(x, y + 3, 3 + s, 1, c); }
      if (t < 5) wisp(CANDLE[0], CANDLE[1] + 1, 16, 2, 0.4 * (1 - t / 5), t);
    },
    lights: () => [[52, -18, 110, '130,160,255', 0.9]],
  },
  failed: {
    label: 'Failed', color: '#f89a38', candle: false,
    pose: () => ({ ...REST, head: [-1, 0], tilt: -0.1, hat: -0.5, soot: true, eyes: 'wide', hand: [37, DESK - 2] }),
    props: () => { ell(PX + 11, DESK - 0.4, 9, 1.4, '#2c4226'); cauldron(true); },
    back: () => { g.save(); g.filter = 'blur(2.5px)'; ell(PX + 4, 16, 20, 14, 'rgba(4,3,8,.7)'); g.restore(); },
    fx: (t) => {
      wisp(PX + 8, DESK - 6, 30, 5, 0.42, t, '70,70,84'); wisp(PX - 2, DESK - 8, 26, 8, 0.3, t + 1.7, '70,70,84');
      for (let i = 0; i < 7; i++) if (hash(i, (t * 5) | 0) > 0.5) rc(R(PX - 6 + hash(i, 31) * 26), R(DESK - 1 - hash(i, 32) * 3), 1, 1, i % 2 ? '#f89a38' : '#e0641e');
      const [bx, by] = hp({ head: [-1, 0], tilt: -0.1 }, 31.4, 37); flame(R(bx), R(by), t, 0.55);   // the end of his beard is still alight
      if (t < 0.34) { g.save(); g.globalCompositeOperation = 'lighter'; glow(PX, DESK - 10, 70, '255,200,120', 1 - t / 0.34); glow(PX, DESK - 10, 26, '255,255,230', 1 - t / 0.34); g.restore(); }
    },
    lights: (t) => [[PX + 4, DESK - 5, 60, '255,104,44', 0.75 + 0.2 * vnoise(t * 6, 3)], [52, -18, 110, '130,160,255', 0.55], ...(t < 0.34 ? [[PX, DESK - 10, 150, '255,220,160', 1 - t / 0.34]] : [])],
  },
};

// ───────── one frame ─────────
function scene(name, t, time) {
  const st = STATES[name], cand = st.candle !== false, fl = 0.86 + 0.14 * vnoise(time * 8, 1);
  const S = { amb: 'rgb(68,72,118)', lights: [...st.lights(t)] };
  if (cand) S.lights.push([CANDLE[0], CANDLE[1], 112, '255,184,110', (st.dim || 1) * fl]);
  const p = st.pose(t), blink = time % 3.7 < 0.13, main = S.lights[0];
  g = sctx; g.setTransform(1, 0, 0, 1, 0, 0); g.clearRect(0, 0, W, H);
  if (name === 'failed' && t < 0.26) g.translate(R((hash((t * 60) | 0, 1) - 0.5) * 3), R((hash((t * 60) | 0, 2) - 0.5) * 2));
  const BG = lit(layer(() => { g.drawImage(ROOM, 0, 0); if (st.back) st.back(); }), S); g.drawImage(BG, 0, 0);
  // he is always lit from in front, by whatever he is working at, so the edge that faces it catches the light
  const FG = layer(() => body(p)); lit(FG, S); rim(FG, -1.2, -0.3, main[0], main[1], 70, main[3], 0.8); g.drawImage(FG, 0, 0);
  const DK = lit(layer(() => { g.drawImage(DESKL, 0, 0);  if (st.props) st.props(t); }), S); g.drawImage(DK, 0, 0);
  const AR = layer(() => nearArm(p)); lit(AR, S); rim(AR, -1, -0.6, main[0], main[1], 60, main[3], 0.7); g.drawImage(AR, 0, 0);
  release(BG, FG, DK, AR);
  features(p, blink && p.eyes !== 'shut');
  g.save(); g.globalCompositeOperation = 'lighter'; glow(10.2, 4.6, 5, '90,220,230', 0.3 + 0.1 * Math.sin(time * 2)); g.restore(); rc(10, 4, 1, 1, '#c8f8f4');   // the stone in his staff
  if (cand) flame(CANDLE[0], CANDLE[1] + 1, time);
  if (st.fx) st.fx(t);
  const v = g.createLinearGradient(92, 0, W, 0); v.addColorStop(0, 'rgba(6,5,14,0)'); v.addColorStop(0.4, 'rgba(6,5,14,.4)'); v.addColorStop(1, 'rgba(6,5,14,.5)'); g.fillStyle = v; g.fillRect(92, 0, W - 92, DESK);
}

// ───────── the chip: a plain frame, because it is not a button ─────────
const INK = '#26221c', FW = W + 4, FH = H + 4, chip = mk(FW, FH), cctx = chip.getContext('2d');
function frame() {
  cctx.clearRect(0, 0, FW, FH); cctx.fillStyle = INK; cctx.fillRect(1, 0, FW - 2, FH); cctx.fillRect(0, 1, FW, FH - 2);
  cctx.fillStyle = '#6a5c50'; cctx.fillRect(1, 1, FW - 2, 1); cctx.fillRect(1, 1, 1, FH - 2); cctx.fillStyle = '#3c3430'; cctx.fillRect(1, FH - 2, FW - 2, 1); cctx.fillRect(FW - 2, 1, 1, FH - 2);
  cctx.drawImage(art, 2, 2);
}

// ───────── the element ─────────
const fitText = (str, n) => (str.length > n ? str.slice(0, n - 2) + '..' : str);
// A run the way an agent has them: plan, look things up, read, try something, watch it fail, try again, write it up, ask, finish.
const RUN = [[2.6, 'thinking', '', 'Planning'], [3.2, 'searching', '', '3 sources'], [3.2, 'reading', '', 'README.md'], [3, 'running', '', 'npm test'], [2.8, 'failed', '', 'Exit code 1'], [2.2, 'thinking', '', 'Trying again'], [2.8, 'running', '', 'npm test'], [3.4, 'writing', '', 'app.js'], [4, 'waiting', '', 'Approve the edit'], [4.6, 'done', '', '9 steps, 32s']];
// every chip on the page is painted from one loop, with the same scratch canvases
const LIVE = new Set(); let ticking = false, last = 0, baked = false;
// A first frame can be stamped before wake() ran, so the step is kept from going negative: time must not run backwards.
function loop(now) { if (!LIVE.size || SageStatus.paused) { ticking = false; return; } const dt = Math.max(0, Math.min(0.05, (now - last) / 1000)); last = now; for (const el of LIVE) el.advance(dt); requestAnimationFrame(loop); }
function wake() { if (!ticking && LIVE.size && !SageStatus.paused) { ticking = true; last = performance.now(); requestAnimationFrame(loop); } }
const SHEET = ':host{display:inline-block;position:relative;width:306px;max-width:100%;aspect-ratio:204/48;vertical-align:middle}canvas{display:block;width:100%;height:100%;image-rendering:pixelated}span{position:absolute;width:1px;height:1px;overflow:hidden;clip-path:inset(50%);white-space:nowrap}';
class SageStatus extends HTMLElement {
  static get observedAttributes() { return ['state', 'label', 'detail']; }
  constructor() {
    super();
    this._s = { name: 'thinking', t: 0, time: 0, label: STATES.thinking.label, detail: '', from: null, ft: 0, sw: 1 }; this._run = { on: false, i: -1, left: 0 };
    const root = this.attachShadow({ mode: 'open' });
    root.innerHTML = `<style>${SHEET}</style><canvas aria-hidden="true"></canvas><span role="status" aria-live="polite"></span>`;   // the words are also in the page, for screen readers
    this._view = root.querySelector('canvas'); this._say = root.querySelector('span'); this._view.width = FW * 3; this._view.height = FH * 3;
  }
  connectedCallback() {
    if (!baked) { bake(); baked = true; }
    if (this.hasAttribute('demo')) this.play(); else { this._go(this.getAttribute('state') || 'thinking', this.getAttribute('label'), this.getAttribute('detail')); this._s.sw = 1; }
    LIVE.add(this); this._render(); wake();
  }
  disconnectedCallback() { LIVE.delete(this); }
  attributeChangedCallback() { if (this.isConnected && !this._quiet) { this._run.on = false; this._go(this.getAttribute('state') || 'thinking', this.getAttribute('label'), this.getAttribute('detail')); } }
  _go(name, label, detail) {
    const s = this._s; if (!STATES[name]) return;
    if (name !== s.name || s.sw < 1) { s.from = s.name; s.ft = s.t; s.sw = 0; s.t = 0; }
    s.name = name; s.label = label || STATES[name].label; s.detail = detail || '';
    this._say.textContent = s.detail ? `${s.label}: ${s.detail}` : s.label;
    this._quiet = true; this.setAttribute('state', name); for (const [k, v] of [['label', label], ['detail', detail]]) v ? this.setAttribute(k, v) : this.removeAttribute(k); this._quiet = false;
  }
  // set('reading', 'Reading', 'AGENTS.md'): the state, and optionally your own label and a second line. An unknown state is ignored.
  set(name, label, detail) { if (!STATES[name]) return; this._run.on = false; this._go(name, label, detail); }
  play() { this._run = { on: true, i: -1, left: 0 }; }   // the made-up run, on a loop
  get state() { return this._s.name; }
  get states() { return Object.keys(STATES); }
  get runLength() { return RUN.reduce((a, r) => a + r[0], 0); }
  advance(dt) {
    const s = this._s, run = this._run;
    if (run.on) { run.left -= dt; if (run.left <= 0) { run.i = (run.i + 1) % RUN.length; const [d, name, label, detail] = RUN[run.i]; run.left += d; this._go(name, label, detail); } }
    s.time += dt; s.t += dt; if (s.sw < 1) { s.sw = Math.min(1, s.sw + dt / 0.26); if (s.sw < 0.5) s.ft += dt; }
    this._render();
  }
  _render() {
    // a change of state is a dip to dark and back, with the old scene on the way down and the new one on the way up
    const s = this._s, old = s.sw < 0.5 && s.from, dark = s.sw < 1 ? 1 - Math.abs(s.sw * 2 - 1) : 0, name = old ? s.from : s.name, st = STATES[s.name];
    scene(name, old ? s.ft : s.t, s.time);
    if (dark > 0) { g.setTransform(1, 0, 0, 1, 0, 0); g.fillStyle = `rgba(6,5,14,${dark * 0.9})`; g.fillRect(0, 0, W, H); }
    crush();
    if (!old) {
      g = actx; const dots = st.busy ? '.'.repeat(1 + (Math.floor(s.t * 2.5) % 3)) : '', label = fitText(s.label, 14 - (st.busy ? 3 : 0)) + dots, col = dark > 0.5 ? '#46639a' : st.color || '#e4ecf6';
      const detail = fitText(s.detail || (st.busy ? Math.floor(s.t) + 's' : ''), 17);
      ptext(label, 97, 10, '#090b15', 1); ptext(label, 96, 9, col, 1); if (detail) { ptext(detail, 97, 22, '#090b15'); ptext(detail, 96, 21, dark > 0.5 ? '#32497c' : '#8eaad2'); }
      if (s.name === 'done') { const x = 96 + ptextW(label, 1) + 5; for (const [dx, dy] of [[0, 3], [1, 4], [2, 5], [3, 4], [4, 3], [5, 2], [6, 1], [7, 0]]) rc(x + dx, 9 + dy, 1, 2, col); }
      g = sctx;
    }
    frame();
    const v = this._view.getContext('2d'); v.imageSmoothingEnabled = false; v.drawImage(chip, 0, 0, this._view.width, this._view.height);
  }
}
SageStatus.paused = false;   // set true to stop the clock and step it yourself with el.advance(seconds)
customElements.define('sage-status', SageStatus);
})();
