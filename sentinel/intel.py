"""Threat intel: known attackers preloaded into an ipset, and our own bans reported to AbuseIPDB."""
import os
import re
import shutil
import socket
import subprocess
import urllib.error
import urllib.parse
import urllib.request

from . import config, firewall

SETS = {4: 'SENTINEL_BL', 6: 'SENTINEL_BL6'}
MAXELEM = 262144
ABUSE_API = 'https://api.abuseipdb.com/api/v2/'
RETRY_SECONDS = 3600
_PRIVATE = ('10.', '127.', '192.168.', '0.', 'fe80:', 'fc', 'fd', '::1')


def parse_ips(text):
    found = {4: set(), 6: set()}
    for line in text.splitlines():
        ip = line.split('#', 1)[0].strip()
        if not ip or ip.lower().startswith(_PRIVATE) or re.match(r'172\.(1[6-9]|2\d|3[01])\.', ip):
            continue
        family = 6 if ':' in ip else 4
        try:
            socket.inet_pton(socket.AF_INET6 if family == 6 else socket.AF_INET, ip)
        except (OSError, ValueError):
            continue
        found[family].add(ip)
    return found


def restore_script(name, family, ips):
    """Fill a temp set and swap it in, so the live set is never empty mid-update."""
    tmp = name + '_new'
    lines = ['create %s hash:ip family %s maxelem %d' % (n, 'inet6' if family == 6 else 'inet', MAXELEM)
             for n in (name, tmp)]
    lines.append('flush ' + tmp)
    lines += ['add %s %s' % (tmp, ip) for ip in sorted(ips)]
    lines += ['swap %s %s' % (tmp, name), 'destroy ' + tmp]
    return '\n'.join(lines) + '\n'


def _rule(op, family, name):
    tool = 'ip6tables' if family == 6 else 'iptables'
    where = [firewall.CHAIN, '1'] if op == '-I' else [firewall.CHAIN]
    return ([tool, '-w', op] + where + ['-p', 'tcp', '-m', 'multiport',
            '--dports', ','.join(str(p) for p in config.BLOCKLIST_PORTS),
            '-m', 'conntrack', '--ctstate', 'NEW', '-m', 'set', '--match-set', name, 'src', '-j', 'DROP'])


def _get(url, headers=None):
    req = urllib.request.Request(url, headers=dict(headers or {}, **{'User-Agent': 'sentinel-ids'}))
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read().decode('utf-8', 'replace')


class Blocklist:
    def __init__(self, state, cache_dir, abuse_key):
        self.state = state
        self.cache = os.path.join(cache_dir, 'blocklist.txt')
        self.abuse_key = abuse_key
        self.ready = False

    def setup(self):
        if not config.BLOCKLIST_URLS and not self.abuse_key:
            return []
        if not shutil.which('ipset'):
            return ['blocklist disabled: ipset is not installed (sudo apt install ipset)']
        problems = []
        for family, name in SETS.items():
            create = ['ipset', '-exist', 'create', name, 'hash:ip', 'family', 'inet6' if family == 6 else 'inet',
                      'maxelem', str(MAXELEM)]
            if not firewall._run(create):
                problems.append('blocklist: could not create ipset ' + name)
                continue
            if not (firewall._run(_rule('-C', family, name)) or firewall._run(_rule('-I', family, name))):
                problems.append('blocklist: could not add the %s firewall rule' % name)
        self.ready = not problems
        if self.ready and os.path.exists(self.cache):
            with open(self.cache) as f:
                self._load(f.read())  # sets are empty after a reboot until the next download
        return problems

    def _load(self, text):
        total = 0
        for family, ips in parse_ips(text).items():
            run = subprocess.run(['ipset', '-exist', 'restore'], input=restore_script(SETS[family], family, ips),
                                 universal_newlines=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            if run.returncode:
                raise RuntimeError('ipset restore failed: %s' % run.stderr.strip()[:200])
            total += len(ips)
        return total

    def refresh(self, now):
        """Downloads at most once per BLOCKLIST_REFRESH; returns the number of IPs loaded, or None."""
        if not self.ready or now < self.state.get('blocklist_next', 0):
            return None
        self.state['blocklist_next'] = now + RETRY_SECONDS
        texts, errors = [], []
        sources = [(url, None) for url in config.BLOCKLIST_URLS]
        if self.abuse_key:
            sources.append((ABUSE_API + 'blacklist?limit=10000&plaintext',
                            {'Key': self.abuse_key, 'Accept': 'text/plain'}))
        for url, headers in sources:
            try:
                texts.append(_get(url, headers))
            except Exception as e:
                errors.append('%s: %s' % (url.split('/')[2], e))
        if not texts:
            raise RuntimeError('all blocklist downloads failed (%s)' % '; '.join(errors))
        text = '\n'.join(texts)
        count = self._load(text)
        with open(self.cache, 'w') as f:
            f.write(text)
        self.state['blocklist_next'] = now + config.BLOCKLIST_REFRESH
        self.state['blocklist_size'] = count
        return count


class Reporter:
    """Queues our bans and reports a few per scan: TLS handshakes are slow on the B+."""

    def __init__(self, key):
        self.key = key
        self.queue = []
        self.retry_at = 0

    def add(self, ip, strikes, users):
        if not self.key or not config.ABUSEIPDB_REPORT:
            return
        tried = ', '.join(re.sub(r'[^\w.@-]', '', u)[:20] for u in users[:5]) or 'none'
        comment = 'SSH brute force: %d failed logins within %d min (usernames tried: %s). Automated report.' % (
            strikes, config.STRIKE_WINDOW // 60, tried)
        self.queue.append((ip, comment))
        del self.queue[:-200]

    def flush(self, now, limit=5):
        sent = 0
        while self.queue and limit > 0 and now >= self.retry_at:
            ip, comment = self.queue[0]
            result = self._post(ip, comment)
            if result is None:
                self.retry_at = now + RETRY_SECONDS  # offline or out of quota: keep the queue
                break
            self.queue.pop(0)
            limit -= 1
            sent += result
        return sent

    def _post(self, ip, comment):
        data = urllib.parse.urlencode({'ip': ip, 'categories': '18,22', 'comment': comment}).encode()
        req = urllib.request.Request(ABUSE_API + 'report', data,
                                     {'Key': self.key, 'Accept': 'application/json', 'User-Agent': 'sentinel-ids'})
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                return int(resp.status == 200)
        except urllib.error.HTTPError as e:
            if e.code == 429:
                return None  # daily quota: try again later
            return 0  # e.g. 422 for an IP already reported in the last 15 min
        except Exception:
            return None
