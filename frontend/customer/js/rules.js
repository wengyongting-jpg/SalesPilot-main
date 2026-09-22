/**
 * Pure presentation rules for the message list.
 *
 * Extracted from messageList.js so they can be tested without a DOM. Grouping,
 * tail attribution, date-separator placement and the auto-scroll decision are the
 * rules most likely to be broken by a careless edit, and they were previously
 * only checkable by eye.
 *
 * Nothing here touches the DOM, the store, or any module-level state. Every
 * function is a function of its arguments alone.
 */

const MS_PER_DAY = 86400000;

/** 24-hour `HH:MM`, independent of locale ordering (requirement 1.6). */
export function formatTime(date) {
  const hours = String(date.getHours()).padStart(2, '0');
  const minutes = String(date.getMinutes()).padStart(2, '0');
  return `${hours}:${minutes}`;
}

export function startOfDay(date) {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate());
}

export function isSameDay(a, b) {
  return startOfDay(a).getTime() === startOfDay(b).getTime();
}

/**
 * Which kind of date-separator label a message needs.
 *
 * Returns a token rather than text so the copy stays in strings.js
 * (requirement 1.5).
 *
 * @param {Date} date
 * @param {Date} [now] injectable for testing
 * @returns {'today'|'yesterday'|'absolute'}
 */
export function dayLabelKind(date, now = new Date()) {
  const dayDiff = Math.round((startOfDay(now) - startOfDay(date)) / MS_PER_DAY);
  if (dayDiff === 0) return 'today';
  if (dayDiff === 1) return 'yesterday';
  return 'absolute';
}

/** True when a date separator belongs before `message` (requirement 1.4). */
export function needsDateSeparator(message, previous) {
  if (!previous) return true;
  return !isSameDay(previous.ts, message.ts);
}

/**
 * True when `message` begins a new run, and therefore carries the bubble tail
 * and the larger top gap (requirements 1.2, 1.3).
 *
 * A run breaks on a different author, on a gap wider than the grouping window,
 * and around system messages — which are not bubbles and so never group.
 *
 * @param {{author: string, ts: Date}} message
 * @param {{author: string, ts: Date}|null} previous
 * @param {number} groupWindowMs
 */
export function startsRun(message, previous, groupWindowMs) {
  if (!previous) return true;
  if (previous.author === 'system' || message.author === 'system') return true;
  if (previous.author !== message.author) return true;
  return message.ts - previous.ts > groupWindowMs;
}

/**
 * True when the list is close enough to the bottom to follow new messages
 * (requirement 4.1, 4.2).
 *
 * @param {{scrollHeight: number, scrollTop: number, clientHeight: number}} metrics
 * @param {number} thresholdPx
 */
export function isNearBottom({ scrollHeight, scrollTop, clientHeight }, thresholdPx) {
  return scrollHeight - scrollTop - clientHeight <= thresholdPx;
}

/**
 * Whether to scroll to the newest message after a render.
 *
 * Sending always scrolls, regardless of position (requirement 4.5). Anything
 * arriving from the other side scrolls only when already near the bottom
 * (requirements 4.1, 4.2).
 *
 * @param {{ appended: number, typingAppeared: boolean, atBottom: boolean,
 *           lastAppendedDirection: 'out'|'in'|null }} args
 */
export function shouldAutoScroll({
  appended,
  typingAppeared,
  atBottom,
  lastAppendedDirection,
}) {
  const somethingChanged = appended > 0 || typingAppeared;
  if (!somethingChanged) return false;
  if (lastAppendedDirection === 'out') return true;
  return atBottom;
}
