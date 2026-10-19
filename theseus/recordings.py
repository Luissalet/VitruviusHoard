"""Portable observations of supplied ELF64 Linux core recordings; no target launch."""
import base64
import struct


AMD64 = 'r15 r14 r13 r12 rbp rbx r11 r10 r9 r8 rax rcx rdx rsi rdi orig_rax rip cs eflags rsp ss fs_base gs_base ds es fs gs'.split()
ARM64 = [f'x{i}' for i in range(31)] + ['sp', 'pc', 'pstate']
PARAMETERS = {'type': 'object', 'additionalProperties': False, 'properties': {
    'memory_reads': {'type': 'array', 'items': {'type': 'object', 'additionalProperties': False,
        'required': ['address', 'bytes'], 'properties': {
            'address': {'type': 'string', 'pattern': '^0x[0-9a-fA-F]+$'},
            'bytes': {'type': 'integer', 'minimum': 0}}}},
    'frame_limit': {'type': ['integer', 'null'], 'minimum': 0}}}
OPERATIONS = [{'name': 'crash.recording', 'title': 'Fallos · Volcado ELF guardado', 'worker': 'python',
    'description': 'Inspecciona un core Linux ELF64 x86_64/ARM64: notas originales, hilos, registros, señales y mapas. Lee memoria grabada y candidatos de pila por frame pointer; no ejecuta ni conecta con procesos.',
    'inputSchema': PARAMETERS}]


def encoded(raw):
    return base64.b64encode(raw).decode('ascii')


