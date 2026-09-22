# AGENTS.md — Project-wide agent working protocol

**Applies to:** every agent, sub-agent, and automated contributor working in this
repository, on any track (backend, customer frontend, admin frontend, docs) and in
any tool.

This document governs **how you work**: when to ask, when to test, what you may
commit, and what language to write in. It does not describe what to build — for
that, see the document map in §3.

**Precedence.** Where this document conflicts with any other instruction in the
repository, this document wins. Where it is silent, follow the steering files and
specs. If a user instruction in the current session conflicts with a rule here,
the user's instruction wins for that session only — it does not amend this file
(see Rule 7).

---

## 1. The rules

### Rule 0 — Read this file before starting work

No agent may begin work in this repository without first reading this file in
full.

**Enforcement of this clause is the user's decision.** Unless the user has
explicitly waived it, treat it as in force.

*In practice:* read this file at the start of a session, before your first edit.
If you are a sub-agent, your parent must ensure you have received these rules. If
you find yourself editing files without having read this document, stop, read it,
and re-evaluate what you have already done against it.

### Rule 1 — When something is unclear, ask; do not decide for the user

If a requirement, scope boundary, or design choice is ambiguous, ask a question
instead of picking an interpretation and proceeding.

*In practice:* this applies to genuine ambiguity in intent, scope, or
architecture — not to reversible trivia. Choosing a variable name, an ordering of
equivalent CSS properties, or which of two identical-cost approaches to take does
not need a question; picking a data model, adding a dependency, changing a public
contract, or deciding what "done" means does.

When you do ask, state your recommended option and the reasoning, so the user can
answer with a single word rather than writing the design for you.

### Rule 2 — Get consent before adding test code

Do not create test files or add test cases without the user's prior agreement.

*In practice:* running existing tests is always allowed and is required by
Rule 6. What needs consent is *authoring* new tests. If you believe a test is
necessary, describe what you would test and why, then wait. See §2 for how this
interacts with Rule 6.

### Rule 3 — Get consent before adding documentation

Do not create documentation files without the user's prior agreement.

*In practice:* this covers new `.md` files, new sections of substantial length in
existing docs, README rewrites, and changelog entries. Code comments that explain
the code you are writing are part of the code, not documentation, and are
expected.

`docs/frontend-changelog.md` is a specific, already-established instance of this
rule: it is updated **only** on explicit authorisation, and completing a change is
not authorisation.

### Rule 4 — Never perform git upload operations on the user's behalf

Do not push, open pull or merge requests, create or move tags, or otherwise mutate
a remote unless the user explicitly asks in the current session.

*In practice:* reading git state is always fine — `git status`, `git log`,
`git diff`, `git show`. Local history is the user's too: they have been committing
this repository themselves, so ask before creating local commits rather than
assuming. Never touch git configuration. Never use destructive commands
(`push --force`, `reset --hard`, `clean -fd`, `branch -D`) without an explicit
request.

### Rule 5 — Code and documentation are English by default

All code, identifiers, comments, commit messages, documentation and user-facing
strings are written in English unless the user explicitly requests otherwise.

*In practice:* conversation language is separate from artefact language. The user
may discuss the work in another language while the repository stays English. Do
not mirror the conversation language into files.

### Rule 6 — After changing code, run self-review and test checks; raise risky gaps rather than writing tests

After modifying code, review your own change and run the relevant existing checks.
If that reveals a **high-risk gap in test coverage**, report it to the user
instead of writing a test file to close it.

*In practice:* three steps, in order.

1. **Self-review.** Re-read your own diff as if reviewing someone else's. Check it
   against the specs and steering rules that apply to the files you touched.
2. **Run existing checks.** For backend changes, the suite must stay green:

   ```powershell
   py -3 -m pytest tests/ -v
   # stdlib-only equivalent
   py -3 -m unittest discover -s tests -v
   ```

   For frontend changes, verification is manual and scripted by design; use the
   `_Verify:_` steps in the relevant `tasks.md`. Do not introduce a JavaScript test
   runner, because that would introduce a build step.
3. **Report, do not patch, coverage gaps.** If you identify behaviour that is
   risky and untested, describe the gap, why it is risky, and what a test would
   assert. Then stop and wait. Rule 2 still applies.

