/**
 * SalesPilot backend transport — admin tier.
 *
 * The inverse of the customer adapter: this side keeps the full sales
 * intelligence, including model telemetry.
 *
 *   GET    /api/admin/opportunities[?history_limit=]
 *   GET    /api/admin/opportunities/{id}[?since=&history_limit=]
 *   GET    /api/admin/opportunities/{id}/cost
 *   POST   /api/admin/opportunities/{id}/rep-reply
 *   GET    /api/admin/cases
 *   PATCH  /api/admin/cases/{id}
 *   GET    /api/admin/agent-runs?opportunity_id=[&client_message_id=&limit=]
 *   GET    /api/admin/agent-runs/{run_id}
 *   GET    /api/admin/analytics
 *   GET    /api/admin/dashboard
 *   POST   /api/admin/seed
 *
 * Verified against a live `py -3 -m backend --serve --seed` on 2026-09-22.
 *
 * Three things the wire does differently from the earlier draft, each handled
 * here so no view has to know:
 *
 * 1. **`role` is `"business"`, not `"agent"`.** `author` refines it into
 *    `ai` / `human` / `system`, and `generation` records whether a model was
 *    involved at all.
 * 2. **The score is two-axis.** Fit and behaviour are separate totals and
 *    `score.total` is explicitly display-only — ranking comes from `priority`,
 *    which the kernel derives from a matrix rather than a threshold on a number.
 * 3. **`agent-runs` requires `opportunity_id` and returns newest first.** The
 *    store expects oldest first, so the list is reversed on the way in.
 */
import { normaliseStatus } from '../format.js';

/* ==========================================================================
   Normalisation
   ========================================================================== */

const originOf = (wire) =>
  wire.role === 'customer' ? 'customer' : wire.author ?? 'ai';

/** One transcript entry. `generation` is carried so the console can say whether
 *  a model produced the wording — a template reply involved none. */
const toMessage = (wire) => ({
  id: wire.id,
  clientMessageId: wire.client_message_id ?? null,
  role: wire.role,
  origin: originOf(wire),
  generation: wire.generation ?? null,
  text: wire.text ?? '',
  ts: wire.ts ? new Date(wire.ts) : null,
  repName: wire.rep_name ?? null,
});

/**
 * The two-axis score card.
 *
 * Kept as the backend's own decomposition rather than flattened: the point of the
 * redesign is that a reviewer can take a headline apart, and "behaviour 82"
 * is not reviewable while "raw 82, recency 100%" is.
 */
const toScore = (score) =>
  score
    ? {
        fit: {
          needIdentified: score.need_identified,
          productPotential: score.product_potential,
          expansion: score.expansion,
          total: score.fit_total,
        },
        behaviour: {
          purchaseIntent: score.purchase_intent,
          purchaseReadiness: score.purchase_readiness,
          engagement: score.engagement,
          engagementDepth: score.engagement_depth,
          engagementUrgency: score.engagement_urgency,
          engagementRecency: score.engagement_recency,
          raw: score.behaviour_raw,
          total: score.behaviour_total,
        },
        // Display only. Never used for ordering — see `priority`.
        total: score.total,
        priority: score.priority,
      }
    : null;

const toOpportunity = (wire) => ({
  id: wire.opportunity_id,
  name: wire.customer_name,
  state: wire.state,
  product: wire.product,
  priority: wire.priority,
  finalScore: wire.final_score,
  score: toScore(wire.score),
  qualification: wire.qualification,
  qualificationReason: wire.qualification_reason,
  signals: wire.signals ?? [],
  signalHistory: wire.signal_history ?? [],
  mainConcern: wire.main_concern,
  competitiveRisk: wire.competitive_risk,
  churnRisk: wire.churn_risk,
  complianceRisk: wire.compliance_risk,
  expansion: wire.expansion ?? [],
  humanTakeover: wire.human_takeover,
  humanInterventionRequired: wire.human_intervention_required,
  pendingHandoffReason: wire.pending_handoff_reason ?? null,
  // The truthful name. `turns` is the deprecated alias and is deliberately not
  // read anywhere in this app — interface-v1.md §1.1.
  customerMessageCount: wire.customer_message_count,
  scoreHistory: (wire.score_history ?? []).map((entry) => ({
    ts: entry.ts ? new Date(entry.ts) : null,
    score: entry.score,
    state: entry.state,
    trigger: entry.trigger,
    evidence: entry.evidence ?? null,
  })),
  stateHistory: (wire.state_history ?? []).map((entry) => ({
    ts: entry.ts ? new Date(entry.ts) : null,
    from: entry.from,
    to: entry.to,
    reason: entry.reason,
  })),
  createdAt: wire.created_at ? new Date(wire.created_at) : null,
  updatedAt: wire.updated_at ? new Date(wire.updated_at) : null,
});

