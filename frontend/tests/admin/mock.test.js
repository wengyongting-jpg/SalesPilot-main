/**
 * Admin mock transport and the agent-run shape.
 *
 * The invariants asserted here are the ones the project keeps insisting on:
 * retrieval is never reported as a tool call, model calls are counted in full,
 * an unmeasured cost is absent rather than zero, and a synthesised run is
 * labelled as such instead of passing for a measurement.
 */
import { test, describe, beforeEach } from 'node:test';
import assert from 'node:assert/strict';

import { installWindow } from '../helpers/browserStubs.js';

const stub = installWindow();
const { createMockGateway } = await import('../../admin/js/gateway/mock.js');
const { createSalesPilotGateway } = await import(
  '../../admin/js/gateway/salespilot.js'
);
stub.restore();

describe('artificial latency', () => {
  // The admin mock threads latencyScale through an explicit constructor option
  // rather than a lazily-read URL parameter, which is why it did not suffer the
  // same regression as the customer mock (see customer/mock.test.js). This test
  // guards the same property directly rather than assuming the architectural
  // difference makes it immune forever.
  test('latencyScale: 0 actually eliminates the delay', async () => {
    const gateway = createMockGateway({ latencyScale: 0 });
    const started = Date.now();
    await gateway.getConversation('C-1024');
    assert.ok(Date.now() - started < 100);
  });

  test('the default scale is non-zero, so production timing is unchanged', async () => {
    const gateway = createMockGateway();
    const started = Date.now();
    await gateway.listConversations();
    assert.ok(
      Date.now() - started >= 100,
      'the default construction must still feel like a network call'
    );
  });
});

describe('capabilities', () => {
  test('the mock advertises what the console needs to be buildable', () => {
    const gateway = createMockGateway({ latencyScale: 0 });
    assert.equal(gateway.capabilities.repReply, true);
    assert.equal(gateway.capabilities.telemetry, true);
    assert.equal(gateway.capabilities.quickReplies, false);
  });

  test('the salespilot adapter advertises what the rebuilt backend serves', () => {
    const gateway = createSalesPilotGateway();
    assert.deepEqual(gateway.capabilities, {
      repReply: true,
      telemetry: true,
      author: true,
      quickReplies: true,
    });
  });

  test('the salespilot adapter reports an unreachable backend rather than hanging', async () => {
    const gateway = createSalesPilotGateway({ apiBase: 'http://127.0.0.1:1' });
    assert.equal(await gateway.health(), false);
  });
});

describe('conversations', () => {
  let gateway;
  beforeEach(() => {
    gateway = createMockGateway({ latencyScale: 0 });
  });

  test('lists four conversations', async () => {
    const { items } = await gateway.listConversations();
    assert.equal(items.length, 4);
  });

  test('includes two customers sharing a name but not an id', async () => {
    const { items } = await gateway.listConversations();
    const sarahs = items.filter((i) => i.name === 'Sarah');
    assert.equal(sarahs.length, 2);
    assert.notEqual(sarahs[0].id, sarahs[1].id);
  });

  test('summaries carry customerMessageCount, not turns', async () => {
    const { items } = await gateway.listConversations();
    for (const item of items) {
      assert.equal(typeof item.customerMessageCount, 'number');
      assert.ok(!('turns' in item));
    }
  });

  test('an unknown conversation raises a 404', async () => {
    await assert.rejects(
      () => gateway.getConversation('C-nope'),
      (error) => error.status === 404
    );
  });

  test('a conversation under takeover carries its open case', async () => {
    const { opportunity, linkedCase } = await gateway.getConversation('C-1026');
    assert.equal(opportunity.humanTakeover, true);
    assert.ok(linkedCase);
    assert.equal(linkedCase.opportunityId, 'C-1026');
    assert.notEqual(linkedCase.statusToken, 'CLOSED');
  });

  test('the transcript exposes all four message origins', async () => {
    const { messages } = await gateway.getConversation('C-1026');
    const origins = new Set(messages.map((m) => m.origin));
    for (const expected of ['customer', 'ai', 'human', 'system']) {
      assert.ok(origins.has(expected), `missing origin: ${expected}`);
    }
  });

  test('a human message keeps role agent and names the representative', async () => {
    const { messages } = await gateway.getConversation('C-1026');
    const human = messages.find((m) => m.origin === 'human');
    assert.equal(human.role, 'agent', 'role stays the coarse axis');
    assert.equal(human.repName, 'Alex');
  });

  test('missing score dimensions are null rather than fabricated', async () => {
    const { opportunity } = await gateway.getConversation('C-2044');
    assert.equal(opportunity.scoreDimensions, null);
    assert.equal(typeof opportunity.score, 'number');
  });
});

