import * as THREE from "/showcase/assets/three.module.js";

const root = document.documentElement;
const id = document.body.dataset.scene;
const canvas = document.querySelector("#scene");
const panel = document.querySelector("#controls");
const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
const still = new URLSearchParams(location.search).has("still");
const spec = JSON.parse(document.querySelector("#spec").textContent);
const state = Object.fromEntries(spec.controls.map((c) => [c.key, c.default]));

const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(42, 1, 0.1, 100);
camera.position.set(0, 0.4, 7);
const group = new THREE.Group();
scene.add(group);
let drag = { x: 0, y: 0, down: false, vx: 0.0025 };

const color = () => new THREE.Color().setHSL(state.hue / 360, 0.7, 0.62);

function disposeGroup() {
  for (const child of [...group.children]) {
    group.remove(child);
    child.geometry?.dispose();
    child.material?.dispose();
  }
}

const builders = {
  orbital() {
    const count = Math.round(state.count);
    const positions = new Float32Array(count * 3);
    const golden = Math.PI * (3 - Math.sqrt(5));
    for (let i = 0; i < count; i++) {
      const y = 1 - (i / (count - 1)) * 2;
      const r = Math.sqrt(1 - y * y);
      const t = golden * i;
      positions.set([Math.cos(t) * r * state.radius, y * state.radius, Math.sin(t) * r * state.radius], i * 3);
    }
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));
    group.add(new THREE.Points(geometry, new THREE.PointsMaterial({ color: color(), size: 0.035, sizeAttenuation: true })));
    for (let k = 0; k < 2; k++) {
      const ring = new THREE.Mesh(new THREE.TorusGeometry(state.radius * (1.28 + k * 0.18), 0.006, 8, 160), new THREE.MeshBasicMaterial({ color: color(), transparent: true, opacity: 0.55 }));
      ring.rotation.set(Math.PI / 2.3 + k * 0.5, k * 0.6, 0);
      group.add(ring);
    }
  },
  waves() {
    const n = Math.round(state.count);
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute("position", new THREE.BufferAttribute(new Float32Array(n * n * 3), 3));
    const points = new THREE.Points(geometry, new THREE.PointsMaterial({ color: color(), size: 0.03 }));
    points.userData.n = n;
    group.add(points);
    group.rotation.x = -0.9;
    updateWaves(0);
  },
  crystal() {
    const detail = Math.round(state.detail);
    const geometry = new THREE.IcosahedronGeometry(state.radius, detail);
    group.add(new THREE.Mesh(geometry, new THREE.MeshStandardMaterial({ color: color(), flatShading: true, roughness: 0.35, metalness: 0.2 })));
    group.add(new THREE.LineSegments(new THREE.EdgesGeometry(geometry), new THREE.LineBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.35 })));
  },
};

const lights = [new THREE.AmbientLight(0xffffff, 0.55), new THREE.DirectionalLight(0xffffff, 2.2)];
lights[1].position.set(3, 4, 5);
lights.forEach((l) => scene.add(l));

function updateWaves(t) {
  const points = group.children[0];
  if (!points || id !== "waves") return;
  const n = points.userData.n;
  const attr = points.geometry.attributes.position;
  const span = 9;
  for (let i = 0; i < n; i++) {
    for (let j = 0; j < n; j++) {
      const x = (i / (n - 1) - 0.5) * span;
      const z = (j / (n - 1) - 0.5) * span;
      const y = Math.sin(x * state.frequency + t) * Math.cos(z * state.frequency * 0.8 + t * 0.7) * state.amplitude;
      attr.setXYZ(i * n + j, x, y, z);
    }
  }
  attr.needsUpdate = true;
}

function rebuild() {
  disposeGroup();
  builders[id]();
}

function resize() {
  const { clientWidth: w, clientHeight: h } = canvas.parentElement;
  renderer.setSize(w, h, false);
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
}

for (const c of spec.controls) {
  const label = document.createElement("label");
  label.className = "ctl";
  label.innerHTML = `<span>${c.label}</span><input type="range" min="${c.min}" max="${c.max}" step="${c.step}" value="${c.default}"><output>${c.default}</output>`;
  const input = label.querySelector("input");
  const out = label.querySelector("output");
  input.addEventListener("input", () => {
    state[c.key] = Number(input.value);
    out.textContent = input.value;
    if (c.key === "hue" || c.key === "count" || c.key === "radius" || c.key === "detail") rebuild();
  });
  panel.append(label);
}

canvas.addEventListener("pointerdown", (e) => { drag.down = true; drag.x = e.clientX; canvas.setPointerCapture(e.pointerId); });
canvas.addEventListener("pointerup", () => { drag.down = false; });
canvas.addEventListener("pointermove", (e) => {
  if (!drag.down) return;
  drag.vx = (e.clientX - drag.x) * 0.0006;
  group.rotation.y += (e.clientX - drag.x) * 0.006;
  drag.x = e.clientX;
});
canvas.addEventListener("keydown", (e) => {
  if (e.key === "ArrowLeft") group.rotation.y -= 0.2;
  if (e.key === "ArrowRight") group.rotation.y += 0.2;
});
addEventListener("resize", resize);

resize();
rebuild();
const clock = new THREE.Clock();
function frame() {
  const t = clock.getElapsedTime() * state.speed;
  if (!reduced && !still && !drag.down) group.rotation.y += 0.002 * state.speed;
  if (id === "waves") updateWaves(reduced || still ? 0 : t);
  renderer.render(scene, camera);
  if (!still) requestAnimationFrame(frame);
}
frame();
root.dataset.ready = "1";
