Status: draft (M1). 40 tests pass on Windows, Linux (WSL and CI) and macOS (CI). The extension was exercised once by hand in an isolated Chrome profile on Windows. Not measured: your own large profile, audible tabs, incognito, Chrome on Linux or macOS.

[한국어](README.ko.md)

# mai-tabs

Before you close a pile of browser tabs, save them as a categorized Markdown list, see which ones are duplicates or long unused, and see how much memory the browser takes. It proposes; it never closes a tab or ends a process.

- A small Chrome extension (permissions: `tabs`, `tabGroups` only) downloads one JSON file of the open tabs. Addresses are stripped of query strings and fragments before they leave the browser, so tokens in URLs are not saved.
- Python commands turn that file into Markdown, a cleanup proposal, and a process report.

## Tab library (0.2)

Keeps every page the browser had open as one line, by category or by date, and lets you open them again in the computer's Chrome (one by one, as a named tab group, or asleep), put them to sleep, or close them, with buttons. A page you opened several times is one item marked "duplicate 3 tabs" and can be cut down to one. Before and after a sleep or close it measures Chrome's memory and each GPU's memory, so you see what was actually freed. The same page and buttons work on a phone (inside your Tailscale network only).

1. Server: from `tools/mai-tabs`, `python -m mai_tabs serve` (127.0.0.1:28766, data in `~/.mai/tabs`). For other devices: `tailscale serve --bg --https=8443 http://127.0.0.1:28766`
2. Extension: in `chrome://extensions` turn on Developer mode, **Load unpacked**, choose `tools/mai-tabs/extension` (if you had 0.1, press reload there). The mai-tabs button should say "sent n seconds ago, tabs n"
3. Page: http://127.0.0.1:28766/ on the computer, port 8443 of your Tailscale name elsewhere

Not stored: sign-in, mail and bank hosts, sign-in and password-reset paths, token-like values in addresses (`?token=` and similar). Add hosts to block to `~/.mai/tabs/deny.txt`, one per line. Page content is never read (the one-line note comes from the address and title).

Tests: `python -I tests/test_library.py`, `node --test tests/extension.test.cjs`, real Chrome: `node tests/e2e_chrome.mjs` (your own profile is not touched). Design: [DESIGN.md](DESIGN.md) section 12.

## Try it

From `tools/mai-tabs`.

**Without a browser (one minute)**, using the example file that ships with the schema:

```powershell
python -m mai_tabs render schema/examples/valid-full.json --out $HOME/tabs-demo.md   # wrote ...tabs-demo.md
python -m mai_tabs propose schema/examples/valid-full.json                 # "Proposal only. Nothing was closed."
python -m mai_tabs verify schema/examples/valid-full.json --expect-tabs 1  # windows 1, tabs 1, groups 1; collection complete
python -m mai_tabs verify schema/examples/valid-full.json --expect-tabs 2  # tab count 1 does not match the expected 2 (exit 2)
python -m mai_tabs procs --name chrome.exe                                 # browser processes by type and memory (needs psutil)
```

**With your browser (five minutes)**:

1. Open `chrome://extensions`, turn on **Developer mode**, press **Load unpacked**, choose the folder `tools/mai-tabs/extension`. You should see `mai-tabs 0.1.0` with no errors. Do not grant anything else.
2. Press the mai-tabs button in the toolbar, then **Export open tabs**. Write down the numbers the popup shows (tabs, windows, groups) and whether it says INCOMPLETE. "Download requested" alone does not mean the file was saved; check that `mai-tabs-<time>.json` is in your downloads folder.
3. Check the file against what the popup said: `python -m mai_tabs verify <file> --expect-tabs <number>`. It must print `collection complete` and exit 0. With the number plus one it must exit 2.
4. `python -m mai_tabs render <file> --out $HOME/tabs.md` and open that file. `python -m mai_tabs propose <file>` for duplicates and tabs unused for 14 days. Pinned and audible tabs are never proposed.
5. Close tabs yourself if you want to; the list is for review, not a backup (addresses are shortened, so a closed tab cannot be reopened from it). To remove the extension, press **Remove** in `chrome://extensions`.

Categories come from `mai_tabs/rules.default.json`; copy it, edit, and pass `--rules your-rules.json` (`check-rules` validates it).

Measured 2026-10-18 on Windows: all commands above with the example file gave the outputs shown; `procs` listed 197 Chrome processes. The browser steps were measured by an independent reviewer in an isolated profile (10 tabs, 1 window, 1 group: popup, file and `verify` agreed); they were not yet run on the owner's own profile.

Design and review history: [DESIGN.md](DESIGN.md). Tests: `python -I tests/test_mai_tabs.py` (needs `jsonschema` and Node.js).
