/**
 * Cases route — the console's one mutation besides replying.
 *
 * Transitions are never optimistic (requirement 5.5). A takeover that looks like
 * it succeeded but did not is worse than a slow one, because two people could
 * believe they own the same customer. The new status comes from the response body,
 * not from the value that was requested.
 *
 * The legacy console's takeover button only toggled CSS and never called the API.
 * This one performs the real transition.
 */
import { strings } from '../strings.js';
import { el, clear, badge, stateBlock, skeleton, kvRow } from '../dom.js';
import { dateTime } from '../format.js';

const STATUS_CLASS = {
  OPEN: 'badge--high',
  TAKEN_OVER: 'badge--info',
  CLOSED: 'badge--neutral',
};

/**
 * @param {object} deps
 * @param {HTMLElement} deps.el
 * @param {(caseId: string, statusToken: string) => void} deps.onTransition
 * @param {() => void} deps.onRefresh
 * @param {(opportunityId: string) => void} deps.onOpenConversation
 */
export function createCases({ el: root, onTransition, onRefresh, onOpenConversation }) {
  let lastSignature = null;

  const card = (item, transition) => {
    const inFlight = transition.inFlight && transition.caseId === item.id;
    const failed = Boolean(transition.error) && transition.caseId === item.id;

    const actions = [];
    if (item.statusToken === 'OPEN') {
      actions.push(
        el('button', {
          className: 'btn btn--primary btn--small',
          text: inFlight ? strings.cases.working : strings.cases.takeOver,
          attrs: { type: 'button', disabled: inFlight },
          on: { click: () => onTransition(item.id, 'TAKEN_OVER') },
        }),
        el('button', {
          className: 'btn btn--secondary btn--small',
          text: strings.cases.resolve,
          attrs: { type: 'button', disabled: inFlight },
          on: { click: () => onTransition(item.id, 'CLOSED') },
        })
      );
    } else if (item.statusToken === 'TAKEN_OVER') {
      actions.push(
        el('button', {
          className: 'btn btn--secondary btn--small',
          text: inFlight ? strings.cases.working : strings.cases.markResolved,
          attrs: { type: 'button', disabled: inFlight },
          on: { click: () => onTransition(item.id, 'CLOSED') },
        })
      );
    }

    actions.push(
      el('button', {
        className: 'btn btn--link',
        text: strings.conversation.openCase,
        attrs: { type: 'button' },
        on: { click: () => onOpenConversation(item.opportunityId) },
      })
    );

    return el('div', { className: 'case' }, [
      el('div', { className: 'case__head' }, [
        el('span', { className: 'case__id', text: item.id }),
        badge(item.status, STATUS_CLASS[item.statusToken] ?? 'badge--neutral'),
      ]),
      el('div', { className: 'kv' }, [
        ...kvRow(
          strings.cases.customerLabel,
          `${item.customerName} · ${item.opportunityId}`
        ),
        ...kvRow(strings.cases.stateLabel, item.state),
        ...kvRow(
          strings.cases.productLabel,
          strings.product[item.product] ?? item.product
        ),
        ...kvRow(strings.cases.reasonLabel, item.reason),
        ...kvRow(strings.cases.recommendedLabel, item.recommendedAction),
        ...kvRow(strings.cases.summaryLabel, item.summary),
        ...kvRow(strings.cases.createdLabel, dateTime(item.createdAt)),
      ]),
      el('div', { className: 'case__actions' }, actions),
      failed
        ? el('div', { className: 'case__error', text: strings.cases.transitionFailed })
        : null,
    ]);
  };

  return {
    render(state) {
      const { status, items } = state.cases;
      const transition = state.transition;
      const signature = `${status}|${items
        .map((c) => `${c.id}:${c.statusToken}`)
        .join(',')}|${transition.caseId}|${transition.inFlight}|${Boolean(transition.error)}`;
      if (signature === lastSignature) return;
      lastSignature = signature;

      clear(root);

      root.append(
        el('div', { className: 'route-head' }, [
          el('h1', { className: 'route-head__title', text: strings.cases.title }),
          el('div', { className: 'route-head__actions' }, [
            el('button', {
              className: 'btn btn--secondary btn--small',
              text: strings.cases.refresh,
              attrs: { type: 'button' },
              on: { click: onRefresh },
            }),
          ]),
        ])
      );

      if (status === 'loading' && items.length === 0) {
        root.append(skeleton(4));
        return;
      }

      if (status === 'error') {
        root.append(
          stateBlock({
            title: strings.common.error,
            body: strings.cases.loadFailed,
            actionLabel: strings.common.retry,
            onAction: onRefresh,
            variant: 'error',
          })
        );
        return;
      }

      if (items.length === 0) {
        root.append(
          stateBlock({
            title: strings.cases.emptyTitle,
            body: strings.cases.emptyBody,
          })
        );
        return;
      }

      // Requirement 5.9: the side effect of resolving is stated before anyone
      // clicks it, not discovered afterwards.
      root.append(
        el('div', { className: 'notice', attrs: { role: 'note' } }, [
          el('span', { text: strings.cases.resolveNotice }),
        ])
      );

      const ordered = [...items].sort((a, b) => {
        const rank = { OPEN: 0, TAKEN_OVER: 1, CLOSED: 2 };
        return (rank[a.statusToken] ?? 3) - (rank[b.statusToken] ?? 3);
      });

      root.append(
        el('div', { className: 'case-grid' }, ordered.map((item) => card(item, transition)))
      );
    },
  };
}
