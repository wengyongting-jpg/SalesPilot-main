/**
 * Admin formatting helpers.
 *
 * The rule under test throughout: **absent is not zero.** An unmeasured cost and
 * a cost of zero are different facts, and conflating them produces a
 * plausible-looking wrong number — the failure mode this project keeps hitting.
 */
import { test, describe } from 'node:test';
import assert from 'node:assert/strict';

import { installWindow } from '../helpers/browserStubs.js';

const stub = installWindow();
const {
  time,
  dateTime,
  shortWhen,
  duration,
  count,
  cost,
  sumCost,
  chars,
  preview,
  normaliseStatus,
  priorityClass,
  runStatusClass,
} = await import('../../admin/js/format.js');
stub.restore();

describe('time', () => {
  test('24-hour HH:MM', () => {
    assert.equal(time(new Date(2026, 8, 22, 9, 5)), '09:05');
    assert.equal(time(new Date(2026, 8, 22, 0, 0)), '00:00');
  });

  test('an invalid date renders as an em dash, not NaN', () => {
    assert.equal(time('not a date'), '—');
  });
});

describe('dateTime', () => {
  test('combines a locale-agnostic day/month with the 24-hour time', () => {
    // Assert only what this module is responsible for: the day number is
    // present and the time portion is exactly HH:MM. The month name's exact
    // spelling and the ordering of day vs month are the runtime's locale
    // formatting, not this function's logic, and are deliberately not pinned
    // here (see the locale-sensitivity findings for `count`).
    const rendered = dateTime(new Date(2026, 8, 22, 14, 30));
    assert.match(rendered, /\b22\b/, 'day number must appear');
    assert.match(rendered, /14:30$/, 'must end with the 24-hour time');
  });

  test('an invalid date renders as an em dash', () => {
    assert.equal(dateTime('not a date'), '—');
    // Not dateTime(null): new Date(null) coerces to 0 (the 1970 epoch), which is
    // a *valid* date, not an invalid one — an easy trap when writing this kind
    // of test. dateTime(undefined) is the actual invalid case.
    assert.equal(dateTime(undefined), '—');
  });

  test('midnight renders as 00:00, not blank or 24:00', () => {
    assert.match(dateTime(new Date(2026, 8, 22, 0, 0)), /00:00$/);
  });
});

describe('shortWhen', () => {
  test('today renders as just the time', () => {
    const now = new Date();
    assert.equal(shortWhen(now), time(now));
    assert.doesNotMatch(shortWhen(now), /\d{1,2}:\d{2}.*\d{1,2}:\d{2}/);
  });

  test('a date on another day does not render as a bare time', () => {
    const yesterday = new Date();
    yesterday.setDate(yesterday.getDate() - 1);
    const rendered = shortWhen(yesterday);
    // It must differ from the HH:MM format used for "today", i.e. it must not
    // match the strict today-branch pattern. (node:assert/strict has
    // doesNotMatch, not notMatch — an easy typo since assert.match exists.)
    assert.doesNotMatch(rendered, /^\d{2}:\d{2}$/);
  });

  test('an invalid date does not throw, and renders empty rather than NaN', () => {
    // Unlike time()/dateTime()/duration()/count(), which render an em dash for
    // an absent or invalid value, shortWhen renders an empty string. This is an
    // existing inconsistency in the module, not something introduced here —
    // asserted as-is so a future harmonisation is a deliberate, visible change
    // rather than a silent one.
    assert.equal(shortWhen('not a date'), '');
  });

  test('undefined does not throw', () => {
    // new Date(null) is the 1970 epoch, a *valid* date — not tested here for
    // "absent", because it is not actually absent to the Date constructor.
    assert.equal(shortWhen(undefined), '');
  });
});

describe('duration', () => {
  test('sub-second in milliseconds', () => {
    assert.equal(duration(940), '940 ms');
  });

  test('one second and above in seconds', () => {
    assert.equal(duration(1240), '1.24 s');
  });

  test('exactly 1000ms crosses to seconds', () => {
    assert.equal(duration(1000), '1.00 s');
  });

  test('zero is a real measurement and renders as such', () => {
    assert.equal(duration(0), '0 ms');
  });

  test('absent renders as an em dash', () => {
    assert.equal(duration(null), '—');
    assert.equal(duration(undefined), '—');
  });
});

describe('count', () => {
  test('zero is shown, because zero is a measurement', () => {
    assert.equal(count(0), '0');
  });

  test('absent is an em dash, not zero', () => {
    assert.equal(count(null), '—');
    assert.equal(count(undefined), '—');
  });

  test('large numbers are grouped rather than printed as one run of digits', () => {
    // What this function is actually responsible for is calling
    // toLocaleString() at all. The exact separator character and grouping width
    // are the JS runtime's Intl implementation, which varies by locale — de-DE
    // uses '.', fr-FR uses a narrow no-break space, en-US and zh-CN use ','.
    // Pinning a specific separator, as an earlier version of this test did,
    // passes only by accident of the machine's configured locale and fails on
    // de-DE. Strip every non-digit and compare the digits alone instead.
    const digitsOnly = count(1234567).replace(/\D/g, '');
    assert.equal(digitsOnly, '1234567');
    assert.notEqual(count(1234567), '1234567', 'must be grouped, not one run of digits');
  });
});

