/**
 * SalesPilot FastAPI transport.
 *
 * The inverse of the customer adapter: this one keeps the full sales
 * intelligence, because the staff console is the tier entitled to see it
 * (`docs/api/interface-v1.md` §2). It reads the admin surface at
 * `/api/admin/*`, which interface v1 §5.1 defines and which the backend now
 * serves.
 *
 * Three renames happen here and nowhere else, so the misleading wire names are
 * confined to this file:
 *
 *   turns            -> customerMessageCount   (§1.1 — it counts customer messages)
 *   role + author    -> origin                 (§1.2 — one axis for the transcript)
 *   status string    -> status + statusToken   (label to display, token to act on)
 *
 * Everything the views read is normalised to the shapes in
 * `.kiro/specs/admin-console-ui/design.md` § Data models, so no view knows
 * whether it is reading this adapter or the mock.
 */
import { normaliseStatus } from '../format.js';

const STATUS_LABEL = { OPEN: 'Open', TAKEN_OVER: 'Taken Over', CLOSED: 'Closed' };

/** Wire `role`/`author` collapsed to the single axis the transcript renders. */
function toOrigin(wire) {
  if (wire.role === 'customer') return 'customer';
  // An agent-side message with no author predates §5.2 and is AI by definition.
  return wire.author ?? 'ai';
}

function toMessage(wire) {
  return {
    id: wire.id ?? null,
    clientMessageId: wire.client_message_id ?? null,
    role: wire.role,
    origin: toOrigin(wire),
    text: wire.text ?? '',
    ts: new Date(wire.ts),
    repName: wire.rep_name ?? null,
  };
}

function toCase(wire) {
  if (!wire) return null;
  const statusToken = normaliseStatus(wire.status);
  return {
    id: wire.id,
    opportunityId: wire.opportunity_id,
    customerName: wire.customer_name,
    state: wire.state,
    product: wire.product,
    reason: wire.reason,
    summary: wire.summary,
    recommendedAction: wire.recommended_action,
    // `status` is the label a badge renders; `statusToken` is what code acts on.
    status: wire.status ?? STATUS_LABEL[statusToken] ?? statusToken,
    statusToken,
    createdAt: new Date(wire.created_at),
  };
}

function toSummary(wire) {
  return {
    id: wire.opportunity_id,
    name: wire.customer_name,
    score: wire.final_score ?? null,
    priority: wire.priority ?? null,
    state: wire.state,
    product: wire.product,
    humanTakeover: Boolean(wire.human_takeover),
    lastMessagePreview: wire.last_message_preview ?? '',
    // Deliberately `undefined` rather than `null` when absent: `new Date(null)`
    // is the 1970 epoch and would render as a real timestamp.
    lastMessageAt: wire.last_message_at ? new Date(wire.last_message_at) : undefined,
    customerMessageCount: wire.customer_message_count ?? 0,
  };
}

/**
 * The five dimensions the intelligence panel knows how to draw. The backend
 * also reports the two axes separately (`fit`, `behaviour`); those are richer
 * but have no view yet, so they are not invented into this shape.
 */
function toScoreDimensions(score) {
  if (!score) return null;
  return {
    purchase_intent: score.purchase_intent,
    purchase_readiness: score.purchase_readiness,
    product_potential: score.product_potential,
    expansion: score.expansion,
    engagement: score.engagement,
  };
}

function toHistoryEntry(entry) {
  return { ...entry, ts: new Date(entry.ts) };
}

function toOpportunity(wire) {
  return {
    id: wire.opportunity_id,
    name: wire.customer_name,
    state: wire.state,
    product: wire.product,
    priority: wire.priority ?? null,
    score: wire.final_score ?? null,
    scoreDimensions: toScoreDimensions(wire.score),
    signals: wire.signals ?? [],
    signalHistory: wire.signal_history ?? [],
    mainConcern: wire.main_concern ?? null,
    competitiveRisk: Boolean(wire.competitive_risk),
    churnRisk: Boolean(wire.churn_risk),
    complianceRisk: Boolean(wire.compliance_risk),
    // The panel reads `.length` unguarded, so these are always arrays.
    expansion: wire.expansion ?? [],
    humanTakeover: Boolean(wire.human_takeover),
    humanInterventionRequired: Boolean(wire.human_intervention_required),
    customerMessageCount: wire.customer_message_count ?? wire.turns ?? 0,
    scoreHistory: (wire.score_history ?? []).map(toHistoryEntry),
    stateHistory: (wire.state_history ?? []).map(toHistoryEntry),
    nextBestAction: wire.next_best_action
      ? {
          action: wire.next_best_action.action,
          reason: wire.next_best_action.reason,
          priority: wire.next_best_action.priority,
          humanInterventionRequired: Boolean(
            wire.next_best_action.human_intervention_required
          ),
        }
      : null,
  };
}

/** `{ amount, currency }` or `null`. Never `0` — that would claim a measured zero. */
const toCost = (wire) => (wire ? { amount: wire.amount, currency: wire.currency } : null);

