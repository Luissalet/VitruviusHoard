"""Native static analysis operations and persistent, individually readable results."""
import json
import shutil
import sys
from pathlib import Path

from jsonschema import validate

from .inspection import digest
from .store import identifier
from .structured import OPERATIONS as STRUCTURED_OPERATIONS
from .recordings import OPERATIONS as RECORDING_OPERATIONS
from .signals import OPERATIONS as SIGNAL_OPERATIONS, engine as signal_engine
from .android import OPERATIONS as ANDROID_OPERATIONS, available as android_availability
from .packets import OPERATIONS as PACKET_OPERATIONS, engine as packet_engine
from .qlog import OPERATIONS as QLOG_OPERATIONS
from .firmware import OPERATIONS as FIRMWARE_OPERATIONS, available as firmware_availability
from .process_compare import QUERY as PROCESS_QUERY
from .retained_evidence import OPERATIONS as EVIDENCE_OPERATIONS
from .elf_layout import OPERATIONS as ELF_OPERATIONS
from .objdump_inspection import OPERATIONS as OBJDUMP_OPERATIONS, engine as objdump_engine

ENGINE = Path(__file__).resolve().parent.parent / "software_native" / "engine"
MEMBER_PARAMETERS = {"type": "object", "additionalProperties": False, "properties": {
    "type_names": {"type": "array", "items": {"type": "string"}},
    "method_offset": {"type": "integer", "minimum": 0},
    "method_limit": {"type": "integer", "minimum": 0},
    "user_strings": {"type": "boolean"}}}
EMPTY_PARAMETERS = {"type": "object", "properties": {}, "additionalProperties": False}
OPERATIONS = [
    {"name": "managed.artifact", "title": ".NET · Metadatos",
     "description": "Identidad PE/CLI, clasificación del runtime, ensamblado y módulo, referencias, recursos y atributos. No carga el CLR.",
     "inputSchema": EMPTY_PARAMETERS},
    {"name": "managed.members", "title": ".NET · Miembros y CIL",
     "description": "Tipos, firmas, campos, métodos, instrucciones CIL con sus bytes y offsets originales, excepciones y referencias. Permite seleccionar tipos exactos y un intervalo de métodos.",
     "inputSchema": MEMBER_PARAMETERS},
    {"name": "managed.native_boundaries", "title": ".NET · Fronteras nativas",
     "description": "Declaraciones P/Invoke y otras fronteras nativas, con tokens y offsets. Una declaración no demuestra una llamada durante la ejecución.",
     "inputSchema": EMPTY_PARAMETERS},
    {"name": "go.build", "title": "Go · Compilación y módulos",
     "description": "Contenedor ELF, PE o Mach-O, versión de compilador y módulos Go con ubicaciones y bytes originales. La ausencia de metadatos no descarta Go.", "inputSchema": EMPTY_PARAMETERS},
    {"name": "rust.dependencies", "title": "Rust · Dependencias y compilador",
     "description": "Sección auditable de dependencias y commits rustc inferidos en un contenedor ELF, PE o Mach-O. Distingue metadatos ausentes de dependencias desconocidas.", "inputSchema": EMPTY_PARAMETERS},
    {"name": "electron.fuses", "title": "Electron · Fuses del ejecutable",
     "description": "Lee las opciones de compilación fuses y sus offsets en cada arquitectura del ejecutable, sin iniciarlo.", "inputSchema": EMPTY_PARAMETERS},
    {"name": "apple.macho", "title": "Apple · Contenedor Mach-O",
     "description": "Arquitecturas, comandos de carga, librerías, rpaths, plataformas y rangos de firma del archivo Mach-O. El análisis estático funciona también en Windows.", "inputSchema": EMPTY_PARAMETERS},
    {"name": "apple.keyed_archive", "title": "Apple · Archivo de objetos Foundation",
     "description": "Lee NSKeyedArchiver XML/binario como grafo de objetos, clases, raíces y referencias UID. No instancia clases.",
     "inputSchema": {"type": "object", "additionalProperties": False, "properties": {
         "root": {"type": "string"}, "offset": {"type": "integer", "minimum": 0}, "limit": {"type": "integer", "minimum": 0}}}},
    {"name": "apple.nib", "title": "Apple · Interfaz NIBArchive",
     "description": "Recupera los objetos, clases, valores y conexiones de un NIBArchive compilado, sin cargar su interfaz.", "inputSchema": EMPTY_PARAMETERS},
    {"name": "wasm.artifact", "title": "WebAssembly · Interfaz y desensamblado",
     "description": "Valida y desensambla con WABT local: rangos y bytes originales de secciones, WAT completo con hash, firmas, imports y exports. Relaciona literales de JavaScript con los candidatos seleccionados; no carga módulos ni consulta la red.",
     "inputSchema": {"type": "object", "additionalProperties": False, "properties": {
         "glue_paths": {"type": "array", "items": {"type": "string", "minLength": 1}},
         "candidate_paths": {"type": "array", "items": {"type": "string", "minLength": 1}}}}},
    {"name": "evm.interface", "title": "EVM · Bytecode e interfaz",
     "description": "Analiza bytecode local: selectores, argumentos, mutabilidad, almacenamiento, instrucciones, bloques, flujo y metadatos CBOR. No consulta cadenas ni servicios.",
     "inputSchema": {"type": "object", "additionalProperties": False, "properties": {"encoding": {"type": "string", "enum": ["raw", "hex"]}}}},
    {"name": "flutter.elf", "title": "Flutter · ELF y snapshots Dart",
     "description": "Lee cabecera ELF, build IDs y símbolos/snapshots Dart seleccionados. Identifica las limitaciones del layout; no reconstruye código Dart.",
     "inputSchema": {"type": "object", "additionalProperties": False, "properties": {
         "symbols": {"type": "array", "items": {"type": "string"}},
         "snapshot_offsets": {"type": "array", "items": {"type": "integer", "minimum": 0}}}}},
    {"name": "javascript.application", "title": "JavaScript y Electron · Aplicación",
     "description": "Analiza un directorio o ASAR completo con parser JS/TS: módulos, imports/exports, roles, IPC, ventanas, fuentes y grafos semánticos. Conserva incertidumbres y contradicciones; no ejecuta los scripts.",
     "inputSchema": {"type": "object", "additionalProperties": False, "properties": {
         "source_paths": {"type": "array", "items": {"type": "string"}}}}},
    {"name": "javascript.query", "title": "JavaScript · Procedencia e influencia",
     "input": "analysis", "requires_operation": "javascript.application",
     "description": "Consulta el grafo semántico guardado sin volver a analizar la aplicación. query: {seed:{kind:'literal',value:7},direction:'backward-provenance'|'forward-influence'|'callers'|'ownership'}. Admite semillas property/name, endpoint/value, event/name, semantic-node/node_id o function/fingerprint_sha256; mantiene las fronteras desconocidas.",
     "example": {"query": {"seed": {"kind": "literal", "value": 7}, "direction": "forward-influence"}},
     "inputSchema": {"type": "object", "additionalProperties": False, "required": ["source_job_id", "query"], "properties": {
         "source_job_id": {"type": "string"}, "query": {"type": "object"}}}},
    {"name": "javascript.feature", "title": "JavaScript y Electron · Trazar función de la aplicación",
     "input": "analysis", "requires_operation": "javascript.application",
     "description": "Sigue una función de la aplicación desde un canal, ruta, cadena, módulo o nodo del grafo guardado. query: {seed:{kind:'channel'|'route'|'string'|'module'|'node-id'|'api'|'native-export',value:'…'},direction:'incoming'|'outgoing'|'both'}. Conserva el alcance y las inferencias de cada relación.",
     "example": {"query": {"seed": {"kind": "channel", "value": "gauge:read"}, "direction": "both"}},
     "inputSchema": {"type": "object", "additionalProperties": False, "required": ["source_job_id", "query"], "properties": {
         "source_job_id": {"type": "string"}, "query": {"type": "object"}}}},
]

