# v1.0 current work

This directory holds work for the `salespilot-v1.0` branch. A document's own
status controls whether it describes a proposal or implemented behavior.

- [Persistence and evaluation repair plan](persistence-repair-plan.md) — implemented;
  backend and offline acceptance gates passed 2026-09-25.
- [Conversation intent research and revision plan](conversation-intent-research-and-revision-plan.md) — evidence review of the teammate sales-signal and compliance drafts, with proposed revision rounds; not implemented.
- [Conversation memory repair plan](conversation-memory-repair-plan.md) — bounded model context, sourced summaries, SQLite history search, and verification; implemented 2026-09-25.
- [Conversation labels, scoring, and decision rules](conversation-ruleset-proposal.md) — proposed human-reviewable ruleset and acceptance gates; not implemented.
- [对话标签、评分与决策规则（中文版）](conversation-ruleset-proposal.zh-CN.md) — translation of the proposed ruleset for team review; not implemented.
- [Backend decision-chain repair plan](backend-decision-chain-repair-plan.md) — original implementation handoff; typed observation, decisions and pending handoff actions now implemented and offline-verified.
- [Semantic and logic verification](semantic-and-logic-verification.md) — current backend path, two corrected mismatches, checks and remaining live-model limits.
- [Staff priority and audit plan](staff-priority-and-audit-plan.md) — approved direction for manual takeover, separate staff priority, score provenance, reviewed reply evaluation, and model-cost accounting; not implemented.

Current setup and operating instructions remain in the repository, backend,
frontend, and backend-evals READMEs. Historical design and contract records are
indexed in [v0.0](../v0.0/README.md).
