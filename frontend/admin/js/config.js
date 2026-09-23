/**
 * Runtime configuration — admin console.
 *
 * One module so the console can be re-pointed without editing view code
 * (requirement 9.1).
 */
export const config = {
  business: {
    name: 'CareSure',
  },

  /**
   * The signed-in operator. There is no authentication anywhere in this project,
   * so this is simply who the console claims to be when sending a human reply.
   */
  operator: {
    name: 'Alex',
    role: 'Sales Representative',
  },

  /**
   * Transport adapter: 'mock' | 'salespilot'.
   *
   * Defaults to 'mock'. The backend is mid-refactor and the visibility-tier split
   * in docs/api/interface-v1.md §5.1 will move admin reads to /api/admin/*, so
   * binding to today's paths would be rework. See design.md § Transport.
   */
  transport: 'salespilot',

  /** Empty string means same-origin. */
  apiBase: 'http://127.0.0.1:8010',

  /** Relative path to the customer app, embedded by the harness route. */
  customerAppPath: '../customer/index.html',

  /** Device frame size for the harness. Below the customer app's 600px
   *  breakpoint, so it renders its full-viewport mobile layout. */
  device: { width: 400, height: 844 },

  refreshIntervalMs: 15000,

  /**
   * Multiplies every artificial delay in the mock gateway. `1` preserves the
   * demo feel; the test suite overrides this to `0` when constructing the mock
   * directly, so it never touches this file. Exposed here too so the running
   * console could be sped up the same way if ever needed.
   */
  mockLatencyScale: 1,

  /** How long to wait for the embedded device's `ready` handshake. */
  deviceReadyTimeoutMs: 8000,

  features: {
    demoMode: true,
    analytics: false,
    autoRefresh: false,
    darkMode: false,
  },
};
