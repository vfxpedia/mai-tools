"""The outside of mai-resume: Orca CLI calls, files, the loop, one instance only, heartbeat and the restart alert.

Orca is called as its executable with an argument list, never through a shell: through cmd a multi-line message was cut
at its first line (measured 10/20), and shell quoting could change the text. Every child process starts without a window
on Windows (CREATE_NO_WINDOW), as in mai-watch.
"""
import datetime as dt
import json
import os
import shutil
import socket
import subprocess
import sys
import time

from . import core

NO_WINDOW = 0x08000000 if os.name == 'nt' else 0
LOCK_PORT = 28766              # one mai-resume per machine: a second one cannot bind and exits


def home_dir(home=None):
    return home or os.path.join(os.path.expanduser('~'), '.mai', 'resume')


def load_json(path, default):
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def save_json(path, doc):
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


class Log:
    def __init__(self, path):
        self.path = path

    def __call__(self, msg):
        line = '%s %s\n' % (dt.datetime.now().strftime('%Y-%m-%dT%H:%M:%S'), core.one_line(msg))
        try:
            with open(self.path, 'a', encoding='utf-8') as f:
                f.write(line)
        except OSError:
            pass


def find_orca(cfg):
    if cfg.get('orca'):
        return cfg['orca']
    names = ['orca.exe'] if os.name == 'nt' else ['orca-ide', 'orca']
    for n in names:
        p = shutil.which(n)
        if p:
            return p
    return None


class Orca:
    """Thin wrapper over the Orca CLI. Each method returns parsed data or raises RuntimeError."""

    def __init__(self, exe, timeout=60):
        self.exe, self.timeout = exe, timeout

    def _run(self, args):
        p = subprocess.run([self.exe] + args + ['--json'], capture_output=True, text=True, encoding='utf-8',
                           errors='replace', timeout=self.timeout, creationflags=NO_WINDOW)
        try:
            doc = json.loads(p.stdout)
        except ValueError:
            raise RuntimeError('orca %s: rc=%s, not JSON: %s' % (args[:2], p.returncode, (p.stdout or p.stderr)[:200]))
        if not doc.get('ok'):
            raise RuntimeError('orca %s: %s' % (args[:2], json.dumps(doc.get('error'))[:200]))
        return doc.get('result') or {}

    def terminals(self):
        return self._run(['terminal', 'list']).get('terminals') or []

    def screen(self, handle):
        """{'text': screen text, 'prompt_trailing': trailing spaces of the last prompt row} (see core.screen_state)."""
        t = self._run(['terminal', 'read', '--terminal', handle, '--screen']).get('terminal') or {}
        lines, rows = t.get('tail') or [], t.get('tailRows') or []
        trailing = None
        for i in range(len(lines) - 1, -1, -1):
            if lines[i].strip().startswith(('\u276f', '\u203a')):
                trailing = (rows[i] or {}).get('trailingSpaces') if i < len(rows) and isinstance(rows[i], dict) else None
                break
        return {'text': '\n'.join(lines), 'prompt_trailing': trailing}

    def split(self, handle, command):
        # 'horizontal' puts the new pane UNDER the chat (checked on screen 10/20). The gauge goes below, never beside
        # (owner raised it three times). Orca's CLI has no size option, so the new pane starts at half the height.
        r = self._run(['terminal', 'split', '--terminal', handle, '--direction', 'horizontal', '--command', command])
        return bool(r)

    def send(self, handle, text):
        r = self._run(['terminal', 'send', '--terminal', handle, '--text', core.one_line(text), '--enter'])
        s = r.get('send') or {}
        return bool(s.get('accepted'))


def notify(cfg, text, log):
    """Hand text to the configured sender (like mai-watch: write notify_file, then run notify_cmd with the text on stdin)."""
    cmd = cfg.get('notify_cmd')
    if not cmd:
        log('NOTIFY (no sender configured) ' + text)
        return False
    try:
        if cfg.get('notify_file'):
            with open(cfg['notify_file'], 'w', encoding='utf-8') as f:
                f.write(text + '\n')
        p = subprocess.run(cmd if isinstance(cmd, list) else cmd.split(), input=text, capture_output=True, text=True,
                           encoding='utf-8', errors='replace', timeout=120, creationflags=NO_WINDOW)
        log('NOTIFY rc=%s %s' % (p.returncode, (p.stdout or p.stderr).strip()[:120]))
        return p.returncode == 0
    except (OSError, subprocess.SubprocessError) as e:
        log('NOTIFY failed %r' % e)
        return False


def take_lock(port=LOCK_PORT):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(('127.0.0.1', port))
        s.listen(1)
        return s
    except OSError:
        s.close()
        return None


_targets_seen = {}


