"""Known-answer tests for the decisions in mai_resume.core (fake time, fake limits, fake terminal list, fake screens)."""
import datetime as dt
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from mai_resume import core  # noqa: E402

UTC = dt.timezone.utc
KST = dt.timezone(dt.timedelta(hours=9))
T0 = dt.datetime(2026, 10, 20, 0, 0, 0, tzinfo=UTC)
RESET = T0 + dt.timedelta(hours=2)
IDLE_CLAUDE = 'some output\n❯ \n  auto mode on'
IDLE_CODEX = 'output\n› Ask Codex to do anything\n  GPT'


def ms(t):
    return int(t.timestamp() * 1000)


def limits(pct, at=T0, reset=RESET, window='five_hour', account='default'):
    return {account: {window: [{'at': ms(at - dt.timedelta(minutes=30)), 'pct': 10, 'reset': reset.strftime('%Y-%m-%dT%H:%M:%S.000Z')},
                               {'at': ms(at), 'pct': pct, 'reset': reset.strftime('%Y-%m-%dT%H:%M:%S.000Z')}]}}


def term(handle, engine='claude', connected=True, writable=True):
    return {'handle': handle, 'agentIdentity': engine, 'connected': connected, 'writable': writable, 'title': handle}


def tick(state, now, lim, terms, screens=None):
    if screens is None:
        screens = {t['handle']: (IDLE_CODEX if t.get('agentIdentity') == 'codex' else IDLE_CLAUDE) for t in terms}
    return core.tick(state, now, lim, terms, screens, {}, local_tz=KST)


class Warn(unittest.TestCase):
    def test_below_threshold_sends_nothing(self):
        st, sends, _ = tick({}, T0, limits(92), [term('a')])
        self.assertEqual(sends, [])
        self.assertEqual(st['windows'], {})

    def test_crossing_warns_every_claude_session_once_and_not_codex(self):
        terms = [term('a'), term('b'), term('x', 'codex')]
        st, sends, logs = tick({}, T0, limits(94), terms)
        self.assertEqual(sorted(h for h, _, _ in sends), ['a', 'b'])
        self.assertTrue(all('\n' not in t and '94%' in t for _, t, _ in sends))
        self.assertTrue(any(l.startswith('WARN claude|five_hour|') for l in logs))
        st2, sends2, _ = tick(st, T0 + dt.timedelta(minutes=1), limits(95), terms)
        self.assertEqual(sends2, [], 'same window must not be warned twice')

    def test_session_that_appears_later_in_the_window_gets_the_warning(self):
        st, sends, _ = tick({}, T0, limits(94), [term('a')])
        st, sends, _ = tick(st, T0 + dt.timedelta(minutes=5), limits(96), [term('a'), term('new')])
        self.assertEqual([h for h, _, _ in sends], ['new'])

    def test_after_reset_the_old_window_does_not_warn(self):
        st, sends, _ = tick({}, RESET + dt.timedelta(minutes=1), limits(99), [term('a')])
        self.assertEqual(sends, [])

    def test_stale_limits_warn_early_fresh_do_not(self):
        fresh = limits(88, at=T0)
        stale = limits(88, at=T0 - dt.timedelta(minutes=20))
        self.assertEqual(tick({}, T0, fresh, [term('a')])[1], [])
        self.assertEqual([h for h, _, _ in tick({}, T0, stale, [term('a')])[1]], ['a'])

    def test_only_and_exclude_filters(self):
        terms = [term('a'), term('b'), term('c')]
        self.assertEqual([s['handle'] for s in core.discover(terms, only=['b'])], ['b'])
        self.assertEqual([s['handle'] for s in core.discover(terms, exclude=['b'])], ['a', 'c'])
        _, sends, _ = core.tick({}, T0, limits(94), terms, {t['handle']: IDLE_CLAUDE for t in terms}, {'only_handles': ['c']}, local_tz=KST)
        self.assertEqual([h for h, _, _ in sends], ['c'])

    def test_disconnected_or_unknown_panes_are_ignored(self):
        terms = [term('off', connected=False), term('ro', writable=False), {'handle': 'shell', 'connected': True, 'writable': True}]
        self.assertEqual(core.discover(terms), [])
        self.assertEqual(tick({}, T0, limits(99), terms)[1], [])


