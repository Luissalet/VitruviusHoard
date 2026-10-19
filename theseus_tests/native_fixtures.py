"""Original tiny format fixtures; none contains reference-project test data."""
import json
import plistlib
import struct
import zlib


def pe(section, payload, flags=0xC0000040):
    raw_size = (len(payload) + 511) // 512 * 512
    data = bytearray(512 + raw_size)
    data[:2] = b'MZ'
    struct.pack_into('<I', data, 60, 128)
    data[128:132] = b'PE\0\0'
    struct.pack_into('<HHIIIHH', data, 132, 0x8664, 1, 0, 0, 0, 240, 0x2022)
    struct.pack_into('<H', data, 152, 0x20b)
    struct.pack_into('<Q', data, 176, 0x140000000)
    struct.pack_into('<II', data, 184, 4096, 512)
    struct.pack_into('<II', data, 208, 8192, 512)
    struct.pack_into('<I', data, 260, 16)
    data[392:400] = section.encode().ljust(8,b'\0')
    struct.pack_into('<IIIIIIHHI', data, 400, len(payload), 4096, raw_size, 512, 0, 0, 0, 0, flags)
    data[512:512+len(payload)] = payload
    return bytes(data)


def uleb(number):
    data=bytearray()
    while number>=128:
        data.append((number & 127)|128)
        number >>= 7
    data.append(number)
    return bytes(data)


def go_image():
    body=b'path\tfixture.local/gauge\nmod\tfixture.local/gauge\tv1.2.3\th1:fixture\n'
    module=bytes.fromhex('3077af0c9274080241e1c107e6d618e6')+body+bytes.fromhex('f932433186182072008242104116d8f2')
    version=b'go1.fixture'
    header=bytearray(32)
    header[:14]=bytes.fromhex('ff20476f206275696c64696e663a')
    header[14:16]=bytes([8,2])
    return pe('.data',bytes(header)+uleb(len(version))+version+uleb(len(module))+module)


def rust_image(trailing=False):
    document={'packages':[{'name':'gauge','version':'1.2.3','source':'local','kind':'runtime','root':True,'dependencies':[1]},
                          {'name':'units','version':'2.0.1','source':'registry','kind':'runtime','dependencies':[]}]}
    compressed=zlib.compress(json.dumps(document,separators=(',',':')).encode())
    if trailing: compressed+=b'junk'
    return pe('.dep-v0',compressed,0x40000040)


def electron_image():
    sentinel=b'dL7pKGdnNz796PbbjQWNKmHXBZaB9tsX'
    return pe('.data',sentinel+bytes([1,9])+b'101010101')


def macho_image():
    def command(kind,prefix,text):
        size=(8+len(prefix)+len(text)+1+7)//8*8
        return struct.pack('<II',kind,size)+prefix+text+b'\0'*(size-8-len(prefix)-len(text))
    commands=command(0x8000001c,struct.pack('<I',12),b'@loader_path/Frameworks')
    commands+=command(0xc,struct.pack('<IIII',24,0,0x10203,0x10000),b'@rpath/Fixture.dylib')
    return struct.pack('<IIIIIIII',0xfeedfacf,0x1000007,3,6,2,len(commands),0,0)+commands


def keyed_archive(binary=True):
    uid = plistlib.UID if binary else lambda number:{'CF$UID':number}
    archive={'$archiver':'NSKeyedArchiver','$version':100000,'$top':{'root':uid(1)},'$objects':[
        '$null', {'$class':uid(2),'title':'Año','next':uid(1)}, {'$classname':'GaugeView','$classes':['GaugeView','NSObject']}]}
    return plistlib.dumps(archive,fmt=plistlib.FMT_BINARY if binary else plistlib.FMT_XML,sort_keys=False)


def nib_archive():
    def number(value):
        assert value<128
        return bytes([value|128])
    objects=number(0)+number(0)+number(1)+number(1)+number(1)+number(1)
    keys=number(5)+b'title'+number(11)+b'destination'
    title='Año'.encode()
    values=number(0)+bytes([8])+number(len(title))+title+number(1)+bytes([10])+struct.pack('<I',0)
    classes=number(7)+number(0)+b'UIView\0'+number(19)+number(0)+b'UIOutletConnection\0'
    offsets=[50,50+len(objects),50+len(objects)+len(keys),50+len(objects)+len(keys)+len(values)]
    return b'NIBArchive'+struct.pack('<10I',1,1,2,offsets[0],2,offsets[1],2,offsets[2],2,offsets[3])+objects+keys+values+classes


def evm_bytecode():
    code=bytes.fromhex('60003560e01c63deadbeef146012575f5ffd5b60805f5260205ff3')
    metadata=bytes.fromhex('a164736f6c6343000801')
    return code+metadata+struct.pack('>H',len(metadata))


def dart_elf():
    names=['', '.rodata', '.dynstr', '.dynsym', '.note.gnu.build-id', '.shstrtab']
    shstrings=b'\0'
    name_offsets={}
    for name in names[1:]:
        name_offsets[name]=len(shstrings)
        shstrings+=name.encode()+b'\0'
    symbol_names=['_kDartVmSnapshotData','_kDartIsolateSnapshotData']
    strings=b'\0'
    symbol_offsets=[]
    for name in symbol_names:
        symbol_offsets.append(len(strings))
        strings+=name.encode()+b'\0'
    snapshot=struct.pack('<IQQ',0xdcdcf5f5,48,3)+b'1234567890abcdef1234567890abcdef'
    note=struct.pack('<III',4,8,3)+b'GNU\0'+b'gauge779'
    data=bytearray(120)
    sections=[(0,0,0,0,0,0,0,0,0,0)]
    for index,payload in enumerate([snapshot,strings,b'\0'*72,note,shstrings],1):
        while len(data)%8: data.append(0)
        offset=len(data)
        data+=payload
        kind=[0,1,3,11,7,3][index]
        sections.append((name_offsets[names[index]],kind,2 if index<5 else 0,offset if index<5 else 0,
                         offset,len(payload),2 if index==3 else 0,1 if index==3 else 0,8 if index==3 else 1,24 if index==3 else 0))
    for i,name_offset in enumerate(symbol_offsets,1):
        struct.pack_into('<IBBHQQ',data,sections[3][4]+i*24,name_offset,17,0,1,sections[1][4],len(snapshot))
    while len(data)%8: data.append(0)
    section_offset=len(data)
    for section in sections: data+=struct.pack('<IIQQQQIIQQ',*section)
    ident=b'\x7fELF'+bytes([2,1,1])+b'\0'*9
    struct.pack_into('<16sHHIQQQIHHHHHH',data,0,ident,3,62,1,0,64,section_offset,0,64,56,1,64,len(sections),5)
    struct.pack_into('<IIQQQQQQ',data,64,1,4,0,0,0,len(data),len(data),4096)
    return bytes(data)
