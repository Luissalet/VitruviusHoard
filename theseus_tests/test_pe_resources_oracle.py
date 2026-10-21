"""PE resource reader against PE files built here and the `pefile` library as an independent oracle.

Every image is linked in the test with zig from a small .rc script (VERSIONINFO with two translations, string tables
in two languages, RCDATA, a custom numeric and a custom named type, named ids, icon, bitmap, manifest, dialog, menu)
or compiled by the .NET Framework csc.exe. The expected facts come from walking `DIRECTORY_ENTRY_RESOURCE` with pefile
and hashing the bytes it reads at each leaf's RVA.
"""
import hashlib
import os
from pathlib import Path
import shutil
import struct
import subprocess

import pytest

from test_native_formats import inspect

try:
    import pefile
except ImportError:  # pragma: no cover
    pefile = None


def tool(variable, name):
    value = os.environ.get(variable) or shutil.which(name)
    return value if value and Path(value).is_file() else None


ZIG = tool('THESEUS_TEST_ZIG', 'zig')
CSC = tool('THESEUS_TEST_CSC', 'csc') or next((p for p in [r'C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe'] if Path(p).is_file()), None)
pytestmark = pytest.mark.skipif(pefile is None, reason='Requires the pefile library')

BLOB = bytes(range(256)) + b'\x00\x00resource-blob\xff\xfe' * 3
OVERLAY_NAME = 'NAMED_BLOB'


def icon_bytes():
    """A 2x2 32-bit .ico written byte by byte: ICONDIR, one entry, BITMAPINFOHEADER (doubled height), pixels, AND mask."""
    dib = struct.pack('<IiiHHIIiiII', 40, 2, 4, 1, 32, 0, 0, 0, 0, 0, 0) + bytes([10, 20, 30, 255, 40, 50, 60, 255, 70, 80, 90, 255, 1, 2, 3, 0]) + b'\0' * 8
    return struct.pack('<HHH', 0, 1, 1) + struct.pack('<BBBBHHII', 2, 2, 0, 0, 1, 32, len(dib), 22) + dib


def bitmap_bytes():
    pixels = bytes([255, 0, 0, 0, 255, 0] + [0, 0] + [0, 0, 255, 17, 34, 51] + [0, 0])
    return b'BM' + struct.pack('<IHHI', 14 + 40 + len(pixels), 0, 0, 54) + struct.pack('<IiiHHIIiiII', 40, 2, 2, 1, 24, 0, len(pixels), 0, 0, 0, 0) + pixels


MANIFEST = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<assembly xmlns="urn:schemas-microsoft-com:asm.v1" manifestVersion="1.0">\n'
            '  <assemblyIdentity version="3.4.5.6" processorArchitecture="*" name="Oracle.Probe" type="win32"/>\n'
            '  <description>Resource oracle \u00f1</description>\n'
            '</assembly>\n')


def version_block(translation, language_name, extra=''):
    return f'''  BLOCK "{translation}"
  BEGIN
   VALUE "CompanyName", "Oracle Works {language_name}"
   VALUE "FileDescription", "Resource oracle {language_name}"
   VALUE "FileVersion", "3.4.5.6"
   VALUE "InternalName", "oracle"
   VALUE "LegalCopyright", "(c) \u00dcn\u00ef\u00e7\u00f6de {language_name}"
   VALUE "OriginalFilename", "oracle.exe"
   VALUE "ProductName", "Oracle"
   VALUE "ProductVersion", "7.8.9.10"{extra}
  END
'''


