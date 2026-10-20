"""ELF64 x86-64 file observations, with retained bytes and scoped inferences.

This reader never loads the selected image or resolves a runtime library.
"""
import base64
import hashlib
import struct
from pathlib import Path

OPERATIONS = [{"name": "binary.layout", "title": "ELF · Secciones, símbolos y relocaciones",
    "description": "Lee ELF64 x86-64 little-endian: bytes y ubicaciones originales, símbolos, REL/RELA/RELR, dependencias e indicadores estáticos. No carga ni ejecuta el binario.",
    "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}, "worker": "python"}]

SECTION_TYPES = {0: "SHT_NULL", 1: "SHT_PROGBITS", 2: "SHT_SYMTAB", 3: "SHT_STRTAB",
    4: "SHT_RELA", 5: "SHT_HASH", 6: "SHT_DYNAMIC", 7: "SHT_NOTE", 8: "SHT_NOBITS",
    9: "SHT_REL", 10: "SHT_SHLIB", 11: "SHT_DYNSYM", 14: "SHT_INIT_ARRAY",
    15: "SHT_FINI_ARRAY", 16: "SHT_PREINIT_ARRAY", 17: "SHT_GROUP", 18: "SHT_SYMTAB_SHNDX", 19: "SHT_RELR"}
SEGMENT_TYPES = {0: "PT_NULL", 1: "PT_LOAD", 2: "PT_DYNAMIC", 3: "PT_INTERP", 4: "PT_NOTE",
    5: "PT_SHLIB", 6: "PT_PHDR", 7: "PT_TLS", 0x6474e550: "PT_GNU_EH_FRAME",
    0x6474e551: "PT_GNU_STACK", 0x6474e552: "PT_GNU_RELRO", 0x6474e553: "PT_GNU_PROPERTY"}
U64 = (1 << 64) - 1


def location(offset, length):
    return {"offset": hex(offset), "bytes": hex(length)}


class ElfReader:
    def __init__(self, raw):
        self.raw = raw
        self.records = []
        self.limits = []

    def read(self, offset, size):
        if offset < 0 or size < 0 or offset > len(self.raw) or size > len(self.raw) - offset:
            raise ValueError(f"ELF file range outside selected artifact: {offset:#x}+{size:#x}")
        return self.raw[offset:offset + size]

    def unpack(self, fmt, offset):
        return struct.unpack(fmt, self.read(offset, struct.calcsize(fmt)))

    def retain(self, kind, identity, offset, size):
        raw = self.read(offset, size)
        self.records.append({"kind": kind, "identity": identity, "location": location(offset, size),
            "bytes_base64": base64.b64encode(raw).decode("ascii"), "sha256": hashlib.sha256(raw).hexdigest()})

    def unknown_name(self, reason):
        return {"display": "", "bytes_base64": None, "location": None, "unknown_reason": reason}

    def name(self, offset, size, index=0):
        if index >= size:
            return self.unknown_name("String offset is outside its declared table")
        table = self.read(offset, size)
        end = table.find(b"\0", index)
        if end < 0:
            return self.unknown_name("String has no terminator within its declared range")
        raw = table[index:end]
        return {"display": raw.decode("utf8", errors="replace"), "bytes_base64": base64.b64encode(raw).decode("ascii"),
            "location": location(offset + index, len(raw)), "unknown_reason": None}

    def section(self, index):
        if not 0 <= index < len(self.sh):
            raise ValueError(f"ELF section index outside declared inventory: {index}")
        return self.sh[index]

    def table_entries(self, section, minimum):
        stride, size = section[9], section[5]
        if stride < minimum or size % stride:
            raise ValueError("ELF table has an invalid entry size or incomplete final entry")
        self.read(section[4], size)
        return ((i, section[4] + i * stride) for i in range(size // stride))

    def parse(self, path):
        h = self.unpack("<16sHHIQQQIHHHHHH", 0)
        ident, typ, machine, version, entry, phoff, shoff, flags, ehsize, phsize, phnum, shsize, shnum, shnames = h
        if ident[:7] != b"\x7fELF\x02\x01\x01" or machine != 62 or typ not in {1, 2, 3}:
            raise ValueError("binary.layout supports ELF64 little-endian x86-64 ET_REL, ET_EXEC and ET_DYN")
        if version != 1 or ehsize < 64:
            raise ValueError("Invalid ELF header version or size")
        self.retain("elf-header", {}, 0, ehsize)
        self.sh = []
        if shoff:
            if shsize < 64:
                raise ValueError("Invalid ELF section-header stride")
            zero = self.unpack("<IIQQQQIIQQ", shoff)
            if not shnum or shnames == 0xffff or phnum == 0xffff:
                if zero[1] != 0:
                    raise ValueError("Extended ELF numbering requires a null section zero")
                if not shnum: shnum = zero[5]
                if shnames == 0xffff: shnames = zero[6]
                if phnum == 0xffff: phnum = zero[7]
            self.read(shoff, shsize * shnum)
            self.sh = [self.unpack("<IIQQQQIIQQ", shoff + i * shsize) for i in range(shnum)]
        elif shnum or shnames or phnum == 0xffff:
            raise ValueError("ELF header references missing section headers")
        if phnum and (not phoff or phsize < 56):
            raise ValueError("Invalid ELF program-header offset or stride")
        self.read(phoff, phsize * phnum)
        self.ph = [self.unpack("<IIQQQQQQ", phoff + i * phsize) for i in range(phnum)]
        name_table = self.section(shnames) if shnames else None
        if name_table is not None and name_table[1] != 3:
            raise ValueError("Section names must refer to a string table")
        sections = []
        for i, s in enumerate(self.sh):
            self.retain("section-header", {"section_index": i}, shoff + i * shsize, shsize)
            if s[1] not in {0, 8}:
                self.retain('section-payload', {'section_index': i}, s[4], s[5])
            sections.append({"index": i, "name": self.name(name_table[4], name_table[5], s[0]) if name_table else self.unknown_name("No section name table"),
                "name_offset": hex(s[0]), "type": SECTION_TYPES.get(s[1], s[1]), "header_location": location(shoff + i * shsize, shsize),
                "address": hex(s[3]), "offset": hex(s[4]), "size": hex(s[5]), "alignment": hex(s[8]), "flags": hex(s[2]),
                "link": s[6], "info": s[7], "entry_size": hex(s[9]), "file_backing": "none" if s[1] in {0, 8} else "file"})
        segments = []
        for i, p in enumerate(self.ph):
            self.retain("segment-header", {"segment_index": i}, phoff + i * phsize, phsize)
            backed = p[0] != 0 and p[5] != 0
            if backed: self.read(p[2], p[5])
            segments.append({"index": i, "type": SEGMENT_TYPES.get(p[0], p[0]), "header_location": location(phoff + i * phsize, phsize),
                "offset": hex(p[2]), "file_size": hex(p[5]), "memory_size": hex(p[6]), "virtual_address": hex(p[3]),
                "physical_address": hex(p[4]), "alignment": hex(p[7]), "flags": hex(p[1]), "file_backing": "file" if backed else "none",
                "permissions": None if p[0] == 0 else {"read": bool(p[1] & 4), "write": bool(p[1] & 2), "execute": bool(p[1] & 1)}})
        symbols = self.symbols(typ)
        relocations, packed = self.relocations(typ, symbols)
        linkage, dynamic = self.linkage()
        by_symbol = {(s['table_index'], s['entry_index']): s for s in symbols}
        for rel in relocations:
            if typ != 1 and rel['type'] in {6, 7} and rel['symbol_index']:
                sym = by_symbol[(rel['symbol_table_index'], rel['symbol_index'])]
                linkage['got'].append({'display_name': sym['name']['display'], 'address': rel['reported_offset']})
        stacks = [p for p in self.ph if p[0] == 0x6474e551]
        nx = None if not stacks or len({bool(p[1] & 1) for p in stacks}) != 1 else not bool(stacks[0][1] & 1)
        bind_now = any(tag == 24 or tag == 30 and val & 8 or tag == 0x6ffffffb and val & 1 for tag, val in dynamic)
        relro = ("Full" if bind_now else "Partial") if any(p[0] == 0x6474e552 for p in self.ph) else None
        self.limits.extend(["File and linked-image observations do not establish a runtime load base, execution or behavior.",
            "Relocation inventory and GOT/PLT convenience-map completeness remain unknown; no PLT instruction pattern is guessed.",
            "Mitigations are header, dynamic-tag and symbol indicators; canary references do not prove protection of every function.",
            "ET_DYN indicates position independence, not proof that the artifact is a PIE executable; stack-header absence does not establish NX.",
            "String display uses UTF-8 replacement for invalid bytes; retained base64 and original ranges remain authoritative."])
        return {"artifact": {"path": str(path), "sha256": hashlib.sha256(self.raw).hexdigest(), "bytes": len(self.raw)},
            "format": "elf", "architecture": {"machine": "EM_X86_64", "bits": 64, "byte_order": "little"},
            "image_type": {1: "ET_REL", 2: "ET_EXEC", 3: "ET_DYN"}[typ],
            "entry_point": {"reported_value": hex(entry), "meaning": "not-applicable" if typ == 1 else "absent" if not entry else "linked-virtual-address", "execution_status": "unknown"},
            "runtime_load_base": None, "sections": sections, "segments": segments, "symbols": symbols, "relocations": relocations,
            "packed_relative_relocations": packed, "relocation_inventory_completeness": "unknown", "linkage": linkage,
            "mitigations": {"evidence_kind": "inferred", "position_independent": typ == 3, "nx_indicator": nx,
                "executable_stack_indicator": any(p[1] & 1 for p in stacks),
                "stack_canary_indicator": any(s['name']['display'] in {'__stack_chk_fail', '__stack_chk_guard', '__stack_chk_fail_local'} for s in symbols), "relro": relro},
            "diagnostics": {"stdout": "", "stderr": "", "truncated": False}, "limitations": self.limits,
            "original_records": self.records}

    def symbols(self, typ):
        result = []
        extensions = {}
        for i, s in enumerate(self.sh):
            if s[1] == 18:
                if s[6] in extensions: raise ValueError("Ambiguous extended symbol section-index tables")
                if self.section(s[6])[1] not in {2, 11}: raise ValueError("Extended indices require a symbol table")
                extensions[s[6]] = s
        for i, s in enumerate(self.sh):
            if s[1] not in {2, 11}: continue
            strings = self.section(s[6])
            if strings[1] != 3: raise ValueError("Symbol table must link to a string table")
            extra = extensions.get(i)
            indices = [self.unpack('<I', offset)[0] for _, offset in self.table_entries(extra, 4)] if extra else None
            entries = list(self.table_entries(s, 24))
            if indices is not None and len(indices) != len(entries): raise ValueError("Extended symbol-index count differs from symbol count")
            for j, offset in entries:
                n, info, other, section, val, size = self.unpack('<IBBHQQ', offset)
                self.retain('symbol', {'table_index': i, 'entry_index': j}, offset, s[9])
                resolved = indices[j] if section == 0xffff and indices is not None else section
                if section == 0xffff and indices is None: raise ValueError("Missing extended symbol section indices")
                # Reserved values are special only in the original 16-bit field.
                special = section != 0xffff and section >= 0xff00
                stype = info & 15
                if resolved == 0: meaning = 'undefined'
                elif special and section == 0xfff2: meaning = 'alignment'
                elif special and section == 0xfff1: meaning = 'absolute-value'
                elif stype == 4: meaning = 'no-address'
                elif special or resolved >= len(self.sh) or self.sh[resolved][1] == 0: meaning = 'unknown-section-index'
                elif stype == 6: meaning = 'tls-offset'
                else: meaning = 'section-offset' if typ == 1 else 'linked-virtual-address'
                section_value = {0: 'SHN_UNDEF', 0xfff1: 'SHN_ABS', 0xfff2: 'SHN_COMMON'}.get(section, section) if special or section == 0 else resolved
                result.append({'table_index': i, 'entry_index': j, 'name': self.name(strings[4], strings[5], n), 'name_offset': hex(n),
                    'location': location(offset, s[9]), 'value': hex(val), 'value_meaning': meaning, 'size': hex(size),
                    'binding': {0:'STB_LOCAL',1:'STB_GLOBAL',2:'STB_WEAK'}.get(info >> 4, info >> 4),
                    'type': {0:'STT_NOTYPE',1:'STT_OBJECT',2:'STT_FUNC',3:'STT_SECTION',4:'STT_FILE',5:'STT_COMMON',6:'STT_TLS'}.get(stype, stype),
                    'visibility': {0:'STV_DEFAULT',1:'STV_INTERNAL',2:'STV_HIDDEN',3:'STV_PROTECTED'}[other & 3], 'section_index': section_value})
        return result

    def relocations(self, typ, symbols):
        result, packed = [], []
        available = {(s['table_index'], s['entry_index']) for s in symbols}
        for i, s in enumerate(self.sh):
            if s[1] == 19:
                if s[9] != 8: raise ValueError('ELF64 RELR entries must be eight bytes')
                entries, cursor = [], None
                for j, offset in self.table_entries(s, 8):
                    word = self.unpack('<Q', offset)[0]
                    if not word & 1:
                        values = [word]; cursor = word + 8
                    else:
                        if cursor is None: raise ValueError('RELR bitmap precedes an address entry')
                        values = [cursor + bit * 8 for bit in range(63) if word & (1 << (bit + 1))]; cursor += 63 * 8
                    if cursor > U64 + 1 or any(v > U64 for v in values): raise ValueError('RELR address overflow')
                    base = len(entries)
                    entries.extend({'decoded_index': base + j, 'reported_offset': hex(v)} for j, v in enumerate(values))
                self.retain('packed-relative-table', {'section_index': i}, s[4], s[5])
                packed.append({'section_index': i, 'location': location(s[4], s[5]), 'encoded_bytes_base64': base64.b64encode(self.read(s[4], s[5])).decode('ascii'),
                    'entries': entries, 'offset_meaning': 'unknown' if typ == 1 else 'linked-virtual-address', 'evidence_kind':'derived', 'entry_source_locations':None,'addends':None})
            if s[1] not in {4, 9}: continue
            if s[6] and self.section(s[6])[1] not in {2, 11}: raise ValueError('Relocation links to a non-symbol table')
            if typ == 1: owner = self.section(s[7])
            for j, offset in self.table_entries(s, 24 if s[1] == 4 else 16):
                fields = self.unpack('<QQq' if s[1] == 4 else '<QQ', offset); reported, info = fields[:2]
                sym, rtype = info >> 32, info & 0xffffffff
                if sym and (s[6], sym) not in available: raise ValueError('Relocation symbol reference is outside its linked table')
                self.retain('relocation', {'section_index':i,'entry_index':j}, offset, s[9])
                target = {'kind':'linked-virtual-address','address':hex(reported)}
                if typ == 1:
                    target = ({'kind':'section-offset','section_index':s[7],'offset':hex(reported)} if s[7] and owner[1] else
                        {'kind':'unknown-section','reported_section_index':s[7],'offset':hex(reported),
                         'unknown_reason':'inactive-section-header' if s[7] else 'undefined-section-reference'})
                result.append({'section_index':i,'entry_index':j,'reported_offset':hex(reported),'target':target,'location':location(offset,s[9]),
                    'type':rtype,'symbol_table_index':s[6],'symbol_index':sym,'symbol_reference_meaning':'symbol-table-entry' if sym else 'zero-symbol-value',
                    'addend':str(fields[2]) if s[1] == 4 else None})
        return result, packed

    def virtual_range(self, address, size):
        candidates = {p[2] + address - p[3] for p in self.ph if p[0] == 1 and p[3] <= address and address - p[3] <= p[5] and size <= p[5] - (address - p[3])}
        if len(candidates) != 1: return None
        offset = candidates.pop(); self.read(offset, size)
        return offset

    def linkage(self):
        result = {'needed_libraries':[],'interpreters':[],'got':[],'plt':[],'convenience_maps_completeness':'unknown','runtime_library_paths':None}
        tables, dynamic = {}, []
        for i, s in enumerate(self.sh):
            if s[1] != 6: continue
            stride = s[9]
            if stride < 16 or s[5] % stride: raise ValueError('Invalid dynamic table entry size')
            strings = self.section(s[6]) if s[6] else None
            if strings and strings[1] != 3: raise ValueError('Dynamic section must link to a string table')
            tables[(s[4],s[5])] = (stride, strings)
        for p in self.ph:
            if p[0] == 3:
                self.retain('interpreter',{},p[2],p[5]); result['interpreters'].append(self.name(p[2],p[5]))
            if p[0] == 2:
                if p[5] % 16: raise ValueError('Incomplete dynamic program table')
                tables.setdefault((p[2],p[5]),(16,None))
        for (offset, size), (stride, strings) in tables.items():
            self.retain('dynamic-table',{},offset,size); values=[]
            for at in range(offset,offset+size,stride):
                tag, val = self.unpack('<qQ',at)
                if tag == 0: break
                values.append((tag,val))
            dynamic.extend(values)
            if strings:
                string_range = (strings[4],strings[5])
            else:
                addresses={v for t,v in values if t==5}; lengths={v for t,v in values if t==10}
                mapped = self.virtual_range(next(iter(addresses)),next(iter(lengths))) if len(addresses)==len(lengths)==1 else None
                string_range=(mapped,next(iter(lengths))) if mapped is not None else None
            for tag, val in values:
                if tag == 1:
                    result['needed_libraries'].append(self.name(*string_range,val) if string_range else self.unknown_name('Dynamic string table is unavailable or its file mapping is ambiguous'))
        return result, dynamic


def inspect_layout(source):
    source = Path(source)
    return ElfReader(source.read_bytes()).parse(source)
