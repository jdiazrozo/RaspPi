"""Bans live in a dedicated SENTINEL chain jumped from INPUT, so they never touch other rules."""
import subprocess

CHAIN = 'SENTINEL'
TOOLS = ('iptables', 'ip6tables')


def _run(args):
    try:
        return subprocess.run(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
    except OSError:
        return False


def _rule(op, ip):
    return ['ip6tables' if ':' in ip else 'iptables', '-w', op, CHAIN, '-s', ip, '-j', 'DROP']


def setup():
    ok = True
    for tool in TOOLS:
        _run([tool, '-w', '-N', CHAIN])
        if not _run([tool, '-w', '-C', 'INPUT', '-j', CHAIN]):
            ok = _run([tool, '-w', '-I', 'INPUT', '1', '-j', CHAIN]) and ok
    return ok


def ban(ip):
    return _run(_rule('-C', ip)) or _run(_rule('-A', ip))


def unban(ip):
    while _run(_rule('-D', ip)):
        pass
