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

    def test_stale_limits_send_only_the_notice_never_the_stop(self):
        fresh = limits(88, at=T0)
        stale = limits(99, at=T0 - dt.timedelta(minutes=20))
        self.assertEqual(tick({}, T0, fresh, [term('a')])[1], [])
        st, sends, _ = tick({}, T0, stale, [term('a')])
        self.assertEqual([m for _, _, m in sends], ['notice|a|claude|five_hour|' + core._iso(RESET)])
        self.assertIn('keep doing the current work', sends[0][1])
        self.assertEqual(st['windows'], {}, 'a stale reading must not hold the window')


WEEK_RESET = T0 + dt.timedelta(days=5)


def week(pct, stale=False, now=T0):
    at = now - dt.timedelta(minutes=20) if stale else now
    return limits(pct, at=at, reset=WEEK_RESET, window='seven_day', account='codex:x')


class Weekly(unittest.TestCase):
    """seven_day (lead 10/20): stop only at 98 %; 85 to 97 % is a keep-working notice; a stale reading never stops."""
    cx = [term('cx', 'codex')]

    def kinds(self, lim):
        st, sends, _ = tick({}, T0, lim, self.cx)
        return [m.split('|', 1)[0] for _, _, m in sends], st, sends

    def test_84_sends_nothing(self):
        self.assertEqual(self.kinds(week(84))[0], [])

    def test_85_is_a_notice_without_hold(self):
        kinds, st, sends = self.kinds(week(85))
        self.assertEqual(kinds, ['notice'])
        self.assertIn('Do not stop', sends[0][1])
        self.assertNotIn('lead', sends[0][1])
        self.assertEqual(st['windows'], {})

    def test_97_is_still_a_notice_and_only_once_per_window(self):
        kinds, st, _ = self.kinds(week(97))
        self.assertEqual(kinds, ['notice'])
        _, sends, _ = tick(st, T0 + dt.timedelta(minutes=1), week(97), self.cx)
        self.assertEqual(sends, [])

    def test_98_is_the_stop_and_holds_until_reset(self):
        kinds, st, sends = self.kinds(week(98))
        self.assertEqual(kinds, ['warn'])
        self.assertIn('and stop', sends[0][1])
        self.assertEqual(list(st['windows']), ['codex|seven_day|' + core._iso(WEEK_RESET)])

    def test_stale_98_is_only_a_notice_marked_old(self):
        kinds, st, sends = self.kinds(week(98, stale=True))
        self.assertEqual(kinds, ['notice'])
        self.assertIn('reading is old', sends[0][1])
        self.assertEqual(st['windows'], {})

    def test_notice_then_fresh_98_still_stops(self):
        _, st, _ = self.kinds(week(90))
        later = T0 + dt.timedelta(hours=1)
        _, sends, _ = tick(st, later, week(98, now=later), self.cx)
        self.assertEqual([m.split('|', 1)[0] for _, _, m in sends], ['warn'])

    def test_stopped_window_gets_no_notice_when_the_reading_goes_stale(self):
        _, st, _ = self.kinds(week(98))
        st['sent'] = {p['id']: p['since'] for p in st['pending']}
        st['pending'] = []
        _, sends, _ = tick(st, T0 + dt.timedelta(hours=1), week(98), self.cx)   # same reading, now 1 h old
        self.assertEqual(sends, [])


