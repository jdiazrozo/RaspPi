import ipaddress
import unittest

from sentinel import config
from sentinel.lan import LanWatch, arp_request, parse_arp, randomized
from sentinel.netwatch import listeners

DAY = 86400
GW_MAC = '00:11:22:33:44:55'


def lan(now=0):
    w = LanWatch({}, now)
    w.my_mac, w.my_ip, w.net = 'b8:27:eb:31:d1:0e', '192.168.1.47', ipaddress.ip_network('192.168.1.0/24')
    return w


def frame(mac, ip, target, oper=1):
    raw = arp_request(bytes.fromhex(mac.replace(':', '')), ip, target)
    return raw[:20] + bytes([0, oper]) + raw[22:]


class LanTest(unittest.TestCase):
    def test_parse_roundtrip(self):
        self.assertEqual(parse_arp(frame('aa:bb:cc:dd:ee:01', '192.168.1.20', '192.168.1.1')),
                         (1, 'aa:bb:cc:dd:ee:01', '192.168.1.20', '192.168.1.1'))
        self.assertIsNone(parse_arp(b'\0' * 60))

    def test_learning_then_new_device(self):
        w = lan(0)
        self.assertEqual(w.handle(parse_arp(frame('aa:bb:cc:dd:ee:01', '192.168.1.20', '192.168.1.1')), 10), [])
        later = 4 * DAY
        self.assertEqual(w.handle(parse_arp(frame('aa:bb:cc:dd:ee:01', '192.168.1.20', '192.168.1.1')), later), [])
        out = w.handle(parse_arp(frame('da:bb:cc:dd:ee:02', '192.168.1.83', '192.168.1.1')), later)
        self.assertEqual(out[0][0], 'device:da:bb:cc:dd:ee:02')
        self.assertIn('phone/tablet', out[0][1])
        self.assertEqual(w.devices['aa:bb:cc:dd:ee:01']['last'], later)
        self.assertEqual(w.handle(parse_arp(frame(w.my_mac, w.my_ip, '192.168.1.5')), later), [])

    def test_router_impersonation(self):
        w = lan(0)
        w.handle(parse_arp(frame(GW_MAC, '192.168.1.1', '192.168.1.47', oper=2)), 1)
        self.assertEqual(w.state['gateway_mac'], GW_MAC)
        out = w.handle(parse_arp(frame('aa:bb:cc:dd:ee:01', '192.168.1.1', '192.168.1.47', oper=2)), 2)
        self.assertIn('gateway', [k for k, _ in out])

    def test_arp_scan(self):
        w = lan(0)
        out = []
        for i in range(2, 40):
            out += w.handle(parse_arp(frame('aa:bb:cc:dd:ee:09', '192.168.1.66', '192.168.1.%d' % i)), 100 + i * 0.1)
        self.assertIn('arpscan:aa:bb:cc:dd:ee:09', [k for k, _ in out])
        w2 = lan(0)
        out = []
        for i in range(2, 40):
            out += w2.handle(parse_arp(frame('aa:bb:cc:dd:ee:09', '192.168.1.66', '192.168.1.%d' % i)), i * 30)
        self.assertEqual(out, [])
        for i in range(2, 40):  # the router sweeping the network is normal
            out += w2.handle(parse_arp(frame(GW_MAC, '192.168.1.1', '192.168.1.%d' % i)), 5000)
        self.assertEqual(out, [])

    def test_decoy_port(self):
        import socket, time
        saved = config.LAN_DECOY_PORTS
        config.LAN_DECOY_PORTS = [47123]
        try:
            w = lan(0)
            w.open()
            self.assertEqual([p for p, _ in w.decoys], [47123])
            socket.create_connection(('127.0.0.1', 47123)).close()
            time.sleep(0.2)
            out = w.poll(10)
            self.assertEqual([k for k, _ in out], ['decoy:127.0.0.1'])
        finally:
            config.LAN_DECOY_PORTS = saved
            for _, d in w.decoys:
                d.close()

    def test_misc(self):
        self.assertTrue(randomized('da:00:00:00:00:00'))
        self.assertFalse(randomized('b8:27:eb:00:00:00'))
        socks = [('tcp', '0.0.0.0', p, '0.0.0.0', 0, '0A', '1') for p in (22, 23, 3389)]
        self.assertEqual(list(listeners(socks)), ['tcp/22'])


if __name__ == '__main__':
    unittest.main()
