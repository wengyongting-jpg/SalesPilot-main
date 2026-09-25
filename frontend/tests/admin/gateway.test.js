/**
 * Admin transport selection and the salespilot stub's explicit refusal to work.
 * Same audit-identified gap as the customer app's equivalent suite.
 */
import { test, describe } from 'node:test';
import assert from 'node:assert/strict';

import { installWindow } from '../helpers/browserStubs.js';

const stub = installWindow();
const { createGateway } = await import('../../admin/js/gateway/index.js');
const { createSalesPilotGateway } = await import(
  '../../admin/js/gateway/salespilot.js'
);
stub.restore();

describe('createGateway', () => {
  test('selects the mock adapter', () => {
    const gateway = createGateway({ transport: 'mock', mockLatencyScale: 0 });
    assert.equal(gateway.name, 'mock');
  });

  test('threads mockLatencyScale through to the mock adapter', async () => {
    const gateway = createGateway({ transport: 'mock', mockLatencyScale: 0 });
    const started = Date.now();
    await gateway.listConversations();
    assert.ok(Date.now() - started < 100);
  });

  test('selects the salespilot adapter', () => {
    const gateway = createGateway({ transport: 'salespilot' });
    assert.equal(gateway.name, 'salespilot');
  });

  test('an unknown transport throws', () => {
    assert.throws(() => createGateway({ transport: 'carrier-pigeon' }));
  });

  test('the error names the offending value', () => {
    assert.throws(
      () => createGateway({ transport: 'carrier-pigeon' }),
      (error) => error.message.includes('carrier-pigeon')
    );
  });
});

describe('salespilot adapter', () => {
  // No network here: these assert the adapter's contract surface. Request and
  // response mapping is verified against a live backend separately, because a
  // mocked fetch would only prove the mock agrees with itself.
  const gateway = () => createSalesPilotGateway({ apiBase: 'http://127.0.0.1:8000' });

  test('exposes the whole gateway interface', () => {
    const g = gateway();
    for (const method of [
      'listConversations',
      'getConversation',
      'listCases',
      'updateCaseStatus',
      'listAgentRuns',
      'getConversationCost',
      'sendRepReply',
      'seedDemoData',
      'analytics',
      'health',
    ]) {
      assert.equal(typeof g[method], 'function', `missing ${method}`);
    }
  });

  test('advertises every capability, now that the backend provides them', () => {
    assert.deepEqual(gateway().capabilities, {
      repReply: true,
      telemetry: true,
      author: true,
      quickReplies: true,
    });
  });

  test('a correlation key with no opportunity id returns nothing rather than querying', async () => {
    // The endpoint requires opportunity_id. Querying without it would be a 422;
    // the adapter short-circuits so the harness sees "no runs" instead of an error.
    const result = await gateway().listAgentRuns({ clientMessageId: 'orphan-key' });
    assert.deepEqual(result.items, []);
  });

  test('health resolves false rather than throwing when nothing is listening', async () => {
    const offline = createSalesPilotGateway({ apiBase: 'http://127.0.0.1:59999' });
    assert.equal(await offline.health(), false);
  });

  test('tolerates a trailing slash on apiBase', () => {
    const g = createSalesPilotGateway({ apiBase: 'http://127.0.0.1:8000/' });
    assert.equal(g.name, 'salespilot');
  });
});
