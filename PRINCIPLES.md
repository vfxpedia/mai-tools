# Principles

**Start with myself. Validate with evidence. Generalize for others.**

1. **Start with myself.** A tool is built because its author needed it on a real machine and a real workload. A tool nobody needed is not added.
2. **Validate with evidence.** A passing test is not a result. Before a tool is called working it runs on an input whose answer is already known, and the outcome is checked at the layer the user sees. Reports from a tool, from a script, or from another reviewer are not facts until they are measured.
3. **Generalize for others.** Only after that does the tool leave its first machine: no machine names, account names or paths of one person in the code or examples, English documentation first, the same behavior on Windows, Linux and macOS or an honest statement of which of them was measured.
4. **Anywhere, any space.** Nothing in this repository depends on one computer being switched on. Automation lives in the repository and in CI, not on a person's machine.
5. **Say what was not measured.** The words "not measured" are part of the result. Support for an operating system is claimed only after a run on it.
6. **Quiet failures are loud failures.** A check that scanned nothing fails. A parse that found no valid row is a broken source, not an empty one. An unknown stays unknown and is never counted as a good or a bad value.
7. **Read-only until told otherwise.** Tools observe and propose. Anything that closes, deletes, kills or sends is outside the tools or behind an explicit owner action.

Style rule for all text in this repository: no long dash character; use a middle dot, a comma or a full stop.
