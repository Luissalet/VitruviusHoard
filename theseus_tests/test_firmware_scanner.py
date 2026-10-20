"""Real producer completion and failure contracts for the synchronous driver."""
import gzip
import hashlib
import json
import os
from pathlib import Path
import subprocess

import pytest

SCANNER=Path(__file__).resolve().parents[1]/'.cargo-target/release'/('theseus-firmware-scanner.exe' if os.name=='nt' else 'theseus-firmware-scanner')
pytestmark=pytest.mark.skipif(not SCANNER.is_file(),reason='Build the synchronous firmware scanner with Cargo')


@pytest.mark.parametrize('kind',['gzip','empty','unknown'])
def test_real_scanner_publishes_one_complete_analysis_even_without_signatures(tmp_path,kind):
    body=b'Original synchronous firmware payload128\x00'
    encoded=gzip.compress(body,mtime=0)
    raw=b'Prefix'.ljust(128,b'\xff')+encoded if kind=='gzip' else b'' if kind=='empty' else b'Original unsigned bytes'
    source=tmp_path/'original ñ😀 image.bin';source.write_bytes(raw);report=tmp_path/'observation.json'
    reply=subprocess.run([str(SCANNER),'--quiet','--threads','1','--log',str(report),str(source)],capture_output=True)
    assert reply.returncode==0,(reply.stdout,reply.stderr)
    rows=json.loads(report.read_text(encoding='utf8'));assert len(rows)==1
    result=rows[0]['Analysis'];assert result['file_path']==str(source) and result['extractions']=={}
    if kind=='gzip':
        region=next(row for row in result['file_map'] if row['name']=='gzip')
        assert region['offset']==128 and region['size']==len(encoded)
        assert gzip.decompress(raw[region['offset']:region['offset']+region['size']])==body
    else:assert result['file_map']==[]
    assert hashlib.sha256(source.read_bytes()).digest()==hashlib.sha256(raw).digest()


def test_real_scanner_errors_do_not_report_success_or_replace_an_observation(tmp_path):
    source=tmp_path/'original.bin';source.write_bytes(b'Original input')
    report=tmp_path/'report.json';report.write_bytes(b'Original retained observation')
    for args in ([str(tmp_path/'absent.bin')],['--threads','2',str(source)],[str(source)]):
        reply=subprocess.run([str(SCANNER),'--log',str(report),*args],capture_output=True)
        assert reply.returncode!=0 and reply.stderr
        assert report.read_bytes()==b'Original retained observation'
    missing=tmp_path/'not-created.json'
    reply=subprocess.run([str(SCANNER),'--log',str(missing),str(tmp_path/'absent.bin')],capture_output=True)
    assert reply.returncode!=0 and not missing.exists()
