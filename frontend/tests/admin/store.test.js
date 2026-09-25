/**
 * Admin console store.
 *
 * Two behaviours here are load-bearing for correctness rather than polish:
 *   - priority counts are tallied from backend strings, never re-banded locally;
 *   - a case transition is applied from the response body and keeps the open
 *     conversation's composer gate in step.
 */
import { test, describe, beforeEach } from 'node:test';
import assert from 'node:assert/strict';

import { installWindow } from '../helpers/browserStubs.js';

const stub = installWindow();
const { createStore } = await import('../../admin/js/store.js');
stub.restore();

const summary = (id, score, priority, extra = {}) => ({
  id,
  name: `Customer ${id}`,
  score,
  priority,
  state: 'Potential Interest',
  product: 'plus',
  humanTakeover: false,
  lastMessagePreview: 'hello',
  lastMessageAt: new Date(),
  customerMessageCount: 1,
  ...extra,
});

const caseItem = (id, opportunityId, statusToken) => ({
  id,
  opportunityId,
  customerName: 'X',
  state: 'High Intent',
  product: 'plus',
  reason: 'r',
  summary: 's',
  recommendedAction: 'a',
  status: { OPEN: 'Open', TAKEN_OVER: 'Taken Over', CLOSED: 'Closed' }[statusToken],
  statusToken,
  createdAt: new Date(),
});

describe('inbox ordering and counts', () => {
  let store;
  beforeEach(() => {
    store = createStore();
  });

  test('sorts by score descending', () => {
    store.inboxLoaded([
      summary('C-1', 37, 'LOW'),
      summary('C-2', 88, 'HIGH'),
      summary('C-3', 48, 'LOW'),
    ]);
    assert.deepEqual(
      store.getState().inbox.items.map((i) => i.id),
      ['C-2', 'C-3', 'C-1']
    );
  });

  test('unscored conversations sort last, not first', () => {
    store.inboxLoaded([
      summary('C-null', null, 'LOW'),
      summary('C-low', 10, 'LOW'),
    ]);
    assert.deepEqual(
      store.getState().inbox.items.map((i) => i.id),
      ['C-low', 'C-null']
    );
  });

  test('counts tally the backend priority strings', () => {
    store.inboxLoaded([
      summary('C-1', 88, 'HIGH'),
      summary('C-2', 83, 'HIGH'),
      summary('C-3', 60, 'MEDIUM'),
      summary('C-4', 37, 'LOW'),
    ]);
    assert.deepEqual(store.getState().inbox.counts, { HIGH: 2, MEDIUM: 1, LOW: 1 });
  });

  test('a HIGH score with a LOW backend priority is counted as LOW', () => {
    // Proves the console is not re-banding from the number. If the backend says
    // LOW, the console says LOW, even when the score looks high.
    store.inboxLoaded([summary('C-1', 95, 'LOW')]);
    assert.deepEqual(store.getState().inbox.counts, { HIGH: 0, MEDIUM: 0, LOW: 1 });
  });

  test('an unknown priority is counted as LOW rather than dropped', () => {
    store.inboxLoaded([summary('C-1', 50, 'WEIRD'), summary('C-2', 50, null)]);
    const counts = store.getState().inbox.counts;
    assert.equal(counts.HIGH + counts.MEDIUM + counts.LOW, 2);
  });
});

