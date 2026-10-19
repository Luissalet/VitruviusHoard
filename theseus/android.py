"""Static APK/DEX observations through a Theseus-owned JADX library reader."""
import json
import os
from pathlib import Path
import shutil
import xml.etree.ElementTree as ET
import zipfile

if __package__:
    from .signals import observed, sha
else:
    from signals import observed, sha


def engines():
    java_home = os.environ.get('THESEUS_JAVA_HOME', os.environ.get('JAVA_HOME', 'D:/LocalAI/tools/jdk21/jdk-21.0.12.1+1'))
    suffix = '.exe' if os.name == 'nt' else ''
    java = Path(java_home) / 'bin' / ('java'+suffix)
    javac = Path(java_home) / 'bin' / ('javac'+suffix)
    jadx = Path(os.environ.get('THESEUS_JADX_LIB', 'D:/LocalAI/tools/jadx779/runtime/lib'))
    apktool = Path(os.environ.get('THESEUS_APKTOOL', 'D:/LocalAI/tools/apktool779/apktool_3.0.3.jar'))
    return {'java': str(java) if java.is_file() else shutil.which('java'),
        'javac': str(javac) if javac.is_file() else shutil.which('javac'),
        'jadx_jars': sorted(str(p) for p in jadx.glob('*.jar')),
        'apktool': str(apktool) if apktool.is_file() else None}


PAGE = {'offset': {'type': 'integer', 'minimum': 0}, 'limit': {'type': ['integer', 'null'], 'minimum': 0}}
CLASS = {'class_name': {'type': 'string', 'minLength': 1}}
METHOD = {'method_name': {'type': 'string', 'minLength': 1}, 'overload_index': {'type': 'integer', 'minimum': 0}}
OPERATIONS = []
for name, title, description, properties, required in [
    ('package', 'Paquete y manifiesto', 'Manifiesto decodificado, permisos, SDK, clases y recursos del APK; no instala ni ejecuta el paquete.', {}, []),
    ('classes', 'Buscar clases', 'Clases DEX con nombres originales y alias. Búsqueda literal sensible a mayúsculas; paginación explícita sin deduplicar clases.',
     {**PAGE, 'query': {'type': 'string'}, 'include_inner': {'type': 'boolean'}}, []),
    ('class', 'Miembros de una clase', 'Métodos y campos DEX, incluidos sintéticos, firmas, prototipos y sobrecargas fijados antes de generar Java; código de clase opcional.',
     {**CLASS, 'include_code': {'type': 'boolean'}}, ['class_name']),
    ('method', 'Código de un método', 'Selecciona clase/método/sobrecarga exactos. Java reconstruido o Smali con motivo explícito si no aparece en Java. Declaraciones sin cuerpo diferenciadas.',
     {**CLASS, **METHOD}, ['class_name', 'method_name']),
    ('references', 'Referencias estáticas', 'Nodos que usan una clase o un método, invocaciones DEX directas con offsets en unidades de código y posiciones de Java reconstruido opcionales. No demuestra llamadas en ejecución.',
     {**CLASS, **METHOD, **PAGE, 'resolve_lines': {'type': 'boolean'}}, ['class_name']),
    ('resources', 'Decodificar recursos', 'Decodifica recursos APK con Apktool local en un directorio nuevo; registra cada archivo derivado y su hash, conserva diagnósticos y originales.', {}, []),
]:
    OPERATIONS.append({'name': 'android.'+name, 'title': 'Android · '+title, 'description': description,
        'worker': 'python', 'inputSchema': {'type': 'object', 'additionalProperties': False,
            'properties': properties, 'required': required}})


def available(operation):
    tools = engines()
    if not tools['java']:
        return 'Instala Java o configura THESEUS_JAVA_HOME.'
    if operation == 'android.resources':
        return '' if tools['apktool'] else 'Configura THESEUS_APKTOOL con el JAR de Apktool.'
    return '' if tools['javac'] and tools['jadx_jars'] else 'Instala un JDK y configura THESEUS_JADX_LIB con los JAR de JADX.'


