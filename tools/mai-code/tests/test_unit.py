import copy
import importlib.util
import sys
import unittest
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parent)]
from support import Fixture, git


class UnitTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('mai_code'), 'unit preparation is not implemented')
        from mai_code import unit
        self.api = unit
        self.f = Fixture()
        self.addCleanup(self.f.close)

    def load(self):
        return self.api.load_unit(self.f.save())

    def test_valid_unchanged_git(self):
        before = git(self.f.work, 'status', '--porcelain'), git(self.f.work, 'rev-parse','HEAD')
        packet = self.api.prepare_packet(self.load())
        self.assertEqual(packet['fingerprint']['head'], before[1])
        self.assertEqual((git(self.f.work,'status','--porcelain'), git(self.f.work,'rev-parse','HEAD')), before)
        self.assertEqual(packet['unit']['unit_id'], 'fixture-one')

    def test_invalid_contracts(self):
        original = copy.deepcopy(self.f.unit)
        changes = [{'inputs':[]}, {'test_argv':[]}, {'surprise':True}, {'outputs':['x','x']}, {'outputs':['../escape']}, {'workspace':'Z:\\foreign' if sys.platform != 'win32' else '/foreign/path'}, {'engines':{}}, {'unit_id':'../escape'}]
        for change in changes:
            with self.subTest(change=change):
                self.f.unit=copy.deepcopy(original); self.f.unit.update(change)
                with self.assertRaises(ValueError): self.api.prepare_packet(self.load())

    def test_wrong_sha(self):
        self.f.unit['inputs'][0]['sha256']='0'*64
        with self.assertRaisesRegex(ValueError,'hash'): self.api.prepare_packet(self.load())

    def test_primary_refused(self):
        self.f.unit['workspace']=str(self.f.primary)
        with self.assertRaisesRegex(ValueError,'primary'): self.api.prepare_packet(self.load())

    def test_unrelated_dirty(self):
        (self.f.work/'unrelated.txt').write_text('not owned')
        with self.assertRaisesRegex(ValueError,'dirty'): self.api.prepare_packet(self.load())

    def test_escape_symlink(self):
        outside=self.f.root/'outside'; outside.mkdir()
        link=self.f.work/'link'
        try: link.symlink_to(outside, target_is_directory=True)
        except OSError:
            if sys.platform!='win32': raise
            import subprocess
            subprocess.run(['cmd','/c','mklink','/J',str(link),str(outside)],check=True,capture_output=True)
        self.f.unit['outputs']=['link/escaped.py']
        with self.assertRaisesRegex(ValueError,'escape'): self.api.prepare_packet(self.load())

if __name__=='__main__': unittest.main()
