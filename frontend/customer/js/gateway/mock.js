/**
 * Mock transport — scripted, no network.
 *
 * Runs the whole UI without the Python server, which is what the frontend-only
 * slices are built against and what makes the demo independent of the backend
 * (requirement 9.3).
 *
 * Scenario is chosen with a URL query parameter:
 *
 *   ?scenario=fresh      (default) empty conversation, shows the welcome state
 *   ?scenario=rendering  a fixture exercising every rendering rule at once:
 *                        a cross-midnight date separator, a same-minute run that
 *                        must group, a same-minute pair from *different* authors
 *                        that must NOT group, an emoji-only message, a message
 *                        whose body is literal HTML, and a system message
 *
 * Send behaviour:
 *   - any message containing the word "fail" is rejected, so the failed tick and
 *     retry control can be demonstrated without unplugging the network
 *   - everything else returns the next canned reply
 *
 * Capabilities are reported to mirror the *current* real backend rather than an
 * ideal one: no idempotency, no quick replies, no incremental fetch. That keeps
 * the degraded paths — including the retry duplicate warning — on the exercised
 * code path instead of a path nobody sees until task 4. See
 * docs/v0.0/backend/backend-contract.md Part B.
 */
import { createMessage } from '../store.js';

/** The backend appends this sentence into replies that quote premiums. */
const DEMO_DISCLAIMER =
  'All premiums are fictional indicative rates for the SalesPilot demo and do ' +
  'not represent actual insurance quotations. Final premiums are subject to ' +
  'age, underwriting, plan selection and insurer assessment.';

/**
 * Default reply script — the nurture arc. Served in order; the last one repeats
 * once exhausted.
 */
const REPLY_SCRIPT = [
  "Hi! I'm CareSure's AI sales assistant. I can help with plan information, " +
    'indicative premiums, coverage, eligibility, claims process and ' +
    'applications. Which plan would you like to know about: Essential, ' +
    'Family, Plus or Corporate?',

  'CareSure Plus: Enhanced health protection for customers who want higher ' +
    'coverage limits, broader healthcare options and private-hospital access.\n' +
    'Indicative premium: From S$1,500/year per adult.\n' +
    'Deductible / co-payment: S$2,500 deductible + 5% co-payment on eligible ' +
    `claims.\n${DEMO_DISCLAIMER}`,

  'Coverage: Private / higher-tier hospital coverage; inpatient care, ' +
    'specialist treatment, selected outpatient treatments, emergency care and ' +
    'selected preventive benefits.\n' +
    'Coverage limit: Annual claim limit up to S$500,000 per person per year.',

  'Adding family members is subject to the plan\'s age, dependency and ' +
    'underwriting rules. A CareSure representative can confirm exactly who can ' +
    'be included and what documents are needed.',
];

const FAIL_TRIGGER = /\bfail\b/i;

const MIN_LATENCY_MS = 700;
const JITTER_MS = 500;

const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

/**
 * Scales every artificial delay in this module. `1` (the default) preserves the
 * demo feel exactly. The test suite sets it to `0` via `?mockLatency=0`, because
 * asserting behaviour has no reason to wait on a `setTimeout` — the delays exist
 * for the human watching the demo, not for the code under test.
 *
 * Read once at module load, like `readScenario()` below. Reading it lazily
 * inside `send()`/`loadHistory()` would sample `window.location.search` at call
 * time rather than at construction time — and tests restore their stubbed
 * `window` immediately after `createMockGateway()` returns, before any `await`
 * on a returned method resolves, so a lazy read would silently see the wrong
 * (or no) window and fall back to the un-scaled default.
 */
function readLatencyScale() {
  try {
    const raw = new URLSearchParams(window.location.search).get('mockLatency');
    const scale = raw === null ? 1 : Number(raw);
    return Number.isFinite(scale) && scale >= 0 ? scale : 1;
  } catch {
    return 1;
  }
}

/** A Date at a given day offset and wall-clock time, for stable fixtures. */
function at(dayOffset, hours, minutes) {
  const date = new Date();
  date.setDate(date.getDate() + dayOffset);
  date.setHours(hours, minutes, 0, 0);
  return date;
}

function renderingFixture() {
  return [
    // --- Yesterday: produces a "Yesterday" separator ---------------------
    createMessage({
      id: 'fx-1',
      direction: 'out',
      author: 'customer',
      text: 'Hi, is anyone there?',
      ts: at(-1, 16, 4),
      status: 'read',
    }),
    // Same minute as the message above but a different author, so this must
    // start a new run and keep its tail.
    createMessage({
      id: 'fx-2',
      direction: 'in',
      author: 'ai',
      text: 'Hello! Yes, I am here and happy to help.',
      ts: at(-1, 16, 4),
    }),

    // --- Today: crossing midnight produces a "Today" separator -----------
    createMessage({
      id: 'fx-3',
      direction: 'out',
      author: 'customer',
      text: 'Morning!',
      ts: at(0, 9, 12),
      status: 'read',
    }),
    // Same author, same minute: grouped, no tail.
    createMessage({
      id: 'fx-4',
      direction: 'out',
      author: 'customer',
      text: 'Quick question about the Plus plan.',
      ts: at(0, 9, 12),
      status: 'read',
    }),
    // Literal HTML in the body. Must render as text and execute nothing
    // (requirement 1.7).
    createMessage({
      id: 'fx-5',
      direction: 'out',
      author: 'customer',
      text: '<script>alert(1)</script> and <b>bold?</b>',
      ts: at(0, 9, 12),
      status: 'read',
    }),
    // A URL, which must stay plain text and not become a link
    // (requirement 1.9).
    createMessage({
      id: 'fx-6',
      direction: 'in',
      author: 'ai',
      text:
        'You can read the plan summary at https://example.com/caresure-plus ' +
        'or ask me here.',
      ts: at(0, 9, 13),
    }),
    // Emoji-only: enlarged, no bubble (requirement 1.8).
    createMessage({
      id: 'fx-7',
      direction: 'out',
      author: 'customer',
      text: '👍',
      ts: at(0, 9, 14),
      status: 'read',
    }),
    // System message, visually distinct from both bubble kinds
    // (requirement 6.5).
    createMessage({
      id: 'fx-8',
      direction: 'in',
      author: 'system',
      text:
        'This conversation is handled by an AI assistant. A human ' +
        'representative can join at any time.',
      ts: at(0, 9, 15),
    }),
  ];
}

