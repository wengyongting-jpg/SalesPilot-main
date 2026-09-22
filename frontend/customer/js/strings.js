/**
 * Every user-facing string in the customer chat (requirement 11.2).
 *
 * English only. Keeping them in one module is what makes translation possible
 * later without touching view code.
 *
 * No backend detail, status code or stack trace is ever surfaced to a customer:
 * there is one generic message per class of failure, and diagnostics go to the
 * console instead.
 */
import { config } from './config.js';

const business = config.business.name;

export const strings = {
  documentTitle: `${business} — Chat`,

  header: {
    /** Presence line while the AI is handling the conversation. */
    aiOnline: `${config.assistant.label} · online`,
    typing: 'typing…',
    /** @param {string} name representative name, when known */
    human: (name) =>
      `${name || 'Representative'} · ${business} representative`,
    menuLabel: 'Conversation options',
    resetLabel: 'Reset conversation',
  },

  list: {
    ariaLabel: `Conversation with ${business}`,
  },

  empty: {
    title: business,
    body:
      'Hi! I can help with plan information, coverage, eligibility and how to ' +
      'apply. Send a message to get started.',
  },

  loading: {
    ariaLabel: 'Loading conversation',
  },

  historyError: {
    body: 'We could not load this conversation.',
    action: 'Try again',
  },

  composer: {
    placeholder: 'Type a message',
    inputLabel: 'Message',
    sendLabel: 'Send message',
    micLabel: 'Voice messages are not available',
  },

  message: {
    retryLabel: 'Retry sending message',
    /** Used while backend idempotency is unavailable (requirement 2.10). */
    retryDuplicateWarning:
      'Retrying may deliver this message twice, because the server cannot yet ' +
      'detect duplicates.',
    statusSending: 'Sending',
    statusSent: 'Sent',
    statusRead: 'Read',
    statusFailed: 'Not delivered',
  },

  separator: {
    today: 'Today',
    yesterday: 'Yesterday',
  },

  jump: {
    label: 'Jump to latest message',
    /** @param {number} n unread incoming messages */
    unreadLabel: (n) => `${n} unread message${n === 1 ? '' : 's'}`,
  },

  banner: {
    offline: 'You are offline. Messages will not send until you reconnect.',
    handoff: `A ${business} representative is handling this conversation.`,
  },

  system: {
    /** @param {string} name representative name, when known */
    takeoverStarted: (name) =>
      `${name || 'A representative'} from ${business} has joined and is now ` +
      'handling your conversation.',
    takeoverEnded: `You are chatting with the ${config.assistant.label} again.`,
  },

  errors: {
    sendFailed: 'Message not delivered.',
    whatsappNotImplemented:
      'The WhatsApp transport is not implemented. Set config.transport to ' +
      '"mock" or "salespilot".',
    unknownTransport: 'Unknown transport configured.',
  },
};
