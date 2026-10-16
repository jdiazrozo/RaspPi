"""Sockets from /proc/net: new listening ports and new programs talking out. Owners resolved only for new sockets."""
import ipaddress
import os
import socket

from . import config
from .guard import is_trusted, normalize
from .procwatch import describe, ident, read_proc

TCP_ESTABLISHED, TCP_LISTEN, UDP_UNCONNECTED = '01', '0A', '07'
EPHEMERAL_START = 32768


def _addr(hexaddr):
    ip_hex, port_hex = hexaddr.split(':')
    raw = bytes.fromhex(ip_hex)
    if len(raw) == 4:
        ip = socket.inet_ntop(socket.AF_INET, raw[::-1])
    else:
        raw = b''.join(raw[i:i + 4][::-1] for i in range(0, 16, 4))
        ip = socket.inet_ntop(socket.AF_INET6, raw)
    return normalize(ip), int(port_hex, 16)


def read_sockets(netdir='/proc/net'):
    out = []
    for name in ('tcp', 'tcp6', 'udp', 'udp6'):
        try:
            f = open(os.path.join(netdir, name))
        except OSError:
            continue
        with f:
            next(f, None)
            for line in f:
                p = line.split()
                if len(p) < 10:
                    continue
                lip, lport = _addr(p[1])
                rip, rport = _addr(p[2])
                out.append((name.rstrip('6'), lip, lport, rip, rport, p[3], p[9]))
    return out


def listeners(socks):
    found = {}
    for proto, lip, lport, rip, rport, st, inode in socks:
        if proto == 'tcp' and (st != TCP_LISTEN or lport in config.LAN_DECOY_PORTS):
            continue
        # Unbound UDP on ephemeral ports is just clients (DHCP, DNS); not worth an alert.
        if proto == 'udp' and (st != UDP_UNCONNECTED or rport != 0 or lport >= EPHEMERAL_START):
            continue
        local = ipaddress.ip_address(lip).is_loopback
        found['%s/%d%s' % (proto, lport, ' (localhost only)' if local else '')] = inode
    return found


def outbound(socks):
    served = {lport for proto, _, lport, _, _, st, _ in socks if proto == 'tcp' and st == TCP_LISTEN}
    return [(inode, rip, rport) for proto, lip, lport, rip, rport, st, inode in socks
            if proto == 'tcp' and st == TCP_ESTABLISHED and lport not in served and not is_trusted(rip)]


def socket_owners(inodes, proc='/proc'):
    want = {'socket:[%s]' % i: i for i in inodes}
    found = {}
    for pid in os.listdir(proc):
        if not pid.isdigit():
            continue
        fd_dir = os.path.join(proc, pid, 'fd')
        try:
            fds = os.listdir(fd_dir)
        except OSError:
            continue
        for fd in fds:
            try:
                target = os.readlink(os.path.join(fd_dir, fd))
            except OSError:
                continue
            if target in want:
                found[want[target]] = pid
        if len(found) == len(want):
            break
    return found


class NetWatch:
    def __init__(self, state):
        self.listen = state.setdefault('listeners', {})
        self.talkers = state.setdefault('net_exes', {})
        self.seen = set()

    def scan(self, now, learning, proc='/proc'):
        socks = read_sockets(os.path.join(proc, 'net'))
        ports = listeners(socks)
        new_ports = [k for k in ports if k not in self.listen]
        outs = outbound(socks)
        new_outs = [o for o in outs if o[0] not in self.seen]
        self.seen = {o[0] for o in outs}
        need = [ports[k] for k in new_ports] + [o[0] for o in new_outs]
        owners = socket_owners(need, proc) if need else {}
        procs = {inode: read_proc(pid, proc) for inode, pid in owners.items()}
        findings = []
        for key in new_ports:
            self.listen[key] = now
            if not learning:
                p = procs.get(ports[key])
                findings.append(('listen:' + key, '🔌 New listening port %s by %s'
                                 % (key, describe(p) if p else 'unknown process')))
        for inode, rip, rport in new_outs:
            p = procs.get(inode)
            who = ident(p) if p else 'unknown process'
            if rport in config.SUSPICIOUS_PORTS:
                findings.append(('port:%s:%d' % (rip, rport), '🚩 Outbound connection to %s:%d (miner/reverse-shell port) by %s'
                                 % (rip, rport, describe(p) if p else who)))
            if p and who not in self.talkers:
                self.talkers[who] = now
                if not learning:
                    findings.append(('talker:' + who, '🌐 New program talking to the internet: %s -> %s:%d'
                                     % (who, rip, rport)))
        return findings