/**
 * Scripted scenarios (requirement 13.4). Each is a list of replies served in
 * order; `takeover: n` flips the conversation to human handling from the nth
 * reply onwards, which is what exercises the handoff treatment end to end.
 *
 * `fresh` uses the default nurture script above. `rendering` loads a transcript
 * fixture instead of a reply script, for the rendering-rule checks.
 */
const SCENARIOS = {
  nurture: {
    replies: REPLY_SCRIPT,
  },

  hesitation: {
    replies: [
      'CareSure Plus gives you private-hospital access with an annual claim ' +
        'limit up to S$500,000 per person.',
      'Indicative premium: From S$1,500/year per adult, with a S$2,500 ' +
        `deductible and 5% co-payment on eligible claims.\n${DEMO_DISCLAIMER}`,
      'I understand price matters. I can only share CareSure-approved facts ' +
        'rather than compare other insurers — a representative can talk you ' +
        'through the value in detail.',
      'That is completely reasonable. Take the time you need; I can send a ' +
        'summary of the plan whenever you would like one.',
    ],
  },

  takeover: {
    replies: [
      'CareSure Corporate covers employee groups under a single policy.',
      'Corporate quotations need a human specialist, so I have created a case ' +
        'for a CareSure representative to follow up with you directly.',
      'A representative is now looking after your case and will reply here.',
    ],
    // From the second reply onwards the conversation is human-handled.
    takeover: 2,
    repName: 'Alex',
  },
};

const SCENARIO_ALIASES = { fresh: 'nurture' };

function readScenarioName() {
  try {
    return new URLSearchParams(window.location.search).get('scenario') || 'fresh';
  } catch {
    return 'fresh';
  }
}

export function createMockGateway() {
  const scenarioName = readScenarioName();
  const scenario =
    SCENARIOS[SCENARIO_ALIASES[scenarioName] ?? scenarioName] ?? SCENARIOS.nurture;

  // Captured now, not lazily — see readLatencyScale()'s comment.
  const latencyScale = readLatencyScale();
  const scaledDelay = (ms) => delay(ms * latencyScale);
  const latency = () => scaledDelay(MIN_LATENCY_MS + Math.random() * JITTER_MS);

  /** How many replies have been served; drives the script and the takeover point. */
  let replyCount = 0;

  /** @type {Array<object>} */
  let history = scenarioName === 'rendering' ? renderingFixture() : [];

  const nextReply = () => {
    const { replies } = scenario;
    const text = replies[Math.min(replyCount, replies.length - 1)];
    replyCount += 1;
    return text;
  };

  /** True once the scenario's takeover point has been reached. */
  const takeoverActive = () =>
    typeof scenario.takeover === 'number' && replyCount >= scenario.takeover;

  return {
    name: 'mock',

    async loadHistory() {
      // Compare the scenario *name*: `scenario` is the resolved config object.
      await scaledDelay(history.length === 0 ? 120 : 420);
      return {
        messages: [...history],
        humanTakeover: false,
        repName: null,
        capabilities: {
          idempotency: false,
          quickReplies: false,
          incrementalFetch: false,
        },
      };
    },

    async send({ text }) {
      await latency();

      if (FAIL_TRIGGER.test(text)) {
        // Rejecting here exercises the failed tick and the retry control
        // (requirements 2.7, 2.8) without touching the network.
        throw new Error('Mock transport: simulated send failure');
      }

      const replyText = nextReply();
      const humanTakeover = takeoverActive();

      const reply = createMessage({
        direction: 'in',
        // Once a human owns the conversation the reply is attributed to them,
        // which is what drives the header change and the handoff banner.
        author: humanTakeover ? 'human' : 'ai',
        text: replyText,
      });

      return {
        messages: [reply],
        quickReplies: [],
        humanTakeover,
        repName: humanTakeover ? scenario.repName ?? null : null,
        // Mirrors the current backend. See the module comment.
        capabilities: {
          idempotency: false,
          quickReplies: false,
          incrementalFetch: false,
        },
      };
    },

    async fetchSince() {
      return { messages: [] };
    },

    async reset() {
      history = [];
      replyCount = 0;
    },

    async health() {
      return true;
    },
  };
}
