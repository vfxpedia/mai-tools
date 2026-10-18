import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
from support import Fixture


class CliTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('mai_code.cli'),'CLI missing')
        self.f=Fixture();self.addCleanup(self.f.close)

    def call(self,*args):
        return subprocess.run([sys.executable,'-B','-m','mai_code',*map(str,args)],cwd=Path(__file__).resolve().parents[1],capture_output=True,text=True,encoding='utf-8')

    def test_help_prepare_status_no_model(self):
        self.assertEqual(self.call('--help').returncode,0)
        result=self.call('prepare',self.f.save(),'--data-root',self.f.root/'data')
        self.assertEqual(result.returncode,0,result.stderr)
        run=json.loads(result.stdout)['run']
        status=self.call('status',run)
        self.assertEqual(json.loads(status.stdout)['status'],'prepared')
        self.assertEqual(list((Path(run)/'attempts').iterdir()),[])

    def test_invalid_exit_two(self):
        result=self.call('prepare',self.f.root/'missing')
        self.assertEqual(result.returncode,2)

    def test_packaging_contract(self):
        import tomllib
        path=Path(__file__).resolve().parents[1]/'pyproject.toml'
        self.assertTrue(path.is_file(),'installable package metadata missing')
        project=tomllib.loads(path.read_text())['project']
        self.assertEqual(project['scripts']['mai-code'],'mai_code.cli:main')
        self.assertEqual(project.get('dependencies',[]),[])
        self.assertEqual(project['version'],'0.1.0a1')

if __name__=='__main__':unittest.main()
