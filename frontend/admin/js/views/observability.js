/**
 * Agent observability panel — what the agent actually did.
 *
 * Three rules this view exists to uphold:
 *
 * 1. **Absent is not zero.** When the backend does not report a metric, it reads
 *    "not reported". Showing 0 tokens or 0 cost for an unmeasured run would be a
 *    plausible-looking wrong number (requirement 4.10).
 * 2. **Retrieval is not a tool call.** `toolCallCount` counts only calls the model
 *    chose to make. Knowledge retrieval is a fixed pipeline step and is listed
 *    with kind `retrieval` (requirement 4.8, interface-v1.md §1.1).
 * 3. **Cost is the backend's number.** Never computed here from tokens
 *    (requirement 4.11).
 *
 * Prompt and completion content is untrusted data — it echoes the customer's own
 * words — so it renders through `textContent`. When the backend withholds it, the
 * character count is shown and the withholding is stated (requirement 4.5).
 */
import { strings } from '../strings.js';
import { el, clear, badge, section, stateBlock, skeleton, dataTable } from '../dom.js';
import {
  time,
  duration,
  count,
  cost,
  sumCost,
  chars,
  runStatusClass,
} from '../format.js';

/**
 * Renders a run list plus the selected run's detail. Reused by the Inbox route
 * and by the harness route, which is why the harness needs no telemetry UI of
 * its own.
 *
 * @param {object} deps
 * @param {HTMLElement} deps.el
 * @param {(runId: string) => void} deps.onSelectRun
 * @param {boolean} [deps.standalone] true when mounted outside the side panel
 */