PAIR_PARAMETERS = {"type": "object", "additionalProperties": False,
    "required": ["reference_job_id", "candidate_job_id"], "properties": {
        "reference_job_id": {"type": "string"}, "candidate_job_id": {"type": "string"}}}
OPERATIONS += [{"name": "javascript.reconcile_runtime", "title": "JavaScript · Comparar fuentes y scripts observados",
    "input": "pair", "worker": "python", "requires_operation": "javascript.application",
    "candidate_requires_operation": "javascript.observe",
    "description": "Compara hashes de archivos y textos Inspector guardados. Los mapeos URL/ruta son declaraciones; conserva contradicciones, ambigüedad y no observados sin conectarse al destino.",
    "inputSchema": {**PAIR_PARAMETERS, "properties": {**PAIR_PARAMETERS['properties'],
        "mappings": {"type": "array", "items": {"type": "object", "additionalProperties": False,
            "required": ["runtime_url", "source_path"], "properties": {
                "runtime_url": {"type": "string"}, "source_path": {"type": "string"}}}}}}}]
OPERATIONS += [
    {"name":"process.compare","title":"Procesos · Comparar capturas guardadas","input":"pair","worker":"python",
     "retained_only":True,"requires_operation":"process.capture",
     "source_states":["finished","failed","cancelled","interrupted","imported"],
     "description":"Compara dimensiones explícitas de dos capturas guardadas: bytes de salida, código final, terminal, archivos antes/después y obligaciones de orden parcial. Conserva las ausencias como desconocidas; no ejecuta los programas ni consulta sus rutas originales.",
     "inputSchema":{**PAIR_PARAMETERS,"required":[*PAIR_PARAMETERS['required'],'query'],
         "properties":{**PAIR_PARAMETERS['properties'],'query':PROCESS_QUERY}},
     "example":{"query":{"dimensions":["stdout","stderr","exit","files"]}}},
    {**OPERATIONS[-1],"name":"browser.reconcile_sources","title":"Web · Comparar fuentes y scripts de página",
     "candidate_requires_operation":["browser.observe","browser.scenario","browser.coverage"],"candidate_states":["finished","failed","cancelled","interrupted"]},
    {"name":"browser.compare","title":"Web · Comparar capturas guardadas","input":"pair","worker":"python",
     "requires_operation":["browser.observe","browser.scenario"],"inputSchema":PAIR_PARAMETERS,
     "source_states":["finished","failed","cancelled","interrupted"],
     "description":"Compara observaciones de scripts/red, árbol DOM sin IDs locales y hashes PNG guardados. Conserva ausencias como desconocidas; igualdad de observaciones no demuestra equivalencia."},
]
OPERATIONS += [
    {"name": "browser.export_scripts", "title": "Web · Exportar fuentes guardadas", "input": "analysis", "worker": "python",
     "retained_only": True,
     "requires_operation": ["browser.observe", "browser.scenario", "browser.coverage"],
     "source_states": ["finished", "failed", "cancelled", "interrupted", "imported"],
     "description": "Exporta scripts y respuestas ya guardados, con manifiesto, bytes y hashes. Conserva duplicados, exclusiones y ausencias; no conecta con el navegador ni descarga fuentes.",
     "inputSchema": {"type": "object", "additionalProperties": False, "required": ["source_job_id"], "properties": {"source_job_id": {"type": "string"}}}},
    *[{"name": name, "title": title, "input": "analysis", "requires_operation": "browser.export_scripts", "retained_only": True,
       "source_states": ["finished", "imported"], "description": description, "example": {"query": example},
       "inputSchema": {"type": "object", "additionalProperties": False, "required": ["source_job_id", "query"],
           "properties": {"source_job_id": {"type": "string"}, "query": {"type": "object"}}}}
      for name, title, description, example in [
          ("javascript.trace_source", "Web · Trazar posición original", "Consulta un script y mapa exportados por sus IDs, línea generada desde 1 y columna UTF-16 desde 0. Conserva todas las correspondencias de la posición y los límites sin mapa; no ejecuta ni descarga código.",
           {"script_id": "script-000000", "map_id": "response-000000", "line": 1, "column": 0}),
          ("javascript.trace_imports", "Web · Trazar imports guardados", "Lee imports y reexports literales de un script exportado con su URL y un import_map opcional. Conserva versiones, duplicados y resoluciones desconocidas; no ejecuta módulos.",
           {"script_id": "script-000000"}),
      ]],
]
OPERATIONS += [
    {"name": "artifact.compare", "title": "Artefactos · Comparar inventarios guardados", "input": "pair",
     "requires_operation": "artifact.inventory", "inputSchema": PAIR_PARAMETERS,
     "description": "Compara contenido, metadatos y relaciones por ocurrencia lógica de dos inventarios guardados. Conserva duplicados ambiguos y cobertura desconocida; no lee los originales ni demuestra equivalencia de comportamiento."},
    {"name": "managed.compare", "title": ".NET · Comparar miembros y CIL", "input": "pair",
     "requires_operation": "managed.members", "inputSchema": PAIR_PARAMETERS,
     "description": "Compara dos análisis guardados: firmas, miembros e IL normalizado. Los tokens se tratan como identidades de cada compilación; las coincidencias ambiguas y la cobertura parcial permanecen explícitas."},
    {"name": "javascript.compare_versions", "title": "JavaScript · Comparar versiones", "input": "pair",
     "requires_operation": "javascript.application", "inputSchema": PAIR_PARAMETERS,
     "description": "Compara dos grafos guardados de aplicaciones: módulos, funciones, canales y relaciones. Conserva las coincidencias ambiguas y los cambios de cobertura, sin ejecutar las aplicaciones."},
    {"name": "javascript.compare_exports", "title": "JavaScript · Comparar formas de exports", "input": "pair",
     "requires_operation": "javascript.application", "inputSchema": {**PAIR_PARAMETERS,
         "required": [*PAIR_PARAMETERS["required"], "query"], "properties": {**PAIR_PARAMETERS["properties"],
         "query": {"type": "object", "additionalProperties": False, "required": ["reference", "candidate"],
             "properties": {side: {"type": "object", "additionalProperties": False,
                 "required": ["module_path", "export_name"], "properties": {
                     "module_path": {"type": "string"}, "export_name": {"type": "string"}}}
                 for side in ("reference", "candidate")}}}},
     "example": {"query": {"reference": {"module_path": "rule.cjs", "export_name": "normalize"},
                           "candidate": {"module_path": "rule.cjs", "export_name": "normalize"}}},
     "description": "Selecciona exactamente un export de cada grafo guardado y compara sus formas de retorno estáticas, propiedades y variantes. Una forma desconocida o ausente no se convierte en una coincidencia."},
]

