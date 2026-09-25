/**
 * SalesPilot backend transport — customer tier.
 *
 * Maps the three customer endpoints onto the gateway interface:
 *
 *   POST   /api/messages
 *   GET    /api/conversations/{id}[?since=]
 *   DELETE /api/conversations/{id}
 *
 * **There is no sales intelligence to discard here any more.** The earlier design
 * had this adapter strip `score`, `priority`, `signals`, `state`,
 * `next_best_action` and `case` from the response, because the old backend sent
 * them to whoever asked. The rebuilt backend enforces the boundary server-side
 * with a typed projection that has no field for them
 * (`docs/v0.0/api/interface-v1.md` §2), so the customer response cannot carry them.
 * `assertNoIntelligence` below verifies that at runtime rather than trusting it:
 * if a future change widens the surface, this logs loudly instead of quietly
 * rendering internal data to a customer.
 *
 * Verified against a live `py -3 -m backend --serve --seed` on 2026-09-22.
 */
import { createMessage } from '../store.js';

/** Keys that must never appear on a customer-tier payload. */
const FORBIDDEN_KEYS = [
  'score',
  'priority',
  'signals',
  'signal_history',
  'state',
  'next_best_action',
  'case',
  'detection',
  'retrieval',
  'opportunity',
  'agent_run',
  'qualification',
  'final_score',
];

/**
 * The tier boundary belongs to the backend, but a frontend that silently renders
 * whatever arrives is no safeguard at all. This does not filter — filtering would
 * hide a regression. It reports one.
 */
function assertNoIntelligence(payload) {
  const leaked = FORBIDDEN_KEYS.filter((key) => key in payload);
  if (leaked.length > 0) {
    console.error(
      '[customer-chat] the customer surface returned sales intelligence, which is ' +
        'a backend tier-boundary regression. Keys: ' +
        leaked.join(', ')
    );
  }
  return payload;
}

/**
 * A customer message is `role: "customer"`; anything from the business side is
 * `role: "business"` — not `"agent"`, which is what an earlier draft of the
 * interface assumed. `author` refines the business side into `ai` / `human` /
 * `system` and is null on the customer's own messages.
 */
const directionOf = (message) => (message.role === 'customer' ? 'out' : 'in');
const authorOf = (message) =>
  message.role === 'customer' ? 'customer' : message.author ?? 'ai';

/**
 * Normalise one wire message into the store's internal shape.
 *
 * Messages already stored server-side are, by definition, delivered: an outgoing
 * one is marked `read` so a reloaded transcript does not show a stack of pending
 * clocks. Incoming messages carry no tick state at all.
 */
function toMessage(wire) {
  return createMessage({
    id: wire.id ?? null,
    clientId: wire.client_message_id ?? undefined,
    direction: directionOf(wire),
    author: authorOf(wire),
    text: wire.text ?? '',
    ts: wire.ts ?? Date.now(),
    status: directionOf(wire) === 'out' ? 'read' : null,
    repName: wire.rep_name ?? null,
  });
}

/** The representative's name, when a human wrote the most recent reply. */
const repNameOf = (wire) => (wire && wire.author === 'human' ? wire.rep_name ?? null : null);

/**
 * Turn an error body into one line of text.
 *
 * `detail` is a string for the backend's own errors, but FastAPI's validation
 * failures (422) send an array of objects. Passing that straight to `new Error`
 * produced the literal string "[object Object]" — an error message that tells
 * nobody anything.
 */
function describeError(payload, fallback) {
  const detail = payload?.detail;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    const messages = detail
      .map((entry) => {
        if (typeof entry === 'string') return entry;
        const field = Array.isArray(entry?.loc) ? entry.loc.at(-1) : null;
        return [field, entry?.msg].filter(Boolean).join(': ');
      })
      .filter(Boolean);
    if (messages.length) return messages.join('; ');
  }
  return fallback;
}

