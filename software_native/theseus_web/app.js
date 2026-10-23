const $ = (selector) => document.querySelector(selector);
const escape = (value) =>
  String(value ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const json = (value) => JSON.stringify(value, null, 2);
let clientInspectionDownload = null;
const SWIFT_STATUS = {demangled: "demangled", unchanged: "sin cambio", invalid: "inválido"};
function swiftFlags(flags) {
  if (!flags) return "";
  const notes = [];
  if (flags.thunk) notes.push(flags.thunk_target ? `thunk de ${escape(flags.thunk_target)}` : "thunk sin destino registrado");
  if (flags.foreign_calling_convention) notes.push("sin convención de llamada Swift");
  return notes.length ? " · " + notes.join(" · ") : "";
}
async function demangleSwiftForm(form) {
  const button = form.querySelector('button[type="submit"]');
  const result = $("#swift-demangle-result");
  const symbols = String(new FormData(form).get("symbols") || "").split(/\r?\n/u).filter((line) => line.length);
  button.disabled = true;
  result.setAttribute("aria-busy", "true");
  result.textContent = "Demangling…";
  try {
    const observed = await api("/swift/demangle", {symbols});
    result.innerHTML = '<ol class="swift-symbols">' + observed.symbols.map((row) =>
      `<li data-status="${escape(row.status)}"><code>${escape(row.input)}</code> → <code>${escape(row.output)}</code> <span class="small">${escape(SWIFT_STATUS[row.status] || row.status)}${swiftFlags(row.classification)}</span></li>`).join("") +
      `</ol><p class="small">${escape(observed.provenance[0]?.version.split("\n").find((line) => /version/iu.test(line)) || "")}</p>`;
  } catch (error) {
    result.textContent = error.message;
  } finally {
    result.removeAttribute("aria-busy");
    button.disabled = false;
  }
}
async function inspectClientForm(form) {
  const button = form.querySelector('button[type="submit"]');
  const result = $("#client-inspection-result");
  button.disabled = true;
  result.setAttribute("aria-busy", "true");
  result.textContent = "Consultando versiones…";
  try {
    const observed = await api("/engines/inspect", {family: new FormData(form).get("family")});
    if (clientInspectionDownload) URL.revokeObjectURL(clientInspectionDownload);
    clientInspectionDownload = URL.createObjectURL(new Blob([json(observed)], {type: "application/json"}));
    state.clientInspection = observed;
    result.innerHTML = '<a href="#client-inspection-report">Consulta disponible en el espacio de trabajo</a>';
    render();
    $("#client-inspection-report").scrollIntoView({block:"start"});
  } catch (error) {
    result.textContent = error.message;
  } finally {
    result.removeAttribute("aria-busy");
    button.disabled = false;
  }
}
const state = {
  projects: [],
  data: null,
  view: "artifacts",
  artifact: "",
  excerpt: null,
  engines: null,
  catalog: null,
  binaryCatalog: null,
  cutterSessions: null,
  cutterObservation: null,
  runtimeCatalog: null,
  analysisPage: null,
  analysisRecord: null,
  webSourceChoices: null,
  clientInspection: null,
  showArchived: false,
  busy: false,
  sequence: 0,
  drafts: {},
};
try {
  state.drafts = JSON.parse(localStorage.getItem("theseus:drafts") || "{}");
} catch {}
const labels = {
  artifacts: "Artefactos",
  analyses: "Análisis",
  binary: "Binarios",
  findings: "Hallazgos",
  specification: "Especificación",
  scenarios: "Escenarios",
  reconstruction: "Reconstrucción",
  jobs: "Ejecuciones",
};
const statusLabels = {
  queued: "En cola",
  running: "En curso",
  finished: "Terminada",
  failed: "Error",
  cancelled: "Cancelada",
  interrupted: "Interrumpida",
  imported: "Evidencia importada",
};
const sectionLabels = {
  artifact: "Artefacto", module: "Módulo", metadata: "Metadatos", identity_scope: "Identidad y alcance",
  cli_native: "Frontera CLI/nativa", module_refs: "Referencias a módulos", pinvoke_imports: "Importaciones P/Invoke",
  native_implementations: "Implementaciones nativas", summary: "Resumen", coverage: "Cobertura", limitations: "Limitaciones",
  signature_resolution: "Resolución de firmas", types: "Tipos", nesting_read: "Tipos anidados", exported_types: "Tipos exportados",
  fields: "Campos", methods: "Métodos e instrucciones", member_refs: "Referencias a miembros", call_edges: "Llamadas",
  field_accesses: "Accesos a campos", user_strings: "Cadenas de usuario", selection: "Selección analizada",
  pe: "Cabecera PE", classification: "Clasificación", assembly: "Ensamblado", target_frameworks: "Frameworks",
  references: "Referencias", resources: "Recursos", attributes: "Atributos",
};
const sectionLabel = key => sectionLabels[key] || key;
const binaryLabels = {
  get_navigation_context: "Contexto de navegación", inspect_address_context: "Contexto de una dirección",
  read_binary_inventory_summary: "Resumen del binario", inspect_native_load_image: "Imagen cargada y relocaciones",
  list_names: "Símbolos", list_procedures: "Funciones", list_segments: "Segmentos", list_strings: "Cadenas",
  address_name: "Nombre de una dirección", procedure_address: "Dirección de una función",
  resolve_containing_procedure: "Función que contiene una dirección", procedure_assembly: "Desensamblado de una función",
  procedure_callees: "Funciones llamadas", procedure_callers: "Funciones que llaman", procedure_info: "Información de función",
  procedure_pseudo_code: "Pseudocódigo", read_function_instructions: "Instrucciones de una función",
  read_function_byte_evidence: "Bytes de función y datos referenciados",
  procedure_references: "Referencias de una función", search_procedures: "Buscar funciones", search_strings: "Buscar cadenas",
  read_bytes: "Leer bytes de memoria", search_bytes: "Buscar bytes", address_to_file_offset: "Dirección a offset del archivo",
  inspect_native_data_type: "Tipo de datos", inspect_native_instruction: "Instrucción y referencias",
  resolve_native_call_targets: "Destinos de una llamada", xrefs: "Referencias a una dirección", analyze_function: "Dossier de función y p-code",
  annotate_native_function: "Anotar una función", set_address_name: "Nombrar una dirección", set_addresses_names: "Nombrar varias direcciones",
  list_documents: "Programa de la sesión", ping: "Estado del motor",
  current_document: "Documento activo", current_address: "Dirección seleccionada", current_procedure: "Función seleccionada",
  goto_address: "Ir a una dirección", next_address: "Dirección siguiente", prev_address: "Dirección anterior",
  comment: "Leer comentario", inline_comment: "Leer comentario en línea", set_comment: "Escribir comentario",
  set_inline_comment: "Escribir comentario en línea", list_bookmarks: "Marcadores", set_bookmark: "Guardar marcador",
  unset_bookmark: "Quitar marcador", get_call_graph: "Grafo de llamadas", trace_call_path: "Buscar camino de llamadas",
  batch_decompile: "Descompilar varias funciones", inspect_native_api: "Interfaz nativa de una función",
  trace_native_values: "Trazar valores entre funciones",
};
const parameterLabels = {procedure: "Función o dirección", address: "Dirección", length: "Número de bytes", pattern: "Patrón",
  mode: "Modo (literal o regex)", case_sensitive: "Distinguir mayúsculas", type: "Ruta de tipo en la base de análisis", limit: "Resultados por página",
  name: "Nombre de analista", names: "Direcciones y nombres · JSON", comment: "Comentario de función", inline_comment: "Comentario de instrucción",
  category: "Categoría", text: "Texto de la anotación", from_procedure: "Función de origen", to_procedure: "Función de destino",
  max_depth: "Profundidad máxima, opcional", procedures: "Funciones · lista JSON", query: "Opciones · JSON"};
const sessionLabels = {starting:"Abriendo",open:"Conectada",closing:"Guardando y cerrando",closed:"Cerrada",interrupted:"Interrumpida",failed:"Error",imported:"Evidencia importada"};
const projectId = () => state.data?.project.id || "";
const draft = (name, fallback = "") =>
  state.drafts[projectId()]?.[name] ?? fallback;
const attr = (name, fallback = "") => escape(draft(name, fallback));

async function api(path, body, method) {
  const response = await fetch("/theseus/api" + path, {
    method: method || (body === undefined ? "GET" : "POST"),
    headers: {
      "X-Hoard-Request": "1",
      ...(body === undefined ? {} : { "Content-Type": "application/json" }),
    },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
  const result = await response.json();
  if (!response.ok)
    throw new Error(
      typeof result.detail === "string"
        ? result.detail
        : json(result.detail || result),
    );
  return result;
}

function notice(message, error = false) {
  const banner = $("#notice");
  const copy = document.createElement("div");
  copy.className = "notice-copy";
  copy.textContent = error
    ? "No se pudo completar la operación. Revisa los datos y vuelve a intentarlo."
    : message;
  if (error) {
    const details = document.createElement("details");
    const summary = document.createElement("summary");
    const diagnostic = document.createElement("pre");
    summary.textContent = "Ver diagnóstico";
    diagnostic.textContent = message;
    details.append(summary, diagnostic);
    copy.append(details);
  }
  const close = document.createElement("button");
  close.type = "button";
  close.textContent = "Cerrar";
  close.setAttribute("aria-label", "Cerrar aviso");
  close.onclick = () => banner.replaceChildren();
  banner.replaceChildren(copy, close);
  banner.classList.toggle("error", error);
  banner.setAttribute("role", error ? "alert" : "status");
}

function keepDrafts() {
  try {
    localStorage.setItem("theseus:drafts", json(state.drafts));
  } catch {}
}

function clearDrafts(...names) {
  for (const name of names) delete state.drafts[projectId()]?.[name];
  keepDrafts();
}

async function act(run) {
  if (state.busy) return;
  state.busy = true;
  $("#workspace").setAttribute("aria-busy", "true");
  document.querySelectorAll("main button").forEach((button) => {
    button.disabled = true;
  });
  try {
    await run();
  } catch (error) {
    notice(error.message, true);
  } finally {
    state.busy = false;
    render();
  }
}

function route() {
  if (!state.data) return;
  history.replaceState(
    null,
    "",
    `#/projects/${projectId()}/${state.view}${state.artifact ? "/" + state.artifact : ""}`,
  );
  window.dispatchEvent(new CustomEvent("hoard:copilot-context-changed"));
}

async function load(id) {
  const sequence = ++state.sequence;
  const data = await api("/projects/" + id);
  if (sequence !== state.sequence) return;
  if (state.data?.project.id !== data.project.id) state.cutterObservation = null;
  state.data = data;
  if (!data.artifacts.some((row) => row.id === state.artifact)) {
    state.artifact = data.artifacts[0]?.id || "";
    state.excerpt = null;
  }
  route();
  render();
}

async function refresh() {
  const rows = await api("/projects");
  state.projects = rows.projects;
  if (projectId()) await load(projectId());
  else render();
}

function table(rows, columns) {
  if (!rows?.length)
    return '<p class="muted">No se han encontrado entradas en esta sección.</p>';
  return `<div class="data-table"><table><thead><tr>${columns.map(([key, label]) => `<th>${escape(label)}</th>`).join("")}</tr></thead><tbody>${rows.map((row) => `<tr>${columns.map(([key]) => `<td>${escape(typeof row[key] === "object" ? json(row[key]) : row[key])}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
}

function renderRail() {
  const projects = state.projects.filter(
    (row) => state.showArchived || !row.archived,
  );
  $("#project-list").innerHTML = projects.length
    ? projects
        .map(
          (row) =>
            `<button data-action="project" data-id="${row.id}" aria-current="${row.id === projectId()}">${escape(row.name)}${row.archived ? "<small>Archivado</small>" : ""}</button>`,
        )
        .join("")
    : '<p class="small">No hay proyectos. Crea uno para guardar archivos, observaciones y comparaciones.</p>';
}

// Stable IDs anchor job receipts even when a new execution is inserted above them.
function elementPath(element) {
  if (!(element instanceof Element)) return "";
  if (element.id) return "#" + CSS.escape(element.id);
  const parent = element.parentElement;
  if (!parent) return element.localName;
  const index = [...parent.children].indexOf(element) + 1;
  return elementPath(parent) + ` > :nth-child(${index})`;
}

function captureView() {
  const element = document.activeElement;
  return {
    focus: elementPath(element),
    selection: [
      element?.selectionStart,
      element?.selectionEnd,
      element?.selectionDirection,
    ],
    open: [...document.querySelectorAll("details[id][open]")].map(
      (el) => el.id,
    ),
    scroll: [
      ...document.querySelectorAll(".tabs, .data-table, .artifact-list, pre"),
    ]
      .filter((el) => el.scrollLeft || el.scrollTop)
      .map((el) => [elementPath(el), el.scrollLeft, el.scrollTop]),
    x: window.scrollX,
    y: window.scrollY,
  };
}

function restoreView(view) {
  for (const id of view.open) {
    const element = document.getElementById(id);
    if (element) element.open = true;
  }
  const focused = view.focus && document.querySelector(view.focus);
  if (focused) {
    focused.focus({ preventScroll: true });
    if (
      typeof focused.setSelectionRange === "function" &&
      view.selection[0] != null
    )
      focused.setSelectionRange(...view.selection);
  }
  for (const [selector, x, y] of view.scroll) {
    const element = document.querySelector(selector);
    if (element) {
      element.scrollLeft = x;
      element.scrollTop = y;
    }
  }
  window.scrollTo(view.x, view.y);
  revealSelectedTab();
}

function revealSelectedTab() {
  const tab = document.querySelector('.tabs [aria-selected="true"]');
  if (tab) {
    const rail = tab.parentElement;
    const box = tab.getBoundingClientRect(),
      bounds = rail.getBoundingClientRect();
    if (box.left < bounds.left) rail.scrollLeft -= bounds.left - box.left;
    else if (box.right > bounds.right)
      rail.scrollLeft += box.right - bounds.right;
  }
}

window.addEventListener("resize", revealSelectedTab);

function differenceLabel(diagnostic) {
  if (diagnostic === "stdout differs")
    return "La salida de los programas es distinta.";
  if (diagnostic === "stderr differs")
    return "Los mensajes de error son distintos.";
  if (diagnostic.startsWith("exit code"))
    return "Los códigos de retorno son distintos.";
  if (diagnostic.includes("expected"))
    return "El resultado no coincide con la salida esperada.";
  return "Los resultados difieren. Consulta el diagnóstico original en «Recibo reproducible».";
}

function renderClientInspection() {
  const observed = state.clientInspection;
  if (!observed) return "";
  const statuses = {ok:"Disponible", unavailable:"No disponible", error:"No se pudo consultar", timeout:"Consulta agotada", "nonzero-exit":"El lector devolvió un error", "changed-during-inspection":"El archivo cambió durante la consulta"};
  const names = {java:"Java",apktool:"Apktool",tshark:"TShark",capinfos:"capinfos",objdump:"GNU objdump"};
  const rows = observed.clients.map(client => {
    const version = (client.stdout.text || client.stderr.text).split(/\r?\n/).find(line=>line.trim()) || "Sin texto de versión";
    const source = {"bundled-default":"Ubicación predeterminada", "system-default":"Instalación del sistema", "selected-tshark-directory":"Junto al TShark seleccionado"}[client.selection.source] || client.selection.source || "Sin selección";
    return `<tr><td><strong>${escape(names[client.client] || client.client)}</strong><br>${escape(statuses[client.status] || client.status)}</td><td>${escape(version)}</td><td><code>${escape(client.selection.path || "Sin lector seleccionado")}</code><br><span class="small">${escape(source)}</span></td></tr>`;
  }).join("");
  const targets = observed.advertised_targets;
  const targetsView = !targets ? "" : targets.stdout ? `<h3>Formatos anunciados por el lector</h3><p>La lista describe los destinos BFD del lector instalado. La compatibilidad de un artefacto se comprueba al inspeccionarlo.</p>${targets.client_identity_consistent === false ? '<p class="warning">La identidad del lector cambió entre las consultas de versión y formatos. Consulta ambos diagnósticos.</p>' : ""}<p>Código de salida: ${escape(targets.exit_code)} · Finalización: ${targets.completion_status === "complete" ? "Completa" : "No confirmada"}</p><pre>${escape(targets.stdout.text)}</pre>${targets.stderr.text ? `<pre>${escape(targets.stderr.text)}</pre>` : ""}` : `<p class="warning">No se pudieron consultar los formatos: ${escape(targets.reason)}</p>`;
  return `<section id="client-inspection-report" class="reading"><div class="toolbar"><h2>Lectores instalados · ${escape({apktool:"Android",pcap:"Capturas",objdump:"Binarios"}[observed.family] || observed.family)}</h2><button data-action="dismiss-client-inspection">Cerrar consulta</button></div><p>Versiones consultadas sin abrir un artefacto. La consulta no demuestra que el lector pueda decodificar un archivo concreto.</p><table><thead><tr><th>Lector</th><th>Versión observada</th><th>Ruta y selección</th></tr></thead><tbody>${rows}</tbody></table>${targetsView}<p><a href="${escape(clientInspectionDownload)}" download="lectores-${escape(observed.family)}.json">Descargar consulta completa</a></p><details><summary>Diagnósticos y hashes</summary><pre>${escape(json(observed))}</pre></details></section>`;
}

function render() {
  const view = captureView();
  renderRail();
  const main = $("#workspace");
  main.removeAttribute("aria-busy");
  if (!state.data) {
    main.innerHTML =
      renderClientInspection() + '<section class="empty"><h1>Inspecciona un programa local</h1><p>Crea un proyecto con la pregunta que quieres resolver. Añade archivos, anota lo que encuentras y compara el comportamiento de una reconstrucción.</p><button class="primary" data-action="new-project">Crear proyecto</button></section>';
    return;
  }
  const p = state.data.project;
  main.innerHTML = `${renderClientInspection()}<div class="project-heading"><div><h1>${escape(p.name)}</h1><p class="muted">${escape(p.question || "Añade una pregunta para orientar la investigación.")}</p></div><div class="toolbar"><a class="button" href="/theseus/api/projects/${p.id}/export" download>Exportar proyecto</a><a class="button" href="/theseus/api/projects/${p.id}/evidence" download>Exportar evidencias</a><button data-action="archive">${p.archived ? "Restaurar" : "Archivar"}</button></div></div>
    ${state.data.evidence_import ? `<p class="small">Evidencias importadas. Los recibos conservan lo observado en origen; vuelve a ejecutar los escenarios para verificar el entorno actual. <a href="/theseus/api/projects/${p.id}/evidence/original" download>Descargar documento de origen</a>.</p>` : ""}
    <details id="project-editor"><summary>Editar proyecto</summary><form id="edit-project" class="reading"><label>Nombre<input name="name" data-draft="project-name" value="${attr("project-name", p.name)}" required></label><label>Pregunta<textarea name="question" data-draft="project-question" rows="2">${attr("project-question", p.question)}</textarea></label><button type="submit">Guardar proyecto</button></form></details>
    <nav class="tabs" role="tablist" aria-label="Secciones del proyecto">${Object.entries(
      labels,
    )
      .map(
        ([key, label]) =>
          `<button role="tab" id="tab-${key}" tabindex="${state.view === key ? 0 : -1}" aria-controls="section" aria-selected="${state.view === key}" data-action="tab" data-view="${key}">${label}${Array.isArray(state.data[key]) ? `<span>${state.data[key].length}</span>` : ""}</button>`,
      )
      .join(
        "",
      )}</nav><section id="section" role="tabpanel" aria-labelledby="tab-${state.view}">${renderSection()}</section>`;
  restoreView(view);
}

function renderSection() {
  if (state.view === "artifacts") return artifacts();
  if (state.view === "analyses") return nativeAnalyses();
  if (state.view === "binary") return binaryWorkspace();
  if (state.view === "findings") return findings();
  if (state.view === "specification")
    return `<form id="specification-form" class="reading"><label>Especificación de comportamiento<textarea class="mono specification" name="content" data-draft="specification" placeholder="Objetivo, entradas, salidas, errores, hallazgos que lo respaldan y preguntas pendientes…">${attr("specification", state.data.project.specification)}</textarea></label><p class="small">Se guarda como texto editable. Cita los identificadores de hallazgos y distingue lo observado de lo que queda por comprobar.</p><button class="primary" type="submit">Guardar especificación</button></form>`;
  if (state.view === "scenarios") return scenarios();
  if (state.view === "reconstruction") return reconstruction();
  return jobs();
}

const claimFields = ["id", "kind", "statement", "owner", "finding_ids", "scenario_ids", "depends_on", "resolution"];
const claimStatus = {verified:"Verificada con estos casos",different:"Se han observado diferencias",unknown:"Sin resolver",resolved:"Pregunta resuelta"};
function reconstruction() {
  const workflow = state.data.workflow || {claims:[],handoffs:[],oracle_jobs:[]};
  const commandScenarios=state.data.scenarios.filter(row=>!isRetainedKind(row.definition.kind));
  const options = (rows, key, label) => rows.map(row => `<option value="${escape(row.id)}" ${draft(key)===row.id?"selected":""}>${escape(label(row))}</option>`).join("");
  const links = (rows,key,label) => rows.length ? `<div class="claim-links">${rows.map(row=>`<label class="inline"><input type="checkbox" name="${key}" value="${escape(row.id)}" data-linkset="${key}" data-draft="claim-${key}" ${String(draft("claim-"+key)).split(",").map(value=>value.trim()).includes(row.id)?"checked":""}>${escape(label(row))}</label>`).join("")}</div>` : '<p class="small">No hay entradas disponibles para vincular.</p>';
  return `<div class="reading"><h2>Obligaciones y preguntas</h2>
    <p>${workflow.complete ? "Todas las obligaciones registradas tienen casos observados y un oráculo que detecta las perturbaciones guardadas." : "Relaciona cada comportamiento con sus escenarios y conserva las preguntas que faltan por resolver."}</p>
    <p class="small">La cobertura se refiere a los casos guardados. Una comparación coincidente no demuestra equivalencia para todas las entradas.</p>
    ${workflow.claims.map(row=>`<article class="record" id="claim-record-${escape(row.id)}"><h3>${escape(row.statement)}</h3><p><span class="status">${row.kind==="unknown"?"Pregunta":"Obligación"}</span> ${escape(claimStatus[row.status])}${row.owner?` · ${escape(row.owner)}`:""}</p>
      ${row.resolution?`<p>${escape(row.resolution)}</p>`:""}
      <p class="small">${row.evidence.length} casos coincidentes · ${row.unobserved.length} sin evidencia vigente · ${row.different.length} distintos · ${row.oracle_unchecked.length} sin prueba de sensibilidad.</p>
      <button data-action="edit-claim" data-id="${row.id}">Editar obligación o pregunta</button><details id="claim-${row.id}"><summary>Evidencias y dependencias</summary>${claimRelations(row)}<details><summary>Registro completo en JSON</summary><pre>${escape(json(row))}</pre></details></details></article>`).join("")}
    <form id="claim-form"><h3>${draft("claim-id")?"Editar obligación o pregunta":"Añadir obligación o pregunta"}</h3>
      <label>Tipo<select name="kind" data-draft="claim-kind"><option value="obligation">Obligación verificable</option><option value="unknown" ${draft("claim-kind")==="unknown"?"selected":""}>Pregunta abierta</option></select></label>
      <label>Comportamiento o pregunta<textarea name="statement" data-draft="claim-statement" rows="2" required>${attr("claim-statement")}</textarea></label>
      <label>Responsable<input name="owner" data-draft="claim-owner" value="${attr("claim-owner")}"></label>
      <fieldset><legend>Escenarios que lo comprueban</legend>${links(state.data.scenarios,"scenario_ids",row=>row.name)}</fieldset>
      <details id="claim-support"><summary>Vincular hallazgos y dependencias</summary><fieldset><legend>Hallazgos de apoyo</legend>${links(state.data.findings,"finding_ids",row=>row.observation)}</fieldset><fieldset><legend>Depende de estas obligaciones o preguntas</legend>${links(workflow.claims.filter(row=>row.id!==draft("claim-id")),"depends_on",row=>row.statement)}</fieldset></details>
      <label>Respuesta o aclaración<textarea name="resolution" data-draft="claim-resolution" rows="2">${attr("claim-resolution")}</textarea></label>
      <div class="toolbar"><button type="submit">Guardar obligación o pregunta</button>${draft("claim-id")?'<button type="button" data-action="new-claim">Cancelar edición</button>':""}</div>
    </form>
    <h2>Entrega al constructor</h2><p>Congela la especificación de comportamiento y las preguntas registradas. El documento descargable del constructor excluye los hallazgos del lector y las rutas de los artefactos; revisa que la especificación escrita describa comportamiento.</p>
    <form id="handoff-form"><label>Directorio del constructor<input name="builder_directory" data-draft="builder-directory" value="${attr("builder-directory")}" required></label><button type="submit">Crear entrega de especificación</button></form>
    ${workflow.handoffs.map(row=>`<article class="record"><h3>Entrega ${escape(new Date(row.created_at).toLocaleString("es"))}</h3><p class="small mono analysis-source">${escape(row.sha256)}</p><p>${row.specification_changed||row.claims_changed?"La especificación o las obligaciones han cambiado desde esta entrega.":"Conserva la especificación y las obligaciones actuales."}</p><a class="button" href="/theseus/api/projects/${projectId()}/handoffs/${row.id}?builder_only=true" download="behavior-handoff.json">Descargar especificación para construir</a></article>`).join("")}
    <h2>Probar el oráculo</h2><p>Indica implementaciones deliberadamente erróneas: por ejemplo, una constante distinta, una rama invertida y un índice fuera de frontera. Los programas se ejecutan con los escenarios de programas guardados; las capturas se comprueban sin volver al original.</p>
    <form id="oracle-form"><label>Perturbaciones de programas · lista JSON con nombre y argumentos<textarea name="variants" class="mono" data-draft="oracle-variants" rows="6" placeholder='[{"name":"constante incorrecta","candidate":["python","ruta/error.py"]}]' required>${attr("oracle-variants")}</textarea></label><button type="submit" ${!commandScenarios.length?"disabled":""}>Ejecutar prueba de sensibilidad</button></form>
    ${retainedOracleForm()}
    ${[...workflow.oracle_jobs].reverse().map(oracleJob).join("")}
    <h2>Verificar y reintentar</h2><form id="verify-form"><label>Especificación entregada<select name="handoff_id" data-draft="verify-handoff">${options(workflow.handoffs,"verify-handoff",row=>new Date(row.created_at).toLocaleString("es"))}</select></label><p class="small">Ejecuta los escenarios actuales y conserva el vínculo con la entrega elegida. Cada intento tiene un recibo nuevo en Ejecuciones.</p><button class="primary" type="submit" ${!workflow.handoffs.length||!state.data.scenarios.length?"disabled":""}>Verificar reconstrucción</button></form></div>`;
}

function claimRelations(claim) {
  const group=(title,ids,collection,action,label)=>`<dt>${title}</dt><dd>${ids.length?`<ul>${ids.map(id=>{
    const row=collection.find(item=>item.id===id);
    return `<li><button data-action="${action}" data-id="${escape(id)}">${escape(row?label(row):"Entrada no disponible")}</button></li>`;
  }).join("")}</ul>`:'Sin vínculos registrados.'}</dd>`;
  return `<dl class="claim-relations">${group("Escenarios",claim.scenario_ids,state.data.scenarios,"claim-scenario",row=>row.name)}
    ${group("Hallazgos",claim.finding_ids,state.data.findings,"claim-finding",row=>`${row.location} · ${row.observation}`)}
    ${group("Depende de",claim.depends_on,state.data.workflow.claims,"claim-dependency",row=>row.statement)}
    ${group("Ejecuciones coincidentes vigentes",[...new Set(claim.evidence.map(row=>row.job_id))],state.data.jobs,"claim-job",row=>new Date(row.created_at).toLocaleString("es"))}</dl>`;
}

function oracleJob(job) {
  const data=job.result;
  return `<article class="record" id="job-${job.id}"><h3>Prueba del oráculo · ${escape(statusLabels[job.state]||job.state)}</h3>
    <p>${data.detected.length} defectos detectados · ${data.survived.length} no detectados · ${data.invalid.length} sin observación válida.</p>
    ${data.survived.length?`<p class="warning">El oráculo acepta estas implementaciones erróneas: ${escape(data.survived.join(", "))}. Amplía los escenarios y vuelve a probar.</p>`:""}
    ${data.error?`<p class="error">${escape(data.error)}</p>`:""}
    ${["queued","running"].includes(job.state)?`<button data-action="cancel-job" data-id="${job.id}">Cancelar prueba</button>`:""}
    <details id="oracle-${job.id}"><summary>Entradas, referencias y resultados de cada perturbación</summary><pre>${escape(json(job))}</pre></details></article>`;
}

function retainedOracleForm() {
  const cases=state.data.scenarios.filter(row=>isRetainedKind(row.definition.kind));
  if(!cases.length)return '';
  const chosen=draft('retained-oracle-scenario')||cases[0].id;
  const kind=(cases.find(row=>row.id===chosen)||cases[0]).definition.kind;
  return `<h3>Probar una perturbación guardada</h3><p>Elige un escenario y la captura de una reconstrucción deliberadamente errónea con los mismos pasos. Una captura incompleta o con peticiones distintas queda inválida y no cuenta como defecto detectado.</p>
    <form id="retained-oracle-form"><label>Escenario guardado<select id="retained-oracle-scenario" name="scenario_id" data-draft="retained-oracle-scenario" required>${cases.map(row=>`<option value="${escape(row.id)}" ${row.id===chosen?'selected':''}>${escape(row.name)}</option>`).join('')}</select></label>
    <label>Defecto introducido<input name="name" data-draft="retained-oracle-name" value="${attr('retained-oracle-name')}" placeholder="Por ejemplo: devolver una constante" required></label>
    ${captureSelect('Captura de la perturbación','candidate_job_id','retained-oracle-candidate','',kind)}
    <button type="submit">Probar perturbación guardada</button></form>`;
}

function artifacts() {
  const artifact = state.data.artifacts.find(
    (row) => row.id === state.artifact,
  );
  return `<form id="artifact-form" class="source-form"><label>Ruta de un archivo o directorio local<input name="path" data-draft="artifact-path" value="${attr("artifact-path")}" placeholder="C:\\ruta\\programa.exe o archivo de código" required></label><button class="primary" type="submit">Inspeccionar artefacto</button><button type="button" data-action="upload">Subir archivo</button><input id="upload-file" type="file" hidden></form>
    ${!artifact ? '<section class="empty"><h2>Añade el primer artefacto</h2><p>Admite ejecutables PE, código Python y JavaScript, capturas HAR, source maps, ZIP, ASAR, bases SQLite y archivos de texto. El análisis de archivos no los ejecuta.</p></section>' : `<div class="inspection"><nav class="artifact-list" aria-label="Artefactos del proyecto">${state.data.artifacts.map((row) => `<button data-action="artifact" data-id="${row.id}" aria-current="${row.id === state.artifact}">${escape(row.name)}<small>${escape(row.inspection.format)} · ${row.size.toLocaleString("es")} bytes</small></button>`).join("")}</nav><div>${inspect(artifact)}</div></div>`}`;
}

function inspect(artifact) {
  const data = artifact.inspection;
  const observed =
    data.symbols ||
    data.sections ||
    data.requests ||
    data.members ||
    data.observations;
  let body = `<h2>${escape(artifact.name)}</h2><dl class="file-meta"><dt>Formato</dt><dd>${escape(data.format)}</dd><dt>Ruta</dt><dd>${escape(artifact.path)}</dd><dt>SHA-256</dt><dd class="mono">${escape(artifact.sha256)}</dd><dt>Inspección</dt><dd>${data.format === "directory" ? `${data.members.length} entradas; hash del inventario de rutas y contenidos.` : `${data.bytes_inspected.toLocaleString("es")} de ${data.size.toLocaleString("es")} bytes de vista previa; hash del archivo completo.`}</dd></dl>`;
  if(data.format==="png") body+=`<img class="artifact-image" src="/theseus/api/projects/${encodeURIComponent(projectId())}/artifacts/${encodeURIComponent(artifact.id)}/image" alt="Imagen del artefacto ${escape(artifact.name)}"><a href="/theseus/api/projects/${encodeURIComponent(projectId())}/artifacts/${encodeURIComponent(artifact.id)}/image" download="${escape(artifact.name)}">Descargar PNG</a>`;
  const related=(state.data.artifact_links||[]).filter(row=>row.parent_id===artifact.id||row.child_id===artifact.id);
  if(related.length) body+=`<h3>Procedencia y artefactos extraídos</h3><ul>${related.map(link=>{
    const other=state.data.artifacts.find(row=>row.id===(link.parent_id===artifact.id?link.child_id:link.parent_id));
    return `<li>${link.parent_id===artifact.id?"Extraído":"Origen"}: ${other?`<button data-action="artifact" data-id="${other.id}">${escape(other.name)}</button>`:"Referencia no disponible"} · ${escape(link.source_location)}</li>`;
  }).join("")}</ul>`;
  if (data.preview_truncated)
    body +=
      '<p class="warning">La vista previa está truncada. Lee fragmentos del archivo para seguir inspeccionándolo.</p>';
  body += data.warnings
    .map((text) => `<p class="warning">${escape(text)}</p>`)
    .join("");
  if (data.headers)
    body += `<h3>Cabecera PE</h3>${table(
      [data.headers],
      [
        ["machine", "Máquina"],
        ["image_base", "Base"],
        ["entry_rva", "Entrada RVA"],
        ["managed", "CLR/.NET"],
      ],
    )}`;
  if (data.symbols)
    body += `<h3>Definiciones</h3>${table(observed, [
      ["name", "Nombre"],
      ["kind", "Tipo"],
      ["line", "Línea"],
      ["end_line", "Fin"],
    ])}`;
  else if (data.sections)
    body += `<h3>Secciones</h3>${table(data.sections, [
      ["name", "Sección"],
      ["offset", "Offset"],
      ["size", "Bytes"],
      ["rva", "RVA"],
      ["entropy", "Entropía"],
    ])}`;
  else if (data.requests)
    body += `<h3>Tráfico capturado</h3>${table(data.requests, [
      ["method", "Método"],
      ["url", "URL"],
      ["status", "Estado"],
      ["location", "Ubicación"],
    ])}<p class="small">Se lee la captura guardada; no se solicita ninguna de estas URL.</p>`;
  else if (data.format === "directory")
    body += `<h3>Contenido del directorio</h3>${table(data.members, [["name","Ruta"],["kind","Tipo"],["size","Bytes"],["sha256","SHA-256"]])}`;
  else if (data.observations.length)
    body += `<h3>Estructura</h3>${table(data.observations, [
      ["kind", "Tipo"],
      ["name", "Nombre"],
      ["text", "Definición"],
    ])}`;
  if (data.imports?.length)
    body += `<details><summary>Importaciones (${data.imports.length})</summary><pre>${escape(json(data.imports))}</pre></details>`;
  if (data.calls?.length)
    body += `<details><summary>Llamadas observadas en la sintaxis (${data.calls.length})</summary>${table(
      data.calls,
      [
        ["target", "Destino"],
        ["line", "Línea"],
        ["certainty", "Certeza"],
      ],
    )}</details>`;
  if (data.sources)
    body += `<h3>Fuentes del source map</h3><pre>${escape(json(data.sources))}</pre><details><summary>Nombres y contenido incorporado</summary><pre>${escape(json({ names: data.names, sourcesContent: data.sources_content }))}</pre></details>`;
  if (data.strings) {
    const query = String(draft("string-query")).toLowerCase();
    const strings = data.strings.filter(
      (row) => !query || row.text.toLowerCase().includes(query),
    );
    const page = Math.min(
      Number(draft("string-page", 0)),
      Math.max(0, Math.ceil(strings.length / 100) - 1),
    );
    body += `<h3>Cadenas del binario</h3><form id="strings-filter" class="string-filter"><label>Buscar cadena<input id="string-query" data-draft="string-query" value="${escape(query)}" type="search"></label><button type="submit">Filtrar</button></form><p class="small">${strings.length.toLocaleString("es")} coincidencias · página ${page + 1} de ${Math.max(1, Math.ceil(strings.length / 100))}</p>${table(
      strings.slice(page * 100, (page + 1) * 100),
      [
        ["offset", "Offset"],
        ["encoding", "Codificación"],
        ["text", "Cadena"],
      ],
    )}<div class="toolbar"><button data-action="strings-page" data-page="${Math.max(0, page - 1)}" ${page === 0 ? "disabled" : ""}>Anterior</button><button data-action="strings-page" data-page="${page + 1}" ${(page + 1) * 100 >= strings.length ? "disabled" : ""}>Siguiente</button></div>`;
  }
  if (["pe", "binary"].includes(data.format)) body += binaryAnalysis(artifact);
  const current =
    state.excerpt?.artifact_id === artifact.id ? state.excerpt : null;
  body += `<h3>Leer contenido</h3><form id="excerpt-form" class="excerpt-form">${data.members ? `<label class="member">Miembro del archivo<select name="member"><option value="">${data.format === "directory" ? "Elige un archivo" : "Archivo completo"}</option>${data.members.filter(row => data.format !== "directory" || row.kind === "file").map((row) => `<option value="${escape(row.name)}" ${current?.member === row.name ? "selected" : ""}>${escape(row.name)} (${row.size} bytes)</option>`).join("")}</select></label>` : ""}<label>Offset<input name="offset" type="number" min="0" value="${current?.offset || 0}"></label><label>Bytes<input name="length" type="number" min="0" value="4096"></label><button type="submit">Leer fragmento</button></form>`;
  if (current)
    body += `${current.source_changed ? '<p class="warning">El archivo ha cambiado desde su inspección. El hash registrado conserva la identidad de la evidencia anterior. Inspecciónalo de nuevo para crear otra observación.</p>' : ""}<pre>${escape(current.text)}</pre><button data-action="cite-excerpt">Usar fragmento como observación</button>`;
  body += `<form id="finding-form" class="finding-form"><input type="hidden" name="source_sha256" value="${attr("finding-source-sha256", artifact.sha256)}"><h3>Guardar hallazgo</h3><label>Ubicación en el artefacto<input name="location" data-draft="finding-location" value="${attr("finding-location")}" placeholder="Línea 42, offset 0x120 o log.entries[3]" required></label><label>Observación<textarea name="observation" data-draft="finding-observation" rows="3" required>${attr("finding-observation")}</textarea></label><label>Interpretación o hipótesis<textarea name="interpretation" data-draft="finding-interpretation" rows="2">${attr("finding-interpretation")}</textarea></label><button type="submit">Guardar hallazgo</button></form><details id="artifact-json"><summary>Inspección completa en JSON</summary><pre>${escape(json(data))}</pre></details>`;
  return body;
}

function binaryAnalysis(artifact) {
  const data = artifact.inspection;
  const analyses = state.data.jobs.filter(
    (job) =>
      job.result.kind === "binary_analysis" &&
      job.result.artifact_id === artifact.id,
  );
  const active = analyses.find((job) =>
    ["queued", "running"].includes(job.state),
  );
  const latest = [...analyses]
    .reverse()
    .find((job) => job.state === "finished");
  const functions = latest?.result.analysis.functions || [];
  const selected =
    functions.find((row) => row.address === draft("function-" + artifact.id)) ||
    functions[0];
  let body = `<section class="binary-analysis"><div class="section-title"><h2>Funciones del binario</h2><button data-action="analyze" ${!state.engines?.available ? "disabled" : ""}>Analizar con Ghidra local</button></div><p class="small">${state.engines?.available ? "Motor instalado y disponible sin conexión." : "Instala un motor Ghidra local y configura sus rutas siguiendo el README."} La descompilación es una reconstrucción estática; conserva sus inferencias y el hash del archivo.</p>`;
  if (data.headers?.managed)
    body +=
      '<p class="warning">Este PE contiene CLR/.NET. El análisis de Ghidra cubre sus instrucciones nativas; no equivale a recuperar el código C# original.</p>';
  if (active)
    body +=
      '<p role="status">Análisis en curso. Puedes seguir trabajando y consultar su estado en Ejecuciones.</p>';
  if (
    latest?.result.source_changed ||
    latest?.result.source_changed_during_analysis
  )
    body +=
      '<p class="warning">La fuente cambió respecto a la inspección guardada. Consulta en el recibo el hash exacto de esta ejecución.</p>';
  if (selected) {
    body += `<label>Función (${functions.length})<select id="binary-function">${functions.map((row) => `<option value="${escape(row.address)}" ${selected.address === row.address ? "selected" : ""}>${escape(row.address)} · ${escape(row.name)}</option>`).join("")}</select></label><p class="mono">${escape(selected.signature)}</p><pre>${escape(selected.code || selected.error || "Función externa sin cuerpo disponible.")}</pre>`;
    const callers = functions.filter((row) =>
      row.calls?.some((call) => call.address === selected.address),
    );
    const links = (rows) =>
      rows.length
        ? `<div class="toolbar">${rows.map((row) => (functions.some((f) => f.address === row.address) ? `<button data-action="function" data-address="${escape(row.address)}">${escape(row.name)} · ${escape(row.address)}</button>` : `<span class="small">${escape(row.name)} · ${escape(row.address)}</span>`)).join("")}</div>`
        : '<p class="muted">No se han resuelto relaciones en esta dirección.</p>';
    body += `<h3>Llama a</h3>${links(selected.calls || [])}<h3>Llamada por</h3>${links(callers)}<button data-action="cite-function" data-job="${latest.id}" data-address="${escape(selected.address)}">Usar función como observación</button>`;
  }
  return body + "</section>";
}

function nativeAnalyses() {
  const operations = state.catalog?.operations || [];
  const selected = operations.find(row => row.name === draft("analysis-operation")) || operations[0];
  const runs = [...state.data.jobs].reverse().filter(row => row.result.kind === "native_analysis");
  const saved = [...state.data.jobs].reverse().filter(row => ["native_analysis", "runtime_analysis"].includes(row.result.kind));
  const pair = selected?.input === "pair";
  const setInput = selected?.input === "set";
  const derived = selected?.input === "analysis" || pair || setInput;
  const sourceStates=selected?.source_states || ["finished"], candidateStates=selected?.candidate_states || sourceStates;
  const sourceOps=[selected?.requires_operation].flat(),candidateOps=[selected?.candidate_requires_operation || selected?.requires_operation].flat();
  const sources = saved.filter(row => sourceStates.includes(row.state) && row.result.analysis_sha256 && (!selected?.requires_operation || sourceOps.includes(row.result.operation)));
  const candidateSources = saved.filter(row => candidateStates.includes(row.state) && row.result.analysis_sha256 && candidateOps.includes(row.result.operation));
  const targetPicker = setInput
    ? `<fieldset><legend>Análisis guardados del conjunto</legend>${sources.map(row=>`<label class="inline"><input type="checkbox" name="source_job_ids" value="${escape(row.id)}" data-draft="analysis-set-${selected.name}-${row.id}" ${draft("analysis-set-"+selected.name+"-"+row.id,false)?"checked":""}>${escape(row.result.artifact_name)} · ${escape(row.result.title||row.result.operation)}${row.result.operation==="binary.analyze_function"?" · "+escape(row.result.parameters?.procedure||"dirección no declarada"):""} · ${escape(statusLabels[row.state]||row.state)} · SHA ${escape(row.result.analysis_sha256)} · ${row.id.slice(0,8)}</label>`).join("")}${!sources.length?'<p class="warning">Guarda primero los análisis del tipo indicado.</p>':""}</fieldset><p class="small">Elige uno o varios documentos. Se conservan sus bytes y hashes; las referencias guardadas se incluyen en el cierre sin consultar las rutas originales.</p>`
    : pair
    ? ["reference", "candidate"].map(side=>{
      const choices=side === "reference"?sources:candidateSources;
      const mixed=(side==="reference"?sourceOps:candidateOps).length>1;
      return `<label>${side === "reference" ? "Análisis de referencia" : "Análisis candidato"}<select name="${side}_job_id" data-draft="analysis-${side}-${selected.name}">${choices.map(row=>`<option value="${row.id}" ${draft("analysis-"+side+"-"+selected.name,side === "reference" ? choices.at(-1)?.id : choices[0]?.id)===row.id?"selected":""}>${escape(row.result.artifact_name)}${row.result.operation==="binary.analyze_function"?" · "+escape(row.result.parameters?.procedure||"dirección no declarada"):""}${mixed?" · "+escape(row.result.title||row.result.operation):""}${row.state==="finished"?"":" · "+escape(statusLabels[row.state]||row.state)} · SHA ${escape(row.result.analysis_sha256?.slice(0,12))} · ${new Date(row.created_at).toLocaleString("es")} · ${row.id.slice(0,8)}</option>`).join("")}</select></label>`;
    }).join("") + (!sources.length || !candidateSources.length ? '<p class="warning">Primero guarda los análisis de referencia y candidato del tipo indicado para poder compararlos.</p>' : "")
    : derived
    ? `<label>Análisis de origen<select id="analysis-source-job" name="source_job_id" data-draft="analysis-source-job">${sources.map(row => `<option value="${row.id}" ${draft("analysis-source-job") === row.id ? "selected" : ""}>${escape(row.result.artifact_name)} · ${new Date(row.created_at).toLocaleString("es")} · ${row.id.slice(0,8)}</option>`).join("")}</select></label>${!sources.length ? '<p class="warning">Primero guarda un análisis del tipo indicado. La consulta reutiliza sus observaciones guardadas.</p>' : ""}`
    : `<label>Artefacto<select name="artifact_id" data-draft="analysis-artifact">${state.data.artifacts.map(row => `<option value="${row.id}" ${draft("analysis-artifact", state.artifact) === row.id ? "selected" : ""}>${escape(row.name)}</option>`).join("")}</select></label>`;
  const parameterDraft = "analysis-parameters-" + selected?.name;
  const source = sources.find(row=>row.id===draft("analysis-source-job")) || sources[0];
  const webTrace = ["javascript.trace_source", "javascript.trace_imports"].includes(selected?.name);
  const webChoices = source && state.webSourceChoices?.job_id===source.id && state.webSourceChoices.sha256===source.result.analysis_sha256 ? state.webSourceChoices : null;
  let body = `<div class="reading"><h2>Análisis estático local</h2><p>Inspecciona archivos y aplicaciones con ubicaciones originales, o consulta los análisis guardados. El análisis estático no ejecuta el programa.</p>`;
  if (!state.data.artifacts.length) return body + '<p>Añade un archivo desde Artefactos para analizarlo.</p><button data-action="tab" data-view="artifacts">Añadir artefacto</button></div>';
  body += `<form id="native-analysis-form">
    <label>Operación<select id="analysis-operation" name="operation" data-draft="analysis-operation">${operations.map(row => `<option value="${escape(row.name)}" ${row.name === selected?.name ? "selected" : ""}>${escape(row.title)}</option>`).join("")}</select></label>
    <p class="small">${escape(selected?.description)}</p>${selected?.available === false ? '<p class="warning">'+escape(selected.availability_reason || 'Requiere '+selected.platforms?.join(", "))+'</p>' : ""}${targetPicker}
    ${webTrace ? webSourceFields(source, selected.name, webChoices) : ""}
    <details id="analysis-parameters" ${derived && selected?.example && !webTrace ? "open" : ""}><summary>${webTrace ? "Contexto adicional · JSON" : "Parámetros de la operación"}</summary>
      <label>Parámetros JSON<textarea class="mono" name="parameters" data-draft="${escape(parameterDraft)}" rows="6">${attr(parameterDraft, json(selected?.example || {}))}</textarea></label>
      <pre>${escape(json(selected?.inputSchema))}</pre>
    </details>
    <button class="primary" type="submit" ${selected?.available === false || (!state.catalog?.engine.available && selected?.worker !== "python") || (derived && !sources.length) || (pair && !candidateSources.length) || (webTrace && !webChoices?.entries.some(row=>row.kind!=="inline-source-map" && row.state==="captured")) ? "disabled" : ""}>${pair ? "Comparar análisis guardados" : derived ? "Consultar análisis guardado" : "Iniciar análisis"}</button>
    ${!state.catalog?.engine.available && selected?.worker !== "python" ? '<p class="warning">El núcleo de análisis no está compilado. Ejecuta Install.ps1 y vuelve a abrir esta página.</p>' : ""}
  </form><h2>Análisis guardados</h2>`;
  body += runs.length ? runs.map(job => nativeAnalysisJob(job)).join("") : '<p class="muted">Todavía no hay análisis nativos en este proyecto.</p>';
  body += analysisBrowser(runs);
  return body + '</div>';
}

function webSourceFields(source, operation, choices) {
  if(!source) return "";
  if(!choices) return `<button type="button" data-action="load-web-sources" data-id="${source.id}">Cargar fuentes del análisis</button><p class="small">Carga el manifiesto guardado para seleccionar sus scripts y mapas.</p>`;
  const scripts=choices.entries.filter(row=>row.kind!=="inline-source-map");
  const maps=choices.entries.filter(row=>row.kind!=="page-script");
  const picker=(rows,name,label)=>`<label>${label}<select name="web-${name}" data-draft="web-${name}-${source.id}" required><option value="">Seleccionar…</option>${rows.map(row=>`<option value="${escape(row.id)}" ${row.state!=="captured"?"disabled":""} ${draft("web-"+name+"-"+source.id)===row.id?"selected":""}>${escape(row.kind==="inline-source-map"?"Mapa incrustado de "+row.script_entry_id:row.url||"Script sin URL")} · ${escape(row.id)}${row.state==="captured"?"":" · "+escape(row.state)}</option>`).join("")}</select></label>`;
  let body=picker(scripts,"script","Script guardado");
  if(!scripts.some(row=>row.state==="captured")) body+='<p class="warning">Esta exportación no contiene scripts capturados. Selecciona una captura que incluya sus fuentes y vuelve a exportarla.</p>';
  if(operation==="javascript.trace_source") {
    body+=picker(maps,"map","Mapa o respuesta guardada")+
      `<label>Línea generada<input type="number" name="web-line" min="1" step="1" required data-draft="web-line" value="${attr("web-line",1)}"></label><label>Columna generada · UTF-16<input type="number" name="web-column" min="0" step="1" required data-draft="web-column" value="${attr("web-column",0)}"></label><p class="small">La línea empieza en 1 y la columna en 0. La selección del mapa declara una correspondencia; no acredita qué se desplegó.</p>`;
  } else body+='<p class="small">Se usa la URL guardada del script. Puedes indicar importer_url, import_map e import_map_base_url en el contexto adicional.</p>';
  return body;
}

function analysisBrowser(runs) {
  let body = '';
  const page = state.analysisPage;
  const active = page && runs.find(job => job.id === page.job_id);
  if (active) {
    const contextFacets = page.section === "facets" && ["binary.get_navigation_context", "binary.inspect_address_context"].includes(active.result.operation);
    body += `<section id="analysis-browser"><h2>${escape(sectionLabel(page.section))} · ${escape(active.result.artifact_name)}</h2><form id="analysis-search"><label>Buscar por nombre<input type="search" name="query" data-draft="analysis-query" value="${attr("analysis-query")}"></label><button type="submit">Buscar registros</button></form><p class="small">${page.total} registros · desde ${page.offset + (page.records.length ? 1 : 0)}</p><p class="small mono analysis-source">${active.result.kind==="runtime_analysis"?"SHA-256 de la captura JSON":"SHA-256"} ${escape(page.artifact_sha256)}</p><div class="toolbar">${page.records.map(row => `<button data-action="analysis-record" data-key="${escape(row.record_key)}">${contextFacets ? "Facetas observadas" : `${escape(row.name)} · ${escape(row.record_key)}`}</button>`).join("")}</div>${page.total === 0 ? '<p class="muted">No hay registros que coincidan con esta búsqueda.</p>' : ""}<div class="toolbar"><button data-action="analysis-page" data-offset="${Math.max(0, page.offset - 50)}" ${page.offset === 0 ? "disabled" : ""}>Anterior</button><button data-action="analysis-page" data-offset="${page.offset + 50}" ${!page.has_more ? "disabled" : ""}>Siguiente</button></div>`;
    const record = state.analysisRecord;
    if (record?.job_id === page.job_id && record?.section === page.section) body += analysisRecordView(record, contextFacets);
    body += '</section>';
  }
  return body;
}

function nativeAnalysisJob(job) {
  const result = job.result;
  const sections = Object.entries(result.sections || {});
  const runtime=result.kind==="runtime_analysis";
  const problem=runtime?"La captura no terminó. Consulta el diagnóstico en el recibo; el destino puede haber recibido cambios.":"El análisis no terminó. Consulta el diagnóstico en el recibo y revisa el archivo o sus parámetros.";
  const outcome={observed:"Observación guardada", "command-error":"El comando informó de un error", "observation-error":"Observación incompleta", "refused-or-unknown":"El sistema no confirmó la solicitud", "destination-exists":"El archivo de destino ya existe", "not-png":"El cliente no devolvió un PNG", "launcher-unresolved":"No se resolvió una actividad de inicio"}[result.observation_status];
  const reader = result.reader_observation;
  const readerMessage = !reader ? "" : reader.completion_status !== "complete" ? '<p class="warning">Lectura incompleta · se conserva el prefijo observado.</p>' : `<p class="${reader.exit_code ? "warning" : "small"}">GNU objdump · código de salida ${escape(reader.exit_code)}${reader.exit_code ? ". Consulta el diagnóstico original del lector." : ""}</p>`;
  const command=result.command_observation;
  const commandMessage=!command?"":`<p class="${command.completion_status!=="complete"||command.exit_code?"warning":"small"}">${command.completion_status!=="complete"?"Finalización de la orden desconocida · se conserva el prefijo observado. No repitas la orden para recuperar su respuesta.":`Orden observada · código de salida ${escape(command.exit_code)}. La respuesta no certifica su efecto.`}${command.output_truncated?" La salida excedió los 16 MiB combinados.":""}${command.artifact_changed===true?" El archivo original ha cambiado.":""} Los efectos realizados persisten.</p>`;
  const wasm=result.wasm_observation;
  const wasmMessage=!wasm||wasm.validators_agree!==false?"":`<p class="warning">Los validadores no coinciden: ${wasm.validation==="valid"?"WABT lo valida, pero el validador del runtime lo rechaza":"el validador del runtime lo acepta, pero WABT no pudo leerlo ni validarlo"}. Consulta host_validation.</p>`;
  const coverage=result.operation==="browser.coverage"?result.progress:null;
  const coverageMessage=!coverage?"":!["queued","running","finished"].includes(job.state)?"La medición se interrumpió. El recibo conserva la última fase. "+(coverage.cleanup==="confirmed"?"El cierre del perfilador fue confirmado.":"No se confirmó el cierre del perfilador."):({armed:"Armada. Ya puedes realizar las acciones externas en la página seleccionada.",sampling:"La ventana ha terminado. Se están recogiendo la muestra y sus fuentes.",ended:"La muestra y sus fuentes están guardadas; el cierre del perfilador fue confirmado.",incomplete:"La ventana no terminó sobre el mismo documento. Consulta el prefijo y su diagnóstico."}[coverage.state]||"");
  return `<article class="record" id="job-${job.id}"><div class="job-head"><h3>${escape(result.title)} · ${escape(result.artifact_name)}</h3><span class="status">${statusLabels[job.state] || escape(job.state)}</span>${["queued", "running"].includes(job.state) ? `<button data-action="cancel-job" data-id="${job.id}">Cancelar ${runtime?"cliente":"análisis"}</button>` : ""}</div>${readerMessage}${commandMessage}${wasmMessage}${coverageMessage?`<p>${escape(coverageMessage)}</p><p class="small mono">${coverage.armed_at?"Armada: "+escape(coverage.armed_at):""}</p>`:""}${runtime && outcome?`<p>${escape(outcome)}${result.verdict==="success"?". El sistema aceptó la solicitud.":""}</p>`:""}${result.error ? `<p class="error">${problem}</p>` : ""}${result.source_changed || result.source_changed_during_analysis ? '<p class="warning">La fuente ha cambiado. El recibo identifica los bytes analizados por su hash.</p>' : ""}${result.derived_artifacts?.length ? `<h4>Archivos derivados</h4><div class="toolbar">${result.derived_artifacts.map(row => `<button data-action="artifact" data-id="${row.id}">${escape(row.name)}</button>`).join("")}</div>` : ""}${sections.length ? `<form data-analysis-job="${job.id}" class="analysis-section-form"><label>Sección del análisis<select name="section" data-draft="analysis-section-${job.id}">${sections.map(([section,count]) => `<option value="${escape(section)}" ${draft("analysis-section-" + job.id) === section ? "selected" : ""}>${escape(sectionLabel(section))} (${count})</option>`).join("")}</select></label><button type="submit">Consultar registros</button></form>` : ""}${result.analysis_file ? `<a class="button" href="/theseus/api/jobs/${job.id}/analysis.json" download>Descargar análisis completo</a>` : ""}<details id="receipt-${job.id}"><summary>Recibo y salida del motor</summary><pre>${escape(json(job))}</pre></details></article>`;
}

function analysisRecordView(record, contextFacets = false) {
  const data = record.record;
  const instructions = data?.body?.instructions;
  const terminal=record.section==="terminal"&&data?.rendered?.final;
  let sourceLines = (record.sources || []).map(source=>`<p class="small mono analysis-source">${escape(source.kind === "runtime-observation" ? "Captura en ejecución" : source.side === "candidate" ? "Candidato" : source.side === "reference" ? "Referencia" : "Fuente")} · ${escape(source.sha256)}</p>`).join("");
  if(record.section.startsWith("trace.") && data?.evidence_id) sourceLines += `<button data-action="analysis-evidence" data-evidence="${escape(data.evidence_id)}">Consultar evidencia de origen</button>`;
  if(record.section.startsWith("verification.") && Array.isArray(data?.evidence_links)) sourceLines += data.evidence_links.map((id,index)=>`<button data-action="analysis-evidence" data-evidence="${escape(id)}">Consultar evidencia de origen ${index+1}</button>`).join("");
  return sourceLines + `<h3>${contextFacets ? "Facetas observadas" : `${escape(data?.name || "Registro")} · ${escape(record.record_key)}`}</h3>${terminal?processTerminalView(data):''}${instructions ? `<p class="mono analysis-source">${escape(data.declaring_type)} · ${escape(data.signature?.return_type)} (${escape((data.signature?.parameter_types || []).join(", "))})</p><h4>Instrucciones CIL (${instructions.length})</h4>${table(instructions, [["il_offset", "Offset IL"], ["opcode", "Instrucción"], ["operand", "Operando"], ["file_offset", "Offset de archivo"], ["bytes", "Bytes"]])}${data.body.exception_regions?.length ? `<h4>Regiones de excepción</h4>${table(data.body.exception_regions, [["flags", "Flags"], ["try_offset", "Inicio try"], ["try_length", "Bytes try"], ["handler_offset", "Inicio handler"], ["handler_length", "Bytes handler"], ["class_token", "Tipo"]])}` : ""}<details id="analysis-record-json"><summary>Registro completo en JSON</summary><pre>${escape(json(data))}</pre></details>` : terminal?`<details><summary>Bytes y fotogramas completos · JSON</summary><pre>${escape(json(data))}</pre></details>`:`<pre>${escape(json(data))}</pre>`}<button data-action="cite-analysis">Usar registro como observación</button>`;
}

async function readAnalysisPage(job, section, offset = 0, query = "") {
  state.analysisPage = await api(`/jobs/${job}/records/${encodeURIComponent(section)}?${new URLSearchParams({offset, limit: 50, query})}`);
  state.analysisRecord = null;
}

function processTerminalView(data) {
  const key='terminal-frame-'+data.raw_bytes.sha256;
  const frames=data.rendered.frames,chosen=draft(key)||'-1';
  const screen=chosen==='-1'?data.rendered.final:frames[Number(chosen)]||data.rendered.final;
  return `<section><h4>Terminal guardado · ${screen.columns} × ${screen.rows}</h4><label>Fotograma<select id="process-terminal-frame" data-draft="${escape(key)}"><option value="-1" ${chosen==='-1'?'selected':''}>Estado final</option>${frames.map((frame,index)=>`<option value="${index}" ${String(index)===chosen?'selected':''}>${index+1} · ${escape(frame.event_id)} · ${frame.columns} × ${frame.rows}</option>`).join('')}</select></label><p class="small">Buffer ${escape(screen.active_buffer)} · cursor ${screen.cursor_x}, ${screen.cursor_y}. Interpretación de los bytes VT guardados; no ejecuta el programa.</p><pre class="mono" aria-label="Contenido del terminal guardado">${escape(screen.lines.join('\n'))}</pre><p class="small mono">Bytes originales · SHA-256 ${escape(data.raw_bytes.sha256)}</p></section>`;
}

function cutterWorkspace() {
  const discovery = state.cutterSessions;
  const sessions = discovery?.sessions || [];
  const selected = sessions.find(row => row.session_id === draft('cutter-session')) || sessions[0];
  const observation = state.cutterObservation;
  return `<section id="cutter-workspace"><h2>Cutter · Sesión abierta</h2><p>Consulta y modifica una sesión local con órdenes Rizin. Instala el puente en el perfil de Cutter que quieras conectar y abre allí el archivo.</p>
    <div class="toolbar"><a class="button" href="/theseus/api/cutter/plugin.py" download>Descargar puente Python</a><button data-action="cutter-refresh">Buscar sesiones de Cutter</button></div>
    <details><summary>Instalar el puente</summary><p>Guarda <code>vitruvius_bridge.py</code> en la carpeta de plugins Python indicada por Cutter y reinicia ese editor. El puente usa PySide6 incluido en Cutter. La carpeta compartida predeterminada es <code>Vitruvius/cutter-bridge</code> dentro de los datos locales del usuario; ambos procesos pueden elegir otra con <code>THESEUS_CUTTER_BRIDGE_DIR</code>.</p><p>La identidad del documento es parcial: archivo y generación observados no equivalen a una huella de todos sus bytes. La consulta informa por separado del estado de la carpeta del puente.</p></details>
    ${discovery ? `<p class="small">${sessions.length ? `${sessions.length} sesiones disponibles.` : 'No se ha encontrado un puente activo. Comprueba la instalación y vuelve a buscar.'} <span class="mono">${escape(discovery.discovery_status)} · ${escape(discovery.bridge_directory_security)}</span></p>` : '<p class="muted">Busca las sesiones cuando quieras conectar. No se abre Cutter automáticamente.</p>'}
    ${selected ? `<form id="cutter-command-form"><label>Sesión de Cutter<select id="cutter-session" name="session_id" data-draft="cutter-session">${sessions.map(row => `<option value="${escape(row.session_id)}" ${row.session_id === selected.session_id ? 'selected' : ''}>${escape(row.current_file || 'Sin archivo observado')} · PID ${row.pid}</option>`).join('')}</select></label><p class="small">Cutter ${escape(selected.cutter_version)} · generación observada <strong>${selected.document_generation}</strong> · identidad parcial</p><input type="hidden" name="expected_generation" value="${selected.document_generation}"><label>Orden Rizin<input class="mono" name="command" data-draft="cutter-command" value="${attr('cutter-command')}" required autocomplete="off" placeholder="iIj"></label><label class="inline"><input type="checkbox" name="json" data-draft="cutter-json" ${draft('cutter-json',false) ? 'checked' : ''}>Interpretar la salida como JSON</label><p class="warning">La orden puede modificar archivos, ejecutar plugins o cambiar el editor. Si se pierde la respuesta, no se repite automáticamente.</p><button class="primary" type="submit">Enviar orden a Cutter</button></form>` : ''}
    ${observation ? `<div id="cutter-observation" role="status"><h3>Resultado de la orden</h3><p><code>${escape(observation.command)}</code></p><p>${escape({complete:'El motor ha respondido',failed:'La respuesta contiene un error',unknown:'Finalización desconocida',not_started:'La orden no se ha enviado al motor'}[observation.execution_state] || observation.execution_state)}</p>${observation.error ? `<p class="error">${escape(observation.error)}</p>` : ''}${observation.retention_error ? `<p class="error">No se ha podido conservar toda la observación. Consulta el estado de la ejecución; no repitas la orden automáticamente.</p>` : ''}<pre>${escape(typeof observation.output === 'string' ? observation.output : json(observation.output))}</pre><p class="small">${escape(observation.message)}</p>${observation.job_id && !observation.retention_error ? `<a href="/theseus/api/jobs/${observation.job_id}/analysis.json" download>Descargar observación conservada</a>` : ''}</div>` : ''}</section>`;
}

function binaryWorkspace() {
  const sessions = [...state.data.jobs].reverse().filter(row => row.result.kind === "binary_session");
  const selected = sessions.find(row => row.id === draft("binary-session")) || sessions.find(row => row.result.session_state === "open") || sessions[0];
  const operations = state.binaryCatalog?.operations || [];
  const operation = operations.find(row => row.name === draft("binary-operation")) || operations.find(row => row.name === "search_procedures") || operations[0];
  const retained = state.data.jobs.filter(row => row.result.project_directory && (row.result.kind === "binary_analysis" || row.result.kind === "binary_session"));
  let body = `<div class="reading">${cutterWorkspace()}<h2>Proyecto de análisis del binario</h2><p>Conecta Ghidra local para navegar funciones, instrucciones, referencias, tipos y valores. Las anotaciones se guardan en la base de análisis y conservan los bytes del archivo original.</p>`;
  if (!state.data.artifacts.length) return body + '<p>Añade un ejecutable o una imagen binaria desde Artefactos.</p><button data-action="tab" data-view="artifacts">Añadir artefacto</button></div>';
  body += `<form id="binary-open-form"><label>Artefacto<select name="artifact_id" data-draft="binary-artifact">${state.data.artifacts.map(row => `<option value="${row.id}" ${draft("binary-artifact",state.artifact)===row.id?"selected":""}>${escape(row.name)}</option>`).join("")}</select></label>
    <label>Proyecto nativo<select name="analysis_job_id" data-draft="binary-project"><option value="">Importar en un proyecto nuevo</option>${retained.map(row => `<option value="${row.id}" ${draft("binary-project")===row.id?"selected":""}>${escape(row.result.artifact_name)} · ${row.id.slice(0,8)}${row.result.session_state ? " · " + (sessionLabels[row.result.session_state] || row.result.session_state) : ""}</option>`).join("")}</select></label>
    <details id="binary-import-options"><summary>Arquitectura e importación de imagen sin cabecera</summary><label>Opciones JSON<textarea class="mono" name="options" data-draft="binary-options" rows="3" placeholder='{"raw":true,"language_id":"6502:LE:16:default","base_address":"0x8000"}'>${attr("binary-options","{}")}</textarea></label><p class="small">En una imagen sin cabecera, indica el lenguaje de Ghidra y su dirección de carga. Los ejecutables con cabecera se detectan al importar.</p></details>
    <button class="primary" type="submit" ${!state.binaryCatalog?.engine.available?"disabled":""}>Abrir sesión de análisis</button>${!state.binaryCatalog?.engine.available?'<p class="warning">Configura Ghidra y su JDK siguiendo el README para conectar el motor local.</p>':""}</form>`;
  if (!sessions.length) return body + '<h2>Sesiones</h2><p class="muted">Todavía no hay sesiones de binario en este proyecto.</p></div>';
  body += `<h2>Sesión de trabajo</h2><label>Sesión<select id="binary-session" data-draft="binary-session">${sessions.map(row => `<option value="${row.id}" ${selected.id===row.id?"selected":""}>${escape(row.result.artifact_name)} · ${sessionLabels[row.result.session_state]||escape(row.result.session_state)} · ${row.id.slice(0,8)}</option>`).join("")}</select></label>${binarySessionJob(selected)}`;
  if (selected.result.session_state === "open") {
    const parameters = Object.entries(operation.parameters).filter(([key]) => key !== "document");
    const optional = operation.name === "annotate_native_function" ? {name:"",comment:"",inline_comment:""} : {};
    body += `<form id="binary-call-form"><input type="hidden" name="session_id" value="${selected.id}"><label>Operación<select name="operation" id="binary-operation" data-draft="binary-operation">${operations.map(row => `<option value="${row.name}" ${row.name===operation.name?"selected":""}>${escape(binaryLabels[row.name]||row.name)}</option>`).join("")}</select></label>
      ${parameters.map(([key,value])=>binaryParameter(operation.name,key,value)).join("")}
      ${Object.entries(optional).map(([key,value])=>`<div><label class="inline"><input type="checkbox" name="include:${key}" data-draft="binary-include-${key}" ${draft("binary-include-"+key,false)?"checked":""}>Cambiar ${escape(parameterLabels[key].toLowerCase())}</label>${binaryParameter(operation.name,key,value)}</div>`).join("")}
      <button class="primary" type="submit">${operation.writes_analysis_project?"Guardar cambio en el análisis":"Consultar motor"}</button><p class="small">El resultado se guarda como una ejecución con registros consultables. Puedes continuar trabajando mientras termina.</p>
    </form>`;
    const connected = sessions.filter(row => row.result.session_state === "open");
    body += `<details id="binary-compare"><summary>Comparar una función con otra sesión</summary><p>Compara instrucciones y los bytes exactos de sus datos referenciados. Las direcciones se normalizan sólo cuando el decodificador identifica sus bits y el destino está resuelto. Las referencias sin resolver quedan como desconocidas.</p><form id="binary-compare-form"><input type="hidden" name="reference_session_id" value="${selected.id}">
      <label>Función de referencia<input name="reference_procedure" data-draft="compare-reference-procedure" value="${attr("compare-reference-procedure")}" required></label>
      <label>Sesión candidata<select name="candidate_session_id" data-draft="compare-candidate-session">${connected.map(row=>`<option value="${row.id}" ${draft("compare-candidate-session")===row.id?"selected":""}>${escape(row.result.artifact_name)} · ${row.id.slice(0,8)}</option>`).join("")}</select></label>
      <label>Función candidata<input name="candidate_procedure" data-draft="compare-candidate-procedure" value="${attr("compare-candidate-procedure")}" required></label><button type="submit">Comparar bytes y datos</button></form><p class="small">Una coincidencia de estas observaciones no demuestra equivalencia de comportamiento del programa.</p></details>`;
  }
  const calls = [...state.data.jobs].reverse().filter(row => row.result.session_id === selected.id);
  if (calls.length) body += `<h2>Consultas de esta sesión</h2>${calls.map(row=>nativeAnalysisJob(row)).join("")}`;
  return body + '</div>';
}

function binaryParameter(operation,key,value) {
  const label=escape(key==="type" && operation.includes("bookmark") ? "Tipo de marcador" : parameterLabels[key]||key), name=escape(key), token="binary-param-"+operation+"-"+key;
  const current=draft(token,typeof value==="object" && value!==null ? json(value) : value??"");
  if (typeof value==="boolean") return `<label class="inline"><input type="checkbox" name="${name}" data-draft="${token}" ${current?"checked":""}>${label}</label>`;
  if (value!==null && typeof value==="object") return `<label>${label}<textarea name="${name}" data-draft="${token}" rows="4" class="mono">${escape(current)}</textarea></label>`;
  if (key.includes("comment") || key==="text") return `<label>${label}<textarea name="${name}" data-draft="${token}" rows="3">${escape(current)}</textarea></label>`;
  if (key==="max_depth") return `<label>${label}<input name="${name}" data-draft="${token}" value="${escape(current)}" type="number" min="0" placeholder="Sin límite"></label>`;
  return `<label>${label}<input name="${name}" data-draft="${token}" value="${escape(current)}" ${typeof value==="number"?'type="number" min="1"':""}></label>`;
}

function binarySessionJob(job) {
  const data=job.result;
  return `<article class="record" id="job-${job.id}"><div class="job-head"><h3>${escape(data.artifact_name)}</h3><span class="status">${sessionLabels[data.session_state]||escape(data.session_state)}</span>${data.session_state==="open"?`<button data-action="binary-close" data-id="${job.id}">Guardar y cerrar sesión</button>`:""}${["queued","running"].includes(job.state)?`<button data-action="cancel-job" data-id="${job.id}">Cancelar apertura</button>`:""}</div><p class="small mono analysis-source">SHA-256 ${escape(data.artifact_sha256)}</p>${data.error?'<p class="error">La sesión no está disponible. Consulta sus registros y vuelve a abrir el proyecto nativo conservado.</p>':""}<div class="toolbar">${data.pid?`<a class="button" href="/theseus/api/binary-sessions/${job.id}/logs/stdout" download>Salida del motor</a><a class="button" href="/theseus/api/binary-sessions/${job.id}/logs/stderr" download>Diagnóstico del motor</a>`:""}${data.import_execution?`<a class="button" href="/theseus/api/binary-sessions/${job.id}/logs/import-stdout" download>Salida de importación</a><a class="button" href="/theseus/api/binary-sessions/${job.id}/logs/import-stderr" download>Diagnóstico de importación</a>`:""}</div><details id="session-${job.id}"><summary>Proyecto y estado nativo</summary><pre>${escape(json(job))}</pre></details></article>`;
}

function findings() {
  return state.data.findings.length
    ? `<div class="reading">${state.data.findings.map((row) => `<article class="record" id="finding-${escape(row.id)}"><small>${escape(row.id)} · ${escape(row.location)}</small><p class="small mono analysis-source">SHA-256: ${escape(row.source_sha256)}</p>${findingSources(row.source_refs)}<blockquote>${escape(row.observation)}</blockquote>${row.interpretation ? `<p><strong>Interpretación:</strong> ${escape(row.interpretation)}</p>` : ""}<button data-action="finding-artifact" data-id="${row.artifact_id}">Ver artefacto</button></article>`).join("")}</div>`
    : '<section class="empty"><h2>No hay hallazgos guardados</h2><p>Desde un artefacto, indica dónde aparece una observación y guárdala. La interpretación queda en un campo separado.</p><button data-action="tab" data-view="artifacts">Volver a los artefactos</button></section>';
}

function findingSources(sources = []) {
  return sources.length ? `<details><summary>Fuentes citadas (${sources.length})</summary>${sources.map(source=>`<p class="small mono analysis-source">${escape(source.side === "candidate" ? "Candidato" : source.side === "reference" ? "Referencia" : "Fuente")} · ${escape(state.data.artifacts.find(row=>row.id===source.artifact_id)?.name || source.artifact_id)}<br>SHA-256 ${escape(source.sha256)}</p>`).join("")}</details>` : "";
}

function scenarios() {
  const kind=draft('scenario-kind'),retained=isRetainedKind(kind);
  return `<div class="reading"><form id="scenario-form"><h2>${draft("scenario-id") ? "Editar escenario" : "Nuevo escenario"}</h2>
    <label>Nombre<input name="name" data-draft="scenario-name" value="${attr("scenario-name")}" required></label>
    <label>Tipo de escenario<select id="scenario-kind" name="kind" data-draft="scenario-kind"><option value="commands">Programas locales</option><option value="retained-page-scenarios" ${kind==='retained-page-scenarios'?'selected':''}>Capturas de página guardadas</option><option value="retained-process-scenarios" ${kind==='retained-process-scenarios'?'selected':''}>Capturas de procesos guardadas</option></select></label>
    ${retained?retainedScenarioFields(kind):commandScenarioFields()}
    <div class="toolbar"><button class="primary" type="submit">Guardar escenario</button>${draft("scenario-id") ? '<button type="button" data-action="new-scenario">Cancelar edición</button>' : ""}</div></form>
    <h2>Escenarios guardados</h2>${state.data.scenarios.length?state.data.scenarios.map(row=>`<article class="record"><h3>${escape(row.name)}</h3>${isRetainedKind(row.definition.kind)?`<p>${row.definition.kind==='retained-process-scenarios'?'Capturas de procesos guardadas · '+escape(row.definition.query.dimensions.join(', ')):'Capturas de página guardadas · respuestas a peticiones literales'}</p>${['reference','candidate'].map(side=>`<p class="small mono analysis-source">${side==='reference'?'Referencia':'Reconstrucción'} · ${escape(row.definition[side+'_job_id'])}<br>SHA-256 ${escape(row.definition[side+'_sha256'])}</p>`).join('')}`:`<p class="mono">${escape(json(row.definition.reference))}<br>${escape(json(row.definition.candidate))}</p>`}<button data-action="edit-scenario" data-id="${row.id}">Editar escenario</button></article>`).join(''):'<p class="muted">Todavía no hay escenarios.</p>'}
    <button data-action="tab" data-view="jobs">Ver comparaciones</button></div>`;
}

function commandScenarioFields() {
  return `<div class="split"><label>Programa de referencia · argumentos JSON<textarea class="mono" name="reference" data-draft="scenario-reference" rows="3" placeholder='["python", "C:\\\\ruta\\\\original.py"]' required>${attr("scenario-reference")}</textarea></label><label>Reconstrucción · argumentos JSON<textarea class="mono" name="candidate" data-draft="scenario-candidate" rows="3" placeholder='["python", "C:\\\\ruta\\\\candidato.py"]' required>${attr("scenario-candidate")}</textarea></label></div><label>Entrada compartida (stdin)<textarea class="mono" name="stdin" data-draft="scenario-stdin" rows="3">${attr("scenario-stdin")}</textarea></label><div class="split"><label>Directorio de trabajo, opcional<input name="cwd" data-draft="scenario-cwd" value="${attr("scenario-cwd")}"></label><label>Comparar stdout como<select name="mode" data-draft="scenario-mode"><option value="text">Texto exacto</option><option value="json" ${draft("scenario-mode") === "json" ? "selected" : ""}>JSON (sin importar el orden de claves)</option></select></label></div>${scenarioExpectations()}<p class="small">Se ejecutan estos programas locales con la misma entrada; se comparan salida, errores y código de retorno. La ejecución empieza al pulsar Comparar, no al guardar.</p>`;
}

function isRetainedKind(kind) {
  return ['retained-page-scenarios','retained-process-scenarios'].includes(kind);
}

function savedScenarioCaptures(kind='retained-page-scenarios') {
  return state.data.jobs.filter(job=>job.result.operation===(kind==='retained-process-scenarios'?'process.capture':'browser.scenario')&&job.result.analysis_sha256);
}

function captureSelect(label,name,key,hashKey='',kind='retained-page-scenarios') {
  const selected=draft(key),rows=savedScenarioCaptures(kind),job=rows.find(row=>row.id===selected);
  const hash=(hashKey&&draft(hashKey))||job?.result.analysis_sha256;
  return `<label>${escape(label)}<select name="${escape(name)}" data-draft="${escape(key)}" data-capture-hash="${escape(hashKey)}" required><option value="">Elige una captura guardada</option>${selected&&!job?`<option value="${escape(selected)}" selected>Captura no disponible · ${escape(selected)}</option>`:''}${rows.map(row=>`<option value="${escape(row.id)}" ${row.id===selected?'selected':''}>${escape(row.result.artifact_name||'Página')} · ${escape(statusLabels[row.state]||row.state)} · ${escape(row.id.slice(0,8))}</option>`).join('')}</select></label>${hash?`<p class="small mono analysis-source">SHA-256 ${escape(hash)}</p>`:''}`;
}

function retainedScenarioFields(kind) {
  const process=kind==='retained-process-scenarios';
  return `<p>${process?'Compara las dimensiones elegidas de procesos con las mismas entradas declaradas.':'Compara las respuestas conservadas a los mismos pasos.'} No repite acciones. Las capturas incompletas o alteradas quedan sin evidencia válida.</p>${!savedScenarioCaptures(kind).length?`<p class="muted">Guarda primero dos ejecuciones «${process?'Procesos · Capturar escenario':'Web · Ejecutar escenario CDP'}» en Ejecuciones. Después podrás elegirlas aquí.</p>`:''}<div class="split">${['reference','candidate'].map(side=>`<section>${captureSelect(side==='reference'?'Captura de referencia':'Captura de la reconstrucción',side+'_job_id','scenario-'+side+'_job_id','scenario-'+side+'_sha256',kind)}</section>`).join('')}</div>${process?`<label>Dimensiones y reglas de comparación · JSON<textarea name="query" class="mono" rows="5" data-draft="scenario-query" required>${attr('scenario-query',JSON.stringify({dimensions:['stdout','stderr','exit','files']},null,2))}</textarea></label><p class="small">Dimensiones: stdout, stderr, exit, terminal, files, http, websocket, commands y trace. Terminal admite terminal_view: rendered o raw; trace requiere nodos y relaciones before explícitas. Las normalizaciones literales se declaran en esta consulta y conservan sus recuentos.</p>`:''}<p class="small">Coincidir sólo verifica estas observaciones guardadas; no demuestra equivalencia para todas las entradas.</p>`;
}

function scenarioExpectations() {
  return `<details id="scenario-expectations"><summary>Resultado de referencia esperado y duración</summary>
    <label>Salida esperada, opcional<textarea class="mono" name="expected_stdout" data-draft="scenario-expected_stdout" rows="3">${attr("scenario-expected_stdout")}</textarea></label>
    <p class="small">Texto exacto, incluidos saltos de línea; en modo JSON, escribe un valor JSON. Activa la comprobación para esperar una salida vacía.</p>
    <label class="inline"><input name="check_stdout" type="checkbox" data-draft="scenario-check_stdout" ${draft("scenario-check_stdout")?"checked":""}>Comprobar también la salida esperada</label>
    <div class="split"><label>Retorno esperado, opcional<input name="expected_exit_code" type="number" step="1" data-draft="scenario-expected_exit_code" value="${attr("scenario-expected_exit_code")}"></label>
    <label>Duración máxima en segundos, opcional<input name="timeout_seconds" type="number" min="0.001" step="any" data-draft="scenario-timeout_seconds" value="${attr("scenario-timeout_seconds")}"></label></div></details>`;
}

const runtimeLabels = {serial:"Serial del dispositivo",package_name:"Paquete",scope:"Ámbito de paquetes",query:"Buscar",offset:"Desde el registro",limit:"Número de registros",output_directory:"Directorio local de destino",local_path:"Archivo local",remote_path:"Ruta absoluta en el dispositivo",overwrite:"Sobrescribir el archivo del dispositivo",replace:"Sustituir una instalación existente",buffer:"Registro",lines:"Últimas líneas",pid:"PID",namespace:"Grupo de ajustes",key:"Clave del ajuste",action:"Acción del intent",data_uri:"URI",component:"Componente",extras:"Extras tipados · JSON"};

Object.assign(runtimeLabels,{device_id:"Dispositivo Frida",remote_endpoint:"Endpoint remoto",token:"Token remoto",mode:"Modo de conexión",argv:"Programa y argumentos · JSON",cwd:"Directorio de trabajo",session_id:"Sesión de este proyecto",script_id:"Script de la sesión",source:"JavaScript de instrumentación",name:"Nombre del script",runtime:"Motor JavaScript"});
Object.assign(runtimeLabels,{inspector_endpoint:"Endpoint Inspector",target_id:"ID exacto del destino",observation_ms:"Ventana de observación · milisegundos",capture_sources:"Leer también los textos de los scripts"});
Object.assign(runtimeLabels,{capture_dom:"Guardar el árbol DOM",listener_selector:"Selector CSS para consultar listeners",capture_response_bodies:"Leer los cuerpos de respuestas completadas",capture_screenshot:"Guardar una captura PNG de la página"});
Object.assign(runtimeLabels,{steps:"Pasos CDP · JSON"});
Object.assign(runtimeLabels,{environment:"Variables del programa · JSON",terminal:"Terminal · JSON",files:"Archivos observados · JSON",services:"Servicios HTTP y WebSocket · JSON",commands:"Comandos declarados · JSON",timeout_seconds:"Tiempo máximo · segundos"});

function runtimeForm() {
  const operations=state.runtimeCatalog?.operations || [];
  const selected=operations.find(row=>row.name===draft("runtime-operation")) || operations[0];
  if (!selected) return '<p>El catálogo de ejecución no está disponible. Vuelve a cargar esta página.</p>';
  const sessions=state.data.runtime_sessions || [];
  const mode=draft("runtime-frida.start-mode","attach");
  const fields=Object.entries(selected.inputSchema.properties).filter(([key])=>selected.name!=="frida.start" || (mode==="spawn"?key!=="pid":!['argv','cwd'].includes(key))).map(([key,schema])=>{
    const token=key==="serial"?"runtime-serial":key==="session_id"?"runtime-frida-session":`runtime-${selected.name}-${key}`;
    const name=`runtime-param-${key}`;
    const required=selected.inputSchema.required.includes(key) || (selected.name==="frida.start" && (mode==="attach"?key==="pid":key==="argv"));
    const label=selected.name==="process.capture" && key==="mode"?"Modo de captura":selected.name==="process.capture" && key==="steps"?"Entradas y acciones · JSON":runtimeLabels[key] || key;
    const value=draft(token,key==="device_id"?"local":schema.default??"");
    if(key==="token") return `<label>${escape(label)} · opcional<input name="${name}" type="password" autocomplete="off"><span class="small">Se usa en esta conexión y no se guarda en la captura.</span></label>`;
    if(key==="session_id") return `<label>${escape(label)}<select name="${name}" data-draft="${token}" required><option value="">Elige una sesión conectada</option>${sessions.map(row=>`<option value="${escape(row.session_id)}" ${value===row.session_id?"selected":""}>PID ${escape(row.target.pid)} · ${escape(row.session_state)} · ${escape(row.session_id)}</option>`).join("")}</select></label>${!sessions.length?'<p>No hay sesiones conectadas. Abre una sesión para instrumentar un proceso; las capturas importadas se consultan en el historial.</p>':""}`;
    if(key==="script_id") {
      const scripts=sessions.find(row=>row.session_id===draft("runtime-frida-session"))?.scripts || [];
      return `<label>${escape(label)}<select name="${name}" data-draft="${token}" required><option value="">Elige un script cargado</option>${scripts.map(row=>`<option value="${escape(row.script_id)}" ${value===row.script_id?"selected":""}>${escape(row.name)} · ${escape(row.script_id)}</option>`).join("")}</select></label>`;
    }
    if(key==="source") return `<label>${escape(label)}<textarea name="${name}" data-draft="${token}" rows="8" class="mono" required>${escape(value)}</textarea></label>`;
    if(schema.type==="boolean") return `<label class="inline"><input name="${name}" type="checkbox" data-draft="${token}" ${value?"checked":""}>${escape(label)}</label>`;
    if(schema.enum) return `<label>${escape(label)}<select name="${name}" data-draft="${token}">${!required?'<option value="">Predeterminado</option>':""}${schema.enum.map(option=>`<option value="${escape(option)}" ${value===option?"selected":""} ${selected.name==="process.capture" && option==="pty" && (!selected.pty_available || !selected.terminal_renderer_available)?"disabled":""}>${escape(selected.name==="process.capture" && key==="mode"?({pipes:"Salida y errores separados",pty:"Terminal interactivo · Windows"}[option] || option):option)}</option>`).join("")}</select></label>`;
    if(schema.type==="array" || schema.type==="object") {
      const example=key==="steps"?(selected.name==="process.capture"?'[{"kind":"wait_output","text":"Ready"},{"kind":"input","text":"3\\r"}]':'[{"method":"Page.getFrameTree","parameters":{}}]'):key==="argv"?'["C:/ruta/programa.exe", "argumento"]':key==="files"?'[{"label":"resultado","path":"resultado.txt"}]':key==="terminal"?'{"columns":80,"rows":24,"scrollback":1000}':schema.type==="object"?'{}':'[{"name":"count","type":"int","value":128}]';
      return `<label>${escape(label)}${required?"":" · opcional"}<textarea name="${name}" data-draft="${token}" rows="${key==="steps"?8:3}" class="mono" ${required?"required":""} placeholder='${escape(example)}'>${escape(typeof value==="object"?json(value):value)}</textarea></label>`;
    }
    return `<label>${escape(label)}${required?"":" · opcional"}<input name="${name}" data-draft="${token}" value="${escape(value)}" ${required?"required":""} ${["integer","number"].includes(schema.type)?`type="number" min="0" step="${schema.type==="number"?"any":"1"}"`:""} ${key==="serial"?'placeholder="Serial de Dispositivos conectados"':Array.isArray(schema.type)?'placeholder="null para todos"':""}></label>`;
  }).join("");
  const mutates=selected.mutates_device || selected.mutates_target;
  const modifiedTarget=selected.name==="process.capture"?"el estado del programa y los archivos que utilice":selected.name.startsWith("browser.")?"la página seleccionada":selected.mutates_device?"el dispositivo seleccionado":"el proceso seleccionado";
  return `<section class="reading"><h2>Observaciones en ejecución</h2><p>Android usa el serial exacto del dispositivo. Frida usa un dispositivo y PID o programa, o una sesión de este proyecto. Inspector usa un endpoint y el ID exacto del destino; leer textos de scripts es opcional. Cada operación conserva una captura independiente; cerrar una sesión Frida desconecta la instrumentación sin matar el proceso.</p><form id="runtime-form"><label>Operación<select id="runtime-operation" name="operation" data-draft="runtime-operation">${operations.map(row=>`<option value="${escape(row.name)}" ${row.name===selected.name?"selected":""}>${escape(row.title)}</option>`).join("")}</select></label><p class="small">${escape(selected.description)}</p>${mutates?`<p>Esta operación modifica ${modifiedTarget}. Cancelar no revierte sus cambios.</p>`:""}${selected.available?"":`<p class="warning">${escape(selected.availability_reason)}</p>`}${fields}<button class="primary" type="submit" ${selected.available?"":"disabled"}>${selected.name==="browser.scenario"?"Ejecutar escenario":selected.name==="browser.coverage"?"Medir cobertura":selected.provider==="frida"?escape(selected.title.split(" · ").at(-1)):selected.mutates_device?"Ejecutar en el dispositivo":"Iniciar observación"}</button></form></section>`;
}

function jobs() {
  return `${runtimeForm()}<div class="section-title"><h2>Ejecuciones</h2><button class="primary" data-action="compare" ${!state.data.scenarios.length ? "disabled" : ""}>Comparar ${state.data.scenarios.length} escenario${state.data.scenarios.length === 1 ? "" : "s"}</button></div><p class="small">Se conservan las entradas, las huellas y los resultados de cada análisis y comparación. Puedes seguir trabajando mientras se ejecutan.</p>${
    state.data.jobs.length
      ? [...state.data.jobs]
          .reverse()
          .map((job) =>
            job.result.kind === "binary_analysis"
              ? analysisJob(job)
              : ["native_analysis","runtime_analysis"].includes(job.result.kind) ? nativeAnalysisJob(job) : job.result.kind === "binary_session" ? binarySessionJob(job) : job.result.kind === "oracle_selftest" ? oracleJob(job) : comparisonJob(job),
          )
          .join("")
      : '<section class="empty"><h2>Aún no hay ejecuciones</h2><p>Inicia una observación Android, prepara un escenario para comparar programas o analiza un binario desde Artefactos.</p><button data-action="tab" data-view="scenarios">Preparar escenario</button></section>'
  }${analysisBrowser(state.data.jobs.filter(row=>row.result.kind==="runtime_analysis"))}`;
}

function analysisJob(job) {
  return `<article class="record" id="job-${job.id}"><div class="job-head"><h2>Análisis de ${escape(job.result.artifact_name)}</h2><span class="status">${statusLabels[job.state] || escape(job.state)}</span>${["queued", "running"].includes(job.state) ? `<button data-action="cancel-job" data-id="${job.id}">Cancelar análisis</button>` : ""}</div><p class="small">${new Date(job.created_at).toLocaleString("es")} ${job.result.analysis ? `· ${job.result.analysis.functions.length} funciones` : ""}</p>${job.result.error ? `<p class="error">${escape(job.result.kind === "binary_analysis" ? "El análisis local falló. Abre «Recibo y salida del motor» para revisar el diagnóstico y vuelve a analizar el artefacto." : "La comparación no pudo terminar. Abre «Recibo reproducible» para revisar el diagnóstico, corrige el escenario y vuelve a comparar.")}</p>` : ""}<button data-action="finding-artifact" data-id="${job.result.artifact_id}">Ver funciones del artefacto</button><details id="receipt-${job.id}"><summary>Recibo y salida del motor</summary><pre>${escape(json(job))}</pre></details></article>`;
}

function comparisonJob(job) {
  const unknown=job.result.cases.filter(test=>test.valid===false).length;
  return `<article class="record" id="job-${job.id}"><div class="job-head"><h2>${new Date(job.created_at).toLocaleString("es")}</h2><span class="status">${statusLabels[job.state] || escape(job.state)}</span><span class="pass">Casos iguales: ${job.result.passed}</span><span class="fail">Casos distintos: ${job.result.failed-unknown}</span>${unknown?`<span class="warning">Sin evidencia válida: ${unknown}</span>`:''}${["queued", "running"].includes(job.state) ? `<button data-action="cancel-job" data-id="${job.id}">Cancelar comparación</button>` : ""}</div>${job.result.running_scenario ? `<p class="small">${escape(job.result.running_scenario)} · ${job.result.phase === "reference" ? "referencia" : "reconstrucción"}</p>` : ""}${job.result.error ? `<p class="error">${escape(job.result.kind === "binary_analysis" ? "El análisis local falló. Abre «Recibo y salida del motor» para revisar el diagnóstico y vuelve a analizar el artefacto." : "La comparación no pudo terminar. Abre «Recibo reproducible» para revisar el diagnóstico, corrige el escenario y vuelve a comparar.")}</p>` : ""}${job.result.message ? `<p>${escape(job.result.message)}</p>` : ""}${reconstructionReceipt(job)}${job.result.cases.map(test=>comparisonCase(job,test)).join('')}<details id="receipt-${job.id}"><summary>Recibo reproducible</summary><pre>${escape(json(job))}</pre></details></article>`;
}

function comparisonCase(job,test) {
  const retained=isRetainedKind(test.reference.kind),process=test.reference.kind==='retained-process-scenarios',unknown=test.valid===false;
  return `<details id="case-${job.id}-${test.scenario_id}"><summary class="${unknown?'warning':test.passed?'pass':'fail'}">${escape(test.name)} · ${unknown?'Sin evidencia válida':test.passed?'Coincide':'Difiere'}</summary>${test.differences.map(text=>`<p class="${unknown?'warning':'fail'}">${escape(differenceLabel(text))}</p>`).join('')}${retained?'<p class="small">Sólo se comparan las observaciones guardadas seleccionadas. No se ha conectado al original y no se afirma equivalencia general.</p>':''}<div class="comparison-output">${['reference','candidate'].map((side,index)=>{
    const observation=test[side];
    return `<section><h3>${index?'Reconstrucción':'Referencia'}</h3>${retained?`<p class="small mono analysis-source">SHA-256 ${escape(observation.analysis_sha256)}</p><a href="/theseus/api/jobs/${encodeURIComponent(observation.capture_job_id)}/analysis.json" download>Descargar captura guardada</a><h4>${process?"Consulta de comparación":"Peticiones"}</h4><pre>${escape(json(process?observation.query:observation.requests))}</pre><details><summary>${process?"Observación de proceso conservada":"Respuestas conservadas"}</summary><pre>${escape(json(process?observation.record:observation.responses))}</pre></details>`:`<p class="small">Retorno ${observation.exit_code} · ${observation.duration_seconds}s</p><pre>${escape(observation.stdout||'(sin salida)')}</pre>${observation.stderr?`<h3>stderr</h3><pre>${escape(observation.stderr)}</pre>`:''}`}</section>`;
  }).join('')}</div></details>`;
}

function reconstructionReceipt(job) {
  const link=job.result.reconstruction;
  if(!link) return "";
  const handoff=state.data.workflow?.handoffs.find(row=>row.id===link.handoff_id);
  return `<p class="small">Verificación de la entrega ${escape(handoff?new Date(handoff.created_at).toLocaleString("es"):link.handoff_id)}.</p>${link.specification_changed?'<p class="warning">La especificación actual es distinta de la que recibió el constructor. Esta ejecución conserva el contrato anterior.</p>':""}<button data-action="tab" data-view="reconstruction">Ver entrega y obligaciones</button>`;
}

document.addEventListener("input", (event) => {
  const field = event.target;
  if (!field.dataset.draft || !projectId()) return;
  state.drafts[projectId()] ||= {};
  state.drafts[projectId()][field.dataset.draft] = field.dataset.linkset ? [...document.querySelectorAll(`#claim-form input[name="${field.dataset.linkset}"]:checked`)].map(item=>item.value).join(", ") : field.type === "checkbox" ? field.checked : field.value;
  keepDrafts();
});

document.addEventListener("click", (event) => {
  const button = event.target.closest("button[data-action]");
  if (!button) return;
  const { action, id, view, page } = button.dataset;
  if (action === "dismiss-client-inspection") {
    state.clientInspection = null;
    if (clientInspectionDownload) URL.revokeObjectURL(clientInspectionDownload);
    clientInspectionDownload = null;
    $("#client-inspection-result").textContent = "";
    render();
    $("#client-inspection-form button").focus();
    return;
  }
  if (action === "load-web-sources") return act(async () => {
    const source=state.data.jobs.find(row=>row.id===id);
    const response=await fetch(`/theseus/api/jobs/${id}/analysis.json`);
    if(!response.ok) throw Error("No se pudo cargar el manifiesto. Consulta el recibo del análisis de origen.");
    const bytes=await response.arrayBuffer();
    const sha=Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256",bytes)),value=>value.toString(16).padStart(2,"0")).join("");
    if(sha!==source.result.analysis_sha256) throw Error("El manifiesto cambió respecto al recibo guardado. Vuelve a exportar la captura.");
    const document=JSON.parse(new TextDecoder().decode(bytes));
    if(document.result?.format!=="vitruvius.web-sources/1") throw Error("Selecciona una exportación de fuentes web guardadas.");
    state.webSourceChoices={job_id:id,sha256:sha,entries:document.result.entries.map(row=>({
      id:row.id,kind:row.kind,url:row.url,state:row.state,sha256:row.sha256,script_entry_id:row.script_entry_id}))};
    render();
    notice("Fuentes cargadas. Selecciona el script que quieres consultar.");
  });
  if (["claim-finding","claim-dependency","claim-job"].includes(action)) {
    state.view=action==="claim-finding"?"findings":action==="claim-job"?"jobs":"reconstruction";
    route();render();
    const target=document.getElementById((action==="claim-finding"?"finding-":action==="claim-job"?"job-":"claim-record-")+id);
    if(target) {target.tabIndex=-1;target.focus();target.scrollIntoView({block:"center"});}
    return;
  }
  if (action === "edit-claim" || action === "new-claim") {
    clearDrafts(...claimFields.map(key=>"claim-"+key));
    if (action === "edit-claim") {
      const claim=state.data.workflow.claims.find(row=>row.id===id);
      state.drafts[projectId()] ||= {};
      for (const key of claimFields) state.drafts[projectId()]["claim-"+key]=Array.isArray(claim[key])?claim[key].join(", "):claim[key];
      keepDrafts();
    }
    render();$("#claim-form textarea").focus();return;
  }
  if (action === "binary-close") return act(async () => {
    await api(`/binary-sessions/${id}/close`,{});
    await refresh();
    notice("La sesión está guardando su proyecto y cerrando el motor.");
  });
  if (action === 'cutter-refresh') return act(async () => {
    state.cutterSessions = await api('/cutter/sessions');
    render();
  });
  if (action === "analysis-section") return act(async () => {
    state.view = "analyses";
    clearDrafts("analysis-query");
    await readAnalysisPage(button.dataset.job, button.dataset.section);
    route();
  });
  if (action === "analysis-page") return act(async () => {
    const current = state.analysisPage;
    await readAnalysisPage(current.job_id, current.section, Number(button.dataset.offset), draft("analysis-query"));
  });
  if (action === "analysis-record") return act(async () => {
    const current = state.analysisPage;
    state.analysisRecord = await api(`/jobs/${current.job_id}/records/${encodeURIComponent(current.section)}/${encodeURIComponent(button.dataset.key)}`);
  });
  if (action === "analysis-evidence") return act(async () => {
    const original=state.analysisRecord;
    const evidenceId=button.dataset.evidence || original.record.evidence_id;
    await readAnalysisPage(original.job_id,"source_observations");
    state.analysisRecord=await api(`/jobs/${original.job_id}/records/source_observations/${encodeURIComponent(evidenceId)}`);
  });
  if (action === "cite-analysis") {
    const record = state.analysisRecord;
    state.artifact = record.artifact_id;
    state.view = "artifacts";
    state.drafts[projectId()] ||= {};
    Object.assign(state.drafts[projectId()], {
      "finding-location": `${record.section} · ${record.record_key} · análisis ${record.job_id}`,
      "finding-source-sha256": record.artifact_sha256,
      "finding-observation": json(record.record),
      "finding-source-refs": json((record.sources || []).map(({artifact_id,sha256,side})=>({artifact_id,sha256,...(side===undefined?{}:{side})}))),
      "finding-interpretation": "",
    });
    keepDrafts(); route(); render();
    $("#finding-form textarea").focus();
    return;
  }
  if (action === "new-project") return openNewProject();
  if (action === "project")
    return act(async () => {
      state.artifact = "";
      state.excerpt = null;
      await load(id);
    });
  if (action === "tab") {
    state.view = view;
    route();
    render();
    $("#tab-" + state.view).focus();
    return;
  }
  if (action === "artifact" || action === "finding-artifact") {
    state.artifact = id;
    state.excerpt = null;
    state.view = "artifacts";
    route();
    render();
    return;
  }
  if (action === "upload") return $("#upload-file").click();
  if (action === "analyze")
    return act(async () => {
      await api(
        `/projects/${projectId()}/artifacts/${state.artifact}/analyze`,
        {},
      );
      await refresh();
      notice("Análisis local iniciado.");
    });
  if (action === "function") {
    state.drafts[projectId()] ||= {};
    state.drafts[projectId()]["function-" + state.artifact] =
      button.dataset.address;
    render();
    return;
  }
  if (action === "cite-function") {
    const job = state.data.jobs.find((row) => row.id === button.dataset.job);
    const fn = job.result.analysis.functions.find(
      (row) => row.address === button.dataset.address,
    );
    state.drafts[projectId()] ||= {};
    Object.assign(state.drafts[projectId()], {
      "finding-location": `${job.result.analysis.engine} · ${fn.address} · análisis ${job.id}`,
      "finding-source-sha256": job.result.artifact_sha256,
      "finding-source-refs": "[]",
      "finding-observation": fn.code || fn.signature,
      "finding-interpretation":
        "Descompilación inferida por el motor; contrastar con el comportamiento observado.",
    });
    keepDrafts();
    render();
    $("#finding-form textarea").focus();
    return;
  }
  if (action === "archive")
    return act(async () => {
      await api(
        "/projects/" + projectId(),
        { archived: !state.data.project.archived },
        "PATCH",
      );
      await refresh();
      notice(
        state.data.project.archived
          ? "Proyecto archivado; puedes restaurarlo."
          : "Proyecto restaurado.",
      );
    });
  if (action === "strings-page") {
    state.drafts[projectId()] ||= {};
    state.drafts[projectId()]["string-page"] = Number(page);
    render();
    return;
  }
  if (action === "cite-excerpt") {
    state.drafts[projectId()] ||= {};
    Object.assign(state.drafts[projectId()], {
      "finding-location": `${state.excerpt.member ? state.excerpt.member + " · " : ""}bytes ${state.excerpt.offset}–${state.excerpt.offset + state.excerpt.bytes}`,
      "finding-observation": state.excerpt.text,
      "finding-source-sha256": state.excerpt.current_sha256,
      "finding-source-refs": "[]",
    });
    keepDrafts();
    render();
    $("#finding-form textarea").focus();
    return;
  }
  if (action === "edit-scenario" || action === "claim-scenario") {
    const row = state.data.scenarios.find((item) => item.id === id),
      data = row.definition;
    state.drafts[projectId()] ||= {};
    Object.assign(state.drafts[projectId()], {
      "scenario-id": row.id,
      "scenario-name": row.name,
      "scenario-kind": data.kind || 'commands',
      "scenario-query": data.query?json(data.query):"",
      "scenario-reference_job_id": data.reference_job_id || '',
      "scenario-reference_sha256": data.reference_sha256 || '',
      "scenario-candidate_job_id": data.candidate_job_id || '',
      "scenario-candidate_sha256": data.candidate_sha256 || '',
      "scenario-reference": json(data.reference),
      "scenario-candidate": json(data.candidate),
      "scenario-stdin": data.stdin || "",
      "scenario-cwd": data.cwd || "",
      "scenario-mode": data.mode || "text",
      "scenario-expected_stdout": Object.hasOwn(data,"expected_stdout") ? (data.mode==="json"?json(data.expected_stdout):data.expected_stdout) : "",
      "scenario-check_stdout": Object.hasOwn(data,"expected_stdout"),
      "scenario-expected_exit_code": data.expected_exit_code ?? "",
      "scenario-timeout_seconds": data.timeout_seconds ?? "",
    });
    keepDrafts();
    state.view="scenarios";route();
    render();
    $("#scenario-form input").focus();
    return;
  }
  if (action === "new-scenario") {
    clearDrafts(
      ...["id", "name", "kind", "query", "reference_job_id", "reference_sha256", "candidate_job_id", "candidate_sha256", "reference", "candidate", "stdin", "cwd", "mode", "expected_stdout", "check_stdout", "expected_exit_code", "timeout_seconds"].map(
        (key) => "scenario-" + key,
      ),
    );
    render();
    return;
  }
  if (action === "compare")
    return act(async () => {
      await api("/projects/" + projectId() + "/comparisons", {});
      await refresh();
      notice("Comparación iniciada.");
    });
  if (action === "cancel-job")
    return act(async () => {
      await api("/jobs/" + id + "/cancel", {});
      await refresh();
      notice("Cancelación solicitada.");
    });
});

document.addEventListener("keydown", (event) => {
  if (event.ctrlKey || event.metaKey || event.altKey) return;
  if (!event.target.matches('[role="tab"]')) return;
  const keys = Object.keys(labels);
  let index = keys.indexOf(state.view);
  if (event.key === "ArrowRight") index = (index + 1) % keys.length;
  else if (event.key === "ArrowLeft")
    index = (index - 1 + keys.length) % keys.length;
  else if (event.key === "Home") index = 0;
  else if (event.key === "End") index = keys.length - 1;
  else return;
  event.preventDefault();
  state.view = keys[index];
  route();
  render();
  $("#tab-" + state.view).focus();
});

document.addEventListener("submit", (event) => {
  const form = event.target;
  event.preventDefault();
  if (form.id === "client-inspection-form") {
    void inspectClientForm(form);
    return;
  }
  if (form.id === "swift-demangle-form") {
    void demangleSwiftForm(form);
    return;
  }
  if (form.id === "strings-filter") {
    render();
    return;
  }
  const fields = Object.fromEntries(new FormData(form));
  void act(async () => {
    if (form.id === "evidence-import-form") {
      const file = form.elements.file.files[0];
      const content = file ? await file.text() : fields.bundle;
      if (!content?.trim()) throw new Error("Selecciona un archivo de evidencias o introduce su JSON.");
      const imported = await api("/evidence/import", {bundle: JSON.parse(content), name: fields.name});
      form.reset();
      $("#evidence-import").open = false;
      state.projects = (await api("/projects")).projects;
      state.view = "reconstruction";
      await load(imported.project.id);
      notice("Evidencias importadas en un proyecto nuevo. Los recibos conservan su carácter histórico.");
    }
    if (form.id === "claim-form") {
      const payload={...fields,claim_id:draft("claim-id")};
      for (const key of ["finding_ids","scenario_ids","depends_on"]) payload[key]=new FormData(form).getAll(key);
      await api(`/projects/${projectId()}/claims`,payload);
      clearDrafts(...claimFields.map(key=>"claim-"+key));
      await refresh();notice("Obligación o pregunta guardada.");
    }
    if (form.id === "handoff-form") {
      await api(`/projects/${projectId()}/handoffs`,fields);
      await refresh();notice("Especificación congelada para el constructor.");
    }
    if (form.id === "oracle-form") {
      const scenario_ids=state.data.scenarios.filter(row=>!isRetainedKind(row.definition.kind)).map(row=>row.id);
      await api(`/projects/${projectId()}/oracle-selftests`,{variants:JSON.parse(fields.variants),scenario_ids});
      await refresh();notice("Prueba de sensibilidad iniciada.");
    }
    if(form.id==='retained-oracle-form') {
      const scenario=state.data.scenarios.find(row=>row.id===fields.scenario_id);
      const job=savedScenarioCaptures(scenario?.definition.kind).find(row=>row.id===fields.candidate_job_id);
      if(!job)throw new Error('Elige una captura guardada para la perturbación.');
      await api(`/projects/${projectId()}/oracle-selftests`,{scenario_ids:[fields.scenario_id],variants:[{name:fields.name,captures:[{scenario_id:fields.scenario_id,candidate_job_id:job.id,candidate_sha256:job.result.analysis_sha256}]}]});
      await refresh();notice('Perturbación guardada enviada al oráculo. No se ha vuelto a conectar al original.');
    }
    if (form.id === "verify-form") {
      await api(`/projects/${projectId()}/reconstructions/verify`,fields);
      state.view="jobs";route();await refresh();notice("Verificación de reconstrucción iniciada.");
    }
    if (form.id === 'cutter-command-form') {
      // Never turn a transport error into an automatic resend.
      state.cutterSessions = null;
      state.cutterObservation = {command: fields.command, output: null, execution_state: 'unknown',
        error: 'No se ha recibido una observación completa.',
        message: 'La orden puede haber tenido efectos. No la repitas automáticamente; comprueba la sesión y las ejecuciones guardadas.'};
      try {
        state.cutterObservation = await api(`/projects/${projectId()}/cutter/command`, {
          session_id: fields.session_id, expected_generation: Number(fields.expected_generation),
          command: fields.command, json: Object.hasOwn(fields, 'json')});
      } catch (error) {
        state.cutterObservation.error = error.message;
        notice('No se ha recibido el resultado. Comprueba la sesión y las ejecuciones guardadas antes de decidir otra orden.');
        return;
      }
      await refresh();
      notice('Observación conservada. Busca de nuevo las sesiones antes de decidir otra orden.');
    }
    if (form.id === "binary-compare-form") {
      await api("/binary-comparisons", fields);
      await refresh();notice("Comparación iniciada. El resultado conservará los bytes y los datos de ambas funciones.");
    }
    if (form.id === "binary-open-form") {
      const options=JSON.parse(fields.options||"{}");
      if (fields.analysis_job_id) options.analysis_job_id=fields.analysis_job_id;
      const session=await api(`/projects/${projectId()}/artifacts/${fields.artifact_id}/binary-sessions`,{options});
      state.drafts[projectId()] ||= {};
      state.drafts[projectId()]["binary-session"]=session.id;
      keepDrafts();await refresh();notice("El motor está abriendo el proyecto de análisis.");
    }
    if (form.id === "binary-call-form") {
      const operation=state.binaryCatalog.operations.find(row=>row.name===fields.operation);
      const parameters={};
      for (const [key,value] of Object.entries(operation.parameters)) {
        if (key==="document") continue;
        if (key==="max_depth") { parameters[key]=fields[key]===""?null:Number(fields[key]); continue; }
        parameters[key]=typeof value==="boolean" ? Object.hasOwn(fields,key) : typeof value==="number" ? Number(fields[key]) : value!==null && typeof value==="object" ? JSON.parse(fields[key]) : value===null ? fields[key]||null : fields[key];
      }
      for (const key of ["name","comment","inline_comment"]) if (Object.hasOwn(fields,"include:"+key)) parameters[key]=fields[key];
      await api(`/binary-sessions/${fields.session_id}/call`,{operation:fields.operation,parameters});
      await refresh();notice("Consulta iniciada. El resultado aparecerá en las consultas de esta sesión.");
    }
    if (form.dataset.analysisJob) {
      state.view = state.data.jobs.find(row=>row.id===form.dataset.analysisJob)?.result.kind==="runtime_analysis"?"jobs":"analyses";
      clearDrafts("analysis-query");
      await readAnalysisPage(form.dataset.analysisJob, fields.section);
      route();
    }
    if (form.id === "native-analysis-form") {
      const setJobs=[...form.querySelectorAll('input[name="source_job_ids"]:checked')].map(row=>row.value);
      const setInput=state.catalog.operations.find(row=>row.name===fields.operation)?.input==="set";
      if(setInput&&!setJobs.length) throw new Error("Elige al menos un análisis guardado del conjunto.");
      const source = (setJobs[0] || fields.source_job_id || fields.reference_job_id) && state.data.jobs.find(row => row.id === (setJobs[0] || fields.source_job_id || fields.reference_job_id));
      const selectedSources = setInput?{source_job_ids:setJobs}:fields.reference_job_id ? {reference_job_id:fields.reference_job_id,candidate_job_id:fields.candidate_job_id} : source ? {source_job_id:source.id} : {};
      const parameters=JSON.parse(fields.parameters || "{}");
      if(["javascript.trace_source","javascript.trace_imports"].includes(fields.operation)) {
        parameters.query={...parameters.query,script_id:fields["web-script"]};
        if(fields.operation==="javascript.trace_source") Object.assign(parameters.query,{
          map_id:fields["web-map"],line:Number(fields["web-line"]),column:Number(fields["web-column"])});
      }
      await api(`/projects/${projectId()}/artifacts/${source ? source.result.artifact_id : fields.artifact_id}/analyses`, {
        operation: fields.operation, parameters: {...parameters, ...selectedSources},
      });
      await refresh();
      notice("Análisis nativo iniciado.");
    }
    if (form.id === "runtime-form") {
      const selected=state.runtimeCatalog.operations.find(row=>row.name===fields.operation);
      const parameters={};
      for(const [key,schema] of Object.entries(selected.inputSchema.properties)) {
        const value=fields[`runtime-param-${key}`];
        if(schema.type==="boolean") { parameters[key]=value==="on";continue; }
        if(value===undefined || value==="") continue;
        if(schema.type==="array" || schema.type==="object") parameters[key]=JSON.parse(value);
        else if(schema.type==="number") {
          parameters[key]=Number(value);
          if(!Number.isFinite(parameters[key]) || parameters[key]<0) throw Error("Indica una duración válida en segundos.");
        }
        else if(schema.type==="integer" || Array.isArray(schema.type)) {
          if(value==="null") parameters[key]=null;
          else { parameters[key]=Number(value);if(!Number.isInteger(parameters[key]) || parameters[key]<0) throw Error("Indica un número entero no negativo o null para todos."); }
        } else parameters[key]=value;
      }
      await api(`/projects/${projectId()}/runtime`,{operation:fields.operation,parameters});
      await refresh();notice("Observación iniciada. Consulta su estado y sus registros en Ejecuciones.");
    }
    if (form.id === "analysis-search") {
      const page = state.analysisPage;
      await readAnalysisPage(page.job_id, page.section, 0, fields.query);
    }
    if (form.id === "new-project") {
      const project = await api("/projects", fields);
      form.reset();
      form.hidden = true;
      $("#new-project-toggle").setAttribute("aria-expanded", "false");
      state.projects = (await api("/projects")).projects;
      await load(project.id);
      notice("Proyecto creado.");
    }
    if (form.id === "edit-project") {
      await api("/projects/" + projectId(), fields, "PATCH");
      clearDrafts("project-name", "project-question");
      await refresh();
      notice("Proyecto guardado.");
    }
    if (form.id === "artifact-form") {
      const artifact = await api(
        "/projects/" + projectId() + "/artifacts",
        fields,
      );
      state.artifact = artifact.id;
      state.excerpt = null;
      clearDrafts("artifact-path");
      await refresh();
      notice("Archivo inspeccionado.");
    }
    if (form.id === "excerpt-form") {
      state.excerpt = await api(
        `/projects/${projectId()}/artifacts/${state.artifact}/excerpt?${new URLSearchParams(fields)}`,
      );
    }
    if (form.id === "finding-form") {
      await api("/projects/" + projectId() + "/findings", {
        ...fields,
        source_refs: JSON.parse(draft("finding-source-refs", "[]")),
        artifact_id: state.artifact,
      });
      clearDrafts(
        "finding-location",
        "finding-observation",
        "finding-interpretation",
        "finding-source-sha256",
        "finding-source-refs",
      );
      await refresh();
      notice("Hallazgo guardado.");
    }
    if (form.id === "specification-form") {
      await api(
        "/projects/" + projectId(),
        { specification: fields.content },
        "PATCH",
      );
      clearDrafts("specification");
      await refresh();
      notice("Especificación guardada.");
    }
    if (form.id === "scenario-form") {
      const definition = isRetainedKind(fields.kind)?{
        kind:fields.kind,...(fields.kind==='retained-process-scenarios'?{query:JSON.parse(fields.query)}:{}),...Object.fromEntries(['reference','candidate'].flatMap(side=>{
          const id=fields[side+'_job_id'],job=savedScenarioCaptures(fields.kind).find(row=>row.id===id);
          if(!job)throw new Error('Elige una captura guardada disponible para '+(side==='reference'?'la referencia':'la reconstrucción')+'.');
          return [[side+'_job_id',id],[side+'_sha256',draft('scenario-'+side+'_sha256')||job.result.analysis_sha256]];
        })),
      }:{
        reference: JSON.parse(fields.reference),
        candidate: JSON.parse(fields.candidate),
        stdin: fields.stdin,
        mode: fields.mode,
        ...(fields.cwd ? { cwd: fields.cwd } : {}),
        ...(fields.check_stdout ? {expected_stdout: fields.mode==="json" ? JSON.parse(fields.expected_stdout) : fields.expected_stdout} : {}),
        ...(fields.expected_exit_code!=="" ? {expected_exit_code:Number(fields.expected_exit_code)} : {}),
        ...(fields.timeout_seconds!=="" ? {timeout_seconds:Number(fields.timeout_seconds)} : {}),
      };
      await api("/projects/" + projectId() + "/scenarios", {
        name: fields.name,
        definition,
        scenario_id: draft("scenario-id"),
      });
      clearDrafts(
        ...["id", "name", "kind", "query", "reference_job_id", "reference_sha256", "candidate_job_id", "candidate_sha256", "reference", "candidate", "stdin", "cwd", "mode", "expected_stdout", "check_stdout", "expected_exit_code", "timeout_seconds"].map(
          (key) => "scenario-" + key,
        ),
      );
      await refresh();
      notice("Escenario guardado.");
    }
  });
});

document.addEventListener("change", (event) => {
  if(['scenario-kind','retained-oracle-scenario','process-terminal-frame'].includes(event.target.id)||event.target.dataset.captureHash!==undefined) {
    if(event.target.dataset.captureHash)clearDrafts(event.target.dataset.captureHash);
    render();
  }
  if (["binary-session","binary-operation","cutter-session"].includes(event.target.id)) render();
  if (["analysis-operation","analysis-source-job"].includes(event.target.id)) render();
  if (event.target.id === "runtime-operation" || (event.target.form?.id==="runtime-form" && ['runtime-param-mode','runtime-param-session_id'].includes(event.target.name))) render();
  if (event.target.id === "show-archived") {
    state.showArchived = event.target.checked;
    renderRail();
  }
  if (event.target.id === "upload-file" && event.target.files[0]) {
    const body = new FormData();
    body.append("file", event.target.files[0]);
    void act(async () => {
      const response = await fetch("/theseus/api/projects/" + projectId() + "/upload", {
        method: "POST",
        headers: { "X-Hoard-Request": "1" },
        body,
      });
      const artifact = await response.json();
      if (!response.ok)
        throw new Error(artifact.detail || "No se pudo subir el archivo");
      state.artifact = artifact.id;
      state.excerpt = null;
      await refresh();
      notice("Archivo subido e inspeccionado.");
    });
  }
  if (event.target.id === "binary-function") {
    state.drafts[projectId()] ||= {};
    state.drafts[projectId()]["function-" + state.artifact] =
      event.target.value;
    render();
  }
});

function openNewProject() {
  $("#new-project").hidden = false;
  $("#new-project-toggle").setAttribute("aria-expanded", "true");
  $("#new-project input").focus();
}
$("#new-project-toggle").addEventListener("click", () => {
  if ($("#new-project").hidden) openNewProject();
  else {
    $("#new-project").hidden = true;
    $("#new-project-toggle").setAttribute("aria-expanded", "false");
  }
});

window.hoardCopilot = {
  context: async () => ({
    project: state.data
      ? { id: projectId(), name: state.data.project.name }
      : null,
    active_objects: state.data
      ? [
          {
            kind: "inspection_project",
            id: projectId(),
            label: state.data.project.name,
          },
          ...(state.artifact ? [{ kind: "artifact", id: state.artifact }] : []),
        ]
      : [],
    view: state.view,
  }),
  onTurnEnd: () => void refresh().catch((error) => notice(error.message, true)),
};

let polling = false;
setInterval(async () => {
  if (polling || state.busy || !state.data) return;
  const active = state.data.jobs.filter((job) =>
    ["queued", "running"].includes(job.state),
  );
  if (!active.length) return;
  polling = true;
  const selected = projectId();
  try {
    const jobs = await Promise.all(active.map((job) => api("/jobs/" + job.id)));
    if (projectId() === selected) {
      for (const job of jobs) {
        const index = state.data.jobs.findIndex((row) => row.id === job.id);
        if (index >= 0) state.data.jobs[index] = job;
        if (job.result.session_id && job.result.kind!=="runtime_analysis" && !["queued","running"].includes(job.state)) {
          const session=await api("/binary-sessions/"+job.result.session_id);
          if(projectId()!==selected) break;
          const parent=state.data.jobs.findIndex(row=>row.id===session.id);
          if(parent>=0) state.data.jobs[parent]=session;
        }
      }
      if (jobs.some(job=>!["queued","running"].includes(job.state))) {
        if (jobs.some(job=>job.result.derived_artifacts?.length || job.result.kind==="runtime_analysis")) {
          const project=await api(`/projects/${selected}`);
          if(projectId()!==selected) return;
          state.data.artifacts=project.artifacts;
          state.data.artifact_links=project.artifact_links;
          state.data.runtime_sessions=project.runtime_sessions;
        }
        const workflow=await api(`/projects/${selected}/workflow`);
        if(projectId()!==selected) return;
        state.data.workflow=workflow;
      }
      if (
        state.view === "jobs" || state.view === "analyses" || state.view === "binary" || state.view === "reconstruction" ||
        (state.view === "artifacts" &&
          jobs.some(
            (job) =>
              job.result.kind === "binary_analysis" && job.state === "finished",
          ))
      ) {
        const view = captureView();
        $("#section").innerHTML = renderSection();
        restoreView(view);
      }
    }
  } catch (error) {
    notice(error.message, true);
  } finally {
    polling = false;
  }
}, 2000);

async function start() {
  const parts = location.hash.split("/");
  state.view = Object.hasOwn(labels, parts[3]) ? parts[3] : "artifacts";
  state.artifact = parts[4] || "";
  const [projects, engines, catalog, binaryCatalog, runtimeCatalog] = await Promise.all([
    api("/projects"),
    api("/engines"),
    api("/analyses/catalog"),
    api("/binary-sessions/catalog"),
    api("/runtime/catalog"),
  ]);
  state.projects = projects.projects;
  state.engines = engines;
  state.catalog = catalog;
  state.binaryCatalog = binaryCatalog;
  state.runtimeCatalog = runtimeCatalog;
  const id =
    state.projects.find((row) => row.id === parts[2])?.id ||
    state.projects.find((row) => !row.archived)?.id;
  if (id) await load(id);
  else render();
}
void start().catch((error) => {
  render();
  notice(error.message, true);
});
