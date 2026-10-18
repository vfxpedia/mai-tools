---
name: mai-codex-continuity
description: Use when a Codex MAI gauge checkpoint is pending, a session resumes after compact, or Codex Mods installation and runtime observations need verification.
---

> 분류: 시스템 운영 스킬
> 작성: pipeline · 2026-10-13
> 근거: mai-os #30 · Codex Mods 0.2.2
> 요지: 원문 참조와 검증된 Issue 영수증으로 진행 중 업무를 잇는다
> 상태: 명령 참조 · 엔진 compact 통제나 비용 제공 자체를 보장하지 않음

# Codex MAI continuity

Resolve the installed product as `CODEX_HOME/mai-codex-gauge`, with `~/.codex` only when CODEX_HOME is absent. Run helpers with `node`, not a bare script path.

Read current observations with `node <product>/src/setup.mjs doctor --session <exact ID>` and `node <product>/src/cli.mjs show --session <exact ID>`.

The 50% checkpoint saves the original transcript reference and current work state. At 75%, finish the current authorized work unit and record results, decisions, measured evidence and remaining work in its owning Issue. After reading the published comment back, run `node <product>/src/setup.mjs checkpoint --session <exact ID> --comment <exact GitHub Issue comment URL>`. This command independently reads the comment and saves a receipt hash, not the conversation body. Update doing/next/waiting with the product's `status` command. A requested checkpoint is not a verified record.

At 85%, prepare these references at the work-unit boundary. After compact or resume, reopen the original and evidence at the saved paths before continuing. The index and Issue do not replace the original. This plugin does not prevent engine compaction or call `/compact` itself.

Peer files under `~/.mai/sessions` are observations, not approvals. Identify live Orca handles separately before messaging. Installation or trust approval never authorizes restarting another session.

Cost is the provider's API estimate when present, not an invoice and not local arithmetic. Missing USD or a 300-minute quota window remains unavailable. A successful installer does not prove trusted hooks ran or that the native CLI supports five custom rows.
