"""Original format carriers, assembled independently from the executable specs."""
import json
import struct
import zlib

from native_fixtures import uleb


CASES=[('pe',32,'little'),('pe',64,'little')]+[
    (kind,bits,order) for kind in ['elf','macho'] for bits in [32,64] for order in ['little','big']]


def data_address(kind,bits):
    return (0x401000 if bits==32 else 0x140001000) if kind=='pe' else 0x1000


def go_payload(kind,bits,order,encoding):
    version=b'go1.original-fixture'
    text=b'path\tfixture.local/measure\nmod\tfixture.local/measure\tv1.2.3\th1:original\nbuild\tCGO_ENABLED=0\n'
    module=bytes.fromhex('3077af0c9274080241e1c107e6d618e6')+text+bytes.fromhex('f932433186182072008242104116d8f2')
    header=bytearray(32);header[:14]=bytes.fromhex('ff20476f206275696c64696e663a')
    width=bits//8;header[14]=width
    if encoding=='inline':
        header[15]=2
        return bytes(header)+uleb(len(version))+version+uleb(len(module))+module
    header[15]=1 if order=='big' else 0
    base=data_address(kind,bits);word=lambda value:value.to_bytes(width,order)
    header[16:16+width]=word(base+32)
    header[16+width:16+width*2]=word(base+32+width*2)
    start=32+width*4
    descriptors=word(base+start)+word(len(version))+word(base+start+len(version))+word(len(module))
    return bytes(header)+descriptors+version+module


def rust_payload():
    document={'packages':[{'name':'measure','version':'1.2.3','source':'local','kind':'runtime','root':True,'dependencies':[1]},
        {'name':'units','version':'2.0.1','source':'registry','kind':'runtime','dependencies':[]}]}
    return zlib.compress(json.dumps(document,separators=(',',':')).encode())


def carrier(kind,bits,order,language,payload,rust_path=None):
    wide=bits==64;endian='<' if order=='little' else '>';address=data_address(kind,bits)
    name=('.data' if kind=='pe' else '.go.buildinfo' if kind=='elf' else '__go_buildinfo') if language=='go' else '.dep-v0'
    # Rustc commit provenance is an independent inferred path in readonly bytes.
    # Zlib only permits padding after its stream, so use a second readonly section.
    contents=[(name,payload)]
    if language=='rust': contents.append(('.rodata',rust_path if rust_path is not None else b'/rustc/'+b'1'*40+b'/library/measure.rs\0'))
    positions=[];cursor=512
    for _,data in contents:
        alignment=512 if kind=='pe' else 16
        positions.append(cursor);cursor=(cursor+len(data)+alignment-1)//alignment*alignment
    raw_end=cursor
    if kind=='pe':
        optional=240 if wide else 224;section_table=152+optional
        raw_end=(raw_end+511)//512*512
        result=bytearray(raw_end);result[:2]=b'MZ';struct.pack_into('<I',result,60,128);result[128:132]=b'PE\0\0'
        struct.pack_into('<HHIIIHH',result,132,0x8664 if wide else 0x14c,len(contents),0,0,0,optional,0x2022)
        struct.pack_into('<H',result,152,0x20b if wide else 0x10b)
        struct.pack_into('<Q' if wide else '<I',result,176 if wide else 180,address-0x1000)
        struct.pack_into('<II',result,184,4096,512);struct.pack_into('<II',result,208,8192,512)
        struct.pack_into('<I',result,260 if wide else 244,16)
        for i,((section,data),at) in enumerate(zip(contents,positions)):
            section_offset=section_table+40*i
            result[section_offset:section_offset+8]=section.encode().ljust(8,b'\0')
            struct.pack_into('<IIIIIIHHI',result,section_offset+8,len(data),0x1000+at-512,(len(data)+511)//512*512,at,0,0,0,0,0xc0000040 if language=='go' else 0x40000040)
    elif kind=='elf':
        names=b'\0'+b''.join(section.encode()+b'\0' for section,_ in contents)+b'.shstrtab\0'
        names_at=raw_end;section_at=(names_at+len(names)+7)//8*8;section_width=64 if wide else 40
        result=bytearray(section_at+section_width*(len(contents)+2))
        result[:16]=b'\x7fELF'+bytes([2 if wide else 1,1 if order=='little' else 2,1])+bytes(9)
        header_size,ph_width=(64,56) if wide else (52,32)
        machine=(62 if wide else 3) if order=='little' else (21 if wide else 20)
        struct.pack_into(endian+('HHIQQQIHHHHHH' if wide else 'HHIIIIIHHHHHH'),result,16,
            2,machine,1,0,header_size,section_at,0,header_size,ph_width,1,section_width,len(contents)+2,len(contents)+1)
        flags=6 if language=='go' else 4
        if wide: struct.pack_into(endian+'IIQQQQQQ',result,header_size,1,flags,512,address,address,raw_end-512,raw_end-512,1)
        else: struct.pack_into(endian+'IIIIIIII',result,header_size,1,512,address,address,raw_end-512,raw_end-512,flags,1)
        for i,((section,data),at) in enumerate(zip(contents,positions),1):
            fields=(names.index(section.encode()+b'\0'),1,3 if language=='go' else 2,address+at-512,at,len(data),0,0,1,0)
            struct.pack_into(endian+('IIQQQQIIQQ' if wide else 'IIIIIIIIII'),result,section_at+section_width*i,*fields)
        fields=(names.index(b'.shstrtab\0'),3,0,0,names_at,len(names),0,0,1,0)
        struct.pack_into(endian+('IIQQQQIIQQ' if wide else 'IIIIIIIIII'),result,section_at+section_width*(len(contents)+1),*fields)
        result[names_at:names_at+len(names)]=names
    else:
        segment_width,section_width,header_size=(72,80,32) if wide else (56,68,28)
        command_size=segment_width+section_width*len(contents)
        result=bytearray(raw_end);cpu=(0x1000007 if wide else 7) if order=='little' else (0x1000012 if wide else 18)
        struct.pack_into(endian+'7I',result,0,0xfeedfacf if wide else 0xfeedface,cpu,3,2,1,command_size,0)
        protection=3 if language=='go' else 1
        struct.pack_into(endian+('II16sQQQQIIII' if wide else 'II16sIIIIIIII'),result,header_size,
            0x19 if wide else 1,command_size,b'__DATA'.ljust(16,b'\0'),address,raw_end-512,512,raw_end-512,protection,protection,len(contents),0)
        for i,((section,data),at) in enumerate(zip(contents,positions)):
            section_name=section if section!='.rodata' else '__const'
            common=(section_name.encode().ljust(16,b'\0'),b'__DATA'.ljust(16,b'\0'),address+at-512,len(data),at,0,0,0,0,0,0)
            struct.pack_into(endian+('16s16sQQIIIIIIII' if wide else '16s16sIIIIIIIII'),result,header_size+segment_width+section_width*i,*(common+(0,) if wide else common))
    for (_,data),at in zip(contents,positions): result[at:at+len(data)]=data
    return bytes(result)
