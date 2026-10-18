# Changelog

## Unreleased

- First import of mai-approve, mai-watch and mai-tabs, with the findings of two independent review rounds each fixed with a reproducing test.
- Fixed after the first cross-system review: the viewer named a wrong-shaped snapshot as a file read failure and dropped the real heartbeat (now named for what it is, tested through the real page script); a Windows process path was not reduced to its file name on Linux; mai-approve refuses approvals and requests written in another operating system's absolute path notation.
- Added the hygiene gate, the all-tests runner and the CI matrix.