OPERATIONS += [{"name": name, "title": title, "description": description, "inputSchema": EMPTY_PARAMETERS}
    for name, title, description in [
        ("artifact.inventory", "Artefactos · Inventario completo", "Inventario de directorios y contenedores, con identidades, relaciones y limitaciones explícitas; no ejecuta su contenido."),
        ("artifact.extract", "Artefactos · Extraer contenido", "Extrae archivos y cortes de arquitectura a un directorio nuevo del trabajo; conserva hashes y rutas de origen."),
        ("managed.graph", ".NET · Grafo de aplicación", "Relaciona ensamblados, módulos, tipos, miembros, llamadas CIL y fronteras P/Invoke con los metadatos del mismo archivo."),
        ("apple.application", "Apple · Grafo de aplicación", "Proyecta el inventario IPA/app/ZIP en componentes, bundles, plataformas y posibles puentes; no afirma llamadas observadas."),
        ("android.application", "Android · Grafo de aplicación", "Proyecta inventarios APK, DEX, recursos y bibliotecas en un grafo con identidades y límites de cobertura."),
        ("harmony.application", "HarmonyOS · Grafo de aplicación", "Proyecta inventarios HAP/HSP/App Pack, manifiestos, bytecode, recursos y bibliotecas; no afirma decodificar semántica Ark."),
    ]]
