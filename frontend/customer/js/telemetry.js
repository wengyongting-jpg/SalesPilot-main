/**
 * Harness telemetry channel — Plane B of docs/v0.0/api/interface-v1.md §3.
 *
 * Active **only** when this app runs inside an iframe. Standalone, every method
 * is a no-op and nothing is ever posted anywhere (requirement 6.10): a customer
 * running the real app must not emit diagnostics to anyone.
 *
 * What travels on this channel is deliberately tiny and non-sensitive: a
 * correlation id, a client-observed duration, a status, and a few counters. It
 * carries **no** agent telemetry, because under interface §2 the customer surface
 * has no shape for that data — this app never receives it in the first place. The
 * console fetches the agent run itself, joining on `clientMessageId`.
 *
 * Security: an explicit target origin, never `*`. Inbound messages are checked
 * for origin and for the expected source tag before being acted on.
 */
const OUTBOUND_SOURCE = 'salespilot-customer';
const INBOUND_SOURCE = 'salespilot-admin';

const noop = () => {};

/** @returns {boolean} true when running inside another document */
function isEmbedded() {
  try {
    return typeof window !== 'undefined' && window.parent !== window;
  } catch {
    // Cross-origin access to window.parent throws; treat as not embedded.
    return false;
  }
}

/**
 * @returns {{
 *   enabled: boolean,
 *   ready: (payload?: object) => void,
 *   exchange: (payload: object) => void,
 *   state: (payload: object) => void,
 *   onCommand: (handler: (type: string, payload: object) => void) => void,
 * }}
 */
export function createTelemetry() {
  if (!isEmbedded()) {
    return {
      enabled: false,
      ready: noop,
      exchange: noop,
      state: noop,
      onCommand: noop,
    };
  }

  const targetOrigin = window.location.origin;

  const post = (type, payload = {}) => {
    try {
      window.parent.postMessage(
        { source: OUTBOUND_SOURCE, type, payload },
        targetOrigin
      );
    } catch (error) {
      // A closed or cross-origin parent must never break the chat.
      console.warn('[customer] telemetry post failed:', error);
    }
  };

  /** Coalesce state spam: one snapshot per frame is plenty for a debug panel. */
  let statePending = null;
  let stateScheduled = false;
  const flushState = () => {
    stateScheduled = false;
    if (statePending) post('state', statePending);
    statePending = null;
  };

  return {
    enabled: true,

    ready(payload) {
      post('ready', payload);
    },

    /**
     * One customer/agent exchange, as observed by this client.
     *
     * @param {{ clientMessageId: string, durationMs: number, status: number }} payload
     */
    exchange(payload) {
      post('exchange', payload);
    },

    state(payload) {
      statePending = payload;
      if (stateScheduled) return;
      stateScheduled = true;
      if (typeof requestAnimationFrame === 'function') {
        requestAnimationFrame(flushState);
      } else {
        setTimeout(flushState, 16);
      }
    },

    /**
     * Subscribe to console commands: `reset` and `inject`.
     *
     * Configuration changes are not delivered here. The console reconfigures the
     * device by reloading the iframe with new query parameters, which rebuilds
     * the transport cleanly instead of mutating a live gateway. See
     * docs/v0.0/frontend/admin-console-ui/design.md § Harness.
     */
    onCommand(handler) {
      window.addEventListener('message', (event) => {
        if (event.origin !== targetOrigin) return;
        const data = event.data;
        if (!data || data.source !== INBOUND_SOURCE) return;
        if (typeof data.type !== 'string') return;
        handler(data.type, data.payload ?? {});
      });
    },
  };
}
