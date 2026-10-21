"""Property lists and NSKeyedArchiver graphs against values built here and Python's plistlib.

Every document is built in the test with plistlib (XML and binary, plus hand-written bytes where plistlib cannot
write the construct). apple.plist is compared value by value with what was constructed and with plistlib's own
reader. apple.keyed_archive is compared with a graph (objects, classes, roots, UID edges) derived from the
construction by a walker that shares no code with the product reader.
"""
import base64
import datetime
import math
from pathlib import Path
import plistlib
import struct

import pytest

from test_native_formats import inspect

U = plistlib.UID
B, X = plistlib.FMT_BINARY, plistlib.FMT_XML
FORMATS = [pytest.param(X, id='xml'), pytest.param(B, id='binary')]
SAFE = 2**53 - 1


class Runner:
    """inspect() needs an existing, unused directory for every call."""

    def __init__(self, root):
        self.root, self.count = Path(root), 0

    def _dir(self):
        self.count += 1
        path = self.root / ('run%03d' % self.count)
        path.mkdir()
        return path

    def ok(self, operation, data, parameters=None):
        return inspect(self._dir(), operation, data, parameters)

    def fails(self, operation, data, parameters=None, mentions=None):
        job = inspect(self._dir(), operation, data, parameters, expected_state='failed')
        execution = job['result']['execution']
        assert execution['exit_code'] != 0 and not job['result']['cases'], job
        if mentions:
            assert mentions in execution['stderr'], execution['stderr']
        return job


@pytest.fixture
def run(tmp_path):
    return Runner(tmp_path)