/** An inbox row. */
const toSummary = (wire) => {
  const messages = wire.messages ?? [];
  const last = messages[messages.length - 1];
  return {
    id: wire.opportunity_id,
    name: wire.customer_name,
    score: wire.final_score,
    priority: wire.priority,
    state: wire.state,
    product: wire.product,
    qualification: wire.qualification,
    humanTakeover: wire.human_takeover,
    lastMessagePreview: last ? last.text : '',
    lastMessageAt: last?.ts ? new Date(last.ts) : null,
    customerMessageCount: wire.customer_message_count,
    reason: wire.attention_reason ?? null,
    keywords: wire.signals?.slice(0, 5) ?? [],
  };
};

const toCase = (wire) => ({
  id: wire.id,
  opportunityId: wire.opportunity_id,
  customerName: wire.customer_name,
  state: wire.state,
  product: wire.product,
  reason: wire.reason,
  summary: wire.summary,
  recommendedAction: wire.recommended_action,
  status: wire.status,
  statusToken: normaliseStatus(wire.status),
  priority: wire.priority ?? null,
  score: wire.score ?? null,
  keywords: wire.keywords ?? [],
  createdAt: wire.created_at ? new Date(wire.created_at) : null,
});

/**
 * One agent run.
 *
 * `cost.pricing_known` matters: with no model configured the backend reports a
 * genuine zero rather than an unknown, and the console must show those
 * differently. A run with no model calls is not a measurement failure.
 */
/**
 * Turn an error body into one line of text.
 *
 * `detail` is a string for the backend's own errors, but FastAPI's validation
 * failures (422) send an array of objects. Passing that straight to `new Error`
 * produced the literal string "[object Object]", which the case-transition and
 * reply error banners would then show to an operator.
 *
 * Duplicated from `frontend/customer/js/gateway/salespilot.js` — the two apps are
 * deliberately self-contained (see `docs/v0.0/conventions/tech.md`).
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

/**
 * Cost is the one wire object that was passed through raw, which meant
 * `pricing_known` never reached `format.cost` in the camelCase shape it reads.
 * Normalised here like every other field, and the distinction is preserved:
 * absent cost stays `null`, an unpriced model keeps its amount *and* its
 * `pricingKnown: false`.
 */
const toCost = (wire) =>
  wire
    ? {
        amount: wire.amount ?? null,
        currency: wire.currency ?? 'USD',
        pricingKnown: wire.pricing_known ?? true,
      }
    : null;

const toRun = (wire) => ({
  runId: wire.run_id,
  opportunityId: wire.opportunity_id,
  clientMessageId: wire.client_message_id ?? null,
  trigger: wire.trigger,
  status: wire.status,
  startedAt: wire.started_at ? new Date(wire.started_at) : null,
  finishedAt: wire.finished_at ? new Date(wire.finished_at) : null,
  durationMs: wire.duration_ms,
  customerMessageCount: wire.customer_message_count,
  steps: (wire.steps ?? []).map((step) => ({
    index: step.index,
    name: step.name,
    kind: step.kind,
    durationMs: step.duration_ms,
    status: step.status,
    detail: step.detail ?? null,
  })),
  llmCalls: (wire.llm_calls ?? []).map((call) => ({
    index: call.index,
    purpose: call.purpose,
    model: call.model,
    durationMs: call.duration_ms,
    promptTokens: call.prompt_tokens,
    completionTokens: call.completion_tokens,
    totalTokens: call.total_tokens,
    cost: toCost(call.cost),
    input: call.input ?? null,
    output: call.output ?? null,
  })),
  // Empty until a real tool-calling loop runs. Never populated from retrieval
  // steps — interface-v1.md §1.1 rule 2.
  toolCalls: wire.tool_calls ?? [],
  // Model contract violations: a value the domain refused. Worth surfacing,
  // because the old build downgraded these silently.
  violations: wire.violations ?? [],
  totals: {
    agentStepCount: wire.totals?.agent_step_count ?? 0,
    llmCallCount: wire.totals?.llm_call_count ?? 0,
    toolCallCount: wire.totals?.tool_call_count ?? 0,
    totalTokens: wire.totals?.total_tokens ?? 0,
    cost: toCost(wire.totals?.cost),
  },
  // A run fetched from the backend is a real measurement, never synthesised.
  simulated: false,
});

/* ==========================================================================
   Adapter
   ========================================================================== */

