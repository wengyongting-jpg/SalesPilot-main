/**
 * Navigation: three destinations, active indication, open-case badge, operator.
 */
import { config } from '../config.js';
import { strings } from '../strings.js';
import { el, clear } from '../dom.js';

const ROUTES = ['inbox', 'cases', 'debug', 'harness'];

/**
 * @param {object} deps
 * @param {HTMLElement} deps.el
 * @param {(route: string) => void} deps.onNavigate
 */
export function createNav({ el: root, onNavigate }) {
  const buttons = new Map();

  const brand = el('div', { className: 'nav__brand' }, [
    el('div', { className: 'nav__mark', text: 'SP', attrs: { 'aria-hidden': 'true' } }),
    el('div', {}, [
      el('div', { className: 'nav__title', text: strings.nav.title }),
      el('div', { className: 'nav__subtitle', text: strings.nav.subtitle }),
    ]),
  ]);

  const badge = el('span', {
    className: 'nav__badge',
    attrs: { hidden: true },
  });

  const items = ROUTES.map((route) => {
    const isCases = route === 'cases';
    const button = el(
      'button',
      {
        className: 'nav__item',
        attrs: { type: 'button', 'aria-current': 'false' },
        on: { click: () => onNavigate(route) },
      },
      [el('span', { text: strings.nav[route] }), isCases ? badge : null]
    );
    buttons.set(route, button);
    return button;
  });

  const operator = el('div', { className: 'nav__operator' }, [
    el('div', { text: strings.nav.operatorLabel }),
    el('div', {
      className: 'nav__operator-name',
      text: `${config.operator.name} · ${config.operator.role}`,
    }),
    // Stated plainly rather than disguised with a fake login.
    el('div', { text: strings.nav.noAuthNote }),
  ]);

  clear(root);
  root.append(brand, ...items, operator);

  let lastRoute = null;
  let lastOpenCount = -1;

  return {
    render(state) {
      if (state.route !== lastRoute) {
        lastRoute = state.route;
        for (const [route, button] of buttons) {
          const active = route === state.route;
          button.classList.toggle('is-active', active);
          button.setAttribute('aria-current', active ? 'page' : 'false');
        }
      }

      const open = state.cases.openCount;
      if (open !== lastOpenCount) {
        lastOpenCount = open;
        if (open > 0) {
          badge.textContent = String(open);
          badge.removeAttribute('hidden');
          badge.setAttribute('aria-label', strings.nav.openCases(open));
        } else {
          badge.setAttribute('hidden', '');
        }
      }
    },
  };
}
