import base64
import io
import struct

from fastapi.testclient import TestClient
import pytest

from crash_fixture import core_image
from test_portfolio import run
from theseus.api import create_app
from theseus.recordings import inspect_core


@pytest.mark.parametrize('machine,architecture,register', [(62,'x86_64','rip'), (183,'arm64','pc')])
def test_recorded_core_register_signal_module_and_exact_memory(tmp_path, machine, architecture, register):
    path = tmp_path/'original.core'
    raw = core_image(machine)
    path.write_bytes(raw)
    result = inspect_core(path,{'memory_reads':[{'address':'0x7018','bytes':24}]})
    assert result['architecture'] == architecture
    assert result['threads'][0]['historical_pid'] == 5678
    pc = next(r for r in result['threads'][0]['registers'] if r['name'] == register)
    assert pc['value'] == '0x401234'
    assert raw[pc['file_offset']:pc['file_offset']+8] == struct.pack('<Q',0x401234)
    assert result['signals'][0]['fault_address'] == '0xdeadbeef'
    assert result['recorded_modules'][0]['current_file_identity'] == 'unknown'
    frames = result['frame_pointer_candidates']
    assert len(frames) == 2 and frames[0]['return_address'] == '0x401234'
    assert frames[0]['module_candidates'][0]['recorded_module_offset'] == '0x3234'
    memory = result['memory_reads'][0]
    assert not memory['complete']
    assert memory['chunks'][0]['status'] == 'recorded' and memory['chunks'][1]['status'] == 'unrecorded'
    assert base64.b64decode(memory['chunks'][0]['base64']) == struct.pack('<Q',0x401567)
    assert base64.b64decode(result['notes'][-1]['descriptor_base64']) == b'\x80\xffopaque'
    assert result['target_execution'] == 'not-performed' and path.read_bytes() == raw
    # Independent generic ELF parser confirms the original container, not our reader's output.
    from elftools.elf.elffile import ELFFile
    image = ELFFile(io.BytesIO(raw))
    assert image.header['e_type'] == 'ET_CORE' and image.num_segments() == 2
    assert [n['n_type'] for n in image.get_segment(0).iter_notes()][:2] == ['NT_PRSTATUS','NT_SIGINFO']


def test_recorded_core_unknown_owner_cycle_and_explicit_selection(tmp_path):
    path = tmp_path/'owner.core'
    path.write_bytes(core_image(owner=b'FOREIGN\0'))
    result = inspect_core(path,{})
    assert result['notes'] and not result['threads'] and not result['signals']
    path.write_bytes(core_image(cycle=True))
    result = inspect_core(path,{})
    assert result['frame_pointer_candidates'][-1]['status'] == 'cycle'
    assert inspect_core(path,{'frame_limit':0})['frame_pointer_candidates'][0]['status'] == 'selection-limit'


def test_recorded_core_extended_header_count_overlap_and_signal_unknown(tmp_path):
    path = tmp_path/'extended.core'
    raw = bytearray(core_image())
    section = len(raw)
    raw.extend(bytes(64))
    struct.pack_into('<Q',raw,40,section)
    struct.pack_into('<H',raw,56,65535)
    struct.pack_into('<H',raw,58,64)
    struct.pack_into('<I',raw,section+44,2)
    path.write_bytes(raw)
    assert len(inspect_core(path,{})['segments']) == 2
    # Overlapping dump segments cannot silently establish one observed byte sequence.
    struct.pack_into('<I',raw,64+56,1)
    struct.pack_into('<H',raw,56,3)
    raw[176:232] = raw[120:176]
    path.write_bytes(raw)
    read = inspect_core(path,{'memory_reads':[{'address':'0x7000','bytes':8}]})['memory_reads'][0]
    assert not read['complete'] and read['chunks'][0]['status'] == 'ambiguous'
    assert read['chunks'][0].get('base64') is None
    # Note ownership is exact, not a lossy display-name match.
    path.write_bytes(core_image(owner=b'CORE\0extra'))
    assert not inspect_core(path,{})['threads']


@pytest.mark.parametrize('mutation', ['short','wrong-kind','wrong-architecture','note-overrun','load-overrun','invalid-prstatus','non-linux'])
def test_recorded_core_rejects_incomplete_or_wrong_abi(tmp_path, mutation):
    data = bytearray(core_image())
    if mutation == 'short': data = data[:63]
    elif mutation == 'wrong-kind': struct.pack_into('<H',data,16,2)
    elif mutation == 'wrong-architecture': struct.pack_into('<H',data,18,3)
    elif mutation == 'note-overrun': struct.pack_into('<I',data,0x104,0xffffffff)
    elif mutation == 'load-overrun': struct.pack_into('<Q',data,64+56+32,len(data))
    elif mutation == 'invalid-prstatus': struct.pack_into('<I',data,0x104,16)
    elif mutation == 'non-linux': data[7] = 9
    path = tmp_path/'invalid.core'
    path.write_bytes(data)
    with pytest.raises(ValueError): inspect_core(path,{})


def test_recorded_core_normal_worker_records_and_portable_evidence(tmp_path):
    path = tmp_path/'original.core'
    original = core_image()
    path.write_bytes(original)
    app = create_app(tmp_path/'data')
    with TestClient(app,base_url='http://127.0.0.1:5217') as client:
        client.get('/')
        project = app.state.store.create_project('Recorded original')
        artifact = app.state.store.add_artifact(project['id'],path)
        job,result = run(client,project['id'],artifact['id'],'crash.recording',{'memory_reads':[{'address':'0x7000','bytes':16}]})
        assert result['threads'][0]['historical_pid'] == 5678
        records = client.get(f'/api/jobs/{job["id"]}/records/threads').json()
        assert records['total'] == 1
        record = client.get(f'/api/jobs/{job["id"]}/records/threads/{records["records"][0]["record_key"]}').json()
        assert record['artifact_sha256'] == artifact['sha256'] and record['record']['registers']
        bundle = client.get(f'/api/projects/{project["id"]}/evidence').json()
        imported = client.post('/api/evidence/import',json={'bundle':bundle,'name':'Recorded import'})
        assert imported.status_code == 200,imported.text
        imported_job = imported.json()['id_map'][job['id']]
        transferred = client.get(f'/api/jobs/{imported_job}/records/threads/{records["records"][0]["record_key"]}').json()
        assert transferred['record'] == record['record']
        assert path.read_bytes() == original
