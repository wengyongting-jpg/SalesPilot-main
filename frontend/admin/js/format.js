/**
 * Display formatting helpers.
 *
 * These are presentation only. Nothing here derives, bands or recomputes a
 * backend value (requirement 3.7) — cost in particular is rendered from the
 * backend's amount and currency and never computed from tokens
 * (requirement 4.11).
 */
import { strings } from './strings.js';

/** 24-hour HH:MM, independent of locale ordering. */
export function time(value) {
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) return '—';
  return `${String(date.getHours()).padStart(2, '0')}:${String(
    date.getMinutes()
  ).padStart(2, '0')}`;
}

export function dateTime(value) {
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) return '—';
  return `${date.toLocaleDateString(undefined, {
    day: 'numeric',
    month: 'short',
  })} ${time(date)}`;
}

/** Relative-ish preview stamp for inbox rows. */
export function shortWhen(value) {
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  const today = new Date();
  const sameDay =
    date.getFullYear() === today.getFullYear() &&
    date.getMonth() === today.getMonth() &&
    date.getDate() === today.getDate();
  return sameDay ? time(date) : date.toLocaleDateString(undefined, {
    day: 'numeric',
    month: 'short',
  });
}

/** Milliseconds as ms or seconds. */
export function duration(ms) {
  if (ms === null || ms === undefined || Number.isNaN(ms)) return '—';
  if (ms < 1000) return `${Math.round(ms)} ms`;
  return `${(ms / 1000).toFixed(2)} s`;
}

/** Thousands separators, or an em dash when genuinely absent. */
export function count(value) {
  if (value === null || value === undefined) return '—';
  return Number(value).toLocaleString();
}

/**
 * Cost from the backend's own amount and currency.
 *
 * Three outcomes, because there are three different facts (requirement 4.10,
 * interface-v1.md §5.3 requirement 7):
 *
 * - no cost object at all  -> "not reported", never "0"
 * - `pricingKnown: false`  -> "price unknown". The backend sends `amount: 0.0`
 *   for a model absent from its price table, and that zero means "no idea", not
 *   "free". Rendering it as a number invites someone to budget against it.
 * - otherwise               -> the backend's own amount and currency
 */
export function cost(value) {
  if (!value || value.amount === null || value.amount === undefined) {
    return strings.observability.notReported;
  }
  if (value.pricingKnown === false) return strings.observability.priceUnknown;
  const amount = Number(value.amount);
  const currency = value.currency || '';
  const digits = amount > 0 && amount < 0.01 ? 6 : 4;
  return `${amount.toFixed(digits)} ${currency}`.trim();
}

/**
 * Sum a list of backend cost objects without inventing a currency.
 *
 * One unpriced part makes the whole total unpriced, mirroring the backend's own
 * `MIN(pricing_known)`: a sum is only as trustworthy as its worst component.
 */
export function sumCost(costs) {
  const present = costs.filter(
    (c) => c && c.amount !== null && c.amount !== undefined
  );
  if (present.length === 0) return null;
  const currencies = new Set(present.map((c) => c.currency || ''));
  return {
    amount: present.reduce((total, c) => total + Number(c.amount), 0),
    // Mixed currencies would be a backend bug; surface it rather than hide it.
    currency: currencies.size === 1 ? [...currencies][0] : '?',
    pricingKnown: present.every((c) => c.pricingKnown !== false),
  };
}

export function chars(value) {
  if (value === null || value === undefined) return '—';
  return `${count(value)} ${strings.observability.charsSuffix}`;
}

/** Truncate a transcript line for an inbox preview. */
export function preview(text, limit = 64) {
  const collapsed = String(text || '').replace(/\s+/g, ' ').trim();
  if (collapsed.length <= limit) return collapsed;
  return `${collapsed.slice(0, limit - 1)}…`;
}

/** Normalise a case status to a canonical token (requirement 5.3). */
export function normaliseStatus(value) {
  return String(value || '').toUpperCase().replace(/[\s-]+/g, '_');
}

/** Map a priority to a badge modifier. */
export function priorityClass(priority) {
  switch (String(priority || '').toUpperCase()) {
    case 'HIGH':
      return 'badge--high';
    case 'MEDIUM':
      return 'badge--medium';
    default:
      return 'badge--low';
  }
}

/** Map an agent run status to a badge modifier. */
export function runStatusClass(status) {
  switch (status) {
    case 'ok':
      return 'badge--ok';
    case 'degraded':
      return 'badge--degraded';
    case 'error':
      return 'badge--error';
    default:
      return 'badge--neutral';
  }
}
