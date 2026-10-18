"""Known-answer tests for the hygiene gate: planted bad lines must be found, clean lines must pass, an empty scan must fail.
Run: python -I common/tests/test_hygiene.py
"""
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))
import hygiene_check as H  # noqa: E402

B = chr(92)


def rules(text, deny=()):
    return sorted({r for _, _, r, _ in H.scan_text('x', text, deny)})


class HygieneTests(unittest.TestCase):
    def test_personal_paths_are_found_in_every_notation(self):
        self.assertEqual(rules('C:/Users/realname/lab'), ['personal_path'])
        self.assertEqual(rules('C:' + B + 'Users' + B + 'realname' + B + 'lab'), ['personal_path'])
        self.assertEqual(rules('/home/realname/lab'), ['personal_path'])
        self.assertEqual(rules('/Users/realname/lab'), ['personal_path'])

    def test_placeholder_users_pass(self):
        for t in ('C:/Users/user/lab', '/home/user/lab', '/Users/someone/x', 'C:/Users/Public/x', 'C:/Users/u/.mai', '/Users/a/b'):
            self.assertEqual(rules(t), [], t)

    def test_email_and_secrets(self):
        self.assertEqual(rules('write to a.b@realdomain.org'), ['email'])
        self.assertEqual(rules('t = ' + 'ghp_' + 'A' * 30), ['secret'])
        self.assertEqual(rules('k = ' + 'sk-' + 'a1' * 15), ['secret'])
        self.assertEqual(rules('id AKIA' + 'ABCDEFGHIJKLMNOP'), ['secret'])
        self.assertEqual(rules('-----BEGIN ' + 'RSA PRIVATE KEY-----'), ['secret'])

    def test_em_dash_and_denied_host(self):
        self.assertEqual(rules('a ' + chr(0x2014) + ' b'), ['em_dash'])
        self.assertEqual(rules('run on MyBox now', deny=['mybox']), ['hostname'])
        self.assertEqual(rules('run on MyBox now'), [])

    def test_placeholder_mail_domains_pass(self):
        self.assertEqual(rules('user@example.com and x@host.local'), [])

    def test_clean_text_passes(self):
        self.assertEqual(rules('plain text, a path like tools/mai-watch/mai_watch and C:/lab/runs'), [])

    def test_empty_scan_fails(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, 'blob.bin')
            with open(p, 'wb') as f:
                f.write(b'\xff\xfe\x00')
            self.assertEqual(H.main([p]), 1)

    def test_planted_file_fails_and_clean_file_passes(self):
        with tempfile.TemporaryDirectory() as d:
            bad = os.path.join(d, 'bad.md')
            ok = os.path.join(d, 'ok.md')
            with open(bad, 'w', encoding='utf-8') as f:
                f.write('see /home/realname/x\n')
            with open(ok, 'w', encoding='utf-8') as f:
                f.write('nothing personal here\n')
            self.assertEqual(H.main([bad]), 1)
            self.assertEqual(H.main([ok]), 0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
