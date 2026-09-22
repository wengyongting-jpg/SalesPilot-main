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
   * Defaults to 'salespilot' so the console shows the backend's real queue,
   * transcript and agent telemetry. Select the mock explicitly for fixture-only
   * development.
   *
   * Browser integration used to be blocked by the absence of CORS headers
   * (`docs/backend-contract.md` item 15, formerly numbered 13). That shipped on
   * 2026-09-22: the API now echoes `Access-Control-Allow-Origin` for configured
   * loopback origins, so serving this console from 8123 against the API on 8000
   * works in a browser. The origin must appear in the backend's
   * `SALESPILOT_CORS_ORIGINS`.
   */
  transport: 'salespilot',

  /**
   * Base URL for the backend REST API, used by the 'salespilot' transport.
   *
   * Not empty, because same-origin can never be right here: the backend serves no
   * static files, so the console is always on a different origin than the API.
   */
  apiBase: 'http://127.0.0.1:8000',

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
