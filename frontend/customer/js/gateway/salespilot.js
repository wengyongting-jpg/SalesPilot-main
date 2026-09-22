/**
 * SalesPilot FastAPI transport.
 *
 * STUB — implemented in customer-chat-ui task 4. It exists now so the transport
 * selector in index.js resolves for every configured value.
 *
 * When implemented this adapter maps `POST /api/messages` onto the gateway
 * interface and, critically, DISCARDS the sales intelligence at this boundary:
 * `score`, `priority`, `signals`, `state`, `next_best_action` and `case` must
 * never travel further into the app, so internal scoring cannot leak into a
 * customer-facing view (requirement 3.4). See
 * .kiro/specs/customer-chat-ui/design.md for the full field mapping, and
 * docs/backend-contract.md for the API reference.
 */

export function createSalesPilotGateway() {
  const notImplemented = () => {
    throw new Error(
      'The SalesPilot transport is not implemented yet (task 4). Set ' +
        'config.transport to "mock".'
    );
  };

  return {
    name: 'salespilot',
    loadHistory: notImplemented,
    send: notImplemented,
    fetchSince: notImplemented,
    reset: notImplemented,
    health: async () => false,
  };
}