export function createSalesPilotGateway(config) {
  const base = (config.apiBase || '').replace(/\/$/, '');
  const admin = (path) => `${base}/api/admin${path}`;
  const debugExchanges = [];
  const secretField = /^(api[_-]?key|password|secret|access[_-]?token|refresh[_-]?token|authorization|cookie)$/i;
  const redactDebug = (value) => {
    if (Array.isArray(value)) return value.map(redactDebug);
    if (value && typeof value === 'object') {
      return Object.fromEntries(
        Object.entries(value).map(([key, item]) => [
          key, secretField.test(key) ? '[redacted]' : redactDebug(item),
        ])
      );
    }
    return value;
  };

  async function request(path, { method = 'GET', body, timeoutMs = 15000 } = {}) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    const startedAt = performance.now();
    const record = { method, path, requestBody: redactDebug(body ?? null), status: 0, responseBody: null, durationMs: 0 };
    try {
      const response = await fetch(path, {
        method,
        headers: body ? { 'Content-Type': 'application/json' } : undefined,
        body: body ? JSON.stringify(body) : undefined,
        signal: controller.signal,
      });
      const payload = await response.json().catch(() => null);
      record.status = response.status;
      record.responseBody = redactDebug(payload);
      if (!response.ok) {
        const error = new Error(
          describeError(payload, `${method} ${path} failed with ${response.status}`)
        );
        error.status = response.status;
        throw error;
      }
      return payload;
    } catch (error) {
      if (error.name === 'AbortError') {
        const timeout = new Error(`${method} ${path} timed out`);
        timeout.status = 0;
        throw timeout;
      }
      if (error.status === undefined) error.status = 0;
      throw error;
    } finally {
      clearTimeout(timer);
      record.durationMs = Math.round(performance.now() - startedAt);
      debugExchanges.unshift(record);
      if (debugExchanges.length > 30) debugExchanges.length = 30;
    }
  }

  return {
    name: 'salespilot',
    getDebugExchanges: () => [...debugExchanges],

    // Everything the console needs is now live. `author` landed as its own axis,
    // so the transcript can distinguish an AI reply from a representative's.
    capabilities: {
      repReply: true,
      telemetry: true,
      author: true,
      quickReplies: true,
    },

    async listConversations() {
      // The dashboard endpoint is intentionally lightweight: it carries only the
      // latest message and omits score/state history arrays.
      const payload = await request(admin('/dashboard'));
      return { items: (payload.items ?? []).map(toSummary), held: payload.held ?? 0 };
    },

    async getConversation(id) {
      const payload = await request(
        admin(`/opportunities/${encodeURIComponent(id)}`)
      );
      const opportunity = toOpportunity(payload);
      const messages = (payload.messages ?? []).map(toMessage);

      // One active case per opportunity, so the non-closed one is unambiguous.
      // Looked up unconditionally rather than only when `humanTakeover` is set:
      // the two facts can disagree (item 14 in docs/v0.0/backend/backend-contract.md), and it
      // is the disagreement the composer needs to see in order to explain it.
      const cases = await request(admin('/cases'));
      const linkedCase =
        (cases.items ?? [])
          .map(toCase)
          .find((c) => c.opportunityId === id && c.statusToken !== 'CLOSED') ?? null;

      return { opportunity, messages, linkedCase };
    },

    async listCases() {
      const payload = await request(admin('/cases'));
      return { items: (payload.items ?? []).map(toCase) };
    },

    async updateCaseStatus(id, statusToken) {
      const payload = await request(admin(`/cases/${encodeURIComponent(id)}`), {
        method: 'PATCH',
        body: { status: statusToken },
      });
      return toCase(payload);
    },

    /**
     * `opportunity_id` is required by the endpoint, so the harness must pass it
     * alongside the correlation key rather than querying by key alone.
     */
    async listAgentRuns({ opportunityId, clientMessageId, limit } = {}) {
      if (!opportunityId) return { items: [] };

      const query = new URLSearchParams({ opportunity_id: opportunityId });
      if (clientMessageId) query.set('client_message_id', clientMessageId);
      if (limit) query.set('limit', String(limit));

      const payload = await request(admin(`/agent-runs?${query.toString()}`));
      // The endpoint returns newest first; the store renders oldest first.
      return { items: (payload.items ?? []).map(toRun).reverse() };
    },

    async getConversationCost(id) {
      const payload = await request(
        admin(`/opportunities/${encodeURIComponent(id)}/cost`)
      );
      return {
        opportunityId: payload.opportunity_id,
        runCount: payload.run_count,
        totalTokens: payload.total_tokens,
        cost: toCost(payload.cost),
      };
    },

    async sendRepReply({ id, text, repName, clientMessageId }) {
      const payload = await request(
        admin(`/opportunities/${encodeURIComponent(id)}/rep-reply`),
        {
          method: 'POST',
          body: { text, rep_name: repName, client_message_id: clientMessageId },
        }
      );
      return { message: toMessage(payload.message) };
    },

    async generateStaffBrief(id) {
      return request(admin(`/opportunities/${encodeURIComponent(id)}/brief`), {
        method: 'POST',
      });
    },

    async seedDemoData() {
      const payload = await request(admin('/seed'), { method: 'POST' });
      return { seeded: true, ...payload };
    },

    async analytics() {
      return request(admin('/analytics'));
    },

    async health() {
      try {
        const payload = await request(`${base}/health`, { timeoutMs: 5000 });
        return payload?.status === 'ok';
      } catch {
        return false;
      }
    },
  };
}