describe('agent runs', () => {
  let gateway;
  beforeEach(() => {
    gateway = createMockGateway({ latencyScale: 0 });
  });

  test('one run per customer message', async () => {
    const { items } = await gateway.listAgentRuns({ opportunityId: 'C-1024' });
    assert.equal(items.length, 5);
  });

  test('retrieval is never reported as a tool call', async () => {
    const { items } = await gateway.listAgentRuns({ opportunityId: 'C-1024' });
    for (const run of items) {
      assert.equal(run.toolCalls.length, 0);
      assert.equal(run.totals.toolCallCount, 0);
      assert.ok(
        run.steps.some((step) => step.kind === 'retrieval'),
        'a retrieval step must exist'
      );
      assert.ok(
        !run.steps.some((step) => step.kind === 'tool'),
        'no step may claim to be a tool call'
      );
    }
  });

  test('step kinds are drawn from the agreed set', async () => {
    const allowed = new Set(['llm', 'rule', 'retrieval', 'tool']);
    const { items } = await gateway.listAgentRuns({ opportunityId: 'C-1024' });
    for (const run of items) {
      for (const step of run.steps) assert.ok(allowed.has(step.kind), step.kind);
    }
  });

  test('llmCallCount counts extraction and generation, not just one', async () => {
    const { items } = await gateway.listAgentRuns({ opportunityId: 'C-1024' });
    assert.equal(items[0].totals.llmCallCount, 2);
    assert.equal(items[0].llmCalls.length, 2);
  });

  test('totals agree with the per-call figures', async () => {
    const { items } = await gateway.listAgentRuns({ opportunityId: 'C-1024' });
    for (const run of items) {
      const tokens = run.llmCalls.reduce((sum, call) => sum + call.totalTokens, 0);
      assert.equal(run.totals.totalTokens, tokens);
      assert.equal(run.totals.llmCallCount, run.llmCalls.length);
      assert.equal(run.totals.agentStepCount, run.steps.length);
    }
  });

  test('each call total equals prompt plus completion', async () => {
    const { items } = await gateway.listAgentRuns({ opportunityId: 'C-1024' });
    for (const run of items) {
      for (const call of run.llmCalls) {
        assert.equal(call.totalTokens, call.promptTokens + call.completionTokens);
      }
    }
  });

  test('a degraded run is flagged and names the step that degraded', async () => {
    const { items } = await gateway.listAgentRuns({ opportunityId: 'C-1024' });
    const degraded = items.find((run) => run.status === 'degraded');
    assert.ok(degraded, 'the fixture must contain a degraded run');
    assert.equal(degraded.degradedStep, 'extraction');
    assert.equal(
      degraded.totals.llmCallCount,
      1,
      'extraction fell back to rules, so one model call remains'
    );
    const step = degraded.steps.find((s) => s.name === 'extraction');
    assert.equal(step.status, 'degraded');
    assert.equal(step.kind, 'rule', 'the fallback ran as a rule, not a model call');
  });

  test('withheld content exposes a length but no text', async () => {
    const { items } = await gateway.listAgentRuns({ opportunityId: 'C-1024' });
    const withheld = items.find((run) =>
      run.llmCalls.some((call) => call.input.content === undefined)
    );
    assert.ok(withheld, 'the fixture must contain a run with withheld content');
    for (const call of withheld.llmCalls) {
      assert.equal(typeof call.input.chars, 'number');
      assert.equal(call.input.content, undefined);
      assert.equal(call.output.content, undefined);
    }
  });

  test('a rule-only run reports absent cost rather than zero', async () => {
    const { items } = await gateway.listAgentRuns({ opportunityId: 'C-1025' });
    for (const run of items) {
      assert.equal(run.totals.llmCallCount, 0);
      assert.equal(run.totals.cost, null, 'unmeasured cost must be null, not 0');
      assert.equal(run.totals.totalTokens, 0);
    }
  });

  test('runs are retrievable by correlation id', async () => {
    const { items } = await gateway.listAgentRuns({ clientMessageId: 'c-1024-2' });
    assert.equal(items.length, 1);
    assert.equal(items[0].clientMessageId, 'c-1024-2');
  });

  test('a recorded run is not marked simulated', async () => {
    const { items } = await gateway.listAgentRuns({ clientMessageId: 'c-1024-2' });
    assert.equal(items[0].simulated, undefined);
  });

  test('an unknown correlation id yields a run explicitly marked simulated', async () => {
    // The harness device shares no backend with the console in mock mode, so a
    // just-sent message has no recorded run. Generating one keeps the correlation
    // mechanism demonstrable; the flag keeps it honest.
    const { items } = await gateway.listAgentRuns({ clientMessageId: 'c-brand-new' });
    assert.equal(items.length, 1);
    assert.equal(items[0].simulated, true);
  });

  test('a synthesised run still obeys the tool-call rule', async () => {
    const { items } = await gateway.listAgentRuns({ clientMessageId: 'c-brand-new-2' });
    const run = items[0];
    assert.equal(run.totals.toolCallCount, 0);
    assert.equal(run.toolCalls.length, 0);
    assert.ok(run.steps.some((step) => step.kind === 'retrieval'));
  });

  test('no query returns nothing rather than everything', async () => {
    const { items } = await gateway.listAgentRuns({});
    assert.equal(items.length, 0);
  });
});