def inspect_android(source, operation, parameters, output, source_sha256):
    reason = available(operation)
    if reason:
        raise ValueError(reason)
    tools = engines()
    folder = output.parent
    snapshot = folder / ('android-input'+source.suffix)
    bridge = Path(__file__).resolve().parent.parent / 'engine/bridge/android/TheseusAndroidBridge.java'
    identity = {'java': {'path': tools['java'], 'sha256': sha(tools['java']),
        'version': observed([tools['java'], '-version'])}}
    try:
        shutil.copyfile(source, snapshot)
        if sha(snapshot) != source_sha256 or sha(source) != source_sha256:
            raise ValueError('Android input changed while capturing its bytes')
        if operation == 'android.resources':
            identity['apktool'] = {'path': tools['apktool'], 'sha256': sha(tools['apktool']),
                'version': observed([tools['java'], '-jar', tools['apktool'], '--version'])}
            extracted = folder / 'extracted'
            invocation = observed([tools['java'], '-jar', tools['apktool'], 'd', '--no-src', '--jobs', '1',
                '--frame-path', str(folder/'apktool-framework'), '--output', str(extracted), str(snapshot)])
            artifacts = []
            if extracted.is_dir():
                for path in sorted(extracted.rglob('*')):
                    if path.is_symlink() or not path.resolve().is_relative_to(extracted.resolve()):
                        raise ValueError('Decoded resource leaves its job directory')
                    if path.is_file():
                        artifacts.append({'relative_path': path.relative_to(extracted).as_posix(),
                            'sha256': sha(path), 'size_bytes': path.stat().st_size})
            result = {'status': 'decoded' if invocation['exit_code'] == 0 else 'decoder-error',
                'artifacts': artifacts, 'observation': invocation,
                'limitations': ['Decoded resource names/XML are tool interpretations of this APK; target code was not executed.',
                    'A decoder-error can leave partial files; retained artifacts and diagnostics do not establish complete decoding.']}
        else:
            identity['jadx_jars'] = [{'path': p, 'sha256': sha(p)} for p in tools['jadx_jars']]
            identity['bridge_sha256'] = sha(bridge)
            compiled = folder / 'android-bridge'
            compiled.mkdir()
            classpath = os.pathsep.join(tools['jadx_jars'])
            compile_result = observed([tools['javac'], '-encoding', 'UTF-8', '-cp', classpath, '-d', str(compiled), str(bridge)])
            if compile_result['exit_code']:
                raise ValueError('Android reader compilation failed: '+compile_result['stderr'])
            request = folder / 'android-request.json'
            request.write_text(json.dumps({'path': str(snapshot), 'operation': operation, 'parameters': parameters}), encoding='utf8')
            reply = folder / 'android-reply.json'
            invocation = observed([tools['java'], '-cp', os.pathsep.join([str(compiled), classpath]),
                'TheseusAndroidBridge', str(request), str(reply)])
            result = json.loads(reply.read_text(encoding='utf8')) if invocation['exit_code'] == 0 and reply.is_file() else {
                'status': 'reader-error', 'limitations': ['The reader did not complete; inspect retained diagnostics. No absence of classes or references is established.']}
            result.update(observation=invocation, compilation=compile_result)
            with snapshot.open('rb') as handle:
                magic = handle.read(8)
            result['input_container'] = 'zip' if zipfile.is_zipfile(snapshot) else 'dex' if magic.startswith(b'dex\n') else 'unknown'
            if result['input_container'] == 'unknown':
                result.update(status='unrecognized-input')
                result['limitations'].append('The captured input is not recognized as ZIP/APK or DEX; empty engine lists do not certify absent classes or resources.')
            if operation == 'android.package' and result.get('manifest_xml'):
                try:
                    manifest = ET.fromstring(result['manifest_xml'])
                except ET.ParseError as exc:
                    result.update(status='partial', manifest_metadata_error=str(exc))
                else:
                    android = '{http://schemas.android.com/apk/res/android}'
                    sdk = manifest.find('uses-sdk')
                    result.update(package_name=manifest.get('package'),
                        sdk={} if sdk is None else {key.removeprefix(android): val for key, val in sdk.attrib.items()},
                        permissions=[row.get(android+'name') for row in manifest if row.tag.startswith('uses-permission')])
        result.update(engine=identity, snapshot_sha256=source_sha256)
        return result
    finally:
        snapshot.unlink(missing_ok=True)
