/** Suggested reply chips. Selecting one uses the ordinary send path. */
import { strings } from '../strings.js';

/**
 * @param {object} deps
 * @param {HTMLElement} deps.el
 * @param {(text: string) => void} deps.onSelect
 */
export function createQuickReplies({ el, onSelect }) {
  let lastKey = null;

  el.setAttribute('aria-label', strings.quickReplies.label);

  return {
    render(state) {
      const chips = state.assistant.humanTakeover ? [] : state.quickReplies;
      const key = chips.map((chip) => `${chip.id}:${chip.label}`).join('|');
      if (key === lastKey) return;
      lastKey = key;

      el.replaceChildren(
        ...chips.map((chip) => {
          const button = document.createElement('button');
          button.type = 'button';
          button.className = 'quick-reply';
          button.textContent = chip.label;
          button.addEventListener('click', () => onSelect(chip.label));
          return button;
        })
      );
    },
  };
}