describe('case transitions', () => {
  let gateway;
  beforeEach(() => {
    gateway = createMockGateway({ latencyScale: 0 });
  });

  test('returns the canonical status pair', async () => {
    const updated = await gateway.updateCaseStatus('H-A911AB', 'TAKEN_OVER');
    assert.equal(updated.status, 'Taken Over');
    assert.equal(updated.statusToken, 'TAKEN_OVER');
  });

  test('accepts the backend title-case value as input too', async () => {
    const updated = await gateway.updateCaseStatus('H-A911AB', 'Taken Over');
    assert.equal(updated.statusToken, 'TAKEN_OVER');
  });

  test('an invalid status is rejected with 400', async () => {
    await assert.rejects(
      () => gateway.updateCaseStatus('H-A911AB', 'NOPE'),
      (error) => error.status === 400
    );
  });

  test('an unknown case is rejected with 404', async () => {
    await assert.rejects(
      () => gateway.updateCaseStatus('H-nope', 'CLOSED'),
      (error) => error.status === 404
    );
  });

  test('closing a case clears takeover on its opportunity', async () => {
    await gateway.updateCaseStatus('H-A911AB', 'CLOSED');
    const { opportunity } = await gateway.getConversation('C-1024');
    assert.equal(opportunity.humanTakeover, false);
    assert.equal(opportunity.humanInterventionRequired, false);
  });

  test('taking over sets takeover on its opportunity', async () => {
    await gateway.updateCaseStatus('H-A911AB', 'CLOSED');
    await gateway.updateCaseStatus('H-A911AB', 'TAKEN_OVER');
    const { opportunity } = await gateway.getConversation('C-1024');
    assert.equal(opportunity.humanTakeover, true);
  });
});

