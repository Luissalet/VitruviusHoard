// Sigil: a loading spinner that is a summoning circle cut into a slate-blue stone floor, with a will-o'-wisp for a light.
// With no value the wisp circles the ring on its own and leaves a comet of ring and runes igniting and cooling behind it.
// Give it a value (0 to 1) and the wisp becomes the head of an arc that fills clockwise from the top, with the runes charging behind it.
// A value that stands still shows as waiting. At 100% the wisp dives into the middle and flares, and something climbs out of the floor and takes the light in its hands.
// If the task fails, el.fail() cracks the stone and the circle smoulders.
// Everything is painted in code at 97 x 97: a height map of the stone under a cool ambient, lit per pixel by the wisp (grooves catch it and throw shadows), then crushed to a fixed palette. No assets, no network.
//
// One file, no dependencies. Load it with a script tag and put <sigil-spinner></sigil-spinner> where the spinner goes.
// It fires "sigil:done" once, when the circle is answered.
(() => {
'use strict';
if (customElements.get('sigil-spinner')) return;   // loaded twice: the first one stands
function hash(x, y) { let h = (x * 374761393 + y * 668265263) | 0; h = (h ^ (h >>> 13)) * 1274126177 | 0; return ((h ^ (h >>> 16)) >>> 0) / 4294967296; }
function vnoise(x, y) { const xi = Math.floor(x), yi = Math.floor(y), fx = x - xi, fy = y - yi, sx = fx * fx * (3 - 2 * fx), sy = fy * fy * (3 - 2 * fy), l = (a, b, t) => a + (b - a) * t; return l(l(hash(xi, yi), hash(xi + 1, yi), sx), l(hash(xi, yi + 1), hash(xi + 1, yi + 1), sx), sy); }
const clamp = (v, a, b) => (v < a ? a : v > b ? b : v), mix = (a, b, t) => a + (b - a) * t, smooth = (a, b, v) => { const t = clamp((v - a) / (b - a), 0, 1); return t * t * (3 - 2 * t); };
const TAU = Math.PI * 2;
const RM = matchMedia('(prefers-reduced-motion: reduce)');   // with it on: a slow wisp, no flash, no sparks thrown

const W = 97, H = 97, C = 48, UP = 4, N = 16;   // the scene in art pixels, its middle pixel, canvas pixels to each art pixel, and how many runes there are
const R_D = 47.6, R_RUNE = 33, REV = 1.6;       // the edge of the flagstone, the radius of the rune ring (and of the wisp's orbit), seconds for a turn
const PAL = [
  '#020307', '#05060b', '#090b13', '#0e111c', '#141928', '#1b2236', '#242d46', '#2f3b5a', '#3d4d72', '#516590', '#6c83ad',   // the stone, cold
  '#0a0813', '#110d20',                                                                                                    // the stone in deep shadow, a little violet
  '#04100f', '#071a1b', '#0b2628', '#103639', '#16494c', '#1f6064', '#2c7c7e', '#40999a', '#5fb8b4', '#8adbd0',            // the stone with the wisp on it
  '#a6b0d2', '#c6cde4', '#2a4a5c', '#386478', '#4c8296', '#68a2b2',                                                       // pale stone for the rim, and mid stone with the wisp on it
  '#0f4a4a', '#14706a', '#1f9a88', '#38c4a6', '#7aeccc', '#c4fff0', '#f4fffa',                                            // the wisp itself
  '#3a0a08', '#7c1e12', '#b8421a', '#e0641e', '#f89a38', '#fbe88a',                                                       // ember: eyes
  '#030206', '#08060e', '#4a4038', '#8a7c68',                                                                              // the figure, and horn
  '#140a08', '#24100c', '#3a1c14', '#5a2c1c', '#7a4228',                                                                   // the stone with a dying ember on it
];
const mk = (w, h) => Object.assign(document.createElement('canvas'), { width: w, height: h });
const soft = mk(W, H), sctx = soft.getContext('2d', { willReadFrequently: true });
let g = sctx;
const rc = (x, y, w, h, c) => { g.fillStyle = c; g.fillRect(x, y, w, h); };

// ───────── crush: every pixel to the nearest palette colour, with a 4 x 4 ordered dither ─────────
const B4 = [0, 8, 2, 10, 12, 4, 14, 6, 3, 11, 1, 9, 15, 7, 13, 5], SPREAD = 8;
const bayer = (x, y) => (B4[(y & 3) * 4 + (x & 3)] + 0.5) / 16;
const RGB = PAL.map((h) => [parseInt(h.slice(1, 3), 16), parseInt(h.slice(3, 5), 16), parseInt(h.slice(5, 7), 16)]);
const PAL32 = new Uint32Array(RGB.map((c) => (255 << 24) | (c[2] << 16) | (c[1] << 8) | c[0])), LUT = new Uint8Array(32768);
for (let r = 0; r < 32; r++) for (let gg = 0; gg < 32; gg++) for (let b = 0; b < 32; b++) {
  let best = 0, bd = 1e9; const R = r * 8 + 4, G = gg * 8 + 4, Bv = b * 8 + 4;
  for (let q = 0; q < RGB.length; q++) { const c = RGB[q], e = 2 * (R - c[0]) ** 2 + 4 * (G - c[1]) ** 2 + 3 * (Bv - c[2]) ** 2; if (e < bd) { bd = e; best = q; } }
  LUT[(r << 10) | (gg << 5) | b] = best;
}
const art = mk(W, H), actx = art.getContext('2d'), artImg = actx.createImageData(W, H), art32 = new Uint32Array(artImg.data.buffer);
function crush() {
  const d = sctx.getImageData(0, 0, W, H).data;
  for (let y = 0, i = 0, j = 0; y < H; y++) for (let x = 0; x < W; x++, i += 4, j++) {
    const nz = (bayer(x, y) - 0.5) * SPREAD;
    let r = d[i] + nz, gg = d[i + 1] + nz, b = d[i + 2] + nz;
    r = r < 0 ? 0 : r > 255 ? 255 : r; gg = gg < 0 ? 0 : gg > 255 ? 255 : gg; b = b < 0 ? 0 : b > 255 ? 255 : b;
    art32[j] = PAL32[LUT[((r >> 3) << 10) | ((gg >> 3) << 5) | (b >> 3)]];
  }
  actx.putImageData(artImg, 0, 0);
}

// ───────── the stone: baked once as a height map, an albedo and a shine, so that a light can be put on it every frame ─────────
const NPX = W * H, SW = 36, SH = 40, FEET = 60;   // the figure's sprite is 36 x 40, and its hem rests on row 60
const dist = (x, y) => Math.hypot(x - C, y - C);
let HT, NX, NY, NZ, AR, AG, AB, SP, RID, RW, RBW, RBI, DISC, MASK, RGW, STID, STW, ANG, CRKW, CRKB;
// The crack that opens across the floor when the task fails: a main run from rim to rim, with two branches. It exists only in the failed state.
const CRACK = [[[8, 31], [20, 37], [26, 34], [37, 43], [46, 45], [53, 54], [62, 57], [69, 66], [80, 68], [90, 77]], [[46, 45], [44, 56], [38, 64], [39, 74]], [[62, 57], [66, 47], [64, 38], [70, 30]]];
let CAL, CAA, CNX, CNY, CNZ, CHT;   // the figure: albedo, alpha, normals, height
function boxBlur(a, w, h, r) {
  const t = new Float32Array(a.length), o = new Float32Array(a.length), n = 2 * r + 1;
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) { let s = 0; for (let k = -r; k <= r; k++) s += a[y * w + clamp(x + k, 0, w - 1)]; t[y * w + x] = s / n; }
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) { let s = 0; for (let k = -r; k <= r; k++) s += t[clamp(y + k, 0, h - 1) * w + x]; o[y * w + x] = s / n; }
  return o;
}
function maskOf(w, h, draw) {   // draw white strokes on black and get back a 0 to 1 map
  const c = mk(w, h), x = c.getContext('2d', { willReadFrequently: true }); x.fillStyle = '#000'; x.fillRect(0, 0, w, h); x.strokeStyle = x.fillStyle = '#fff'; x.lineCap = x.lineJoin = 'round'; draw(x);
  const d = x.getImageData(0, 0, w, h).data, m = new Float32Array(w * h); for (let i = 0; i < m.length; i++) m[i] = d[i * 4] / 255; return m;
}
// Sixteen runes, each a few straight strokes on a 5 x 7 grid, with the top of the rune pointing out from the circle. They are made up: none is a letter.
const RUNES = [
  [[[1, 0], [1, 7]], [[1, 2], [4, 0]], [[1, 4], [4, 2]]], [[[0, 7], [0, 0], [3, 2], [3, 7]]], [[[1, 0], [1, 7]], [[1, 2], [4, 3.5], [1, 5]]], [[[1, 0], [1, 7]], [[1, 1], [4, 3]], [[1, 3], [4, 5]]],
  [[[1, 0], [1, 7]], [[1, 0], [4, 2], [1, 4]], [[1, 4], [4, 7]]], [[[4, 1], [1, 3.5], [4, 6]]], [[[0, 1], [4, 6]], [[4, 1], [0, 6]]], [[[1, 0], [1, 7]], [[1, 0], [4, 2], [1, 4]]],
  [[[0, 0], [0, 7]], [[4, 0], [4, 7]], [[0, 2], [4, 5]]], [[[2, 0], [2, 7]], [[0, 2.5], [4, 4.5]]], [[[2, 0], [0, 2], [2, 4]], [[2, 3], [4, 5], [2, 7]]], [[[2, 0], [2, 7]], [[2, 0], [0, 2]], [[2, 7], [4, 5]]],
  [[[2, 0], [2, 7]], [[2, 3.5], [0, 0.5]], [[2, 3.5], [4, 0.5]]], [[[3.5, 0], [0.5, 2.3], [3.5, 4.7], [0.5, 7]]], [[[2, 0], [2, 7]], [[2, 0], [0, 2.5]], [[2, 0], [4, 2.5]]], [[[1, 0], [1, 7]], [[1, 0], [4, 1.7], [1, 3.5], [4, 5.2], [1, 7]]],
];
const RUNE_A = (i) => (i * TAU) / N;
function bakeStone() {
  const CX = C + 0.5, ring = (x, r, w) => { x.lineWidth = w; x.beginPath(); x.arc(CX, CX, r, 0, TAU); x.stroke(); }, line = (x, a, b) => { x.beginPath(); x.moveTo(a[0], a[1]); x.lineTo(b[0], b[1]); x.stroke(); };
  // the circle: rings with a dial of ticks between them, a ring of runes, an inner ring, a five-pointed star, and a round well in the middle
  const GR = maskOf(W, H, (x) => {
    ring(x, 42.6, 1.7); ring(x, 40, 1); x.lineWidth = 0.9;
    for (let k = 0; k < 48; k++) { const a = (k * TAU) / 48, r1 = k % 4 === 0 ? 42.2 : 41.4; line(x, [CX + 40.5 * Math.sin(a), CX - 40.5 * Math.cos(a)], [CX + r1 * Math.sin(a), CX - r1 * Math.cos(a)]); }
    ring(x, 27, 1.7); ring(x, 25.2, 1);
    const v = Array.from({ length: 5 }, (_, k) => { const a = -Math.PI / 2 + (k * TAU) / 5; return [CX + 24.2 * Math.cos(a), CX + 24.2 * Math.sin(a)]; });
    x.lineWidth = 1.15; for (let k = 0; k < 5; k++) line(x, v[k], v[(k + 2) % 5]);
    x.lineWidth = 0.9; for (const [vx, vy] of v) { x.beginPath(); x.arc(vx, vy, 2.4, 0, TAU); x.stroke(); }
    ring(x, 9, 1.4); ring(x, 6.4, 0.8);
  });
  const RM = Array.from({ length: N }, (_, i) => maskOf(W, H, (x) => {
    x.save(); x.translate(CX, CX); x.rotate(RUNE_A(i)); x.translate(0, -R_RUNE); x.scale(1.25, 1.25); x.lineWidth = 1.45 / 1.25;
    for (const st of RUNES[i]) { x.beginPath(); st.forEach(([px, py], q) => (q ? x.lineTo(px - 2, py - 3.5) : x.moveTo(px - 2, py - 3.5))); x.stroke(); } x.restore();
  }));
  CRKW = maskOf(W, H, (x) => { CRACK.forEach((pts, i) => { x.lineWidth = i ? 0.9 : 1.3; x.beginPath(); pts.forEach(([px, py], q) => (q ? x.lineTo(px, py) : x.moveTo(px, py))); x.stroke(); }); }); CRKB = boxBlur(CRKW, W, H, 2);
  // the parts of the circle that can glow by themselves: the outer ring (it is a gauge), and the five strokes of the star
  const sv = Array.from({ length: 5 }, (_, k) => { const a = -Math.PI / 2 + (k * TAU) / 5; return [CX + 24.2 * Math.cos(a), CX + 24.2 * Math.sin(a)]; });
  RGW = maskOf(W, H, (x) => ring(x, 42.6, 1.7));
  const STM = sv.map((v, k) => maskOf(W, H, (x) => { x.lineWidth = 1.15; line(x, v, sv[(k + 2) % 5]); x.lineWidth = 0.9; x.beginPath(); x.arc(v[0], v[1], 2.4, 0, TAU); x.stroke(); }));
  STID = new Int8Array(NPX).fill(-1); STW = new Float32Array(NPX); ANG = new Float32Array(NPX);
  for (let k = 0; k < 5; k++) for (let i = 0; i < NPX; i++) if (STM[k][i] > STW[i]) { STW[i] = STM[k][i]; STID[i] = k; }
  for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) { const a = Math.atan2(x - C, C - y); ANG[y * W + x] = a < 0 ? a + TAU : a; }   // how far round the circle each pixel is, clockwise from the top
  // cracks and pits, placed by hand; a crack is a few straight runs with a kink at each joint
  const crack = (pts) => (x) => { x.lineWidth = 0.8; x.beginPath(); pts.forEach(([px, py], q) => (q ? x.lineTo(px, py) : x.moveTo(px, py))); x.stroke(); };
  const CK = maskOf(W, H, (x) => {
    for (const pts of [[[8, 61], [12, 65], [13, 70], [18, 74], [19, 79]], [[13, 70], [9, 74], [10, 78]], [[88, 24], [83, 28], [82, 34], [76, 38], [75, 44]], [[82, 34], [87, 37]], [[62, 88], [60, 82], [63, 77], [61, 72]], [[33, 8], [36, 12], [34, 17], [38, 20]]]) crack(pts)(x);
  });
  const PT = maskOf(W, H, (x) => { for (let k = 0; k < 16; k++) { const a = hash(k, 5) * TAU, r = 13 + hash(k, 6) * 29; x.beginPath(); x.ellipse(CX + r * Math.cos(a), CX + r * Math.sin(a), 0.7 + hash(k, 7) * 1.3, 0.6 + hash(k, 8) * 1.0, hash(k, 9) * 3, 0, TAU); x.fill(); } });
  const D = new Float32Array(NPX); RID = new Int8Array(NPX).fill(-1); RW = new Float32Array(NPX);
  for (let i = 0; i < NPX; i++) D[i] = GR[i];
  for (let q = 0; q < N; q++) for (let i = 0; i < NPX; i++) { if (RM[q][i] > D[i]) D[i] = RM[q][i]; if (RM[q][i] > RW[i]) { RW[i] = RM[q][i]; RID[i] = q; } }
  // a halo around each rune, so a charged one blooms a little into the stone
  RBW = boxBlur(RW, W, H, 2); RBI = new Int8Array(NPX).fill(-1);
  for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) { let best = 0, id = -1; for (let dy = -3; dy <= 3; dy++) for (let dx = -3; dx <= 3; dx++) { const j = clamp(y + dy, 0, H - 1) * W + clamp(x + dx, 0, W - 1); if (RW[j] > best) { best = RW[j]; id = RID[j]; } } RBI[y * W + x] = id; }
  const DS = boxBlur(D, W, H, 1), CKS = boxBlur(CK, W, H, 1), PTS = boxBlur(PT, W, H, 1);
  // flagstones: a grid that wanders, laid in running bond, each slab a little domed, with a joint round it
  HT = new Float32Array(NPX); AR = new Float32Array(NPX); AG = new Float32Array(NPX); AB = new Float32Array(NPX); SP = new Float32Array(NPX); DISC = new Uint8Array(NPX);
  for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) {
    const p = y * W + x, d = dist(x, y); DISC[p] = d <= R_D ? 1 : 0;
    const wx = x + 1.6 * Math.sin(y * 0.09 + 1), wy = y + 1.4 * Math.sin(x * 0.075), gx = Math.floor(wx / 34), off = gx & 1 ? 0.5 : 0, gyf = wy / 26 + off, gy = Math.floor(gyf);
    const fx = wx / 34 - gx, fy = gyf - gy, dj = Math.min(fx * 34, (1 - fx) * 34, fy * 26, (1 - fy) * 26), jd = 1 - smooth(0.2, 1.2, dj), tint = hash(gx, gy) - 0.5;
    let h = 0.45 * smooth(0, 7, dj) + 0.22 * (vnoise(x * 0.07, y * 0.07) - 0.5) - 0.8 * jd - 2.5 * DS[p] - 1.5 * CKS[p] - 1.2 * PTS[p];
    h += 1.5 * smooth(43.4, 45.4, d) - 4.5 * smooth(46, 47.6, d);   // a raised lip round the edge, and the drop outside it
    HT[p] = h;
    const mott = 0.82 + 0.3 * vnoise(x * 0.05 + 9, y * 0.05), dark = (1 - 0.4 * jd) * (1 - 0.8 * D[p]) * (1 - 0.7 * CKS[p]) * (1 - 0.5 * PTS[p]) * (1 + 0.5 * smooth(43.2, 44.6, d) * (1 - smooth(45.6, 46.4, d))) * (1 - 0.7 * smooth(46.3, 47.5, d));   // a pale bevel round the edge, then a dark outline
    AR[p] = (108 + tint * 22) * mott * dark; AG[p] = (118 + tint * 14) * mott * dark; AB[p] = (146 - tint * 10) * mott * dark;
    SP[p] = 0.22 + 0.5 * vnoise(x * 0.06 + 3, y * 0.06 + 11);   // damp patches shine more
  }
  HT = boxBlur(HT, W, H, 1); NX = new Float32Array(NPX); NY = new Float32Array(NPX); NZ = new Float32Array(NPX);
  for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) {
    const p = y * W + x, nx = (HT[y * W + clamp(x - 1, 0, W - 1)] - HT[y * W + clamp(x + 1, 0, W - 1)]) * 1.0, ny = (HT[clamp(y - 1, 0, H - 1) * W + x] - HT[clamp(y + 1, 0, H - 1) * W + x]) * 1.0, l = 1 / Math.hypot(nx, ny, 1);
    NX[p] = nx * l; NY[p] = ny * l; NZ[p] = l;
  }
  MASK = mk(W, H); { const m = MASK.getContext('2d'); m.fillStyle = '#000'; for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) if (DISC[y * W + x]) m.fillRect(x, y, 1, 1); }
}
// ───────── the thing that answers: a hooded, horned figure, painted once, with a height from its own outline so that light can find its edges ─────────
const HAND = [18, 30];   // where its open hand is, in the sprite
function bakeFigure() {
  const c = mk(SW, SH), x = c.getContext('2d', { willReadFrequently: true });
  const poly = (pts, col) => { x.fillStyle = col; x.beginPath(); pts.forEach(([px, py], q) => (q ? x.lineTo(px, py) : x.moveTo(px, py))); x.closePath(); x.fill(); };
  const horn = (s) => { x.fillStyle = '#d8c8a4'; x.beginPath(); x.moveTo(18 + s * 6, 11); x.bezierCurveTo(18 + s * 13, 11, 18 + s * 17, 7, 18 + s * 16.5, 0.3); x.bezierCurveTo(18 + s * 14, 5, 18 + s * 9, 7, 18 + s * 4.5, 7); x.closePath(); x.fill(); };
  horn(-1); horn(1);
  const cl = x.createLinearGradient(0, 14, 0, 40); cl.addColorStop(0, '#2a2240'); cl.addColorStop(1, '#120e1c');
  poly([[11.5, 14.5], [24.5, 14.5], [29, 17], [30, 24], [31, 32], [34, 39.5], [31, 38], [28, 40], [25, 38.5], [22, 40], [18.5, 38.5], [15, 40], [11.5, 38.5], [8, 40], [6, 38], [4.5, 39.5], [5, 32], [6, 24], [8, 17]], cl);
  x.lineCap = 'round'; x.strokeStyle = '#3a2f52'; x.lineWidth = 3.4;   // both arms come forward and the hands are cupped under the light
  for (const sg of [-1, 1]) { x.beginPath(); x.moveTo(18 + sg * 9.5, 18); x.lineTo(18 + sg * 10, 25); x.lineTo(18 + sg * 5.5, 29.5); x.stroke(); }
  x.fillStyle = '#4a3e66'; for (const sg of [-1, 1]) { x.beginPath(); x.ellipse(18 + sg * 4, 30.6, 3.2, 1.7, sg * 0.3, 0, TAU); x.fill(); }
  x.strokeStyle = '#4a3e66'; x.lineWidth = 0.9; for (const sg of [-1, 1]) for (const [dx, dy] of [[1.5, -1.6], [3, -1.2], [4.5, 0.2]]) { x.beginPath(); x.moveTo(18 + sg * dx, 30); x.lineTo(18 + sg * (dx - 0.8), 28.1 + dy * 0.3); x.stroke(); }
  const hood = x.createLinearGradient(0, 4, 0, 15); hood.addColorStop(0, '#32284a'); hood.addColorStop(1, '#1c1630');
  x.fillStyle = hood; x.beginPath(); x.moveTo(18, 3); x.quadraticCurveTo(26.5, 8, 25.5, 16); x.lineTo(10.5, 16); x.quadraticCurveTo(9.5, 8, 18, 3); x.fill();
  x.fillStyle = '#030206'; x.beginPath(); x.ellipse(18, 11.4, 4.8, 5.4, 0, 0, TAU); x.fill();   // the face is a dark hollow
  const d = x.getImageData(0, 0, SW, SH).data; CAL = new Uint8Array(d); CAA = new Float32Array(SW * SH); for (let i = 0; i < CAA.length; i++) CAA[i] = d[i * 4 + 3] / 255;
  const F = maskOf(SW, SH, (f) => { f.lineWidth = 0.9; for (const [x0, y0, x1, y1] of [[14, 18, 12, 38], [18, 17, 18, 39], [22, 18, 25, 38], [10, 22, 8, 36], [27, 24, 30, 37]]) { f.beginPath(); f.moveTo(x0, y0); f.lineTo(x1, y1); f.stroke(); } });   // folds in the cloak
  const ARM = maskOf(SW, SH, (f) => { f.lineWidth = 3.4; for (const sg of [-1, 1]) { f.beginPath(); f.moveTo(18 + sg * 9.5, 18); f.lineTo(18 + sg * 10, 25); f.lineTo(18 + sg * 5.5, 29.5); f.stroke(); f.beginPath(); f.ellipse(18 + sg * 4, 30.6, 3.2, 1.7, sg * 0.3, 0, TAU); f.fill(); } });
  const HOL = maskOf(SW, SH, (f) => { f.beginPath(); f.ellipse(18, 11.4, 4.8, 5.4, 0, 0, TAU); f.fill(); });
  const B = boxBlur(CAA, SW, SH, 2), B2 = boxBlur(B, SW, SH, 2); CHT = new Float32Array(SW * SH);
  for (let i = 0; i < CHT.length; i++) CHT[i] = B2[i] * 7 + 0.8 * F[i] - 1.6 * HOL[i] + 2.2 * ARM[i];
  CNX = new Float32Array(SW * SH); CNY = new Float32Array(SW * SH); CNZ = new Float32Array(SW * SH);
  for (let yy = 0; yy < SH; yy++) for (let xx = 0; xx < SW; xx++) { const p = yy * SW + xx, nx = (CHT[yy * SW + clamp(xx - 1, 0, SW - 1)] - CHT[yy * SW + clamp(xx + 1, 0, SW - 1)]) * 0.8, ny = (CHT[clamp(yy - 1, 0, SH - 1) * SW + xx] - CHT[clamp(yy + 1, 0, SH - 1) * SW + xx]) * 0.8, l = 1 / Math.hypot(nx, ny, 1); CNX[p] = nx * l; CNY[p] = ny * l; CNZ[p] = l; }
}

