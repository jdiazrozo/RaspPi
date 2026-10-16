"""Run from RasPi_Services: python -m unittest discover -s sentinel/tests -t ."""
import os
import shutil
import tempfile
import unittest

from sentinel import alerts, config, state as store
from sentinel.authlog import LogTail, parse_line
from sentinel.guard import Guard, is_trusted, normalize
from sentinel.integrity import Integrity
from sentinel.netwatch import listeners, outbound, read_sockets
from sentinel.procwatch import ident

P = 'Oct 16 10:00:01 pagolapi sshd[1234]: '


class ParseTest(unittest.TestCase):
    def test_sshd_failures(self):
        cases = {
            'Failed password for pi from 203.0.113.5 port 5555 ssh2': ('fail', '203.0.113.5', 'pi'),
            'Failed password for invalid user admin from 203.0.113.5 port 5555 ssh2': ('fail', '203.0.113.5', 'admin'),
            'Invalid user oracle from 203.0.113.5 port 41022': ('fail', '203.0.113.5', 'oracle'),
            'Connection closed by authenticating user root 203.0.113.5 port 41022 [preauth]': ('fail', '203.0.113.5', 'root'),
            'Disconnected from authenticating user pi 2001:db8::1 port 41022 [preauth]': ('fail', '2001:db8::1', 'pi'),
            'error: maximum authentication attempts exceeded for root from 203.0.113.5 port 5555 ssh2 [preauth]': ('fail', '203.0.113.5', 'root'),
            'Did not receive identification string from 203.0.113.5 port 5555': ('fail', '203.0.113.5', None),
            "Bad protocol version identification 'GET / HTTP/1.1' from 203.0.113.5 port 5555": ('fail', '203.0.113.5', None),
            'Unable to negotiate with 203.0.113.5 port 5555: no matching key exchange method found. Their offer: x': ('fail', '203.0.113.5', None),
            'Failed password for pi from ::ffff:203.0.113.5 port 5555 ssh2': ('fail', '203.0.113.5', 'pi'),
        }
        for line, expected in cases.items():
            self.assertEqual(parse_line(P + line), expected, line)

    def test_ignored_lines(self):
        for line in ('Received disconnect from 203.0.113.5 port 5555:11: Bye Bye [preauth]',
                     'Connection closed by invalid user admin 203.0.113.5 port 5555 [preauth]',
                     'Server listening on 0.0.0.0 port 22.'):
            self.assertIsNone(parse_line(P + line), line)

    def test_username_cannot_redirect_the_strike(self):
        ev = parse_line(P + 'Invalid user x from 192.168.1.1 port 22 from 203.0.113.9 port 4000')
        self.assertEqual(ev[1], '203.0.113.9')

    def test_accept_and_sudo(self):
        self.assertEqual(parse_line(P + 'Accepted publickey for pi from 192.168.1.20 port 50000 ssh2: ED25519 SHA256:abc'),
                         ('accept', '192.168.1.20', 'pi', 'publickey'))
        self.assertEqual(parse_line('Oct 16 sudo:       pi : 3 incorrect password attempts ; TTY=pts/0 ; USER=root'),
                         ('sudo_fail', 'pi'))
        self.assertEqual(parse_line('Oct 16 pagolapi su[99]: FAILED SU (to root) pi on pts/0'),
                         ('su_fail', 'pi', 'root'))


