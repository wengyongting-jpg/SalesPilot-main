/**
 * Customer mock transport, including the rendering fixture that the visual checks
 * in tasks.md depend on. If the fixture stops covering a case, the corresponding
 * manual check silently becomes vacuous — so its shape is asserted here.
 */
import { test, describe } from 'node:test';
import assert from 'node:assert/strict';

import { installWindow, importFresh } from '../helpers/browserStubs.js';

async function loadGateway(search, tag) {
  const stub = installWindow({ search });
  const { createMockGateway } = await importFresh(
    '../../customer/js/gateway/mock.js',
    tag
  );
  const gateway = createMockGateway();
  stub.restore();
  return gateway;
}

describe('scenario selection', () => {
  test('defaults to a fresh, empty conversation', async () => {
    const gateway = await loadGateway('', 'fresh');
    const { messages } = await gateway.loadHistory();
    assert.equal(messages.length, 0);
  });

  test('an unknown scenario falls back to fresh', async () => {
    const gateway = await loadGateway('?scenario=nonsense', 'unknown');
    const { messages } = await gateway.loadHistory();
    assert.equal(messages.length, 0);
  });

  test('the rendering fixture loads a transcript', async () => {
    const gateway = await loadGateway('?scenario=rendering', 'render');
    const { messages } = await gateway.loadHistory();
    assert.ok(messages.length >= 8);
  });
});

describe('rendering fixture coverage', () => {
  /** @type {Array<object>} */
  let messages;
  let byId;

  test('load', async () => {
    const gateway = await loadGateway('?scenario=rendering', 'render-cov');
    ({ messages } = await gateway.loadHistory());
    byId = Object.fromEntries(messages.map((m) => [m.id, m]));
    assert.ok(messages.length > 0);
  });

  test('timestamps never go backwards', () => {
    for (let i = 1; i < messages.length; i += 1) {
      assert.ok(
        messages[i].ts >= messages[i - 1].ts,
        `out of order at index ${i}`
      );
    }
  });

  test('spans two calendar days, so a date separator is exercised', () => {
    const days = new Set(messages.map((m) => m.ts.toDateString()));
    assert.equal(days.size, 2);
  });

  test('contains a same-author same-minute run that must group', () => {
    assert.equal(byId['fx-3'].author, byId['fx-4'].author);
    assert.equal(byId['fx-4'].author, byId['fx-5'].author);
    assert.ok(byId['fx-5'].ts - byId['fx-3'].ts < 60000);
  });

  test('contains a same-timestamp pair from different authors that must NOT group', () => {
    assert.equal(byId['fx-1'].ts.getTime(), byId['fx-2'].ts.getTime());
    assert.notEqual(byId['fx-1'].author, byId['fx-2'].author);
  });

  test('contains literal HTML, to prove it renders as text', () => {
    assert.match(byId['fx-5'].text, /<script>/);
  });

  test('contains a URL, to prove it is not linkified', () => {
    assert.match(byId['fx-6'].text, /https:\/\//);
  });

  test('contains an emoji-only message', () => {
    assert.equal(byId['fx-7'].text, '\u{1F44D}');
  });

  test('contains a system message', () => {
    assert.equal(byId['fx-8'].author, 'system');
  });

  test('every message carries a normalised shape', () => {
    for (const message of messages) {
      assert.ok(['out', 'in'].includes(message.direction));
      assert.ok(['customer', 'ai', 'human', 'system'].includes(message.author));
      assert.ok(message.ts instanceof Date);
      assert.equal(typeof message.text, 'string');
      assert.equal(typeof message.clientId, 'string');
    }
  });
});

describe('artificial latency', () => {
  // Regression guard: an earlier version read `mockLatency` lazily inside
  // send()/loadHistory(), which sampled window.location.search *after* the test
  // helper had already restored the real window, so the override silently had no
  // effect and every test in this file took 700-1200ms for real. The fix reads it
  // once at construction time, alongside the scenario. This test would fail
  // (time out or take over half a second) if that regressed.
  test('mockLatency=0 actually eliminates the delay, not just accepts the param', async () => {
    const gateway = await loadGateway('', 'latency-real');
    const started = Date.now();
    await gateway.send({ text: 'hello' });
    const elapsed = Date.now() - started;
    assert.ok(
      elapsed < 200,
      `expected near-instant resolution, took ${elapsed}ms — the MIN_LATENCY_MS ` +
        'floor is 700ms, so anything close to that means the scale is not applied'
    );
  });

  test('loadHistory is scaled the same way', async () => {
    const gateway = await loadGateway('?scenario=rendering', 'latency-real-2');
    const started = Date.now();
    await gateway.loadHistory();
    assert.ok(Date.now() - started < 200);
  });
});

describe('send', () => {
  test('returns one reply and no quick replies', async () => {
    const gateway = await loadGateway('', 'send');
    const result = await gateway.send({ text: 'hello' });
    assert.equal(result.messages.length, 1);
    assert.equal(result.messages[0].direction, 'in');
    assert.equal(result.messages[0].author, 'ai');
    assert.equal(result.quickReplies.length, 0);
  });

  test('advertises the current backend capability set', async () => {
    // Mirrors the real backend on purpose, so the degraded paths are the ones
    // being exercised rather than an idealised set.
    const gateway = await loadGateway('', 'caps');
    const { capabilities } = await gateway.send({ text: 'hello' });
    assert.equal(capabilities.quickReplies, false);
    assert.equal(capabilities.incrementalFetch, false);
  });

  test('a message containing "fail" is rejected, so retry can be demonstrated', async () => {
    const gateway = await loadGateway('', 'fail');
    await assert.rejects(() => gateway.send({ text: 'please fail' }));
  });

  test('"failure" also trips the word-boundary trigger only as a whole word', async () => {
    const gateway = await loadGateway('', 'fail-word');
    // "failsafe" contains "fail" but not as a whole word, so it must succeed.
    const result = await gateway.send({ text: 'failsafe please' });
    assert.equal(result.messages.length, 1);
  });

  test('a scripted reply carries the demo disclaimer untruncated', async () => {
    const gateway = await loadGateway('', 'disclaimer');
    await gateway.send({ text: 'hi' });
    const second = await gateway.send({ text: 'how much?' });
    assert.match(second.messages[0].text, /fictional indicative rates/);
    assert.match(second.messages[0].text, /insurer assessment\./);
  });

  test('the reply script does not run out', async () => {
    const gateway = await loadGateway('', 'exhaust');
    for (let i = 0; i < 8; i += 1) {
      const result = await gateway.send({ text: `message ${i}` });
      assert.equal(result.messages.length, 1);
      assert.ok(result.messages[0].text.length > 0);
    }
  });
});

describe('reset and health', () => {
  test('reset empties the history', async () => {
    const gateway = await loadGateway('?scenario=rendering', 'reset');
    await gateway.reset();
    const { messages } = await gateway.loadHistory();
    assert.equal(messages.length, 0);
  });

  test('health is true for the offline mock', async () => {
    const gateway = await loadGateway('', 'health');
    assert.equal(await gateway.health(), true);
  });

  test('fetchSince returns nothing, matching the absent backend cursor', async () => {
    const gateway = await loadGateway('', 'since');
    const { messages } = await gateway.fetchSince();
    assert.equal(messages.length, 0);
  });
});
