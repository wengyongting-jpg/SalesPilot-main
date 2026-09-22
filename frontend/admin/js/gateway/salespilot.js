/**
 * SalesPilot FastAPI transport — STUB.
 *
 * Deliberately not implemented yet. The backend is mid-refactor, and the
 * visibility-tier split in docs/api/interface-v1.md §5.1 moves admin reads to
 * `/api/admin/*`. Writing this adapter against today's paths would bind to
 * endpoints that are about to move, so it waits until interface v1 is frozen.
 *
 * When implemented, this adapter:
 *   - reads the admin surface, keeping the full sales intelligence (the inverse
 *     of the customer adapter, which discards it);
 *   - renames `turns` to `customerMessageCount` on the way in, confining that
 *     misleading name to one line (interface §1.1);
 *   - resolves `role` + `author` into a single `origin` axis once (interface §1.2);
 *   - reports real `capabilities` so the console disables what the backend cannot
 *     do, rather than failing at submit time.
 */

export function createSalesPilotGateway() {
  const notImplemented = () => {
    throw new Error(
      'The SalesPilot admin transport is not implemented yet. Set ' +
        'config.transport to "mock".'
    );
  };

  return {
    name: 'salespilot',

    // Nothing is advertised as available, so every dependent control renders
    // disabled with a stated reason instead of erroring on use.
    capabilities: {
      repReply: false,
      telemetry: false,
      author: false,
      quickReplies: false,
    },

    listConversations: notImplemented,
    getConversation: notImplemented,
    listCases: notImplemented,
    updateCaseStatus: notImplemented,
    listAgentRuns: notImplemented,
    sendRepReply: notImplemented,
    seedDemoData: notImplemented,
    health: async () => false,
  };
}
