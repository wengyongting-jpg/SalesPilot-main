/**
 * Minimal browser globals for testing modules that read `window`.
 *
 * Deliberately not a DOM implementation. Bringing in jsdom would add a
 * dependency, which the project forbids, so these stubs cover only what the
 * modules under test actually touch: `window.location`, `window.parent`,
 * `postMessage` and `addEventListener`.
 *
 * Anything that genuinely needs layout — scroll offsets, element geometry — is
 * not tested here. That logic lives in `customer/js/rules.js` as pure functions
 * precisely so it can be tested without a browser.
 */

const DEFAULT_ORIGIN = 'http://127.0.0.1:8123';

/**
 * Install a fake `window`.
 *
 * @param {object} [options]
 * @param {string} [options.search] query string, e.g. '?transport=mock'
 * @param {string} [options.origin]
 * @param {boolean} [options.embedded] when true, `window.parent !== window`
 * @returns {{
 *   posts: Array<{ message: object, targetOrigin: string }>,
 *   listeners: Array<{ type: string, handler: Function }>,
 *   emit: (type: string, event: object) => void,
 *   restore: () => void,
 * }}
 */
export function installWindow({
  search = '',
  origin = DEFAULT_ORIGIN,
  embedded = false,
  // Every test-driven mock load runs with artificial delays disabled: tests
  // assert behaviour, not the setTimeout that exists for a human watching a
  // demo. Callers that specifically want to verify the default timing pass
  // zeroLatency: false and add their own `mockLatency` parameter to `search`.
  zeroLatency = true,
} = {}) {
  if (zeroLatency && !/(^|[?&])mockLatency=/.test(search)) {
    search += (search.includes('?') ? '&' : '?') + 'mockLatency=0';
  }
  const posts = [];
  const listeners = [];
  const previous = globalThis.window;
  const previousRaf = globalThis.requestAnimationFrame;

  const win = {
    location: { origin, search, href: `${origin}/${search}` },
    addEventListener(type, handler) {
      listeners.push({ type, handler });
    },
    removeEventListener(type, handler) {
      const index = listeners.findIndex(
        (entry) => entry.type === type && entry.handler === handler
      );
      if (index >= 0) listeners.splice(index, 1);
    },
  };

  win.parent = embedded
    ? {
        postMessage(message, targetOrigin) {
          posts.push({ message, targetOrigin });
        },
      }
    : win;

  globalThis.window = win;
  // Flush telemetry state coalescing synchronously so tests need no timers.
  globalThis.requestAnimationFrame = (fn) => {
    fn();
    return 0;
  };

  return {
    posts,
    listeners,
    /** Deliver an event to every registered listener of `type`. */
    emit(type, event) {
      for (const entry of listeners) {
        if (entry.type === type) entry.handler(event);
      }
    },
    restore() {
      globalThis.window = previous;
      globalThis.requestAnimationFrame = previousRaf;
    },
  };
}

/**
 * Import a module with a cache-busting query so repeated imports re-evaluate it
 * against freshly installed globals.
 *
 * @param {string} specifier
 * @param {string} tag unique per call site
 */
export function importFresh(specifier, tag) {
  return import(`${specifier}?fresh=${tag}`);
}

/** A message-shaped object for `window.postMessage` listener tests. */
export function messageEvent({ origin = DEFAULT_ORIGIN, data, source } = {}) {
  return { origin, data, source };
}

export { DEFAULT_ORIGIN };