A command exiting zero is not by itself evidence that the change is correct. Say
what you verified and what you could not.

### Rule 7 — Amending this file requires explicit authorisation

Do not create, edit, restructure, or delete any part of this document without the
user's explicit instruction to do so.

*In practice:* if you believe a rule is wrong, missing, or in conflict with
another instruction, say so and propose the wording. Do not apply it yourself.
This includes tidying, reformatting, and "clarifying" edits.

---

## 2. How the rules interact

Two pairs are worth stating explicitly, because a careless reading makes them look
contradictory.

**Rule 2 and Rule 6.** Rule 6 requires you to run tests and to notice coverage
gaps; Rule 2 forbids you from writing tests without consent. There is no conflict:
*run* freely, *report* freely, *author* only with permission. Rule 6's third step
exists precisely to route a discovered gap into a conversation rather than into an
unrequested file.

**Rule 1 and autonomy.** Rule 1 is not an instruction to stop and ask before every
action. It draws the line at decisions the user would want to make: scope, public
contracts, data models, dependencies, and anything hard to reverse. Inside an
agreed scope, implement rather than narrate.

---

## 3. Document map

Read the documents that apply to your track. Do not duplicate their content into
new files.

| Document | Purpose |
| --- | --- |
| `AGENTS.md` (this file) | How to work. Binding on every agent. |
| `.kiro/steering/product.md` | Product context, the two audiences, non-goals, compliance red lines. |
| `.kiro/steering/tech.md` | Stack, repository layout, and the backend read-only rule for frontend work. |
| `.kiro/steering/frontend-conventions.md` | Frontend coding rules and design-token discipline. Applies to `frontend/**`. |
| `docs/backend-handoff.md` | Track ownership, priorities, and the contracts that must not change. Start here if you own the backend. |
| `docs/api/interface-v1.md` | Authoritative request/response contract. Shared; editable while draft. |
| `docs/backend-plan.md` | Backend rebuild plan. Backend-owned; frontend read-only. |
| `docs/backend-contract.md` | Current REST API reference plus the specification of every requested backend change. |
| `docs/backend-changelog.md` | Gated changelog for the Python backend. Authorisation required. |
| `docs/frontend-changelog.md` | Gated changelog. Authorisation required. |
| `.kiro/specs/customer-chat-ui/` | Customer chat: requirements, design, UX spec, tasks, demo checklist. |
| `.kiro/specs/admin-console-ui/` | Admin console: requirements, design, tasks. |

## 4. Standing project constraints

These are not new rules. They are existing constraints an agent will hit
immediately, collected here so they are impossible to miss. Each is specified in
full in the document named.

- **Backend is read-only for frontend work.** Frontend tracks do not modify
  `salespilot/`, `tests/`, `run.py`, or `requirements.txt`. Needed backend
  changes are recorded in `docs/backend-contract.md` instead, and the frontend
  degrades rather than blocking. See `.kiro/steering/tech.md`.
- **Frontend is read-only for backend work.** The reciprocal rule. See
  `docs/backend-handoff.md`.
- **The legacy console `salespilot/static/` is frozen.** Neither track extends,
  migrates, or refactors it.
- **No frontend build step and no dependencies.** Vanilla HTML, CSS and ES
  modules. No npm, no bundler, no CDN. See `.kiro/steering/tech.md`.
- **The frontend holds no business logic.** State, signals, score, priority, next
  best action and escalation come from the backend and are displayed, never
  recomputed. See `.kiro/steering/frontend-conventions.md`.
- **Compliance red lines.** The assistant is labelled as AI; premium disclaimers
  are never hidden or truncated; no WhatsApp trademarks, fonts, or sounds. See
  `.kiro/steering/product.md`.
- **No authentication exists anywhere in this project.** It is an accepted,
  documented demo limitation. Do not silently "fix" it, and do not add a fake
  login to disguise it.

## 5. Before you report work as finished

- Re-read the original request and check the result against its actual success
  criteria, not against the fact that commands ran without error.
- State what you verified and what you could not verify.
- Confirm you stayed inside your track's file ownership, for example with
  `git status --short`.
- Confirm you added no tests (Rule 2) or docs (Rule 3) without consent, performed
  no git upload (Rule 4), and left this file untouched (Rule 7).