// ───────── the wisp, and when things happen ─────────
// Three things the circle can be doing, and each has to look like itself:
//   a plain spinner: the wisp goes round and round on its own, with a comet of ring and runes behind it that fades.
//   progress: the wisp is a tracker. It sits at the front of an arc that grows clockwise from the top, and goes no further than the value.
//   a stall (progress that has not moved for about a second, el.stalled): the wisp stays where it is, breathes, and sends a slow ripple out across the stone. It is waiting, and it is clearly not frozen.
// The answer, in seconds from the moment the value reaches 1:
//   0 to 0.5       the ring closes and flashes, and the runes flash round in turn
//   0.5 to 1.2     the wisp dives into the middle in a spiral and the star is drawn behind it, one stroke at a time
//   1.2 to 1.4     everything dims: a breath in
//   1.4            the flare: a blast of light, two rings across the floor, sparks and a pillar of light
//   1.55 to 3.0    the figure climbs out. 3.0 to 3.9: the wisp goes to its hand. After that it is quiet, and moves a little.
const T_RING = 0.5, T_DIVE = 1.2, T_BLAST = 1.4, T_UP0 = 1.55, T_UP1 = 3.0, T_HAND0 = 3.0, T_HAND1 = 3.9, SETTLED = 4.5;
const FX = C - 18, FY = FEET - SH;   // where the figure's sprite is, when it has come all the way up
const HX = FX + HAND[0], HY = FY + HAND[1] - 7;   // where the wisp rests: just above its cupped hands
const flashAt = (s) => (s.done ? smooth(T_BLAST - 0.02, T_BLAST + 0.05, s.ta) * (1 - smooth(T_BLAST + 0.04, T_BLAST + 0.5, s.ta)) * (RM.matches ? 0.3 : 1) : 0);
const dimAt = (s) => (s.done ? smooth(T_DIVE, T_DIVE + 0.1, s.ta) * (1 - smooth(T_BLAST - 0.03, T_BLAST, s.ta)) * (RM.matches ? 0.3 : 1) : 0);
function divePos(ta) { const u = clamp((ta - T_RING) / (T_DIVE - T_RING), 0, 1), R = R_RUNE * Math.pow(1 - u, 1.6), a = 4.6 * u * u; return [C + R * Math.sin(a), C - R * Math.cos(a), u]; }
function wispAt(s) {   // { x, y, z, I, a }: where the light is, how high above the floor, how bright, and how far round the ring
  const t = s.time, fl = 0.9 + 0.1 * vnoise(t * 9, 4), bob = Math.sin(t * 5.3); let z = 11 + Math.sin(t * 4.1) * 1.1, I = fl, x, y, a = (t / (REV * (RM.matches ? 3 : 1))) * TAU;
  if (s.failed) {   // it falls, stutters and goes out, and what is left is a coal
    const tf = s.tf, g2 = smooth(0.1, 1.3, tf); x = s.fx; y = s.fy + 2.5 * g2; z = mix(z, 2.5, g2); I = fl * (tf < 0.3 ? 1.5 : mix(1.2, 0.26, smooth(0.3, 1.7, tf)) * (0.6 + 0.4 * vnoise(t * 22, 5))) + (tf > 1.7 ? 0.05 * Math.sin(t * 1.3) : 0);
  } else if (!s.done) {
    const R = R_RUNE + bob * 1.2, xs = C + R * Math.sin(a), ys = C - R * Math.cos(a);   // where it would be going round on its own
    if (s.det || s.dm > 0.01) {   // the tracker: at the front of the arc, and restless in place when it is waiting. Going to and from a plain spin it crosses the floor rather than jumping.
      const w = s.stall, ap = s.p * TAU, Rd = R_RUNE + bob * 1.2 * (1 - 0.6 * w), m = s.dm * s.dm * (3 - 2 * s.dm);
      const xd = C + Rd * Math.sin(ap) + w * 1.8 * Math.sin(t * 2.3), yd = C - Rd * Math.cos(ap) + w * 1.4 * Math.cos(t * 1.9);
      x = mix(xs, xd, m); y = mix(ys, yd, m); I = fl * mix(1, mix(1, 0.74 + 0.26 * Math.sin(t * 2.8), w), m); z += w * 1.5 * Math.sin(t * 2.8) * m; if (s.det) a = ap;
    } else { x = xs; y = ys; }
  } else {
    const ta = s.ta, f = flashAt(s), settle = smooth(T_HAND0, SETTLED, ta);
    if (ta < T_DIVE) { const [dx, dy, u] = divePos(ta); x = dx; y = dy; z += 3 * u; I = fl * (1.2 + 1.5 * u) * (ta < T_RING ? 0.9 + 0.5 * smooth(0, T_RING, ta) : 1); }
    else { const v = smooth(T_HAND0, T_HAND1, ta); x = mix(C, HX, v); y = mix(C + 3, HY, v) + (ta > T_HAND1 ? bob * 0.6 : 0); z = mix(14, 9, v) + Math.sin(t * 3) * 0.5; I = fl * mix(1.7, 1.2, settle) * (1 + 0.1 * settle * Math.sin(t * 1.7)); }
    I = I * (1 - 0.9 * dimAt(s)) + 1.6 * f * fl;
  }
  return { x, y, z, I, a };
}

