"""Release hygiene gate: the repository must not carry one person's machine, account or secrets.

Rules (each is reported with file and line):
  personal_path   a user-specific home path (C:/Users/<name>, /home/<name>, /Users/<name>) unless <name> is a placeholder
  email           an e-mail address
  secret          a token or key shaped value (GitHub, OpenAI style, AWS, private key block)
  em_dash         the long dash character (project style rule)
  hostname        a known real machine name given with --deny-host (optional, repeatable)

Usage: python common/hygiene_check.py [--deny-host NAME ...] [paths ...]   (default: every tracked text file under the repository)
Exit code 1 when anything is found. A scan that read zero files is also a failure.
"""
import argparse
import os
import re
import subprocess
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
PLACEHOLDER_USERS = {'user', 'users', 'you', 'name', 'username', 'someone', 'owner', 'example', 'me', 'public', 'default'}
B = chr(92)
HOME = re.compile(r'(?:[A-Za-z]:[/' + B + B + r']+Users[/' + B + B + r']+|/home/|/Users/)([A-Za-z0-9._-]+)')
EMAIL = re.compile(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+')
SECRETS = [
    ('github token', re.compile(r'\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}')),
    ('api key', re.compile(r'\bsk-[A-Za-z0-9_-]{20,}')),
    ('aws key id', re.compile(r'\bAKIA[0-9A-Z]{16}\b')),
    ('private key block', re.compile(r'-----BEGIN [A-Z ]*PRIVATE KEY-----')),
    ('bearer token', re.compile(r'(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{24,}')),
]
EM_DASH = chr(0x2014)
PLACEHOLDER_MAIL = re.compile(r'@(?:[A-Za-z0-9-]+\.)*(?:example\.(?:com|org|net)|invalid|test|local|localhost)$|@(?:b\.com)$')
SELF = 'common/tests/test_hygiene.py'   # plants bad strings on purpose
TEXT_EXT = ('.md', '.py', '.js', '.html', '.json', '.yml', '.yaml', '.txt', '.cfg', '.toml', '.gitignore', '.gitattributes')


def tracked_files():
    try:
        out = subprocess.run(['git', 'ls-files'], cwd=ROOT, capture_output=True, text=True, encoding='utf-8', check=True).stdout
        files = [os.path.join(ROOT, f) for f in out.splitlines() if f]
    except Exception:
        files = []
    if not files:
        for dp, dn, fn in os.walk(ROOT):
            dn[:] = [d for d in dn if d != '.git']
            files += [os.path.join(dp, f) for f in fn]
    return [f for f in files if f.endswith(TEXT_EXT) or os.path.basename(f).startswith('.git')]


def scan_text(name, text, deny_hosts=()):
    found = []
    for no, line in enumerate(text.splitlines(), 1):
        for m in HOME.finditer(line):
            if m.group(1).lower() not in PLACEHOLDER_USERS and len(m.group(1)) > 1:   # one letter is a placeholder
                found.append((name, no, 'personal_path', m.group(0)))
        for m in EMAIL.finditer(line):
            if not PLACEHOLDER_MAIL.search(m.group(0)):
                found.append((name, no, 'email', m.group(0)))
        for label, rx in SECRETS:
            if rx.search(line):
                found.append((name, no, 'secret', label))
        if EM_DASH in line:
            found.append((name, no, 'em_dash', 'long dash'))
        for h in deny_hosts:
            if re.search(r'(?i)\b' + re.escape(h) + r'\b', line):
                found.append((name, no, 'hostname', h))
    return found


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--deny-host', action='append', default=[])
    ap.add_argument('paths', nargs='*')
    a = ap.parse_args(argv)
    files = [os.path.abspath(p) for p in a.paths] if a.paths else tracked_files()
    read = 0
    found = []
    for f in files:
        try:
            with open(f, encoding='utf-8') as fh:
                text = fh.read()
        except (OSError, UnicodeDecodeError):
            continue
        read += 1
        try:
            rel = os.path.relpath(f, ROOT).replace(os.sep, '/')
        except ValueError:          # a file on another drive (Windows): show it as given
            rel = f.replace(os.sep, '/')
        if rel == SELF and not a.paths:
            continue
        found += scan_text(rel, text, a.deny_host)
    for name, no, rule, what in found:
        print('%s:%d: %s: %s' % (name, no, rule, what))
    print('files scanned: %d, findings: %d' % (read, len(found)))
    if read == 0:
        print('nothing was scanned: that is a failure, not a pass')
        return 1
    return 1 if found else 0


if __name__ == '__main__':
    sys.exit(main())
