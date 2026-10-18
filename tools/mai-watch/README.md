Status: draft (M2). Windows and Linux (WSL) tests pass; real-job check (M3), notifier and macOS not measured.

# mai_watch

Read-only monitor for resource utilization and workload status. Works on any OS. Design: [DESIGN.md](DESIGN.md).

## Status

| Milestone | State |
|---|---|
| M0 design, status schema v1, contract test | done (this folder) |
| M1 collector, idle detection, event log, CLI | done (71 tests, 10 mutation checks, read-only smoke run on real nvidia-smi; review findings W1 to W5 and M01 to M07 answered) |
| M2 static viewer | done in part (Chrome, light mode, 1456 and 390 px; dark mode not rendered) |
| M3 real-device read-only check, notifier | not started |
| M4 verification, Linux run, release | not started |

## What exists

- `DESIGN.md`: purpose, terminology, architecture, status schema, idle detection, liveness, testing, milestones.
- `schema/status.v1.schema.json`: the status document contract (JSON Schema 2020-12).
- `schema/examples/`: valid and invalid documents. An invalid file name states the reason.
- `mai_watch/`: the package (`status.py` validator, `nvidia.py` parsers, `idle.py` detection, `collector.py`, `cli.py`).
- `tests/test_mai_watch.py`: parsers, idle detection, collector cycle, CLI end to end with a stub `nvidia-smi`, runtime validator against the schema, mutation tests.
- `tests/test_schema_contract.py`: checks that valid documents pass, that each invalid one is rejected for its stated reason, and that three deliberately broken schemas are detected.

## Use

```
python -m mai_watch init mywatch        # writes mywatch/mai-watch.toml
cd tools/mai-watch && python -m mai_watch collect --config mywatch/mai-watch.toml
python -m mai_watch check --config mywatch/mai-watch.toml   # exit 1 on any alert
python -m mai_watch serve --config mywatch/mai-watch.toml   # viewer at http://127.0.0.1:28765/
```

Workloads write status documents (schema v1) into `status_dir`. The collector writes `snapshot.json`, `events.jsonl`, `collector_heartbeat.json` into `out_dir`.

## Run the tests

```
python -I tools/mai-watch/tests/test_mai_watch.py
```

## Run the contract test

```
python -I tools/mai-watch/tests/test_schema_contract.py
```

Needs the `jsonschema` package. A missing package fails the test on purpose.

## Rules

Read-only. Local only. No secrets. No synthetic GPU load in tests.