RC = ('// oracle script\n#pragma code_page(65001)\n'
      'LANGUAGE 9, 1\n'
      '1 VERSIONINFO\nFILEVERSION 3,4,5,6\nPRODUCTVERSION 7,8,9,10\nFILEFLAGSMASK 0x3fL\nFILEFLAGS 0x1L\nFILEOS 0x40004L\nFILETYPE 0x1L\nFILESUBTYPE 0\nBEGIN\n'
      ' BLOCK "StringFileInfo"\n BEGIN\n' + version_block('040904B0', 'EN', '\n   VALUE "Comments", "first"') + version_block('0C0A04B0', 'ES') +
      ' END\n BLOCK "VarFileInfo"\n BEGIN\n  VALUE "Translation", 0x409, 1200, 0xC0A, 1200\n END\nEND\n'
      'STRINGTABLE\nBEGIN\n 16 "Sixteen"\n 17 "Seventeen \u00f1 \u20ac"\n 18 ""\n 19 "Line\\nbreak"\n 300 "Block 18 entry"\nEND\n'
      '2 DIALOG 0, 0, 120, 60\nCAPTION "Oracle dialog"\nFONT 8, "MS Shell Dlg"\nBEGIN\n DEFPUSHBUTTON "OK", 1, 10, 10, 40, 14\nEND\n'
      '3 MENU\nBEGIN\n POPUP "&File"\n BEGIN\n  MENUITEM "E&xit", 100\n END\nEND\n'
      '1 ICON "oracle.ico"\n'
      '2 BITMAP "oracle.bmp"\n'
      '1 24 "oracle.manifest"\n'
      'LANGUAGE 10, 3\n'
      'STRINGTABLE\nBEGIN\n 16 "Diecis\u00e9is"\n 17 "Diecisiete"\nEND\n'
      '4 MENU\nBEGIN\n POPUP "&Archivo"\n BEGIN\n  MENUITEM "S&alir", 101\n END\nEND\n'
      'LANGUAGE 0, 0\n'
      '5 RCDATA "blob.bin"\n'
      '6 RCDATA\nBEGIN\n 0x1234, "ab", 7L\nEND\n'
      '7 256 "blob.bin"\n'
      f'{OVERLAY_NAME} MYBLOB "blob.bin"\n'
      'ODD_NAME 300 "blob.bin"\n'
      'ÑANDÚ_Ö MYBLOB "blob.bin"\n')


def source_directory(root):
    root.mkdir(parents=True, exist_ok=True)
    (root / 'oracle.rc').write_text(RC, encoding='utf8')
    (root / 'oracle.ico').write_bytes(icon_bytes())
    (root / 'oracle.bmp').write_bytes(bitmap_bytes())
    (root / 'oracle.manifest').write_bytes(MANIFEST.encode('utf8'))  # bytes, so Windows does not turn \n into \r\n
    (root / 'blob.bin').write_bytes(BLOB)
    (root / 'main.c').write_text('int main(void) { return 0; }\n', encoding='utf8')
    (root / 'dll.c').write_text('int __stdcall DllMain(void *h, unsigned long r, void *x) { return 1; }\n', encoding='utf8')
    return root


def zig_link(root, name, target, shared=False, resources=True):
    env = dict(os.environ, ZIG_GLOBAL_CACHE_DIR=str(root / 'zig-global'), ZIG_LOCAL_CACHE_DIR=str(root / 'zig-local'))
    output = root / name
    command = [ZIG, 'cc', '-target', target, '-O0', '-o', str(output)]
    command += ['-shared', 'dll.c'] if shared else ['main.c']
    command += ['oracle.rc'] if resources else []
    result = subprocess.run(command, cwd=root, env=env, capture_output=True, text=True)
    assert result.returncode == 0 and output.is_file(), result.stdout + result.stderr
    return output


CSC_SOURCE = ('using System.Reflection;\n[assembly: AssemblyTitle("Oracle csc")]\n[assembly: AssemblyCompany("Oracle Works")]\n'
              '[assembly: AssemblyVersion("1.2.3.4")]\n[assembly: AssemblyFileVersion("5.6.7.8")]\nclass P { static void Main() { } }\n')


def csc_build(root, name, win32res=None):
    if CSC is None:
        pytest.skip('Requires csc.exe (THESEUS_TEST_CSC)')
    (root / 'prog.cs').write_text(CSC_SOURCE, encoding='utf8')
    output = root / name
    command = [CSC, '/nologo', '/out:' + str(output), 'prog.cs'] + (['/win32res:' + win32res] if win32res else [])
    result = subprocess.run(command, cwd=root, capture_output=True, text=True)
    assert result.returncode == 0 and output.is_file(), result.stdout + result.stderr
    return output


