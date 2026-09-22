/**
 * Message-list presentation rules.
 *
 * These were previously module-private inside messageList.js and therefore only
 * checkable by eye: a careless change to the grouping condition would have
 * produced no warning anywhere. They are the reason this suite exists.
 */
import { test, describe } from 'node:test';
import assert from 'node:assert/strict';

import {
  formatTime,
  startOfDay,
  isSameDay,
  dayLabelKind,
  needsDateSeparator,
  startsRun,
  isNearBottom,
  shouldAutoScroll,
} from '../../customer/js/rules.js';

const GROUP_WINDOW_MS = 60000;

/** A message stub carrying only what the rules read. */
const msg = (author, ts) => ({ author, ts: ts instanceof Date ? ts : new Date(ts) });

const at = (y, m, d, h, min) => new Date(y, m - 1, d, h, min, 0, 0);

describe('formatTime', () => {
  test('pads to 24-hour HH:MM', () => {
    assert.equal(formatTime(at(2026, 9, 22, 9, 5)), '09:05');
    assert.equal(formatTime(at(2026, 9, 22, 23, 59)), '23:59');
  });

  test('renders midnight as 00:00, not 24:00 or 12:00', () => {
    assert.equal(formatTime(at(2026, 9, 22, 0, 0)), '00:00');
  });

  test('renders noon as 12:00 with no meridiem', () => {
    assert.equal(formatTime(at(2026, 9, 22, 12, 0)), '12:00');
  });
});

describe('startOfDay / isSameDay', () => {
  test('same calendar day at different times', () => {
    assert.ok(isSameDay(at(2026, 9, 22, 0, 1), at(2026, 9, 22, 23, 58)));
  });

  test('one minute apart across midnight is NOT the same day', () => {
    assert.ok(!isSameDay(at(2026, 9, 22, 23, 59), at(2026, 9, 23, 0, 0)));
  });

  test('same day-of-month in different months is not the same day', () => {
    assert.ok(!isSameDay(at(2026, 8, 22, 10, 0), at(2026, 9, 22, 10, 0)));
  });

  test('startOfDay zeroes the time component', () => {
    const start = startOfDay(at(2026, 9, 22, 17, 43));
    assert.equal(start.getHours(), 0);
    assert.equal(start.getMinutes(), 0);
    assert.equal(start.getSeconds(), 0);
    assert.equal(start.getMilliseconds(), 0);
  });
});

describe('dayLabelKind', () => {
  const now = at(2026, 9, 22, 12, 0);

  test('today', () => {
    assert.equal(dayLabelKind(at(2026, 9, 22, 1, 0), now), 'today');
  });

  test('yesterday', () => {
    assert.equal(dayLabelKind(at(2026, 9, 21, 23, 59), now), 'yesterday');
  });

  test('two days ago falls back to an absolute date', () => {
    assert.equal(dayLabelKind(at(2026, 9, 20, 12, 0), now), 'absolute');
  });

  test('a minute before midnight is yesterday, not today', () => {
    // The boundary that a naive "less than 24 hours" check gets wrong.
    assert.equal(dayLabelKind(at(2026, 9, 21, 23, 59), at(2026, 9, 22, 0, 1)), 'yesterday');
  });

  test('crossing a month boundary still reads as yesterday', () => {
    assert.equal(dayLabelKind(at(2026, 8, 31, 22, 0), at(2026, 9, 1, 9, 0)), 'yesterday');
  });
});

describe('needsDateSeparator', () => {
  test('the first message always gets one', () => {
    assert.ok(needsDateSeparator(msg('customer', at(2026, 9, 22, 9, 0)), null));
  });

  test('no separator within the same day', () => {
    const previous = msg('customer', at(2026, 9, 22, 9, 0));
    const current = msg('ai', at(2026, 9, 22, 18, 0));
    assert.ok(!needsDateSeparator(current, previous));
  });

  test('separator inserted across midnight', () => {
    const previous = msg('customer', at(2026, 9, 22, 23, 59));
    const current = msg('customer', at(2026, 9, 23, 0, 0));
    assert.ok(needsDateSeparator(current, previous));
  });
});

