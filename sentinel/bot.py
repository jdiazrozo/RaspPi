"""Sentinel's own Telegram bot: long-polled in a daemon thread, so buttons and commands reach the main loop.

A separate bot from telebot.py's, since two pollers on one token steal each other's updates.
"""
import http.client
import json
import queue
import threading
import time
import urllib.parse
import urllib.request

POLL_SECONDS = 50


class Bot:
    def __init__(self, token, chat_id):
        self.token = token
        self.chat_id = str(chat_id)
        self.inbox = queue.Queue()
        self.offset = None

    def start(self):
        threading.Thread(target=self._run, name='telegram', daemon=True).start()

    def _run(self):
        conn = None
        while True:
            try:
                if conn is None:
                    # One kept-alive connection: a TLS handshake per poll is expensive on the B+.
                    conn = http.client.HTTPSConnection('api.telegram.org', timeout=POLL_SECONDS + 20)
                params = {'timeout': POLL_SECONDS, 'allowed_updates': '["message","callback_query"]'}
                if self.offset is not None:
                    params['offset'] = self.offset
                conn.request('GET', '/bot%s/getUpdates?%s' % (self.token, urllib.parse.urlencode(params)))
                resp = conn.getresponse()
                data = json.loads(resp.read().decode())
                if not data.get('ok'):
                    raise RuntimeError(data.get('description'))
                for update in data['result']:
                    self.offset = update['update_id'] + 1
                    if self._mine(update):
                        self.inbox.put(update)
            except Exception as e:
                print('telegram poll: %s' % e, flush=True)
                if conn is not None:
                    conn.close()
                conn = None
                time.sleep(30)

    def _mine(self, update):
        """Only the owner's chat may drive the bot; anyone can find and message a bot."""
        msg = update.get('message') or (update.get('callback_query') or {}).get('message') or {}
        return str(msg.get('chat', {}).get('id')) == self.chat_id

    def drain(self):
        out = []
        while True:
            try:
                out.append(self.inbox.get_nowait())
            except queue.Empty:
                return out

    def call(self, method, **params):
        if method in ('sendMessage', 'editMessageText'):
            params.setdefault('chat_id', self.chat_id)
        req = urllib.request.Request('https://api.telegram.org/bot%s/%s' % (self.token, method),
                                     json.dumps(params).encode(), {'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode()).get('result')
        except Exception as e:
            print('telegram %s failed: %s' % (method, e), flush=True)
            return None