OPERATIONS += [{"name": name, "title": title, "description": description,
    "inputSchema": {"type": "object", "additionalProperties": False, "properties": {"query": {"type": "object"}}},
    **({"platforms": ["darwin"]} if name == "apple.assets" else {})}
    for name, title, description in [
        ("apple.interface_builder", "Apple · Interfaz y conexiones", "Decodifica NIB/storyboards compilados y jerarquías dentro de un app bundle sin cargar su interfaz."),
        ("apple.assets", "Apple · Catálogos de recursos", "Relaciona metadatos Assets.car con claves de Interface Builder. Requiere assetutil de macOS."),
        ("apple.dylibs", "Apple · Resolución de bibliotecas", "Sigue comandos de carga y rutas de bibliotecas Mach-O locales sin ejecutarlas."),
    ]]


OPERATIONS += STRUCTURED_OPERATIONS
OPERATIONS += ELF_OPERATIONS
OPERATIONS += OBJDUMP_OPERATIONS
OPERATIONS += EVIDENCE_OPERATIONS
OPERATIONS += RECORDING_OPERATIONS
OPERATIONS += SIGNAL_OPERATIONS
OPERATIONS += ANDROID_OPERATIONS
OPERATIONS += PACKET_OPERATIONS
OPERATIONS += QLOG_OPERATIONS
OPERATIONS += FIRMWARE_OPERATIONS
OPERATIONS += [{"name": "apple.dispatch", "title": "Apple · Metadatos Objective-C y Swift",
    "description": "Decodifica clases, métodos, protocolos, propiedades, ivars, conformances y dispatch/vtables admitidos desde bytes Mach-O de 64 bits. Conserva offsets y cobertura de cada faceta; funciona sin ejecutar la app ni cargar el runtime Apple.",
    "inputSchema": {"type": "object", "additionalProperties": False, "properties": {
        "architecture": {"enum": ["arm64", "x86_64"]}, "max_records": {"type": "integer", "minimum": 1}}}}]
OPERATIONS += [{"name": "pe.resources", "title": "PE · Recursos nativos", "inputSchema": EMPTY_PARAMETERS,
    "description": "Decodifica el árbol tipo/nombre/idioma de recursos PE con offsets de archivo y RVA, tamaños y hashes de payload. Conserva identidades UTF-16 y relaciones de iconos; no ejecuta el binario."}]
