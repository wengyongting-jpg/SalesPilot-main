/**
 * Composer: text input plus the mic/send action control.
 *
 * Behaviour:
 *   - empty input shows a disabled mic glyph; typing swaps it to an enabled send
 *     glyph (requirements 2.1, 2.2)
 *   - Enter sends, Shift+Enter inserts a newline (requirements 10.1, 10.2)
 *   - the field auto-grows to five lines, then scrolls internally (10.3)
 *   - recognised emoticons convert to emoji as you type (10.4)
 *   - messages are trimmed, and an empty result is rejected (10.5)
 *
 * The input stays editable while a send is in flight (requirement 2.9): losing
 * typed text would be worse than a failed send.
 *
 * The mic glyph is presentational only — voice notes are out of scope. It is
 * never enabled, so no keyboard user can reach a dead control.
 */
import { strings } from '../strings.js';
import { icons } from '../icons.js';
import { convertTrailingEmoticon } from '../emoji.js';

/**
 * @param {object} deps
 * @param {HTMLFormElement} deps.el
 * @param {(text: string) => void} deps.onSend
 * @param {() => void} deps.onTyping
 */
export function createComposer({ el, onSend, onTyping }) {
  const input = document.createElement('textarea');
  input.className = 'composer__input';
  input.rows = 1;
  input.placeholder = strings.composer.placeholder;
  input.setAttribute('aria-label', strings.composer.inputLabel);
  input.autocomplete = 'off';

  const button = document.createElement('button');
  button.type = 'submit';
  button.className = 'composer__send';

  const glyph = document.createElement('span');
  glyph.className = 'composer__send-glyph';
  glyph.setAttribute('aria-hidden', 'true');

  button.append(glyph);
  el.append(input, button);

  let hasContent = null;

  function autoGrow() {
    input.style.height = 'auto';
    input.style.height = `${input.scrollHeight}px`;
  }

  function refreshControl() {
    const next = input.value.trim().length > 0;
    if (next === hasContent) return;
    hasContent = next;

    glyph.innerHTML = next ? icons.send : icons.mic; // icon constants
    button.disabled = !next;
    button.setAttribute(
      'aria-label',
      next ? strings.composer.sendLabel : strings.composer.micLabel
    );
  }

  function submit() {
    const text = input.value.trim();
    if (!text) return;
    input.value = '';
    autoGrow();
    refreshControl();
    onSend(text);
  }

  input.addEventListener('input', () => {
    // Convert a just-completed emoticon, preserving the caret position.
    const caret = input.selectionStart ?? input.value.length;
    const converted = convertTrailingEmoticon(input.value.slice(0, caret));
    if (converted) {
      const after = input.value.slice(caret);
      input.value = converted.text + after;
      const nextCaret = converted.text.length;
      input.setSelectionRange(nextCaret, nextCaret);
    }

    autoGrow();
    refreshControl();
    onTyping();
  });

  input.addEventListener('keydown', (event) => {
    if (event.key !== 'Enter' || event.shiftKey) return;
    event.preventDefault();
    submit();
  });

  el.addEventListener('submit', (event) => {
    event.preventDefault();
    submit();
  });

  refreshControl();

  return {
    focus() {
      input.focus();
    },
    render() {
      // The composer is deliberately never disabled by state: not while sending
      // (requirement 2.9), not while offline (ux-spec §7), and not during human
      // takeover (requirement 7.6).
    },
  };
}
