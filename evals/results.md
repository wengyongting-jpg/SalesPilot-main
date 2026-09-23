# Evaluation results

**Last run:** 2026-09-23, against backend commit `2753bef`.
**Suite:** `evals/conversation-scenarios.json` (28 scenarios), run via `evals/run_evals.py`.
**Environments tested:** offline (no model configured — the rules/template peers) and live model (`global.anthropic.claude-sonnet-4-5-20250929-v1:0`, via an OpenAI-compatible gateway).

Both runs used a throwaway backend instance (scratch SQLite DB, non-default port), torn down after each run. Neither touched the project's persistent `runtime/backend.db`.

## Latest result

| Mode | Passed | Failed | Informational |
| --- | --- | --- | --- |
| Offline (rules/template) | 28 | 0 | 0 |
| Live model | 28 | 0 | 0 |

Reproduce:
```
python3 -m backend --serve --port 8010 --db /tmp/eval.db &
python3 evals/run_evals.py --base-url http://127.0.0.1:8010

# with a live model:
SALESPILOT_LLM=openai SALESPILOT_LLM_MODEL=<model> \
SALESPILOT_LLM_BASE_URL=<gateway url> SALESPILOT_LLM_API_KEY=<key> \
python3 -m backend --serve --port 8010 --db /tmp/eval.db &
python3 evals/run_evals.py --base-url http://127.0.0.1:8010 --timeout 30
```

## Scenario list (28)

| Scenario | Category |
| --- | --- |
| baseline-greeting | baseline |
| baseline-price-essential | baseline |
| baseline-claims-question | baseline |
| baseline-eligibility-question | baseline |
| baseline-corporate-browsing-no-escalation | baseline |
| escalation-human-request | escalation |
| escalation-complaint | escalation |
| escalation-underwriting-medical | escalation |
| escalation-negotiation-discount-plain | escalation |
| escalation-competitive-at-high-intent | escalation |
| escalation-corporate-ready-to-sign | escalation |
| adversarial-empty-message-rejected | adversarial |
| adversarial-whitespace-only-message | adversarial |
| adversarial-sql-injection-payload | adversarial |
| adversarial-xss-payload | adversarial |
| adversarial-extremely-long-message | adversarial |
| adversarial-emoji-and-mixed-language | adversarial |
| regression-negotiation-obfuscation-evasion | regression |
| regression-comparison-grounds-both-products | regression |
| regression-withdrawal-then-reengagement-restores-quick-replies | regression |
| lifecycle-application-through-conversion-cancellation-and-expansion | lifecycle |
| lifecycle-postponement-moves-evaluation-to-dormant | lifecycle |
| isolation-two-customers-do-not-cross-contaminate | isolation |
| robustness-all-caps-message | adversarial |
| robustness-repeated-message-without-key-is-not-deduped | adversarial |
| regression-two-strikes-required-before-a-solicitation-hold | regression |
| regression-zero-width-space-no-longer-evades-negotiation | regression |
| regression-ambiguous-followup-after-greeting-stays-unknown | regression |

