/**
 * Chat header.
 *
 * Carries the AI disclosure (requirement 3.6): the status line names the AI
 * assistant whenever the AI is answering, and only a genuine human takeover
 * replaces that label. The customer always knows who they are talking to.
 */
import { config } from '../config.js';
import { strings } from '../strings.js';
import { icons } from '../icons.js';

/**
 * @param {object} deps
 * @param {HTMLElement} deps.el
 * @param {() => void} deps.onReset
 */
export function createHeader({ el, onReset }) {
  const avatar = document.createElement('div');
  avatar.className = 'avatar';
  avatar.setAttribute('aria-hidden', 'true');
  avatar.textContent = config.business.avatarInitials;

  const textWrap = document.createElement('div');
  textWrap.className = 'chat-header__text';

  const name = document.createElement('div');
  name.className = 'chat-header__name';
  name.textContent = config.business.name;

  const status = document.createElement('div');
  status.className = 'chat-header__status';

  textWrap.append(name, status);

  const actions = document.createElement('div');
  actions.className = 'chat-header__actions';

  // Demo reset control (requirement 13.1, 13.3).
  if (config.features.demoMode) {
    const reset = document.createElement('button');
    reset.type = 'button';
    reset.className = 'header-btn';
    reset.innerHTML = icons.refresh; // icon constant, not user input
    reset.setAttribute('aria-label', strings.header.resetLabel);
    reset.title = strings.header.resetLabel;
    reset.addEventListener('click', onReset);
    actions.append(reset);
  }

  el.append(avatar, textWrap, actions);

  let lastStatus = null;

  return {
    render(state) {
      const { typing, humanTakeover, repName } = state.assistant;

      let next;
      if (humanTakeover) {
        next = strings.header.human(repName);
      } else if (typing) {
        next = strings.header.typing;
      } else {
        next = strings.header.aiOnline;
      }

      if (next !== lastStatus) {
        lastStatus = next;
        status.textContent = next;
      }
    },
  };
}
