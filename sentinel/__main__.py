"""python3 -m sentinel [--status | --unban IP | --test-alert]"""
import argparse
import os
import sys
import time

from . import alerts, config, state as store
from .guard import normalize


def main():
    ap = argparse.ArgumentParser(prog='sentinel')
    ap.add_argument('--status', action='store_true', help='show bans and mode')
    ap.add_argument('--unban', metavar='IP', help='lift a ban (applied by the running agent within a minute)')
    ap.add_argument('--test-alert', action='store_true', help='send a Telegram test message')
    args = ap.parse_args()
    unknown = config.apply_overrides()

    if args.unban:
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


if __name__ == '__main__':
    main()