OPERATIONS += [
    {"name": "source.graph", "title": "Fuentes · Inventario histórico", "inputSchema": EMPTY_PARAMETERS,
     "description": "Compromete rutas y contenido físico de una carpeta de fuentes sin ejecutarlo; conserva incertidumbres de enlaces y entradas especiales."},
    {"name": "javascript.compare_source", "title": "JavaScript · Comparar fuentes con distribución", "input": "pair",
     "requires_operation": "source.graph", "candidate_requires_operation": "javascript.application", "inputSchema": PAIR_PARAMETERS,
     "description": "Relaciona el inventario de fuentes con el grafo de la aplicación mediante hashes, rutas y mapas de fuentes. Una correspondencia inferida no demuestra equivalencia."},
    {"name": "wasm.compare_interfaces", "title": "WebAssembly · Comparar interfaces", "input": "pair", "retained_only": True,
     "source_states": ["finished", "failed", "cancelled", "interrupted", "imported"],
     "requires_operation": "wasm.artifact", "inputSchema": {**PAIR_PARAMETERS, "properties": {**PAIR_PARAMETERS["properties"], "query": {"type": "object", "properties": {"scope": {"enum": ["both", "imports", "exports"]}}, "additionalProperties": False}}},
     "description": "Compara interfaces tipadas de dos análisis WABT guardados: cambios de firma y límites, duplicados y semántica desconocida explícitos; no ejecuta módulos."},
    {"name": "managed.reconstruction", "title": ".NET · Importar reconstrucción", "input": "analysis",
     "requires_operation": "managed.members", "inputSchema": {"type": "object", "additionalProperties": False,
        "required": ["source_job_id", "query"], "properties": {"source_job_id": {"type": "string"}, "query": {"type": "object"}}},
     "description": "Importa texto C#/IL/pseudocódigo de un decompilador con tokens y hashes exactos del análisis CIL guardado. query requiere decompiler{name,family} y methods[{token,signature_sha256,normalized_il_sha256,reconstruction{kind,language,text}}]; se guarda como inferencia, sin ejecutar ni modificar el original."},
]
OPERATIONS += [{"name": "javascript.recover", "title": "JavaScript · Recuperar fuentes legibles",
    "description": "Recupera sintaxis y módulos de tablas webpack/browserify, con mapas y rangos de bytes originales. No ejecuta el código; las formas estructurales no prueban equivalencia ni recuperan nombres originales.",
    "inputSchema": {"type": "object", "additionalProperties": False, "properties": {
        "query": {"type": "object", "additionalProperties": False, "properties": {
            "extraction_mode": {"enum": ["structural", "heuristic", "inspection"]},
            "rewrite_level": {"enum": ["minimal", "standard", "aggressive"]}}}}}}]

OPERATIONS += [{"name": "managed.verify_native", "title": ".NET · Contrastar declaraciones con nativo",
    "input": "analysis", "requires_operation": "managed.native_boundaries",
    "description": "Contrasta P/Invoke del análisis guardado con funciones Ghidra guardadas del mismo proyecto. native_job_ids selecciona sus trabajos analyze_function; conserva hashes, módulos, candidatos y desconocidos. Una coincidencia estática no prueba ejecución ni enlace del sistema.",
    "inputSchema": {"type": "object", "additionalProperties": False, "required": ["source_job_id", "native_job_ids"],
        "properties": {"source_job_id": {"type": "string"}, "native_job_ids": {"type": "array", "minItems": 1,
            "uniqueItems": True, "items": {"type": "string"}}}}}]


def engine():
    node = shutil.which("node")
    entry = ENGINE / "dist" / "entry.js"
    return {"available": bool(node and entry.is_file()), "node": node, "entry": str(entry),
            "external_api_required": False}


def catalog():
    rows = []
    for row in OPERATIONS:
        reason = ""
        if sys.platform not in row.get("platforms", [sys.platform]):
            reason = "Requiere " + ", ".join(row["platforms"])
        elif row["name"].startswith("capture.") and not packet_engine():
            reason = "Instala TShark o configura THESEUS_TSHARK."
        elif row["name"].startswith("signal.") and not signal_engine():
            reason = "Instala sigrok-cli o configura THESEUS_SIGROK."
        elif row["name"] in {item["name"] for item in ANDROID_OPERATIONS}:
            reason = android_availability(row["name"])
        elif row["name"].startswith("firmware."):
            reason = firmware_availability(row["name"])
        elif row["name"] == "binary.objdump" and not objdump_engine()['available']:
            reason = "Instala GNU objdump o configura THESEUS_OBJDUMP."
        rows.append({**row, "available": not reason, "availability_reason": reason})
    return {"engine": engine(), "operations": rows}


