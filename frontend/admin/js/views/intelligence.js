/**
 * Sales intelligence panel.
 *
 * Displays backend values verbatim. Nothing here recomputes a score, re-bands a
 * priority or re-ranks anything (requirement 3.7). When the five score dimensions
 * are unavailable — they are only returned when a message is processed — the
 * total is shown alone with an explanation, rather than a fabricated breakdown
 * (requirement 3.2).
 */
import { strings } from '../strings.js';
import { el, clear, badge, section, kvRow, stateBlock, dataTable } from '../dom.js';
import { time, priorityClass } from '../format.js';

const SCORE_MAX = 100;

export function createIntelligence({ el: root }) {
  let lastSignature = null;

  const kv = (pairs) =>
    el(
      'div',
      { className: 'kv' },
      pairs.flatMap(([key, value, muted]) => kvRow(key, value, muted))
    );

  /**
   * One axis of the two-axis score.
   *
   * The bar is scaled against the axis total rather than a per-component maximum:
   * the backend publishes the components and the total, not a cap per component,
   * and inventing a denominator here would be the frontend deriving a number the
   * backend never stated.
   */
  const axis = (title, components, labels, total, totalLabel, extra = []) => {
    const children = [
      el('div', { className: 'dim__head' }, [
        el('strong', { text: title }),
        el('span', { text: `${totalLabel} ${total}` }),
      ]),
    ];

    for (const [key, value] of Object.entries(components)) {
      const pct = total > 0 ? Math.min(100, (value / total) * 100) : 0;
      children.push(
        el('div', { className: 'dim' }, [
          el('div', { className: 'dim__head' }, [
            el('span', { text: labels[key] ?? key }),
            el('span', { text: String(value) }),
          ]),
          el('div', { className: 'dim__track' }, [
            el('div', { className: 'dim__fill', style: { width: `${pct}%` } }),
          ]),
        ])
      );
    }

    children.push(...extra);
    return el('div', { className: 'panel-section' }, children);
  };

  const signals = (list) =>
    list.length === 0
      ? el('div', { className: 'kv__val kv__val--muted', text: strings.intelligence.none })
      : el(
          'div',
          {},
          list.map((value) =>
            el('span', {
              className: 'tag',
              text: strings.signalShort[value] ?? value,
              attrs: { title: value },
            })
          )
        );

  const scoreHistory = (list) =>
    dataTable({
      caption: strings.intelligence.scoreHistoryCaption,
      headers: strings.intelligence.scoreHistoryColumns,
      rows: list.map((entry) => [
        el('span', { className: 'history__time', text: time(entry.ts) }),
        el('strong', { text: String(entry.score) }),
        entry.state,
        el('span', { className: 'history__reason', text: entry.trigger }),
      ]),
    });

  const stateHistory = (list) =>
    dataTable({
      caption: strings.intelligence.stateHistoryCaption,
      headers: strings.intelligence.stateHistoryColumns,
      rows: list.map((entry) => [
        el('span', { className: 'history__time', text: time(entry.ts) }),
        entry.from,
        el('strong', { text: entry.to }),
        el('span', { className: 'history__reason', text: entry.reason }),
      ]),
    });

  return {
    render(state) {
      if (state.activePanel !== 'intelligence') {
        root.classList.remove('is-active');
        return;
      }
      root.classList.add('is-active');

      const opportunity = state.conversation.opportunity;
      const linkedCase = state.conversation.linkedCase;
      // The score is an object, so interpolating it produced the constant string
      // "[object Object]". That kept this hidden panel cached after a conversation
      // changed: the transcript and run timeline updated while Assessment showed
      // stale values. Include backend revision data and scalar fallbacks instead.
      const signature = [
        opportunity?.id ?? '-',
        opportunity?.updatedAt?.getTime?.() ?? '-',
        opportunity?.finalScore ?? '-',
        opportunity?.customerMessageCount ?? '-',
        opportunity?.humanTakeover ?? '-',
        linkedCase?.statusToken ?? '-',
      ].join('|');
      if (signature === lastSignature) return;
      lastSignature = signature;

      clear(root);

      if (!opportunity) {
        root.append(stateBlock({ body: strings.inbox.selectBody }));
        return;
      }

      // ---- Score: two axes, plus a display-only headline ---------------
      const score = opportunity.score;
      const scoreChildren = [
        el('div', { className: 'score-total' }, [
          el('span', {
            className: 'score-total__value',
            text: opportunity.finalScore ?? strings.intelligence.noScore,
          }),
          opportunity.finalScore !== null && opportunity.finalScore !== undefined
            ? el('span', { className: 'score-total__max', text: `/ ${SCORE_MAX}` })
            : null,
          badge(opportunity.priority ?? '—', priorityClass(opportunity.priority)),
        ]),
        el('div', {
          className: 'kv__val kv__val--muted',
          text: strings.score.headlineNote,
        }),
      ];

      if (score) {
        scoreChildren.push(
          axis(
            strings.score.fitTitle,
            {
              need_identified: score.fit.needIdentified,
              product_potential: score.fit.productPotential,
              expansion: score.fit.expansion,
            },
            strings.score.fit,
            score.fit.total,
            strings.score.fitTotal
          ),
          axis(
            strings.score.behaviourTitle,
            {
              purchase_intent: score.behaviour.purchaseIntent,
              purchase_readiness: score.behaviour.purchaseReadiness,
              engagement: score.behaviour.engagement,
            },
            strings.score.behaviour,
            score.behaviour.raw,
            strings.score.behaviourRaw,
            [
              // The decay is the part a reviewer most needs to see: a high raw
              // behaviour score that has decayed after silence is a different
              // situation from a low one, and the totals alone hide that.
              el('div', { className: 'kv' }, [
                ...kvRow(
                  strings.score.behaviourTotal,
                  String(score.behaviour.total)
                ),
                ...kvRow(
                  strings.score.engagementRecency,
                  strings.score.recencyNote(score.behaviour.engagementRecency)
                ),
                ...kvRow(
                  strings.score.engagementDepth,
                  String(score.behaviour.engagementDepth)
                ),
                ...kvRow(
                  strings.score.engagementUrgency,
                  String(score.behaviour.engagementUrgency)
                ),
              ]),
            ]
          )
        );
      } else {
        scoreChildren.push(
          el('div', {
            className: 'kv__val kv__val--muted',
            text: strings.intelligence.dimensionsUnavailable,
          })
        );
      }
      root.append(section(strings.intelligence.scoreTitle, scoreChildren));

      // ---- Qualification ----------------------------------------------
      // A held opportunity is excluded from the queue, so the reason it is held
      // has to be visible rather than implied by its absence.
      root.append(
        section(strings.qualification.label, [
          el('div', { className: 'case__head' }, [
            badge(
              strings.qualification[opportunity.qualification] ??
                opportunity.qualification,
              opportunity.qualification === 'qualified' ? 'badge--ok' : 'badge--medium'
            ),
          ]),
          opportunity.qualificationReason
            ? el('div', { className: 'kv' }, [
                ...kvRow(
                  strings.qualification.reasonLabel,
                  opportunity.qualificationReason
                ),
              ])
            : null,
          opportunity.qualification === 'held'
            ? el('div', {
                className: 'kv__val kv__val--muted',
                text: strings.qualification.heldNote,
              })
            : null,
        ])
      );

      // ---- Profile ----------------------------------------------------
      root.append(
        section(strings.panels.intelligence, [
          kv([
            [strings.intelligence.stateLabel, opportunity.state],
            [
              strings.intelligence.productLabel,
              strings.product[opportunity.product] ?? opportunity.product,
            ],
            [
              strings.intelligence.messageCountLabel,
              opportunity.customerMessageCount,
            ],
            [
              strings.intelligence.concernLabel,
              opportunity.mainConcern ?? strings.intelligence.empty,
              !opportunity.mainConcern,
            ],
            [
              strings.intelligence.competitiveLabel,
              opportunity.competitiveRisk ? strings.intelligence.yes : strings.intelligence.no,
            ],
            [
              strings.intelligence.churnLabel,
              opportunity.churnRisk ? strings.intelligence.yes : strings.intelligence.no,
            ],
            [
              strings.intelligence.complianceLabel,
              opportunity.complianceRisk ? strings.intelligence.yes : strings.intelligence.no,
            ],
            [
              strings.intelligence.expansionLabel,
              opportunity.expansion.length
                ? opportunity.expansion.join(', ')
                : strings.intelligence.none,
              opportunity.expansion.length === 0,
            ],
            [
              strings.intelligence.takeoverLabel,
              opportunity.humanTakeover ? strings.intelligence.yes : strings.intelligence.no,
            ],
          ]),
        ])
      );

      // ---- Signals ----------------------------------------------------
      root.append(
        section(strings.intelligence.signalsTitle, [signals(opportunity.signals)])
      );

      // ---- Next best action -------------------------------------------
      if (opportunity.nextBestAction) {
        const nba = opportunity.nextBestAction;
        root.append(
          section(strings.intelligence.nbaTitle, [
            el('div', { className: 'kv__val', text: nba.action }),
            el('div', { className: 'kv' }, [
              ...kvRow(strings.intelligence.nbaReasonLabel, nba.reason),
              ...kvRow(
                strings.intelligence.nbaHumanLabel,
                nba.humanInterventionRequired
                  ? strings.intelligence.required
                  : strings.intelligence.notRequired
              ),
            ]),
          ])
        );
      }

      // ---- Linked case ------------------------------------------------
      if (linkedCase) {
        root.append(
          section(strings.intelligence.caseTitle, [
            el('div', { className: 'case__head' }, [
              el('span', { className: 'case__id', text: linkedCase.id }),
              badge(linkedCase.status, 'badge--info'),
            ]),
            el('div', { className: 'kv' }, [
              ...kvRow(strings.intelligence.caseReasonLabel, linkedCase.reason),
              ...kvRow(
                strings.intelligence.caseActionLabel,
                linkedCase.recommendedAction
              ),
            ]),
          ])
        );
      }

      // ---- Histories --------------------------------------------------
      if (opportunity.scoreHistory?.length) {
        root.append(
          section(strings.intelligence.scoreHistoryTitle, [
            scoreHistory(opportunity.scoreHistory),
          ])
        );
      }
      if (opportunity.stateHistory?.length) {
        root.append(
          section(strings.intelligence.stateHistoryTitle, [
            stateHistory(opportunity.stateHistory),
          ])
        );
      }
    },
  };
}
