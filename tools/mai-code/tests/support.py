"""Owned Git fixtures. No model calls or host configuration writes."""
import hashlib
import json
import subprocess
import tempfile
from pathlib import Path


def git(path, *args):
    return subprocess.check_output(['git', '-C', str(path), *args], text=True, encoding='utf-8').strip()


class Fixture:
    def __init__(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.primary = self.root / 'primary'
        self.primary.mkdir()
        git(self.primary, 'init', '-q')
        git(self.primary, 'config', 'user.name', 'Fixture')
        git(self.primary, 'config', 'user.email', 'fixture@example.invalid')
        (self.primary / 'paper.txt').write_text('TEST ONLY. Affine: y=w*x+b. Loss=(y-target)^2.', encoding='utf-8')
        (self.primary / 'fixed_test.py').write_text('import unittest,sys\nnegative="--negative" in sys.argv\nif negative: sys.argv.remove("--negative")\nclass Fixed(unittest.TestCase):\n def test_answer(self): self.assertEqual(0 if negative else 2+2,4)\nif __name__ == "__main__": unittest.main()\n', encoding='utf-8')
        git(self.primary, 'add', '.')
        git(self.primary, 'commit', '-qm', 'fixture baseline')
        self.work = self.root / 'owned space 유니코드 & work'
        git(self.primary, 'worktree', 'add', '-qb', 'unit-fixture', str(self.work))
        self.unit = dict(schema='mai-code-unit-v1', unit_id='fixture-one', issue_url='https://github.com/example/project/issues/1', workspace=str(self.work), inputs=[dict(path='paper.txt', sha256=hashlib.sha256((self.work/'paper.txt').read_bytes()).hexdigest(), references=['section 1'])], contract={'module': 'TEST ONLY affine', 'negative_test_id': '__main__.Fixed.test_answer', 'negative_failures': 1}, outputs=['analysis.json','plan.json','module.py'], engines={s: {'engine': 'codex'} for s in ('analyze','plan','implement')}, test_argv=['python','fixed_test.py'], test_framework='unittest', negative_control_argv=['python','fixed_test.py','--negative'])

    def save(self):
        path = self.root / 'unit.json'
        path.write_text(json.dumps(self.unit), encoding='utf-8')
        return path

    def close(self):
        self.temp.cleanup()
