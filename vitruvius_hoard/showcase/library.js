const $ = (selector) => document.querySelector(selector);
let selected;
let version = 0;
let poll;

async function request(url, options) {
  const response = await fetch(url, options);
  const body = await response.json();
  if (!response.ok)
    throw new Error(body.error || body.detail || response.statusText);
  return body;
}
function call(name, arguments_) {
  return request("/api/ui/call", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, arguments: arguments_ }),
  });
}
function text(tag, value) {
  const node = document.createElement(tag);
  node.textContent = value;
  return node;
}
function list(selector, values) {
  $(selector).replaceChildren(...values.map((value) => text("li", value)));
}

async function choose(id) {
  const current = ++version;
  clearTimeout(poll);
  $("#status").textContent = "Cargando receta…";
  try {
    const recipe = await request("/api/showcase/" + id);
    if (current !== version) return;
    selected = recipe;
    $("#selected").hidden = false;
    $("#title").textContent = recipe.title;
    $("#summary").textContent = recipe.summary;
    $("#open").href = recipe.reference_url;
    $("#download").href = recipe.download_url;
    $("#preview").src = recipe.reference_url;
    $("#prompt").value = recipe.prompt;
    $("#skill").textContent = recipe.skill;
    $("#run").replaceChildren();
    const labels = {
      light: "Luz",
      rhythm: "Ritmo",
      typography: "Tipografía",
      interaction: "Interacción",
      why: "Por qué",
    };
    $("#decisions").replaceChildren(
      ...Object.entries(recipe.decisions).flatMap(([key, value]) => [
        text("h3", labels[key]),
        text("p", value),
      ]),
    );
    list("#implementation", recipe.implementation);
    list("#checkpoints", recipe.checkpoints);
    $("#sources").replaceChildren(
      ...recipe.sources.map((source) => {
        const node = document.createElement("div");
        node.className = "source";
        const link = text(
          "a",
          `Fuente Darwin ${source.darwin_id} · segundo ${source.frame_seconds}`,
        );
        link.href = source.url;
        link.target = "_blank";
        link.rel = "noopener";
        const frame = text("a", "Abrir fotograma en Links");
        frame.href = source.frame_url;
        frame.target = "_blank";
        frame.rel = "noopener";
        node.append(
          link,
          text("p", source.observed),
          frame,
          text(
            "small",
            "El vídeo conserva los derechos de su autor. La descarga incluye recursos propios y de stock con sus licencias.",
          ),
        );
        return node;
      }),
    );
    document
      .querySelectorAll("#recipes button")
      .forEach((button) =>
        button.setAttribute("aria-current", String(button.dataset.id === id)),
      );
    history.replaceState(null, "", "?recipe=" + id);
    const source = await request("/api/showcase/" + id + "/source");
    if (current !== version) return;
    $("#source").textContent = source.text;
    $("#status").textContent = "";
  } catch (error) {
    $("#status").textContent = error.message;
  }
}

async function search(query = "") {
  try {
    const found = await request(
      "/api/showcase?query=" + encodeURIComponent(query),
    );
    $("#recipes").replaceChildren(
      ...found.recipes.map((recipe) => {
        const button = text("button", recipe.title);
        button.type = "button";
        button.dataset.id = recipe.id;
        button.onclick = () => choose(recipe.id);
        return button;
      }),
    );
    $("#empty").hidden = found.recipes.length > 0;
    if (!found.recipes.length) {
      $("#selected").hidden = true;
      return;
    }
    const desired = new URLSearchParams(location.search).get("recipe");
    await choose(
      found.recipes.some((recipe) => recipe.id === desired)
        ? desired
        : found.recipes[0].id,
    );
  } catch (error) {
    $("#status").textContent =
      "No se pudo leer la biblioteca. " + error.message;
  }
}

$("#search").onsubmit = (event) => {
  event.preventDefault();
  search($("#query").value);
};
$("#copy").onclick = async () => {
  try {
    await navigator.clipboard.writeText($("#prompt").value);
    $("#status").textContent = "Instrucción copiada.";
  } catch {
    $("#prompt").focus();
    $("#prompt").select();
    $("#status").textContent = "Seleccionada para copiar con Ctrl+C.";
  }
};
$("#enable").onclick = async () => {
  $("#enable").disabled = true;
  try {
    await call("software_module_set", { module: "design", enabled: true });
    $("#status").textContent = "Diseño activado. Puedes iniciar Rehacer.";
  } catch (error) {
    $("#status").textContent = error.message;
  } finally {
    $("#enable").disabled = false;
  }
};
function showRun(run) {
  $("#run").replaceChildren(
    text("p", `${run.phase || run.status} · ${run.id}`),
  );
  if (run.best_score !== null && run.best_score !== undefined)
    $("#run").append(
      text(
        "p",
        `Paridad de composición ${Number(run.best_score).toFixed(2)} %`,
      ),
    );
  if (run.error) $("#run").append(text("p", run.error));
  for (const [label, url] of [
    ["Ver informe", run.report_url],
    ["Abrir resultado", run.site_url],
  ]) {
    if (!url) continue;
    const link = text("a", label);
    link.href = "/design" + url;
    link.target = "_blank";
    link.rel = "noopener";
    $("#run").append(link);
  }
}
async function progress(id, current) {
  if (current !== version) return;
  try {
    const run = await call("remake_get", { id });
    if (current !== version) return;
    showRun(run);
    if (["queued", "running"].includes(run.status) || run.running)
      poll = setTimeout(() => progress(id, current), 1800);
  } catch (error) {
    $("#run").textContent = error.message;
  }
}
$("#remake").onclick = async () => {
  if (!selected) return;
  const current = version;
  $("#remake").disabled = true;
  $("#run").textContent = "Iniciando Rehacer…";
  try {
    const result = await call("showcase_remake", {
      id: selected.id,
      mode: $("#mode").value,
    });
    if (current !== version) return;
    showRun(result.remake);
    poll = setTimeout(() => progress(result.remake.id, current), 1000);
  } catch (error) {
    $("#run").textContent = error.message;
  } finally {
    $("#remake").disabled = false;
  }
};
window.addEventListener("pagehide", () => clearTimeout(poll));
await search();