def start(manager, project_id, artifact_id, operation, parameters=None):
    definition = next((row for row in OPERATIONS if row["name"] == operation), None)
    if definition is None:
        raise ValueError("Unknown native analysis operation")
    if sys.platform not in definition.get("platforms", [sys.platform]):
        raise ValueError("This operation requires " + ", ".join(definition["platforms"]))
    if operation.startswith("firmware.") and firmware_availability(operation):
        raise ValueError(firmware_availability(operation))
    parameters = json.loads(json.dumps(parameters or {}))
    try:
        validate(parameters, definition["inputSchema"])
    except Exception as exc:
        raise ValueError("Analysis parameters do not match the operation: " + str(exc)) from exc
    artifact = manager.store.artifact(project_id, artifact_id)
    parent = None
    candidate = None
    selected_inputs = []
    if definition.get('input') == 'set':
        from .retained_evidence import bind_inputs
        selected_inputs = bind_inputs(manager.store, project_id, parameters['source_job_ids'])
        parent = manager.store.job(parameters['source_job_ids'][0])
        if parent['result']['artifact_id'] != artifact_id:
            raise ValueError('The first selected analysis must belong to this project artifact')
        required = definition.get('requires_operation')
        if required and any(row['operation'] not in ([required] if isinstance(required,str) else required)
                            for row in selected_inputs if row['selected']):
            raise ValueError('Select retained documents of the required operation')
    if definition.get("input") in {"analysis", "pair"}:
        source_key = "reference_job_id" if definition["input"] == "pair" else "source_job_id"
        parent = manager.store.job(parameters[source_key])
        if parent["project_id"] != project_id or parent["result"].get("artifact_id") != artifact_id:
            raise ValueError("The source analysis must belong to this project artifact")
        source_operations=definition['requires_operation']
        if isinstance(source_operations,str):source_operations=[source_operations]
        if parent["state"] not in definition.get('source_states',['finished']) or parent["result"].get("operation") not in source_operations:
            raise ValueError("Select a completed " + ' or '.join(source_operations) + " analysis")
        if definition["input"] == "pair":
            candidate = manager.store.job(parameters["candidate_job_id"])
            candidate_operation = definition.get("candidate_requires_operation", definition["requires_operation"])
            if isinstance(candidate_operation,str):candidate_operation=[candidate_operation]
            if candidate["project_id"] != project_id or candidate["state"] not in definition.get('candidate_states',definition.get('source_states',['finished'])) or candidate["result"].get("operation") not in candidate_operation:
                raise ValueError("Select a completed candidate " + ' or '.join(candidate_operation) + " analysis in this project")
    configured = engine() if definition.get("worker") != "python" else {
        "available": True, "python": sys.executable, "entry": str(Path(__file__).with_name("structured.py"))}
    if operation == 'evidence.compare_functions':
        from .retained_evidence import bind_inputs
        selected_inputs = bind_inputs(manager.store,project_id,[parent['id'],candidate['id']])
    if not configured["available"]:
        raise ValueError("Install the native analysis core with Install.ps1 (Node 22.19+ and engine build)")
    native_jobs, native_inputs = [], []
    if operation == "managed.verify_native":
        for native_id in parameters["native_job_ids"]:
            observed = manager.store.job(native_id)
            if observed["project_id"] != project_id or observed["state"] != "finished" or observed["result"].get("operation") != "binary.analyze_function":
                raise ValueError("Select completed native analyze_function observations in this project")
            original = manager.store.artifact(project_id, observed["result"]["artifact_id"])
            profile = manager.store.job(observed["result"]["session_id"])["result"]["profile"]
            kind = original["inspection"]["format"]
            native_inputs.append({"path": str(analysis_file(manager.store,native_id)),
                "sha256": observed["result"]["analysis_sha256"], "artifact_path": original["path"],
                "artifact_sha256": observed["result"]["artifact_sha256"],
                "artifact_format": kind if kind in {"pe","elf","mach-o"} else "unknown",
                "version": profile["version"], "job_id": native_id})
            native_jobs.append(observed)
    job_id = identifier()
    folder = manager.store.directory / "analyses" / job_id
    folder.mkdir(parents=True)
    request = {"operation": operation, "path": artifact["path"], "parameters": parameters}
    if operation in {"artifact.extract", "javascript.recover", "firmware.extract"}:
        request["parameters"] = {**parameters, "output_directory": str(folder / "extracted")}
    if parent:
        request.update(path=str(analysis_file(manager.store, parent["id"])),
                       expected_input_sha256=parent["result"]["analysis_sha256"],
                       source_artifact_sha256=parent["result"]["artifact_sha256"])
        request["parameters"] = {key: value for key, value in parameters.items() if key not in {
            "source_job_id", "reference_job_id", "candidate_job_id"}}
    if selected_inputs:
        request['source_inputs'] = selected_inputs
        request['parameters'] = {key:value for key,value in parameters.items() if key not in {
            'source_job_ids','source_job_id','reference_job_id','candidate_job_id'}}
        if operation=='evidence.compare_functions':
            request['source_input_roles']={'reference_job_id':parent['id'],'candidate_job_id':candidate['id']}
        if operation in {'evidence.changed_behavior','evidence.correlate'}:
            request['validation_engine'] = engine()
    if candidate:
        request.update(candidate_path=str(analysis_file(manager.store, candidate["id"])),
                       expected_candidate_sha256=candidate["result"]["analysis_sha256"])
    if operation == "browser.export_scripts":
        request["parameters"]["output_directory"] = str(folder / "extracted")
    if operation == "managed.verify_native":
        request["parameters"].pop("native_job_ids")
        request["native_inputs"] = native_inputs
    (folder / "request.json").write_text(json.dumps(request, ensure_ascii=False, indent=2), encoding="utf-8")
    result = {"kind": "native_analysis", "operation": operation, "title": definition["title"],
              "artifact_id": artifact_id, "artifact_name": artifact["name"],
              "recorded_artifact_sha256": artifact["sha256"],
              "initial_source_sha256": parent["result"]["artifact_sha256"] if parent else digest(artifact["path"]),
              "parameters": parameters, "engine": configured, "cases": [], "passed": 0, "failed": 0}
    if parent:
        result.update(source_analysis_job_id=parent["id"], source_analysis_sha256=parent["result"]["analysis_sha256"])
    if candidate:
        result["source_analyses"] = [{"side": side, "job_id": job["id"],
            "artifact_id": job["result"]["artifact_id"], "sha256": job["result"]["artifact_sha256"],
            "analysis_sha256": job["result"]["analysis_sha256"]}
            for side, job in (("reference", parent), ("candidate", candidate))]
    if selected_inputs:
        result['source_analyses'] = [{'side':'selected' if row['selected'] else 'closure','job_id':row['job_id'],
            'artifact_id':row['artifact_id'],'sha256':row['artifact_sha256'],'analysis_sha256':row['analysis_sha256']}
            for row in selected_inputs if 'path' in row]
    if native_jobs:
        result["source_analyses"] = [{"side": side, "job_id": job["id"], "artifact_id": job["result"]["artifact_id"],
            "sha256": job["result"]["artifact_sha256"], "analysis_sha256": job["result"]["analysis_sha256"]}
            for side,job in [("reference",parent), *[("native",item) for item in native_jobs]]]
    manager.store.save_job(project_id, job_id, "queued", result)
    manager.pool.submit(_run, manager, project_id, job_id, artifact, folder, result)
    return manager.store.job(job_id)


