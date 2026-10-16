"""Sentinel defaults. Any UPPERCASE name can be overridden in /etc/sentinel/config.json."""
import json

STATE_DIR = '/var/lib/sentinel'
ENV_FILE = '/home/pi/keys/.env'
AUTH_LOG = '/var/log/auth.log'
OVERRIDES = '/etc/sentinel/config.json'

TICK_SECONDS = 5
SCAN_SECONDS = 60
LEARNING_HOURS = 72
ALERT_COOLDOWN = 3600
SUMMARY_HOUR = 9
# Dead-man switch off the Pi (e.g. https://hc-ping.com/<uuid>): a silent Pi raises the alarm there.
HEARTBEAT_URL = ''
HEARTBEAT_SECONDS = 300

STRIKE_LIMIT = 5
STRIKE_WINDOW = 600
BAN_LADDER = [3600, 86400, 7 * 86400]
OFFENDER_MEMORY = 30 * 86400
# Never banned, and logins from here only alert the first time. Covers LAN and the WireGuard subnet.
TRUSTED_NETS = ['127.0.0.0/8', '10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16',
                '::1/128', 'fe80::/10', 'fc00::/7']

WATCH_FILES = [
    '/etc/passwd', '/etc/shadow', '/etc/group', '/etc/sudoers', '/etc/sudoers.d/*',
    '/etc/ssh/sshd_config', '/root/.ssh/authorized_keys', '/home/*/.ssh/authorized_keys',
    '/etc/crontab', '/etc/cron.d/*', '/var/spool/cron/crontabs/*',
    '/etc/systemd/system/*.service', '/etc/systemd/system/*.wants/*', '/etc/rc.local',
    '/etc/profile', '/etc/profile.d/*', '/etc/bash.bashrc', '/root/.bashrc',
    '/home/*/.bashrc', '/home/*/.profile',
    '/etc/pam.d/common-auth', '/etc/pam.d/sshd', '/etc/pam.d/sudo',
    '/etc/hosts', '/etc/ld.so.preload', '/home/pi/keys/.env',
    '/opt/sentinel/sentinel/*.py',
]
ALARM_IF_EXISTS = ['/etc/ld.so.preload']

SUSPICIOUS_DIRS = ['/tmp/', '/var/tmp/', '/dev/shm/', '/run/shm/', '/run/user/']
SYSTEM_DIRS = ['/usr/', '/bin/', '/sbin/', '/lib/', '/opt/']
NEW_EXE_ALERTS = True
CPU_ALERT_PCT = 80
CPU_ALERT_MINUTES = 15
# Substrings of a process identity allowed to burn CPU for long stretches.
CPU_ALLOW = ['raspitrader.py', 'apt', 'dpkg', 'unattended-upgr', 'minidlnad', 'rsync', 'tar', 'gzip', 'git']
SUSPICIOUS_PORTS = [3333, 4444, 5555, 6666, 7777, 14433, 14444, 45560, 45700]


def apply_overrides(path=None):
    """Load the JSON override file; returns the keys it did not recognise."""
    try:
        with open(path or OVERRIDES) as f:
            data = json.load(f)
    except FileNotFoundError:
        return []
    names = globals()
    unknown = []
    for key, value in data.items():
        if key.isupper() and key in names:
            names[key] = value
        else:
            unknown.append(key)
    return unknown
