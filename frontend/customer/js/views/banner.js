/**
 * Banner stack: offline above handoff, both able to show at once (ux-spec §5).
 *
 * The offline banner is driven by `navigator.onLine` in this slice. Health-check
 * polling, which needs a backend, arrives with the SalesPilot adapter in task 5.
 */
import { strings } from '../strings.js';
import { icons } from '../icons.js';

function buildBanner(variant, glyph, text) {
  const el = document.createElement('div');
  el.className = `banner banner--${variant}`;
  el.setAttribute('role', 'status');

  const icon = document.createElement('span');
  icon.className = 'banner__icon';
  icon.setAttribute('aria-hidden', 'true');
  icon.innerHTML = glyph; // icon constant, not user input

  const label = document.createElement('span');
  label.textContent = text;

  el.append(icon, label);
  return el;
}

/**
 * @param {object} deps
 * @param {HTMLElement} deps.el
 */
export function createBanner({ el }) {
  let lastKey = null;

  return {
    render(state) {
      const offline = state.connection === 'offline';
      const handoff = state.assistant.humanTakeover;
      const key = `${offline}:${handoff}`;
      if (key === lastKey) return;
      lastKey = key;

      el.replaceChildren();
      if (offline) {
        el.append(buildBanner('offline', icons.wifiOff, strings.banner.offline));
      }
      if (handoff) {
        el.append(buildBanner('handoff', icons.userCheck, strings.banner.handoff));
      }
    },
  };
}
