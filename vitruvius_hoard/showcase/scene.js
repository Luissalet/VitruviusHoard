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
  let navigate = () => {};
  let elapsed = 0;
  const renderTarget = new THREE.WebGLRenderTarget(1, 1, {
    type: THREE.HalfFloatType,
  });
  renderTarget.depthTexture = new THREE.DepthTexture(1, 1);
  const screenScene = new THREE.Scene();
  const screenCamera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1);
  const grade = new THREE.ShaderMaterial({
    uniforms: {
      image: { value: renderTarget.texture },
      depth: { value: renderTarget.depthTexture },
      pixel: { value: new THREE.Vector2() },
      bloom: { value: id === "city" ? 0.28 : 0.12 },
      focus: { value: 30 },
    },
    vertexShader:
      "varying vec2 v; void main(){v=uv;gl_Position=vec4(position.xy,0.,1.);}",
    fragmentShader: `uniform sampler2D image; uniform sampler2D depth; uniform vec2 pixel;
      uniform float bloom; uniform float focus; varying vec2 v;
      vec3 film(vec3 c){return clamp((c*(2.51*c+.03))/(c*(2.43*c+.59)+.14),0.,1.);}
      void main(){vec3 base=texture2D(image,v).rgb;vec3 glow=vec3(0.);vec3 soft=vec3(0.);
        float z=texture2D(depth,v).r;float distance=.2*160./(160.1-(2.*z-1.)*159.9);
        float coc=clamp(abs(distance-focus)/65.,0.,.75);
        for(int i=0;i<12;i++){float a=float(i)*.523599;vec2 d=vec2(cos(a),sin(a));
          vec3 c=texture2D(image,v+d*pixel*3.).rgb;glow+=max(c-vec3(1.),vec3(0.))/12.;
          soft+=texture2D(image,v+d*pixel*coc*5.).rgb/12.;}
        base=mix(base,soft,coc*.35)+glow*bloom;
        float vignette=1.-.3*pow(length((v-.5)*1.3),2.);
        gl_FragColor=vec4(pow(film(base*vignette),vec3(1./2.2)),1.);}`,
    depthTest: false,
    depthWrite: false,
  });
  screenScene.add(new THREE.Mesh(new THREE.PlaneGeometry(2, 2), grade));

  function invalidate(count = 35) {
    remaining = Math.max(remaining, count);
    if (!frame && !document.hidden) frame = requestAnimationFrame(render);
  }

  function render(time) {
    frame = 0;
    if (document.hidden) return;
    const dt = Math.min(0.05, Math.max(0.016, (time - previousTime) / 1000));
    previousTime = time;
    elapsed += dt;
    smoothPointer.lerp(
      pointer,
      reduced.matches || still ? 1 : 1 - Math.exp(-10 * dt),
    );
    update(dt, smoothPointer);
    renderer.setRenderTarget(renderTarget);
    renderer.render(scene, camera);
    renderer.setRenderTarget(null);
    renderer.render(screenScene, screenCamera);
    state.frames += 1;
    remaining -= 1;
    if (remaining > 0 || (!reduced.matches && !still && id === "city"))
      frame = requestAnimationFrame(render);
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

  function grainTexture(size = 256) {
    const data = new Uint8Array(size * size * 4);
    for (let y = 0; y < size; y++)
      for (let x = 0; x < size; x++) {
        const n = Math.sin(x * 127.1 + y * 311.7) * 43758.5453;
        const v = 95 + (n - Math.floor(n)) * 120;
        const k = (y * size + x) * 4;
        data[k] = data[k + 1] = data[k + 2] = v;
        data[k + 3] = 255;
      }
    const t = new THREE.DataTexture(data, size, size);
    t.needsUpdate = true;
    t.wrapS = t.wrapT = THREE.RepeatWrapping;
    t.repeat.set(8, 8);
    t.magFilter = THREE.LinearFilter;
    return t;
  }

  function beam(x, y, z, tx, ty, tz, color, power = 0.055) {
    const origin = new THREE.Vector3(x, y, z),
      end = new THREE.Vector3(tx, ty, tz);
    const length = origin.distanceTo(end);
    const g = new THREE.ConeGeometry(length * 0.28, length, 40, 1, true);
    const m = new THREE.ShaderMaterial({
      transparent: true,
      depthWrite: false,
      side: THREE.DoubleSide,
      blending: THREE.AdditiveBlending,
      uniforms: {
        tint: { value: new THREE.Color(color) },
        power: { value: power },
      },
      vertexShader:
        "varying vec2 v;void main(){v=uv;gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.);}",
      fragmentShader:
        "varying vec2 v;uniform vec3 tint;uniform float power;void main(){float a=pow(sin(v.x*3.14159),3.)*pow(v.y,.6)*(1.-smoothstep(.85,1.,v.y));gl_FragColor=vec4(tint,a*power);}",
    });
    const cone = new THREE.Mesh(g, m);
    cone.position.copy(origin).lerp(end, 0.5);
    cone.quaternion.setFromUnitVectors(
      new THREE.Vector3(0, 1, 0),
      origin.clone().sub(end).normalize(),
    );
    scene.add(cone);
    return cone;
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
    if (found) {
      navigate(found.object.userData.project);
      detail(found.object.userData.project);
    }
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
    scene.background = new THREE.Color("#07120e");
    const cutout = await new THREE.TextureLoader().loadAsync(
      "../assets/portrait-cutout.png",
    );
    cutout.colorSpace = THREE.SRGBColorSpace;
    const uniforms = {
      portrait: { value: cutout },
      pointer: { value: new THREE.Vector2() },
      strength: { value: 0.7 },
      impulse: { value: 0 },
      clock: { value: 0 },
    };
    const material = new THREE.ShaderMaterial({
      uniforms,
      transparent: true,
      depthWrite: false,
      vertexShader: `varying vec2 v;uniform sampler2D portrait;void main(){v=uv;
        float l=dot(texture2D(portrait,uv).rgb,vec3(.299,.587,.114));
        vec3 p=position;p.z+=(l-.35)*.12;gl_Position=projectionMatrix*modelViewMatrix*vec4(p,1.);}`,
      fragmentShader: `varying vec2 v;uniform sampler2D portrait;uniform vec2 pointer;
        uniform float strength;uniform float impulse;uniform float clock;
        void main(){float local=exp(-5.*distance(v,pointer*.5+.5));
          float band=step(.86,sin(floor(v.y*56.)*19.3+floor(clock*14.)));
          float block=step(.93,fract(sin(dot(floor(v*vec2(15.,22.)),vec2(12.9,78.2))+floor(clock*9.))*43758.5));
          float shift=(band*.025+block*.055)*impulse*strength*local;
          vec2 q=v+vec2(shift,0.);vec4 pic=texture2D(portrait,q);
          float l=dot(pic.rgb,vec3(.299,.587,.114));
          vec2 g=abs(fract(v*vec2(110.,150.))-.5);float line=1.-smoothstep(.025,.09,min(g.x,g.y));
          vec3 ink=mix(vec3(.06,.16,.11),vec3(.63,1.,.8),pow(l,.65));
          ink*=.75+line*.42;
          float offset=.012*impulse*strength*local;
          ink.r+=(texture2D(portrait,q+vec2(offset,0.)).r-pic.r)*impulse;
          ink.b+=(texture2D(portrait,q-vec2(offset,0.)).b-pic.b)*impulse;
          float fade=smoothstep(0.,.09,v.y)*smoothstep(0.,.025,v.x)*smoothstep(0.,.025,1.-v.x);
          if(pic.a<.1)discard;gl_FragColor=vec4(ink,pic.a*fade);}`,
    });
    const portrait = mesh(
      new THREE.PlaneGeometry(2.65, 4, 100, 130),
      material,
      0.65,
      -0.07,
      0,
    );
    const gridMaterial = new THREE.ShaderMaterial({
      uniforms: { pointer: uniforms.pointer },
      vertexShader: `varying vec2 v;uniform vec2 pointer;void main(){v=uv;vec3 p=position;
        float d=distance(uv,pointer*.12+.5);p.z+=exp(-12.*d)*.55;
        gl_Position=projectionMatrix*modelViewMatrix*vec4(p,1.);}`,
      fragmentShader: `varying vec2 v;void main(){vec2 g=abs(fract(v*vec2(38.,24.))-.5);
        float line=1.-smoothstep(.008,.028,min(g.x,g.y));
        gl_FragColor=vec4(mix(vec3(.008,.017,.012),vec3(.08,.14,.1),line),1.);}`,
    });
    mesh(new THREE.PlaneGeometry(15, 10, 100, 80), gridMaterial, 0, 0, -0.55);
    content.innerHTML =
      '<h1 class="glitch-title">Estudio del retrato</h1><p class="glitch-copy">Fotografía / campo digital<br>El gesto altera la señal.</p><div class="signal-meta">SEÑAL <span id="signal">ESTABLE</span><br>RGB / 110 × 150<br>ESTUDIO FOTOGRÁFICO</div><div class="crosshair">+</div>';
    controls.innerHTML =
      '<label>Intensidad <input id="strength" type="range" min="0" max="1.5" step="0.05" value="0.7"></label><button id="reset">Centrar retrato</button>';
    controls.querySelector("#strength").oninput = (e) => {
      uniforms.strength.value = Number(e.target.value);
      state.strength = uniforms.strength.value;
      invalidate();
    };
    let last = new THREE.Vector2(),
      impulse = 0;
    controls.querySelector("#reset").onclick = () => {
      pointer.set(0, 0);
      impulse = 0;
      invalidate();
    };
    update = (dt) => {
      const active = !reduced.matches && !still;
      impulse = Math.max(
        impulse * Math.exp(-9 * dt),
        Math.min(1, pointer.distanceTo(last) * 9),
      );
      last.copy(pointer);
      uniforms.pointer.value.copy(active ? smoothPointer : new THREE.Vector2());
      uniforms.impulse.value = active ? impulse : 0;
      uniforms.clock.value = elapsed;
      portrait.position.x = innerWidth < 700 ? 0 : 0.65;
      portrait.scale.setScalar(innerWidth < 700 ? 0.86 : 1);
      camera.position.set(0, 0, innerWidth < 700 ? 6.7 : 5.9);
      state.deformation = uniforms.pointer.value.x;
      state.impulse = uniforms.impulse.value;
      content.querySelector("#signal").textContent =
        impulse > 0.12 ? "INTERFERENCIA" : "ESTABLE";
    };
  }

  if (id === "gallery") {
    canvas.style.touchAction = "none";
    scene.background = new THREE.Color("#111614");
    scene.fog = new THREE.FogExp2("#19211e", 0.029);
    scene.add(new THREE.HemisphereLight("#cad8cf", "#101512", 0.7));
    const plaster = grainTexture();
    plaster.repeat.set(12, 8);
    const floor = box(24, 0.15, 60, "#454d49", 0, -0.1, -15);
    Object.assign(floor.material, {
      roughness: 0.27,
      metalness: 0.32,
      bumpMap: plaster,
      bumpScale: 0.015,
      roughnessMap: plaster,
    });
    for (const x of [-10, 10]) {
      const wall = box(0.3, 9, 60, "#5b615a", x, 4.4, -15);
      Object.assign(wall.material, {
        bumpMap: plaster,
        bumpScale: 0.045,
        roughness: 0.92,
      });
    }
    box(20, 9, 0.4, "#343e37", 0, 4.4, -40);
    box(20, 0.2, 60, "#181e1b", 0, 8, -15);
    for (let i = -4; i <= 4; i++)
      box(0.015, 0.004, 60, "#242c27", i * 2.5, 0.002, -15);
    for (let i = -17; i <= 4; i++)
      box(20, 0.004, 0.015, "#242c27", 0, 0.002, i * 2.5);
    for (let z = 3; z > -35; z -= 6) {
      box(0.08, 0.1, 18, "#242b26", 0, 7.8, z).rotation.y = Math.PI / 2;
      const strip = box(0.05, 0.03, 16, "#a2aaa0", 0, 7.7, z);
      strip.rotation.y = Math.PI / 2;
      strip.material = new THREE.MeshBasicMaterial({
        color: new THREE.Color(0.8, 0.9, 0.8),
      });
    }
    let travel = 0,
      desiredTravel = 0,
      desiredX = 0,
      cameraX = 0;
    const look = new THREE.Vector3(0, 2.7, -10);
    const images = await Promise.all(
      ["ceramic.jpg", "portrait.jpg", "coast.jpg"].map((name) =>
        new THREE.ImageLoader().loadAsync("../assets/" + name),
      ),
    );
    const exhibits = [],
      reflections = [];
    for (let i = 0; i < 8; i++) {
      const project = i % 3;
      const x = i < 3 ? (i - 1) * 5.5 : i % 2 ? -6.3 : 6.3;
      const z =
        i < 3 ? (i === 1 ? -8 : -5.5) : -14 - Math.floor((i - 3) / 2) * 7;
      const panel = box(4.85, 3.5, 0.34, "#101713", x, 3, z);
      panel.castShadow = true;
      const surface = document.createElement("canvas");
      surface.width = 1200;
      surface.height = 840;
      const ctx = surface.getContext("2d"),
        image = images[project];
      ctx.fillStyle = "#151d18";
      ctx.fillRect(0, 0, 1200, 840);
      const scale = Math.max(1200 / image.width, 840 / image.height);
      ctx.drawImage(
        image,
        (1200 - image.width * scale) / 2,
        (840 - image.height * scale) / 2,
        image.width * scale,
        image.height * scale,
      );
      const shade = ctx.createLinearGradient(0, 0, 0, 840);
      shade.addColorStop(0, "#08100ac9");
      shade.addColorStop(0.6, "#08100a00");
      shade.addColorStop(1, "#08100aa9");
      ctx.fillStyle = shade;
      ctx.fillRect(0, 0, 1200, 840);
      ctx.fillStyle = "#fff7e7";
      ctx.font = "104px Instrument";
      ctx.fillText(projects[project].name, 65, 130);
      ctx.font = "26px Barlow";
      ctx.fillText(projects[project].material, 70, 184);
      ctx.fillText(
        "Estudio " + String(i + 1).padStart(2, "0") + " / Abrir proyecto",
        70,
        790,
      );
      const texture = new THREE.CanvasTexture(surface);
      texture.colorSpace = THREE.SRGBColorSpace;
      const artwork = mesh(
        new THREE.PlaneGeometry(4.55, 3.2),
        new THREE.MeshBasicMaterial({ map: texture, toneMapped: false }),
        x,
        3,
        z + 0.18,
      );
      artwork.userData.project = project;
      targets.push(artwork);
      exhibits.push({ artwork, panel, baseY: 3 });
      const reflectionCanvas = document.createElement("canvas");
      reflectionCanvas.width = 400;
      reflectionCanvas.height = 280;
      const reflectionContext = reflectionCanvas.getContext("2d");
      reflectionContext.filter = "blur(9px)";
      reflectionContext.drawImage(surface, 0, 0, 400, 280);
      reflectionContext.filter = "none";
      reflectionContext.globalCompositeOperation = "destination-in";
      const fade = reflectionContext.createLinearGradient(0, 0, 0, 280);
      fade.addColorStop(0, "transparent");
      fade.addColorStop(1, "#ffffffa0");
      reflectionContext.fillStyle = fade;
      reflectionContext.fillRect(0, 0, 400, 280);
      const reflectionMap = new THREE.CanvasTexture(reflectionCanvas);
      reflectionMap.colorSpace = THREE.SRGBColorSpace;
      reflectionMap.wrapT = THREE.RepeatWrapping;
      reflectionMap.repeat.y = -1;
      const reflection = mesh(
        new THREE.PlaneGeometry(4.5, 3.8),
        new THREE.MeshBasicMaterial({
          map: reflectionMap,
          transparent: true,
          opacity: 0.2,
          depthWrite: false,
        }),
        x,
        0.006,
        z + 2,
      );
      reflection.rotation.x = -Math.PI / 2;
      reflections.push(reflection);
      box(3.6, 0.28, 0.8, "#141b16", x, 0.14, z + 1.1);
      spot("#efffe6", 185, x, 7, z + 1.3, x, 2.6, z, 0.48);
      beam(x, 7, z + 1.3, x, 0.1, z + 0.3, "#dfefd7", 0.012);
      const trim = box(1.4, 0.06, 0.18, "#e8eedb", x, 6.8, z + 0.4);
      trim.material = new THREE.MeshBasicMaterial({
        color: new THREE.Color(2.2, 2.5, 2),
      });
    }
    canvas.addEventListener("pointermove", () => {
      raycaster.setFromCamera(pointer, camera);
      const hit = raycaster.intersectObjects(targets, false)[0];
      state.hover = hit?.object.userData.project ?? -1;
    });
    navigate = (index) => {
      desiredX = (index - 1) * 5.5;
      desiredTravel = 4;
      invalidate(100);
    };
    content.innerHTML =
      '<div class="scene-copy"><h1>Sala de estudios</h1><p>Ocho obras en perspectiva.<br>Selecciona una pieza para abrirla.</p></div>';
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
          navigate(Number(link.dataset.project));
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
        cameraX +
          (reduced.matches || still ? 0 : smoothPointer.x) *
            (mobile ? 0.5 : 1.3),
        mobile ? 3.4 : 3.1,
        12 - travel,
      );
      look.x = cameraX + (reduced.matches || still ? 0 : smoothPointer.x) * 2;
      camera.lookAt(look);
      for (const exhibit of exhibits) {
        const lift =
          state.hover === exhibit.artwork.userData.project ? 0.12 : 0;
        exhibit.artwork.position.y = THREE.MathUtils.lerp(
          exhibit.artwork.position.y,
          exhibit.baseY + lift,
          reduced.matches ? 1 : 0.15,
        );
        exhibit.panel.position.y = exhibit.artwork.position.y;
      }
      grade.uniforms.focus.value = 22 - travel;
      state.travel = travel;
    };
  }

  if (id === "city") {
    scene.background = new THREE.Color("#081622");
    scene.fog = new THREE.FogExp2("#28516c", 0.024);
    renderer.toneMappingExposure = 0.85;
    scene.add(new THREE.HemisphereLight("#7599b1", "#050d17", 0.55));
    const sun = new THREE.DirectionalLight("#86bbd4", 1.7);
    sun.position.set(-15, 30, -10);
    sun.castShadow = true;
    sun.shadow.mapSize.set(2048, 2048);
    Object.assign(sun.shadow.camera, {
      left: -45,
      right: 45,
      top: 45,
      bottom: -45,
    });
    scene.add(sun);
    const streets = box(100, 0.3, 100, "#0b1c29", 0, -0.28, 0);
    const asphalt = grainTexture();
    asphalt.repeat.set(32, 32);
    Object.assign(streets.material, {
      roughness: 0.24,
      metalness: 0.55,
      bumpMap: asphalt,
      bumpScale: 0.018,
    });
    const blocks = new THREE.InstancedMesh(
      new THREE.BoxGeometry(1, 1, 1),
      new THREE.MeshStandardMaterial({
        color: "#45657a",
        roughness: 0.72,
        metalness: 0.2,
        bumpMap: asphalt,
        bumpScale: 0.055,
      }),
      3000,
    );
    blocks.castShadow = true;
    blocks.receiveShadow = true;
    // Recessed facade joints and concrete variation are part of the material,
    // unlike the former world-grid lines that crossed the buildings.
    blocks.material.onBeforeCompile = (shader) => {
      shader.vertexShader =
        "varying vec3 facadePosition;\n" + shader.vertexShader;
      shader.vertexShader = shader.vertexShader.replace(
        "#include <begin_vertex>",
        "#include <begin_vertex>\nfacadePosition=(instanceMatrix*vec4(position,1.)).xyz;",
      );
      shader.fragmentShader =
        "varying vec3 facadePosition;\n" + shader.fragmentShader;
      shader.fragmentShader = shader.fragmentShader.replace(
        "#include <color_fragment>",
        `#include <color_fragment>
        vec3 facadeNormal=abs(normalize(cross(dFdx(facadePosition),dFdy(facadePosition))));
        float side=facadeNormal.x>facadeNormal.z?facadePosition.z:facadePosition.x;
        float verticalJoint=1.-smoothstep(.012,.055,abs(fract(side*1.65)-.5));
        float horizontalJoint=1.-smoothstep(.012,.035,abs(fract(facadePosition.y*1.65)-.5));
        float concrete=fract(sin(dot(floor(facadePosition*22.),vec3(12.9,78.2,42.1)))*43758.5);
        float weather=.88+.12*sin(facadePosition.y*.45+side*2.);
        diffuseColor.rgb*=mix(1.,(.9+concrete*.12)*weather*(1.-verticalJoint*.14-horizontalJoint*.2),1.-step(.5,facadeNormal.y));`,
      );
    };
    const panes = new THREE.InstancedMesh(
      new THREE.BoxGeometry(1, 1, 0.025),
      new THREE.MeshStandardMaterial({
        color: "#d6b48a",
        emissive: "#ffd2a1",
        emissiveIntensity: 1.15,
      }),
      40000,
    );
    const dummy = new THREE.Object3D();
    let b = 0,
      w = 0;
    const random = (a, b) => {
      const n = Math.sin(a * 127.1 + b * 311.7) * 43758.5453;
      return n - Math.floor(n);
    };
    const part = (x, y, z, sx, sy, sz, tint) => {
      dummy.position.set(x, y, z);
      dummy.scale.set(sx, sy, sz);
      dummy.rotation.set(0, 0, 0);
      dummy.updateMatrix();
      blocks.setMatrixAt(b, dummy.matrix);
      blocks.setColorAt(b++, new THREE.Color(tint));
    };
    for (let x = -8; x <= 8; x++)
      for (let z = -8; z <= 8; z++) {
        if (x === 0 || z === 0 || (Math.abs(x) < 2 && Math.abs(z) < 2))
          continue;
        const r = random(x, z),
          h = 3 + r * r * 13,
          wide = 2.1 + random(z, x) * 0.65,
          deep = 2 + random(x + 9, z) * 0.65;
        const px = x * 3.6,
          pz = z * 3.6;
        part(px, h / 2, pz, wide, h, deep, r > 0.6 ? "#45677e" : "#2b495f");
        part(px, h + 0.16, pz, wide + 0.08, 0.32, deep + 0.08, "#172f41");
        for (const corner of [-1, 1]) {
          part(
            px + corner * (wide / 2 - 0.08),
            h / 2,
            pz + deep / 2 + 0.03,
            0.08,
            h,
            0.08,
            "#487186",
          );
          part(
            px + wide / 2 + 0.03,
            h / 2,
            pz + corner * (deep / 2 - 0.08),
            0.08,
            h,
            0.08,
            "#487186",
          );
        }
        if (r > 0.5)
          for (let ledge = 3; ledge < h; ledge += 3.5)
            part(px, ledge, pz, wide + 0.12, 0.1, deep + 0.12, "#1d394e");
        if (r > 0.38) {
          const crown = h * (r > 0.75 ? 0.24 : 0.1);
          part(
            px,
            h + crown / 2,
            pz,
            wide * 0.65,
            crown,
            deep * 0.64,
            "#32526b",
          );
        }
        if (r > 0.8) part(px + 0.3, h + 2, pz, 0.04, 3, 0.04, "#63828f");
        for (let side = 0; side < 4; side++)
          for (let row = 0.65; row < h - 0.3; row += 0.61)
            for (let col = -0.7; col <= 0.71; col += 0.48) {
              const lit = random(
                x * 17 + col * 13 + side * 5,
                z * 21 + row * 12,
              );
              if (lit < 0.71 || w >= 40000) continue;
              dummy.position.set(
                px +
                  (side % 2
                    ? side === 1
                      ? wide / 2 + 0.02
                      : -wide / 2 - 0.02
                    : col),
                row,
                pz +
                  (side % 2
                    ? col
                    : side === 0
                      ? deep / 2 + 0.02
                      : -deep / 2 - 0.02),
              );
              dummy.scale.set(
                0.18 + lit * 0.12,
                0.27 + (lit > 0.9 ? 0.15 : 0),
                1,
              );
              dummy.rotation.set(0, (side * Math.PI) / 2, 0);
              dummy.updateMatrix();
              panes.setMatrixAt(w, dummy.matrix);
              panes.setColorAt(
                w++,
                new THREE.Color().setRGB(
                  0.35 + lit * 0.65,
                  0.3 + lit * 0.45,
                  0.22 + lit * 0.32,
                ),
              );
            }
      }
    blocks.count = b;
    panes.count = w;
    scene.add(blocks, panes);
    const trails = [];
    for (let i = 0; i < 36; i++) {
      const horizontal = i % 2 === 0,
        avenue = (Math.floor(i / 6) - 3) * 3.6 + 0.2;
      const along = ((i % 6) - 3) * 9;
      const material = new THREE.MeshBasicMaterial({
        color: new THREE.Color(
          i % 3 === 0 ? 4 : 0.7,
          i % 3 === 0 ? 0.22 : 1.6,
          i % 3 === 0 ? 0.08 : 2.3,
        ),
        transparent: true,
        opacity: 0.7,
      });
      const streak = mesh(
        new THREE.PlaneGeometry(0.035, 1.1 + (i % 4) * 0.6),
        material,
        horizontal ? along : avenue,
        0.02,
        horizontal ? avenue : along,
      );
      streak.rotation.x = -Math.PI / 2;
      if (horizontal) streak.rotation.z = Math.PI / 2;
      const reflected = streak.clone();
      reflected.material = material.clone();
      reflected.material.opacity = 0.07;
      reflected.scale.set(9, 1.8, 1);
      reflected.position.y = 0.014;
      scene.add(reflected);
      trails.push({ streak, reflected, horizontal, start: along });
    }
    const monument = mesh(
      new THREE.TorusKnotGeometry(1.5, 0.32, 150, 20),
      new THREE.MeshStandardMaterial({
        color: "#b31706",
        emissive: "#f51503",
        emissiveIntensity: 1.5,
        roughness: 0.25,
        metalness: 0.35,
      }),
      0,
      2.4,
      0,
    );
    monument.userData.project = 2;
    targets.push(monument);
    const redLight = new THREE.PointLight("#ff2410", 500, 23, 2);
    redLight.position.set(0, 3, 0);
    scene.add(redLight);
    const avenueLight = new THREE.PointLight("#6db8ec", 450, 60, 2);
    avenueLight.position.set(-2, 14, -9);
    scene.add(avenueLight);
    beam(-3, 25, -12, 0, 0, 4, "#77a6cb", 0.07);
    const destinations = [
      new THREE.Vector3(-8, 0, -8),
      new THREE.Vector3(8, 0, 6),
      new THREE.Vector3(0, 0, 0),
    ];
    const selected = new THREE.Vector3();
    const selectedTarget = new THREE.Vector3();
    let zoom = 1;
    let yaw = 0.28;
    let cameraYaw = yaw,
      cameraZoom = 1;
    content.innerHTML =
      '<div class="scene-copy city-title"><h1>Atlas de proyectos</h1><p>Tres destinos en una ciudad.<br><span class="city-key">La pieza roja señala Materia.</span></p></div>';
    controls.innerHTML =
      '<button id="zoom-in">Acercar</button><button id="zoom-out">Alejar</button><button id="rotate">Girar mapa</button>';
    const nav = links();
    controls.append(nav);
    nav.addEventListener("click", (event) => {
      const link = event.target.closest("[data-project]");
      if (link) {
        navigate(Number(link.dataset.project));
        invalidate(70);
      }
    });
    navigate = (index) => {
      selectedTarget.copy(destinations[index]);
      invalidate(100);
    };
    // The three selectable plinths share the raycast navigation contract.
    destinations.forEach((p, i) => {
      const plinth = box(
        2.7,
        0.25,
        2.7,
        i === 2 ? "#67180e" : "#426575",
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
      const smoothing = reduced.matches || still ? 1 : 1 - Math.exp(-4 * dt);
      cameraYaw = THREE.MathUtils.lerp(cameraYaw, yaw, smoothing);
      cameraZoom = THREE.MathUtils.lerp(cameraZoom, zoom, smoothing);
      const orbit =
        cameraYaw + (!reduced.matches && !still ? elapsed * 0.009 : 0);
      const distance = (innerWidth < 700 ? 43 : 29) * cameraZoom;
      for (const t of trails) {
        const value =
          still || reduced.matches
            ? t.start
            : ((t.start + elapsed * 1.3 + 30) % 60) - 30;
        t.streak.position[t.horizontal ? "x" : "z"] = value;
        t.reflected.position[t.horizontal ? "x" : "z"] = value;
      }
      grade.uniforms.focus.value = distance * 1.3;
      camera.position.set(
        selected.x +
          Math.sin(orbit) * distance +
          (reduced.matches || still ? 0 : smoothPointer.x),
        distance * 0.95,
        selected.z + Math.cos(orbit) * distance,
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
    const stoneTexture = grainTexture(512);
    stoneTexture.repeat.set(2, 2);
    const size = 256,
      normals = new Uint8Array(size * size * 4);
    const hash = (x, y, z) => {
      const n = Math.sin(x * 127.1 + y * 311.7 + z * 74.7) * 43758.5453;
      return n - Math.floor(n);
    };
    function noise(x, y, z) {
      const ix = Math.floor(x),
        iy = Math.floor(y),
        iz = Math.floor(z);
      const t = [x - ix, y - iy, z - iz].map((v) => v * v * (3 - 2 * v));
      let v = 0;
      for (let i = 0; i < 2; i++)
        for (let j = 0; j < 2; j++)
          for (let k = 0; k < 2; k++)
            v +=
              hash(ix + i, iy + j, iz + k) *
              (i ? t[0] : 1 - t[0]) *
              (j ? t[1] : 1 - t[1]) *
              (k ? t[2] : 1 - t[2]);
      return v;
    }
    for (let y = 0; y < size; y++)
      for (let x = 0; x < size; x++) {
        const h = (u, v) =>
          noise(u * 0.18, v * 0.18, 2) + noise(u * 0.6, v * 0.6, 3) * 0.32;
        const n = new THREE.Vector3(
          (h(x - 1, y) - h(x + 1, y)) * 2,
          (h(x, y - 1) - h(x, y + 1)) * 2,
          1,
        ).normalize();
        const k = (y * size + x) * 4;
        normals[k] = (n.x * 0.5 + 0.5) * 255;
        normals[k + 1] = (n.y * 0.5 + 0.5) * 255;
        normals[k + 2] = (n.z * 0.5 + 0.5) * 255;
        normals[k + 3] = 255;
      }
    const normalMap = new THREE.DataTexture(normals, size, size);
    normalMap.needsUpdate = true;
    normalMap.wrapS = normalMap.wrapT = THREE.RepeatWrapping;
    normalMap.repeat.set(6, 5);
    const stoneMaterial = new THREE.MeshStandardMaterial({
      color: "#303334",
      map: stoneTexture,
      roughness: 0.87,
      normalMap,
      normalScale: new THREE.Vector2(0.38, 0.38),
      metalness: 0.04,
      envMapIntensity: 0.13,
    });
    const geometry = new THREE.BoxGeometry(4.5, 2.3, 3.9, 56, 32, 48),
      positions = geometry.attributes.position;
    for (let i = 0; i < positions.count; i++) {
      const x = positions.getX(i),
        y = positions.getY(i),
        z = positions.getZ(i);
      const n =
        noise(x * 1.1 + 7, y * 1.1 + 6, z * 1.1 + 5) * 0.35 +
        noise(x * 3 + 9, y * 3 + 7, z * 3 + 5) * 0.16 +
        noise(x * 9 + 3, y * 9 + 9, z * 9 + 6) * 0.065;
      const ridges = Math.abs(Math.sin(x * 3 + z * 2 + y * 0.7)) * 0.065;
      positions.setXYZ(
        i,
        x * (0.84 + n * 0.6),
        y * 0.7 + n * 0.75 - ridges,
        z * (0.86 + n * 0.6),
      );
    }
    geometry.computeVertexNormals();
    // Join face seams after displacement while retaining the slab silhouette.
    const normalSums = new Map(),
      normalKeys = [];
    const vertexNormals = geometry.attributes.normal;
    for (let i = 0; i < positions.count; i++) {
      const key = [positions.getX(i), positions.getY(i), positions.getZ(i)]
        .map((value) => Math.round(value * 10000))
        .join(",");
      normalKeys.push(key);
      if (!normalSums.has(key)) normalSums.set(key, new THREE.Vector3());
      normalSums
        .get(key)
        .add(new THREE.Vector3().fromBufferAttribute(vertexNormals, i));
    }
    for (const normal of normalSums.values()) normal.normalize();
    for (let i = 0; i < positions.count; i++) {
      const normal = normalSums.get(normalKeys[i]);
      vertexNormals.setXYZ(i, normal.x, normal.y, normal.z);
    }
    const rock = mesh(geometry, stoneMaterial, 1, -1.15, 0);
    rock.scale.set(1.4, 1.2, 1.05);
    const secondRock = mesh(geometry, stoneMaterial, -3.8, -0.7, -4.3);
    secondRock.rotation.y = 1.7;
    secondRock.scale.set(1.15, 1.5, 1.1);
    // Broken basalt faces continue behind the plinths, catching the grazing rim.
    for (let i = 0; i < 7; i++) {
      const cliff = mesh(
        geometry,
        stoneMaterial,
        (i - 3) * 3.4,
        1.2,
        -8 - (i % 2),
      );
      cliff.scale.set(0.9, 3.8, 1.1);
      cliff.rotation.set(0.1, i * 0.8, 0.1 * (i % 3));
    }
    const floor = box(100, 0.1, 100, "#0b100e", 0, -3.2, 0);
    floor.material.envMapIntensity = 0.1;
    const ring = new THREE.Group();
    ring.position.set(1, 1.1, 0);
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
    const secondRing = ring.clone();
    secondRing.position.set(-3.8, 1.85, -4.3);
    secondRing.rotation.set(0.1, 0.5, 0.18);
    secondRing.children[2].material = gem.material.clone();
    secondRing.children[2].material.color.set("#3b6bba");
    scene.add(secondRing);
    const caustic = spot("#5ea28a", 12, 1, 1.5, 0.5, 1, -0.3, 0, 0.4);
    const caustic2 = spot("#5d8fdb", 14, -3.8, 2, -4, -3.8, -0.2, -4.3, 0.4);
    beam(-3, 7, 5, 1, -0.6, 0, "#e7e1bf", 0.008);
    beam(-6, 8, -1, -3.8, 0.2, -4.3, "#bfdbef", 0.009);
    const dustGeometry = new THREE.BufferGeometry(),
      dust = [];
    for (let i = 0; i < 180; i++)
      dust.push(
        (hash(i, 1, 1) - 0.5) * 10,
        hash(i, 2, 2) * 7 - 1,
        (hash(i, 3, 3) - 0.5) * 8,
      );
    dustGeometry.setAttribute(
      "position",
      new THREE.Float32BufferAttribute(dust, 3),
    );
    const motes = new THREE.Points(
      dustGeometry,
      new THREE.PointsMaterial({
        color: "#e1d1b7",
        size: 0.018,
        transparent: true,
        opacity: 0.3,
        depthWrite: false,
      }),
    );
    scene.add(motes);
    const key = spot("#fff0dd", 140, -3, 7, 5, 1, 0, 0, 0.42);
    spot("#9dbec2", 200, 5, 3, -3, 1, 0.6, 0, 0.6);
    spot("#cfdbff", 190, -6, 6, -6, -3.8, 0.4, -4.3, 0.55);
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
      const t = progress < 0.5 ? progress * 2 : (progress - 0.5) * 2;
      const ease = t * t * (3 - 2 * t),
        part = progress < 0.5 ? 0 : 1;
      const positions = mobile
        ? [
            [3.8, 3.1, 12],
            [1.5, 2.6, 10],
            [-3.2, 2.9, 4.3],
          ]
        : [
            [3.8, 2.4, 9.5],
            [1, 2.3, 7.5],
            [-4.8, 2.9, 2.8],
          ];
      const targets = [
        [mobile ? 0.8 : -0.4, 0.5, -0.2],
        [0.3, 0.65, -0.5],
        [-3.8, 1.3, -4.3],
      ];
      const pos = new THREE.Vector3(...positions[part]).lerp(
        new THREE.Vector3(...positions[part + 1]),
        ease,
      );
      const target = new THREE.Vector3(...targets[part]).lerp(
        new THREE.Vector3(...targets[part + 1]),
        ease,
      );
      camera.position.copy(pos);
      camera.lookAt(target);
      ring.rotation.y = -0.3 + progress * 0.55;
      secondRing.rotation.y = 0.5 - progress * 0.25;
      key.intensity = 140 + progress * 70;
      caustic.intensity = 12 + Math.sin(progress * Math.PI) * 8;
      grade.uniforms.focus.value = camera.position.distanceTo(target);
      motes.rotation.y = reduced.matches || still ? 0 : elapsed * 0.007;
      content.querySelector(".product-spec").style.opacity = String(
        0.92 + 0.08 * ease,
      );
      content.querySelector(".product-spec").style.transform =
        `translateY(${(1 - ease) * 12}px)`;
      state.scrollProgress = progress;
      content.querySelector("#chapter").textContent =
        progress > 0.65
          ? "Segundo plano. Piedra azul sobre basalto. Pieza de demostración."
          : "Desplaza la página para acercarte a la pieza.";
      content.querySelector(".product-copy").style.visibility =
        progress > 0.6 ? "hidden" : "visible";
    };
    disposeScene = () => {
      environmentMap.dispose();
      stoneTexture.dispose();
      normalMap.dispose();
    };
  }

  function resize() {
    renderer.setSize(innerWidth, innerHeight, false);
    const size = renderer.getDrawingBufferSize(new THREE.Vector2());
    renderTarget.setSize(size.x, size.y);
    grade.uniforms.pixel.value.set(1 / size.x, 1 / size.y);
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
    renderTarget.dispose();
    grade.dispose();
    screenScene.children[0].geometry.dispose();
    renderer.dispose();
  });
  await document.fonts.ready;
  resize();
  state.ready = true;
}