def same(a, b, ordered=True, strict=True):
    """Deep equality that keeps bool apart from numbers; strict also keeps int apart from float."""
    if isinstance(a, bool) or isinstance(b, bool):
        return type(a) is type(b) and a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return a == b and (not strict or type(a) is type(b))
    if isinstance(a, dict) and isinstance(b, dict):
        if (list(a) != list(b)) if ordered else (set(a) != set(b)):
            return False
        return all(same(a[key], b[key], ordered, strict) for key in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(same(x, y, ordered, strict) for x, y in zip(a, b))
    return type(a) is type(b) and a == b


def assert_same(observed, expected, **options):
    assert same(observed, expected, **options), '\nobserved: %r\nexpected: %r' % (observed, expected)


def dumps(value, fmt):
    return plistlib.dumps(value, fmt=fmt, sort_keys=False)


def binary_trailer(data):
    return struct.unpack('>5xBBBQQQ', data[-32:])


# ---------------------------------------------------------------- apple.plist

def plist_expect(value):
    """Typed representation the apple.plist operation documents: explicit uid/blob/date/integer/real objects."""
    if isinstance(value, U):
        return {'type': 'uid', 'decimal': str(value.data)}
    if isinstance(value, datetime.datetime):
        return {'type': 'date', 'iso8601': value.isoformat(), 'timezone': 'UTC'}
    if isinstance(value, bytes):
        return {'type': 'blob', 'bytes': len(value), 'base64': base64.b64encode(value).decode()}
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return {'type': 'integer', 'decimal': str(value)} if abs(value) > SAFE else value
    if isinstance(value, float):
        if not math.isfinite(value):
            return {'type': 'real', 'representation': repr(value)}
        if value == 0 and math.copysign(1, value) < 0:
            return {'type': 'real', 'representation': '-0.0'}
        return value
    if isinstance(value, dict):
        return {key: plist_expect(item) for key, item in value.items()}
    if isinstance(value, list):
        return [plist_expect(item) for item in value]
    return value


def plist_entries(value):
    if isinstance(value, dict):
        return 'dictionary', [(str(key), item) for key, item in value.items()]
    if isinstance(value, list):
        return 'array', [(str(index), item) for index, item in enumerate(value)]
    return 'scalar', [('$', value)]


def check_plist(result, document, fmt):
    kind, pairs = plist_entries(document)
    assert result['format'] == ('binary' if fmt == B else 'xml')
    assert result['container_type'] == kind
    assert [entry['name'] for entry in result['entries']] == [name for name, _ in pairs]
    for entry, (name, item) in zip(result['entries'], pairs):
        assert_same(entry['value'], plist_expect(item))


def micro(fmt, moment):
    """The XML plist stores whole seconds, so the constructed date loses its microseconds there."""
    return moment if fmt == B else moment.replace(microsecond=0)


INT_LADDER = [0, 1, 127, 128, 255, 256, 65535, 65536, 2**24, 2**31 - 1, 2**31, 2**32 - 1, 2**32, 2**53 - 2, SAFE, SAFE + 1,
              SAFE + 2, 2**62, 2**63 - 1, 2**63, 2**64 - 1, -1, -2, -127, -128, -129, -32768, -32769, -2**31, -2**31 - 1,
              -SAFE, -SAFE - 1, -2**62, -2**63 + 1, -2**63]
# 0.0 and -0.0 are equal, so plistlib's binary writer stores one object for both: they get separate documents below
REALS = [-0.0, 1.5, -2.25, 3.0, 1e20, 1.7976931348623157e308, -1.7976931348623157e308, 5e-324, 1e-320,
         2.2250738585072014e-308, 0.1, math.inf, -math.inf, math.nan]
STRINGS = ['', 'a', 'plain ascii text', 'x' * 14, 'x' * 15, 'y' * 300, 'Año', 'naïve façade', 'カタカナ漢字', '😀 astral',
           'mixed Año ✓ 😀', 'quote " apos \' amp & lt < gt >', 'line\nbreak\ttab', 'ü' * 20, '漢' * 300, 'ÿĀ', 'end']


@pytest.mark.parametrize('fmt', FORMATS)
def test_every_scalar_type_matches_construction_and_plistlib(run, fmt):
    document = {
        'ints': INT_LADDER, 'reals': REALS, 'strings': STRINGS, 'true': True, 'false': False,
        'dates': [micro(fmt, datetime.datetime(2020, 1, 2, 3, 4, 5, 123456)), datetime.datetime(2001, 1, 1),
                  datetime.datetime(1970, 1, 1), datetime.datetime(1, 1, 1), datetime.datetime(9999, 12, 31, 23, 59, 59),
                  datetime.datetime(1969, 12, 31, 23, 59, 59)],
        'data': [b'', b'\x00', bytes(range(256)), b'\xff' * 14, b'\xff' * 15, b'ab' * 5000],
        'nested': {'list': [[], {}, [[[]]], [{'k': [1, {'deep': 'v'}]}]], 'empty': {}, '': 'empty key', 'Año': 'ñ'},
    }
    raw = dumps(document, fmt)
    parsed = plistlib.loads(raw)
    for name in ['ints', 'strings', 'true', 'false', 'dates', 'data', 'nested']:
        assert_same(parsed[name], document[name])  # plistlib itself kept every constructed value
    result = run.ok('apple.plist', raw)
    check_plist(result, document, fmt)
    check_plist(result, parsed, fmt)  # and agrees with plistlib's reader


@pytest.mark.parametrize('fmt', FORMATS)
def test_top_level_array_and_scalars(run, fmt):
    for document in [[1, 'two', [3.5], {'k': 4}], [], {}, 'só', 7, 2**64 - 1, 0.0, -0.0, math.inf, True, False,
                     b'\x00\x01', datetime.datetime(2022, 2, 2, 22, 22, 22)]:
        check_plist(run.ok('apple.plist', dumps(document, fmt)), plistlib.loads(dumps(document, fmt)), fmt)


def test_binary_top_level_uid(run):
    for number in [0, 255, 256, 65536, 2**32, 2**63, 2**64 - 1]:
        raw = dumps({'u': U(number), 'list': [U(number)]}, B)
        result = run.ok('apple.plist', raw)
        uid = {'type': 'uid', 'decimal': str(number)}
        assert_same([entry['value'] for entry in result['entries']], [uid, [uid]])


def test_xml_uid_is_typed_like_binary_uid(run):
    # Core Foundation writes a UID in XML as <dict><key>CF$UID</key><integer>n</integer></dict>.
    xml = (b'<?xml version="1.0" encoding="UTF-8"?><plist version="1.0"><dict><key>uid</key>'
           b'<dict><key>CF$UID</key><integer>5</integer></dict></dict></plist>')
    result = run.ok('apple.plist', xml)
    assert result['entries'][0]['value'] == {'type': 'uid', 'decimal': '5'}


def test_binary_object_reference_and_offset_widths(run):
    wide = {'key%04d' % index: index for index in range(300)}  # >255 objects: two-byte references
    wide['blob'] = b'\x01' * 70000  # offsets past 65535: four-byte offsets (plistlib writes 1, 2, 4 or 8)
    wide['tail'] = 'ünï'
    raw = dumps(wide, B)
    version, offset_size, ref_size, count, top, table = binary_trailer(raw)
    assert (offset_size, ref_size) == (4, 2) and count > 300
    check_plist(run.ok('apple.plist', raw), wide, B)
    many = list(range(1000, 71000))  # 70000 distinct objects: four-byte references
    raw = dumps(many, B)
    assert binary_trailer(raw)[2] == 4
    check_plist(run.ok('apple.plist', raw), many, B)
    check_plist(run.ok('apple.plist', dumps(wide, X)), wide, X)


def test_xml_forms_that_plistlib_does_not_write(run):
    xml = ('<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
           '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n<plist version="1.0"><!-- comment --><dict>'
           '<key>hex</key><integer>0xFFFFFFFFFFFFFFFF</integer><key>hexsmall</key><integer>0x1F</integer>'
           '<key>exp</key><real>1e3</real><key>t</key><true/><key>f</key><false/><key>empty</key><string/>'
           '<key>arr</key><array/><key>d</key><dict/><key>data</key><data>\n  AAEC\n  Aw==\n</data><key>nodata</key><data/>'
           '<key>ent</key><string>a &amp; b &lt;c&gt; &#233; &#x1F600; <![CDATA[<raw>&]]></string>'
           '<key>date</key><date>2020-01-02T03:04:05Z</date></dict></plist>').encode()
    parsed = plistlib.loads(xml)
    expected = {'hex': 2**64 - 1, 'hexsmall': 31, 'exp': 1000.0, 't': True, 'f': False, 'empty': '', 'arr': [], 'd': {},
                'data': b'\x00\x01\x02\x03', 'nodata': b'', 'ent': 'a & b <c> é 😀 <raw>&',
                'date': datetime.datetime(2020, 1, 2, 3, 4, 5)}
    assert_same(parsed, expected)
    check_plist(run.ok('apple.plist', xml), expected, X)


@pytest.mark.parametrize('encoding,bom', [('utf-8', b'\xef\xbb\xbf'), ('utf-16', b'')])
def test_xml_text_encodings(run, encoding, bom):
    text = ('<?xml version="1.0" encoding="%s"?><plist version="1.0"><dict><key>k</key><string>Año ✓</string></dict></plist>'
            % encoding.upper())
    raw = bom + text.encode(encoding)
    expected = {'k': 'Año ✓'}
    assert_same(plistlib.loads(raw), expected)
    check_plist(run.ok('apple.plist', raw), expected, X)


def test_binary_shared_containers_are_values_not_references(run):
    # object 0 is a dict whose two keys point at the same array object
    raw = raw_bplist([('d', [(1, 3), (2, 3)]), ('s', 'a'), ('s', 'b'), ('a', [4]), ('s', 'shared')])
    expected = {'a': ['shared'], 'b': ['shared']}
    assert_same(plistlib.loads(raw), expected)
    check_plist(run.ok('apple.plist', raw), expected, B)


def raw_bplist(objects, top=0, ref_size=1, offset_size=1):
    """Minimal binary plist writer for shapes plistlib refuses to write: cycles, shared containers, odd field widths."""
    refs = lambda numbers: b''.join(number.to_bytes(ref_size, 'big') for number in numbers)
    body, offsets = bytearray(b'bplist00'), []
    for kind, item in objects:
        offsets.append(len(body))
        if kind == 's':
            body += (bytes([0x50 | len(item)]) if len(item) < 15 else bytes([0x5F, 0x10, len(item)])) + item.encode('ascii')
        elif kind == 'i':
            body += b'\x10' + bytes([item])
        elif kind == 'r':
            body += b'\x23' + struct.pack('>d', item)
        elif kind == 'a':
            body += bytes([0xA0 | len(item)]) + refs(item)
        elif kind == 'd':
            body += bytes([0xD0 | len(item)]) + refs(key for key, _ in item) + refs(value for _, value in item)
    table = len(body)
    body += b''.join(offset.to_bytes(offset_size, 'big') for offset in offsets)
    return bytes(body) + struct.pack('>5xBBBQQQ', 0, offset_size, ref_size, len(objects), top, table)


@pytest.mark.parametrize('ref_size,offset_size', [(1, 3), (3, 1), (3, 3), (5, 5), (2, 6), (7, 7), (8, 8)])
def test_binary_plist_with_unusual_field_widths(run, ref_size, offset_size):
    # plistlib only writes 1, 2, 4 or 8 byte fields; the format allows any width up to eight bytes
    objects = [('d', [(1, 4), (2, 5), (3, 6)]), ('s', 'list'), ('s', 'text'), ('s', 'number'), ('a', [7, 8]), ('s', 'hello'),
               ('i', 200), ('s', 'x'), ('r', 2.5)]
    raw = raw_bplist(objects, ref_size=ref_size, offset_size=offset_size)
    expected = {'list': ['x', 2.5], 'text': 'hello', 'number': 200}
    assert_same(plistlib.loads(raw), expected)
    check_plist(run.ok('apple.plist', raw), expected, B)


GOOD_BINARY = dumps({'a': [1, 'two', 3.0], 'b': 'x'}, B)
SORT, OFFSET_SIZE, REF_SIZE, OBJECTS, TOP, TABLE = binary_trailer(GOOD_BINARY)


def with_trailer(**changes):
    fields = {'sort': SORT, 'offset': OFFSET_SIZE, 'ref': REF_SIZE, 'objects': OBJECTS, 'top': TOP, 'table': TABLE, **changes}
    return GOOD_BINARY[:-32] + struct.pack('>5xBBBQQQ', fields['sort'], fields['offset'], fields['ref'], fields['objects'],
                                           fields['top'], fields['table'])


def damaged_binaries():
    entry = bytearray(GOOD_BINARY)
    entry[TABLE + OFFSET_SIZE:TABLE + 2 * OFFSET_SIZE] = b'\xff' * OFFSET_SIZE  # second object offset beyond the file
    return {
        'offset-size-9': with_trailer(offset=9), 'offset-size-0': with_trailer(offset=0), 'ref-size-9': with_trailer(ref=9),
        'ref-size-0': with_trailer(ref=0), 'table-beyond-file': with_trailer(table=len(GOOD_BINARY) + 1000),
        'top-object-out-of-range': with_trailer(top=99), 'object-count-huge': with_trailer(objects=10**6),
        'object-offset-out-of-range': bytes(entry), 'truncated-trailer': GOOD_BINARY[:-10], 'header-only': b'bplist00',
        'wrong-magic': b'bplist99' + GOOD_BINARY[8:], 'zero-objects': with_trailer(objects=0),
        'array-contains-itself': raw_bplist([('a', [0])]),
        'dict-contains-itself': raw_bplist([('d', [(1, 0)]), ('s', 'k')]),
        'mutual-cycle': raw_bplist([('a', [1]), ('a', [0])]),
    }


@pytest.mark.parametrize('name', sorted(damaged_binaries()))
def test_damaged_binary_plists_fail_instead_of_returning_data(run, name):
    run.fails('apple.plist', damaged_binaries()[name], mentions='reference cycle' if 'cycle' in name else None)


@pytest.mark.parametrize('raw', [b'', b'   ', b'not a plist', b'<plist version="1.0"><dict><key>a</key></dict></plist>',
                                 b'<?xml version="1.0"?><plist version="1.0"><dict><key>a</key><integer>x</integer></dict></plist>',
                                 b'<?xml version="1.0"?><plist version="1.0"><dict>', b'\x00\x01\x02\xff'])
def test_damaged_xml_and_unknown_formats_fail(run, raw):
    run.fails('apple.plist', raw)


# ---------------------------------------------------------- apple.keyed_archive

class Archive:
    """NSKeyedArchiver-shaped plist under construction; add() returns the UID that points at the new object."""

    def __init__(self, top=None):
        self.objects, self.top = ['$null'], top

    def add(self, value=None):
        self.objects.append(value)
        return U(len(self.objects) - 1)

    def cls(self, name, *ancestors):
        return self.add({'$classname': name, '$classes': [name, *ancestors, 'NSObject']})

    def document(self):
        return {'$version': 100000, '$archiver': 'NSKeyedArchiver', '$top': self.top, '$objects': self.objects}


def encode_archive(document, fmt):
    """plistlib cannot write a UID in XML, so XML archives carry the CF$UID dictionary Core Foundation writes."""
    def walk(value):
        if isinstance(value, U):
            return {'CF$UID': value.data} if fmt == X else value
        if isinstance(value, dict):
            return {key: walk(item) for key, item in value.items()}
        if isinstance(value, list):
            return [walk(item) for item in value]
        return value
    return plistlib.dumps(walk(document), fmt=fmt, sort_keys=False)


def ms(moment):
    """The reader reports dates as JavaScript dates, i.e. rounded to the nearest millisecond."""
    total = (moment.microsecond + 500) // 1000
    moment = moment.replace(microsecond=0) + datetime.timedelta(milliseconds=total)
    return '%04d-%02d-%02dT%02d:%02d:%02d.%03dZ' % (moment.year, moment.month, moment.day, moment.hour, moment.minute,
                                                    moment.second, moment.microsecond // 1000)


def typed(value, fmt):
    if isinstance(value, U):
        return {('UID' if fmt == B else 'CF$UID'): value.data}
    if isinstance(value, bytes):
        return {'$plist_type': 'data', 'base64': base64.b64encode(value).decode()}
    if isinstance(value, datetime.datetime):
        return {'$plist_type': 'date', 'iso8601': ms(value)}
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return {'$plist_type': 'integer', 'decimal': str(value)} if abs(value) > SAFE else value
    if isinstance(value, float):
        if not math.isfinite(value):
            return {'$plist_type': 'real', 'value': None}
        if value == 0 and math.copysign(1, value) < 0:
            return {'$plist_type': 'real', 'value': '-0'}
        return value
    if isinstance(value, dict):
        return {key: typed(item, fmt) for key, item in value.items()}
    if isinstance(value, list):
        return [typed(item, fmt) for item in value]
    return value


def edges(value, path, source, objects, fmt, out):
    """Every UID under value in document order: array order, dictionary keys sorted."""
    if isinstance(value, U):
        target = value.data
        status = ('unresolved' if target >= len(objects) else 'nil' if target == 0 and objects[0] == '$null' else 'resolved')
        out.append({'source': source, 'path': path, 'target': target, 'status': status, 'raw': typed(value, fmt)})
    elif isinstance(value, list):
        for index, item in enumerate(value):
            edges(item, path + [index], source, objects, fmt, out)
    elif isinstance(value, dict):
        for key in sorted(value):
            edges(value[key], path + [key], source, objects, fmt, out)


def node(index, value, objects, fmt):
    descriptor_of = value.get('$class') if isinstance(value, dict) else None
    class_id = descriptor_of.data if isinstance(descriptor_of, U) else None
    descriptor = objects[class_id] if class_id is not None and class_id < len(objects) else None
    name = descriptor.get('$classname') if isinstance(descriptor, dict) else None
    name = name if isinstance(name, str) else None
    nil = index == 0 and value == '$null'
    if nil:
        kind = 'nil'
    elif isinstance(value, list):
        kind = 'array'
    elif not isinstance(value, dict):
        kind = 'scalar'
    elif isinstance(value.get('$classname'), str):
        kind = 'class-descriptor'
    elif '$class' in value:
        kind = 'archived-object'
    else:
        kind = 'dictionary'
    if nil:
        status = 'nil'
    elif isinstance(value, dict) and '$class' in value:
        status = 'unresolved-class' if name is None else 'unknown-class'
    else:
        status = 'observed'
    return {'id': index, 'kind': kind, 'class_id': class_id, 'class_name': name, 'status': status, 'value': typed(value, fmt)}


def expected_graph(archive, fmt, root=None, offset=0, limit=20000):
    objects, top = archive.objects, archive.top
    chosen = top if root is None else {root: top[root]}
    nodes = [node(index, value, objects, fmt) for index, value in enumerate(objects)]
    every = []
    for key in sorted(chosen):
        edges(chosen[key], [key], None, objects, fmt, every)
    for index, value in enumerate(objects):
        edges(value, [], index, objects, fmt, every)
    end = min(len(nodes), offset + limit)
    page = nodes[offset:end]
    ids = {entry['id'] for entry in page}
    return {'archive_format': 'binary-plist' if fmt == B else 'xml-plist',
            'roots': {key: typed(value, fmt) for key, value in chosen.items()}, 'objects': page,
            'references': [link for link in every if link['source'] is None or link['source'] in ids],
            'total_objects': len(nodes), 'total_references': len(every), 'offset': offset,
            'next_offset': end if end < len(nodes) else None, 'truncated': len(page) != len(nodes)}


def check_archive(result, archive, fmt, **selection):
    expected = expected_graph(archive, fmt, **selection)
    assert {key: result[key] for key in expected if key not in ('objects', 'references', 'roots')} == {
        key: value for key, value in expected.items() if key not in ('objects', 'references', 'roots')}
    # JSON has one number type: the reader reports a real such as 2.0 as 2, so numbers compare by value.
    assert_same(result['roots'], expected['roots'], ordered=False, strict=False)
    assert [entry['id'] for entry in result['objects']] == [entry['id'] for entry in expected['objects']]
    for seen, wanted in zip(result['objects'], expected['objects']):
        assert {key: seen[key] for key in seen if key != 'value'} == {key: wanted[key] for key in wanted if key != 'value'}, wanted
        assert_same(seen['value'], wanted['value'], ordered=False, strict=False)
    assert_same(result['references'], expected['references'], ordered=False, strict=False)
    return result


SAMPLE_NUMBERS = [0, 1, 255, 256, 65535, 65536, 2**32 - 1, 2**32, SAFE, SAFE + 1, 2**63 - 1, 2**64 - 1, -1, -128, -129, -2**31,
                  -SAFE, -SAFE - 1, -2**63, 1.5, -2.25, 1e300, 5e-324, 3.0, True, False, -0.0, math.inf, -math.inf, math.nan]


def sample(fmt):
    """A GaugeView graph: nested custom classes, NS collections, every NSNumber width, NSData, NSDate, sharing and cycles."""
    a = Archive()
    view_class, controller_class = a.cls('GaugeView', 'UIView'), a.cls('GaugeController')
    array_class, mutable_array = a.cls('NSArray'), a.cls('NSMutableArray', 'NSArray')
    dictionary_class, string_class = a.cls('NSDictionary'), a.cls('NSMutableString', 'NSString')
    data_class, date_class = a.cls('NSData'), a.cls('NSDate')
    title, shared = a.add('Año ✓ 😀'), a.add('shared string')
    view, controller, child, pair = a.add(), a.add(), a.add(), a.add()
    numbers = [a.add(number) for number in SAMPLE_NUMBERS]
    number_array = a.add({'$class': array_class, 'NS.objects': numbers})
    subviews = a.add({'$class': mutable_array, 'NS.objects': [child, shared, U(0)]})
    key_one, key_two = a.add('first key'), a.add('second key')
    mapping = a.add({'$class': dictionary_class, 'NS.keys': [key_one, key_two, shared],
                     'NS.objects': [view, number_array, controller]})
    text = a.add({'$class': string_class, 'NS.string': 'mutable text'})
    blob = a.add({'$class': data_class, 'NS.data': bytes(range(256))})
    stamp = a.add({'$class': date_class, 'NS.time': 612345678.123456})
    moment = a.add(micro(fmt, datetime.datetime(2020, 1, 2, 3, 4, 5, 123456)))
    late = a.add(datetime.datetime(9999, 12, 31, 23, 59, 59))
    raw_data = a.add(b'\x00\xffraw')
    a.objects[view.data] = {'$class': view_class, 'title': title, 'subviews': subviews, 'delegate': controller, 'tag': 7,
                            'scale': 1.5, 'hidden': True, 'nilref': U(0), 'map': mapping, 'text': text, 'blob': blob,
                            'stamp': stamp, 'when': moment, 'late': late, 'raw': raw_data, 'also_shared': shared}
    a.objects[controller.data] = {'$class': controller_class, 'view': view, 'self': controller, 'shared': shared}
    a.objects[child.data] = {'$class': view_class, 'parent': view, 'sibling': pair, 'title': shared}
    a.objects[pair.data] = {'$class': view_class, 'sibling': child, 'parent': view}
    a.top = {'root': view, 'controller': controller, 'nothing': U(0), 'literal': 42, 'again': view}
    return a


@pytest.mark.parametrize('fmt', FORMATS)
def test_object_graph_matches_construction(run, fmt):
    archive = sample(fmt)
    result = run.ok('apple.keyed_archive', encode_archive(archive.document(), fmt))
    check_archive(result, archive, fmt)
    notes = ' '.join(result['limitations'])
    assert '3 non-finite real' in notes and '1 negative-zero real' in notes, notes
    assert any(row['class_name'] == 'GaugeView' and row['kind'] == 'archived-object' for row in result['objects'])
    assert any(row['source'] == row['target'] for row in result['references'])  # the controller references itself


def test_binary_and_xml_report_the_same_graph(run):
    # Same construction in both encodings: only the UID spelling and the date precision of the plist differ.
    seen = []
    for fmt in (B, X):
        archive = sample(B)
        seen.append(run.ok('apple.keyed_archive', encode_archive(archive.document(), fmt)))
    binary, xml = seen
    assert [(row['id'], row['kind'], row['class_name'], row['status']) for row in binary['objects']] == \
           [(row['id'], row['kind'], row['class_name'], row['status']) for row in xml['objects']]
    assert [(row['source'], row['path'], row['target'], row['status']) for row in binary['references']] == \
           [(row['source'], row['path'], row['target'], row['status']) for row in xml['references']]


@pytest.mark.parametrize('fmt', FORMATS)
def test_roots_offset_and_limit(run, fmt):
    archive = sample(fmt)
    raw = encode_archive(archive.document(), fmt)
    total = len(archive.objects)
    selections = [dict(), dict(root='controller'), dict(root='literal', offset=3, limit=4), dict(offset=0, limit=1),
                  dict(offset=5, limit=10), dict(offset=total - 3, limit=50), dict(offset=total, limit=5),
                  dict(root='nothing', offset=total - 1, limit=1)]
    if fmt == X:
        selections = selections[1:3] + selections[5:7]
    for selection in selections:
        result = run.ok('apple.keyed_archive', raw, selection)
        check_archive(result, archive, fmt, **selection)


def test_pages_cover_the_table_exactly_once(run):
    archive = sample(B)
    raw = encode_archive(archive.document(), B)
    seen, offset = [], 0
    while offset is not None:
        result = run.ok('apple.keyed_archive', raw, {'offset': offset, 'limit': 17})
        seen += [row['id'] for row in result['objects']]
        offset = result['next_offset']
    assert seen == list(range(len(archive.objects)))


@pytest.mark.parametrize('root', ['missing', 'constructor', '__proto__', 'toString', 'ROOT', ''])
def test_unknown_root_is_rejected(run, root):
    run.fails('apple.keyed_archive', encode_archive(sample(B).document(), B), {'root': root})


@pytest.mark.parametrize('fmt', FORMATS)
def test_wide_archive_with_multibyte_references_and_offsets(run, fmt):
    a = Archive()
    klass = a.cls('Link')
    blob = a.add({'$class': a.cls('NSData'), 'NS.data': b'\x07' * 70000})
    chain = [a.add() for _ in range(700)]
    for index, slot in enumerate(chain):
        a.objects[slot.data] = {'$class': klass, 'index': index, 'next': chain[(index + 1) % len(chain)],
                                'blob': blob if index == 0 else U(0), 'name': 'node %d' % index}
    a.top = {'head': chain[0], 'tail': chain[-1]}
    raw = encode_archive(a.document(), fmt)
    if fmt == B:
        assert binary_trailer(raw)[1:3] == (4, 2)
    result = check_archive(run.ok('apple.keyed_archive', raw), a, fmt)
    assert result['total_objects'] == len(a.objects) and result['next_offset'] is None


@pytest.mark.parametrize('fmt', FORMATS)
def test_top_level_names_that_look_like_uid_markers(run, fmt):
    for top in [{'UID': None}, {'CF$UID': None}, {'UID': 3}, {'CF$UID': 3}]:
        a = Archive()
        target = a.add({'$class': a.cls('Thing'), 'v': 1})
        a.top = {key: (target if value is None else value) for key, value in top.items()}
        check_archive(run.ok('apple.keyed_archive', encode_archive(a.document(), fmt)), a, fmt)


@pytest.mark.parametrize('fmt', FORMATS)
def test_malformed_references_and_classes_are_reported_not_hidden(run, fmt):
    a = Archive()
    klass = a.cls('Known')
    a.add({'$class': klass, 'dangling': U(500), 'nil': U(0), 'list': [U(2), U(501), [U(0)]]})
    a.add({'$class': U(0)})  # class pointer at $null
    a.add({'$class': U(900)})  # class pointer past the table
    a.add({'$class': a.add('a string, not a class dictionary')})
    a.add({'$class': 'not a uid'})
    a.add({'$classname': 'NoClassesArray'})  # descriptor without $classes
    a.add({'$classes': ['OnlyClasses']})  # $classes without $classname: an ordinary dictionary
    a.add({'$class': a.add({'$classname': 17, '$classes': []})})  # $classname that is not a string
    a.top = {'root': U(2), 'bad': U(777)}
    check_archive(run.ok('apple.keyed_archive', encode_archive(a.document(), fmt)), a, fmt)


@pytest.mark.parametrize('fmt', FORMATS)
def test_archive_without_a_null_sentinel_keeps_index_zero_as_data(run, fmt):
    a = Archive()
    a.objects = ['first object', {'$class': U(2), 'back': U(0)}, {'$classname': 'K', '$classes': ['K']}]
    a.top = {'root': U(1)}
    result = check_archive(run.ok('apple.keyed_archive', encode_archive(a.document(), fmt)), a, fmt)
    assert result['objects'][0]['kind'] == 'scalar' and result['references'][-1]['status'] == 'resolved'


def test_oversized_and_negative_uid_markers_are_malformed(run):
    huge = Archive(top={'root': U(1)})
    huge.add({'x': U(2**64 - 1)})
    negative = ('<?xml version="1.0" encoding="UTF-8"?><plist version="1.0"><dict><key>$archiver</key><string>NSKeyedArchiver'
                '</string><key>$version</key><integer>100000</integer><key>$top</key><dict><key>root</key><dict><key>CF$UID</key>'
                '<integer>1</integer></dict></dict><key>$objects</key><array><string>$null</string><dict><key>x</key><dict>'
                '<key>CF$UID</key><integer>-1</integer></dict></dict></array></dict></plist>').encode()
    for raw in [encode_archive(huge.document(), B), negative]:
        result = run.ok('apple.keyed_archive', raw)
        link = [row for row in result['references'] if row['source'] == 1][0]
        assert link['status'] == 'malformed' and link['target'] is None and link['path'] == ['x']


def test_xml_archive_with_integer_and_text_forms_plistlib_does_not_write(run):
    xml = ('<?xml version="1.0" encoding="UTF-8"?><plist version="1.0"><dict><key>$archiver</key><string>NSKeyedArchiver</string>'
           '<key>$version</key><integer>100000</integer><key>$top</key><dict><key>root</key><dict><key>CF$UID</key><integer>1'
           '</integer></dict></dict><key>$objects</key><array><string>$null</string><dict><key>hex</key><integer>0xFFFFFFFFFFFFFFFF'
           '</integer><key>small</key><integer>0x1F</integer><key>exp</key><real>1e3</real><key>t</key><true/><key>f</key><false/>'
           '<key>empty</key><string/><key>data</key><data>\n AAEC\n Aw==\n</data><key>text</key><string>a &amp; b &#233; &#x1F600; '
           '<![CDATA[<raw>]]></string><key>when</key><date>2020-01-02T03:04:05Z</date></dict></array></dict></plist>').encode()
    result = run.ok('apple.keyed_archive', xml)
    expected = {'hex': {'$plist_type': 'integer', 'decimal': str(2**64 - 1)}, 'small': 31, 'exp': 1000, 't': True, 'f': False,
                'empty': '', 'data': {'$plist_type': 'data', 'base64': base64.b64encode(b'\x00\x01\x02\x03').decode()},
                'text': 'a & b é 😀 <raw>', 'when': {'$plist_type': 'date', 'iso8601': '2020-01-02T03:04:05.000Z'}}
    assert_same(result['objects'][1]['value'], expected, ordered=False, strict=False)


def test_non_finite_reals_are_reported_as_unknown_with_a_count(run):
    a = Archive(top={'root': U(1)})
    a.add([math.inf, -math.inf, math.nan, 1.5])
    for fmt in (B, X):
        result = run.ok('apple.keyed_archive', encode_archive(a.document(), fmt))
        assert_same(result['objects'][1]['value'], [{'$plist_type': 'real', 'value': None}] * 3 + [1.5], strict=False)
        assert any('3 non-finite real' in note for note in result['limitations'])


def keyed_binary_cases():
    good = encode_archive(sample(B).document(), B)
    version, offset_size, ref_size, count, top, table = binary_trailer(good)
    trailer = lambda **fields: good[:-32] + struct.pack('>5xBBBQQQ', 0, fields.get('offset', offset_size), fields.get('ref', ref_size),
                                                       fields.get('objects', count), fields.get('top', top), fields.get('table', table))
    # an archive-shaped dictionary whose $objects array contains the dictionary itself
    cyclic = raw_bplist([('d', [(1, 2), (3, 6), (4, 5)]), ('s', '$archiver'), ('s', 'NSKeyedArchiver'), ('s', '$objects'),
                         ('s', '$top'), ('d', []), ('a', [0])])
    return {'table-beyond-file': trailer(table=len(good) + 10), 'truncated': good[:-40], 'top-out-of-range': trailer(top=count + 5),
            'offset-size-9': trailer(offset=9), 'wrong-magic': b'bplist99' + good[8:], 'object-count-huge': trailer(objects=10**6),
            'cyclic-object-references': cyclic, 'empty': b'', 'garbage': b'\x00\x01\x02' * 50}


@pytest.mark.parametrize('name', sorted(keyed_binary_cases()))
def test_damaged_archives_fail(run, name):
    raw = keyed_binary_cases()[name]
    run.fails('apple.keyed_archive', raw, mentions='cycle' if name.startswith('cyclic') else None)


def minimal(**changes):
    document = {'$archiver': 'NSKeyedArchiver', '$version': 100000, '$top': {'root': U(1)}, '$objects': ['$null', 'x']}
    for key, value in changes.items():
        if value is None:
            document.pop(key)
        else:
            document[key] = value
    return document


@pytest.mark.parametrize('fmt', FORMATS)
@pytest.mark.parametrize('document', [
    minimal(**{'$objects': None}), minimal(**{'$objects': {'not': 'an array'}}), minimal(**{'$top': None}), minimal(**{'$top': {}}),
    minimal(**{'$top': [U(1)]}), minimal(**{'$archiver': None}), minimal(**{'$archiver': 'NSArchiver'}), minimal(**{'$archiver': 7}),
    {'plain': 'dictionary'}, ['array', 'root'], 'string root'],
    ids=['no-objects', 'objects-dict', 'no-top', 'empty-top', 'top-array', 'no-archiver', 'other-archiver', 'archiver-int',
         'plain-dict', 'array-root', 'string-root'])
def test_documents_that_are_not_keyed_archives_fail(run, fmt, document):
    run.fails('apple.keyed_archive', encode_archive(document, fmt))


def test_property_list_and_compiled_nib_are_refused_with_a_pointer_to_the_right_tool(run):
    run.fails('apple.keyed_archive', dumps({'CFBundleName': 'App', 'n': 1}, B), mentions='not an NSKeyedArchiver')
    run.fails('apple.keyed_archive', b'NIBArchive' + b'\x00' * 60, mentions='NIBArchive')


@pytest.mark.parametrize('parameters', [{'offset': -1}, {'limit': 'ten'}, {'limit': -1}, {'offset': 1.5}, {'unknown': 1}, {'root': 3}])
def test_invalid_parameters_are_refused_by_the_api(run, parameters):
    with pytest.raises(Exception, match='400'):  # the operation schema is enforced when the analysis is requested
        run.ok('apple.keyed_archive', encode_archive(sample(B).document(), B), parameters)


def test_plist_operation_takes_no_parameters(run):
    with pytest.raises(Exception, match='400'):
        run.ok('apple.plist', dumps({'a': 1}, B), {'root': 'a'})


def test_zero_limit_cannot_stall_a_paging_client(run):
    # A page of zero objects would leave next_offset equal to offset; the operation schema refuses it.
    raw = encode_archive(sample(B).document(), B)
    with pytest.raises(Exception, match='400'):
        run.ok('apple.keyed_archive', raw, {'limit': 0})


@pytest.mark.parametrize('flag', [b'<true/>', b'<false/>', b'<real>5.0</real>', b'<integer>-1</integer>'])
def test_xml_cf_uid_dictionary_without_a_non_negative_integer_stays_a_dictionary(run, flag):
    # plistlib reads <true/> as True, which is an int subclass in Python; Core Foundation only reads an integer here
    raw = b'<?xml version="1.0" encoding="UTF-8"?><plist version="1.0"><dict><key>u</key><dict><key>CF$UID</key>' + flag + b'</dict></dict></plist>'
    entry = run.ok('apple.plist', raw)['entries'][0]
    assert entry['name'] == 'u' and set(entry['value']) == {'CF$UID'}


def test_shared_objects_that_expand_beyond_the_value_budget_fail_quickly(run):
    # object i is [i+1, i+1]: 40 levels are 41 bplist objects but 2**41 values once every reference is expanded
    objects = [[None, None] for _ in range(40)] + ['leaf']
    for index in range(40):
        objects[index][0] = objects[index][1] = objects[index + 1]
    raw = dumps({'root': objects[0]}, B)
    assert len(raw) < 2000
    import time
    started = time.monotonic()
    run.fails('apple.plist', raw, mentions='expands to more than')
    assert time.monotonic() - started < 60


def test_shared_but_small_graphs_are_expanded_in_full(run):
    leaf = {'k': 1}
    shared = [leaf, leaf, [leaf, leaf]]
    result = run.ok('apple.plist', dumps({'root': shared}, B))
    assert result['entries'][0]['value'] == [{'k': 1}, {'k': 1}, [{'k': 1}, {'k': 1}]]


def test_nesting_beyond_the_depth_limit_fails_with_a_message(run):
    raw = b'<?xml version="1.0"?><plist version="1.0">' + b'<array>' * 3000 + b'</array>' * 3000 + b'</plist>'
    run.fails('apple.plist', raw, mentions='nest')

