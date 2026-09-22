/**
 * Harness telemetry channel.
 *
 * The load-bearing requirement here is 6.10: when the customer app is **not**
 * embedded it must emit nothing at all. A regression would leak a customer's
 * diagnostics to whatever page framed it.
 */
import { test, describe } from 'node:test';
import assert from 'node:assert/strict';

import {
  installWindow,
  importFresh,
  messageEvent,
  DEFAULT_ORIGIN,
} from '../helpers/browserStubs.js';

/** Load telemetry.js against a freshly installed fake window. */
async function load(options, tag) {
  const stub = installWindow(options);
  const { createTelemetry } = await importFresh(
    '../../customer/js/telemetry.js',
    tag
  );
  return { stub, telemetry: createTelemetry() };
}

describe('standalone (not embedded)', () => {
  test('is disabled and emits nothing', async () => {
    const { stub, telemetry } = await load({ embedded: false }, 'standalone');
    try {
      assert.equal(telemetry.enabled, false);

      telemetry.ready({ transport: 'mock' });
      telemetry.exchange({ clientMessageId: 'c-1', durationMs: 10, status: 200 });
      telemetry.state({ customerMessageCount: 1 });

      assert.equal(stub.posts.length, 0, 'nothing may be posted');
    } finally {
      stub.restore();
    }
  });

  test('registers no message listener, so it cannot be driven from outside', async () => {
    const { stub, telemetry } = await load({ embedded: false }, 'standalone-cmd');
    try {
      let called = false;
      telemetry.onCommand(() => {
        called = true;
      });
      stub.emit('message', messageEvent({ data: { source: 'salespilot-admin', type: 'reset' } }));
      assert.equal(called, false);
      assert.equal(stub.listeners.length, 0);
    } finally {
      stub.restore();
    }
  });
});

describe('embedded', () => {
  test('is enabled and posts to an explicit origin', async () => {
    const { stub, telemetry } = await load({ embedded: true }, 'embedded-1');
    try {
      assert.equal(telemetry.enabled, true);
      telemetry.ready({ transport: 'mock', customerId: 'C-2001' });

      assert.equal(stub.posts.length, 1);
      assert.equal(stub.posts[0].targetOrigin, DEFAULT_ORIGIN);
      assert.notEqual(stub.posts[0].targetOrigin, '*');
    } finally {
      stub.restore();
    }
  });

  test('tags every message with the customer source', async () => {
    const { stub, telemetry } = await load({ embedded: true }, 'embedded-2');
    try {
      telemetry.ready({});
      telemetry.exchange({ clientMessageId: 'c-1', durationMs: 5, status: 200 });
      telemetry.state({ customerMessageCount: 1 });

      assert.equal(stub.posts.length, 3);
      for (const post of stub.posts) {
        assert.equal(post.message.source, 'salespilot-customer');
      }
      assert.deepEqual(
        stub.posts.map((p) => p.message.type),
        ['ready', 'exchange', 'state']
      );
    } finally {
      stub.restore();
    }
  });

  test('the exchange payload carries only a correlation id and client timing', async () => {
    const { stub, telemetry } = await load({ embedded: true }, 'embedded-3');
    try {
      telemetry.exchange({ clientMessageId: 'c-1', durationMs: 1240, status: 200 });
      const payload = stub.posts[0].message.payload;
      assert.deepEqual(Object.keys(payload).sort(), [
        'clientMessageId',
        'durationMs',
        'status',
      ]);
    } finally {
      stub.restore();
    }
  });

  test('no agent telemetry can travel on this channel', async () => {
    const { stub, telemetry } = await load({ embedded: true }, 'embedded-4');
    try {
      telemetry.ready({ transport: 'mock', customerId: 'C-2001' });
      telemetry.exchange({ clientMessageId: 'c-1', durationMs: 1, status: 200 });
      telemetry.state({
        customerMessageCount: 2,
        messageCount: 4,
        humanTakeover: false,
        connection: 'online',
      });

      const serialised = JSON.stringify(stub.posts).toLowerCase();
      for (const banned of [
        'prompt',
        'token',
        'cost',
        'score',
        'priority',
        'next_best_action',
        'signal',
      ]) {
        assert.ok(!serialised.includes(banned), `must not carry "${banned}"`);
      }
    } finally {
      stub.restore();
    }
  });

  test('state uses customerMessageCount and never the word turns', async () => {
    const { stub, telemetry } = await load({ embedded: true }, 'embedded-5');
    try {
      telemetry.state({ customerMessageCount: 3, messageCount: 6 });
      const payload = stub.posts[0].message.payload;
      assert.ok('customerMessageCount' in payload);
      assert.ok(!('turns' in payload));
    } finally {
      stub.restore();
    }
  });

  test('state emissions coalesce to the latest snapshot', async () => {
    const { stub, telemetry } = await load({ embedded: true }, 'embedded-6');
    try {
      // requestAnimationFrame is stubbed to run synchronously, so the first call
      // flushes and the second schedules again. What matters is that the payload
      // delivered is the most recent one, never a stale earlier snapshot.
      telemetry.state({ customerMessageCount: 1 });
      telemetry.state({ customerMessageCount: 2 });
      const last = stub.posts[stub.posts.length - 1].message.payload;
      assert.equal(last.customerMessageCount, 2);
    } finally {
      stub.restore();
    }
  });
});