def inspect_core(source, parameters):
    size = source.stat().st_size
    with source.open('rb') as stream:
        def read(offset, length, end=None):
            if offset < 0 or length < 0 or offset + length > (size if end is None else end):
                raise ValueError('Recorded range exceeds its file or note segment')
            stream.seek(offset)
            raw = stream.read(length)
            if len(raw) != length:
                raise ValueError('Recording changed or ended during read')
            return raw

        header = read(0, 64)
        if header[:7] != b'\x7fELF\x02\x01\x01' or header[7] not in (0, 3) or header[8] != 0:
            raise ValueError('Select a Linux/System V ELF64 little-endian core recording')
        kind, machine, version, _, phoff, shoff, _, ehsize, phsize, count, shsize, _, _ = struct.unpack('<HHIQQQIHHHHHH', header[16:])
        if kind != 4 or machine not in (62, 183) or version != 1 or ehsize < 64:
            raise ValueError('Supported recording profiles are ET_CORE Linux x86_64 and ARM64')
        if count == 65535:
            if not shoff or shsize < 64:
                raise ValueError('Extended program header count needs section zero')
            count = struct.unpack_from('<I', read(shoff, shsize), 44)[0]
        if count and phsize < 56:
            raise ValueError('Truncated ELF64 program header entry')
        if phoff + count * phsize > size:
            raise ValueError('Program header table exceeds the recording')
        segments, notes, padding, threads, signals, mappings, auxv = [], [], [], [], [], [], []
        for index in range(count):
            offset = phoff + index * phsize
            ptype, flags, start, address, physical, file_size, memory_size, alignment = struct.unpack('<IIQQQQQQ', read(offset, 56))
            if ptype and file_size and start + file_size > size:
                raise ValueError('Segment bytes exceed the recording')
            if ptype == 1 and file_size > memory_size:
                raise ValueError('PT_LOAD file bytes exceed memory size')
            segment = {'name': f'segment {index}', 'index': index, 'type': ptype,
                'header_offset': offset, 'file_offset': start, 'file_bytes': file_size,
                'address': hex(address), 'memory_bytes': hex(memory_size), 'physical_address': hex(physical),
                'alignment': hex(alignment), 'flags': flags}
            segments.append(segment)
            if ptype != 4:
                continue
            if any(s['type'] == 4 and max(start, s['file_offset']) < min(start + file_size, s['file_offset'] + s['file_bytes'])
                   for s in segments[:-1]):
                raise ValueError('Overlapping note segments make recorded thread identities ambiguous')
            position, end = start, start + file_size
            while position < end:
                if end - position < 12:
                    raw = read(position, end - position, end)
                    if any(raw):
                        raise ValueError('Nonzero trailing bytes lack a complete note header')
                    padding.append({'segment_index': index, 'file_offset': position, 'base64': encoded(raw)})
                    break
                namesz, descsz, ntype = struct.unpack('<III', read(position, 12, end))
                owner_start = position + 12
                descriptor_start = owner_start + ((namesz + 3) // 4) * 4
                next_position = descriptor_start + ((descsz + 3) // 4) * 4
                if next_position > end:
                    raise ValueError('Aligned note exceeds its PT_NOTE segment')
                owner, raw = read(owner_start, namesz, end), read(descriptor_start, descsz, end)
                if owner and b'\0' not in owner:
                    raise ValueError('Note owner lacks a NUL terminator')
                note_index = len(notes)
                notes.append({'name': f'note {note_index} · {ntype}', 'index': note_index,
                    'segment_index': index, 'type': ntype, 'file_offset': position, 'bytes': next_position - position,
                    'owner_offset': owner_start, 'owner_base64': encoded(owner),
                    'owner_display': owner.split(b'\0', 1)[0].decode('utf8', errors='replace'),
                    'descriptor_offset': descriptor_start, 'descriptor_bytes': descsz, 'descriptor_base64': encoded(raw)})
                position = next_position
                if owner != b'CORE\0':
                    continue
                if ntype == 1:
                    names, minimum = (AMD64, 336) if machine == 62 else (ARM64, 392)
                    if descsz < minimum:
                        raise ValueError('Truncated Linux NT_PRSTATUS register descriptor')
                    registers = [{'name': name, 'value': hex(struct.unpack_from('<Q', raw, 112 + ordinal * 8)[0]),
                        'file_offset': descriptor_start + 112 + ordinal * 8, 'bytes': 8} for ordinal, name in enumerate(names)]
                    threads.append({'name': f'thread note {note_index}', 'note_index': note_index,
                        'historical_pid': struct.unpack_from('<i', raw, 32)[0],
                        'signal': struct.unpack_from('<h', raw, 12)[0], 'registers': registers})
                elif ntype == 0x53494749:
                    if descsz < 128:
                        raise ValueError('Truncated Linux NT_SIGINFO descriptor')
                    number, errno, code = struct.unpack_from('<iii', raw)
                    signals.append({'note_index': note_index, 'number': number, 'errno': errno, 'code': code,
                        'fault_address': hex(struct.unpack_from('<Q', raw, 16)[0]) if number == 11 and code in (1, 2) else None,
                        'thread_association': 'unknown'})
                elif ntype == 0x46494c45:
                    if descsz < 16:
                        raise ValueError('Truncated Linux NT_FILE descriptor')
                    entries, page_size = struct.unpack_from('<QQ', raw)
                    boundary = 16 + entries * 24
                    if boundary > descsz or not page_size:
                        raise ValueError('Invalid NT_FILE count or page size')
                    names = raw[boundary:].split(b'\0')
                    if len(names) < entries + 1:
                        raise ValueError('NT_FILE path list lacks complete NUL-terminated names')
                    for ordinal in range(entries):
                        first, last, pages = struct.unpack_from('<QQQ', raw, 16 + ordinal * 24)
                        if last < first:
                            raise ValueError('Reversed recorded module mapping')
                        mappings.append({'name': names[ordinal].decode('utf8', errors='replace'),
                            'path_base64': encoded(names[ordinal]), 'note_index': note_index,
                            'file_offset': descriptor_start + 16 + ordinal * 24,
                            'start': hex(first), 'end': hex(last), 'module_file_offset': hex(pages * page_size),
                            'current_file_identity': 'unknown'})
                elif ntype == 6:
                    if descsz % 16:
                        raise ValueError('NT_AUXV descriptor has a partial word pair')
                    auxv.extend({'note_index': note_index, 'file_offset': descriptor_start + i,
                        'type': str(struct.unpack_from('<Q', raw, i)[0]),
                        'value': hex(struct.unpack_from('<Q', raw, i + 8)[0])} for i in range(0, descsz, 16))

        def memory(address, length):
            cursor, last, chunks = address, address + length, []
            loads = [s for s in segments if s['type'] == 1]
            boundaries = sorted({address, last, *[point for s in loads for point in
                (int(s['address'], 16), int(s['address'], 16) + s['file_bytes']) if address < point < last]})
            for cursor, boundary in zip(boundaries, boundaries[1:]):
                matches = [s for s in loads if int(s['address'], 16) <= cursor and boundary <= int(s['address'], 16) + s['file_bytes']]
                chunk = {'address': hex(cursor), 'bytes': boundary - cursor, 'status': 'unrecorded' if not matches else 'ambiguous'}
                if len(matches) == 1:
                    s = matches[0]
                    start = s['file_offset'] + cursor - int(s['address'], 16)
                    chunk.update(status='recorded', segment_index=s['index'], file_offset=start,
                                 base64=encoded(read(start, boundary - cursor)))
                chunks.append(chunk)
            return {'address': hex(address), 'bytes': length, 'chunks': chunks,
                    'complete': all(c['status'] == 'recorded' for c in chunks)}

        frames = []
        for thread in threads:
            registers = {r['name']: int(r['value'], 16) for r in thread['registers']}
            pointer = registers['rbp' if machine == 62 else 'x29']
            visited, selected = set(), parameters.get('frame_limit')
            while pointer:
                if selected is not None and len(visited) >= selected:
                    frames.append({'note_index': thread['note_index'], 'address': hex(pointer), 'status': 'selection-limit'})
                    break
                if pointer in visited:
                    frames.append({'note_index': thread['note_index'], 'address': hex(pointer), 'status': 'cycle'})
                    break
                visited.add(pointer)
                observed = memory(pointer, 16)
                if not observed['complete']:
                    frames.append({'note_index': thread['note_index'], 'address': hex(pointer), 'status': 'unavailable', 'memory': observed})
                    break
                data = b''.join(base64.b64decode(c['base64']) for c in observed['chunks'])
                following, returning = struct.unpack('<QQ', data)
                candidates = [{**m, 'recorded_module_offset': hex(returning - int(m['start'], 16) + int(m['module_file_offset'], 16))}
                    for m in mappings if int(m['start'], 16) <= returning < int(m['end'], 16)]
                frames.append({'note_index': thread['note_index'], 'address': hex(pointer), 'status': 'candidate',
                    'next_frame_pointer': hex(following), 'return_address': hex(returning), 'memory': observed,
                    'module_candidates': candidates})
                pointer = following
        return {'format': 'elf-core', 'architecture': 'x86_64' if machine == 62 else 'arm64',
            'segments': segments, 'notes': notes, 'note_padding': padding, 'threads': threads,
            'signals': signals, 'recorded_modules': mappings, 'auxv': auxv, 'frame_pointer_candidates': frames,
            'memory_reads': [memory(int(row['address'], 16), row['bytes']) for row in parameters.get('memory_reads', [])],
            'target_execution': 'not-performed', 'live_process_identity': 'unknown',
            'limitations': ['Recorded PIDs, paths and addresses do not identify current processes or current host files.',
                'System V OSABI alone does not prove Linux origin; only exact CORE note owners use the declared Linux ABI.',
                'Only Linux ELF64 little-endian x86_64 and ARM64 PRSTATUS, SIGINFO, FILE and AUXV notes are interpreted; other notes retain original bytes.',
                'Frame-pointer chains are candidates, not verified stack unwinding; optimized code, omitted frame pointers and pointer authentication can invalidate them.',
                'Missing PT_LOAD bytes remain unknown; no zero fill or current executable/library substitution is performed.',
                'Signal-to-thread association remains unknown. Only SIGSEGV codes 1/2 select the recorded fault-address union.']}