class GuardTest(unittest.TestCase):
    def test_ladder_and_trust(self):
        state = {}
        g = Guard(state)
        for i in range(config.STRIKE_LIMIT - 1):
            self.assertIsNone(g.strike('203.0.113.5', 'root', 1000 + i))
        ban = g.strike('203.0.113.5', 'admin', 1010)
        self.assertEqual((ban['duration'], ban['offence'], ban['users']), (3600, 1, ['admin', 'root']))
        self.assertIsNone(g.strike('203.0.113.5', 'root', 1011))  # already banned
        self.assertEqual(g.expired(1010 + 3600), ['203.0.113.5'])
        for i in range(config.STRIKE_LIMIT):
            ban = g.strike('203.0.113.5', None, 5000 + i)
        self.assertEqual((ban['duration'], ban['offence']), (86400, 2))
        for i in range(20):
            self.assertIsNone(g.strike('192.168.1.7', 'pi', 1000 + i))
        self.assertIn('203.0.113.5', state['bans'])

    def test_window_slides(self):
        g = Guard({})
        for i in range(10):
            self.assertIsNone(g.strike('203.0.113.6', None, i * config.STRIKE_WINDOW / 2))

    def test_trusted(self):
        self.assertTrue(is_trusted('10.6.0.2'))
        self.assertTrue(is_trusted('fe80::1'))
        self.assertFalse(is_trusted('203.0.113.5'))
        self.assertFalse(is_trusted('2001:db8::1'))
        self.assertIsNone(normalize('not-an-ip'))


class TailTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, 'auth.log')

    def tearDown(self):
        shutil.rmtree(self.dir)

    def write(self, text, mode='a'):
        with open(self.path, mode, newline='') as f:
            f.write(text)

    def test_starts_at_end_then_reads_new_and_partial(self):
        self.write('old\n')
        t = LogTail(self.path)
        self.assertEqual(t.read_lines(), [])
        self.write('one\ntw')
        self.assertEqual(t.read_lines(), ['one'])
        self.write('o\n')
        self.assertEqual(t.read_lines(), ['two'])
        inode, offset = t.position()
        self.write('three\n')
        t.f.close()
        t2 = LogTail(self.path, inode, offset)
        self.assertEqual(t2.read_lines(), ['three'])
        t2.f.close()

    def test_truncation(self):
        self.write('a\nb\n')
        t = LogTail(self.path)
        self.write('', mode='w')
        self.write('c\n')
        self.assertEqual(t.read_lines(), [])
        self.assertEqual(t.read_lines(), ['c'])
        t.f.close()

    @unittest.skipIf(os.name == 'nt', 'cannot rename an open file on Windows')
    def test_rotation_keeps_last_lines(self):
        self.write('')
        t = LogTail(self.path)
        self.write('before\n')
        os.rename(self.path, self.path + '.1')
        self.write('after\n', mode='w')
        self.assertEqual(t.read_lines(), ['before', 'after'])


class IntegrityTest(unittest.TestCase):
    def test_create_modify_delete_and_accounts(self):
        d = tempfile.mkdtemp()
        try:
            passwd = os.path.join(d, 'passwd')
            with open(passwd, 'w') as f:
                f.write('root:x:0:0::/root:/bin/bash\npi:x:1000:1000::/home/pi:/bin/bash\n')
            saved = config.WATCH_FILES, config.PRELOAD_FILE
            config.WATCH_FILES, config.PRELOAD_FILE = [passwd, os.path.join(d, '*.conf')], os.path.join(d, 'preload')
            state = {}
            integ = Integrity(state, passwd=passwd)
            self.assertEqual(integ.scan(), [])
            with open(passwd, 'a') as f:
                f.write('toor:x:0:0::/root:/bin/sh\n')
            texts = ' | '.join(t for _, t in integ.scan())
            self.assertIn('modified', texts)
            self.assertIn('toor has UID 0', texts)
            self.assertIn('New account: toor', texts)
            open(os.path.join(d, 'x.conf'), 'w').close()
            self.assertIn('New file', integ.scan()[0][1])
            os.remove(os.path.join(d, 'x.conf'))
            self.assertIn('deleted', integ.scan()[0][1])
            self.assertEqual(integ.scan(), [])
            with open(config.PRELOAD_FILE, 'w') as f:
                f.write('/usr/lib/arm-linux-gnueabihf/libarmmem-${PLATFORM}.so\n')
            self.assertEqual(integ.scan(), [])
            with open(config.PRELOAD_FILE, 'a') as f:
                f.write('/lib/libhide.so\n')
            self.assertEqual([(k, '/lib/libhide.so' in t) for k, t in integ.scan()], [('preload', True)])
        finally:
            config.WATCH_FILES, config.PRELOAD_FILE = saved
            shutil.rmtree(d)


