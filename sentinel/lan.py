"""Home network watch: device inventory, router impersonation and network scans from ARP, decoy ports,
and trusting/blocking devices.

The kernel hands us only ARP frames (ethertype filter on the socket), so this costs next to nothing.
"""
import ipaddress
import socket
import struct

try:
    import fcntl
except ImportError:  # Windows dev box
    fcntl = None

from . import config, firewall

ETH_P_ARP = 0x0806
SIOCGIFADDR, SIOCGIFNETMASK = 0x8915, 0x891b
BROADCAST = b'\xff' * 6
SCAN_WINDOW = 60
LAST_SEEN_STEP = 3600  # coarse last-seen keeps state writes (SD wear) rare
ICONS = {'trusted': '✅', 'new': '❔', 'blocked': '🚫'}


def mac_str(raw):
    return ':'.join('%02x' % b for b in raw)


def parse_arp(frame):
    if len(frame) < 42 or frame[12:14] != b'\x08\x06':
        return None
    htype, ptype, hlen, plen, oper = struct.unpack('!HHBBH', frame[14:22])
    if htype != 1 or ptype != 0x0800 or hlen != 6 or plen != 4:
        return None
    return oper, mac_str(frame[22:28]), socket.inet_ntoa(frame[28:32]), socket.inet_ntoa(frame[38:42])


def arp_request(my_mac, my_ip, target):
    return (BROADCAST + my_mac + b'\x08\x06' + struct.pack('!HHBBH', 1, 0x0800, 6, 4, 1)
            + my_mac + socket.inet_aton(my_ip) + b'\0' * 6 + socket.inet_aton(target))


def arp_reply(my_mac, claimed_ip, dst_mac, dst_ip):
    return (dst_mac + my_mac + b'\x08\x06' + struct.pack('!HHBBH', 1, 0x0800, 6, 4, 2)
            + my_mac + socket.inet_aton(claimed_ip) + dst_mac + socket.inet_aton(dst_ip))


def mac_rule(op, tool, mac):
    """raw/PREROUTING: dropped before routing, so a blocked device can't use the Pi as a router either."""
    where = ['PREROUTING', '1'] if op == '-I' else ['PREROUTING']
    return [tool, '-w', '-t', 'raw', op] + where + ['-m', 'mac', '--mac-source', mac, '-j', 'DROP']


def randomized(mac):
    """Locally administered bit: phones and tablets use these private per-network MACs."""
    return bool(int(mac[1], 16) & 2)


def _ifaddr(iface, request):
    if fcntl is None:
        raise OSError('fcntl not available')
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        data = fcntl.ioctl(s.fileno(), request, struct.pack('256s', iface[:15].encode()))
    return socket.inet_ntoa(data[20:24])