describe('cost', () => {
  test('absent cost says so rather than showing zero', () => {
    assert.match(cost(null), /not reported/);
    assert.match(cost(undefined), /not reported/);
    assert.match(cost({ amount: null, currency: 'USD' }), /not reported/);
  });

  test('a real zero cost is rendered as a number', () => {
    assert.match(cost({ amount: 0, currency: 'USD' }), /0\.0000 USD/);
  });

  test('sub-cent amounts keep enough precision to be meaningful', () => {
    const rendered = cost({ amount: 0.00021, currency: 'USD' });
    assert.match(rendered, /0\.000210 USD/);
  });

  test('larger amounts use four decimals', () => {
    assert.match(cost({ amount: 1.5, currency: 'USD' }), /1\.5000 USD/);
  });
});

describe('sumCost', () => {
  test('an empty list totals to absent, not zero', () => {
    assert.equal(sumCost([]), null);
  });

  test('a list of only absent entries totals to absent', () => {
    assert.equal(sumCost([null, undefined, { amount: null }]), null);
  });

  test('sums matching currencies', () => {
    const total = sumCost([
      { amount: 1, currency: 'USD' },
      { amount: 2.5, currency: 'USD' },
    ]);
    assert.equal(total.amount, 3.5);
    assert.equal(total.currency, 'USD');
  });

  test('mixed currencies are flagged rather than silently added', () => {
    const total = sumCost([
      { amount: 1, currency: 'USD' },
      { amount: 2, currency: 'EUR' },
    ]);
    assert.equal(total.currency, '?');
  });

  test('absent entries are skipped, not treated as zero contributors', () => {
    const total = sumCost([{ amount: 5, currency: 'USD' }, null]);
    assert.equal(total.amount, 5);
    assert.equal(total.currency, 'USD');
  });
});

describe('chars', () => {
  test('renders a length with a unit', () => {
    // Same locale caveat as count(): assert the digits and the unit word are
    // present, not a specific grouping punctuation.
    const rendered = chars(2180);
    assert.equal(rendered.replace(/\D/g, ''), '2180');
    assert.match(rendered, /chars/);
  });

  test('absent length is an em dash', () => {
    assert.equal(chars(null), '—');
  });

  test('zero length is shown', () => {
    assert.match(chars(0), /^0 /);
  });
});

describe('preview', () => {
  test('collapses whitespace', () => {
    assert.equal(preview('hello   \n  world'), 'hello world');
  });

  test('truncates with an ellipsis', () => {
    const result = preview('x'.repeat(100), 20);
    assert.equal(result.length, 20);
    assert.ok(result.endsWith('…'));
  });

  test('leaves short text alone', () => {
    assert.equal(preview('short', 20), 'short');
  });

  test('handles absent text', () => {
    assert.equal(preview(null), '');
    assert.equal(preview(undefined), '');
  });
});

describe('normaliseStatus', () => {
  test('the backend title-case values become canonical tokens', () => {
    assert.equal(normaliseStatus('Open'), 'OPEN');
    assert.equal(normaliseStatus('Taken Over'), 'TAKEN_OVER');
    assert.equal(normaliseStatus('Closed'), 'CLOSED');
  });

  test('hyphens normalise too', () => {
    assert.equal(normaliseStatus('taken-over'), 'TAKEN_OVER');
  });

  test('an already canonical token is unchanged', () => {
    assert.equal(normaliseStatus('TAKEN_OVER'), 'TAKEN_OVER');
  });

  test('absent input does not throw', () => {
    assert.equal(normaliseStatus(null), '');
  });
});

describe('badge mapping', () => {
  test('priority bands', () => {
    assert.equal(priorityClass('HIGH'), 'badge--high');
    assert.equal(priorityClass('medium'), 'badge--medium');
    assert.equal(priorityClass('LOW'), 'badge--low');
  });

  test('an unknown priority degrades to low rather than throwing', () => {
    assert.equal(priorityClass(null), 'badge--low');
    assert.equal(priorityClass('WEIRD'), 'badge--low');
  });

  test('run statuses', () => {
    assert.equal(runStatusClass('ok'), 'badge--ok');
    assert.equal(runStatusClass('degraded'), 'badge--degraded');
    assert.equal(runStatusClass('error'), 'badge--error');
    assert.equal(runStatusClass('something-new'), 'badge--neutral');
  });
});
