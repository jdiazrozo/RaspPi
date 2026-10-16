"""Main loop: tail auth.log every tick, run the heavier scans every SCAN_SECONDS."""
import os
import signal
import time
import traceback
from datetime import datetime

from . import alerts, config, firewall, state as store
from .authlog import LogTail, parse_line
from .guard import Guard, is_trusted
from .integrity import Integrity
from .netwatch import NetWatch
from .procwatch import ProcWatch

MAX_LOGIN_IPS = 200


def human(seconds):
    if seconds >= 86400:
        return '%dd' % (seconds // 86400)
    if seconds >= 3600:
        return '%dh' % (seconds // 3600)
    return '%dm' % max(1, seconds // 60)


def unban_file():
    return os.path.join(config.STATE_DIR, 'unban')


class Agent:
    def __init__(self, unknown_keys=()):
        os.makedirs(config.STATE_DIR, mode=0o700, exist_ok=True)
        self.path = os.path.join(config.STATE_DIR, 'state.json')
        self.state = store.load(self.path)
        self.saved = store.dumps(self.state)
        env = alerts.read_env(config.ENV_FILE)
        self.notify = alerts.Notifier(env.get('telegram_key'), env.get('chat_id'), config.ALERT_COOLDOWN)
        self.first_start = self.state.setdefault('first_start', time.time())
        self.guard = Guard(self.state)
        self.integrity = Integrity(self.state)
        self.net = NetWatch(self.state)
        self.procs = ProcWatch(self.state)
        self.login_ips = self.state.setdefault('login_ips', {})
        log = self.state.get('authlog', {})
        self.tail = LogTail(config.AUTH_LOG, log.get('inode'), log.get('offset'))
        self.unknown_keys = list(unknown_keys)
        self.last_heartbeat = 0
        self.running = True

    @property
    def learning(self):
        return time.time() - self.first_start < config.LEARNING_HOURS * 3600

    def stats(self):
        return self.state.setdefault('stats', {'strikes': 0, 'bans': 0, 'since': time.time()})

    def start(self):
        now = time.time()
        if not firewall.setup():
            self.notify.alert('⚙️ Could not set up the SENTINEL iptables chain - bans will not work')
        for ip in self.guard.expired(now):
            firewall.unban(ip)
        for ip in self.guard.bans:
            firewall.ban(ip)
        if self.learning:
            until = datetime.fromtimestamp(self.first_start + config.LEARNING_HOURS * 3600)
            mode = 'learning what is normal until %s (brute-force and hard rules already active)' % until.strftime('%d/%m %H:%M')
        else:
            mode = 'full detection'
        self.notify.alert('🛡 Sentinel started: %s. %d IPs banned.' % (mode, len(self.guard.bans)))
        if not os.path.exists(config.AUTH_LOG):
            self.notify.alert('⚙️ %s not found - SSH brute-force detection is blind' % config.AUTH_LOG)
        if self.unknown_keys:
            self.notify.alert('⚙️ Unknown keys in %s: %s' % (config.OVERRIDES, ', '.join(self.unknown_keys)))

    def run(self):
        signal.signal(signal.SIGTERM, lambda *_: setattr(self, 'running', False))
        self.start()
        next_scan = 0
        while self.running:
            now = time.time()
            self._guarded('auth log', self._auth, now)
            if now >= next_scan:
                self.scan(now)
                next_scan = now + config.SCAN_SECONDS
            self.notify.flush(now)
            time.sleep(config.TICK_SECONDS)
        self.save()

    def _guarded(self, name, fn, now):
        try:
            fn(now)
        except Exception as e:
            traceback.print_exc()
            self.notify.alert('⚙️ Sentinel %s check failed: %s' % (name, e), key='err:' + name, now=now)

    def _auth(self, now):
        for line in self.tail.read_lines():
            event = parse_line(line)
            if event:
                self.handle(event, now)

    def handle(self, event, now):
        kind = event[0]
        if kind == 'fail':
            _, ip, user = event
            self.stats()['strikes'] += 1
            ban = self.guard.strike(ip, user, now)
            if ban:
                self.stats()['bans'] += 1
                ok = firewall.ban(ip)
                users = ', '.join(u[:20] for u in ban['users'][:5]) or '-'
                self.notify.alert('%s %s for %s: %d failed SSH attempts (users: %s), offence #%d'
                                  % ('🛡 Banned' if ok else '⚙️ FAILED to ban', ip, human(ban['duration']),
                                     ban['strikes'], users, ban['offence']), now=now)
        elif kind == 'accept':
            _, ip, user, method = event
            failed = self.guard.pending(ip)
            if failed:
                self.notify.alert('🚨 SSH login as %s from %s (%s) right after %d failed attempts - was it you?'
                                  % (user, ip, method, failed), now=now)
            elif not is_trusted(ip):
                self.notify.alert('⚠️ SSH login from the internet: %s from %s (%s)' % (user, ip, method),
                                  key='login:' + ip, now=now)
            elif ip not in self.login_ips and not self.learning:
                self.notify.alert('🔑 SSH login from a new LAN/VPN address: %s from %s' % (user, ip), now=now)
            self.login_ips[ip] = now
            if len(self.login_ips) > MAX_LOGIN_IPS:
                del self.login_ips[min(self.login_ips, key=self.login_ips.get)]
        elif kind == 'sudo_fail':
            self.notify.alert('⚠️ Failed sudo by %s' % event[1], key='sudo:' + event[1], now=now)
        elif kind == 'su_fail':
            self.notify.alert('⚠️ Failed su from %s to %s' % (event[1], event[2]), key='su:' + event[1], now=now)

    def scan(self, now):
        learning = self.learning
        for name, check in (('file integrity', lambda: self.integrity.scan()),
                            ('network', lambda: self.net.scan(now, learning)),
                            ('process', lambda: self.procs.scan(now, learning))):
            try:
                findings = check()
            except Exception as e:
                traceback.print_exc()
                findings = [('err:' + name, '⚙️ Sentinel %s check failed: %s' % (name, e))]
            for key, text in findings:
                self.notify.alert(text, key=key, now=now)
        self._guarded('ban expiry', self._expire, now)
        self._guarded('heartbeat', self._heartbeat, now)
        self._guarded('daily summary', self._summary, now)
        self.save()

    def _expire(self, now):
        for ip in self.guard.expired(now):
            firewall.unban(ip)
        self.guard.prune(now)
        path = unban_file()
        if not os.path.exists(path):
            return
        with open(path) as f:
            ips = f.read().split()
        os.remove(path)
        for ip in ips:
            self.guard.forgive(ip)
            firewall.unban(ip)
            self.notify.alert('✅ Unbanned %s (manual request)' % ip, now=now)

    def _heartbeat(self, now):
        if config.HEARTBEAT_URL and now - self.last_heartbeat >= config.HEARTBEAT_SECONDS:
            alerts.ping(config.HEARTBEAT_URL)
            self.last_heartbeat = now

    def _summary(self, now):
        today = datetime.fromtimestamp(now).strftime('%Y-%m-%d')
        if datetime.fromtimestamp(now).hour < config.SUMMARY_HOUR or self.state.get('summary_day') == today:
            return
        self.state['summary_day'] = today
        s = self.stats()
        cpu = sum(os.times()[:2])
        self.notify.alert('☀️ Daily report: %d failed logins, %d bans, %d IPs banned now. %s. '
                          'Agent footprint: %s RSS, %.0fs CPU since start.'
                          % (s['strikes'], s['bans'], len(self.guard.bans),
                             'Learning mode' if self.learning else 'Full detection', _rss(), cpu), now=now)
        self.state['stats'] = {'strikes': 0, 'bans': 0, 'since': now}

    def save(self):
        self.state['authlog'] = dict(zip(('inode', 'offset'), self.tail.position()))
        text = store.dumps(self.state)
        if text != self.saved:
            store.save(self.path, text)
            self.saved = text


def _rss():
    try:
        with open('/proc/self/status') as f:
            for line in f:
                if line.startswith('VmRSS:'):
                    return '%d MB' % (int(line.split()[1]) // 1024)
    except OSError:
        pass
    return '?'
