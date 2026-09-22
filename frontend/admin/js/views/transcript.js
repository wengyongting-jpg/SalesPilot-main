/**
 * Conversation header and transcript.
 *
 * Every entry is labelled with its origin in text — Customer, AI Assistant,
 * Representative, System — not by colour alone (requirement 2.2, 9.7). `origin`
 * is resolved once in the adapter from `role` plus `author`, so this view never
 * re-derives it.
 *
 * All text renders through `textContent`. Transcript content is untrusted data.
 */
import { strings } from '../strings.js';
import { el, clear, badge, stateBlock, skeleton } from '../dom.js';
import { applyAvatar } from '../identity.js';
import { time, dateTime, priorityClass } from '../format.js';

/**
 * @param {object} deps
 * @param {HTMLElement} deps.headerEl
 * @param {HTMLElement} deps.transcriptEl
 * @param {() => void} deps.onRetry
 * @param {() => void} deps.onViewCase
 */
export function createTranscript({ headerEl, transcriptEl, onRetry, onViewCase }) {
  let lastSignature = null;

  const renderHeader = (opportunity) => {
    clear(headerEl);
    if (!opportunity) return;

    const avatar = el('div', { className: 'avatar' });
    applyAvatar(avatar, { id: opportunity.id, name: opportunity.name });

    headerEl.append(
      avatar,
      el('div', { className: 'conv-header__text' }, [
        el('div', { className: 'conv-header__name', text: opportunity.name }),
        el('div', { className: 'conv-header__sub' }, [
          el('span', { text: opportunity.id }),
          el('span', {
            text: `${opportunity.customerMessageCount} ${strings.conversation.messageCountLabel}`,
          }),
          el('span', { text: strings.product[opportunity.product] ?? opportunity.product }),
        ]),
      ]),
      el('div', { className: 'conv-header__actions' }, [
        badge(opportunity.state, 'badge--neutral'),
        badge(opportunity.priority ?? '—', priorityClass(opportunity.priority)),
        opportunity.humanTakeover
          ? badge(strings.inbox.takeoverMarker, 'badge--info')
          : null,
        onViewCase
          ? el('button', {
              className: 'btn btn--secondary btn--small',
              text: strings.conversation.openCase,
              attrs: { type: 'button' },
              on: { click: onViewCase },
            })
          : null,
      ])
    );
  };

  const entry = (message) => {
    const originLabel =
      message.origin === 'human' && message.repName
        ? `${strings.origin.human} · ${message.repName}`
        : strings.origin[message.origin] ?? message.origin;

    return el('div', { className: `entry entry--${message.origin}` }, [
      el('div', { className: 'entry__head' }, [
        el('span', { className: 'entry__origin', text: originLabel }),
        el('span', {
          className: 'entry__time',
          text: time(message.ts),
          attrs: { title: dateTime(message.ts) },
        }),
      ]),
      el('div', { className: 'entry__text', text: message.text }),
    ]);
  };

  return {
    render(state) {
      const { status, opportunity, messages } = state.conversation;
      const signature = `${status}|${opportunity?.id ?? '-'}|${opportunity?.humanTakeover}|${messages.length}`;
      if (signature === lastSignature) return;
      lastSignature = signature;

      if (!state.selectedId) {
        clear(headerEl);
        clear(transcriptEl);
        transcriptEl.append(
          stateBlock({
            title: strings.inbox.selectTitle,
            body: strings.inbox.selectBody,
          })
        );
        return;
      }

      if (status === 'loading') {
        clear(headerEl);
        clear(transcriptEl);
        transcriptEl.append(skeleton(5));
        return;
      }

      if (status === 'error') {
        clear(headerEl);
        clear(transcriptEl);
        transcriptEl.append(
          stateBlock({
            title: strings.common.error,
            body: strings.inbox.conversationFailed,
            actionLabel: strings.common.retry,
            onAction: onRetry,
            variant: 'error',
          })
        );
        return;
      }

      renderHeader(opportunity);
      clear(transcriptEl);

      if (messages.length === 0) {
        transcriptEl.append(
          stateBlock({ body: strings.conversation.transcriptEmpty })
        );
        return;
      }

      for (const message of messages) transcriptEl.append(entry(message));
      transcriptEl.scrollTop = transcriptEl.scrollHeight;
    },
  };
}
