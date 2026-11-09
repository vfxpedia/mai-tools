"""Send the Telegram outbox to the MAI OS bot: the Python sender that replaces tg-send.ps1 where there is no PowerShell.

Same job as C:/ssd-cleanup-logs/tg-send.ps1, so callers that write an outbox and read the result keep working:
- reads the outbox (UTF-8) and the two lines TELEGRAM_BOT_TOKEN= and TELEGRAM_CHAT_ID= from the .env file
- posts sendMessage with parse_mode HTML and no link preview (callers escape & < > themselves, as with the ps1)
- prints "sent ok=True" on success, "FAIL: ..." otherwise, and appends one line to the log

One difference on purpose: a failure exits 1. The ps1 exits 0 even on FAIL, so a caller that only reads the exit code
took a failed send for a sent one. Success still exits 0 and prints the same "sent ok=True".

The token is never printed or logged; any error text that contains it is masked before it is shown.

Defaults (Linux): outbox ~/.mai/tg/tg-outbox.txt · log ~/.mai/tg/tg-error.log · env ~/.claude/channels/telegram/.env
Usage: python3 tg_send.py [--outbox PATH] [--env PATH] [--log PATH]
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
import urllib.request

HOME = os.path.expanduser('~')
DEFAULT_OUTBOX = os.path.join(HOME, '.mai', 'tg', 'tg-outbox.txt')
DEFAULT_LOG = os.path.join(HOME, '.mai', 'tg', 'tg-error.log')
DEFAULT_ENV = os.path.join(HOME, '.claude', 'channels', 'telegram', '.env')
API = 'https://api.telegram.org/bot{token}/sendMessage'


def read_env(path):
    """The two values the ps1 reads, and nothing else. Missing file or line -> ValueError naming the key, not the value."""
    vals = {}
    with open(path, encoding='utf-8-sig') as f:
        for line in f:
            line = line.strip()
            for key in ('TELEGRAM_BOT_TOKEN', 'TELEGRAM_CHAT_ID'):
                if line.startswith(key + '='):
                    vals[key] = line[len(key) + 1:].strip().strip('"').strip("'")
    for key in ('TELEGRAM_BOT_TOKEN', 'TELEGRAM_CHAT_ID'):
        if not vals.get(key):
            raise ValueError('%s missing in %s' % (key, path))
    return vals['TELEGRAM_BOT_TOKEN'], vals['TELEGRAM_CHAT_ID']


def payload(chat_id, text):
    return {'chat_id': chat_id, 'text': text, 'parse_mode': 'HTML', 'disable_web_page_preview': True}


def post(token, body, opener=urllib.request.urlopen, timeout=30):
    req = urllib.request.Request(API.format(token=token), data=json.dumps(body).encode('utf-8'),
                                 headers={'Content-Type': 'application/json; charset=utf-8'}, method='POST')
    with opener(req, timeout=timeout) as r:
        return json.loads(r.read().decode('utf-8'))


def _log(path, line):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'a', encoding='utf-8') as f:
            f.write('%s %s\n' % (datetime.datetime.now().strftime('%H:%M:%S'), line))
    except OSError:
        pass                                    # the printed result is the contract; the log is a convenience


def send(outbox=DEFAULT_OUTBOX, env=DEFAULT_ENV, log=DEFAULT_LOG, opener=urllib.request.urlopen, out=None):
    """Returns the exit code. Prints exactly one result line, as the ps1 does."""
    out = out or sys.stdout
    if not os.path.isfile(outbox):
        print('no outbox', file=out)
        return 1
    with open(outbox, encoding='utf-8-sig') as f:
        text = f.read()
    if not text.strip():
        print('outbox empty', file=out)
        return 1
    token = ''
    try:
        token, chat_id = read_env(env)
        r = post(token, payload(chat_id, text), opener=opener)
        ok = bool(r.get('ok'))
    except Exception as e:                      # network, HTTP 400 (bad HTML), missing .env: all are one failed send
        msg = '%s: %s' % (type(e).__name__, e)
        if token:
            msg = msg.replace(token, '***')
        print('FAIL: ' + msg, file=out)
        _log(log, 'outbox FAIL: ' + msg)
        return 1
    print('sent ok=%s' % ok, file=out)
    _log(log, 'outbox sent' if ok else 'outbox FAIL: ok=False')
    return 0 if ok else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--outbox', default=DEFAULT_OUTBOX)
    ap.add_argument('--env', default=DEFAULT_ENV)
    ap.add_argument('--log', default=DEFAULT_LOG)
    a = ap.parse_args(argv)
    return send(a.outbox, a.env, a.log)


if __name__ == '__main__':
    sys.exit(main())
