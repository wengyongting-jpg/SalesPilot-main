/**
 * Mock transport — scripted, no network.
 *
 * Runs the entire console so the admin UI can be built and demonstrated while the
 * backend is mid-refactor. Data mirrors the backend's demo script, verified
 * against a live seed run: Sarah C-1024 reaches High Intent 83/100 with an open
 * case, Michael C-1025 sits at Evaluation & Hesitation 37/100, ABC Pte Ltd C-1026
 * reaches High Intent 88/100 with an open case on its second message.
 *
 * A fourth conversation is added deliberately: a **second customer also named
 * Sarah** with a different opportunity id, so identity disambiguation is
 * exercised (requirement 1.3). The backend keys opportunities on id alone and
 * never updates a name after creation, so duplicate names are legitimate.
 *
 * Capabilities are advertised as available here so the full UI can be built and
 * shown. The real adapter will advertise what the backend actually supports; the
 * degraded paths are exercised by flipping these flags.
 */
import { normaliseStatus } from '../format.js';

const rawDelay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

/**
 * Scales every artificial delay in this module. `1` (the default) preserves the
 * demo feel exactly. The test suite passes `latencyScale: 0` through
 * `createMockGateway`, because asserting behaviour has no reason to wait on a
 * `setTimeout` — the delays exist for the operator watching the console, not for
 * the code under test.
 */
function delay(ms, scale) {
  return rawDelay(ms * scale);
}

/** Minutes ago, as a Date. */
const ago = (minutes) => new Date(Date.now() - minutes * 60000);

const USD = (amount) => ({ amount, currency: 'USD' });

const EXTRACTION_PROMPT_EXCERPT =
  'You are a sales intelligence extractor for CareSure Health Insurance.\n' +
  'Analyse the customer message in the context of the conversation history.\n' +
  'Return ONLY a JSON object with these fields: intent, product, signals, concern.';

/* ==========================================================================
   Agent run construction
   ========================================================================== */

/**
 * Build one agent run. Step kinds follow interface-v1.md §5.3:
 * `llm`, `rule`, `retrieval`, `tool` — where `tool` means a call the *model*
 * chose to make. Knowledge retrieval is a fixed pipeline step and is reported as
 * `retrieval`, never as a tool call.
 */
function buildRun({
  runId,
  clientMessageId,
  startedAt,
  customerMessageCount,
  status = 'ok',
  extraction,
  generation,
  degradedStep = null,
  withholdContent = false,
}) {
  const llmCalls = [];
  let index = 0;

  const addCall = (spec) => {
    if (!spec) return;
    const input = withholdContent
      ? { chars: spec.inputChars }
      : { chars: spec.inputChars, content: spec.inputContent };
    const output = withholdContent
      ? { chars: spec.outputChars }
      : { chars: spec.outputChars, content: spec.outputContent };
    llmCalls.push({
      index: index++,
      purpose: spec.purpose,
      model: 'gpt-4o-mini',
      durationMs: spec.durationMs,
      promptTokens: spec.promptTokens,
      completionTokens: spec.completionTokens,
      totalTokens: spec.promptTokens + spec.completionTokens,
      cost: USD(
        Number(
          (
            (spec.promptTokens * 0.15 + spec.completionTokens * 0.6) /
            1000000
          ).toFixed(8)
        )
      ),
      input,
      output,
    });
  };

  addCall(extraction);
  addCall(generation);

  const steps = [
    {
      index: 0,
      name: 'extraction',
      kind: extraction ? 'llm' : 'rule',
      durationMs: extraction ? extraction.durationMs : 2,
      status: degradedStep === 'extraction' ? 'degraded' : 'ok',
    },
    { index: 1, name: 'state_transition', kind: 'rule', durationMs: 1, status: 'ok' },
    { index: 2, name: 'signal_accumulation', kind: 'rule', durationMs: 1, status: 'ok' },
    { index: 3, name: 'scoring', kind: 'rule', durationMs: 1, status: 'ok' },
    { index: 4, name: 'next_best_action', kind: 'rule', durationMs: 1, status: 'ok' },
    { index: 5, name: 'hitl_evaluation', kind: 'rule', durationMs: 1, status: 'ok' },
    { index: 6, name: 'knowledge_retrieval', kind: 'retrieval', durationMs: 9, status: 'ok' },
    {
      index: 7,
      name: 'response_generation',
      kind: generation ? 'llm' : 'rule',
      durationMs: generation ? generation.durationMs : 3,
      status: 'ok',
    },
    { index: 8, name: 'persistence', kind: 'rule', durationMs: 4, status: 'ok' },
  ];

  const totalTokens = llmCalls.reduce((sum, call) => sum + call.totalTokens, 0);
  const totalCost = llmCalls.reduce((sum, call) => sum + call.cost.amount, 0);

  return {
    runId,
    clientMessageId,
    trigger: 'customer_message',
    status,
    startedAt,
    durationMs: steps.reduce((sum, step) => sum + step.durationMs, 0),
    customerMessageCount,
    degradedStep,
    steps,
    llmCalls,
    // Empty on purpose: there is no tool-calling loop in the backend.
    toolCalls: [],
    totals: {
      agentStepCount: steps.length,
      llmCallCount: llmCalls.length,
      toolCallCount: 0,
      totalTokens,
      cost: llmCalls.length ? USD(Number(totalCost.toFixed(8))) : null,
    },
  };
}

