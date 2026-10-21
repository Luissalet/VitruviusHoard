"""Capture summary against a capture written byte by byte here and parsed independently by dpkt.

The summary operation aggregates what the decoder reports for every packet. The expectations below
come from dpkt reading the same bytes: addresses and ports, DNS questions and answers, TLS server
names from ClientHello extensions and HTTP request URIs. Nothing is captured or sent.
"""
import datetime
from decimal import Decimal
import io
import socket
import struct

import pytest

from test_pcap_oracle import (ETHERNET, Lab, dns_query, dns_response, eth, ipv4, ipv6, lab, pcap_file, stamp, tcp,  # noqa: F401
                              udp)
from theseus.packets import engine

dpkt = pytest.importorskip('dpkt')
pytestmark = pytest.mark.skipif(not engine(), reason='Requires installed free TShark')

A, DNS, WEB, TLS_HOST = '192.0.2.1', '192.0.2.53', '198.51.100.80', '198.51.100.43'
V6, V6DNS = '2001:db8::1', '2001:db8::53'


def client_hello(server_name):
    name = server_name.encode()
    sni = struct.pack('!HBH', len(name) + 3, 0, len(name)) + name
    extensions = struct.pack('!HH', 0, len(sni)) + sni
    body = b'\x03\x03' + bytes(range(32)) + b'\x00' + struct.pack('!HH', 2, 0x1301) + b'\x01\x00' + struct.pack('!H', len(extensions)) + extensions
    handshake = b'\x01' + len(body).to_bytes(3, 'big') + body
    return b'\x16\x03\x01' + struct.pack('!H', len(handshake)) + handshake


def http_get(uri):
    return f'GET {uri} HTTP/1.1\r\nHost: web.gauge.fixture\r\nUser-Agent: oracle\r\n\r\n'.encode()


def labels(name):
    return b''.join(bytes([len(part)]) + part.encode() for part in name.split('.')) + b'\0'


def dns_aaaa_response(name, address):
    question = labels(name) + struct.pack('!HH', 28, 1)
    answer = b'\xc0\x0c' + struct.pack('!HHIH', 28, 1, 60, 16) + socket.inet_pton(socket.AF_INET6, address)
    return struct.pack('!HHHHHH', 0x5555, 0x8180, 1, 1, 0, 0) + question + answer


def dns_answer_without_question(address):
    # QDCOUNT 0: the answer cannot be tied to any question in this message
    answer = labels('orphan.gauge.fixture') + struct.pack('!HHIH', 1, 1, 60, 4) + socket.inet_aton(address)
    return struct.pack('!HHHHHH', 0x6666, 0x8180, 0, 1, 0, 0) + answer


def frames():
    return [
        eth(ipv4(A, DNS, 17, udp(A, DNS, 50000, 53, dns_query('www.gauge.fixture', 1)))),
        eth(ipv4(DNS, A, 17, udp(DNS, A, 53, 50000, dns_response()))),
        eth(ipv6(V6, V6DNS, 17, udp(V6, V6DNS, 41000, 53, dns_query('six.gauge.fixture', 28))), 0x86dd),
        eth(ipv6(V6DNS, V6, 17, udp(V6DNS, V6, 53, 41000, dns_aaaa_response('six.gauge.fixture', '2001:db8::99'))), 0x86dd),
        eth(ipv4(DNS, A, 17, udp(DNS, A, 53, 50001, dns_answer_without_question('203.0.113.9')))),
        eth(ipv4(A, TLS_HOST, 6, tcp(A, TLS_HOST, 40001, 443, 1, 0, 0x02))),
        eth(ipv4(A, TLS_HOST, 6, tcp(A, TLS_HOST, 40001, 443, 2, 1, 0x18, client_hello('tls.gauge.fixture')))),
        eth(ipv4(A, TLS_HOST, 6, tcp(A, TLS_HOST, 40002, 443, 2, 1, 0x18, client_hello('tls.gauge.fixture')))),
        eth(ipv4(A, TLS_HOST, 6, tcp(A, TLS_HOST, 40003, 443, 2, 1, 0x18, client_hello('other.gauge.fixture')))),
        eth(ipv4(A, WEB, 6, tcp(A, WEB, 40010, 80, 1, 1, 0x18, http_get('/search?q=private-term&page=2')))),
        eth(ipv4(A, WEB, 6, tcp(A, WEB, 40011, 80, 1, 1, 0x18, http_get('/index.html')))),
        eth(ipv4(A, WEB, 6, tcp(A, WEB, 40012, 80, 1, 1, 0x18, http_get('/index.html')))),
        eth(ipv4(A, DNS, 17, udp(A, DNS, 7000, 7001, b'plain datagram'))),
    ]