describe('conversation lifecycle', () => {
  test('requesting a conversation clears the previous one and its runs', () => {
    const store = createStore();
    store.conversationLoaded({
      opportunity: { id: 'C-1', humanTakeover: true },
      messages: [{ id: 'm1' }],
      linkedCase: caseItem('H-1', 'C-1', 'OPEN'),
    });
    store.runsLoaded([{ runId: 'ar-1' }]);
    store.draftChanged('half-typed reply');

    store.conversationRequested('C-2');

    const state = store.getState();
    assert.equal(state.selectedId, 'C-2');
    assert.equal(state.conversation.opportunity, null);
    assert.equal(state.conversation.messages.length, 0);
    assert.equal(state.conversation.linkedCase, null);
    assert.equal(state.runs.items.length, 0);
    assert.equal(state.compose.draft, '', 'a draft must not follow you to another customer');
  });

  test('runsLoaded selects the newest run so the panel is never blank for no reason', () => {
    const store = createStore();
    store.runsLoaded([{ runId: 'ar-1' }, { runId: 'ar-2' }, { runId: 'ar-3' }]);
    assert.equal(store.getState().runs.selectedRunId, 'ar-3');
  });

  test('runsLoaded with nothing selects nothing', () => {
    const store = createStore();
    store.runsLoaded([]);
    assert.equal(store.getState().runs.selectedRunId, null);
  });
});

describe('case transitions', () => {
  let store;
  beforeEach(() => {
    store = createStore();
    store.casesLoaded([
      caseItem('H-1', 'C-1', 'OPEN'),
      caseItem('H-2', 'C-2', 'TAKEN_OVER'),
      caseItem('H-3', 'C-3', 'CLOSED'),
    ]);
  });

  test('open count comes from the normalised token', () => {
    assert.equal(store.getState().cases.openCount, 1);
  });

  test('a transition replaces the case from the response body', () => {
    store.transitionStarted('H-1');
    assert.equal(store.getState().transition.inFlight, true);

    store.transitionSucceeded(caseItem('H-1', 'C-1', 'TAKEN_OVER'));

    const updated = store.getState().cases.items.find((c) => c.id === 'H-1');
    assert.equal(updated.statusToken, 'TAKEN_OVER');
    assert.equal(store.getState().cases.openCount, 0);
    assert.equal(store.getState().transition.inFlight, false);
  });

  test('a failed transition leaves the case untouched', () => {
    store.transitionStarted('H-1');
    store.transitionFailed('H-1', 'network');

    const unchanged = store.getState().cases.items.find((c) => c.id === 'H-1');
    assert.equal(unchanged.statusToken, 'OPEN');
    assert.equal(store.getState().cases.openCount, 1);
    assert.ok(store.getState().transition.error);
  });

  test('taking over attaches the case but does not invent the takeover flag', () => {
    store.conversationLoaded({
      opportunity: { id: 'C-1', humanTakeover: false },
      messages: [],
      linkedCase: null,
    });
    store.transitionSucceeded(caseItem('H-1', 'C-1', 'TAKEN_OVER'));

    assert.equal(store.getState().conversation.linkedCase.id, 'H-1');
    // The flag belongs to the backend. Inferring it here would have the console
    // enable the composer for a reply the backend then rejects with 409.
    assert.equal(store.getState().conversation.opportunity.humanTakeover, false);
  });

  test('resolving detaches the case without inventing the takeover flag', () => {
    store.conversationLoaded({
      opportunity: { id: 'C-1', humanTakeover: true },
      messages: [],
      linkedCase: caseItem('H-1', 'C-1', 'TAKEN_OVER'),
    });
    store.transitionSucceeded(caseItem('H-1', 'C-1', 'CLOSED'));

    assert.equal(store.getState().conversation.linkedCase, null);
    assert.equal(store.getState().conversation.opportunity.humanTakeover, true);
  });

  test('a transition for a different customer does not disturb the open one', () => {
    store.conversationLoaded({
      opportunity: { id: 'C-1', humanTakeover: true },
      messages: [],
      linkedCase: caseItem('H-1', 'C-1', 'TAKEN_OVER'),
    });
    store.transitionSucceeded(caseItem('H-2', 'C-2', 'CLOSED'));

    assert.equal(store.getState().conversation.opportunity.humanTakeover, true);
    assert.equal(store.getState().conversation.linkedCase.id, 'H-1');
  });
});

