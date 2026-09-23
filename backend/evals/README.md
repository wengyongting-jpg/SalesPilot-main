# SalesPilot multi-turn evaluation

The suite contains 20 conversations of three or four turns each (67 total). Escalation
cases require a separate customer confirmation before human takeover. Expectations are business
labels (intent, product, signals, state, qualification and handover), not reply copy.

Offline baseline, with no paid calls:

```powershell
python -m backend.evals
```

Configured-model evaluation is opt-in and writes a detailed JSON report under
`runtime/evals/`:

```powershell
python -m backend.evals --model --max-model-calls 160 --max-cost-usd 1.00
```

Use `--case ID`, `--exclude-case ID`, and `--attempt 1|2|3` to run targeted
iterations. The runner reserves the maximum permitted cost and request count for the
next turn before starting it, so a whole-suite budget stops early rather than being
noticed only after another turn is sent. Each model segment is additionally bounded
by the limits in `backend.config`.

Reports include each customer utterance, expected and actual labels, extraction
source, model/tool/token/cost totals, and the complete agent-run timeline. They may
contain customer text when telemetry content capture is enabled and must not be
committed.
