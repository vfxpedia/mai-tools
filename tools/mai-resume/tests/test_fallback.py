"""Tests for fallback/limit_guard.py: it stays silent while mai-resume holds its lock port and takes over when the port is free.

No real pane is written to (send is replaced) and no real ~/.mai file is touched (BASE and LOG point at a temp folder).
The lock is held the way mai-resume holds it (bind, listen(1), never accept), on a free port of this test's own.
"""
import datetime as dt
import importlib.util
import json
import os
import socket
import tempfile
import unittest
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, '..', 'fallback', 'limit_guard.py')


def load(env=None):
    old = {k: os.environ.get(k) for k in (env or {})}
    os.environ.update(env or {})
    try:
        spec = importlib.util.spec_from_file_location('limit_guard_under_test', SRC)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        return m
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def free_port():
    s = socket.socket()
    s.bind(('127.0.0.1', 0))
    p = s.getsockname()[1]
    s.close()
    return p


def hold_like_mai_resume(port):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(('127.0.0.1', port))
    s.listen(1)
    return s


NOW = dt.datetime(2026, 10, 26, 6, 0, tzinfo=dt.timezone.utc)
HOT = {'default': {'five_hour': [{'pct': 95, 'reset': '2026-10-26T08:00:00Z', 'at': 1}]}}


class FallbackTest(unittest.TestCase):
    def setUp(self):
        self.m = load()
        tmp = Path(tempfile.mkdtemp(prefix='guard-test-'))
        self.m.BASE, self.m.LOG = tmp, tmp / 'guard.log'
        self.sent = []
        self.m.send = lambda h, text, dry: self.sent.append(h) or True
        self.port = free_port()
        self.cfg = {'sessions': {'a': 'term_a', 'b': 'term_b'}, 'warn_pct_five_hour': 93, 'warn_pct_seven_day': 98,
                    'resume_grace_s': 180, 'poll_s': 60, 'keepalive_s': 0, 'primary_lock_port': self.port}

    def log(self):
        return self.m.LOG.read_text(encoding='utf-8') if self.m.LOG.exists() else ''

    def test_held_port_reads_alive_every_round(self):
        # mai-resume never accepts; a connect() probe fills the listen(1) backlog and then times out (seen 10/26).
        # The check must keep saying "alive" round after round.
        lk = hold_like_mai_resume(self.port)
        try:
            self.assertEqual([True] * 6, [self.m.primary_alive(self.port) for _ in range(6)])
        finally:
            lk.close()
        self.assertFalse(self.m.primary_alive(self.port))

    def test_silent_while_primary_alive(self):
        lk = hold_like_mai_resume(self.port)
        try:
            st = self.m.tick(self.cfg, {}, HOT, NOW, True)
            st = self.m.tick(self.cfg, st, HOT, NOW, True)
        finally:
            lk.close()
        self.assertEqual([], self.sent)
        self.assertTrue(st['standby'])
        self.assertIsNone(st.get('five_hour', {}).get('warned_key'))
        self.assertEqual(1, self.log().count('STANDBY'))

    def test_takes_over_when_port_free(self):
        lk = hold_like_mai_resume(self.port)
        st = self.m.tick(self.cfg, {}, HOT, NOW, True)
        lk.close()
        st = self.m.tick(self.cfg, st, HOT, NOW, True)
        self.assertEqual(['term_a', 'term_b'], self.sent)
        self.assertIn('ACTIVE', self.log())
        self.m.tick(self.cfg, st, HOT, NOW, True)
        self.assertEqual(2, len(self.sent), 'same window must not be warned twice')

    def test_port_zero_skips_the_check(self):
        lk = hold_like_mai_resume(self.port)
        try:
            self.m.tick(dict(self.cfg, primary_lock_port=0), {}, HOT, NOW, True)
        finally:
            lk.close()
        self.assertEqual(['term_a', 'term_b'], self.sent)

    def test_keepalive_also_silent(self):
        lk = hold_like_mai_resume(self.port)
        try:
            self.m.tick(dict(self.cfg, keepalive_s=10), {'keepalive': {'a': '2026-10-26T00:00:00+00:00'}},
                        {'default': {}}, NOW, True)
        finally:
            lk.close()
        self.assertEqual([], self.sent)

    def test_orca_command(self):
        self.assertEqual('my-orca', load({'ORCA_CLI_COMMAND': 'my-orca'}).ORCA)
        bare = load({'ORCA_CLI_COMMAND': ''}).ORCA
        if os.name == 'nt':
            self.assertTrue(bare.lower().endswith(os.path.join('programs', 'orca', 'resources', 'bin', 'orca.exe')))
        else:
            self.assertEqual('orca-ide', bare)  # the bare `orca` on Linux is the GNOME screen reader

    def test_example_config_has_every_key(self):
        cfg = json.load(open(os.path.join(HERE, '..', 'fallback', 'config.example.json'), encoding='utf-8'))
        for k in ('warn_pct_five_hour', 'warn_pct_seven_day', 'resume_grace_s', 'poll_s', 'keepalive_s',
                  'primary_lock_port', 'sessions'):
            self.assertIn(k, cfg)
        self.assertEqual(98, cfg['warn_pct_seven_day'])
        self.assertEqual(28766, cfg['primary_lock_port'])


if __name__ == '__main__':
    unittest.main()
