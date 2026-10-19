import unittest

from sentinel import config
from sentinel.intel import Reporter, parse_ips, restore_script, _rule


class IntelTest(unittest.TestCase):
    def test_parse_skips_junk_and_private(self):
        got = parse_ips('1.2.3.4\n# comment\n5.6.7.8 # tail\n10.0.0.1\n192.168.1.5\n172.20.0.1\n'
                        '172.32.0.1\n2001:db8::1\nfe80::1\nnot-an-ip\n999.1.1.1\n')
        self.assertEqual(got, {4: {'1.2.3.4', '5.6.7.8', '172.32.0.1'}, 6: {'2001:db8::1'}})

    def test_restore_swaps_a_filled_temp_set(self):
        lines = restore_script('SENTINEL_BL', 4, {'5.6.7.8', '1.2.3.4'}).splitlines()
        self.assertEqual(lines[0], 'create SENTINEL_BL hash:ip family inet maxelem 262144')
        self.assertEqual(lines[2:5], ['flush SENTINEL_BL_new', 'add SENTINEL_BL_new 1.2.3.4', 'add SENTINEL_BL_new 5.6.7.8'])
        self.assertEqual(lines[-2:], ['swap SENTINEL_BL_new SENTINEL_BL', 'destroy SENTINEL_BL_new'])

    def test_rule_only_new_ssh_connections(self):
        r = _rule('-I', 6, 'SENTINEL_BL6')
        self.assertEqual(r[:5], ['ip6tables', '-w', '-I', 'SENTINEL', '1'])
        self.assertIn('NEW', r)
        self.assertEqual(r[r.index('--dports') + 1], ','.join(map(str, config.BLOCKLIST_PORTS)))
        self.assertNotIn('1', _rule('-C', 4, 'SENTINEL_BL')[:5])

    def test_reporter_queue(self):
        r = Reporter('key')
        posted = []
        results = iter([1, 0, None])
        r._post = lambda ip, comment: posted.append((ip, comment)) or next(results)
        for i in range(4):
            r.add('203.0.113.%d' % i, 6, ['root', 'a b;<x>'])
        self.assertIn('usernames tried: root, abx', r.queue[0][1])
        self.assertEqual(r.flush(now=0), 1)
        self.assertEqual(len(r.queue), 2)
        self.assertEqual(r.flush(now=10), 0)  # backing off after the failure
        Reporter(None).add('1.2.3.4', 5, [])


if __name__ == '__main__':
    unittest.main()
