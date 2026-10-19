"""Original inert Mach-O bytes, laid out from Swift's public metadata ABI.

This is a format fixture, not output from a Swift compiler or a runnable image.
"""
import struct

BASE=0x100000000


def swift_image(architecture='arm64',*,indirect=False,async_slots=False,generic=False,
                conditional=False,unmapped=False,bad_header=False,bad_relative=False):
    raw=bytearray(8192)
    def u32(at,value): struct.pack_into('<I',raw,at,value)
    def ptr(at,target): struct.pack_into('<Q',raw,at,BASE+target)
    def rel(at,target,tag=0): struct.pack_into('<i',raw,at,(target-at)|tag)
    def segment(at,name,offset,protection,sections):
        size=72+80*len(sections)
        struct.pack_into('<II16sQQQQIIII',raw,at,0x19,size,name.encode(),BASE+offset,4096,offset,4096,protection,protection,len(sections),0)
        for index,(section,pos,length) in enumerate(sections):
            struct.pack_into('<16s16sQQIIIIIIII',raw,at+72+80*index,section.encode(),name.encode(),BASE+pos,length,pos,2,0,0,0,0,0,0)
        return size
    code_size=segment(32,'__TEXT',0,5,[('__text',0x800,0x100)])
    data_size=segment(32+code_size,'__DATA',4096,3,[('__swift5_proto',0x1000,4),('__swift5_types',0x1010,4),('__const',0x1020,0xfe0)])
    struct.pack_into('<8I',raw,0,0xfeedfacf,0x100000c if architecture=='arm64' else 0x1000007,0 if architecture=='arm64' else 3,6,2,code_size+data_size,0,0)
    raw[0x800:0x804]=b'\xc0\x03\x5f\xd6' if architecture=='arm64' else b'\x48\x31\xc0\xc3'
    raw[0x820:0x824]=raw[0x800:0x804]
    rel(0x1000,0x1100);rel(0x1010,0x1300)
    # Conformance: protocol, type, witness-table pattern and type-reference flags.
    rel(0x1100,0x9000 if bad_relative else 0x1588 if indirect else 0x1200,1 if indirect and not bad_relative else 0)
    rel(0x1104,0x1580 if indirect else 0x1300);rel(0x1108,0x1500)
    u32(0x110c,(8 if indirect else 0)|(0x100 if conditional else 0))
    ptr(0x1580,0x1300);ptr(0x1588,0x1200)
    # Protocol descriptor, two synchronous method requirements and UTF-8 name.
    u32(0x1200,3);rel(0x1208,0x1600);u32(0x1210,2)
    u32(0x1218,0x21 if async_slots else 1);u32(0x1220,1)
    # Non-resilient class descriptor with a two-entry vtable at metadata word16.
    u32(0x1300,0x80000010|(0x80 if generic else 0));rel(0x1308,0x1620)
    u32(0x131c,20);u32(0x132c,16);u32(0x1330,2)
    u32(0x1334,0x40 if async_slots else 0);rel(0x1338,0x1700 if unmapped else 0x800)
    rel(0x1340,0x820)
    ptr(0x1500,0x1200 if bad_header else 0x1100)
    ptr(0x1508,0x1700 if unmapped else 0x800);ptr(0x1510,0x820)
    for at,text in [(0x1600,'MeasureRule'),(0x1620,'Gaugeñ')]:
        encoded=text.encode()+b'\0';raw[at:at+len(encoded)]=encoded
    return bytes(raw)


def swift_fat(*,wide=False,little=False):
    """Two separately addressable slices; offsets in evidence own the container."""
    order='<' if little else '>';raw=bytearray(24576)
    struct.pack_into(order+'II',raw,0,0xcafebabf if wide else 0xcafebabe,2)
    for index,(architecture,cpu,subtype,at) in enumerate([('arm64',0x100000c,0,4096),('x86_64',0x1000007,3,16384)]):
        struct.pack_into(order+('IIQQII' if wide else 'IIIII'),raw,8+index*(32 if wide else 20),
            cpu,subtype,at,8192,12,*([0] if wide else []))
        raw[at:at+8192]=swift_image(architecture)
    return bytes(raw)