class Deliver(unittest.TestCase):
    def test_typing_prompt_waits_then_gets_it(self):
        typing = {'a': 'x\n❯ 한글 입력 중\n'}
        st, sends, _ = tick({}, T0, limits(94), [term('a')], typing)
        self.assertEqual(sends, [])
        self.assertEqual(len(st['pending']), 1)
        st, sends, _ = tick(st, T0 + dt.timedelta(minutes=1), limits(94), [term('a')])
        self.assertEqual([h for h, _, _ in sends], ['a'])
        self.assertEqual(st['pending'], [])

    def test_unreadable_screen_is_never_typed_into(self):
        st, sends, _ = tick({}, T0, limits(94), [term('a')], {})
        self.assertEqual(sends, [])
        self.assertEqual(len(st['pending']), 1)

    def test_give_up_after_the_limit(self):
        typing = {'a': '❯ still typing'}
        st, _, _ = tick({}, T0, limits(94), [term('a')], typing)
        st, sends, logs = tick(st, T0 + dt.timedelta(seconds=1801), limits(94), [term('a')], typing)
        self.assertEqual(sends, [])
        self.assertEqual(st['pending'], [])
        self.assertTrue(any(l.startswith('DROP warn|a|') for l in logs))

    def test_pane_gone_drops_its_message(self):
        st, _, _ = tick({}, T0, limits(94), [term('a')], {})
        st, sends, logs = tick(st, T0 + dt.timedelta(minutes=1), limits(94), [term('b')])
        self.assertNotIn('a', [h for h, _, _ in sends])
        self.assertTrue(any('pane gone' in l for l in logs))

    def test_busy_pane_is_sent_to_so_it_queues(self):
        busy = {'a': '✳ Working… (12s · esc to interrupt)\n❯ \n'}
        self.assertTrue(core.screen_state('claude', busy['a'], T0)['busy'])
        self.assertEqual([h for h, _, _ in tick({}, T0, limits(94), [term('a')], busy)[1]], ['a'])

    def test_message_text_is_one_line(self):
        cfg = {'messages': {'warn': 'line one\nline two\n\n {pct}%'}}
        _, sends, _ = core.tick({}, T0, limits(94), [term('a')], {'a': IDLE_CLAUDE}, cfg, local_tz=KST)
        self.assertEqual(sends[0][1], 'line one line two 94%')


class Resume(unittest.TestCase):
    def test_resume_after_reset_plus_grace_once_to_warned_sessions_only(self):
        st, _, _ = tick({}, T0, limits(94), [term('a'), term('b')])
        terms = [term('a'), term('b'), term('late')]
        st, sends, _ = tick(st, RESET + dt.timedelta(minutes=2), limits(5, at=RESET + dt.timedelta(minutes=2)), terms)
        self.assertEqual([s for s in sends if s[2].startswith('resume')], [], 'not before reset + 3 min')
        st, sends, logs = tick(st, RESET + dt.timedelta(minutes=3), limits(5, at=RESET + dt.timedelta(minutes=3)), terms)
        self.assertEqual(sorted(h for h, _, i in sends if i.startswith('resume')), ['a', 'b'])
        self.assertTrue(any(l.startswith('RESUME claude|five_hour|') for l in logs))
        st, sends, _ = tick(st, RESET + dt.timedelta(minutes=4), limits(5), terms)
        self.assertEqual(sends, [], 'resume is sent once')

    def test_screen_hit_books_a_resume_without_the_limits_file(self):
        now = dt.datetime(2026, 10, 20, 9, 0, tzinfo=UTC)            # 18:00 in Seoul
        hit = {'a': "x\n⎿  You've hit your session limit · resets 7:10pm (Asia/Seoul)\n❯ \n"}
        st, sends, logs = tick({}, now, {}, [term('a')], hit)
        self.assertEqual(sends, [])
        self.assertTrue(any(l.startswith('HIT a claude|hit:session|2026-10-20T10:10:00Z') for l in logs))
        st, sends, _ = tick(st, dt.datetime(2026, 10, 20, 10, 12, 59, tzinfo=UTC), {}, [term('a')])
        self.assertEqual(sends, [])
        st, sends, _ = tick(st, dt.datetime(2026, 10, 20, 10, 13, 0, tzinfo=UTC), {}, [term('a')])
        self.assertEqual([(h, i.split('|')[0]) for h, _, i in sends], [('a', 'resume')])