def with_targets(cfg, log):
    """Read the allow list file every round (lead edits it without a restart). A file that exists, even empty, is the
    whole list; without the file every pane is watched, and that is logged once."""
    path = cfg.get('targets_file')
    if not path:
        return cfg
    try:
        with open(path, encoding='utf-8') as f:
            ids = core.read_targets(f.read())
    except FileNotFoundError:
        if _targets_seen.get(path) != 'missing':
            log('TARGETS %s missing: every pane is watched' % path)
            _targets_seen[path] = 'missing'
        return cfg
    except OSError as e:
        log('TARGETS %s unreadable (%s): nothing is sent this round' % (path, e))
        return dict(cfg, only_handles=[])
    if _targets_seen.get(path) != ids:
        log('TARGETS %d: %s' % (len(ids), ' '.join(ids)))
        _targets_seen[path] = ids
    return dict(cfg, only_handles=ids)


def round_once(orca, state, cfg, limits_path, now, log, dry=False):
    """One round: read Orca and limits, decide, deliver. Returns the new state."""
    terminals = orca.terminals()
    cfg = with_targets(cfg, log)
    sessions = core.discover(terminals, cfg.get('only_handles'), cfg.get('exclude_handles'))
    screens = {}
    for s in sessions:
        try:
            screens[s['handle']] = orca.screen(s['handle'])
        except (RuntimeError, OSError, subprocess.SubprocessError) as e:
            log('READ failed %s %s' % (s['handle'], e))        # unread pane: nothing is typed into it this round
    limits = load_json(limits_path, {})
    new, sends, lines = core.tick(state, now, limits, terminals, screens, cfg)
    for ln in lines:
        log(ln)
    engines = {s['handle']: s['engine'] for s in sessions}
    for handle, text, mid in sends:
        try:                                                     # look again right before typing: someone may have started
            fresh = orca.screen(handle)
            eng = engines.get(handle, 'claude')
            # typing now: the prompt row changed since this round's first read (lead 10/20, same rule as `send`)
            late = core.screen_state(eng, fresh, now)['typing'] or (
                handle in screens and core.prompt_key(eng, screens[handle]) != core.prompt_key(eng, fresh))
        except (RuntimeError, OSError, subprocess.SubprocessError):
            late = True
        if late:
            log('DEFER %s (prompt holds text right before sending)' % mid)
            new['sent'].pop(mid, None)
            new['pending'].append({'handle': handle, 'text': text, 'id': mid, 'since': core._iso(now)})
            continue
        if dry:
            log('DRY send %s %s: %s' % (handle, mid, text[:100]))
            continue
        try:
            ok = orca.send(handle, text)
        except (RuntimeError, OSError, subprocess.SubprocessError) as e:
            ok = False
            log('SEND error %s %s' % (handle, e))
        log('SEND %s %s accepted=%s' % (handle, mid, ok))
        if not ok:                                               # undo, so the next round tries again
            new['sent'].pop(mid, None)
            new['pending'].append({'handle': handle, 'text': text, 'id': mid, 'since': core._iso(now)})
    new['sessions'] = len(sessions)
    new['companions'] = dict(state.get('companions') or {})   # tick keeps only its own keys
    attach_companions(orca, new, cfg, terminals, sessions, log, dry)
    return new


def codex_ids_from_sessions(folder):
    """handle -> codex session id, newest file per handle, from the session gauges' ~/.mai/sessions/*.json."""
    best = {}
    try:
        names = os.listdir(folder)
    except OSError:
        return {}
    for n in names:
        if not n.endswith('.json'):
            continue
        d = load_json(os.path.join(folder, n), None)
        if not isinstance(d, dict) or not d.get('handle') or not str(d.get('id', '')).startswith('01'):
            continue          # codex thread ids start with 01 (UUID v7); Claude ids do not
        at = d.get('updatedAt') or 0
        if d['handle'] not in best or at > best[d['handle']][0]:
            best[d['handle']] = (at, d['id'])
    return {h: v[1] for h, v in best.items()}


def attach_companions(orca, state, cfg, terminals, sessions, log, dry=False):
    """Open the codex gauge next to codex panes that have none (lead · owner 10/20). Off when companion_cli is missing."""
    cli = cfg.get('companion_cli') or os.path.join(os.path.expanduser('~'), '.codex', 'mai-codex-gauge', 'src', 'cli.mjs')
    if cfg.get('companion') is False or not os.path.isfile(cli) or not hasattr(orca, 'split'):
        return
    done = state.setdefault('companions', {})
    ids = codex_ids_from_sessions(cfg.get('sessions_dir') or os.path.join(os.path.expanduser('~'), '.mai', 'sessions'))
    inc = {t.get('handle'): t.get('incarnationId', '') for t in terminals or [] if isinstance(t, dict)}
    for handle, sid in core.need_companion(terminals, sessions, ids, done, cfg.get('only_handles')):
        cmd = '%s "%s" watch --session %s' % (cfg.get('node') or 'node', cli, sid)
        if dry:
            log('DRY companion %s %s' % (handle, cmd))
            continue
        try:
            ok = orca.split(handle, cmd)
        except (RuntimeError, OSError, subprocess.SubprocessError) as e:
            ok = False
            log('COMPANION error %s %s' % (handle, e))
        log('COMPANION %s session=%s opened=%s' % (handle, sid, ok))
        done[handle] = inc.get(handle, '')      # once per incarnation, even if it failed: no retry storm


