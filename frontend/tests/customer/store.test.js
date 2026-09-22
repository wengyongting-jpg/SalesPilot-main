/**
 * Customer conversation store: the delivery-tick state machine, retry identity,
 * deduplication, unread counting and takeover.
 */
import { test, describe, beforeEach } from 'node:test';
import assert from 'node:assert/strict';

import { installWindow } from '../helpers/browserStubs.js';

// config.js reads window.location at import time.
const stub = installWindow();
const { createStore, createMessage, messageKey, newClientId } = await import(
  '../../customer/js/store.js'
);
stub.restore();

const incoming = (id, text = 'hi') =>
  createMessage({ id, direction: 'in', author: 'ai', text });

describe('newClientId', () => {
  test('is unique across calls', () => {
    const ids = new Set(Array.from({ length: 200 }, () => newClientId()));
    assert.equal(ids.size, 200);
  });
});

describe('messageKey', () => {
  test('prefers the server id', () => {
    assert.equal(messageKey({ id: 'server-1', clientId: 'c-1' }), 'server-1');
  });

  test('falls back to clientId when there is no server id', () => {
    assert.equal(messageKey({ id: null, clientId: 'c-1' }), 'c-1');
  });
});

describe('send flow', () => {
  let store;
  beforeEach(() => {
    store = createStore();
  });

  test('sending appends one outgoing message and starts the typing indicator', () => {
    const message = store.sendRequested({ text: 'hello' });
    const state = store.getState();
    assert.equal(state.messages.length, 1);
    assert.equal(message.direction, 'out');
    assert.equal(message.author, 'customer');
    assert.equal(message.status, 'sending');
    assert.equal(state.assistant.typing, true);
  });

  test('tick progression is sending -> sent -> read as three transitions', () => {
    const message = store.sendRequested({ text: 'hello' });
    assert.equal(message.status, 'sending');
    store.sendAcknowledged(message.clientId);
    assert.equal(message.status, 'sent');
    store.markRead(message.clientId);
    assert.equal(message.status, 'read');
  });

  test('a read message leaves the pending index', () => {
    const message = store.sendRequested({ text: 'hello' });
    assert.equal(store.getState().pending.size, 1);
    store.sendAcknowledged(message.clientId);
    store.markRead(message.clientId);
    assert.equal(store.getState().pending.size, 0);
  });

  test('a failed message stays retryable', () => {
    const message = store.sendRequested({ text: 'boom' });
    store.sendFailed(message.clientId);
    assert.equal(message.status, 'failed');
    assert.equal(store.getState().assistant.typing, false);
    assert.equal(store.findByClientId(message.clientId).status, 'failed');
  });

  test('retry reuses the bubble and preserves the original text', () => {
    const first = store.sendRequested({ text: 'original' });
    store.sendFailed(first.clientId);

    const retried = store.sendRequested({ text: '', clientId: first.clientId });

    assert.equal(store.getState().messages.length, 1, 'no second bubble');
    assert.equal(retried.clientId, first.clientId);
    assert.equal(retried.text, 'original');
    assert.equal(retried.status, 'sending');
  });

  test('retry restarts the typing indicator', () => {
    const message = store.sendRequested({ text: 'x' });
    store.sendFailed(message.clientId);
    assert.equal(store.getState().assistant.typing, false);
    store.sendRequested({ text: '', clientId: message.clientId });
    assert.equal(store.getState().assistant.typing, true);
  });

  test('sending clears any quick replies', () => {
    store.quickRepliesChanged([{ id: 'q1', label: 'A' }]);
    assert.equal(store.getState().quickReplies.length, 1);
    store.sendRequested({ text: 'x' });
    assert.equal(store.getState().quickReplies.length, 0);
  });
});

describe('replyReceived', () => {
  test('appends incoming messages', () => {
    const store = createStore();
    store.replyReceived([incoming('r1'), incoming('r2')]);
    assert.equal(store.getState().messages.length, 2);
  });

  test('deduplicates on server id', () => {
    const store = createStore();
    store.replyReceived([incoming('r1')]);
    store.replyReceived([incoming('r1')]);
    assert.equal(store.getState().messages.length, 1);
  });

  test('clears the typing indicator', () => {
    const store = createStore();
    store.sendRequested({ text: 'x' });
    store.replyReceived([incoming('r1')]);
    assert.equal(store.getState().assistant.typing, false);
  });
});

describe('unread counting', () => {
  test('no unread while the customer is at the bottom', () => {
    const store = createStore();
    store.replyReceived([incoming('r1')]);
    assert.equal(store.getState().scroll.unread, 0);
  });

  test('counts incoming messages received while scrolled away', () => {
    const store = createStore();
    store.scrollChanged(false);
    store.replyReceived([incoming('r1')]);
    store.replyReceived([incoming('r2'), incoming('r3')]);
    assert.equal(store.getState().scroll.unread, 3);
  });

  test('a deduplicated message is not counted twice', () => {
    const store = createStore();
    store.scrollChanged(false);
    store.replyReceived([incoming('r1')]);
    store.replyReceived([incoming('r1')]);
    assert.equal(store.getState().scroll.unread, 1);
  });

  test('returning to the bottom clears the count', () => {
    const store = createStore();
    store.scrollChanged(false);
    store.replyReceived([incoming('r1')]);
    store.scrollChanged(true);
    assert.equal(store.getState().scroll.unread, 0);
  });

  test('unreadCleared resets without moving the scroll flag', () => {
    const store = createStore();
    store.scrollChanged(false);
    store.replyReceived([incoming('r1')]);
    store.unreadCleared();
    assert.equal(store.getState().scroll.unread, 0);
    assert.equal(store.getState().scroll.atBottom, false);
  });
});