TCP = """  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode
   0: 00000000:0016 00000000:0000 0A 00000000:00000000 00:00000000 00000000     0        0 1001 1 0
   1: 0100007F:0277 00000000:0000 0A 00000000:00000000 00:00000000 00000000     0        0 1002 1 0
   2: 1401A8C0:0016 0571007B:A1B2 01 00000000:00000000 00:00000000 00000000     0        0 1003 1 0
   3: 1401A8C0:C350 0571007B:115C 01 00000000:00000000 00:00000000 00000000  1000        0 1004 1 0
   4: 1401A8C0:C351 0101A8C0:01BB 01 00000000:00000000 00:00000000 00000000  1000        0 1005 1 0
"""
UDP = """  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode ref pointer drops
   0: 00000000:076C 00000000:0000 07 00000000:00000000 00:00000000 00000000   108        0 2001 2 0 0
   1: 00000000:A3B4 00000000:0000 07 00000000:00000000 00:00000000 00000000     0        0 2002 2 0 0
"""


class NetTest(unittest.TestCase):
    def test_proc_net_parsing(self):
        d = tempfile.mkdtemp()
        try:
            for name, text in (('tcp', TCP), ('udp', UDP)):
                with open(os.path.join(d, name), 'w') as f:
                    f.write(text)
            socks = read_sockets(d)
            self.assertEqual(sorted(listeners(socks)), ['tcp/22', 'tcp/631 (localhost only)', 'udp/1900'])
            # inbound SSH (1003) and the LAN connection (1005) are not "outbound to the internet"
            self.assertEqual(outbound(socks), [('1004', '123.0.113.5', 4444)])
        finally:
            shutil.rmtree(d)


class MiscTest(unittest.TestCase):
    def test_ident(self):
        p = {'exe': '/usr/bin/python3.7', 'argv': ['python3', '-u', '/home/pi/telebot.py']}
        self.assertEqual(ident(p), '/usr/bin/python3.7 /home/pi/telebot.py')
        self.assertEqual(ident({'exe': '/usr/bin/python3.7', 'argv': ['python3', '-m', 'sentinel']}),
                         '/usr/bin/python3.7 -m sentinel')
        self.assertEqual(ident({'exe': '/usr/sbin/sshd', 'argv': ['sshd: pi']}), '/usr/sbin/sshd')

    def test_notifier_cooldown_and_batching(self):
        sent = []
        n = alerts.Notifier('t', 1, cooldown=100)
        n._send = lambda text: sent.append(text) or True
        self.assertTrue(n.alert('a', key='k', now=0))
        self.assertFalse(n.alert('a again', key='k', now=50))
        n.alert('b', now=50)
        n.flush(now=50)
        self.assertEqual(len(sent), 1)
        self.assertTrue(sent[0].endswith('a\nb'))
        self.assertTrue(n.alert('a later', key='k', now=200))

    def test_notifier_backs_off_when_offline(self):
        calls = []
        n = alerts.Notifier('t', 1, cooldown=0)
        n._send = lambda text: calls.append(text) and False
        n.alert('x', now=0)
        self.assertFalse(n.flush(now=0))
        n.flush(now=10)
        self.assertEqual(len(calls), 1)
        self.assertEqual(n.queue, ['x'])

    def test_overrides_and_state_roundtrip(self):
        d = tempfile.mkdtemp()
        try:
            path = os.path.join(d, 'c.json')
            with open(path, 'w') as f:
                f.write('{"STRIKE_LIMIT": 3, "bogus": 1}')
            saved = config.STRIKE_LIMIT
            self.assertEqual(config.apply_overrides(path), ['bogus'])
            self.assertEqual(config.STRIKE_LIMIT, 3)
            config.STRIKE_LIMIT = saved
            sp = os.path.join(d, 's.json')
            store.save(sp, store.dumps({'bans': {'1.2.3.4': 5}}))
            self.assertEqual(store.load(sp), {'bans': {'1.2.3.4': 5}})
            self.assertEqual(store.load(os.path.join(d, 'missing')), {})
        finally:
            shutil.rmtree(d)


if __name__ == '__main__':
    unittest.main()
