"""Tell the owner's window about overdue (C1) and late-start (C2) items, once per item per REPEAT_S.

Default is a dry run: it prints exactly what it would send and to whom, and sends nothing. `--send` sends through mai-resume's
safe send (`python -m mai_resume send --to <handle> --text <line> --wait 600`, which never types into a prompt that holds text) and
records the send only when it succeeded. Owner names map to Orca terminal handles in a small TSV (`owner<TAB>handle`), because
handles change when a session is reopened. An owner without a handle is reported, not guessed.

Telegram is not sent from here. Lines that would warrant it (design 8 절 정할 것 3: a P0 overdue, or a P0 wait on the owner) are
marked `telegram` in the output for the operations check to pass on.
"""
import json
import os
import subprocess
import sys
import time

from . import check as chk

REPEAT_S = 6 * 3600
RULES = ('C1', 'C2')
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
RESUME = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'mai-resume')


def read_owners(path):
    owners = {}
    if path and os.path.exists(path):
        with open(path, encoding='utf-8') as f:
            for line in f:
                line = line.split('#', 1)[0].strip()
                if line:
                    name, _, handle = line.partition('\t')
                    if handle.strip():
                        owners[name.strip()] = handle.strip()
    return owners


def text_for(f, item, list_path):
    when = item['end_plan'][3:].replace('T', ' ') if item['end_plan'].startswith('at:') else item['end_plan']
    what = '마감 %s 지남 · 증거 없음' % when if f['rule'] == 'C1' else '시작 예정 %s 지남 · 아직 시작 안 함' % item['start_plan'][3:].replace('T', ' ')
    return ('[mai-work] %s %s · %s · %s · 끝났으면 증거 파일을 만들고 상태를 끝으로, 늦어지면 마감을 근거와 함께 고쳐 주세요 · 목록 %s'
            % (item['id'], item['priority'], what, item['title'][:60], list_path))


def plan(list_path, owners, state, now, it=None):
    d = chk.document(list_path, now=now, it=it)
    if 'error' in d:
        return d, []
    items = {i['id']: i for i in d['items']}
    out = []
    for f in d['findings']:
        item = items.get(f['id'])
        if not item:
            continue
        telegram = item['priority'] == 'P0' and f['rule'] in ('C1', 'C9')
        if f['rule'] not in RULES and not telegram:
            continue
        key = '%s:%s:%s' % (f['rule'], f['id'], item['end_plan'] if f['rule'] == 'C1' else item['start_plan'])
        due = now - state.get(key, 0) >= REPEAT_S
        out.append({'key': key, 'rule': f['rule'], 'id': f['id'], 'owner': f['owner'], 'handle': owners.get(f['owner']),
                    'text': text_for(f, item, list_path) if f['rule'] in RULES else '', 'telegram': telegram, 'due': due})
    return d, out


def send(handle, text, wait=600):
    r = subprocess.run([sys.executable, '-m', 'mai_resume', 'send', '--to', handle, '--text', text, '--wait', str(wait)],
                       cwd=RESUME, capture_output=True, text=True, encoding='utf-8', errors='replace', creationflags=NO_WINDOW)
    return r.returncode, (r.stdout + r.stderr).strip()


def run(list_path, owners_path, state_path, do_send=False, now=None, it=None, sender=send):
    now = time.time() if now is None else now
    owners = read_owners(owners_path)
    try:
        with open(state_path, encoding='utf-8') as f:
            state = json.load(f)
    except (OSError, ValueError):
        state = {}
    d, lines = plan(list_path, owners, state, now, it)
    if 'error' in d:
        return {'error': d['error'], 'lines': []}
    for ln in lines:
        ln['result'] = 'dry run'
        if not ln['due']:
            ln['result'] = 'sent within %d h' % (REPEAT_S // 3600)
        elif not ln['text']:
            ln['result'] = 'telegram only'
        elif not ln['handle']:
            ln['result'] = 'no handle for owner %s' % ln['owner']
        elif do_send:
            rc, out = sender(ln['handle'], ln['text'])
            ln['result'] = 'sent' if rc == 0 else 'send failed rc %d: %s' % (rc, out[:200])
            if rc == 0:
                state[ln['key']] = now
    if do_send:
        tmp = state_path + '.tmp'
        os.makedirs(os.path.dirname(os.path.abspath(state_path)), exist_ok=True)
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(state, f, ensure_ascii=False, indent=1)
        os.replace(tmp, state_path)
    return {'lines': lines}
