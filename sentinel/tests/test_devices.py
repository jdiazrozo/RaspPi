import ipaddress
import os
import shutil
import tempfile
import unittest

from sentinel import agent, config, firewall
from sentinel.lan import LanWatch, arp_reply, parse_arp

PHONE = 'da:4f:00:00:00:91'
DAY = 86400


class FakeBot:
    def __init__(self):
        self.calls, self.updates, self.next_id = [], [], 100

    def drain(self):
        out, self.updates = self.updates, []
        return out

    def call(self, method, **params):
        self.calls.append((method, params))
        self.next_id += 1
        return {'message_id': self.next_id}


class DevicesTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.saved = (config.STATE_DIR, config.AUTH_LOG, config.ENV_FILE, config.WATCH_FILES, firewall._run)
        config.STATE_DIR, config.AUTH_LOG = self.dir, os.path.join(self.dir, 'auth.log')
        config.ENV_FILE, config.WATCH_FILES = os.path.join(self.dir, 'none'), []
        self.rules = []
        firewall._run = lambda args: self.rules.append(args) or '-C' not in args
        self.a = agent.Agent()
        self.a.notify._send = lambda text: True
        lan = self.a.lan
        lan.first_start = 0
        lan.my_mac, lan.my_ip, lan.net = 'b8:27:eb:31:d1:0e', '192.168.1.47', ipaddress.ip_network('192.168.1.0/24')
        lan.devices[PHONE] = {'ip': '192.168.1.83', 'first': 4 * DAY, 'last': 4 * DAY, 'status': 'new'}
        self.a.bot = FakeBot()

    def tearDown(self):
        config.STATE_DIR, config.AUTH_LOG, config.ENV_FILE, config.WATCH_FILES, firewall._run = self.saved
        shutil.rmtree(self.dir)

    def test_new_device_gets_buttons(self):
        self.a.lan.poll = lambda now: [('device:aa:bb:cc:dd:ee:01', '📱 New device')]
        self.a._lan(5 * DAY)
        method, params = self.a.bot.calls[0]
        self.assertEqual(method, 'sendMessage')
        self.assertEqual([b['callback_data'] for b in params['reply_markup']['inline_keyboard'][0]],
                         ['trust:aa:bb:cc:dd:ee:01', 'block:aa:bb:cc:dd:ee:01'])

    def test_trust_button_then_name_reply(self):
        self.a.bot.updates = [{'callback_query': {'id': 'q1', 'data': 'trust:' + PHONE,
                                                  'message': {'message_id': 7, 'text': '📱 New device'}}}]
        self.a._telegram(0)
        self.assertEqual(self.a.lan.status(PHONE), 'trusted')
        ask_id = self.a.bot.next_id
        self.assertIn(ask_id, self.a.naming)
        self.a.bot.updates = [{'message': {'text': 'Javi iPhone', 'reply_to_message': {'message_id': ask_id}}}]
        self.a._telegram(0)
        self.assertEqual(self.a.lan.devices[PHONE]['name'], 'Javi iPhone')
        self.assertEqual(self.a.lan.resolve('javi iphone'), PHONE)
        self.assertEqual(self.a.lan.resolve('00:91'), PHONE)

    def test_block_adds_raw_rule_and_unblock_removes_it(self):
        reply = self.a.command('/block 0091')
        self.assertTrue(reply.startswith('🚫'), reply)
        self.assertIn(['iptables', '-w', '-t', 'raw', '-I', 'PREROUTING', '1', '-m', 'mac', '--mac-source', PHONE,
                       '-j', 'DROP'], self.rules)
        self.assertIn('🚫 192.168.1.83', self.a.command('/devices'))
        firewall._run = lambda args: self.rules.append(args) or False  # -D succeeds once per rule below
        self.a.command('/unblock 0091')
        self.assertEqual(self.a.lan.status(PHONE), 'trusted')

    def test_refuses_router_and_unknown(self):
        self.a.state['gateway_mac'] = '00:11:22:33:44:55'
        self.a.lan.devices['00:11:22:33:44:55'] = {'ip': '192.168.1.1', 'first': 0, 'last': 0}
        self.assertIn('refusing', self.a.command('/block 00:11:22:33:44:55'))
        self.assertIn('Unknown device', self.a.command('/block ff:ff'))
        self.assertIn('/devices', self.a.command('/help'))

    def test_cli_requests_file(self):
        with open(os.path.join(self.dir, 'requests'), 'w') as f:
            f.write('{"op": "name", "device": "00:91", "name": "Tablet"}\n{"op": "trust", "device": "Tablet"}\n')
        self.a._expire(0)
        self.assertEqual((self.a.lan.devices[PHONE]['name'], self.a.lan.status(PHONE)), ('Tablet', 'trusted'))

    def test_cutoff_frame_claims_router_for_our_mac(self):
        frame = arp_reply(bytes.fromhex('b827eb31d10e'), '192.168.1.1', bytes.fromhex('da4f00000091'), '192.168.1.83')
        self.assertEqual(parse_arp(frame), (2, 'b8:27:eb:31:d1:0e', '192.168.1.1', '192.168.1.83'))
        self.assertEqual(frame[:6], bytes.fromhex('da4f00000091'))

    def test_learned_devices_are_trusted(self):
        w = LanWatch({}, 0)
        w.my_mac, w.net = 'b8:27:eb:31:d1:0e', ipaddress.ip_network('192.168.1.0/24')
        w.handle((1, 'aa:aa:aa:aa:aa:01', '192.168.1.9', '192.168.1.1'), 10)
        w.handle((1, 'aa:aa:aa:aa:aa:02', '192.168.1.10', '192.168.1.1'), 4 * DAY)
        self.assertEqual([w.status(m) for m in sorted(w.devices)], ['trusted', 'new'])


if __name__ == '__main__':
    unittest.main()
