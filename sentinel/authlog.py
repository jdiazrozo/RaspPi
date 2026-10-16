"""Tail auth.log across rotations and turn sshd/sudo/su lines into events."""
import os
import re

from .guard import normalize

_IP = r'(?P<ip>[0-9A-Fa-f:.]+)'
# Anchored at end of line and with greedy user groups: a username like "x from 10.0.0.1 port 1"
# cannot redirect the strike to an IP of the attacker's choosing.
_TAIL = r' port \d+(?: ssh2)?(?: \[preauth\])?$'
SSHD_FAILS = [re.compile(p) for p in (
    r'Failed \S+ for (?:invalid user )?(?P<user>.*) from ' + _IP + _TAIL,
    r'Invalid user (?P<user>.*) from ' + _IP + _TAIL,
    r'(?:Connection closed by|Disconnected from) authenticating user (?P<user>.*) ' + _IP + _TAIL,
    r'maximum authentication attempts exceeded for (?:invalid user )?(?P<user>.*) from ' + _IP + _TAIL,
    r'Did not receive identification string from ' + _IP + _TAIL,
    r'Bad protocol version identification .* from ' + _IP + _TAIL,
    r'Unable to negotiate with ' + _IP + r' port \d+: no matching ',
)]
SSHD_ACCEPT = re.compile(r'Accepted (?P<method>\S+) for (?P<user>.*) from ' + _IP
                         + r' port \d+ ssh2(?:: \S+ \S+)?$')
SUDO_FAIL = re.compile(r'sudo:\s+(?P<user>\S+) : (?:\d+ incorrect password attempts?|user NOT in sudoers)')
SU_FAIL = re.compile(r'su(?:\[\d+\])?: FAILED SU \(to (?P<target>\S+)\) (?P<user>\S+)')


def parse_line(line):
    line = line.rstrip()
    if ' sshd[' in line:
        m = SSHD_ACCEPT.search(line)
        if m:
            ip = normalize(m.group('ip'))
            return ('accept', ip, m.group('user'), m.group('method')) if ip else None
        for rx in SSHD_FAILS:
            m = rx.search(line)
            if m:
                ip = normalize(m.group('ip'))
                user = m.groupdict().get('user')
                return ('fail', ip, user) if ip else None
        return None
    m = SUDO_FAIL.search(line)
    if m:
        return ('sudo_fail', m.group('user'))
    m = SU_FAIL.search(line)
    if m:
        return ('su_fail', m.group('user'), m.group('target'))
    return None


class LogTail:
    """Keeps the file open so lines written just before a rotation are still read."""

    def __init__(self, path, inode=None, offset=None):
        self.path = path
        self.f = None
        self.inode = None
        self.buf = b''
        self._open(resume=(inode, offset))

    def _open(self, resume=None):
        try:
            f = open(self.path, 'rb')
        except OSError:
            self.f = None
            return
        st = os.fstat(f.fileno())
        self.f, self.inode, self.buf = f, st.st_ino, b''
        if resume is None:
            return
        inode, offset = resume
        if inode == st.st_ino and offset is not None and offset <= st.st_size:
            f.seek(offset)
        else:
            f.seek(0, 2)

    def position(self):
        if self.f is None:
            return None, None
        return self.inode, self.f.tell() - len(self.buf)

    def read_lines(self):
        if self.f is None:
            self._open()
            if self.f is None:
                return []
        lines = self._drain()
        try:
            st = os.stat(self.path)
        except OSError:
            return lines
        if st.st_ino != self.inode:
            self.f.close()
            self._open()
            if self.f is not None:
                lines += self._drain()
        elif st.st_size < self.f.tell():
            self.f.seek(0)
            self.buf = b''
        return lines

    def _drain(self):
        data = self.buf + self.f.read(1 << 20)
        parts = data.split(b'\n')
        self.buf = parts.pop()
        return [p.decode('utf-8', 'replace') for p in parts]
