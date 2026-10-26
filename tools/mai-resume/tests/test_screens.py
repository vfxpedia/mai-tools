"""Decisions on real pane screens: tests/screens holds `orca terminal read --screen --json` captures (tail and tailRows,
cut to the last rows, local paths dropped) from Claude Code 2.1.310 and Codex on Orca 1.4.241, 10/27."""
import datetime as dt
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from mai_resume import core, runner  # noqa: E402

HERE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'screens')
KST = dt.timezone(dt.timedelta(hours=9))
NOW = dt.datetime(2026, 10, 27, 1, 5, tzinfo=KST)


def screen(name):
    with open(os.path.join(HERE, name + '.json'), encoding='utf-8') as f:
        return runner.screen_of(json.load(f))


def held(name, engine='claude'):
    ss = core.screen_state(engine, screen(name), NOW, KST)
    return tuple(core.holds(k + '|x', engine, ss) for k in ('keep', 'warn', 'resume'))


class FakeOrca:
    def __init__(self, name, engine):
        self.name, self.engine, self.sent = name, engine, []

    def terminals(self):
        return [{'handle': 'h', 'agentIdentity': self.engine}]

    def screen(self, handle):
        return screen(self.name)

    def send(self, handle, text):
        self.sent.append(text)
        return True


def safe_send(name, engine='claude'):
    o = FakeOrca(name, engine)
    rc = runner.safe_send(o, 'h', 'report', wait_s=10, step_s=5, sleep=lambda s: None, log=lambda s: None)
    return rc, o.sent


class RealScreens(unittest.TestCase):
    def test_the_captures_are_what_they_say(self):
        # guard the fixtures themselves: the prompt rows and trailing spaces the cases below depend on
        self.assertEqual(screen('claude_hint_empty')['prompt_trailing'], 0)
        self.assertIn('Try "', screen('claude_hint_empty')['text'])
        self.assertEqual(screen('claude_typed_resting')['prompt_trailing'], 0)
        self.assertEqual(screen('claude_busy_empty')['prompt_trailing'], 1)
        for name in ('claude_queued_empty', 'claude_queued_typed'):
            self.assertIn('ctrl+enter to send now', screen(name)['text'])
            self.assertEqual(screen(name)['prompt_trailing'], 0, name)

    # (a) 10/27 lead: a new pane's empty prompt shows the Try hint with 0 trailing spaces and read as typing forever
    def test_a_empty_pane_with_the_hint_gets_messages(self):
        self.assertEqual(held('claude_hint_empty'), (False, False, False))
        self.assertEqual(safe_send('claude_hint_empty'), (0, ['report']))

    # (b) text really typed: a bare marker with 0 trailing spaces
    def test_b_typed_text_holds_everything(self):
        self.assertEqual(held('claude_typed_resting'), (True, True, True))
        self.assertEqual(safe_send('claude_typed_resting'), (4, []))

    # (c) 10/27 lead: a message the owner sent during a long turn waits in the queue; the prompt under it reads bare 0
    # whether or not text is typed (both captured), so it is taken as not typing: one more message joins the queue
    def test_c_queued_message_does_not_hold_a_report(self):
        self.assertTrue(core.screen_state('claude', screen('claude_queued_empty'), NOW, KST)['queued'])
        self.assertEqual(held('claude_queued_empty'), (True, False, False), 'a keep-alive still waits: the pane works')
        self.assertEqual(safe_send('claude_queued_empty'), (0, ['report']))

    def test_c_queue_hint_in_the_prompt_row_is_not_typing(self):
        s = screen('claude_busy_empty')
        s = {'text': s['text'] + '\n❯\xa0Press up to edit queued messages\n' + '─' * 20,   # lead's 10/27 row
             'prompt_trailing': 0}
        self.assertFalse(core.screen_state('claude', s, NOW, KST)['typing'])

    def test_working_pane_with_empty_prompt(self):
        self.assertEqual(held('claude_busy_empty'), (True, False, False))
        self.assertEqual(safe_send('claude_busy_empty'), (0, ['report']))

    def test_resting_pane_after_turns(self):
        self.assertEqual(held('claude_resting_after_turn'), (False, False, False))
        self.assertEqual(safe_send('claude_resting_after_turn'), (0, ['report']))

    # 00:42 reviewer: the keep-alive text itself came back as the gray suggestion in the prompt row
    def test_keepalive_text_as_suggestion_is_not_typing(self):
        s = screen('claude_resting_after_turn')
        rows = s['text'].split('\n')
        i = max(j for j, r in enumerate(rows) if r.strip().startswith('❯'))
        rows[i] = '❯\xa0[캐시 유지] 「대기」 한 단어로만 답하세요'
        s = {'text': '\n'.join(rows), 'prompt_trailing': 0}
        ss = core.screen_state('claude', s, NOW, KST)
        self.assertEqual((ss['typing'], ss['shown_text']), (False, True))

    # (d) a Codex pane: its placeholder is not typing (regression guard; 00:52 lead measured a working one)
    def test_d_codex_pane_gets_messages(self):
        self.assertEqual(held('codex_idle', 'codex'), (False, False, False))
        self.assertEqual(safe_send('codex_idle', 'codex'), (0, ['report']))


if __name__ == '__main__':
    unittest.main()