RECORDS = [(*stamp(index), frame, len(frame)) for index, frame in enumerate(frames())]
CAPTURE = pcap_file(RECORDS)


def address(raw):
    return socket.inet_ntop(socket.AF_INET6 if len(raw) == 16 else socket.AF_INET, raw)


def server_name(payload):
    record = dpkt.ssl.TLS(payload).records[0]
    hello = dpkt.ssl.TLSHandshake(record.data).data
    for kind, data in hello.extensions:
        if kind == 0:
            length = struct.unpack('!H', data[3:5])[0]
            return data[5:5 + length].decode()
    return None


def oracle():
    """The summary as dpkt reads the capture: (facts, endpoints, dns, sni, uris, redactions, unattributed, protocols)."""
    endpoints, dns, sni, uris, protocols = {}, {}, set(), [], {}
    redacted, unattributed, unattributed_packets, times = 0, set(), 0, []
    for timestamp, data in dpkt.pcap.Reader(io.BytesIO(CAPTURE)):
        times.append(Decimal(str(timestamp)))
        frame = dpkt.ethernet.Ethernet(data)
        network = frame.data
        seen = {'ip' if isinstance(network, dpkt.ip.IP) else 'ipv6'}
        transport = network.data
        kind = 'tcp' if isinstance(transport, dpkt.tcp.TCP) else 'udp'
        seen.add(kind)
        for host, port in ((address(network.src), transport.sport), (address(network.dst), transport.dport)):
            endpoints[(host, port)] = endpoints.get((host, port), 0) + 1
        if kind == 'udp' and 53 in (transport.sport, transport.dport):
            seen.add('dns')
            message = dpkt.dns.DNS(transport.data)
            names = [question.name for question in message.qd]
            answers = [address(answer.rdata) for answer in message.an if answer.type in (dpkt.dns.DNS_A, dpkt.dns.DNS_AAAA)]
            for name in names:
                dns.setdefault(name, [])
            if names and message.qr == dpkt.dns.DNS_R:
                dns[names[0]].extend(answer for answer in answers if answer not in dns[names[0]])
            elif not names and answers:
                unattributed_packets += 1
                unattributed.update(answers)
        if kind == 'tcp' and transport.dport == 443 and transport.data:
            seen.add('tls')
            sni.add(server_name(transport.data))
        if kind == 'tcp' and transport.dport == 80 and transport.data:
            seen.add('http')
            uri = dpkt.http.Request(transport.data).uri
            if '?' in uri:
                uri, redacted = uri.split('?', 1)[0] + '?<redacted>', redacted + 1
            uris.append(uri)
        for name in seen:
            protocols[name] = protocols.get(name, 0) + 1
    return dict(times=times, endpoints=endpoints, dns=dns, sni=sni, uris=uris, redacted=redacted,
                unattributed=unattributed, unattributed_packets=unattributed_packets, protocols=protocols)


TRUTH = oracle()