// ───────── the scene: one light, put on every pixel of the stone ─────────
const AMB = [0.36, 0.40, 0.54], FAMB = [0.054, 0.0675, 0.117], SF = [0.07, 0.15, 0.27, 0.42, 0.6], AMP = 2.1, R0 = 21, RMAX = 62;
const IMG = sctx.createImageData(W, H), OUT = IMG.data;
const MOTES = Array.from({ length: 26 }, (_, k) => [hash(k, 1) * 70 + 13, hash(k, 2) * 60 + 18, 0.6 + hash(k, 3) * 1.1, hash(k, 4) * TAU]);
const EGAIN = 1.35;
let ER = 0, EG = 0, EB = 0, TR = 0, TG = 0, TB = 0, TW = 0;
function tone(r, g, b) {   // light to colour. Each channel rolls off on its own, which goes white when it is bright; in the flare (TW) it keeps its hue, so the blast stays a bright teal and the stone shows through it
  const pr = 1 - Math.exp(-1.25 * r), pg = 1 - Math.exp(-1.25 * g), pb = 1 - Math.exp(-1.25 * b);
  if (TW > 0) { const m = Math.max(r, g, b); if (m > 1e-4) { const k = (1 - Math.exp(-1.25 * m)) / m * 0.9; TR = 255 * (pr + (r * k - pr) * TW); TG = 255 * (pg + (g * k - pg) * TW); TB = 255 * (pb + (b * k - pb) * TW); return; } }
  TR = 255 * pr; TG = 255 * pg; TB = 255 * pb;
}
function emit(gl, w) {   // something that glows by itself: dim and teal at first, then white-hot. It adds to ER, EG, EB
  const hot = Math.max(0, gl - 0.62) * 2.6, tw = Math.min(1, gl * 1.5);
  ER += w * (0.08 * tw + 0.5 * hot) * EGAIN; EG += w * (0.85 * tw + 0.5 * hot) * EGAIN; EB += w * (0.7 * tw + 0.5 * hot) * EGAIN;   // on a lighter stone the glow needs a little more to read
}
const FLARE = new Float32Array(N), STAR_LV = new Float32Array(5);
const EMBER = [1, 0.42, 0.16];   // what the light turns into when it has failed
function tint(E, fm) { return fm > 0 ? [mix(E[0], E[1] * 1.1, fm), mix(E[1], E[1] * 0.38, fm), mix(E[2], E[1] * 0.1, fm)] : E; }
function scene(s) {
  const t = s.time, ta = s.ta, done = s.done, det = s.det, wsp = wispAt(s), wx = wsp.x, wy = wsp.y, wz = wsp.z, I = wsp.I, wa = wsp.a, flash = flashAt(s), dim = dimAt(s), heat = s.heat, stall = done || s.failed ? 0 : s.stall, failed = s.failed, tf = s.tf, FM = failed ? smooth(0, 0.4, tf) : 0, ff = 1, crk = failed ? smooth(0.15, 0.6, tf) : 0, crkFlash = failed ? Math.exp(-(((tf - 0.35) / 0.12) ** 2)) : 0;
  const settle = done ? smooth(T_HAND0, SETTLED, ta) : 0, charge = done ? mix(1 + 0.9 * flash, 0.55, settle) * (1 - 0.7 * dim) : 1;   // the runes burn brighter in the flare and bank down once it is quiet
  const up = done ? clamp((ta - T_UP0) / (T_UP1 - T_UP0), 0, 1) : 0, rise = 1 - (1 - up) * (1 - up) * (1 - up), oy = Math.round(FY + SH * (1 - rise));   // how far the figure has come out of the floor
  const pAng = s.p * TAU, tb = ta - T_BLAST;
  const ringR = done && tb > 0 ? tb * 78 : -50, ringA = done ? clamp(1 - tb / 0.85, 0, 1) : 0, ring2R = done && tb > 0.2 ? (tb - 0.2) * 78 : -50, ring2A = done ? clamp(1 - (tb - 0.2) / 0.85, 0, 1) * 0.6 : 0;
  const beamA = done ? smooth(T_BLAST, T_BLAST + 0.12, ta) * (1 - smooth(T_UP1 - 0.5, T_UP1 + 0.5, ta)) * (0.85 + 0.15 * Math.sin(t * 20)) : 0;   // a pillar of light up out of the middle
  const ringLv = done ? (Math.max(0.34 * (1 + 0.22 * settle * Math.sin(t * 0.9)), 1.3 * (1 - smooth(0.3, T_RING + 0.2, ta))) * (0.7 + 0.3 * smooth(0, 0.15, ta)) + 0.8 * flash) * (1 - 0.85 * dim) : 0;
  for (let i = 0; i < N; i++) FLARE[i] = done && ta < 0.8 ? 1.1 * Math.exp(-(((ta - 0.04 - i * 0.027) / 0.07) ** 2)) : 0;   // a flash that runs round the runes in turn, clockwise from the top
  for (let k = 0; k < 5; k++) STAR_LV[k] = failed ? 0.2 * smooth(0.2, 1.0, tf) * (0.8 + 0.2 * Math.sin(t * 1.1 + k)) : done ? smooth(T_RING + 0.1 + k * 0.12, T_RING + 0.3 + k * 0.12, ta) * (mix(1, 0.3 + 0.1 * Math.sin(t * 1.5 + k * 1.3), settle) + 0.9 * flash) * (1 - 0.85 * dim) : 0;   // the star is drawn, a stroke at a time
  TW = clamp(flash * 1.6, 0, 1);
  const aF = 1 - 0.6 * dim - 0.3 * flash - 0.3 * FM, A0 = AMB[0] * aF, A1 = AMB[1] * aF, A2 = AMB[2] * aF;   // the cool ambient dips for the breath in and the blast, and cools when it fails
  const amp = AMP * I, pingR = ((t % 2.1) / 2.1), pingA = stall * (1 - pingR) * (1 - pingR) * 1.0;
  for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) {
    const p = y * W + x, o = p * 4; if (!DISC[p]) { OUT[o] = OUT[o + 1] = OUT[o + 2] = 0; OUT[o + 3] = 255; continue; }
    const hh = HT[p], dx = wx - x, dy = wy - y, dz = wz - hh, dxy2 = dx * dx + dy * dy, d2 = dxy2 + dz * dz, inv = 1 / Math.sqrt(d2), lx = dx * inv, ly = dy * inv, lz = dz * inv;
    const nl = NX[p] * lx + NY[p] * ly + NZ[p] * lz, win = 1 - Math.min(1, d2 / (RMAX * RMAX)), att = (win * win) / (1 + d2 / (R0 * R0));
    let diff = 0, spec = 0;
    if (nl > 0) {
      let occ = 0; for (let q = 0; q < 5; q++) { const f = SF[q], sx = clamp((x + dx * f + 0.5) | 0, 0, W - 1), sy = clamp((y + dy * f + 0.5) | 0, 0, H - 1); if (HT[sy * W + sx] > hh + dz * f - 0.1) occ += 0.1; }   // a groove or a lip in the way throws a shadow
      const sh = 1 - Math.min(0.4, occ); diff = nl * att * amp * sh;
      const hz = lz + 1, hl = 1 / Math.hypot(lx, ly, hz), nh = Math.max(0, (NX[p] * lx + NY[p] * ly + NZ[p] * hz) * hl), n2 = nh * nh, n4 = n2 * n2, n8 = n4 * n4, n16 = n8 * n8; spec = n16 * n16 * SP[p] * att * amp * sh * 0.55;
    }
    const hot = Math.min(1, att * I * 0.9), lr = mix(mix(0.32, 0.72, hot), EMBER[0], FM), lg = mix(1, EMBER[1], FM), lb = mix(mix(0.82, 0.95, hot), EMBER[2], FM), haze = 0.09 * I / (1 + dxy2 / 60);   // the light is teal, and whiter at its heart; some of it hangs in the air
    const ch = crk > 0 ? 1 - 0.55 * crk * CRKB[p] : 1;
    let r = ch * AR[p] * (A0 + lr * diff) / 255 + lr * (spec + haze * 0.4), gg = ch * AG[p] * (A1 + lg * diff) / 255 + lg * (spec + haze), b = ch * AB[p] * (A2 + lb * diff) / 255 + lb * (spec + haze * 0.85);
    ER = EG = EB = 0;
    // the runes: charged ones glow in their grooves, most where the wisp is. In a plain spin, the ones it passes ignite and cool behind it.
    const id = RID[p], bid = RBI[p];
    if (id >= 0 || (bid >= 0 && RBW[p] > 0.02)) {
      const k = id >= 0 ? id : bid; let e = heat[k] * charge * (1 + 0.2 * settle * Math.sin(t * 1.1 - k * 0.5) + (failed ? 0.25 * Math.sin(t * 1.3 + k * 0.6) : 0)) + FLARE[k];
      if (det && !done && heat[k] > 0.02 && heat[k] < 0.98) e *= 1 - 0.3 * stall * (0.5 + 0.5 * Math.sin(t * 4.2));   // the rune it is waiting on beats
      if (e > 0.01) emit(e * (failed ? 1 : 0.34 + 0.66 / (1 + dxy2 / 150)), id >= 0 ? RW[p] : RBW[p] * 0.16);
    }
    // the outer ring is a gauge. Progress fills it from the top and the wisp is its head; a plain spin leaves a fading comet on it
    const rg = RGW[p];
    if (rg > 0.02) {
      let e = 0;
      if (done) e = ringLv;
      else if (failed) { e = (0.3 + 0.07 * Math.sin(t * 1.2 + ANG[p] * 2)) * smooth(0.1, 0.7, tf); if (det && ANG[p] <= pAng) e += 0.26 * smooth(0.1, 0.7, tf); }   // a dim ember ring, brighter along the way it had got
      else if (det) { const a = ANG[p]; if (a <= pAng) { const q = pAng - a; e = (0.42 + 0.55 * Math.exp(-q * q / 0.03)) * (1 + 0.5 * stall * Math.sin(t * 2.8)); } }
      else { const behind = (((wa - ANG[p]) % TAU) + TAU) % TAU; if (behind < 2.1) e = Math.pow(1 - behind / 2.1, 1.5) * 0.9; }
      if (e > 0.01) emit(e, rg);
    }
    const sid = STID[p]; if (sid >= 0 && STAR_LV[sid] > 0.01) emit(STAR_LV[sid] * (0.5 + 0.5 / (1 + dxy2 / 400)), STW[p]);
    if (crk > 0.01 && CRKB[p] > 0.01) { const ce = (CRKW[p] * (0.75 + 0.25 * Math.sin(t * 1.6 - x * 0.12)) * crk + CRKW[p] * crkFlash * 0.9) * 1.15; if (ce > 0.01) emit(ce, 1); }   // the crack glows like a seam of coal, with a slow wave along it
    if (ER + EG + EB > 0) { if (FM > 0) { const lum = EG * ff; ER = mix(ER * ff, lum * 1.1, FM); EG = mix(EG * ff, lum * 0.38, FM); EB = mix(EB * ff, lum * 0.1, FM); } r += ER; gg += EG; b += EB; }
    if (failed && tf < 0.9) { const dd = (dist(x, y) - tf * 60) / 2.4, rv = Math.exp(-dd * dd) * (1 - tf / 0.9) * 0.55; r += rv; gg += rv * 0.38; b += rv * 0.1; }   // one dull ring goes out when it fails
    if (ringA > 0 || ring2A > 0) { const dd = dist(x, y), d1 = (dd - ringR) / 2.2, d3 = (dd - ring2R) / 2.2, rv = Math.exp(-d1 * d1) * ringA * 1.3 + Math.exp(-d3 * d3) * ring2A * 1.3; r += rv * 0.5; gg += rv; b += rv * 0.9; }   // the answer goes out across the floor as rings of light
    if (beamA > 0.01) { const bx = (x - C) / 5.5, v = smooth(6, 26, y) * (1 - smooth(C + 6, C + 14, y)), bv = Math.exp(-bx * bx) * v * beamA * 0.55; r += bv * 0.6; gg += bv; b += bv * 0.9; }
    if (pingA > 0.01) { const dd = (Math.sqrt(dxy2) - pingR * 26) / (1.6 + pingR * 1.4), rv = Math.exp(-dd * dd) * pingA * 0.5; r += rv * 0.3; gg += rv; b += rv * 0.8; }   // a stalled ring listens: a slow ripple goes out from the wisp
    tone(r, gg, b); OUT[o] = TR; OUT[o + 1] = TG; OUT[o + 2] = TB; OUT[o + 3] = 255;
  }
  // the figure, lit by the same wisp, with the part of it still under the floor not drawn. Its hem sways a little once it is still.
  if (done && ta > T_UP0 - 0.05) {
    const sway = smooth(T_UP1, SETTLED, ta);
    for (let sy = 0; sy < SH; sy++) {
      const y = oy + sy; if (y > FEET || y < 0) continue;
      const shift = Math.round(Math.sin(t * 1.3 + sy * 0.35) * Math.max(0, sy - 24) / 16 * 1.1 * sway);
      for (let sx = 0; sx < SW; sx++) {
        const sxs = clamp(sx - shift, 0, SW - 1), i = sy * SW + sxs, a = CAA[i]; if (a < 0.05) continue; const x = FX + sx; if (x < 0 || x >= W) continue;
        const dx = wx - x, dy = wy - y, dz = wz - 2 - CHT[i], d2 = dx * dx + dy * dy + dz * dz, inv = 1 / Math.sqrt(d2), nl = Math.max(0, CNX[i] * dx * inv + CNY[i] * dy * inv + CNZ[i] * dz * inv), win = 1 - Math.min(1, d2 / (RMAX * RMAX)), att = (win * win) / (1 + d2 / (R0 * R0));
        const df = nl * att * amp * 2.4, hot = Math.min(1, att * I * 0.9), lr = mix(mix(0.32, 0.72, hot), EMBER[0], FM), lg = mix(1, EMBER[1], FM), lb = mix(mix(0.82, 0.95, hot), EMBER[2], FM), rimv = Math.pow(1 - CNZ[i], 2) * att * amp * 2.2;   // the edge facing the light catches it
        const r = CAL[i * 4] * (FAMB[0] + lr * (df + rimv * 0.5)) / 255, gg = CAL[i * 4 + 1] * (FAMB[1] + lg * (df + rimv)) / 255, b = CAL[i * 4 + 2] * (FAMB[2] + lb * (df + rimv * 0.9)) / 255, o = (y * W + x) * 4;
        tone(r, gg, b); OUT[o] += a * (TR - OUT[o]); OUT[o + 1] += a * (TG - OUT[o + 1]); OUT[o + 2] += a * (TB - OUT[o + 2]);
      }
    }
  }
  g = sctx; g.setTransform(1, 0, 0, 1, 0, 0); g.globalAlpha = 1; g.globalCompositeOperation = 'source-over'; g.putImageData(IMG, 0, 0);

  // what hangs in the air: mist round the figure's feet once it is still, mist where it climbs out, dust that only shows where the light catches it, and sparks off the wisp
  g.globalCompositeOperation = 'lighter';
  const mist = (mx, my, rr, a) => { const gr = g.createRadialGradient(mx, my, 1, mx, my, rr); gr.addColorStop(0, `rgba(80,200,170,${a})`); gr.addColorStop(1, 'rgba(80,200,170,0)'); g.fillStyle = gr; g.fillRect(Math.max(0, mx - rr), Math.max(0, my - rr), rr * 2, rr * 2); };
  if (done && ta > T_UP0 - 0.2 && ta < T_HAND1 + 0.6) { const m = smooth(T_UP0 - 0.2, T_UP0 + 0.4, ta) * (1 - smooth(T_UP1, T_HAND1 + 0.6, ta)); for (const [oyy, rr] of [[0, 15], [-9, 12], [-18, 9]]) mist(C, FEET + oyy, rr, 0.2 * m); }
  if (done && settle > 0) for (let k = 0; k < 3; k++) { const mx = C + 15 * Math.sin(t * 0.21 + k * 2.1), my = FEET - 2 + 3 * Math.sin(t * 0.3 + k), pr = 1 / (1 + ((mx - wx) ** 2 + (my - wy) ** 2) / 500); mist(mx, my, 15, 0.05 * settle * (0.3 + 0.7 * pr)); }   // low mist drifts in and out of the light
  const dust = (k) => { const m = MOTES[k]; return [m[0] + 5 * Math.sin(t * 0.33 + m[3]) + 3 * Math.sin(t * 0.9 + k), ((m[1] - t * m[2] * 1.4) % 64 + 64) % 64 + 16]; };
  for (let k = 0; k < MOTES.length; k++) { const [mx, my] = dust(k), px = Math.round(mx), py = Math.round(my); if (dist(px, py) > 42) continue; const dd = (px - wx) ** 2 + (py - wy) ** 2, br = I * Math.exp(-dd / 700) * (0.6 + 0.4 * Math.sin(t * 3 + k * 2)); if (br > 0.14) rc(px, py, 1, 1, failed ? (br > 0.5 ? '#b8421a' : '#7c1e12') : br > 0.8 ? '#7aeccc' : br > 0.4 ? '#38c4a6' : '#14706a'); }
  g.globalCompositeOperation = 'source-over';
  // the blast throws sparks up and out, and they fall
  if (done && tb > 0 && !RM.matches) for (let k = 0; k < 30; k++) {
    const th = hash(k, 11) * TAU, spd = 20 + hash(k, 12) * 52, life = 0.8 + hash(k, 13) * 1.3; if (tb > life) continue;
    const px = Math.round(C + Math.cos(th) * spd * tb * 0.9), py = Math.round(C + 4 - Math.abs(Math.sin(th)) * spd * tb * 1.15 + 58 * tb * tb), f = 1 - tb / life;
    if (dist(px, py) < 44) { g.fillStyle = f > 0.7 ? '#f4fffa' : f > 0.45 ? '#7aeccc' : f > 0.2 ? '#1f9a88' : '#0f4a4a'; g.fillRect(px, py, k % 4 === 0 ? 2 : 1, 1); }
  }
  if (failed && tf > 1.0) for (let k = 0; k < 6; k++) {   // sparks lift off the crack and go out
    const ph = (t * 0.28 + k / 6) % 1, pts = CRACK[0], v = pts[(k * 3 + 1) % pts.length], px = Math.round(v[0] + 2 * Math.sin(t * 0.7 + k)), py = Math.round(v[1] - ph * 13);
    if (ph < 0.85 && dist(px, py) < 44) rc(px, py, 1, 1, ph < 0.3 ? '#f89a38' : ph < 0.6 ? '#b8421a' : '#7c1e12');
  }
  // a little ember lifts off the figure's hem now and then, and goes out
  if (done && settle > 0.3) for (let k = 0; k < 6; k++) { const ph = (t * 0.3 + k / 6) % 1, px = Math.round(FX + 8 + k * 4 + 2 * Math.sin(t * 0.8 + k * 2)), py = Math.round(FEET - 4 - ph * 32); if (ph < 0.85 && dist(px, py) < 40) rc(px, py, 1, 1, ph < 0.3 ? '#f89a38' : ph < 0.6 ? '#b8421a' : '#7c1e12'); }
  // the wisp itself: a little flame with a tail of the places it has just been, and sparks that come off it and rise
  const wispOn = !done || ta < T_HAND1 + 2, wxr = Math.round(wx), wyr = Math.round(wy);
  const tail = failed ? 0 : done ? (ta < T_DIVE ? 1 : 0) : det ? smooth(0.1, 0.9, s.vel) : 1;
  if (tail > 0.02) for (let k = 14; k >= 1; k--) {
    let x, y; if (done) { const q = divePos(Math.max(0, ta - k * 0.035)); x = Math.round(q[0]); y = Math.round(q[1]); } else { const a = wa - k * 0.075, R = R_RUNE + Math.sin((t - k * 0.012) * 5.3) * 1.2; x = C + Math.round(R * Math.sin(a)); y = C - Math.round(R * Math.cos(a)); }
    const ix = Math.round((5.6 - k * 0.36) * tail); if (ix >= 1) { g.fillStyle = ['#0f4a4a', '#14706a', '#1f9a88', '#38c4a6', '#7aeccc', '#c4fff0'][clamp(ix - 1, 0, 5)]; g.fillRect(x, y, 1, 1); if (k < 5) g.fillRect(x, y - 1, 1, 1); }
  }
  if (stall > 0.05) for (const off of [0, 0.5]) {   // a stalled ring is listening: thin rings go out from the wisp, one after another, and fade
    const ph = (t / 2.1 + off) % 1, rr = 3 + ph * 25, al = stall * (1 - ph) * (1 - ph) * 0.95;
    g.globalCompositeOperation = 'lighter'; g.strokeStyle = `rgba(120,240,205,${al})`; g.lineWidth = 1; g.beginPath(); g.arc(wxr + 0.5, wyr + 0.5, rr, 0, TAU); g.stroke(); g.globalCompositeOperation = 'source-over';
  }
  if (wispOn) {
    const fc = failed ? ['#7c1e12', '#e0641e', '#fbe88a'] : ['#38c4a6', '#7aeccc', '#f4fffa'], gc = failed ? '240,110,40' : '120,240,205';
    const gl = g.createRadialGradient(wxr + 0.5, wyr + 0.5, 0.5, wxr + 0.5, wyr + 0.5, 11); gl.addColorStop(0, `rgba(${gc},${0.2 * Math.min(1.6, I)})`); gl.addColorStop(1, `rgba(${gc},0)`); g.globalCompositeOperation = 'lighter'; g.fillStyle = gl; g.fillRect(0, 0, W, H); g.globalCompositeOperation = 'source-over';
    const f1 = vnoise(t * 13, 7), f2 = vnoise(t * 17, 3), big = (1.35 + 0.45 * Math.max(0, I - 1.6)) * (1 - 0.25 * stall * (0.5 + 0.5 * Math.sin(t * 2.8))) * (1 - 0.6 * dim) * (failed ? 1 - 0.6 * smooth(0.3, 1.7, tf) : 1);
    g.fillStyle = fc[0]; g.beginPath(); g.moveTo(wxr - 2.4 * big, wyr + 1.5); g.quadraticCurveTo(wxr - 2.2 * big, wyr - 2.5, wxr + (f1 - 0.5) * 2.5, wyr - (8 + 4 * f2) * (1 - 0.3 * stall)); g.quadraticCurveTo(wxr + 2.2 * big, wyr - 2.5, wxr + 2.4 * big, wyr + 1.5); g.quadraticCurveTo(wxr, wyr + 3.5, wxr - 2.4 * big, wyr + 1.5); g.fill();
    g.fillStyle = fc[1]; g.beginPath(); g.ellipse(wxr, wyr, 1.8 * big, 2.7 * big, 0, 0, TAU); g.fill(); g.fillStyle = fc[2]; g.beginPath(); g.ellipse(wxr, wyr + 0.3, 0.9 * big, 1.5 * big, 0, 0, TAU); g.fill();
    const ns = failed ? (tf < 1.2 ? 5 : 0) : stall > 0.3 ? 12 : 8; for (let k = 0; k < ns; k++) { const ph = (t * 0.9 + k / ns) % 1, sd = Math.floor(t * 0.9 + k / ns), sx = wxr + Math.round((hash(k, sd) - 0.5) * 9 * (0.4 + ph)), sy = wyr - 3 - Math.round(ph * 12); if (ph < 0.9) rc(sx, sy, 1, 1, failed ? (ph < 0.4 ? '#e0641e' : '#7c1e12') : ph < 0.3 ? '#c4fff0' : ph < 0.6 ? '#7aeccc' : '#1f9a88'); }
  }
  if (done && ta > T_UP0) {   // the eyes: two slits that open, white and then ember, with a little glow round them. They glance at the wisp now and then. They are the figure's own, and light nothing.
    const e = smooth(T_UP1 - 0.7, T_UP1, ta), blink = (t % 4.1) > 3.98, ey = oy + 11, c = ta < T_UP1 + 0.4 ? '#fffbd4' : '#f89a38', cyc = t % 6.2, look = settle > 0.5 && cyc > 2.2 && cyc < 3.6 ? 1 : 0, eyl = ey + look;
    if (e > 0.05 && ey <= FEET && !blink) {
      g.globalCompositeOperation = 'lighter'; for (const ex of [FX + 16, FX + 20]) { const gr = g.createRadialGradient(ex, eyl + 0.5, 0.5, ex, eyl + 0.5, 3.6); gr.addColorStop(0, `rgba(240,110,40,${0.12 * e})`); gr.addColorStop(1, 'rgba(240,110,40,0)'); g.fillStyle = gr; g.fillRect(ex - 4, eyl - 4, 9, 9); } g.globalCompositeOperation = 'source-over';
      rc(FX + 15, eyl, 2, 1, c); rc(FX + 15, eyl - 1, 1, 1, '#e0641e'); rc(FX + 19, eyl, 2, 1, c); rc(FX + 20, eyl - 1, 1, 1, '#e0641e');
    }
  }
}