describe('inbound command validation', () => {
  /** @returns {{stub: object, received: Array}} */
  async function withCommands(tag) {
    const { stub, telemetry } = await load({ embedded: true }, tag);
    const received = [];
    telemetry.onCommand((type, payload) => received.push({ type, payload }));
    return { stub, received };
  }

  test('accepts a well-formed command from the console', async () => {
    const { stub, received } = await withCommands('cmd-ok');
    try {
      stub.emit(
        'message',
        messageEvent({ data: { source: 'salespilot-admin', type: 'reset' } })
      );
      assert.equal(received.length, 1);
      assert.equal(received[0].type, 'reset');
    } finally {
      stub.restore();
    }
  });

  test('rejects a message from a different origin', async () => {
    const { stub, received } = await withCommands('cmd-origin');
    try {
      stub.emit(
        'message',
        messageEvent({
          origin: 'https://evil.example',
          data: { source: 'salespilot-admin', type: 'reset' },
        })
      );
      assert.equal(received.length, 0);
    } finally {
      stub.restore();
    }
  });

  test('rejects a message without the expected source tag', async () => {
    const { stub, received } = await withCommands('cmd-source');
    try {
      stub.emit('message', messageEvent({ data: { source: 'somebody-else', type: 'reset' } }));
      assert.equal(received.length, 0);
    } finally {
      stub.restore();
    }
  });

  test('ignores malformed payloads without throwing', async () => {
    const { stub, received } = await withCommands('cmd-malformed');
    try {
      stub.emit('message', messageEvent({ data: null }));
      stub.emit('message', messageEvent({ data: 'a string' }));
      stub.emit('message', messageEvent({ data: { source: 'salespilot-admin' } }));
      stub.emit('message', messageEvent({ data: { source: 'salespilot-admin', type: 42 } }));
      assert.equal(received.length, 0);
    } finally {
      stub.restore();
    }
  });

  test('passes the payload through for inject', async () => {
    const { stub, received } = await withCommands('cmd-inject');
    try {
      stub.emit(
        'message',
        messageEvent({
          data: { source: 'salespilot-admin', type: 'inject', payload: { text: 'hello' } },
        })
      );
      assert.equal(received[0].type, 'inject');
      assert.equal(received[0].payload.text, 'hello');
    } finally {
      stub.restore();
    }
  });

  test('passes a representative reply through for receive', async () => {
    const { stub, received } = await withCommands('cmd-receive');
    try {
      stub.emit(
        'message',
        messageEvent({
          data: {
            source: 'salespilot-admin',
            type: 'receive',
            payload: { text: 'Alex here', author: 'human', repName: 'Alex' },
          },
        })
      );
      assert.equal(received[0].type, 'receive');
      assert.equal(received[0].payload.author, 'human');
      assert.equal(received[0].payload.repName, 'Alex');
    } finally {
      stub.restore();
    }
  });

  test('an unknown command type still reaches the handler for it to reject', async () => {
    // Validation of the command *name* belongs to the handler, not the channel.
    const { stub, received } = await withCommands('cmd-unknown');
    try {
      stub.emit(
        'message',
        messageEvent({ data: { source: 'salespilot-admin', type: 'nonsense' } })
      );
      assert.equal(received.length, 1);
      assert.equal(received[0].type, 'nonsense');
    } finally {
      stub.restore();
    }
  });
});