describe('human takeover', () => {
  test('appends exactly one system message and is idempotent', () => {
    const store = createStore();
    store.takeoverChanged(true, 'Alex');
    store.takeoverChanged(true, 'Alex');
    const system = store.getState().messages.filter((m) => m.author === 'system');
    assert.equal(system.length, 1);
    assert.match(system[0].text, /Alex/);
  });

  test('sets the representative name', () => {
    const store = createStore();
    store.takeoverChanged(true, 'Alex');
    assert.equal(store.getState().assistant.repName, 'Alex');
  });

  test('ending takeover appends a second system message and clears the name', () => {
    const store = createStore();
    store.takeoverChanged(true, 'Alex');
    store.takeoverChanged(false);
    const system = store.getState().messages.filter((m) => m.author === 'system');
    assert.equal(system.length, 2);
    assert.equal(store.getState().assistant.repName, null);
    assert.equal(store.getState().assistant.humanTakeover, false);
  });

  test('quick replies are suppressed while a human owns the conversation', () => {
    const store = createStore();
    store.takeoverChanged(true, 'Alex');
    store.quickRepliesChanged([{ id: 'q1', label: 'A' }]);
    assert.equal(store.getState().quickReplies.length, 0);
  });
});

describe('quick replies', () => {
  test('capped at three', () => {
    const store = createStore();
    store.quickRepliesChanged(
      [1, 2, 3, 4, 5].map((n) => ({ id: `q${n}`, label: `Q${n}` }))
    );
    assert.equal(store.getState().quickReplies.length, 3);
  });
});

describe('history and reset', () => {
  test('historyLoaded replaces the transcript and clears pending', () => {
    const store = createStore();
    store.sendRequested({ text: 'x' });
    store.historyLoaded([incoming('h1'), incoming('h2')]);
    assert.equal(store.getState().messages.length, 2);
    assert.equal(store.getState().pending.size, 0);
    assert.equal(store.getState().history, 'idle');
  });

  test('conversationReset clears everything', () => {
    const store = createStore();
    store.sendRequested({ text: 'x' });
    store.takeoverChanged(true, 'Alex');
    store.scrollChanged(false);
    store.conversationReset();

    const state = store.getState();
    assert.equal(state.messages.length, 0);
    assert.equal(state.pending.size, 0);
    assert.equal(state.assistant.humanTakeover, false);
    assert.equal(state.assistant.typing, false);
    assert.equal(state.scroll.atBottom, true);
    assert.equal(state.scroll.unread, 0);
  });
});

describe('capability detection', () => {
  test('defaults to everything unavailable', () => {
    const store = createStore();
    assert.deepEqual(store.getState().capabilities, {
      idempotency: false,
      quickReplies: false,
      incrementalFetch: false,
    });
  });

  test('merges detected capabilities', () => {
    const store = createStore();
    store.capabilitiesDetected({ idempotency: true });
    assert.equal(store.getState().capabilities.idempotency, true);
    assert.equal(store.getState().capabilities.quickReplies, false);
  });
});

describe('subscribe', () => {
  test('notifies on change and unsubscribes cleanly', () => {
    const store = createStore();
    let calls = 0;
    const unsubscribe = store.subscribe(() => {
      calls += 1;
    });
    store.sendRequested({ text: 'x' });
    assert.ok(calls > 0);

    const seen = calls;
    unsubscribe();
    store.sendRequested({ text: 'y' });
    assert.equal(calls, seen, 'no notifications after unsubscribe');
  });
});

describe('receiving a human representative message', () => {
  // Drives the behaviour behind the harness "Send as business — human
  // representative" control: the customer's view of a human reply.

  test('a human message flips the conversation into takeover', () => {
    const store = createStore();
    store.takeoverChanged(true, 'Alex');
    store.replyReceived([
      createMessage({ direction: 'in', author: 'human', text: 'Alex here' }),
    ]);

    const state = store.getState();
    assert.equal(state.assistant.humanTakeover, true);
    assert.equal(state.assistant.repName, 'Alex');
  });

  test('the announcement precedes the reply in the transcript', () => {
    const store = createStore();
    store.takeoverChanged(true, 'Alex');
    store.replyReceived([
      createMessage({ direction: 'in', author: 'human', text: 'Alex here' }),
    ]);

    const authors = store.getState().messages.map((m) => m.author);
    assert.deepEqual(authors, ['system', 'human']);
  });

  test('a second human message announces nothing further', () => {
    const store = createStore();
    store.takeoverChanged(true, 'Alex');
    store.replyReceived([
      createMessage({ direction: 'in', author: 'human', text: 'first' }),
    ]);
    store.takeoverChanged(true, 'Alex');
    store.replyReceived([
      createMessage({ direction: 'in', author: 'human', text: 'second' }),
    ]);

    const system = store.getState().messages.filter((m) => m.author === 'system');
    assert.equal(system.length, 1);
    assert.equal(store.getState().messages.length, 3);
  });

  test('a human message is incoming and carries no delivery status', () => {
    const store = createStore();
    const message = createMessage({
      direction: 'in',
      author: 'human',
      text: 'Alex here',
    });
    store.replyReceived([message]);

    assert.equal(message.direction, 'in');
    assert.equal(message.status, null, 'ticks are for outgoing messages only');
  });

  test('an incoming human message counts as unread when scrolled away', () => {
    const store = createStore();
    store.scrollChanged(false);
    store.replyReceived([
      createMessage({ direction: 'in', author: 'human', text: 'Alex here' }),
    ]);
    assert.equal(store.getState().scroll.unread, 1);
  });
});
