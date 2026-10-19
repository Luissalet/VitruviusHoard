"""Original ELF64 core bytes with deliberately controlled recorded observations."""
import struct


def core_image(machine=62, owner=b'CORE\0', cycle=False):
    def note(kind, data):
        return struct.pack('<III', len(owner), len(data), kind) + owner + bytes(-len(owner) % 4) + data + bytes(-len(data) % 4)
    status = bytearray(336 if machine == 62 else 392)
    struct.pack_into('<h', status, 12, 11)
    struct.pack_into('<i', status, 32, 5678)
    # Frame pointer, instruction pointer and stack pointer in the declared Linux ABI.
    for index, value in ([(4, 0x7000), (16, 0x401234), (19, 0x7000)] if machine == 62 else [(29, 0x7000), (32, 0x401234), (31, 0x7000)]):
        struct.pack_into('<Q', status, 112 + index * 8, value)
    signal = bytearray(128)
    struct.pack_into('<iii', signal, 0, 11, 0, 1)
    struct.pack_into('<Q', signal, 16, 0xDEADBEEF)
    files = struct.pack('<QQQQQ', 1, 4096, 0x400000, 0x402000, 2) + b'/recorded/old-module\0'
    notes = note(1, status) + note(0x53494749, signal) + note(0x46494c45, files) + note(6, struct.pack('<QQQQ', 9, 0x401234, 0, 0)) + note(42, b'\x80\xffopaque')
    stack = struct.pack('<QQQQ', 0x7010, 0x401234, 0x7000 if cycle else 0, 0x401567)
    ident = b'\x7fELF\x02\x01\x01' + bytes(9)
    header = ident + struct.pack('<HHIQQQIHHHHHH', 4, machine, 1, 0, 64, 0, 0, 64, 56, 2, 0, 0, 0)
    note_header = struct.pack('<IIQQQQQQ', 4, 0, 0x100, 0, 0, len(notes), len(notes), 4)
    load_header = struct.pack('<IIQQQQQQ', 1, 6, 0x1000, 0x7000, 0, len(stack), 4096, 4096)
    data = bytearray(0x1000 + len(stack))
    data[:64] = header
    data[64:176] = note_header + load_header
    data[0x100:0x100 + len(notes)] = notes
    data[0x1000:] = stack
    return bytes(data)
