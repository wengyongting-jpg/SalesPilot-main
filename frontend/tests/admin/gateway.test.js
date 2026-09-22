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

describe('salespilot stub', () => {
  test('every read and write method throws', () => {
    const gateway = createSalesPilotGateway();
    assert.throws(() => gateway.listConversations());
    assert.throws(() => gateway.getConversation('C-1'));
    assert.throws(() => gateway.listCases());
    assert.throws(() => gateway.updateCaseStatus('H-1', 'CLOSED'));
    assert.throws(() => gateway.listAgentRuns({}));
    assert.throws(() => gateway.sendRepReply({}));
    assert.throws(() => gateway.seedDemoData());
  });

  test('health reports false rather than throwing', async () => {
    const gateway = createSalesPilotGateway();
    assert.equal(await gateway.health(), false);
  });

  test('capabilities are all false, so dependent controls degrade rather than error', () => {
    const gateway = createSalesPilotGateway();
    assert.deepEqual(Object.values(gateway.capabilities), [false, false, false, false]);
  });
});
