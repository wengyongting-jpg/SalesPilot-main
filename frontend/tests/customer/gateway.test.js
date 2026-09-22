/**
 * Transport selection (requirement 9.1) and the WhatsApp stub's explicit refusal
 * to work (requirement 9.4).
 *
 * These were an audit-identified gap: both behaviours are pure, cheap to test,
 * and tied to numbered requirements, yet had no coverage at all.
 */
import { test, describe } from 'node:test';
import assert from 'node:assert/strict';

import { createGateway } from '../../customer/js/gateway/index.js';
import { createWhatsAppGateway } from '../../customer/js/gateway/whatsapp.js';

describe('createGateway', () => {
  test('selects the mock adapter', () => {
    const gateway = createGateway({ transport: 'mock' });
    assert.equal(gateway.name, 'mock');
  });

  test('selects the salespilot adapter', () => {
    const gateway = createGateway({ transport: 'salespilot' });
    assert.equal(gateway.name, 'salespilot');
  });

  test('selects the whatsapp adapter', () => {
    const gateway = createGateway({ transport: 'whatsapp' });
    assert.equal(gateway.name, 'whatsapp');
  });

  test('an unknown transport throws rather than silently falling back', () => {
    assert.throws(() => createGateway({ transport: 'carrier-pigeon' }));
  });

  test('the error names the offending value, so a misconfiguration is diagnosable', () => {
    assert.throws(
      () => createGateway({ transport: 'carrier-pigeon' }),
      (error) => error.message.includes('carrier-pigeon')
    );
  });

  test('an absent transport also throws rather than defaulting silently', () => {
    assert.throws(() => createGateway({}));
  });
});

describe('whatsapp stub — requirement 9.4', () => {
  // Every data method is a synchronous function that throws immediately, not an
  // async function returning a rejected promise — confirmed against the actual
  // module before writing this, rather than assumed. assert.rejects would pass
  // for the wrong reason here (it awaits whatever is passed, and awaiting a
  // thrown synchronous error still rejects) — assert.throws is the honest match
  // for what the code actually does.
  test('every method throws synchronously instead of appearing to work', () => {
    const gateway = createWhatsAppGateway();
    assert.throws(() => gateway.loadHistory());
    assert.throws(() => gateway.send({}));
    assert.throws(() => gateway.fetchSince());
    assert.throws(() => gateway.reset());
  });

  test('health reports false rather than throwing, so a caller can probe safely', async () => {
    const gateway = createWhatsAppGateway();
    assert.equal(await gateway.health(), false);
  });

  test('the failure message says the transport is not implemented', () => {
    const gateway = createWhatsAppGateway();
    assert.throws(
      () => gateway.send({}),
      (error) => /not implemented/i.test(error.message)
    );
  });
});
