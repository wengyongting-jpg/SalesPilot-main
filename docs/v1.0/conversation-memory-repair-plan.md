# SalesPilot conversation memory repair plan

Status: **implemented 2026-09-25; offline verification passed**

Scope: backend model context, durable conversation memory, and read-only recall.
This follows the persistence repair work. It does not change the customer or admin
API contract, product knowledge source, or kernel ownership of opportunity state.

## Decision and current baseline

The approved direction is a default window of **six recent messages**, a persisted
source-linked summary when older material must leave the model context, and a
model-selectable read-only tool for finding older messages in the **current
opportunity only**. Raw messages remain in SQLite. The summary is a compact aid
to recall, not a replacement for the transcript or an authoritative business fact.
This intentionally revises the historical decision in `docs/v0.0/backend/backend-plan.md`
§12.1, which deferred summarisation and preferred retrieval alone.

The live `ConversationService` passes prior messages to extraction, but
`agent/extraction/model_based.py` sends only the latest text to its model.
Its `get_conversation_summary` tool receives a `ToolContext` without an
opportunity, so it returns the no-history result. `agent/runtime.py` defines a
six-message window and a richer tool context, but `build_service()` wires the
separate extractor and composer instead. `policy.trim_history()` keeps ten
messages and has no live caller. The reply model selects approved facts from a
self-contained prompt; its `ReplyRequest.history` is not sent to that model.

SQLite currently saves the complete opportunity, including all messages, in
`opportunities.payload`. Each `Message` has a stable ID. The repository has no
conversation-search method. The per-request token limits are cost guards, not
context compaction. None of these existing mechanisms supplies durable, sourced
model memory today.

## Proposed memory contract

1. **Recent context.** Build one context packet for the live extractor from at
   most five preceding messages, the latest customer message, and a bounded,
   customer-safe projection of approved profile fields. Keep roles and message
   IDs explicit. Keep at most six transcript messages in total and deduplicate
   the latest message. The six-message count is a
   default, not a guarantee that an oversized message fits a token budget.
2. **Automatic compaction.** Before the next model call, identify messages that
   have aged out of the six-message window. Compact their relevant customer
   facts into a bounded summary. If the remaining packet still exceeds the
   configured input budget, remove the oldest recent messages from that request
   while preserving the latest customer message and required instructions. They
   remain in SQLite, can be retrieved by the history tool, and enter a later
   summary as they age out. Trigger from a conservative text/token estimate with
   room reserved for the system prompt, tool schemas, and model output. Never
   rely on a provider rejection to perform compaction. A single latest message
   that still cannot fit follows an explicit degraded path and is reported, not
   silently cut.
3. **Provenance and authority.** Persist summary version, text, an ordered list
   of covered message IDs and the last covered transcript position, generation
   time, and source references for each
   retained claim. Validate IDs against the same opportunity and enforce length
   limits. ID validation confirms only that a referenced message exists; it
   does not establish that the summary text is semantically supported by that
   message. Every generated summary is therefore an **unverified recall note**;
   source IDs identify candidate messages, not proof. The model must search for
   the underlying detail and inspect the original message before relying on a
   note for a customer-specific claim, correction, or decision. Treat summary
   text as untrusted data in prompts. Only the kernel may update authoritative state, scores, risk
   flags, and handoff decisions. Summary disagreements are resolved against
   raw messages and approved profile fields.
4. **Long-term recall.** Add a bounded repository read scoped by opportunity ID.
   The model-facing tool accepts a short query and optional limit, never a
   customer or opportunity ID. The service binds the current opportunity ID
   and performs the lookup. Return snippets with message IDs, roles, and
   timestamps; exclude internal score, priority, run telemetry, and unrelated
   customers. Cap query length, result count, snippet size, and tool usage.
   Use a simple indexed or bounded SQLite search first; add a separate search
   service or vector database only if measured quality or latency requires it.
5. **Durability.** Store memory metadata separately from raw transcript in a
   versioned form, readable when absent from older databases. Extend the
   existing completed-turn transaction so opportunity, memory state, run,
   case, and optional idempotency receipt commit together. A replay must not
   re-summarise or duplicate sources. Retain old raw messages during migration
   and after compaction. Deleting an opportunity must remove its memory state.
6. **Failure behavior.** If summary generation or search fails, keep the raw
   transcript and the last valid summary; proceed within the safe context
   budget using recent messages and approved profile data. Record the failure
   and any skipped recall in the agent run. Never invent a summary, treat a
   missing tool result as evidence, or let a failed memory write create a
   partially committed customer turn.

## Implementation rounds

| Round | Work | Acceptance gate |
| --- | --- | --- |
| 1. Context inventory | Capture the exact live extraction and fact-selection inputs, token usage, and tool availability. Define the shared packet builder and budget accounting; remove or retire the unused ten-message trim path. | A multi-turn trace shows the six-message window, latest message, and approved profile projection that were actually sent. No internal score or priority appears in model-visible or customer-visible text. |
| 2. Durable summary | Add the versioned memory record, codec and repository methods, incremental compaction, source-ID validation, and atomic save. Make old SQLite files load with empty memory. | Messages beyond the window are represented by a bounded summary whose cited IDs belong to that opportunity; raw messages remain queryable; restart, replay, and write failure preserve consistent memory. |
| 3. Scoped history tool | Add read-only bounded search on the current opportunity and register it on the live extraction path. Return cited snippets and record actual model-selected calls. | The model can retrieve an older fact from this opportunity; a query cannot read another opportunity or bypass the result and cost caps. |
| 4. Quality and cost gate | Compare memory-dependent scenarios before and after the change, including contradiction, correction, long chats, adversarial text, unavailable model, and SQLite reopen. Review token and latency growth. | Recall improves without unsupported customer claims or a growing per-turn context; offline fallback and existing API behavior remain intact. |

The plan proposes test coverage as an acceptance gate; test code requires separate
consent under `AGENTS.md`. Existing backend tests and offline evaluations can be
run during implementation. Paid model evaluation remains subject to the existing
request, token, and cost caps.

## Review boundaries

- Keep the historical frozen v1 API document unchanged. If a public field is
  needed later, propose a versioned API delta first.
- Do not add summary text to approved product knowledge or use model-written
  text as a source for pricing, coverage, medical, or underwriting claims.
- Do not log full transcripts or summary content beyond the existing telemetry
  policy; report message IDs, versions, sizes, and failure reasons where enough.
- The `docs/v0.0/` memory design remains a historical record. This plan records
  the approved change in direction without editing that archive.

## Implementation and verification

Implemented the live extractor context builder, source-ID checked summary
compaction, a current-opportunity-only read tool, SQLite transcript projection
and legacy lazy hydration, versioned memory storage, and transactional turn
writes. Initial offline verification on 2026-09-25 passed all 337 then-current
backend tests; follow-up hardening also passed the full 339-test suite. The
20-case / 67-turn suite passed with both in-memory and SQLite storage. TestModel
exercises the compaction and tool-registration paths. No live-provider quality
run was performed, so summary accuracy with the configured production model
remains unmeasured.

Follow-up hardening: persisted summary facts explicitly carry `unverified`
status, and model prompts state that IDs are pointers rather than evidence and
require original-message lookup before reliance. This remains an instruction,
not an automated semantic/entailment verifier.
