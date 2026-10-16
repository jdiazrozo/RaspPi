"""Process checks from /proc: temp-dir binaries, deleted binaries, fake kernel threads, first-seen programs, CPU hogs."""
import os

from . import config

INTERPRETERS = ('python', 'perl', 'ruby', 'node', 'php')


def read_proc(pid, proc='/proc'):
    base = os.path.join(proc, str(pid))
    try:
        exe = os.readlink(base + '/exe')
        with open(base + '/stat') as f:
            stat = f.read()
        with open(base + '/cmdline', 'rb') as f:
            raw = f.read()
    except OSError:
        return None  # kernel thread (no exe) or already gone
    fields = stat[stat.rfind(')') + 2:].split()
    try:
        ticks = int(fields[11]) + int(fields[12])
    except (IndexError, ValueError):
        ticks = 0
    argv = [a.decode('utf-8', 'replace') for a in raw.split(b'\0') if a]
    return {'pid': int(pid), 'exe': exe, 'argv': argv, 'ticks': ticks}


def ident(p):
    """Interpreters are identified by their script, otherwise every Python program looks the same."""
    exe = p['exe']
    if exe.endswith(' (deleted)'):
        exe = exe[:-10]
    if not os.path.basename(exe).startswith(INTERPRETERS):
        return exe
    args = p['argv'][1:]
    for i, arg in enumerate(args):
        if arg == '-m' and i + 1 < len(args):
            return '%s -m %s' % (exe, args[i + 1])
        if arg == '-c':
            return exe + ' -c'
        if not arg.startswith('-'):
            return '%s %s' % (exe, arg)
    return exe


def describe(p):
    return '%s (pid %d: %s)' % (p['exe'], p['pid'], ' '.join(p['argv'])[:120])


class ProcWatch:
    def __init__(self, state):
        self.known = state.setdefault('exes', {})
        self.prev = {}
        self.hot = {}
        self.flagged = set()
        self.clk = os.sysconf('SC_CLK_TCK') if hasattr(os, 'sysconf') else 100

    def scan(self, now, learning, proc='/proc'):
        findings = []
        alive = set()
        for name in os.listdir(proc):
            if not name.isdigit():
                continue
            p = read_proc(name, proc)
            if p is None:
                continue
            alive.add(p['pid'])
            exe, who = p['exe'], ident(p)
            if exe.startswith(tuple(config.SUSPICIOUS_DIRS)):
                findings.append(('tmpexe:' + exe, '🧨 Program running from a temp dir: ' + describe(p)))
            elif exe.endswith(' (deleted)') and not exe.startswith(tuple(config.SYSTEM_DIRS)):
                findings.append(('deleted:' + exe, '🧨 Running program whose file was deleted: ' + describe(p)))
            if p['argv'] and p['argv'][0].startswith('['):
                findings.append(('kthread:' + exe, '🎭 Process posing as a kernel thread: ' + describe(p)))
            if who not in self.known:
                self.known[who] = now
                if not learning and config.NEW_EXE_ALERTS:
                    findings.append(('newexe:' + who, '🆕 First time seen running: %s (pid %d)' % (who, p['pid'])))
            findings += self._cpu(p, who, now)
        for pid in [pid for pid in self.prev if pid not in alive]:
            self.prev.pop(pid)
            self.hot.pop(pid, None)
            self.flagged.discard(pid)
        return findings

    def _cpu(self, p, who, now):
        pid = p['pid']
        prev = self.prev.get(pid)
        self.prev[pid] = (p['ticks'], now)
        if prev is None or now <= prev[1]:
            return []
        pct = (p['ticks'] - prev[0]) / self.clk / (now - prev[1]) * 100
        if pct < config.CPU_ALERT_PCT:
            self.hot.pop(pid, None)
            return []
        self.hot[pid] = self.hot.get(pid, 0) + now - prev[1]
        if (self.hot[pid] < config.CPU_ALERT_MINUTES * 60 or pid in self.flagged
                or any(a in who for a in config.CPU_ALLOW)):
            return []
        self.flagged.add(pid)
        return [(None, '🔥 %s has used %d%% CPU for %d min - crypto miner?'
                 % (describe(p), pct, self.hot[pid] // 60))]
