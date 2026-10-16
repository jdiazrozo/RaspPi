"""Telegram alerts (batched, per-key cooldown) and the off-host heartbeat. Stdlib only."""
import time
import urllib.parse
import urllib.request

MAX_LEN = 3900
MAX_QUEUE = 100
RETRY_SECONDS = 60


def read_env(path):
    env = {}
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#') or '=' not in line:
                    continue
                key, value = line.split('=', 1)
                key = key.strip()
                if key.startswith('export '):
                    key = key[7:].strip()
                env[key] = value.strip().strip('"\'')
    except OSError:
        pass
    return env


class Notifier:
    def __init__(self, token, chat_id, cooldown, header='🛡 #Sentinel #PagolaPi'):
        self.token = token
        self.chat_id = chat_id
        self.cooldown = cooldown
        self.header = header
        self.queue = []
        self.last = {}
        self.retry_at = 0

    def alert(self, text, key=None, now=None):
        now = time.time() if now is None else now
        if key is not None:
            if key in self.last and now - self.last[key] < self.cooldown:
                return False
            self.last[key] = now
        self.queue.append(text[:MAX_LEN])
        del self.queue[:-MAX_QUEUE]
        return True

    def flush(self, now=None):
        now = time.time() if now is None else now
        if not self.queue or now < self.retry_at:
            return not self.queue
        while self.queue:
            chunk, count = self._next_chunk()
            if not self._send(self.header + '\n' + chunk):
                self.retry_at = now + RETRY_SECONDS
                return False
            del self.queue[:count]
        self.last = {k: t for k, t in self.last.items() if now - t < self.cooldown}
        return True

    def _next_chunk(self):
        parts, size = [], 0
        for text in self.queue:
            if parts and size + len(text) + 1 > MAX_LEN:
                break
            parts.append(text)
            size += len(text) + 1
        return '\n'.join(parts), len(parts)

    def _send(self, text):
        if not self.token or not self.chat_id:
            print(text, flush=True)
            return True
        data = urllib.parse.urlencode({'chat_id': self.chat_id, 'text': text,
                                       'disable_web_page_preview': 'true'}).encode()
        url = 'https://api.telegram.org/bot%s/sendMessage' % self.token
        try:
            with urllib.request.urlopen(url, data, timeout=15) as resp:
                return resp.status == 200
        except Exception as e:
            print('telegram send failed: %s' % e, flush=True)
            return False


def ping(url):
    try:
        urllib.request.urlopen(url, timeout=10).close()
        return True
    except Exception:
        return False
