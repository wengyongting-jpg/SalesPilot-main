/**
 * URL overrides on the customer config.
 *
 * The allow-list is a security boundary, not a convenience: the harness passes
 * configuration through the iframe URL, so anything reachable from a query string
 * is reachable by anyone who can hand someone a link.
 */
import { test, describe } from 'node:test';
import assert from 'node:assert/strict';

import { installWindow, importFresh } from '../helpers/browserStubs.js';

async function loadConfig(search, tag) {
  const stub = installWindow({ search });
  const { config } = await importFresh('../../customer/js/config.js', tag);
  stub.restore();
  return config;
}

describe('defaults', () => {
  test('mock transport, so the app runs with no server', async () => {
    const config = await loadConfig('', 'default');
    assert.equal(config.transport, 'mock');
    assert.equal(config.apiBase, '');
  });

  test('polling interval and scroll threshold are configured, not hard-coded', async () => {
    const config = await loadConfig('', 'default-2');
    assert.equal(typeof config.pollIntervalMs, 'number');
    assert.equal(typeof config.scrollBottomThresholdPx, 'number');
    assert.equal(typeof config.groupWindowMs, 'number');
  });
});

describe('allowed overrides', () => {
  test('transport, customer id and name', async () => {
    const config = await loadConfig(
      '?transport=salespilot&customerId=C-9001&customerName=Zed',
      'allowed'
    );
    assert.equal(config.transport, 'salespilot');
    assert.equal(config.customer.id, 'C-9001');
    assert.equal(config.customer.name, 'Zed');
  });

  test('apiBase', async () => {
    const config = await loadConfig('?apiBase=http://localhost:8000', 'apibase');
    assert.equal(config.apiBase, 'http://localhost:8000');
  });

  test('an empty parameter value is ignored rather than blanking the default', async () => {
    const config = await loadConfig('?customerName=', 'empty');
    assert.equal(config.customer.name, 'Sam');
  });
});

describe('rejected overrides', () => {
  test('an unknown transport falls back to the default', async () => {
    const config = await loadConfig('?transport=evil', 'bad-transport');
    assert.equal(config.transport, 'mock');
  });

  test('feature flags are not reachable from the URL', async () => {
    const config = await loadConfig('?features=hacked&demoMode=false', 'features');
    assert.equal(typeof config.features, 'object');
    assert.equal(config.features.demoMode, true);
  });

  test('nested internals are not reachable', async () => {
    // Read the untouched default once, so the assertion below tracks whatever
    // that default legitimately is instead of hard-coding a copy of it that
    // would go stale — and start from a value that could not, by coincidence,
    // equal the attack payload.
    const baseline = await loadConfig('', 'nested-baseline');
    assert.notEqual(baseline.sendTimeoutMs, 1, 'test payload must differ from the default');

    const config = await loadConfig(
      '?business=Evil&sendTimeoutMs=1&operator=x',
      'nested'
    );
    assert.equal(config.business.name, baseline.business.name);
    assert.equal(config.sendTimeoutMs, baseline.sendTimeoutMs);
    assert.equal(config.operator, undefined, 'there is no operator key to pollute');
  });

  test('prototype pollution attempts are ignored', async () => {
    const config = await loadConfig('?__proto__=x&constructor=y', 'proto');
    assert.equal(config.transport, 'mock');
    assert.equal({}.x, undefined);
  });
});

describe('robustness', () => {
  test('a malformed query string does not throw', async () => {
    const config = await loadConfig('?%%%&&&=', 'malformed');
    assert.equal(config.transport, 'mock');
  });

  test('the whatsapp transport is accepted by the allow-list', async () => {
    // Selecting it is expected to fail loudly at boot, not be silently rewritten.
    const config = await loadConfig('?transport=whatsapp', 'whatsapp');
    assert.equal(config.transport, 'whatsapp');
  });
});
