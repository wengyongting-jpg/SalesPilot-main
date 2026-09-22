/**
 * Inbox list — the left column.
 *
 * Rows are ordered by score descending (done in the store; presentation only).
 * Every row shows the opportunity id, because the backend keys opportunities on
 * id alone and two customers may legitimately share a display name
 * (requirement 1.3). Avatar colour is derived from the id for the same reason.
 *
 * There is deliberately no unread count: no read state exists anywhere in the
 * system, so attention is conveyed by priority and takeover only
 * (requirement 1.9).
 */
import { strings } from '../strings.js';
import { el, clear, badge, stateBlock, skeleton } from '../dom.js';
import { applyAvatar } from '../identity.js';
import { preview, shortWhen, priorityClass } from '../format.js';

/**
 * @param {object} deps
 * @param {HTMLElement} deps.el
 * @param {(id: string) => void} deps.onSelect
 * @param {() => void} deps.onRefresh
 * @param {() => void} deps.onSeed
 */
export function createInboxList({ el: root, onSelect, onRefresh, onSeed }) {
  let lastSignature = null;

  const header = (counts) =>
    el('div', { className: 'list-header' }, [
      el('div', { className: 'list-header__title', text: strings.inbox.listTitle }),
      el('div', { className: 'list-header__counts' }, [
        badge(`${counts.HIGH} high`, 'badge--high'),
        badge(`${counts.MEDIUM} med`, 'badge--medium'),
        badge(`${counts.LOW} low`, 'badge--low'),
      ]),
    ]);

  const row = (item, selected) => {
    const avatar = el('div', { className: 'avatar' });
    applyAvatar(avatar, { id: item.id, name: item.name });

    return el(
      'button',
      {
        className: selected ? 'conv-row is-selected' : 'conv-row',
        attrs: {
          type: 'button',
          'aria-pressed': selected ? 'true' : 'false',
          // The accessible name carries the id, so two same-named customers are
          // distinguishable without sight.
          'aria-label': `${item.name}, ${item.id}, score ${item.score ?? 'none'}, ${item.priority ?? 'unknown'} priority`,
        },
        on: { click: () => onSelect(item.id) },
      },
      [
        avatar,
        el('div', { className: 'conv-row__main' }, [
          el('div', { className: 'conv-row__top' }, [
            el('span', { className: 'conv-row__name', text: item.name }),
            el('span', { className: 'conv-row__id', text: item.id }),
          ]),
          el('div', {
            className: 'conv-row__preview',
            text: preview(item.lastMessagePreview),
          }),
        ]),
        el('div', { className: 'conv-row__meta' }, [
          el('span', {
            className: 'conv-row__score',
            text: item.score ?? '—',
          }),
          badge(item.priority ?? '—', priorityClass(item.priority)),
          item.humanTakeover
            ? badge(strings.inbox.takeoverMarker, 'badge--info')
            : el('span', {
                className: 'conv-row__id',
                text: shortWhen(item.lastMessageAt),
              }),
        ]),
      ]
    );
  };

  return {
    render(state) {
      const { status, items, counts } = state.inbox;
      const signature = `${status}|${state.selectedId}|${items
        .map((i) => `${i.id}:${i.score}:${i.humanTakeover}`)
        .join(',')}`;
      if (signature === lastSignature) return;
      lastSignature = signature;

      clear(root);

      if (status === 'loading' && items.length === 0) {
        root.append(skeleton(6));
        return;
      }

      if (status === 'error') {
        root.append(
          stateBlock({
            title: strings.common.error,
            body: strings.inbox.loadFailed,
            actionLabel: strings.inbox.retry,
            onAction: onRefresh,
            variant: 'error',
          })
        );
        return;
      }

      if (items.length === 0) {
        root.append(
          stateBlock({
            title: strings.inbox.emptyTitle,
            body: strings.inbox.emptyBody,
            actionLabel: strings.inbox.seed,
            onAction: onSeed,
          })
        );
        return;
      }

      root.append(header(counts));
      for (const item of items) {
        root.append(row(item, item.id === state.selectedId));
      }
      root.append(
        el('div', { className: 'list-header' }, [
          el('button', {
            className: 'btn btn--link',
            text: strings.inbox.refresh,
            attrs: { type: 'button' },
            on: { click: onRefresh },
          }),
        ])
      );
    },
  };
}