def compile_resources(root):
    env = dict(os.environ, ZIG_GLOBAL_CACHE_DIR=str(root / 'zig-global'), ZIG_LOCAL_CACHE_DIR=str(root / 'zig-local'))
    result = subprocess.run([ZIG, 'rc', '/fo', 'oracle.res', 'oracle.rc'], cwd=root, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    return 'oracle.res'


BUILDERS = {
    'x64.exe': lambda root: zig_link(root, 'x64.exe', 'x86_64-windows-gnu'),
    'x86.exe': lambda root: zig_link(root, 'x86.exe', 'x86-windows-gnu'),
    'x64.dll': lambda root: zig_link(root, 'x64.dll', 'x86_64-windows-gnu', shared=True),
    'x86.dll': lambda root: zig_link(root, 'x86.dll', 'x86-windows-gnu', shared=True),
    'plain.exe': lambda root: zig_link(root, 'plain.exe', 'x86_64-windows-gnu', resources=False),
    'csc-default.exe': lambda root: csc_build(root, 'csc-default.exe'),
    'csc-resources.exe': lambda root: csc_build(root, 'csc-resources.exe', compile_resources(root)),
}
ZIG_IMAGES = ['x64.exe', 'x86.exe', 'x64.dll', 'x86.dll', 'csc-resources.exe']
ALL_IMAGES = ZIG_IMAGES + ['csc-default.exe']


@pytest.fixture(scope='session')
def workspace(tmp_path_factory):
    if ZIG is None:
        pytest.skip('Requires zig (THESEUS_TEST_ZIG or zig on PATH)')
    return source_directory(tmp_path_factory.mktemp('pe-resources'))


def image(workspace, name):
    if name.startswith('csc') and name != 'csc-default.exe' and ZIG is None:
        pytest.skip('Requires zig to compile the resource script')
    path = workspace / name
    return path if path.is_file() else BUILDERS[name](workspace)


# ---- oracle: pefile ---------------------------------------------------------------------------------------------------

def sha(data):
    return hashlib.sha256(data).hexdigest()


def oracle_identity(entry):
    # pefile stores a resource name as UTF-8 bytes converted from the on-disk UTF-16 string.
    return ('name', entry.name.decode('utf-8')) if entry.name is not None else ('id', entry.id)


def oracle(path):
    """Directory nodes (pre-order), leaves and header facts as pefile reads them."""
    pe = pefile.PE(str(path))
    # The byte-frequency note describes file contents (padding), not structure, so it is not a parse problem.
    assert [warning for warning in pe.get_warnings() if 'makes up' not in warning] == []
    data_directory = pe.OPTIONAL_HEADER.DATA_DIRECTORY[pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_RESOURCE']]
    base = pe.get_offset_from_rva(data_directory.VirtualAddress)
    directories, leaves = [], []

    def visit(directory, depth):
        s = directory.struct
        directories.append({'offset': s.get_file_offset(), 'bytes': 16 + 8 * (s.NumberOfNamedEntries + s.NumberOfIdEntries), 'characteristics': s.Characteristics,
                            'timestamp': s.TimeDateStamp, 'major_version': s.MajorVersion, 'minor_version': s.MinorVersion,
                            'named_entries': s.NumberOfNamedEntries, 'id_entries': s.NumberOfIdEntries})
        for entry in directory.entries:
            if depth < 2:
                visit(entry.directory, depth + 1)

    visit(pe.DIRECTORY_ENTRY_RESOURCE, 0)
    for kind in pe.DIRECTORY_ENTRY_RESOURCE.entries:
        for name in kind.directory.entries:
            for language in name.directory.entries:
                s = language.data.struct
                strings = []
                for level, entry in (('type', kind), ('name', name)):
                    if entry.name is not None:
                        encoded = entry.name.decode('utf-8').encode('utf-16-le')
                        strings.append((level, base + (entry.struct.Name & 0x7fffffff), 2 + len(encoded), encoded.hex()))
                payload = pe.get_data(s.OffsetToData, s.Size)
                leaves.append({'type': oracle_identity(kind), 'name': oracle_identity(name), 'language': ('id', language.id), 'code_page': s.CodePage,
                               'reserved': s.Reserved, 'rva': s.OffsetToData, 'offset': pe.get_offset_from_rva(s.OffsetToData), 'size': s.Size,
                               'sha256': sha(payload), 'entries': [(e.struct.get_file_offset(), 8) for e in (kind, name, language)],
                               'data_entry': (s.get_file_offset(), 16), 'strings': strings, 'lang': language.data.lang, 'sublang': language.data.sublang})
    header = {'format': 'pe32-plus' if pe.PE_TYPE == pefile.OPTIONAL_HEADER_MAGIC_PE_PLUS else 'pe32', 'machine': pe.FILE_HEADER.Machine,
              'directory': {'rva': data_directory.VirtualAddress, 'location': {'offset': base, 'bytes': data_directory.Size},
                            'data_directory_location': {'offset': data_directory.get_file_offset(), 'bytes': 8}}}
    return pe, header, directories, leaves


def product_identity(value):
    return ('name', value['name']) if value['kind'] == 'name' else ('id', value['id'])


def product_leaf(row):
    payload = row['payload']
    strings = [(level, row[level]['location']['offset'], row[level]['location']['bytes'], row[level]['utf16le_hex']) for level in ('type', 'name') if row[level]['kind'] == 'name']
    for level in ('type', 'name'):  # the stored hex must be the stored name
        if row[level]['kind'] == 'name':
            assert bytes.fromhex(row[level]['utf16le_hex']).decode('utf-16-le') == row[level]['name']
    return {'type': product_identity(row['type']), 'name': product_identity(row['name']), 'language': product_identity(row['language']),
            'code_page': row['code_page'], 'reserved': row['reserved'], 'rva': payload['rva'], 'offset': payload['location']['offset'],
            'size': payload['location']['bytes'], 'sha256': payload['sha256'],
            'entries': [(at['offset'], at['bytes']) for at in row['entry_locations']],
            'data_entry': (row['data_entry_location']['offset'], row['data_entry_location']['bytes']), 'strings': strings}


def strip(leaves):
    return [{key: value for key, value in leaf.items() if key not in ('lang', 'sublang')} for leaf in leaves]


def payload_of(content, row):
    at = row['payload']['location']
    data = content[at['offset']:at['offset'] + at['bytes']]
    assert len(data) == at['bytes'] and sha(data) == row['payload']['sha256']
    return data


def fresh(tmp_path, name):
    (tmp_path / name).mkdir()
    return tmp_path / name


def find(result, kind, name=None, language=None):
    rows = [row for row in result['resources'] if product_identity(row['type']) == kind and (name is None or product_identity(row['name']) == name)
            and (language is None or product_identity(row['language']) == language)]
    assert rows, (kind, name, language)
    return rows


# ---- decoders for the three payload families the reader leaves opaque ----------------------------------------------------

def align(value):
    return (value + 3) & ~3


def version_node(data, at):
    length, value_length, kind = struct.unpack_from('<HHH', data, at)
    end, cursor = at + length, at + 6
    while data[cursor:cursor + 2] != b'\0\0':
        cursor += 2
    key = data[at + 6:cursor].decode('utf-16-le')
    cursor = align(cursor + 2)
    size = value_length * 2 if kind == 1 else value_length
    value = data[cursor:cursor + size]
    cursor, children = align(cursor + size), []
    while cursor < end:
        child, child_end = version_node(data, cursor)
        children.append(child)
        cursor = align(child_end)
    return {'key': key, 'type': kind, 'value': value, 'children': children}, end


def decode_version(data):
    root, _ = version_node(data, 0)
    fixed = dict(zip(['Signature', 'StrucVersion', 'FileVersionMS', 'FileVersionLS', 'ProductVersionMS', 'ProductVersionLS', 'FileFlagsMask', 'FileFlags',
                      'FileOS', 'FileType', 'FileSubtype', 'FileDateMS', 'FileDateLS'], struct.unpack('<13I', root['value'])))
    strings = {}
    translations = []
    for child in root['children']:
        if child['key'] == 'StringFileInfo':
            for table in child['children']:
                strings[table['key'].lower()] = {entry['key']: entry['value'].decode('utf-16-le').rstrip('\0') for entry in table['children']}
        if child['key'] == 'VarFileInfo':
            raw = child['children'][0]['value']
            translations = [struct.unpack_from('<HH', raw, at) for at in range(0, len(raw), 4)]
    return fixed, strings, translations


def text(value):
    # Representation only: this pefile build returns str for some fields and bytes for others.
    return value.decode() if isinstance(value, bytes) else value


def oracle_version(pe):
    fixed = pe.VS_FIXEDFILEINFO[0]
    names = ['Signature', 'StrucVersion', 'FileVersionMS', 'FileVersionLS', 'ProductVersionMS', 'ProductVersionLS', 'FileFlagsMask', 'FileFlags',
             'FileOS', 'FileType', 'FileSubtype', 'FileDateMS', 'FileDateLS']
    strings, translations = {}, []
    for info in pe.FileInfo[0]:
        if info.Key == b'StringFileInfo':
            for table in info.StringTable:
                # pefile keeps bytes (UTF-8 re-encoded); the node keys are compared as text and LangID lower-cased like the on-disk hex digits
                strings[text(table.LangID).lower()] = {text(k): text(v) for k, v in table.entries.items()}
        if info.Key == b'VarFileInfo':
            words = [int(word, 16) for word in text(info.Var[0].entry[b'Translation']).split()]
            translations = list(zip(words[::2], words[1::2]))
    return {name: getattr(fixed, name) for name in names}, strings, translations


def decode_string_block(block, data):
    entries, at = {}, 0
    for index in range(16):
        (count,) = struct.unpack_from('<H', data, at)
        if count:
            entries[(block - 1) * 16 + index] = data[at + 2:at + 2 + 2 * count].decode('utf-16-le')
        at += 2 + 2 * count
    assert at == len(data)
    return entries


# ---- tests ---------------------------------------------------------------------------------------------------------------

def compare_inventory(tmp_path, content, path):
    result = inspect(tmp_path, 'pe.resources', content)
    pe, header, directories, leaves = oracle(path)
    assert {key: result[key] for key in ('format', 'machine')} == {key: header[key] for key in ('format', 'machine')}
    assert result['directory'] == header['directory']
    fields = ['characteristics', 'timestamp', 'major_version', 'minor_version', 'named_entries', 'id_entries']
    assert [{'offset': row['location']['offset'], 'bytes': row['location']['bytes']} | {key: row[key] for key in fields}
            for row in result['directories']] == [{'offset': row['offset'], 'bytes': row['bytes']} | {key: row[key] for key in fields} for row in directories]
    assert [product_leaf(row) for row in result['resources']] == strip(leaves)
    assert [row['index'] for row in result['resources']] == list(range(len(leaves)))
    assert result['coverage'] == {'status': 'complete', 'examined_entries': sum(row['named_entries'] + row['id_entries'] for row in directories),
                                  'resources': len(leaves)}
    for row in result['resources']:
        payload_of(content, row)  # the reported file range holds exactly the hashed bytes
    return result, pe, leaves


@pytest.mark.parametrize('name', ALL_IMAGES)
def test_resource_inventory_matches_pefile(tmp_path, workspace, name):
    path = image(workspace, name)
    result, _, leaves = compare_inventory(tmp_path, path.read_bytes(), path)
    assert leaves, name
    # The reader keeps the full language id; pefile splits the same id into primary language and sublanguage.
    assert all((leaf['language'][1] & 0x3ff, leaf['language'][1] >> 10) == (leaf['lang'], leaf['sublang']) for leaf in leaves)


EXPECTED_IDENTITIES = sorted([
    (('name', 'MYBLOB'), ('name', 'NAMED_BLOB'), 0), (('name', 'MYBLOB'), ('name', 'ÑANDÚ_Ö'), 0), (('id', 2), ('id', 2), 1033), (('id', 3), ('id', 1), 1033),
    (('id', 4), ('id', 3), 1033), (('id', 4), ('id', 4), 3082), (('id', 5), ('id', 2), 1033), (('id', 6), ('id', 2), 1033), (('id', 6), ('id', 2), 3082),
    (('id', 6), ('id', 19), 1033), (('id', 10), ('id', 5), 0), (('id', 10), ('id', 6), 0), (('id', 14), ('id', 1), 1033), (('id', 16), ('id', 1), 1033),
    (('id', 24), ('id', 1), 1033), (('id', 256), ('id', 7), 0), (('id', 300), ('name', 'ODD_NAME'), 0)], key=repr)


@pytest.mark.parametrize('name', ZIG_IMAGES)
def test_identities_equal_the_resource_script(tmp_path, workspace, name):
    path = image(workspace, name)
    result = inspect(tmp_path, 'pe.resources', path.read_bytes())
    observed = sorted([(product_identity(row['type']), product_identity(row['name']), row['language']['id']) for row in result['resources']], key=repr)
    assert observed == EXPECTED_IDENTITIES
    assert all(row['language']['kind'] == 'id' for row in result['resources'])


@pytest.mark.parametrize('name', ZIG_IMAGES)
def test_payload_bytes_equal_the_sources(tmp_path, workspace, name):
    path = image(workspace, name)
    content = path.read_bytes()
    result = inspect(tmp_path, 'pe.resources', content)
    expected = {(('name', 'MYBLOB'), ('name', 'NAMED_BLOB')): BLOB, (('name', 'MYBLOB'), ('name', 'ÑANDÚ_Ö')): BLOB, (('id', 10), ('id', 5)): BLOB,
                (('id', 256), ('id', 7)): BLOB, (('id', 300), ('name', 'ODD_NAME')): BLOB, (('id', 10), ('id', 6)): b'\x34\x12ab\x07\0\0\0',
                (('id', 24), ('id', 1)): MANIFEST.encode(), (('id', 3), ('id', 1)): icon_bytes()[22:], (('id', 2), ('id', 2)): bitmap_bytes()[14:],
                (('id', 14), ('id', 1)): struct.pack('<HHH', 0, 1, 1) + struct.pack('<BBBBHHIH', 2, 2, 0, 0, 1, 32, 64, 1)}
    for row in result['resources']:
        key = (product_identity(row['type']), product_identity(row['name']))
        if key in expected:
            assert payload_of(content, row) == expected.pop(key), key
            assert row['payload']['sha256'] == sha(payload_of(content, row))
    assert expected == {}
    dialog = payload_of(content, find(result, ('id', 5))[0])
    assert 'Oracle dialog'.encode('utf-16-le') in dialog and 'MS Shell Dlg'.encode('utf-16-le') in dialog
    menus = {row['language']['id']: payload_of(content, row) for row in find(result, ('id', 4))}
    assert 'E&xit'.encode('utf-16-le') in menus[1033] and 'S&alir'.encode('utf-16-le') in menus[3082]


def test_zig_exe_header_and_architectures(tmp_path, workspace):
    seen = {}
    for name in ['x64.exe', 'x86.exe', 'x64.dll', 'x86.dll']:
        result = inspect(fresh(tmp_path, name), 'pe.resources', image(workspace, name).read_bytes())
        seen[name] = (result['format'], result['machine'])
    assert seen == {'x64.exe': ('pe32-plus', 0x8664), 'x86.exe': ('pe32', 0x14c), 'x64.dll': ('pe32-plus', 0x8664), 'x86.dll': ('pe32', 0x14c)}


@pytest.mark.parametrize('name', ZIG_IMAGES + ['csc-default.exe'])
def test_version_information_decodes_from_the_reported_range(tmp_path, workspace, name):
    path = image(workspace, name)
    content = path.read_bytes()
    result = inspect(tmp_path, 'pe.resources', content)
    pe, _, _, _ = oracle(path)
    rows = find(result, ('id', 16))
    assert len(rows) == 1 and product_identity(rows[0]['name']) == ('id', 1)
    fixed, strings, translations = decode_version(payload_of(content, rows[0]))
    expected_fixed, expected_strings, expected_pairs = oracle_version(pe)
    assert (fixed, strings) == (expected_fixed, expected_strings)
    # pefile keeps only the last language/codepage pair of a Translation value, so the full list is checked on the bytes it reads.
    assert expected_pairs == translations[-1:]
    leaf = next(row for row in oracle(path)[3] if row['type'] == ('id', 16))
    assert decode_version(pe.get_data(leaf['rva'], leaf['size']))[2] == translations
    assert fixed['Signature'] == 0xfeef04bd
    if name == 'csc-default.exe':
        assert any(table['FileVersion'] == '5.6.7.8' and table['CompanyName'] == 'Oracle Works' for table in strings.values())
        return
    expected = {'040904b0': {'CompanyName': 'Oracle Works EN', 'FileDescription': 'Resource oracle EN', 'FileVersion': '3.4.5.6', 'InternalName': 'oracle',
                             'LegalCopyright': '(c) Ünïçöde EN', 'OriginalFilename': 'oracle.exe', 'ProductName': 'Oracle',
                             'ProductVersion': '7.8.9.10', 'Comments': 'first'},
                '0c0a04b0': {'CompanyName': 'Oracle Works ES', 'FileDescription': 'Resource oracle ES', 'FileVersion': '3.4.5.6', 'InternalName': 'oracle',
                             'LegalCopyright': '(c) Ünïçöde ES', 'OriginalFilename': 'oracle.exe', 'ProductName': 'Oracle',
                             'ProductVersion': '7.8.9.10'}}
    assert strings == expected and translations == [(0x409, 1200), (0xc0a, 1200)]
    assert (fixed['FileVersionMS'], fixed['FileVersionLS'], fixed['ProductVersionMS'], fixed['ProductVersionLS']) == (0x30004, 0x50006, 0x70008, 0x9000a)
    assert (fixed['FileFlagsMask'], fixed['FileFlags'], fixed['FileOS'], fixed['FileType'], fixed['FileSubtype']) == (0x3f, 1, 0x40004, 1, 0)
    assert rows[0]['language']['id'] == 1033


@pytest.mark.parametrize('name', ZIG_IMAGES)
def test_string_tables_decode_per_language_like_the_script(tmp_path, workspace, name):
    path = image(workspace, name)
    content = path.read_bytes()
    result = inspect(tmp_path, 'pe.resources', content)
    pe, _, _, leaves = oracle(path)
    observed, from_oracle = {}, {}
    for row in find(result, ('id', 6)):
        observed.setdefault(row['language']['id'], {}).update(decode_string_block(row['name']['id'], payload_of(content, row)))
    for leaf in leaves:
        if leaf['type'] == ('id', 6):
            from_oracle.setdefault(leaf['language'][1], {}).update(decode_string_block(leaf['name'][1], pe.get_data(leaf['rva'], leaf['size'])))
    assert observed == from_oracle == {1033: {16: 'Sixteen', 17: 'Seventeen ñ €', 19: 'Line\nbreak', 300: 'Block 18 entry'},
                                       3082: {16: 'Dieciséis', 17: 'Diecisiete'}}


@pytest.mark.parametrize('name', ZIG_IMAGES + ['csc-default.exe'])
def test_manifest_text_matches_pefile(tmp_path, workspace, name):
    path = image(workspace, name)
    content = path.read_bytes()
    result = inspect(tmp_path, 'pe.resources', content)
    pe, _, _, leaves = oracle(path)
    manifest = next(leaf for leaf in leaves if leaf['type'] == ('id', 24))
    rows = find(result, ('id', 24))
    assert [(product_identity(row['name']), row['language']['id']) for row in rows] == [(manifest['name'], manifest['language'][1])]
    text = payload_of(content, rows[0]).decode('utf-8')
    assert text == pe.get_data(manifest['rva'], manifest['size']).decode('utf-8')
    assert ('requestedExecutionLevel' in text) if name == 'csc-default.exe' else (text == MANIFEST)


def oracle_icon_groups(pe, leaves):
    groups = []
    for index, leaf in enumerate(leaves):
        if leaf['type'] != ('id', 14):
            continue
        data = pe.get_data(leaf['rva'], leaf['size'])
        images = []
        for at in range(struct.unpack_from('<H', data, 4)[0]):
            width, height, colors, reserved, planes, bits, declared, identifier = struct.unpack_from('<BBBBHHIH', data, 6 + 14 * at)
            candidates = [i for i, other in enumerate(leaves) if other['type'] == ('id', 3) and other['name'] == ('id', identifier)]
            same = [i for i in candidates if leaves[i]['language'] == leaf['language']]
            images.append({'location': {'offset': leaf['offset'] + 6 + 14 * at, 'bytes': 14}, 'width': width, 'height': height, 'color_count': colors,
                           'reserved': reserved, 'planes': planes, 'bit_count': bits, 'declared_bytes': declared, 'resource_id': identifier,
                           'candidate_resource_indices': candidates, 'same_language_resource_index': same[0] if same else None,
                           'size_matches': leaves[same[0]]['size'] == declared if same else None})  # nothing to compare when no icon resource resolves
        groups.append({'resource_index': index, 'images': images})
    return groups


@pytest.mark.parametrize('name', ZIG_IMAGES)
def test_icon_groups_follow_the_resource_table(tmp_path, workspace, name):
    path = image(workspace, name)
    result = inspect(tmp_path, 'pe.resources', path.read_bytes())
    pe, _, _, leaves = oracle(path)
    assert result['icon_groups'] == oracle_icon_groups(pe, leaves)
    assert result['icon_groups'][0]['images'][0]['candidate_resource_indices'] and result['icon_groups'][0]['images'][0]['size_matches']


@pytest.mark.parametrize('patch', ['dangling-id', 'declared-size'])
def test_icon_group_relationships_after_patching_the_entry(tmp_path, workspace, patch):
    path = image(workspace, 'x64.exe')
    pe, _, _, leaves = oracle(path)
    group = next(leaf for leaf in leaves if leaf['type'] == ('id', 14))
    content = bytearray(path.read_bytes())
    entry = group['offset'] + 6
    if patch == 'dangling-id':
        struct.pack_into('<H', content, entry + 12, 99)
    else:
        struct.pack_into('<I', content, entry + 8, 63)
    patched = tmp_path / 'patched.exe'
    patched.write_bytes(content)
    result = inspect(fresh(tmp_path, 'run'), 'pe.resources', bytes(content))
    pe, _, _, leaves = oracle(patched)
    assert result['icon_groups'] == oracle_icon_groups(pe, leaves)
    image_row = result['icon_groups'][0]['images'][0]
    assert image_row['size_matches'] is (None if patch == 'dangling-id' else False)
    assert (image_row['candidate_resource_indices'] == []) == (patch == 'dangling-id')


def test_changed_payload_bytes_change_only_that_hash(tmp_path, workspace):
    path = image(workspace, 'x64.exe')
    pe, _, _, leaves = oracle(path)
    blob = next(leaf for leaf in leaves if leaf['type'] == ('id', 256))
    content = bytearray(path.read_bytes())
    content[blob['offset'] + 100] ^= 0xff
    mutated = tmp_path / 'mutated.exe'
    mutated.write_bytes(content)
    _, _, new_leaves = compare_inventory(fresh(tmp_path, 'run'), bytes(content), mutated)
    changed = [(old['type'], old['name']) for old, new in zip(leaves, new_leaves) if old['sha256'] != new['sha256']]
    covering = [(old['type'], old['name']) for old in leaves if old['offset'] <= blob['offset'] + 100 < old['offset'] + old['size']]
    assert changed == covering and (('id', 256), ('id', 7)) in changed


def test_pe_without_resources_reports_none_and_invents_nothing(tmp_path, workspace):
    path = image(workspace, 'plain.exe')
    result = inspect(tmp_path, 'pe.resources', path.read_bytes())
    pe = pefile.PE(str(path))
    assert not hasattr(pe, 'DIRECTORY_ENTRY_RESOURCE')
    assert pe.OPTIONAL_HEADER.DATA_DIRECTORY[2].VirtualAddress == 0 and pe.OPTIONAL_HEADER.DATA_DIRECTORY[2].Size == 0
    assert result['directory'] is None and result['resources'] == [] and result['directories'] == [] and result['icon_groups'] == []
    assert result['coverage'] == {'status': 'complete', 'examined_entries': 0, 'resources': 0}


def outcome(tmp_path, content):
    """('finished', result) or ('failed', job); the second call proves the failure is a real failed job."""
    for name in ('first', 'second'):
        (tmp_path / name).mkdir()
    try:
        return 'finished', inspect(tmp_path / 'first', 'pe.resources', content)
    except AssertionError:
        return 'failed', inspect(tmp_path / 'second', 'pe.resources', content, expected_state='failed')


def corrupt(content, case, pe):
    off = pe.get_offset_from_rva(pe.OPTIONAL_HEADER.DATA_DIRECTORY[2].VirtualAddress)
    data = bytearray(content)
    first = pe.DIRECTORY_ENTRY_RESOURCE.entries[0].directory.entries[0].directory.entries[0].data.struct.get_file_offset()
    second = pe.DIRECTORY_ENTRY_RESOURCE.entries[1].directory.entries[0].directory.entries[0].data.struct
    if case == 'truncated-in-directory':
        return bytes(data[:off + 200])
    if case == 'truncated-in-payload':
        return bytes(data[:len(data) - 3000])
    if case == 'subdirectory-outside-section':
        struct.pack_into('<I', data, off + 16 + 4, 0x80000000 | 0x7fff0000)
    elif case == 'directory-cycle':
        struct.pack_into('<I', data, off + 16 + 4, 0x80000000)
    elif case == 'payload-size-huge':
        struct.pack_into('<I', data, first + 4, 0x7fffffff)
    elif case == 'payload-rva-outside-image':
        struct.pack_into('<I', data, first, 0x7fffffff)
    elif case == 'resource-directory-rva-outside-image':
        struct.pack_into('<I', data, pe.OPTIONAL_HEADER.DATA_DIRECTORY[2].get_file_offset(), 0x7ffffff0)
    elif case == 'entry-count-huge':
        struct.pack_into('<H', data, off + 14, 5000)
    elif case == 'overlapping-payloads':
        struct.pack_into('<I', data, second.get_file_offset(), pe.DIRECTORY_ENTRY_RESOURCE.entries[0].directory.entries[0].directory.entries[0].data.struct.OffsetToData + 10)
        struct.pack_into('<I', data, second.get_file_offset() + 4, 64)
    return bytes(data)


CORRUPTIONS = ['truncated-in-directory', 'truncated-in-payload', 'subdirectory-outside-section', 'directory-cycle', 'payload-size-huge',
               'payload-rva-outside-image', 'resource-directory-rva-outside-image', 'entry-count-huge', 'overlapping-payloads']


@pytest.mark.parametrize('case', CORRUPTIONS)
def test_corrupt_resource_directory_fails_or_reports_gaps(tmp_path, workspace, case):
    path = image(workspace, 'x64.exe')
    pe, _, _, leaves = oracle(path)
    content = corrupt(path.read_bytes(), case, pe)
    assert content != path.read_bytes()
    state, observed = outcome(tmp_path, content)
    if state == 'failed':
        assert 'ArtifactReaderFailure' in observed['result']['execution']['stderr'] and observed['result']['execution']['exit_code'] != 0
        return
    # A finished job may only show rows that exist in the intact file and must say that the walk was incomplete.
    assert observed['coverage']['status'] != 'complete', observed['coverage']
    intact = strip(leaves)
    assert all(product_leaf(row) in intact for row in observed['resources'])
