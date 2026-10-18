"""Writes the valid and invalid examples. The hash rule (canonical JSON, sorted keys, compact, UTF-8, sha256 field removed) lives here and in the contract test."""
import copy, hashlib, json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__)); OUT = os.path.join(HERE, 'examples')

def canon_hash(doc):
    d = {k: v for k, v in doc.items() if k != 'sha256'}
    return hashlib.sha256(json.dumps(d, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')).hexdigest()

def sealed(doc):
    doc = copy.deepcopy(doc); doc['sha256'] = canon_hash(doc); return doc

BASE = {
    'schema': 'mai-approval-v1', 'scope': 'lab', 'granted_at': '2026-10-18T02:00:00Z', 'valid_until': '2026-10-25T02:00:00Z',
    'granted_by': {'os_user': 'owner', 'host': 'example-host'}, 'method': 'owner-run mai-approve',
    'eula': {'accepted': True, 'license': 'NVIDIA Omniverse License', 'subject': 'owner', 'consent_source': 'owner typed at a terminal the owner operates'},
    'execution_mode': 'unattended',
    'limits': {'allowed_paths': ['C:/lab/runs'], 'devices': ['GPU-0'], 'max_runs_per_unit': 1, 'canary_retries': 1, 'count_per': 'experiment_unit_id'},
    'exclusions': ['paid_or_external_resource', 'data_deletion', 'kill_foreign_process', 'system_or_security_setting', 'external_send', 'out_of_scope_experiment'],
    'note': 'weekly nightly runs'}

def mut(**kw):
    d = copy.deepcopy(BASE)
    for k, v in kw.items(): d[k] = v
    return sealed(d)

def drop(key):
    d = copy.deepcopy(BASE); d.pop(key); return sealed(d)

valid = {
    'valid-minimal.json': sealed({k: BASE[k] for k in BASE if k not in ('note',)} | {'limits': {'allowed_paths': ['/data/run'], 'max_runs_per_unit': 1, 'count_per': 'experiment_unit_id'}}),
    'valid-full.json': sealed(BASE),
    'valid-linux-host.json': mut(granted_by={'os_user': 'user', 'host': 'example-linux'}, limits={'allowed_paths': ['/home/user/lab/runs'], 'max_runs_per_unit': 2, 'count_per': 'experiment_unit_id'}),
}
invalid = {
    'invalid-missing-valid_until.json': drop('valid_until'),
    'invalid-unknown-schema.json': mut(schema='mai-approval-v2'),
    'invalid-method-agent.json': mut(method='agent-written'),
    'invalid-time-not-utc.json': mut(valid_until='2026-10-25T11:00:00+09:00'),
    'invalid-empty-exclusions.json': mut(exclusions=[]),
    'invalid-unknown-exclusion.json': mut(exclusions=['everything']),
    'invalid-no-allowed-paths.json': mut(limits={'allowed_paths': [], 'max_runs_per_unit': 1, 'count_per': 'experiment_unit_id'}),
    'invalid-missing-eula.json': drop('eula'),
    'invalid-eula-not-accepted.json': mut(eula={'accepted': False, 'license': 'x', 'subject': 'x', 'consent_source': 'x'}),
    'invalid-execution-mode.json': mut(execution_mode='sometimes'),
    'invalid-count-per-run-id.json': mut(limits={'allowed_paths': ['/x'], 'max_runs_per_unit': 1, 'count_per': 'run_id'}),
    'invalid-extra-field.json': mut(auto_renew=True),
    'invalid-scope-space.json': mut(scope='my lab'),
}
# semantic invalids (schema passes, contract test must catch): tampered hash, window over 31 days, valid_until before granted_at
tamper = sealed(BASE); tamper['limits']['max_runs_per_unit'] = 99
semantic = {
    'semantic-tampered-hash.json': tamper,
    'semantic-window-over-31-days.json': mut(valid_until='2026-12-01T02:00:00Z'),
    'semantic-expires-before-grant.json': mut(valid_until='2026-10-17T02:00:00Z'),
}
RBASE = {'schema': 'mai-run-receipt-v1', 'run_id': 'r-20261018-01', 'experiment_unit_id': 'unit-b', 'attempt_kind': 'normal', 'approval_sha256': sealed(BASE)['sha256'], 'started_at': '2026-10-18T14:00:00Z'}
def rmut(**kw):
    d = dict(RBASE); d.update(kw); return d
def rdrop(k):
    d = dict(RBASE); d.pop(k); return d
receipts = {
    'receipt-valid-normal.json': RBASE,
    'receipt-valid-canary.json': rmut(attempt_kind='canary_retry', run_id='r-20261018-02', ended_at='2026-10-18T14:30:00Z'),
    'receipt-invalid-missing-unit.json': rdrop('experiment_unit_id'),
    'receipt-invalid-attempt-kind.json': rmut(attempt_kind='fresh_start'),
}
os.makedirs(OUT, exist_ok=True)
for name, doc in receipts.items():
    with open(os.path.join(OUT, name), 'w', encoding='utf-8', newline='\n') as f:
        json.dump(doc, f, indent=2, ensure_ascii=False); f.write('\n')
for name, doc in {**valid, **invalid, **semantic}.items():
    with open(os.path.join(OUT, name), 'w', encoding='utf-8', newline='\n') as f:
        json.dump(doc, f, indent=2, ensure_ascii=False); f.write('\n')
print('wrote', len(valid) + len(invalid) + len(semantic), 'examples')