describe('startsRun', () => {
  test('the first message starts a run', () => {
    assert.ok(startsRun(msg('customer', at(2026, 9, 22, 9, 0)), null, GROUP_WINDOW_MS));
  });

  test('same author within the window continues the run', () => {
    const previous = msg('customer', at(2026, 9, 22, 9, 0));
    const current = msg('customer', new Date(previous.ts.getTime() + 30000));
    assert.ok(!startsRun(current, previous, GROUP_WINDOW_MS));
  });

  test('same author exactly at the window boundary still continues', () => {
    const previous = msg('customer', at(2026, 9, 22, 9, 0));
    const current = msg('customer', new Date(previous.ts.getTime() + GROUP_WINDOW_MS));
    assert.ok(!startsRun(current, previous, GROUP_WINDOW_MS), 'boundary is inclusive');
  });

  test('same author one millisecond past the window starts a new run', () => {
    const previous = msg('customer', at(2026, 9, 22, 9, 0));
    const current = msg('customer', new Date(previous.ts.getTime() + GROUP_WINDOW_MS + 1));
    assert.ok(startsRun(current, previous, GROUP_WINDOW_MS));
  });

  test('different author in the same minute starts a new run', () => {
    // The case the rendering fixture exercises: alignment differs, so these must
    // not group even though they share a timestamp.
    const ts = at(2026, 9, 22, 16, 4);
    assert.ok(startsRun(msg('ai', ts), msg('customer', ts), GROUP_WINDOW_MS));
  });

  test('ai and human are different authors and do not group', () => {
    const previous = msg('ai', at(2026, 9, 22, 9, 0));
    const current = msg('human', new Date(previous.ts.getTime() + 1000));
    assert.ok(startsRun(current, previous, GROUP_WINDOW_MS));
  });

  test('a system message always starts a run', () => {
    const previous = msg('ai', at(2026, 9, 22, 9, 0));
    const current = msg('system', new Date(previous.ts.getTime() + 1000));
    assert.ok(startsRun(current, previous, GROUP_WINDOW_MS));
  });

  test('a message after a system message always starts a run', () => {
    const previous = msg('system', at(2026, 9, 22, 9, 0));
    const current = msg('ai', new Date(previous.ts.getTime() + 1000));
    assert.ok(startsRun(current, previous, GROUP_WINDOW_MS));
  });

  test('two consecutive system messages do not group either', () => {
    const previous = msg('system', at(2026, 9, 22, 9, 0));
    const current = msg('system', new Date(previous.ts.getTime() + 1000));
    assert.ok(startsRun(current, previous, GROUP_WINDOW_MS));
  });
});

describe('isNearBottom', () => {
  const threshold = 80;

  test('exactly at the bottom', () => {
    assert.ok(isNearBottom({ scrollHeight: 1000, scrollTop: 600, clientHeight: 400 }, threshold));
  });

  test('within the threshold', () => {
    assert.ok(isNearBottom({ scrollHeight: 1000, scrollTop: 530, clientHeight: 400 }, threshold));
  });

  test('exactly on the threshold counts as near', () => {
    assert.ok(isNearBottom({ scrollHeight: 1000, scrollTop: 520, clientHeight: 400 }, threshold));
  });

  test('one pixel beyond the threshold is not near', () => {
    assert.ok(!isNearBottom({ scrollHeight: 1000, scrollTop: 519, clientHeight: 400 }, threshold));
  });

  test('a list shorter than its viewport is always near the bottom', () => {
    assert.ok(isNearBottom({ scrollHeight: 200, scrollTop: 0, clientHeight: 400 }, threshold));
  });
});

describe('shouldAutoScroll', () => {
  const base = {
    appended: 0,
    typingAppeared: false,
    atBottom: true,
    lastAppendedDirection: null,
  };

  test('nothing changed means no scroll', () => {
    assert.ok(!shouldAutoScroll(base));
  });

  test('own message scrolls even when scrolled far away', () => {
    assert.ok(
      shouldAutoScroll({
        ...base,
        appended: 1,
        atBottom: false,
        lastAppendedDirection: 'out',
      })
    );
  });

  test('incoming message does not scroll when scrolled away', () => {
    assert.ok(
      !shouldAutoScroll({
        ...base,
        appended: 1,
        atBottom: false,
        lastAppendedDirection: 'in',
      })
    );
  });

  test('incoming message scrolls when already at the bottom', () => {
    assert.ok(
      shouldAutoScroll({
        ...base,
        appended: 1,
        atBottom: true,
        lastAppendedDirection: 'in',
      })
    );
  });

  test('the typing indicator appearing scrolls when at the bottom', () => {
    assert.ok(shouldAutoScroll({ ...base, typingAppeared: true, atBottom: true }));
  });

  test('the typing indicator does not yank the view when scrolled away', () => {
    assert.ok(!shouldAutoScroll({ ...base, typingAppeared: true, atBottom: false }));
  });
});