def _run(manager, project_id, job_id, artifact, folder, result):
    output = folder / "analysis.json"
    state = "failed"
    configured = result["engine"]
    command = [configured.get("python", configured.get("node")), configured["entry"], str(folder / "request.json"), str(output)]
    try:
        manager.store.save_job(project_id, job_id, "running", result)
        execution_definition = {}
        if result['operation']=='wasm.artifact':
            from .wasm_recording import record_worker
            def observe_worker(process):
                result['worker_identity_recording']=record_worker(folder,process,command)
            execution_definition['spawn_observer']=observe_worker
        execution = manager._execute(job_id, command, execution_definition)
        result["execution"] = execution
        with manager.lock:
            stopped = job_id in manager.cancelled
        failed_execution = bool(execution["exit_code"]) or not output.is_file()
        retained_firmware = False
        retained_objdump = False
        retained_wasm = False
        if result['operation']=='wasm.artifact':
            from .wasm_recording import recording
            snapshot=recording(folder,output)
            if snapshot is not None:
                output=snapshot[0];retained_wasm=True
                if failed_execution:
                    result['error']='The WebAssembly inspection did not complete; retained observations and the engine diagnostic remain available'
        if result['operation'] == 'binary.objdump':
            from .objdump_inspection import recording
            value = recording(folder, interrupted=stopped or failed_execution)
            if value is not None:
                document = {'operation': result['operation'], 'artifact_sha256': value['artifact']['sha256'],
                    'runtime': sys.version.split()[0], 'result': value}
                output = folder / 'objdump-retained.json'
                output.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding='utf8')
                retained_objdump = True
        if result["operation"].startswith("firmware."):
            from .firmware import recording_file
            checkpoint = recording_file(folder, output)
            retained_firmware = checkpoint is not None
            if retained_firmware: output = checkpoint
        if stopped and not (retained_firmware or retained_objdump or retained_wasm):
            state = "cancelled"
        elif failed_execution and not (retained_firmware or retained_objdump or retained_wasm):
            state = "failed"
            result["error"] = "The native analysis did not complete; inspect the engine diagnostic"
        else:
            if retained_firmware and (stopped or failed_execution):
                from .firmware import freeze_recording
                output = freeze_recording(folder, output)
            retain(manager.store, project_id, job_id, artifact, folder, output, result,
                   observe_source=not (retained_wasm and (stopped or failed_execution)))
            with manager.lock:
                stopped = job_id in manager.cancelled
            state = "cancelled" if stopped else "failed" if failed_execution else "finished"
    except InterruptedError:
        state = "cancelled"
    except Exception as exc:
        result["error"] = type(exc).__name__ + ": " + str(exc)
        state = "failed"
    finally:
        if result["operation"].startswith("firmware."):
            try:
                (folder / "firmware-input.bin").unlink(missing_ok=True)
            except OSError as exc:
                result["cleanup_error"] = str(exc)
                if state == "finished": state = "failed"
        with manager.lock:
            manager.cancelled.discard(job_id)
    manager.store.save_job(project_id, job_id, state, result)


