/**
 * Admin console store.
 *
 * The only mutable state. Views read from it and dispatch named actions; the
 * gateway adapter never touches it directly.
 *
 * This console is the inverse of the customer app: the customer adapter discards
 * sales intelligence at the boundary, this one keeps all of it. Both rules exist
 * so the audience boundary lives in exactly one place per app.
 *
 * Counter naming: the store uses `customerMessageCount`, never `turns`. The
 * adapter renames the backend field on the way in, which confines the misleading
 * name to a single line of code. See docs/v0.0/api/interface-v1.md §1.1.
 */

export function createStore() {
  /** @type {Set<Function>} */
  const listeners = new Set();

  const state = {
    /** @type {'inbox'|'cases'|'debug'|'harness'} */
    route: 'inbox',
    /** @type {string|null} opportunity id */
    selectedId: null,
    /** @type {'intelligence'|'observability'} */
    activePanel: 'intelligence',

    inbox: {
      /** @type {'idle'|'loading'|'error'} */
      status: 'idle',
      items: [],
      counts: { HIGH: 0, MEDIUM: 0, LOW: 0 },
    },

    conversation: {
      /** @type {'idle'|'loading'|'error'} */
      status: 'idle',
      opportunity: null,
      messages: [],
      linkedCase: null,
    },

    runs: {
      /** @type {'idle'|'loading'|'error'} */
      status: 'idle',
      items: [],
      selectedRunId: null,
    },

    cases: {
      /** @type {'idle'|'loading'|'error'} */
      status: 'idle',
      items: [],
      openCount: 0,
    },

    compose: { draft: '', inFlight: false, error: null },
    brief: { loading: false, text: '', source: '', error: null },

    transition: { caseId: null, inFlight: false, error: null },

    harness: {
      deviceReady: false,
      deviceError: null,
      transport: 'mock',
      scenario: 'fresh',
      customerId: '',
      customerName: '',
      connection: 'unknown',
      humanTakeover: false,
      customerMessageCount: 0,
      messageCount: 0,
      /** @type {Array<object>} */
      timeline: [],
      selectedEntryId: null,
    },

    /** What the selected transport can actually do. Drives degradation. */
    capabilities: {
      repReply: false,
      telemetry: false,
      author: false,
      quickReplies: false,
    },
  };

  const notify = () => {
    for (const listener of listeners) listener(state);
  };

  /**
   * Tally the backend's own priority strings. Never re-band from raw scores:
   * the thresholds live in backend config and duplicating them here would be a
   * second source of truth (requirement 3.8).
   */
  const tallyPriorities = (items) => {
    const counts = { HIGH: 0, MEDIUM: 0, LOW: 0 };
    for (const item of items) {
      const key = String(item.priority || 'LOW').toUpperCase();
      if (key in counts) counts[key] += 1;
      else counts.LOW += 1;
    }
    return counts;
  };

  /**
   * Presentation ordering only — no value is recomputed.
   *
   * Ranking is by **priority**, not by the score. The kernel derives priority from
   * a two-axis fit/behaviour matrix rather than a threshold on a single number,
   * and the backend marks `score.total` as display-only. Sorting by the number
   * would therefore contradict the ranking the backend actually made — a
   * HIGH-priority opportunity could sit below a MEDIUM one with a bigger total.
   * The score breaks ties within a band so the order stays stable.
   */
  const PRIORITY_RANK = { HIGH: 0, MEDIUM: 1, LOW: 2 };

  const byPriorityThenScore = (a, b) => {
    const rankA = PRIORITY_RANK[String(a.priority ?? '').toUpperCase()] ?? 3;
    const rankB = PRIORITY_RANK[String(b.priority ?? '').toUpperCase()] ?? 3;
    if (rankA !== rankB) return rankA - rankB;
    return (b.score ?? -1) - (a.score ?? -1);
  };

  return {
    getState: () => state,

    subscribe(listener) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },

    // ---- Routing ---------------------------------------------------------

    routeChanged(route) {
      if (state.route === route) return;
      state.route = route;
      notify();
    },

    panelChanged(panel) {
      if (state.activePanel === panel) return;
      state.activePanel = panel;
      notify();
    },

    capabilitiesSet(capabilities) {
      Object.assign(state.capabilities, capabilities);
      notify();
    },

    // ---- Inbox -----------------------------------------------------------

    inboxLoading() {
      state.inbox.status = 'loading';
      notify();
    },

    inboxLoaded(items) {
      state.inbox.status = 'idle';
      state.inbox.items = [...items].sort(byPriorityThenScore);
      state.inbox.counts = tallyPriorities(items);
      notify();
    },

    inboxFailed() {
      state.inbox.status = 'error';
      notify();
    },

    // ---- Conversation ----------------------------------------------------

    conversationRequested(id) {
      state.selectedId = id;
      state.conversation.status = 'loading';
      state.conversation.opportunity = null;
      state.conversation.messages = [];
      state.conversation.linkedCase = null;
      state.compose.draft = '';
      state.compose.error = null;
      state.brief = { loading: false, text: '', source: '', error: null };
      state.runs = { status: 'idle', items: [], selectedRunId: null };
      notify();
    },

    conversationLoaded({ opportunity, messages, linkedCase }) {
      state.conversation.status = 'idle';
      state.conversation.opportunity = opportunity;
      state.conversation.messages = messages;
      state.conversation.linkedCase = linkedCase ?? null;
      notify();
    },

    conversationFailed() {
      state.conversation.status = 'error';
      notify();
    },

    briefStarted() {
      state.brief.loading = true;
      state.brief.error = null;
      notify();
    },

    briefLoaded(result) {
      state.brief = {
        loading: false, text: result.text, source: result.source, error: null,
      };
      notify();
    },

    briefFailed(message) {
      state.brief.loading = false;
      state.brief.error = message;
      notify();
    },

    // ---- Agent runs ------------------------------------------------------

    runsLoading() {
      state.runs.status = 'loading';
      notify();
    },

    runsLoaded(items) {
      state.runs.status = 'idle';
      state.runs.items = items;
      // Default to the newest run so the panel is never empty for no reason.
      state.runs.selectedRunId = items.length
        ? items[items.length - 1].runId
        : null;
      notify();
    },

    runsFailed() {
      state.runs.status = 'error';
      notify();
    },

    runSelected(runId) {
      state.runs.selectedRunId = runId;
      notify();
    },

    // ---- Composer --------------------------------------------------------

    draftChanged(text) {
      state.compose.draft = text;
    },

    replyStarted() {
      state.compose.inFlight = true;
      state.compose.error = null;
      notify();
    },

    replyAppended(message) {
      state.compose.inFlight = false;
      state.compose.draft = '';
      state.conversation.messages = [...state.conversation.messages, message];
      notify();
    },

    /** The draft is deliberately preserved (requirement 2.9). */
    replyFailed(message) {
      state.compose.inFlight = false;
      state.compose.error = message || true;
      notify();
    },

    // ---- Cases -----------------------------------------------------------

    casesLoading() {
      state.cases.status = 'loading';
      notify();
    },

    casesLoaded(items) {
      state.cases.status = 'idle';
      state.cases.items = items;
      state.cases.openCount = items.filter(
        (c) => c.statusToken === 'OPEN'
      ).length;
      notify();
    },

    casesFailed() {
      state.cases.status = 'error';
      notify();
    },

    transitionStarted(caseId) {
      state.transition = { caseId, inFlight: true, error: null };
      notify();
    },

    /**
     * Replace from the response body, not from the requested value. A takeover
     * that appears to succeed but did not is worse than a slow one.
     */
    transitionSucceeded(updated) {
      state.transition = { caseId: null, inFlight: false, error: null };
      state.cases.items = state.cases.items.map((c) =>
        c.id === updated.id ? updated : c
      );
      state.cases.openCount = state.cases.items.filter(
        (c) => c.statusToken === 'OPEN'
      ).length;

      // Keep the open conversation's linked case in step (requirement 5.10).
      // The takeover flag is deliberately NOT inferred from the case status:
      // they are two backend facts, and the backend is the only authority on
      // the second one. main.js re-reads the opportunity after a transition.
      const opportunity = state.conversation.opportunity;
      if (opportunity && opportunity.id === updated.opportunityId) {
        state.conversation.linkedCase =
          updated.statusToken === 'CLOSED' ? null : updated;
      }
      notify();
    },

    transitionFailed(caseId, message) {
      state.transition = { caseId, inFlight: false, error: message || true };
      notify();
    },

    // ---- Harness ---------------------------------------------------------

    harnessConfigured(patch) {
      Object.assign(state.harness, patch);
      notify();
    },

    deviceReady(payload) {
      state.harness.deviceReady = true;
      state.harness.deviceError = null;
      if (payload?.transport) state.harness.transport = payload.transport;
      if (payload?.customerId) state.harness.customerId = payload.customerId;
      notify();
    },

    deviceLost(message) {
      state.harness.deviceReady = false;
      state.harness.deviceError = message || true;
      notify();
    },

    deviceStateReported(payload) {
      Object.assign(state.harness, {
        connection: payload.connection ?? state.harness.connection,
        humanTakeover: payload.humanTakeover ?? state.harness.humanTakeover,
        customerMessageCount:
          payload.customerMessageCount ?? state.harness.customerMessageCount,
        messageCount: payload.messageCount ?? state.harness.messageCount,
      });
      notify();
    },

    /**
     * An exchange observed by the device. The payload is deliberately small and
     * non-sensitive; the telemetry itself is fetched separately from the admin
     * surface, because the customer surface has no shape for it.
     */
    exchangeObserved({ clientMessageId, durationMs, status }) {
      state.harness.timeline = [
        ...state.harness.timeline,
        {
          id: clientMessageId,
          clientMessageId,
          at: new Date(),
          durationMs,
          status,
          /** @type {object|null} filled once the run is fetched */
          run: null,
          runStatus: 'idle',
        },
      ];
      state.harness.selectedEntryId = clientMessageId;
      notify();
    },

    entrySelected(id) {
      state.harness.selectedEntryId = id;
      notify();
    },

    entryRunLoading(id) {
      const entry = state.harness.timeline.find((e) => e.id === id);
      if (entry) entry.runStatus = 'loading';
      notify();
    },

    entryRunLoaded(id, run) {
      const entry = state.harness.timeline.find((e) => e.id === id);
      if (entry) {
        entry.run = run;
        entry.runStatus = run ? 'idle' : 'empty';
      }
      notify();
    },

    entryRunFailed(id) {
      const entry = state.harness.timeline.find((e) => e.id === id);
      if (entry) entry.runStatus = 'error';
      notify();
    },

    harnessReset() {
      state.harness.timeline = [];
      state.harness.selectedEntryId = null;
      state.harness.customerMessageCount = 0;
      state.harness.messageCount = 0;
      state.harness.humanTakeover = false;
      notify();
    },
  };
}
