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
  test('constructing it does no I/O and needs no configuration', () => {
    const gateway = createSalesPilotGateway();
    assert.equal(gateway.name, 'salespilot');
    for (const method of [
      'listConversations',
      'getConversation',
      'listCases',
      'updateCaseStatus',
      'listAgentRuns',
      'sendRepReply',
      'seedDemoData',
      'health',
    ]) {
      assert.equal(typeof gateway[method], 'function', method);
    }
  });

  test('health reports false rather than throwing when the backend is unreachable', async () => {
    const gateway = createSalesPilotGateway({ apiBase: 'http://127.0.0.1:1' });
    assert.equal(await gateway.health(), false);
  });

  test('a request against an unreachable backend rejects with status 0', async () => {
    const gateway = createSalesPilotGateway({ apiBase: 'http://127.0.0.1:1' });
    await assert.rejects(
      () => gateway.listConversations(),
      (error) => error.status === 0
    );
  });

  test('capabilities report what this backend serves', () => {
    const gateway = createSalesPilotGateway();
    assert.deepEqual(gateway.capabilities, {
      repReply: true,
      telemetry: true,
      author: true,
      quickReplies: true,
    });
  });

  test('listAgentRuns without a correlation key asks the backend nothing', async () => {
    // Guards the console's boot path: no opportunity selected means no query.
    const gateway = createSalesPilotGateway({ apiBase: 'http://127.0.0.1:1' });
    assert.deepEqual(await gateway.listAgentRuns(), { items: [] });
  });
});
