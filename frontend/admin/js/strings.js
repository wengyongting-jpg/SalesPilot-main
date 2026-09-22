/**
 * Every user-facing string in the admin console (requirement 9.2).
 *
 * English only. Also holds the presentation label maps for backend enums, so a
 * view never embeds a backend value as display copy.
 *
 * Vocabulary note: this file never says "turns". Per docs/api/interface-v1.md
 * §1.1 the customer-message counter is named explicitly, because "turns" is read
 * as agent turns and is not.
 */
import { config } from './config.js';

export const strings = {
  documentTitle: `${config.business.name} — Sales Console`,

  nav: {
    title: 'SalesPilot',
    subtitle: 'Sales Console',
    inbox: 'Inbox',
    cases: 'Cases',
    harness: 'Test Harness',
    openCases: (n) => `${n} open case${n === 1 ? '' : 's'}`,
    operatorLabel: 'Signed in as',
    noAuthNote: 'Demo — no authentication',
  },

  inbox: {
    listTitle: 'Conversations',
    refresh: 'Refresh',
    seed: 'Load demo data',
    emptyTitle: 'No conversations',
    emptyBody:
      'Nothing has come in yet. Load the demo data, or send a message from the ' +
      'customer app.',
    loadFailed: 'Could not load conversations.',
    retry: 'Try again',
    takeoverMarker: 'Human handling',
    selectTitle: 'Select a conversation',
    selectBody:
      'Choose a customer on the left to see their conversation, assessment and ' +
      'agent activity.',
    conversationFailed: 'Could not load this conversation.',
  },

  conversation: {
    messageCountLabel: 'customer messages',
    transcriptEmpty: 'No messages in this conversation yet.',
    openCase: 'View case',
  },

  origin: {
    customer: 'Customer',
    ai: 'AI Assistant',
    human: 'Representative',
    system: 'System',
  },

  composer: {
    placeholder: 'Reply to the customer…',
    inputLabel: 'Reply to the customer',
    send: 'Send reply',
    sending: 'Sending…',
    // Why it is unavailable, stated rather than implied (requirement 2.6, 2.7).
    needsTakeover:
      'Take over the case before replying. While the AI owns the conversation it ' +
      'answers on its own.',
    unsupported:
      'The backend does not provide a write path for a human reply yet, so this ' +
      'composer is disabled. Tracked as item 4 in docs/backend-contract.md.',
    failed: 'Reply not sent. Your draft has been kept.',
    noConversation: 'Select a conversation to reply.',
  },

  panels: {
    intelligence: 'Assessment',
    observability: 'Agent Activity',
  },

  intelligence: {
    stateLabel: 'Journey state',
    productLabel: 'Product',
    priorityLabel: 'Priority',
    concernLabel: 'Main concern',
    competitiveLabel: 'Competitive risk',
    churnLabel: 'Churn risk',
    complianceLabel: 'Compliance risk',
    expansionLabel: 'Expansion',
    takeoverLabel: 'Human takeover',
    messageCountLabel: 'Customer messages',
    signalsTitle: 'Signals',
    scoreTitle: 'Opportunity value score',
    dimensionsUnavailable:
      'The dimension breakdown is only returned when a message is processed, so ' +
      'only the total is available here.',
    scoreHistoryTitle: 'Score history',
    stateHistoryTitle: 'State history',
    nbaTitle: 'Next best action',
    nbaReasonLabel: 'Reason',
    nbaHumanLabel: 'Human intervention',
    caseTitle: 'Open case',
    caseReasonLabel: 'Escalation reason',
    caseActionLabel: 'Recommended action',
    yes: 'Yes',
    no: 'No',
    none: 'None',
    required: 'Required',
    notRequired: 'Not required',
    noScore: 'Not scored yet',
    empty: '—',
  },

  observability: {
    title: 'Agent runs',
    runsEmpty: 'No agent activity recorded for this conversation yet.',
    runsFailed: 'Could not load agent activity.',
    // Requirement 4.10: absent telemetry is labelled, never shown as zero.
    notReported: 'not reported',
    unavailableTitle: 'Telemetry not available',
    unavailableBody:
      'This transport does not report agent telemetry. Client-observed duration ' +
      'and status are shown where available; model, token, cost and step detail ' +
      'are not reported. Tracked as item 8 in docs/backend-contract.md.',
    totalTokens: 'Total tokens',
    totalCost: 'Total cost',
    runCount: 'Agent runs',
    llmCalls: 'Model calls',
    toolCalls: 'Tool calls',
    steps: 'Steps',
    // Requirement 4.8 / interface §1.1: retrieval is not a tool call.
    toolCallsNote:
      'Tool calls count only calls the model chose to make. Knowledge retrieval ' +
      'is a fixed pipeline step and is not counted here.',
    stepsTitle: 'Steps',
    callsTitle: 'Model calls',
    selectRun: 'Select a run to see its steps and model calls.',
    triggerLabel: 'Trigger',
    promptTokens: 'Prompt',
    completionTokens: 'Completion',
    totalTokensShort: 'Total',
    inputLabel: 'Input',
    outputLabel: 'Output',
    charsSuffix: 'chars',
    contentWithheld:
      'Content is not exposed by the backend. Length is shown above.',
    degradedAt: (step) => `Degraded at: ${step}`,
    clientObserved: 'Client-observed',
  },

  stepKind: {
    llm: 'model',
    rule: 'rule',
    retrieval: 'retrieval',
    tool: 'tool',
  },

  trigger: {
    customer_message: 'Customer message',
    retry: 'Retry',
    scheduled: 'Scheduled',
  },

  cases: {
    title: 'Human escalation cases',
    refresh: 'Refresh',
    emptyTitle: 'No cases',
    emptyBody:
      'Cases appear here when the agent escalates a conversation to a person.',
    loadFailed: 'Could not load cases.',
    takeOver: 'Take over',
    resolve: 'Resolve',
    markResolved: 'Mark resolved',
    working: 'Working…',
    transitionFailed: 'Could not change the case status. Nothing was changed.',
    // Requirement 5.9: the side effect of closing must be stated up front.
    resolveNotice:
      'Resolving a case clears human takeover on the opportunity, which lets the ' +
      'AI resume selling on the customer’s next message.',
    customerLabel: 'Customer',
    reasonLabel: 'Reason',
    summaryLabel: 'Summary',
    recommendedLabel: 'Recommended',
    createdLabel: 'Created',
    stateLabel: 'State',
    productLabel: 'Product',
  },

  harness: {
    title: 'Test harness',
    deviceCaption: 'Customer app — live instance',
    sessionTitle: 'Session',
    customerIdLabel: 'Customer ID',
    customerNameLabel: 'Customer name',
    transportLabel: 'Device transport',
    scenarioLabel: 'Scenario',
    apply: 'Apply',
    reload: 'Reload device',
    reset: 'Reset conversation',
    // Replaces an earlier "Send as customer" control, which was redundant:
    // typing in the device on the right does exactly that. What nothing else can
    // show is the customer's view of a human representative's reply.
    injectTitle: 'Send as business — human representative',
    injectPlaceholder: 'Reply to the customer as a representative…',
    injectLabel: 'Reply to the customer as a human representative',
    inject: 'Send to device',
    injectNote:
      'Delivers the message straight into the device so you can see how a human ' +
      'reply looks to the customer. This is not the same as the Inbox composer: ' +
      'that one goes through the backend write path, which does not exist yet.',
    repNameLabel: 'Representative name',
    statusTitle: 'Live status',
    connection: 'Connection',
    takeover: 'Takeover',
    messages: 'Messages',
    timelineTitle: 'Exchanges',
    timelineEmpty:
      'No exchanges yet. Send a message in the device on the right to record one.',
    deviceWaiting: 'Waiting for the device…',
    deviceTimeout:
      'The device did not respond. Both apps must be served from the same HTTP ' +
      'origin — opening the file directly will not work.',
    detailTitle: 'Selected exchange',
    selectEntry: 'Select an exchange to see what the agent did.',
    // Requirement 6.12
    isolationNote:
      'The device is the unmodified customer app. Assessment and telemetry are ' +
      'shown here only, never inside the device.',
    // Honest labelling: in mock mode the device and this console share no
    // backend, so a run for a new exchange is synthesised rather than measured.
    simulatedRun:
      'Simulated run. The device and this console share no backend in mock mode, ' +
      'so this agent run was generated. The duration and status in the timeline ' +
      'are genuinely observed by the device.',
    clientObservedTitle: 'Client-observed',
    statusLabel: 'Status',
    durationLabel: 'Duration',
    correlationLabel: 'Correlation id',
    runPending: 'Looking up the agent run…',
    runMissing: 'No agent run is recorded for this exchange.',
    runFailed: 'Could not load the agent run for this exchange.',
    deviceReadyLabel: 'Device',
    deviceReadyYes: 'Connected',
    deviceReadyNo: 'Not connected',
    statusOk: 'OK',
    statusFailed: 'Failed',
    transportMock: 'Mock (no server)',
    transportSalesPilot: 'SalesPilot backend',
    scenarioFresh: 'Fresh conversation',
    scenarioRendering: 'Rendering fixture',
  },

  common: {
    loading: 'Loading…',
    error: 'Something went wrong.',
    retry: 'Try again',
    dismiss: 'Dismiss',
    unknown: 'Unknown',
    empty: '—',
  },

  /** Backend enum -> display label. */
  product: {
    essential: 'Essential',
    family: 'Family',
    plus: 'Plus',
    corporate: 'Corporate',
    unknown: 'Not identified',
  },

  /** Long signal values shortened for dense rows; full value kept as a title. */
  signalShort: {
    'Expansion: Family': 'Exp: Family',
    'Expansion: Corporate': 'Exp: Corporate',
    'Purchase Preparation': 'Purchase Prep',
    'Compliance Risk': 'Compliance',
    'Human Request': 'Human Req',
  },

  scoreDimension: {
    purchase_intent: 'Purchase intent',
    purchase_readiness: 'Purchase readiness',
    product_potential: 'Product potential',
    expansion: 'Expansion',
    engagement: 'Engagement & urgency',
  },
};

/** Maximum for each score dimension, per the 100-point model. */
export const SCORE_DIMENSION_MAX = {
  purchase_intent: 30,
  purchase_readiness: 20,
  product_potential: 20,
  expansion: 15,
  engagement: 15,
};
