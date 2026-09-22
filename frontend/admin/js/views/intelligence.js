/**
 * Sales intelligence panel.
 *
 * Displays backend values verbatim. Nothing here recomputes a score, re-bands a
 * priority or re-ranks anything (requirement 3.7). When the five score dimensions
 * are unavailable — they are only returned when a message is processed — the
 * total is shown alone with an explanation, rather than a fabricated breakdown
 * (requirement 3.2).
 */
import { strings, SCORE_DIMENSION_MAX } from '../strings.js';
import { el, clear, badge, section, kvRow, stateBlock } from '../dom.js';
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

  const dimensions = (dims) =>
    Object.entries(dims).map(([key, value]) => {
      const max = SCORE_DIMENSION_MAX[key] ?? 0;
      const pct = max ? Math.min(100, (value / max) * 100) : 0;
      return el('div', { className: 'dim' }, [
        el('div', { className: 'dim__head' }, [
          el('span', { text: strings.scoreDimension[key] ?? key }),
          el('span', { text: `${value} / ${max}` }),
        ]),
        el('div', { className: 'dim__track' }, [
          el('div', { className: 'dim__fill', style: { width: `${pct}%` } }),
        ]),
      ]);
    });

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
    el(
      'div',
      { className: 'history' },
      list.map((entry) =>
        el('div', { className: 'history__item' }, [
          el('span', { className: 'history__time', text: time(entry.ts) }),
          el('strong', { text: String(entry.score) }),
          el('span', { className: 'history__reason', text: `${entry.state} · ${entry.trigger}` }),
        ])
      )
    );

  const stateHistory = (list) =>
    el(
      'div',
      { className: 'history' },
      list.map((entry) =>
        el('div', { className: 'history__item' }, [
          el('span', { className: 'history__time', text: time(entry.ts) }),
          el('strong', { text: entry.to }),
          el('span', {
            className: 'history__reason',
            text: `from ${entry.from} — ${entry.reason}`,
          }),
        ])
      )
    );

  return {
    render(state) {
      if (state.activePanel !== 'intelligence') {
        root.classList.remove('is-active');
        return;
      }
      root.classList.add('is-active');

      const opportunity = state.conversation.opportunity;
      const linkedCase = state.conversation.linkedCase;
      const signature = `${opportunity?.id ?? '-'}|${opportunity?.score}|${opportunity?.humanTakeover}|${linkedCase?.statusToken ?? '-'}`;
      if (signature === lastSignature) return;
      lastSignature = signature;

      clear(root);

      if (!opportunity) {
        root.append(stateBlock({ body: strings.inbox.selectBody }));
        return;
      }

      // ---- Score ------------------------------------------------------
      const scoreChildren = [
        el('div', { className: 'score-total' }, [
          el('span', {
            className: 'score-total__value',
            text: opportunity.score ?? strings.intelligence.noScore,
          }),
          opportunity.score !== null && opportunity.score !== undefined
            ? el('span', { className: 'score-total__max', text: `/ ${SCORE_MAX}` })
            : null,
          badge(opportunity.priority ?? '—', priorityClass(opportunity.priority)),
        ]),
      ];
      if (opportunity.scoreDimensions) {
        scoreChildren.push(...dimensions(opportunity.scoreDimensions));
      } else {
        scoreChildren.push(
          el('div', {
            className: 'kv__val kv__val--muted',
            text: strings.intelligence.dimensionsUnavailable,
          })
        );
      }
      root.append(section(strings.intelligence.scoreTitle, scoreChildren));

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