export function createObservability({ el: root, onSelectRun, standalone = false }) {
  let lastSignature = null;

  const metric = (label, value, unreported = false) =>
    el('div', { className: 'metric' }, [
      el('div', { className: 'metric__label', text: label }),
      el('div', {
        className: unreported ? 'metric__value metric__value--unreported' : 'metric__value',
        text: value,
      }),
    ]);

  const totals = (runs) => {
    const tokenTotal = runs.reduce(
      (sum, run) => sum + (run.totals?.totalTokens ?? 0),
      0
    );
    const anyTokens = runs.some((run) => (run.totals?.totalTokens ?? 0) > 0);
    const costTotal = sumCost(runs.map((run) => run.totals?.cost).filter(Boolean));
    const llmTotal = runs.reduce(
      (sum, run) => sum + (run.totals?.llmCallCount ?? 0),
      0
    );

    return el('div', { className: 'totals' }, [
      metric(strings.observability.runCount, count(runs.length)),
      metric(strings.observability.llmCalls, count(llmTotal)),
      metric(
        strings.observability.totalTokens,
        anyTokens ? count(tokenTotal) : strings.observability.notReported,
        !anyTokens
      ),
      metric(
        strings.observability.totalCost,
        cost(costTotal),
        !costTotal
      ),
    ]);
  };

  const runButton = (run, selected) =>
    el(
      'button',
      {
        className: selected ? 'run is-selected' : 'run',
        attrs: { type: 'button', 'aria-pressed': selected ? 'true' : 'false' },
        on: { click: () => onSelectRun(run.runId) },
      },
      [
        el('div', { className: 'run__top' }, [
          el('span', {
            className: 'run__trigger',
            text: strings.trigger[run.trigger] ?? run.trigger,
          }),
          badge(run.status, runStatusClass(run.status)),
          el('span', { className: 'run__duration', text: duration(run.durationMs) }),
        ]),
        el('div', {
          className: 'run__sub',
          text: `${time(run.startedAt)} · ${run.totals.llmCallCount} model calls · ${
            run.totals.totalTokens > 0
              ? `${count(run.totals.totalTokens)} tokens`
              : strings.observability.notReported
          }`,
        }),
        run.status === 'degraded' && run.degradedStep
          ? el('div', {
              className: 'run__sub',
              text: strings.observability.degradedAt(run.degradedStep),
            })
          : null,
      ]
    );

  const stepsTable = (steps) =>
    dataTable({
      caption: strings.observability.stepsCaption,
      headers: strings.observability.stepsColumns,
      rows: steps.map((step) => [
        el('span', { className: 'step__index', text: String(step.index) }),
        // A degraded step is named in text, not signalled by colour alone.
        step.status === 'ok'
          ? step.name
          : el('span', {}, [
              el('span', { text: `${step.name} ` }),
              badge(step.status, runStatusClass(step.status)),
            ]),
        el('span', {
          className: 'step__kind',
          text: strings.stepKind[step.kind] ?? step.kind,
        }),
        el('span', { className: 'step__duration', text: duration(step.durationMs) }),
      ]),
    });

  /**
   * The backend explains each step in `detail` — why it degraded, which transition
   * fired, how many facts were retrieved. That reasoning is the most useful thing
   * in the panel, so it gets its own block rather than being squeezed into a
   * table cell or dropped.
   */
  const stepDetails = (steps) => {
    const explained = steps.filter((step) => step.detail);
    if (explained.length === 0) return null;
    return el(
      'div',
      { className: 'panel-section' },
      explained.map((step) =>
        el('div', { className: 'step-detail' }, [
          el('span', { className: 'step__kind', text: step.name }),
          el('span', { className: 'step-detail__text', text: step.detail }),
        ])
      )
    );
  };

  const payload = (label, data) => {
    const children = [
      el('div', { className: 'payload__head' }, [
        el('span', { className: 'payload__label', text: label }),
        el('span', { className: 'payload__chars', text: chars(data?.chars) }),
      ]),
    ];
    if (data && typeof data.content === 'string') {
      // Untrusted: rendered as text, never markup.
      children.push(el('pre', { className: 'payload__body', text: data.content }));
    } else {
      children.push(
        el('div', {
          className: 'payload__withheld',
          text: strings.observability.contentWithheld,
        })
      );
    }
    return el('div', { className: 'payload' }, children);
  };

  const llmCall = (call) =>
    el('div', { className: 'llm-call' }, [
      el('div', { className: 'llm-call__head' }, [
        el('span', { className: 'llm-call__purpose', text: call.purpose }),
        el('span', { className: 'llm-call__model', text: call.model }),
        el('span', { className: 'run__duration', text: duration(call.durationMs) }),
      ]),
      el('div', { className: 'token-grid' }, [
        el('div', { className: 'token-grid__cell' }, [
          el('span', { className: 'token-grid__value', text: count(call.promptTokens) }),
          el('span', { text: strings.observability.promptTokens }),
        ]),
        el('div', { className: 'token-grid__cell' }, [
          el('span', {
            className: 'token-grid__value',
            text: count(call.completionTokens),
          }),
          el('span', { text: strings.observability.completionTokens }),
        ]),
        el('div', { className: 'token-grid__cell' }, [
          el('span', { className: 'token-grid__value', text: cost(call.cost) }),
          el('span', { text: strings.observability.totalCost }),
        ]),
      ]),
      payload(strings.observability.inputLabel, call.input),
      payload(strings.observability.outputLabel, call.output),
    ]);

  const runDetail = (run) =>
    el('div', {}, [
      section(strings.observability.stepsTitle, [
        stepsTable(run.steps),
        stepDetails(run.steps),
        // A model contract violation means the model proposed a value the domain
        // refused. The previous build downgraded these silently, which is exactly
        // how three escalation triggers went missing, so they are surfaced loudly.
        run.violations?.length
          ? el('div', { className: 'notice notice--warn', attrs: { role: 'note' } }, [
              el('span', {
                text: strings.observability.violations(run.violations.length),
              }),
            ])
          : null,
        el('div', { className: 'totals' }, [
          metric(strings.observability.steps, count(run.totals.agentStepCount)),
          metric(strings.observability.toolCalls, count(run.totals.toolCallCount)),
        ]),
        // Stated so nobody reads "0 tool calls" as a measurement failure.
        el('div', {
          className: 'kv__val kv__val--muted',
          text: strings.observability.toolCallsNote,
        }),
      ]),
      run.llmCalls.length
        ? section(strings.observability.callsTitle, run.llmCalls.map(llmCall))
        : section(strings.observability.callsTitle, [
            el('div', {
              className: 'kv__val kv__val--muted',
              text: strings.observability.notReported,
            }),
          ]),
    ]);

  return {
    render(state) {
      if (!standalone) {
        if (state.activePanel !== 'observability') {
          root.classList.remove('is-active');
          return;
        }
        root.classList.add('is-active');
      }

      const { status, items, selectedRunId } = state.runs;
      const signature = `${status}|${state.selectedId}|${items.length}|${selectedRunId}|${state.capabilities.telemetry}`;
      if (signature === lastSignature) return;
      lastSignature = signature;

      clear(root);

      // Requirement 4.10: no telemetry means say so, not show zeros.
      if (!state.capabilities.telemetry) {
        root.append(
          stateBlock({
            title: strings.observability.unavailableTitle,
            body: strings.observability.unavailableBody,
          })
        );
        return;
      }

      if (!state.selectedId) {
        root.append(stateBlock({ body: strings.inbox.selectBody }));
        return;
      }

      if (status === 'loading') {
        root.append(skeleton(5));
        return;
      }

      if (status === 'error') {
        root.append(
          stateBlock({
            title: strings.common.error,
            body: strings.observability.runsFailed,
            variant: 'error',
          })
        );
        return;
      }

      if (items.length === 0) {
        root.append(stateBlock({ body: strings.observability.runsEmpty }));
        return;
      }

      root.append(totals(items));
      root.append(
        section(
          strings.observability.title,
          el('div', { className: 'run-list' },
            items.map((run) => runButton(run, run.runId === selectedRunId)))
        )
      );

      const selected = items.find((run) => run.runId === selectedRunId);
      if (selected) root.append(runDetail(selected));
      else
        root.append(
          el('div', {
            className: 'kv__val kv__val--muted',
            text: strings.observability.selectRun,
          })
        );
    },

    /** Render a single run outside the panel flow (harness detail). */
    renderRun(run) {
      clear(root);
      if (!run) {
        root.append(stateBlock({ body: strings.harness.selectEntry }));
        return;
      }
      root.append(
        el('div', { className: 'totals' }, [
          metric(strings.observability.llmCalls, count(run.totals.llmCallCount)),
          metric(strings.observability.toolCalls, count(run.totals.toolCallCount)),
          metric(
            strings.observability.totalTokens,
            run.totals.totalTokens > 0
              ? count(run.totals.totalTokens)
              : strings.observability.notReported,
            run.totals.totalTokens === 0
          ),
          metric(strings.observability.totalCost, cost(run.totals.cost), !run.totals.cost),
        ])
      );
      root.append(runDetail(run));
    },
  };
}