describe('composer', () => {
  test('a failed reply preserves the draft', () => {
    const store = createStore();
    store.draftChanged('carefully worded reply');
    store.replyStarted();
    store.replyFailed('boom');

    assert.equal(store.getState().compose.draft, 'carefully worded reply');
    assert.equal(store.getState().compose.inFlight, false);
    assert.ok(store.getState().compose.error);
  });

  test('a successful reply appends and clears the draft', () => {
    const store = createStore();
    store.conversationLoaded({ opportunity: { id: 'C-1' }, messages: [], linkedCase: null });
    store.draftChanged('hello');
    store.replyStarted();
    store.replyAppended({ id: 'm-rep', origin: 'human', text: 'hello' });

    assert.equal(store.getState().compose.draft, '');
    assert.equal(store.getState().conversation.messages.length, 1);
    assert.equal(store.getState().conversation.messages[0].origin, 'human');
  });
});

describe('harness state', () => {
  test('an observed exchange becomes a timeline entry awaiting its run', () => {
    const store = createStore();
    store.exchangeObserved({ clientMessageId: 'c-1', durationMs: 900, status: 200 });

    const entry = store.getState().harness.timeline[0];
    assert.equal(entry.clientMessageId, 'c-1');
    assert.equal(entry.durationMs, 900);
    assert.equal(entry.run, null);
    assert.equal(entry.runStatus, 'idle');
    assert.equal(store.getState().harness.selectedEntryId, 'c-1');
  });

  test('a loaded run attaches to its entry', () => {
    const store = createStore();
    store.exchangeObserved({ clientMessageId: 'c-1', durationMs: 900, status: 200 });
    store.entryRunLoading('c-1');
    assert.equal(store.getState().harness.timeline[0].runStatus, 'loading');

    store.entryRunLoaded('c-1', { runId: 'ar-1' });
    assert.equal(store.getState().harness.timeline[0].run.runId, 'ar-1');
    assert.equal(store.getState().harness.timeline[0].runStatus, 'idle');
  });

  test('a missing run is marked empty, not left pending forever', () => {
    const store = createStore();
    store.exchangeObserved({ clientMessageId: 'c-1', durationMs: 1, status: 200 });
    store.entryRunLoaded('c-1', null);
    assert.equal(store.getState().harness.timeline[0].runStatus, 'empty');
  });

  test('device state uses customerMessageCount', () => {
    const store = createStore();
    store.deviceStateReported({
      customerMessageCount: 4,
      messageCount: 8,
      humanTakeover: true,
      connection: 'online',
    });
    const harness = store.getState().harness;
    assert.equal(harness.customerMessageCount, 4);
    assert.equal(harness.humanTakeover, true);
    assert.ok(!('turns' in harness));
  });

  test('harnessReset clears the timeline and counters', () => {
    const store = createStore();
    store.exchangeObserved({ clientMessageId: 'c-1', durationMs: 1, status: 200 });
    store.deviceStateReported({ customerMessageCount: 4, humanTakeover: true });
    store.harnessReset();

    const harness = store.getState().harness;
    assert.equal(harness.timeline.length, 0);
    assert.equal(harness.selectedEntryId, null);
    assert.equal(harness.customerMessageCount, 0);
    assert.equal(harness.humanTakeover, false);
  });

  test('deviceLost records an error and marks the device disconnected', () => {
    const store = createStore();
    store.deviceReady({ transport: 'mock' });
    assert.equal(store.getState().harness.deviceReady, true);

    store.deviceLost('timed out');
    assert.equal(store.getState().harness.deviceReady, false);
    assert.ok(store.getState().harness.deviceError);
  });
});

describe('routing', () => {
  test('route and panel changes notify', () => {
    const store = createStore();
    let calls = 0;
    store.subscribe(() => {
      calls += 1;
    });
    store.routeChanged('cases');
    store.panelChanged('observability');
    assert.equal(store.getState().route, 'cases');
    assert.equal(store.getState().activePanel, 'observability');
    assert.equal(calls, 2);
  });

  test('setting the same route does not notify again', () => {
    const store = createStore();
    store.routeChanged('cases');
    let calls = 0;
    store.subscribe(() => {
      calls += 1;
    });
    store.routeChanged('cases');
    assert.equal(calls, 0);
  });
});