/** `content` is omitted, not nulled, when telemetry content is withheld. */
function toContent(wire) {
  if (!wire) return { chars: 0 };
  return typeof wire.content === 'string'
    ? { chars: wire.chars, content: wire.content }
    : { chars: wire.chars };
}

function toRun(wire) {
  const steps = (wire.steps ?? []).map((step) => ({
    index: step.index,
    name: step.name,
    kind: step.kind,
    durationMs: step.duration_ms,
    status: step.status,
  }));
  const llmCalls = (wire.llm_calls ?? []).map((call) => ({
    index: call.index,
    purpose: call.purpose,
    model: call.model,
    durationMs: call.duration_ms,
    promptTokens: call.prompt_tokens,
    completionTokens: call.completion_tokens,
    totalTokens: call.total_tokens,
    cost: toCost(call.cost),
    input: toContent(call.input),
    output: toContent(call.output),
  }));
  const totals = wire.totals ?? {};
  return {
    runId: wire.run_id,
    clientMessageId: wire.client_message_id ?? null,
    trigger: wire.trigger,
    status: wire.status,
    startedAt: new Date(wire.started_at),
    durationMs: wire.duration_ms,
    customerMessageCount: wire.customer_message_count,
    // The console shows this only when the run is degraded; the backend names
    // the offending value in the step detail.
    degradedStep: steps.find((step) => step.status === 'degraded')?.name ?? null,
    steps,
    llmCalls,
    toolCalls: (wire.tool_calls ?? []).map((call) => ({
      index: call.index,
      name: call.name,
      arguments: call.arguments,
      resultChars: call.result_chars,
      durationMs: call.duration_ms,
      status: call.status,
    })),
    totals: {
      agentStepCount: totals.agent_step_count ?? steps.length,
      llmCallCount: totals.llm_call_count ?? llmCalls.length,
      toolCallCount: totals.tool_call_count ?? 0,
      totalTokens: totals.total_tokens ?? 0,
      cost: toCost(totals.cost),
    },
  };
}

export function createSalesPilotGateway(config = {}) {
  const base = (config.apiBase ?? '').replace(/\/$/, '');
  const admin = (path) => `${base}/api/admin${path}`;

  async function request(path, { method = 'GET', body, timeoutMs = 15000 } = {}) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    let response;
    try {
      response = await fetch(path, {
        method,
        headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
        body: body === undefined ? undefined : JSON.stringify(body),
        signal: controller.signal,
      });
    } catch (cause) {
      const error = new Error(`SalesPilot admin transport: ${method} ${path} failed`);
      error.status = 0;
      error.cause = cause;
      throw error;
    } finally {
      clearTimeout(timer);
    }

    if (!response.ok) {
      // interface §4.5: the body is FastAPI's `{"detail": …}`; there is no
      // application error envelope to depend on. `.status` is what callers read.
      let detail = `${method} ${path} -> ${response.status}`;
      try {
        const failure = await response.json();
        if (typeof failure?.detail === 'string') detail = failure.detail;
      } catch {
        /* a non-JSON error body is not itself worth reporting */
      }
      const error = new Error(detail);
      error.status = response.status;
      throw error;
    }
    if (response.status === 204) return null;
    return response.json();
  }

  return {
    name: 'salespilot',

    // What this backend can actually do. Every flag is true because the
    // rebuild serves all of it; an older backend would report fewer and the
    // console would disable those controls rather than fail at submit time.
    capabilities: {
      repReply: true,
      telemetry: true,
      author: true,
      quickReplies: true,
    },

    async listConversations() {
      const payload = await request(admin('/opportunities'));
      return { items: (payload.items ?? []).map(toSummary) };
    },

    async getConversation(id) {
      const payload = await request(admin(`/opportunities/${encodeURIComponent(id)}`));
      return {
        opportunity: toOpportunity(payload),
        messages: (payload.messages ?? []).map(toMessage),
        // The backend embeds the one active case, which is exactly what the
        // console means by "linked": a closed case leaves this null.
        linkedCase: toCase(payload.case),
      };
    },

    async listCases() {
      const payload = await request(admin('/cases'));
      return { items: (payload.items ?? []).map(toCase) };
    },

    async updateCaseStatus(id, statusToken) {
      const payload = await request(admin(`/cases/${encodeURIComponent(id)}`), {
        method: 'PATCH',
        body: { status: normaliseStatus(statusToken) },
      });
      // Bare case, not an envelope: the store replaces list state with it and
      // re-derives takeover from the token the server actually recorded.
      return toCase(payload);
    },

    async listAgentRuns({ opportunityId, clientMessageId } = {}) {
      if (!opportunityId && !clientMessageId) return { items: [] };
      const query = new URLSearchParams();
      if (opportunityId) query.set('opportunity_id', opportunityId);
      if (clientMessageId) query.set('client_message_id', clientMessageId);
      const payload = await request(admin(`/agent-runs?${query}`));
      // The backend returns newest first; the store selects the *last* item as
      // the default, so hand them over oldest first.
      return { items: (payload.items ?? []).map(toRun).reverse() };
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

    async seedDemoData() {
      const payload = await request(admin('/seed'), { method: 'POST' });
      return { seeded: Boolean(payload?.seeded) };
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