class Parse(unittest.TestCase):
    def test_reset_times(self):
        now = dt.datetime(2026, 10, 20, 9, 0, tzinfo=UTC)            # 18:00 KST
        self.assertEqual(core.parse_reset('7:10pm', 'Asia/Seoul', now), dt.datetime(2026, 10, 20, 19, 10, tzinfo=KST))
        self.assertEqual(core.parse_reset('1:10am', 'Asia/Seoul', now), dt.datetime(2026, 10, 21, 1, 10, tzinfo=KST))
        self.assertEqual(core.parse_reset('Oct 24, 8pm', 'Asia/Seoul', now), dt.datetime(2026, 10, 24, 20, 0, tzinfo=KST))
        self.assertEqual(core.parse_reset('12:30am', 'Asia/Seoul', now), dt.datetime(2026, 10, 21, 0, 30, tzinfo=KST))
        self.assertIsNone(core.parse_reset('soon', 'Asia/Seoul', now))
        self.assertIsNone(core.parse_reset('7pm', 'Mars/Base', now))

    def test_the_three_real_wordings(self):
        now = dt.datetime(2026, 9, 15, 0, 0, tzinfo=UTC)
        for text, what in (("You've hit your session limit · resets 9:30pm (Asia/Seoul)", 'session'),
                           ("You've hit your weekly limit · resets Sep 19, 8pm (Asia/Seoul)", 'weekly'),
                           ("You've hit your Fable 5 limit · resets Sep 19, 8pm (Asia/Seoul)", 'fable 5')):
            self.assertEqual(core.screen_state('claude', text, now)['hit'][0], what, text)

    def test_prompt_reading(self):
        self.assertFalse(core.screen_state('claude', IDLE_CLAUDE, T0)['typing'])
        self.assertTrue(core.screen_state('claude', '❯ hello', T0)['typing'])
        # a fresh pane shows a hint in the empty prompt (seen 10/20 in a real pane)
        self.assertFalse(core.screen_state('claude', '❯ Try "fix typecheck errors"', T0)['typing'])
        self.assertTrue(core.screen_state('claude', '❯ Try "fix it" and also this', T0)['typing'])
        # Orca hides unsubmitted text; the bare prompt row's trailing space (1 empty, 0 typed) tells (measured 10/20)
        self.assertFalse(core.screen_state('claude', {'text': '❯', 'prompt_trailing': 1}, T0)['typing'])
        self.assertTrue(core.screen_state('claude', {'text': '❯', 'prompt_trailing': 0}, T0)['typing'])
        self.assertFalse(core.screen_state('claude', {'text': '❯', 'prompt_trailing': None}, T0)['typing'])
        # a dialog (folder trust) has a selection arrow: read as busy prompt, never typed into
        self.assertTrue(core.screen_state('claude', ' ❯ No, exit\n   Yes, I trust this folder', T0)['typing'])
        self.assertFalse(core.screen_state('codex', IDLE_CODEX, T0)['typing'])
        self.assertTrue(core.screen_state('codex', '› fix the failing test', T0)['typing'])


def done_screen(t_local):
    """An idle Claude pane whose last turn ended at t_local (KST wall clock), as Claude Code shows it in Korean."""
    ap = '오전' if t_local.hour < 12 else '오후'
    h12 = t_local.hour % 12 or 12
    return '● idle\n✻ Brewed for 2s · done %s %d:%02d\n❯ \n' % (ap, h12, t_local.minute)


