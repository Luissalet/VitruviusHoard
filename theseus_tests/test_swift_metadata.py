import hashlib
import struct

from fastapi.testclient import TestClient
import pytest

from swift_fixture import BASE,swift_image,swift_fat
from test_portfolio import run
from theseus.api import create_app


@pytest.mark.parametrize('architecture',['arm64','x86_64'])
@pytest.mark.parametrize('indirect',[False,True])
def test_original_swift_conformance_witness_vtable_offsets_and_historical_transfer(tmp_path,architecture,indirect):
    original=swift_image(architecture,indirect=indirect);target=tmp_path/'swift-metadata.dylib';target.write_bytes(original)
    with TestClient(create_app(tmp_path/'data'),base_url='http://127.0.0.1:5217') as client:
        client.get('/');store=client.app.state.store;pid=store.create_project('Original Swift ABI fixture')['id']
        artifact=store.add_artifact(pid,target)
        job,result=run(client,pid,artifact['id'],'apple.dispatch',{'architecture':architecture})
        row=result['swift_conformances'][0]
        assert row['type_name']=='Gaugeñ' and row['protocol_name']=='MeasureRule'
        assert row['location']=={'address':hex(BASE+0x1100),'file_offset':0x1100}
        assert row['witness_table']=={'address':hex(BASE+0x1500),'file_offset':0x1500}
        assert row['decode']['status']=='decoded'
        slots=result['swift_dispatch_slots'];assert len(slots)==4
        for kind,indices,offsets in [('witness_table',[1,2],[0x1508,0x1510]),('class_vtable',[16,17],[0x1334,0x133c])]:
            selected=[r for r in slots if r['table_kind']==kind]
            assert [r['slot_index'] for r in selected]==indices
            assert [r['location']['file_offset'] for r in selected]==offsets
            assert [r['implementation_address'] for r in selected]==[hex(BASE+0x800),hex(BASE+0x820)]
            assert all(r['decode']['status']=='decoded' for r in selected)
        # Independent raw layout checks; slot indices are metadata words, not method ordinals.
        assert struct.unpack_from('<Q',original,0x1508)[0]==BASE+0x800
        assert 0x1338+struct.unpack_from('<i',original,0x1338)[0]==0x800
        assert any(r['displacement']<0 for r in result['relative_pointers'])
        if indirect: assert any(r['indirect'] for r in result['relative_pointers'])
        record=client.get(f'/api/jobs/{job["id"]}/records/swift_conformances/0').json()
        assert record['record']==row and record['sources']
        store.add_finding(pid,artifact['id'],'swift_conformances/0','Recorded Gaugeñ conformance','')
        imported=client.app.state.evidence.load(client.app.state.evidence.export(pid))
        moved=client.get(f'/api/jobs/{imported["id_map"][job["id"]]}/records/swift_conformances/0').json()
        assert moved['record']==row
        assert target.read_bytes()==original and artifact['sha256']==hashlib.sha256(original).hexdigest()


@pytest.mark.parametrize('change',['async_slots','generic','conditional','unmapped','bad_header','bad_relative'])
def test_swift_unsupported_metadata_stays_partial_without_invented_targets(tmp_path,change):
    target=tmp_path/'partial.dylib';target.write_bytes(swift_image(**{change:True}))
    with TestClient(create_app(tmp_path/'data'),base_url='http://127.0.0.1:5217') as client:
        client.get('/');store=client.app.state.store;pid=store.create_project('Partial Swift metadata')['id']
        artifact=store.add_artifact(pid,target)
        _,result=run(client,pid,artifact['id'],'apple.dispatch')
        if change in {'async_slots','unmapped'}:
            slots=result['swift_dispatch_slots']
            for kind in ['witness_table','class_vtable']:
                row=next(r for r in slots if r['table_kind']==kind)
                assert row['decode']['status']=='partial' and row['implementation_address'] is None
        elif change=='bad_relative':
            assert not result['swift_conformances']
        else:
            assert result['swift_conformances'][0]['decode']['status']=='partial'


@pytest.mark.parametrize('wide,little',[(False,False),(False,True),(True,False),(True,True)])
def test_swift_fat_selected_slice_keeps_container_offsets(tmp_path,wide,little):
    target=tmp_path/'two-slices.dylib';target.write_bytes(swift_fat(wide=wide,little=little))
    with TestClient(create_app(tmp_path/'data'),base_url='http://127.0.0.1:5217') as client:
        client.get('/');store=client.app.state.store;pid=store.create_project('Swift container locations')['id']
        artifact=store.add_artifact(pid,target)
        for architecture,at in [('arm64',4096),('x86_64',16384)]:
            _,result=run(client,pid,artifact['id'],'apple.dispatch',{'architecture':architecture})
            row=result['swift_conformances'][0]
            assert row['location']['file_offset']==at+0x1100
            assert row['witness_table']['file_offset']==at+0x1500
            assert row['evidence'][0]['artifact_sha256']==artifact['sha256']
            assert result['swift_dispatch_slots'][0]['location']['file_offset']==at+0x1508


@pytest.mark.parametrize('bad_string',[False,True])
def test_invalid_swift_name_or_table_bounds_are_explicit_decode_failures(tmp_path,bad_string):
    raw=bytearray(swift_image())
    if bad_string: raw[0x1620]=0xff
    else: struct.pack_into('<I',raw,0x1330,21)
    target=tmp_path/'invalid-metadata.dylib';target.write_bytes(raw)
    with TestClient(create_app(tmp_path/'data'),base_url='http://127.0.0.1:5217') as client:
        client.get('/');store=client.app.state.store;pid=store.create_project('Invalid Swift layout')['id']
        artifact=store.add_artifact(pid,target)
        _,result=run(client,pid,artifact['id'],'apple.dispatch')
        assert not any(r['table_kind']=='class_vtable' for r in result['swift_dispatch_slots'])
        if bad_string: assert not result['swift_conformances']
