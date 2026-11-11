// A segmented sheet follows a damped spring. Each segment rotates in real 3D.
export function createBook(content, controls, reduced, state) {
  const spreads = [
    [
      '<div class="editorial"><img class="book-plate" src="../assets/coast.jpg" alt="Costa iluminada y superficie del agua"><div class="plate-shade"></div><h1>Cuaderno<br>de formas</h1><p>Volumen, materia<br>y luz natural.</p><small>ESTUDIOS DE DEMOSTRACIÓN / 2026</small></div>',
      '<div class="editorial"><img class="book-plate ceramic-plate" src="../assets/ceramic.jpg" alt="Estudio fotográfico de cerámica"><div class="plate-shade"></div><h2>Arco</h2><p>La curva.<br>La sombra.<br>El espesor.</p><a href="#arco">Leer estudio</a><small>CERÁMICA / PLIEGO 1 DE 3</small></div>',
    ],
    [
      '<div class="editorial"><img class="book-plate portrait-plate" src="../assets/portrait.jpg" alt="Retrato fotográfico en claroscuro"><div class="plate-shade"></div><h2>Retrato</h2><small>FOTOGRAFÍA / PLIEGO 2 DE 3</small></div>',
      '<div class="editorial quiet-page"><h2>Una luz<br>lateral.</h2><div class="book-rule"></div><p>Un solo foco organiza el rostro. El margen conserva la pausa entre imagen y texto.</p><a href="#retrato">Leer estudio</a><small>LUZ / SOMBRA / SUPERFICIE</small><div class="editorial-orbit"></div></div>',
    ],
    [
      '<div class="editorial"><img class="book-plate" src="../assets/ceramic.jpg" alt="Materia cerámica y superficie"><div class="plate-shade"></div><h2>Materia</h2><small>VOLUMEN / PLIEGO 3 DE 3</small></div>',
      '<div class="editorial quiet-page ochre-page"><h2>Tierra<br>cocida</h2><div class="book-rule"></div><p>Una superficie mate recibe una luz amplia. El color permanece concentrado en la pieza.</p><a href="#materia">Leer estudio</a><small>ESTUDIO DE SUPERFICIE / 2026</small></div>',
    ],
  ];
  const paper = document.createElement("canvas");
  paper.width = paper.height = 128;
  const context = paper.getContext("2d"),
    grain = context.createImageData(128, 128);
  for (let i = 0; i < grain.data.length; i += 4) {
    const n = Math.sin(i * 12.9898) * 43758.5453;
    grain.data[i] = grain.data[i + 1] = grain.data[i + 2] = 180;
    grain.data[i + 3] = (n - Math.floor(n)) * 26;
  }
  context.putImageData(grain, 0, 0);
  document.body.style.setProperty("--paper-grain", `url(${paper.toDataURL()})`);
  content.innerHTML =
    '<div class="book-stage"><div class="book"><div class="spread"></div><div class="book-spine"></div></div></div>';
  const book = content.querySelector(".book");
  const stage = content.querySelector(".book-stage");
  const spread = content.querySelector(".spread");
  stage.style.pointerEvents = "auto";
  controls.innerHTML =
    '<button id="previous">Pliego anterior</button><span id="folio" aria-live="polite"></span><button id="next">Pliego siguiente</button><span>Arrastra una hoja o usa las flechas</span>';
  const previous = controls.querySelector("#previous");
  const next = controls.querySelector("#next");
  const folio = controls.querySelector("#folio");
  let index = 0;
  let turning = false;
  let progress = 0;
  let velocity = 0;
  let target = 0;
  let direction = 1;
  let dragging = false;
  let lastTime = 0;
  let frame = 0;
  let startX = 0;
  let fold;
  let segments = [];

  function show() {
    spread.innerHTML = spreads[index]
      .map((text) => `<article class="book-page">${text}</article>`)
      .join("");
    previous.disabled = index === 0;
    next.disabled = index === spreads.length - 1;
    folio.textContent = `${index + 1} / ${spreads.length}`;
    state.spread = index;
    state.turning = false;
  }

  function draw() {
    const width = book.clientWidth / 2;
    const step = width / segments.length;
    let x = 0;
    let z = 0;
    segments.forEach((segment, i) => {
      const curl =
        Math.sin(Math.PI * progress) *
        Math.sin((Math.PI * (i + 0.5)) / segments.length) *
        0.42;
      const angle = -Math.PI * progress + curl;
      segment.style.width = `${step + 0.7}px`;
      segment.style.transform = `translate3d(${x}px,0,${z + 3}px) rotateY(${angle}rad)`;
      segment.style.filter = `brightness(${0.58 + 0.42 * Math.abs(Math.cos(angle))})`;
      const [front, back] = segment.children;
      front.firstElementChild.style.width = `${width}px`;
      front.firstElementChild.style.padding = `${width * 0.08}px`;
      front.firstElementChild.style.transform = `translateX(${-i * step}px)`;
      back.firstElementChild.style.width = `${width}px`;
      back.firstElementChild.style.padding = `${width * 0.08}px`;
      back.firstElementChild.style.transform = `translateX(${-(segments.length - i - 1) * step}px)`;
      x += Math.cos(angle) * step;
      z -= Math.sin(angle) * step;
    });
    state.pageProgress = progress;
  }

  function finish(commit) {
    if (commit) index += direction;
    fold.remove();
    turning = false;
    dragging = false;
    show();
  }

  function animate(time) {
    const dt = Math.min(0.032, Math.max(0.008, (time - lastTime) / 1000));
    lastTime = time;
    velocity += ((target - progress) * 100 - velocity * 18) * dt;
    progress += velocity * dt;
    progress = Math.max(0, Math.min(1, progress));
    draw();
    if (Math.abs(target - progress) < 0.0015 && Math.abs(velocity) < 0.02) {
      finish(direction === 1 ? target === 1 : target === 0);
      return;
    }
    frame = requestAnimationFrame(animate);
  }

  function begin(step) {
    if (turning || index + step < 0 || index + step >= spreads.length)
      return false;
    if (reduced.matches) {
      index += step;
      show();
      return false;
    }
    turning = true;
    state.turning = true;
    direction = step;
    progress = step === 1 ? 0 : 1;
    velocity = 0;
    const from = step === 1 ? index : index - 1;
    spread.innerHTML = `<article class="book-page">${spreads[from][0]}</article><article class="book-page">${spreads[from + 1][1]}</article>`;
    fold = document.createElement("div");
    fold.className = "page-fold";
    fold.style.left = "50%";
    fold.setAttribute("aria-hidden", "true");
    fold.inert = true;
    segments = Array.from({ length: 20 }, () => {
      const segment = document.createElement("div");
      segment.style.cssText =
        "position:absolute;top:0;height:100%;transform-origin:left center;transform-style:preserve-3d";
      segment.innerHTML = `<div style="position:absolute;inset:0;overflow:hidden;backface-visibility:hidden"><article class="book-page" style="height:100%;padding:16%">${spreads[from][1]}</article></div><div style="position:absolute;inset:0;overflow:hidden;backface-visibility:hidden;transform:rotateY(180deg)"><article class="book-page" style="height:100%;padding:16%">${spreads[from + 1][0]}</article></div>`;
      fold.append(segment);
      return segment;
    });
    book.append(fold);
    draw();
    return true;
  }

  function go(step) {
    if (!begin(step)) return;
    target = step === 1 ? 1 : 0;
    lastTime = performance.now();
    frame = requestAnimationFrame(animate);
  }
  previous.addEventListener("click", () => go(-1));
  next.addEventListener("click", () => go(1));
  window.addEventListener("keydown", (event) => {
    if (event.key === "ArrowRight") {
      event.preventDefault();
      go(1);
    }
    if (event.key === "ArrowLeft") {
      event.preventDefault();
      go(-1);
    }
  });
  stage.addEventListener("pointerdown", (event) => {
    if (event.target.closest("a,button")) return;
    const bounds = book.getBoundingClientRect();
    const step = event.clientX >= bounds.left + bounds.width / 2 ? 1 : -1;
    if (!begin(step)) return;
    dragging = true;
    startX = event.clientX;
    stage.setPointerCapture(event.pointerId);
  });
  stage.addEventListener("pointermove", (event) => {
    if (!dragging) return;
    progress = Math.max(
      0,
      Math.min(
        1,
        (direction === 1 ? 0 : 1) +
          (startX - event.clientX) / (book.clientWidth / 2),
      ),
    );
    draw();
  });
  function release(event) {
    if (!dragging) return;
    dragging = false;
    target = progress > 0.5 ? 1 : 0;
    if (event.type === "pointercancel") target = direction === 1 ? 0 : 1;
    lastTime = performance.now();
    frame = requestAnimationFrame(animate);
  }
  stage.addEventListener("pointerup", release);
  stage.addEventListener("pointercancel", release);
  window.addEventListener("pagehide", () => cancelAnimationFrame(frame));
  window.addEventListener("hashchange", () => {
    const descriptions = {
      arco: "Arco · Cerámica mate, borde grueso y sombra lateral.",
      retrato: "Retrato · Fotografía en claroscuro. Procedencia en la receta.",
      materia: "Materia · Estudio de volumen en tierra cocida.",
    };
    document.querySelector("#feedback").textContent =
      descriptions[location.hash.slice(1)] || "";
  });
  show();
}