describe('human reply', () => {
  let gateway;
  beforeEach(() => {
    gateway = createMockGateway({ latencyScale: 0 });
  });

  test('is rejected with 409 when the conversation is not under takeover', async () => {
    const { opportunity } = await gateway.getConversation('C-1025');
    assert.equal(opportunity.humanTakeover, false, 'fixture precondition');

    await assert.rejects(
      () => gateway.sendRepReply({ id: 'C-1025', text: 'hi', repName: 'Alex' }),
      (error) => error.status === 409
    );
  });

  test('is accepted while under takeover and attributed to the human', async () => {
    const { message } = await gateway.sendRepReply({
      id: 'C-1024',
      text: 'Hi Sarah, Alex here.',
      repName: 'Alex',
      clientMessageId: 'r-1',
    });
    assert.equal(message.origin, 'human');
    assert.equal(message.role, 'agent');
    assert.equal(message.repName, 'Alex');
    assert.equal(message.clientMessageId, 'r-1');
  });

  test('appears in the transcript afterwards', async () => {
    await gateway.sendRepReply({ id: 'C-1024', text: 'Following up', repName: 'Alex' });
    const { messages } = await gateway.getConversation('C-1024');
    assert.ok(messages.some((m) => m.text === 'Following up' && m.origin === 'human'));
  });

  test('is rejected again once the case is closed', async () => {
    await gateway.updateCaseStatus('H-A911AB', 'CLOSED');
    await assert.rejects(
      () => gateway.sendRepReply({ id: 'C-1024', text: 'hi', repName: 'Alex' }),
      (error) => error.status === 409
    );
  });

  test('an unknown conversation is rejected with 404', async () => {
    await assert.rejects(
      () => gateway.sendRepReply({ id: 'C-nope', text: 'hi', repName: 'Alex' }),
      (error) => error.status === 404
    );
  });

  test('a message containing "fail" is rejected, so the failure path is reachable', async () => {
    await assert.rejects(() =>
      gateway.sendRepReply({ id: 'C-1024', text: 'please fail', repName: 'Alex' })
    );
  });
});

describe('cases listing', () => {
  test('every case exposes a normalised token alongside the display status', async () => {
    const gateway = createMockGateway({ latencyScale: 0 });
    const { items } = await gateway.listCases();
    assert.ok(items.length > 0);
    for (const item of items) {
      assert.ok(['OPEN', 'TAKEN_OVER', 'CLOSED'].includes(item.statusToken));
      assert.ok(['Open', 'Taken Over', 'Closed'].includes(item.status));
    }
  });
});

/**
 * Fixture data-quality checks, deliberately separated from behavioural tests
 * above. These verify the mock's hand-authored fixture is internally
 * consistent — e.g. that a customer's score dimensions actually sum to their
 * total — rather than verifying any function's logic. A failure here means "the
 * fixture numbers were edited and now disagree with each other", not "the code
 * is broken", and the two should never be mistaken for one another in a report.
 */
describe('fixture data-quality checks (not behavioural)', () => {
  test('score dimensions, when present, sum to the total', async () => {
    const gateway = createMockGateway({ latencyScale: 0 });
    const { opportunity } = await gateway.getConversation('C-1024');
    const sum = Object.values(opportunity.scoreDimensions).reduce((a, b) => a + b, 0);
    assert.equal(sum, opportunity.score);
  });

  test('cases link to an existing opportunity', async () => {
    const gateway = createMockGateway({ latencyScale: 0 });
    const { items: cases } = await gateway.listCases();
    const { items: conversations } = await gateway.listConversations();
    const ids = new Set(conversations.map((c) => c.id));
    for (const item of cases) assert.ok(ids.has(item.opportunityId));
  });

  test('every conversation marked under takeover has a corresponding open case', async () => {
    const gateway = createMockGateway({ latencyScale: 0 });
    const { items: conversations } = await gateway.listConversations();
    const { items: cases } = await gateway.listCases();
    for (const conversation of conversations.filter((c) => c.humanTakeover)) {
      const linked = cases.find(
        (c) => c.opportunityId === conversation.id && c.statusToken !== 'CLOSED'
      );
      assert.ok(linked, `${conversation.id} claims takeover but has no open case`);
    }
  });
});
