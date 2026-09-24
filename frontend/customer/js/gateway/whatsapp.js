/**
 * WhatsApp Cloud API transport — SHAPE-ONLY STUB.
 *
 * Intentionally not implemented. The seam exists so the same UI can serve a real
 * WhatsApp transport later; the payload shapes are recorded below so a future
 * implementation has a target. Nothing here pretends to work: selecting this
 * transport fails loudly at boot rather than showing a blank screen
 * (requirement 9.4).
 *
 * Inbound webhook (abridged):
 *   entry[].changes[].value.messages[] = [
 *     { id, from, timestamp, type: 'text', text: { body } }
 *   ]
 *   Mapping to our normalised message:
 *     id            -> id
 *     from          -> customer.id
 *     timestamp (s) -> ts        (multiply by 1000)
 *     text.body     -> text
 *     (constant)    -> direction 'in', author 'customer'
 *
 * Outbound send:
 *   POST /{phone-number-id}/messages
 *   { messaging_product: 'whatsapp', to, type: 'text', text: { body } }
 *
 * Delivery status arrives as separate webhook events rather than on the send
 * response:
 *   entry[].changes[].value.statuses[] = [{ id, status, timestamp }]
 *   status: 'sent' | 'delivered' | 'read'  ->  our message.status
 *
 * Note the difference from the SalesPilot backend: WhatsApp issues real delivery
 * receipts, so a future implementation could drive ticks from server events
 * instead of the client-observed milestones documented in
 * docs/v0.0/backend/backend-contract.md Part B item 5.
 *
 * TODO(customer-chat-ui task 6): complete the documented stub. Implementation of
 * real sending is out of scope for this project.
 */
import { strings } from '../strings.js';

export function createWhatsAppGateway() {
  const notImplemented = () => {
    throw new Error(strings.errors.whatsappNotImplemented);
  };

  return {
    name: 'whatsapp',
    loadHistory: notImplemented,
    send: notImplemented,
    fetchSince: notImplemented,
    reset: notImplemented,
    health: async () => false,
  };
}
