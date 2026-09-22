/**
 * Transport selection.
 *
 * Exactly one adapter is chosen at boot from configuration (requirement 9.1).
 * Every adapter normalises to the same internal message shape, so no view or
 * store code knows which transport is active (requirement 9.2).
 *
 * Adapter interface:
 *
 *   loadHistory(customerId)        -> { messages, humanTakeover }
 *   send({ customerId, customerName, text, clientId })
 *                                  -> { messages, quickReplies, humanTakeover,
 *                                       capabilities }
 *   fetchSince(customerId, cursor) -> { messages }
 *   reset(customerId)              -> void
 *   health()                       -> boolean
 *   name                           -> string
 *
 * `messages` is always "messages to append". The store deduplicates on
 * `id ?? clientId`, so an adapter may include the echoed outgoing message or
 * omit it; both are safe.
 */
import { strings } from '../strings.js';
import { createMockGateway } from './mock.js';
import { createSalesPilotGateway } from './salespilot.js';
import { createWhatsAppGateway } from './whatsapp.js';

/**
 * @param {typeof import('../config.js').config} config
 * @returns {object} the selected adapter
 */
export function createGateway(config) {
  switch (config.transport) {
    case 'mock':
      return createMockGateway(config);
    case 'salespilot':
      return createSalesPilotGateway(config);
    case 'whatsapp':
      return createWhatsAppGateway(config);
    default:
      throw new Error(
        `${strings.errors.unknownTransport} (got "${config.transport}")`
      );
  }
}
