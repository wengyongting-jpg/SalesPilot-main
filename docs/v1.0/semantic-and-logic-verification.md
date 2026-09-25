# Semantic and logic verification — 2026-09-26

Status: backend code-path review and offline verification complete. No live provider was called. This is an implementation check, not human approval of the proposed scoring weights or evidence that the configured model performs well on real conversations.

## Contract traced

1. The latest customer message is appended with a stable ID. A replayed `client_message_id` returns the saved response without running extraction or creating another case.
2. A typed pending action is resolved first. A readiness invitation plus a contextual affirmative produces a handoff **offer**, not a case. Confirming a handoff offer creates or updates one open case; Cancel clears that offer. Actual `human_takeover` starts only when staff take ownership of the case.
3. Extraction reports current intent, buying posture and transaction issue. The service binds clear evidence spans to the latest message ID. Reported payment, failed payment and order-status questions remain unverified; they cannot count as verified conversion or cause an autonomous order action.
4. The deterministic kernel assesses takeover, qualification, state, profile, score, knowledge retrieval, handoff decision and next-best action. A model handoff proposal is an input, not authority to create a case. The candidate numerical score overhaul has **not** been adopted.
5. The service composes a confirmation prompt or a reply from an executed outcome. The reply model selects approved fact indices and an allowed template; it does not write free-form customer prose. Long conversation context is passed in bounded form, with unverified memory notes treated as recall pointers. A fixed reply skips an otherwise wasted reply-model call.
6. The completed turn, run, pending action/case and optional idempotency receipt are persisted together. Customer projection exposes only facts actually rendered in the reply, not the entire retrieval candidate list.

## Corrections made during this review

- The gateway cost wrapper read `pricing_known` from `cost_for()`'s return value, but that value is a `Cost` or `None`. On a priced model response with missing provider cost, this would raise an uncaught `AttributeError` and fail the request. It now assigns the calculated `Cost.amount`; an unknown served model or missing usage raises a classified usage-limit error, allowing the existing safe offline fallback rather than bypassing the configured cost limit or failing the HTTP request.
- `customer_facts` previously copied all retrieved facts even when the model selected only one or two, or a deterministic reply replaced the composed text. The composer now returns the facts it actually rendered. Confirmation, fixed and standalone replies return no fact cards. The customer-facing field name and wire shape are unchanged.

## Verification

- Offline backend suite: 350 tests passed.
- Multi-turn offline evaluation: 27/27 conversations, 90 turns passed in both in-memory and SQLite modes; no provider calls or cost.
- Local synthetic gateway response: the configured Claude Sonnet 4.5 model ID with 1000 input and 500 output tokens was assigned USD 0.0105; an unpriced served model was rejected. A synthetic reply-model selection rendered only its selected second fact. These checks did not contact the gateway.
- `git diff --check` passed. Existing test coverage does not exercise every live-provider response shape or adjudicate the semantic labels in the evaluation set.

## Remaining gates

- Run a bounded, explicitly approved live-model sample to check actual extraction, fact selection, context use, token accounting and false/omitted handoffs. Offline success cannot establish model quality or production pricing accuracy.
- Human-review evaluation labels and customer-facing handoff wording. In particular, distinguish **offer**, **queued case**, and **staff-owned conversation** in UI and operating instructions.
- Keep product/price statements limited to approved knowledge. A source ID on a memory summary is a pointer, not a semantic proof. Unknown order/payment status still requires staff verification; no order integration is present.
