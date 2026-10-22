"""Static APK/DEX observations through a Theseus-owned JADX library reader."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import re
import xml.etree.ElementTree as ET
from xml.parsers import expat
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
LOCALE = {'type': 'string', 'pattern': r'^(?:[a-z]{2,3}(?:-(?:r?[A-Z]{2}|r?[0-9]{3}))?|b\+[a-z]{2,3}(?:\+[A-Za-z0-9]{2,8})*)$'}
RESOURCE_SELECTION = {'include_strings': {'type': 'boolean'}, 'locale': LOCALE,
                      'locales': {'type': 'array', 'minItems': 1, 'items': LOCALE}}
OPERATIONS = []
for name, title, description, properties, required in [
    ('package', 'Paquete y manifiesto', 'Manifiesto decodificado, permisos, SDK, clases y recursos del APK. Resumen opcional enlazado a la fuente completa conservada; no instala ni ejecuta el paquete.', {'detail': {'enum': ['complete', 'summary']}}, []),
    ('classes', 'Buscar clases', 'Clases DEX con nombres originales y alias. Búsqueda literal sensible a mayúsculas; paginación explícita sin deduplicar clases.',
     {**PAGE, 'query': {'type': 'string'}, 'include_inner': {'type': 'boolean'}}, []),
    ('class', 'Miembros de una clase', 'Métodos y campos DEX, incluidos sintéticos, firmas, prototipos y sobrecargas fijados antes de generar Java; código de clase opcional.',
     {**CLASS, 'include_code': {'type': 'boolean'}}, ['class_name']),
    ('method', 'Código de un método', 'Selecciona clase/método/sobrecarga exactos. Java reconstruido o Smali con motivo explícito si no aparece en Java. Declaraciones sin cuerpo diferenciadas.',
     {**CLASS, **METHOD}, ['class_name', 'method_name']),
    ('references', 'Referencias estáticas', 'Nodos que usan una clase o un método, invocaciones DEX directas con offsets en unidades de código y posiciones de Java reconstruido opcionales. No demuestra llamadas en ejecución.',
     {**CLASS, **METHOD, **PAGE, 'resolve_lines': {'type': 'boolean'}}, ['class_name']),
    ('resources', 'Decodificar recursos', 'Decodifica recursos APK con Apktool local, metadatos y tablas de cadenas predeterminadas o por idioma. Conserva archivos completos, conteos, cobertura y diagnósticos; no ejecuta el APK.', RESOURCE_SELECTION, []),
]:
    OPERATIONS.append({'name': 'android.'+name, 'title': 'Android · '+title, 'description': description,
        'worker': 'python', 'inputSchema': {'type': 'object', 'additionalProperties': False,
            'properties': properties, 'required': required}})

OPERATIONS.append({'name': 'android.package_view', 'title': 'Android · Consultar paquete guardado',
    'description': 'Resumen de declaraciones o ventana de manifiesto en unidades UTF-16 del análisis conservado; no vuelve a abrir el APK ni el lector.',
    'worker': 'python', 'input': 'analysis', 'requires_operation': 'android.package',
    'source_states': ['finished', 'imported'], 'retained_only': True,
    'inputSchema': {'type': 'object', 'additionalProperties': False, 'required': ['source_job_id'],
        'properties': {'source_job_id': {'type': 'string'}, 'facet': {'enum': ['summary', 'manifest']},
                       'offset': {'type': 'integer', 'minimum': 0}, 'limit': {'type': 'integer', 'minimum': 1}}}})


def locale_directory(locale):
    if (not isinstance(locale, str) or not re.fullmatch(LOCALE['pattern'], locale)
            or locale in {'car', 'desk', 'television', 'appliance', 'watch', 'vrheadset', 'night', 'notnight'}):
        raise ValueError('Select an Android locale, such as es, pt-BR or b+zh+Hans+CN')
    return re.sub(r'^([a-z]{2,3})-([A-Z]{2}|[0-9]{3})$', r'\1-r\2', locale)


def apktool_metadata(text):
    import yaml
    from yaml.nodes import MappingNode, ScalarNode
    def mapping(node):
        if not isinstance(node, MappingNode):
            raise ValueError('Apktool metadata must contain mappings')
        result = {}
        for key, value in node.value:
            if not isinstance(key, ScalarNode) or key.value in result:
                raise ValueError('Apktool metadata has a non-scalar or duplicate key')
            result[key.value] = value
        return result
    # Compose nodes, never construct objects. Numeric scalar spelling remains
    # exact (45.1, 0x2d), while quoted strings retain their decoded YAML value.
    try:
        root = mapping(yaml.compose(text, Loader=yaml.SafeLoader))
    except yaml.YAMLError as error:
        raise ValueError('Apktool metadata is not valid YAML') from error
    output = {}
    for group, source_key, destination in [('versionInfo', 'versionName', 'version_name'),
            ('versionInfo', 'versionCode', 'version_code'), ('sdkInfo', 'minSdkVersion', 'min_sdk_version'),
            ('sdkInfo', 'targetSdkVersion', 'target_sdk_version')]:
        node = mapping(root[group]).get(source_key) if group in root else None
        output[destination] = node.value if isinstance(node, ScalarNode) and node.tag != 'tag:yaml.org,2002:null' else None
    return output


def decoded_strings(text):
    """Keep lexical entity spelling and whitespace, excluding markup-bearing values."""
    raw = text.encode('utf-8')
    parser = expat.ParserCreate()
    stack, entries = [], []
    current = None
    unparsed = 0
    def start(name, attributes):
        nonlocal current
        if not stack and name != 'resources':
            raise ValueError('String table root must be resources')
        if current is not None:
            current['unsupported'] = True
        if len(stack) == 1 and name == 'string':
            current = {'name': attributes.get('name'), 'parts': [], 'end': -1, 'unsupported': False}
        stack.append(name)
    def end(name):
        nonlocal current, unparsed
        if len(stack) == 2 and name == 'string':
            if not current['name'] or current['unsupported']:
                unparsed += 1
            else:
                entries.append({'name': current['name'], 'value': ''.join(current['parts'])})
            current = None
        stack.pop()
    def characters(value):
        if current is None or len(stack) != 2:
            return
        offset = parser.CurrentByteIndex
        if offset < current['end']:
            return  # Entity callbacks can fall within an already retained text span.
        finish = raw.find(b'<', offset)
        if finish < 0:
            raise ValueError('String text has no closing markup')
        current['parts'].append(raw[offset:finish].decode('utf-8'))
        current['end'] = finish
    def unsupported(*args):
        if current is not None:
            current['unsupported'] = True
    parser.StartElementHandler, parser.EndElementHandler = start, end
    parser.CharacterDataHandler = characters
    parser.StartCdataSectionHandler = unsupported
    parser.ProcessingInstructionHandler = unsupported
    parser.ExternalEntityRefHandler = lambda *args: 0
    parser.Parse(raw, True)
    return entries, unparsed


def resource_projection(folder, parameters, *, decoded=True):
    selected = [parameters.get('locale'), *parameters.get('locales', [])]
    selected = list(dict.fromkeys(selected))
    for locale in selected:
        if locale is not None:
            locale_directory(locale)
    result = {'metadata': {key: None for key in ('version_name', 'version_code', 'min_sdk_version', 'target_sdk_version', 'package_name')},
              'manifest': None, 'strings': [], 'locale': parameters.get('locale'), 'locales': [],
              'string_tables': [], 'coverage': 'complete' if decoded else 'partial', 'limitations': []}
    try:
        result['manifest'] = (folder / 'AndroidManifest.xml').read_bytes().decode('utf-8')
        manifest = ET.fromstring(result['manifest'])
        if manifest.tag != 'manifest':
            raise ValueError('Manifest root must be manifest')
        result['metadata']['package_name'] = manifest.get('package')
    except (OSError, UnicodeError, ET.ParseError, ValueError) as error:
        result['coverage'] = 'partial'
        result['limitations'].append('Decoded manifest unavailable or malformed: ' + type(error).__name__)
    try:
        result['metadata'].update(apktool_metadata((folder / 'apktool.yml').read_text(encoding='utf-8')))
    except (OSError, UnicodeError, ValueError) as error:
        result['coverage'] = 'partial'
        result['limitations'].append('Decoded metadata unavailable or malformed: ' + type(error).__name__)
    available = []
    for path in sorted((folder / 'res').glob('values-*/strings.xml')):
        suffix = path.parent.name.removeprefix('values-')
        try:
            if locale_directory(suffix) == suffix:
                available.append(suffix)
        except ValueError:
            pass  # A configuration such as night is not a selectable locale.
    result['locales'] = available
    if parameters.get('include_strings', True):
        physical = {}
        for locale in selected:
            directory = 'values' if locale is None else 'values-' + locale_directory(locale)
            if directory not in physical:
                path = folder / 'res' / directory / 'strings.xml'
                fact = {'status': 'present', 'strings': [], 'total_count': None, 'unparsed_count': None, 'coverage': 'partial'}
                try:
                    entries, skipped = decoded_strings(path.read_bytes().decode('utf-8'))
                    fact.update(strings=entries, total_count=len(entries), unparsed_count=skipped,
                                coverage='partial' if skipped or not decoded else 'complete')
                except FileNotFoundError:
                    fact.update(status='missing' if decoded else 'unavailable', total_count=0 if decoded else None,
                                unparsed_count=0 if decoded else None, coverage='complete' if decoded else 'partial')
                except (OSError, UnicodeError, ValueError, expat.ExpatError):
                    fact['status'] = 'malformed'
                physical[directory] = fact
            table = {'locale': locale, **physical[directory]}
            result['string_tables'].append(table)
            if table['coverage'] == 'partial':
                result['coverage'] = 'partial'
        result['strings'] = result['string_tables'][0]['strings']
    return result


def delivery_sha256(value):
    payload = {key: item for key, item in value.items() if key != 'view_sha256'}
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest()


def package_summary(report):
    manifest = report.get('manifest_xml')
    result = {key: report[key] for key in ('status', 'package_name', 'version_code', 'version_name', 'sdk',
        'permissions', 'class_count', 'top_level_class_count', 'engine', 'diagnostics', 'snapshot_sha256', 'limitations') if key in report}
    result.update(resource_count=len(report.get('resources', [])), signature_verification='not_performed',
        manifest={'status': 'complete' if isinstance(manifest, str) and not report.get('manifest_metadata_error') else 'partial',
                  'text_code_units': len(manifest.encode('utf-16-le')) // 2 if isinstance(manifest, str) else 0,
                  'reported_total_bytes': len(manifest.encode('utf-8')) if isinstance(manifest, str) else None,
                  'text_included': False})
    return result


def package_view(source, parameters, expected_sha256):
    raw = source.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ValueError('Retained Android document changed while reading')
    document = json.loads(raw)
    if document.get('operation') != 'android.package':
        raise ValueError('Select a retained Android package analysis')
    summary = package_summary(document['result'])
    result = {'parent_analysis_sha256': expected_sha256, 'artifact_sha256': document['artifact_sha256'],
              'facet': parameters.get('facet', 'manifest')}
    if result['facet'] == 'summary':
        return {**result, 'summary': summary}
    text = document['result'].get('manifest_xml')
    if not isinstance(text, str):
        raise ValueError('The retained Android analysis has no decoded manifest text')
    raw_text = text.encode('utf-16-le')
    total = len(raw_text) // 2
    start = min(parameters.get('offset', 0), total)
    finish = min(start + parameters.get('limit', 4096), total)
    def splits(index):
        return (0 < index < total and 0xd800 <= int.from_bytes(raw_text[2*index-2:2*index], 'little') <= 0xdbff
                and 0xdc00 <= int.from_bytes(raw_text[2*index:2*index+2], 'little') <= 0xdfff)
    if splits(start):
        raise ValueError('Manifest offset splits a UTF-16 surrogate pair')
    if splits(finish):
        finish -= 1
    if finish == start and start < total:
        raise ValueError('Increase manifest limit to include the next complete Unicode character')
    return {**result, 'text': raw_text[2*start:2*finish].decode('utf-16-le'), 'unit': 'utf16-code-units',
            'source_status': summary['manifest']['status'], 'reported_total_bytes': summary['manifest']['reported_total_bytes'],
            'coverage': {'offset': start, 'examined': finish-start, 'total': total,
                         'next_offset': finish if finish < total else None, 'exhausted': finish >= total}}


def available(operation):
    if operation == 'android.package_view':
        return ''
    tools = engines()
    if not tools['java']:
        return 'Instala Java o configura THESEUS_JAVA_HOME.'
    if operation == 'android.resources':
        return '' if tools['apktool'] else 'Configura THESEUS_APKTOOL con el JAR de Apktool.'
    return '' if tools['javac'] and tools['jadx_jars'] else 'Instala un JDK y configura THESEUS_JADX_LIB con los JAR de JADX.'


def inspect_android(source, operation, parameters, output, source_sha256):
    if operation == 'android.package_view':
        return package_view(source, parameters, source_sha256)
    if operation == 'android.resources':
        for locale in [parameters.get('locale'), *parameters.get('locales', [])]:
            if locale is not None:
                locale_directory(locale)
    reason = available(operation)
    if reason:
        raise ValueError(reason)
    tools = engines()
    folder = output.parent
    snapshot = folder / ('android-input'+source.suffix)
    bridge = Path(__file__).resolve().parent.parent / 'software_native/engine/bridge/android/TheseusAndroidBridge.java'
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
            projection = resource_projection(extracted, parameters, decoded=invocation['exit_code'] == 0)
            projection['limitations'] = result['limitations'] + projection['limitations']
            result.update(projection, decoded_file_count=len(artifacts))
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
                    result.update(package_name=manifest.get('package'), version_code=manifest.get(android+'versionCode'),
                        version_name=manifest.get(android+'versionName'),
                        sdk={} if sdk is None else {key.removeprefix(android): val for key, val in sdk.attrib.items()},
                        permissions=[row.get(android+'name') for row in manifest if row.tag.startswith('uses-permission')])
        result.update(engine=identity, snapshot_sha256=source_sha256)
        if operation == 'android.package':
            result['summary'] = package_summary(result)
        return result
    finally:
        snapshot.unlink(missing_ok=True)
