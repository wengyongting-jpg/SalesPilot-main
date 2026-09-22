/**
 * Message list view.
 *
 * Owns the scroll container: bubbles, grouping, tails, date separators, system
 * messages, delivery ticks, the typing indicator, and the empty / loading /
 * error states.
 *
 * Rendering is incremental. Messages only ever append, and a message's "lead of
 * run" status and preceding date separator are decided by the message before it,
 * which already exists — so appending never requires revisiting earlier bubbles.
 * That keeps the pop-in animation from replaying on every state change.
 *
 * All text is written with `textContent`. Message bodies, and later
 * knowledge-base facts, are untrusted data and are never treated as markup.
 * Exception: AI-generated messages may contain Markdown formatting which is
 * parsed into safe DOM structure (no innerHTML).
 */
import { config } from '../config.js';
import { strings } from '../strings.js';
import { icons } from '../icons.js';
import { isEmojiOnly } from '../emoji.js';
import { messageKey } from '../store.js';
import { parseMessageMarkdown, hasMarkdownFormatting } from '../markdown.js';
import {
  formatTime,
  dayLabelKind,
  needsDateSeparator,
  startsRun as startsRunRule,
  isNearBottom,
  shouldAutoScroll,
} from '../rules.js';

/** Today / Yesterday / absolute date (requirement 1.5). */
function formatDateLabel(date) {
  switch (dayLabelKind(date)) {
    case 'today':
      return strings.separator.today;
    case 'yesterday':
      return strings.separator.yesterday;
    default:
      return date.toLocaleDateString(undefined, {
        day: 'numeric',
        month: 'long',
        year: 'numeric',
      });
  }
}

const startsRun = (message, previous) =>
  startsRunRule(message, previous, config.groupWindowMs);

function tickMarkup(status) {
  switch (status) {
    case 'sending':
      return { glyph: icons.clock, cls: 'tick--sending', label: strings.message.statusSending };
    case 'sent':
      return { glyph: icons.tickSingle, cls: 'tick--sent', label: strings.message.statusSent };
    case 'read':
      return { glyph: icons.tickDouble, cls: 'tick--read', label: strings.message.statusRead };
    case 'failed':
      return { glyph: icons.alertCircle, cls: 'tick--failed', label: strings.message.statusFailed };
    default:
      return null;
  }
}

/**
 * @param {object} deps
 * @param {HTMLElement} deps.listEl scroll container
 * @param {HTMLElement} deps.statesEl empty / loading / error mount
 * @param {HTMLElement} deps.itemsEl message mount
 * @param {(clientId: string) => void} deps.onRetry
 * @param {() => void} deps.onRetryHistory
 * @param {(atBottom: boolean) => void} deps.onScrollChange
 */
