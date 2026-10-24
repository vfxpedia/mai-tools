Status: v0.2 draft. M0 to M2 as before (40 tests). v0.2 adds the tab library (section 12): a server on 127.0.0.1, a page that works on a phone through Tailscale Serve, and an extension that opens, sleeps and closes tabs when the owner presses a button. 30 more tests, plus a real-Chrome check (`tests/e2e_chrome.mjs`, 10 checks, Chrome 155 on Windows, 2026-10-25). Not measured yet: the owner's own profile with hundreds of tabs, Linux and macOS Chrome.

**Start with myself. Validate with evidence. Generalize for others.**

# mai-tabs design v0.1

## 1. Purpose and scope

Before the owner cleans up Chrome processes, write down what is open (windows, tab groups, pages), classified by category, into a Markdown file. Then propose, never perform, what could be closed. Process termination only after the owner confirms.

In scope: browser extension that exports tabs as JSON, URL sanitizer, rule-based classifier, Markdown renderer, cleanup proposal, read-only process report. Out of scope for the v0.1 export: closing tabs, ending processes, any network access (v0.2 adds closing and sleeping tabs on the owner's request, through the library in section 12; ending processes stays out of scope), any dependency on MAI CAPTURE or other MAI world modules (deferred by the owner on 10/17; the export keeps `schema` and an optional `labels` object so a later integration needs no rewrite).

## 2. Terminology

| Term | Definition |
|---|---|
| export | One JSON document `mai-tabs-export-v1` written by the extension |
| sanitize | Remove userinfo, query string and fragment from a URL; redact long token-like path segments |
| rules file | JSON `mai-tabs-rules-v1`: ordered categories, each with match rules. Configuration, not code |
| proposal | Text that lists duplicate and stale tabs. It has no effect |

## 3. Architecture

1. `extension/` (Manifest V3, plain JavaScript, no build step). The popup button reads windows and tab groups with the standard `tabs`, `windows`, `tabGroups` APIs, builds the export with `export.js`, and offers it as a file download. It makes no network request and stores nothing. Permissions: `tabs`, `tabGroups`. Tab groups exist in Chrome and Edge only; the popup works without them.
2. `mai_tabs/` (Python standard library; `psutil` only for the process report). `render` turns an export plus a rules file into Markdown, `propose` into a proposal, `procs` prints the process report.
3. One direction: browser, then JSON file, then reports. The Python side never talks to the browser.

## 4. Export schema v1

`schema/export.v1.schema.json`. Fields: `schema`, `exported_at` (RFC 3339 UTC), `browser` (name, version), `urls_sanitized` (must be true), `counts`, `windows` (id, focused, tabs), `groups` (id, title, color, collapsed), optional `labels`. A tab has `id`, `index`, `title`, `url`, `pinned`, `audible`, `discarded`, `group_id` (null when ungrouped; the browser's -1 is converted), `last_accessed_ms` (null when unknown).

Rules the schema cannot express are checked by `render.consistency_problems`: counts match the content, and every `group_id` refers to a listed group. `render` and `propose` refuse an inconsistent export.

## 5. Privacy

URLs can carry tokens. The extension sanitizes every URL before it leaves the page, the schema rejects any URL containing `?` or `#`, and the renderer sanitizes again, so an export from another tool still cannot put a query string into the Markdown. Path segments of 32 or more characters made of letters, digits, `_` and `-` that contain both a letter and a digit are replaced with `_redacted_` (default on; one function argument turns it off). Titles are kept as the browser reports them and can contain personal text: the owner reviews the Markdown before sharing it (M3). `file:` URLs keep only the file name. `data:`, `javascript:` and `mailto:` URLs keep the scheme only.

The JavaScript and Python sanitizers must stay identical: `tests/test_mai_tabs.py` runs both on 24 fixed cases and compares them. Known remaining difference: characters that the two URL libraries percent-encode differently outside those cases.

## 6. Classification

The default rules file is `mai_tabs/rules.default.json` (generic: code, ai, docs and notes, research, video and music, chat and mail, browser internal). Categories are tried in file order and the first with any matching rule wins; nothing matching goes to `default` (`uncategorized`). Rule kinds: `host` (exact), `host_suffix`, `url_prefix`, `title_contains` (case-insensitive). A rules file is checked for shape and duplicate names before use. No language model is called.

## 7. Cleanup proposal

`propose` lists extra copies of the same page (equal `url_id`, the hash of the full original address, so two pages that differ only by query string are different pages) (keeping the most recently used one) and tabs not used for more than N days (default 14). Pinned and audible tabs are never listed. The text states that nothing was closed.

## 8. Process report

`procs` groups browser processes by `--type=` (renderer, gpu-process, utility, browser...) with count and resident memory, largest first. It never claims a GPU share: per-process GPU memory is `[N/A]` on Windows under WDDM (measured 10/15). RSS counts shared pages in every process, so the total overstates real use; the report says so. Measured 10/18: 171 Chrome processes against 170 from the OS task list a moment apart.

## 9. Testing

Known-answer first. The expected Markdown and proposal in `tests/fixtures` were derived by hand from the fixture input before the code ran. Tests: contract (valid, invalid for the stated reason, semantic), sanitizer on 24 cases in both languages, end to end (browser-shaped input through the JavaScript export, the schema and the Python renderer, byte for byte), classifier, process summary, and 9 mutation checks (a broken rule must fail its suite). Run: `python -I tools/mai-tabs/tests/test_mai_tabs.py` (needs `jsonschema` and Node.js; a missing one is a failure, not a skip).

Exercised once in an isolated Chrome profile by an independent reviewer: the popup counts (10 tabs, 1 window, 1 group) matched the downloaded file and the schema, `verify --expect-tabs` exited 0 for the true count and 2 for a wrong one. Not measured: a large real profile, audible tabs, incognito or other profiles, other operating systems.

## 9b. Independent review, findings T1 to T4 (each probe is now a test)

| ID | Finding | Rule now |
|---|---|---|
| T1 | A protected (audible) tab was proposed as the duplicate to close | Pinned and audible tabs are never close candidates, in every section; in a duplicate set a protected tab is the one that stays; two protected copies give no candidate |
| T2 | Two different YouTube videos looked identical after sanitizing and were proposed as duplicates | The sanitized address is for display only. The export keeps `url_id`, the first 16 hex characters of SHA-256 of the full original address (JavaScript and Python hash code checked against each other, including 55, 56, 63, 64, 65 byte inputs and non-ASCII). Duplicates are decided by `url_id`. Exports without it propose nothing from address equality. A separate section lists shown addresses shared by different or unknown pages. Every candidate prints window, tab index, tab id, title, address and the tab that stays |
| T3 | A title with `<img ...>` went into the Markdown as raw HTML | Titles, group names and category names are escaped for HTML and Markdown, control characters are removed, link destinations cannot close the link or open a tag |
| T4 | A failed group query was turned into an empty list and reported as saved | A failed query marks `collection.complete = false` with the error, keeps group ids with placeholder groups, and the popup checks consistency before it downloads. An unsupported groups API is a note, not a failure. The popup now says "Download requested" and "INCOMPLETE" when relevant; `python -m mai_tabs verify <file> --expect-tabs N` re-reads the downloaded file for the comparison |

Boundaries stated by the same review. The list is for review and classification, not a backup: addresses have no query string, fragment or long path tokens, so a closed tab cannot be restored from this file. "All open tabs" means the windows of the current browser profile that the extension API returned (incognito only when the owner allowed it for the extension); other profiles are not collected. `url_id` is one-way but a guessable address can be confirmed by hashing it, and titles can hold personal text, so the JSON and Markdown are personal files and no flow uploads them automatically. Download is a request, not proof that a file arrived. The tool still never closes a tab or ends a process.

## 10. Milestones

| Milestone | Content | State |
|---|---|---|
| M0 | Design, export schema v1, examples, contract test | done |
| M1 | Extension, JSON export, Markdown renderer, classifier, fixtures | done except the real browser |
| M2 | Process report (read-only) | done (smoke run on this machine) |
| M3 | Real-browser run on the owner's own profile, owner reviews the Markdown before any cleanup | partly done in an isolated profile; the owner's own profile needs the owner: load `extension/` unpacked in `chrome://extensions` (developer mode) and press the button |
| M4 | independent verification, Linux and macOS runs, license, release | not started |

## 11. Open decisions (owner)

1. Distribution: load unpacked for now, or the Chrome Web Store later (account and review needed).
2. License.
3. After M3: whether the Markdown should be rendered inside the extension too. Today it is not: two renderers would need the same conformance test the sanitizer has.

## 12. Tab library (v0.2, owner request 2026-10-25, vfxpedia/mai-os#57)

The owner asked for five things: open the same tabs again later, a one-line note per tab, tabs grouped by topic (papers with papers), the memory a cleanup actually freed, and the list from anywhere, phone included, with the buttons working there too. The design keeps the v0.1 export as it was and adds a second path next to it.

### 12.1 Parts

| Part | Where | Job |
|---|---|---|
| extension 0.2 | `extension/background.js`, `core.js` | every 30 s and 2 s after any tab change, send the open tabs to the server; carry out the actions the server hands back; report each result |
| server | `mai_tabs/server.py`, `python -m mai_tabs serve` | 127.0.0.1:28766 only; the library, the page, the action queue |
| library | `mai_tabs/library.py` | what is stored, one item per page, the days each page was open, actions and their results |
| page | `mai_tabs/app.html` | by category or by date, search, select; open on this device, or ask the computer's Chrome to open, sleep or close |
| memory | `mai_tabs/memory.py` | Chrome's memory and each GPU's used memory before an action and 20 s after it |

The page never talks to the browser. A phone presses a button, the server queues the action, and the extension in the computer's Chrome picks it up within 30 seconds. Opening a link on the phone itself is a plain link.

### 12.2 What is stored

The library keeps addresses that can be opened again, so the decision is made in `library.clean_url` before anything is written: only http and https; user name and password dropped; query parameters that carry secrets (token, code, sig, key, session and similar names, or a value of 40 or more random-looking characters) and tracking parameters dropped; the fragment dropped. Pages on deny-listed hosts (sign-in, mail and bank hosts by default, more in `<data>/deny.txt`) and sign-in or password-reset paths are not stored at all; the page counts them as "not stored". The data folder is `~/.mai/tabs` (or `MAI_TABS_HOME`), never the repository.

### 12.3 One item per page, two views

Two tabs are the same page when their cleaned addresses are equal after dropping `www.` and a trailing slash and sorting the query; an arXiv paper is one page whatever its version or format. A page open three times is one item marked "duplicate 3 tabs", and "keep one" or "PC duplicate cleanup" closes the copies, keeping the most recently used one. The owner asked whether to sort by date or by category; the page does both over the same items: by category for "what do I have", by date for "what was I doing on Tuesday" (each local date keeps the ids that were open that day). A closed tab stays in the library, so either view can open it again, one by one, as a named Chrome tab group, or asleep.

### 12.4 Actions

| Action | What the extension does | Never touches |
|---|---|---|
| open | creates the tabs in the background; with a group name, puts them in that tab group (reusing a group of the same name); asleep: waits for each tab's address, then discards it | addresses that are not in the library, anything but http and https |
| sleep | `chrome.tabs.discard` | the active tab, pinned and audible tabs |
| close | `chrome.tabs.remove` | the active tab, pinned and audible tabs |
| dedupe | closes extra copies of a page, keeps the most recently used | the same three |

Order matters: Chrome gives a tab a new id when it is discarded, and a tab discarded before its address commits loses the address, so the extension groups first, waits for the address, then discards. A step that fails is counted and named in the result, and a group that could not be made makes the whole action "failed", never a quiet success (all three found by the real-Chrome check, now in `tests/extension.test.cjs`).

### 12.5 Who may do what

The server binds 127.0.0.1. Requests must name it in `Host` (127.0.0.1, localhost or a `*.ts.net` name), which stops DNS rebinding. Every POST needs the header `X-Mai-Tabs: 1` and a JSON body; a site open in the browser cannot add that header to a request to another origin without a preflight, and the server answers no preflight, so a site cannot press the buttons. Tab reports and results come only from the extension (an `Origin` of `chrome-extension://` and no `Tailscale-User-Login` header, which Tailscale Serve adds), so the library only ever holds addresses the browser itself reported, and the page can only ask to open those. From outside the computer the page is reached only through Tailscale Serve (tailnet devices).

### 12.6 Memory figure

Per-tab memory is not available to an extension, and per-process GPU memory under WDDM does not add up (dwm shows more than the GPU's total), so the figure is the whole: Chrome's private bytes on Windows (resident memory elsewhere) and each GPU's used memory from `nvidia-smi`, before the action and 20 s after the extension reported it done. The page says the difference also contains whatever else changed in those seconds.

### 12.7 Testing

`tests/test_library.py` (23): cleaning and the deny list, one item per page, arXiv versions, the days, planning only known items, sparing active, pinned and audible tabs, dedupe order, the action life cycle, a broken file kept aside, and the server: round trip, a web page or a phone cannot report tabs, POST needs the header, unknown hosts are refused, bad requests are 400. `tests/extension.test.cjs` (7): the extension core against a fake browser that, like Chrome, renames a discarded tab and loses the address of a tab discarded too early. `tests/e2e_chrome.mjs` (10 checks, not in CI): a throwaway Chrome profile and data folder, the extension loaded with `Extensions.loadUnpacked` over a DevTools pipe (Chrome 137+ ignores `--load-extension`), local test pages; it checks duplicates, sleep, dedupe, close, opening a named group asleep, the memory reading and that every action was acknowledged. The page was looked at at 390 px and 1280 px, light and dark, with no sideways scroll at 390 px.

### 12.8 Not done yet

Page-content summaries (the one-line note is built from the address and title only; reading page text would need wider permissions and would send page text to a model, which is the owner's call). Other browsers. Chrome on Linux and macOS is expected to work the same and has not been run. A copy of the library on the NAS.