const extractionCall = (durationMs, promptTokens, completionTokens, raw) => ({
  purpose: 'extraction',
  durationMs,
  promptTokens,
  completionTokens,
  inputChars: EXTRACTION_PROMPT_EXCERPT.length + 180,
  inputContent: `${EXTRACTION_PROMPT_EXCERPT}\n\nCustomer message: …`,
  outputChars: raw.length,
  outputContent: raw,
});

const generationCall = (durationMs, promptTokens, completionTokens, output) => ({
  purpose: 'response_generation',
  durationMs,
  promptTokens,
  completionTokens,
  inputChars: 1480,
  inputContent:
    'Approved knowledge-base facts (retrieval confidence 0.90):\n' +
    '- CareSure Plus: Enhanced health protection …\n\n' +
    'Write one concise WhatsApp-style reply using only the facts above.',
  outputChars: output.length,
  outputContent: output,
});

/* ==========================================================================
   Conversations
   ========================================================================== */

function buildData() {
  /* ---- Sarah — C-1024 — the full five-turn arc ------------------------ */
  const sarahTexts = [
    "Hi! I'm looking for health insurance with private hospital coverage.",
    'How much does CareSure Plus cost?',
    'Can I add my child to the plan?',
    "It's a bit expensive, and another insurer offered something cheaper.",
    'How do I apply? What documents do I need?',
  ];
  const sarahReplies = [
    'I appreciate you sharing that. CareSure Plus offers private-hospital access ' +
      'with higher coverage limits, up to S$500,000 per person per year.',
    'Indicative premium: From S$1,500/year per adult, with a S$2,500 deductible ' +
      'and 5% co-payment on eligible claims.',
    "Adding family members is subject to the plan's age, dependency and " +
      'underwriting rules; a representative can confirm who can be included.',
    'I understand price matters. I can only share CareSure-approved facts rather ' +
      'than compare other insurers; a representative can discuss value with you.',
    'Thank you. This needs a human specialist to handle properly, so I have ' +
      'created a case for a CareSure representative to follow up.',
  ];

  const sarahMessages = [];
  const sarahRuns = [];
  const sarahScores = [45, 47, 59, 63, 83];
  sarahTexts.forEach((text, i) => {
    const clientMessageId = `c-1024-${i + 1}`;
    const ts = ago(120 - i * 12);
    sarahMessages.push({
      id: `m-1024-${i}-c`,
      clientMessageId,
      role: 'customer',
      origin: 'customer',
      text,
      ts,
      repName: null,
    });
    sarahMessages.push({
      id: `m-1024-${i}-a`,
      clientMessageId: null,
      role: 'agent',
      origin: 'ai',
      text: sarahReplies[i],
      ts: new Date(ts.getTime() + 2000),
      repName: null,
    });

    // Turn 4 degrades: LLM extraction failed and rules took over. That is a real
    // path in the backend, visible today only as extraction_source.
    const degraded = i === 3;
    sarahRuns.push(
      buildRun({
        runId: `ar-1024-${i + 1}`,
        clientMessageId,
        startedAt: ts,
        customerMessageCount: i + 1,
        status: degraded ? 'degraded' : 'ok',
        degradedStep: degraded ? 'extraction' : null,
        extraction: degraded
          ? null
          : extractionCall(
              620 + i * 40,
              380 + i * 35,
              70 + i * 6,
              JSON.stringify({
                intent: ['coverage', 'price', 'family_need', 'comparison', 'application'][i],
                product: 'plus',
                signals: [[], [], ['Expansion: Family'], ['Hesitation', 'Competitive'], ['Purchase']][i],
                concern: ['', 'premium cost', 'child cover', 'price versus competitor', 'application steps'][i],
              })
            ),
        generation: generationCall(
          310 + i * 25,
          520 + i * 60,
          88 + i * 10,
          sarahReplies[i]
        ),
        // Turn 5 withholds content, standing in for the backend flag being off.
        withholdContent: i === 4,
      })
    );
  });

  /* ---- Michael — C-1025 ----------------------------------------------- */
  const michaelMessages = [
    {
      id: 'm-1025-0-c',
      clientMessageId: 'c-1025-1',
      role: 'customer',
      origin: 'customer',
      text: "Hi, what's your cheapest basic plan?",
      ts: ago(300),
      repName: null,
    },
    {
      id: 'm-1025-0-a',
      clientMessageId: null,
      role: 'agent',
      origin: 'ai',
      text:
        'CareSure Essential: Affordable entry-level protection for essential ' +
        'hospital and medical needs, from S$600/year.',
      ts: ago(299),
      repName: null,
    },
    {
      id: 'm-1025-1-c',
      clientMessageId: 'c-1025-2',
      role: 'customer',
      origin: 'customer',
      text: 'Thanks. What does the Essential plan cover?',
      ts: ago(290),
      repName: null,
    },
    {
      id: 'm-1025-1-a',
      clientMessageId: null,
      role: 'agent',
      origin: 'ai',
      text:
        'Public hospital B1-level coverage: inpatient hospitalisation, selected ' +
        'outpatient treatments, specialist treatment and emergency treatment.',
      ts: ago(289),
      repName: null,
    },
  ];

  // Rule-based only: no model calls at all, so cost is absent rather than zero.
  const michaelRuns = [
    buildRun({
      runId: 'ar-1025-1',
      clientMessageId: 'c-1025-1',
      startedAt: ago(300),
      customerMessageCount: 1,
    }),
    buildRun({
      runId: 'ar-1025-2',
      clientMessageId: 'c-1025-2',
      startedAt: ago(290),
      customerMessageCount: 2,
    }),
  ];

  /* ---- ABC Pte Ltd — C-1026 ------------------------------------------- */
  const abcMessages = [
    {
      id: 'm-1026-0-c',
      clientMessageId: 'c-1026-1',
      role: 'customer',
      origin: 'customer',
      text:
        'We are a company with 120 employees and need corporate health insurance ' +
        'for our staff.',
      ts: ago(75),
      repName: null,
    },
    {
      id: 'm-1026-0-a',
      clientMessageId: null,
      role: 'agent',
      origin: 'ai',
      text:
        'For employee and corporate cover, a corporate sales representative can ' +
        "assess your company's needs and the right plan structure.",
      ts: ago(74),
      repName: null,
    },
    {
      id: 'm-1026-1-c',
      clientMessageId: 'c-1026-2',
      role: 'customer',
      origin: 'customer',
      text: "We'd like to proceed with a corporate quotation. How do we sign up?",
      ts: ago(40),
      repName: null,
    },
    {
      id: 'm-1026-1-a',
      clientMessageId: null,
      role: 'agent',
      origin: 'ai',
      text:
        'Corporate quotations need a human specialist, so I have created a case ' +
        'for a CareSure representative to follow up with you directly.',
      ts: ago(39),
      repName: null,
    },
    {
      id: 'm-1026-2-s',
      clientMessageId: null,
      role: 'agent',
      origin: 'system',
      text:
        'Human takeover active. The AI has stopped making autonomous sales ' +
        'decisions for this conversation.',
      ts: ago(38),
      repName: null,
    },
    // A human reply already in the transcript, so the origin axis is visible
    // before anyone types anything (interface-v1.md §1.2).
    {
      id: 'm-1026-3-h',
      clientMessageId: 'r-1026-1',
      role: 'agent',
      origin: 'human',
      text:
        'Hello, this is Alex from CareSure corporate sales. I can prepare a ' +
        'quotation for 120 employees — could you tell me your preferred ward ' +
        'level and start date?',
      ts: ago(30),
      repName: 'Alex',
    },
  ];

  const abcRuns = [
    buildRun({
      runId: 'ar-1026-1',
      clientMessageId: 'c-1026-1',
      startedAt: ago(75),
      customerMessageCount: 1,
      extraction: extractionCall(
        710,
        402,
        74,
        JSON.stringify({
          intent: 'corporate_need',
          product: 'corporate',
          signals: ['Expansion: Corporate'],
          concern: 'employee coverage',
        })
      ),
      generation: generationCall(
        340,
        560,
        96,
        'For employee and corporate cover, a corporate sales representative can help.'
      ),
    }),
    buildRun({
      runId: 'ar-1026-2',
      clientMessageId: 'c-1026-2',
      startedAt: ago(40),
      customerMessageCount: 2,
      extraction: extractionCall(
        680,
        455,
        81,
        JSON.stringify({
          intent: 'application',
          product: 'corporate',
          signals: ['Purchase', 'Compliance Risk'],
          concern: 'corporate quotation',
        })
      ),
      generation: generationCall(
        290,
        610,
        84,
        'Corporate quotations need a human specialist.'
      ),
    }),
  ];

  /* ---- Sarah (second) — C-2044 — same name, different id -------------- */
  const sarah2Messages = [
    {
      id: 'm-2044-0-c',
      clientMessageId: 'c-2044-1',
      role: 'customer',
      origin: 'customer',
      text: 'Hello, I want to know about family cover for two adults and a baby.',
      ts: ago(18),
      repName: null,
    },
    {
      id: 'm-2044-0-a',
      clientMessageId: null,
      role: 'agent',
      origin: 'ai',
      text:
        'CareSure Family covers a household under one plan. Adding a newborn is ' +
        'subject to the plan’s dependency and underwriting rules.',
      ts: ago(17),
      repName: null,
    },
  ];

  const sarah2Runs = [
    buildRun({
      runId: 'ar-2044-1',
      clientMessageId: 'c-2044-1',
      startedAt: ago(18),
      customerMessageCount: 1,
      extraction: extractionCall(
        590,
        366,
        68,
        JSON.stringify({
          intent: 'family_need',
          product: 'family',
          signals: ['Expansion: Family'],
          concern: 'family cover',
        })
      ),
    }),
  ];

  /* ---- Opportunities -------------------------------------------------- */
  const opportunities = {
    'C-1024': {
      id: 'C-1024',
      name: 'Sarah',
      state: 'High Intent',
      product: 'plus',
      priority: 'HIGH',
      score: 83,
      scoreDimensions: {
        purchase_intent: 28,
        purchase_readiness: 18,
        product_potential: 15,
        expansion: 10,
        engagement: 12,
      },
      signals: ['Purchase', 'Hesitation', 'Competitive', 'Expansion: Family'],
      signalHistory: ['Expansion: Family', 'Hesitation', 'Competitive', 'Purchase'],
      mainConcern: 'price versus competitor',
      competitiveRisk: true,
      churnRisk: false,
      complianceRisk: false,
      expansion: ['Family'],
      humanTakeover: true,
      humanInterventionRequired: true,
      customerMessageCount: 5,
      scoreHistory: sarahScores.map((score, i) => ({
        ts: ago(120 - i * 12),
        score,
        state: ['Potential Interest', 'Evaluation & Hesitation', 'Evaluation & Hesitation', 'Evaluation & Hesitation', 'High Intent'][i],
        trigger: i === 3 ? 'message(rule)' : 'message(llm)',
      })),
      stateHistory: [
        { ts: ago(120), from: 'Cold Lead', to: 'Potential Interest', reason: 'Clear insurance need identified' },
        { ts: ago(108), from: 'Potential Interest', to: 'Evaluation & Hesitation', reason: 'Product / price / coverage evaluation' },
        { ts: ago(72), from: 'Evaluation & Hesitation', to: 'High Intent', reason: 'Purchase preparation strengthens' },
      ],
      nextBestAction: {
        action: 'Human sales intervention: address competitive risk',
        reason: 'High intent with competitive comparison — needs human follow-up',
        priority: 'HIGH',
        humanInterventionRequired: true,
      },
    },

    'C-1025': {
      id: 'C-1025',
      name: 'Michael',
      state: 'Evaluation & Hesitation',
      product: 'essential',
      priority: 'LOW',
      score: 37,
      scoreDimensions: {
        purchase_intent: 18,
        purchase_readiness: 7,
        product_potential: 5,
        expansion: 0,
        engagement: 7,
      },
      signals: [],
      signalHistory: [],
      mainConcern: null,
      competitiveRisk: false,
      churnRisk: false,
      complianceRisk: false,
      expansion: [],
      humanTakeover: false,
      humanInterventionRequired: false,
      customerMessageCount: 2,
      scoreHistory: [
        { ts: ago(300), score: 35, state: 'Potential Interest', trigger: 'message(rule)' },
        { ts: ago(290), score: 37, state: 'Evaluation & Hesitation', trigger: 'message(rule)' },
      ],
      stateHistory: [
        { ts: ago(300), from: 'Cold Lead', to: 'Potential Interest', reason: 'Clear insurance need identified' },
        { ts: ago(290), from: 'Potential Interest', to: 'Evaluation & Hesitation', reason: 'Product / price / coverage evaluation' },
      ],
      nextBestAction: {
        action: 'Address concern with grounded information',
        reason: 'Continued evaluation — provide factual support',
        priority: 'LOW',
        humanInterventionRequired: false,
      },
    },

    'C-1026': {
      id: 'C-1026',
      name: 'ABC Pte Ltd',
      state: 'High Intent',
      product: 'corporate',
      priority: 'HIGH',
      score: 88,
      scoreDimensions: {
        purchase_intent: 28,
        purchase_readiness: 18,
        product_potential: 20,
        expansion: 15,
        engagement: 7,
      },
      signals: ['Purchase', 'Expansion: Corporate', 'Compliance Risk'],
      signalHistory: ['Expansion: Corporate', 'Purchase', 'Compliance Risk'],
      mainConcern: 'corporate quotation',
      competitiveRisk: false,
      churnRisk: false,
      complianceRisk: true,
      expansion: ['Corporate'],
      humanTakeover: true,
      humanInterventionRequired: true,
      customerMessageCount: 2,
      scoreHistory: [
        { ts: ago(75), score: 66, state: 'Potential Interest', trigger: 'message(llm)' },
        { ts: ago(40), score: 88, state: 'High Intent', trigger: 'message(llm)' },
      ],
      stateHistory: [
        { ts: ago(75), from: 'Cold Lead', to: 'Potential Interest', reason: 'Clear insurance need identified' },
        { ts: ago(40), from: 'Potential Interest', to: 'High Intent', reason: 'Strong purchase preparation' },
      ],
      nextBestAction: {
        action: 'Human take-over: contact the customer and handle the case',
        reason: 'Restricted case or HITL trigger requires human intervention',
        priority: 'HIGH',
        humanInterventionRequired: true,
      },
    },

    'C-2044': {
      id: 'C-2044',
      name: 'Sarah',
      state: 'Potential Interest',
      product: 'family',
      priority: 'LOW',
      score: 48,
      // Deliberately null: the dimension breakdown is only returned when a
      // message is processed, so the panel must cope with the total alone
      // (requirement 3.2).
      scoreDimensions: null,
      signals: ['Expansion: Family'],
      signalHistory: ['Expansion: Family'],
      mainConcern: 'family cover',
      competitiveRisk: false,
      churnRisk: false,
      complianceRisk: false,
      expansion: ['Family'],
      humanTakeover: false,
      humanInterventionRequired: false,
      customerMessageCount: 1,
      scoreHistory: [
        { ts: ago(18), score: 48, state: 'Potential Interest', trigger: 'message(llm)' },
      ],
      stateHistory: [
        { ts: ago(18), from: 'Cold Lead', to: 'Potential Interest', reason: 'Clear insurance need identified' },
      ],
      nextBestAction: {
        action: 'Explore expansion opportunity and recommend the right plan',
        reason: 'Expansion signal detected — identify the right product',
        priority: 'LOW',
        humanInterventionRequired: false,
      },
    },
  };

  const messages = {
    'C-1024': sarahMessages,
    'C-1025': michaelMessages,
    'C-1026': abcMessages,
    'C-2044': sarah2Messages,
  };

  const runs = {
    'C-1024': sarahRuns,
    'C-1025': michaelRuns,
    'C-1026': abcRuns,
    'C-2044': sarah2Runs,
  };

  const cases = [
    {
      id: 'H-A911AB',
      opportunityId: 'C-1024',
      customerName: 'Sarah',
      state: 'High Intent',
      product: 'plus',
      reason:
        'High purchase intent with competitive comparison — recommend human sales intervention',
      summary:
        "Customer is in state 'High Intent' interested in plus. Signals: Purchase, " +
        'Hesitation, Competitive, Expansion: Family. Main concern: price versus ' +
        'competitor. Competitive risk: High. Expansion: Family.',
      recommendedAction: 'Human sales intervention: address competitive risk',
      status: 'Open',
      statusToken: 'OPEN',
      createdAt: ago(72),
    },
    {
      id: 'H-E41B5F',
      opportunityId: 'C-1026',
      customerName: 'ABC Pte Ltd',
      state: 'High Intent',
      product: 'corporate',
      reason: 'Corporate quotation / negotiation requires human handling',
      summary:
        "Customer is in state 'High Intent' interested in corporate. Signals: " +
        'Purchase, Expansion: Corporate, Compliance Risk. Main concern: corporate ' +
        'quotation. Competitive risk: None. Expansion: Corporate.',
      recommendedAction: 'Human take-over: contact the customer and handle the case',
      status: 'Taken Over',
      statusToken: 'TAKEN_OVER',
      createdAt: ago(40),
    },
  ];

  return { opportunities, messages, runs, cases };
}

