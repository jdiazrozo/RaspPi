"""Brute-force accounting: strikes per IP in a sliding window; bans climb a ladder for repeat offenders."""
import functools
import ipaddress

from . import config


@functools.lru_cache(maxsize=8192)
def normalize(ip):
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return None
    if addr.version == 6 and addr.ipv4_mapped:
        addr = addr.ipv4_mapped
    return str(addr)


def is_trusted(ip):
    return _trusted(ip, tuple(config.TRUSTED_NETS))


@functools.lru_cache(maxsize=8192)
def _trusted(ip, nets):
    addr = ipaddress.ip_address(ip)
    return any(addr in net for net in _networks(nets))


@functools.lru_cache(maxsize=4)
def _networks(nets):
    return [ipaddress.ip_network(n) for n in nets]


class Guard:
    def __init__(self, state):
        self.bans = state.setdefault('bans', {})
        self.offenders = state.setdefault('offenders', {})
        self.strikes = {}

    def pending(self, ip):
        return len(self.strikes.get(ip, ([], None))[0])

    def strike(self, ip, user, now):
        """Count one failure; returns the ban it triggers, if any."""
        if ip in self.bans or is_trusted(ip):
            return None
        times, users = self.strikes.get(ip, ([], set()))
        times = [t for t in times if now - t < config.STRIKE_WINDOW] + [now]
        if user:
            users.add(user)
        if len(times) < config.STRIKE_LIMIT:
            self.strikes[ip] = (times, users)
            return None
        self.strikes.pop(ip, None)
        past = self.offenders.get(ip)
        level = past['count'] if past and now - past['last'] < config.OFFENDER_MEMORY else 0
        ladder = config.BAN_LADDER
        duration = ladder[min(level, len(ladder) - 1)]
        self.offenders[ip] = {'count': level + 1, 'last': now}
        self.bans[ip] = now + duration
        return {'ip': ip, 'duration': duration, 'offence': level + 1,
                'users': sorted(users), 'strikes': len(times)}

    def expired(self, now):
        ips = [ip for ip, until in self.bans.items() if until <= now]
        for ip in ips:
            del self.bans[ip]
        return ips

    def forgive(self, ip):
        self.offenders.pop(ip, None)
        self.strikes.pop(ip, None)
        return self.bans.pop(ip, None) is not None

    def prune(self, now):
        for ip in [ip for ip, (t, _) in self.strikes.items() if now - t[-1] >= config.STRIKE_WINDOW]:
            del self.strikes[ip]
        for ip in [ip for ip, o in self.offenders.items() if now - o['last'] >= config.OFFENDER_MEMORY]:
            del self.offenders[ip]