def retain(store, project_id, job_id, artifact, folder, output, result, *, observe_source=True):
    document = json.loads(output.read_text(encoding="utf-8"))
    if result['operation'] == 'binary.objdump':
        result['reader_observation'] = {key: document['result'][key] for key in
            ['exit_code', 'completion_status', 'stream_complete', 'artifact_changed']}
    if result['operation']=='wasm.artifact':
        result['wasm_observation']={key:document['result'].get(key) for key in ['validation','phase','completion_status']}
    result.update(artifact_sha256=document["artifact_sha256"], analysis_file=str(output),
                  analysis_sha256=digest(output), runtime=document["runtime"])
    result["source_changed"] = document["artifact_sha256"] != artifact["sha256"]
    definition = next(row for row in OPERATIONS if row["name"] == result["operation"])
    if definition.get("retained_only") or not observe_source:
        result.update(source_unavailable=None, source_changed_during_analysis=None,
                      original_source_check="not-performed-retained-input" if observe_source else "not-performed-retained-observation")
    else:
        available = Path(artifact["path"]).exists()
        result["source_unavailable"] = not available
        result["source_changed_during_analysis"] = available and digest(artifact["path"]) != document["artifact_sha256"]
    result["sections"] = store.index_analysis(job_id, document["result"])
    if result["operation"] in {"artifact.extract", "javascript.recover", "android.resources", "firmware.extract", "browser.export_scripts"}:
        result["derived_artifacts"] = []
        derived_by_path = {}
        for row in document["result"]["artifacts"]:
            path = (folder / "extracted" / row["relative_path"]).resolve()
            if not path.is_relative_to((folder / "extracted").resolve()):
                raise ValueError("Extracted artifact leaves its job directory")
            child = store.add_artifact(project_id, path)
            if child["sha256"] != row["sha256"]:
                raise ValueError("Extracted artifact differs from its recorded bytes")
            parent_id = derived_by_path[row["parent_relative_path"]] if row.get("parent_relative_path") else artifact["id"]
            store.link_artifact(project_id, parent_id, child["id"], job_id, row.get("source_location", row["relative_path"]))
            derived_by_path[row["relative_path"]] = child["id"]
            result["derived_artifacts"].append({"id": child["id"], "name": row["relative_path"], "sha256": child["sha256"]})


def recover(store):
    from .firmware import freeze_recording, stop_interrupted_worker, recording_file
    for project in store.projects():
        for job in store.items('jobs',project['id']):
            result=job['result']
            if job['state']=='interrupted' and result.get('operation')=='wasm.artifact' and not result.get('analysis_file'):
                from . import wasm_recording
                import psutil
                folder=store.directory/'analyses'/job['id']
                try:
                    configured=result['engine']
                    command=[configured['node'],configured['entry'],str(folder/'request.json'),str(folder/'analysis.json')]
                    cleanup=wasm_recording.stop_interrupted_worker(folder,command)
                    frozen=wasm_recording.freeze_recording(folder,folder/'analysis.json')
                    if frozen is not None:
                        output,snapshot=frozen
                        retain(store,project['id'],job['id'],store.artifact(project['id'],result['artifact_id']),folder,output,result,observe_source=False)
                        result.update(recovered_recording=True,recovery_cleanup=cleanup,recording_snapshot=snapshot)
                except (OSError,ValueError,KeyError,RuntimeError,psutil.Error) as error:
                    result['recovery_error']=str(error)
                store.save_job(project['id'],job['id'],'interrupted',result)
                continue
            if job['state'] == 'interrupted' and result.get('operation') == 'binary.objdump' and not result.get('analysis_file'):
                from . import objdump_inspection
                folder = store.directory / 'analyses' / job['id']
                try:
                    cleanup = objdump_inspection.stop_interrupted_worker(folder)
                    value = objdump_inspection.recording(folder, interrupted=True)
                    if value is not None:
                        value['recovery_cleanup'] = cleanup
                        output = folder / 'objdump-recovered.json'
                        output.write_text(json.dumps({'operation': result['operation'],
                            'artifact_sha256': value['artifact']['sha256'], 'runtime': sys.version.split()[0],
                            'result': value}, ensure_ascii=False, indent=2), encoding='utf8')
                        retain(store, project['id'], job['id'], store.artifact(project['id'], result['artifact_id']), folder, output, result)
                        result['recovered_recording'] = True
                except (OSError, ValueError, KeyError) as exc:
                    result['recovery_error'] = str(exc)
                store.save_job(project['id'], job['id'], 'interrupted', result)
                continue
            if job['state']!='interrupted' or not result.get('operation','').startswith('firmware.') or result.get('analysis_file'):
                continue
            folder=store.directory/'analyses'/job['id'];output=recording_file(folder,folder/'analysis.json')
            if not (folder/'request.json').is_file() or output is None:continue
            try:
                cleanup=stop_interrupted_worker(folder,output)
                output=recording_file(folder,folder/'analysis.json')
                frozen=freeze_recording(folder,output,cleanup)
                retain(store,project['id'],job['id'],store.artifact(project['id'],result['artifact_id']),folder,frozen,result)
                result['recovered_recording']=True
                if cleanup['status'] in {'terminated-owned-worker','not-running','no-owned-worker-identity'}:
                    (folder/'firmware-input.bin').unlink(missing_ok=True)
            except (OSError,ValueError,KeyError) as exc:result['recovery_error']=str(exc)
            store.save_job(project['id'],job['id'],'interrupted',result)


def analysis_file(store, job_id):
    job = store.job(job_id)
    if job["result"].get("kind") not in {"native_analysis", "runtime_analysis"} or "analysis_file" not in job["result"]:
        raise LookupError("No retained native analysis document")
    path = Path(job["result"]["analysis_file"]).resolve()
    if not path.is_relative_to(store.directory / "analyses"):
        raise ValueError("Analysis document is outside its project storage")
    return path
