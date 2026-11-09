"""CPU tests for tg_send.py. No network: the HTTP opener is replaced. Run: python -m unittest test_tg_send"""
import io
import json
import os
import tempfile
import unittest
import urllib.error

import tg_send

FAKE_TOKEN = '123456:FAKE-test-token'


class Resp:
    def __init__(self, obj):
        self.b = json.dumps(obj).encode()

    def read(self):
        return self.b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class T(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.box = os.path.join(self.d, 'tg-outbox.txt')
        self.env = os.path.join(self.d, '.env')
        self.log = os.path.join(self.d, 'log', 'tg-error.log')
        with open(self.env, 'w', encoding='utf-8') as f:
            f.write('OTHER=1\nTELEGRAM_BOT_TOKEN=%s\nTELEGRAM_CHAT_ID=42\n' % FAKE_TOKEN)
        self.sent = []

    def opener(self, reply=None, exc=None):
        def op(req, timeout=None):
            self.sent.append((req.full_url, json.loads(req.data.decode())))
            if exc:
                raise exc
            return Resp(reply if reply is not None else {'ok': True})
        return op

    def run_send(self, text, **kw):
        if text is not None:
            with open(self.box, 'w', encoding='utf-8') as f:
                f.write(text)
        out = io.StringIO()
        rc = tg_send.send(self.box, self.env, self.log, opener=kw.get('opener', self.opener()), out=out)
        return rc, out.getvalue().strip()

    def test_sends_same_payload_as_ps1(self):
        rc, out = self.run_send('[EX-42] 한글 &amp; 줄\n둘째 줄\n')
        self.assertEqual((rc, out), (0, 'sent ok=True'))
        url, body = self.sent[0]
        self.assertTrue(url.endswith('/sendMessage'))
        self.assertEqual(body, {'chat_id': '42', 'text': '[EX-42] 한글 &amp; 줄\n둘째 줄\n',
                                'parse_mode': 'HTML', 'disable_web_page_preview': True})
        self.assertIn('outbox sent', open(self.log, encoding='utf-8').read())

    def test_failure_exits_1_and_never_shows_token(self):
        err = urllib.error.URLError('cannot reach https://api.telegram.org/bot%s/sendMessage' % FAKE_TOKEN)
        rc, out = self.run_send('hello', opener=self.opener(exc=err))
        self.assertEqual(rc, 1)
        self.assertTrue(out.startswith('FAIL: '))
        self.assertNotIn(FAKE_TOKEN, out)
        self.assertNotIn(FAKE_TOKEN, open(self.log, encoding='utf-8').read())

    def test_ok_false_is_a_failure(self):
        rc, out = self.run_send('hello', opener=self.opener(reply={'ok': False}))
        self.assertEqual((rc, out), (1, 'sent ok=False'))

    def test_missing_and_empty_outbox(self):
        self.assertEqual(self.run_send(None), (1, 'no outbox'))
        self.assertEqual(self.run_send('  \n'), (1, 'outbox empty'))
        self.assertEqual(self.sent, [])

    def test_missing_env_line_names_key_only(self):
        with open(self.env, 'w', encoding='utf-8') as f:
            f.write('TELEGRAM_BOT_TOKEN=%s\n' % FAKE_TOKEN)
        rc, out = self.run_send('hello')
        self.assertEqual(rc, 1)
        self.assertIn('TELEGRAM_CHAT_ID missing', out)
        self.assertNotIn(FAKE_TOKEN, out)
        self.assertEqual(self.sent, [])


if __name__ == '__main__':
    unittest.main()
