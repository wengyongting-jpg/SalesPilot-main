/**
 * Floating jump-to-latest control with an unread badge.
 *
 * Visible only when the customer has scrolled away from the bottom
 * (requirement 4.2). The badge counts incoming messages received since they
 * last reached the bottom (requirement 4.3).
 */
import { strings } from '../strings.js';
import { icons } from '../icons.js';

/**
 * @param {object} deps
 * @param {HTMLElement} deps.el
 * @param {() => void} deps.onJump
 */
export function createJumpToLatest({ el, onJump }) {
  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'jump-btn';
  button.addEventListener('click', onJump);

  const glyph = document.createElement('span');
  glyph.setAttribute('aria-hidden', 'true');
  glyph.innerHTML = icons.chevronDown; // icon constant, not user input

  const badge = document.createElement('span');
  badge.className = 'jump-btn__badge';

  button.append(glyph);

  let visible = false;
  let lastUnread = -1;

  return {
    render(state) {
      const shouldShow = !state.scroll.atBottom;

      if (shouldShow !== visible) {
        visible = shouldShow;
        if (visible) el.append(button);
        else el.replaceChildren();
      }
      if (!visible) {
        lastUnread = -1;
        return;
      }

      const unread = state.scroll.unread;
      if (unread === lastUnread) return;
      lastUnread = unread;

      if (unread > 0) {
        badge.textContent = String(unread);
        if (!badge.isConnected) button.append(badge);
        button.setAttribute(
          'aria-label',
          `${strings.jump.label}. ${strings.jump.unreadLabel(unread)}`
        );
      } else {
        badge.remove();
        button.setAttribute('aria-label', strings.jump.label);
      }
    },
  };
}
