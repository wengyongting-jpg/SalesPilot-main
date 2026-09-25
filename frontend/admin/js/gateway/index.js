/**
 * Transport selection for the admin console.
 *
 * One adapter chosen at boot from configuration. Every adapter normalises to the
 * shapes in docs/v0.0/frontend/admin-console-ui/design.md § Data models, so no view or
 * store code knows which transport is active.
 *
 * Adapter interface:
 *
 *   listConversations()                     -> { items: ConversationSummary[] }
 *   getConversation(id)                     -> { opportunity, messages, linkedCase }
 *   listCases()                             -> { items: Case[] }
 *   updateCaseStatus(id, statusToken)       -> Case
 *   listAgentRuns({ opportunityId, clientMessageId }) -> { items: AgentRun[] }
 *   sendRepReply({ id, text, repName, clientMessageId }) -> { message }
 *   seedDemoData()                          -> { seeded: boolean }
 *   health()                                -> boolean
 *   name
 *   capabilities  -> { repReply, telemetry, author, quickReplies }
 *
 * `capabilities` is how the console degrades rather than breaks. A false flag
 * disables the dependent control with a stated reason; it is never an error.
 */
import { createMockGateway } from './mock.js';
import { createSalesPilotGateway } from './salespilot.js';

export function createGateway(config) {
  switch (config.transport) {
    case 'mock':
      return createMockGateway({ latencyScale: config.mockLatencyScale });
    case 'salespilot':
      return createSalesPilotGateway(config);
    default:
      throw new Error(`Unknown admin transport: "${config.transport}"`);
  }
}
