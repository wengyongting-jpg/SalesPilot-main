/**
 * Runtime configuration — customer chat.
 *
 * Everything presentation- or environment-specific lives here so the demo can be
 * re-pointed without editing view code (requirement 11.1).
 *
 * A few values may be overridden by URL query parameters, which is how the admin
 * console's test harness points a device at a given identity and transport. Only
 * the keys listed in URL_OVERRIDES are honoured, so a crafted link cannot reach
 * anything else.
 */

/** Query parameter -> config path. Nothing outside this map is overridable. */
const URL_OVERRIDES = {
  transport: ['transport'],
  customerId: ['customer', 'id'],
  customerName: ['customer', 'name'],
  apiBase: ['apiBase'],
};

const ALLOWED_TRANSPORTS = new Set(['mock', 'salespilot', 'whatsapp']);

function applyUrlOverrides(target) {
  let params;
  try {
    params = new URLSearchParams(window.location.search);
  } catch {
    return target;
  }

  for (const [param, path] of Object.entries(URL_OVERRIDES)) {
    const raw = params.get(param);
    if (raw === null || raw === '') continue;
    if (param === 'transport' && !ALLOWED_TRANSPORTS.has(raw)) continue;

    let node = target;
    for (const key of path.slice(0, -1)) node = node[key];
    node[path[path.length - 1]] = raw;
  }
  return target;
}

export const config = applyUrlOverrides({
  business: {
    name: 'CareSure',
    avatarInitials: 'CS',
  },

  assistant: {
    /** Shown in the header. The assistant must always be identifiable as AI. */
    label: 'AI Assistant',
    aiDisclosure: true,
  },

  /** Demo identity. There is no authentication anywhere in this project. */
  customer: {
    id: 'C-2001',
    name: 'Sam',
  },

  /**
   * Transport adapter: 'mock' | 'salespilot' | 'whatsapp'.
   *
   * Defaults to 'mock' so the app runs with no Python server, which is what the
   * frontend-only slices are built and demonstrated against.
   */
  transport: 'mock',

  /** Empty string means same-origin, used when FastAPI serves these files. */
  apiBase: '',

  /** Polling is used ONLY while human takeover is active (requirement 8.7). */
  pollIntervalMs: 2000,
  healthIntervalMs: 15000,

  /** Abort budget for a send. Generous: an LLM-backed reply is legitimately slow. */
  sendTimeoutMs: 30000,

  /** Scroll distance from the bottom within which new messages auto-scroll. */
  scrollBottomThresholdPx: 80,

  /** Messages from the same author within this window are grouped. */
  groupWindowMs: 60000,

  features: {
    demoMode: true,
    sounds: false,
    notifications: false,
    darkMode: false,
  },
});
