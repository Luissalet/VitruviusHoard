import * as THREE from "./assets/three.module.js";
import { createBook } from "./book.js";

const id = document.body.dataset.recipe;
const canvas = document.querySelector("#scene");
const content = document.querySelector("#content");
const controls = document.querySelector("#controls");
const feedback = document.querySelector("#feedback");
const reduced = matchMedia("(prefers-reduced-motion: reduce)");
const still = new URLSearchParams(location.search).has("still");
const state = {
  recipe: id,
  ready: false,
  renderer: "webgl",
  selection: 0,
  frames: 0,
};
window.showcaseState = state;

const projects = [
  {
    name: "Arco",
    material: "Cerámica y volumen",
    text: "Estudio de una pieza cerámica. Luz lateral cálida, borde grueso y acabado mate.",
    color: "#e5c7a4",
    href: "../book/index.html#arco",
  },
  {
    name: "Retrato",
    material: "Fotografía y luz",
    text: "Retrato convertido en un campo de líneas. Acércate para leer su superficie.",
    color: "#b8d1c4",
    href: "../glitch/index.html",
  },
  {
    name: "Materia",
    material: "Metal y piedra",
    text: "Un anillo de demostración sobre basalto. La cámara y la luz siguen el recorrido.",
    color: "#afb6cb",
    href: "../rock/index.html",
  },
];

function detail(index) {
  state.selection = index;
  document.querySelector(".project-detail")?.remove();
  const project = projects[index];
  const panel = document.createElement("article");
  panel.className = "project-detail";
  panel.innerHTML = `<button aria-label="Cerrar detalle">Cerrar</button><h2>${project.name}</h2><p>${project.text}</p><a href="${project.href}">Abrir proyecto</a>`;
  panel.querySelector("button").onclick = () => panel.remove();
  content.append(panel);
  feedback.textContent = project.name + " seleccionado";
  document
    .querySelectorAll("[data-project]")
    .forEach((link) =>
      link.setAttribute(
        "aria-current",
        String(Number(link.dataset.project) === index),
      ),
    );
}

function links() {
  const nav = document.createElement("nav");
  nav.className = "project-links";
  nav.setAttribute("aria-label", "Proyectos de demostración");
  nav.innerHTML = projects
    .map(
      (p, i) =>
        `<a href="#${p.name.toLowerCase()}" data-project="${i}">${p.name}</a>`,
    )
    .join("");
  nav.addEventListener("click", (event) => {
    const link = event.target.closest("[data-project]");
    if (!link) return;
    event.preventDefault();
    detail(Number(link.dataset.project));
  });
  return nav;
}

if (id === "book") {
  canvas.remove();
  state.renderer = "css-3d";
  createBook(content, controls, reduced, state);
  state.ready = true;
} else {
  try {
    await start();
  } catch (error) {
    document.body.classList.add("fallback");
    state.renderer = "fallback";
    state.error = String(error);
    content.innerHTML = `<h1>${document.title.split(" · ")[0]}</h1><p>La escena 3D necesita WebGL. Puedes recorrer los proyectos mediante sus enlaces y descargar el código de la referencia.</p><img src="../assets/portrait.jpg" alt="Retrato del estudio fotográfico">`;
    controls.replaceChildren(links());
    state.ready = true;
  }
}

