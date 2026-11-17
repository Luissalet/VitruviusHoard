// Raven: a send button with a raven in it.
// He sits on a branch with the message at his feet. Hover and he stretches his neck and caws. Press and he lifts a wing.
// Let go and he carries the message across the button to the tower window: that flight is the progress.
// When he is in behind the window frame it lights, with him sitting in it, and the button says the message is sent.
// Everything is painted in code at 192 x 40, lit, and crushed to a fixed palette every frame. No assets, no network.
//
// One file, no dependencies. Load it with a script tag and put <raven-send></raven-send> where the button goes.
// A click runs a timed flight. Give it a progress attribute (0 to 1) and it follows a real upload instead.
// It fires "raven:sent" once, when he arrives.
(() => {
'use strict';
function hash(x, y) { let h = (x * 374761393 + y * 668265263) | 0; h = (h ^ (h >>> 13)) * 1274126177 | 0; return ((h ^ (h >>> 16)) >>> 0) / 4294967296; }
function vnoise(x, y) { const xi = Math.floor(x), yi = Math.floor(y), fx = x - xi, fy = y - yi, sx = fx * fx * (3 - 2 * fx), sy = fy * fy * (3 - 2 * fy), l = (a, b, t) => a + (b - a) * t; return l(l(hash(xi, yi), hash(xi + 1, yi), sx), l(hash(xi, yi + 1), hash(xi + 1, yi + 1), sx), sy); }
const clamp = (v, a, b) => (v < a ? a : v > b ? b : v), mix = (a, b, t) => a + (b - a) * t, smooth = (a, b, v) => { const t = clamp((v - a) / (b - a), 0, 1); return t * t * (3 - 2 * t); };

const W = 192, H = 40, FLIGHT = 2.5;   // the button's scene in art pixels, and how long a timed flight takes, in seconds
const PAL = [
  '#04050a', '#101322', '#181c32', '#1e2446', '#243560', '#32497c', '#46639a', '#6f8cc0', '#8eaad2', '#e4ecf6',
  '#332a52', '#3b3a80', '#473a6c', '#62528a', '#8a6aa6',
  '#565a84', '#787ca4', '#a0a2c0', '#c6c4d2', '#8c7e8c',
  '#24160c', '#5e3b0f', '#855714', '#ae7a1c', '#d4a02c', '#f0ca4a', '#fbe88a', '#fffbd4',
  '#7c1e12', '#b8421a', '#e0641e', '#f89a38',
  '#3c3430', '#5a5266', '#6a5c50', '#9c8a70', '#c8b08a', '#ecdcb0',
];
const mk = (w, h) => Object.assign(document.createElement('canvas'), { width: w, height: h });
const soft = mk(W, H), sctx = soft.getContext('2d', { willReadFrequently: true });
let g = sctx;
const POOL = [];
function scratch() { const c = POOL.pop() || mk(W, H), x = c.getContext('2d'); x.setTransform(1, 0, 0, 1, 0, 0); x.globalAlpha = 1; x.globalCompositeOperation = 'source-over'; x.filter = 'none'; x.clearRect(0, 0, W, H); return c; }
const release = (...cs) => { for (const c of cs) if (c) POOL.push(c); };
function layer(draw) { const L = scratch(), prev = g; g = L.getContext('2d'); g.save(); draw(); g.restore(); g = prev; return L; }
const rc = (x, y, w, h, c) => { g.fillStyle = c; g.fillRect(x, y, w, h); };

// ───────── light ─────────
// Every layer is multiplied by the same kind of map: a cold ambient plus whatever is giving light in this frame.
function lit(L, S) {
  const k = L.getContext('2d'), M = scratch(), m = M.getContext('2d');
  m.fillStyle = S.amb; m.fillRect(0, 0, W, H); m.globalCompositeOperation = 'lighter';
  for (const [x, y, r, rgb, a, hard] of S.lights) {
    const s = Math.min(1, a), gr = m.createRadialGradient(x, y, hard ? 0 : 2, x, y, r);
    if (hard) for (const [at, v] of [[0, 1], [0.5, 1], [0.5, 0.45], [1, 0.45], [1, 0]]) gr.addColorStop(at, `rgba(${rgb},${s * v})`);   // two flat rings, for a wall: a soft pool crushes to speckle
    else { gr.addColorStop(0, `rgba(${rgb},${s})`); gr.addColorStop(0.42, `rgba(${rgb},${s * 0.5})`); gr.addColorStop(1, `rgba(${rgb},0)`); }
    m.fillStyle = gr; m.fillRect(0, 0, W, H);
  }
  m.globalCompositeOperation = 'destination-in'; m.drawImage(L, 0, 0);
  k.globalCompositeOperation = 'multiply'; k.drawImage(M, 0, 0); k.globalCompositeOperation = 'source-over'; release(M);
  return L;
}
function rim(L, dx, dy, x, y, r, rgb, a) {
  if (a <= 0) return;
  const k = L.getContext('2d'), R = scratch(), q = R.getContext('2d');
  q.drawImage(L, 0, 0); q.globalCompositeOperation = 'source-in';
  const gr = q.createRadialGradient(x, y, 2, x, y, r); gr.addColorStop(0, `rgba(${rgb},${a})`); gr.addColorStop(0.5, `rgba(${rgb},${a * 0.6})`); gr.addColorStop(1, `rgba(${rgb},0)`);
  q.fillStyle = gr; q.fillRect(0, 0, W, H); q.globalCompositeOperation = 'destination-out'; q.drawImage(L, dx, dy);
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

// ───────── crush: every pixel to the nearest palette colour, with a 4 x 4 ordered dither ─────────
const B4 = [0, 8, 2, 10, 12, 4, 14, 6, 3, 11, 1, 9, 15, 7, 13, 5], SPREAD = 5;
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

// ───────── the raven ─────────
// He is too small to draw, so he is a shape: every pose is placed by hand, a pixel at a time, and nothing is rotated or scaled.
// b body, w the near wing, f the far wing and tail, k bill (as dark as the body, so the outline is what says raven), l legs.
// Each is painted in its daylight colour and the light is put on afterwards.
const INKS = { b: '#2c3050', w: '#404a69', f: '#20233a', k: '#2c3050', l: '#4a4450' };
function spr(rows, x, y, flip, one) {   // (x, y) is where the top left pixel goes; flipped, it is drawn leftward from x
  for (let r = 0; r < rows.length; r++) for (let q = 0, row = rows[r]; q < row.length; q++) if (row[q] !== '.') rc(flip ? x - q : x + q, y + r, 1, 1, one || INKS[row[q]]);
}
const SIT = [   // on the branch, facing right. The feet are in row 17, under column 11.
  '...........bbbbb.......',
  '..........bbbbbbbkkk...',
  '.........bbbbbbbbkkkkk.',
  '.........bbbbbbbbkkkkkk',
  '.........bbbbbbbbkkkk..',
  '.........bbbbbbbbb....',
  '........bbbbbbbbbbb...',
  '.......wbbbbbbbbb.....',
  '......wwwbbbbbbbbb....',
  '.....wwwwwbbbbbbb.....',
  '....wwwwwwwbbbbbbb....',
  '....wwwwwwwwbbbbb.....',
  '...wwwwwwwwwbbbbb.....',
  '...wwwwwwwwwbbbb......',
  '..wwwwwwwwwbbbbb......',
  '..fwwwwww.bbbb........',
  '.ffwwww...l.l.........',
  '.fffw....lllll........',
  'fff...................',
  'ff....................',
];
// his head when something has his attention: the neck stretched two rows, and the same again with the bill open
const UP = [...SIT.slice(0, 5), '.........bbbbbbbb.....', '.........bbbbbbbbb....'];
const CAW = ['...........bbbbb...kkk.', '..........bbbbbbbkkkkk.', '.........bbbbbbbbkkk...', '.........bbbbbbbb......', '.........bbbbbbbbkkkk..', '.........bbbbbbbbkk....', '.........bbbbbbbbb.....'];
const FLY = [   // the body in flight, facing right. Its middle is column 12, row 3. The wings are separate, and go on in front and behind.
  '...............bbbbb......',
  '.......bbbbbbbbbbbbbbkkk..',
  '.ffffbbbbbbbbbbbbbbbbkkkkk',
  'fffffbbbbbbbbbbbbbbbbkkkk.',
  '.ffff.bbbbbbbbbbbbbbbb....',
  '.........bbbbbbbb.bb......',
];
// Four wing poses, stepped between and never blended. In every one the wings are outside the body's outline, so there is always a bird to see.
// Each is [rows, x, y] with x, y measured from the middle of the body.
const WINGS = [
  { near: [['.w..........', '.ww.........', '.www........', '..www.......', '..wwww......', '...wwww.....', '...wwwww....', '....wwwww...', '....wwwwww..', '.....wwwwww.', '.....wwwwww.', '......wwwww.'], -8, -13],   // up: two blades over the back
    far: [['....f.', '...ff.', '...fff', '..ffff', '..ffff', '.ffff.', '.ffff.', 'ffff..', 'ffff..'], -1, -11] },
  { near: [['.wwwwwwww.', '.wwwwwwww.', '..wwwwwww.', '...wwwww..', '....wwww..', '.....ww...'], -3, 1],   // level: one above and one below, as if seen a little from above
    far: [['....ff..', '...fff..', '..ffff..', '.fffff..', '.ffffff.', 'ffffff..'], -2, -8] },
  { near: [['wwwwwwwww.', 'wwwwwwwww.', '.wwwwwwww.', '.wwwwwww..', '..wwwwww..', '..wwwww...', '...wwww...', '...www....', '....w.....'], -2, 2],   // down: two blades under the body, ahead of the feet
    far: [['fffff.', 'fffff.', '.ffff.', '.ffff.', '..fff.', '..ff..', '...f..'], 3, 2] },
  { near: [['ww............', 'wwww..........', '.wwwww........', '..wwwwwww.....', '....wwwwwwww..', '......wwwwwwww', '........wwwwww'], -11, -8],   // coming back up: swept low over the tail
    far: [['ff.....', '.fff...', '..ffff.', '....fff'], -6, -8] },
];
const EYE = '#e4ecf6';
function bird(x, y, pose, carry) {   // (x, y) is the middle of the body
  const wg = WINGS[pose];
  spr(wg.far[0], x + wg.far[1], y + wg.far[2]);
  spr(FLY, x - 12, y - 3);
  if (carry) { rc(x - 6, y + 2, 1, 2, INKS.l); rc(x - 4, y + 2, 1, 2, INKS.l); }
  spr(wg.near[0], x + wg.near[1], y + wg.near[2]);
}
// The message is the thing to watch, so it is drawn after the light, in exact parchment colours. It is 7 by 3: small enough to be held in the feet.
function scroll(x, y) { rc(x + 1, y, 5, 1, '#fffbd4'); rc(x, y + 1, 7, 1, '#ecdcb0'); rc(x + 1, y + 2, 5, 1, '#c8b08a'); rc(x, y + 1, 1, 1, '#c8b08a'); rc(x + 6, y + 1, 1, 1, '#9c8a70'); rc(x + 3, y, 1, 3, '#b8421a'); rc(x + 3, y + 2, 1, 1, '#7c1e12'); }

// ───────── the scene inside the button ─────────
const BY = 26, FEET = 20;                      // the top of the branch, and where he stands on it
const REST = [30, BY - 3];                     // where the message lies until he takes it
const WCX = 167, WCY = 19, WTOP = 8, SILL = 30, TX = 155;   // the tower window, which is the one light, and the tower's left edge
const T0 = 0.1, T1 = 0.76, FLY_Y = 14;         // p: take the message until T0, cross until T1, then in at the window
const WIN = [];                                // the window opening, a row at a time, so its arch is stepped
for (let y = WTOP; y < SILL; y++) { const dy = 17 - (y + 0.5), hw = dy > 0 ? Math.round(Math.sqrt(Math.max(0, 81 - dy * dy))) : 9; WIN.push([WCX - hw, y, hw * 2]); }
// The far side of the opening, row by row. He flies in front of the wall, and whatever of him is past this line has gone inside. Above the arch and below the sill it carries on straight.
const INSIDE = Array.from({ length: H }, (_, y) => { const r = WIN[clamp(y - WTOP, 0, WIN.length - 1)]; return r[0] + r[2]; });
const AMB = 'rgb(120,124,170)', WARM = '255,190,110';
const RAMP = ['#7c1e12', '#b8421a', '#e0641e', '#f89a38', '#f0ca4a', '#fbe88a', '#fffbd4'];
let BACK, TOWER, BRANCH;
function bake() {   // the things that never change, painted once in their own colours
  const still = (draw) => { const c = mk(W, H), prev = g; g = c.getContext('2d'); draw(); g = prev; return c; };
  // The sky and hills are too far off to catch the window, so they get no light: flat palette tones, and a hand-placed dither where the sky pales.
  BACK = still(() => {
    rc(0, 0, W, H, '#46639a');
    for (let y = 15; y < 26; y++) for (let x = 0; x < W; x++) if (bayer(x, y) < (y - 14) / 4) rc(x, y, 1, 1, '#62528a');
    for (const [x, y] of [[52, 5], [70, 9], [88, 4], [107, 10], [126, 5], [140, 12], [62, 13], [118, 14], [38, 4], [146, 3]]) rc(x, y, 1, 1, '#8eaad2');
    for (let x = 0; x < W; x++) { const y = Math.round(23 + 2.2 * Math.sin(x * 0.045 + 1) + 1.3 * Math.sin(x * 0.11)); rc(x, y, 1, H - y, '#3b3a80'); }                  // far hills
    for (let x = 0; x < W; x++) { const y = Math.round(29.5 - 5 * Math.exp(-(((x - 98) / 44) ** 2)) + 0.8 * Math.sin(x * 0.08)); rc(x, y, 1, H - y, '#332a52'); }   // near hill, under the label
  });
  TOWER = still(() => {
    const stone = '#c6c4d2', shade = '#a6a4b8', lite = '#e2e0ea';
    rc(TX, 6, W - TX, H - 6, stone); for (let x = TX; x < W; x += 8) { rc(x, 2, 6, 4, stone); rc(x, 2, 6, 1, lite); }
    rc(TX, 6, 1, H - 6, shade);
    for (let y = 11; y < H; y += 6) { rc(TX, y, W - TX, 1, 'rgba(24,18,44,.3)'); for (let x = TX + (((y / 6) | 0) & 1 ? 4 : 10); x < W; x += 12) rc(x, y - 5, 1, 5, 'rgba(24,18,44,.22)'); }
    for (const [x, y, w] of WIN) rc(x - 2, y - 2, w + 4, 3, shade);                 // the arch stones
    rc(WCX - 12, SILL, 24, 2, lite); rc(WCX - 12, SILL + 2, 24, 1, shade);          // the sill
    g.globalCompositeOperation = 'destination-out'; for (const [x, y, w] of WIN) rc(x, y, w, 1, '#000'); g.globalCompositeOperation = 'source-over';   // the opening
  });
  BRANCH = still(() => {
    const bark = '#8a5a2c', dark = '#6e4420', pale = '#c89858';
    for (let x = 0; x < 51; x++) { const y = BY + (x < 12 ? 1 : 0) - (x > 44 ? 1 : 0), t = x < 10 ? 5 : x < 28 ? 4 : x < 42 ? 3 : 2; rc(x, y, 1, t, bark); rc(x, y, 1, 1, pale); rc(x, y + t - 1, 1, 1, dark); }
    for (let i = 0; i < 8; i++) { rc(42 + i, BY - 1 - i, 1, 2, bark); rc(42 + i, BY - 1 - i, 1, 1, pale); }     // a twig going up
    for (let i = 0; i < 4; i++) rc(46 + i, BY - 6 - (i >> 1), 1, 1, bark);
    rc(51, BY - 1, 2, 1, bark); rc(6, BY - 1, 1, 1, bark); rc(5, BY - 2, 1, 1, bark);                           // a broken end and a stub
  });
}
// Where he is and what his wings are doing, from p and the clock. Returns [x, y, pose, carrying].
function flight(s) {
  const p = s.p, beat = (s.time * 2.7) % 1; let pose = beat < 0.27 ? 0 : beat < 0.45 ? 1 : beat < 0.78 ? 2 : 3, x, y, carry = true;
  const PU = [REST[0] + 9, REST[1] - 4], A = [FEET + 2, BY - 9], B0 = 52, B1 = TX - 13;
  if (p < T0) {   // off the branch: a hop onto the message, then up with it
    const u = p / T0, v = (u % 0.5) / 0.5; carry = u >= 0.5; pose = v < 0.5 ? 0 : 2;
    if (!carry) { x = mix(A[0], PU[0], v); y = mix(A[1], PU[1], v) - 3 * Math.sin(Math.PI * v); } else { x = mix(PU[0], B0, v); y = mix(PU[1], FLY_Y, smooth(0, 1, v)); }
  } else if (p < T1) { x = mix(B0, B1, (p - T0) / (T1 - T0)); y = FLY_Y + (pose === 0 ? 1 : pose === 2 ? -1 : 0); }
  else { const u = (p - T1) / (1 - T1); x = mix(B1, WCX + 20, u); y = mix(FLY_Y, WCY + 1, smooth(0, 0.7, u)); }   // on past the opening, so all of him goes in
  return [Math.round(x), Math.round(y), pose, carry];
}
// One frame of the button, from the state. Returns how far across the label has turned gold.
function scene(s) {
  const time = s.time, p = s.p, sent = s.sent, idle = p <= 0 && !sent;
  const fl = 0.9 + 0.1 * vnoise(time * 8, 3), arrive = sent ? smooth(0, 0.4, s.ta) : 0, flash = sent ? 1 - smooth(0.02, 0.3, s.ta) : 0;
  const steady = Math.round((0.3 + 0.3 * p) * 10) / 10 + (sent && flash <= 0.5 ? 0.3 : 0), lv = (0.3 + 0.3 * p + 0.3 * arrive) * fl;   // the send turns the light up; the wall takes it in steps, so its tones stay flat
  let split = sent ? W : 0;
  g = sctx; g.setTransform(1, 0, 0, 1, 0, 0); g.globalAlpha = 1; g.globalCompositeOperation = 'source-over'; g.clearRect(0, 0, W, H);
  g.drawImage(BACK, 0, 0);
  // inside the window: it glows, so no light is put on it. Two flat tones and a dithered edge that comes down from the arch as it heats.
  const heat = clamp(1.2 + 2.3 * p + 1.3 * arrive, 0, 5.99), lo = RAMP[heat | 0], hi = RAMP[(heat | 0) + 1], edge = WTOP - 2 + (heat % 1) * 26 + (fl - 0.95) * 16;
  for (const [x, y, w] of WIN) { rc(x, y, w, 1, flash > 0.5 ? '#fffbd4' : lo); if (flash <= 0.5) for (let q = x; q < x + w; q++) if (bayer(q, y) > clamp((y - edge) / 5 + 0.5, 0, 1)) rc(q, y, 1, 1, hi); }
  if (sent && flash <= 0.5) { spr(SIT, WCX + 13, SILL - 18, true, '#101322'); rc(WCX - 1, SILL - 16, 1, 1, '#fbe88a'); }   // in, and turned round to look back
  const TW = lit(layer(() => g.drawImage(TOWER, 0, 0)), { amb: AMB, lights: [[WCX, WCY, Math.round(14 + 24 * steady), WARM, steady, true]] }); g.drawImage(TW, 0, 0);
  // He flies in front of the tower and in through the window: the part of him that has passed the far side of the opening is inside, and is not drawn.
  if (!idle && !sent) {
    const [x, y, pose, carry] = flight(s); split = Math.min(x, W);
    const B = layer(() => bird(x, y, pose, carry)); lit(B, { amb: AMB, lights: [] }); rim(B, -1, 0, WCX, WCY, 110, '255,205,140', (0.4 + lv * 0.6) * (1 - smooth(T1 - 0.1, T1, p)));   // in front of the window he is only a dark shape
    const prev = g; g = B.getContext('2d'); g.setTransform(1, 0, 0, 1, 0, 0); g.globalAlpha = 1; g.globalCompositeOperation = 'source-over';
    if (carry) scroll(x - 9, y + 4);
    if (!s.blink) rc(x + 6, y - 1, 1, 1, EYE);
    g.globalCompositeOperation = 'destination-out'; for (let q = 0; q < H; q++) rc(INSIDE[q], q, W - INSIDE[q], 1, '#000'); g.globalCompositeOperation = 'source-over';
    g = prev; g.drawImage(B, 0, 0); release(B);
  }
  const up = idle && (s.ready || s.look > 0), caw = up && !s.ready && (s.look % 0.38) > 0.06 && (s.look % 0.38) < 0.24 && s.look < 0.76;
  const PL = layer(() => {
    g.drawImage(BRANCH, 0, 0);
    if (!idle) return;
    const x = FEET - 11, y = BY - 18, wg = WINGS[0].near;
    if (up) { spr(caw ? CAW : UP, x, y - 2); spr(SIT.slice(5), x, y + 5); } else spr(SIT, x, y);
    if (s.ready) spr(wg[0], FEET - 6 + wg[1], BY - 9 + wg[2]);   // one wing lifted, ready to go
  });
  lit(PL, { amb: AMB, lights: [] }); rim(PL, -1, 0, WCX, WCY, 230, '255,205,140', 0.3 + lv * 0.4); g.drawImage(PL, 0, 0);
  release(TW, PL);
  if (idle || (p < T0 * 0.5 && !sent)) scroll(REST[0], REST[1]);
  if (idle && !s.blink) rc(FEET + 3, BY - 16 - (up ? 2 : 0), 1, 1, EYE);
  return split;
}

// ───────── the button: an ink capsule with stepped ends and a hard shadow, around the scene ─────────
const INK = '#26221c', CW = W + 4, CH = H + 4, SH = 4, cap = mk(CW, CH + SH), cctx = cap.getContext('2d');
const SPAN = [0, 2].map((inset) => Array.from({ length: CH }, (_, y) => { if (y < inset || y >= CH - inset) return null; const r = CH / 2, rr = r - inset, dy = y + 0.5 - r, dx = Math.sqrt(Math.max(0, rr * rr - dy * dy)), x0 = Math.round(r - dx); return [x0, Math.round(CW - r + dx) - x0]; }));
function capsule(down, col) {
  const oy = down ? SH : 0; cctx.clearRect(0, 0, CW, CH + SH); cctx.fillStyle = col;
  for (let y = 0; y < CH; y++) { const a = SPAN[0][y]; cctx.fillRect(a[0], y + oy, a[1], 1); if (!down) cctx.fillRect(a[0], y + SH, a[1], 1); }
  for (let y = 2; y < CH - 2; y++) { const a = SPAN[1][y]; if (a && a[1] > 0) cctx.drawImage(art, a[0] - 2, y - 2, a[1], 1, a[0], y + oy, a[1], 1); }
}

// ───────── the element ─────────
const SHEET = `
:host{display:inline-block;position:relative;vertical-align:middle;font:15px/1.45 -apple-system,"Helvetica Neue","Segoe UI",sans-serif}
:host([hidden]){display:none}
canvas{display:block;position:absolute;left:0;top:0;image-rendering:pixelated;pointer-events:none}
button{position:relative;display:block;width:294px;height:66px;margin:0 0 6px;padding:0;border:0;background:none;font:inherit;color:transparent;cursor:pointer;outline:none;user-select:none;-webkit-user-select:none;touch-action:manipulation;-webkit-touch-callout:none;-webkit-tap-highlight-color:transparent}
button[aria-disabled="true"]{cursor:default}
.say{position:absolute;width:1px;height:1px;overflow:hidden;clip-path:inset(50%);white-space:nowrap}`;
// every button on the page is painted from one loop, with the same scratch canvases
const LIVE = new Set(); let ticking = false, last = 0, baked = false, paused = false;
function loop(now) { if (!LIVE.size || paused) { ticking = false; return; } const dt = last < 0 ? 0 : clamp((now - last) / 1000, 0, 0.05); last = now; for (const el of LIVE) el.advance(dt); requestAnimationFrame(loop); }
function wake() { if (!ticking && LIVE.size && !paused) { ticking = true; last = -1; requestAnimationFrame(loop); } }
class RavenSend extends HTMLElement {
  static get observedAttributes() { return ['label', 'sent-label', 'progress']; }
  static get paused() { return paused; }                 // set true to stop the clock and step it yourself with el.advance(seconds)
  static set paused(v) { paused = !!v; wake(); }
  constructor() {
    super();
    // The words stay in the page for layout and for screen readers. Everything you see is drawn in art pixels.
    const root = this.attachShadow({ mode: 'open', delegatesFocus: true });
    root.innerHTML = `<style>${SHEET}</style><button type="button"><canvas aria-hidden="true"></canvas><span></span></button><span class="say" role="status"></span>`;
    this._btn = root.querySelector('button'); this._face = root.querySelector('canvas'); this._l = root.querySelector('button span'); this._say = root.querySelector('.say');
    this._face.width = CW * 3; this._face.height = (CH + SH) * 3; this._face.style.width = CW * 1.5 + 'px'; this._face.style.height = (CH + SH) * 1.5 + 'px';
    this._s = { time: LIVE.size * 1.37, p: 0, target: 0, flying: false, sent: false, ta: 0, look: 0, ready: false, press: 0, blink: false };
    this.input = { hover: false, down: false, focus: false };   // what the pointer and keys are doing; a script can set these too
    this._wasDown = false; this._want = null;
    const b = this._btn, drop = () => { this.input.down = false; this._wasDown = false; };   // let go without sending
    b.addEventListener('pointerenter', () => { this.input.hover = true; });
    b.addEventListener('pointerleave', () => { this.input.hover = false; drop(); });
    b.addEventListener('pointerdown', (e) => { if (e.button === 0) this.input.down = true; });
    b.addEventListener('pointercancel', drop);
    b.addEventListener('keydown', (e) => { this.input.focus = b.matches(':focus-visible'); if ((e.key === ' ' || e.key === 'Enter') && !e.repeat) this.input.down = true; });
    b.addEventListener('focus', () => { this.input.focus = b.matches(':focus-visible'); });
    b.addEventListener('blur', () => { this.input.focus = false; drop(); });
    b.addEventListener('click', () => { drop(); this._go(); });   // a mouse, a finger, Space, Enter and assistive tech all arrive here
  }
  connectedCallback() { if (!baked) { bake(); baked = true; } this._words(); LIVE.add(this); this._render(); wake(); }
  disconnectedCallback() { LIVE.delete(this); }
  attributeChangedCallback(name, _, v) {
    if (name === 'progress') this._want = v === null ? null : clamp(parseFloat(v) || 0, 0, 1);   // with this set it follows the page, and does not run its own timer
    else this._words();
  }
  _words() {   // what it says now, from the attributes
    const s = this._s, word = s.sent ? this.getAttribute('sent-label') || 'Sent' : this.getAttribute('label') || 'Send';
    if (this._l.textContent !== word) this._l.textContent = word;
    this._say.textContent = s.sent ? word : '';
    this._btn.setAttribute('aria-disabled', s.sent ? 'true' : 'false'); this._btn.setAttribute('aria-busy', !s.sent && s.p > 0 ? 'true' : 'false');
  }
  _go() {   // start a timed flight, unless one is under way, it has been sent, or the page is driving it
    const s = this._s; if (s.sent || s.flying || this._want !== null) return;
    s.flying = true; s.press = 0.12;
  }
  reset() { Object.assign(this._s, { p: 0, target: 0, flying: false, sent: false, ta: 0, press: 0 }); if (this._want !== null) this._want = 0; this._words(); if (paused) this._render(); }   // put it back
  get progress() { return this._s.p; }   // 0 to 1, how far he has flown
  get sent() { return this._s.sent; }    // true once it has fired
  advance(dt) {
    const s = this._s, inp = this.input, was = s.p;
    s.time += dt;
    if (this._wasDown && !inp.down) this._go();   // a script pressed it and let go
    this._wasDown = inp.down;
    if (!s.sent) {
      if (this._want !== null) { s.flying = false; s.target = this._want; s.p += clamp(s.target - s.p, -dt * 3, dt * 1.6); }   // a jump in progress is flown, not teleported
      else if (s.flying) { const d = parseFloat(this.getAttribute('duration')); s.p = s.target = Math.min(1, s.target + dt / (d > 0 ? d : FLIGHT)); }
      if (s.p >= 1) { s.p = 1; s.sent = true; s.flying = false; s.ta = 0; this._words(); this.dispatchEvent(new CustomEvent('raven:sent', { bubbles: true, composed: true })); }
      else if ((was > 0) !== (s.p > 0)) this._words();
    } else s.ta += dt;
    s.press = Math.max(0, s.press - dt);
    const idle = s.p <= 0 && !s.sent;
    s.ready = idle && inp.down;
    s.look = idle && (inp.hover || inp.focus || inp.down) ? s.look + dt : 0;   // how long something has had his attention
    s.blink = (s.time % 3.7) > 3.57;
    this._render();
  }
  _render() {
    const s = this._s, inp = this.input;
    const split = scene(s); crush();
    // the label, in the art: pale to begin with, gold where he has flown over it
    const label = this._l.textContent, lx = 99 - Math.round(ptextW(label, 1) / 2), ly = 27;
    g = actx; ptext(label, lx + 1, ly + 1, '#101322', 1); ptext2(label, lx, ly, split, '#fbe88a', '#e4ecf6', W, H); g = sctx;
    const settled = s.sent && s.ta > 0.3;
    capsule(settled || s.press > 0 || (inp.down && s.p <= 0 && !s.sent), inp.focus ? '#f0ca4a' : settled ? '#6a5642' : INK);
    const v = this._face.getContext('2d'); v.imageSmoothingEnabled = false; v.clearRect(0, 0, this._face.width, this._face.height); v.drawImage(cap, 0, 0, this._face.width, this._face.height);
  }
}
customElements.define('raven-send', RavenSend);
})();