def safe_send(orca, handle, text, wait_s=600, step_s=5, sleep=time.sleep, log=print):
    """Send one line into another session only when nobody is typing there (10/20: a report pasted into the lead pane
    while the owner was typing in it). The prompt must read empty twice, step_s apart, with the same screen both times,
    and once more right before the send. Waits up to wait_s. Returns 0 sent, 4 still busy, 2 pane not found or error."""
    eng = next((t.get('agentIdentity') for t in orca.terminals() if t.get('handle') == handle), None)
    if eng not in ('claude', 'codex'):
        log('no claude or codex pane %s' % handle)
        return 2
    waited = 0.0
    while True:
        try:
            a = orca.screen(handle)
            sleep(step_s)
            b = orca.screen(handle)
        except (RuntimeError, OSError, subprocess.SubprocessError) as e:
            log('read failed: %s' % e)
            return 2
        now = dt.datetime.now(dt.timezone.utc)
        quiet = a == b and not core.screen_state(eng, a, now)['typing'] and not core.screen_state(eng, b, now)['typing']
        if quiet:
            try:
                last = orca.screen(handle)
            except (RuntimeError, OSError, subprocess.SubprocessError) as e:
                log('read failed: %s' % e)
                return 2
            if last == b:
                ok = orca.send(handle, core.one_line(text))
                log('sent' if ok else 'send refused')
                return 0 if ok else 2
        waited += step_s
        if waited >= wait_s:
            log('not quiet for %d s (someone typing or output still moving), nothing sent' % waited)
            return 4
        sleep(step_s)
        waited += step_s


def run(home=None, limits_path=None, once=False, dry=False, clock=None, orca=None, sleep=time.sleep):
    home = home_dir(home)
    os.makedirs(home, exist_ok=True)
    log = Log(os.path.join(home, 'resume.log'))
    cfg = core.merged(load_json(os.path.join(home, 'config.json'), {}))
    cfg.setdefault('targets_file', os.path.join(home, 'targets.txt'))
    limits_path = limits_path or os.path.join(os.path.expanduser('~'), '.mai', 'limits.json')
    clock = clock or (lambda: dt.datetime.now(dt.timezone.utc))
    lock = None if once else take_lock(cfg.get('lock_port', LOCK_PORT))
    if not once and lock is None:
        log('another mai-resume is running (port %s busy); exiting' % cfg.get('lock_port', LOCK_PORT))
        return 3
    state_path = os.path.join(home, 'state.json')
    state = load_json(state_path, {})
    if orca is None:
        exe = find_orca(cfg)
        if not exe:
            log('orca CLI not found; set "orca" in config.json')
            return 2
        orca = Orca(exe)
    if not once:
        hb, clean = state.get('heartbeat'), state.get('clean_exit', True)
        if hb and not clean:
            gap = (clock() - core._parse_iso(hb)).total_seconds()
            if gap > 3 * cfg['poll_s']:
                notify(cfg, core.one_line('[mai-resume] restarted after stopping unexpectedly; no watch for %d min '
                                          '(last heartbeat %s)' % (gap // 60, hb)), log)
        log('start pid=%d dry=%s orca=%s' % (os.getpid(), dry, getattr(orca, 'exe', 'fake')))
    state['clean_exit'] = False
    try:
        while True:
            try:
                state = round_once(orca, state, cfg, limits_path, clock(), log, dry)
                state['clean_exit'] = False
            except Exception as e:                               # one bad round must not kill the guard
                log('ROUND error %r' % e)
                state['heartbeat'] = core._iso(clock())
            state['pid'] = os.getpid()
            save_json(state_path, state)
            if once:
                state['clean_exit'] = True
                save_json(state_path, state)
                return 0
            sleep(cfg['poll_s'])
    except KeyboardInterrupt:
        state['clean_exit'] = True
        save_json(state_path, state)
        log('stop (interrupted)')
        return 0
    finally:
        if lock:
            lock.close()


def status(home=None, clock=None):
    """Print the guard's state. Exit 0 healthy, 1 heartbeat stale or missing."""
    home = home_dir(home)
    cfg = core.merged(load_json(os.path.join(home, 'config.json'), {}))
    st = load_json(os.path.join(home, 'state.json'), {})
    clock = clock or (lambda: dt.datetime.now(dt.timezone.utc))
    hb = st.get('heartbeat')
    age = (clock() - core._parse_iso(hb)).total_seconds() if hb else None
    ok = age is not None and age <= 3 * cfg['poll_s']
    print('heartbeat: %s (%s s ago) pid=%s sessions=%s pending=%d windows=%d -> %s' % (
        hb, int(age) if age is not None else '?', st.get('pid'), st.get('sessions'), len(st.get('pending') or []),
        len(st.get('windows') or {}), 'ok' if ok else 'STALE'))
    return 0 if ok else 1
