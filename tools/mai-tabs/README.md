Status: draft (M0 + M1). Exercised in an isolated Chrome profile; other profiles and operating systems not measured.

# mai-tabs

**Start with myself. Validate with evidence. Generalize for others.**

Design: [DESIGN.md](DESIGN.md). Works on Windows, Linux and macOS.

## Use

1. Chrome: `chrome://extensions`, turn on developer mode, "Load unpacked", choose `tools/mai-tabs/extension`. Press the toolbar button; a file `mai-tabs-<time>.json` downloads. URLs have no query string or fragment.
2. `python -m mai_tabs render mai-tabs-<time>.json --out tabs.md` (from `tools/mai-tabs`). Edit a copy of `mai_tabs/rules.default.json` and pass it with `--rules` to change the categories.
3. `python -m mai_tabs propose mai-tabs-<time>.json` lists duplicate and stale tabs. It closes nothing.
4. `python -m mai_tabs verify mai-tabs-<time>.json --expect-tabs N` re-reads the downloaded file; compare with the popup message.
5. `python -m mai_tabs procs [--name chrome.exe]` prints browser processes by type and memory (needs `psutil`).

## Tests

```
python -I tools/mai-tabs/tests/test_mai_tabs.py
```

Needs `jsonschema` and Node.js. The extension itself is not covered by the automated tests. It was exercised once by hand in an isolated Chrome profile, see DESIGN.md.