// ───────── the element ─────────
const SHEET = `
:host{display:inline-block;position:relative;vertical-align:middle;width:${W}px;aspect-ratio:1;line-height:0}
:host([hidden]){display:none}
.ring{position:absolute;inset:0}
canvas{display:block;width:100%;height:100%;image-rendering:pixelated}
.say{position:absolute;width:1px;height:1px;overflow:hidden;clip-path:inset(50%);white-space:nowrap}`;
// every spinner on the page is painted from one loop, with the same scratch canvases
const LIVE = new Set(); let ticking = false, last = 0, baked = false, paused = false;
function loop(now) { if (!LIVE.size || paused) { ticking = false; return; } const dt = last < 0 ? 0 : clamp((now - last) / 1000, 0, 0.05); last = now; for (const el of LIVE) el.advance(dt); requestAnimationFrame(loop); }
function wake() { if (!ticking && LIVE.size && !paused) { ticking = true; last = -1; requestAnimationFrame(loop); } }
const fin = mk(W, H), fctx = fin.getContext('2d');
class SigilSpinner extends HTMLElement {
  static get observedAttributes() { return ['value', 'label', 'done-label', 'fail-label']; }
  static get paused() { return paused; }                 // set true to stop the clock and step it yourself with el.advance(seconds)
  static set paused(v) { paused = !!v; wake(); }
  constructor() {
    super();
    const root = this.attachShadow({ mode: 'open' });
    root.innerHTML = `<style>${SHEET}</style><div class="ring" role="progressbar" aria-valuemin="0" aria-valuemax="100"><canvas aria-hidden="true"></canvas></div><span class="say" role="status"></span>`;
    this._bar = root.querySelector('.ring'); this._face = root.querySelector('canvas'); this._say = root.querySelector('.say');
    this._face.width = W * UP; this._face.height = H * UP;
    this._s = { time: LIVE.size * 1.37, p: 0, det: false, done: false, ta: 0, heat: new Array(N).fill(0), vel: 0, idle: 0, stall: 0, dm: 0, mark: 0, failed: false, tf: 0, fx: C, fy: C };
    this._want = null;
  }
  connectedCallback() { if (!baked) { bakeStone(); bakeFigure(); baked = true; } this._aria(); if (window.ResizeObserver) { this._ro = this._ro || new ResizeObserver(() => { this._face.style.imageRendering = this.clientWidth && this.clientWidth < W ? 'auto' : 'pixelated'; }); this._ro.observe(this); } LIVE.add(this); this._render(); wake(); }
  disconnectedCallback() { LIVE.delete(this); if (this._ro) this._ro.disconnect(); }
  attributeChangedCallback(name, _, v) {
    if (name === 'value') { const n = v === null ? NaN : parseFloat(v); this._want = Number.isFinite(n) ? clamp(n, 0, 1) : null; }   // with no usable number it is a plain spinner
    this._aria();
  }
  _aria() {   // what a screen reader gets: a progress bar, with no value while it is only spinning
    const s = this._s, b = this._bar;
    b.setAttribute('aria-label', this.getAttribute('label') || 'Loading');
    if (s.done) b.setAttribute('aria-valuenow', '100'); else if (this._want !== null) b.setAttribute('aria-valuenow', String(Math.round(this._want * 100))); else b.removeAttribute('aria-valuenow');
    b.setAttribute('aria-busy', s.done || s.failed ? 'false' : 'true');
    this._say.textContent = s.failed ? this.getAttribute('fail-label') || 'Failed' : s.done ? this.getAttribute('done-label') || 'Done' : '';
  }
  set(n, now) {   // the task's progress, 0 to 1. With nothing, or null, it goes back to a plain spinner. With a second argument of true it goes straight there.
    const v = n === null || n === undefined ? null : Number.isFinite(+n) ? clamp(+n, 0, 1) : this._want;
    if (this._s.failed) return;   // once it has failed it stays failed until reset()
    this._want = v; const s = this._s;
    if (now && v !== null && !s.done) { s.p = v; s.det = true; if (v >= 1) { this._finish(); s.ta = SETTLED + 1; } }
    this._aria();
  }
  reset() { Object.assign(this._s, { p: 0, det: false, done: false, ta: 0, vel: 0, idle: 0, stall: 0, dm: 0, mark: 0, failed: false, tf: 0 }); this._s.heat.fill(0); this._want = null; this.removeAttribute('value'); this._aria(); if (paused) this._render(); }   // back to a plain spinner, ready for the next task
  get value() { return this._s.failed ? null : this._s.done ? 1 : this._s.det ? this._s.p : null; }   // the progress it is showing, 1 once done, or null while it only spins
  get done() { return this._s.done; }
  fail() {   // the task failed: the wisp falls, stutters and goes out, the runes go cold, and one dull ring crosses the floor. Fires sigil:fail once.
    const s = this._s; if (s.done || s.failed) return; const w = wispAt(s); s.failed = true; s.tf = 0; s.fx = w.x; s.fy = w.y; this._aria(); this.dispatchEvent(new CustomEvent('sigil:fail', { bubbles: true, composed: true }));
  }
  get failed() { return this._s.failed; }
  get stalled() { return !this._s.done && !this._s.failed && this._s.stall > 0.5; }   // true while a value has stood still for a moment and the wisp is waiting
  _finish() { const s = this._s; s.done = true; s.p = 1; s.det = true; s.ta = 0; this._aria(); this.dispatchEvent(new CustomEvent('sigil:done', { bubbles: true, composed: true })); }
  advance(dt) {
    const s = this._s; s.time += dt;
    if (s.failed) { s.tf += dt; for (let i = 0; i < N; i++) s.heat[i] += clamp(0.45 - s.heat[i], -dt * 1.1, dt * 0.6); this._render(); return; }   // the runes cool to a dim ember and stay
    if (!s.done) {
      s.det = this._want !== null; const was = s.p;
      s.p += clamp((s.det ? this._want : 0) - s.p, -dt * 3, dt * 1.6);   // a jump in progress is walked, not teleported
      const speed = dt > 0 ? Math.abs(s.p - was) / dt : 0; s.vel += (speed - s.vel) * Math.min(1, dt * 8);   // how fast the wisp is travelling, for its tail
      if (!s.det || this._want >= 1 || Math.abs(s.p - s.mark) > 0.004) { s.mark = s.p; s.idle = 0; } else s.idle += dt;   // how long the value has stood still: it counts as moving if it has gone more than 0.4% since it last did
      s.stall += (smooth(0.5, 1.2, s.idle) - s.stall) * Math.min(1, dt * 4); s.dm += ((s.det ? 1 : 0) - s.dm) * Math.min(1, dt * 7);
      if (s.det && this._want >= 1 && s.p >= 0.999) this._finish();
    } else s.ta += dt;
    // which runes are charged. With a value: the first p x 16 of them, clockwise from the top. Without one: the ones the wisp has just gone past, cooling behind it.
    const wa = wispAt(s).a;
    for (let i = 0; i < N; i++) {
      const target = s.done ? 1 : s.det ? clamp(s.p * N - i, 0, 1) : (() => { const behind = (((wa - RUNE_A(i)) % TAU) + TAU) % TAU; return behind < 4.4 ? Math.pow(1 - behind / 4.4, 1.3) : 0; })();
      s.heat[i] += clamp(target - s.heat[i], -dt * 7, dt * 14);
    }
    this._render();
  }
  _render() {
    scene(this._s); crush();
    fctx.globalCompositeOperation = 'source-over'; fctx.clearRect(0, 0, W, H); fctx.drawImage(art, 0, 0); fctx.globalCompositeOperation = 'destination-in'; fctx.drawImage(MASK, 0, 0);   // the corners are clear: it is a round floor
    const v = this._face.getContext('2d'); v.imageSmoothingEnabled = false; v.clearRect(0, 0, this._face.width, this._face.height); v.drawImage(fin, 0, 0, this._face.width, this._face.height);
  }
}
customElements.define('sigil-spinner', SigilSpinner);
})();