async function start() {
  await document.fonts.ready;
  const renderer = new THREE.WebGLRenderer({
    canvas,
    antialias: true,
    alpha: false,
    preserveDrawingBuffer: true,
  });
  renderer.setPixelRatio(Math.min(devicePixelRatio, 1.75));
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.1;
  const scene = new THREE.Scene();
  scene.background = new THREE.Color("#101713");
  const camera = new THREE.PerspectiveCamera(42, 1, 0.1, 160);
  const pointer = new THREE.Vector2();
  const smoothPointer = new THREE.Vector2();
  const raycaster = new THREE.Raycaster();
  const targets = [];
  let frame = 0;
  let remaining = 0;
  let previousTime = 0;
  let update = () => {};
  let disposeScene = () => {};

  function invalidate(count = 35) {
    remaining = Math.max(remaining, count);
    if (!frame && !document.hidden) frame = requestAnimationFrame(render);
  }

  function render(time) {
    frame = 0;
    if (document.hidden) return;
    const dt = Math.min(0.05, Math.max(0.016, (time - previousTime) / 1000));
    previousTime = time;
    smoothPointer.lerp(
      pointer,
      reduced.matches || still ? 1 : 1 - Math.exp(-10 * dt),
    );
    update(dt, smoothPointer);
    renderer.render(scene, camera);
    state.frames += 1;
    remaining -= 1;
    if (remaining > 0) frame = requestAnimationFrame(render);
  }

  function mesh(geometry, material, x, y, z) {
    const object = new THREE.Mesh(geometry, material);
    object.position.set(x, y, z);
    object.castShadow = true;
    object.receiveShadow = true;
    scene.add(object);
    return object;
  }

  function box(width, height, depth, color, x, y, z) {
    return mesh(
      new THREE.BoxGeometry(width, height, depth),
      new THREE.MeshStandardMaterial({ color, roughness: 0.78 }),
      x,
      y,
      z,
    );
  }

  function spot(color, power, x, y, z, tx, ty, tz, angle = 0.5) {
    const light = new THREE.SpotLight(color, power, 90, angle, 0.65, 1.4);
    light.position.set(x, y, z);
    light.target.position.set(tx, ty, tz);
    light.castShadow = true;
    light.shadow.mapSize.set(1024, 1024);
    light.shadow.bias = -0.0003;
    scene.add(light, light.target);
    return light;
  }

  function hit(event) {
    const bounds = canvas.getBoundingClientRect();
    raycaster.setFromCamera(
      new THREE.Vector2(
        ((event.clientX - bounds.left) / bounds.width) * 2 - 1,
        (-(event.clientY - bounds.top) / bounds.height) * 2 + 1,
      ),
      camera,
    );
    const found = raycaster.intersectObjects(targets, false)[0];
    if (found) detail(found.object.userData.project);
  }

  canvas.addEventListener("pointermove", (event) => {
    const bounds = canvas.getBoundingClientRect();
    pointer.set(
      ((event.clientX - bounds.left) / bounds.width) * 2 - 1,
      (-(event.clientY - bounds.top) / bounds.height) * 2 + 1,
    );
    state.pointer = [pointer.x, pointer.y];
    invalidate();
  });
  canvas.addEventListener("pointerleave", () => {
    pointer.set(0, 0);
    invalidate();
  });
  let down;
  let lastPointer;
  let dragged = false;
  canvas.addEventListener("pointerdown", (event) => {
    down = [event.clientX, event.clientY];
    lastPointer = down;
    dragged = false;
    if (id === "gallery") canvas.setPointerCapture(event.pointerId);
  });
  canvas.addEventListener("pointerup", (event) => {
    if (
      !dragged &&
      down &&
      Math.hypot(event.clientX - down[0], event.clientY - down[1]) < 8
    )
      hit(event);
    if (canvas.hasPointerCapture(event.pointerId))
      canvas.releasePointerCapture(event.pointerId);
    down = null;
    lastPointer = null;
  });
  canvas.addEventListener("pointercancel", () => {
    down = null;
    lastPointer = null;
    dragged = false;
  });

  if (id === "glitch") {
    const texture = await new THREE.TextureLoader().loadAsync(
      "../assets/portrait.jpg",
    );
    texture.colorSpace = THREE.SRGBColorSpace;
    const uniforms = {
      portrait: { value: texture },
      pointer: { value: new THREE.Vector2() },
      strength: { value: 0.7 },
      aspect: { value: 1 },
    };
    const material = new THREE.ShaderMaterial({
      uniforms,
      vertexShader: `
        varying vec2 uv0;
        uniform sampler2D portrait;
        uniform vec2 pointer;
        uniform float strength;
        void main(){
          uv0=uv;
          vec3 p=position;
          float light=dot(texture2D(portrait,uv).rgb,vec3(.299,.587,.114));
          float nearPointer=exp(-9.*distance(uv,pointer*.5+.5));
          float band=sin(floor(uv.y*74.)*.83+pointer.x*8.);
          p.z+=(light-.35)*.48+nearPointer*strength*.25;
          p.x+=step(.65,band)*nearPointer*strength*.12;
          gl_Position=projectionMatrix*modelViewMatrix*vec4(p,1.);
        }`,
      fragmentShader: `
        varying vec2 uv0;
        uniform sampler2D portrait;
        uniform vec2 pointer;
        uniform float strength;
        void main(){
          float influence=exp(-7.*distance(uv0,pointer*.5+.5));
          float row=floor(uv0.y*74.);
          float shift=step(.64,sin(row*.83+pointer.x*8.))*influence*.035*strength;
          vec2 sampleUV=uv0+vec2(shift,0.);
          float l=dot(texture2D(portrait,sampleUV).rgb,vec3(.299,.587,.114));
          float r=texture2D(portrait,sampleUV+vec2(.012*influence*strength,0.)).r;
          vec2 grid=abs(fract(uv0*vec2(100.,74.))-.5);
          float line=1.-smoothstep(.025,.07,min(grid.x,grid.y));
          float silhouette=smoothstep(.15,.55,l);
          vec3 ink=mix(vec3(.025,.055,.042),vec3(.68,.92,.75),silhouette);
          ink=mix(ink*.52,ink,line*.8+.25);
          ink.r+=max(0.,r-l)*influence*.8;
          gl_FragColor=vec4(ink,1.);
        }`,
    });
    const portrait = mesh(
      new THREE.PlaneGeometry(3.05, 3.6, 160, 150),
      material,
      0.65,
      -0.02,
      0,
    );
    const grid = new THREE.GridHelper(14, 36, "#7d9c87", "#314b39");
    grid.rotation.x = Math.PI / 2;
    grid.position.z = -0.5;
    scene.add(grid);
    camera.position.set(0, 0, 5.5);
    content.innerHTML =
      '<h1 class="glitch-title">Estudio del retrato</h1><p class="glitch-copy">Fotografía, desplazamiento y rejilla.<br>Mueve el puntero sobre el rostro.</p>';
    controls.innerHTML =
      '<label>Deformación <input id="strength" type="range" min="0" max="1.5" step="0.05" value="0.7"></label><button id="reset">Centrar retrato</button>';
    controls.querySelector("#strength").oninput = (event) => {
      uniforms.strength.value = Number(event.target.value);
      state.strength = uniforms.strength.value;
      invalidate();
    };
    controls.querySelector("#reset").onclick = () => {
      pointer.set(0, 0);
      invalidate();
    };
    update = () => {
      uniforms.pointer.value.copy(
        reduced.matches || still ? new THREE.Vector2() : smoothPointer,
      );
      portrait.rotation.y =
        (reduced.matches || still ? 0 : smoothPointer.x) * 0.13;
      portrait.position.x = innerWidth < 700 ? 0 : 0.65;
      portrait.scale.setScalar(innerWidth < 700 ? 0.78 : 1);
      camera.position.z = innerWidth < 700 ? 5.9 : 5.5;
      state.deformation = uniforms.pointer.value.x;
    };
  }

  if (id === "gallery") {
    canvas.style.touchAction = "none";
    scene.background = new THREE.Color("#161a18");
    scene.fog = new THREE.Fog("#161a18", 18, 42);
    scene.add(new THREE.HemisphereLight("#bbc9bd", "#151914", 1.2));
    const floor = box(28, 0.15, 42, "#454a44", 0, -0.1, -9);
    floor.material.roughness = 0.3;
    box(0.3, 8, 42, "#242a24", -10, 4, -9);
    box(0.3, 8, 42, "#242a24", 10, 4, -9);
    box(20, 8, 0.4, "#252b26", 0, 4, -28);
    for (let i = -5; i <= 5; i++)
      box(0.025, 0.008, 42, "#262e28", i * 2, 0, -9);
    for (let i = -13; i <= 4; i++)
      box(20, 0.008, 0.025, "#262e28", 0, 0, i * 2);
    let travel = 0;
    let desiredTravel = 0;
    let desiredX = 0;
    let cameraX = 0;
    const look = new THREE.Vector3(0, 2.4, -12);
    const portraitImage = await new THREE.ImageLoader().loadAsync(
      "../assets/portrait.jpg",
    );
    for (let i = 0; i < 3; i++) {
      const x = (i - 1) * 5.4;
      const z = i === 1 ? -12 : -10;
      const panel = box(4.7, 3.3, 0.14, "#222620", x, 2.9, z);
      const surface = document.createElement("canvas");
      surface.width = 1024;
      surface.height = 720;
      const ctx = surface.getContext("2d");
      ctx.fillStyle = projects[i].color;
      ctx.fillRect(0, 0, 1024, 720);
      ctx.fillStyle = "#28362e";
      ctx.font = "88px Instrument";
      ctx.fillText(projects[i].name, 70, 130);
      ctx.font = "30px Barlow";
      ctx.fillText(projects[i].material, 74, 188);
      if (i === 1) {
        ctx.drawImage(portraitImage, 490, 230, 420, 430);
      } else {
        const glaze = ctx.createLinearGradient(480, 250, 800, 620);
        glaze.addColorStop(0, i === 0 ? "#809779" : "#f0d8a6");
        glaze.addColorStop(0.45, i === 0 ? "#3b5b41" : "#574b2c");
        glaze.addColorStop(0.8, i === 0 ? "#9bab8c" : "#e8d6af");
        glaze.addColorStop(1, i === 0 ? "#3f4e35" : "#77623d");
        ctx.lineWidth = i === 0 ? 80 : 44;
        ctx.strokeStyle = glaze;
        ctx.shadowColor = "#263c3466";
        ctx.shadowBlur = 22;
        ctx.shadowOffsetY = 25;
        ctx.beginPath();
        ctx.ellipse(
          660,
          440,
          130,
          i === 0 ? 150 : 170,
          i === 0 ? -0.6 : 0.3,
          0,
          Math.PI * 2,
        );
        ctx.stroke();
        ctx.shadowColor = "transparent";
        if (i === 2) {
          ctx.fillStyle = "#397e72";
          ctx.beginPath();
          ctx.ellipse(710, 280, 55, 48, 0.3, 0, Math.PI * 2);
          ctx.fill();
        }
      }
      ctx.fillStyle = "#18261d";
      ctx.font = "24px Barlow";
      ctx.fillText("Abrir estudio", 74, 645);
      const texture = new THREE.CanvasTexture(surface);
      texture.colorSpace = THREE.SRGBColorSpace;
      const artwork = mesh(
        new THREE.PlaneGeometry(4.5, 3.16),
        new THREE.MeshBasicMaterial({ map: texture, toneMapped: false }),
        x,
        2.9,
        z + 0.085,
      );
      artwork.userData.project = i;
      targets.push(artwork);
      box(3.4, 0.38, 1, "#292e29", x, 0.2, z + 1.5);
      spot("#e5eedc", 150, x, 6.8, z + 2, x, 2.9, z, 0.56);
      const trim = box(4.4, 0.04, 0.07, "#e8eedb", x, 5.1, z + 0.25);
      trim.material = new THREE.MeshBasicMaterial({ color: "#d8e4ca" });
      panel.castShadow = false;
    }
    content.innerHTML =
      '<div class="scene-copy"><h1>Sala de estudios</h1><p>Camina entre tres paneles.<br>Selecciona una pieza para abrirla.</p></div>';
    controls.innerHTML =
      '<button id="backward">Retroceder</button><button id="forward">Avanzar</button><button id="home">Volver a la entrada</button>';
    controls.append(links());
    function move(delta) {
      desiredTravel = THREE.MathUtils.clamp(desiredTravel + delta, 0, 10);
      invalidate(65);
    }
    controls.querySelector("#forward").onclick = () => move(2);
    controls.querySelector("#backward").onclick = () => move(-2);
    controls.querySelector("#home").onclick = () => {
      desiredTravel = 0;
      desiredX = 0;
      invalidate(65);
    };
    controls
      .querySelector(".project-links")
      .addEventListener("click", (event) => {
        const link = event.target.closest("[data-project]");
        if (link) {
          desiredX = (Number(link.dataset.project) - 1) * 5.4;
          invalidate(65);
        }
      });
    canvas.addEventListener(
      "wheel",
      (event) => {
        event.preventDefault();
        move(event.deltaY * 0.008);
      },
      { passive: false },
    );
    window.addEventListener("keydown", (event) => {
      if (["ArrowUp", "ArrowDown", "w", "s"].includes(event.key)) {
        event.preventDefault();
        move(["ArrowUp", "w"].includes(event.key) ? 1 : -1);
      }
    });
    canvas.addEventListener("pointermove", (event) => {
      if (down && event.pointerType === "touch") {
        move((lastPointer[1] - event.clientY) * 0.025);
        desiredX = THREE.MathUtils.clamp(
          desiredX + (lastPointer[0] - event.clientX) * 0.025,
          -6,
          6,
        );
      }
      if (down) {
        dragged =
          dragged ||
          Math.hypot(event.clientX - down[0], event.clientY - down[1]) >= 8;
        lastPointer = [event.clientX, event.clientY];
      }
    });
    update = (dt) => {
      travel = THREE.MathUtils.lerp(
        travel,
        desiredTravel,
        reduced.matches || still ? 1 : 1 - Math.exp(-7 * dt),
      );
      cameraX = THREE.MathUtils.lerp(
        cameraX,
        desiredX,
        reduced.matches || still ? 1 : 1 - Math.exp(-7 * dt),
      );
      const mobile = innerWidth < 700;
      camera.fov = mobile ? 60 : 48;
      camera.updateProjectionMatrix();
      camera.position.set(
        cameraX + smoothPointer.x * (mobile ? 0.5 : 1.3),
        mobile ? 3.4 : 3.1,
        12 - travel,
      );
      look.x = cameraX + smoothPointer.x * 2;
      camera.lookAt(look);
      state.travel = travel;
    };
  }

  if (id === "city") {
    scene.background = new THREE.Color("#10273e");
    scene.fog = new THREE.FogExp2("#244c68", 0.013);
    scene.add(new THREE.HemisphereLight("#b6d6ec", "#122539", 1.9));
    const sun = new THREE.DirectionalLight("#bcd9ed", 3);
    sun.position.set(-9, 25, 15);
    sun.castShadow = true;
    sun.shadow.mapSize.set(2048, 2048);
    Object.assign(sun.shadow.camera, {
      left: -30,
      right: 30,
      top: 30,
      bottom: -30,
    });
    scene.add(sun);
    box(70, 0.3, 70, "#1f3445", 0, -0.3, 0);
    const windows = new THREE.MeshStandardMaterial({
      color: "#e6bfa1",
      emissive: "#e6ad79",
      emissiveIntensity: 0.9,
    });
    const buildingMaterial = new THREE.MeshStandardMaterial({
      color: "#3b627b",
      roughness: 0.82,
    });
    const blocks = new THREE.InstancedMesh(
      new THREE.BoxGeometry(1, 1, 1),
      buildingMaterial,
      120,
    );
    blocks.castShadow = true;
    blocks.receiveShadow = true;
    const panes = new THREE.InstancedMesh(
      new THREE.BoxGeometry(0.18, 0.28, 0.025),
      windows,
      1500,
    );
    const dummy = new THREE.Object3D();
    let b = 0;
    let w = 0;
    for (let x = -5; x <= 5; x++)
      for (let z = -5; z <= 5; z++) {
        if (Math.abs(x) < 1.1 || Math.abs(z) < 1.1) continue;
        const seed = Math.abs(Math.sin(x * 31.7 + z * 17.3));
        const height = 2 + seed * 7;
        dummy.position.set(x * 3.4, height / 2, z * 3.4);
        dummy.scale.set(2.4, height, 2.5);
        dummy.rotation.set(0, 0, 0);
        dummy.updateMatrix();
        blocks.setMatrixAt(b++, dummy.matrix);
        for (let level = 0.7; level < height - 0.3; level += 1.15)
          for (let col = -0.7; col <= 0.7; col += 0.7) {
            if (w >= 1500) continue;
            dummy.position.set(x * 3.4 + col, level, z * 3.4 + 1.26);
            dummy.scale.set(1, 1, 1);
            dummy.updateMatrix();
            panes.setMatrixAt(w++, dummy.matrix);
          }
        box(2.1, 0.18, 2.2, "#193e54", x * 3.4, height + 0.09, z * 3.4);
      }
    blocks.count = b;
    panes.count = w;
    scene.add(blocks, panes);
    for (let i = -5; i <= 5; i++) {
      box(0.055, 0.01, 55, "#8d9da3", i * 3.4 - 1.55, 0.005, 0);
      box(55, 0.01, 0.055, "#8d9da3", 0, 0.005, i * 3.4 - 1.55);
    }
    const monument = mesh(
      new THREE.TorusKnotGeometry(0.9, 0.24, 100, 16),
      new THREE.MeshStandardMaterial({
        color: "#d94a39",
        roughness: 0.32,
        metalness: 0.3,
      }),
      0,
      1.6,
      0,
    );
    monument.userData.project = 2;
    targets.push(monument);
    const destinations = [
      new THREE.Vector3(-8, 0, -8),
      new THREE.Vector3(8, 0, 6),
      new THREE.Vector3(0, 0, 0),
    ];
    const selected = new THREE.Vector3();
    const selectedTarget = new THREE.Vector3();
    let zoom = 1;
    let yaw = 0.28;
    content.innerHTML =
      '<div class="scene-copy city-title"><h1>Atlas de proyectos</h1><p>Tres destinos en una ciudad.<br><span class="city-key">La pieza roja señala Materia.</span></p></div>';
    controls.innerHTML =
      '<button id="zoom-in">Acercar</button><button id="zoom-out">Alejar</button><button id="rotate">Girar mapa</button>';
    const nav = links();
    controls.append(nav);
    nav.addEventListener("click", (event) => {
      const link = event.target.closest("[data-project]");
      if (link) {
        selectedTarget.copy(destinations[Number(link.dataset.project)]);
        invalidate(70);
      }
    });
    // The three selectable plinths share the raycast navigation contract.
    destinations.forEach((p, i) => {
      const plinth = box(
        2.7,
        0.25,
        2.7,
        i === 2 ? "#ba4236" : "#86a9b7",
        p.x,
        0.15,
        p.z,
      );
      plinth.userData.project = i;
      targets.push(plinth);
    });
    controls.querySelector("#zoom-in").onclick = () => {
      zoom = Math.max(0.55, zoom - 0.15);
      invalidate();
    };
    controls.querySelector("#zoom-out").onclick = () => {
      zoom = Math.min(1.6, zoom + 0.15);
      invalidate();
    };
    controls.querySelector("#rotate").onclick = () => {
      yaw += Math.PI / 4;
      invalidate();
    };
    canvas.addEventListener(
      "wheel",
      (event) => {
        event.preventDefault();
        zoom = THREE.MathUtils.clamp(zoom + event.deltaY * 0.001, 0.55, 1.6);
        invalidate();
      },
      { passive: false },
    );
    update = (dt) => {
      selected.lerp(
        selectedTarget,
        reduced.matches || still ? 1 : 1 - Math.exp(-8 * dt),
      );
      const distance = (innerWidth < 700 ? 45 : 32) * zoom;
      camera.position.set(
        selected.x + Math.sin(yaw) * distance + smoothPointer.x,
        distance * 1.35,
        selected.z + Math.cos(yaw) * distance,
      );
      camera.lookAt(selected.x, 0, selected.z);
      state.zoom = zoom;
      state.yaw = yaw;
      state.destination = selected.toArray();
    };
  }

  if (id === "rock") {
    document.body.classList.add("product-scroll");
    scene.background = new THREE.Color("#0c110f");
    scene.add(new THREE.HemisphereLight("#a3a991", "#141915", 0.7));
    const noiseSize = 256;
    const noise = new Uint8Array(noiseSize * noiseSize * 4);
    for (let y = 0; y < noiseSize; y++)
      for (let x = 0; x < noiseSize; x++) {
        const grain =
          Math.abs(Math.sin(x * 12.9898 + y * 78.233) * 43758.5453) % 1;
        const strata = (Math.sin(y * 0.2 + Math.sin(x * 0.04) * 3) + 1) * 0.18;
        const value = Math.floor(145 + grain * 18 + strata * 24);
        const offset = (y * noiseSize + x) * 4;
        noise[offset] = noise[offset + 1] = noise[offset + 2] = value;
        noise[offset + 3] = 255;
      }
    const stoneTexture = new THREE.DataTexture(noise, noiseSize, noiseSize);
    stoneTexture.needsUpdate = true;
    stoneTexture.wrapS = stoneTexture.wrapT = THREE.RepeatWrapping;
    stoneTexture.repeat.set(4, 3);
    stoneTexture.magFilter = THREE.LinearFilter;
    stoneTexture.minFilter = THREE.LinearMipmapLinearFilter;
    stoneTexture.generateMipmaps = true;
    const stoneMaterial = new THREE.MeshStandardMaterial({
      color: "#252d2a",
      map: stoneTexture,
      roughness: 0.96,
      bumpMap: stoneTexture,
      bumpScale: 0.025,
      envMapIntensity: 0.05,
    });
    const geometry = new THREE.SphereGeometry(2.3, 96, 64);
    const positions = geometry.attributes.position;
    for (let i = 0; i < positions.count; i++) {
      const x = positions.getX(i),
        y = positions.getY(i),
        z = positions.getZ(i);
      const relief =
        1 +
        0.1 * Math.sin(x * 2.7 + z) * Math.cos(y * 3) +
        0.035 * Math.sin(z * 6 + x * 2);
      const height =
        Math.tanh(y * 1.25) * 1.02 + 0.025 * Math.sin(x * 3 + z * 4);
      positions.setXYZ(i, x * relief, height, z * relief);
    }
    geometry.computeVertexNormals();
    const rock = mesh(geometry, stoneMaterial, 1, -1.1, 0);
    rock.scale.set(1.4, 0.85, 1.05);
    const floor = box(100, 0.1, 100, "#0b100e", 0, -3.2, 0);
    floor.material.envMapIntensity = 0.1;
    const ring = new THREE.Group();
    ring.position.set(1, 0.72, 0);
    ring.rotation.set(0.22, -0.3, -0.2);
    scene.add(ring);
    const metal = new THREE.MeshStandardMaterial({
      color: "#d5c6ae",
      metalness: 1,
      roughness: 0.22,
    });
    const band = new THREE.Mesh(
      new THREE.TorusGeometry(0.84, 0.14, 28, 100),
      metal,
    );
    ring.add(band);
    band.castShadow = true;
    band.receiveShadow = true;
    const setting = new THREE.Mesh(
      new THREE.CylinderGeometry(0.42, 0.36, 0.25, 12),
      metal,
    );
    setting.rotation.x = Math.PI / 2;
    setting.position.set(0, 0.84, 0);
    ring.add(setting);
    const gem = new THREE.Mesh(
      new THREE.IcosahedronGeometry(0.45, 1),
      new THREE.MeshPhysicalMaterial({
        color: "#4d9a91",
        metalness: 0.3,
        roughness: 0.12,
        clearcoat: 1,
        clearcoatRoughness: 0.08,
      }),
    );
    gem.position.set(0, 0.89, 0.21);
    gem.scale.set(1, 0.85, 0.65);
    ring.add(gem);
    gem.castShadow = true;
    const key = spot("#fff0dd", 140, -3, 7, 5, 1, 0, 0, 0.42);
    spot("#9dbec2", 80, 5, 3, -3, 1, 0.6, 0, 0.6);
    // Broad luminous cards provide a real reflection on the metal surface.
    const environment = new THREE.Scene();
    environment.background = new THREE.Color("#303b35");
    const softbox = new THREE.Mesh(
      new THREE.PlaneGeometry(5, 9),
      new THREE.MeshBasicMaterial({ color: new THREE.Color(7, 6, 4.6) }),
    );
    softbox.position.set(-4, 3, 4);
    softbox.lookAt(0, 0, 0);
    environment.add(softbox);
    const rim = softbox.clone();
    rim.position.set(5, 2, -2);
    rim.lookAt(0, 0, 0);
    environment.add(rim);
    const generator = new THREE.PMREMGenerator(renderer);
    const environmentMap = generator.fromScene(environment, 0.08);
    scene.environment = environmentMap.texture;
    generator.dispose();
    content.innerHTML =
      '<div class="scene-copy product-copy"><h1>Anillo sobre basalto</h1><p>Estudio de producto.<br>Metal pulido, piedra verde y luz lateral.</p></div><div class="product-spec"><h2>Materia</h2><p id="chapter">Desplaza la página para acercarte a la pieza.</p></div><span class="scroll-label">Desliza para recorrer la luz</span>';
    controls.innerHTML =
      '<button id="beginning">Volver al inicio</button><button id="close-up">Ver detalle</button>';
    let progress = 0;
    let desired = 0;
    controls.querySelector("#beginning").onclick = () =>
      scrollTo({ top: 0, behavior: reduced.matches ? "instant" : "smooth" });
    controls.querySelector("#close-up").onclick = () =>
      scrollTo({
        top: document.documentElement.scrollHeight - innerHeight,
        behavior: reduced.matches ? "instant" : "smooth",
      });
    window.addEventListener(
      "scroll",
      () => {
        desired =
          scrollY /
          Math.max(1, document.documentElement.scrollHeight - innerHeight);
        invalidate(60);
      },
      { passive: true },
    );
    update = (dt) => {
      progress = THREE.MathUtils.lerp(
        progress,
        still ? 0 : desired,
        reduced.matches ? 1 : 1 - Math.exp(-8 * dt),
      );
      const mobile = innerWidth < 700;
      camera.position.set(
        3.8 - progress * 2.2,
        mobile ? 2.7 : 2.4,
        mobile ? 10 - progress * 2.6 : 8 - progress * 3,
      );
      camera.lookAt(
        mobile ? 0.8 : -0.1,
        (mobile ? 0.9 : 0.3) + progress * 0.4,
        0,
      );
      ring.rotation.y = -0.3 + progress * 0.7;
      key.intensity = 140 + progress * 50;
      state.scrollProgress = progress;
      content.querySelector("#chapter").textContent =
        progress > 0.65
          ? "Detalle del engaste y del reflejo. Pieza de demostración."
          : "Desplaza la página para acercarte a la pieza.";
      content.querySelector(".product-copy").style.visibility =
        progress > 0.6 ? "hidden" : "visible";
    };
    disposeScene = () => {
      environmentMap.dispose();
      stoneTexture.dispose();
    };
  }

  function resize() {
    renderer.setSize(innerWidth, innerHeight, false);
    camera.aspect = innerWidth / innerHeight;
    camera.updateProjectionMatrix();
    invalidate();
  }
  window.addEventListener("resize", resize);
  reduced.addEventListener("change", () => invalidate());
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) {
      cancelAnimationFrame(frame);
      frame = 0;
    } else invalidate();
  });
  canvas.addEventListener("webglcontextlost", (event) => {
    event.preventDefault();
    feedback.textContent =
      "Se ha perdido el contexto 3D. Recarga la referencia para recuperarlo.";
    state.contextLost = true;
    cancelAnimationFrame(frame);
    frame = 0;
  });
  window.addEventListener("pagehide", () => {
    cancelAnimationFrame(frame);
    disposeScene();
    scene.traverse((object) => {
      object.geometry?.dispose();
      if (object.material) {
        for (const material of [object.material].flat()) {
          material.map?.dispose();
          material.dispose();
        }
      }
    });
    renderer.dispose();
  });
  await document.fonts.ready;
  resize();
  state.ready = true;
}