/* ==========================================================================
   Synthesised run — harness only
   ========================================================================== */

/**
 * Build a plausible run for a correlation id this mock has never seen.
 *
 * Needed only by the harness: the embedded device is a separate browsing context
 * and there is no shared backend in mock mode, so a message it just sent cannot
 * appear in this adapter's records. Against a real backend the join on
 * `client_message_id` resolves normally.
 *
 * The result is flagged `simulated: true` so the console labels it rather than
 * presenting invented numbers as measurements.
 */
function synthesiseRun(clientMessageId) {
  const run = buildRun({
    runId: `ar-sim-${String(clientMessageId).slice(-8)}`,
    clientMessageId,
    startedAt: new Date(),
    customerMessageCount: 1,
    extraction: extractionCall(
      560 + Math.round(Math.random() * 220),
      340 + Math.round(Math.random() * 120),
      60 + Math.round(Math.random() * 30),
      JSON.stringify({
        intent: 'generic',
        product: 'unknown',
        signals: [],
        concern: '',
      })
    ),
    generation: generationCall(
      280 + Math.round(Math.random() * 160),
      480 + Math.round(Math.random() * 160),
      70 + Math.round(Math.random() * 40),
      'Reply generated for the harness device.'
    ),
  });
  run.simulated = true;
  return run;
}

