"""Main loop: tail auth.log every tick, run the heavier scans every SCAN_SECONDS."""
import os
import signal
import time
import traceback
from datetime import datetime

import json

from . import alerts, config, firewall, state as store
from .bot import Bot
from .authlog import LogTail, parse_line
from .guard import Guard, is_trusted
from .integrity import Integrity
from .intel import Blocklist, Reporter
from .lan import LanWatch
from .netwatch import NetWatch
from .procwatch import ProcWatch

MAX_LOGIN_IPS = 200


def human(seconds):
    if seconds >= 86400:
        return '%dd' % (seconds // 86400)
    if seconds >= 3600:
        return '%dh' % (seconds // 3600)
    return '%dm' % max(1, seconds // 60)


def request_file(name):
    """CLI -> running agent: requests are files in STATE_DIR, picked up within a minute."""
    return os.path.join(config.STATE_DIR, name)


class Agent:
    def __init__(self, unknown_keys=()):
        os.makedirs(config.STATE_DIR, mode=0o700, exist_ok=True)
        self.path = os.path.join(config.STATE_DIR, 'state.json')
        self.state = store.load(self.path)
        self.saved = store.dumps(self.state)
        env = alerts.read_env(config.ENV_FILE)
        bot_key = env.get('sentinel_bot_key')
        self.shared_bot = bool(bot_key) and bot_key == env.get('telegram_key')
        self.bot = Bot(bot_key, env.get('chat_id')) if bot_key and not self.shared_bot else None
        self.naming = {}
        self.notify = alerts.Notifier(bot_key or env.get('telegram_key'), env.get('chat_id'), config.ALERT_COOLDOWN)
        self.first_start = self.state.setdefault('first_start', time.time())
        self.guard = Guard(self.state)
        self.integrity = Integrity(self.state)
        self.net = NetWatch(self.state)
        self.procs = ProcWatch(self.state)
        self.lan = LanWatch(self.state, time.time())
        self.blocklist = Blocklist(self.state, config.STATE_DIR, env.get('abuseipdb_key'))
        self.reporter = Reporter(env.get('abuseipdb_key'))
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
        if self.lan.learning(now):
            until = datetime.fromtimestamp(self.lan.first_start + config.LEARNING_HOURS * 3600)
            self.notify.alert('🏠 Home network: learning your devices until %s' % until.strftime('%d/%m %H:%M'))
        for problem in self.lan.open() + self.blocklist.setup():
            self.notify.alert('⚙️ ' + problem)
        for mac in self.lan.reapply_blocks():
            self.notify.alert('⚙️ Could not re-apply the block on ' + self.lan.label(mac))
        if self.bot:
            self.bot.start()
        elif self.shared_bot:
            self.notify.alert('⚙️ sentinel_bot_key is the same bot as telebot: buttons disabled, create a separate bot')
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
            self._guarded('home network', self._lan, now)
            if self.bot:
                self._guarded('telegram', self._telegram, now)
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

    def _lan(self, now):
        for key, text in self.lan.poll(now):
            if key.startswith('device:'):
                if self._ask_device(key[7:], text):
                    continue
                text += '\nsudo sentinel --trust %s  (or --block)' % key[7:]
            self.notify.alert(text, key=key, now=now)

    def _ask_device(self, mac, text):
        if not self.bot:
            return False
        buttons = [[{'text': '✅ Trust', 'callback_data': 'trust:' + mac},
                    {'text': '🚫 Block', 'callback_data': 'block:' + mac}]]
        return self.bot.call('sendMessage', text=text, reply_markup={'inline_keyboard': buttons}) is not None

    def device_action(self, action, token):
        mac = self.lan.resolve(token)
        if mac is None:
            return 'Unknown device: %s (see /devices)' % token
        status = 'blocked' if action == 'block' else 'trusted'
        error = self.lan.set_status(mac, status)
        if error:
            return '⚙️ %s: %s' % (self.lan.label(mac), error)
        if status == 'trusted':
            return '✅ %s trusted' % self.lan.label(mac)
        return ('🚫 %s blocked: no access to the Pi, and cut off from the internet while the Pi is on (best effort). '
                'For good: block its MAC in the router or change the Wi-Fi password.' % self.lan.label(mac))

    def _telegram(self, now):
        for update in self.bot.drain():
            cb = update.get('callback_query')
            if cb:
                msg = cb.get('message') or {}
                action, _, mac = (cb.get('data') or '').partition(':')
                reply = self.device_action(action, mac)
                self.bot.call('answerCallbackQuery', callback_query_id=cb['id'], text=reply[:190])
                self.bot.call('editMessageText', message_id=msg.get('message_id'),
                              text='%s\n→ %s' % (msg.get('text', ''), reply))
                if action == 'trust' and reply.startswith('✅'):
                    ask = self.bot.call('sendMessage', text='Name for %s? Reply to this message, e.g. "Javi iPhone".' % mac,
                                        reply_markup={'force_reply': True})
                    if ask:
                        self.naming[ask['message_id']] = mac
                continue
            msg = update.get('message') or {}
            text = (msg.get('text') or '').strip()
            replied = (msg.get('reply_to_message') or {}).get('message_id')
            if replied in self.naming:
                mac = self.naming.pop(replied)
                self.lan.rename(mac, text)
                answer = '🏷 Saved: ' + self.lan.label(mac)
            else:
                answer = self.command(text)
            self.bot.call('sendMessage', text=answer)

    def command(self, text):
        parts = text.split(None, 2)
        cmd = parts[0].split('@')[0].lower() if parts else ''
        if cmd == '/devices':
            return self.lan.listing()
        if cmd in ('/trust', '/block', '/unblock') and len(parts) > 1:
            return self.device_action(cmd[1:], ' '.join(parts[1:]))
        if cmd == '/name' and len(parts) == 3:
            mac = self.lan.resolve(parts[1])
            if mac is None:
                return 'Unknown device: ' + parts[1]
            self.lan.rename(mac, parts[2])
            return '🏷 Saved: ' + self.lan.label(mac)
        if cmd == '/status':
            return '%s. %d IPs banned, %d known attackers blocked in advance.' % (
                'Learning mode' if self.learning else 'Full detection', len(self.guard.bans),
                self.state.get('blocklist_size', 0))
        return ('/devices - devices on your network (✅ trusted, ❔ waiting for review, 🚫 blocked)\n'
                '/trust X, /block X, /unblock X - X is a MAC, its last digits, or a name\n'
                '/name X New name\n/status - bans and mode')

    def handle(self, event, now):
        kind = event[0]
        if kind == 'fail':
            _, ip, user = event
            self.stats()['strikes'] += 1
            ban = self.guard.strike(ip, user, now)
            if ban:
                self.stats()['bans'] += 1
                ok = firewall.ban(ip)
                self.reporter.add(ip, ban['strikes'], ban['users'])
                if ok and not config.BAN_ALERTS:
                    return
                users = ', '.join(u[:20] for u in ban['users'][:5]) or '-'
                self.notify.alert('%s %s for %s: %d failed SSH attempts (users: %s), offence #%d'
                                  % ('🛡 Banned' if ok else '⚙️ FAILED to ban', ip, human(ban['duration']),
                                     ban['strikes'], users, ban['offence']),
                                  key=None if ok else 'banfail', now=now)
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
        self._guarded('network sweep', self.lan.sweep, now)
        self._guarded('threat intel', self._intel, now)
        self._guarded('heartbeat', self._heartbeat, now)
        self._guarded('daily summary', self._summary, now)
        self.save()

    def _expire(self, now):
        for ip in self.guard.expired(now):
            firewall.unban(ip)
        self.guard.prune(now)
        if os.path.exists(request_file('accept-gateway')):
            os.remove(request_file('accept-gateway'))
            self.state.pop('gateway_mac', None)
            self.notify.alert('✅ Router MAC forgotten; the next one seen is trusted', now=now)
        path = request_file('requests')
        if os.path.exists(path):
            with open(path) as f:
                lines = f.read().splitlines()
            os.remove(path)
            for line in lines:
                req = json.loads(line)
                if req['op'] == 'name':
                    mac = self.lan.resolve(req['device'])
                    if mac:
                        self.lan.rename(mac, req['name'])
                else:
                    self.notify.alert(self.device_action(req['op'], req['device']), now=now)
        path = request_file('unban')
        if not os.path.exists(path):
            return
        with open(path) as f:
            ips = f.read().split()
        os.remove(path)
        for ip in ips:
            self.guard.forgive(ip)
            firewall.unban(ip)
            self.notify.alert('✅ Unbanned %s (manual request)' % ip, now=now)

    def _intel(self, now):
        self.blocklist.refresh(now)
        sent = self.reporter.flush(now)
        if sent:
            self.stats()['reported'] = self.stats().get('reported', 0) + sent

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
        intel = ''
        if self.blocklist.ready:
            intel += ' %d known attackers blocked in advance.' % self.state.get('blocklist_size', 0)
        if self.reporter.key:
            intel += ' %d reported to AbuseIPDB.' % s.get('reported', 0)
        waiting = sum(1 for mac in self.lan.devices if self.lan.status(mac) == 'new')
        if waiting:
            intel += ' %d new devices waiting for your review (/devices).' % waiting
        self.notify.alert('☀️ Daily report: %d failed logins, %d bans, %d IPs banned now.%s %s. '
                          'Agent footprint: %s RSS, %.0fs CPU since start.'
                          % (s['strikes'], s['bans'], len(self.guard.bans), intel,
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
