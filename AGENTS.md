# AGENTS.md — Project-wide agent working protocol

**Applies to:** every agent, sub-agent, and automated contributor working in this
repository, on any track (backend, customer frontend, admin frontend, docs) and in
any tool.

This document governs **how you work**: when to ask, when to test, what you may
commit, and what language to write in. It does not describe what to build — for
that, see the document map in §3.

**Precedence.** Where this document conflicts with any other instruction in the
repository, this document wins. Where it is silent, follow the current READMEs
and approved `docs/v1.0/` documents. The `docs/v0.0/` archive records earlier
decisions but is not an active instruction source. If a user instruction in the
current session conflicts with a rule here,
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

`docs/v0.0/frontend/frontend-changelog.md` is a specific, already-established instance of this
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
2. **Run existing checks.** For backend changes, run the relevant suite:

   ```powershell
   $env:SALESPILOT_LLM = 'offline'
   py -3 -m unittest discover -s backend/tests
   ```

   For frontend changes, run the existing Node built-in test suite with
   `node --test "frontend/tests/**/*.test.js"`, then manually verify changed views
   in a browser. This runner is already part of the repository and requires no
   dependency or build step. Historical `_Verify:_` steps are archived under
   `docs/v0.0/frontend/` and may be used as supplementary checks.
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
| `AGENTS.md` (this file) | Binding working protocol. |
| `README.md`, `backend/README.md`, `frontend/README.md` | Current setup, product boundaries, implementation, and operating instructions. |
| `backend/evals/README.md` | Current multi-turn evaluation instructions. |
| `docs/README.md` | Documentation entry point and version map. |
| `docs/v1.0/` | Current proposals and approved work; each file states its own implementation status. |
| `docs/v0.0/` | Historical contracts, Kiro-era specs, plans, and changelogs. These are references, not active implementation instructions. |
| `docs/v0.0/api/interface-v1.md` | Frozen historical v1 wire contract. Preserve API semantics; later changes belong in a versioned delta. |

## 4. Standing project constraints

These are not new rules. They are existing constraints an agent will hit
immediately, collected here so they are impossible to miss. Each is specified in
full in the document named.

- **Track ownership is advisory, not a wall** *(amended 2026-09-22 on the
  owner's explicit instruction; previously the two tracks were read-only to
  each other)*. That rule existed because two tracks worked the repository in
  parallel and neither could be allowed to move the other's ground mid-flight.
  They no longer do. One operator now directs the whole repository, so an
  agent may change any track it is asked to change. What survives from the old
  rule is the part that was never about parallelism: **say which track you are
  touching and why before you touch it**, and keep a change that crosses a
  track boundary in its own reviewable step rather than smuggled into another.
- **`docs/v0.0/api/interface-v1.md` is frozen** (2026-09-22). Its relocation and
  link corrections were explicitly authorised; its API semantics and fields
  remain frozen. Contract changes require a new versioned contract, not an edit
  to v1. The archived `docs/v0.0/backend/backend-contract.md` is historical.
- **No frontend build step and no dependencies.** Vanilla HTML, CSS and ES
  modules. No npm, no bundler, no CDN. See `frontend/README.md`.
- **The frontend holds no business logic.** State, signals, score, priority, next
  best action and escalation come from the backend and are displayed, never
  recomputed. See `frontend/README.md`.
- **Compliance red lines.** The assistant is labelled as AI; premium disclaimers
  are never hidden or truncated; no WhatsApp trademarks, fonts, or sounds. See
  `README.md` and `frontend/README.md`.
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
  no git upload (Rule 4), and changed this file only with explicit authorisation
  (Rule 7).