/* ==========================================================================
   Adapter
   ========================================================================== */

/**
 * @param {object} [options]
 * @param {number} [options.latencyScale] multiplies every artificial delay;
 *   `0` in tests, `1` (default) for the real console.
 */
export function createMockGateway({ latencyScale = 1 } = {}) {
  let data = buildData();
  let seeded = true;

  const summaryOf = (id) => {
    const opportunity = data.opportunities[id];
    const list = data.messages[id] ?? [];
    const last = list[list.length - 1];
    return {
      id: opportunity.id,
      name: opportunity.name,
      score: opportunity.score,
      priority: opportunity.priority,
      state: opportunity.state,
      product: opportunity.product,
      humanTakeover: opportunity.humanTakeover,
      lastMessagePreview: last ? last.text : '',
      lastMessageAt: last ? last.ts : null,
      customerMessageCount: opportunity.customerMessageCount,
    };
  };

  return {
    name: 'mock',

    capabilities: {
      repReply: true,
      telemetry: true,
      author: true,
      quickReplies: false,
    },

    async listConversations() {
      await delay(180, latencyScale);
      if (!seeded) return { items: [] };
      return { items: Object.keys(data.opportunities).map(summaryOf) };
    },

    async getConversation(id) {
      await delay(220, latencyScale);
      const opportunity = data.opportunities[id];
      if (!opportunity) {
        const error = new Error('Conversation not found');
        error.status = 404;
        throw error;
      }
      const linkedCase =
        data.cases.find(
          (c) => c.opportunityId === id && c.statusToken !== 'CLOSED'
        ) ?? null;
      return {
        opportunity: { ...opportunity },
        messages: [...(data.messages[id] ?? [])],
        linkedCase,
      };
    },

    async listCases() {
      await delay(160, latencyScale);
      if (!seeded) return { items: [] };
      return { items: data.cases.map((c) => ({ ...c })) };
    },

    async updateCaseStatus(id, statusToken) {
      await delay(260, latencyScale);
      const target = data.cases.find((c) => c.id === id);
      if (!target) {
        const error = new Error('Case not found');
        error.status = 404;
        throw error;
      }

      const token = normaliseStatus(statusToken);
      const label = { OPEN: 'Open', TAKEN_OVER: 'Taken Over', CLOSED: 'Closed' }[token];
      if (!label) {
        const error = new Error(`Invalid status: ${statusToken}`);
        error.status = 400;
        throw error;
      }

      target.status = label;
      target.statusToken = token;

      // Mirrors the backend: closing a case clears human takeover, which lets
      // the AI resume autonomous selling on the next customer message.
      const opportunity = data.opportunities[target.opportunityId];
      if (opportunity) {
        opportunity.humanTakeover = token !== 'CLOSED';
        opportunity.humanInterventionRequired = token !== 'CLOSED';
      }

      return { ...target };
    },

    async listAgentRuns({ opportunityId, clientMessageId } = {}) {
      await delay(200, latencyScale);
      let items = [];
      if (opportunityId) {
        items = data.runs[opportunityId] ?? [];
      } else if (clientMessageId) {
        items = Object.values(data.runs)
          .flat()
          .filter((run) => run.clientMessageId === clientMessageId);

        // The harness device is a separate browsing context talking to no shared
        // backend, so a message it just sent has no recorded run here. Against a
        // real backend the correlation would resolve. Rather than return nothing
        // and leave the mechanism undemonstrable, synthesise a run — and mark it
        // `simulated` so the console can say so. Fabricating metrics that look
        // measured is precisely what this project avoids.
        if (items.length === 0) {
          items = [synthesiseRun(clientMessageId)];
        }
      }
      return { items: items.map((run) => ({ ...run })) };
    },

    async sendRepReply({ id, text, repName, clientMessageId }) {
      await delay(320, latencyScale);
      const opportunity = data.opportunities[id];
      if (!opportunity) {
        const error = new Error('Conversation not found');
        error.status = 404;
        throw error;
      }
      // Mirrors the specified backend behaviour: a human reply is only valid
      // while the conversation is under takeover.
      if (!opportunity.humanTakeover) {
        const error = new Error('Conversation is not under human takeover');
        error.status = 409;
        throw error;
      }
      // Lets the failure path be demonstrated without unplugging anything.
      if (/\bfail\b/i.test(text)) {
        throw new Error('Mock transport: simulated reply failure');
      }

      const message = {
        id: `m-${id}-rep-${Date.now()}`,
        clientMessageId,
        role: 'agent',
        origin: 'human',
        text,
        ts: new Date(),
        repName,
      };
      data.messages[id] = [...(data.messages[id] ?? []), message];
      return { message };
    },

    async seedDemoData() {
      await delay(300, latencyScale);
      if (seeded) return { seeded: false };
      data = buildData();
      seeded = true;
      return { seeded: true };
    },

    async health() {
      return true;
    },

    /** Test affordance: empty the console to exercise the empty states. */
    async __clear() {
      data = { opportunities: {}, messages: {}, runs: {}, cases: [] };
      seeded = false;
    },
  };
}
