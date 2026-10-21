"""Packet-capture reader against captures written byte by byte here and the dpkt parser.

Every capture is assembled in the test (classic pcap in both byte orders and both timestamp
resolutions, pcapng with several interfaces); nothing is captured or sent. The expectations come
from the values written into the bytes and from dpkt, which parses the same bytes independently.
"""
import calendar
from decimal import Decimal
from fractions import Fraction
import datetime
import hashlib
import io
import json
import os
import socket
import struct
import subprocess
import time

from fastapi.testclient import TestClient
import pytest

from test_native_analysis import wait
from theseus.api import create_app
from theseus.packets import engine

dpkt = pytest.importorskip('dpkt')
pytestmark = pytest.mark.skipif(not engine(), reason='Requires installed free TShark')

MAC_A, MAC_B = bytes.fromhex('001122334455'), bytes.fromhex('66778899aabb')
ETHERNET, RAW_IP = 1, 101
NS = 1_000_000_000


def cksum(data):
    data += b'\0' * (len(data) % 2)
    total = sum(struct.unpack('!%dH' % (len(data) // 2), data))
    while total >> 16:
        total = (total & 0xffff) + (total >> 16)
    return ~total & 0xffff


def eth(payload, ethertype=0x0800, vlan=None):
    tag = b'' if vlan is None else struct.pack('!HH', 0x8100, vlan)
    return MAC_A + MAC_B + tag + struct.pack('!H', ethertype) + payload


def ipv4(src, dst, proto, payload, ident=1, frag=0, ttl=64, bad=False):
    head = struct.pack('!BBHHHBBH4s4s', 0x45, 0x10, 20 + len(payload), ident, frag, ttl, proto, 0,
                       socket.inet_aton(src), socket.inet_aton(dst))
    check = cksum(head) ^ (0x00ff if bad else 0)
    return head[:10] + struct.pack('!H', check) + head[12:] + payload


def ipv6(src, dst, proto, payload):
    return struct.pack('!IHBB16s16s', 0x6 << 28 | 0x28 << 20 | 0x12345, len(payload), proto, 63,
                       socket.inet_pton(socket.AF_INET6, src), socket.inet_pton(socket.AF_INET6, dst)) + payload


def pseudo(src, dst, proto, length):
    if ':' in src:
        return socket.inet_pton(socket.AF_INET6, src) + socket.inet_pton(socket.AF_INET6, dst) + struct.pack('!IBBBB', length, 0, 0, 0, proto)
    return socket.inet_aton(src) + socket.inet_aton(dst) + struct.pack('!BBH', 0, proto, length)


def udp(src, dst, sport, dport, data):
    head = struct.pack('!HHHH', sport, dport, 8 + len(data), 0)
    check = cksum(pseudo(src, dst, 17, 8 + len(data)) + head + data) or 0xffff
    return head[:6] + struct.pack('!H', check) + data


def tcp(src, dst, sport, dport, seq, ack, flags, data=b'', options=b'', window=8192):
    head = struct.pack('!HHIIBBHHH', sport, dport, seq, ack, (20 + len(options)) // 4 << 4, flags, window, 0, 0) + options
    check = cksum(pseudo(src, dst, 6, len(head) + len(data)) + head + data)
    return head[:16] + struct.pack('!H', check) + head[18:] + data


def icmp_echo(kind, ident, seq, data):
    head = struct.pack('!BBHHH', kind, 0, 0, ident, seq)
    return head[:2] + struct.pack('!H', cksum(head + data)) + head[4:] + data


def dns_response():
    # www.gauge.fixture CNAME edge.gauge.fixture (name and rdata compressed), then two A records
    question = b'\x03www\x05gauge\x07fixture\0' + struct.pack('!HH', 1, 1)
    cname = b'\xc0\x0c' + struct.pack('!HHIH', 5, 1, 300, 7) + b'\x04edge\xc0\x10'
    owner = b'\xc0' + bytes([12 + len(question) + 12])
    answers = b''.join(owner + struct.pack('!HHIH', 1, 1, 60, 4) + socket.inet_aton(ip) for ip in ('192.0.2.10', '192.0.2.11'))
    return struct.pack('!HHHHHH', 0x1234, 0x8180, 1, 3, 0, 0) + question + cname + answers


def dns_query(name, qtype, ident=0x4321):
    labels = b''.join(bytes([len(part)]) + part.encode() for part in name.split('.')) + b'\0'
    return struct.pack('!HHHHHH', ident, 0x0100, 1, 0, 0, 0) + labels + struct.pack('!HH', qtype, 1)


def frames():
    """Fourteen Ethernet frames: (name, bytes, captured length or None)."""
    a, b, c = '192.0.2.1', '192.0.2.53', '198.51.100.7'
    syn = bytes.fromhex('0204 05b4 0101 0402 0103 0307'.replace(' ', ''))
    tsopt = bytes.fromhex('0101 080a 00010203 0a0b0c0d'.replace(' ', ''))
    datagram = udp(a, b, 9000, 9001, bytes(range(24)))
    response = eth(ipv4(b, a, 17, udp(b, a, 53, 50000, dns_response()), ident=2))
    return [
        ('dns-query', eth(ipv4(a, b, 17, udp(a, b, 50000, 53, dns_query('www.gauge.fixture', 1)))), None),
        ('dns-response', response, None),
        ('tcp-syn', eth(ipv4(a, c, 6, tcp(a, c, 40000, 4444, 1000, 0, 0x02, options=syn), ident=3)), None),
        ('tcp-synack', eth(ipv4(c, a, 6, tcp(c, a, 4444, 40000, 7000, 1001, 0x12, options=syn), ident=4)), None),
        ('tcp-data', eth(ipv4(a, c, 6, tcp(a, c, 40000, 4444, 1001, 7001, 0x18, b'gauge-data', tsopt), ident=5)), None),
        ('icmp-request', eth(ipv4(a, c, 1, icmp_echo(8, 0x0bad, 7, b'abcdefgh'), ident=6)), None),
        ('icmp-reply', eth(ipv4(c, a, 1, icmp_echo(0, 0x0bad, 7, b'abcdefgh'), ident=7)), None),
        ('fragment-first', eth(ipv4(a, c, 17, datagram[:16], ident=0x4242, frag=0x2000)), None),
        ('fragment-last', eth(ipv4(a, c, 17, datagram[16:], ident=0x4242, frag=2)), None),
        ('ipv6-dns-query', eth(ipv6('2001:db8::1', '2001:db8::53', 17, udp('2001:db8::1', '2001:db8::53', 41000, 53, dns_query('gauge.fixture', 28))), 0x86dd), None),
        ('vlan-udp', eth(ipv4(a, b, 17, udp(a, b, 5000, 5001, b'tagged'), ident=8), vlan=5 << 13 | 100), None),
        ('bad-checksum', eth(ipv4(a, b, 17, udp(a, b, 7777, 7778, b'damaged'), ident=9, bad=True)), None),
        ('truncated', response, 14 + 20 + 8 + 12 + 23 + 6),
        ('ipv6-tcp-fin', eth(ipv6('2001:db8::1', '2001:db8::53', 6, tcp('2001:db8::1', '2001:db8::53', 41001, 4445, 5000, 6000, 0x11)), 0x86dd), None),
    ]


def stamp(index):
    return 1_700_000_000 + index * 3, 100_123_456 + index * 7_000_001


def pad4(data):
    return data + b'\0' * (-len(data) % 4)


def pcap_file(records, endian='<', nano=False, linktype=ETHERNET, snaplen=65535):
    """records: (second, nanosecond, bytes, original length)."""
    out = struct.pack(endian + 'IHHiIII', 0xa1b23c4d if nano else 0xa1b2c3d4, 2, 4, 0, 0, snaplen, linktype)
    for sec, nsec, data, length in records:
        out += struct.pack(endian + 'IIII', sec, nsec if nano else nsec // 1000, len(data), length) + data
    return out


def option(code, value, endian):
    return struct.pack(endian + 'HH', code, len(value)) + pad4(value)


def block(kind, body, endian):
    body = pad4(body)
    return struct.pack(endian + 'II', kind, len(body) + 12) + body + struct.pack(endian + 'I', len(body) + 12)


def ticks_per_second(code):
    return 2 ** (code & 0x7f) if code & 0x80 else 10 ** code


def pcapng_file(interfaces, records, endian='<'):
    """interfaces: (link type, if_tsresol code, name); records: (interface, second, nanosecond, data, original length, comment)."""
    end = option(0, b'', endian)
    out = block(0x0a0d0d0a, struct.pack(endian + 'IHHq', 0x1a2b3c4d, 1, 0, -1) + option(4, b'pcap-oracle', endian) + end, endian)
    for linktype, code, name in interfaces:
        out += block(1, struct.pack(endian + 'HHI', linktype, 0, 65535) + option(2, name.encode(), endian) + option(9, bytes([code]), endian) + end, endian)
    for item in records:
        if isinstance(item, bytes):  # a ready-made block (statistics, name resolution, unknown type)
            out += item
            continue
        index, sec, nsec, data, length, comment = item
        rate = ticks_per_second(interfaces[index][1])
        ticks = sec * rate + nsec * rate // NS
        options = option(1, comment.encode(), endian) + end if comment else b''
        out += block(6, struct.pack(endian + 'IIIII', index, ticks >> 32, ticks & 0xffffffff, len(data), length) + pad4(data) + options, endian)
    return out


IFACES = [(ETHERNET, 6, 'eth0'), (RAW_IP, 9, 'raw0'), (ETHERNET, 3, 'eth-ms'), (ETHERNET, 0x8a, 'eth-binary')]
PLACEMENT = [0, 0, 2, 2, 0, 1, 1, 0, 0, 3, 0, 1, 0, 3]
COMMENTS = {0: 'first packet', 12: 'cut by snaplen'}
NAMES = ['le-us.pcap', 'be-us.pcap', 'le-ns.pcap', 'be-ns.pcap', 'raw-ipv4.pcap', 'le.pcapng', 'be.pcapng']


def record(iface, rate, sec, nsec, data, length, linktype, name=None, comment=None):
    return dict(iface=iface, time=Fraction(sec * rate + nsec * rate // NS, rate), data=data, caplen=len(data),
                origlen=length, linktype=linktype, ifname=name, comment=comment)


def captures():
    """name -> (file bytes, what was written into it)."""
    base = frames()
    full = [frame for _, frame, _ in base]
    kept = [frame[:cut] if cut else frame for _, frame, cut in base]
    ether = [(*stamp(i), kept[i], len(full[i])) for i in range(len(base))]
    ipv4_only = [(s, n, d[14:], length - 14) for (s, n, d, length), frame in zip(ether, full) if frame[12:14] == b'\x08\x00']
    out = {}
    for name, endian, nano in [('le-us.pcap', '<', False), ('be-us.pcap', '>', False), ('le-ns.pcap', '<', True), ('be-ns.pcap', '>', True)]:
        rate = NS if nano else 10 ** 6
        out[name] = (pcap_file(ether, endian, nano), [record(0, rate, *r[:2], r[2], r[3], ETHERNET) for r in ether])
    out['raw-ipv4.pcap'] = (pcap_file(ipv4_only, linktype=RAW_IP), [record(0, 10 ** 6, *r[:2], r[2], r[3], RAW_IP) for r in ipv4_only])
    for name, endian in [('le.pcapng', '<'), ('be.pcapng', '>')]:
        written, truth = [], []
        for i, index in enumerate(PLACEMENT):
            sec, nsec = stamp(i)
            if index == 3:  # 2**-10 s ticks: keep only quarter seconds, which that clock stores exactly
                nsec = i % 4 * 250_000_000
            skip = 14 if index == 1 else 0
            data, length, comment = kept[i][skip:], len(full[i]) - skip, COMMENTS.get(i)
            written.append((index, sec, nsec, data, length, comment))
            truth.append(record(index, ticks_per_second(IFACES[index][1]), sec, nsec, data, length, IFACES[index][0], IFACES[index][2], comment))
        out[name] = (pcapng_file(IFACES, written, endian), truth)
    return out


CAPTURES = captures()


def mac(raw):
    return ':'.join('%02x' % byte for byte in raw)


def read_classic(content):
    """The classic capture as dpkt reads it (record headers through dpkt's own header classes)."""
    little = content[:4] in (struct.pack('<I', 0xa1b2c3d4), struct.pack('<I', 0xa1b23c4d))
    rate = NS if content[:4] in (struct.pack('<I', 0xa1b23c4d), struct.pack('>I', 0xa1b23c4d)) else 10 ** 6
    reader = dpkt.pcap.Reader(io.BytesIO(content))
    header, offset, out = (dpkt.pcap.LEPktHdr if little else dpkt.pcap.PktHdr), 24, []
    for _, data in reader:
        head = header(content[offset:offset + 16])
        out.append(dict(iface=0, time=Fraction(head.tv_sec * rate + head.tv_usec, rate), data=data, caplen=head.caplen,
                        origlen=head.len, linktype=reader.datalink(), ifname=None, comment=None))
        offset += 16 + head.caplen
    return out


def read_pcapng(content):
    little = content[8:12] == struct.pack('<I', 0x1a2b3c4d)
    idb_class, epb_class = ((dpkt.pcapng.InterfaceDescriptionBlockLE, dpkt.pcapng.EnhancedPacketBlockLE) if little
                            else (dpkt.pcapng.InterfaceDescriptionBlock, dpkt.pcapng.EnhancedPacketBlock))
    interfaces, out, offset = [], [], 0
    while offset < len(content):
        kind, length = struct.unpack('<II' if little else '>II', content[offset:offset + 8])
        body = content[offset:offset + length]
        if kind == 1:
            idb = idb_class(body)
            options = {opt.code: opt.data for opt in idb.opts}
            interfaces.append((idb.linktype, ticks_per_second(options[9][0]), options[2].decode()))
        elif kind == 6:
            epb = epb_class(body)
            linktype, rate, name = interfaces[epb.iface_id]
            comment = next((opt.data.decode() for opt in epb.opts if opt.code == 1), None)
            ticks = epb.ts_high << 32 | epb.ts_low
            out.append(dict(iface=epb.iface_id, time=Fraction(ticks, rate), data=epb.pkt_data, caplen=epb.caplen,
                            origlen=epb.pkt_len, linktype=linktype, ifname=name, comment=comment))
        offset += length
    return out


def read_capture(content):
    return read_pcapng(content) if content[:4] == b'\x0a\x0d\x0d\x0a' else read_classic(content)


def dns_question(body):
    labels, at = [], 12
    while body[at]:
        labels.append(body[at + 1:at + 1 + body[at]].decode())
        at += 1 + body[at]
    return '.'.join(labels), struct.unpack('!H', body[at + 1:at + 3])[0]


def dns_facts(body, x):
    ident, flags, queries, answers = struct.unpack('!HHHH', body[:8])
    x.update({'dns.id': [ident], 'dns.flags': [flags], 'dns.flags.response': [bool(flags >> 15)],
              'dns.count.queries': [queries], 'dns.count.answers': [answers]})
    if flags >> 15:  # the dissector shows the response code of responses only
        x['dns.flags.rcode'] = [flags & 15]
    try:
        message = dpkt.dns.DNS(body)
    except dpkt.UnpackError:  # cut short mid-record: only the header and the question are present, nothing more is known
        name, qtype = dns_question(body)
        x.update({'dns.qry.name': [name], 'dns.qry.type': [qtype]})
        return
    if message.qd:
        x.update({'dns.qry.name': [q.name for q in message.qd], 'dns.qry.type': [q.type for q in message.qd]})
    if message.an:
        x.update({'dns.resp.name': [a.name for a in message.an], 'dns.resp.type': [a.type for a in message.an],
                  'dns.resp.ttl': [a.ttl for a in message.an]})
        if any(a.type == 1 for a in message.an):
            x['dns.a'] = [socket.inet_ntoa(a.ip) for a in message.an if a.type == 1]
        if any(a.type == 5 for a in message.an):
            x['dns.cname'] = [a.cname for a in message.an if a.type == 5]


def parse_all(records):
    """Expected tshark field values of every record, derived from dpkt's parse of its bytes."""
    out, groups = [], {}
    for number, rec in enumerate(records, 1):
        data, x, stack = rec['data'], {}, []
        x.update({'frame.number': [number], 'frame.len': [rec['origlen']], 'frame.cap_len': [rec['caplen']],
                  'frame.encap_type': [{ETHERNET: 1, RAW_IP: 7}[rec['linktype']]],  # Wireshark's own encapsulation numbers
                  'frame.time_epoch': [rec['time']]})
        if rec['ifname'] is not None:
            x.update({'frame.interface_id': [rec['iface']], 'frame.interface_name': [rec['ifname']]})
        if rec['comment']:
            x['frame.comment'] = [rec['comment']]
        if rec['linktype'] == ETHERNET:
            ethernet = dpkt.ethernet.Ethernet(data)
            tags = getattr(ethernet, 'vlan_tags', ())  # dpkt only sets the attribute on tagged frames
            offset, l3 = 14 + 4 * len(tags), ethernet.data
            x.update({'eth.dst': [mac(ethernet.dst)], 'eth.src': [mac(ethernet.src)], 'eth.type': [ethernet.type]})
            stack = ['eth', 'ethertype']
            if tags:  # the type after the tag is the one dpkt chose the network-layer class by
                inner = dpkt.ethernet.ETH_TYPE_IP if isinstance(l3, dpkt.ip.IP) else dpkt.ethernet.ETH_TYPE_IP6
                x.update({'vlan.id': [tags[0].id], 'vlan.priority': [tags[0].pri], 'vlan.dei': [bool(tags[0].cfi)], 'vlan.etype': [inner]})
                stack += ['vlan', 'ethertype']
        else:
            offset, l3, stack = 0, (dpkt.ip.IP(data) if data[0] >> 4 == 4 else dpkt.ip6.IP6(data)), ['raw']
        if isinstance(l3, dpkt.ip.IP):
            x.update({'ip.src': [socket.inet_ntoa(l3.src)], 'ip.dst': [socket.inet_ntoa(l3.dst)], 'ip.proto': [l3.p], 'ip.ttl': [l3.ttl],
                      'ip.id': [l3.id], 'ip.len': [l3.len], 'ip.hdr_len': [l3.hl * 4], 'ip.flags.mf': [bool(l3.mf)],
                      'ip.frag_offset': [l3.offset], 'ip.checksum': [l3.sum]})
            payload, proto, stack = data[offset + l3.hl * 4:offset + l3.len], l3.p, stack + ['ip']
            if l3.mf or l3.offset:
                group = groups.setdefault((l3.src, l3.dst, l3.id, l3.p), [])
                group.append((l3.offset, payload))
                # the datagram is complete, and only then decoded, at its last fragment
                payload = None if l3.mf else b''.join(part for _, part in sorted(group))
                if payload is None:
                    stack.append('data')
        else:
            x.update({'ipv6.src': [socket.inet_ntop(socket.AF_INET6, l3.src)], 'ipv6.dst': [socket.inet_ntop(socket.AF_INET6, l3.dst)],
                      'ipv6.hlim': [l3.hlim], 'ipv6.nxt': [l3.nxt], 'ipv6.plen': [l3.plen], 'ipv6.flow': [l3.flow], 'ipv6.tclass': [l3.fc]})
            payload, proto, stack = data[offset + 40:offset + 40 + l3.plen], l3.nxt, stack + ['ipv6']
        body = b''
        if payload is not None and proto == 17:
            u = dpkt.udp.UDP(payload)
            x.update({'udp.srcport': [u.sport], 'udp.dstport': [u.dport], 'udp.length': [u.ulen], 'udp.checksum': [u.sum]})
            stack.append('udp')
            body = payload[8:u.ulen]
            if 53 in (u.sport, u.dport) and len(body) >= 12:
                dns_facts(body, x)
                stack.append('dns')
                body = b''
        elif payload is not None and proto == 6:
            t = dpkt.tcp.TCP(payload)
            options = dpkt.tcp.parse_opts(t.opts)
            body = payload[t.off * 4:]
            x.update({'tcp.srcport': [t.sport], 'tcp.dstport': [t.dport], 'tcp.seq_raw': [t.seq], 'tcp.ack_raw': [t.ack], 'tcp.flags': [t.flags],
                      'tcp.flags.syn': [bool(t.flags & 2)], 'tcp.flags.ack': [bool(t.flags & 16)], 'tcp.flags.push': [bool(t.flags & 8)],
                      'tcp.flags.fin': [bool(t.flags & 1)], 'tcp.flags.reset': [bool(t.flags & 4)], 'tcp.hdr_len': [t.off * 4],
                      'tcp.len': [len(body)], 'tcp.window_size_value': [t.win], 'tcp.checksum': [t.sum]})
            if options:
                x['tcp.option_kind'] = [kind for kind, _ in options]
            for kind, value in options:
                if kind == 2:
                    x['tcp.options.mss_val'] = [struct.unpack('!H', value)[0]]
                elif kind == 3:
                    x['tcp.options.wscale.shift'] = [value[0]]
                elif kind == 8:
                    x['tcp.options.timestamp.tsval'], x['tcp.options.timestamp.tsecr'] = [[v] for v in struct.unpack('!II', value)]
            stack.append('tcp')
        elif payload is not None and proto == 1:
            i = dpkt.icmp.ICMP(payload)
            x.update({'icmp.type': [i.type], 'icmp.code': [i.code], 'icmp.checksum': [i.sum], 'icmp.ident': [i.data.id], 'icmp.seq': [i.data.seq]})
            stack.append('icmp')
            body = payload[8:]
        if body:
            stack.append('data')
        x['frame.protocols'] = [':'.join(stack)]
        out.append(x)
    return out


KIND = {}
for _field in ('frame.number frame.len frame.cap_len frame.encap_type frame.interface_id eth.type vlan.id vlan.priority vlan.etype ip.proto '
               'ip.ttl ip.id ip.len ip.hdr_len ip.frag_offset ip.checksum ipv6.hlim ipv6.nxt ipv6.plen ipv6.flow ipv6.tclass udp.srcport '
               'udp.dstport udp.length udp.checksum tcp.srcport tcp.dstport tcp.seq_raw tcp.ack_raw tcp.flags tcp.hdr_len tcp.len '
               'tcp.window_size_value tcp.checksum tcp.option_kind tcp.options.mss_val tcp.options.timestamp.tsval tcp.options.timestamp.tsecr '
               'tcp.options.wscale.shift icmp.type icmp.code icmp.checksum icmp.ident icmp.seq dns.id dns.flags dns.flags.rcode '
               'dns.count.queries dns.count.answers dns.qry.type dns.resp.type dns.resp.ttl').split():
    KIND[_field] = 'i'
for _field in 'ip.flags.mf vlan.dei tcp.flags.syn tcp.flags.ack tcp.flags.push tcp.flags.fin tcp.flags.reset dns.flags.response'.split():
    KIND[_field] = 'b'
KIND['frame.time_epoch'] = 't'
FIELDS = sorted(set(KIND) | set('frame.interface_name frame.comment frame.protocols eth.src eth.dst ip.src ip.dst ipv6.src ipv6.dst '
                                'dns.qry.name dns.resp.name dns.a dns.cname'.split()))


def instant(text):
    if 'T' in text:  # the JSON tree prints ISO-8601 UTC, -e prints epoch seconds
        head, fraction = text.rstrip('Z').split('.')
        return Fraction(calendar.timegm(time.strptime(head, '%Y-%m-%dT%H:%M:%S'))) + Fraction(int(fraction), 10 ** len(fraction))
    return Fraction(Decimal(text))


def normal(field, values, tree=False):
    """Observed text values as python values. tshark prints numbers (hex for flag-like fields), booleans (1 or True) and times as text."""
    kind = KIND.get(field, 's')
    if kind == 'i':
        out = [int(v, 0) if v[:2].lower() == '0x' else int(v) for v in values]
    elif kind == 'b':
        out = [v in ('1', 'True') for v in values]
    elif kind == 't':
        out = [instant(v) for v in values]
    else:
        out = list(values)
    # the tree groups options by name (all NOPs together), -e keeps wire order
    return sorted(out) if tree and field == 'tcp.option_kind' else out


def flatten(node, out):
    for key, value in node.items():
        for item in value if isinstance(value, list) else [value]:
            if isinstance(item, dict):
                flatten(item, out)
            else:
                out.setdefault(key, []).append(item)
    return out


def mismatches(label, packets, expected, tree=False):
    found = []
    if len(packets) != len(expected):
        found.append('%s: %d packets, expected %d' % (label, len(packets), len(expected)))
    for number, (layers, x) in enumerate(zip(packets, expected), 1):
        seen = flatten(layers, {}) if tree else layers
        for field in FIELDS:
            want, got = x.get(field, []), normal(field, seen.get(field, []), tree)
            if tree and field == 'tcp.option_kind':
                want = sorted(want)
            if got != want:
                found.append('%s frame %d %s: expected %r observed %r' % (label, number, field, want, got))
    return found


class Lab:
    def __init__(self, client, store, project, root):
        self.client, self.store, self.project, self.root = client, store, project, root
        self.artifacts, self.results = {}, {}

    def artifact(self, name, content):
        if name not in self.artifacts:
            path = self.root / name
            path.write_bytes(content)
            self.artifacts[name] = (self.store.add_artifact(self.project, path), path)
        return self.artifacts[name][0]

    def job(self, name, content, operation, parameters=None):
        artifact = self.artifact(name, content)
        reply = self.client.post('/api/agent/call', json={'tool': 'theseus_analysis_start', 'arguments': {
            'project_id': self.project, 'artifact_id': artifact['id'], 'operation': operation, 'parameters': parameters or {}}})
        reply.raise_for_status()
        return wait(self.client, reply.json()['result'])

    def run(self, name, operation='capture.packets', parameters=None, content=None):
        key = (name, operation, json.dumps(parameters or {}, sort_keys=True))
        if key not in self.results:
            job = self.job(name, content if content is not None else CAPTURES[name][0], operation, parameters)
            assert job['state'] == 'finished', job['result'].get('execution', {}).get('stderr', job)
            self.results[key] = self.client.get('/api/jobs/' + job['id'] + '/analysis.json').json()['result']
        return self.results[key]

    def layers(self, name, parameters=None):
        return [row['_source']['layers'] for row in self.run(name, 'capture.packets', parameters)['packets']]

    def failure(self, name, content, parameters=None):
        job = self.job(name, content, 'capture.packets', parameters)
        assert job['state'] == 'failed', job
        return job['result']['execution']['stderr']


@pytest.fixture(scope='module')
def lab(tmp_path_factory):
    root = tmp_path_factory.mktemp('pcap-oracle')
    with TestClient(create_app(root / 'data'), base_url='http://127.0.0.1:5217') as client:
        client.get('/')
        store = client.app.state.store
        (root / 'files').mkdir()
        yield Lab(client, store, store.create_project('Packet oracle')['id'], root / 'files')


def test_fixture_bytes_read_back_by_dpkt_as_written():
    # guards the oracle itself: dpkt's reading of every file equals what was put into it
    for name, (content, written) in CAPTURES.items():
        assert read_capture(content) == written, name
        assert len(written) == (11 if name.startswith('raw') else 14)


def expected_of(name):
    return parse_all(read_capture(CAPTURES[name][0]))


ALL = FIELDS


@pytest.mark.parametrize('name', NAMES)
def test_selected_fields_match_the_independent_parse(lab, name):
    content = CAPTURES[name][0]
    result = lab.run(name, parameters={'fields': ALL})
    assert not mismatches(name, [row['_source']['layers'] for row in result['packets']], expected_of(name))
    assert result['snapshot_sha256'] == hashlib.sha256(content).hexdigest()
    assert result['coverage'] == {'decoded_matching_records': len(CAPTURES[name][1]), 'offset': 0, 'limit': None,
                                  'returned': len(CAPTURES[name][1]), 'has_more': False}
    assert result['warnings'] == '' and result['capture_metadata']['exit_code'] == 0
    assert result['engine']['version'].startswith('TShark') and '-r' in result['command']
    assert lab.artifacts[name][1].read_bytes() == content
    assert not list(lab.store.directory.rglob('packet-input.bin'))


@pytest.mark.parametrize('name', NAMES)
def test_full_tree_agrees_with_the_independent_parse(lab, name):
    packets = lab.layers(name)
    assert not mismatches(name, packets, expected_of(name), tree=True)
    for layers, rec in zip(packets, read_capture(CAPTURES[name][0])):
        truncated = rec['caplen'] < rec['origlen']
        # a packet cut by the snapshot length is marked in the tree and nowhere else
        assert ('_ws.short' in layers) == truncated, layers.keys()
        assert not any(key.startswith('_ws.malformed') for key in layers)
        if truncated:
            assert 'Packet size limited during capture' in layers['_ws.short']


@pytest.mark.parametrize('name', NAMES)
def test_original_captured_bytes_are_returned_unchanged(lab, name):
    packets = lab.layers(name, {'raw': True})
    for layers, rec in zip(packets, read_capture(CAPTURES[name][0])):
        hexed, start, length = layers['frame_raw'][:3]
        assert (bytes.fromhex(hexed), start, length) == (rec['data'], 0, rec['caplen'])
    assert len(packets) == len(CAPTURES[name][1])


@pytest.mark.parametrize('name', NAMES)
def test_capinfos_metadata_matches_what_was_written(lab, name):
    content, written = CAPTURES[name]
    text = lab.run(name)['capture_metadata']['stdout']
    info = dict(line.split(':', 1) for line in text.splitlines() if ':' in line and not line.startswith(' '))
    info = {key.strip(): value.strip() for key, value in info.items()}
    # capinfos names the nanosecond variant of the classic format "nsecpcap"
    assert info['File type'] == ('pcapng' if name.endswith('ng') else 'nsecpcap' if '-ns' in name else 'pcap')
    assert info['Number of packets'] == str(len(written))
    if name.endswith('ng'):
        assert info['Number of interfaces in file'] == str(len(IFACES))
        return
    digits = 9 if '-ns' in name else 6
    assert info['File timestamp precision'] == ('nanoseconds (9)' if digits == 9 else 'microseconds (6)')
    for label, moment in (('Earliest packet time', min(r['time'] for r in written)), ('Latest packet time', max(r['time'] for r in written))):
        # capinfos prints local time
        whole = int(moment)
        assert info[label] == datetime.datetime.fromtimestamp(whole).strftime('%Y-%m-%d %H:%M:%S') + '.' + str(int((moment - whole) * 10 ** digits)).zfill(digits)
    assert 'Packet size limit:   file hdr: 65535 bytes' in text


FILTERS = [
    ('ip.src == 192.0.2.1', lambda x: x.get('ip.src') == ['192.0.2.1']),
    ('ip.addr == 198.51.100.7', lambda x: '198.51.100.7' in x.get('ip.src', []) + x.get('ip.dst', [])),
    ('tcp.flags.syn == 1 && tcp.flags.ack == 0', lambda x: x.get('tcp.flags.syn') == [True] and x.get('tcp.flags.ack') == [False]),
    ('tcp.port == 4444', lambda x: 4444 in x.get('tcp.srcport', []) + x.get('tcp.dstport', [])),
    ('icmp.type == 8', lambda x: x.get('icmp.type') == [8]),
    ('vlan.id == 100', lambda x: x.get('vlan.id') == [100]),
    ('ipv6', lambda x: 'ipv6.src' in x),
    ('ip.flags.mf == 1', lambda x: x.get('ip.flags.mf') == [True]),
    ('frame.cap_len < frame.len', lambda x: x['frame.cap_len'][0] < x['frame.len'][0]),
    ('dns.flags.response == 1', lambda x: x.get('dns.flags.response') == [True]),
    ('dns.qry.name == "www.gauge.fixture"', lambda x: x.get('dns.qry.name') == ['www.gauge.fixture']),
    ('dns.a == 192.0.2.11', lambda x: '192.0.2.11' in x.get('dns.a', [])),
    ('frame.time_epoch > 1700000020', lambda x: x['frame.time_epoch'][0] > 1700000020),
    ('udp.length == 32', lambda x: x.get('udp.length') == [32]),
]


@pytest.mark.parametrize('rule,predicate', FILTERS, ids=[rule for rule, _ in FILTERS])
def test_display_filters_select_exactly_the_packets_the_oracle_selects(lab, rule, predicate):
    wanted = [x['frame.number'][0] for x in expected_of('le-us.pcap') if predicate(x)]
    assert wanted, 'the filter must select something for the check to mean anything'
    result = lab.run('le-us.pcap', parameters={'display_filter': rule, 'fields': ['frame.number']})
    assert [int(row['_source']['layers']['frame.number'][0]) for row in result['packets']] == wanted
    assert result['coverage']['decoded_matching_records'] == len(wanted)


def test_filter_matching_nothing_returns_no_packets_and_complete_coverage(lab):
    result = lab.run('le-us.pcap', parameters={'display_filter': 'tcp.port == 1', 'fields': ['frame.number']})
    assert result['packets'] == [] and result['coverage']['has_more'] is False and result['coverage']['decoded_matching_records'] == 0


@pytest.mark.parametrize('offset,limit', [(0, None), (0, 0), (0, 1), (1, 2), (2, None), (3, 100), (6, 1), (7, None), (99, None), (1, 0)])
def test_paging_slices_the_matching_packets_and_reports_what_is_left(lab, offset, limit):
    matching = [x['frame.number'][0] for x in expected_of('le-us.pcap') if 'udp.srcport' in x]
    parameters = {'display_filter': 'udp', 'fields': ['frame.number'], 'offset': offset}
    if limit is not None:
        parameters['limit'] = limit
    result = lab.run('le-us.pcap', parameters=parameters)
    page = matching[offset:] if limit is None else matching[offset:offset + limit]
    assert [int(row['_source']['layers']['frame.number'][0]) for row in result['packets']] == page
    assert result['coverage'] == {'decoded_matching_records': len(matching), 'offset': offset, 'limit': limit,
                                  'returned': len(page), 'has_more': offset + len(page) < len(matching)}


def test_packet_limit_reads_only_the_first_packets_and_says_so(lab):
    result = lab.run('le-us.pcap', parameters={'packet_limit': 3, 'fields': ['frame.number']})
    assert [row['_source']['layers']['frame.number'] for row in result['packets']] == [['1'], ['2'], ['3']]
    # 11 of the 14 packets were not read; a reader that reports has_more False for them hides that gap
    assert result['coverage']['has_more'] is True, result['coverage']
    assert (result['coverage']['packet_limit'], result['coverage']['capture_packets'], result['coverage']['unread_packets']) == (3, 14, 11)


def test_decode_as_changes_the_dissector_of_the_selected_port_only(lab):
    selected = {'display_filter': 'frame.number == 11', 'fields': ['frame.number', 'frame.protocols']}
    before = lab.layers('le-us.pcap', selected)[0]['frame.protocols']
    after = lab.layers('le-us.pcap', dict(selected, decode_as=['udp.port==5001,syslog']))[0]['frame.protocols']
    assert before == ['eth:ethertype:vlan:ethertype:ip:udp:data']
    assert after == ['eth:ethertype:vlan:ethertype:ip:udp:syslog']
    other = {'display_filter': 'frame.number == 12', 'fields': ['frame.protocols']}
    assert lab.layers('le-us.pcap', dict(other, decode_as=['udp.port==5001,syslog'])) == lab.layers('le-us.pcap', other)


def test_two_pass_resolves_the_fragment_forward_reference(lab):
    x = expected_of('le-us.pcap')
    first, last = x[7], x[8]
    assert last['ip.id'] == first['ip.id'] and first['ip.flags.mf'] == [True] and last['ip.flags.mf'] == [False]
    fields = ['frame.number', 'ip.reassembled_in', 'ip.fragment.count', 'ip.reassembled.length']
    rows = {int(r['frame.number'][0]): r for r in lab.layers('le-us.pcap', {'fields': fields, 'two_pass': True, 'display_filter': 'ip.id == 0x4242'})}
    assert rows[8].get('ip.reassembled_in') == ['9'], rows
    assert rows[9]['ip.fragment.count'] == ['2'] and rows[9]['ip.reassembled.length'] == [str(8 + 24)]
    assert 'ip.reassembled_in' not in rows[9]


def test_bad_ipv4_checksum_is_never_reported_valid_and_the_stored_value_is_kept(lab):
    content = CAPTURES['le-us.pcap'][0]
    rows = lab.layers('le-us.pcap', {'fields': ['frame.number', 'ip.checksum', 'ip.checksum.status']})
    records = read_capture(content)
    for row, rec in zip(rows, records):
        if rec['data'][12:14] != b'\x08\x00':
            continue
        header = rec['data'][14:34]
        valid = dpkt.in_cksum(header) == 0
        assert int(row['ip.checksum'][0], 16) == struct.unpack('!H', header[10:12])[0]
        # status 1 = verified good, 0 = verified bad, 2 = not verified
        assert row['ip.checksum.status'][0] in (('1', '2') if valid else ('0', '2')), (row, valid)
    assert dpkt.in_cksum(records[11]['data'][14:34]) != 0


def test_empty_captures_finish_with_no_packets(lab):
    for name, content in [('empty-classic.pcap', CAPTURES['le-us.pcap'][0][:24]), ('empty-ng.pcapng', pcapng_file(IFACES, []))]:
        result = lab.run(name, content=content)
        assert result['packets'] == [] and result['coverage']['decoded_matching_records'] == 0 and result['warnings'] == ''
        assert 'Number of packets:   0' in result['capture_metadata']['stdout']


def test_blocks_that_are_not_packets_add_no_packet(lab):
    def custom(kind, body):
        return block(kind, body, '<')
    stats = custom(5, struct.pack('<III', 0, 0, 0) + option(4, struct.pack('<Q', 3), '<') + option(0, b'', '<'))
    names = custom(4, struct.pack('<HH', 1, 4 + 13) + bytes([192, 0, 2, 1]) + b'host.fixture\0' + b'\0\0\0' + struct.pack('<HH', 0, 0))
    unknown = custom(0x00000999, b'not a packet')
    base = [(0, *stamp(i), CAPTURES['le-us.pcap'][1][i]['data'], CAPTURES['le-us.pcap'][1][i]['origlen'], None) for i in range(3)]
    content = pcapng_file(IFACES[:1], [base[0], names, unknown, base[1], stats, base[2], unknown])
    result = lab.run('interleaved.pcapng', parameters={'fields': ['frame.number', 'frame.time_epoch', 'frame.len']}, content=content)
    assert [(r['_source']['layers']['frame.number'], r['_source']['layers']['frame.len']) for r in result['packets']] == \
        [(['1'], ['77']), (['2'], [str(base[1][4])]), (['3'], [str(base[2][4])])]
    assert result['warnings'] == ''


def cut_points():
    kept = [rec['data'] for rec in CAPTURES['le-us.pcap'][1]]
    record = 24 + sum(16 + len(d) for d in kept[:4])
    small = pcapng_file(IFACES[:1], [(0, *stamp(i), kept[i], len(kept[i]), None) for i in range(5)])
    third = len(pcapng_file(IFACES[:1], [])) + sum(len(block(6, struct.pack('<IIIII', 0, 0, 0, len(kept[i]), len(kept[i])) + pad4(kept[i]), '<')) for i in range(2))
    good = CAPTURES['le-us.pcap'][0]
    first = len(pcapng_file(IFACES[:1], [])) + 8  # interface id of the first packet block, pointed at an interface never declared
    undeclared = small[:first] + struct.pack('<I', 5) + small[first + 4:]
    return {
        'pcap-cut-in-record-data': good[:record + 16 + 10],
        'pcap-cut-in-record-header': good[:record + 7],
        'pcap-caplen-beyond-file': good[:record + 8] + struct.pack('<I', 5000) + good[record + 12:],
        'pcapng-cut-in-block': small[:-30],
        'pcapng-trailing-length-wrong': small[:-4] + struct.pack('<I', 0x1234),
        'pcapng-block-length-below-minimum': small[:third + 4] + struct.pack('<I', 7) + small[third + 8:],
        'pcapng-block-length-not-multiple-of-four': small[:third + 4] + struct.pack('<I', struct.unpack('<I', small[third + 4:third + 8])[0] + 1) + small[third + 8:],
        'pcapng-packet-on-undeclared-interface': undeclared,
    }


DAMAGED = cut_points()


@pytest.mark.parametrize('name', sorted(DAMAGED))
def test_damaged_captures_fail_with_the_decoder_diagnostic_instead_of_partial_packets(lab, name):
    stderr = lab.failure(name, DAMAGED[name])
    assert 'Packet decoder failed' in stderr
    assert any(word in stderr for word in ('cut short', 'damaged or corrupt', "doesn't", 'cannot'))


@pytest.mark.parametrize('name,content', [('empty-file', b''), ('wrong-magic.pcap', b'\xde\xad\xbe\xef' + CAPTURES['le-us.pcap'][0][4:]),
                                          ('text-file', b'this is not a capture\n' * 40)], ids=['empty', 'wrong-magic', 'text'])
def test_bytes_that_are_not_a_capture_are_not_reported_as_an_ordinary_empty_capture(lab, name, content):
    job = lab.job(name, content, 'capture.packets', {})
    # tshark guesses other container formats for junk; the reader refuses anything without a PCAP/PCAPNG header.
    assert job['state'] == 'failed', job
    assert 'Not a PCAP or PCAPNG capture' in job['result']['execution']['stderr']


@pytest.mark.parametrize('parameters,message', [({'display_filter': 'nonsense ==='}, 'Unexpected end of filter'),
                                               ({'fields': ['no.such.field']}, "fields aren't valid"),
                                               ({'decode_as': ['bogus']}, 'bogus')])
def test_invalid_decoder_parameters_fail_with_the_decoder_message(lab, parameters, message):
    assert message in lab.failure('le-us.pcap', CAPTURES['le-us.pcap'][0], parameters)


@pytest.fixture(scope='module')
def catalog(tmp_path_factory):
    config = tmp_path_factory.mktemp('tshark-config')
    env = dict(os.environ, WIRESHARK_CONFIG_DIR=str(config))
    run_ = lambda kind: subprocess.run([engine(), '-G', kind], env=env, capture_output=True, check=True).stdout.decode('utf8').splitlines()
    return [line.split('\t') for line in run_('fields')], [line.split('\t') for line in run_('protocols')]


KNOWN_FIELDS = [('ip.src', 'FT_IPv4', 'ip'), ('ip.ttl', 'FT_UINT8', 'ip'), ('ip.flags.mf', 'FT_BOOLEAN', 'ip'), ('ipv6.src', 'FT_IPv6', 'ipv6'),
                ('eth.src', 'FT_ETHER', 'eth'), ('vlan.id', 'FT_UINT16', 'vlan'), ('udp.length', 'FT_UINT16', 'udp'), ('tcp.seq_raw', 'FT_UINT32', 'tcp'),
                ('tcp.flags.syn', 'FT_BOOLEAN', 'tcp'), ('icmp.type', 'FT_UINT8', 'icmp'), ('dns.qry.name', 'FT_STRING', 'dns'),
                ('dns.a', 'FT_IPv4', 'dns'), ('dns.aaaa', 'FT_IPv6', 'dns'), ('frame.cap_len', 'FT_UINT32', 'frame'),
                ('frame.time_epoch', 'FT_ABSOLUTE_TIME', 'frame')]


@pytest.mark.parametrize('field,kind,protocol', KNOWN_FIELDS)
def test_field_catalogue_lists_known_fields_with_protocol_and_type(lab, field, kind, protocol):
    rows = lab.run('le-us.pcap', 'capture.fields', {'match': field, 'protocol': protocol})['fields']
    assert [(row['field'], row['type'], row['protocol']) for row in rows if row['field'] == field] == [(field, kind, protocol)]
    assert all(row['protocol'] == protocol for row in rows)


def test_every_field_the_packet_tests_request_is_in_the_catalogue(lab):
    for protocol in sorted({field.split('.')[0] for field in FIELDS}):
        listed = {row['field'] for row in lab.run('le-us.pcap', 'capture.fields', {'protocol': protocol})['fields']}
        assert {field for field in FIELDS if field.split('.')[0] == protocol} <= listed, protocol


@pytest.mark.parametrize('protocol', ['ip', 'udp', 'vlan', 'icmp'])
def test_catalogue_of_a_protocol_equals_tshark_listing_with_paging(lab, catalog, protocol):
    raw = [(cols[1], cols[2], cols[3], cols[4]) for cols in catalog[0] if cols[0] == 'F' and cols[4] == protocol]
    result = lab.run('le-us.pcap', 'capture.fields', {'protocol': protocol})
    assert [(r['name'], r['field'], r['type'], r['protocol']) for r in result['fields']] == raw and raw
    assert result['coverage'] == {'decoded_matching_records': len(raw), 'offset': 0, 'limit': None, 'returned': len(raw), 'has_more': False}
    page = lab.run('le-us.pcap', 'capture.fields', {'protocol': protocol, 'offset': 2, 'limit': 3})
    assert [(r['name'], r['field'], r['type'], r['protocol']) for r in page['fields']] == raw[2:5]
    assert page['coverage'] == {'decoded_matching_records': len(raw), 'offset': 2, 'limit': 3, 'returned': 3, 'has_more': len(raw) > 5}


def test_catalogue_match_is_case_insensitive_and_exact_names_survive_it(lab):
    lower = lab.run('le-us.pcap', 'capture.fields', {'match': 'tcp.flags.syn'})['fields']
    upper = lab.run('le-us.pcap', 'capture.fields', {'match': 'TCP.FLAGS.SYN'})['fields']
    assert lower == upper and any(row['field'] == 'tcp.flags.syn' for row in lower)
    assert lab.run('le-us.pcap', 'capture.fields', {'match': 'no-such-field-anywhere'})['fields'] == []


@pytest.mark.parametrize('abbreviation,short,title', [('dns', 'DNS', 'Domain Name System'), ('tcp', 'TCP', 'Transmission Control Protocol'),
                                                      ('udp', 'UDP', 'User Datagram Protocol'), ('icmp', 'ICMP', 'Internet Control Message Protocol'),
                                                      ('vlan', 'VLAN', '802.1Q Virtual LAN')])
def test_protocol_catalogue_names_the_protocols_used_here(lab, abbreviation, short, title):
    rows = lab.run('le-us.pcap', 'capture.fields', {'kind': 'protocols', 'match': title})['fields']
    assert {'name': title, 'short_name': short, 'protocol': abbreviation} in rows


def test_checksum_validation_flags_only_the_damaged_ipv4_header(lab):
    rows = lab.layers('le-us.pcap', {'fields': ['frame.number', 'ip.checksum.status'], 'check_checksums': True})
    statuses = {row['frame.number'][0]: row.get('ip.checksum.status') for row in rows if row.get('ip.checksum.status')}
    bad = [number for number, status in statuses.items() if status != ['1']]
    assert len(bad) == 1 and statuses[bad[0]] == ['0'], statuses
