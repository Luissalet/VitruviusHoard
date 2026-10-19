import hashlib
import socket
import struct

from fastapi.testclient import TestClient
import pytest

from test_portfolio import run
from theseus.api import create_app
from theseus.packets import engine


def dns_frame():
    name = b'\x05gauge\x07fixture\0'
    question = name+struct.pack('!HH', 1, 1)
    answers = b''.join(b'\xc0\x0c'+struct.pack('!HHIH', 1, 1, 60, 4)+socket.inet_aton(ip)
                       for ip in ('192.0.2.10', '192.0.2.11'))
    dns = struct.pack('!HHHHHH', 0x1234, 0x8180, 1, 2, 0, 0)+question+answers
    udp = struct.pack('!HHHH', 53, 50000, len(dns)+8, 0)+dns
    ip = struct.pack('!BBHHHBBH4s4s', 0x45, 0, len(udp)+20, 1, 0, 64, 17, 0,
                     socket.inet_aton('192.0.2.53'), socket.inet_aton('192.0.2.1'))
    return bytes.fromhex('00112233445566778899aabb0800')+ip+udp


def capture_bytes(pcapng=False):
    frame = dns_frame()
    if not pcapng:
        return struct.pack('<IHHIIII', 0xa1b2c3d4, 2, 4, 0, 0, 65535, 1)+struct.pack('<IIII', 1, 0, len(frame), len(frame))+frame
    def block(kind, payload):
        return struct.pack('<II', kind, len(payload)+12)+payload+struct.pack('<I', len(payload)+12)
    section = block(0x0a0d0d0a, struct.pack('<IHHq', 0x1a2b3c4d, 1, 0, -1))
    interface = block(1, struct.pack('<HHI', 1, 0, 65535))
    packet = struct.pack('<IIIII', 0, 0, 1000000, len(frame), len(frame))+frame+b'\0'*((-len(frame))%4)
    return section+interface+block(6, packet)


@pytest.mark.skipif(not engine(), reason='Requires installed free TShark')
@pytest.mark.parametrize('pcapng', [False, True])
def test_actual_packet_fields_capture_identity_paging_and_negative_filter(tmp_path, pcapng):
    path = tmp_path/('original.pcapng' if pcapng else 'original.pcap')
    original = capture_bytes(pcapng)
    path.write_bytes(original)
    with TestClient(create_app(tmp_path/'data'), base_url='http://127.0.0.1:5217') as client:
        client.get('/')
        store = client.app.state.store
        pid = store.create_project('Original offline capture')['id']
        artifact = store.add_artifact(pid, path)
        job, observed = run(client, pid, artifact['id'], 'capture.packets', {
            'display_filter': 'dns.flags.response == 1', 'fields': ['frame.number', 'ip.src', 'dns.qry.name', 'dns.a'], 'two_pass': True})
        assert job['result']['artifact_sha256'] == hashlib.sha256(original).hexdigest()
        layers = observed['packets'][0]['_source']['layers']
        assert layers['dns.qry.name'] == ['gauge.fixture']
        assert layers['dns.a'] == ['192.0.2.10', '192.0.2.11']
        assert observed['coverage']['decoded_matching_records'] == 1
        assert observed['capture_metadata']['exit_code'] == 0
        assert observed['snapshot_sha256'] == artifact['sha256']
        assert not list((store.directory/'analyses').rglob('packet-input.bin'))
        _, absent = run(client, pid, artifact['id'], 'capture.packets', {'display_filter': 'tcp'})
        assert absent['packets'] == [] and absent['coverage']['decoded_matching_records'] == 0
        _, paged = run(client, pid, artifact['id'], 'capture.packets', {'limit': 0, 'raw': True})
        assert paged['packets'] == [] and paged['coverage']['has_more']
        _, fields = run(client, pid, artifact['id'], 'capture.fields', {'protocol': 'dns', 'match': 'dns.a'})
        assert any(row['field'] == 'dns.a' for row in fields['fields'])
        _, protocols = run(client, pid, artifact['id'], 'capture.fields', {'kind': 'protocols', 'match': 'Domain Name'})
        assert any(row['protocol'] == 'dns' for row in protocols['fields'])
        assert path.read_bytes() == original
