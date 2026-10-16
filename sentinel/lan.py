"""Home network watch: device inventory, router impersonation and network scans from ARP, plus decoy ports.

The kernel hands us only ARP frames (ethertype filter on the socket), so this costs next to nothing.
"""
import ipaddress
import socket
import struct

try:
    import fcntl
except ImportError:  # Windows dev box
    fcntl = None

from . import config

ETH_P_ARP = 0x0806
SIOCGIFADDR, SIOCGIFNETMASK = 0x8915, 0x891b
BROADCAST = b'\xff' * 6
SCAN_WINDOW = 60
LAST_SEEN_STEP = 3600  # coarse last-seen keeps state writes (SD wear) rare


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
        return findings

    def _who(self, ip):
        macs = [mac for mac, d in self.devices.items() if d.get('ip') == ip]
        return ' (%s)' % macs[0] if macs else ''

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
            self.devices[mac] = {'ip': ip if local else None, 'first': now, 'last': now}
            if not self.learning(now):
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
