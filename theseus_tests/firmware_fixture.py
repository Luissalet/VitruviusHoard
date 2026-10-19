"""Original embedded compression and archive fixtures, never target executables."""
import bz2
import gzip
import io
import lzma
import stat
import tarfile
import zipfile


def embedded_streams():
    bodies=[b'Original gzip measure 128\n',b'Original xz measure 256\n',b'Original bzip measure 512\n']
    encoded=[gzip.compress(bodies[0],mtime=0),lzma.compress(bodies[1]),bz2.compress(bodies[2])]
    image=b'Original firmware header\0'.ljust(128,b'\xff');ranges=[]
    for name,compressed,body in zip(['gzip','xz','bzip2'],encoded,bodies):
        ranges.append({'name':name,'offset':len(image),'length':len(compressed),'body':body})
        image+=compressed+bytes(64)
    return image,ranges


def archive_image(kind):
    stream=io.BytesIO()
    if kind=='zip':
        with zipfile.ZipFile(stream,'w',compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("../outside\nquote'.bin",b'Original quoted member\x00')
            archive.writestr('repeat.bin',b'First original')
            archive.writestr('repeat.bin',b'Second original')
            link=zipfile.ZipInfo('do-not-create-link');link.create_system=3;link.external_attr=(stat.S_IFLNK|0o777)<<16
            archive.writestr(link,b'../../outside')
    else:
        with tarfile.open(fileobj=stream,mode='w') as archive:
            data=b'Original TAR member\x00'
            entry=tarfile.TarInfo('../outside');entry.size=len(data);archive.addfile(entry,io.BytesIO(data))
            link=tarfile.TarInfo('do-not-create-link');link.type=tarfile.SYMTYPE;link.linkname='../../outside';archive.addfile(link)
    return b'Original container prefix'.ljust(128,b'\xff')+stream.getvalue()


def many_members():
    stream=io.BytesIO()
    with zipfile.ZipFile(stream,'w',compression=zipfile.ZIP_DEFLATED) as archive:
        for number in range(500):archive.writestr(f'original-{number}.bin',b'Original body'+str(number).encode())
    return stream.getvalue()