class Keepalive(unittest.TestCase):
    LOW = limits(10)

    def k(self, state, now, screens, terms=None):
        terms = terms or [term('a')]
        return core.tick(state, now, self.LOW, terms, screens, {}, local_tz=KST)

    def test_first_seen_starts_the_clock_only(self):
        st, sends, _ = self.k({}, T0, {'a': done_screen(T0.astimezone(KST))})
        self.assertEqual(sends, [])
        self.assertEqual(st['keepalive']['a'], '2026-10-20T00:00:00Z')

    def test_idle_pane_is_nudged_at_55_minutes_once(self):
        scr = {'a': done_screen((T0 - dt.timedelta(minutes=1)).astimezone(KST))}
        st, _, _ = self.k({}, T0, scr)
        st, sends, _ = self.k(st, T0 + dt.timedelta(minutes=54), scr)
        self.assertEqual(sends, [])
        st, sends, logs = self.k(st, T0 + dt.timedelta(minutes=55), scr)
        self.assertEqual([(h, i.split('|')[0]) for h, _, i in sends], [('a', 'keep')])
        self.assertIn('KEEPALIVE a', logs)
        st, sends, _ = self.k(st, T0 + dt.timedelta(minutes=56), scr)
        self.assertEqual(sends, [], 'one nudge per period')

    def test_working_pane_only_restarts_its_clock(self):
        busy = {'a': '✳ Working… (40s · esc to interrupt)\n❯ \n'}
        st, _, _ = self.k({}, T0, busy)
        st, sends, _ = self.k(st, T0 + dt.timedelta(minutes=55), busy)
        self.assertEqual(sends, [])
        self.assertEqual(st['keepalive']['a'], '2026-10-20T00:55:00Z')

    def test_a_newer_turn_end_counts_as_activity(self):
        st, _, _ = self.k({}, T0, {'a': done_screen((T0 - dt.timedelta(minutes=1)).astimezone(KST))})
        later = {'a': done_screen((T0 + dt.timedelta(minutes=30)).astimezone(KST))}
        st, sends, _ = self.k(st, T0 + dt.timedelta(minutes=55), later)
        self.assertEqual(sends, [], 'the pane worked at +30 min, so its cache is fresh')
        st, sends, _ = self.k(st, T0 + dt.timedelta(minutes=85), later)
        self.assertEqual([h for h, _, _ in sends], ['a'])

    def test_no_nudge_while_a_limit_window_is_held(self):
        scr = {'a': done_screen((T0 - dt.timedelta(minutes=1)).astimezone(KST))}
        st, sends, _ = core.tick({}, T0, limits(94), [term('a')], scr, {}, local_tz=KST)   # warned, reset at T0 + 2 h
        st, sends, _ = core.tick(st, T0 + dt.timedelta(minutes=70), limits(97), [term('a')], scr, {}, local_tz=KST)
        self.assertEqual([i for _, _, i in sends if i.startswith('keep')], [])

    def test_delivered_warning_renews_the_clock(self):
        scr = {'a': done_screen((T0 - dt.timedelta(minutes=1)).astimezone(KST))}
        st, _, _ = self.k({}, T0, scr)
        st, sends, _ = core.tick(st, T0 + dt.timedelta(minutes=30), limits(94), [term('a')], scr, {}, local_tz=KST)
        self.assertEqual(st['keepalive']['a'], '2026-10-20T00:30:00Z')

    def test_unknown_state_or_codex_gets_nothing(self):
        st, _, _ = self.k({}, T0, {'a': 'no done line here\n❯ \n', 'x': IDLE_CODEX}, [term('a'), term('x', 'codex')])
        st, sends, _ = self.k(st, T0 + dt.timedelta(hours=2), {'a': 'no done line here\n❯ \n', 'x': IDLE_CODEX},
                              [term('a'), term('x', 'codex')])
        self.assertEqual(sends, [])

    def test_typing_defers_the_nudge(self):
        idle = {'a': done_screen((T0 - dt.timedelta(minutes=1)).astimezone(KST))}
        st, _, _ = self.k({}, T0, idle)
        typing = {'a': {'text': idle['a'], 'prompt_trailing': 0}}
        st, sends, _ = self.k(st, T0 + dt.timedelta(minutes=55), typing)
        self.assertEqual(sends, [])
        self.assertEqual([p['id'].split('|')[0] for p in st['pending']], ['keep'])

    def test_done_line_parsing(self):
        now = dt.datetime(2026, 10, 20, 3, 0, tzinfo=UTC)      # 12:00 KST
        self.assertEqual(core.screen_state('claude', '· done 오전 11:42', now, KST)['done_at'],
                         dt.datetime(2026, 10, 20, 11, 42, tzinfo=KST))
        self.assertEqual(core.screen_state('claude', '· done 오후 11:42', now, KST)['done_at'],
                         dt.datetime(2026, 10, 19, 23, 42, tzinfo=KST), 'a later wall time means yesterday')
        self.assertEqual(core.screen_state('claude', '· done 12:05 am', now, KST)['done_at'],
                         dt.datetime(2026, 10, 20, 0, 5, tzinfo=KST))


class Codex(unittest.TestCase):
    def test_codex_window_warns_codex_sessions_only(self):
        lim = limits(96, window='seven_day', account='codex:ai-ws01-orca')
        lim.update(limits(10))
        _, sends, _ = tick({}, T0, lim, [term('a'), term('x', 'codex')])
        self.assertEqual([h for h, _, _ in sends], ['x'])


if __name__ == '__main__':
    unittest.main()
