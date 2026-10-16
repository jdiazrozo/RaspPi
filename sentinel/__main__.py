"""python3 -m sentinel [--status | --unban IP | --test-alert | --replay LOG...]"""
import argparse
import gzip
import os
import sys
import time
from collections import Counter
from datetime import datetime

from . import alerts, config, state as store
from .authlog import parse_line
from .guard import Guard, is_trusted, normalize


def main():
    ap = argparse.ArgumentParser(prog='sentinel')
    ap.add_argument('--status', action='store_true', help='show bans and mode')
    ap.add_argument('--unban', metavar='IP', help='lift a ban (applied by the running agent within a minute)')
    ap.add_argument('--test-alert', action='store_true', help='send a Telegram test message')
    ap.add_argument('--replay', nargs='+', metavar='LOG', help='dry-run old auth logs (oldest first, .gz ok)')
    args = ap.parse_args()
    unknown = config.apply_overrides()

    if args.replay:
        replay(args.replay)
    elif args.unban:
        ip = normalize(args.unban)
        if not ip:
            sys.exit('not an IP address: %s' % args.unban)
        with open(os.path.join(config.STATE_DIR, 'unban'), 'a') as f:
            f.write(ip + '\n')
        print('queued unban of %s' % ip)
    elif args.status:
        state = store.load(os.path.join(config.STATE_DIR, 'state.json'))
        now = time.time()
        learn_end = state.get('first_start', now) + config.LEARNING_HOURS * 3600
        print('mode: %s' % ('learning (%.1fh left)' % ((learn_end - now) / 3600) if now < learn_end else 'full detection'))
        bans = state.get('bans', {})
        print('active bans: %d' % len(bans))
        for ip, until in sorted(bans.items(), key=lambda kv: kv[1]):
            print('  %-40s %6.1fh left' % (ip, (until - now) / 3600))
    elif args.test_alert:
        env = alerts.read_env(config.ENV_FILE)
        n = alerts.Notifier(env.get('telegram_key'), env.get('chat_id'), 0)
        n.alert('✅ Sentinel test alert')
        sys.exit(0 if n.flush() else 'telegram send failed')
    else:
        from .agent import Agent
        Agent(unknown).run()


def _syslog_time(line, now):
    try:
        t = datetime.strptime(line[:15], '%b %d %H:%M:%S').replace(year=now.year)
    except ValueError:
        return None
    if t > now:
        t = t.replace(year=now.year - 1)
    return t.timestamp()


def replay(paths):
    """What the agent would have done with these logs; touches neither firewall nor state."""
    guard, now = Guard({}), datetime.now()
    fails, ips, bans, logins = 0, Counter(), [], []
    for path in paths:
        opener = gzip.open if path.endswith('.gz') else open
        with opener(path, 'rt', errors='replace') as f:
            for line in f:
                event = parse_line(line)
                ts = event and _syslog_time(line, now)
                if not ts:
                    continue
                if event[0] == 'fail':
                    fails += 1
                    ips[event[1]] += 1
                    ban = guard.strike(event[1], event[2], ts)
                    if ban:
                        bans.append(ban)
                    guard.expired(ts)
                elif event[0] == 'accept':
                    logins.append((line[:15], event, guard.pending(event[1])))
    print('failed-auth events: %d from %d IPs; %d bans by %d IPs'
          % (fails, len(ips), len(bans), len({b['ip'] for b in bans})))
    print('IPs that never reached the ban limit: %d (they made %d of the events)'
          % (sum(1 for ip in ips if ip not in {b['ip'] for b in bans}),
             sum(n for ip, n in ips.items() if ip not in {b['ip'] for b in bans})))
    print('top sources: ' + ', '.join('%s x%d' % kv for kv in ips.most_common(5)))
    print('successful logins (%d):' % len(logins))
    for when, (_, ip, user, method), pending in logins:
        flag = '  <-- FROM THE INTERNET' if not is_trusted(ip) else ''
        flag += '  <-- right after %d failures' % pending if pending else ''
        print('  %s  %-8s %-18s %s%s' % (when, user, ip, method, flag))


if __name__ == '__main__':
    main()
