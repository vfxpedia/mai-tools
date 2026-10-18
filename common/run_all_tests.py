"""Runs every tool's test files, each in its own isolated interpreter (python -I) from the tool's folder, and prints one line per file.

Exit code is 0 only when every file passed. A file that ran zero tests is a failure, so an empty run cannot look like success.
Usage: python common/run_all_tests.py [tool-name ...]
"""
import os
import re
import subprocess
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
SUITES = {
    'mai-approve': ['tests/test_schema_contract.py', 'tests/test_cli.py', 'tests/test_hardening.py'],
    'mai-watch': ['tests/test_mai_watch.py', 'tests/test_schema_contract.py'],
    'mai-tabs': ['tests/test_mai_tabs.py'],
    'common': ['tests/test_hygiene.py'],
}
# suites that are not Python: (folder, command, how to read the count)
NODE_SUITES = {
    'mai-codex-gauge': ('mods/mai-codex-gauge', ['node', '--test', 'tests/*.test.mjs']),
}


def run_file(tool, rel):
    cwd = os.path.join(ROOT, 'common') if tool == 'common' else os.path.join(ROOT, 'tools', tool)
    p = subprocess.run([sys.executable, '-I', rel], cwd=cwd, capture_output=True, text=True, encoding='utf-8', errors='replace')
    out = p.stdout + p.stderr
    ran = re.search(r'Ran (\d+) tests?', out)
    skipped = re.search(r'skipped=(\d+)', out)
    n = int(ran.group(1)) if ran else 0
    ok = p.returncode == 0 and n > 0
    return ok, n, int(skipped.group(1)) if skipped else 0, out


def run_node(name):
    folder, cmd = NODE_SUITES[name]
    p = subprocess.run(cmd, cwd=os.path.join(ROOT, folder), capture_output=True, text=True, encoding='utf-8', errors='replace')
    out = p.stdout + p.stderr
    get = lambda k: int((re.search(r'^\S* ?' + k + r' (\d+)', out, re.M) or [0, 0])[1])
    n, failed, sk = get('tests'), get('fail'), get('skipped')
    ok = p.returncode == 0 and n > 0 and failed == 0
    return ok, n, sk, out


def main(argv):
    wanted = argv or list(SUITES) + list(NODE_SUITES)
    bad = 0
    total = 0
    for tool in wanted:
        if tool in NODE_SUITES:
            ok, n, sk, out = run_node(tool)
            total += n
            print('%-4s %-12s %-34s tests=%d skipped=%d' % ('OK' if ok else 'FAIL', tool, ' '.join(NODE_SUITES[tool][1]), n, sk))
            if not ok:
                bad += 1
                print(chr(10).join(out.splitlines()[-25:]))
            continue
        if tool not in SUITES:
            print('unknown tool: ' + tool)
            return 2
        for rel in SUITES[tool]:
            ok, n, sk, out = run_file(tool, rel)
            total += n
            print('%-4s %-12s %-34s tests=%d skipped=%d' % ('OK' if ok else 'FAIL', tool, rel, n, sk))
            if not ok:
                bad += 1
                print('\n'.join(out.splitlines()[-25:]))
    print('files failed: %d, tests run: %d' % (bad, total))
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
