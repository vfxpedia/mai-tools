Status: draft. M0 (design, schema, contract tests) and M1 (extension, renderer, classifier, proposal, verify) are implemented, 40 tests. Independently exercised in an isolated Chrome profile (popup, API calls, download, verify). Not measured: a large real profile, audible tabs, incognito or other profiles, other operating systems.

**Start with myself. Validate with evidence. Generalize for others.**

# mai-tabs design v0.1

## 1. Purpose and scope

Before the owner cleans up Chrome processes, write down what is open (windows, tab groups, pages), classified by category, into a Markdown file. Then propose, never perform, what could be closed. Process termination only after the owner confirms.

In scope: browser extension that exports tabs as JSON, URL sanitizer, rule-based classifier, Markdown renderer, cleanup proposal, read-only process report. Out of scope: closing tabs, ending processes, any network access, any dependency on MAI CAPTURE or other MAI world modules (deferred by the owner on 10/17; the export keeps `schema` and an optional `labels` object so a later integration needs no rewrite).

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
