"""작업 tab: work.json carries mai-work's findings for the list given with --worklist, a probe answers at once, no list means 404,
and a broken list becomes an error document instead of a failed request."""
import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

from mai_watch import server, worklist

LEGACY = 'id\tsource\tpriority\tdue\towner\tevidence\tstatus\twhat\n'


def get(srv, path):
    with urllib.request.urlopen('http://127.0.0.1:%d/%s' % (srv.server_address[1], path), timeout=10) as r:
        return r.status, json.loads(r.read().decode('utf-8'))


class WorklistTabTest(unittest.TestCase):
    def serve(self, work):
        srv = server.make_server(None, 0, worklist=work)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        return srv

    def test_findings_probe_and_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = os.path.join(tmp, 'WORKLIST.tsv')
            with open(p, 'w', encoding='utf-8', newline='') as f:
                f.write(LEGACY + 'A1\tchat\tP1\tat:2020-01-01T00:00\tbob\t-\topen\tlong overdue\n')
            srv = self.serve(worklist.Worklist(p))
            code, d = get(srv, 'work.json?probe=1')
            self.assertEqual((code, d), (200, {'schema': 'mai-work-check-v1', 'probe': True}))
            code, d = get(srv, 'work.json')
            self.assertEqual(d['schema'], 'mai-work-check-v1')
            self.assertEqual([(f['rule'], f['id']) for f in d['findings']], [('C1', 'A1')])
            self.assertEqual(d['items'][0]['due'], 'passed')
            w = worklist.Worklist(os.path.join(tmp, 'missing.tsv'))
            self.assertIn('error', w.document())

    def test_no_list_is_404_and_page_lists_the_scripts(self):
        srv = self.serve(None)
        with self.assertRaises(urllib.error.HTTPError) as e:
            get(srv, 'work.json')
        self.assertEqual(e.exception.code, 404)
        with urllib.request.urlopen('http://127.0.0.1:%d/' % srv.server_address[1], timeout=10) as r:
            page = r.read().decode('utf-8')
        for name in ('viewer-tabs.js', 'viewer-work.js', 'id="tab-work"', 'id="work-section"'):
            self.assertIn(name, page)
        for name in ('viewer-tabs.js', 'viewer-work.js'):
            with urllib.request.urlopen('http://127.0.0.1:%d/%s' % (srv.server_address[1], name), timeout=10) as r:
                self.assertEqual(r.status, 200)


if __name__ == '__main__':
    unittest.main()
