# mai-work

A work list that a check reads instead of a person remembering it: each item has a state, an order (`after`), a planned start
and end, and the time it was decided. Two TSV files in the project:

- `WORK.tsv`: one row per item, its current state
- `WORK-events.tsv`: append-only, every change with `decided_at` (when it was decided) apart from `ts` (when it was written)

States: `open` · `doing` · `done` · `hold` · `cancelled` · `replaced` (see `mai_work/schema.py`).

Status: step 2 of 4. Only `convert` exists so far. The check, the commands that write the list, and the mai-watch tab come next.

## Try it

Move an eight-column `WORKLIST.tsv` (`id source priority due owner evidence status what`) into the new files and prove that no
cell was lost:

```
cd tools/mai-work
python -m mai_work convert path/to/WORKLIST.tsv out/
```

It writes `out/WORK.tsv`, `out/WORK-events.tsv` and `out/CONVERT-REPORT.md`, rebuilds the old file from the new one and compares
cell by cell and byte for byte. Exit 0 only when both match; 1 when anything differs; 2 when it refuses (unknown status, extra or
missing column, repeated id). The source file is only read.

```
python -m unittest discover -s tests
```
