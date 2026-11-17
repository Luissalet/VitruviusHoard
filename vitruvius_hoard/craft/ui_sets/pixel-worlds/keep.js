// Keep: a password field where strength is a castle.
// Every keystroke drops building pieces into a 180x96 pixel scene: rope fence, palisade,
// stone wall and moat, castle, dragon. When you stop typing, a raccoon tests the defences.
// The strength score is a small estimate of how guessable it is, not a security tool. Nothing typed here is stored or sent anywhere.
//
// One file, no dependencies. Load it with a script tag and put <keep-field></keep-field> where the password field goes.
// el.value is what was typed, el.score is 0 to 1 and el.stage is 0 to 5. It fires "keep:change" whenever the score changes.
(() => {
'use strict';
if (customElements.get('keep-field')) return;   // loaded twice: the first one stands

// Everything down to "one field" is made once and shared by every field on the page: the palette, the baked background,
// the sprites, the plan of the 100 pieces, the scoring and the 180x96 scratch buffer the scene is painted into.

const clamp = (v, a, b) => (v < a ? a : v > b ? b : v);
const lerp = (a, b, t) => a + (b - a) * t;
const smooth = (a, b, v) => { const t = clamp((v - a) / (b - a), 0, 1); return t * t * (3 - 2 * t); };
function mulberry(seed) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6D2B79F5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
const brnd = mulberry(11);   // the dice for the background. Each field has its own for everything that moves.

// ───────────────────────── framebuffer ─────────────────────────
const GW = 180, GH = 96, PXS = 4, GY = 78, WATER = 80;
const low = document.createElement('canvas'); low.width = GW; low.height = GH;
const lctx = low.getContext('2d');
const img = lctx.createImageData(GW, GH);
const fb = new Uint32Array(img.data.buffer);
const bg = new Uint32Array(GW * GH), sky = new Uint8Array(GW * GH);
const col = (h) => { const n = parseInt(h.slice(1), 16); return ((255 << 24) | ((n & 255) << 16) | (n & 0xff00) | (n >> 16)) >>> 0; };
const pal = (o) => { const p = {}; for (const k in o) p[k] = col(o[k]); return p; };

function px(x, y, c) { x |= 0; y |= 0; if (x >= 0 && y >= 0 && x < GW && y < GH) fb[y * GW + x] = c; }
function rc(x, y, w, h, c) {
  x |= 0; y |= 0; w |= 0; h |= 0;
  const x1 = Math.max(0, x), x2 = Math.min(GW, x + w), y1 = Math.max(0, y), y2 = Math.min(GH, y + h);
  if (x2 <= x1) return;
  for (let yy = y1; yy < y2; yy++) fb.fill(c, yy * GW + x1, yy * GW + x2);
}
function spr(rows, p, x, y, flip, r0 = 0, r1 = rows.length) {
  x = Math.round(x); y = Math.round(y);
  for (let r = r0; r < r1; r++) {
    const row = rows[r], n = row.length;
    for (let c = 0; c < n; c++) { const ch = row[flip ? n - 1 - c : c]; if (ch !== '.') px(x + c, y + r, p[ch]); }
  }
}

// ───────────────────────── colours ─────────────────────────
const K = pal({
  wood: '#b07a42', woodL: '#cf9a5c', woodD: '#7d5228', gwood: '#8a5a2c', gwoodL: '#a87240', gwoodD: '#5e3b1a',
  rope: '#e6d3a3', iron: '#3b3f47', ironL: '#6b717c', ink: '#2a2620',
  st0: '#a3a9b3', st1: '#989ea8', st2: '#adb3bd', stL: '#d0d5dc', stD: '#737984',
  ks0: '#8c92a0', ks1: '#848a98', ks2: '#949aa8', ksL: '#b4bac6', ksD: '#646a78',
  roof: '#c8483c', roofL: '#e4705a', roofD: '#93302a', gold: '#f2c230', goldD: '#c9961a', red: '#d84a4a', redD: '#a83434',
  gate: '#2b2530', glow: '#f7d46a', glowD: '#d9a53c', dark: '#3a3540',
  pit: '#4f3421', pitD: '#3f2919', water: '#3f86d6', waterD: '#2f6cb8', waterL: '#a6d4ff', white: '#ffffff',
  dust: '#e9dcc0', cloud: '#ffffff', cloudS: '#d6e6f4', smoke: '#8d8a90', smokeD: '#5e5b63',
  f0: '#fff2a8', f1: '#ffb52e', f2: '#f0641e', f3: '#7a3a2a', bub: '#fffdf5',
});
const STONE = { base: [K.st0, K.st1, K.st2], L: K.stL, D: K.stD };
const KSTONE = { base: [K.ks0, K.ks1, K.ks2], L: K.ksL, D: K.ksD };

// ───────────────────────── background (painted once) ─────────────────────────
const bushPix = [];
function buildBg() {
  const B4 = [0, 8, 2, 10, 12, 4, 14, 6, 3, 11, 1, 9, 15, 7, 13, 5];
  const SKY = ['#58a4e0', '#7dbcea', '#a4d3f1', '#cde6f3', '#f3e7cb'].map(col);
  const set = (x, y, c, isSky = 0) => { if (x >= 0 && y >= 0 && x < GW && y < GH) { bg[y * GW + x] = c; sky[y * GW + x] = isSky; } };
  for (let y = 0; y < GH; y++) for (let x = 0; x < GW; x++) {
    const b = (B4[(y & 3) * 4 + (x & 3)] + 0.5) / 16;
    set(x, y, SKY[clamp(Math.floor(y / (GY - 1) * 4 + 0.5 + (b - 0.5) * 0.5), 0, 4)], 1);
  }
  // sun
  for (let y = -8; y <= 8; y++) for (let x = -8; x <= 8; x++) {
    const d = Math.hypot(x, y);
    if (d < 5.5) set(148 + x, 15 + y, col('#fff6c9'), 1);
    else if (d < 7.6 && ((x + y) & 1)) set(148 + x, 15 + y, col('#fdf0c0'), 1);
  }
  // mountains
  const PEAKS = [[18, 43], [56, 36], [96, 46], [131, 33], [168, 44]];
  for (let x = 0; x < GW; x++) {
    let top = 99, pk = PEAKS[0];
    for (const p of PEAKS) { const t = p[1] + Math.abs(x - p[0]) * 0.72; if (t < top) { top = t; pk = p; } }
    top = Math.round(top + (brnd() < 0.3 ? 1 : 0));
    for (let y = top; y < GY; y++) {
      const snow = y < pk[1] + 5 + ((x * 7) % 3);
      const shade = x > pk[0] + (y - pk[1]) * 0.25;
      set(x, y, col(snow ? (shade ? '#d5e0ee' : '#f4f8fc') : (shade ? '#7f97ba' : '#93aacb')));
    }
  }
  // two rows of hills
  for (let x = 0; x < GW; x++) {
    const h1 = Math.round(64 + 4 * Math.sin(x * 0.045 + 0.6) + 2.5 * Math.sin(x * 0.11 + 2) - 11 * Math.exp(-(((x - 166) / 17) ** 2)));
    for (let y = h1; y < GY; y++) set(x, y, col(y === h1 ? '#a3d488' : '#8cc474'));
    const h2 = Math.round(71 + 3 * Math.sin(x * 0.06 + 3.5) + 2 * Math.sin(x * 0.13));
    for (let y = h2; y < GY; y++) set(x, y, col(y === h2 ? '#86c96c' : '#72b85c'));
  }
  // ground
  for (let y = GY; y < GH; y++) for (let x = 0; x < GW; x++) {
    const n = brnd(), d = y - GY;
    let c = d === 0 ? '#8fd465' : d === 1 ? '#62b04c' : d === 2 && n < 0.45 ? '#4f9a40'
      : n < 0.12 ? '#77502f' : n < 0.2 ? '#a0714c' : '#8d6040';
    if (d > 11 && ((x + y) & 1) && n < 0.7) c = '#7a5236';
    set(x, y, col(c));
  }
  // trees
  const tree = (cx, r) => {
    const by = GY - 1, cy = by - 5 - r + 2;
    for (let y = 0; y < 7; y++) { set(cx - 1, by - y, col('#7a5230')); set(cx, by - y, col('#5e3d22')); }
    for (let y = -r; y <= r; y++) for (let x = -r; x <= r; x++) {
      if (x * x + y * y > r * r + 1) continue;
      const hi = (x + 2) ** 2 + (y + 2) ** 2 < (r - 2.5) ** 2, lo = y > r * 0.35;
      set(cx + x, cy + y, col(hi ? '#63b85c' : lo ? '#2f7a3c' : '#429a4a'));
    }
  };
  tree(8, 7); tree(21, 5);
  // flowers and tufts
  for (let k = 0; k < 26; k++) {
    const x = brnd() * GW | 0;
    if (x > 30 && x < 150) continue;
    set(x, GY - 1, col(['#f6e562', '#f08aa0', '#ffffff', '#8fd465'][brnd() * 4 | 0]));
  }
  // the raccoon's bush, kept as a sprite so it can be drawn in front of him
  const blobs = [[160, 73, 6], [167, 70, 7.5], [174, 73, 5.5], [155, 75, 4]];
  for (let y = 58; y < GY; y++) for (let x = 148; x < GW; x++) {
    let inside = false, lit = false;
    for (const [bx, by, r] of blobs) {
      const d = (x - bx) ** 2 + (y - by) ** 2;
      if (d <= r * r) { inside = true; if ((x - bx + r * 0.35) ** 2 + (y - by + r * 0.35) ** 2 < (r * 0.55) ** 2) lit = true; }
    }
    if (inside) bushPix.push(x, y, col(lit ? '#63b85c' : y > 73 ? '#2f7a3c' : '#429a4a'));
  }
}
buildBg();
const CLOUD_SHAPES = [
  [[2, 3, 22, 4], [6, 1, 10, 2], [14, 0, 7, 3], [0, 7, 26, 1, 1]],
  [[1, 2, 14, 3], [4, 0, 7, 2], [0, 5, 16, 1, 1]],
  [[2, 3, 18, 3], [5, 1, 6, 2], [11, 0, 6, 3], [0, 6, 22, 1, 1]],
];
const CLOUDS = [{ x: 22, y: 7, s: 2.1, k: 0 }, { x: 96, y: 21, s: 1.3, k: 1 }, { x: 178, y: 30, s: 1.7, k: 2 }];

// ───────────────────────── building pieces ─────────────────────────
const OX = -10;   // where the build sits; everything structural is offset by this
const PLAN = [];   // the 100 pieces as designed. Every field lays its own copy of them.
function add(kind, x, y, w, h, layer, cols, extra) {
  const p = { kind, x: x + OX, y, w, h, layer, cols, on: false, t0: -9, v: PLAN.length % 3, ...extra };
  PLAN.push(p);
  return p;
}
const ENDS = [0];
let PIT = null;   // the pit on the raccoon's side
(function buildPieces() {
  const W = [K.wood, K.woodL, K.woodD], G = [K.st0, K.stL, K.stD], KS = [K.ks0, K.ksL, K.ksD];
  // 1. rope fence and a sign
  for (const x of [72, 106, 79, 99]) add('stake', x, 71, 2, 7, 1, W);
  add('rope', 74, 73, 5, 1, 1, [K.rope]); add('rope', 101, 73, 5, 1, 1, [K.rope]); add('rope', 81, 73, 18, 1, 1, [K.rope]);
  add('post', 114, 70, 1, 8, 1, W); add('board', 111, 65, 7, 5, 1, W);
  ENDS.push(PLAN.length);
  // 2. palisade, built from both ends toward the gate
  for (let k = 0; k < 8; k++) for (const i of [k, 15 - k]) add('log', 58 + i * 4, 50, 4, 28, 2, W, { gate: i >= 6 && i <= 9 });
  add('beam', 58, 60, 64, 2, 2, W);
  ENDS.push(PLAN.length);
  // 3. stone wall in running bond, battlements, gate, then the moat
  for (let r = 0; r < 5; r++) {
    for (let x = r & 1 ? 52 : 58; x < 122; x += 12) {
      const x1 = Math.max(58, x), x2 = Math.min(122, x + 12);
      add('stone', x1, 72 - r * 6, x2 - x1, 6, 3, G);
    }
  }
  for (const x of [58, 70, 82, 94, 106, 116]) add('stone', x, 44, 6, 4, 4, G);
  add('gate', 83, 59, 14, 19, 3, [K.gate, K.ironL]);
  add('pit', 36, GY, 14, 9, 6, [K.pit, K.pitD], { dig: true });
  PIT = add('pit', 130, GY, 16, 9, 6, [K.pit, K.pitD], { dig: true });
  add('water', 36, WATER, 14, 7, 6, [K.water, K.waterL], { dig: true });
  add('water', 130, WATER, 16, 7, 6, [K.water, K.waterL], { dig: true });
  ENDS.push(PLAN.length);
  // 4. castle: keep behind the wall, towers at the ends, roofs, windows, flags
  for (let r = 0; r < 3; r++) for (const x of [76, 90]) add('kstone', x, 42 - r * 6, 14, 6, 0, KS);
  add('kcap', 75, 26, 30, 4, 0, KS);
  add('window', 87, 33, 6, 8, 0, [K.glow, K.gate]);
  for (let r = 0; r < 8; r++) for (const x of [52, 116]) add('stone', x, 72 - r * 6, 12, 6, 5, G);
  add('tcap', 51, 26, 14, 4, 5, G); add('tcap', 115, 26, 14, 4, 5, G);
  add('roof', 51, 17, 14, 9, 5, [K.roof, K.roofL, K.roofD]); add('roof', 115, 17, 14, 9, 5, [K.roof, K.roofL, K.roofD]);
  add('slit', 57, 40, 2, 6, 5, [K.gate]); add('slit', 121, 40, 2, 6, 5, [K.gate]);
  add('pole', 58, 9, 1, 8, 5, [K.gold, K.ink], { flag: K.gold, flagD: K.goldD, fw: 5 });
  add('pole', 122, 9, 1, 8, 5, [K.gold, K.ink], { flag: K.gold, flagD: K.goldD, fw: 5 });
  add('pole', 90, 12, 1, 14, 0, [K.red, K.ink], { flag: K.red, flagD: K.redD, fw: 8, banner: true });
  ENDS.push(PLAN.length);
})();
const TOTAL = PLAN.length;
const CUT = [0, 0.12, 0.36, 0.62, 0.9];   // score at which each stage is complete
const DROP = 0.2;

function block(x, y, w, h, v, S) {
  rc(x, y, w, h, S.base[v]); rc(x, y, w, 1, S.L); rc(x, y + h - 1, w, 1, S.D); rc(x + w - 1, y, 1, h, S.D);
  if (w > 5) px(x + 2 + v * 2, y + 2, S.D);
}

// ───────────────────────── sprites ─────────────────────────
const RACC_A = [
  '.d...d........',
  '.ggggg........',
  'ldeded....gtgt',
  'kllggggggggtgt',
  '.lggggggggggt.',
  '..gggggggggg..',
  '..ggllllgggg..',
  '..d..d..d..d..',
  '..d..d..d..d..',
];
const RACC_B = [...RACC_A.slice(0, 7), '...d.d...d.d..', '..d...d.d...d.'];
const RP = pal({ g: '#787d87', d: '#3a3d45', l: '#e4e7ea', k: '#15161a', t: '#4a4d55', e: '#15161a' });
const RP_BLINK = { ...RP, e: RP.d };
const CHEST = ['.wwwwwwww.', 'wyyyyyyyyw', 'wwwwwwwwww', 'yyyykkyyyy', 'wwwwkkwwww', 'wwwwwwwwww', 'dwwwwwwwwd'];
const CP = pal({ w: '#a5642a', y: '#f2c230', k: '#3a2a12', d: '#6e3f18' });
const KNIGHT = ['..r..', '.sss.', '.sks.', '.sss.', 'bbbbb', 'bbbbb', '.s.s.', '.s.s.'];
const KP = pal({ s: '#cfd4dc', k: '#22252b', r: '#d84a4a', b: '#3c6fc4' });
// The dragon is written as [x, pixels] runs per row so positions stay readable.
const DRAGON_SRC = [
  [[3, 'W']],
  [[2, 'WWW'], [26, 'h'], [30, 'h']],
  [[2, 'WmWW'], [26, 'h'], [30, 'h']],
  [[2, 'WmmWW'], [25, 'GGGGGGG']],
  [[2, 'WmmmWWW'], [24, 'GGGGGGGGGG']],
  [[2, 'WmmmmmWWW'], [24, 'GGeGGGGGGGGn']],
  [[2, 'WmmmmmmmWWW'], [24, 'GGGGGGGGGGGG']],
  [[2, 'WmmmWmmmmmmWW'], [23, 'GGGGGGtGtGtGt']],
  [[2, 'WmmmWmmmmmmmWW'], [22, 'GGGGGGrrrrrr']],
  [[2, 'WMmmWmmmWmmmmWW'], [21, 'GGGGGGGGGGGGG']],
  [[2, 'WMmmWmmmWmmmmmW'], [20, 'sGGGGbbGGGGG']],
  [[3, 'WMmWMmmWmmmmmW'], [19, 'sGGGGbbb']],
  [[3, 'WW.WMmmWmmmmWW'], [18, 'sGGGGbbb']],
  [[6, 'WWMmWMmmWW'], [16, 'sGGGGGGbbb']],
  [[7, 'W.WW.WW'], [14, 'sGGGGGGGGbbbb']],
  [[13, 'sGGGGGGGGGbbbb']],
  [[12, 'GGGGGGGGGGGbbbb']],
  [[11, 'GGGGGGGGGGGGbbbb']],
  [[10, 'GGGGGGGGGGGGGbbb']],
  [[9, 'GGGGGGGGGGGGGGbbG']],
  [[5, 'GGGGGGGGGGGGGGGGGGbGG']],
  [[2, 'GGGGGGG'], [10, 'GGGGGGG'], [19, 'GGGGG']],
  [[0, 'GGGGG'], [10, 'DDGGDD'], [19, 'DDGDD']],
  [[0, 'sGG']],
  [[0, 'ss']],
];
const DW_ = 36;
const DRAGON_A = DRAGON_SRC.map((runs) => {
  const row = new Array(DW_).fill('.');
  for (const [x, str] of runs) for (let i = 0; i < str.length; i++) row[x + i] = str[i];
  return row;
});
// shade the underside, then make a second frame with the wing folded down for flapping
for (let r = 0; r < DRAGON_A.length - 1; r++) {
  for (let c = 0; c < DW_; c++) if (DRAGON_A[r][c] === 'G' && DRAGON_A[r + 1][c] === '.') DRAGON_A[r][c] = 'g';
}
const DRAGON_B = DRAGON_A.map((row, r) => {
  if (r > 12) return row;
  const src = r < 6 ? null : DRAGON_A[(r - 6) * 2];
  return row.map((ch, c) => (c >= 16 ? ch : src ? src[c] : '.'));
});
const DP = pal({ G: '#4fb06c', g: '#37895a', b: '#f0df95', W: '#2a6e45', m: '#93dcb4', M: '#62ba92', D: '#f3ead0', h: '#f3ead0', e: '#ffe14a', n: '#1d3a28', t: '#ffffff', r: '#8e2f28', s: '#2a6e45' });
const DP_BLINK = { ...DP, e: DP.G };

// ───────────────────────── strength ─────────────────────────
// An estimate of how many guesses it would take, the way an attacker tries things: the usual passwords first, then words,
// keyboard runs, sequences, repeats and years, and only then one character at a time. Length on its own buys very little.
// It is a small hand-written estimate with a short word list, not a security tool.
const TOP = ('password 123456 12345678 123456789 qwerty abc123 letmein hunter2 iloveyou admin welcome monkey dragon password1 111111 qwerty123 passw0rd football baseball trustno1 raccoon ' +
  'master shadow sunshine princess superman batman login hello freedom whatever starwars secret love money computer internet michael jennifer jordan ashley daniel jessica charlie thomas robert matthew andrew joshua ' +
  'george pepper ginger cookie cheese banana flower pokemon mustang harley ranger hockey soccer killer tigger buster summer winter spring autumn test guest root pass changeme').split(' ');
const COMMON = new Set(TOP.slice(0, 21)), RANK = new Map(TOP.map((w, i) => [w, 4 + i * 6]));
const LEET = { '@': 'a', 4: 'a', 0: 'o', 1: 'l', 3: 'e', $: 's', 5: 's', 7: 't', '!': 'i' };
const KEYS = [['1234567890', 0], ['qwertyuiop', 0.5], ['asdfghjkl', 0.75], ['zxcvbnm', 1.25]], KPOS = {};
KEYS.forEach(([row, off], r) => [...row].forEach((ch, i) => { KPOS[ch] = [r, i + off]; }));
const nextKey = (a, b) => { const p = KPOS[a], q = KPOS[b]; return !!p && !!q && a !== b && Math.abs(p[0] - q[0]) <= 1 && Math.abs(p[1] - q[1]) <= 1.01; };
const isL = (c) => c >= 'a' && c <= 'z';
function guesses(pw) {
  const n = pw.length, lc = pw.toLowerCase();
  // letters, with a symbol or digit standing in for a letter (p@ssw0rd) read as that letter
  const nm = [...lc].map((c, i) => (LEET[c] && isL(lc[i - 1] || '') && isL(lc[i + 1] || '') ? LEET[c] : c)), M = [];
  const add = (i, j, g) => M.push([i, j, Math.max(1, g)]);
  for (let i = 0; i < n; i++) {
    if (!isL(nm[i])) continue;
    for (let j = i + 2; j <= n && isL(nm[j - 1]); j++) {   // every run of letters, as a known password, a pronounceable word, or neither
      const w = nm.slice(i, j).join(''), raw = pw.slice(i, j), caps = [...raw].filter((c) => c >= 'A' && c <= 'Z').length, swaps = [...lc.slice(i, j)].filter((c, k) => c !== nm[i + k]).length;
      const wordy = /[aeiouy]/.test(w) && !/[^aeiouy]{5}/.test(w), base = RANK.get(w) || (wordy ? Math.pow(10, 0.55 * w.length) : Math.pow(20, w.length));
      add(i, j, base * (caps === 0 ? 1 : caps === w.length || (caps === 1 && raw[0] !== lc[i]) ? 2 : 2 + caps) * (swaps ? Math.pow(2, swaps) : 1));
    }
  }
  for (const w of TOP) for (let i = lc.indexOf(w); i >= 0; i = lc.indexOf(w, i + 1)) add(i, i + w.length, RANK.get(w));   // the ones with digits in them
  for (let i = 0; i < n; i++) {
    let j = i + 1; while (j < n && lc[j] === lc[i]) j++;                                   // aaaa
    if (j - i >= 3) add(i, j, 12 * (j - i));
    j = i + 1; const d = lc.charCodeAt(j) - lc.charCodeAt(i);                              // abcd, 9876
    if (Math.abs(d) === 1) { while (j + 1 < n && lc.charCodeAt(j + 1) - lc.charCodeAt(j) === d) j++; if (j + 1 - i >= 3) add(i, j + 1, (lc[i] >= '0' && lc[i] <= '9' ? 10 : 26) * (j + 1 - i) * (d < 0 ? 2 : 1)); }
    j = i; let turns = 0; while (j + 1 < n && nextKey(lc[j], lc[j + 1])) { if (j > i && Math.sign(KPOS[lc[j + 1]][1] - KPOS[lc[j]][1]) !== Math.sign(KPOS[lc[j]][1] - KPOS[lc[j - 1]][1])) turns++; j++; }   // qwerty, asdf
    if (j + 1 - i >= 4) add(i, j + 1, 47 * (j + 1 - i) * Math.pow(2, Math.min(turns, 6)));
    if (/^(19|20)\d\d/.test(lc.slice(i))) add(i, i + 4, 120);                              // a year
    for (let len = 2; i + len * 2 <= n; len++) {                                          // the same thing again and again
      const chunk = pw.slice(i, i + len); let k = 1; while (pw.startsWith(chunk, i + len * k)) k++;
      if (k > 1) add(i, i + len * k, guesses(chunk) * k);
    }
  }
  const best = new Array(n + 1).fill(Infinity); best[0] = 1;   // the cheapest way to cover the whole thing
  for (let k = 1; k <= n; k++) {
    const c = lc[k - 1]; best[k] = best[k - 1] * (isL(c) ? 20 : c >= '0' && c <= '9' ? 10 : 30);
    for (const [i, j, g] of M) if (j === k && best[i] * g < best[k]) best[k] = best[i] * g;
  }
  return best[n];
}
// guesses, as powers of ten, onto the five stages: a thousand is a fence, a million a palisade, ten billion a castle
const STEPS = [[0, 0], [3, 0.12], [6, 0.36], [8, 0.62], [10, 0.9], [13, 0.97], [14, 1]];
function strength(pw) {
  if (!pw) return 0;
  const lg = Math.log10(guesses(pw.slice(0, 40)));
  for (let k = 1; k < STEPS.length; k++) if (lg <= STEPS[k][0]) return STEPS[k - 1][1] + (lg - STEPS[k - 1][0]) / (STEPS[k][0] - STEPS[k - 1][0]) * (STEPS[k][1] - STEPS[k - 1][1]);
  return 1;
}
function countFor(s) {
  for (let k = 0; k < 4; k++) {
    if (s <= CUT[k + 1]) return Math.round(ENDS[k] + (s - CUT[k]) / (CUT[k + 1] - CUT[k]) * (ENDS[k + 1] - ENDS[k]));
  }
  return TOTAL;
}
const NAMES = ['WIDE OPEN', 'ROPE FENCE', 'PALISADE', 'WALL + MOAT', 'CASTLE', 'DRAGON'];
function stageOf(s) {   // the stage a score earns, which is where the build ends up once the pieces have landed
  if (s >= 0.97) return 5;
  const n = countFor(s);
  for (let k = 4; k >= 1; k--) if (n >= ENDS[k]) return k;
  return 0;
}
const QMARK = ['.kk.', 'k..k', '...k', '..k.', '..k.', '....', '..k.'];
const BANG = ['.kk.', '.kk.', '.kk.', '.kk.', '....', '.kk.', '....'];

// ───────────────────────── the page it is drawn on ─────────────────────────
// Positions are on the 1080-wide page the card was designed on. A field on a page shows only BOX: the card, the meter and the two lines under it.
const CARD = { x: 240, y: 96, w: 720 }, SCENE_H = GH * PXS, FIELD_H = 88, CARD_H = SCENE_H + FIELD_H, RAD = 26;
const FCY = CARD.y + SCENE_H + FIELD_H / 2, MY = CARD.y + CARD_H + 40, VY = MY + 60;
const INK = '#26221c', PAGE = '#efe8d8', PAPER = '#fffdf6';
const MONO = 'ui-monospace, "SF Mono", Menlo, Consolas, monospace';
const SANS = '-apple-system, "Helvetica Neue", "Segoe UI", sans-serif';
const SEG = ['#dd5a4c', '#e8963a', '#e0bd3c', '#7fb850', '#3f9e6b'];
const BOX = { x: CARD.x - 12, y: CARD.y - 12, w: CARD.w + 24, h: VY + 24 - (CARD.y - 12) };

// ───────────────────────── one field ─────────────────────────
// Everything in here belongs to one field: its clock, its dice, what was typed, its copy of the pieces, its raccoon, knight and
// dragon, and its canvas. ui is what the element made in its shadow root: { root, canvas, input, eye, live, typed() }.
// mode is {} for a field on a page. { demo, film, take, loop } is the scripted take; see film() on the element.
function field(ui, mode) {
  const FILM = !!mode.film, DEMO = FILM || !!mode.demo, LOOP = !!mode.loop;
  const TAKE = mode.take || '';   // '' is the default take; 'chbs' types correct horse battery staple
  const canvas = ui.canvas, ctx = canvas.getContext('2d'), input = ui.input, eyeBtn = ui.eye;
  const rnd = mulberry(4242);
  const pieces = PLAN.map((p) => ({ ...p })), LAYERS = [[], [], [], [], [], [], []], PITR = pieces[PLAN.indexOf(PIT)];
  for (const p of pieces) LAYERS[p.layer].push(p);
  let placeholder = 'choose a password';

  // ───────────────────────── its pieces ─────────────────────────
  function drawPiece(p) {
    if (!p.on) return;
    const u = clamp((T - p.t0) / DROP, 0, 1);
    const x = p.x, w = p.w, h = p.h, y = p.y + (p.dig ? 0 : -Math.round(28 * (1 - u * u)));
    switch (p.kind) {
      case 'stake': rc(x, y, w, h, K.wood); rc(x, y, 1, h, K.woodL); break;
      case 'rope': rc(x, y, w, 1, K.rope); break;
      case 'post': rc(x, y, w, h, K.woodD); break;
      case 'board':
        rc(x, y, w, h, K.woodL); rc(x, y + h - 1, w, 1, K.wood);
        px(x + 1, y + 1, K.ink); px(x + 2, y + 1, K.ink); px(x + 4, y + 1, K.ink); px(x + 5, y + 1, K.ink);
        px(x + 1, y + 3, K.ink); px(x + 3, y + 3, K.ink); px(x + 4, y + 3, K.ink);
        break;
      case 'log': {
        const a = p.gate ? K.gwood : K.wood, l = p.gate ? K.gwoodL : K.woodL, d = p.gate ? K.gwoodD : K.woodD;
        rc(x + 1, y, w - 2, 2, a); px(x + 1, y, l);
        rc(x, y + 2, w, h - 2, a); rc(x, y + 2, 1, h - 2, l); rc(x + w - 1, y + 2, 1, h - 2, d);
        if (p.gate) { rc(x, y + 14, w, 1, K.iron); rc(x, y + 22, w, 1, K.iron); }
        break;
      }
      case 'beam': rc(x, y, w, h, K.woodD); for (let i = x + 2; i < x + w; i += 8) px(i, y, K.woodL); break;
      case 'stone': block(x, y, w, h, p.v, STONE); break;
      case 'kstone': block(x, y, w, h, p.v, KSTONE); break;
      case 'kcap': rc(x, y + 2, w, 2, K.ks0); rc(x, y + 3, w, 1, K.ksD); for (let i = 0; i < w; i += 6) { rc(x + i, y, 4, 2, K.ks2); rc(x + i, y, 4, 1, K.ksL); } break;
      case 'tcap': rc(x, y + 2, w, 2, K.st0); rc(x, y + 3, w, 1, K.stD); for (const i of [0, 5, 10]) { rc(x + i, y, 4, 2, K.st2); rc(x + i, y, 4, 1, K.stL); } break;
      case 'gate':
        rc(x + 2, y, w - 4, 1, K.gate); rc(x + 1, y + 1, w - 2, 1, K.gate); rc(x, y + 2, w, h - 2, K.gate);
        for (let i = x + 2; i < x + w - 1; i += 3) rc(i, y + 2, 1, h - 2, K.ironL);
        for (let j = y + 5; j < y + h; j += 5) rc(x + 1, j, w - 2, 1, K.ironL);
        break;
      case 'window':
        rc(x + 1, y, w - 2, 1, K.glow); rc(x, y + 1, w, h - 1, K.glow); rc(x, y + h - 2, w, 2, K.glowD);
        rc(x + w / 2 - 0.5, y, 1, h, K.gate); rc(x, y + 4, w, 1, K.gate);
        break;
      case 'slit': rc(x, y, w, h, K.gate); break;
      case 'roof':
        for (let r = 0; r < h; r++) {
          const half = Math.max(1, Math.round((r + 1) * w / 2 / h));
          rc(x + w / 2 - half, y + r, half * 2, 1, K.roof);
          px(x + w / 2 - half, y + r, K.roofL); px(x + w / 2 + half - 1, y + r, K.roofD);
        }
        break;
      case 'pole':
        if (p.banner && dragon.state === 'perched') break;   // the dragon is sitting on it
        rc(x, y, 1, h, K.ink);
        for (let i = 0; i < p.fw; i++) {
          const yy = y + (u >= 1 ? Math.round(Math.sin(T * 6 - i * 0.9) * 0.9) : 0);
          rc(x + 1 + i, yy, 1, p.banner ? 4 : 3, i > p.fw - 3 ? p.flagD : p.flag);
        }
        if (p.banner) px(x + 3, y + 1, K.gold);
        break;
      case 'pit': { const hh = Math.round(h * u); rc(x, y, w, hh, K.pit); rc(x, y, 1, hh, K.pitD); rc(x + w - 1, y, 1, hh, K.pitD); if (hh > 1) rc(x, y + hh - 1, w, 1, K.pitD); break; }
      case 'water': {
        const hh = Math.round(h * u), top = y + h - hh;
        rc(x + 1, top, w - 2, hh - 1, K.water);
        if (hh > 1) { rc(x + 1, top, w - 2, 1, K.waterL); px(x + 1 + ((T * 5 + x) | 0) % (w - 2), top, K.white); rc(x + 1, top + hh - 2, w - 2, 1, K.waterD); }
        break;
      }
    }
  }

  // ───────────────────────── state ─────────────────────────
  let T = 0;
  const S = {
    val: '', score: 0, want: 0, builtF: 0, tier: 0, focus: false, show: DEMO, lastKey: -9,
    press: 0, by: 0, vy: 0, pop: 0, verdict: 'nothing to guard yet', verdictT: -9, override: false, common: false,
    attempted: false, celebrate: -1, duckT: -9,
  };
  let on = 0;                       // how many pieces are currently placed
  const falling = [], parts = [], chars = [], fallen = [];
  const chest = { taken: false, t0: -9 };
  const HOME_X = 160, RY = GY - 9;
  const R = { x: HOME_X, y: RY, flip: false, walk: false, dist: 0, out: false, behind: false, carry: false, swim: false, burn: false,
    abortable: false, peek: 0.4, bubble: '', bubT: 0, blink: 0, next: 2 };
  const knight = { x: 70 + OX, dir: 1, t0: -9, hold: 0 };
  const dragon = { state: 'away', x: -40, y: -30, t: 0, sx: 0, sy: 0, amt: 0, fire: 0, blink: 0, next: 3, acc: 0 };
  const PERCH = { x: 72 + OX, y: 4 };
  const arrow = { live: false, stuck: 0, x: 0, y: 0, vx: 0, vy: 0 };
  let ladder = false, bushSmoke = 0, seq = null, smokeAcc = 0;

  // ───────────────────────── stage and verdict ─────────────────────────
  function effTier() {
    if (dragon.state === 'perched') return 5;
    for (let k = 4; k >= 1; k--) if (on >= ENDS[k]) return k;
    return 0;
  }
  function baseVerdict() {
    if (!S.val) return 'nothing to guard yet';
    if (S.common) return "he's seen that one before";
    return ['a raccoon could walk in', 'a rope. he can step over a rope', 'a palisade. he owns a ladder',
      "a moat. he can't swim that well", "a castle. he'll think about it", 'there is a dragon now'][S.tier];
  }
  function say(text, override) {
    if (text === S.verdict) return;
    S.verdict = text; S.verdictT = T; S.override = !!override;
    announce();
  }
  function announce() {   // keeps the screen-reader text in step with the drawn label
    ui.live.textContent = NAMES[S.tier].toLowerCase() + '. ' + S.verdict;
  }

  function setValue(v) {
    const old = S.val;
    if (v === old) return;
    let p = 0;
    while (p < old.length && p < v.length && old[p] === v[p]) p++;
    for (let i = old.length - 1; i >= p; i--) fallen.push({ ch: chars[i].ch, i, y: 0, vy: -120 - rnd() * 80, vx: (rnd() - 0.5) * 120, rot: 0, vr: (rnd() - 0.5) * 9, life: 0 });
    chars.length = p;
    for (let i = p; i < v.length; i++) chars.push({ ch: v[i], born: T + (i - p) * 0.02 });
    const was = S.score;
    S.val = v; S.score = strength(v); S.want = countFor(S.score); S.common = COMMON.has(v.toLowerCase());
    S.lastKey = T; S.press = 1; S.attempted = false; S.override = false;
    if (chest.taken) { chest.taken = false; chest.t0 = T; }
    if (seq && R.abortable) seq = flee();
    say(baseVerdict());
    ui.typed(S.score !== was);   // the element keeps its form value in step, and says so when the score moved
  }

  // ───────────────────────── particles ─────────────────────────
  function part(x, y, vx, vy, g, max, c, fire = 0) {
    if (parts.length < 800) parts.push({ x, y, vx, vy, g, life: 0, max, c, fire });
  }
  function dust(x, y, w) { for (let k = 0; k < 3; k++) part(x + rnd() * w, y, (rnd() - 0.5) * 20, -5 - rnd() * 12, 70, 0.3 + rnd() * 0.2, K.dust); }
  function debris(p) {
    for (let k = 0; k < 5; k++) part(p.x + rnd() * p.w, p.y + rnd() * p.h, (rnd() - 0.5) * 60, -25 - rnd() * 45, 230, 0.45 + rnd() * 0.35, p.cols[k % p.cols.length]);
  }
  function splash(x, y) {
    for (let k = 0; k < 22; k++) part(x + (rnd() - 0.5) * 10, y, (rnd() - 0.5) * 55, -30 - rnd() * 50, 200, 0.45 + rnd() * 0.4, k & 1 ? K.waterL : K.white);
  }

  // ───────────────────────── the raccoon ─────────────────────────
  function* wait(d) { let t = 0; while (t < d) t += yield; }
  function* tween(d, fn) { let t = 0; while (t < d) { t += yield; fn(Math.min(1, t / d)); } }
  function* walkTo(x, speed = 50) {
    const x0 = R.x;
    R.flip = x > x0; R.walk = true;
    yield* tween(Math.abs(x - x0) / speed, (u) => { const nx = lerp(x0, x, u); R.dist += Math.abs(nx - R.x); R.x = nx; });
    R.walk = false;
  }
  function bubble(ch, d) { R.bubble = ch; R.bubT = d; }
  function* goHome(speed) { yield* walkTo(HOME_X, speed); R.out = false; R.carry = false; R.burn = false; R.flip = false; }
  function* flee() {
    R.abortable = false; bubble('!', 0.45);
    yield* wait(0.12);
    yield* goHome(120);
  }
  function* attempt() {
    const t0 = T, tier = effTier(), took = () => (T - t0).toFixed(1);
    R.out = true; R.abortable = true; R.flip = false; R.y = RY;
    if (tier === 5) {
      yield* walkTo(140, 40);
      R.abortable = false;
      yield* wait(0.2); bubble('?', 0.5); yield* wait(0.35);
      dragon.fire = 0.8;
      yield* wait(0.45); bubble('!', 0.45); R.burn = true;
      yield* wait(0.3);
      say("he is on fire. he'll be fine", true);
      yield* goHome(125);
      bushSmoke = 1.8;
    } else if (tier === 4) {
      yield* walkTo(141);
      R.abortable = false; bubble('?', 0.7);
      yield* wait(0.65);
      const ax = knight.x + 4, ay = 42, tx = 138, ty = 77, ft = 0.36, g = 170;
      Object.assign(arrow, { live: true, stuck: 0, x: ax, y: ay, vx: (tx - ax) / ft, vy: (ty - ay - 0.5 * g * ft * ft) / ft });
      knight.hold = 1.2;
      yield* wait(ft); bubble('!', 0.5);
      yield* tween(0.22, (u) => { R.y = RY - 6 * Math.sin(Math.PI * u); });
      R.y = RY;
      say('he went home', true);
      yield* goHome(115);
    } else if (PITR.on) {
      yield* walkTo(138);
      R.abortable = false;
      yield* wait(0.35);
      yield* tween(0.42, (u) => { R.x = lerp(138, 121, u); R.y = RY - 9 * Math.sin(Math.PI * u) + Math.max(0, u - 0.5) * 8; });
      splash(128, WATER); R.swim = true; bubble('!', 0.5);
      say('he fell in the moat', true);
      yield* tween(0.9, (u) => { R.y = WATER - 3 + Math.round(Math.sin(u * 12)); R.flip = u > 0.45; });
      R.swim = false;
      yield* tween(0.36, (u) => { R.x = lerp(121, 138, u); R.y = lerp(WATER - 3, RY, u) - 4 * Math.sin(Math.PI * u); });
      R.y = RY;
      yield* tween(0.5, (u) => { R.x = 138 + ((u * 12 | 0) & 1); if (rnd() < 0.5) part(R.x + rnd() * 14, R.y + 2, (rnd() - 0.5) * 50, -20 - rnd() * 20, 200, 0.35, K.waterL); });
      yield* goHome(34);
    } else if (tier === 2) {
      yield* walkTo(113);
      R.abortable = false; ladder = true;
      yield* wait(0.25);
      yield* tween(0.75, (u) => { R.y = lerp(RY, 40, u); R.dist += 0.3; R.walk = true; });
      yield* tween(0.2, (u) => { R.x = lerp(113, 102, u); });
      R.behind = true; R.walk = false;
      yield* wait(0.6);
      chest.taken = true; R.carry = true; R.behind = false; R.flip = true;
      say(`stolen. the ladder took him ${took()} seconds`, true);
      yield* tween(0.2, (u) => { R.x = lerp(102, 113, u); });
      yield* tween(0.75, (u) => { R.y = lerp(40, RY, u); R.dist += 0.3; R.walk = true; });
      R.y = RY;
      yield* goHome(50);
      ladder = false;
    } else {
      const hop = tier >= 1;
      yield* walkTo(hop ? 102 : 87);
      if (hop) { yield* tween(0.42, (u) => { R.x = lerp(102, 87, u); R.y = RY - 8 * Math.sin(Math.PI * u); }); R.y = RY; }
      R.abortable = false;
      yield* wait(0.25);
      chest.taken = true; R.carry = true; R.flip = true;
      say(`stolen. it took him ${took()} seconds`, true);
      yield* wait(0.15);
      if (hop) { yield* tween(0.42, (u) => { R.x = lerp(87, 102, u); R.y = RY - 8 * Math.sin(Math.PI * u); }); R.y = RY; }
      yield* goHome(50);
    }
  }

  // ───────────────────────── simulation ─────────────────────────
  function simulate(dt) {
    T += dt;
    if (DEMO) demoStep();

    // lay or remove pieces until the build matches the score
    const diff = S.want - S.builtF;
    if (diff !== 0) {
      const rate = Math.max(34, Math.abs(diff) / 0.55);
      S.builtF += Math.sign(diff) * Math.min(Math.abs(diff), rate * dt);
    }
    const tgt = diff >= 0 ? Math.floor(S.builtF + 1e-6) : Math.ceil(S.builtF - 1e-6);
    while (on < tgt) { const p = pieces[on++]; p.on = true; p.t0 = T; falling.push(p); }
    while (on > tgt) { const p = pieces[--on]; p.on = false; debris(p); }
    for (let k = falling.length - 1; k >= 0; k--) {
      const p = falling[k];
      if (!p.on) { falling.splice(k, 1); continue; }
      if (T - p.t0 >= DROP) {
        falling.splice(k, 1);
        if (!p.dig) { dust(p.x, p.y + p.h - 1, p.w); S.vy += 16; }
      }
    }

    // dragon: arrives once the castle is whole and the score is near the top
    const wantDragon = S.score >= 0.97 && on === TOTAL && falling.length === 0;
    dragon.t += dt;
    if (dragon.state === 'away' && wantDragon) { dragon.state = 'arriving'; dragon.t = 0; dragon.sx = -40; dragon.sy = -34; }
    else if ((dragon.state === 'perched' || dragon.state === 'arriving') && S.score < 0.97) { dragon.state = 'leaving'; dragon.t = 0; dragon.sx = dragon.x; dragon.sy = dragon.y; }
    if (dragon.state === 'arriving') {
      const u = Math.min(1, dragon.t / 1.1), e = 1 - (1 - u) ** 3;
      dragon.x = lerp(dragon.sx, PERCH.x, e); dragon.y = lerp(dragon.sy, PERCH.y, e) - 14 * Math.sin(Math.PI * u);
      dragon.amt = u;
      if (u >= 1) { dragon.state = 'perched'; S.vy += 190; S.duckT = T; for (let k = 0; k < 4; k++) dust(76 + OX + k * 7, 26, 6); }
    } else if (dragon.state === 'leaving') {
      const u = Math.min(1, dragon.t / 0.9);
      dragon.x = lerp(dragon.sx, 200, u * u); dragon.y = lerp(dragon.sy, -40, u) - 6 * Math.sin(Math.PI * u);
      dragon.amt = 1 - u;
      if (u >= 1) dragon.state = 'away';
    } else if (dragon.state === 'perched') {
      dragon.x = PERCH.x; dragon.y = PERCH.y; dragon.amt = 1;
      dragon.next -= dt; dragon.blink -= dt;
      if (dragon.next <= 0) { dragon.blink = 0.14; dragon.next = 2 + rnd() * 3; part(dragon.x + 35, dragon.y + 4, 3, -7, 0, 0.9, K.smoke); }
      if (dragon.fire > 0) {
        dragon.fire -= dt; dragon.acc += 260 * dt;
        const mx = dragon.x + 34, my = dragon.y + 8, dx = R.x + 5 - mx, dy = R.y + 4 - my, d = Math.hypot(dx, dy) || 1;
        while (dragon.acc >= 1) {
          dragon.acc--;
          const sp = 135 + rnd() * 45, a = (rnd() - 0.5) * 0.2, ca = Math.cos(a), sa = Math.sin(a);
          part(mx, my, (dx / d * ca - dy / d * sa) * sp, (dx / d * sa + dy / d * ca) * sp, 0, 0.42 + rnd() * 0.22, 0, 2);
        }
      }
    }

    // stage changes
    const tr = effTier();
    if (tr !== S.tier) {
      if (tr > S.tier) { S.celebrate = T + (tr === 5 ? 0 : DROP); S.duckT = T; }
      if (tr >= 4 && S.tier < 4) { knight.t0 = T + DROP; knight.x = 70 + OX; }
      S.tier = tr;
      if (!S.override) say(baseVerdict());
      announce();
    }
    if (S.celebrate >= 0 && T >= S.celebrate) {
      S.celebrate = -1; S.pop = 1; S.vy += 120;
      for (let k = 0; k < 14; k++) part(56 + OX + rnd() * 68, 40 + rnd() * 30, (rnd() - 0.5) * 30, -30 - rnd() * 30, 60, 0.5 + rnd() * 0.4, k & 1 ? K.gold : K.white);
    }

    // card springs
    S.press *= Math.exp(-13 * dt); S.pop *= Math.exp(-6 * dt);
    for (let k = 0; k < 2; k++) { S.vy += (-900 * S.by - 34 * S.vy) * dt / 2; S.by += S.vy * dt / 2; }

    // raccoon
    if (seq) { if (seq.next(dt).done) { seq = null; S.attempted = true; } }
    else if (!S.attempted && S.val && on === S.want && falling.length === 0
      && dragon.state !== 'arriving' && dragon.state !== 'leaving' && T - S.lastKey > (DEMO ? 0.9 : 1.3)
      && !(S.score >= 0.97 && dragon.state !== 'perched')) seq = attempt();
    const peekTo = T - S.duckT < 0.6 ? 0 : S.val || S.focus ? 1 : 0.4;
    R.peek += (peekTo - R.peek) * (1 - Math.exp(-dt * 9));
    R.bubT -= dt; R.next -= dt; R.blink -= dt;
    if (R.next <= 0) { R.blink = 0.12; R.next = 1.6 + rnd() * 3; }
    if (R.burn) for (let k = 0; k < 2; k++) part(R.x + (R.flip ? 1 : 12), R.y + 1, (rnd() - 0.5) * 14, -18 - rnd() * 16, 0, 0.3 + rnd() * 0.2, 0, 1);
    if (bushSmoke > 0) {
      bushSmoke -= dt; smokeAcc += 22 * dt;
      while (smokeAcc >= 1) { smokeAcc--; part(160 + rnd() * 12, 66, (rnd() - 0.5) * 6, -9 - rnd() * 9, 0, 0.9 + rnd() * 0.7, rnd() < 0.5 ? K.smoke : K.smokeD); }
    }
    // knight paces the wall
    if (S.tier >= 4) {
      if (knight.hold > 0) { knight.hold -= dt; knight.dir = 1; }
      else { knight.x += knight.dir * 5 * dt; if (knight.x > 111 + OX) knight.dir = -1; if (knight.x < 62 + OX) knight.dir = 1; }
    }
    if (arrow.live) {
      arrow.vy += 170 * dt; arrow.x += arrow.vx * dt; arrow.y += arrow.vy * dt;
      if (arrow.y >= 77) { arrow.live = false; arrow.stuck = 5; arrow.y = 77; dust(arrow.x, 77, 2); }
    } else if (arrow.stuck > 0) arrow.stuck -= dt;

    for (let k = parts.length - 1; k >= 0; k--) {
      const p = parts[k];
      p.life += dt; p.vy += p.g * dt; p.x += p.vx * dt; p.y += p.vy * dt;
      if (p.life > p.max) parts.splice(k, 1);
    }
    for (let k = fallen.length - 1; k >= 0; k--) {
      const f = fallen[k];
      f.life += dt; f.vy += 1500 * dt; f.y += f.vy * dt; f.x = (f.x || 0) + f.vx * dt; f.rot += f.vr * dt;
      if (f.life > 0.55) fallen.splice(k, 1);
    }
  }

  // ───────────────────────── scene rendering ─────────────────────────
  function renderWorld() {
    fb.set(bg);
    for (const c of CLOUDS) {
      const span = GW + 60, x0 = Math.floor(((c.x + T * c.s) % span + span) % span) - 30;
      for (const [dx, dy, w, h, sh] of CLOUD_SHAPES[c.k]) for (let yy = 0; yy < h; yy++) for (let xx = 0; xx < w; xx++) {
        const X = x0 + dx + xx, Y = c.y + dy + yy;
        if (X >= 0 && X < GW && sky[Y * GW + X]) fb[Y * GW + X] = sh ? K.cloudS : K.cloud;
      }
    }
    for (const p of LAYERS[0]) drawPiece(p);
    if (!chest.taken) {
      const u = clamp((T - chest.t0) / 0.25, 0, 1);
      spr(CHEST, CP, 85 + OX, 71 - Math.round(24 * (1 - u * u)));
      if (((T * 1.3) | 0) % 4 === 0 && u >= 1) px(87 + OX + ((T * 9 | 0) % 6), 72, K.white);
    }
    for (const p of LAYERS[1]) drawPiece(p);
    for (const p of LAYERS[2]) drawPiece(p);
    for (const p of LAYERS[3]) drawPiece(p);
    if (S.tier >= 4 && T >= knight.t0) {
      const rise = clamp((T - knight.t0) / 0.3, 0, 1), y = 40 + Math.round(8 * (1 - rise));
      spr(KNIGHT, KP, knight.x, y, knight.dir < 0, 0, Math.max(0, Math.min(8, 48 - y)));
    }
    for (const p of LAYERS[4]) drawPiece(p);
    for (const p of LAYERS[5]) drawPiece(p);
    for (const p of LAYERS[6]) drawPiece(p);
    if (ladder) {
      rc(122 + OX, 47, 1, 31, K.woodL); rc(125 + OX, 47, 1, 31, K.woodL);
      for (let y = 49; y < 78; y += 3) rc(123 + OX, y, 2, 1, K.wood);
    }
    if (arrow.live) {
      const d = Math.hypot(arrow.vx, arrow.vy) || 1;
      for (let k = 0; k < 5; k++) px(arrow.x - arrow.vx / d * k, arrow.y - arrow.vy / d * k, k ? K.woodD : K.ironL);
    } else if (arrow.stuck > 0) { px(arrow.x, 77, K.woodD); px(arrow.x - 1, 76, K.woodD); px(arrow.x - 2, 75, K.woodD); px(arrow.x - 3, 74, K.red); }

    // raccoon, then his bush in front of him
    if (!R.behind) {
      const rp = R.blink > 0 ? RP_BLINK : RP;
      if (!R.out) spr(RACC_A, rp, HOME_X, RY + 4 - 10 * R.peek, false);
      else if (R.swim) { spr(RACC_A, rp, R.x, R.y, R.flip, 0, 5); rc(Math.round(R.x), WATER, 14, 1, K.waterL); }
      else {
        spr(R.walk && ((R.dist / 4 | 0) & 1) ? RACC_B : RACC_A, rp, R.x, R.y, R.flip);
        if (R.carry) spr(CHEST, CP, R.x + 2, R.y - 6);
        if (R.burn) { const tx = Math.round(R.x) + (R.flip ? 1 : 12); px(tx, R.y, K.f1); px(tx, R.y - 1, K.f0); }
      }
    }
    for (let k = 0; k < bushPix.length; k += 3) fb[bushPix[k + 1] * GW + bushPix[k]] = bushPix[k + 2];

    // dragon
    if (dragon.state !== 'away') {
      const fly = dragon.state !== 'perched';
      const rows = (fly ? (T * 7 | 0) & 1 : (T % 2.7) < 0.16) ? DRAGON_B : DRAGON_A;
      const dp = dragon.blink > 0 ? DP_BLINK : DP, x0 = Math.round(dragon.x), y0 = Math.round(dragon.y);
      for (let r = 0; r < rows.length; r++) {
        const row = rows[r], sway = !fly && r >= 20 ? Math.round(Math.sin(T * 1.8)) : 0;
        for (let c = 0; c < row.length; c++) if (row[c] !== '.') px(x0 + c + (c < 9 ? sway : 0), y0 + r, dp[row[c]]);
      }
    }
    for (const p of parts) {
      if (p.fire) {
        const k = p.life / p.max, c = k < 0.22 ? K.f0 : k < 0.55 ? K.f1 : k < 0.85 ? K.f2 : K.f3;
        if (p.fire === 2 && k < 0.6) rc(p.x, p.y, 2, 2, c); else px(p.x, p.y, c);
      } else px(p.x, p.y, p.c);
    }
    if (R.bubT > 0 && R.out) {
      const bx = Math.round(R.x) + (R.flip ? 6 : 0), by2 = Math.round(R.y) - 13;
      rc(bx, by2, 8, 11, K.ink); rc(bx + 1, by2 + 1, 6, 9, K.bub); px(bx + 3, by2 + 11, K.ink);
      const g = R.bubble === '!' ? BANG : QMARK, c = R.bubble === '!' ? K.red : K.ink;
      for (let r = 0; r < 7; r++) for (let q = 0; q < 4; q++) if (g[r][q] === 'k') px(bx + 2 + q, by2 + 2 + r, c);
    }
  }

  // ───────────────────────── full-res interface ─────────────────────────
  let dpr = 1, cssW = 0, cssH = 0, scale = 1, offX = 0, offY = 0;

  function layout(w) {
    if (DEMO) {   // the scripted take paints the whole page it was made on, to the window
      dpr = FILM ? (window.devicePixelRatio || 1) : Math.min(window.devicePixelRatio || 1, 2);
      cssW = window.innerWidth; cssH = window.innerHeight;
      if (FILM) {
        scale = cssW * 0.86 / CARD.w;
        offX = cssW / 2 - (CARD.x + CARD.w / 2) * scale;
        offY = cssH * 0.555 - (CARD.y + VY) / 2 * scale;
      } else {
        // fit the card itself, so it stays a usable size on a phone
        scale = Math.min(1.25, cssW * 0.94 / CARD.w, cssH * 0.94 / (VY + 24 - CARD.y));
        offX = cssW / 2 - (CARD.x + CARD.w / 2) * scale;
        offY = cssH / 2 - (CARD.y + VY + 14) / 2 * scale;
      }
    } else {      // a field on a page is BOX and nothing else, as wide as the element
      dpr = Math.min(window.devicePixelRatio || 1, 2);
      cssW = w; scale = w / BOX.w; cssH = BOX.h * scale;
      offX = -BOX.x * scale; offY = -BOX.y * scale;
    }
    const pw = Math.round(cssW * dpr), ph = Math.round(cssH * dpr);
    if (canvas.width !== pw || canvas.height !== ph) { canvas.width = pw; canvas.height = ph; }
    // the real controls go over the drawn ones
    const place = (el, x, y, w, h) => Object.assign(el.style, { left: offX + x * scale + 'px', top: offY + y * scale + 'px', width: w * scale + 'px', height: h * scale + 'px' });
    place(input, CARD.x, CARD.y + SCENE_H, CARD.w - 84, FIELD_H);
    place(eyeBtn, CARD.x + CARD.w - 84, CARD.y + SCENE_H, 84, FIELD_H);
  }
  function rr(x, y, w, h, r) {
    ctx.beginPath();
    ctx.moveTo(x + r, y); ctx.arcTo(x + w, y, x + w, y + h, r); ctx.arcTo(x + w, y + h, x, y + h, r);
    ctx.arcTo(x, y + h, x, y, r); ctx.arcTo(x, y, x + w, y, r); ctx.closePath();
  }
  function spaced(v) { if ('letterSpacing' in ctx) ctx.letterSpacing = v + 'px'; }
  function progress() {
    const b = S.builtF;
    for (let k = 0; k < 4; k++) if (b < ENDS[k + 1]) return k + (b - ENDS[k]) / (ENDS[k + 1] - ENDS[k]);
    return 4 + dragon.amt;
  }

  function draw() {
    if (!canvas.width || !canvas.height) return;   // not on a page yet, or hidden
    renderWorld();
    lctx.putImageData(img, 0, 0);
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    if (DEMO) { ctx.fillStyle = PAGE; ctx.fillRect(0, 0, canvas.width, canvas.height); }
    else ctx.clearRect(0, 0, canvas.width, canvas.height);   // a field on a page has no page of its own
    ctx.setTransform(dpr * scale, 0, 0, dpr * scale, dpr * offX, dpr * offY);

    // card: hard shadow stays put, the card sinks toward it on every keystroke
    const cx = CARD.x, cy = CARD.y + 4 * S.press + S.by, cw = CARD.w;
    ctx.fillStyle = INK; rr(cx, CARD.y + 11, cw, CARD_H, RAD); ctx.fill();
    ctx.fillStyle = PAPER; rr(cx, cy, cw, CARD_H, RAD); ctx.fill();
    ctx.save();
    rr(cx, cy, cw, CARD_H, RAD); ctx.clip();
    ctx.imageSmoothingEnabled = false;
    ctx.drawImage(low, cx, cy, cw, SCENE_H);
    ctx.fillStyle = INK; ctx.fillRect(cx, cy + SCENE_H - 1.5, cw, 3);

    // field
    const fy = cy + SCENE_H + FIELD_H / 2, fx = cx + 32;
    ctx.font = `600 32px ${MONO}`; ctx.textBaseline = 'middle'; ctx.textAlign = 'center';
    const room = cw - 32 - 96, adv32 = ctx.measureText('M').width + 3;
    const fs = clamp(32 * (room - 10) / Math.max(1, chars.length * adv32), 26, 32), adv = adv32 * fs / 32;
    const FIELD_FONT = `600 ${fs}px ${MONO}`;
    ctx.font = FIELD_FONT;
    const scroll = Math.max(0, chars.length * adv + 10 - room);
    ctx.save();
    ctx.beginPath(); ctx.rect(cx + 20, cy + SCENE_H + 2, cw - 110, FIELD_H - 2); ctx.clip();
    if (!chars.length && !fallen.length) {
      ctx.textAlign = 'left'; ctx.font = `500 30px ${SANS}`; ctx.fillStyle = '#b5ad9c';
      ctx.fillText(placeholder, fx + (S.focus ? 12 : 0), fy + 1);
      ctx.textAlign = 'center'; ctx.font = FIELD_FONT;
    }
    const glyph = (ch) => {
      if (S.show) ctx.fillText(ch, 0, 1);
      else { ctx.beginPath(); ctx.arc(0, 0, 6.5, 0, Math.PI * 2); ctx.fill(); }
    };
    ctx.fillStyle = INK;
    for (let i = 0; i < chars.length; i++) {
      const age = T - chars[i].born;
      if (age < 0) continue;
      const u = Math.min(1, age / 0.17), s = 1 + 2.2 * (u - 1) ** 3 + 1.2 * (u - 1) ** 2;   // overshoot, then settle
      ctx.save();
      ctx.translate(fx + (i + 0.5) * adv - scroll, fy - 12 * (1 - Math.min(1, age / 0.12)));
      ctx.scale(s, s); glyph(chars[i].ch);
      ctx.restore();
    }
    for (const f of fallen) {
      ctx.save();
      ctx.globalAlpha = 1 - f.life / 0.55;
      ctx.translate(fx + (f.i + 0.5) * adv - scroll + (f.x || 0), fy + f.y); ctx.rotate(f.rot);
      glyph(f.ch);
      ctx.restore();
    }
    if (S.focus && ((T - S.lastKey) % 1.06 < 0.6)) {
      ctx.fillStyle = INK; ctx.fillRect(fx + chars.length * adv - scroll + 2, fy - 19, 3, 38);
    }
    ctx.restore();
    // eye toggle
    const ex = cx + cw - 46;
    ctx.strokeStyle = INK; ctx.lineWidth = 3; ctx.lineCap = 'round'; ctx.lineJoin = 'round';
    ctx.beginPath(); ctx.moveTo(ex - 17, fy); ctx.quadraticCurveTo(ex, fy - 15, ex + 17, fy); ctx.quadraticCurveTo(ex, fy + 15, ex - 17, fy); ctx.closePath(); ctx.stroke();
    ctx.fillStyle = INK; ctx.beginPath(); ctx.arc(ex, fy, 5, 0, Math.PI * 2); ctx.fill();
    if (!S.show) { ctx.strokeStyle = PAPER; ctx.lineWidth = 8; ctx.beginPath(); ctx.moveTo(ex - 14, fy + 13); ctx.lineTo(ex + 14, fy - 13); ctx.stroke(); ctx.strokeStyle = INK; ctx.lineWidth = 3; ctx.stroke(); }
    ctx.restore();
    ctx.strokeStyle = INK; ctx.lineWidth = 3; rr(cx, cy, cw, CARD_H, RAD); ctx.stroke();
    if (S.focus) { ctx.strokeStyle = '#f2b430'; ctx.lineWidth = 3; rr(cx + 9, cy + SCENE_H + 9, cw - 18, FIELD_H - 18, 17); ctx.stroke(); }
    if (!DEMO && ui.root.activeElement === eyeBtn) { ctx.strokeStyle = '#f2b430'; ctx.lineWidth = 3; rr(ex - 28, fy - 26, 56, 52, 14); ctx.stroke(); }

    // meter, stage name and the raccoon's verdict
    const prog = progress();
    for (let k = 0; k < 5; k++) {
      const f = clamp(prog - k, 0, 1), sx = CARD.x + k * 74, pop = k === S.tier - 1 ? 1 + 0.22 * S.pop : 1;
      ctx.save();
      ctx.translate(sx + 33, MY + 9); ctx.scale(pop, pop); ctx.translate(-33, -9);
      ctx.fillStyle = '#dcd3c0'; rr(0, 0, 66, 18, 6); ctx.fill();
      if (f > 0) { ctx.save(); rr(0, 0, 66, 18, 6); ctx.clip(); ctx.fillStyle = SEG[k]; ctx.fillRect(0, 0, 66 * f, 18); ctx.restore(); }
      ctx.strokeStyle = INK; ctx.lineWidth = 2.5; rr(0, 0, 66, 18, 6); ctx.stroke();
      ctx.restore();
    }
    ctx.textBaseline = 'middle'; ctx.textAlign = 'right';
    ctx.font = `700 22px ${MONO}`; spaced(2.5); ctx.fillStyle = INK;
    ctx.fillText(NAMES[S.tier], CARD.x + CARD.w + 2, MY + 10);
    ctx.textAlign = 'left'; ctx.font = `500 22px ${SANS}`; spaced(0.2);
    const va = smooth(0, 0.25, T - S.verdictT);
    ctx.fillStyle = `rgba(104,95,80,${va})`;
    ctx.fillText(S.verdict, CARD.x + 1, VY + 6 * (1 - va));
    spaced(0);

    if (DEMO) drawCursor();
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    if (DEMO) drawCaptions();
  }

  // ───────────────────────── scripted take (?demo=1, ?film=1) ─────────────────────────
  // timings that differ between takes: length, when the opening caption leaves, when the cursor leaves, when the end card arrives
  const TK = TAKE === 'chbs' ? { dur: 14.4, cap: [2.9, 3.4], out: [10.4, 11.3], end: 11.5 } : { dur: 17.8, cap: [5.6, 6.1], out: [13.6, 14.6], end: 14.7 };
  const DUR = TK.dur;
  const demo = { t: 0, t0: 0, i: 0, x: 0, y: 0, clickT: -9, down: false };
  const EV = [];
  (function script() {
    let cur = '', t;
    const type = (str, start, base, wordPause = 0) => {
      t = start;
      for (let i = 0; i < str.length; i++) {
        const next = cur + str.slice(0, i + 1);
        EV.push({ t, fn: () => setValue(next) });
        t += base * (0.72 + 0.56 * (((i * 7919 + str.length * 31) % 13) / 12)) + (str[i] === ' ' || str[i + 1] === ' ' ? wordPause : 0);
      }
      cur += str;
    };
    EV.push({ t: 0.95, fn: () => { S.focus = true; demo.clickT = 0.95; S.lastKey = T; } });
    if (TAKE === 'chbs') type('correct horse battery staple', 1.25, 0.19, 0.07);
    else {
      type('hunter2', 1.25, 0.16);
      for (let i = 1; i <= 7; i++) { const next = 'hunter2'.slice(0, 7 - i); EV.push({ t: 6.3 + i * 0.065, fn: () => setValue(next) }); }
      cur = '';
      type('plum-Otter-47-kayak', 7.3, 0.185);
    }
    EV.sort((a, b) => a.t - b.t);
  })();
  const P0 = { x: CARD.x + 560, y: 1100 }, P1 = { x: CARD.x + 150, y: FCY + 8 }, P2 = { x: CARD.x + 560, y: VY + 4 };
  function demoStep() {
    let tt = T - demo.t0;
    if (LOOP && tt >= DUR) {
      demo.t0 = T; demo.i = 0; tt = 0; demo.clickT = -9;
      setValue(''); S.focus = false; S.verdict = 'nothing to guard yet';
    }
    demo.t = tt;
    while (demo.i < EV.length && EV[demo.i].t <= tt) EV[demo.i++].fn();
    const tr = 0.9 * Math.sin(tt * 6.1) + 0.6 * Math.sin(tt * 11.3 + 1);
    if (tt < 1.15) {
      const u = clamp((tt - 0.15) / 0.75, 0, 1), e = 1 - (1 - u) ** 3;
      demo.x = lerp(P0.x, P1.x, e) - Math.sin(u * Math.PI) * 30; demo.y = lerp(P0.y, P1.y, e);
    } else {
      const u = smooth(1.15, 2.1, tt), out = smooth(TK.out[0], TK.out[1], tt);
      demo.x = lerp(P1.x, P2.x, u) + tr; demo.y = lerp(P1.y, P2.y, u) + tr * 0.7 + 600 * out * out;
    }
    demo.down = tt >= 0.9 && tt < 1.05;
  }
  function drawCursor() {
    const tt = demo.t;
    if (tt < 0.15 || tt > TK.out[1]) return;
    const rp = tt - demo.clickT;
    if (rp >= 0 && rp < 0.45) {
      ctx.strokeStyle = `rgba(38,34,28,${0.5 * (1 - rp / 0.45)})`; ctx.lineWidth = 3;
      ctx.beginPath(); ctx.arc(demo.x, demo.y, 8 + rp * 80, 0, Math.PI * 2); ctx.stroke();
    }
    const s = 1.45 * (demo.down ? 0.88 : 1);
    ctx.save();
    ctx.translate(demo.x, demo.y); ctx.scale(s, s);
    ctx.beginPath();
    ctx.moveTo(0, 0); ctx.lineTo(0, 26); ctx.lineTo(6.5, 20.5); ctx.lineTo(11, 31); ctx.lineTo(15.5, 29);
    ctx.lineTo(11, 18.5); ctx.lineTo(19, 18.5); ctx.closePath();
    ctx.shadowColor = 'rgba(38,34,28,0.35)'; ctx.shadowBlur = 0; ctx.shadowOffsetX = 3 * dpr * scale; ctx.shadowOffsetY = 4 * dpr * scale;
    ctx.fillStyle = '#ffffff'; ctx.fill();
    ctx.shadowColor = 'transparent';
    ctx.strokeStyle = INK; ctx.lineWidth = 2; ctx.lineJoin = 'round'; ctx.stroke();
    ctx.restore();
  }
  function drawCaptions() {
    const tt = demo.t, u = cssW / 1080;
    ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
    const a = smooth(0.15, 0.5, tt) * (1 - smooth(TK.cap[0], TK.cap[1], tt));
    if (a > 0) {
      ctx.font = `600 ${46 * u}px ${SANS}`; spaced(0.3 * u);
      ctx.fillStyle = `rgba(38,34,28,${a})`;
      ctx.fillText('password strength, as a castle', cssW / 2, cssH * 0.115);
    }
    const b = smooth(TK.end, TK.end + 0.5, tt);
    if (b > 0) {
      ctx.font = `700 ${70 * u}px ${MONO}`; spaced(20 * u);
      ctx.fillStyle = `rgba(38,34,28,${b})`;
      ctx.fillText('KEEP', cssW / 2 + 10 * u, cssH * 0.085);
      ctx.font = `500 ${32 * u}px ${SANS}`; spaced(0.3 * u);
      ctx.fillStyle = `rgba(104,95,80,${b})`;
      ctx.fillText('a password field that builds what it is worth', cssW / 2, cssH * 0.158);
    }
    spaced(0);
  }

  // what the element needs of it
  return {
    scripted: DEMO, length: DEMO ? DUR : 0,
    fit(w) { layout(w); draw(); },
    step(dt) { simulate(dt); draw(); },
    type: setValue,
    focus(v) { S.focus = v; if (v) S.lastKey = T; },
    get clock() { return T; },
    get value() { return S.val; },
    get score() { return S.score; },
    get shown() { return S.show; },
    set shown(v) { S.show = v; },
    set placeholder(v) { placeholder = v; },
  };
}

// ───────────────────────── the element ─────────────────────────
// The real controls sit invisibly on top of their drawn versions, so typing, paste, mobile keyboards and screen readers all work the normal way.
// .size gives the element a width of its own where nothing else does, such as in the middle of a flex or grid box. It has no height.
const SHEET = `
:host{display:block;position:relative;max-width:${BOX.w}px;aspect-ratio:${BOX.w}/${BOX.h};-webkit-tap-highlight-color:transparent}
:host([hidden]){display:none}
.size{width:${BOX.w}px;max-width:100%;height:0}
canvas{display:block;position:absolute;left:0;top:0;width:100%;height:100%}
canvas.page{position:fixed;cursor:none}
input,button{position:absolute;opacity:0;margin:0;padding:0;border:0;background:none}
input{font-size:16px;cursor:text;caret-color:transparent}
button{cursor:pointer}
p{position:absolute;width:1px;height:1px;margin:0;overflow:hidden;clip-path:inset(50%);white-space:nowrap}`;
// every field on the page is stepped and painted from one loop
const LIVE = new Set(); let ticking = false, last = 0, paused = false;
function loop(now) { if (!LIVE.size || paused) { ticking = false; return; } const dt = clamp((now - last) / 1000, 0, 0.05); last = now; for (const el of LIVE) el._p.step(dt); requestAnimationFrame(loop); }
function wake() { if (!ticking && LIVE.size && !paused) { ticking = true; last = performance.now(); requestAnimationFrame(loop); } }
addEventListener('resize', () => { for (const el of LIVE) el._fit(); });   // a zoom changes the pixel ratio without always changing the element's width
class KeepField extends HTMLElement {
  static get observedAttributes() { return ['placeholder', 'maxlength', 'autocomplete', 'name']; }
  static get formAssociated() { return true; }   // with a name, what was typed is sent with the form it is in
  static get paused() { return paused; }
  static set paused(v) { paused = !!v; wake(); }   // true stops the clock, so you can step a field yourself with el.advance(seconds)
  constructor() {
    super();
    const root = this.attachShadow({ mode: 'open', delegatesFocus: true });
    root.innerHTML = `<style>${SHEET}</style><div class="size"></div><canvas aria-hidden="true"></canvas>`
      + '<input type="password" maxlength="40" aria-label="Password" aria-describedby="verdict" autocomplete="new-password" autocapitalize="off" autocorrect="off" spellcheck="false">'
      + '<button type="button" aria-label="Show password" aria-pressed="false"></button><p id="verdict" aria-live="polite"></p>';
    const $ = (q) => root.querySelector(q), cv = (this._cv = $('canvas')), inp = (this._in = $('input')), eye = (this._eye = $('button'));
    this._form = this.attachInternals ? this.attachInternals() : null;
    if (this._form) this._form.setFormValue('');
    this._w = 0;   // the width it was last laid out to, in CSS pixels
    this._ui = { root, canvas: cv, input: inp, eye, live: $('p'), typed: (moved) => this._typed(moved) };
    this._make({});
    inp.addEventListener('input', () => this._p.type(inp.value));
    inp.addEventListener('focus', () => this._p.focus(true));
    inp.addEventListener('blur', () => this._p.focus(false));
    inp.addEventListener('keydown', (e) => {
      // the drawn caret always sits at the end, so keep the real one there too
      if (['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'Home', 'End'].includes(e.key)) e.preventDefault();
      else if (e.key === 'Enter' && !e.isComposing && this._form && this._form.form) this._form.form.requestSubmit();   // Enter sends the form, as it does from a plain input
    });
    inp.addEventListener('pointerup', () => requestAnimationFrame(() => { const n = inp.value.length; inp.setSelectionRange(n, n); }));
    eye.addEventListener('click', (e) => {
      if (e.detail > 0) inp.focus();   // a mouse click shouldn't take you out of the field
      this.shown = !this.shown;
    });
    cv.addEventListener('pointerdown', (e) => { if (this._p.scripted) return; e.preventDefault(); inp.focus(); });   // a press anywhere on the picture puts you in the field
    this._ro = new ResizeObserver((e) => this._fit(e[e.length - 1].contentRect.width));
  }
  connectedCallback() { LIVE.add(this); this._ro.observe(this._cv); this._fit(this._cv.clientWidth); wake(); }
  disconnectedCallback() { LIVE.delete(this); this._ro.disconnect(); }
  attributeChangedCallback(name, was, v) {
    const inp = this._in;
    if (name === 'placeholder') this._p.placeholder = v === null ? 'choose a password' : v;
    else if (name === 'maxlength') inp.setAttribute('maxlength', /^\d+$/.test(v || '') ? v : '40');
    else if (name === 'autocomplete') inp.setAttribute('autocomplete', v || 'new-password');
    else if (v === null) inp.removeAttribute('name'); else inp.setAttribute('name', v);
  }
  formResetCallback() { this.value = ''; }
  _make(mode) {   // a fresh field: nothing typed, nothing built
    this._p = field(this._ui, mode);
    if (this.hasAttribute('placeholder')) this._p.placeholder = this.getAttribute('placeholder');
  }
  _fit(w) {   // size the canvas to the element and lay the real input and button over the drawn ones, whenever the element's size changes
    if (w !== undefined) this._w = w;
    if (this._w > 0 || this._p.scripted) this._p.fit(this._w);
  }
  _typed(moved) {   // called by the field whenever what is typed has changed; moved says the score changed with it
    if (this._form) this._form.setFormValue(this._p.value);
    if (moved) this.dispatchEvent(new CustomEvent('keep:change', { bubbles: true, composed: true, detail: { score: this.score, stage: this.stage, stageName: this.stageName } }));
  }
  get value() { return this._p.value; }   // what is typed
  set value(v) { this._in.value = v === null || v === undefined ? '' : v; this._p.type(this._in.value); }
  get score() { return this._p.score; }   // 0 to 1
  get stage() { return stageOf(this._p.score); }   // 0 to 5: the stage that score earns. The drawing gets there as the pieces land.
  get stageName() { return NAMES[this.stage]; }
  get shown() { return this._p.shown; }   // whether the characters are showing; the eye button flips it
  set shown(v) {
    this._p.shown = v = !!v;
    this._eye.setAttribute('aria-pressed', String(v));
    this._eye.setAttribute('aria-label', v ? 'Hide password' : 'Show password');
  }
  get clock() { return this._p.clock; }   // seconds this field's own clock has run
  advance(seconds) { this._p.step(Math.max(0, +seconds || 0)); }   // move this field's clock on and paint it
  // The scripted take the clips were made from. It is for filming and is not part of the field: it turns the element into the page
  // those clips were filmed on. The canvas fills the window and paints the cream page, a caption, a drawn cursor and an end card
  // round the card, and the real input and button are taken away. take is '' (hunter2, then plum-Otter-47-kayak) or 'chbs'
  // (correct horse battery staple). live frames it for watching instead of filming. loop starts it again at the end.
  // Returns the take's length in seconds.
  film(take = '', { live = false, loop = false } = {}) {
    this._in.value = ''; this._in.hidden = this._eye.hidden = true;
    if (this._form) this._form.setFormValue('');
    this._cv.classList.add('page'); this._cv.width = 0;   // a new canvas state, as on a page that has just loaded
    this._make({ demo: true, film: !live, take, loop });
    this._fit();
    return this._p.length;
  }
}
customElements.define('keep-field', KeepField);
})();
