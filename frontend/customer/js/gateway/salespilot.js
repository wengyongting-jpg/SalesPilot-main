/**
 * SalesPilot FastAPI transport.
 *
 * Maps the customer tier of `docs/api/interface-v1.md` §5.1 onto the gateway
 * interface in index.js:
 *
 *   POST   /api/messages              -> send()
 *   GET    /api/conversations/{id}    -> loadHistory(), fetchSince(cursor)
 *   DELETE /api/conversations/{id}    -> reset()
 *   GET    /health                    -> health()
 *
 * There is nothing to discard at this boundary any more. The backend's customer
 * schema has no field for `score`, `priority`, `signals`, `state`,
 * `next_best_action`, `case` or telemetry (requirement 3.4 is now enforced
 * server-side by payload shape), so this adapter maps what arrives rather than
 * filtering what must not. If a future response did carry one of those keys,
 * this adapter would still not forward it: it names every field it reads.
 *
 * Capabilities are detected, never assumed — an older backend simply reports
 * fewer of them and the UI disables those paths.
 */
import { createMessage } from '../store.js';

/** Business-side `author` values the backend may send, mapped to store authors. */
const AUTHOR = { ai: 'ai', human: 'human', system: 'system' };

/**
 * One wire message -> one store message.
 *
 * `direction` is viewer-relative and therefore internal to this app: the wire
 * says `role: "customer" | "business"` (interface §1.2) and the store says
 * out/in.
 */
function toMessage(wire) {
  const fromCustomer = wire.role === 'customer';
  return createMessage({
    id: wire.id ?? null,
    clientId: wire.client_message_id ?? undefined,
    direction: fromCustomer ? 'out' : 'in',
    author: fromCustomer ? 'customer' : (AUTHOR[wire.author] ?? 'ai'),
    text: wire.text ?? '',
    ts: wire.ts,
    status: fromCustomer ? 'read' : null,
  });
}

function toQuickReplies(wire) {
  if (!Array.isArray(wire)) return [];
  return wire
    .filter((chip) => chip && typeof chip.id === 'string' && typeof chip.label === 'string')
    .map((chip) => ({ id: chip.id, label: chip.label }));
}

export function createSalesPilotGateway(config = {}) {
  const base = (config.apiBase ?? '').replace(/\/$/, '');
  const url = (path) => `${base}${path}`;
  const sendTimeoutMs = config.sendTimeoutMs ?? 30000;

  /**
   * One fetch, with a timeout and an error carrying `.status` so the caller can
   * tell a rejected request from an unreachable server (main.js reads it).
   */
  async function request(path, { method = 'GET', body, timeoutMs = 10000 } = {}) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    let response;
    try {
      response = await fetch(url(path), {
        method,
        headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
        body: body === undefined ? undefined : JSON.stringify(body),
        signal: controller.signal,
      });
    } catch (cause) {
      const error = new Error(`SalesPilot transport: ${method} ${path} failed`);
      error.status = 0;
      error.cause = cause;
      throw error;
    } finally {
      clearTimeout(timer);
    }

    if (!response.ok) {
      const error = new Error(`SalesPilot transport: ${method} ${path} -> ${response.status}`);
      error.status = response.status;
      throw error;
    }
    if (response.status === 204) return null;
    return response.json();
  }

  const conversation = (customerId) =>
    `/api/conversations/${encodeURIComponent(customerId)}`;

  return {
    name: 'salespilot',

    async loadHistory(customerId) {
      // A conversation that has not started yet is not an error: the backend
      // has no opportunity for this id until the first message.
      let payload;
      try {
        payload = await request(conversation(customerId));
      } catch (error) {
        if (error.status === 404) return { messages: [], humanTakeover: false };
        throw error;
      }
      return {
        messages: (payload.messages ?? []).map(toMessage),
        humanTakeover: Boolean(payload.human_takeover),
      };
    },

    async send({ customerId, customerName, text, clientId }) {
      const payload = await request('/api/messages', {
        method: 'POST',
        timeoutMs: sendTimeoutMs,
        body: {
          customer_id: customerId,
          customer_name: customerName,
          text,
          client_message_id: clientId,
        },
      });

      const reply = createMessage({
        direction: 'in',
        author: payload.generation === 'human' ? 'human' : 'ai',
        text: payload.reply ?? '',
      });

      return {
        status: 200,
        messages: [reply],
        quickReplies: toQuickReplies(payload.quick_replies),
        humanTakeover: Boolean(payload.human_takeover),
        capabilities: {
          // Detected from what actually came back, per the store's comment.
          idempotency: payload.client_message_id === clientId,
          quickReplies: Array.isArray(payload.quick_replies),
          incrementalFetch: true,
        },
      };
    },

    async fetchSince(customerId, cursor) {
      const path = cursor
        ? `${conversation(customerId)}?since=${encodeURIComponent(cursor)}`
        : conversation(customerId);
      let payload;
      try {
        payload = await request(path);
      } catch (error) {
        // A cursor the backend rejects (400) must not wedge polling; fall back
        // to no new messages and let the next poll re-cursor.
        if (error.status === 404 || error.status === 400) return { messages: [] };
        throw error;
      }
      return { messages: (payload.messages ?? []).map(toMessage) };
    },

    async reset(customerId) {
      await request(conversation(customerId), { method: 'DELETE' });
    },

    async health() {
      try {
        const payload = await request('/health', { timeoutMs: 5000 });
        return payload?.status === 'ok';
      } catch {
        return false;
      }
    },
  };
}