export function createMessageList({
  listEl,
  statesEl,
  itemsEl,
  onRetry,
  onRetryHistory,
  onScrollChange,
}) {
  /** key -> { bubbleEl, tickEl, retryEl, status, separatorEl } */
  const rendered = new Map();
  /** Keys in render order, used to detect a reset or a history replacement. */
  let renderedKeys = [];
  let typingEl = null;
  let lastHistoryState = null;

  listEl.setAttribute('role', 'log');
  listEl.setAttribute('aria-live', 'polite');
  listEl.setAttribute('aria-relevant', 'additions');
  listEl.setAttribute('aria-label', strings.list.ariaLabel);

  listEl.addEventListener('scroll', () => {
    onScrollChange(isNearBottom(listEl, config.scrollBottomThresholdPx));
  });

  function scrollToBottom() {
    listEl.scrollTop = listEl.scrollHeight;
  }

  // ---- States ----------------------------------------------------------

  function renderEmptyState() {
    const wrap = document.createElement('div');
    wrap.className = 'state';

    const avatar = document.createElement('div');
    avatar.className = 'state__avatar';
    avatar.textContent = config.business.avatarInitials;

    const title = document.createElement('div');
    title.className = 'state__title';
    title.textContent = strings.empty.title;

    const body = document.createElement('div');
    body.className = 'state__body';
    body.textContent = strings.empty.body;

    wrap.append(avatar, title, body);
    return wrap;
  }

  function renderLoadingState() {
    const wrap = document.createElement('div');
    wrap.className = 'skeleton';
    wrap.setAttribute('aria-label', strings.loading.ariaLabel);
    wrap.setAttribute('aria-busy', 'true');
    for (const variant of ['in', 'out', 'in-wide']) {
      const bubble = document.createElement('div');
      bubble.className = `skeleton__bubble skeleton__bubble--${variant}`;
      wrap.append(bubble);
    }
    return wrap;
  }

  function renderErrorState() {
    const wrap = document.createElement('div');
    wrap.className = 'state';

    const body = document.createElement('div');
    body.className = 'state__body';
    body.textContent = strings.historyError.body;

    const action = document.createElement('button');
    action.type = 'button';
    action.className = 'state__action';
    action.textContent = strings.historyError.action;
    action.addEventListener('click', onRetryHistory);

    wrap.append(body, action);
    return wrap;
  }

  /** Empty state only when there is genuinely nothing to show. */
  function renderStates(state) {
    const key = `${state.history}:${state.messages.length === 0}`;
    if (key === lastHistoryState) return;
    lastHistoryState = key;

    statesEl.replaceChildren();
    if (state.history === 'loading' && state.messages.length === 0) {
      statesEl.append(renderLoadingState());
    } else if (state.history === 'error') {
      // Requirement 12.3: messages already rendered stay on screen.
      statesEl.append(renderErrorState());
    } else if (state.messages.length === 0) {
      statesEl.append(renderEmptyState());
    }
  }

  // ---- Messages --------------------------------------------------------

  function buildSeparator(date) {
    const el = document.createElement('div');
    el.className = 'separator';
    el.textContent = formatDateLabel(date);
    return el;
  }

  function buildSystemMessage(message) {
    const el = document.createElement('div');
    el.className = 'system-message';
    el.setAttribute('role', 'note');
    el.textContent = message.text;
    return el;
  }

  function buildTick(status) {
    const spec = tickMarkup(status);
    if (!spec) return null;
    const el = document.createElement('span');
    el.className = `tick ${spec.cls}`;
    el.innerHTML = spec.glyph; // hand-authored icon constant, not user input
    el.setAttribute('aria-label', spec.label);
    el.setAttribute('role', 'img');
    return el;
  }

  function buildRetry(message, capabilities) {
    const el = document.createElement('button');
    el.type = 'button';
    el.className = 'retry';
    el.textContent = strings.message.retryLabel;
    el.setAttribute('aria-label', strings.message.retryLabel);

    // Requirement 2.10: warn while the backend cannot deduplicate a resend.
    if (!capabilities.idempotency) {
      el.title = strings.message.retryDuplicateWarning;
      const description = document.createElement('span');
      description.className = 'visually-hidden';
      description.id = `retry-note-${message.clientId}`;
      description.textContent = strings.message.retryDuplicateWarning;
      el.append(description);
      el.setAttribute('aria-describedby', description.id);
    }

    el.addEventListener('click', () => onRetry(message.clientId));
    return el;
  }

  function buildBubble(message, isLead) {
    const el = document.createElement('div');
    const classes = ['bubble', message.direction === 'out' ? 'bubble--out' : 'bubble--in'];
    if (isLead) classes.push('bubble--lead');
    if (isEmojiOnly(message.text)) classes.push('bubble--emoji');
    el.className = classes.join(' ');

    const text = document.createElement('div');
    text.className = 'bubble__text';

    // AI messages may contain Markdown formatting - parse it into safe DOM
    // Customer messages are always plain text (requirements 1.7, 1.9)
    if (message.direction === 'in' && message.author === 'ai' && hasMarkdownFormatting(message.text)) {
      text.appendChild(parseMessageMarkdown(message.text));
    } else {
      // Untrusted content: text only, and no linkification
      text.textContent = message.text;
    }

    const meta = document.createElement('div');
    meta.className = 'bubble__meta';

    const time = document.createElement('span');
    time.className = 'bubble__time';
    time.textContent = formatTime(message.ts);
    meta.append(time);

    el.append(text, meta);
    return { el, meta };
  }

  /** Full rebuild, used on reset and on history replacement. */
  function rebuild() {
    itemsEl.replaceChildren();
    rendered.clear();
    renderedKeys = [];
    typingEl = null;
  }

  /** True when the rendered list is no longer a prefix of the current list. */
  function needsRebuild(messages) {
    if (messages.length < renderedKeys.length) return true;
    return renderedKeys.some((key, index) => messageKey(messages[index]) !== key);
  }

  function appendMessage(message, previous, capabilities) {
    const key = messageKey(message);
    const entry = { separatorEl: null, bubbleEl: null, tickEl: null, retryEl: null, status: message.status };

    if (needsDateSeparator(message, previous)) {
      entry.separatorEl = buildSeparator(message.ts);
      itemsEl.append(entry.separatorEl);
    }

    if (message.author === 'system') {
      entry.bubbleEl = buildSystemMessage(message);
      itemsEl.append(entry.bubbleEl);
    } else {
      const { el, meta } = buildBubble(message, startsRun(message, previous));
      entry.bubbleEl = el;
      itemsEl.append(el);

      if (message.direction === 'out') {
        entry.tickEl = buildTick(message.status);
        if (entry.tickEl) meta.append(entry.tickEl);
        if (message.status === 'failed') {
          entry.retryEl = buildRetry(message, capabilities);
          itemsEl.append(entry.retryEl);
        }
      }
    }

    rendered.set(key, entry);
    renderedKeys.push(key);
  }

  /** Update the tick and retry affordance of an already-rendered message. */
  function updateMessage(message, capabilities) {
    const entry = rendered.get(messageKey(message));
    if (!entry || entry.status === message.status) return;
    entry.status = message.status;

    if (message.direction !== 'out') return;

    const meta = entry.bubbleEl.querySelector('.bubble__meta');
    const nextTick = buildTick(message.status);
    if (entry.tickEl) entry.tickEl.remove();
    entry.tickEl = nextTick;
    if (nextTick && meta) meta.append(nextTick);

    if (message.status === 'failed' && !entry.retryEl) {
      entry.retryEl = buildRetry(message, capabilities);
      entry.bubbleEl.after(entry.retryEl);
    } else if (message.status !== 'failed' && entry.retryEl) {
      entry.retryEl.remove();
      entry.retryEl = null;
    }
  }

  // ---- Typing indicator ------------------------------------------------

  function renderTyping(typing) {
    if (typing && !typingEl) {
      typingEl = document.createElement('div');
      typingEl.className = 'typing';
      typingEl.setAttribute('aria-hidden', 'true');
      for (let i = 0; i < 3; i += 1) {
        const dot = document.createElement('span');
        dot.className = 'typing__dot';
        typingEl.append(dot);
      }
      itemsEl.append(typingEl);
      return true;
    }
    if (!typing && typingEl) {
      typingEl.remove();
      typingEl = null;
    }
    return false;
  }

  // ---- Public ----------------------------------------------------------

  return {
    scrollToBottom,

    render(state) {
      renderStates(state);

      if (needsRebuild(state.messages)) rebuild();

      let appended = 0;
      let lastAppended = null;

      for (let i = 0; i < state.messages.length; i += 1) {
        const message = state.messages[i];
        if (rendered.has(messageKey(message))) {
          updateMessage(message, state.capabilities);
          continue;
        }
        appendMessage(message, state.messages[i - 1] ?? null, state.capabilities);
        appended += 1;
        lastAppended = message;
      }

      // The typing indicator must always sit after the newest message.
      const typingAppeared = renderTyping(state.assistant.typing);
      if (typingEl && appended > 0) itemsEl.append(typingEl);

      if (
        shouldAutoScroll({
          appended,
          typingAppeared,
          atBottom: state.scroll.atBottom,
          lastAppendedDirection: lastAppended?.direction ?? null,
        })
      ) {
        scrollToBottom();
      }
    },
  };
}