export function createSalesPilotGateway(config) {
  const base = (config.apiBase || '').replace(/\/$/, '');
  const url = (path) => `${base}${path}`;

  /**
   * One fetch with a timeout budget. Errors carry `.status` so the telemetry
   * channel can report the real HTTP code rather than a guess.
   */
  async function request(path, { method = 'GET', body, timeoutMs } = {}) {
    const controller = new AbortController();
    const budget = timeoutMs ?? config.sendTimeoutMs ?? 30000;
    const timer = setTimeout(() => controller.abort(), budget);

    try {
      const response = await fetch(url(path), {
        method,
        headers: body ? { 'Content-Type': 'application/json' } : undefined,
        body: body ? JSON.stringify(body) : undefined,
        signal: controller.signal,
      });

      const payload = await response.json().catch(() => null);

      if (!response.ok) {
        const error = new Error(
          describeError(payload, `${method} ${path} failed with ${response.status}`)
        );
        error.status = response.status;
        throw error;
      }
      return { status: response.status, payload };
    } catch (error) {
      if (error.name === 'AbortError') {
        const timeout = new Error(`${method} ${path} timed out after ${budget}ms`);
        timeout.status = 0;
        throw timeout;
      }
      if (error.status === undefined) error.status = 0;
      throw error;
    } finally {
      clearTimeout(timer);
    }
  }

  return {
    name: 'salespilot',

    async loadHistory(customerId) {
      try {
        const { payload } = await request(
          `/api/conversations/${encodeURIComponent(customerId)}`
        );
        assertNoIntelligence(payload);
        const messages = (payload.messages ?? []).map(toMessage);
        const latestHuman = messages.findLast((message) => message.author === 'human');
        return {
          messages,
          quickReplies: payload.quick_replies ?? [],
          question: payload.customer_question ?? null,
          humanTakeover: Boolean(payload.human_takeover),
          repName: latestHuman?.repName ?? null,
          capabilities: {
            idempotency: true,
            quickReplies: true,
            incrementalFetch: true,
          },
        };
      } catch (error) {
        // A customer who has never written has no conversation yet. That is the
        // ordinary first-run case, not a failure, so it must not surface as an
        // error state over an empty chat.
        if (error.status === 404) {
          return {
            messages: [],
            quickReplies: [],
            question: null,
            humanTakeover: false,
            repName: null,
            capabilities: {
              idempotency: true,
              quickReplies: true,
              incrementalFetch: true,
            },
          };
        }
        throw error;
      }
    },

    async send({ customerId, customerName, text, clientId }) {
      // The request model is `extra="forbid"`, so exactly these four keys.
      const { status, payload } = await request('/api/messages', {
        method: 'POST',
        body: {
          customer_id: customerId,
          customer_name: customerName,
          text,
          client_message_id: clientId,
        },
      });

      assertNoIntelligence(payload);

      // `message` is the business-side reply. The customer's own message is
      // already on screen optimistically, and the server echoes their key at the
      // top level rather than on the reply.
      const replyWire = payload.message;
      const messages = replyWire
        ? [toMessage(replyWire)]
        : [
            // Defensive: if a future build omits the message object, the reply
            // text is still the thing the customer must see.
            createMessage({
              direction: 'in',
              author: payload.human_takeover ? 'human' : 'ai',
              text: payload.reply ?? '',
            }),
          ];

      return {
        status,
        messages,
        quickReplies: payload.quick_replies ?? [],
        question: payload.customer_question ?? null,
        humanTakeover: Boolean(payload.human_takeover),
        repName: repNameOf(replyWire),
        // Facts are returned for the product card in customer task 5. They are
        // deliberately not turned into a card here: the backend's reply text
        // already embeds them, so rendering both would duplicate the content.
        facts: payload.facts ?? [],
        capabilities: {
          idempotency: true,
          quickReplies: true,
          incrementalFetch: true,
        },
      };
    },

    async fetchSince(customerId, cursor) {
      const query = cursor ? `?since=${encodeURIComponent(cursor)}` : '';
      const { payload } = await request(
        `/api/conversations/${encodeURIComponent(customerId)}${query}`
      );
      assertNoIntelligence(payload);
      const messages = (payload.messages ?? []).map(toMessage);
      const latestHuman = messages.findLast((message) => message.author === 'human');
      return {
        messages,
        humanTakeover: Boolean(payload.human_takeover),
        repName: latestHuman?.repName ?? null,
      };
    },

    async reset(customerId) {
      await request(`/api/conversations/${encodeURIComponent(customerId)}`, {
        method: 'DELETE',
      });
    },

    async health() {
      try {
        const { payload } = await request('/health', { timeoutMs: 5000 });
        return payload?.status === 'ok';
      } catch {
        return false;
      }
    },
  };
}