def iso(seconds):
    whole = int(seconds)
    fraction = format(seconds - whole, 'f').partition('.')[2].rstrip('0')
    return datetime.datetime.fromtimestamp(whole, datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%S') + ('.' + fraction if fraction else '') + 'Z'


@pytest.fixture(scope='module')
def summary(lab):
    return lab.run('summary.pcap', 'capture.summary', content=CAPTURE)


def test_capture_facts_match_the_written_file(summary):
    assert summary['packet_count'] == len(RECORDS) == 13
    assert summary['encapsulation'] == 'ether'  # the wiretap short name of link type 1, as capinfos -M reports it
    assert 'pcap' in summary['file_type'].lower()
    assert summary['snapshot_length'] == 65535
    assert summary['capture_start'] == iso(min(TRUTH['times']))
    assert summary['capture_end'] == iso(max(TRUTH['times']))
    assert summary['capture_duration_seconds'] == pytest.approx(float(max(TRUTH['times']) - min(TRUTH['times'])), abs=1e-6)
    assert summary['coverage'] == 'complete'


def test_endpoints_count_each_packet_at_its_source_and_destination(summary):
    got = {(row['address'], row['port']): row['packet_count'] for row in summary['endpoints']}
    assert got == TRUTH['endpoints']
    assert summary['endpoint_count'] == len(TRUTH['endpoints'])
    counts = [row['packet_count'] for row in summary['endpoints']]
    assert counts == sorted(counts, reverse=True)
    assert sum(counts) == 2 * len(RECORDS)


def test_dns_answers_belong_to_their_question_and_cnames_are_not_addresses(summary):
    got = {row['query']: row['response_addresses'] for row in summary['dns_queries']}
    assert got == TRUTH['dns']
    assert got['www.gauge.fixture'] == ['192.0.2.10', '192.0.2.11']
    assert got['six.gauge.fixture'] == ['2001:db8::99']
    assert all(row['response_address_count'] == len(row['response_addresses']) for row in summary['dns_queries'])
    assert summary['dns_query_count'] == len(TRUTH['dns'])


def test_answers_without_a_question_are_reported_apart(summary):
    assert summary['unattributed_dns_addresses'] == sorted(TRUTH['unattributed']) == ['203.0.113.9']
    assert summary['unattributed_dns_address_count'] == 1
    assert summary['unattributed_dns_packet_count'] == TRUTH['unattributed_packets'] == 1
    assert '203.0.113.9' not in {value for row in summary['dns_queries'] for value in row['response_addresses']}


def test_tls_server_names_are_the_distinct_clienthello_values(summary):
    assert summary['tls_sni_values'] == sorted(TRUTH['sni']) == ['other.gauge.fixture', 'tls.gauge.fixture']
    assert summary['tls_sni_count'] == 2


def test_http_uris_keep_the_path_and_never_the_query(summary):
    assert summary['http_request_uris'] == sorted(set(TRUTH['uris'])) == ['/index.html', '/search?<redacted>']
    assert summary['http_request_uri_count'] == 2
    assert summary['http_uri_redaction_count'] == TRUTH['redacted'] == 1
    assert 'private-term' not in str(summary)


def test_protocol_distribution_counts_packets_per_protocol(summary):
    got = {row['protocol']: row['packet_count'] for row in summary['protocol_distribution']}
    for name, count in TRUTH['protocols'].items():
        assert got.get(name) == count, (name, got)
    assert got['eth'] == len(RECORDS)
    assert summary['protocol_count'] == len(got)


def test_max_items_clips_every_list_but_keeps_the_totals(lab, summary):
    clipped = lab.run('summary.pcap', 'capture.summary', {'max_items': 1}, content=CAPTURE)
    for name, total in [('endpoints', 'endpoint_count'), ('dns_queries', 'dns_query_count'), ('tls_sni_values', 'tls_sni_count'),
                        ('protocol_distribution', 'protocol_count'), ('http_request_uris', 'http_request_uri_count')]:
        assert len(clipped[name]) == 1 and clipped[name][0] == summary[name][0], name
        assert clipped[total] == summary[total], total
    assert clipped['coverage'] == 'partial'


def test_summary_of_an_empty_capture_has_no_times_and_is_complete(lab):
    empty = lab.run('empty-summary.pcap', 'capture.summary', content=pcap_file([]))
    assert (empty['packet_count'], empty['capture_start'], empty['capture_end'], empty['capture_duration_seconds']) == (0, None, None, None)
    assert empty['endpoints'] == [] and empty['coverage'] == 'complete'


def test_bytes_that_are_not_a_capture_fail(lab):
    job = lab.job('not-a-capture.bin', b'MZ' + bytes(100), 'capture.summary')
    assert job['state'] == 'failed'
    assert 'Not a PCAP or PCAPNG capture' in str(job['result'])