class LanWatch:
    def __init__(self, state, now):
        self.state = state
        self.devices = state.setdefault('lan_devices', {})
        self.first_start = state.setdefault('lan_first_start', now)
        self.requests = {}
        self.sock = None
        self.decoys = []
        self.my_mac = self.my_ip = self.net = None
        self.last_sweep = 0

    def learning(self, now):
        return now - self.first_start < config.LEARNING_HOURS * 3600

    def open(self):
        """Returns problems found while opening; empty when everything is listening."""
        problems = []
        iface = config.LAN_INTERFACE
        try:
            with open('/sys/class/net/%s/address' % iface) as f:
                self.my_mac = f.read().strip()
            self.my_ip = _ifaddr(iface, SIOCGIFADDR)
            self.net = ipaddress.ip_network('%s/%s' % (self.my_ip, _ifaddr(iface, SIOCGIFNETMASK)), strict=False)
            sock = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(ETH_P_ARP))
            sock.bind((iface, ETH_P_ARP))
            sock.setblocking(False)
            self.sock = sock
        except (OSError, AttributeError) as e:
            problems.append('ARP watch on %s disabled: %s' % (iface, e))
        for port in config.LAN_DECOY_PORTS:
            try:
                d = socket.socket()
                d.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                d.bind(('0.0.0.0', port))
                d.listen(8)
                d.setblocking(False)
                self.decoys.append((port, d))
            except OSError as e:
                problems.append('decoy port %d not opened: %s' % (port, e))
        return problems

    def poll(self, now):
        findings = []
        for port, d in self.decoys:
            while True:
                try:
                    conn, addr = d.accept()
                except OSError:
                    break
                conn.close()
                findings.append(('decoy:' + addr[0], '🪤 %s%s connected to decoy port %d on the Pi - '
                                 'something on your network is probing for victims' % (addr[0], self._who(addr[0]), port)))
        while self.sock is not None:
            try:
                frame = self.sock.recv(128)
            except OSError:
                break
            arp = parse_arp(frame)
            if arp:
                findings += self.handle(arp, now)
        self.cut_off()
        return findings

    def _who(self, ip):
        macs = [mac for mac, d in self.devices.items() if d.get('ip') == ip]
        return ' (%s)' % self.label(macs[0]) if macs else ''

    def handle(self, arp, now):
        oper, mac, ip, target = arp
        if mac == self.my_mac:
            return []
        out = []
        if ip == config.GATEWAY_IP:
            known = self.state.get('gateway_mac')
            if known is None:
                self.state['gateway_mac'] = mac
            elif mac != known:
                out.append(('gateway', '🚨 %s claims to be your router %s (the real one is %s) - someone may be '
                            'intercepting traffic on your network. If you replaced the router: sudo sentinel --accept-gateway'
                            % (mac, ip, known)))
        local = ip != '0.0.0.0' and (self.net is None or ipaddress.ip_address(ip) in self.net)
        dev = self.devices.get(mac)
        if dev is None:
            learning = self.learning(now)
            self.devices[mac] = {'ip': ip if local else None, 'first': now, 'last': now,
                                 'status': 'trusted' if learning else 'new'}
            if not learning:
                out.append(('device:' + mac, '📱 New device on your network: %s%s at %s'
                            % (mac, ' (private MAC: phone/tablet)' if randomized(mac) else '', ip if local else 'no IP yet')))
        else:
            if local:
                dev['ip'] = ip
            if now - dev['last'] >= LAST_SEEN_STEP:
                dev['last'] = now
        if oper == 1 and ip != config.GATEWAY_IP and mac not in config.LAN_SCAN_ALLOW:
            seen = self.requests.setdefault(mac, {})
            seen[target] = now
            if len(seen) >= config.ARP_SCAN_TARGETS:
                seen = {t: ts for t, ts in seen.items() if now - ts < SCAN_WINDOW}
                self.requests[mac] = seen
                if len(seen) >= config.ARP_SCAN_TARGETS:
                    out.append(('arpscan:' + mac, '🔎 %s (%s) is scanning your network: it looked for %d addresses '
                                'in a minute' % (mac, ip, len(seen))))
        return out

    def status(self, mac):
        return self.devices.get(mac, {}).get('status', 'trusted')

    def label(self, mac):
        name = self.devices.get(mac, {}).get('name')
        return '%s (%s)' % (name, mac) if name else mac

    def resolve(self, token):
        """A full MAC, its last few hex digits, or a device name."""
        token = token.strip().lower()
        if token in self.devices:
            return token
        hexed = token.replace(':', '').replace('-', '')
        hits = [m for m, d in self.devices.items()
                if (hexed and m.replace(':', '').endswith(hexed)) or (d.get('name') or '').lower() == token]
        return hits[0] if len(hits) == 1 else None

    def rename(self, mac, name):
        self.devices[mac]['name'] = name.strip()[:40]

    def set_status(self, mac, status):
        """Returns an error message, or None."""
        if mac not in self.devices:
            return 'unknown device'
        if status == 'blocked' and mac in (self.my_mac, self.state.get('gateway_mac')):
            return 'refusing to block the Pi itself or the router'
        old = self.status(mac)
        if status == 'blocked':
            for tool in firewall.TOOLS:
                if not (firewall._run(mac_rule('-C', tool, mac)) or firewall._run(mac_rule('-I', tool, mac))):
                    if tool == 'iptables':
                        return 'firewall rule failed (is the iptables raw table available?)'
        elif old == 'blocked':
            for tool in firewall.TOOLS:
                while firewall._run(mac_rule('-D', tool, mac)):
                    pass
        self.devices[mac]['status'] = status
        return None

    def reapply_blocks(self):
        """Firewall rules don't survive a reboot; the state does."""
        return [mac for mac in self.devices if self.status(mac) == 'blocked' and self.set_status(mac, 'blocked')]

    def cut_off(self):
        """Tell each blocked device the router lives at our MAC; raw/PREROUTING then drops what it sends."""
        if self.sock is None or not config.LAN_CUTOFF or not self.my_mac:
            return
        mine = bytes.fromhex(self.my_mac.replace(':', ''))
        for mac, d in self.devices.items():
            if d.get('status') == 'blocked' and d.get('ip'):
                try:
                    self.sock.send(arp_reply(mine, config.GATEWAY_IP, bytes.fromhex(mac.replace(':', '')), d['ip']))
                except OSError:
                    return

    def listing(self):
        def ip_key(item):
            return tuple(int(p) for p in (item[1].get('ip') or '0.0.0.0').split('.'))
        lines = ['%s %-15s %s%s' % (ICONS.get(self.status(mac), '?'), d.get('ip') or '-', self.label(mac),
                                     '  [router]' if mac == self.state.get('gateway_mac') else '')
                 for mac, d in sorted(self.devices.items(), key=ip_key)]
        return '\n'.join(lines) or 'no devices seen yet'

    def sweep(self, now):
        """Hourly ARP sweep so quiet devices also make it into the inventory."""
        if self.sock is None or now - self.last_sweep < config.LAN_SWEEP_SECONDS or self.net.num_addresses > 1024:
            return
        self.last_sweep = now
        mac = bytes.fromhex(self.my_mac.replace(':', ''))
        for host in self.net.hosts():
            if str(host) != self.my_ip:
                try:
                    self.sock.send(arp_request(mac, self.my_ip, str(host)))
                except OSError:
                    break
        self.requests = {m: s for m, s in self.requests.items() if any(now - ts < SCAN_WINDOW for ts in s.values())}