All 28 passed in both modes on the run above. Full per-turn logs from that run: `/tmp/offline_eval_output.txt` (offline; not preserved beyond this session's scratch space) and the equivalent live-model transcript, both reproducible via the commands above.

## Bugs found and fixed during this evaluation cycle

Nine defects were found by actually running these scenarios (not by inspection) and fixed, in three rounds:

### Round 1 — offline eval, first pass

1. **Reply-safety check crashed the turn on ordinary words.** `assert_customer_safe` was applied to the model's own free-form output using a token set that included plain English words ("priority", "escalate", "score"), so a normal sentence like "you can escalate to our hotline" raised an uncaught exception and lost the turn. *Fix:* split into `assert_customer_safe` (developer-authored prompt text, full token set) and a narrower `assert_reply_safe` (model output, enum values only), with a degrade-to-template fallback on failure instead of a crash. — `backend/agent/policy.py`, `backend/agent/reply/model_based.py`

2. **A ready-to-sign corporate lead was never escalated.** "Sign up" classified as `Intent.APPLICATION`, which the corporate-quote escalation gate didn't check (only `CORPORATE_NEED`/`PRICE`). *Fix:* added `APPLICATION` to the gate's intent set. — `backend/kernel/hitl.py`

3. **Discount-request escalation trivially evaded by leetspeak.** `"disc0unt"` matched no negotiation phrase. *Fix:* added a de-leeting normalization pass before phrase matching. — `backend/agent/extraction/rules/signals.py`

4. **Two-product comparisons only ever answered about one product.** `Detection.product` is a single sticky field; a phrase-list ordering quirk also picked the wrong one of the two named products. *Fix:* added `KnowledgeRetriever.detect_mentioned_products`/`retrieve_comparison`, used when intent is `COMPARISON` and two products are named. — `backend/knowledge/retriever.py`, `backend/services/conversation.py`

5. **Withdrawal signal never cleared.** Once set, `Signal.WITHDRAWAL` stayed in `opp.signals` forever, permanently suppressing quick replies even after a full, normal re-engagement. *Fix:* clear it from the profile as soon as a later message doesn't itself withdraw. — `backend/services/conversation.py`

### Round 2 — first live-model run

6. **Reply generation failed 100% of the time on this gateway.** The reply agent (no tools of its own) was given the extraction agent's tool-call history via `message_history`; the gateway (Bedrock-backed) rejects any request with tool-call content blocks unless a matching `toolConfig` is sent. *Fix:* stopped reusing that history; the customer's raw text (the only information it was actually carrying) is now passed directly in the reply prompt instead. — `backend/agent/reply/model_based.py`, `backend/agent/reply/__init__.py`, `backend/services/conversation.py`

7. **Greeting mode lost specifically in the degraded/fallback path** (a consequence of #6 always firing): `model_based.compose()` didn't accept or forward a `greeting` flag to either of its template-fallback calls, so every degraded reply — including a first "hi" — fell back to the generic full-catalogue answer. *Fix:* threaded `greeting` through both fallback calls. — `backend/agent/reply/model_based.py`, `backend/agent/reply/__init__.py`

8. **Escalation guarantees weren't structurally enforced under model-based extraction.** Only `solicitation` had deterministic (rule-based) corroboration; every other signal and intent — including what gates a complaint, a negotiation, or a human request — came purely from the model's own judgement, with no keyword safety net. Verified live: "I've completed my payment" didn't register as a conversion, and "I want to cancel my policy" didn't register as a complaint. *Fix:* rule-based signals are now unioned into the model's signals, and the model's intent falls back to the rule-based read whenever it resolves to one of the three escalation-gating intents (`human_request`, `complaint`, `underwriting`). — `backend/agent/extraction/model_based.py`

### Round 3 — known issues, then a second live-model run

9. **Solicitation "two strikes" collapsed into one strike.** `opp.solicitation_count` was incremented before calling `qualification.assess()`, which then added its own `+1` for the same message. *Fix:* increment only after the verdict is read. — `backend/services/conversation.py`

10. **Zero-width-space evasion.** A U+200B inserted inside a restricted keyword (`"disc​ount"`) wasn't caught by the leetspeak fix (#3). *Fix:* strip Unicode format characters (category `Cf`) before matching. — `backend/agent/extraction/rules/signals.py`

11. **"hmm" right after a greeting resolved to Plus.** Context-based product inference scanned *any* prior message, including the assistant's own greeting (which names every product). *Fix:* only scan the customer's own prior messages. — `backend/agent/extraction/rules/product.py`

12. **Compliance disclaimer not guaranteed verbatim from a live model.** The reply prompt asked the model to append the disclaimer "verbatim," but that's an instruction, not an enforcement — found via a failing eval run where sampling variance dropped it, confirmed absent by comparing to a passing generation of the same prompt. *Fix:* the disclaimer is now appended deterministically in code whenever an approved fact mentions a premium and the model's own output doesn't already contain it verbatim, mirroring what the template peer always did. Stress-tested across 4 separate live generations after the fix: disclaimer present every time. — `backend/agent/reply/model_based.py`, `backend/domain/detection.py` (`RetrievalResult.mentions_premium`, shared with the template peer)

## Still open

None. All findings raised during this evaluation cycle have been fixed and re-verified in both offline and live-model modes as of the run at the top of this file.