class WarnMore(unittest.TestCase):

    def test_pane_ids_match_whole_or_by_start(self):
        self.assertTrue(core.picked('term_2580fc05-e7ff', ['2580fc05']))
        self.assertTrue(core.picked('term_2580fc05-e7ff', ['term_2580fc05-e7ff']))
        self.assertFalse(core.picked('term_bdb042be-187b', ['2580fc05']))
        self.assertFalse(core.picked('term_x', ['']))
        self.assertEqual(core.read_targets('# note\n 2580fc05  # lead\n\nbdb042be\n'), ['2580fc05', 'bdb042be'])
        self.assertEqual(core.discover([term('a')], only=[]), [], 'an empty list is no pane, not every pane')

    def test_resume_and_keepalive_never_ask_for_new_work(self):
        m = core.DEFAULTS['messages']
        self.assertNotIn('next task', m['resume'])
        self.assertIn('start nothing', m['resume'])
        self.assertIn('carry on with it unchanged', m['keepalive'])   # 10/26: never an order to stop work in progress
        self.assertIn('start nothing new', m['keepalive'])
        self.assertNotIn('Do not start any work', m['keepalive'])

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

    def test_given_up_message_is_not_queued_again(self):
        typing = {'a': '❯ still typing'}
        st, _, _ = tick({}, T0, limits(94), [term('a')], typing)
        st, _, _ = tick(st, T0 + dt.timedelta(seconds=1801), limits(94, at=T0 + dt.timedelta(seconds=1801)), [term('a')], typing)
        later = T0 + dt.timedelta(seconds=1900)
        st, sends, logs = tick(st, later, limits(95, at=later), [term('a')])        # prompt now empty, same window
        self.assertEqual(sends, [], 'the warn given up at 30 min must not come back (10/20 12:27 then 13:07)')
        self.assertEqual(st['pending'], [])

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


    def test_pane_booked_by_limits_and_screen_gets_one_resume(self):
        reset = dt.datetime(2026, 10, 20, 10, 10, tzinfo=UTC)          # 19:10 in Seoul
        now = dt.datetime(2026, 10, 20, 9, 0, tzinfo=UTC)
        hit = {'a': "x\n⎿  You've hit your session limit · resets 7:10pm (Asia/Seoul)\n❯ \n"}
        st, _, _ = tick({}, now, limits(97, at=now, reset=reset), [term('a')])
        st['sent'] = {p['id']: p['since'] for p in st['pending']}
        st['pending'] = []
        st, _, logs = tick(st, now + dt.timedelta(minutes=1), limits(97, at=now, reset=reset), [term('a')], hit)
        self.assertTrue(any(l.startswith('HIT a ') for l in logs))
        late = reset + dt.timedelta(minutes=3)
        st, sends, _ = tick(st, late, limits(3, at=late, reset=reset + dt.timedelta(hours=5)), [term('a')])
        self.assertEqual([h for h, _, i in sends if i.startswith('resume')], ['a'], 'one resume, not one per booking (10/20 rl)')


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

    # A working Claude pane's tail as Orca read it on 10/26 (super2 in the middle of a tool run), names removed.
    WORKING_TAIL = '\n'.join([
        '     2>/dev/null > "$S"; python - "$S" <<…',
        '· Processing… (6m 43s · ↓ 14.0k tokens)',
        'context  ━━━━━━────┃─  54% 521k/1.0M  ● compact in ~13 turns       [-]',
        '5 hours  ━━━━━━━━────  68% [~70%]     ● enough (24m)',
        'turn     $1.75             [$409.8]   ● 14 req · reads 7.2M',
        '────────────────────────────────────────────────── pane ─',
        '❯ ',
        '──────────────────────────────────────────────────────────',
        '  ⏵⏵ auto mode on (shift+tab to cycle) · ← 1 agent',
    ]) + '\n'

    def test_real_working_tail_reads_busy(self):
        st = core.screen_state('claude', self.WORKING_TAIL, T0, KST)
        self.assertEqual((st['busy'], st['typing'], st['done_at']), (True, False, None))

    def deferred(self):
        """10/26 shape: idle at +55 min, but text sits in the prompt, so the nudge waits in pending."""
        idle = {'a': done_screen((T0 - dt.timedelta(minutes=1)).astimezone(KST))}
        st, _, _ = self.k({}, T0, idle)
        st, sends, _ = self.k(st, T0 + dt.timedelta(minutes=55), {'a': {'text': idle['a'], 'prompt_trailing': 0}})
        self.assertEqual((sends, [p['id'].split('|')[0] for p in st['pending']]), ([], ['keep']))
        return st, idle

    def test_waiting_nudge_is_dropped_when_the_pane_is_now_working(self):
        st, _ = self.deferred()
        st, sends, logs = self.k(st, T0 + dt.timedelta(minutes=82), {'a': self.WORKING_TAIL})
        self.assertEqual(sends, [], '10/26 15:46 -> 16:13: a nudge decided while idle must not land in work')
        self.assertEqual(st['pending'], [])
        self.assertTrue(any(l.startswith('DROP keep|') and 'is working' in l for l in logs), logs)

    def test_waiting_nudge_is_dropped_after_a_newer_turn(self):
        st, _ = self.deferred()
        newer = {'a': done_screen((T0 + dt.timedelta(minutes=70)).astimezone(KST))}
        st, sends, logs = self.k(st, T0 + dt.timedelta(minutes=72), newer)
        self.assertEqual([i for _, _, i in sends if i.startswith('keep')], [])
        self.assertTrue(any('finished a newer turn' in l for l in logs), logs)

    def test_waiting_nudge_still_goes_when_the_pane_is_still_idle_on_the_same_turn(self):
        st, idle = self.deferred()
        st, sends, _ = self.k(st, T0 + dt.timedelta(minutes=58), idle)
        self.assertEqual([i.split('|')[0] for _, _, i in sends], ['keep'])

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
