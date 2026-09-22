/**
 * Conversation store.
 *
 * The only mutable state in the app, and the only thing views and gateway
 * adapters both know about. Views read from it and dispatch named actions;
 * adapters never touch it directly.
 *
 * This store holds *presentation* state only — delivery ticks, scroll position,
 * unread count, connectivity, typing. It deliberately holds no opportunity
 * score, priority, signal, state or next best action: that data is discarded at
 * the adapter boundary so it cannot reach a customer (requirement 3.4).
 */
import { config } from './config.js';
import { strings } from './strings.js';

/** @returns {string} a unique client-side message identity */
export function newClientId() {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return `c-${crypto.randomUUID()}`;
  }
  return `c-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
}

/**
 * Build a normalised message. This shape is the contract between transport and
 * UI; every adapter emits it.
 *
 * @param {object} init
 * @param {string|null} [init.id] server id, when available
 * @param {string} [init.clientId]
 * @param {'out'|'in'} init.direction
 * @param {'customer'|'ai'|'human'|'system'} init.author
 * @param {string} init.text
 * @param {Date|string|number} [init.ts]
 * @param {'sending'|'sent'|'read'|'failed'|null} [init.status]
 * @param {string|null} [init.repName]
 * @param {Array<object>} [init.blocks]
 */
export function createMessage({
  id = null,
  clientId,
  direction,
  author,
  text,
  ts,
  status = null,
  repName = null,
  blocks = [],
}) {
  return {
    id,
    clientId: clientId || newClientId(),
    direction,
    author,
    text,
    ts: ts instanceof Date ? ts : new Date(ts ?? Date.now()),
    status,
    repName,
    blocks,
  };
}

/** Deduplication key. Requirement 8.5 depends on this. */
export const messageKey = (message) => message.id ?? message.clientId;

export function createStore() {
  /** @type {Set<Function>} */
  const listeners = new Set();

  const state = {
    customer: { id: config.customer.id, name: config.customer.name },

    /** @type {Array<object>} chronological, append-only */
    messages: [],

    /**
     * clientId -> the same message object held in `messages`.
     * Entries are references, so updating status updates both views of it.
     * Holds messages that are still sending or have failed.
     */
    pending: new Map(),

    assistant: { typing: false, humanTakeover: false, repName: null },

    /** @type {Array<{id: string, label: string}>} */
    quickReplies: [],

    /** @type {'online'|'offline'|'checking'} */
    connection: 'online',

    scroll: { atBottom: true, unread: 0 },

    /** @type {'idle'|'loading'|'error'} */
    history: 'idle',

    /**
     * Detected, never assumed. Populated by the adapter from what the backend
     * actually returns, so a missing backend feature disables itself rather
     * than breaking the UI. See docs/backend-contract.md Part B.
     */
    capabilities: {
      idempotency: false,
      quickReplies: false,
      incrementalFetch: false,
    },
  };

  const notify = () => {
    for (const listener of listeners) listener(state);
  };

  const findByKey = (key) =>
    state.messages.find((message) => messageKey(message) === key);

  /** Append a message unless it is already present (requirement 8.5). */
  const appendUnique = (message) => {
    // A server echo has both a new server id and the optimistic client's id.
    // Comparing only the preferred key would therefore miss the same message
    // during the send/takeover polling race.
    const duplicate = state.messages.some(
      (existing) =>
        (message.id && existing.id === message.id) ||
        (message.clientId && existing.clientId === message.clientId)
    );
    if (duplicate) {
      return false;
    }
    state.messages.push(message);
    return true;
  };

  return {
    getState: () => state,

    /** @param {(state: object) => void} listener @returns {() => void} unsubscribe */
    subscribe(listener) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },

    findByClientId: (clientId) => state.pending.get(clientId) ?? null,

    // ---- History ---------------------------------------------------------

    historyLoading() {
      state.history = 'loading';
      notify();
    },

    /** @param {Array<object>} messages */
    historyLoaded(messages) {
      state.history = 'idle';
      state.messages = [...messages];
      state.pending.clear();
      state.scroll.unread = 0;
      notify();
    },

    historyFailed() {
      state.history = 'error';
      notify();
    },

    // ---- Send flow -------------------------------------------------------

    /**
     * Optimistic send. Pass an existing clientId to retry in place, which
     * reuses the bubble rather than creating a second one (requirement 2.8).
     *
     * @param {{ text: string, clientId?: string }} args
     * @returns {object} the message now in flight
     */
    sendRequested({ text, clientId }) {
      let message = clientId ? state.pending.get(clientId) : null;

      if (message) {
        message.status = 'sending';
        message.ts = new Date();
      } else {
        message = createMessage({
          clientId: clientId || newClientId(),
          direction: 'out',
          author: 'customer',
          text,
          status: 'sending',
        });
        state.messages.push(message);
        state.pending.set(message.clientId, message);
      }

      state.assistant.typing = true;
      state.quickReplies = [];
      notify();
      return message;
    },

    /** HTTP 2xx received: single tick. */
    sendAcknowledged(clientId) {
      const message = state.pending.get(clientId);
      if (message) message.status = 'sent';
      notify();
    },

    /**
     * Second, distinct transition: the reply has rendered, so the outgoing
     * message is treated as read. Keeping this separate from
     * `sendAcknowledged` is what makes the tick semantics real rather than a
     * timer (requirement 2.6).
     */
    markRead(clientId) {
      const message = state.pending.get(clientId);
      if (!message) return;
      message.status = 'read';
      state.pending.delete(clientId);
      notify();
    },

    sendFailed(clientId) {
      const message = state.pending.get(clientId);
      if (message) message.status = 'failed';
      state.assistant.typing = false;
      notify();
    },

    /**
     * Append incoming messages. Increments the unread count when the customer
     * is not at the bottom of the list (requirement 4.2, 4.3).
     *
     * @param {Array<object>} messages
     */
    replyReceived(messages) {
      let appended = 0;
      for (const message of messages) {
        if (appendUnique(message)) appended += 1;
      }
      state.assistant.typing = false;
      if (appended > 0 && !state.scroll.atBottom) {
        state.scroll.unread += appended;
      }
      notify();
    },

    /** @param {Array<{id: string, label: string}>} chips */
    quickRepliesChanged(chips) {
      // Never offer chips while a human owns the conversation (requirement 7.4).
      state.quickReplies = state.assistant.humanTakeover ? [] : chips.slice(0, 3);
      notify();
    },

    // ---- Takeover --------------------------------------------------------

    /**
     * @param {boolean} active
     * @param {string|null} [repName]
     */
    takeoverChanged(active, repName = null) {
      if (state.assistant.humanTakeover === active) {
        if (active && repName && state.assistant.repName !== repName) {
          state.assistant.repName = repName;
          notify();
        }
        return;
      }

      state.assistant.humanTakeover = active;
      state.assistant.repName = active ? repName : null;

      state.messages.push(
        createMessage({
          direction: 'in',
          author: 'system',
          text: active
            ? strings.system.takeoverStarted(repName)
            : strings.system.takeoverEnded,
        })
      );

      if (active) state.quickReplies = [];
      notify();
    },

    /** Restore server state without fabricating a new event in old history. */
    takeoverRestored(active, repName = null) {
      state.assistant.humanTakeover = active;
      state.assistant.repName = active ? repName : null;
      if (active) state.quickReplies = [];
      notify();
    },

    // ---- Connectivity and capabilities -----------------------------------

    /** @param {'online'|'offline'|'checking'} status */
    connectionChanged(status) {
      if (state.connection === status) return;
      state.connection = status;
      notify();
    },

    /** @param {Partial<typeof state.capabilities>} detected */
    capabilitiesDetected(detected) {
      Object.assign(state.capabilities, detected);
      notify();
    },

    // ---- Scrolling -------------------------------------------------------

    /** @param {boolean} atBottom */
    scrollChanged(atBottom) {
      if (state.scroll.atBottom === atBottom) return;
      state.scroll.atBottom = atBottom;
      if (atBottom) state.scroll.unread = 0;
      notify();
    },

    unreadCleared() {
      if (state.scroll.unread === 0) return;
      state.scroll.unread = 0;
      notify();
    },

    // ---- Reset -----------------------------------------------------------

    conversationReset() {
      state.messages = [];
      state.pending.clear();
      state.quickReplies = [];
      state.assistant = { typing: false, humanTakeover: false, repName: null };
      state.scroll = { atBottom: true, unread: 0 };
      state.history = 'idle';
      notify();
    },
  };
}
