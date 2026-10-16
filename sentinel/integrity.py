"""File integrity: a cheap stat signature every scan, SHA-256 only when the signature moves."""
import fnmatch
import glob
import hashlib
import os

from . import config

PASSWD = '/etc/passwd'


def _sig(path):
    try:
        st = os.stat(path)
    except OSError:
        return None
    if not os.path.isfile(path):
        return None
    return [st.st_mtime_ns, st.st_size, st.st_ino]


def _sha256(path):
    h = hashlib.sha256()
    try:
        with open(path, 'rb') as f:
            for block in iter(lambda: f.read(65536), b''):
                h.update(block)
    except OSError:
        return None
    return h.hexdigest()


def _preload():
    try:
        with open(config.PRELOAD_FILE) as f:
            lines = [l.strip() for l in f]
    except OSError:
        return []
    extra = [l for l in lines if l and not l.startswith('#') and l not in config.PRELOAD_ALLOW]
    if not extra:
        return []
    return [('preload', '🚨 %s injects %s into every program - the classic userland rootkit hook'
             % (config.PRELOAD_FILE, ', '.join(extra)[:200]))]


def passwd_users(text):
    users = {}
    for line in text.splitlines():
        parts = line.split(':')
        if len(parts) >= 7 and parts[2].isdigit():
            users[parts[0]] = [int(parts[2]), parts[6]]
    return users


class Integrity:
    def __init__(self, state, passwd=PASSWD):
        self.state = state
        self.files = state.setdefault('files', {})
        self.passwd = passwd

    def _watched(self, path):
        return any(fnmatch.fnmatch(path, p) for p in config.WATCH_FILES)

    def scan(self):
        findings = []
        first = not self.state.get('files_ready')
        current = set()
        for pattern in config.WATCH_FILES:
            current.update(glob.glob(pattern))
        for path in sorted(current | set(self.files)):
            sig = _sig(path)
            old = self.files.get(path)
            if sig is None:
                if old is not None:
                    del self.files[path]
                    if self._watched(path):
                        findings.append(('file:' + path, '🗑 Watched file deleted: ' + path))
                continue
            if old is not None and old['sig'] == sig:
                continue
            digest = _sha256(path)
            if digest is None:
                continue
            self.files[path] = {'sig': sig, 'sha': digest}
            if old is None and not first:
                findings.append(('file:' + path, '🆕 New file in a watched place: ' + path))
            elif old is not None and old['sha'] != digest:
                findings.append(('file:' + path, '📝 Watched file modified: ' + path))
            if path == self.passwd:
                findings += self._accounts()
        self.state['files_ready'] = True
        return findings + _preload()

    def _accounts(self):
        try:
            with open(self.passwd) as f:
                users = passwd_users(f.read())
        except OSError:
            return []
        old = self.state.get('users')
        self.state['users'] = users
        out = []
        for name, (uid, shell) in sorted(users.items()):
            if uid == 0 and name != 'root':
                out.append(('uid0:' + name, '🚨 Account %s has UID 0 (full root powers)' % name))
            if old is not None and name not in old:
                out.append(('user:' + name, '👤 New account: %s (uid %d, shell %s)' % (name, uid, shell)))
        for name in sorted(set(old or ()) - set(users)):
            out.append(('user:' + name, '👤 Account removed: ' + name))
        return out
